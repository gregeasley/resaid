"""Shared fixtures — sample data paths mirror ``examples/simple_example.py``."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLE_INPUT = REPO_ROOT / "examples" / "input_data"


def require_access_driver() -> None:
    """Skip unless pyodbc and the Microsoft Access ODBC driver are installed.

    Checks the installed drivers instead of opening a connection.
    """
    pyodbc = pytest.importorskip("pyodbc", reason="pyodbc not installed (resaid[database])")
    if not any("Microsoft Access Driver" in d for d in pyodbc.drivers()):
        pytest.skip("Microsoft Access ODBC driver not installed")


@pytest.fixture(scope="session")
def example_production_csv() -> Path:
    p = EXAMPLE_INPUT / "production_data.csv"
    if not p.is_file():
        pytest.skip(f"Missing example production CSV: {p}")
    return p


@pytest.fixture(scope="session")
def example_well_csv() -> Path:
    p = EXAMPLE_INPUT / "well_data.csv"
    if not p.is_file():
        pytest.skip(f"Missing example well CSV: {p}")
    return p


@pytest.fixture
def combined_dca_dataframe(example_production_csv: Path, example_well_csv: Path) -> pd.DataFrame:
    prod_df = pd.read_csv(example_production_csv)
    prod_df["DATE"] = pd.to_datetime(prod_df["DATE"])
    well_df = pd.read_csv(example_well_csv)
    well_df["COMPLETION_DATE"] = pd.to_datetime(well_df["COMPLETION_DATE"])
    combined = prod_df.merge(well_df, on="WELL_ID", how="left")
    combined["PHASE"] = "OIL"
    return combined
