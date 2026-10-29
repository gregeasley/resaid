"""b-factor selection toward ``b_prior`` in the default fit (``decline_curve._b_prior_refit``)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from resaid.dca import decline_curve


def _arps(qi, di, b, t):
    return qi / (1.0 + b * di * t) ** (1.0 / b)


def _fit_b(y, **attrs):
    df = pd.DataFrame({
        "UID": "W1",
        "DATE": [pd.Timestamp("2018-01-01") + pd.DateOffset(months=i) for i in range(len(y))],
        "OIL": y, "GAS": 0.5 * y, "WATER": y,
    })
    d = decline_curve()
    d.STAT_FILE = None
    d.dataframe = df
    d.date_col, d.uid_col = "DATE", "UID"
    d.oil_col, d.gas_col, d.water_col = "OIL", "GAS", "WATER"
    d.min_h_b, d.max_h_b = 0.5, 1.3
    for k, v in attrs.items():
        setattr(d, k, v)
    d.run_DCA()
    return float(d.params_dataframe.iloc[0]["b"])


def _weak_well(seed):
    """Late-life, noisy decline: the data cannot tell b values in 0.5-1.3 apart."""
    t = np.arange(96.0)
    return _arps(30000, 0.04, 0.9, t)[60:] * np.random.default_rng(seed).lognormal(0, 0.15, 36)


def _strong_well(seed):
    """Early, clean hyperbolic decline with b = 1.25."""
    t = np.arange(60.0)
    return _arps(30000, 0.25, 1.25, t) * np.random.default_rng(seed).lognormal(0, 0.02, 60)


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_undetermined_b_takes_the_midpoint_by_default(seed):
    assert _fit_b(_weak_well(seed)) == pytest.approx(0.9)


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_undetermined_b_takes_b_prior(seed):
    assert _fit_b(_weak_well(seed), b_prior=0.7) == pytest.approx(0.7)


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_clear_curvature_moves_b_off_the_prior(seed):
    assert _fit_b(_strong_well(seed)) >= 1.0


def test_tolerance_none_keeps_the_least_squares_b():
    y = _strong_well(0)
    b_free = _fit_b(y, b_prior_tolerance=None)
    assert b_free == pytest.approx(1.22, abs=0.03)
    assert _fit_b(y, b_prior_tolerance=None, b_prior=0.6) == pytest.approx(b_free)


def test_b_prior_outside_the_bounds_raises():
    with pytest.raises(ValueError, match="b_prior"):
        _fit_b(_weak_well(0), b_prior=1.6)
