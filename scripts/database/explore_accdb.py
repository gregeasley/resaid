#!/usr/bin/env python3
"""
Explore the .accdb database structure to understand available tables
"""

import sys
from pathlib import Path

# Add the resaid package to the path
sys.path.insert(0, str(Path(__file__).parent))

try:
    from resaid.database import ARIESDatabase
    print("✓ Successfully imported ARIESDatabase")
except ImportError as e:
    print(f"✗ Failed to import ARIESDatabase: {e}")
    sys.exit(1)

def explore_accdb():
    """Explore the .accdb database structure"""
    db_path = Path("reference/ROG_IX_YE22_Database.accdb")
    
    if not db_path.exists():
        print(f"Database file not found: {db_path}")
        return
    
    print(f"Exploring database: {db_path}")
    print(f"File size: {db_path.stat().st_size / (1024*1024):.1f} MB")
    
    try:
        # Create ARIES database interface
        aries_db = ARIESDatabase(db_path)
        
        # Connect to database
        if not aries_db.connect():
            print("✗ Failed to connect to database")
            return
        
        print("✓ Successfully connected to database")
        
        # Get available tables
        tables = aries_db.get_tables()
        print(f"\nAvailable tables ({len(tables)}):")
        for i, table in enumerate(tables, 1):
            print(f"  {i:2d}. {table}")
        
        # Look for potential production data tables
        print(f"\nPotential production data tables:")
        prod_keywords = ['PRODUCT', 'PROD', 'MONTHLY', 'DAILY', 'PRODUCTION']
        for table in tables:
            if any(keyword in table.upper() for keyword in prod_keywords):
                print(f"  - {table}")
        
        # Look for potential property/header tables
        print(f"\nPotential property/header tables:")
        prop_keywords = ['PROPERTY', 'WELL', 'HEADER', 'LEASE']
        for table in tables:
            if any(keyword in table.upper() for keyword in prop_keywords):
                print(f"  - {table}")
        
        # Try to examine some key tables
        key_tables = ['AC_MONTHLY', 'AC_WELL', 'AC_PROPERTY']
        
        for table_name in key_tables:
            if table_name in tables:
                print(f"\nExamining table: {table_name}")
                try:
                    # Try to get column info
                    cursor = aries_db.connection.cursor()
                    columns = [column.column_name for column in cursor.columns(table=table_name)]
                    print(f"  Columns: {columns}")
                    
                    # Try to read a few rows
                    import pandas as pd
                    query = f"SELECT TOP 3 * FROM {table_name}"
                    df = pd.read_sql(query, aries_db.connection)
                    print(f"  Sample data shape: {df.shape}")
                    print(f"  First few rows:")
                    print(df.head())
                    
                except Exception as e:
                    print(f"  Error examining {table_name}: {e}")
        
        # Close database connection
        aries_db.close()
        print("\n✓ Database connection closed")
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    explore_accdb()
