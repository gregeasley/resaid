"""
ARIES export uses the decline *revised* to the export start (L3M_START), not the
initial decline at the fitted T0_DATE.
"""

from __future__ import annotations

import pandas as pd
import pytest
from aries_helpers import fit, make_production, parse_aries, revised_aries_de

SCENARIO = "TEST"
DMIN = 6


@pytest.fixture(scope="module")
def dca():
    return fit(make_production(months=24), True)


def test_export_start_is_after_t0(dca):
    one = dca.oneline_dataframe
    last = pd.to_datetime(dca.dataframe[dca.date_col]).groupby(dca.dataframe[dca.uid_col]).max()
    gaps = [
        12 * (last[u].year - pd.Timestamp(t).year) + (last[u].month - pd.Timestamp(t).month)
        for u, t in zip(one["UID"], one["T0_DATE"])
    ]
    assert all(g >= 0 for g in gaps)
    assert any(g > 0 for g in gaps), "data should give the revision a non-zero interval"


def test_hyperbolic_decline_is_revised_to_export_start(dca, tmp_path):
    path = tmp_path / "aries.txt"
    dca.generate_aries_export(file_path=str(path), scenario=SCENARIO, dmin=DMIN, write_water=True)
    wells = parse_aries(path, SCENARIO)
    one = dca.oneline_dataframe.set_index("UID")

    checked = 0
    for uid, w in wells.items():
        o = one.loc[uid]
        start = pd.Timestamp(pd.to_datetime(w["start"], format="%m/%Y"))
        t0 = pd.Timestamp(o["T0_DATE"])
        dt = 12 * (start.year - t0.year) + (start.month - t0.month)
        for label, (de_col, b_col) in {
            "OIL": ("DO", "BO"),
            "GAS": ("DG", "BG"),
            "WTR": ("DW", "BW"),
        }.items():
            line = w["phases"].get(label)
            if line is None or line["kind"] != "hyperbolic":
                continue
            expected = revised_aries_de(o[de_col], o[b_col], dt)
            assert line["de"] == pytest.approx(round(expected, 2))
            if dt > 0:
                # Hyperbolic decline flattens with time: revised < initial.
                assert line["de"] < round(revised_aries_de(o[de_col], o[b_col], 0), 2)
            checked += 1
    assert checked > 0
