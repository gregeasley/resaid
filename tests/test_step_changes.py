"""Step-change (restim / recovery) detection and its effect on the forecast."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from resaid.dca import DCA_FIT_METHOD_MONOTONE_TWO_STEP, decline_curve

DMIN = 0.08 / 12


def _arps(qi, di, b, t):
    t = np.asarray(t, dtype=float)
    q = qi * (1 + b * di * t) ** (-1 / b)
    d_inst = di / (1 + b * di * t)
    if (d_inst <= DMIN).any():
        k = int(np.argmax(d_inst <= DMIN))
        q[k:] = q[k] * np.exp(-DMIN * (t[k:] - t[k]))
    return q


def _restim_well(step_at=30, months=48, horizon=60, k=2.5, shut_in=False, seed=0):
    """Hyperbolic well restimulated at ``step_at``; returns (history, future truth, true regime peak)."""
    rng = np.random.default_rng(seed)
    t = np.arange(months + horizon, dtype=float)
    q = _arps(20000, 0.2, 1.0, t)
    q[step_at:] = q[step_at] * k * _arps(1.0, 0.15, 1.0, t[step_at:] - step_at)
    if shut_in:
        q[step_at - 2:step_at] *= 0.02
    noisy = q * rng.lognormal(0, 0.05, len(q))
    return noisy[:months], q[months:], step_at


def _plain_well(months=48, seed=0, dips=()):
    rng = np.random.default_rng(seed)
    q = _arps(20000, 0.2, 1.0, np.arange(months)) * rng.lognormal(0, 0.05, months)
    for m in dips:
        q[m] *= 0.05
    return q


@pytest.fixture
def dca():
    d = decline_curve()
    d.STAT_FILE = None
    return d


@pytest.mark.parametrize("shut_in", [False, True])
def test_detects_restim_peak(dca, shut_in):
    hist, _, step_at = _restim_well(shut_in=shut_in)
    start = dca._latest_regime_start(hist)
    assert step_at <= start <= step_at + 3
    assert start == step_at + int(np.argmax(hist[step_at:step_at + 6]))


def test_detects_latest_of_several_steps(dca):
    hist, _, first = _restim_well(step_at=20, months=60)
    second = 45
    hist = hist.copy()
    hist[second:] *= 2.5
    assert dca._latest_regime_start(hist) >= second
    assert dca._latest_regime_start(hist[:second]) >= first


@pytest.mark.parametrize(
    "y",
    [
        _plain_well(),
        _plain_well(dips=(10, 25, 26, 40)),  # single and two-month shut-ins, back on trend
    ],
    ids=["plain", "dips_and_shut_ins"],
)
def test_no_regime_change_without_step(dca, y):
    # Only the initial ramp/peak region may be reported.
    assert dca._latest_regime_start(y) <= 3


def test_step_down_is_not_a_new_regime(dca):
    y = _plain_well(months=48)
    y[24:] *= 0.4
    assert dca._latest_regime_start(y) <= 3


def test_step_too_recent_to_fit_is_ignored(dca):
    hist, _, _ = _restim_well(step_at=44, months=48)
    assert dca._latest_regime_start(hist) <= 3
    dca.step_change_min_points = 3
    assert dca._latest_regime_start(hist) >= 44


def test_detection_can_be_disabled(dca):
    hist, _, _ = _restim_well()
    dca.detect_step_changes = False
    assert dca._latest_regime_start(hist) == 0


def _forecast_ratio(hist, truth, **attrs):
    df = pd.DataFrame(
        {
            "UID": "W1",
            "DATE": [pd.Timestamp("2018-01-01") + pd.DateOffset(months=i) for i in range(len(hist))],
            "OIL": hist,
            "GAS": hist,
            "WATER": hist,
        }
    )
    fit_method = attrs.pop("fit_method", "default")
    d = decline_curve(fit_method=fit_method)
    d.STAT_FILE = None
    d.dataframe = df
    d.date_col, d.uid_col = "DATE", "UID"
    d.oil_col, d.gas_col, d.water_col = "OIL", "GAS", "WATER"
    d.backup_decline = True
    for k, v in attrs.items():
        setattr(d, k, v)
    d.run_DCA()
    r = d.params_dataframe.iloc[0]
    t = np.arange(len(hist), len(hist) + len(truth), dtype=float)
    return d.arps_decline(t, r.qi, r.di, r.b, r.t0).sum() / truth.sum(), r


@pytest.mark.parametrize("shut_in", [False, True])
def test_restim_forecast_uses_new_regime(shut_in):
    hist, truth, step_at = _restim_well(shut_in=shut_in)
    ratio_on, params = _forecast_ratio(hist, truth)
    ratio_off, _ = _forecast_ratio(hist, truth, detect_step_changes=False)
    assert params.t0 >= step_at  # decline anchored in the new regime
    # Short post-restim history leaves some b/di uncertainty, but fitting the old
    # regime's flattened decline over-forecasts far more.
    assert abs(ratio_on - 1) < 0.3
    assert abs(ratio_on - 1) < 0.6 * abs(ratio_off - 1)


def test_restim_forecast_monotone_method():
    hist, truth, _ = _restim_well()
    ratio_on, _ = _forecast_ratio(hist, truth, fit_method=DCA_FIT_METHOD_MONOTONE_TWO_STEP)
    ratio_off, _ = _forecast_ratio(
        hist, truth, fit_method=DCA_FIT_METHOD_MONOTONE_TWO_STEP, detect_step_changes=False
    )
    assert abs(ratio_on - 1) < abs(ratio_off - 1)


def test_plain_well_fit_unchanged_by_detection():
    y = _plain_well(dips=(12, 30))
    truth = np.ones(12)
    _, on = _forecast_ratio(y, truth)
    _, off = _forecast_ratio(y, truth, detect_step_changes=False)
    assert (on.qi, on.di, on.b, on.t0) == pytest.approx((off.qi, off.di, off.b, off.t0))
