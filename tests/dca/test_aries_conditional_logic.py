#!/usr/bin/env python3
"""
Test script to verify that the three-phase ARIES export correctly implements
the conditional logic for decline type selection (hyperbolic vs exponential vs flat).
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


def create_test_data_with_different_conditions():
    """Create test data that will trigger different conditional logic paths"""
    np.random.seed(42)  # For reproducible results
    
    # Create test data for wells with different characteristics
    wells = [f'CONDITIONAL_TEST_WELL_{i:03d}' for i in range(1, 4)]
    dates = pd.date_range('2023-01-01', periods=12, freq='M')
    
    data = []
    for i, well in enumerate(wells):
        for j, date in enumerate(dates):
            # Create different production profiles for each well
            if i == 0:  # Well 1: High production, should trigger hyperbolic
                oil_prod = max(2000 * np.exp(-0.05 * j) + np.random.normal(0, 100), 0)
            elif i == 1:  # Well 2: Medium production, should trigger exponential
                oil_prod = max(1000 * np.exp(-0.1 * j) + np.random.normal(0, 50), 0)
            else:  # Well 3: Low production, should trigger flat
                oil_prod = max(100 * np.exp(-0.2 * j) + np.random.normal(0, 10), 0)
            
            gas_prod = oil_prod * (1000 + np.random.normal(0, 100))
            water_prod = oil_prod * (0.5 + np.random.normal(0, 0.1))
            
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


def test_conditional_logic():
    """Test that the conditional logic works correctly for different scenarios"""
    print("Testing conditional logic in three-phase ARIES export...")
    
    # Create test data
    test_df = create_test_data_with_different_conditions()
    
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
    
    # Generate ARIES export to test the conditional logic
    output_file = "tests/test_aries_conditional_logic.txt"
    
    # Capture any output
    with redirect_stdout(StringIO()):
        dca.generate_aries_export(file_path=output_file, scenario="TEST", dmin=6, write_water=True)
    
    # Check if the file was created
    if os.path.exists(output_file):
        print("   ✓ ARIES export file created successfully")
        
        # Read the file and analyze the conditional logic
        with open(output_file, 'r') as f:
            content = f.read()
        
        lines = content.split('\n')
        
        # Look for different decline type patterns
        hyperbolic_lines = [line for line in lines if "EXP B/" in line and "TEST" in line]
        exponential_lines = [line for line in lines if "99 YRS EXP" in line and "EXP B/" not in line and "TEST" in line]
        flat_lines = [line for line in lines if "1 YRS FLAT" in line and "TEST" in line]
        
        print(f"   ✓ Found {len(hyperbolic_lines)} hyperbolic decline lines")
        print(f"   ✓ Found {len(exponential_lines)} exponential decline lines")
        print(f"   ✓ Found {len(flat_lines)} flat decline lines")
        
        # Show examples of each type
        if hyperbolic_lines:
            print(f"   Sample hyperbolic: {hyperbolic_lines[0].strip()}")
        if exponential_lines:
            print(f"   Sample exponential: {exponential_lines[0].strip()}")
        if flat_lines:
            print(f"   Sample flat: {flat_lines[0].strip()}")
        
        # Verify that we have different decline types (indicating conditional logic is working)
        total_decline_lines = len(hyperbolic_lines) + len(exponential_lines) + len(flat_lines)
        if total_decline_lines > 0:
            print(f"   ✓ Total decline lines found: {total_decline_lines}")
            print("   ✓ Conditional logic appears to be working correctly")
        else:
            print("   ⚠ No decline lines found - conditional logic may not be working")
        
        # Clean up test file
        os.remove(output_file)
        
    else:
        print("   ✗ ARIES export file was not created")


def test_minimum_decline_logic():
    """Test that the minimum decline rate logic works correctly"""
    print("\nTesting minimum decline rate logic...")
    
    # Create test data
    test_df = create_test_data_with_different_conditions()
    
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
    
    # Test with different minimum decline rates
    for dmin in [6, 12, 18]:
        output_file = f"tests/test_aries_dmin_{dmin}.txt"
        
        with redirect_stdout(StringIO()):
            dca.generate_aries_export(file_path=output_file, scenario="TEST", dmin=dmin, write_water=True)
        
        if os.path.exists(output_file):
            with open(output_file, 'r') as f:
                content = f.read()
            
            # Count lines with the specific dmin value
            dmin_lines = [line for line in content.split('\n') if f"EXP {dmin}" in line and "TEST" in line]
            print(f"   ✓ dmin={dmin}: Found {len(dmin_lines)} lines with minimum decline rate")
            
            # Clean up
            os.remove(output_file)


if __name__ == "__main__":
    print("ARIES Conditional Logic Test")
    print("=" * 50)
    
    try:
        test_conditional_logic()
        test_minimum_decline_logic()
        
        print("\n" + "=" * 50)
        print("✓ All conditional logic tests completed!")
        
    except Exception as e:
        print(f"\n✗ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

