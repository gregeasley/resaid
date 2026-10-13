"""Running DCA steps more than once on the same object (e.g. after changing a setting)."""

from __future__ import annotations

import pandas as pd
import pytest

from resaid.dca import decline_curve


@pytest.fixture
def dca():
    rows = []
    for w in range(3):
        for t in range(24):
            q = (800 + 300 * w) * (1 + 0.1 * t) ** -1
            rows.append({"UID": f"W{w}", "DATE": pd.Timestamp("2022-01-01") + pd.DateOffset(months=t),
                         "OIL": q, "GAS": q * 2, "WATER": q / 2})
    d = decline_curve()
    d.STAT_FILE = None
    d.dataframe = pd.DataFrame(rows)
    d.date_col, d.uid_col, d.oil_col, d.gas_col, d.water_col = "DATE", "UID", "OIL", "GAS", "WATER"
    return d


def test_run_dca_three_times(dca):
    # A third run used to add a duplicate MIN_DATE_MIN column, which pandas 3 rejects.
    for _ in range(3):
        dca.run_DCA()
    assert [c for c in dca.dataframe.columns if c.startswith("MIN_DATE")] == ["MIN_DATE"]


def test_generate_oneline_repeatedly(dca):
    # A second oneline used to merge MIN_DATE into the parameters again (KeyError 'MIN_DATE').
    dca.run_DCA()
    dca.generate_oneline(denormalize=True)
    first = dca.oneline_dataframe.copy()
    for _ in range(2):
        dca.generate_oneline(denormalize=True)
    pd.testing.assert_frame_equal(dca.oneline_dataframe, first)
    assert [c for c in dca.params_dataframe.columns if "MIN_DATE" in c] == ["MIN_DATE"]


def test_switch_modes_and_rerun(dca):
    dca.run_DCA()
    dca.generate_oneline(denormalize=True)
    dca.three_phase_mode = True
    dca.run_DCA()
    dca.generate_oneline(denormalize=True)
    assert {"IPO", "IPG", "IPW"} <= set(dca.oneline_dataframe.columns)
    dca.three_phase_mode = False
    dca.run_DCA()
    dca.generate_oneline(denormalize=True)
    dca.generate_typecurve(return_params=True)
    assert "MAJOR" in dca.oneline_dataframe.columns
