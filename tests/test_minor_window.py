"""Three-phase mode: minor phases start their fit window where the major phase's does."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from test_step_changes import _arps

from resaid.dca import decline_curve


def _well(months=72, spike_at=60, seed=1):
    """Gas (major) on a long steady decline; oil (minor) with a step up near the end."""
    rng = np.random.default_rng(seed)
    t = np.arange(months, dtype=float)
    gas = _arps(60000, 0.06, 1.0, t) * rng.lognormal(0, 0.03, months)
    oil = _arps(900, 0.05, 1.0, t)
    oil[spike_at:] = oil[spike_at] * 3.0 * _arps(1.0, 0.25, 1.0, t[spike_at:] - spike_at)
    return gas, oil * rng.lognormal(0, 0.03, months)


def _fit(gas, oil, **attrs):
    df = pd.DataFrame({
        "UID": "W1",
        "DATE": [pd.Timestamp("2018-01-01") + pd.DateOffset(months=i) for i in range(len(gas))],
        "OIL": oil, "GAS": gas, "WATER": 0.0, "MAJOR": "GAS",
    })
    d = decline_curve()
    d.STAT_FILE = None
    d.three_phase_mode = True
    d.dataframe = df
    d.date_col, d.uid_col, d.phase_col = "DATE", "UID", "MAJOR"
    d.oil_col, d.gas_col, d.water_col = "OIL", "GAS", "WATER"
    for k, v in attrs.items():
        setattr(d, k, v)
    d.run_DCA()
    return d.params_dataframe.set_index("phase")[["qi", "di", "b", "t0"]].astype(float)


def test_minor_phase_uses_major_window():
    gas, oil = _well()
    on = _fit(gas, oil)
    off = _fit(gas, oil, minor_window_from_major=False)
    # On its own, oil's step up starts its window at the spike (month 60+).
    assert off["t0"].to_dict()["OIL"] >= 60
    # With the major's window, oil is fit from the gas window start (the first peak, month 0).
    assert on["t0"].to_dict()["OIL"] < 60
    # The major phase itself is unchanged.
    assert on.loc["GAS"].to_numpy() == pytest.approx(off.loc["GAS"].to_numpy())
