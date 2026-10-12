"""First-peak detection when a well's highest month is its first month."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from resaid.dca import decline_curve

# Gas history of a well that peaks in its first month, with a minor bump in month 8.
FIRST_MONTH_PEAK = np.array([401409, 322179, 271933, 259007, 237726, 233779, 214821, 187814,
                             198849, 183177, 180589, 167298, 164152, 155614], dtype=float)


@pytest.fixture
def dca():
    d = decline_curve()
    d.STAT_FILE = None
    return d


@pytest.mark.parametrize("y, expected", [
    (FIRST_MONTH_PEAK, 0),                              # first month is the peak, later bump ignored
    ([10, 50, 80, 70, 60, 65, 50], 2),                  # ramp-up: first local maximum is the peak
    ([10, 50, 80, 70, 60, 85, 50], 2),                  # a later, higher bump is not the first peak
    ([100, 90, 80, 70], 0),                             # no local maximum
    ([10, 20, 30, 40], 0),                              # rising, no local maximum: unchanged (0)
    ([100, 60, np.nan, 70, 50], 0),                     # NaNs do not hide the first-month peak
])
def test_first_peak_index(dca, y, expected):
    assert dca._first_peak_index(y) == expected


def _fit(y, fit_method="default"):
    df = pd.DataFrame({
        "UID": "W1",
        "DATE": [pd.Timestamp("2025-07-01") + pd.DateOffset(months=i) for i in range(len(y))],
        "OIL": 0.0, "GAS": y, "WATER": 0.0,
    })
    d = decline_curve(fit_method=fit_method)
    d.STAT_FILE = None
    d.three_phase_mode = True
    d.dataframe = df
    d.date_col, d.uid_col = "DATE", "UID"
    d.oil_col, d.gas_col, d.water_col = "OIL", "GAS", "WATER"
    d.run_DCA()
    p = d.params_dataframe
    return p[p["phase"] == "GAS"].iloc[0]


def test_first_month_peak_fit_uses_whole_decline():
    r = _fit(FIRST_MONTH_PEAK)
    # Before the fix the default fit started at the month-8 bump (t0 >= 8) and ignored the
    # first 8 months of decline.
    assert r.t0 < 8
    t = np.arange(len(FIRST_MONTH_PEAK), dtype=float)
    q = decline_curve().arps_decline(t, r.qi, r.di, r.b, r.t0)
    early = slice(1, 8)
    assert np.exp(np.abs(np.log(q[early] / FIRST_MONTH_PEAK[early])).mean()) < 1.25
