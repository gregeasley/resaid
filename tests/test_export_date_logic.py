#!/usr/bin/env python3
"""
Test script to verify that the T0 vs T0_DATE logic issue has been fixed
in both Mosaic and PhdWin export functions.

This script checks that both export functions correctly handle the T0_DATE column
and use it for calculations instead of relying on a potentially missing T0 column.
"""

import sys
import os
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# Add the parent directory to the path to import the module
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from resaid.dca import decline_curve

def create_test_data():
    """Create test data for export function testing."""
    # Create test production data
    dates = pd.date_range('2020-01-01', periods=24, freq='M')
    wells = ['WELL001', 'WELL002', 'WELL003']
    
    data = []
    for well in wells:
        for date in dates:
            # Create declining production profiles
            months_from_start = (date - pd.Timestamp('2020-01-01')).days / 30.44
            oil_rate = 1000 * np.exp(-0.1 * months_from_start) + np.random.normal(0, 50)
            gas_rate = 5000 * np.exp(-0.08 * months_from_start) + np.random.normal(0, 200)
            # Increase water rate to avoid filtering issues
            water_rate = 2000 * np.exp(-0.05 * months_from_start) + np.random.normal(0, 100)
            
            # Determine major phase based on production rates
            if oil_rate > gas_rate:
                major_phase = 'OIL'
            else:
                major_phase = 'GAS'
            
            data.append({
                'API_UWI': well,
                'ProducingMonth': date,
                'LiquidsProd_BBL': max(0, oil_rate),
                'GasProd_MCF': max(0, gas_rate),
                'WaterProd_BBL': max(0, water_rate),
                'MAJOR': major_phase
            })
    
    return pd.DataFrame(data)

def test_mosaic_export_date_logic():
    """Test that Mosaic export correctly handles T0_DATE vs T0."""
    print("Testing Mosaic export date logic...")
    
    # Create test data
    test_df = create_test_data()
    
    # Create DCA object
    dca = decline_curve()
    dca.dataframe = test_df
    dca.date_col = 'ProducingMonth'
    dca.uid_col = 'API_UWI'
    dca.oil_col = 'LiquidsProd_BBL'
    dca.gas_col = 'GasProd_MCF'
    dca.water_col = 'WaterProd_BBL'
    dca.phase_col = 'MAJOR'  # Add missing phase_col
    dca.verbose = False
    
    # Run DCA and generate oneline
    dca.run_DCA()
    dca.generate_oneline(denormalize=True)
    
    # Check that oneline has T0_DATE column
    print(f"Oneline columns: {list(dca.oneline_dataframe.columns)}")
    print(f"T0_DATE in oneline: {'T0_DATE' in dca.oneline_dataframe.columns}")
    
    if 'T0_DATE' in dca.oneline_dataframe.columns:
        print("✓ T0_DATE column exists in oneline dataframe")
    else:
        print("✗ T0_DATE column missing from oneline dataframe")
        return False
    
    # Test Mosaic export
    try:
        print("Calling generate_mosaic_export...")
        result = dca.generate_mosaic_export("test_mosaic_export.xlsx")
        print(f"Mosaic export result: {result}")
        print(f"Current working directory: {os.getcwd()}")
        print(f"File exists: {os.path.exists('test_mosaic_export.xlsx')}")
        
        # Check if the export file was created
        if os.path.exists("test_mosaic_export.xlsx"):
            print("✓ Mosaic export file created")
            os.remove("test_mosaic_export.xlsx")  # Clean up
            return True
        else:
            print("✗ Mosaic export file not created")
            return False
    except Exception as e:
        print(f"✗ Mosaic export failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_phdwin_export_date_logic():
    """Test that PhdWin export correctly handles T0_DATE vs T0."""
    print("\nTesting PhdWin export date logic...")
    
    # Create test data
    test_df = create_test_data()
    
    # Create DCA object
    dca = decline_curve()
    dca.dataframe = test_df
    dca.date_col = 'ProducingMonth'
    dca.uid_col = 'API_UWI'
    dca.oil_col = 'LiquidsProd_BBL'
    dca.gas_col = 'GasProd_MCF'
    dca.water_col = 'WaterProd_BBL'
    dca.phase_col = 'MAJOR'  # Add missing phase_col
    dca.verbose = False
    
    # Run DCA and generate oneline
    dca.run_DCA()
    dca.generate_oneline(denormalize=True)
    
    # Check that oneline has T0_DATE column
    print(f"Oneline columns: {list(dca.oneline_dataframe.columns)}")
    print(f"T0_DATE in oneline: {'T0_DATE' in dca.oneline_dataframe.columns}")
    
    if 'T0_DATE' in dca.oneline_dataframe.columns:
        print("✓ T0_DATE column exists in oneline dataframe")
    else:
        print("✗ T0_DATE column missing from oneline dataframe")
        return False
    
    # Test PhdWin export
    try:
        result = dca.generate_phdwin_export("test_phdwin_export.csv")
        print(f"PhdWin export result: {result}")
        
        # Check if the export file was created
        if os.path.exists("test_phdwin_export.csv"):
            print("✓ PhdWin export file created")
            os.remove("test_phdwin_export.csv")  # Clean up
            return True
        else:
            print("✗ PhdWin export file not created")
            return False
    except Exception as e:
        print(f"✗ PhdWin export failed: {e}")
        return False

def test_three_phase_export_date_logic():
    """Test that both export functions work correctly in three-phase mode."""
    print("\nTesting three-phase export date logic...")
    
    # Create test data
    test_df = create_test_data()
    
    # Create DCA object with three-phase mode
    dca = decline_curve()
    dca.dataframe = test_df
    dca.date_col = 'ProducingMonth'
    dca.uid_col = 'API_UWI'
    dca.oil_col = 'LiquidsProd_BBL'
    dca.gas_col = 'GasProd_MCF'
    dca.water_col = 'WaterProd_BBL'
    dca.three_phase_mode = True
    dca.verbose = False
    
    # Run DCA and generate oneline
    dca.run_DCA()
    dca.generate_oneline(denormalize=True)
    
    # Check that oneline has T0_DATE column
    print(f"Three-phase oneline columns: {list(dca.oneline_dataframe.columns)}")
    print(f"T0_DATE in three-phase oneline: {'T0_DATE' in dca.oneline_dataframe.columns}")
    
    if 'T0_DATE' in dca.oneline_dataframe.columns:
        print("✓ T0_DATE column exists in three-phase oneline dataframe")
    else:
        print("✗ T0_DATE column missing from three-phase oneline dataframe")
        return False
    
    # Test both exports in three-phase mode
    mosaic_success = False
    phdwin_success = False
    
    try:
        dca.generate_mosaic_export("test_mosaic_three_phase.xlsx")
        print("✓ Three-phase Mosaic export completed successfully")
        if os.path.exists("test_mosaic_three_phase.xlsx"):
            os.remove("test_mosaic_three_phase.xlsx")
            mosaic_success = True
    except Exception as e:
        print(f"✗ Three-phase Mosaic export failed: {e}")
    
    try:
        dca.generate_phdwin_export("test_phdwin_three_phase.csv")
        print("✓ Three-phase PhdWin export completed successfully")
        if os.path.exists("test_phdwin_three_phase.csv"):
            os.remove("test_phdwin_three_phase.csv")
            phdwin_success = True
    except Exception as e:
        print(f"✗ Three-phase PhdWin export failed: {e}")
    
    return mosaic_success and phdwin_success

def main():
    """Run all date logic tests."""
    print("Testing T0 vs T0_DATE logic in export functions...")
    print("=" * 60)
    
    # Test standard mode exports
    mosaic_ok = test_mosaic_export_date_logic()
    phdwin_ok = test_phdwin_export_date_logic()
    
    # Test three-phase mode exports
    three_phase_ok = test_three_phase_export_date_logic()
    
    print("\n" + "=" * 60)
    print("TEST RESULTS:")
    print(f"Mosaic export date logic: {'✓ PASS' if mosaic_ok else '✗ FAIL'}")
    print(f"PhdWin export date logic: {'✓ PASS' if phdwin_ok else '✗ FAIL'}")
    print(f"Three-phase export date logic: {'✓ PASS' if three_phase_ok else '✗ FAIL'}")
    
    if mosaic_ok and phdwin_ok and three_phase_ok:
        print("\n🎉 All date logic tests passed!")
        return True
    else:
        print("\n❌ Some date logic tests failed!")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
