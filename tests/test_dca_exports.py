"""File exports (ARIES text, PhdWin CSV, Mosaic xlsx) after a full DCA run."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from resaid.dca import decline_curve


@pytest.fixture
def dca_ran_three_phase(combined_dca_dataframe: pd.DataFrame) -> decline_curve:
    dca = decline_curve()
    dca.three_phase_mode = True
    dca.dataframe = combined_dca_dataframe
    dca.date_col = "DATE"
    dca.phase_col = "PHASE"
    dca.uid_col = "WELL_ID"
    dca.oil_col = "OIL"
    dca.gas_col = "GAS"
    dca.water_col = "WATER"
    dca.run_DCA()
    dca.generate_oneline(denormalize=True)
    return dca


def test_generate_aries_export_creates_file(dca_ran_three_phase: decline_curve, tmp_path: Path):
    out = tmp_path / "aries.txt"
    dca_ran_three_phase.generate_aries_export(str(out), write_water=True)
    assert out.is_file()
    text = out.read_text(encoding="utf-8", errors="replace")
    assert len(text) > 0


def test_generate_phdwin_export_creates_csv(dca_ran_three_phase: decline_curve, tmp_path: Path):
    out = tmp_path / "phdwin.csv"
    dca_ran_three_phase.generate_phdwin_export(str(out))
    assert out.is_file()
    df = pd.read_csv(out)
    assert not df.empty
    assert "UniqueId" in df.columns
    assert "Product" in df.columns


def test_generate_mosaic_export_creates_xlsx(dca_ran_three_phase: decline_curve, tmp_path: Path):
    pytest.importorskip("openpyxl")
    out = tmp_path / "mosaic.xlsx"
    dca_ran_three_phase.generate_mosaic_export(str(out))
    assert out.is_file()
    df = pd.read_excel(out)
    assert not df.empty
    assert "Entity Name" in df.columns
