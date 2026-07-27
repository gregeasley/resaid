"""
Decline curve analysis implementation (`decline_curve`).

This module is part of the ``resaid.dca`` package; import from ``resaid.dca`` or ``resaid``.
"""

import logging
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm
from dateutil.relativedelta import relativedelta
from scipy.optimize import curve_fit
from scipy.signal import argrelextrema
from tqdm import tqdm

from ..dca_constants import DEFAULT_FORECAST_HORIZON_MONTHS, DEFAULT_SOLVER_T_MAX_MONTHS

logger = logging.getLogger(__name__)

# ``decline_curve.fit_method`` / ``dca_params(..., fit_method=...)`` — how each row is fit for qi, di, b, t0.
DCA_FIT_METHOD_DEFAULT = "default"
# Backward-compatible alias.
DCA_FIT_METHOD_LEGACY = DCA_FIT_METHOD_DEFAULT
DCA_FIT_METHOD_MONOTONE_TWO_STEP = "monotone_two_step"

# Keys for ``decline_curve._dca_path_counts`` (per-run summary, reset in vectorized / three-phase).
DCA_PATH_MONOTONE_PRIMARY = "monotone_primary"
DCA_PATH_MONOTONE_TAIL = "monotone_fallback_legacy_tail"
DCA_PATH_MONOTONE_TAIL_OL = "monotone_fallback_tail_outliers"
DCA_PATH_MONOTONE_FIRST_POS = "monotone_fallback_first_positive"
DCA_PATH_MONOTONE_BACKUP_PRE = "monotone_backup_insufficient_initial_history"
DCA_PATH_MONOTONE_BACKUP_EXHAUSTED = "monotone_backup_all_segments_failed"

DCA_PATH_LEGACY_PRIMARY = "legacy_primary_filtered"
DCA_PATH_LEGACY_FORCE_T0 = "legacy_primary_forced_t0_full_series"
DCA_PATH_LEGACY_BACKUP_PRE = "legacy_backup_insufficient_initial_history"
DCA_PATH_LEGACY_BACKUP_POST = "legacy_backup_insufficient_after_filters"
DCA_PATH_LEGACY_BACKUP_FIT = "legacy_backup_curve_fit_failed"

DCA_LEGACY_ADJ_BULK_DOWNSIDE = "legacy_adj_bulk_downside_or_equal"
DCA_LEGACY_ADJ_BULK_LOW_B = "legacy_adj_bulk_low_b_upside"
DCA_LEGACY_ADJ_SOLVED_UPSIDE = "legacy_adj_solved_upside"
DCA_LEGACY_ADJ_BULK_FALLBACK = "legacy_adj_bulk_upside_solver_fallback"

# Printed path breakdown is chosen from ``fit_method`` (monotone vs default/legacy alias).
_DCA_PATH_REPORT_MONOTONE = (
    (DCA_PATH_MONOTONE_PRIMARY, "Primary (longest monotone decline segment)"),
    (DCA_PATH_MONOTONE_TAIL, "Fallback (post-trough positive tail, no outlier screen)"),
    (DCA_PATH_MONOTONE_TAIL_OL, "Fallback (post-trough tail after outlier screen)"),
    (DCA_PATH_MONOTONE_FIRST_POS, "Fallback (first positive month through last month)"),
    (
        DCA_PATH_MONOTONE_BACKUP_PRE,
        "Backup (insufficient initial history, ≤3 months before any segment)",
    ),
    (
        DCA_PATH_MONOTONE_BACKUP_EXHAUSTED,
        "Backup (all monotone / fallback segments failed curve_fit or two-step)",
    ),
)

_DCA_PATH_REPORT_LEGACY = (
    (
        DCA_PATH_LEGACY_PRIMARY,
        "Primary (trough / zero filter / outlier screen / curve_fit on filtered series)",
    ),
    (
        DCA_PATH_LEGACY_FORCE_T0,
        "Primary (forced t0 mode — curve_fit on full series, outlier step bypassed for fit)",
    ),
    (
        DCA_PATH_LEGACY_BACKUP_PRE,
        "Backup (insufficient initial history, ≤3 months before peak pipeline)",
    ),
    (
        DCA_PATH_LEGACY_BACKUP_POST,
        "Backup (≤3 points after peak, zero, and outlier filtering)",
    ),
    (
        DCA_PATH_LEGACY_BACKUP_FIT,
        "Backup (curve_fit error, non-finite qi, or infinite popt[0])",
    ),
)

_ALL_DCA_PATH_COUNT_KEYS = frozenset(
    key for table in (_DCA_PATH_REPORT_MONOTONE, _DCA_PATH_REPORT_LEGACY) for key, _ in table
)
_LEGACY_ADJUSTMENT_REPORT = (
    (
        DCA_LEGACY_ADJ_BULK_DOWNSIDE,
        "Bulk shift (L3M actual <= fitted q at latest month)",
    ),
    (
        DCA_LEGACY_ADJ_BULK_LOW_B,
        "Bulk shift (L3M actual > fitted q, but b < 0.1)",
    ),
    (
        DCA_LEGACY_ADJ_SOLVED_UPSIDE,
        "Solved qi/di (L3M up case, b >= 0.1, q-match at latest and convergence month)",
    ),
    (
        DCA_LEGACY_ADJ_BULK_FALLBACK,
        "Bulk shift fallback (up case solver unavailable/non-physical)",
    ),
)
_ALL_LEGACY_ADJUSTMENT_KEYS = frozenset(key for key, _ in _LEGACY_ADJUSTMENT_REPORT)

_decline_solver_type = None


def _decline_solver_cls():
    """Lazy import (avoids cycles) and cache ``decline_solver`` for hot paths."""
    global _decline_solver_type
    if _decline_solver_type is None:
        from .solver import decline_solver as _ds

        _decline_solver_type = _ds
    return _decline_solver_type


class decline_curve:
    """
    Main decline curve analysis class for production forecasting.
    
    This class provides comprehensive decline curve analysis capabilities including:
    - Production data preprocessing and normalization
    - Arps decline curve parameter fitting
    - Single-phase and three-phase forecasting modes
    - Flowstream, oneline, and typecurve generation
    
    Attributes:
        DAYS_PER_MONTH: Days per month normalization factor
        GAS_CUTOFF: Gas-oil ratio cutoff for phase classification (MSCF/STB)
        STANDARD_LENGTH: Standard lateral length for normalization (ft)
        MIN_DECLINE_RATE: Minimum monthly decline rate
        default_initial_decline: Default initial decline rate
        default_b_factor: Default Arps b-factor
        three_phase_mode: Enable three-phase forecasting mode
        fit_method: How ``dca_params`` estimates parameters per row (default
            ``DCA_FIT_METHOD_DEFAULT``; optional ``DCA_FIT_METHOD_MONOTONE_TWO_STEP``).
    """

    def __init__(self, fit_method=DCA_FIT_METHOD_DEFAULT):
        # Constants
        self.DAYS_PER_MONTH = 365/12
        self.GAS_CUTOFF = 3.2  # GOR for classifying well as gas or oil, MSCF/STB
        self.MINOR_TAIL_MONTHS = 6  # Number of months from tail to use for minor phase ratios
        self.STANDARD_LENGTH = 5280  # Length to normalize horizontals to
        self.MIN_DECLINE_RATE = .08/12  # Minimum monthly decline rate
        
        # User-configurable parameters
        self.verbose = False
        self.debug_on = False
        self.stat_file_path = Path.cwd() / "DCA_LOG.txt"
        try:
            # Default run log in the current working directory.
            self.STAT_FILE = open(self.stat_file_path, "a", encoding="utf-8", buffering=1)
        except OSError:
            # Fallback keeps prior behavior if the cwd is not writable.
            self.STAT_FILE = None
        self.filter_bonfp = .5  # Bonferroni correction threshold
        self.default_initial_decline = .8/12
        self.default_b_factor = .5
        self.outlier_correction = True
        self.iqr_limit = 1.5
        self.min_h_b = .99
        self.max_h_b = 2
        
        self.backup_decline = False
        self.qi_tail_points = 3
        self._dataframe = None
        self._date_col = None
        self._phase_col = None
        self._length_col = None
        self._uid_col = None
        self._dayson_col = None
        self._oil_col = None
        self._gas_col = None
        self._water_col = None
        self._input_monthly = True

        self._force_t0 = False

        # Three-phase forecasting mode
        self.three_phase_mode = False

        if fit_method == "legacy":
            fit_method = DCA_FIT_METHOD_DEFAULT
        allowed = (DCA_FIT_METHOD_DEFAULT, DCA_FIT_METHOD_MONOTONE_TWO_STEP)
        if fit_method not in allowed:
            raise ValueError(f"fit_method must be one of {allowed!r}, got {fit_method!r}")
        self.fit_method = fit_method

        # Data storage
        self._normalized_dataframe = pd.DataFrame()
        self._params_dataframe = pd.DataFrame([])
        self._flowstream_dataframe = None
        self._typecurve = None
        self._oneline = pd.DataFrame()

        self.tc_params = pd.DataFrame()
        self.dca_param_df = []
        

    @property
    def dataframe(self):
        return self._dataframe


    @dataframe.setter
    def dataframe(self,value):
        self._dataframe = value

    @property
    def input_monthly(self):
        return self._input_monthly


    @input_monthly.setter
    def input_monthly(self,value):
        self._input_monthly = value

    @property
    def date_col(self):
        return self._date_col


    @date_col.setter
    def date_col(self,value):
        self._date_col = value

    @property
    def phase_col(self):
        return self._phase_col


    @phase_col.setter
    def phase_col(self,value):
        self._phase_col = value

    @property
    def length_col(self):
        return self._length_col


    @length_col.setter
    def length_col(self,value):
        self._length_col = value

    @property
    def uid_col(self):
        return self._uid_col


    @uid_col.setter
    def uid_col(self,value):
        self._uid_col = value

    @property
    def dayson_col(self):
        return self._dayson_col


    @dayson_col.setter
    def dayson_col(self,value):
        self._dayson_col = value

    @property
    def oil_col(self):
        return self._oil_col


    @oil_col.setter
    def oil_col(self,value):
        self._oil_col = value

    @property
    def gas_col(self):
        return self._gas_col


    @gas_col.setter
    def gas_col(self,value):
        self._gas_col = value

    @property
    def water_col(self):
        return self._water_col


    @water_col.setter
    def water_col(self,value):
        self._water_col = value








    @property
    def params_dataframe(self):
        return self._params_dataframe

    @property
    def flowstream_dataframe(self):
        return self._flowstream_dataframe

    @property
    def oneline_dataframe(self):
        return self._oneline

    @property
    def typecurve(self):
        return self._typecurve

    def month_diff(self, a, b):
        return 12 * (a.dt.year - b.dt.year) + (a.dt.month - b.dt.month)

    def day_diff(self,a,b):
        return (a - b) / np.timedelta64(1, 'D')

    def infill_production(self):
        """
        An error was found where gaps in the historical production would be infilled
        with the wrong P_DATE
        """

    def generate_t_index(self):
        """Generate time index for production data."""
        self._dataframe[self._date_col] = pd.to_datetime(self._dataframe[self._date_col])
        self._dataframe = self._dataframe.sort_values(
            [self._uid_col, self._date_col]
        ).reset_index(drop=True)
        min_by_well = self._dataframe[[self._uid_col,self._date_col]].groupby(by=[self._uid_col]).min().reset_index()
        min_by_well = min_by_well.rename(columns={self._date_col:'MIN_DATE'})
        
        self._dataframe = self._dataframe.merge(
            min_by_well, 
            left_on = self._uid_col,
            right_on = self._uid_col,
            suffixes=(None,'_MIN')
        )

        if self._input_monthly:
            self._dataframe['T_INDEX'] = self.month_diff(
                self._dataframe[self._date_col],
                self._dataframe['MIN_DATE']
            )
        else:
            self._dataframe['T_INDEX'] = self.day_diff(
                self._dataframe[self._date_col],
                self._dataframe['MIN_DATE']
            )

        #return 0

    def assign_major(self):
        """Assign major phase (OIL or GAS) based on gas-oil ratio."""
        l_cum = self._normalized_dataframe[['UID','NORMALIZED_OIL','NORMALIZED_GAS']].groupby(by=['UID']).sum().reset_index()
        l_cum['MAJOR'] = np.where(
            l_cum["NORMALIZED_OIL"] > 0,
            np.where(
                l_cum["NORMALIZED_GAS"]/l_cum['NORMALIZED_OIL'] > self.GAS_CUTOFF,
                'GAS',
                'OIL'
            ),
            "GAS"
        )

        self._normalized_dataframe = self._normalized_dataframe.merge(
            l_cum,
            left_on = "UID",
            right_on = "UID",
            suffixes=(None,'_right')
        )

    def normalize_production(self):

        self._normalized_dataframe['UID'] = self._dataframe[self._uid_col]
        self._normalized_dataframe['T_INDEX'] = self._dataframe['T_INDEX']

        if self._length_col == None:
            self._normalized_dataframe['LENGTH_NORM'] = 1.0
        else:
            self._dataframe[self._length_col] = self._dataframe[self._length_col].fillna(0)

            self._normalized_dataframe['LENGTH_NORM'] = np.where(
                self._dataframe[self._length_col] > 1,
                self._dataframe[self._length_col],
                1
            )

        self._normalized_dataframe['HOLE_DIRECTION'] = np.where(
            self._normalized_dataframe['LENGTH_NORM']> 1,
            "H",
            "V"
        )

        if self._length_col == None:
            self._normalized_dataframe['LENGTH_SET'] = 1.0
        else:
            self._normalized_dataframe['LENGTH_SET'] = np.where(
                self._dataframe[self._length_col] > 1,
                self.STANDARD_LENGTH,
                1.0
            )

        

        if self._dayson_col == None:
            self._normalized_dataframe['DAYSON'] = 30.4
        else:
            self._dataframe[self._dayson_col] = self._dataframe[self._dayson_col].fillna(30.4)

            self._normalized_dataframe['DAYSON'] = np.where(
                self._dataframe[self._dayson_col] > 0,
                self._dataframe[self._dayson_col],
                0
            )

        self._dataframe[self._oil_col] = pd.to_numeric(self._dataframe[self._oil_col], errors='coerce')
        self._dataframe[self._oil_col] = self._dataframe[self._oil_col].fillna(0)

        self._dataframe[self._gas_col] = pd.to_numeric(self._dataframe[self._gas_col], errors='coerce')
        self._dataframe[self._gas_col] = self._dataframe[self._gas_col].fillna(0)

        self._dataframe[self._water_col] = pd.to_numeric(self._dataframe[self._water_col], errors='coerce')
        self._dataframe[self._water_col] = self._dataframe[self._water_col].fillna(0)

        #self._normalized_dataframe.to_csv('outputs/test.csv')

        self._normalized_dataframe['NORMALIZED_OIL'] = (
            self._dataframe[self._oil_col]*
            self.DAYS_PER_MONTH*
            self._normalized_dataframe['LENGTH_SET'] /
            (self._normalized_dataframe['LENGTH_NORM'] * self._normalized_dataframe['DAYSON'])
        )

        self._normalized_dataframe['NORMALIZED_GAS'] = (
            self._dataframe[self._gas_col]*
            self.DAYS_PER_MONTH*
            self._normalized_dataframe['LENGTH_SET'] /
            (self._normalized_dataframe['LENGTH_NORM'] * self._normalized_dataframe['DAYSON'])
        )

        self._normalized_dataframe['NORMALIZED_WATER'] = (
            self._dataframe[self._water_col]*
            self.DAYS_PER_MONTH*
            self._normalized_dataframe['LENGTH_SET'] /
            (self._normalized_dataframe['LENGTH_NORM'] * self._normalized_dataframe['DAYSON'])
        )

        
        if self._phase_col == None:
            self.assign_major()
        else:
            self._normalized_dataframe['MAJOR'] = self._dataframe[self._phase_col]
        

        self._normalized_dataframe = self._normalized_dataframe[[
            'UID',
            'LENGTH_NORM',
            "HOLE_DIRECTION",
            'MAJOR',
            'T_INDEX',
            'NORMALIZED_OIL',
            'NORMALIZED_GAS',
            'NORMALIZED_WATER'
        ]]

        self._normalized_dataframe['NORMALIZED_OIL'] = self._normalized_dataframe['NORMALIZED_OIL'].fillna(0) 
        self._normalized_dataframe['NORMALIZED_GAS'] = self._normalized_dataframe['NORMALIZED_GAS'].fillna(0) 
        self._normalized_dataframe['NORMALIZED_WATER'] = self._normalized_dataframe['NORMALIZED_WATER'].fillna(0) 
    
        if self.debug_on:
            self._normalized_dataframe.to_csv('outputs/norm_test.csv')
    
    def outlier_detection(self, input_x, input_y):
        """
        Detect and filter outliers using Bonferroni correction.
        
        Runs a log-rate vs time OLS on points with strictly positive rates, then
        ``outlier_test``. Skips when the design is too small, singular, or would
        leave ``df_resid == 0`` (which otherwise triggers divide-by-zero inside
        statsmodels).
        
        Args:
            input_x: Time values
            input_y: Production values
            
        Returns:
            tuple: (filtered_x, filtered_y) - filtered data without outliers
        """
        as_x = np.asarray(input_x, dtype=float)
        as_y = np.asarray(input_y, dtype=float)

        if as_x.shape != as_y.shape:
            if self.verbose:
                logger.warning("outlier_detection: x and y length mismatch; skipping")
            return input_x, input_y

        valid = (as_y > 0) & np.isfinite(as_y) & np.isfinite(as_x)
        n_valid = int(np.count_nonzero(valid))
        # Need enough observations for intercept + slope and positive df_resid for
        # ``outlier_test`` (studentized residuals, etc.).
        if n_valid < 6:
            return input_x, input_y

        vx = as_x[valid]
        vy = as_y[valid]
        ln_y = np.log(vy)
        orig_idx = np.flatnonzero(valid)

        span_x = float(np.max(vx) - np.min(vx))
        span_ln = float(np.max(ln_y) - np.min(ln_y))
        if span_x < 1e-15 or span_ln < 1e-15:
            return input_x, input_y

        try:
            regression = sm.formula.ols(
                "data ~ x", data=dict(data=ln_y, x=vx)
            ).fit()
        except Exception:
            if self.verbose:
                logger.warning("OLS fit failed in outlier detection.", exc_info=True)
            return input_x, input_y

        exog = np.asarray(regression.model.exog, dtype=float)
        if exog.size == 0 or np.linalg.matrix_rank(exog) < exog.shape[1]:
            return input_x, input_y

        if regression.df_resid <= 0:
            return input_x, input_y
        if not np.all(np.isfinite(regression.params)):
            return input_x, input_y
        resid = np.asarray(regression.resid, dtype=float)
        if resid.size == 0 or not np.all(np.isfinite(resid)):
            return input_x, input_y

        try:
            test = regression.outlier_test()
        except Exception:
            if self.verbose:
                logger.warning("Error in outlier detection outlier_test.", exc_info=True)
            return input_x, input_y

        if len(test) != len(orig_idx):
            if self.verbose:
                logger.warning(
                    "outlier_detection: outlier_test length %s != sample %s; skipping",
                    len(test),
                    len(orig_idx),
                )
            return input_x, input_y

        kept_x = []
        kept_y = []
        outliers_removed = 0
        for j, (_, row) in enumerate(test.iterrows()):
            if row["bonf(p)"] > self.filter_bonfp:
                i = int(orig_idx[j])
                kept_x.append(float(as_x[i]))
                kept_y.append(float(as_y[i]))
            else:
                outliers_removed += 1

        if self.verbose and outliers_removed > 0:
            logger.info(
                "Outlier detection: removed %s points with bonf(p) <= %s",
                outliers_removed,
                self.filter_bonfp,
            )

        return np.asarray(kept_x, dtype=float), np.asarray(kept_y, dtype=float)

    def arps_decline(self, x, qi, di, b, t0):
        """
        Calculate Arps decline curve production rates.
        
        Args:
            x: Time array
            qi: Initial production rate
            di: Initial decline rate
            b: Arps b-factor
            t0: Time offset
            
        Returns:
            numpy array: Production rates over time
        """
        x_arr = np.asarray(x, dtype=float)
        squeeze_back = x_arr.ndim == 0
        x_arr = np.atleast_1d(x_arr)

        if qi <= 0 or not np.isfinite(qi) or np.isinf(qi):
            out = np.zeros_like(x_arr, dtype=float)
            return float(out[0]) if squeeze_back else out

        qi = float(qi)
        di = float(di)
        b = float(b)
        t0 = float(t0)

        bd = b * di
        if not np.isfinite(bd) or abs(bd) < 1e-30:
            problemX = -np.inf
        else:
            problemX = t0 - 1.0 / bd

        if di < self.MIN_DECLINE_RATE:
            qlim = qi
            di = float(self.MIN_DECLINE_RATE)
            tlim = -1
        else:
            ratio = self.MIN_DECLINE_RATE / di
            if ratio <= 0 or not np.isfinite(ratio) or abs(b) < 1e-14:
                qlim = qi
            else:
                qlim = qi * float(np.exp((1.0 / b) * np.log(ratio)))
            if not np.isfinite(qlim) or qlim <= 0:
                qlim = qi
            try:
                inner = (qi / qlim) ** (b) - 1.0
                den_tl = b * di
                if abs(den_tl) < 1e-30 or not np.isfinite(inner):
                    tlim = -1
                else:
                    tlim = int(inner / den_tl + t0)
                    if not np.isfinite(tlim):
                        tlim = -1
            except Exception:
                if self.verbose:
                    logger.warning(
                        "DCA tlim calculation error: qi=%s, qlim=%s, di=%s, b=%s",
                        qi,
                        qlim,
                        di,
                        b,
                    )
                tlim = -1

        mask_outer = (x_arr > problemX) & np.isfinite(x_arr)
        q_x = np.zeros_like(x_arr, dtype=float)

        if tlim < 0 or not np.isfinite(tlim):
            mask_hyp = np.zeros_like(x_arr, dtype=bool)
        else:
            mask_hyp = mask_outer & (x_arr < float(tlim))

        mask_exp = mask_outer & (~mask_hyp)

        if np.any(mask_hyp):
            idx = np.flatnonzero(mask_hyp)
            xm = x_arr[idx] - t0
            den = 1.0 + b * di * xm
            qh = np.zeros(len(idx), dtype=float)
            positive = den > 0
            if np.any(positive):
                expo = np.clip(-(1.0 / b) * np.log(den[positive]), -700.0, 700.0)
                qh[positive] = qi * np.exp(expo)
            q_x[idx] = qh

        if np.any(mask_exp):
            q_x[mask_exp] = qlim * np.exp(
                -self.MIN_DECLINE_RATE * (x_arr[mask_exp] - float(tlim))
            )

        return float(q_x[0]) if squeeze_back else q_x

    def _tail_phase_ratio(self, numerator_tail, denominator_tail):
        num = float(np.sum(numerator_tail))
        den = float(np.sum(denominator_tail))
        if den <= 0.0 or not np.isfinite(den) or not np.isfinite(num):
            return np.nan
        return num / den

    def _di_int_from_endpoints(self, y_head, y_tail, x_head, x_tail, require_positive=False):
        dx = float(x_tail) - float(x_head)
        if dx <= 0.0 or not np.isfinite(dx):
            return 0.1
        y0 = float(y_head)
        y1 = float(y_tail)
        if y0 <= 0.0 or y1 <= 0.0 or not (np.isfinite(y0) and np.isfinite(y1)):
            return 0.1
        v = np.log(y0 / y1) / dx
        if not np.isfinite(v):
            return 0.1
        if require_positive and v <= 0.0:
            return 0.1
        return float(v)

    def handle_dca_error(self,s,x_vals,y_vals):
        if s["MAJOR"] == 'OIL':
            minor_ratio = self._tail_phase_ratio(
                s["NORMALIZED_GAS"][-self.MINOR_TAIL_MONTHS :],
                s["NORMALIZED_OIL"][-self.MINOR_TAIL_MONTHS :],
            )
            water_ratio = self._tail_phase_ratio(
                s["NORMALIZED_WATER"][-self.MINOR_TAIL_MONTHS :],
                s["NORMALIZED_OIL"][-self.MINOR_TAIL_MONTHS :],
            )
        else:
            minor_ratio = self._tail_phase_ratio(
                s["NORMALIZED_OIL"][-self.MINOR_TAIL_MONTHS :],
                s["NORMALIZED_GAS"][-self.MINOR_TAIL_MONTHS :],
            )
            water_ratio = self._tail_phase_ratio(
                s["NORMALIZED_WATER"][-self.MINOR_TAIL_MONTHS :],
                s["NORMALIZED_GAS"][-self.MINOR_TAIL_MONTHS :],
            )
        i = -1
        while i > -len(x_vals):
            if y_vals[i]>0:
                break
            else:
                i -= 1
        s['qi']=y_vals[i]
        s['di']=self.default_initial_decline
        s['b']=self.default_b_factor
        s['t0']=x_vals[i]
        s['q0']=y_vals[0] #Probably will need revision, high chance first value is zero
        s['minor_ratio']=minor_ratio
        s['water_ratio']=water_ratio

        return s

    def _dca_apply_nan_params(self, s):
        """Set decline parameters on ``s`` to NaN (failed fit, no backup)."""
        s["qi"] = np.nan
        s["di"] = np.nan
        s["b"] = np.nan
        s["t0"] = np.nan
        s["q0"] = np.nan
        s["minor_ratio"] = np.nan
        s["water_ratio"] = np.nan
        return s

    def _dca_failure_finish(
        self,
        s,
        x_vals,
        y_vals,
        *,
        note_print=None,
        note_log_warning=None,
        backup_path_key=None,
    ):
        """
        Shared default-fit semantics on irrecoverable fit: bump failure count, log if verbose,
        then either ``handle_dca_error`` or NaN parameters.

        When ``backup_decline`` is True, ``backup_path_key`` selects which resolution path
        counter to increment (default/legacy alias vs monotone backup reasons).
        """
        self.V_DCA_FAILURES += 1
        if self.verbose:
            if note_log_warning is not None:
                logger.warning(note_log_warning)
            if note_print is not None:
                print(note_print, file=self.STAT_FILE, flush=True)
        if self.backup_decline:
            if backup_path_key is not None:
                self._incr_dca_path(backup_path_key)
            return self.handle_dca_error(s, x_vals, y_vals)
        return self._dca_apply_nan_params(s)

    def _reset_dca_run_path_counts(self):
        self._dca_path_counts = {key: 0 for key in _ALL_DCA_PATH_COUNT_KEYS}
        self._legacy_adjust_counts = {key: 0 for key in _ALL_LEGACY_ADJUSTMENT_KEYS}

    def _incr_dca_path(self, path_key):
        d = getattr(self, "_dca_path_counts", None)
        if d is not None and path_key in d:
            d[path_key] += 1

    def _incr_legacy_adjustment(self, adjust_key):
        d = getattr(self, "_legacy_adjust_counts", None)
        if d is not None and adjust_key in d:
            d[adjust_key] += 1

    def _sort_well_series_by_t_index(self, s):
        """Ensure per-well list columns are ordered by T_INDEX (chronological)."""
        x_vals = s["T_INDEX"]
        if len(x_vals) <= 1 or np.all(np.diff(x_vals) >= 0):
            return s

        logger.warning(
            "Well %s: T_INDEX not monotonic — sorting by T_INDEX",
            s["UID"],
        )
        order = np.argsort(x_vals)
        s = s.copy()
        for col in ("T_INDEX", "NORMALIZED_OIL", "NORMALIZED_GAS", "NORMALIZED_WATER"):
            if col in s.index:
                vals = s[col]
                if isinstance(vals, list):
                    s[col] = [vals[i] for i in order]
        return s

    def _raise_if_all_dca_failed(self, attempted, successful):
        if attempted > 0 and successful == 0:
            failures = getattr(self, "V_DCA_FAILURES", attempted)
            raise ValueError(
                f"DCA produced no valid parameters for any of {attempted} well(s) "
                f"({failures} failures). A common cause is unsorted production dates "
                f"per well — sort input by [{self._uid_col}, {self._date_col}] "
                f"before calling resaid, or rely on generate_t_index() sorting."
            )

    def _require_valid_t0_params(self, df):
        if df.empty:
            failures = getattr(self, "V_DCA_FAILURES", "unknown")
            raise ValueError(
                f"DCA produced no valid t0 values for any well ({failures} failures). "
                f"Check that production dates are sorted by [{self._uid_col}, "
                f"{self._date_col}] per well and review data quality."
            )

    def _compute_t0_date_column(self, df):
        return pd.Series(
            [
                self.add_months(min_date, round(t0, 0))
                for min_date, t0 in zip(df["MIN_DATE"], df["t0"])
            ],
            index=df.index,
        )

    def _print_dca_run_summary(self, heading, attempted, successful, elapsed_sec):
        """Uniform footer for vectorized and three-phase DCA generation."""
        sf = self.STAT_FILE
        if sf is None:
            return
        print("", file=sf)
        print(heading, file=sf, flush=True)
        print(f"  Total fits attempted: {attempted}", file=sf, flush=True)
        print(f"  Successful fits: {successful}", file=sf, flush=True)
        print(
            f"  Total DCA failures (no numeric parameters): {self.V_DCA_FAILURES}",
            file=sf,
            flush=True,
        )
        if attempted > 0:
            print(
                f"  Failure fraction: {self.V_DCA_FAILURES}/{attempted} "
                f"({100.0 * self.V_DCA_FAILURES / attempted:.2f}%)",
                file=sf,
                flush=True,
            )
        counts = getattr(self, "_dca_path_counts", None) or {}
        path_rows = (
            _DCA_PATH_REPORT_LEGACY
            if self.fit_method == DCA_FIT_METHOD_DEFAULT
            else _DCA_PATH_REPORT_MONOTONE
        )
        print(
            f"  Fits resolved by path ({self.fit_method}):",
            file=sf,
            flush=True,
        )
        for key, label in path_rows:
            print(f"    - {label}: {counts.get(key, 0)}", file=sf, flush=True)
        if self.fit_method == DCA_FIT_METHOD_DEFAULT:
            ac = getattr(self, "_legacy_adjust_counts", None) or {}
            print("  Legacy post-fit L3M adjustment usage:", file=sf, flush=True)
            for key, label in _LEGACY_ADJUSTMENT_REPORT:
                print(f"    - {label}: {ac.get(key, 0)}", file=sf, flush=True)
        print(f"  Wall time: {elapsed_sec:.2f} seconds", file=sf, flush=True)

    def _longest_mono_decreasing_span(self, y_vals):
        """Inclusive (start, end) indices of the longest positive, non-increasing run."""
        y_vals = np.asarray(y_vals, dtype=float)
        best_start, best_end = -1, -1
        start = None
        prev_y = None
        for i, y in enumerate(y_vals):
            if not np.isfinite(y) or y <= 0:
                if start is not None and (i - start) > (best_end - best_start + 1):
                    best_start, best_end = start, i - 1
                start = None
                prev_y = None
                continue
            if start is None:
                start = i
                prev_y = y
                continue
            if y <= prev_y:
                prev_y = y
            else:
                if (i - start) > (best_end - best_start + 1):
                    best_start, best_end = start, i - 1
                start = i
                prev_y = y
        if start is not None and (len(y_vals) - start) > (best_end - best_start + 1):
            best_start, best_end = start, len(y_vals) - 1
        if best_start < 0:
            best_start, best_end = 0, len(y_vals) - 1
        return int(best_start), int(best_end)

    def _legacy_style_positive_tail_xy(self, x_vals, y_vals):
        """Post-trough slice + positive filter (same geometry as legacy pre-outlier path)."""
        x_vals = np.asarray(x_vals, dtype=float)
        z = np.asarray(y_vals, dtype=float)
        a = argrelextrema(z, np.greater)
        if len(a[0]) > 0:
            index_min = int(a[-1][0])
        else:
            index_min = 0
        filtered_x = x_vals[index_min:]
        filtered_y = z[index_min:]
        m = (filtered_y > 0) & np.isfinite(filtered_y) & np.isfinite(filtered_x)
        return filtered_x[m], filtered_y[m]

    def _first_positive_span_xy(self, x_vals, y_vals):
        """From first positive rate through last index (inclusive)."""
        x_vals = np.asarray(x_vals, dtype=float)
        y_vals = np.asarray(y_vals, dtype=float)
        pos = np.where(np.isfinite(y_vals) & (y_vals > 0))[0]
        if len(pos) == 0:
            return None, None
        i0, i1 = int(pos[0]), int(pos[-1])
        return x_vals[i0 : i1 + 1], y_vals[i0 : i1 + 1]

    def _monotone_fit_xy_candidates(self, x_vals, y_vals):
        """
        Ordered fit windows for monotone two-step (strict → looser), mirroring legacy
        fallbacks without running the full legacy routine.
        """
        x_vals = np.asarray(x_vals, dtype=float)
        y_vals = np.asarray(y_vals, dtype=float)
        raw = []

        ms, me = self._longest_mono_decreasing_span(y_vals)
        raw.append(
            (
                DCA_PATH_MONOTONE_PRIMARY,
                x_vals[ms : me + 1].copy(),
                y_vals[ms : me + 1].copy(),
            )
        )

        lx, ly = self._legacy_style_positive_tail_xy(x_vals, y_vals)
        if len(lx) > 3:
            raw.append(
                (
                    DCA_PATH_MONOTONE_TAIL,
                    np.asarray(lx, dtype=float),
                    np.asarray(ly, dtype=float),
                )
            )
            ox, oy = self.outlier_detection(lx, ly)
            ox = np.asarray(ox, dtype=float)
            oy = np.asarray(oy, dtype=float)
            same_len = len(ox) == len(lx) and np.allclose(ox, lx) and np.allclose(oy, ly)
            if len(ox) > 3 and not same_len:
                raw.append((DCA_PATH_MONOTONE_TAIL_OL, ox, oy))

        fx, fy = self._first_positive_span_xy(x_vals, y_vals)
        if fx is not None and len(fx) > 3:
            raw.append(
                (
                    DCA_PATH_MONOTONE_FIRST_POS,
                    np.asarray(fx, dtype=float),
                    np.asarray(fy, dtype=float),
                )
            )

        uniq = []
        sigs = set()
        for path_key, mx, my in raw:
            if len(mx) <= 3:
                continue
            sig = (
                len(mx),
                float(mx[0]),
                float(mx[-1]),
                float(my[0]),
                float(my[-1]),
                float(np.min(my)),
                float(np.max(my)),
            )
            if sig in sigs:
                continue
            sigs.add(sig)
            uniq.append((path_key, mx, my))
        return uniq

    def _refine_di_int_legacy_style(self, ox, oy, di_int, q_max, q_min):
        """Same di_int recovery logic as default fit after first estimate."""
        ox = np.asarray(ox, dtype=float)
        oy = np.asarray(oy, dtype=float)
        di_int = float(di_int)
        q_max = float(q_max)
        q_min = float(q_min)
        if di_int < 0:
            ix_min = int(np.argmin(oy))
            ix_max = int(np.argmax(oy))
            dx_m = float(ox[ix_min] - ox[ix_max])
            if dx_m != 0.0 and q_min > 0.0 and q_max > 0.0:
                v = np.log(q_max / q_min) / dx_m
                if np.isfinite(v):
                    di_int = float(v)
        if di_int < 0:
            if q_max == oy[-1]:
                di_int = 0.1
            else:
                i_max = int(np.argmax(oy))
                dx_e = float(ox[-1] - ox[i_max])
                y_last = float(oy[-1])
                if dx_e > 0.0 and y_last > 0.0 and q_max > 0.0:
                    v = np.log(q_max / y_last) / dx_e
                    di_int = float(v) if np.isfinite(v) else 0.1
                else:
                    di_int = 0.1
        if not np.isfinite(di_int) or di_int <= 0:
            di_int = 0.1
        return di_int

    def _monotone_two_step_core(self, s, x_vals, y_vals, mono_x, mono_y):
        """
        Single attempt: Arps ``curve_fit`` on ``(mono_x, mono_y)`` then EUR + di solves.
        Returns ``s`` on success; raises on recoverable failure so callers can try another window.
        """
        mono_x = np.asarray(mono_x, dtype=float)
        mono_y = np.asarray(mono_y, dtype=float)

        q_max = float(np.max(mono_y))
        q_min = float(np.min(mono_y))
        if q_min <= 0 or not np.isfinite(q_min):
            q_min = max(q_max * 0.01, 1e-6)

        di_int = self._di_int_from_endpoints(
            mono_y[0],
            mono_y[-1],
            mono_x[0],
            mono_x[-1],
            require_positive=False,
        )
        di_int = self._refine_di_int_legacy_style(mono_x, mono_y, di_int, q_max, q_min)

        if s["HOLE_DIRECTION"] == "H":
            b_min = self.min_h_b
            b_max = self.max_h_b
        else:
            b_min = self.min_h_b
            b_max = self.max_h_b

        if self._force_t0:
            t0_min = 1
            t0_max = 2
            di_min = 0.01
            di_max = 0.9
            weights = np.ones(len(mono_x))
        else:
            t0_min = float(mono_x[0])
            t0_max = float(mono_x[-1] + 1 if mono_x[-1] == mono_x[0] else mono_x[-1])
            di_min = max(di_int / 2, 1e-5)
            di_max = max(di_int * 2, di_min * 1.5)
            weights = np.array(list(range(1, len(mono_x) + 1))[::-1], dtype=float)

        bounds_low = [q_min, di_min, b_min, t0_min]
        bounds_high = [q_max * 1.1, di_max, b_max, t0_max]
        b0 = 0.5 * (float(b_min) + float(b_max))
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            try:
                popt, _ = curve_fit(
                    self.arps_decline,
                    mono_x,
                    mono_y,
                    p0=[float(q_max), float(di_int), b0, float(t0_min)],
                    bounds=(bounds_low, bounds_high),
                    sigma=weights,
                    absolute_sigma=True,
                    maxfev=12000,
                )
            except Exception as exc:
                raise ValueError("monotone stage-1 curve_fit failed") from exc

        if np.isinf(popt[0]):
            raise ValueError("non-finite qi from curve_fit")

        qi_fit = float(popt[0])
        b_fit = float(popt[2])
        de_stage1 = float(popt[1])
        if not np.isfinite(qi_fit) or qi_fit <= 0 or not np.isfinite(b_fit):
            raise ValueError("invalid initial monotone fit parameters")
        if not np.isfinite(de_stage1) or de_stage1 <= 0:
            de_stage1 = float(di_int)

        Solver = _decline_solver_cls()
        eur_solver = Solver(
            qi=qi_fit,
            qf=None,
            de=float(de_stage1),
            dmin=self.MIN_DECLINE_RATE,
            b=b_fit,
            eur=None,
            t_max=DEFAULT_SOLVER_T_MAX_MONTHS,
        )
        _, _, _, _, eur_fit, _, _ = eur_solver.solve()
        eur_fit = float(eur_fit)
        if not np.isfinite(eur_fit) or eur_fit <= 0:
            cum_obs = float(
                np.sum(np.where(np.isfinite(y_vals) & (y_vals > 0), y_vals, 0.0))
            )
            eur_fit = max(cum_obs * 1.05, qi_fit * 24.0, float(np.sum(mono_y)), 1.0)

        n_tail = max(int(self.qi_tail_points), 1)
        pos_tail_idx = np.where(np.isfinite(y_vals) & (y_vals > 0))[0]
        if len(pos_tail_idx) == 0:
            raise ValueError("no positive points for qi tail")
        tail_idx = pos_tail_idx[-n_tail:]
        qi_tail = float(np.mean(y_vals[tail_idx]))
        if not np.isfinite(qi_tail) or qi_tail <= 0:
            raise ValueError("invalid qi from tail average")
        t0_tail = float(np.mean(x_vals[tail_idx]))

        di_solver = Solver(
            qi=qi_tail,
            qf=None,
            de=None,
            dmin=self.MIN_DECLINE_RATE,
            b=b_fit,
            eur=eur_fit,
            t_max=DEFAULT_SOLVER_T_MAX_MONTHS,
        )
        _, _, _, di_new, _, _, _ = di_solver.solve()
        di_new = float(di_new)
        if not np.isfinite(di_new) or di_new <= 0:
            di_new = max(
                self.MIN_DECLINE_RATE,
                min(abs(float(de_stage1)), float(di_max)),
            )

        if s["MAJOR"] == "OIL":
            minor_ratio = self._tail_phase_ratio(
                s["NORMALIZED_GAS"][-self.MINOR_TAIL_MONTHS :],
                s["NORMALIZED_OIL"][-self.MINOR_TAIL_MONTHS :],
            )
            water_ratio = self._tail_phase_ratio(
                s["NORMALIZED_WATER"][-self.MINOR_TAIL_MONTHS :],
                s["NORMALIZED_OIL"][-self.MINOR_TAIL_MONTHS :],
            )
        else:
            minor_ratio = self._tail_phase_ratio(
                s["NORMALIZED_OIL"][-self.MINOR_TAIL_MONTHS :],
                s["NORMALIZED_GAS"][-self.MINOR_TAIL_MONTHS :],
            )
            water_ratio = self._tail_phase_ratio(
                s["NORMALIZED_WATER"][-self.MINOR_TAIL_MONTHS :],
                s["NORMALIZED_GAS"][-self.MINOR_TAIL_MONTHS :],
            )

        s["qi"] = qi_tail
        s["di"] = di_new
        s["b"] = b_fit
        s["t0"] = t0_tail
        s["q0"] = y_vals[0]
        s["minor_ratio"] = minor_ratio
        s["water_ratio"] = water_ratio
        return s

    def _dca_params_default(self, s):
        """Original per-row fit: peak/zero/outlier filtering then ``curve_fit`` on Arps."""

        s = self._sort_well_series_by_t_index(s)
        x_vals = s['T_INDEX']

        if s['MAJOR'] == 'OIL':
            y_vals = s['NORMALIZED_OIL']
        elif s['MAJOR'] == 'GAS':
            y_vals = s['NORMALIZED_GAS']
        elif s['MAJOR'] == 'WATER':
            y_vals = s['NORMALIZED_WATER']
        else:
            # Fallback to gas if phase is not recognized
            y_vals = s['NORMALIZED_GAS']

        if len(x_vals) > 3:
            z = np.array(y_vals)
            a = argrelextrema(z, np.greater)
            if len(a[0]) > 0:
                indexMax = a[-1][-1]
                indexMin = a[-1][0]
                t0Max = x_vals[indexMax]
                t0Min = x_vals[indexMin]
            else:
                indexMax = 0
                indexMin = 0
                t0Max = x_vals[indexMax]
                t0Min = x_vals[indexMin]

            t0Min, t0Max = min(t0Min, t0Max), max(t0Min, t0Max)

            filtered_x = np.array(x_vals[indexMin:])
            filtered_y = np.array(y_vals[indexMin:])
            
            if self.verbose:
                logger.info(
                    'Well %s: After peak detection — %s points (from index %s)',
                    s["UID"],
                    len(filtered_x),
                    indexMin,
                )

            zero_filter = np.array([y > 0 for y in filtered_y])
            zero_filtered_count = len(filtered_y) - np.sum(zero_filter)
            filtered_x = filtered_x[zero_filter]
            filtered_y = filtered_y[zero_filter]
            
            if self.verbose:
                logger.info(
                    'Well %s: After zero filtering — %s points (removed %s zero/negative values)',
                    s["UID"],
                    len(filtered_x),
                    zero_filtered_count,
                )
            
            outliered_x, outliered_y = self.outlier_detection(filtered_x,filtered_y)
            
            if self.verbose:
                outlier_filtered_count = len(filtered_x) - len(outliered_x)
                logger.info(
                    'Well %s: After outlier detection — %s points (removed %s outliers)',
                    s["UID"],
                    len(outliered_x),
                    outlier_filtered_count,
                )

            if self._force_t0:
                # Typecurve fit: decline from empirical peak forward only.
                # Do not fit the pre-peak ramp; pin t0 near peak; weight near-peak points highest.
                x_arr = np.asarray(x_vals, dtype=float)
                y_arr = np.asarray(y_vals, dtype=float)
                finite = np.isfinite(x_arr) & np.isfinite(y_arr)
                x_arr = x_arr[finite]
                y_arr = y_arr[finite]
                if len(y_arr) == 0:
                    return self._dca_failure_finish(
                        s,
                        x_vals,
                        y_vals,
                        note_print="Insufficient data before filtering, well: " + str(s["UID"]),
                        backup_path_key=DCA_PATH_LEGACY_BACKUP_PRE,
                    )
                i_peak = int(np.nanargmax(y_arr))
                outliered_x = x_arr[i_peak:]
                outliered_y = y_arr[i_peak:]
                # Pin decline start to the empirical peak (strictly increasing bounds for curve_fit).
                t0Min = float(outliered_x[0])
                t0Max = t0Min + 1e-3
            

            if len(outliered_x) > 3:
                if t0Min == t0Max:
                    t0Max = t0Max + 1
                di_int = self._di_int_from_endpoints(
                    outliered_y[0],
                    outliered_y[-1],
                    outliered_x[0],
                    outliered_x[-1],
                )
                q_max = float(np.max(outliered_y))
                q_min = float(np.min(outliered_y))
                di_int = self._refine_di_int_legacy_style(
                    outliered_x, outliered_y, di_int, q_max, q_min
                )

                if s['HOLE_DIRECTION'] == 'H':
                    bMin = self.min_h_b
                    bMax = self.max_h_b
                else:
                    bMin = self.min_h_b
                    bMax = self.max_h_b

                if self._force_t0:
                    # curve_fit sigma is uncertainty (larger => less weight).
                    # Use increasing sigma so the peak (first point) is honored most.
                    weight_range = list(range(1, len(outliered_x) + 1))
                    di_min = max(di_int / 2.0, 0.01) if np.isfinite(di_int) and di_int > 0 else 0.01
                    di_max = min(di_int * 2.0, 0.9) if np.isfinite(di_int) and di_int > 0 else 0.9
                    if di_min >= di_max:
                        di_min, di_max = 0.01, 0.9
                else:
                    di_min = di_int/2
                    di_max = di_int*2
                    weight_range = list(range(1,len(outliered_x)+1))
                    weight_range = weight_range[::-1]
                
                try:
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore")
                        popt, pcov = curve_fit(
                            self.arps_decline,
                            outliered_x,
                            outliered_y,
                            p0=[q_max, di_int, (bMin + bMax) / 2, t0Min],
                            bounds=(
                                [q_min, di_min, bMin, t0Min],
                                [q_max * 1.1, di_max, bMax, t0Max],
                            ),
                            sigma=weight_range,
                            absolute_sigma=True,
                        )

                    if s["MAJOR"] == 'OIL':
                        minor_ratio = self._tail_phase_ratio(
                            s["NORMALIZED_GAS"][-self.MINOR_TAIL_MONTHS :],
                            s["NORMALIZED_OIL"][-self.MINOR_TAIL_MONTHS :],
                        )
                        water_ratio = self._tail_phase_ratio(
                            s["NORMALIZED_WATER"][-self.MINOR_TAIL_MONTHS :],
                            s["NORMALIZED_OIL"][-self.MINOR_TAIL_MONTHS :],
                        )
                    else:
                        minor_ratio = self._tail_phase_ratio(
                            s["NORMALIZED_OIL"][-self.MINOR_TAIL_MONTHS :],
                            s["NORMALIZED_GAS"][-self.MINOR_TAIL_MONTHS :],
                        )
                        water_ratio = self._tail_phase_ratio(
                            s["NORMALIZED_WATER"][-self.MINOR_TAIL_MONTHS :],
                            s["NORMALIZED_GAS"][-self.MINOR_TAIL_MONTHS :],
                        )

                    if not np.isinf(popt[0]):
                        if self._force_t0:
                            # Keep peak-forward Arps params; L3M well adjustment is for well DCA only.
                            s['qi'] = popt[0]
                            s['di'] = popt[1]
                            s['b'] = popt[2]
                            s['t0'] = popt[3]
                            self._incr_dca_path(DCA_PATH_LEGACY_FORCE_T0)
                        else:
                            adj_qi, adj_di = self._adjust_default_fit_to_recent_l3m(
                                popt[0], popt[1], popt[2], popt[3], x_vals, y_vals
                            )
                            s['qi'] = adj_qi
                            s['di'] = adj_di
                            s['b'] = popt[2]
                            s['t0'] = popt[3]
                            self._incr_dca_path(DCA_PATH_LEGACY_PRIMARY)
                        s['q0']=y_vals[0] #Probably will need revision, high chance first value is zero
                        s['minor_ratio']=minor_ratio
                        s['water_ratio']=water_ratio
                    else:
                        return self._dca_failure_finish(
                            s,
                            x_vals,
                            y_vals,
                            note_print="DCA Error: " + str(s["UID"]),
                            backup_path_key=DCA_PATH_LEGACY_BACKUP_FIT,
                        )
                except Exception:
                    return self._dca_failure_finish(
                        s,
                        x_vals,
                        y_vals,
                        note_print="DCA Error: " + str(s["UID"]),
                        backup_path_key=DCA_PATH_LEGACY_BACKUP_FIT,
                    )
            else:
                return self._dca_failure_finish(
                    s,
                    x_vals,
                    y_vals,
                    note_log_warning=(
                        "Well %s: INSUFFICIENT DATA AFTER FILTERING "
                        "(original=%s, after_peak=%s, after_outlier=%s; need >3)"
                    )
                    % (s["UID"], len(x_vals), len(filtered_x), len(outliered_x)),
                    note_print="Insufficient data after filtering, well: " + str(s["UID"]),
                    backup_path_key=DCA_PATH_LEGACY_BACKUP_POST,
                )

        else:
            return self._dca_failure_finish(
                s,
                x_vals,
                y_vals,
                note_print="Insufficient data before filtering, well: " + str(s["UID"]),
                backup_path_key=DCA_PATH_LEGACY_BACKUP_PRE,
            )

        return s

    # Backward-compatible internal alias.
    def _dca_params_legacy(self, s):
        return self._dca_params_default(s)

    def _dca_params_monotone_two_step(self, s):
        """
        Two-step decline: try Arps fit + EUR + ``di`` solve on progressively looser
        windows (strict monotone segment, legacy-style post-peak tail with/without
        outlier filtering, then first-positive span). Uses the same terminal backup
        semantics as legacy via ``_dca_failure_finish`` / ``handle_dca_error``.
        """
        s = self._sort_well_series_by_t_index(s)
        x_vals = np.asarray(s["T_INDEX"], dtype=float)

        if s["MAJOR"] == "OIL":
            y_vals = np.asarray(s["NORMALIZED_OIL"], dtype=float)
        elif s["MAJOR"] == "GAS":
            y_vals = np.asarray(s["NORMALIZED_GAS"], dtype=float)
        elif s["MAJOR"] == "WATER":
            y_vals = np.asarray(s["NORMALIZED_WATER"], dtype=float)
        else:
            y_vals = np.asarray(s["NORMALIZED_GAS"], dtype=float)

        if len(x_vals) <= 3:
            return self._dca_failure_finish(
                s,
                x_vals,
                y_vals,
                note_print="Insufficient data before filtering, well: " + str(s["UID"]),
                backup_path_key=DCA_PATH_MONOTONE_BACKUP_PRE,
            )

        for path_key, mono_x, mono_y in self._monotone_fit_xy_candidates(x_vals, y_vals):
            try:
                out = self._monotone_two_step_core(s, x_vals, y_vals, mono_x, mono_y)
                self._incr_dca_path(path_key)
                return out
            except Exception:
                continue

        return self._dca_failure_finish(
            s,
            x_vals,
            y_vals,
            note_print="DCA Error: " + str(s["UID"]),
            backup_path_key=DCA_PATH_MONOTONE_BACKUP_EXHAUSTED,
        )

    def dca_params(self, s, fit_method=None):
        """
        Estimate decline parameters for one grouped row ``s``.

        Args:
            s: Row Series from ``groupby`` / ``apply`` with list columns (T_INDEX, NORMALIZED_* , ...).
            fit_method: Override ``self.fit_method`` for this call only. ``None`` uses the instance default.
        """
        method = self.fit_method if fit_method is None else fit_method
        if method in (DCA_FIT_METHOD_DEFAULT, "legacy"):
            return self._dca_params_default(s)
        if method == DCA_FIT_METHOD_MONOTONE_TWO_STEP:
            return self._dca_params_monotone_two_step(s)
        raise ValueError(
            f"Unknown fit_method {method!r}; expected {DCA_FIT_METHOD_DEFAULT!r} or {DCA_FIT_METHOD_MONOTONE_TWO_STEP!r}."
        )

    def vect_generate_params_tc(self,param_df):

        self._force_t0 = True

        param_df['HOLE_DIRECTION'] = "H"
        param_df = param_df[param_df['T_INDEX']<60]
        param_df = param_df.rename(columns={
            'OIL':'NORMALIZED_OIL',
            'GAS':"NORMALIZED_GAS",
            'WATER':'NORMALIZED_WATER',
            'level_1':'UID'
        })
        param_df = param_df.sort_values(['UID', 'T_INDEX'])

        imploded_df = param_df[[
            'UID',
            'MAJOR',
            'HOLE_DIRECTION',
            'T_INDEX',
            'NORMALIZED_OIL',
            'NORMALIZED_GAS',
            'NORMALIZED_WATER'
        ]].groupby(
            ['UID',
            'MAJOR',
            'HOLE_DIRECTION']
        ).agg({
            'T_INDEX': lambda x: x.tolist(),
            'NORMALIZED_OIL': lambda x: x.tolist(),
            'NORMALIZED_GAS': lambda x: x.tolist(),
            'NORMALIZED_WATER': lambda x: x.tolist()
        }).reset_index()

        imploded_df = imploded_df.apply(self.dca_params, axis=1)
        imploded_df = imploded_df[[
            'UID',
            'MAJOR',
            'q0',
            'qi',
            'di',
            'b',
            't0',
            'minor_ratio',
            'water_ratio',
        ]].rename(columns={
            'MAJOR':'major',
        })

        self._force_t0 = False

        return imploded_df



    def vect_generate_params(self):
        self.V_DCA_FAILURES = 0
        self._reset_dca_run_path_counts()
        l_start = time.time()

        norm_df = self._normalized_dataframe.sort_values(['UID', 'T_INDEX'])
        imploded_df = norm_df[[
            'UID',
            'MAJOR',
            'HOLE_DIRECTION',
            'LENGTH_NORM',
            'T_INDEX',
            'NORMALIZED_OIL',
            'NORMALIZED_GAS',
            'NORMALIZED_WATER'
        ]].groupby(
            ['UID',
            'MAJOR',
            'HOLE_DIRECTION',
            'LENGTH_NORM']
        ).agg({
            'T_INDEX': lambda x: x.tolist(),
            'NORMALIZED_OIL': lambda x: x.tolist(),
            'NORMALIZED_GAS': lambda x: x.tolist(),
            'NORMALIZED_WATER': lambda x: x.tolist()
        }).reset_index()

        # Apply DCA parameters calculation with progress tracking
        tqdm.pandas(desc="Processing wells (vectorized mode)")
        imploded_df = imploded_df.progress_apply(self.dca_params, axis=1)
        attempted = len(imploded_df)
        successful = int(imploded_df["qi"].notna().sum())
        self._raise_if_all_dca_failed(attempted, successful)

        imploded_df = imploded_df[[
            'UID',
            'MAJOR',
            'LENGTH_NORM',
            'q0',
            'qi',
            'di',
            'b',
            't0',
            'minor_ratio',
            'water_ratio',
        ]].rename(columns={
            'MAJOR':'major',
            'LENGTH_NORM':'h_length'
        })

        r_df:pd.DataFrame = pd.DataFrame([])

        for major in ['OIL','GAS']:
            l_df = imploded_df[imploded_df['major']==major]

            if len(l_df)>0:
                if self.outlier_correction:
                    q3, q2, q1 = np.percentile(l_df['minor_ratio'], [75,50 ,25])
                    high_cutoff = self.iqr_limit*(q3-q1)+q3
                    l_df['minor_ratio'] = np.where(
                        l_df['minor_ratio']>high_cutoff,
                        q2,
                        l_df['minor_ratio']
                    )

                    q3, q2, q1 = np.percentile(l_df['water_ratio'], [75,50 ,25])
                    high_cutoff = self.iqr_limit*(q3-q1)+q3
                    l_df['water_ratio'] = np.where(
                        l_df['water_ratio']>high_cutoff,
                        q2,
                        l_df['water_ratio']
                    )

                if r_df.empty:
                    r_df = l_df
                else:
                    r_df = pd.concat([r_df,l_df])

        imploded_df = r_df

        l_duration = time.time() - l_start
        self._print_dca_run_summary(
            "DCA summary (vectorized major-phase mode)",
            attempted,
            successful,
            l_duration,
        )

        self._params_dataframe = imploded_df

    def vect_generate_params_three_phase(self):
        """
        Generate DCA parameters for each non-zero phase independently.
        This method calculates decline parameters for OIL, GAS, and WATER phases
        separately instead of using ratios from the major phase.
        """
        self.V_DCA_FAILURES = 0
        self._reset_dca_run_path_counts()
        l_start = time.time()

        all_results = []

        # Group by well to determine which phases have non-zero production for each well
        well_phases = self._normalized_dataframe.groupby('UID').agg({
            'NORMALIZED_OIL': 'sum',
            'NORMALIZED_GAS': 'sum',
            'NORMALIZED_WATER': 'sum'
        }).reset_index()

        # Calculate total number of operations for progress tracking
        total_operations = 0
        for _, well_row in well_phases.iterrows():
            if well_row['NORMALIZED_OIL'] > 0:
                total_operations += 1
            if well_row['NORMALIZED_GAS'] > 0:
                total_operations += 1
            if well_row['NORMALIZED_WATER'] > 0:
                total_operations += 1

        # Initialize progress bar
        progress_bar = tqdm(total=total_operations, desc="Processing wells (three-phase mode)", unit="well-phase")

        # Determine which phases to analyze for each well
        for _, well_row in well_phases.iterrows():
            uid = well_row['UID']
            phases_to_analyze = []
            
            if well_row['NORMALIZED_OIL'] > 0:
                phases_to_analyze.append('OIL')
            if well_row['NORMALIZED_GAS'] > 0:
                phases_to_analyze.append('GAS')
            if well_row['NORMALIZED_WATER'] > 0:
                phases_to_analyze.append('WATER')

            # Get well data for this UID
            well_data = (
                self._normalized_dataframe[self._normalized_dataframe['UID'] == uid]
                .sort_values('T_INDEX')
            )

            for phase in phases_to_analyze:
                # Create a temporary dataframe for this phase-well combination
                temp_df = well_data[[
                    'UID',
                    'HOLE_DIRECTION',
                    'LENGTH_NORM',
                    'T_INDEX',
                    f'NORMALIZED_{phase}'
                ]].copy()
                
                # Add a MAJOR column for this phase
                temp_df['MAJOR'] = phase
                
                # Add dummy columns for other phases (set to 0)
                for other_phase in ['OIL', 'GAS', 'WATER']:
                    if other_phase != phase:
                        temp_df[f'NORMALIZED_{other_phase}'] = 0

                # Group by well characteristics
                imploded_df = temp_df.groupby([
                    'UID',
                    'MAJOR',
                    'HOLE_DIRECTION',
                    'LENGTH_NORM'
                ]).agg({
                    'T_INDEX': lambda x: x.tolist(),
                    'NORMALIZED_OIL': lambda x: x.tolist(),
                    'NORMALIZED_GAS': lambda x: x.tolist(),
                    'NORMALIZED_WATER': lambda x: x.tolist()
                }).reset_index()

                # Apply DCA parameters calculation
                imploded_df = imploded_df.apply(self.dca_params, axis=1)
                
                # Update progress bar
                progress_bar.update(1)

                # Filter out failed DCA calculations
                imploded_df = imploded_df[imploded_df['qi'].notna()]

                if len(imploded_df) > 0:
                    # Select and rename columns
                    phase_df = imploded_df[[
                        'UID',
                        'MAJOR',
                        'LENGTH_NORM',
                        'qi',
                        'di',
                        'b',
                        't0'
                    ]].rename(columns={
                        'MAJOR': 'phase',
                        'LENGTH_NORM': 'h_length'
                    })
                    
                    # Add phase-specific columns
                    phase_df['minor_ratio'] = 0.0  # No minor ratio in three-phase mode
                    phase_df['water_ratio'] = 0.0  # No water ratio in three-phase mode
                    
                    all_results.append(phase_df)

        # Combine all results
        if all_results:
            imploded_df = pd.concat(all_results, ignore_index=True)
        else:
            imploded_df = pd.DataFrame()

        # Close progress bar
        progress_bar.close()

        l_duration = time.time() - l_start
        successful = len(imploded_df)
        self._raise_if_all_dca_failed(total_operations, successful)
        self._print_dca_run_summary(
            "DCA summary (three-phase mode)",
            total_operations,
            successful,
            l_duration,
        )

        self._params_dataframe = imploded_df


    def run_DCA(self, _verbose=False):
        self.verbose = _verbose
        if self.verbose:
            print('Generating time index.', file=self.STAT_FILE, flush=True)
            
        
        self.generate_t_index()

        if self.verbose:
            print('Normalizing production.', file=self.STAT_FILE, flush=True)

        self.normalize_production()

        if self.verbose:
            print('Generating decline parameters.', file=self.STAT_FILE, flush=True)
        #self.generate_params()
        
        if self.three_phase_mode:
            self.vect_generate_params_three_phase()
        else:
            self.vect_generate_params()

    def add_months(self, start_date, delta_period):
        end_date = start_date + relativedelta(months=delta_period)
        return end_date
    
    def generate_oneline(self, num_months=DEFAULT_FORECAST_HORIZON_MONTHS, denormalize=False, _verbose=False):
        self.verbose = _verbose

        self.generate_flowstream(num_months=num_months,denormalize=denormalize,actual_dates=False,_verbose=_verbose)

        if self._params_dataframe.empty:
            self.run_DCA(_verbose=_verbose)

        if self.three_phase_mode:
            self._generate_oneline_three_phase(num_months, denormalize, _verbose)
        else:
            self._generate_oneline_original(num_months, denormalize, _verbose)

    def _generate_oneline_original(self, num_months, denormalize, _verbose):
        """Original oneline generation using major phase with ratios"""
        # Of note, since you often forget this, the flowstream dataframe inherits the denormalize attribute
        # So the oneline sums will always follow the denormalization settings
        oneline_df = self._flowstream_dataframe.reset_index()[['UID','OIL',"GAS",'WATER']].groupby('UID').sum().reset_index()

        self._dataframe[self._date_col] = pd.to_datetime(self._dataframe[self._date_col])

        min_df = self._dataframe[[self._uid_col,self._date_col]].groupby(by=[self._uid_col]).min().reset_index()
        min_df = min_df.rename(columns={self._uid_col:"UID",self._date_col:"MIN_DATE"})
        min_df = min_df[min_df['MIN_DATE'].notnull()]

        self._params_dataframe = self._params_dataframe.merge(min_df, left_on='UID', right_on='UID')

        self._params_dataframe = self._params_dataframe.replace([np.inf, -np.inf], np.nan)

        self._params_dataframe = self._params_dataframe.dropna(subset='t0')
        self._require_valid_t0_params(self._params_dataframe)
        self._params_dataframe['T0_DATE'] = self._compute_t0_date_column(self._params_dataframe)

        flow_df = self._params_dataframe[['UID','major','h_length','qi','di','b','T0_DATE','minor_ratio','water_ratio']].copy()

        # Calculate flow_df denormalization_scalar
        if denormalize:
            flow_df['denormalization_scalar'] = np.where(
                flow_df['h_length'] > 1,
                flow_df['h_length'] / self.STANDARD_LENGTH,
                1.0
            )
        else:
            flow_df['denormalization_scalar'] = 1.0

        flow_df = flow_df.rename(columns={
            'major':'MAJOR',
            'b':'B',
            'di':'DE',
            'minor_ratio':'MINOR_RATIO',
            'water_ratio':'WATER_RATIO'
        })
        # Fill na in MINOR_RATIO and WATER_RATIO with 0
        flow_df['MINOR_RATIO'] = flow_df['MINOR_RATIO'].fillna(0)
        flow_df['WATER_RATIO'] = flow_df['WATER_RATIO'].fillna(0)

        flow_df['IPO'] = np.where(
            flow_df['MAJOR'] == "OIL",
            flow_df['qi']*flow_df['denormalization_scalar'],
            flow_df['qi']*flow_df['MINOR_RATIO']*flow_df['denormalization_scalar']
        )

        flow_df['IPG'] = np.where(  
            flow_df['MAJOR'] == "GAS",
            flow_df['qi']*flow_df['denormalization_scalar'],
            flow_df['qi']*flow_df['MINOR_RATIO']*flow_df['denormalization_scalar']
        )
        
        flow_df['WATER'] = flow_df['qi']*flow_df['WATER_RATIO']

        flow_df['ARIES_DE'] = flow_df.apply(lambda row: (1-np.power(((row.DE*12)*row.B+1),(-1/row.B)))*100, axis=1)

        self._oneline = oneline_df.merge(
            flow_df[['UID','MAJOR','IPO','IPG','B','DE','T0_DATE','MINOR_RATIO','WATER_RATIO','ARIES_DE']],
            left_on='UID',
            right_on='UID'
        )

    def _generate_oneline_three_phase(self, num_months, denormalize, _verbose):
        """Three-phase oneline generation with independent decline curves for each phase"""
        # Get flowstream totals by well
        oneline_df = self._flowstream_dataframe.reset_index()[['UID','OIL',"GAS",'WATER']].groupby('UID').sum().reset_index()

        # Get minimum dates for each well
        self._dataframe[self._date_col] = pd.to_datetime(self._dataframe[self._date_col])
        min_df = self._dataframe[[self._uid_col,self._date_col]].groupby(by=[self._uid_col]).min().reset_index()
        min_df = min_df.rename(columns={self._uid_col:"UID",self._date_col:"MIN_DATE"})
        min_df = min_df[min_df['MIN_DATE'].notnull()]

        # Merge with params dataframe
        params_with_dates = self._params_dataframe.merge(min_df, left_on='UID', right_on='UID')
        params_with_dates = params_with_dates.replace([np.inf, -np.inf], np.nan)
        params_with_dates = params_with_dates.dropna(subset='t0')
        self._require_valid_t0_params(params_with_dates)
        params_with_dates['T0_DATE'] = self._compute_t0_date_column(params_with_dates)

        # Create oneline data for each well
        well_summaries = []
        
        for uid in oneline_df['UID'].unique():
            well_params = params_with_dates[params_with_dates['UID'] == uid]
            well_flow = oneline_df[oneline_df['UID'] == uid].iloc[0]
            
            # Initialize well summary
            well_summary = {
                'UID': uid,
                'OIL': well_flow['OIL'],
                'GAS': well_flow['GAS'],
                'WATER': well_flow['WATER'],
                'T0_DATE': well_params['T0_DATE'].iloc[0] if len(well_params) > 0 else None
            }
            
            # Add phase-specific parameters
            for phase in ['OIL', 'GAS', 'WATER']:
                phase_params = well_params[well_params['phase'] == phase]
                if len(phase_params) > 0:
                    param = phase_params.iloc[0]
                    h_length = param['h_length']
                    
                    # Calculate denormalization scalar
                    if denormalize and h_length > 1:
                        denormalization_scalar = h_length / self.STANDARD_LENGTH
                    else:
                        denormalization_scalar = 1.0
                    
                    # Add phase-specific parameters
                    well_summary[f'IP{phase[0]}'] = param['qi'] * denormalization_scalar  # IPO, IPG, IPW
                    well_summary[f'D{phase[0]}'] = param['di']  # DO, DG, DW
                    well_summary[f'B{phase[0]}'] = param['b']   # BO, BG, BW
                    well_summary[f'ARIES_D{phase[0]}'] = (1-np.power(((param['di']*12)*param['b']+1),(-1/param['b'])))*100
                else:
                    # No parameters for this phase
                    well_summary[f'IP{phase[0]}'] = 0.0
                    well_summary[f'D{phase[0]}'] = 0.0
                    well_summary[f'B{phase[0]}'] = 0.0
                    well_summary[f'ARIES_D{phase[0]}'] = 0.0
            
            well_summaries.append(well_summary)
        
        # Create the oneline dataframe
        self._oneline = pd.DataFrame(well_summaries)


    def generate_flowstream(self, num_months=DEFAULT_FORECAST_HORIZON_MONTHS, denormalize=False, actual_dates=False, _verbose=False):
        self.verbose = _verbose

        if self._params_dataframe.empty:
            self.run_DCA(_verbose=_verbose)

        t_range = np.array(range(1,num_months))

        if self.three_phase_mode:
            # Three-phase mode: each phase has its own decline curve
            self._generate_flowstream_three_phase(t_range, num_months, denormalize, actual_dates)
        else:
            # Original mode: major phase with ratios
            self._generate_flowstream_original(t_range, num_months, denormalize, actual_dates)

    def _generate_flowstream_original(self, t_range, num_months, denormalize, actual_dates):
        """Original flowstream generation using major phase with ratios"""
        flow_df = self._params_dataframe[['UID','major','h_length','qi','di','b','t0','minor_ratio','water_ratio']].copy()

        flow_df['T_INDEX'] = flow_df.apply(lambda row: t_range, axis=1)
        if denormalize:
            flow_df['denormalization_scalar'] = np.where(
                flow_df['h_length'] > 1,
                    flow_df['h_length'] / self.STANDARD_LENGTH,
                    1.0
                )
        else:
            flow_df['denormalization_scalar'] = 1.0
        
        flow_df['dca_values'] = flow_df.apply(
            lambda row: np.array(self.arps_decline(t_range, row.qi, row.di, row.b, row.t0)) * row['denormalization_scalar'],
            axis=1
        )
        flow_df['OIL'] = np.where(
            flow_df['major'] == "OIL",
            flow_df['dca_values'],
            flow_df['dca_values'] * flow_df['minor_ratio']
        )
        flow_df['GAS'] = np.where(
            flow_df['major'] == "GAS",
            flow_df['dca_values'],
            flow_df['dca_values'] * flow_df['minor_ratio']
        )
        flow_df['WATER'] = flow_df['dca_values'] * flow_df['water_ratio']
        
        self._flowstream_dataframe = flow_df[['UID','major','T_INDEX','OIL','GAS','WATER']].rename(columns={'major':'MAJOR'})
        self._flowstream_dataframe = self._flowstream_dataframe.set_index(['UID','MAJOR']).apply(pd.Series.explode).reset_index()
        self._flowstream_dataframe = self._flowstream_dataframe.set_index(['UID', 'T_INDEX'])

        # Replace na in OIL, GAS, WATER with 0
        self._flowstream_dataframe['OIL'] = self._flowstream_dataframe['OIL'].fillna(0)
        self._flowstream_dataframe['GAS'] = self._flowstream_dataframe['GAS'].fillna(0)
        self._flowstream_dataframe['WATER'] = self._flowstream_dataframe['WATER'].fillna(0)

        self._flowstream_dataframe['OIL'] = pd.to_numeric(self._flowstream_dataframe['OIL'])
        self._flowstream_dataframe['GAS'] = pd.to_numeric(self._flowstream_dataframe['GAS'])
        self._flowstream_dataframe['WATER'] = pd.to_numeric(self._flowstream_dataframe['WATER'])

        self._flowstream_dataframe.replace([np.inf, -np.inf], 0, inplace=True)

        if denormalize:
            actual_df = self._dataframe[[self._uid_col,'T_INDEX',self._oil_col,self._gas_col,self._water_col]]
            actual_df = actual_df.rename(columns={
                self._uid_col:'UID',
                self._oil_col:'OIL',
                self._gas_col:"GAS",
                self._water_col:"WATER"
            })
        else:
            actual_df = self._normalized_dataframe[[
                'UID',
                'T_INDEX',
                'NORMALIZED_OIL',
                'NORMALIZED_GAS',
                'NORMALIZED_WATER'
            ]]
            actual_df = actual_df.rename(columns={
                'NORMALIZED_OIL':'OIL',
                'NORMALIZED_GAS':"GAS",
                'NORMALIZED_WATER':'WATER'
            })

        if actual_dates:
            actual_df['P_DATE'] = self._dataframe[self._date_col]
            self._flowstream_dataframe['P_DATE'] = None
            
        actual_df = actual_df.set_index(['UID', 'T_INDEX'])

    def _generate_flowstream_three_phase(self, t_range, num_months, denormalize, actual_dates):
        """Three-phase flowstream generation with independent decline curves for each phase"""
        # Create a list to store all flow data
        all_flows = []
        
        for _, row in self._params_dataframe.iterrows():
            uid = row['UID']
            phase = row['phase']
            h_length = row['h_length']
            qi = row['qi']
            di = row['di']
            b = row['b']
            t0 = row['t0']
            
            # Calculate denormalization scalar
            if denormalize and h_length > 1:
                denormalization_scalar = h_length / self.STANDARD_LENGTH
            else:
                denormalization_scalar = 1.0
            
            # Calculate DCA values for this phase
            dca_values = np.array(self.arps_decline(t_range, qi, di, b, t0)) * denormalization_scalar
            
            # Create flow data for this phase-well combination
            for t_idx, flow_rate in zip(t_range, dca_values):
                flow_data = {
                    'UID': uid,
                    'T_INDEX': t_idx,
                    'OIL': 0.0,
                    'GAS': 0.0,
                    'WATER': 0.0
                }
                
                # Set the flow rate for the appropriate phase
                if phase == 'OIL':
                    flow_data['OIL'] = flow_rate
                elif phase == 'GAS':
                    flow_data['GAS'] = flow_rate
                elif phase == 'WATER':
                    flow_data['WATER'] = flow_rate
                
                all_flows.append(flow_data)
        
        # Create the flowstream dataframe
        if all_flows:
            self._flowstream_dataframe = pd.DataFrame(all_flows)
            # Group by UID and T_INDEX to combine the three phase entries (OIL, GAS, WATER) into single rows
            # This ensures each (UID, T_INDEX) combination appears only once with all phases populated
            self._flowstream_dataframe = self._flowstream_dataframe.groupby(['UID', 'T_INDEX']).agg({
                'OIL': 'sum',
                'GAS': 'sum',
                'WATER': 'sum'
            }).reset_index()
            self._flowstream_dataframe = self._flowstream_dataframe.set_index(['UID', 'T_INDEX'])
        else:
            self._flowstream_dataframe = pd.DataFrame(columns=['UID', 'T_INDEX', 'OIL', 'GAS', 'WATER'])
            self._flowstream_dataframe = self._flowstream_dataframe.set_index(['UID', 'T_INDEX'])

        # Replace na values with 0
        self._flowstream_dataframe['OIL'] = self._flowstream_dataframe['OIL'].fillna(0)
        self._flowstream_dataframe['GAS'] = self._flowstream_dataframe['GAS'].fillna(0)
        self._flowstream_dataframe['WATER'] = self._flowstream_dataframe['WATER'].fillna(0)

        # Convert to numeric
        self._flowstream_dataframe['OIL'] = pd.to_numeric(self._flowstream_dataframe['OIL'])
        self._flowstream_dataframe['GAS'] = pd.to_numeric(self._flowstream_dataframe['GAS'])
        self._flowstream_dataframe['WATER'] = pd.to_numeric(self._flowstream_dataframe['WATER'])

        # Replace infinite values
        self._flowstream_dataframe.replace([np.inf, -np.inf], 0, inplace=True)

        # Handle actual data comparison
        if denormalize:
            actual_df = self._dataframe[[self._uid_col,'T_INDEX',self._oil_col,self._gas_col,self._water_col]]
            actual_df = actual_df.rename(columns={
                self._uid_col:'UID',
                self._oil_col:'OIL',
                self._gas_col:"GAS",
                self._water_col:"WATER"
            })
        else:
            actual_df = self._normalized_dataframe[[
                'UID',
                'T_INDEX',
                'NORMALIZED_OIL',
                'NORMALIZED_GAS',
                'NORMALIZED_WATER'
            ]]
            actual_df = actual_df.rename(columns={
                'NORMALIZED_OIL':'OIL',
                'NORMALIZED_GAS':"GAS",
                'NORMALIZED_WATER':'WATER'
            })

        if actual_dates:
            actual_df['P_DATE'] = self._dataframe[self._date_col]
            self._flowstream_dataframe['P_DATE'] = None
            
        actual_df = actual_df.set_index(['UID', 'T_INDEX'])


    def generate_typecurve(self, num_months=DEFAULT_FORECAST_HORIZON_MONTHS, denormalize=False, prob_levels=[.1,.5,.9], _verbose=False, return_params=False):
        if self._flowstream_dataframe is None:
            self.generate_flowstream(num_months=num_months,denormalize=denormalize, _verbose=_verbose)
        if self._oneline.empty:
            if self._params_dataframe.empty:
                self.run_DCA(_verbose=_verbose)
            if self.three_phase_mode:
                self._generate_oneline_three_phase(num_months, denormalize, _verbose)
            else:
                self._generate_oneline_original(num_months, denormalize, _verbose)

        if self.three_phase_mode:
            self._generate_typecurve_three_phase(num_months, denormalize, prob_levels, _verbose, return_params)
        else:
            self._generate_typecurve_original(num_months, denormalize, prob_levels, _verbose, return_params)

    def _build_typecurve_flowstream(self, denormalize):
        """
        Typecurve-only flowstream: historical rates overlaid on forecast.

        Prefers historical OIL/GAS/WATER where present and non-NA; keeps forecast
        elsewhere. Does not mutate ``_flowstream_dataframe``.

        Historical ``T_INDEX`` from ``month_diff`` starts at 0; forecast / typecurve
        grid starts at 1. Historical indexes are shifted by +1 before joining so
        first producing month overlays typecurve time zero (``T_INDEX=1``).
        """
        forecast = (
            self._flowstream_dataframe
            .reset_index()[['UID', 'T_INDEX', 'OIL', 'GAS', 'WATER']]
            .copy()
        )

        if denormalize:
            actual_df = self._dataframe[
                [self._uid_col, 'T_INDEX', self._oil_col, self._gas_col, self._water_col]
            ].copy()
            actual_df = actual_df.rename(columns={
                self._uid_col: 'UID',
                self._oil_col: 'OIL',
                self._gas_col: 'GAS',
                self._water_col: 'WATER',
            })
        else:
            actual_df = self._normalized_dataframe[[
                'UID',
                'T_INDEX',
                'NORMALIZED_OIL',
                'NORMALIZED_GAS',
                'NORMALIZED_WATER',
            ]].copy()
            actual_df = actual_df.rename(columns={
                'NORMALIZED_OIL': 'OIL',
                'NORMALIZED_GAS': 'GAS',
                'NORMALIZED_WATER': 'WATER',
            })

        # Align well-life month 0 (history) to forecast/typecurve T_INDEX=1.
        actual_df = actual_df.copy()
        actual_df['T_INDEX'] = actual_df['T_INDEX'] + 1
        actual_df = actual_df.groupby(['UID', 'T_INDEX'], as_index=False)[['OIL', 'GAS', 'WATER']].sum()

        forecast = forecast.set_index(['UID', 'T_INDEX'])
        actual_df = actual_df.set_index(['UID', 'T_INDEX'])
        # History wins on overlap; forecast fills gaps. Restrict to forecast index.
        overlay = actual_df.reindex(forecast.index).combine_first(forecast)

        return overlay.reset_index()[['UID', 'T_INDEX', 'OIL', 'GAS', 'WATER']]

    @staticmethod
    def _tc_model_sum(qi, di, b, t0, t_arr):
        """Type-curve modeled cumulative over provided t-index points."""
        if len(t_arr) == 0:
            return 0.0
        t = np.asarray(t_arr, dtype=float)
        dt = t - float(t0)
        dt = np.where(dt < 0, 0.0, dt)
        b = float(b)
        qi = float(qi)
        di = float(di)
        if abs(b) < 1e-6:
            q = qi * np.exp(-di * dt)
        else:
            den = 1.0 + b * di * dt
            den = np.where(den > 0.0, den, np.nan)
            q = qi * np.power(den, -1.0 / b)
        return float(np.nansum(q))

    @staticmethod
    def _tc_exponential_ramp_prepeak_volume(rate_t0, peak_rate, t_start, t_peak):
        """
        Pre-peak volume assuming an exponential ramp from ``rate_t0`` at ``t_start``
        to ``peak_rate`` at ``t_peak`` (peak month excluded — that starts Arps).

        Discrete monthly rates for ``t`` in ``[t_start, t_peak)``:
        ``q(t) = rate_t0 * (peak_rate / rate_t0) ** ((t - t_start) / (t_peak - t_start))``.
        """
        rate_t0 = float(rate_t0)
        peak_rate = float(peak_rate)
        t_start = float(t_start)
        t_peak = float(t_peak)
        if not (np.isfinite(rate_t0) and np.isfinite(peak_rate) and np.isfinite(t_start) and np.isfinite(t_peak)):
            return 0.0
        if t_peak <= t_start:
            return 0.0
        if rate_t0 <= 0 or peak_rate <= 0:
            return 0.0

        # Integer month indexes covering [t_start, t_peak)
        t_months = np.arange(np.floor(t_start), np.ceil(t_peak), dtype=float)
        t_months = t_months[(t_months >= t_start - 1e-12) & (t_months < t_peak - 1e-12)]
        if len(t_months) == 0:
            return 0.0

        span = t_peak - t_start
        frac = (t_months - t_start) / span
        if np.isclose(rate_t0, peak_rate):
            q = np.full_like(t_months, rate_t0, dtype=float)
        else:
            q = rate_t0 * np.power(peak_rate / rate_t0, frac)
        return float(np.nansum(q))

    @staticmethod
    def _tc_postpeak_eur_target(t_arr, q_arr, rate_t0, peak_rate, t_peak):
        """
        Post-peak EUR target for decline matching:
        ``sum(full curve) - exponential_ramp_prepeak(rate_t0 -> peak_rate)``.
        """
        t_arr = np.asarray(t_arr, dtype=float).reshape(-1)
        q_arr = np.asarray(q_arr, dtype=float).reshape(-1)
        n = min(len(t_arr), len(q_arr))
        if n == 0:
            return 0.0
        t_arr = t_arr[:n]
        q_arr = q_arr[:n]
        total = float(np.nansum(q_arr))
        t_start = float(np.nanmin(t_arr))
        prepeak = decline_curve._tc_exponential_ramp_prepeak_volume(
            rate_t0, peak_rate, t_start, t_peak
        )
        target = total - prepeak
        if not np.isfinite(target) or target <= 0:
            # Fallback: actual post-peak volumes on the curve
            post = q_arr[t_arr >= float(t_peak) - 1e-12]
            target = float(np.nansum(post))
        return max(target, 0.0)

    def _tc_match_di_with_solver(self, qi, di_guess, b, t0, t_arr, target_sum):
        """
        Keep ``qi,b,t0`` fixed and use ``decline_solver`` to match EUR-like target by
        solving decline rate (``de``). Falls back to ``di_guess`` when solve is invalid.
        """
        qi = float(qi)
        di_guess = float(di_guess)
        b = float(b)
        target = float(target_sum)
        if not (np.isfinite(qi) and np.isfinite(di_guess) and np.isfinite(b) and np.isfinite(target)):
            return di_guess
        if qi <= 0 or di_guess <= 0 or b <= 0 or target <= 0:
            return di_guess

        t_arr = np.asarray(t_arr, dtype=float).reshape(-1)
        if len(t_arr) == 0:
            return di_guess
        # Solver integrates from t=0 to t_max with t0=0 semantics.
        t_max = max(int(np.nanmax(t_arr) - float(t0)) + 1, 12)
        Solver = _decline_solver_cls()
        s = Solver(
            qi=qi,
            qf=None,
            de=None,
            dmin=self.MIN_DECLINE_RATE,
            b=b,
            eur=target,
            t_max=t_max,
        )
        _, _, _, de_new, _, _, _ = s.solve()
        de_new = float(de_new)
        if np.isfinite(de_new) and de_new > 0:
            return de_new
        return di_guess

    @staticmethod
    def _tc_rate_at_t0_from_curve(t_arr, q_arr, t0=None):
        """
        Empirical rate on a typecurve quantile/mean series at time zero.

        ``rate_t0`` is the actual curve rate at the start of the probability
        series (minimum ``T_INDEX``), not the Arps-fitted ``t0`` and not a
        back-projected ``qi``. ``_force_t0`` only constrains the Arps fit.

        If ``t0`` is provided it is treated as an explicit lookup time (exact
        match or linear interpolation); otherwise the first chronological
        point on the curve is used.
        """
        t_arr = np.asarray(t_arr, dtype=float).reshape(-1)
        q_arr = np.asarray(q_arr, dtype=float).reshape(-1)
        if len(t_arr) == 0 or len(q_arr) == 0:
            return np.nan
        n = min(len(t_arr), len(q_arr))
        t_arr = t_arr[:n]
        q_arr = q_arr[:n]
        valid = np.isfinite(t_arr) & np.isfinite(q_arr)
        t_arr = t_arr[valid]
        q_arr = q_arr[valid]
        if len(t_arr) == 0:
            return np.nan
        order = np.argsort(t_arr)
        t_sorted = t_arr[order]
        q_sorted = q_arr[order]
        if t0 is None or (isinstance(t0, float) and not np.isfinite(t0)):
            return float(q_sorted[0])
        t0 = float(t0)
        exact = np.isclose(t_sorted, t0)
        if np.any(exact):
            return float(q_sorted[exact][0])
        if t0 < t_sorted[0] or t0 > t_sorted[-1]:
            return np.nan
        return float(np.interp(t0, t_sorted, q_sorted))

    @staticmethod
    def _tc_decline_metrics(di, b):
        """Return nominal/tangent/secant decline metrics from monthly nominal di."""
        di = float(di)
        b = float(b)
        nom_month = di
        nom_annual = di * 12.0
        tan_eff = 100.0 * (1.0 - np.exp(-nom_annual))
        if abs(b) < 1e-6:
            sec_eff = tan_eff
        else:
            sec_eff = (1.0 - np.power((nom_annual * b + 1.0), (-1.0 / b))) * 100.0
        return nom_month, nom_annual, tan_eff, sec_eff

    def _generate_typecurve_original(self, num_months, denormalize, prob_levels, _verbose, return_params):
        """Original typecurve generation using major phase with ratios"""
        tc_flow = self._build_typecurve_flowstream(denormalize)

        if self.debug_on:
            tc_flow.to_csv('outputs/test_quantiles.csv')

        # Ensure T_INDEX is a column before grouping (it may be an index)
        return_df = (
            tc_flow[['T_INDEX','OIL','GAS','WATER']]
                .groupby('T_INDEX')
                .quantile(prob_levels)
                .reset_index()
        )
        avg_df = (
            tc_flow[['T_INDEX','OIL','GAS','WATER']]
                .groupby('T_INDEX')
                .mean()
                .reset_index()
        )
        avg_df['level_1'] = 'mean'
        return_df = pd.concat([return_df,avg_df])
        
        if return_params:
            r_df = pd.DataFrame([])
            for major in ['OIL','GAS']:
                l_df = return_df.copy()
                l_df['MAJOR'] = major
                param_df = self.vect_generate_params_tc(l_df)
                param_df['rate_t0'] = np.nan
                param_df['peak_rate'] = np.nan
                param_df['time_to_peak_months'] = np.nan
                nom = param_df.apply(lambda x: self._tc_decline_metrics(x.di, x.b), axis=1)
                param_df['nominal_initial_monthly_decline'] = [x[0] for x in nom]
                param_df['nominal_annual_decline'] = [x[1] for x in nom]
                param_df['tangent_effective_decline_pct'] = [x[2] for x in nom]
                param_df['secant_effective_decline_pct'] = [x[3] for x in nom]
                param_df['phase'] = major
                param_df['probability'] = param_df['UID']
                # Match EUR-like target by adjusting decline rate via solver (keep qi fixed).
                try:
                    if 'qi' in param_df.columns and 'di' in param_df.columns and 'b' in param_df.columns and 't0' in param_df.columns and 'UID' in param_df.columns:
                        adjusted_di = []
                        q_time0 = []
                        q_peak = []
                        t_peak = []
                        p_list = []
                        for _, prow in param_df.iterrows():
                            prob = prow['UID']
                            qi = float(prow['qi'])
                            di = float(prow['di'])
                            b = float(prow['b'])
                            t0 = float(prow['t0'])
                            p_arr = np.asarray(l_df[l_df['level_1'] == prob][major].values, dtype=float)
                            t_arr = np.asarray(l_df[l_df['level_1'] == prob]['T_INDEX'].values, dtype=float)
                            # Time-zero rate on the probability curve (not fitted Arps t0).
                            rate_t0_val = self._tc_rate_at_t0_from_curve(t_arr, p_arr)
                            q_time0.append(rate_t0_val)
                            di_new = di
                            if len(p_arr) > 0:
                                i_peak = int(np.nanargmax(p_arr))
                                peak_val = float(p_arr[i_peak])
                                peak_t = float(t_arr[i_peak]) if len(t_arr) > i_peak else np.nan
                                q_peak.append(peak_val)
                                t_peak.append(peak_t)
                                post_t = t_arr[i_peak:]
                                # Full-curve EUR minus exponential pre-peak ramp (rate_t0 -> peak).
                                target = self._tc_postpeak_eur_target(
                                    t_arr, p_arr, rate_t0_val, peak_val, peak_t
                                )
                                if target > 0 and np.isfinite(qi) and qi > 0:
                                    di_new = self._tc_match_di_with_solver(
                                        qi, di, b, t0, post_t, target
                                    )
                            else:
                                q_peak.append(np.nan)
                                t_peak.append(np.nan)
                            adjusted_di.append(di_new)
                            p_list.append(prob)
                        param_df['di'] = adjusted_di
                        param_df['rate_t0'] = q_time0
                        param_df['peak_rate'] = q_peak
                        param_df['time_to_peak_months'] = t_peak
                        nom = param_df.apply(lambda x: self._tc_decline_metrics(x.di, x.b), axis=1)
                        param_df['nominal_initial_monthly_decline'] = [x[0] for x in nom]
                        param_df['nominal_annual_decline'] = [x[1] for x in nom]
                        param_df['tangent_effective_decline_pct'] = [x[2] for x in nom]
                        param_df['secant_effective_decline_pct'] = [x[3] for x in nom]
                        param_df['phase'] = major
                        param_df['probability'] = p_list
                except Exception:
                    # Non-fatal; proceed without adjustment if anything unexpected occurs
                    pass
                param_df = param_df[[
                    'rate_t0',
                    'peak_rate',
                    'time_to_peak_months',
                    'b',
                    'nominal_initial_monthly_decline',
                    'nominal_annual_decline',
                    'tangent_effective_decline_pct',
                    'secant_effective_decline_pct',
                    'phase',
                    'probability',
                    'minor_ratio',
                    'water_ratio',
                ]].rename(columns={
                    'b': 'matched_b_factor',
                })
                if r_df.empty:
                    r_df = param_df
                else:
                    r_df = pd.concat([r_df,param_df])
            self.tc_params = r_df
            
        return_df = return_df.pivot(
                index=['T_INDEX'],
                columns='level_1',
                values=['OIL','GAS','WATER']
            )

        self._typecurve = return_df

    def _generate_typecurve_three_phase(self, num_months, denormalize, prob_levels, _verbose, return_params):
        """Three-phase typecurve generation with independent decline curves for each phase"""
        tc_flow = self._build_typecurve_flowstream(denormalize)

        if self.debug_on:
            tc_flow.to_csv('outputs/test_quantiles.csv')

        # Calculate quantiles and mean for each phase independently
        # Ensure T_INDEX is a column before grouping (it may be an index)
        return_df = (
            tc_flow[['T_INDEX','OIL','GAS','WATER']]
                .groupby('T_INDEX')
                .quantile(prob_levels)
                .reset_index()
        )
        avg_df = (
            tc_flow[['T_INDEX','OIL','GAS','WATER']]
                .groupby('T_INDEX')
                .mean()
                .reset_index()
        )
        avg_df['level_1'] = 'mean'
        return_df = pd.concat([return_df,avg_df])
        
        if return_params:
            r_df = pd.DataFrame([])
            # In three-phase mode, we have independent parameters for each phase
            for phase in ['OIL','GAS','WATER']:
                l_df = return_df.copy()
                l_df['PHASE'] = phase
                param_df = self.vect_generate_params_tc_three_phase(l_df, phase)
                if len(param_df) > 0:
                    param_df['rate_t0'] = np.nan
                    param_df['peak_rate'] = np.nan
                    param_df['time_to_peak_months'] = np.nan
                    nom = param_df.apply(lambda x: self._tc_decline_metrics(x.di, x.b), axis=1)
                    param_df['nominal_initial_monthly_decline'] = [x[0] for x in nom]
                    param_df['nominal_annual_decline'] = [x[1] for x in nom]
                    param_df['tangent_effective_decline_pct'] = [x[2] for x in nom]
                    param_df['secant_effective_decline_pct'] = [x[3] for x in nom]
                    param_df['phase'] = phase
                    param_df['probability'] = param_df['UID']
                    # Match EUR-like target by adjusting decline rate via solver (keep qi fixed).
                    try:
                        if {'qi','di','b','t0','UID'}.issubset(param_df.columns):
                            adjusted_di = []
                            q_time0 = []
                            q_peak = []
                            t_peak = []
                            p_list = []
                            for _, prow in param_df.iterrows():
                                prob = prow['UID']
                                qi = float(prow['qi'])
                                di = float(prow['di'])
                                b = float(prow['b'])
                                t0 = float(prow['t0'])
                                p_arr = np.asarray(l_df[l_df['level_1'] == prob][phase].values, dtype=float)
                                t_arr = np.asarray(l_df[l_df['level_1'] == prob]['T_INDEX'].values, dtype=float)
                                # Time-zero rate on the probability curve (not fitted Arps t0).
                                rate_t0_val = self._tc_rate_at_t0_from_curve(t_arr, p_arr)
                                q_time0.append(rate_t0_val)
                                di_new = di
                                if len(p_arr) > 0:
                                    i_peak = int(np.nanargmax(p_arr))
                                    peak_val = float(p_arr[i_peak])
                                    peak_t = float(t_arr[i_peak]) if len(t_arr) > i_peak else np.nan
                                    q_peak.append(peak_val)
                                    t_peak.append(peak_t)
                                    post_t = t_arr[i_peak:]
                                    # Full-curve EUR minus exponential pre-peak ramp (rate_t0 -> peak).
                                    target = self._tc_postpeak_eur_target(
                                        t_arr, p_arr, rate_t0_val, peak_val, peak_t
                                    )
                                    if target > 0 and np.isfinite(qi) and qi > 0:
                                        di_new = self._tc_match_di_with_solver(
                                            qi, di, b, t0, post_t, target
                                        )
                                else:
                                    q_peak.append(np.nan)
                                    t_peak.append(np.nan)
                                adjusted_di.append(di_new)
                                p_list.append(prob)
                            param_df['di'] = adjusted_di
                            param_df['rate_t0'] = q_time0
                            param_df['peak_rate'] = q_peak
                            param_df['time_to_peak_months'] = t_peak
                            nom = param_df.apply(lambda x: self._tc_decline_metrics(x.di, x.b), axis=1)
                            param_df['nominal_initial_monthly_decline'] = [x[0] for x in nom]
                            param_df['nominal_annual_decline'] = [x[1] for x in nom]
                            param_df['tangent_effective_decline_pct'] = [x[2] for x in nom]
                            param_df['secant_effective_decline_pct'] = [x[3] for x in nom]
                            param_df['phase'] = phase
                            param_df['probability'] = p_list
                    except Exception:
                        pass
                    param_df = param_df[[
                        'rate_t0',
                        'peak_rate',
                        'time_to_peak_months',
                        'b',
                        'nominal_initial_monthly_decline',
                        'nominal_annual_decline',
                        'tangent_effective_decline_pct',
                        'secant_effective_decline_pct',
                        'phase',
                        'probability',
                    ]].rename(columns={
                        'b': 'matched_b_factor',
                    })
                    if r_df.empty:
                        r_df = param_df
                    else:
                        r_df = pd.concat([r_df,param_df])
            self.tc_params = r_df
            
        return_df = return_df.pivot(
                index=['T_INDEX'],
                columns='level_1',
                values=['OIL','GAS','WATER']
            )

        self._typecurve = return_df

    def vect_generate_params_tc_three_phase(self, param_df, phase):
        """Generate parameters for typecurve in three-phase mode"""
        self._force_t0 = True

        param_df['HOLE_DIRECTION'] = "H"
        param_df = param_df[param_df['T_INDEX']<60]
        param_df = param_df.rename(columns={
            'OIL':'NORMALIZED_OIL',
            'GAS':"NORMALIZED_GAS",
            'WATER':'NORMALIZED_WATER',
            'level_1':'UID'
        })
        param_df = param_df.sort_values(['UID', 'T_INDEX'])

        # Create a temporary dataframe for this phase
        temp_df = param_df[[
            'UID',
            'HOLE_DIRECTION',
            'T_INDEX',
            f'NORMALIZED_{phase}'
        ]].copy()
        
        # Add a MAJOR column for this phase
        temp_df['MAJOR'] = phase
        
        # Add dummy columns for other phases (set to 0)
        for other_phase in ['OIL', 'GAS', 'WATER']:
            if other_phase != phase:
                temp_df[f'NORMALIZED_{other_phase}'] = 0

        imploded_df = temp_df.groupby([
            'UID',
            'MAJOR',
            'HOLE_DIRECTION'
        ]).agg({
            'T_INDEX': lambda x: x.tolist(),
            'NORMALIZED_OIL': lambda x: x.tolist(),
            'NORMALIZED_GAS': lambda x: x.tolist(),
            'NORMALIZED_WATER': lambda x: x.tolist()
        }).reset_index()

        imploded_df = imploded_df.apply(self.dca_params, axis=1)
        
        imploded_df = imploded_df[[
            'UID',
            'MAJOR',
            'q0',
            'qi',
            'di',
            'b',
            't0'
        ]].rename(columns={
            'MAJOR':'phase'
        })

        self._force_t0 = False

        return imploded_df

    def month_diff(self, a, b):
        """Calculate month difference between two datetime series."""
        return 12 * (a.dt.year - b.dt.year) + (a.dt.month - b.dt.month)

    @staticmethod
    def _arps_rate_from_tau(qi, di, b, tau):
        """Arps rate at elapsed months ``tau = t - t0``."""
        qi = float(qi)
        di = float(di)
        b = float(b)
        tau = float(tau)
        if not np.isfinite(qi) or not np.isfinite(di) or not np.isfinite(b):
            return np.nan
        if qi <= 0 or di <= 0 or b <= 0:
            return np.nan
        den = 1.0 + b * di * tau
        if den <= 0:
            return np.nan
        return float(qi / np.power(den, 1.0 / b))

    @staticmethod
    def _phase_base_qi_from_row(row):
        """Best available base qi for export rows by phase (with ratio fallbacks)."""
        phase = str(row.get("MAJOR", "")).upper()
        if phase == "OIL":
            return float(row.get("IPO", 0.0))
        if phase == "GAS":
            q = float(row.get("IPG", 0.0))
            if q > 0:
                return q
            oil_q = float(row.get("IPO", 0.0))
            return oil_q * float(row.get("MINOR_RATIO", 0.0))
        if phase == "WATER":
            q = float(row.get("IPW", 0.0))
            if q > 0:
                return q
            oil_q = float(row.get("IPO", 0.0))
            return oil_q * float(row.get("WATER_RATIO", 0.0))
        return 0.0

    def _export_rate_at_tau(self, row, tau):
        """Forecast rate at elapsed months tau from fitted parameters."""
        qi0 = self._phase_base_qi_from_row(row)
        de = float(row.get("DE", 0.0))
        b = float(row.get("B", 0.0))
        q = self._arps_rate_from_tau(qi0, de, b, float(tau))
        if np.isfinite(q) and q > 0:
            return float(q)
        return max(qi0, 0.0)

    def _adjust_default_fit_to_recent_l3m(self, qi, di, b, t0, x_vals, y_vals):
        """
        Adjust default-fit ``(qi, di)`` to recent production behavior at fixed ``(b, t0)``.

        Rules:
        - L3M actual <= fitted q at last t: bulk shift (scale qi only).
        - L3M actual > fitted q at last t and b < 0.1: bulk shift.
        - L3M actual > fitted q at last t and b >= 0.1:
          solve qi/di so q(last_t)=L3M actual and q(2*last_t - t0)=base q at same t.
        """
        qi0 = float(qi)
        di0 = float(di)
        b0 = float(b)
        t0 = float(t0)
        x = np.asarray(x_vals, dtype=float).reshape(-1)
        y = np.asarray(y_vals, dtype=float).reshape(-1)

        if len(x) == 0 or len(y) == 0:
            return qi0, di0
        if not (np.isfinite(qi0) and np.isfinite(di0) and np.isfinite(b0) and np.isfinite(t0)):
            return qi0, di0
        if qi0 <= 0 or di0 <= 0 or b0 <= 0:
            return qi0, di0

        tail = y[np.isfinite(y)][-3:]
        if len(tail) == 0:
            return qi0, di0
        q_actual = float(np.mean(tail))
        if not np.isfinite(q_actual) or q_actual <= 0:
            return qi0, di0

        tau1 = float(x[-1] - t0)
        if not np.isfinite(tau1) or tau1 <= 0:
            return qi0, di0
        q_forecast_tau1 = self._arps_rate_from_tau(qi0, di0, b0, tau1)
        if not np.isfinite(q_forecast_tau1) or q_forecast_tau1 <= 0:
            return qi0, di0

        # Bulk-shift path: preserve decline shape, scale qi to hit L3M target now.
        scale = q_actual / q_forecast_tau1
        qi_bulk = qi0 * scale if np.isfinite(scale) and scale > 0 else qi0
        di_bulk = di0

        if q_actual <= q_forecast_tau1:
            self._incr_legacy_adjustment(DCA_LEGACY_ADJ_BULK_DOWNSIDE)
            return float(qi_bulk), float(di_bulk)
        if b0 < 0.1:
            self._incr_legacy_adjustment(DCA_LEGACY_ADJ_BULK_LOW_B)
            return float(qi_bulk), float(di_bulk)

        tau2 = 2.0 * tau1
        q_base_tau2 = self._arps_rate_from_tau(qi0, di0, b0, tau2)
        if not np.isfinite(q_base_tau2) or q_base_tau2 <= 0:
            self._incr_legacy_adjustment(DCA_LEGACY_ADJ_BULK_FALLBACK)
            return float(qi_bulk), float(di_bulk)

        ratio = q_actual / q_base_tau2
        if not np.isfinite(ratio) or ratio <= 0:
            self._incr_legacy_adjustment(DCA_LEGACY_ADJ_BULK_FALLBACK)
            return float(qi_bulk), float(di_bulk)
        # Let R = (q(tau1)/q(tau2))^b.
        # Then R = (1 + b*di*tau2) / (1 + b*di*tau1), so:
        # di = (1 - R) / (b * (R*tau1 - tau2)).
        R = np.power(ratio, b0)
        num = 1.0 - R
        den = b0 * (R * tau1 - tau2)
        if not np.isfinite(den) or abs(den) <= 1e-12:
            self._incr_legacy_adjustment(DCA_LEGACY_ADJ_BULK_FALLBACK)
            return float(qi_bulk), float(di_bulk)

        di1 = num / den
        den_tau1 = 1.0 + b0 * di1 * tau1
        if not np.isfinite(di1) or di1 <= 0 or den_tau1 <= 0:
            self._incr_legacy_adjustment(DCA_LEGACY_ADJ_BULK_FALLBACK)
            return float(qi_bulk), float(di_bulk)

        qi1 = q_actual * np.power(den_tau1, 1.0 / b0)
        if not np.isfinite(qi1) or qi1 <= 0:
            self._incr_legacy_adjustment(DCA_LEGACY_ADJ_BULK_FALLBACK)
            return float(qi_bulk), float(di_bulk)
        self._incr_legacy_adjustment(DCA_LEGACY_ADJ_SOLVED_UPSIDE)
        return float(qi1), float(di1)

    # Backward-compatible internal alias.
    def _adjust_legacy_fit_to_recent_l3m(self, qi, di, b, t0, x_vals, y_vals):
        return self._adjust_default_fit_to_recent_l3m(qi, di, b, t0, x_vals, y_vals)

    def qi_overwrite(self):
        """
        Calculate 3-month average production rates for initial rate estimation.
        
        This function calculates the average production rates over the last 3 months
        for each well, which can be used to overwrite or validate initial rates.
        Uses the production data already loaded into the decline_curve object.
        
        Returns:
            DataFrame: Contains UID, L3M_OIL, L3M_GAS, L3M_WATER, L3M_START
        """
        if self._dataframe is None:
            raise ValueError("No production data loaded. Set dataframe first.")
            
        # Sort by well and date (descending)
        production_df = self._dataframe.sort_values(by=[self._uid_col, self._date_col], ascending=[True, False])
        
        # Group by well and take the first 3 rows for each group
        top_three_dates = production_df.groupby(self._uid_col).head(3).reset_index()
        
        # Calculate the average value for each well
        result = top_three_dates[[self._uid_col, self._oil_col, self._gas_col, self._water_col, self._date_col]].groupby(self._uid_col).agg({
            self._oil_col: 'mean',
            self._gas_col: 'mean',
            self._water_col: 'mean',
            self._date_col: 'max'
        }).reset_index()
        
        result = result.rename(columns={
            self._uid_col: 'UID',
            self._oil_col: 'L3M_OIL',
            self._gas_col: 'L3M_GAS',
            self._water_col: 'L3M_WATER',
            self._date_col: 'L3M_START'
        })
        
        return result

    def aries_eco_gen(self, oneline_df=None, file_path="outputs/eco_output.txt", scenario="RSC425", dmin=6, write_water=False):
        """
        Generate ARIES-compatible economic forecast file.
        
        This function creates a text file in ARIES format containing production forecasts
        for economic analysis in the ARIES software.
        
        Args:
            oneline_df: Oneline results dataframe (uses self._oneline if None)
            file_path: Output file path
            scenario: Scenario name for ARIES
            dmin: Minimum decline rate
            write_water: Whether to include water production
        """
        if oneline_df is None:
            if self._oneline.empty:
                raise ValueError("No oneline data available. Run generate_oneline() first.")
            oneline_df = self._oneline.copy()
        
        oneline_df = oneline_df.fillna(0)
        
        # Ensure required columns exist and add defaults for missing ones
        # Use T0_DATE if available, otherwise T0, otherwise default
        if 'T0_DATE' in oneline_df.columns:
            oneline_df['T0'] = oneline_df['T0_DATE']
        elif 'T0' not in oneline_df.columns:
            oneline_df['T0'] = pd.Timestamp('2020-01-01')
        if 'DE' not in oneline_df.columns:
            oneline_df['DE'] = 0.1
        if 'B' not in oneline_df.columns:
            oneline_df['B'] = 1.0
        if 'MINOR_RATIO' not in oneline_df.columns:
            oneline_df['MINOR_RATIO'] = 0.0
        if 'WATER_RATIO' not in oneline_df.columns:
            oneline_df['WATER_RATIO'] = 0.0
        if 'L3M_START' not in oneline_df.columns:
            oneline_df['L3M_START'] = pd.Timestamp('2023-12-01')
        if 'L3M_OIL' not in oneline_df.columns:
            oneline_df['L3M_OIL'] = 0.0
        if 'L3M_GAS' not in oneline_df.columns:
            oneline_df['L3M_GAS'] = 0.0
        
        # Calculate revised parameters
        oneline_df['T0'] = pd.to_datetime(oneline_df['T0'])
        oneline_df['revised_dt'] = self.month_diff(oneline_df['L3M_START'], oneline_df['T0'])
        oneline_df['revised_ai'] = oneline_df.apply(lambda x: x['DE']/(1+x['B']*x['DE']*x['revised_dt']), axis=1)
        oneline_df['revised_aries_de'] = oneline_df.apply(lambda x: (1-np.power(((x['revised_ai']*12)*x['B']+1),(-1/x['B'])))*100, axis=1)
        oneline_df['forecast_major_rate'] = oneline_df.apply(
            lambda r: self._export_rate_at_tau(r, r['revised_dt']), axis=1
        )
        
        # Create output directory if it doesn't exist
        import os
        output_dir = os.path.dirname(file_path)
        if output_dir:  # Only create directory if there is a path
            os.makedirs(output_dir, exist_ok=True)
        
        with open(file_path, "w") as file:
            for index, row in oneline_df.iterrows():
                # Handle both standard mode (MAJOR column) and three-phase mode (phase column)
                major_phase = row.get('MAJOR', row.get('phase', None))
                if major_phase in ['OIL','GAS'] and row['L3M_START'].year > 2020:
                    propnum = str(row['UID']).ljust(93)
                    production = " PRODUCTION".ljust(93)
                    start = "  START".ljust(13) + row['L3M_START'].strftime('%m/%Y')
                    start_padding = " " * (93 - len(start) - len(scenario))
                    start_line = start+start_padding+scenario
                    
                    if major_phase == 'OIL':
                        major_val = round(row['forecast_major_rate'],0)
                        major_units = "B/M"
                        minor = "  GAS/OIL".ljust(13) + f"{round(row['MINOR_RATIO'],3)} X M/B TO LIFE LIN TIME"
                        water = "  WTR/OIL".ljust(13) + f"{round(row['WATER_RATIO'],3)} X B/B TO LIFE LIN TIME"
                    else:
                        major_val = round(row['forecast_major_rate'],0)
                        major_units = "M/M"
                        minor = "  OIL/GAS".ljust(13) + f"{round(row['MINOR_RATIO'],3)} X B/M TO LIFE LIN TIME"
                        water = "  WTR/GAS".ljust(13) + f"{round(row['WATER_RATIO'],3)} X B/M TO LIFE LIN TIME"
                    
                    # Determine major line based on conditions
                    if row['B']>.01 and row['revised_aries_de'] > dmin and major_val>0:
                        major = f"  {major_phase} ".ljust(13)+f"{major_val} X {major_units} {dmin} EXP B/{round(row['B'],2)} {round(row['revised_aries_de'],2)}"
                        major_padding = " " * (93 - len(major) - len(scenario))
                        major_line = major+major_padding+scenario
                        major_cnt = f'  "'.ljust(13)+f"X X {major_units} 99 YRS EXP {dmin}"
                        major_cnt_padding = " " * (93 - len(major_cnt) - len(scenario))
                        major_cnt_line = major_cnt+major_cnt_padding+scenario
                        
                    elif major_val>0 and row['revised_aries_de'] > dmin:
                        major = f"  {major_phase} ".ljust(13)+f"{major_val} X {major_units} 99 YRS EXP {round(row['revised_aries_de'],2)}"
                        major_padding = " " * (93 - len(major) - len(scenario))
                        major_line = major+major_padding+scenario
                        major_cnt_line = None

                    elif major_val > 0:
                        major = f"  {major_phase} ".ljust(13)+f"{major_val} X {major_units} 99 YRS EXP {dmin}"
                        major_padding = " " * (93 - len(major) - len(scenario))
                        major_line = major+major_padding+scenario
                        major_cnt_line = None

                    else:
                        major = f"  {major_phase} ".ljust(13)+f"{major_val} X {major_units} 1 YRS FLAT 0"
                        major_padding = " " * (93 - len(major) - len(scenario))
                        major_line = major+major_padding+scenario
                        major_cnt_line = None

                    minor_padding = " " * (93 - len(minor) - len(scenario))
                    minor_line = minor+minor_padding+scenario

                    water_padding = " " * (93 - len(water) - len(scenario))
                    water_line = water+water_padding+scenario

                    file.write(propnum + "\n")
                    file.write(production + "\n")
                    file.write(start_line + "\n")
                    file.write(major_line + "\n")
                    if major_cnt_line:
                        file.write(major_cnt_line + "\n")
                    if write_water:
                        file.write(water_line + "\n")

    def aries_eco_gen_three_phase(self, oneline_df=None, file_path="outputs/eco_output.txt", scenario="RSC425", dmin=6, write_water=False):
        """
        Generate ARIES-compatible economic forecast file for three-phase mode.
        
        This function creates a text file in ARIES format containing production forecasts
        for all three phases (OIL, GAS, WATER) with independent decline curves.
        
        Args:
            oneline_df: Oneline results dataframe with phase-specific columns
            file_path: Output file path
            scenario: Scenario name for ARIES
            dmin: Minimum decline rate
            write_water: Whether to include water production
        """
        if oneline_df is None:
            if self._oneline.empty:
                raise ValueError("No oneline data available. Run generate_oneline() first.")
            oneline_df = self._oneline.copy()
        
        oneline_df = oneline_df.fillna(0)
        
        # Ensure required columns exist
        if 'T0_DATE' in oneline_df.columns:
            oneline_df['T0'] = oneline_df['T0_DATE']
        elif 'T0' not in oneline_df.columns:
            oneline_df['T0'] = pd.Timestamp('2020-01-01')
        
        # Calculate revised parameters for each phase
        oneline_df['T0'] = pd.to_datetime(oneline_df['T0'])
        oneline_df['revised_dt'] = self.month_diff(oneline_df['L3M_START'], oneline_df['T0'])
        
        # Calculate revised decline rates for each phase
        oneline_df['OIL_revised_ai'] = oneline_df.apply(lambda x: x['OIL_DI']/(1+x['OIL_B']*x['OIL_DI']*x['revised_dt']) if x['OIL_QI'] > 0 else 0, axis=1)
        oneline_df['OIL_revised_aries_de'] = oneline_df.apply(lambda x: (1-np.power(((x['OIL_revised_ai']*12)*x['OIL_B']+1),(-1/x['OIL_B'])))*100 if x['OIL_QI'] > 0 else 0, axis=1)
        
        oneline_df['GAS_revised_ai'] = oneline_df.apply(lambda x: x['GAS_DI']/(1+x['GAS_B']*x['GAS_DI']*x['revised_dt']) if x['GAS_QI'] > 0 else 0, axis=1)
        oneline_df['GAS_revised_aries_de'] = oneline_df.apply(lambda x: (1-np.power(((x['GAS_revised_ai']*12)*x['GAS_B']+1),(-1/x['GAS_B'])))*100 if x['GAS_QI'] > 0 else 0, axis=1)
        
        oneline_df['WATER_revised_ai'] = oneline_df.apply(lambda x: x['WATER_DI']/(1+x['WATER_B']*x['WATER_DI']*x['revised_dt']) if x['WATER_QI'] > 0 else 0, axis=1)
        oneline_df['WATER_revised_aries_de'] = oneline_df.apply(lambda x: (1-np.power(((x['WATER_revised_ai']*12)*x['WATER_B']+1),(-1/x['WATER_B'])))*100 if x['WATER_QI'] > 0 else 0, axis=1)
        
        # Create output directory if it doesn't exist
        import os
        output_dir = os.path.dirname(file_path)
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
        
        with open(file_path, "w") as file:
            for index, row in oneline_df.iterrows():
                # Write well header
                propnum = str(row['UID']).ljust(93)
                production = " PRODUCTION".ljust(93)
                start = "  START".ljust(13) + row['L3M_START'].strftime('%m/%Y')
                start_padding = " " * (93 - len(start) - len(scenario))
                start_line = start + start_padding + scenario
                
                file.write(propnum + "\n")
                file.write(production + "\n")
                file.write(start_line + "\n")
                
                # Write OIL phase if it exists
                if row['OIL_QI'] > 0:
                    oil_val = round(row['L3M_OIL'], 0)
                    
                    # Determine oil line based on conditions (matching ratio forecast logic)
                    if row['OIL_B'] > 0.05 and round(row['OIL_revised_aries_de'], 2) > dmin and oil_val > 0:
                        oil_line = f"  OIL        {oil_val} X B/M {dmin} EXP B/{round(row['OIL_B'], 2)} {round(row['OIL_revised_aries_de'], 2)}"
                        oil_padding = " " * (93 - len(oil_line) - len(scenario))
                        file.write(oil_line + oil_padding + scenario + "\n")
                        
                        # Write continuation line for oil
                        oil_cnt = f'  "          X X B/M 99 YRS EXP {dmin}'
                        oil_cnt_padding = " " * (93 - len(oil_cnt) - len(scenario))
                        file.write(oil_cnt + oil_cnt_padding + scenario + "\n")
                        
                    elif oil_val > 0 and round(row['OIL_revised_aries_de'], 2) > dmin:
                        oil_line = f"  OIL        {oil_val} X B/M 99 YRS EXP {round(row['OIL_revised_aries_de'], 2)}"
                        oil_padding = " " * (93 - len(oil_line) - len(scenario))
                        file.write(oil_line + oil_padding + scenario + "\n")
                        
                    elif oil_val > 0:
                        oil_line = f"  OIL        {oil_val} X B/M 99 YRS EXP {dmin}"
                        oil_padding = " " * (93 - len(oil_line) - len(scenario))
                        file.write(oil_line + oil_padding + scenario + "\n")
                        
                    else:
                        oil_line = f"  OIL        {oil_val} X B/M 1 YRS FLAT 0"
                        oil_padding = " " * (93 - len(oil_line) - len(scenario))
                        file.write(oil_line + oil_padding + scenario + "\n")
                
                # Write GAS phase if it exists
                if row['GAS_QI'] > 0:
                    gas_val = round(row['L3M_GAS'], 0)
                    
                    # Determine gas line based on conditions (matching ratio forecast logic)
                    if row['GAS_B'] > 0.05 and round(row['GAS_revised_aries_de'], 2) > dmin and gas_val > 0:
                        gas_line = f"  GAS        {gas_val} X M/M {dmin} EXP B/{round(row['GAS_B'], 2)} {round(row['GAS_revised_aries_de'], 2)}"
                        gas_padding = " " * (93 - len(gas_line) - len(scenario))
                        file.write(gas_line + gas_padding + scenario + "\n")
                        
                        # Write continuation line for gas
                        gas_cnt = f'  "          X X M/M 99 YRS EXP {dmin}'
                        gas_cnt_padding = " " * (93 - len(gas_cnt) - len(scenario))
                        file.write(gas_cnt + gas_cnt_padding + scenario + "\n")
                        
                    elif gas_val > 0 and round(row['GAS_revised_aries_de'], 2) > dmin:
                        gas_line = f"  GAS        {gas_val} X M/M 99 YRS EXP {round(row['GAS_revised_aries_de'], 2)}"
                        gas_padding = " " * (93 - len(gas_line) - len(scenario))
                        file.write(gas_line + gas_padding + scenario + "\n")
                        
                    elif gas_val > 0:
                        gas_line = f"  GAS        {gas_val} X M/M 99 YRS EXP {dmin}"
                        gas_padding = " " * (93 - len(gas_line) - len(scenario))
                        file.write(gas_line + gas_padding + scenario + "\n")
                        
                    else:
                        gas_line = f"  GAS        {gas_val} X M/M 1 YRS FLAT 0"
                        gas_padding = " " * (93 - len(gas_line) - len(scenario))
                        file.write(gas_line + gas_padding + scenario + "\n")
                
                # Write WATER phase if it exists and write_water is True
                if write_water and row['WATER_QI'] > 0:
                    water_val = round(row['L3M_WATER'], 0)
                    
                    # Determine water line based on conditions (matching ratio forecast logic)
                    if row['WATER_B'] > 0.05 and round(row['WATER_revised_aries_de'], 2) > dmin and water_val > 0:
                        water_line = f"  WTR        {water_val} X M/M {dmin} EXP B/{round(row['WATER_B'], 2)} {round(row['WATER_revised_aries_de'], 2)}"
                        water_padding = " " * (93 - len(water_line) - len(scenario))
                        file.write(water_line + water_padding + scenario + "\n")
                        
                        # Write continuation line for water
                        water_cnt = f'  "          X X M/M 99 YRS EXP {dmin}'
                        water_cnt_padding = " " * (93 - len(water_cnt) - len(scenario))
                        file.write(water_cnt + water_cnt_padding + scenario + "\n")
                        
                    elif water_val > 0 and round(row['WATER_revised_aries_de'], 2) > dmin:
                        water_line = f"  WTR        {water_val} X M/M 99 YRS EXP {round(row['WATER_revised_aries_de'], 2)}"
                        water_padding = " " * (93 - len(water_line) - len(scenario))
                        file.write(water_line + water_padding + scenario + "\n")
                        
                    elif water_val > 0:
                        water_line = f"  WTR        {water_val} X M/M 99 YRS EXP {dmin}"
                        water_padding = " " * (93 - len(water_line) - len(scenario))
                        file.write(water_line + water_padding + scenario + "\n")
                        
                    else:
                        water_line = f"  WTR        {water_val} X M/M 1 YRS FLAT 0"
                        water_padding = " " * (93 - len(water_line) - len(scenario))
                        file.write(water_line + water_padding + scenario + "\n")

    def generate_aries_export(self, file_path="outputs/eco_output.txt", scenario="RSC425", dmin=6, write_water=False):
        """
        Generate ARIES export with integrated DCA analysis.
        
        This method combines DCA analysis with ARIES export generation.
        When three_phase_mode is enabled, it uses the existing three-phase analysis.
        Otherwise, it creates separate analyses for each phase.
        
        Args:
            file_path: Output file path
            scenario: Scenario name for ARIES
            dmin: Minimum decline rate
            write_water: Whether to include water production
        """
        # Run DCA if not already done
        if self._params_dataframe.empty:
            self.run_DCA()
        
        # Generate oneline if not already done
        if self._oneline.empty:
            self.generate_oneline(denormalize=True)
        
        # Calculate 3-month averages
        l3m_df = self.qi_overwrite()
        
        if self.three_phase_mode:
            # Use existing three-phase analysis
            # The oneline data has separate columns for each phase: IPO/DO/BO, IPG/DG/BG, IPW/DW/BW
            # For ARIES, we need to create a single row per well with all phase data
            # and use the independent decline curves instead of ratios
            
            oneline_with_l3m = self._oneline.merge(l3m_df, left_on='UID', right_on='UID', how='left')
            
            # Create one row per well with all phase information
            well_rows = []
            for _, row in oneline_with_l3m.iterrows():
                well_row = row.copy()
                
                # Add phase-specific decline parameters
                well_row['OIL_QI'] = row['IPO'] if row['IPO'] > 0 else 0
                well_row['OIL_DI'] = row['DO'] if row['IPO'] > 0 else 0
                well_row['OIL_B'] = row['BO'] if row['IPO'] > 0 else 0
                well_row['OIL_ARIES_DE'] = row['ARIES_DO'] if row['IPO'] > 0 else 0
                
                well_row['GAS_QI'] = row['IPG'] if row['IPG'] > 0 else 0
                well_row['GAS_DI'] = row['DG'] if row['IPG'] > 0 else 0
                well_row['GAS_B'] = row['BG'] if row['IPG'] > 0 else 0
                well_row['GAS_ARIES_DE'] = row['ARIES_DG'] if row['IPG'] > 0 else 0
                
                well_row['WATER_QI'] = row['IPW'] if row['IPW'] > 0 else 0
                well_row['WATER_DI'] = row['DW'] if row['IPW'] > 0 else 0
                well_row['WATER_B'] = row['BW'] if row['IPW'] > 0 else 0
                well_row['WATER_ARIES_DE'] = row['ARIES_DW'] if row['IPW'] > 0 else 0
                
                # Set MAJOR to OIL for compatibility (will be overridden in aries_eco_gen)
                well_row['MAJOR'] = 'OIL'
                
                well_rows.append(well_row)
            
            if well_rows:
                well_df = pd.DataFrame(well_rows)
                # Call aries_eco_gen with three_phase_mode flag
                self.aries_eco_gen_three_phase(well_df, file_path, scenario, dmin, write_water)
            else:
                # Fallback if no valid rows
                logger.warning("No valid phase data found for ARIES export")
                self.aries_eco_gen(oneline_with_l3m, file_path, scenario, dmin, write_water)
        else:
            # Use existing oneline data with ratios (ratio mode)
            # The oneline data already has MINOR_RATIO and WATER_RATIO calculated
            # We just need to use these ratios to calculate gas and water production
            
            oneline_with_l3m = self._oneline.merge(l3m_df, left_on='UID', right_on='UID', how='left')
            
            # Create one row per well with all phase information using ratios
            well_rows = []
            for _, row in oneline_with_l3m.iterrows():
                well_row = row.copy()
                
                # Primary phase (OIL) - use existing data
                well_row['OIL_QI'] = row['IPO'] if row['IPO'] > 0 else 0
                well_row['OIL_DI'] = row['DE'] if row['IPO'] > 0 else 0  # Use DE for ratio mode
                well_row['OIL_B'] = row['B'] if row['IPO'] > 0 else 0    # Use B for ratio mode
                well_row['OIL_ARIES_DE'] = row['ARIES_DE'] if row['IPO'] > 0 else 0  # Use ARIES_DE for ratio mode
                
                # Gas phase - calculate using MINOR_RATIO
                if row['MINOR_RATIO'] > 0 and row['IPO'] > 0:
                    well_row['GAS_QI'] = row['IPO'] * row['MINOR_RATIO']
                    well_row['GAS_DI'] = row['DE']  # Use same decline as oil
                    well_row['GAS_B'] = row['B']   # Use same b-factor as oil
                    well_row['GAS_ARIES_DE'] = row['ARIES_DE']  # Use same ARIES decline as oil
                else:
                    well_row['GAS_QI'] = 0
                    well_row['GAS_DI'] = 0
                    well_row['GAS_B'] = 0
                    well_row['GAS_ARIES_DE'] = 0
                
                # Water phase - calculate using WATER_RATIO
                if row['WATER_RATIO'] > 0 and row['IPO'] > 0:
                    well_row['WATER_QI'] = row['IPO'] * row['WATER_RATIO']
                    well_row['WATER_DI'] = row['DE']  # Use same decline as oil
                    well_row['WATER_B'] = row['B']   # Use same b-factor as oil
                    well_row['WATER_ARIES_DE'] = row['ARIES_DE']  # Use same ARIES decline as oil
                else:
                    well_row['WATER_QI'] = 0
                    well_row['WATER_DI'] = 0
                    well_row['WATER_B'] = 0
                    well_row['WATER_ARIES_DE'] = 0
                
                # Set MAJOR to OIL for compatibility
                well_row['MAJOR'] = 'OIL'
                
                well_rows.append(well_row)
            
            if well_rows:
                well_df = pd.DataFrame(well_rows)
                # Call aries_eco_gen_three_phase to format with independent decline curves
                self.aries_eco_gen_three_phase(well_df, file_path, scenario, dmin, write_water)
            else:
                # Fallback if no valid rows
                logger.warning("No valid phase data found for ARIES export")
                self.aries_eco_gen(oneline_with_l3m, file_path, scenario, dmin, write_water)
        
        # Note: This function writes to file and does not return a DataFrame

    def generate_mosaic_export(self, file_path="outputs/mosaic_export.xlsx", reserve_category="USON ARO", dmin=8):
        """
        Generate Mosaic-compatible export with integrated DCA analysis.
        
        This method creates a comprehensive export for Mosaic software including
        all phases (OIL, GAS, WATER) with proper formatting and calculations.
        When three_phase_mode is enabled, it uses the existing three-phase analysis.
        Otherwise, it creates separate analyses for each phase.
        
        Args:
            file_path: Output file path (Excel format)
            reserve_category: Reserve category for Mosaic
            dmin: Minimum decline rate
        """
        # Run DCA if not already done
        if self._params_dataframe.empty:
            self.run_DCA()
        
        # Generate oneline if not already done
        if self._oneline.empty:
            self.generate_oneline(denormalize=True)
        
        # Calculate 3-month averages
        l3m_df = self.qi_overwrite()
        
        if self.three_phase_mode:
            # Use existing three-phase analysis
            # The oneline data has separate columns for each phase: IPO/DO/BO, IPG/DG/BG, IPW/DW/BW
            # We need to create separate rows for each phase to match the expected format
            
            # Start with the base oneline data
            base_df = self._oneline.merge(l3m_df, left_on='UID', right_on='UID', how='left')
            
            # Create separate rows for each phase
            combined_rows = []
            for _, row in base_df.iterrows():
                # OIL phase
                if row['IPO'] > 0:
                    oil_row = row.copy()
                    oil_row['MAJOR'] = 'OIL'
                    oil_row['DE'] = row['DO']
                    oil_row['B'] = row['BO']
                    oil_row['T0'] = row['T0_DATE']
                    combined_rows.append(oil_row)
                
                # GAS phase
                if row['IPG'] > 0:
                    gas_row = row.copy()
                    gas_row['MAJOR'] = 'GAS'
                    gas_row['DE'] = row['DG']
                    gas_row['B'] = row['BG']
                    gas_row['T0'] = row['T0_DATE']
                    combined_rows.append(gas_row)
                
                # WATER phase
                if row['IPW'] > 0:
                    water_row = row.copy()
                    water_row['MAJOR'] = 'WATER'
                    water_row['DE'] = row['DW']
                    water_row['B'] = row['BW']
                    water_row['T0'] = row['T0_DATE']
                    combined_rows.append(water_row)
            
            if combined_rows:
                combined_df = pd.DataFrame(combined_rows)
            else:
                # Fallback if no valid rows
                combined_df = base_df.copy()
                combined_df['MAJOR'] = 'OIL'  # Default
                combined_df['DE'] = 0.1
                combined_df['B'] = 1.0
                combined_df['T0'] = combined_df['T0_DATE']
        else:
            # Use existing oneline data with ratios (ratio mode)
            # The oneline data already has MINOR_RATIO and WATER_RATIO calculated
            # We just need to use these ratios to calculate gas and water production
            
            oneline_with_l3m = self._oneline.merge(l3m_df, left_on='UID', right_on='UID', how='left')
            
            # Create separate rows for each phase using ratios
            combined_rows = []
            for _, row in oneline_with_l3m.iterrows():
                # OIL phase - use existing data
                if row['IPO'] > 0:
                    oil_row = row.copy()
                    oil_row['MAJOR'] = 'OIL'
                    oil_row['DE'] = row['DE']  # Use DE for ratio mode
                    oil_row['B'] = row['B']    # Use B for ratio mode
                    oil_row['T0'] = row['T0_DATE']
                    oil_row['L3M_OIL'] = row['L3M_OIL']
                    combined_rows.append(oil_row)
                
                # GAS phase - calculate using MINOR_RATIO
                if row['MINOR_RATIO'] > 0 and row['IPO'] > 0:
                    gas_row = row.copy()
                    gas_row['MAJOR'] = 'GAS'
                    gas_row['DE'] = row['DE']  # Use same decline as oil
                    gas_row['B'] = row['B']   # Use same b-factor as oil
                    gas_row['T0'] = row['T0_DATE']
                    gas_row['L3M_GAS'] = row['L3M_OIL'] * row['MINOR_RATIO']  # Calculate gas rate using ratio
                    combined_rows.append(gas_row)
                
                # WATER phase - calculate using WATER_RATIO
                if row['WATER_RATIO'] > 0 and row['IPO'] > 0:
                    water_row = row.copy()
                    water_row['MAJOR'] = 'WATER'
                    water_row['DE'] = row['DE']  # Use same decline as oil
                    water_row['B'] = row['B']   # Use same b-factor as oil
                    water_row['T0'] = row['T0_DATE']
                    water_row['L3M_WATER'] = row['L3M_OIL'] * row['WATER_RATIO']  # Calculate water rate using ratio
                    combined_rows.append(water_row)
            
            if combined_rows:
                combined_df = pd.DataFrame(combined_rows)
            else:
                # Fallback if no valid rows
                logger.warning("No valid phase data found for Mosaic export")
                combined_df = oneline_with_l3m.copy()
                combined_df['MAJOR'] = 'OIL'  # Default
                combined_df['DE'] = 0.1
                combined_df['B'] = 1.0
                combined_df['T0'] = combined_df['T0_DATE']
        
        # Calculate revised parameters
        combined_df = combined_df.fillna(0)
        
        # Ensure T0 column exists and use T0_DATE if available
        if 'T0_DATE' in combined_df.columns:
            combined_df['T0'] = combined_df['T0_DATE']
        elif 'T0' not in combined_df.columns:
            combined_df['T0'] = pd.Timestamp('2020-01-01')
        
        combined_df['T0'] = pd.to_datetime(combined_df['T0'])
        combined_df['revised_dt'] = self.month_diff(combined_df['L3M_START'], combined_df['T0'])
        combined_df['revised_ai'] = combined_df.apply(lambda x: x['DE']/(1+x['B']*x['DE']*x['revised_dt']), axis=1)
        combined_df['revised_aries_de'] = combined_df.apply(lambda x: (1-np.power(((x['revised_ai']*12)*x['B']+1),(-1/x['B'])))*100, axis=1)
        
        # Calculate used IP from fitted curve at export start date.
        combined_df['used_ip'] = combined_df.apply(
            lambda r: self._export_rate_at_tau(r, r['revised_dt']),
            axis=1,
        )
        
        # Format for Mosaic
        output_df = combined_df.rename(columns={
            'UID': 'Entity Name',
            'used_ip': 'Initial Rate qi (rate/d)',
            'B': 'Exponent N, b',
            'revised_aries_de': 'Secant Effective Decline Desi (%)',
            'L3M_START': 'Start Date T0  (y-m-d)',
            'MAJOR': 'Product Type'
        })
        
        # Add required columns
        add_list = [
            'UUID', 'Reserve Category', 'Use Type', 'Segment #', 'Final Rate qf (rate/d)',
            'D Cum', 'Final Cum', 'Length DT (years)', 'Final Date Tf  (y-m-d)',
            'Nominal Decline Di (%)', 'Tangential Effective Decline   Dei (%)',
            'Service Factor (fraction)', 'Minimum Effective Decline Dmin (%)'
        ]
        
        for col in add_list:
            output_df[col] = None
        
        # Set default values
        output_df['Reserve Category'] = reserve_category
        output_df['Use Type'] = 'Produced'
        output_df['Segment #'] = 1
        output_df['Length DT (years)'] = 100
        output_df['Minimum Effective Decline Dmin (%)'] = dmin
        output_df['Product Type'] = output_df['Product Type'].str.capitalize()
        output_df['Initial Rate qi (rate/d)'] = output_df['Initial Rate qi (rate/d)'] * 12 / 365
        
        # Ensure minimum decline rate
        output_df['Secant Effective Decline Desi (%)'] = np.where(
            output_df['Secant Effective Decline Desi (%)'] < dmin,
            dmin,
            output_df['Secant Effective Decline Desi (%)']
        )
        
        # Select final columns
        final_columns = [
            'Entity Name', 'UUID', 'Reserve Category', 'Product Type', 'Use Type', 'Segment #',
            'Start Date T0  (y-m-d)', 'Initial Rate qi (rate/d)', 'Final Rate qf (rate/d)',
            'D Cum', 'Final Cum', 'Length DT (years)', 'Final Date Tf  (y-m-d)',
            'Exponent N, b', 'Nominal Decline Di (%)', 'Tangential Effective Decline   Dei (%)',
            'Secant Effective Decline Desi (%)', 'Service Factor (fraction)',
            'Minimum Effective Decline Dmin (%)'
        ]
        
        output_df = output_df[final_columns]
        
        # Create output directory if it doesn't exist
        import os
        output_dir = os.path.dirname(file_path)
        if output_dir:  # Only create directory if there is a path
            os.makedirs(output_dir, exist_ok=True)
        
        # Save to Excel
        output_df.to_excel(file_path, index=False)
        
        # Note: This function writes to file and does not return a DataFrame

    def generate_phdwin_export(self, file_path="outputs/phdwin_export.csv", dmin=6):
        """
        Generate PhdWin-compatible export with integrated DCA analysis.
        
        This method creates a comprehensive export for PhdWin software including
        all phases (OIL, GAS, WATER) with proper formatting and calculations.
        When three_phase_mode is enabled, it uses the existing three-phase analysis.
        Otherwise, it creates separate analyses for each phase.
        
        Args:
            file_path: Output file path (CSV format)
            dmin: Minimum decline rate
        """
        # Run DCA if not already done
        if self._params_dataframe.empty:
            # Set parameters to match reference script
            #self.D_MIN = 0.06/12
            #self.backup_decline = False
            #self.OUTLIER_CORRECTION = False
            #self.min_h_b = 0.01
            #self.max_h_b = 1.3
            self.run_DCA()
        
        # Generate oneline if not already done
        if self._oneline.empty:
            self.generate_oneline(denormalize=True)
        
        # Calculate 3-month averages
        l3m_df = self.qi_overwrite()
        
        if self.three_phase_mode:
            # Use existing three-phase analysis
            # The oneline data has separate columns for each phase: IPO/DO/BO, IPG/DG/BG, IPW/DW/BW
            
            # Start with the base oneline data
            base_df = self._oneline.merge(l3m_df, left_on='UID', right_on='UID', how='left')
            
            # Create separate rows for each phase
            combined_rows = []
            for _, row in base_df.iterrows():
                # OIL phase - use existing data
                if row['IPO'] > 0:
                    oil_row = row.copy()
                    oil_row['MAJOR'] = 'OIL'
                    oil_row['revised_qi'] = row['L3M_OIL']
                    oil_row['DE'] = row['DO']  # Use DO (Decline Oil)
                    oil_row['B'] = row['BO']   # Use BO (B-factor Oil)
                    oil_row['T0'] = row['T0_DATE']
                    combined_rows.append(oil_row)
                
                # GAS phase - use gas production data and gas-specific decline parameters
                if row['IPG'] > 0:
                    gas_row = row.copy()
                    gas_row['MAJOR'] = 'GAS'
                    gas_row['revised_qi'] = row['L3M_GAS']
                    gas_row['DE'] = row['DG']  # Use DG (Decline Gas)
                    gas_row['B'] = row['BG']   # Use BG (B-factor Gas)
                    gas_row['T0'] = row['T0_DATE']
                    combined_rows.append(gas_row)
                
                # WATER phase - use water production data and water-specific decline parameters
                if row['IPW'] > 0:  # Check if water production exists
                    water_row = row.copy()
                    water_row['MAJOR'] = 'WATER'
                    water_row['revised_qi'] = row['L3M_WATER']
                    water_row['DE'] = row['DW']  # Use DW (Decline Water)
                    water_row['B'] = row['BW']   # Use BW (B-factor Water)
                    water_row['T0'] = row['T0_DATE']
                    combined_rows.append(water_row)
            
            if combined_rows:
                tc_df = pd.DataFrame(combined_rows)
            else:
                # Fallback if no valid rows
                tc_df = base_df.copy()
                tc_df['MAJOR'] = 'OIL'  # Default
                tc_df['revised_qi'] = tc_df['L3M_OIL']
                tc_df['DE'] = 0.1
                tc_df['B'] = 1.0
                tc_df['T0'] = tc_df['T0_DATE']
        else:
            # Use existing oneline data with ratios (ratio mode)
            # The oneline data already has MINOR_RATIO and WATER_RATIO calculated
            # We just need to use these ratios to calculate gas and water production
            
            oneline_with_l3m = self._oneline.merge(l3m_df, left_on='UID', right_on='UID', how='left')
            
            # Create separate rows for each phase using ratios
            combined_rows = []
            for _, row in oneline_with_l3m.iterrows():
                # OIL phase - use existing data
                if row['IPO'] > 0:
                    oil_row = row.copy()
                    oil_row['MAJOR'] = 'OIL'
                    oil_row['DE'] = row['DE']  # Use DE for ratio mode
                    oil_row['B'] = row['B']    # Use B for ratio mode
                    oil_row['T0'] = row['T0_DATE']
                    oil_row['L3M_OIL'] = row['L3M_OIL']
                    combined_rows.append(oil_row)
                
                # GAS phase - calculate using MINOR_RATIO
                if row['MINOR_RATIO'] > 0 and row['IPO'] > 0:
                    gas_row = row.copy()
                    gas_row['MAJOR'] = 'GAS'
                    gas_row['DE'] = row['DE']  # Use same decline as oil
                    gas_row['B'] = row['B']   # Use same b-factor as oil
                    gas_row['T0'] = row['T0_DATE']
                    gas_row['L3M_GAS'] = row['L3M_OIL'] * row['MINOR_RATIO']  # Calculate gas rate using ratio
                    combined_rows.append(gas_row)
                
                # WATER phase - calculate using WATER_RATIO
                if row['WATER_RATIO'] > 0 and row['IPO'] > 0:
                    water_row = row.copy()
                    water_row['MAJOR'] = 'WATER'
                    water_row['DE'] = row['DE']  # Use same decline as oil
                    water_row['B'] = row['B']   # Use same b-factor as oil
                    water_row['T0'] = row['T0_DATE']
                    water_row['L3M_WATER'] = row['L3M_OIL'] * row['WATER_RATIO']  # Calculate water rate using ratio
                    combined_rows.append(water_row)
            
            if combined_rows:
                tc_df = pd.DataFrame(combined_rows)
            else:
                # Fallback if no valid rows
                logger.warning("No valid phase data found for PhdWin export")
                tc_df = oneline_with_l3m.copy()
                tc_df['MAJOR'] = 'OIL'  # Default
                tc_df['DE'] = 0.1
                tc_df['B'] = 1.0
                tc_df['T0'] = tc_df['T0_DATE']
        
        # Calculate revised parameters
        # Set StartDate to middle of last three months (L3M_START represents the most recent date)
        # Calculate middle date by going back 1 month from L3M_START (approximating middle of 3 months)
        tc_df['middle_date'] = tc_df['L3M_START'] - pd.DateOffset(months=1)
        
        # Calculate time difference from T0 to middle of last three months
        tc_df['revised_dt'] = self.month_diff(tc_df['middle_date'], tc_df['T0'])
        
        # Adjust decline rate to current point in time (similar to ARIES_DE calculation)
        # This calculates the effective decline rate at the current time point
        tc_df['revised_de'] = tc_df.apply(lambda x: x['DE']/(1+x['B']*x['DE']*x['revised_dt']), axis=1)
        
        # Convert to PhdWin decline rate format (percentage per year)
        tc_df['ARIES_DE'] = tc_df.apply(lambda x: 100*(1-np.exp(-x['revised_de']*12)), axis=1)
        
        # Use fitted curve rate at export start date (middle of last 3 months).
        tc_df['revised_qi'] = tc_df.apply(
            lambda r: self._export_rate_at_tau(r, r['revised_dt']),
            axis=1,
        )
        
        # Format for PhdWin
        output_columns = [
            'UniqueId', 'Product', 'Units', 'ProjType', 'StartDate', 'BegCum',
            'Qi', 'NFactor', 'Decl', 'DeclMin', 'EndDate', 'Qf', 'Volume',
            'EndCum', 'SolveFor'
        ]
        
        output_df = tc_df.copy()
        
        # Set end date (50 years forward) - match reference script
        fifty_years_forward = pd.Timestamp('2075-01-01')
        
        output_df['UniqueId'] = output_df['UID']
        output_df['Product'] = output_df['MAJOR'].str.title()
        output_df['Units'] = np.where(output_df['Product'] == 'Gas', 'Mcf', 'bbl')
        output_df['ProjType'] = 'Arps'
        output_df['StartDate'] = output_df['middle_date']
        output_df['BegCum'] = 0
        output_df['Qi'] = output_df['revised_qi']
        output_df['NFactor'] = np.where(
            (output_df['B'] > 0.01) & (output_df['ARIES_DE'] >= dmin), 
            output_df['B'], 
            0
        )
        output_df['Decl'] = np.where(
            output_df['ARIES_DE'] > dmin,
            output_df['ARIES_DE'],
            np.where(output_df['ARIES_DE'] > 0, dmin, 0)
        )
        output_df['DeclMin'] = np.where(
            (output_df['NFactor'] > 0.01) & (output_df['ARIES_DE'] > dmin),
            dmin,
            np.where((output_df['NFactor'] > 0.01), dmin, 0)
        )
        output_df['Qf'] = None
        output_df['Volume'] = None
        output_df['EndCum'] = None
        output_df['SolveFor'] = np.where(
            output_df['Product'].isin(["Oil", 'Gas', 'Water']),
            'Qf;Vol',
            'Qf'
        )
        output_df['EndDate'] = fifty_years_forward
        
        output_df = output_df[output_columns]
        
        # Create output directory if it doesn't exist
        import os
        output_dir = os.path.dirname(file_path)
        if output_dir:  # Only create directory if there is a path
            os.makedirs(output_dir, exist_ok=True)
        
        # Save to CSV
        output_df.to_csv(file_path, index=False)
        
        # Note: This function writes to file and does not return a DataFrame

    def make_ratio_dfs(self, input_df=None):
        """
        Create ratio dataframes for PhdWin-style analysis.
        
        This function creates separate dataframes for different production ratios
        (GOR, yield, WOR, WGR) that can be used for specialized analysis.
        
        Args:
            input_df: Input dataframe with L3M data (uses qi_overwrite result if None)
            
        Returns:
            DataFrame: Combined ratio dataframes
        """
        if input_df is None:
            input_df = self.qi_overwrite()
        
        # Function to calculate T0 (3 months before L3M_START)
        def calculate_t0(l3m_start):
            if pd.notnull(l3m_start):
                return (l3m_start - pd.DateOffset(months=3)).replace(day=1)
            return pd.NaT

        # Create and populate the new DataFrames
        ratios = {
            "gor_df": lambda row: (row["L3M_GAS"] / row["L3M_OIL"])*1000 if row["L3M_OIL"] else 0,
            "yield_df": lambda row: (row["L3M_OIL"] / row["L3M_GAS"])*1000 if row["L3M_GAS"] else 0,
            "wor_df": lambda row: row["L3M_WATER"] / row["L3M_OIL"] if row["L3M_OIL"] else 0,
            "wgr_df": lambda row: (row["L3M_WATER"] / row["L3M_GAS"])*1000 if row["L3M_GAS"] else 0,
        }

        final_df = pd.DataFrame([])

        for key, func in ratios.items():
            new_df = input_df[["UID", "L3M_OIL", "L3M_GAS", "L3M_WATER", "L3M_START"]].copy()
            new_df["T0"] = new_df["L3M_START"].apply(calculate_t0)
            new_df["revised_qi"] = input_df.apply(func, axis=1).fillna(0)
            new_df["MAJOR"] = key.split("_")[0].upper()
            # Add remaining blank columns
            for col in ["OIL", "GAS", "WATER", "IPO", "IPG", "B", "DE", "MINOR_RATIO", "WATER_RATIO", "ARIES_DE", "revised_dt"]:
                new_df[col] = None
            if final_df.empty:
                final_df = new_df
            else:
                final_df = pd.concat([final_df,new_df])

        final_df = final_df[[
            'UID',
            'OIL',
            'GAS',
            'WATER',
            'MAJOR',
            'IPO',
            'IPG',
            'B',
            'DE',
            'T0',
            'MINOR_RATIO',
            'WATER_RATIO',
            'ARIES_DE',
            'L3M_OIL',
            'L3M_GAS',
            'L3M_START',
            'revised_dt',
            'revised_qi'
        ]]
        
        return final_df
