#!/usr/bin/env python3
"""
Comprehensive test script for ARIES database interface

Tests both .mdb and .accdb files to ensure proper functionality
"""

import sys
from pathlib import Path
import pandas as pd

# Add the resaid package to the path
sys.path.insert(0, str(Path(__file__).parent))

from resaid.database import ARIESDatabase


def verify_aries_database_file(db_path: Path, db_type: str) -> bool:
    """Run checks for a specific database file (script helper; not a pytest test)."""
    print(f"\n{'='*60}")
    print(f"Testing {db_type}: {db_path.name}")
    print(f"{'='*60}")
    
    if not db_path.exists():
        print(f"✗ Database file not found: {db_path}")
        return False
    
    print(f"File size: {db_path.stat().st_size / (1024*1024):.1f} MB")
    
    try:
        # Create ARIES database interface
        print(f"\n1. Creating ARIES database interface...")
        aries_db = ARIESDatabase(db_path)
        print("✓ Interface created successfully")
        
        # Test connection
        print(f"\n2. Testing database connection...")
        if not aries_db.connect():
            print("✗ Failed to connect to database")
            return False
        
        print("✓ Successfully connected to database")
        
        # Get available tables
        print(f"\n3. Getting available tables...")
        tables = aries_db.get_tables()
        print(f"Available tables: {tables}")
        
        # Check for required tables
        required_tables = ['AC_PRODUCT', 'AC_PROPERTY']
        missing_tables = [table for table in required_tables if table not in tables]
        
        if missing_tables:
            print(f"✗ Missing required tables: {missing_tables}")
            return False
        
        print("✓ All required tables found")
        
        # Test reading production data
        print(f"\n4. Testing production data reading...")
        try:
            prod_data = aries_db.read_production_data()
            print(f"✓ Production data loaded: {prod_data.shape}")
            print(f"Columns: {list(prod_data.columns)}")
            
            # Show sample data
            print(f"\nSample production data:")
            sample_cols = ['PROPNUM', 'P_DATE', 'OIL', 'GAS', 'WATER']
            available_cols = [col for col in sample_cols if col in prod_data.columns]
            if available_cols:
                print(prod_data[available_cols].head())
            else:
                print("No expected columns found in production data")
                
        except Exception as e:
            print(f"✗ Failed to read production data: {e}")
            return False
        
        # Test reading header data
        print(f"\n5. Testing header data reading...")
        try:
            header_data = aries_db.read_header_data()
            print(f"✓ Header data loaded: {header_data.shape}")
            print(f"Columns: {list(header_data.columns)}")
            
            # Show sample data
            print(f"\nSample header data:")
            sample_cols = ['PROPNUM', 'LEASE', 'WELL_NO', 'FIELD', 'OPERATOR']
            available_cols = [col for col in sample_cols if col in header_data.columns]
            if available_cols:
                print(header_data[available_cols].head())
            else:
                print("No expected columns found in header data")
                
        except Exception as e:
            print(f"✗ Failed to read header data: {e}")
            return False
        
        # Test data preparation for DCA
        print(f"\n6. Testing data preparation for DCA...")
        try:
            dca_data = aries_db.prepare_data_for_dca()
            print(f"✓ Data prepared for DCA: {dca_data.shape}")
            print(f"Required columns: {list(dca_data.columns)}")
            
            # Check for required columns
            required_cols = ['WELL_ID', 'DATE', 'OIL', 'GAS', 'WATER']
            missing_cols = [col for col in required_cols if col not in dca_data.columns]
            if missing_cols:
                print(f"✗ Missing required columns after preparation: {missing_cols}")
                return False
            
            print("✓ All required columns present")
            
            # Show data summary
            unique_wells = dca_data['WELL_ID'].unique()
            print(f"Total unique wells: {len(unique_wells)}")
            print(f"Date range: {dca_data['DATE'].min()} to {dca_data['DATE'].max()}")
            
            # Show sample data
            print(f"\nSample DCA data:")
            print(dca_data[required_cols].head())
            
        except Exception as e:
            print(f"✗ Failed to prepare data for DCA: {e}")
            return False
        
        # Test with a small subset for DCA analysis
        print(f"\n7. Testing DCA analysis...")
        if len(unique_wells) > 0:
            # Select first well with sufficient data
            test_well = None
            for well_id in unique_wells[:5]:  # Check first 5 wells
                well_data = dca_data[dca_data['WELL_ID'] == well_id]
                if len(well_data) >= 3:  # Need at least 3 data points
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
                        
                        # Test export functionality
                        print(f"\n8. Testing export functionality...")
                        output_dir = Path(f"test_outputs_{db_path.stem}")
                        output_dir.mkdir(exist_ok=True)
                        
                        # Test ARIES export
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
                            print(f"✗ ARIES export error: {e}")
                        
                    else:
                        print(f"✗ DCA analysis failed for {test_well}")
                        
                except Exception as e:
                    print(f"✗ DCA analysis error: {e}")
            else:
                print("✗ No wells with sufficient data for DCA testing")
        else:
            print("✗ No wells found in data")
        
        # Close database connection
        aries_db.close()
        print(f"\n✓ Database connection closed for {db_path.name}")
        return True
        
    except Exception as e:
        print(f"✗ Error testing database {db_path.name}: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Main test function"""
    print("ARIES Database Interface Test")
    print("=" * 60)
    
    # Test both database files
    reference_dir = Path("reference")
    test_files = [
        (reference_dir / "foundation-db.mdb", "ARIES .mdb"),
        (reference_dir / "ROG_IX_YE22_Database.accdb", "ARIES .accdb")
    ]
    
    results = {}
    
    for db_path, db_type in test_files:
        results[db_path.name] = verify_aries_database_file(db_path, db_type)
    
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
        print("\n🎉 All database tests passed! ARIES interface is working correctly.")
    else:
        print("\n❌ Some database tests failed. Check the output above for details.")
    
    print(f"\nTest outputs saved in:")
    for db_path, _ in test_files:
        output_dir = Path(f"test_outputs_{db_path.stem}")
        if output_dir.exists():
            print(f"  - {output_dir.absolute()}")

if __name__ == "__main__":
    main()
