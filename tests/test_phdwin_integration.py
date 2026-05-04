#!/usr/bin/env python3
"""
Test PhdWin database integration with RESAID.

Run manually: ``python tests/test_phdwin_integration.py`` (from repo root).
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


def main() -> None:
    try:
        from resaid.database import PhdWinDatabase

        print("✓ PhdWinDatabase imported successfully")

        phd_file = REPO_ROOT / "reference" / "TxWells.phz"
        if not phd_file.is_file():
            print(f"✗ PhdWin database not found: {phd_file}")
            sys.exit(1)

        print(f"Testing PhdWin database: {phd_file}")

        db = PhdWinDatabase(phd_file)
        print(f"✓ Database type detected: {db.db_type}")

        if db.connect():
            print("✓ Database connection successful")

            tables = db.get_tables()
            print(f"✓ Tables found: {len(tables)}")
            for t in tables[:5]:
                print(f"  - {t}")

            if tables:
                first_table = tables[0]
                columns = db.get_table_columns(first_table)
                print(f"✓ Columns in {first_table}: {len(columns)}")
                for c in columns[:5]:
                    print(f"  - {c}")

            db.close()
            print("✓ Database connection closed")
        else:
            print("✗ Database connection failed")

        print("✓ PhdWin integration test completed")

    except Exception as e:
        print(f"✗ Error: {e}")
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
