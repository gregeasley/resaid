"""
Reservoir Engineering Economic Analysis Module

This module provides comprehensive economic analysis tools for oil and gas production projects.
It includes NPV calculations, IRR analysis, and detailed cashflow modeling for well economics.

Classes:
    npv_calc: Net Present Value and Internal Rate of Return calculations
    well_econ: Well economics analysis with cashflow generation and indicators

All cashflows are monthly: discount rates are per month and IRR is annualized.

Features:
    - NPV and IRR calculations for cashflow analysis
    - Multi-phase production economics (oil, gas and NGL revenue; oil, gas and water costs)
    - Royalty and working interest calculations
    - Operating cost and capital expenditure modeling
    - Severance tax calculations
    - Economic indicators generation (IRR, ROI, payback, breakeven)
    - Cashflow and discounted cashflow generation
"""

import logging
import warnings
from typing import cast

import numpy as np
import pandas as pd
from numpy.typing import ArrayLike
from scipy.optimize import brentq, newton
from tqdm import tqdm

from ._strict import StrictAttributes

logger = logging.getLogger(__name__)

# GOR (Mscf/bbl) above which a well is treated as gas-major for default breakeven phase logic.
GOR_GAS_MAJOR_MSCF_PER_BBL = 3.2


class npv_calc(StrictAttributes):
    """
    Net Present Value and Internal Rate of Return calculator.
    
    This class provides methods to calculate NPV and IRR for cashflow streams.
    
    Attributes:
        _cashflow (np.ndarray): Array of cashflow values
    """
    
    def __init__(self, cashflow: np.ndarray | list):
        """
        Initialize NPV calculator with cashflow array.
        
        Args:
            cashflow: Array of cashflow values (negative for outflows, positive for inflows)
        """
        self._cashflow = cashflow

    def get_npv(self, discount_rate):
        """
        Calculate Net Present Value at given discount rate.
        
        The first cashflow is undiscounted; each later one is discounted by one
        more period.
        
        Args:
            discount_rate (float): Discount rate per period. For monthly cashflows
                use a monthly rate, e.g. ``0.10 / 12`` for 10% per year.
            
        Returns:
            float: Net Present Value
        """
        l_npv = np.sum(self._cashflow / (1 + discount_rate) ** np.arange(0, len(self._cashflow)))
        return l_npv
    
    def get_irr(self, iterations=50):
        """
        Calculate Internal Rate of Return for monthly cashflows.

        Solves NPV = 0 with Newton's method; if that does not converge, the monthly
        rate is bracketed between 0 and 1,000% and solved with Brent's method.

        Args:
            iterations (int): Maximum iterations for Newton's method

        Returns:
            float: Annualized IRR as a fraction (12 x the monthly rate; 0.25 = 25%).
            Returns 0 when the undiscounted cashflow sum is negative, and NaN (with a
            logged warning) when no rate can be found, e.g. when no cashflow is
            negative.
        """
        if np.sum(self._cashflow) < 0:
            return 0

        guess = 0.1 / 12  # Initial guess of 10% annual rate
        with np.errstate(all="ignore"):
            try:
                rate = float(newton(self.get_npv, guess, maxiter=iterations))
            except (RuntimeError, OverflowError, ZeroDivisionError, ValueError):
                rate = np.nan
            if not np.isfinite(rate) or rate <= -1:
                rate = self._bracketed_irr()

        if np.isnan(rate):
            logger.warning("IRR could not be solved for this cashflow; reporting NaN")
            return np.nan
        return 12 * rate  # Convert monthly to annual rate

    def _bracketed_irr(self) -> float:
        """Monthly rate in [0, 10] where NPV changes sign, by Brent's method; NaN if none.

        Called with an undiscounted sum >= 0, so NPV(0) >= 0 and a root exists when
        NPV turns negative at a higher rate (an investment followed by returns).
        """
        high = 10.0  # 1,000% per month
        if not (self.get_npv(0.0) >= 0 > self.get_npv(high)):
            return np.nan
        try:
            return float(brentq(self.get_npv, 0.0, high))
        except (RuntimeError, ValueError):
            return np.nan

class well_econ(StrictAttributes):
    """
    Well economics analysis and cashflow modeling.
    
    This class provides comprehensive economic analysis for oil and gas wells,
    including cashflow generation, economic indicators calculation, and
    multi-phase production economics.
    
    ``flowstreams`` needs one row per well per month with the well ID and
    ``T_INDEX`` as columns (e.g. ``decline_curve.flowstream_dataframe.reset_index()``)
    and ``OIL``, ``GAS``, ``WATER`` volumes. ``discount_rate`` (monthly) must be set;
    other prices, costs and taxes default to 0.

    A ``decline_curve`` flowstream covers the well's whole life: actual production
    (``HISTORICAL`` rows) followed by the projection. By default the economics cover
    all of it; set ``projection_only = True`` to evaluate only the projection (e.g.
    remaining PDP value), which drops the ``HISTORICAL`` rows.
    
    Attributes:
        OIL_COL (str): Column name for oil production data
        GAS_COL (str): Column name for gas production data  
        WATER_COL (str): Column name for water production data
        _verbose (bool): Verbose output flag
    """

    def __init__(self, verbose=False):
        """
        Initialize well economics calculator.
        
        Args:
            verbose (bool): Enable verbose output for progress tracking
        """
        # Constants
        self.OIL_COL = "OIL"
        self.GAS_COL = 'GAS'
        self.WATER_COL = 'WATER'

        # User-configurable parameters
        self.verbose = verbose

        # Data sources
        self._flowstreams: pd.DataFrame | None = None
        self._header_data: pd.DataFrame | None = None
        self._flowstream_uwi_col: str | None = None
        self._flowstream_t_index: str | None = None
        self._header_uwi_col: str | None = None

        # Economic parameters
        self.royalty: float | None = None
        self.opc_t: float | None = None
        self.opc_oil: float | None = None
        self.opc_gas: float | None = None
        self.opc_water: float | None = None
        self.atx: float | None = None
        self.sev_gas: float | None = None
        self.sev_oil: float | None = None
        # A scalar, or monthly prices as a list, tuple, numpy array or Series
        self.oil_pri: ArrayLike | None = None
        self.gas_pri: ArrayLike | None = None
        self.discount_rate: float | None = None
        self.breakeven_phase: str | None = None

        # CAPEX parameters
        self.scale_capex: bool = False
        self.scale_column: str | None = None
        self.capex_val: float | None = None
        self.capex_col: str | None = None

        # Interest and royalty columns
        self.royalty_col: str | None = None
        self.owned_royalty_col: str | None = None
        self._wi_col: str | None = None
        self._nri_col: str | None = None

        # Gas processing parameters
        self.gas_shrink: float = 0
        self.ngl_yield: float = 0  # input as b/M post shrink
        self.ngl_price_fraction: float = 0

        # Scaling parameters
        self.scale_forecast: bool = False
        self.scale_base: float = 5280
        self.oil_diff: float = 0
        self.gas_diff: float = 0

        self.spud_to_online: int | None = None
        self.t_start_column: str | None = None
        self.projection_only: bool = False

        # Results
        self._indicators: pd.DataFrame | None = None

    # Essential property setters for data access
    @property
    def flowstreams(self):
        return self._flowstreams

    @flowstreams.setter
    def flowstreams(self, value):
        self._flowstreams = value

    @property
    def flowstream_uwi_col(self):
        return self._flowstream_uwi_col

    @flowstream_uwi_col.setter
    def flowstream_uwi_col(self, value):
        self._flowstream_uwi_col = value

    @property
    def flowstream_t_index(self):
        return self._flowstream_t_index

    @flowstream_t_index.setter
    def flowstream_t_index(self, value):
        self._flowstream_t_index = value

    @property
    def header_data(self):
        return self._header_data

    @header_data.setter
    def header_data(self, value):
        self._header_data = value

    @property
    def header_uwi_col(self):
        return self._header_uwi_col

    @header_uwi_col.setter
    def header_uwi_col(self, value):
        self._header_uwi_col = value

    @property
    def wi_col(self) -> str | None:
        return self._wi_col

    @wi_col.setter
    def wi_col(self, value):
        self._wi_col = value

    @property
    def nri_col(self) -> str | None:
        return self._nri_col

    @nri_col.setter
    def nri_col(self, value):
        self._nri_col = value

    @property
    def indicators(self):
        return self._indicators

    



   

    @staticmethod
    def _price_series(price, n: int) -> np.ndarray:
        """Monthly prices for ``n`` periods from a scalar or a sequence (list, tuple,
        numpy array, Series). A sequence is truncated, or extended with its last value."""
        if price is None:
            return np.zeros(n)
        values = np.asarray(price, dtype=float)
        if values.ndim == 0:
            return np.full(n, float(values))
        values = values.ravel()
        if values.size == 0:
            raise ValueError("Price sequence is empty")
        if values.size >= n:
            return values[:n]
        return np.concatenate([values, np.full(n - values.size, values[-1])])

    def generate_oil_price(self, times):
        """
        Generate oil price array for given time periods.

        ``oil_pri`` is a scalar or a sequence of monthly prices (list, tuple, numpy
        array or Series); a sequence shorter than ``times`` is extended with its last
        price. ``oil_diff`` is added. Without ``oil_pri`` prices are 0.

        Args:
            times (np.array): Array of time periods

        Returns:
            np.array: Oil prices for each time period
        """
        if self.oil_pri is None:
            return np.zeros(len(times))
        return self._price_series(self.oil_pri, len(times)) + self.oil_diff

    def generate_gas_price(self, times):
        """
        Generate gas price array for given time periods.

        ``gas_pri`` is a scalar or a sequence of monthly prices, as for
        ``generate_oil_price``; ``gas_diff`` is added.

        Args:
            times (np.array): Array of time periods

        Returns:
            np.array: Gas prices for each time period
        """
        if self.gas_pri is None:
            return np.zeros(len(times))
        return self._price_series(self.gas_pri, len(times)) + self.gas_diff

    def generate_capex(self, times, well, capex_point=0):
        """
        Generate CAPEX array for given time periods and well.

        CAPEX is charged in period ``capex_point`` (the first by default). Its amount
        comes from ``capex_col`` in the header data if set; otherwise
        ``capex_val * scale_column`` when ``scale_capex`` is True; otherwise the flat
        ``capex_val`` (no header data needed). A well missing from the header data, or
        with a blank value, is charged no CAPEX, with a warning.

        Args:
            times (np.array): Array of time periods
            well (str): Well identifier
            capex_point (int): Index of the period charged

        Returns:
            np.array: CAPEX values for each time period
        """
        return self._capex(times, well, self._well_header(well), capex_point)

    def _capex(self, times, well, header_row, capex_point):
        l_capex = np.zeros(len(times))
        if self.capex_col:
            amount = self._header_value(header_row, well, self.capex_col, 0.0, "no CAPEX")
        elif self.scale_capex:
            scale_val = self._header_value(
                header_row, well, cast(str, self.scale_column), None, "no CAPEX"
            )
            amount = 0.0 if scale_val is None else float(self.capex_val or 0) * float(scale_val)
        else:
            amount = self.capex_val or 0.0
        l_capex[capex_point] = float(amount)
        return l_capex

    def _header_settings(self) -> list[str]:
        """Names of the configured per-well header columns."""
        names = ["wi_col", "nri_col", "capex_col", "royalty_col", "owned_royalty_col",
                 "t_start_column"]
        configured = [n for n in names if getattr(self, n)]
        if self.scale_forecast or self.scale_capex:
            configured.append("scale_column")
        return configured

    def _well_header(self, well, warn=True) -> pd.Series | None:
        """
        The well's ``header_data`` row, or None when no header columns are configured.
        A well missing from ``header_data`` gets None and a warning naming the
        settings that fall back to defaults; duplicate rows use the first, with a
        warning.
        """
        if self._header_data is None or not self._header_settings():
            return None
        rows = self._header_data[self._header_data[self._header_uwi_col] == well]
        if rows.empty:
            if warn:
                warnings.warn(
                    f"Well {well} is not in header_data; using defaults for "
                    f"{', '.join(self._header_settings())} (no scaling, start delay or "
                    "header CAPEX; WI 1 and the scalar royalty).",
                    stacklevel=3,
                )
            return None
        if len(rows) > 1 and warn:
            warnings.warn(f"Well {well} has {len(rows)} rows in header_data; using the first.",
                          stacklevel=3)
        return rows.iloc[0]

    @staticmethod
    def _header_value(row, well, column, default, meaning):
        """``row[column]``, or ``default`` when the row is missing or the value is blank
        (the latter with a warning describing the fallback as ``meaning``)."""
        if row is None:
            return default
        value = row[column]
        if pd.isna(value):
            warnings.warn(f"Well {well}: {column} is blank in header_data; using {meaning}.",
                          stacklevel=3)
            return default
        return value

    def _require_inputs(self) -> tuple[pd.DataFrame, float]:
        """
        Return ``(flowstreams, discount_rate)`` after checking the inputs are usable.

        Raises ``ValueError`` naming the problem when the flowstream, its ID and
        ``T_INDEX`` column names, or ``discount_rate`` are unset; when the flowstream
        lacks a needed column (``OIL``, ``GAS``, ``WATER``, and ``MAJOR`` when
        ``spud_to_online`` or ``t_start_column`` is used); or when a configured header
        column (``wi_col``, ``nri_col``, ``capex_col``, ``royalty_col``,
        ``owned_royalty_col``, ``t_start_column``, and ``scale_column`` when scaling)
        is set without ``header_data`` or is missing from it.
        """
        flow = self._flowstreams
        if flow is None:
            raise ValueError(
                "No flowstreams: set econ.flowstreams "
                "(e.g. dca.flowstream_dataframe.reset_index())."
            )
        if not isinstance(flow, pd.DataFrame):
            raise TypeError(f"flowstreams must be a pandas DataFrame, got {type(flow).__name__}")
        unset = [
            label for label, value in (
                ("flowstream_uwi_col", self._flowstream_uwi_col),
                ("flowstream_t_index", self._flowstream_t_index),
            ) if not value
        ]
        if unset:
            raise ValueError(f"Set {', '.join(unset)} (e.g. econ.flowstream_uwi_col = 'UID').")

        needed = [self._flowstream_uwi_col, self._flowstream_t_index,
                  self.OIL_COL, self.GAS_COL, self.WATER_COL]
        if self.spud_to_online or self.t_start_column:
            needed.append('MAJOR')
        if self.projection_only:
            needed.append('HISTORICAL')
        missing = [c for c in needed if c not in flow.columns]
        if missing:
            hint = ""
            if any(c in (flow.index.names or []) for c in missing):
                hint = " Some are in the index; pass the flowstream with .reset_index()."
            if 'MAJOR' in missing:
                hint += " MAJOR is required when spud_to_online or t_start_column is set."
            if 'HISTORICAL' in missing:
                hint += (" HISTORICAL (from decline_curve.generate_flowstream) is required"
                         " when projection_only is set.")
            raise ValueError(
                f"flowstreams is missing column(s): {', '.join(map(str, missing))}. "
                f"Available columns: {', '.join(map(str, flow.columns))}.{hint}"
            )

        if self.discount_rate is None:
            raise ValueError("Set econ.discount_rate (a monthly rate, e.g. 0.10 / 12 for 10%/yr).")
        discount_rate = float(self.discount_rate)

        header_fields = {
            "wi_col": self.wi_col,
            "nri_col": self.nri_col,
            "capex_col": self.capex_col,
            "royalty_col": self.royalty_col,
            "owned_royalty_col": self.owned_royalty_col,
            "t_start_column": self.t_start_column,
        }
        if (self.scale_forecast or self.scale_capex) and not self.scale_column:
            raise ValueError("Set scale_column when scale_forecast or scale_capex is True.")
        if self.scale_capex and not self.capex_col and self.capex_val is None:
            raise ValueError("Set capex_val (CAPEX per unit of scale_column) when scale_capex is True.")
        if bool(self.wi_col) != bool(self.nri_col):
            raise ValueError("Set wi_col and nri_col together; one without the other is not used.")
        if self.owned_royalty_col and not (self.wi_col and self.royalty_col):
            raise ValueError(
                "owned_royalty_col is used only with wi_col, nri_col and royalty_col; set them too."
            )
        if self.royalty_col and self.wi_col and not self.owned_royalty_col:
            raise ValueError(
                "With wi_col and nri_col the royalty is 1 - NRI/WI, so royalty_col is not used; "
                "unset royalty_col, or also set owned_royalty_col."
            )
        if self.scale_forecast or self.scale_capex:
            header_fields["scale_column"] = self.scale_column
        header_fields = {k: v for k, v in header_fields.items() if v}
        if header_fields:
            header = self._header_data
            if header is None:
                raise ValueError(
                    f"header_data is required when {', '.join(header_fields)} "
                    f"{'is' if len(header_fields) == 1 else 'are'} set."
                )
            if not self._header_uwi_col:
                raise ValueError("Set header_uwi_col to the well ID column of header_data.")
            missing = [
                f"{k}={v!r}" for k, v in {"header_uwi_col": self._header_uwi_col, **header_fields}.items()
                if v not in header.columns
            ]
            if missing:
                raise ValueError(
                    f"header_data is missing column(s): {', '.join(missing)}. "
                    f"Available columns: {', '.join(map(str, header.columns))}."
                )
        return flow, discount_rate

    def zero_below(self, df: pd.DataFrame, i_max: int, cols: list):
        """
        Zero out values in specified columns for rows where T_INDEX > i_max.
        
        Args:
            df (pd.DataFrame): Input DataFrame
            i_max (int): Maximum time index (``flowstream_t_index`` column) to keep
            cols (list): List of column names to zero out
            
        Returns:
            pd.DataFrame: Modified DataFrame
        """
        t_col = self._flowstream_t_index or 'T_INDEX'
        for col in cols:
            df[col] = np.where(
                df[t_col] <= i_max,
                df[col],
                0
            )

        return df

    def well_flowstream(self, input_well):
        """
        Generate the monthly cashflow for a specific well.
        
        Args:
            input_well (str): Well identifier (value of ``flowstream_uwi_col``)
            
        Returns:
            pd.DataFrame: The well's flowstream rows plus revenue, royalty, expense,
            tax, capex, ``cf``/``dcf`` and ``wi_*``/``net_*`` columns. Volumes and
            cashflows after the economic limit (last month with positive ``dcf``)
            are zeroed.
            
        Raises:
            ValueError: If the well is not in ``flowstreams``.
        """
        flow, discount_rate = self._require_inputs()
        l_flow = flow[flow[self._flowstream_uwi_col] == input_well]
        if self.projection_only:
            l_flow = l_flow[~l_flow['HISTORICAL'].astype(bool)]
        l_flow = l_flow.reset_index(drop=True)
        
        # Check if well data exists
        if l_flow.empty:
            raise ValueError(f"No flowstream data found for well: {input_well}")

        # Set default values for None parameters
        if self.opc_t is None:
            self.opc_t = 0
        if self.opc_oil is None:
            self.opc_oil = 0
        if self.opc_gas is None:
            self.opc_gas = 0
        if self.opc_water is None:
            self.opc_water = 0
        if self.sev_oil is None:
            self.sev_oil = 0
        if self.sev_gas is None:
            self.sev_gas = 0
        if self.atx is None:
            self.atx = 0
        if self.royalty is None:
            self.royalty = 0

        header_row = self._well_header(input_well)

        if self.scale_forecast:
            scale_val = self._header_value(
                header_row, input_well, cast(str, self.scale_column), self.scale_base, "no scaling"
            )
            l_flow[self.OIL_COL] = l_flow[self.OIL_COL] * scale_val / self.scale_base
            l_flow[self.GAS_COL] = l_flow[self.GAS_COL] * scale_val / self.scale_base

        # Months before production: the well's start delay (t_start_column), then
        # spud_to_online. They are inserted as zero-volume rows; capex is charged at
        # spud (the first month after the start delay) and no expense before production.
        start_val = 0
        if self.t_start_column:
            start_val = int(self._header_value(
                header_row, input_well, self.t_start_column, 0, "no start delay"
            ))
        start_val = max(start_val, 0)
        n_delay = start_val + max(int(self.spud_to_online or 0), 0)

        if n_delay:
            t_col = self._flowstream_t_index
            t_first = l_flow[t_col].iloc[0]
            delay_df = pd.DataFrame(0, index=range(n_delay), columns=l_flow.columns)
            delay_df[self._flowstream_uwi_col] = l_flow[self._flowstream_uwi_col].iloc[0]
            delay_df['MAJOR'] = l_flow['MAJOR'].iloc[0]
            if 'HISTORICAL' in delay_df.columns:
                delay_df['HISTORICAL'] = False
            delay_df[t_col] = t_first + np.arange(n_delay)
            l_flow[t_col] += n_delay
            l_flow = pd.concat([delay_df, l_flow]).reset_index(drop=True)

        l_flow['gas_sold'] = l_flow[self.GAS_COL] * (1 - self.gas_shrink)
        l_flow['ngl_volume'] = l_flow['gas_sold'] * self.ngl_yield
        t_series = np.array(range(len(l_flow)))

        l_flow['oil_price'] = self.generate_oil_price(t_series)
        l_flow['gas_price'] = self.generate_gas_price(t_series)
        l_flow['ngl_price'] = l_flow['oil_price'] * self.ngl_price_fraction

        l_flow['oil_revenue'] = l_flow[self.OIL_COL] * l_flow['oil_price']
        l_flow['gas_revenue'] = l_flow['gas_sold'] * l_flow['gas_price']
        l_flow['ngl_revenue'] = l_flow['ngl_volume'] * l_flow['ngl_price']

        l_flow['revenue'] = (
            l_flow[self.OIL_COL] * l_flow['oil_price']
            + l_flow['gas_sold'] * l_flow['gas_price']
            + l_flow['ngl_volume'] * l_flow['ngl_price']
        )

        # Royalty and interests: from the header (wi_col/nri_col, with royalty_col and
        # owned_royalty_col, or royalty_col alone), else the scalar royalty with WI 1.
        l_royalty = self.royalty
        l_wi, l_nri, l_ori = 1, 1 - self.royalty, 0
        if header_row is not None and (self.wi_col or self.royalty_col):
            default = f"the scalar royalty ({self.royalty}) and WI 1"
            columns = {"wi": self.wi_col, "nri": self.nri_col,
                       "royalty": self.royalty_col, "ori": self.owned_royalty_col}
            values = {
                key: self._header_value(header_row, input_well, col, None, default)
                for key, col in columns.items()
                if col
            }
            if all(v is not None for v in values.values()):
                if "ori" in values:
                    l_wi, l_nri = values["wi"], values["nri"]
                    l_ori, l_royalty = values["ori"], values["royalty"]
                    if l_nri + l_royalty > 1:
                        raise ValueError(f"Sum of royalty and NRI must be less than or equal to 1, currently {l_nri + l_royalty}")
                elif "wi" in values:
                    l_wi, l_nri = values["wi"], values["nri"]
                    l_royalty = 1 - l_nri / l_wi
                else:
                    l_royalty = values["royalty"]
                    l_nri = 1 - l_royalty
        l_flow['royalty'] = l_flow['revenue'] * l_royalty

        l_flow['fixed_expense'] = self.opc_t
        l_flow['oil_variable_expense'] = self.opc_oil * l_flow[self.OIL_COL]
        l_flow['gas_variable_expense'] = self.opc_gas * l_flow['gas_sold']
        l_flow['water_variable_expense'] = self.opc_water * l_flow[self.WATER_COL]

        l_flow['expense'] = (
            self.opc_t
            + self.opc_gas * l_flow['gas_sold']
            + self.opc_oil * l_flow[self.OIL_COL]
            + self.opc_water * l_flow[self.WATER_COL]
        )

        # No operating expense before production
        if n_delay:
            l_flow.loc[:n_delay - 1, ['fixed_expense', 'expense']] = 0

        l_flow['severance_tax'] = (
            self.sev_gas * l_flow[self.GAS_COL] * l_flow['gas_price']
            + self.sev_oil * l_flow[self.OIL_COL] * l_flow['oil_price']
        ) * (1 - l_royalty)

        l_flow['ad_val_tax'] = self.atx * l_flow['revenue'] * (1 - l_royalty)

        l_flow['taxes'] = (
            self.atx * l_flow['revenue']
            + self.sev_gas * l_flow[self.GAS_COL] * l_flow['gas_price']
            + self.sev_oil * l_flow[self.OIL_COL] * l_flow['oil_price']
        ) * (1 - l_royalty)

        l_flow['capex'] = self._capex(np.arange(len(l_flow)), input_well, header_row, start_val)

        l_flow['cf'] = (
            l_flow['revenue']
            - l_flow['royalty']
            - l_flow['expense']
            - l_flow['taxes']
            - l_flow['capex']
        )

        l_flow['dcf'] = (l_flow['cf'].to_numpy() / (1 + discount_rate) ** np.arange(0, len(l_flow['cf'].to_numpy())))

        try:
            cf_idx = np.argwhere(l_flow['dcf'].to_numpy() > 0)
        except (TypeError, ValueError):
            cf_idx = np.empty((0, 1), dtype=np.intp)

        if len(cf_idx) > 0:
            last_cf = cf_idx[-1][0]
        else:
            last_cf = 0

        zero_cols = [
            self.OIL_COL,
            self.GAS_COL,
            'gas_sold',
            self.WATER_COL,
            'ngl_volume',
            'oil_revenue',
            'gas_revenue',
            'ngl_revenue',
            'revenue',
            'royalty',
            'fixed_expense',
            'oil_variable_expense',
            'gas_variable_expense',
            'water_variable_expense',
            'expense',
            'severance_tax',
            'ad_val_tax',
            'taxes',
            'capex',
            'cf',
            'dcf'
        ]

        l_flow = self.zero_below(l_flow, l_flow[self._flowstream_t_index].iloc[last_cf], zero_cols)

        # calculate WI values
        l_flow[['wi_oil',
            'wi_gas',
            'wi_ngl',
            'wi_revenue',
            'wi_royalty',
            'wi_expense',
            'wi_severance_tax',
            'wi_ad_val_tax',
            'wi_taxes',
            'wi_capex',
            'wi_cf',
            'wi_dcf']] = l_flow[[self.OIL_COL,
            'gas_sold',
            'ngl_volume',
            'revenue',
            'royalty',
            'expense',
            'severance_tax',
            'ad_val_tax',
            'taxes',
            'capex',
            'cf',
            'dcf']].mul(l_wi)
        
        l_flow['net_oil'] = l_flow[self.OIL_COL]*(l_nri+l_royalty*l_ori)
        l_flow['net_gas'] = l_flow['gas_sold']*(l_nri+l_royalty*l_ori)
        l_flow['net_ngl'] = l_flow['ngl_volume']*(l_nri+l_royalty*l_ori)
        l_flow['net_oil_revenue'] = l_flow['oil_revenue']*(l_nri+l_royalty*l_ori)
        l_flow['net_gas_revenue'] = l_flow['gas_revenue']*(l_nri+l_royalty*l_ori)
        l_flow['net_ngl_revenue'] = l_flow['ngl_revenue']*(l_nri+l_royalty*l_ori)
        l_flow['net_revenue'] = l_flow['revenue']*(l_nri+l_royalty*l_ori)
        l_flow['net_royalty'] = 0
        l_flow['net_expense'] = l_flow['wi_expense']
        l_flow['net_severance_tax'] = l_flow['severance_tax']/(1-l_royalty)*(l_nri+l_royalty*l_ori)
        l_flow['net_ad_val_tax'] = l_flow['ad_val_tax']/(1-l_royalty)*(l_nri+l_royalty*l_ori)
        l_flow['net_taxes'] = l_flow['taxes']/(1-l_royalty)*(l_nri+l_royalty*l_ori)
        l_flow['net_capex'] = l_flow['wi_capex']
        l_flow['net_cf'] = (
            l_flow['net_revenue']
            - l_flow['net_royalty']
            - l_flow['net_expense']
            - l_flow['net_taxes']
            - l_flow['net_capex']
        )
        l_flow['net_dcf'] = (l_flow['net_cf'].to_numpy() / (1+discount_rate)**np.arange(0, len(l_flow['cf'].to_numpy())))

        l_flow['wi_net_oil'] = l_flow[self.OIL_COL]*(l_nri+l_royalty*l_ori)
        l_flow['wi_net_gas'] = l_flow['gas_sold']*(l_nri+l_royalty*l_ori)
        l_flow['wi_net_ngl'] = l_flow['ngl_volume']*(l_nri+l_royalty*l_ori)

        return l_flow


    def generate_indicators(self):
        """
        Generate economic indicators for all wells.
        
        Calculates various economic metrics including EUR, revenue, IRR, ROI,
        payback period, and breakeven analysis for each well. Columns: ``UWI``,
        ``EURO``, ``EURG``, ``EURW``, ``REVENUE``, ``ROYALTY``, ``OPEX``, ``TAXES``,
        ``CAPEX``, ``FCF``, ``DCF``, ``IRR`` (annualized fraction), ``ROI``,
        ``PAYOUT`` (month index; NaN when the well never pays out),
        ``BREAKEVEN`` and ``BREAKEVEN_PHASE``.
        
        Returns:
            None: Sets self._indicators to a DataFrame with economic indicators
        """
        ind_dict: dict = {
            'UWI': [],
            'EURO': [],
            'EURG': [],
            'EURW': [],
            'REVENUE': [],
            'ROYALTY': [],
            'OPEX': [],
            'TAXES': [],
            'CAPEX': [],
            'FCF': [],
            'DCF': [],
            'IRR': [],
            'ROI': [],
            'PAYOUT': [],
            'BREAKEVEN': [],
            'BREAKEVEN_PHASE': []
        }

        flow, discount_rate = self._require_inputs()
        unique_wells = flow[self._flowstream_uwi_col].unique()

        iterable = tqdm(unique_wells) if self.verbose else unique_wells

        for w in iterable:
            
            l_flow = self.well_flowstream(w)
            
            dc_rev = (l_flow['revenue'].to_numpy() / (1+discount_rate)**np.arange(0, len(l_flow['revenue'].to_numpy())))

            if self.breakeven_phase is None:
                if np.sum(l_flow[self.OIL_COL]) > 0:
                    if np.sum(l_flow[self.GAS_COL]) / np.sum(l_flow[self.OIL_COL]) > GOR_GAS_MAJOR_MSCF_PER_BBL:
                        be_major = 'GAS'
                        break_even =(np.sum(dc_rev)- np.sum(l_flow['dcf']))/np.sum(l_flow[self.GAS_COL])
                    else:    
                        be_major = 'OIL'
                        break_even =(np.sum(dc_rev)- np.sum(l_flow['dcf']))/np.sum(l_flow[self.OIL_COL])
                else:
                    be_major = 'GAS'
                    break_even =(np.sum(dc_rev)- np.sum(l_flow['dcf']))/np.sum(l_flow[self.GAS_COL])
            else:
                if self.breakeven_phase == "GAS":
                    be_major = 'GAS'
                    break_even =(np.sum(dc_rev)- np.sum(l_flow['dcf']))/np.sum(l_flow[self.GAS_COL])
                else:
                    be_major = 'OIL'
                    break_even =(np.sum(dc_rev)- np.sum(l_flow['dcf']))/np.sum(l_flow[self.OIL_COL])

            # First month with positive cumulative cashflow; NaN if it never pays out
            paid_out = l_flow['cf'].cumsum().to_numpy() > 0
            payout = int(np.argmax(paid_out)) if paid_out.any() else np.nan


            ind_dict['UWI'].append(w)
            ind_dict['EURO'].append(np.sum(l_flow[self.OIL_COL]))
            ind_dict['EURG'].append(np.sum(l_flow[self.GAS_COL]))
            ind_dict['EURW'].append(np.sum(l_flow[self.WATER_COL]))
            ind_dict['REVENUE'].append(np.sum(l_flow['revenue']))
            ind_dict['ROYALTY'].append(np.sum(l_flow['royalty']))
            ind_dict['OPEX'].append(np.sum(l_flow['expense']))
            ind_dict['TAXES'].append(np.sum(l_flow['taxes']))
            ind_dict['CAPEX'].append(np.sum(l_flow['capex']))
            ind_dict['FCF'].append(np.sum(l_flow['cf']))
            ind_dict['DCF'].append(np.sum(l_flow['dcf']))
            ind_dict['BREAKEVEN'].append(break_even)
            ind_dict['BREAKEVEN_PHASE'].append(be_major)
            ind_dict['PAYOUT'].append(payout)
            ind_dict['IRR'].append(npv_calc(l_flow['cf'].to_numpy()).get_irr())

            capex_total = np.sum(l_flow['capex'])
            ind_dict['ROI'].append(np.sum(l_flow['cf']) / capex_total + 1 if capex_total else np.nan)


        self._indicators = pd.DataFrame(ind_dict)

    def generate_cashflow(self):
        """
        Generate cashflow for all wells.
        
        Creates a comprehensive cashflow DataFrame containing all wells'
        economic data including revenue, expenses, taxes, and cashflow.
        
        Returns:
            pd.DataFrame: Combined cashflow data for all wells
        """
        r_df = pd.DataFrame([])
        flow, _ = self._require_inputs()
        unique_wells = flow[self._flowstream_uwi_col].unique()

        iterable = tqdm(unique_wells) if self.verbose else unique_wells

        for w in iterable:
            l_flow = self.well_flowstream(w)

            if r_df.empty:
                r_df = l_flow
            else:
                r_df = pd.concat([r_df, l_flow])

        return r_df