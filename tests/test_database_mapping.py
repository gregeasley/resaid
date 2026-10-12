"""
Table and column mapping in the database interface.

An in-memory SQLite database stands in for the ARIES file, so these run without
Access drivers. Its AC_PROPERTY table, like real ARIES databases, lacks the default
LATERAL and DAYS_ON columns.
"""

from __future__ import annotations

import sqlite3
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from resaid.database import ARIESDatabase

REPO_ROOT = Path(__file__).resolve().parent.parent
WELLS = ["W1", "W2"]
MONTHS = 24


def _production_rows():
    rows = []
    for w, q0 in zip(WELLS, (1000.0, 600.0)):
        for t in range(MONTHS):
            q = q0 * (1 + 0.1 * t) ** -1.0
            date = (pd.Timestamp("2022-01-01") + pd.DateOffset(months=t)).strftime("%Y-%m-%d")
            rows.append((w, date, q, q * 3.0, q * 0.5))
    return rows


@pytest.fixture
def db(tmp_path):
    """ARIESDatabase backed by an in-memory SQLite copy of a typical ARIES layout."""
    placeholder = tmp_path / "test.accdb"
    placeholder.touch()
    db = ARIESDatabase(placeholder)

    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE AC_PRODUCT (PROPNUM TEXT, P_DATE TEXT, OIL REAL, GAS REAL, WATER REAL)")
    conn.executemany("INSERT INTO AC_PRODUCT VALUES (?, ?, ?, ?, ?)", _production_rows())
    conn.execute(
        "CREATE TABLE AC_PROPERTY (PROPNUM TEXT, MAJOR TEXT, FIELD TEXT, OPERATOR TEXT, LAT_LEN REAL)"
    )
    conn.executemany(
        "INSERT INTO AC_PROPERTY VALUES (?, ?, ?, ?, ?)",
        [("W1", "oil ", "F1", "Op A", 10000.0), ("W2", "GAS", "F2", "Op B", 5280.0)],
    )
    # Production table using reserved words, spaces and mixed case.
    conn.execute('CREATE TABLE "Monthly Prod" ("Well", "DATE", "Oil Prod", "Gas_Prod", "wtr")')
    conn.executemany('INSERT INTO "Monthly Prod" VALUES (?, ?, ?, ?, ?)', _production_rows())
    db.connection = conn
    yield db
    db.close()


def test_default_mapping_skips_missing_header_columns(db):
    """Reporter's case: default header columns absent from AC_PROPERTY."""
    with pytest.warns(UserWarning, match=r"LATERAL \(length\).*DAYS_ON \(dayson\)"):
        data = db.prepare_data_for_dca(production_table="AC_PRODUCT", header_table="AC_PROPERTY")

    assert list(data.columns[:5]) == ["WELL_ID", "DATE", "OIL", "GAS", "WATER"]
    assert {"PHASE", "FIELD", "OPERATOR"} <= set(data.columns)
    assert not {"LENGTH", "DAYSON"} & set(data.columns)
    assert len(data) == len(WELLS) * MONTHS
    # Header fields are merged onto every production row.
    assert data.groupby("WELL_ID")["FIELD"].first().to_dict() == {"W1": "F1", "W2": "F2"}
    assert pd.api.types.is_datetime64_any_dtype(data["DATE"])


def test_user_header_mapping_is_merged(db):
    data = db.prepare_data_for_dca(
        header_columns={"well_id": "PROPNUM", "phase": "MAJOR", "length": "LAT_LEN"}
    )
    lengths = data.groupby("WELL_ID")["LENGTH"].first()
    assert lengths.to_dict() == {"W1": 10000.0, "W2": 5280.0}


def test_user_header_mapping_with_missing_column_raises(db):
    with pytest.raises(ValueError, match=r"no column\(s\): LATERAL_FT \(length\).*Available columns: .*LAT_LEN"):
        db.prepare_data_for_dca(header_columns={"well_id": "PROPNUM", "length": "LATERAL_FT"})


def test_set_header_column_mapping_is_strict(db):
    db.set_header_column_mapping({"well_id": "PROPNUM", "dayson": "DAYS_ON"})
    with pytest.raises(ValueError, match="DAYS_ON"):
        db.prepare_data_for_dca()


def test_skip_missing_header_columns_can_be_requested(db):
    with pytest.warns(UserWarning, match="LATERAL_FT"):
        data = db.prepare_data_for_dca(
            header_columns={"well_id": "PROPNUM", "field": "FIELD", "length": "LATERAL_FT"},
            skip_missing_header_columns=True,
        )
    assert "FIELD" in data.columns and "LENGTH" not in data.columns


def test_header_columns_empty_skips_header(db):
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        data = db.prepare_data_for_dca(header_columns={})
    assert list(data.columns) == ["WELL_ID", "DATE", "OIL", "GAS", "WATER"]


def test_header_requires_well_id(db):
    with pytest.raises(ValueError, match="well_id"):
        db.prepare_data_for_dca(header_columns={"phase": "MAJOR"})


def test_custom_production_table_and_columns(db):
    """Spaces, reserved words and case differences in user-specified names."""
    data = db.prepare_data_for_dca(
        production_table="Monthly Prod",
        production_columns={"well_id": "well", "date": "date", "oil": "Oil Prod",
                            "gas": "Gas_Prod", "water": "WTR"},
        header_columns={},
    )
    assert len(data) == len(WELLS) * MONTHS
    # Columns with PROD in their name stay numeric; only the date column is parsed.
    assert pd.api.types.is_float_dtype(data["OIL"]) and pd.api.types.is_float_dtype(data["GAS"])
    assert pd.api.types.is_datetime64_any_dtype(data["DATE"])


def test_missing_production_column_lists_available(db):
    with pytest.raises(ValueError, match=r"no column\(s\): OIL_BBL \(oil\).*Available columns: PROPNUM"):
        db.prepare_data_for_dca(
            production_columns={"well_id": "PROPNUM", "date": "P_DATE", "oil": "OIL_BBL",
                                "gas": "GAS", "water": "WATER"},
            header_columns={},
        )


def test_unmapped_required_production_field_raises(db):
    with pytest.raises(ValueError, match="water"):
        db.prepare_data_for_dca(
            production_columns={"well_id": "PROPNUM", "date": "P_DATE", "oil": "OIL", "gas": "GAS"},
            header_columns={},
        )


def test_set_table_and_column_mapping(db):
    db.set_table_mapping({"production": "Monthly Prod", "header": "AC_PROPERTY"})
    db.set_column_mapping({"well_id": "Well", "date": "DATE", "oil": "Oil Prod",
                           "gas": "Gas_Prod", "water": "wtr"})
    db.set_header_column_mapping({"well_id": "PROPNUM", "length": "LAT_LEN"})
    data = db.prepare_data_for_dca()
    assert data.groupby("WELL_ID")["LENGTH"].first().to_dict() == {"W1": 10000.0, "W2": 5280.0}


def test_run_dca_uses_header_fields(db):
    data = db.prepare_data_for_dca(
        header_columns={"well_id": "PROPNUM", "phase": "MAJOR", "length": "LAT_LEN"}
    )
    results = db.run_dca_analysis(data, three_phase_mode=False)
    assert set(results) == set(WELLS)
    w1, w2 = results["W1"], results["W2"]
    # Phase from the header (normalized), and lateral length used for normalization.
    assert w1.phase_col == "PHASE" and w1.params_dataframe["major"].iloc[0] == "OIL"
    assert w2.params_dataframe["major"].iloc[0] == "GAS"
    assert w1.length_col == "LENGTH"
    assert w1._normalized_dataframe["LENGTH_NORM"].iloc[0] == pytest.approx(10000.0)


def test_run_dca_ignores_invalid_header_phase(db):
    db.connection.execute("UPDATE AC_PROPERTY SET MAJOR = 'WTR' WHERE PROPNUM = 'W1'")
    data = db.prepare_data_for_dca(header_columns={"well_id": "PROPNUM", "phase": "MAJOR"})
    with pytest.warns(UserWarning, match="W1: header phase"):
        results = db.run_dca_analysis(data, three_phase_mode=False)
    assert results["W1"].phase_col is None
    assert results["W1"].params_dataframe["major"].iloc[0] in ("OIL", "GAS")


ARIES_FILES = [REPO_ROOT / "reference" / "foundation-db.mdb"]


@pytest.mark.parametrize("path", ARIES_FILES, ids=lambda p: p.name)
def test_real_aries_default_header_mapping(path):
    """Against a local ARIES database (skipped when the file or Access driver is absent)."""
    if not path.is_file():
        pytest.skip(f"Optional ARIES fixture not present: {path}")
    pytest.importorskip("pyodbc")
    with ARIESDatabase(path) as db:
        if not db.connect():
            pytest.skip("Microsoft Access ODBC driver not available")
        with pytest.warns(UserWarning, match="LATERAL"):
            data = db.prepare_data_for_dca(production_table="AC_PRODUCT", header_table="AC_PROPERTY")
        assert len(data) > 0
        assert {"WELL_ID", "DATE", "OIL", "GAS", "WATER", "PHASE"} <= set(data.columns)
        assert data["PHASE"].notna().any()
