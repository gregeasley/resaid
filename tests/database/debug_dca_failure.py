#!/usr/bin/env python3
"""
Debug script to understand why DCA analysis is failing
"""

import sys
from pathlib import Path
import pandas as pd

# Add the resaid package to the path
sys.path.insert(0, str(Path(__file__).parent))

try:
    from resaid.database import ARIESDatabase
    print("✓ Successfully imported ARIESDatabase")
except ImportError as e:
    print(f"✗ Failed to import ARIESDatabase: {e}")
    sys.exit(1)

def debug_dca_failure(db_path: Path, db_name: str):
    """Debug DCA failure for a specific database"""
    print(f"\n{'='*60}")
    print(f"Debugging DCA Failure: {db_name}")
    print(f"{'='*60}")
    
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
        
        # Find production and header tables
        prod_table = 'AC_PRODUCT' if 'AC_PRODUCT' in tables else 'AC_MONTHLY'
        header_table = 'AC_PROPERTY' if 'AC_PROPERTY' in tables else 'AC_WELL'
        
        print(f"Using production table: {prod_table}")
        print(f"Using header table: {header_table}")
        
        # Prepare data
        dca_data = aries_db.prepare_data_for_dca(
            production_table=prod_table,
            header_table=header_table
        )
        
        print(f"Data prepared: {dca_data.shape}")
        
        # Examine data quality
        print(f"\nData quality check:")
        print(f"Total rows: {len(dca_data)}")
        print(f"Total wells: {dca_data['WELL_ID'].nunique()}")
        
        # Check for missing values
        missing_data = dca_data[['WELL_ID', 'DATE', 'OIL', 'GAS', 'WATER']].isnull().sum()
        print(f"Missing values:")
        print(missing_data)
        
        # Check data types
        print(f"\nData types:")
        print(dca_data[['WELL_ID', 'DATE', 'OIL', 'GAS', 'WATER']].dtypes)
        
        # Check for zero/negative values
        print(f"\nValue ranges:")
        print(f"OIL: {dca_data['OIL'].min():.2f} to {dca_data['OIL'].max():.2f}")
        print(f"GAS: {dca_data['GAS'].min():.2f} to {dca_data['GAS'].max():.2f}")
        print(f"WATER: {dca_data['WATER'].min():.2f} to {dca_data['WATER'].max():.2f}")
        
        # Check for wells with sufficient data
        well_counts = dca_data.groupby('WELL_ID').size()
        print(f"\nWells by data point count:")
        print(well_counts.value_counts().sort_index().head(10))
        
        # Find a well with good data
        good_wells = well_counts[well_counts >= 12].index  # At least 12 months
        if len(good_wells) > 0:
            test_well = good_wells[0]
            print(f"\nTesting with well: {test_well}")
            
            well_data = dca_data[dca_data['WELL_ID'] == test_well].copy()
            print(f"Well data shape: {well_data.shape}")
            
            # Show sample data
            print(f"Sample well data:")
            print(well_data[['WELL_ID', 'DATE', 'OIL', 'GAS', 'WATER']].head(10))
            
            # Check for production trends
            print(f"\nProduction trends for {test_well}:")
            print(f"First date: {well_data['DATE'].min()}")
            print(f"Last date: {well_data['DATE'].max()}")
            print(f"Total oil: {well_data['OIL'].sum():.0f}")
            print(f"Total gas: {well_data['GAS'].sum():.0f}")
            print(f"Total water: {well_data['WATER'].sum():.0f}")
            
            # Try to identify the issue
            print(f"\nTrying to identify DCA issue...")
            
            # Check if all required columns are present
            required_cols = ['WELL_ID', 'DATE', 'OIL', 'GAS', 'WATER']
            missing_cols = [col for col in required_cols if col not in well_data.columns]
            if missing_cols:
                print(f"✗ Missing columns: {missing_cols}")
                return
            
            # Check if data has enough variation
            oil_std = well_data['OIL'].std()
            gas_std = well_data['GAS'].std()
            water_std = well_data['WATER'].std()
            
            print(f"Standard deviations:")
            print(f"  OIL: {oil_std:.2f}")
            print(f"  GAS: {gas_std:.2f}")
            print(f"  WATER: {water_std:.2f}")
            
            if oil_std == 0 and gas_std == 0 and water_std == 0:
                print("✗ All production values are constant - no decline to analyze")
                return
            
            # Check for negative values
            negative_oil = (well_data['OIL'] < 0).sum()
            negative_gas = (well_data['GAS'] < 0).sum()
            negative_water = (well_data['WATER'] < 0).sum()
            
            if negative_oil > 0 or negative_gas > 0 or negative_water > 0:
                print(f"✗ Negative values found:")
                print(f"  OIL: {negative_oil}")
                print(f"  GAS: {negative_gas}")
                print(f"  WATER: {negative_water}")
            
            # Try to run DCA manually to see the exact error
            print(f"\nAttempting manual DCA analysis...")
            try:
                from resaid.dca import decline_curve
                
                # Create decline curve object
                dca = decline_curve(well_data)
                
                # Set three-phase mode
                if hasattr(dca, 'three_phase_mode'):
                    dca.three_phase_mode = True
                
                print(f"✓ Decline curve object created")
                
                # Try to run DCA
                print(f"Running DCA...")
                dca.run_DCA()
                print(f"✓ DCA completed successfully")
                
                # Try to generate oneline
                print(f"Generating oneline...")
                dca.generate_oneline()
                print(f"✓ Oneline generated successfully")
                
            except Exception as e:
                print(f"✗ DCA error: {e}")
                import traceback
                traceback.print_exc()
        else:
            print("✗ No wells with sufficient data found")
        
        # Close database connection
        aries_db.close()
        print(f"\n✓ Database connection closed")
        
    except Exception as e:
        print(f"✗ Error debugging database: {e}")
        import traceback
        traceback.print_exc()

def main():
    """Main debug function"""
    print("DCA Failure Debug Script")
    print("=" * 60)
    
    # Test both database files
    reference_dir = Path("reference")
    test_files = [
        (reference_dir / "foundation-db.mdb", "ARIES .mdb"),
        (reference_dir / "EIV Fund II_24EY_2025-01-22.accdb", "ARIES .accdb")
    ]
    
    for db_path, db_type in test_files:
        if not db_path.exists():
            print(f"✗ Database not found: {db_path}")
            continue
        
        debug_dca_failure(db_path, db_type)

if __name__ == "__main__":
    main()
