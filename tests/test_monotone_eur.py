"""
monotone_two_step forecasts must not depend on which of several equally good fits is returned.

For a hyperbolic curve, shifting t0 by d with qi' = qi * (1 + b*di*d) ** (-1/b) and
di' = di / (1 + b*di*d) gives the same curve. The stage-1 fit trades qi against t0 this
way, so different NumPy/SciPy versions return different but equivalent parameters. The
forecast after the post-fit step (the default method's L3M adjustment) must be the same.
"""

from __future__ import annotations

import sys

import numpy as np
import pandas as pd
import pytest

from resaid.dca import DCA_FIT_METHOD_MONOTONE_TWO_STEP, decline_curve

dc_module = sys.modules["resaid.dca.decline_curve"]
HORIZON = 600


def _equivalent(popt, shift):
    qi, di, b, t0 = (float(v) for v in popt)
    factor = 1.0 + b * di * shift
    return np.array([qi * factor ** (-1.0 / b), di / factor, b, t0 + shift])


def _well():
    rng = np.random.default_rng(3)
    t = np.arange(36)
    q = 4000.0 * (1 + 1.1 * 0.12 * t) ** (-1 / 1.1) * rng.lognormal(0, 0.05, len(t))
    return pd.DataFrame({
        "UID": "W1",
        "DATE": [pd.Timestamp("2021-01-01") + pd.DateOffset(months=int(i)) for i in t],
        "OIL": q, "GAS": q, "WATER": q,
    })


def _forecast(monkeypatch, shift):
    """Monthly forecast after the history when the fit returns an equivalent curve."""
    real_curve_fit = dc_module.curve_fit

    def shifted_curve_fit(*args, **kwargs):
        popt, pcov = real_curve_fit(*args, **kwargs)
        return _equivalent(popt, shift), pcov

    monkeypatch.setattr(dc_module, "curve_fit", shifted_curve_fit)
    d = decline_curve(fit_method=DCA_FIT_METHOD_MONOTONE_TWO_STEP)
    d.STAT_FILE = None
    d.dataframe = _well()
    d.date_col, d.uid_col, d.oil_col, d.gas_col, d.water_col = "DATE", "UID", "OIL", "GAS", "WATER"
    d.run_DCA()
    monkeypatch.undo()
    p = d.params_dataframe.iloc[0]
    t = np.arange(36, 36 + HORIZON, dtype=float)
    return np.asarray(d.arps_decline(t, p.qi, p.di, p.b, p.t0), dtype=float)


@pytest.mark.parametrize("shift", [2.0, 6.0])
def test_equivalent_fits_give_same_forecast(monkeypatch, shift):
    base = _forecast(monkeypatch, 0.0)
    shifted = _forecast(monkeypatch, shift)
    assert shifted.sum() == pytest.approx(base.sum(), rel=1e-3)
    np.testing.assert_allclose(shifted[:12], base[:12], rtol=1e-3)
