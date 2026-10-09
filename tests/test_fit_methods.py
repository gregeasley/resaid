"""Fit methods on wells whose true decline is at or below the terminal rate."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from resaid.dca import (
    DCA_FIT_METHOD_DEFAULT,
    DCA_FIT_METHOD_MONOTONE_TWO_STEP,
    decline_curve,
)


def _shallow_wells(seed=0):
    """
    Synthetic hyperbolic wells, mostly with initial decline near or below terminal.
    Seed and draw order are fixed: wells W056 and W080 give monotone-fit EUR
    targets the tail rate cannot reach, which exercises the solver lower bound.
    """
    rng = np.random.default_rng(seed)
    keep = {"W003", "W010", "W056", "W080", "W100"}
    rows = []
    for w in range(120):
        di = rng.choice([0.002, 0.004, 0.006, 0.02, 0.06, 0.15])
        b = rng.uniform(0.3, 1.5)
        qi = rng.uniform(200, 3000)
        n = int(rng.integers(12, 60))
        for t in range(n):
            q = qi * (1 + b * di * t) ** (-1 / b) * rng.lognormal(0, 0.08)
            if f"W{w:03d}" in keep:
                rows.append(
                    {
                        "WELL_ID": f"W{w:03d}",
                        "DATE": pd.Timestamp("2018-01-01") + pd.DateOffset(months=t),
                        "OIL": q,
                        "GAS": q * 2,
                        "WATER": q * 0.5,
                    }
                )
    return pd.DataFrame(rows)


@pytest.mark.parametrize("fit_method", [DCA_FIT_METHOD_DEFAULT, DCA_FIT_METHOD_MONOTONE_TWO_STEP])
def test_shallow_decline_fits_are_physical(fit_method):
    dca = decline_curve(fit_method=fit_method)
    dca.STAT_FILE = None
    dca.dataframe = _shallow_wells()
    dca.date_col = "DATE"
    dca.uid_col = "WELL_ID"
    dca.oil_col = "OIL"
    dca.gas_col = "GAS"
    dca.water_col = "WATER"
    dca.backup_decline = True
    dca.run_DCA()
    dca.generate_oneline(num_months=600)

    params = dca.params_dataframe
    assert len(params) == dca.dataframe["WELL_ID"].nunique()
    assert params[["qi", "di", "b"]].notna().all().all()
    if fit_method == DCA_FIT_METHOD_MONOTONE_TWO_STEP:
        # Solved declines are never reported below the terminal decline.
        assert (params["di"] >= dca.MIN_DECLINE_RATE - 1e-15).all()

    one = dca.oneline_dataframe.set_index("UID")
    peak = dca.dataframe.groupby("WELL_ID")["OIL"].max()
    for uid, eur in one["OIL"].items():
        # Never more than a well holding its peak rate and declining at the
        # terminal rate (guards against runaway tails).
        assert 0 < eur <= 1.5 * peak[uid] / dca.MIN_DECLINE_RATE
