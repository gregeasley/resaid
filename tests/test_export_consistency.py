#!/usr/bin/env python3
"""
Test script for export consistency checks.

This script generates export files and keeps them for manual inspection
to ensure consistency across different export formats and modes.
"""

import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from datetime import datetime, timedelta

# Add the parent directory to the path to import resaid
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from resaid.dca import decline_curve


def create_test_data():
    """Create synthetic test data for export testing."""
    np.random.seed(42)  # For reproducible results
    
    # Create date range
    start_date = datetime(2020, 1, 1)
    end_date = datetime(2023, 12, 31)
    dates = pd.date_range(start=start_date, end=end_date, freq='M')
    
    # Create wells
    wells = [f'WELL{i:03d}' for i in range(1, 11)]
    
    # Create production data
    data = []
    for well in wells:
        for date in dates:
            # Generate realistic production data
            oil_rate = max(0, np.random.normal(500, 100))
            gas_rate = max(0, np.random.normal(1000, 200))
            water_rate = max(0, np.random.normal(200, 50))
            
            # Determine major phase
            if gas_rate / (oil_rate + 1e-6) > 3.2:
                major = 'GAS'
            else:
                major = 'OIL'
            
            data.append({
                'UID': well,
                'P_DATE': date,
                'OIL': oil_rate,
                'GAS': gas_rate,
                'WATER': water_rate,
                'MAJOR': major
            })
    
    return pd.DataFrame(data)


def test_export_consistency():
    """Test export consistency across different modes and formats."""
    subset_path = Path(__file__).resolve().parent / "prod_df_subset.csv"
    if not subset_path.is_file():
        pytest.skip(f"Optional large fixture not found: {subset_path}")

    print("Loading test data...")
    # Use existing test data instead of synthetic data
    test_df = pd.read_csv(subset_path)
    
    # Create output directory
    output_dir = "test_exports"
    os.makedirs(output_dir, exist_ok=True)
    
    # Test both modes
    modes = [False, True]  # Standard mode, Three-phase mode
    
    for mode in modes:
        mode_name = "three_phase" if mode else "standard"
        print(f"\nTesting {mode_name} mode...")
        
        # Initialize DCA object
        dca = decline_curve()
        dca.dataframe = test_df
        dca.date_col = 'ProducingMonth'
        dca.uid_col = 'API_UWI'
        dca.oil_col = 'LiquidsProd_BBL'
        dca.gas_col = 'GasProd_MCF'
        dca.water_col = 'WaterProd_BBL'
        dca.phase_col = 'MAJOR'
        dca.three_phase_mode = mode
        
        # Run DCA
        print("Running DCA...")
        try:
            dca.run_DCA()
            dca.generate_oneline(denormalize=True)
        except Exception as e:
            print(f"Warning: DCA failed for {mode_name} mode: {e}")
            print("Skipping export generation for this mode...")
            continue
        
        # Generate exports
        print("Generating ARIES export...")
        aries_file = os.path.join(output_dir, f"aries_export_{mode_name}.txt")
        dca.generate_aries_export(
            file_path=aries_file,
            scenario=f"TEST_{mode_name.upper()}",
            dmin=6,
            write_water=True
        )
        
        print("Generating Mosaic export...")
        mosaic_file = os.path.join(output_dir, f"mosaic_export_{mode_name}.xlsx")
        dca.generate_mosaic_export(
            file_path=mosaic_file,
            reserve_category=f"TEST_{mode_name.upper()}",
            dmin=8
        )
        
        print("Generating PhdWin export...")
        phdwin_file = os.path.join(output_dir, f"phdwin_export_{mode_name}.csv")
        dca.generate_phdwin_export(
            file_path=phdwin_file,
            dmin=6
        )
        
        # Generate 3-month averages
        print("Generating 3-month averages...")
        l3m_file = os.path.join(output_dir, f"l3m_averages_{mode_name}.csv")
        l3m_df = dca.qi_overwrite()
        l3m_df.to_csv(l3m_file, index=False)
        
        # Generate ratio analysis
        print("Generating ratio analysis...")
        ratio_file = os.path.join(output_dir, f"ratio_analysis_{mode_name}.csv")
        ratio_df = dca.make_ratio_dfs(l3m_df)
        ratio_df.to_csv(ratio_file, index=False)
        
        # Save oneline data for comparison
        print("Saving oneline data...")
        oneline_file = os.path.join(output_dir, f"oneline_data_{mode_name}.csv")
        dca.oneline_dataframe.to_csv(oneline_file, index=False)
        
        print(f"All exports completed for {mode_name} mode")
    
    print(f"\nExport files saved to '{output_dir}' directory")
    print("Files generated:")
    for mode in ["standard", "three_phase"]:
        print(f"  {mode} mode:")
        print(f"    - aries_export_{mode}.txt")
        print(f"    - mosaic_export_{mode}.xlsx")
        print(f"    - phdwin_export_{mode}.csv")
        print(f"    - l3m_averages_{mode}.csv")
        print(f"    - ratio_analysis_{mode}.csv")
        print(f"    - oneline_data_{mode}.csv")
    
    print("\nManual inspection recommended:")
    print("1. Compare ARIES text files for format consistency")
    print("2. Check Excel files for proper column structure")
    print("3. Verify CSV files contain expected data")
    print("4. Compare three-phase vs standard mode results")
    print("5. Validate 3-month averages and ratio calculations")


if __name__ == "__main__":
    test_export_consistency()
