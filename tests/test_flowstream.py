"""Flowstream = actual history, then the projection; oneline HIST / PROJ / EUR volumes."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from resaid.dca import decline_curve
from resaid.econ import well_econ

MONTHS = 36
STEP = 24  # restim at month 24: the fit starts late, so t0 is far from month 0


def _wells():
    rows = []
    for w, (q0, step) in enumerate([(900.0, None), (1500.0, STEP)]):
        for t in range(MONTHS):
            if t == 10 and w == 0:
                continue  # a month missing from the data
            q = q0 * (1 + 0.15 * t) ** -1.0
            if step is not None and t >= step:
                q = 2.5 * q0 * (1 + 0.15 * (t - step)) ** -1.0
            rows.append({"UID": f"W{w}", "DATE": pd.Timestamp("2021-01-01") + pd.DateOffset(months=t),
                         "OIL": q, "GAS": q * 1.5, "WATER": q * 0.4, "LEN": 10560.0})
    return pd.DataFrame(rows)


def _dca(three_phase):
    d = decline_curve()
    d.STAT_FILE = None
    d.dataframe = _wells()
    d.date_col, d.uid_col, d.oil_col, d.gas_col, d.water_col = "DATE", "UID", "OIL", "GAS", "WATER"
    d.length_col = "LEN"
    d.three_phase_mode = three_phase
    d.run_DCA()
    return d


@pytest.fixture(params=[False, True], ids=["ratio", "three_phase"])
def dca(request):
    return _dca(request.param)


def test_history_then_projection(dca):
    dca.generate_flowstream(num_months=120, denormalize=True, actual_dates=True)
    flow = dca.flowstream_dataframe.reset_index()
    raw = dca.dataframe
    for uid, well in flow.groupby("UID"):
        actual = raw[raw["UID"] == uid].set_index("T_INDEX")
        n_hist = int(actual.index.max()) + 1
        hist = well[well["HISTORICAL"]]
        assert hist["T_INDEX"].tolist() == list(range(1, n_hist + 1))
        # Actual volumes at T_INDEX = month + 1; a month missing from the data is 0.
        expected = actual["OIL"].reindex(range(n_hist), fill_value=0.0).to_numpy()
        np.testing.assert_allclose(hist["OIL"].to_numpy(), expected)
        assert hist["P_DATE"].notna().sum() == len(actual)
        proj = well[~well["HISTORICAL"]]
        assert proj["T_INDEX"].iloc[0] == n_hist + 1 and proj["P_DATE"].isna().all()
        assert (proj["OIL"] > 0).all()


def test_projection_never_exceeds_its_initial_rate(dca):
    # Before t0 the curve projected backward rises toward a pole; it must never appear.
    dca.generate_flowstream(num_months=120, denormalize=False)
    flow = dca.flowstream_dataframe.reset_index()
    params = dca.params_dataframe
    qcol = "phase" if dca.three_phase_mode else "major"
    for _, p in params.iterrows():
        proj = flow[(flow["UID"] == p["UID"]) & ~flow["HISTORICAL"]][p[qcol]]
        assert proj.max() <= p["qi"] * (1 + 1e-9)


def test_projection_is_zero_before_t0():
    d = _dca(False)
    t = np.arange(1, 40)
    q = d._projection(t, 1000.0, 0.1, 1.0, 20.0)
    assert (q[t - 1 < 20] == 0).all() and (q[t - 1 >= 20] > 0).all()


def test_oneline_hist_proj_eur(dca):
    dca.generate_oneline(num_months=120, denormalize=True)
    one = dca.oneline_dataframe.set_index("UID")
    raw = dca.dataframe.groupby("UID")[["OIL", "GAS", "WATER"]].sum()
    flow = dca.flowstream_dataframe.reset_index()
    for phase in ("OIL", "GAS", "WATER"):
        np.testing.assert_allclose(one[f"HIST_{phase}"], raw.loc[one.index, phase])
        proj = flow[~flow["HISTORICAL"]].groupby("UID")[phase].sum()
        np.testing.assert_allclose(one[f"PROJ_{phase}"], proj.loc[one.index])
        np.testing.assert_allclose(one[f"EUR_{phase}"], one[f"HIST_{phase}"] + one[f"PROJ_{phase}"])
    assert "OIL" not in one.columns


def test_econ_projection_only():
    d = _dca(False)
    d.generate_flowstream(num_months=120, denormalize=True)
    flow = d._require_flowstream().reset_index()

    def run(projection_only):
        e = well_econ()
        e.flowstreams = flow
        e.flowstream_uwi_col, e.flowstream_t_index = "UID", "T_INDEX"
        e.discount_rate = 0.0
        e.oil_pri = 50.0
        e.projection_only = projection_only
        return e.well_flowstream("W0")

    full, remaining = run(False), run(True)
    w0 = flow[flow["UID"] == "W0"]
    assert len(full) == len(w0)
    assert not remaining["HISTORICAL"].any()
    assert remaining["OIL"].sum() == pytest.approx(w0.loc[~w0["HISTORICAL"], "OIL"].sum())


def test_econ_projection_only_needs_historical_column():
    e = well_econ()
    e.flowstreams = pd.DataFrame({"UID": "A", "T_INDEX": [1, 2], "OIL": 1.0, "GAS": 0.0, "WATER": 0.0})
    e.flowstream_uwi_col, e.flowstream_t_index = "UID", "T_INDEX"
    e.discount_rate = 0.0
    e.projection_only = True
    with pytest.raises(ValueError, match="HISTORICAL"):
        e.well_flowstream("A")
