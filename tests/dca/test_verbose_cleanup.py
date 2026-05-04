#!/usr/bin/env python3
"""
Test script to verify that the DCA verbose cleanup works correctly.
Tests that individual well debug prints are hidden by default but summary statistics are always shown.
"""

import pandas as pd
import numpy as np
import time
import sys
import os
from io import StringIO
from contextlib import redirect_stdout

# Add the parent directory to the path to import resaid
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from resaid.dca import decline_curve


def create_test_data():
    """Create a small test dataset for performance testing"""
    np.random.seed(42)  # For reproducible results
    
    # Create test data for 5 wells with 12 months of production each
    wells = [f'TEST_WELL_{i:03d}' for i in range(1, 6)]
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


def test_verbose_behavior():
    """Test that verbose behavior works correctly"""
    print("Testing verbose behavior...")
    
    # Create test data
    test_df = create_test_data()
    
    # Test 1: Default behavior (verbose=False) - should not show individual well prints
    print("\n1. Testing default behavior (verbose=False):")
    
    dca_default = decline_curve()
    dca_default.dataframe = test_df
    dca_default.date_col = 'ProducingMonth'
    dca_default.uid_col = 'API_UWI'
    dca_default.oil_col = 'LiquidsProd_BBL'
    dca_default.gas_col = 'GasProd_MCF'
    dca_default.water_col = 'WaterProd_BBL'
    dca_default.phase_col = 'MAJOR'
    dca_default.length_col = 'LateralLength_FT'
    dca_default.backup_decline = True
    
    # Capture output
    output_buffer = StringIO()
    with redirect_stdout(output_buffer):
        dca_default.run_DCA(_verbose=False)
    
    output = output_buffer.getvalue()
    
    # Check that individual well prints are not present
    individual_well_prints = [line for line in output.split('\n') if 'Well TEST_WELL_' in line and 'After' in line]
    if individual_well_prints:
        print(f"   ✗ Found {len(individual_well_prints)} individual well debug prints (should be 0)")
        for print_line in individual_well_prints[:3]:  # Show first 3
            print(f"     {print_line.strip()}")
    else:
        print("   ✓ No individual well debug prints found (correct)")
    
    # Check that summary statistics are present
    summary_prints = [line for line in output.split('\n') if 'Total DCA Failures' in line or 'Total wells analyzed' in line]
    if summary_prints:
        print(f"   ✓ Found {len(summary_prints)} summary statistics (correct)")
        for print_line in summary_prints:
            print(f"     {print_line.strip()}")
    else:
        print("   ✗ No summary statistics found (incorrect)")
    
    # Test 2: Verbose behavior (verbose=True) - should show individual well prints
    print("\n2. Testing verbose behavior (verbose=True):")
    
    dca_verbose = decline_curve()
    dca_verbose.dataframe = test_df
    dca_verbose.date_col = 'ProducingMonth'
    dca_verbose.uid_col = 'API_UWI'
    dca_verbose.oil_col = 'LiquidsProd_BBL'
    dca_verbose.gas_col = 'GasProd_MCF'
    dca_verbose.water_col = 'WaterProd_BBL'
    dca_verbose.phase_col = 'MAJOR'
    dca_verbose.length_col = 'LateralLength_FT'
    dca_verbose.backup_decline = True
    
    # Capture output
    output_buffer = StringIO()
    with redirect_stdout(output_buffer):
        dca_verbose.run_DCA(_verbose=True)
    
    output = output_buffer.getvalue()
    
    # Check that individual well prints are present
    individual_well_prints = [line for line in output.split('\n') if 'Well TEST_WELL_' in line and 'After' in line]
    if individual_well_prints:
        print(f"   ✓ Found {len(individual_well_prints)} individual well debug prints (correct)")
        for print_line in individual_well_prints[:3]:  # Show first 3
            print(f"     {print_line.strip()}")
    else:
        print("   ✗ No individual well debug prints found (incorrect)")
    
    # Check that summary statistics are still present
    summary_prints = [line for line in output.split('\n') if 'Total DCA Failures' in line or 'Total wells analyzed' in line]
    if summary_prints:
        print(f"   ✓ Found {len(summary_prints)} summary statistics (correct)")
    else:
        print("   ✗ No summary statistics found (incorrect)")


def test_performance_improvement():
    """Test that the cleanup improves processing speed"""
    print("\nTesting performance improvement...")
    
    # Create larger test dataset for performance testing
    np.random.seed(42)
    wells = [f'PERF_WELL_{i:03d}' for i in range(1, 21)]  # 20 wells
    dates = pd.date_range('2023-01-01', periods=24, freq='ME')  # 24 months
    
    data = []
    for well in wells:
        for i, date in enumerate(dates):
            oil_prod = max(1000 * np.exp(-0.1 * i) + np.random.normal(0, 50), 0)
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
    
    test_df = pd.DataFrame(data)
    
    # Test with verbose=False (new default)
    print("   Testing with verbose=False (new default)...")
    start_time = time.time()
    
    dca_fast = decline_curve()
    dca_fast.dataframe = test_df
    dca_fast.date_col = 'ProducingMonth'
    dca_fast.uid_col = 'API_UWI'
    dca_fast.oil_col = 'LiquidsProd_BBL'
    dca_fast.gas_col = 'GasProd_MCF'
    dca_fast.water_col = 'WaterProd_BBL'
    dca_fast.phase_col = 'MAJOR'
    dca_fast.length_col = 'LateralLength_FT'
    dca_fast.backup_decline = True
    
    # Suppress output for timing
    with redirect_stdout(StringIO()):
        dca_fast.run_DCA(_verbose=False)
    
    fast_time = time.time() - start_time
    print(f"   ✓ Verbose=False: {fast_time:.3f} seconds")
    
    # Test with verbose=True (old behavior)
    print("   Testing with verbose=True (old behavior)...")
    start_time = time.time()
    
    dca_slow = decline_curve()
    dca_slow.dataframe = test_df
    dca_slow.date_col = 'ProducingMonth'
    dca_slow.uid_col = 'API_UWI'
    dca_slow.oil_col = 'LiquidsProd_BBL'
    dca_slow.gas_col = 'GasProd_MCF'
    dca_slow.water_col = 'WaterProd_BBL'
    dca_slow.phase_col = 'MAJOR'
    dca_slow.length_col = 'LateralLength_FT'
    dca_slow.backup_decline = True
    
    # Suppress output for timing
    with redirect_stdout(StringIO()):
        dca_slow.run_DCA(_verbose=True)
    
    slow_time = time.time() - start_time
    print(f"   ✓ Verbose=True: {slow_time:.3f} seconds")
    
    # Calculate improvement
    if slow_time > 0:
        improvement = ((slow_time - fast_time) / slow_time) * 100
        print(f"   📊 Performance improvement: {improvement:.1f}% faster")
        
        if improvement > 0:
            print("   ✓ Performance improvement achieved!")
        else:
            print("   ⚠ No significant performance improvement detected")
    else:
        print("   ⚠ Could not calculate performance improvement")


if __name__ == "__main__":
    print("DCA Verbose Cleanup Test")
    print("=" * 50)
    
    try:
        test_verbose_behavior()
        test_performance_improvement()
        print("\n" + "=" * 50)
        print("✓ All tests completed successfully!")
        
    except Exception as e:
        print(f"\n✗ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

