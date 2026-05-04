#!/usr/bin/env python3
"""
Direct test to see exactly where DCA is failing.

Run as a script: ``python tests/database/direct_dca_test.py`` (from repo root).
"""

from __future__ import annotations

import traceback
from pathlib import Path

import pytest

from resaid.database import ARIESDatabase, DatabaseInterface
from resaid.dca import decline_curve

REPO_ROOT = Path(__file__).resolve().parents[2]
REF_ACCDB = REPO_ROOT / "reference" / "EIV Fund II_24EY_2025-01-22.accdb"


def run_direct_dca_check(db_path: Path) -> bool:
    """Run DCA steps against an ARIES .accdb; return True on success (for CLI)."""
    print("Testing DCA directly...")

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

        # Production-only (bypass ARIES defaults that always attach AC_PROPERTY).
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
        print("Sample data:")
        print(test_data[["WELL_ID", "DATE", "OIL", "GAS", "WATER"]].head())

        print("\n1. Creating decline_curve object...")
        dca = decline_curve()
        dca.three_phase_mode = True
        dca.dataframe = test_data
        dca.date_col = "DATE"
        dca.uid_col = "WELL_ID"
        dca.oil_col = "OIL"
        dca.gas_col = "GAS"
        dca.water_col = "WATER"
        print("[OK] Decline curve object created")

        print("\n2. Three-phase mode set")
        print(f"[OK] three_phase_mode: {dca.three_phase_mode}")

        print("\n3. Running DCA...")
        dca.run_DCA()
        print("[OK] DCA completed successfully")

        print("\n4. Generating oneline...")
        dca.generate_oneline()
        print("[OK] Oneline generated successfully")

        print("\n[OK] All DCA steps completed successfully.")
        return True

    except Exception as e:
        print(f"[FAIL] Error: {e}")
        traceback.print_exc()
        return False
    finally:
        if aries_db is not None:
            aries_db.close()


def test_direct_dca():
    """Pytest entry: skips when reference database is not in the workspace."""
    if not REF_ACCDB.is_file():
        pytest.skip(f"Optional ARIES fixture not present: {REF_ACCDB}")
    assert run_direct_dca_check(REF_ACCDB), "Direct DCA check failed (see stdout)"


def main() -> None:
    print("Direct DCA Test")
    print("=" * 50)
    if not REF_ACCDB.is_file():
        print(f"[FAIL] Database not found: {REF_ACCDB}")
        return
    success = run_direct_dca_check(REF_ACCDB)
    if success:
        print("\n[OK] Test passed. DCA is working correctly.")
    else:
        print("\n[FAIL] Test failed. Check the output above for details.")


if __name__ == "__main__":
    main()
