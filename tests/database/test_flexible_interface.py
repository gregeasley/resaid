#!/usr/bin/env python3
"""
Comprehensive test script for the flexible ARIES database interface

Tests both .mdb and .accdb files with flexible table and column mapping
"""

import sys
from pathlib import Path
import pandas as pd

# Add the resaid package to the path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from resaid.database import ARIESDatabase, DatabaseInterface


def explore_database_interface(db_path: Path, db_name: str):
    """Exercise database exploration (script helper; not a pytest test)."""
    print(f"\n{'='*60}")
    print(f"Testing Database Exploration: {db_name}")
    print(f"{'='*60}")
    
    try:
        # Create database interface
        db = DatabaseInterface(db_path)
        
        # Connect to database
        if not db.connect():
            print("✗ Failed to connect to database")
            return False
        
        print("✓ Successfully connected to database")
        
        # Get available tables
        tables = db.get_tables()
        print(f"Available tables ({len(tables)}):")
        for i, table in enumerate(tables[:10], 1):  # Show first 10
            print(f"  {i:2d}. {table}")
        if len(tables) > 10:
            print(f"  ... and {len(tables) - 10} more tables")
        
        # Look for potential production and header tables
        prod_keywords = ['PRODUCT', 'PROD', 'MONTHLY', 'DAILY', 'PRODUCTION']
        header_keywords = ['PROPERTY', 'WELL', 'HEADER', 'LEASE']
        
        prod_tables = [t for t in tables if any(k in t.upper() for k in prod_keywords)]
        header_tables = [t for t in tables if any(k in t.upper() for k in header_keywords)]
        
        print(f"\nPotential production tables: {prod_tables}")
        print(f"Potential header tables: {header_tables}")
        
        # Examine key tables
        key_tables = ['AC_PRODUCT', 'AC_PROPERTY', 'AC_MONTHLY', 'AC_WELL']
        available_key_tables = [t for t in key_tables if t in tables]
        
        if available_key_tables:
            print(f"\nExamining key tables: {available_key_tables}")
            for table_name in available_key_tables:
                try:
                    columns = db.get_table_columns(table_name)
                    print(f"  {table_name}: {len(columns)} columns")
                    
                    # Check for key columns
                    key_columns = ['PROPNUM', 'P_DATE', 'OIL', 'GAS', 'WATER', 'LATERAL', 'MAJOR']
                    found_columns = [col for col in key_columns if col in columns]
                    if found_columns:
                        print(f"    Key columns found: {found_columns}")
                    
                    # Sample data
                    sample_data = db.read_table_data(table_name, columns=columns[:5])  # First 5 columns
                    if not sample_data.empty:
                        print(f"    Sample data: {sample_data.shape}")
                        print(f"    First few rows:")
                        print(sample_data.head(2))
                    else:
                        print(f"    Table appears to be empty")
                        
                except Exception as e:
                    print(f"    Error examining {table_name}: {e}")
        
        db.close()
        return True
        
    except Exception as e:
        print(f"✗ Error exploring database: {e}")
        import traceback
        traceback.print_exc()
        return False

def verify_flexible_mapping(db_path: Path, db_name: str):
    """Exercise flexible table/column mapping (script helper; not a pytest test)."""
    print(f"\n{'='*60}")
    print(f"Testing Flexible Table and Column Mapping: {db_name}")
    print(f"{'='*60}")
    
    try:
        # Create ARIES database interface
        aries_db = ARIESDatabase(db_path)
        
        # Connect to database
        if not aries_db.connect():
            print("✗ Failed to connect to database")
            return False
        
        print("✓ Successfully connected to database")
        
        # Get available tables
        tables = aries_db.get_tables()
        
        # Find production and header tables
        prod_table = None
        header_table = None
        
        if 'AC_PRODUCT' in tables:
            prod_table = 'AC_PRODUCT'
        elif 'AC_MONTHLY' in tables:
            prod_table = 'AC_MONTHLY'
        
        if 'AC_PROPERTY' in tables:
            header_table = 'AC_PROPERTY'
        elif 'AC_WELL' in tables:
            header_table = 'AC_WELL'
        
        if not prod_table:
            print("✗ No production table found")
            return False
        
        print(f"Using production table: {prod_table}")
        if header_table:
            print(f"Using header table: {header_table}")
        
        # Test with default table and column mapping
        print(f"\n1. Testing with default table and column mapping...")
        try:
            dca_data = aries_db.prepare_data_for_dca()
            print(f"✓ Data prepared with defaults: {dca_data.shape}")
            
            # Show sample data
            print(f"Sample data columns: {list(dca_data.columns[:10])}")
            print(f"Sample data:")
            print(dca_data[['WELL_ID', 'DATE', 'OIL', 'GAS', 'WATER']].head())
            
        except Exception as e:
            print(f"✗ Default mapping failed: {e}")
            
            # Try to create custom mapping
            print(f"\n2. Attempting custom table and column mapping...")
            
            # Get columns from production table
            prod_columns = aries_db.get_table_columns(prod_table)
            print(f"Production table columns: {prod_columns}")
            
            # Look for potential mappings
            potential_prod_mappings = {}
            for col in prod_columns:
                col_upper = col.upper()
                if 'PROP' in col_upper or 'WELL' in col_upper:
                    potential_prod_mappings['well_id'] = col
                elif 'DATE' in col_upper:
                    potential_prod_mappings['date'] = col
                elif 'OIL' in col_upper:
                    potential_prod_mappings['oil'] = col
                elif 'GAS' in col_upper:
                    potential_prod_mappings['gas'] = col
                elif 'WATER' in col_upper or 'WTR' in col_upper:
                    potential_prod_mappings['water'] = col
            
            if len(potential_prod_mappings) >= 4:  # Need at least well_id, date, oil, gas
                print(f"Creating custom production mapping: {potential_prod_mappings}")
                
                # Create custom header mapping if header table exists
                header_columns = None
                if header_table:
                    header_cols = aries_db.get_table_columns(header_table)
                    print(f"Header table columns: {header_cols}")
                    
                    potential_header_mappings = {}
                    for col in header_cols:
                        col_upper = col.upper()
                        if 'PROP' in col_upper or 'WELL' in col_upper:
                            potential_header_mappings['well_id'] = col
                        elif 'FIELD' in col_upper:
                            potential_header_mappings['field'] = col
                        elif 'OPERATOR' in col_upper:
                            potential_header_mappings['operator'] = col
                    
                    if len(potential_header_mappings) >= 1:  # Need at least well_id
                        header_columns = potential_header_mappings
                        print(f"Creating custom header mapping: {header_columns}")
                
                try:
                    dca_data = aries_db.prepare_data_for_dca(
                        production_table=prod_table,
                        production_columns=potential_prod_mappings,
                        header_table=header_table,
                        header_columns=header_columns
                    )
                    print(f"✓ Data prepared with custom mapping: {dca_data.shape}")
                    
                    # Show sample data
                    print(f"Sample data:")
                    print(dca_data[['WELL_ID', 'DATE', 'OIL', 'GAS', 'WATER']].head())
                    
                except Exception as e2:
                    print(f"✗ Custom mapping also failed: {e2}")
                    return False
            else:
                print(f"✗ Insufficient columns for mapping: {potential_prod_mappings}")
                return False
        
        # Test DCA analysis if we have data
        if 'dca_data' in locals() and len(dca_data) > 0:
            print(f"\n3. Testing DCA analysis...")
            unique_wells = dca_data['WELL_ID'].unique()
            print(f"Total wells: {len(unique_wells)}")
            
            if len(unique_wells) > 0:
                # Select first well with sufficient data
                test_well = None
                for well_id in unique_wells[:5]:
                    well_data = dca_data[dca_data['WELL_ID'] == well_id]
                    if len(well_data) >= 3:
                        test_well = well_id
                        break
                
                if test_well:
                    print(f"Testing DCA with well: {test_well}")
                    test_data = dca_data[dca_data['WELL_ID'] == test_well].copy()
                    print(f"Data points: {len(test_data)}")
                    
                    try:
                        # Run DCA analysis
                        dca_results = aries_db.run_dca_analysis(
                            test_data, 
                            three_phase_mode=True
                        )
                        
                        if test_well in dca_results:
                            print(f"✓ DCA analysis completed for {test_well}")
                            
                            # Test export
                            print(f"\n4. Testing export functionality...")
                            output_dir = Path(f"test_outputs_{db_path.stem}")
                            output_dir.mkdir(exist_ok=True)
                            
                            try:
                                aries_files = aries_db.export_results(
                                    dca_results,
                                    export_format='aries',
                                    output_dir=output_dir
                                )
                                
                                if test_well in aries_files:
                                    print(f"✓ ARIES export completed: {aries_files[test_well]}")
                                else:
                                    print("✗ ARIES export failed")
                            except Exception as e:
                                print(f"✗ Export error: {e}")
                        else:
                            print(f"✗ DCA analysis failed for {test_well}")
                    except Exception as e:
                        print(f"✗ DCA analysis error: {e}")
                else:
                    print("✗ No wells with sufficient data for DCA testing")
        
        # Close database connection
        aries_db.close()
        print(f"\n✓ Database connection closed")
        return True
        
    except Exception as e:
        print(f"✗ Error testing flexible interface: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Main test function"""
    print("Flexible ARIES Database Interface Test")
    print("=" * 60)
    
    # Test both database files
    reference_dir = Path("../../reference")
    test_files = [
        (reference_dir / "foundation-db.mdb", "ARIES .mdb"),
        (reference_dir / "EIV Fund II_24EY_2025-01-22.accdb", "ARIES .accdb")
    ]
    
    results = {}
    
    for db_path, db_type in test_files:
        if not db_path.exists():
            print(f"✗ Database not found: {db_path}")
            results[db_path.name] = False
            continue
        
        print(f"\nTesting: {db_path.name}")
        
        # Test exploration
        exploration_success = explore_database_interface(db_path, db_type)
        
        # Test flexible interface
        interface_success = verify_flexible_mapping(db_path, db_type)
        
        # Overall success for this database
        results[db_path.name] = exploration_success and interface_success
    
    # Summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    
    all_passed = True
    for db_name, success in results.items():
        status = "✓ PASS" if success else "✗ FAIL"
        print(f"{db_name}: {status}")
        if not success:
            all_passed = False
    
    if all_passed:
        print("\n🎉 All database tests passed! Flexible interface is working correctly.")
    else:
        print("\n❌ Some database tests failed. Check the output above for details.")
    
    print(f"\nTest outputs saved in:")
    for db_path, _ in test_files:
        output_dir = Path(f"../../test_outputs_{db_path.stem}")
        if output_dir.exists():
            print(f"  - {output_dir.absolute()}")

if __name__ == "__main__":
    main()
