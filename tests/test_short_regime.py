"""A step up too recent to fit (short post-workover regime) takes the previous regime's EUR."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from resaid.dca import DCA_FIT_METHOD_MONOTONE_TWO_STEP, decline_curve
from resaid.dca.decline_curve import DCA_PATH_LEGACY_SHORT_REGIME, _decline_solver_cls
from resaid.dca_constants import DEFAULT_SOLVER_T_MAX_MONTHS

from test_step_changes import _arps, _plain_well


def _workover_well(months=48, short=4, k=2.5, seed=0):
    """Plain hyperbolic decline with a workover step up ``short`` months before the end."""
    rng = np.random.default_rng(seed)
    t = np.arange(months, dtype=float)
    q = _arps(20000, 0.2, 1.0, t)
    step = months - short
    q[step:] = q[step] * k * _arps(1.0, 0.15, 1.0, t[step:] - step)
    return q * rng.lognormal(0, 0.03, months), step


def _params(y, **attrs):
    df = pd.DataFrame({
        "UID": "W1",
        "DATE": [pd.Timestamp("2018-01-01") + pd.DateOffset(months=i) for i in range(len(y))],
        "OIL": y, "GAS": y, "WATER": y,
    })
    d = decline_curve(fit_method=attrs.pop("fit_method", "default"))
    d.STAT_FILE = None
    d.dataframe = df
    d.date_col, d.uid_col = "DATE", "UID"
    d.oil_col, d.gas_col, d.water_col = "OIL", "GAS", "WATER"
    d.backup_decline = True
    for k, v in attrs.items():
        setattr(d, k, v)
    d.run_DCA()
    return d, d.params_dataframe.iloc[0]


def _eur(d, qi, di, b):
    out = _decline_solver_cls()(qi=qi, qf=None, de=di, dmin=d.MIN_DECLINE_RATE, b=b, eur=None,
                                t_max=DEFAULT_SOLVER_T_MAX_MONTHS).solve()
    return float(out[4])


@pytest.fixture
def dca():
    d = decline_curve()
    d.STAT_FILE = None
    return d


def test_short_regime_detected_but_not_fit(dca):
    y, step = _workover_well(short=4)
    assert dca._latest_regime_start(y) == 0                  # too short to be the fit regime
    assert step - 1 <= dca._short_regime_start(y) <= step     # onset of the step
    y_long, _ = _workover_well(short=10)
    assert dca._short_regime_start(y_long) is None            # long enough: a normal regime
    assert dca._short_regime_start(_plain_well()) is None


@pytest.mark.parametrize("fit_method", ["default", DCA_FIT_METHOD_MONOTONE_TWO_STEP])
def test_short_regime_takes_prior_regime_eur(fit_method):
    y, step = _workover_well(short=4)
    d, r = _params(y, fit_method=fit_method)
    assert r.t0 > step
    if fit_method == "default":
        assert d._dca_path_counts.get(DCA_PATH_LEGACY_SHORT_REGIME) == 1

    # IP from the current datapoints (tail average), decline from the tail on.
    assert r.qi == pytest.approx(np.mean(y[-3:]), rel=2e-3)   # resaid normalizes volumes per day-month
    assert r.t0 == pytest.approx(len(y) - 2, abs=1e-6)

    # Regime EUR (produced since the onset + remaining from the tail rate) equals the previous
    # regime's EUR: its actual production to the onset + its fitted curve from the onset on.
    onset = d._short_regime_start(y)
    produced = y[onset:len(y) - 2].sum() + 0.5 * y[len(y) - 2]
    remaining = _eur(d, r.qi, r.di, r.b)
    if fit_method == "default":
        qi0, di0, b0, t00 = _unadjusted_fit(y[:onset])
        t_after = np.arange(onset, onset + DEFAULT_SOLVER_T_MAX_MONTHS, dtype=float)
        eur_prev = y[:onset].sum() + d.arps_decline(t_after, qi0, di0, b0, t00).sum()
        assert produced + remaining == pytest.approx(eur_prev, rel=0.03)
    # Much less than if the spike rate simply continued with the old regime's EUR left over.
    assert remaining < _eur(d, r.qi, d.MIN_DECLINE_RATE, r.b)


def _unadjusted_fit(y):
    """Previous-regime Arps fit (qi, di, b) without the L3M adjustment."""
    d = decline_curve()
    d.STAT_FILE = None
    captured = {}
    orig = d._adjust_default_fit_to_recent_l3m

    def keep(qi, di, b, t0, x, yy):
        captured.update(qi=qi, di=di, b=b, t0=t0)
        return orig(qi, di, b, t0, x, yy)

    d._adjust_default_fit_to_recent_l3m = keep
    df = pd.DataFrame({
        "UID": "W1",
        "DATE": [pd.Timestamp("2018-01-01") + pd.DateOffset(months=i) for i in range(len(y))],
        "OIL": y, "GAS": y, "WATER": y,
    })
    d.dataframe = df
    d.date_col, d.uid_col = "DATE", "UID"
    d.oil_col, d.gas_col, d.water_col = "OIL", "GAS", "WATER"
    d.run_DCA()
    return captured["qi"], captured["di"], captured["b"], captured["t0"]


def test_short_regime_match_can_be_disabled():
    y, _ = _workover_well(short=4)
    d, r = _params(y, short_regime_eur_match=False)
    assert not d._dca_path_counts.get(DCA_PATH_LEGACY_SHORT_REGIME)


@pytest.mark.parametrize("fit_method", ["default", DCA_FIT_METHOD_MONOTONE_TWO_STEP])
def test_plain_well_unchanged(fit_method):
    y = _plain_well(dips=(12, 30))
    _, on = _params(y, fit_method=fit_method)
    _, off = _params(y, fit_method=fit_method, short_regime_eur_match=False)
    assert (on.qi, on.di, on.b, on.t0) == pytest.approx((off.qi, off.di, off.b, off.t0))


def test_recompletion_sized_step_is_not_a_workover(dca):
    # A jump far above the previous regime's peak (new zone) gets no EUR match.
    y, step = _workover_well(short=4, k=30.0)
    assert dca._unfit_step(y) is not None
    assert dca._short_regime_start(y) is None
    d, _ = _params(y)
    assert not d._dca_path_counts.get(DCA_PATH_LEGACY_SHORT_REGIME)


def test_ramp_months_after_the_onset_are_not_the_previous_regime(dca):
    # Two ramp months before the new peak must not raise the previous regime's peak.
    prev = list(np.linspace(1300, 300, 54))
    y = np.array(prev + [20654, 31540, 33858, 29500], dtype=float)
    assert dca._unfit_step(y) is not None
    assert dca._short_regime_start(y) is None                 # 30k vs a 1.3k previous peak


def test_young_well_ramp_is_not_a_workover(dca):
    # A new well whose rate keeps climbing (GOR rise, choke opening) has no previous regime.
    y = np.array([0, 0, 4887, 5266, 5437, 6699, 7436, 8085, 8494], dtype=float)
    assert dca._short_regime_start(y) is None
