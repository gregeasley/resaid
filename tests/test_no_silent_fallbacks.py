"""Settings are applied or rejected, and fallbacks are reported instead of silent."""

from __future__ import annotations

import importlib
import sqlite3
import warnings

import numpy as np
import pandas as pd
import pytest

from resaid import ARIESDatabase, decline_curve, well_econ

# The module (the package re-exports the class under the same name).
dc_mod = importlib.import_module("resaid.dca.decline_curve")

# --- database interface ------------------------------------------------------------------


@pytest.fixture
def db(tmp_path):
    placeholder = tmp_path / "test.accdb"
    placeholder.touch()
    db = ARIESDatabase(placeholder)
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE AC_PRODUCT (PROPNUM TEXT, P_DATE TEXT, OIL REAL, GAS REAL, WATER REAL)")
    rows = []
    for t in range(24):
        q = 1000.0 * (1 + 0.1 * t) ** -1.0
        date = (pd.Timestamp("2022-01-01") + pd.DateOffset(months=t)).strftime("%Y-%m-%d")
        rows.append(("W1", date, q, q * 3.0, q * 0.5))
    conn.executemany("INSERT INTO AC_PRODUCT VALUES (?, ?, ?, ?, ?)", rows)
    db.connection = conn
    yield db
    db.close()


def _data(db):
    return db.prepare_data_for_dca(header_columns={})


def test_run_dca_analysis_applies_settings(db):
    results = db.run_dca_analysis(
        _data(db), three_phase_mode=False, fit_method="monotone_two_step", detect_step_changes=False
    )
    dca = results["W1"]
    assert dca.fit_method == "monotone_two_step" and dca.detect_step_changes is False


def test_run_dca_analysis_rejects_unknown_setting_before_running(db):
    with pytest.raises(AttributeError, match="outlier_correction"):
        db.run_dca_analysis(_data(db), OUTLIER_CORRECTION=False)


def test_prepare_data_rejects_unknown_argument(db):
    with pytest.raises(TypeError, match="header_colums"):
        db.prepare_data_for_dca(header_colums={})


# --- economics -----------------------------------------------------------------------------


def _econ(header=None, **attrs):
    t = np.arange(1, 25)
    flow = pd.DataFrame({"UID": np.repeat(["W1", "W2"], len(t)), "T_INDEX": np.tile(t, 2),
                         "MAJOR": "OIL", "OIL": 100.0, "GAS": 0.0, "WATER": 0.0})
    e = well_econ()
    e.flowstreams = flow
    e.flowstream_uwi_col, e.flowstream_t_index = "UID", "T_INDEX"
    e.discount_rate = 0.0
    e.oil_pri = 50.0
    e.royalty = 0.2
    if header is not None:
        e.header_data = pd.DataFrame(header)
        e.header_uwi_col = "UID"
    for name, value in attrs.items():
        setattr(e, name, value)
    return e


def test_well_missing_from_header_warns():
    e = _econ({"UID": ["W1"], "CAPEX": [1000.0]}, capex_col="CAPEX")
    with pytest.warns(UserWarning, match="Well W2 is not in header_data; using defaults for capex_col"):
        e.generate_cashflow()


def test_blank_header_value_warns():
    e = _econ({"UID": ["W1", "W2"], "WI": [1.0, np.nan], "NRI": [0.8, 0.75]}, wi_col="WI", nri_col="NRI")
    with pytest.warns(UserWarning, match="Well W2: WI is blank in header_data; using the scalar royalty"):
        flow = e.well_flowstream("W2")
    assert flow["royalty"].iloc[0] == pytest.approx(0.2 * 100 * 50)
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        w1 = e.well_flowstream("W1")
    assert w1["royalty"].iloc[0] == pytest.approx(0.2 * 100 * 50)  # 1 - NRI/WI


def test_flat_capex_without_header_data():
    # capex_val used to be charged only when the well was in header_data.
    flow = _econ(capex_val=5000.0).well_flowstream("W1")
    assert flow["capex"].tolist()[:2] == [5000.0, 0.0]


@pytest.mark.parametrize("attrs, message", [
    ({"scale_forecast": True}, "Set scale_column"),
    ({"scale_capex": True, "scale_column": "LEN"}, "Set capex_val"),
    ({"wi_col": "WI"}, "Set wi_col and nri_col together"),
    ({"owned_royalty_col": "ORI", "royalty_col": "ROY"}, "owned_royalty_col is used only with"),
    ({"wi_col": "WI", "nri_col": "NRI", "royalty_col": "ROY"}, "royalty_col is not used"),
])
def test_settings_that_would_be_ignored_raise(attrs, message):
    header = {"UID": ["W1", "W2"], "WI": 1.0, "NRI": 0.8, "ROY": 0.2, "ORI": 0.0, "LEN": 5280.0}
    e = _econ(header, **attrs)
    with pytest.raises(ValueError, match=message):
        e.generate_cashflow()


def test_roi_is_nan_without_capex():
    e = _econ()
    e.generate_indicators()
    assert e.indicators is not None and e.indicators["ROI"].isna().all()
    e = _econ(capex_val=1000.0)
    e.generate_indicators()
    assert e.indicators is not None and np.isfinite(e.indicators["ROI"]).all()


# --- three-phase major phase -----------------------------------------------------------------


def _three_phase(gas_factor, phase=None):
    rows = []
    for t in range(24):
        q = 1000.0 * (1 + 0.1 * t) ** -1.0
        rows.append({"UID": "W1", "DATE": pd.Timestamp("2022-01-01") + pd.DateOffset(months=t),
                     "OIL": q, "GAS": q * gas_factor, "WATER": q * 0.5})
    d = decline_curve()
    d.STAT_FILE = None
    d.three_phase_mode = True
    d.dataframe = pd.DataFrame(rows)
    d.date_col, d.uid_col, d.oil_col, d.gas_col, d.water_col = "DATE", "UID", "OIL", "GAS", "WATER"
    if phase is not None:
        d.dataframe["PHASE"] = phase
        d.phase_col = "PHASE"
    d.run_DCA()
    d.generate_oneline()
    return d


@pytest.mark.parametrize("gas_factor, phase, expected", [
    (1.0, None, "OIL"),     # EUR GOR 1 Mcf/bbl
    (10.0, None, "GAS"),    # EUR GOR 10 Mcf/bbl
    (10.0, "OIL", "OIL"),   # phase_col wins
])
def test_three_phase_major(gas_factor, phase, expected):
    d = _three_phase(gas_factor, phase)
    assert set(d._require_flowstream()["MAJOR"]) == {expected}
    assert d.oneline_dataframe["MAJOR"].tolist() == [expected]


def test_three_phase_flowstream_supports_econ_delays():
    d = _three_phase(1.0)
    e = well_econ()
    e.flowstreams = d._require_flowstream().reset_index()
    e.flowstream_uwi_col, e.flowstream_t_index = "UID", "T_INDEX"
    e.discount_rate = 0.0
    e.spud_to_online = 2
    assert e.well_flowstream("W1")["OIL"].tolist()[:2] == [0.0, 0.0]


# --- DCA fallbacks and fit window ------------------------------------------------------------


def _single_well(y, three_phase=False):
    dates = [pd.Timestamp("2020-01-01") + pd.DateOffset(months=i) for i in range(len(y))]
    d = decline_curve()
    d.STAT_FILE = None
    d.three_phase_mode = three_phase
    d.dataframe = pd.DataFrame({"UID": "W1", "DATE": dates, "OIL": y, "GAS": np.asarray(y) * 0.5,
                                "WATER": np.asarray(y) * 0.2})
    d.date_col, d.uid_col, d.oil_col, d.gas_col, d.water_col = "DATE", "UID", "OIL", "GAS", "WATER"
    return d


@pytest.mark.parametrize("fit_method", ["default", "monotone_two_step"])
def test_months_before_the_window_do_not_affect_the_fit(fit_method):
    # Ramp months before the peak are outside the fit window: changing them (below the
    # peak) must not change the fitted curve.
    t = np.arange(36, dtype=float)
    y = 1000.0 * (1 + 0.12 * (t - 3)) ** -1.0
    y[:3] = [200.0, 400.0, 700.0]
    params = []
    for ramp in ([200.0, 400.0, 700.0], [50.0, 300.0, 900.0]):
        y2 = y.copy()
        y2[:3] = ramp
        d = _single_well(y2)
        d.fit_method = fit_method
        d.run_DCA()
        params.append(d.params_dataframe[["qi", "di", "b", "t0"]].to_numpy(dtype=float))
    np.testing.assert_allclose(params[0], params[1], rtol=1e-9)


def test_outlier_screening_failure_warns(monkeypatch):
    def broken_ols(*args, **kwargs):
        raise np.linalg.LinAlgError("singular")

    monkeypatch.setattr(dc_mod.sm.formula, "ols", broken_ols)
    t = np.arange(24, dtype=float)
    d = _single_well(1000.0 * (1 + 0.1 * t) ** -1.0)
    with pytest.warns(UserWarning, match="Outlier screening failed"):
        d.run_DCA()
