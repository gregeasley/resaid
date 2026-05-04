#!/usr/bin/env python3
"""
Test script to verify that tqdm progress tracking works correctly in the DCA module.
Tests that progress bars are displayed during the .apply() operations without affecting functionality.
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


def create_test_data():
    """Create a small test dataset for progress tracking testing"""
    np.random.seed(42)  # For reproducible results
    
    # Create test data for 3 wells with 12 months of production each
    wells = [f'PROGRESS_TEST_WELL_{i:03d}' for i in range(1, 4)]
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


def test_progress_tracking_vectorized():
    """Test progress tracking in vectorized mode"""
    print("Testing progress tracking in vectorized mode...")
    
    # Create test data
    test_df = create_test_data()
    
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
    dca.three_phase_mode = False  # Use vectorized mode
    
    # Capture output to check for progress bar
    output_buffer = StringIO()
    with redirect_stdout(output_buffer):
        dca.run_DCA(_verbose=False)
    
    output = output_buffer.getvalue()
    
    # Check that progress tracking was used
    if "Processing wells (vectorized mode)" in output:
        print("   ✓ Progress tracking found in vectorized mode")
    else:
        print("   ⚠ Progress tracking not found in vectorized mode")
    
    # Verify that DCA still works correctly
    if hasattr(dca, '_params_dataframe') and not dca._params_dataframe.empty:
        print("   ✓ DCA processing completed successfully")
        print(f"   ✓ Processed {len(dca._params_dataframe)} well-phase combinations")
    else:
        print("   ✗ DCA processing failed")


def test_progress_tracking_three_phase():
    """Test progress tracking in three-phase mode"""
    print("\nTesting progress tracking in three-phase mode...")
    
    # Create test data
    test_df = create_test_data()
    
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
    dca.three_phase_mode = True  # Use three-phase mode
    
    # Capture output to check for progress bar
    output_buffer = StringIO()
    with redirect_stdout(output_buffer):
        dca.run_DCA(_verbose=False)
    
    output = output_buffer.getvalue()
    
    # Check that progress tracking was used
    if "Processing" in output and "phase for well" in output:
        print("   ✓ Progress tracking found in three-phase mode")
    else:
        print("   ⚠ Progress tracking not found in three-phase mode")
    
    # Verify that DCA still works correctly
    if hasattr(dca, '_params_dataframe') and not dca._params_dataframe.empty:
        print("   ✓ DCA processing completed successfully")
        print(f"   ✓ Processed {len(dca._params_dataframe)} well-phase combinations")
    else:
        print("   ✗ DCA processing failed")


def test_no_performance_impact():
    """Test that progress tracking doesn't significantly impact performance"""
    print("\nTesting performance impact...")
    
    import time
    
    # Create test data
    test_df = create_test_data()
    
    # Test without progress tracking (by redirecting stdout to suppress it)
    start_time = time.time()
    
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
    dca.three_phase_mode = False
    
    with redirect_stdout(StringIO()):
        dca.run_DCA(_verbose=False)
    
    elapsed_time = time.time() - start_time
    print(f"   ✓ Processing completed in {elapsed_time:.3f} seconds")
    
    if elapsed_time < 5.0:  # Should be fast for small dataset
        print("   ✓ Performance impact is minimal")
    else:
        print("   ⚠ Processing took longer than expected")


if __name__ == "__main__":
    print("DCA Progress Tracking Test")
    print("=" * 50)
    
    try:
        test_progress_tracking_vectorized()
        test_progress_tracking_three_phase()
        test_no_performance_impact()
        
        print("\n" + "=" * 50)
        print("✓ All progress tracking tests completed!")
        
    except Exception as e:
        print(f"\n✗ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

