#!/usr/bin/env python3
"""
Deeper exploration of the .accdb database to find tables with actual data
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

def explore_accdb_deeper():
    """Deeper exploration of the .accdb database"""
    db_path = Path("reference/ROG_IX_YE22_Database.accdb")
    
    if not db_path.exists():
        print(f"Database file not found: {db_path}")
        return
    
    print(f"Deep exploration of database: {db_path}")
    
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
        
        # Check which tables actually have data
        print(f"\nChecking tables for data content...")
        tables_with_data = {}
        
        for table_name in tables:
            try:
                cursor = aries_db.connection.cursor()
                # Count rows
                count_query = f"SELECT COUNT(*) FROM {table_name}"
                cursor.execute(count_query)
                row_count = cursor.fetchone()[0]
                
                if row_count > 0:
                    tables_with_data[table_name] = row_count
                    
            except Exception as e:
                # Table might not exist or be accessible
                pass
        
        # Sort by row count
        sorted_tables = sorted(tables_with_data.items(), key=lambda x: x[1], reverse=True)
        
        print(f"\nTables with data ({len(sorted_tables)}):")
        for table_name, row_count in sorted_tables:
            print(f"  {table_name}: {row_count:,} rows")
        
        # Examine the largest tables in detail
        print(f"\nExamining largest tables in detail...")
        for table_name, row_count in sorted_tables[:5]:  # Top 5
            print(f"\n{'='*60}")
            print(f"Table: {table_name} ({row_count:,} rows)")
            print(f"{'='*60}")
            
            try:
                # Get column info
                cursor = aries_db.connection.cursor()
                columns = [column.column_name for column in cursor.columns(table=table_name)]
                print(f"Columns ({len(columns)}): {columns}")
                
                # Try to read sample data
                import pandas as pd
                sample_query = f"SELECT TOP 3 * FROM {table_name}"
                df = pd.read_sql(sample_query, aries_db.connection)
                
                if not df.empty:
                    print(f"\nSample data:")
                    print(df.head())
                    
                    # Check for potential production-related columns
                    prod_keywords = ['OIL', 'GAS', 'WATER', 'PROD', 'RATE', 'DATE', 'MONTH']
                    prod_columns = [col for col in columns if any(keyword in col.upper() for keyword in prod_keywords)]
                    if prod_columns:
                        print(f"\nPotential production columns: {prod_columns}")
                    
                    # Check for potential well identifier columns
                    well_keywords = ['PROP', 'WELL', 'API', 'UID', 'ID']
                    well_columns = [col for col in columns if any(keyword in col.upper() for keyword in well_keywords)]
                    if well_columns:
                        print(f"Potential well identifier columns: {well_columns}")
                        
                else:
                    print("Table is empty or query returned no results")
                    
            except Exception as e:
                print(f"Error examining {table_name}: {e}")
        
        # Close database connection
        aries_db.close()
        print("\n✓ Database connection closed")
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    explore_accdb_deeper()
