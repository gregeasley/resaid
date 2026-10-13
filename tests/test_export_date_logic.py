"""
Mosaic and PhdWin exports must anchor declines on the fitted ``T0_DATE``.

Each exported decline is the fitted Arps decline advanced from ``T0_DATE`` to the
export start date. These tests recompute that independently from the oneline
parameters and compare against the written files.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from resaid.dca import decline_curve

PHASE_COLS = {  # three-phase oneline columns per exported product
    "Oil": ("DO", "BO"),
    "Gas": ("DG", "BG"),
    "Water": ("DW", "BW"),
}


def _make_production(seed=0):
    rng = np.random.default_rng(seed)
    rows = []
    for w, (q0, d) in enumerate([(1000, 0.10), (2500, 0.06), (600, 0.15)]):
        for t in range(24):
            q = q0 * np.exp(-d * t) * rng.lognormal(0, 0.05)
            rows.append(
                {
                    "API_UWI": f"WELL{w:03d}",
                    "ProducingMonth": pd.Timestamp("2020-01-01") + pd.DateOffset(months=t),
                    "LiquidsProd_BBL": q,
                    "GasProd_MCF": q * 0.5,
                    "WaterProd_BBL": q * 0.8,
                    "MAJOR": "OIL",
                }
            )
    return pd.DataFrame(rows)


@pytest.fixture(params=[False, True], ids=["ratio", "three_phase"])
def fitted_dca(request):
    dca = decline_curve()
    dca.STAT_FILE = None
    dca.dataframe = _make_production()
    dca.date_col = "ProducingMonth"
    dca.uid_col = "API_UWI"
    dca.oil_col = "LiquidsProd_BBL"
    dca.gas_col = "GasProd_MCF"
    dca.water_col = "WaterProd_BBL"
    dca.phase_col = "MAJOR"
    dca.three_phase_mode = request.param
    dca.run_DCA()
    dca.generate_oneline(denormalize=True)
    return dca


def _months(a, b):
    a, b = pd.Timestamp(a), pd.Timestamp(b)
    return 12 * (a.year - b.year) + (a.month - b.month)


def _de_b(dca, oneline_row, product):
    if dca.three_phase_mode:
        de_col, b_col = PHASE_COLS[product]
        return float(oneline_row[de_col]), float(oneline_row[b_col])
    return float(oneline_row["DE"]), float(oneline_row["B"])


def _last_month_by_well(dca):
    df = dca.dataframe
    return pd.to_datetime(df[dca.date_col]).groupby(df[dca.uid_col]).max()


def test_oneline_has_t0_date(fitted_dca):
    one = fitted_dca.oneline_dataframe
    assert "T0_DATE" in one.columns
    t0 = pd.to_datetime(one["T0_DATE"])
    assert t0.notna().all()
    last = _last_month_by_well(fitted_dca)
    first = pd.to_datetime(fitted_dca.dataframe[fitted_dca.date_col]).min()
    for uid, t in zip(one["UID"], t0):
        assert first <= t <= last[uid]


def test_mosaic_export_uses_t0_date(fitted_dca, tmp_path):
    dmin = 8
    path = tmp_path / "mosaic.xlsx"
    fitted_dca.generate_mosaic_export(str(path), dmin=dmin)
    out = pd.read_excel(path)

    one = fitted_dca.oneline_dataframe.set_index("UID")
    last = _last_month_by_well(fitted_dca)
    assert set(out["Entity Name"]) == set(one.index)
    assert set(out["Product Type"]) == {"Oil", "Gas", "Water"}

    revised_somewhere = False
    for _, r in out.iterrows():
        o = one.loc[r["Entity Name"]]
        start = pd.Timestamp(r["Start Date T0  (y-m-d)"])
        assert start == last[r["Entity Name"]]                             # the last actual month

        de, b = _de_b(fitted_dca, o, r["Product Type"])
        dt = _months(start, o["T0_DATE"])
        assert dt >= 0
        ai = de / (1 + b * de * dt)
        expected = max(dmin, (1 - (12 * ai * b + 1) ** (-1 / b)) * 100)
        assert r["Secant Effective Decline Desi (%)"] == pytest.approx(expected, rel=1e-9)
        assert r["Exponent N, b"] == pytest.approx(b, rel=1e-9)

        unrevised = (1 - (12 * de * b + 1) ** (-1 / b)) * 100
        if dt > 0 and expected > dmin:
            assert expected < unrevised
            revised_somewhere = True
    assert revised_somewhere, "test data should exercise a T0_DATE before the export start"


def test_phdwin_export_uses_t0_date(fitted_dca, tmp_path):
    dmin = 6
    path = tmp_path / "phdwin.csv"
    fitted_dca.generate_phdwin_export(str(path), dmin=dmin)
    out = pd.read_csv(path, parse_dates=["StartDate"])

    one = fitted_dca.oneline_dataframe.set_index("UID")
    last = _last_month_by_well(fitted_dca)
    assert set(out["UniqueId"]) == set(one.index)

    for _, r in out.iterrows():
        o = one.loc[r["UniqueId"]]
        # Start at the middle of the last three producing months.
        assert r["StartDate"] == last[r["UniqueId"]] - pd.DateOffset(months=1)

        de, b = _de_b(fitted_dca, o, r["Product"])
        dt = _months(r["StartDate"], o["T0_DATE"])
        revised = 100 * (1 - np.exp(-12 * de / (1 + b * de * dt)))
        assert r["Decl"] == pytest.approx(max(revised, dmin), rel=1e-9)
        assert r["DeclMin"] == dmin
        assert r["Qi"] > 0
