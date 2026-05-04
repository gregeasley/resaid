#!/usr/bin/env python3
"""
Simple test to verify the fixed database interface works.

Run as a script: ``python tests/database/test_fixed_interface.py`` (from repo root).
"""

from __future__ import annotations

import traceback
from pathlib import Path

import pytest

from resaid.database import ARIESDatabase, DatabaseInterface

REPO_ROOT = Path(__file__).resolve().parents[2]
REF_ACCDB = REPO_ROOT / "reference" / "EIV Fund II_24EY_2025-01-22.accdb"


def run_simple_dca_check(db_path: Path) -> bool:
    """Run DCA + export via ARIESDatabase; return True on success (for CLI)."""
    print("Testing simple DCA analysis...")

    if not db_path.exists():
        print(f"[FAIL] Database not found: {db_path}")
        return False

    aries_db = None
    try:
        aries_db = ARIESDatabase(db_path)

        if not aries_db.connect():
            print("[FAIL] Failed to connect to database")
            return False

        print("[OK] Successfully connected to database")

        dca_data = DatabaseInterface.prepare_data_for_dca(
            aries_db,
            production_table="AC_PRODUCT",
            production_columns={
                "well_id": "PROPNUM",
                "date": "P_DATE",
                "oil": "OIL",
                "gas": "GAS",
                "water": "WATER",
            },
            header_table=None,
            header_columns=None,
        )

        print(f"[OK] Data prepared: {dca_data.shape}")

        well_counts = dca_data.groupby("WELL_ID").size()
        good_wells = well_counts[well_counts >= 12].index

        if len(good_wells) == 0:
            print("[FAIL] No wells with sufficient data found")
            return False

        test_well = good_wells[0]
        print(f"Testing with well: {test_well}")

        test_data = dca_data[dca_data["WELL_ID"] == test_well].copy()
        print(f"Test data shape: {test_data.shape}")

        print("Running DCA analysis...")
        dca_results = aries_db.run_dca_analysis(test_data, three_phase_mode=True)

        if test_well not in dca_results:
            print(f"[FAIL] DCA analysis failed for {test_well}")
            return False

        print(f"[OK] DCA analysis completed for {test_well}")

        print("Testing export...")
        output_dir = REPO_ROOT / "test_outputs_simple"
        output_dir.mkdir(exist_ok=True)

        aries_files = aries_db.export_results(
            dca_results,
            export_format="aries",
            output_dir=output_dir,
        )

        if test_well in aries_files:
            print(f"[OK] Export completed: {aries_files[test_well]}")
            return True

        print("[FAIL] Export failed")
        return False

    except Exception as e:
        print(f"[FAIL] Error: {e}")
        traceback.print_exc()
        return False
    finally:
        if aries_db is not None:
            aries_db.close()


def test_simple_dca():
    """Pytest entry: skips when reference database is not in the workspace."""
    if not REF_ACCDB.is_file():
        pytest.skip(f"Optional ARIES fixture not present: {REF_ACCDB}")
    assert run_simple_dca_check(REF_ACCDB), "Simple DCA / export check failed (see stdout)"


def main() -> None:
    print("Fixed Database Interface Test")
    print("=" * 50)
    if not REF_ACCDB.is_file():
        print(f"[FAIL] Database not found: {REF_ACCDB}")
        return
    success = run_simple_dca_check(REF_ACCDB)
    if success:
        print("\n[OK] Test passed. Database interface is working correctly.")
    else:
        print("\n[FAIL] Test failed. Check the output above for details.")


if __name__ == "__main__":
    main()
