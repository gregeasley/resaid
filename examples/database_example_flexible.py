#!/usr/bin/env python3
"""
Example script demonstrating the flexible ARIES database interface

This example shows how to:
1. Connect to an ARIES database
2. Specify custom table names and column mappings (only what DCA needs)
3. Run DCA analysis
4. Export results
"""

import sys
from pathlib import Path

# Add the resaid package to the path
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from resaid.database import ARIESDatabase
    print("✓ Successfully imported ARIESDatabase")
except ImportError as e:
    print(f"✗ Failed to import ARIESDatabase: {e}")
    sys.exit(1)

def main():
    """Main example function"""
    print("Flexible ARIES Database Interface Example")
    print("=" * 60)
    
    # Database path
    db_path = Path("../reference/EIV Fund II_24EY_2025-01-22.accdb")
    
    if not db_path.exists():
        print(f"✗ Database not found: {db_path}")
        return
    
    try:
        # Create ARIES database interface
        print("1. Creating ARIES database interface...")
        aries_db = ARIESDatabase(db_path)
        print("✓ Interface created successfully")
        
        # Connect to database
        print("\n2. Connecting to database...")
        if not aries_db.connect():
            print("✗ Failed to connect to database")
            return
        print("✓ Successfully connected to database")
        
        # Get available tables
        print("\n3. Exploring database structure...")
        tables = aries_db.get_tables()
        print(f"Available tables: {tables}")
        
        # Example 1: Use default table and column mappings
        print("\n4. Example 1: Using default mappings...")
        try:
            dca_data = aries_db.prepare_data_for_dca()
            print(f"✓ Data prepared with defaults: {dca_data.shape}")
            print(f"Sample data:")
            print(dca_data[['WELL_ID', 'DATE', 'OIL', 'GAS', 'WATER']].head())
        except Exception as e:
            print(f"✗ Default mapping failed: {e}")
        
        # Example 2: Custom table and column mappings (only what DCA needs)
        print("\n5. Example 2: Custom table and column mappings...")
        
        # Define custom production table mapping - ONLY production data from AC_PRODUCT
        custom_production_columns = {
            'well_id': 'PROPNUM',      # Well identifier (required)
            'date': 'P_DATE',          # Production date (required)
            'oil': 'OIL',              # Oil production (required)
            'gas': 'GAS',              # Gas production (required)
            'water': 'WATER'           # Water production (required)
        }
        
        # Define custom header table mapping - well properties from AC_PROPERTY
        custom_header_columns = {
            'well_id': 'PROPNUM',      # Well identifier (must match production)
            'phase': 'MAJOR',          # Major phase - optional but useful
            'length': 'LATERAL',       # Lateral length - optional for normalization
            'dayson': 'DAYS_ON',       # Days on production - optional
            'field': 'FIELD',          # Field name - optional
            'operator': 'OPERATOR'     # Operator name - optional
        }
        
        try:
            dca_data = aries_db.prepare_data_for_dca(
                production_table='AC_PRODUCT',
                production_columns=custom_production_columns,
                header_table='AC_PROPERTY',
                header_columns=custom_header_columns
            )
            print(f"✓ Data prepared with custom mappings: {dca_data.shape}")
            print(f"Sample data:")
            print(dca_data[['WELL_ID', 'DATE', 'OIL', 'GAS', 'WATER']].head())
            
            # Show optional columns if they exist
            optional_cols = ['PHASE', 'LENGTH', 'DAYSON', 'FIELD', 'OPERATOR']
            existing_optional = [col for col in optional_cols if col in dca_data.columns]
            if existing_optional:
                print(f"Optional columns found: {existing_optional}")
        except Exception as e:
            print(f"✗ Custom mapping failed: {e}")
            return
        
        # Example 3: Run DCA analysis
        print("\n6. Example 3: Running DCA analysis...")
        
        # Find a well with sufficient data
        well_counts = dca_data.groupby('WELL_ID').size()
        good_wells = well_counts[well_counts >= 12].index  # At least 12 months
        
        if len(good_wells) > 0:
            test_well = good_wells[0]
            print(f"Testing with well: {test_well}")
            
            test_data = dca_data[dca_data['WELL_ID'] == test_well].copy()
            print(f"Data points: {len(test_data)}")
            
            # Run DCA analysis
            dca_results = aries_db.run_dca_analysis(
                test_data, 
                three_phase_mode=True
            )
            
            if test_well in dca_results:
                print(f"✓ DCA analysis completed for {test_well}")
                
                # Example 4: Export results
                print("\n7. Example 4: Exporting results...")
                output_dir = Path("outputs")
                output_dir.mkdir(exist_ok=True)
                
                # Export in different formats
                export_formats = ['aries', 'phdwin', 'mosaic']
                
                for export_format in export_formats:
                    try:
                        export_files = aries_db.export_results(
                            dca_results,
                            export_format=export_format,
                            output_dir=output_dir
                        )
                        
                        if test_well in export_files:
                            print(f"✓ {export_format.upper()} export completed: {export_files[test_well]}")
                        else:
                            print(f"✗ {export_format.upper()} export failed")
                    except Exception as e:
                        print(f"✗ {export_format.upper()} export error: {e}")
            else:
                print(f"✗ DCA analysis failed for {test_well}")
        else:
            print("✗ No wells with sufficient data for DCA testing")
        
        # Close database connection
        aries_db.close()
        print(f"\n✓ Database connection closed")
        
        print(f"\n🎉 Example completed successfully!")
        print(f"Check the 'outputs' folder for exported files.")
        
        print(f"\nKey Points:")
        print(f"- Production data comes from AC_PRODUCT table (well_id, date, oil, gas, water)")
        print(f"- Header data comes from AC_PROPERTY table (phase, length, dayson, field, operator)")
        print(f"- Required: well_id, date, oil, gas, water")
        print(f"- Optional: phase, length, dayson, field, operator")
        print(f"- The interface automatically merges production and header data")
        
    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
