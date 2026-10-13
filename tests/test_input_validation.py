"""Unknown attribute names and missing inputs raise clear errors."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from resaid import ARIESDatabase, decline_curve, decline_solver, npv_calc, well_econ

# --- strict attributes -------------------------------------------------------------------

@pytest.fixture
def dca():
    d = decline_curve()
    d.STAT_FILE = None
    return d


@pytest.mark.parametrize(
    "name, suggestion",
    [
        ("OUTLIER_CORRECTION", "outlier_correction"),
        ("min_hb", "min_h_b"),
        ("SET_LENGTH", "STANDARD_LENGTH"),
        ("DEFAULT_B", "default_b_factor"),
        ("datecol", "date_col"),
    ],
)
def test_decline_curve_rejects_unknown_attribute(dca, name, suggestion):
    with pytest.raises(AttributeError, match=f"no attribute '{name}'.*'{suggestion}'"):
        setattr(dca, name, 1)
    assert name not in vars(dca)


def test_suggestions_exclude_methods(dca):
    with pytest.raises(AttributeError) as exc:
        dca.OUTLIER_CORRECTION = False
    assert "outlier_detection" not in str(exc.value)


def test_known_attributes_and_properties_can_be_set(dca):
    dca.min_h_b = 0.5
    dca.outlier_correction = False
    dca.date_col = "DATE"          # property setter
    dca.STAT_FILE = None           # property setter
    assert dca.min_h_b == 0.5 and dca.date_col == "DATE"


@pytest.mark.parametrize(
    "factory, name, suggestion",
    [
        (lambda: well_econ(), "discount", "discount_rate"),
        (lambda: well_econ(), "oil_price", "oil_pri"),
        (lambda: decline_solver(qi=1000, qf=1, eur=1e5, b=1.0), "Dmin", "dmin"),
        (lambda: npv_calc([1.0, 2.0]), "cash_flow", "_cashflow"),
    ],
)
def test_other_classes_reject_unknown_attribute(factory, name, suggestion):
    obj = factory()
    with pytest.raises(AttributeError, match=f"no attribute '{name}'.*'{suggestion}'"):
        setattr(obj, name, 1)


def test_database_rejects_unknown_attribute(tmp_path):
    path = tmp_path / "x.accdb"
    path.touch()
    db = ARIESDatabase(path)
    with pytest.raises(AttributeError, match="table_mapping"):
        db.table_maping = {}


def test_subclass_can_add_attributes_in_init():
    class Custom(decline_curve):
        def __init__(self):
            super().__init__()
            self.my_setting = 1

    c = Custom()
    c.STAT_FILE = None
    c.my_setting = 2
    with pytest.raises(AttributeError):
        c.my_setting_typo = 3


def test_subclass_can_opt_out():
    class Loose(decline_curve):
        _strict_attributes = False

    c = Loose()
    c.STAT_FILE = None
    c.anything = 1
    assert c.anything == 1


# --- decline_curve inputs ----------------------------------------------------------------

def _production():
    dates = pd.date_range("2022-01-01", periods=24, freq="MS")
    q = 1000.0 * (1 + 0.1 * np.arange(24)) ** -1.0
    return pd.DataFrame({"WELL": "W1", "DATE": dates, "OIL": q, "GAS": q * 2, "WATER": q / 2})


def _configured(df=None):
    d = decline_curve()
    d.STAT_FILE = None
    d.dataframe = _production() if df is None else df
    d.date_col, d.uid_col = "DATE", "WELL"
    d.oil_col, d.gas_col, d.water_col = "OIL", "GAS", "WATER"
    return d


def test_run_without_dataframe(dca):
    with pytest.raises(ValueError, match="set dca.dataframe"):
        dca.run_DCA()


@pytest.mark.parametrize("method", ["generate_oneline", "generate_flowstream", "generate_typecurve", "qi_overwrite"])
def test_outputs_without_dataframe(dca, method):
    with pytest.raises(ValueError, match="set dca.dataframe"):
        getattr(dca, method)()


def test_run_with_unset_column_names():
    d = decline_curve()
    d.STAT_FILE = None
    d.dataframe = _production()
    d.date_col = "DATE"
    with pytest.raises(ValueError, match="uid_col, oil_col, gas_col, water_col"):
        d.run_DCA()


def test_run_with_missing_column_lists_available():
    d = _configured()
    d.oil_col = "OIL_BBL"
    with pytest.raises(ValueError, match=r"oil_col='OIL_BBL'.*Available columns: WELL, DATE, OIL"):
        d.run_DCA()


def test_run_with_missing_optional_column():
    d = _configured()
    d.length_col = "LATERAL"
    with pytest.raises(ValueError, match="length_col='LATERAL'"):
        d.run_DCA()


def test_run_with_empty_dataframe():
    d = _configured(_production().iloc[0:0])
    with pytest.raises(ValueError, match="no rows"):
        d.run_DCA()


def test_valid_inputs_still_run():
    d = _configured()
    d.run_DCA()
    d.generate_oneline()
    assert len(d.oneline_dataframe) == 1


# --- decline_solver inputs ---------------------------------------------------------------

@pytest.mark.parametrize(
    "kwargs, needed",
    [
        ({"qf": 1}, "eur"),
        ({"qi": 1000}, "de"),
        ({"qi": 1000, "qf": 1, "eur": 60000}, "b"),
    ],
)
def test_solver_names_missing_input(kwargs, needed):
    with pytest.raises(ValueError, match=f"needs '{needed}'.*given: "):
        decline_solver(**kwargs).solve()


def test_solver_results_are_floats():
    out = decline_solver(qi=1000, qf=1, eur=60000, b=1.2).solve()
    assert all(isinstance(v, float) for v in out[:5])
    assert isinstance(out[5], bool) and isinstance(out[6], float)


# --- well_econ inputs --------------------------------------------------------------------

def _flow(t_name="T_INDEX", major=True):
    t = np.arange(1, 61)
    q = 1000.0 * (1 + 0.1 * t) ** -1.0
    df = pd.DataFrame({"UID": "W1", t_name: t, "OIL": q, "GAS": q * 2, "WATER": q / 2})
    if major:
        df["MAJOR"] = "OIL"
    return df


def _econ(flow=None, **attrs):
    e = well_econ()
    e.flowstreams = _flow() if flow is None else flow
    e.flowstream_uwi_col = "UID"
    e.flowstream_t_index = "T_INDEX"
    e.oil_pri = 70.0
    e.gas_pri = 3.0
    e.discount_rate = 0.10 / 12
    for k, v in attrs.items():
        setattr(e, k, v)
    return e


def test_econ_without_flowstreams():
    with pytest.raises(ValueError, match="set econ.flowstreams"):
        well_econ().generate_cashflow()


def test_econ_without_discount_rate():
    e = _econ(discount_rate=None)
    with pytest.raises(ValueError, match="discount_rate"):
        e.generate_cashflow()


def test_econ_indexed_flowstream_hints_reset_index():
    e = _econ(flow=_flow().set_index(["UID", "T_INDEX"]))
    with pytest.raises(ValueError, match=r"missing column\(s\): UID, T_INDEX.*reset_index"):
        e.generate_indicators()


def test_econ_header_column_requires_header_data():
    e = _econ(wi_col="WI")
    with pytest.raises(ValueError, match="header_data is required when wi_col"):
        e.generate_cashflow()


def test_econ_missing_header_column_lists_available():
    header = pd.DataFrame({"UID": ["W1"], "WI": [1.0], "NRI": [0.8]})
    e = _econ(header_data=header, header_uwi_col="UID", wi_col="WI", nri_col="NRI", capex_col="CAPX")
    with pytest.raises(ValueError, match=r"capex_col='CAPX'.*Available columns: UID, WI, NRI"):
        e.generate_cashflow()


def test_econ_timing_requires_major_column():
    e = _econ(flow=_flow(major=False), spud_to_online=3)
    with pytest.raises(ValueError, match="MAJOR is required"):
        e.generate_cashflow()


def test_econ_custom_time_index_name():
    flow = _flow(t_name="MONTH")
    e = _econ(flow=flow, flowstream_t_index="MONTH")
    cashflow = e.generate_cashflow()
    e.generate_indicators()
    assert len(cashflow) == 60
    assert e.indicators["DCF"].iloc[0] > 0


def test_econ_valid_inputs_match_default_time_index():
    a = _econ().generate_cashflow()["dcf"].to_numpy()
    b = _econ(flow=_flow(t_name="MONTH"), flowstream_t_index="MONTH").generate_cashflow()["dcf"].to_numpy()
    np.testing.assert_allclose(a, b)


# --- database connection -----------------------------------------------------------------

@pytest.fixture
def unreachable_db(tmp_path, monkeypatch):
    """An ARIES 'database' that is not a real Access file; fallbacks are stubbed out."""
    path = tmp_path / "not_access.accdb"
    path.write_bytes(b"not an access database")
    db = ARIESDatabase(path)
    monkeypatch.setattr(db, "_try_jpype_connection", lambda: False)
    monkeypatch.setattr(db, "_try_external_tools", lambda: False)
    return db


def test_connection_failure_explains_why(unreachable_db):
    assert unreachable_db.connect() is False
    with pytest.raises(ConnectionError, match="pyodbc"):
        unreachable_db.get_tables()


def test_probe_without_connection_is_not_success(unreachable_db, monkeypatch):
    # mdbtools can read the file but gives no connection: not a successful connect().
    monkeypatch.setattr(unreachable_db, "_try_external_tools", lambda: True)
    assert unreachable_db.connect() is False
    with pytest.raises(ConnectionError):
        unreachable_db.read_table_data("AC_PRODUCT")
