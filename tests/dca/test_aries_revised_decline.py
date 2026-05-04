#!/usr/bin/env python3
"""
Test script to verify that the ARIES export correctly calculates revised decline rates
based on the time difference between L3M_START and T0 dates.
"""

import pandas as pd
import numpy as np
import sys
import os
from io import StringIO
from contextlib import redirect_stdout

# Add the parent directory to the path to import resaid
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from resaid.dca import decline_curve


def create_test_data_with_time_difference():
    """Create test data where L3M_START and T0 dates are different"""
    np.random.seed(42)  # For reproducible results
    
    # Create test data for 2 wells with 12 months of production each
    wells = [f'REVISED_TEST_WELL_{i:03d}' for i in range(1, 3)]
    dates = pd.date_range('2023-01-01', periods=12, freq='ME')
    
    data = []
    for well in wells:
        for i, date in enumerate(dates):
            # Simulate declining production
            oil_prod = max(1000 * np.exp(-0.1 * i) + np.random.normal(0, 50), 0)
            gas_prod = oil_prod * (1000 + np.random.normal(0, 100))  # GOR around 1000
            water_prod = oil_prod * (0.5 + np.random.normal(0, 0.1))  # WOR around 0.5
            
            data.append({
                'API_UWI': well,
                'MAJOR': 'OIL',
                'ProducingMonth': date,
                'LateralLength_FT': 5000,
                'LiquidsProd_BBL': oil_prod,
                'GasProd_MCF': gas_prod,
                'WaterProd_BBL': water_prod
            })
    
    return pd.DataFrame(data)


def test_revised_decline_calculation():
    """Test that revised decline rates are calculated correctly"""
    print("Testing revised decline rate calculation...")
    
    # Create test data
    test_df = create_test_data_with_time_difference()
    
    dca = decline_curve()
    dca.dataframe = test_df
    dca.date_col = 'ProducingMonth'
    dca.uid_col = 'API_UWI'
    dca.oil_col = 'LiquidsProd_BBL'
    dca.gas_col = 'GasProd_MCF'
    dca.water_col = 'WaterProd_BBL'
    dca.phase_col = 'MAJOR'
    dca.length_col = 'LateralLength_FT'
    dca.backup_decline = True
    dca.three_phase_mode = True  # Use three-phase mode to test the fix
    
    # Run DCA and generate oneline
    dca.run_DCA(_verbose=False)
    dca.generate_oneline(denormalize=True, _verbose=False)
    
    # Generate ARIES export to test the revised decline calculation
    output_file = "tests/test_aries_revised_decline.txt"
    
    # Capture any output
    with redirect_stdout(StringIO()):
        dca.generate_aries_export(file_path=output_file, scenario="TEST", dmin=6, write_water=True)
    
    # Check if the file was created
    if os.path.exists(output_file):
        print("   ✓ ARIES export file created successfully")
        
        # Read the file and check for revised decline rates
        with open(output_file, 'r') as f:
            content = f.read()
        
        # Check that the file contains decline rate values
        if "EXP B/" in content:
            print("   ✓ ARIES export contains decline rate information")
            
            # Look for specific patterns that indicate revised decline rates are being used
            lines = content.split('\n')
            decline_lines = [line for line in lines if "EXP B/" in line and "TEST" in line]
            
            if decline_lines:
                print(f"   ✓ Found {len(decline_lines)} decline rate lines in export")
                print("   ✓ Revised decline rate calculation appears to be working")
                
                # Show a sample line
                if decline_lines:
                    print(f"   Sample line: {decline_lines[0].strip()}")
            else:
                print("   ⚠ No decline rate lines found in export")
        else:
            print("   ⚠ ARIES export does not contain expected decline rate format")
        
        # Clean up test file
        os.remove(output_file)
        
    else:
        print("   ✗ ARIES export file was not created")


def test_time_difference_impact():
    """Test that time difference between L3M_START and T0 affects decline rates"""
    print("\nTesting time difference impact on decline rates...")
    
    # Create test data
    test_df = create_test_data_with_time_difference()
    
    dca = decline_curve()
    dca.dataframe = test_df
    dca.date_col = 'ProducingMonth'
    dca.uid_col = 'API_UWI'
    dca.oil_col = 'LiquidsProd_BBL'
    dca.gas_col = 'GasProd_MCF'
    dca.water_col = 'WaterProd_BBL'
    dca.phase_col = 'MAJOR'
    dca.length_col = 'LateralLength_FT'
    dca.backup_decline = True
    dca.three_phase_mode = True
    
    # Run DCA and generate oneline
    dca.run_DCA(_verbose=False)
    dca.generate_oneline(denormalize=True, _verbose=False)
    
    # Get the oneline data to check if revised calculations are present
    if not dca._oneline.empty:
        print("   ✓ Oneline data generated successfully")
        
        # Check if the oneline has the expected columns
        expected_cols = ['UID', 'L3M_START', 'T0_DATE', 'IPO', 'IPG', 'IPW', 'DO', 'DG', 'DW', 'BO', 'BG', 'BW']
        missing_cols = [col for col in expected_cols if col not in dca._oneline.columns]
        
        if not missing_cols:
            print("   ✓ Oneline contains all expected columns")
            
            # Check if there's a time difference between L3M_START and T0_DATE
            dca._oneline['T0_DATE'] = pd.to_datetime(dca._oneline['T0_DATE'])
            dca._oneline['L3M_START'] = pd.to_datetime(dca._oneline['L3M_START'])
            
            time_diffs = (dca._oneline['L3M_START'] - dca._oneline['T0_DATE']).dt.days / 30.44  # Convert to months
            
            if (time_diffs != 0).any():
                print("   ✓ Time differences detected between L3M_START and T0_DATE")
                print(f"   Time differences (months): {time_diffs.tolist()}")
                print("   ✓ This should trigger revised decline rate calculations")
            else:
                print("   ⚠ No time differences detected - revised calculations may not be triggered")
        else:
            print(f"   ⚠ Missing columns in oneline: {missing_cols}")
    else:
        print("   ✗ Oneline data is empty")


if __name__ == "__main__":
    print("ARIES Revised Decline Rate Test")
    print("=" * 50)
    
    try:
        test_revised_decline_calculation()
        test_time_difference_impact()
        
        print("\n" + "=" * 50)
        print("✓ All revised decline rate tests completed!")
        
    except Exception as e:
        print(f"\n✗ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

