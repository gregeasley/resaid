#!/usr/bin/env python3
"""
Test script for three-phase forecasting mode in the DCA module.
"""

import os
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from resaid.dca import decline_curve

def calculate_oneline_three_phase(production_df, b_min, b_max) -> pd.DataFrame:
    """Calculate oneline using three-phase forecasting mode"""
    
    l_dca = decline_curve()

    l_dca.backup_decline = True
    l_dca.SET_LENGTH = 10000
    l_dca.DEFAULT_B = (b_min + b_max) / 2
    l_dca.dataframe = production_df
    l_dca.date_col = 'ProducingMonth'
    l_dca.phase_col = 'MAJOR'
    l_dca.length_col = 'LateralLength_FT'
    l_dca.uid_col = 'API_UWI'
    l_dca.oil_col = 'LiquidsProd_BBL'
    l_dca.gas_col = 'GasProd_MCF'
    l_dca.water_col = 'WaterProd_BBL'
    l_dca.min_h_b = b_min
    l_dca.max_h_b = b_max
    l_dca.OUTLIER_CORRECTION = False

    # Enable three-phase mode
    l_dca.three_phase_mode = True

    l_dca.generate_oneline(denormalize=True)

    return l_dca.oneline_dataframe

def calculate_oneline_original(production_df, b_min, b_max) -> pd.DataFrame:
    """Calculate oneline using original mode for comparison"""
    
    l_dca = decline_curve()

    l_dca.backup_decline = True
    l_dca.SET_LENGTH = 10000
    l_dca.DEFAULT_B = (b_min + b_max) / 2
    l_dca.dataframe = production_df
    l_dca.date_col = 'ProducingMonth'
    l_dca.phase_col = 'MAJOR'
    l_dca.length_col = 'LateralLength_FT'
    l_dca.uid_col = 'API_UWI'
    l_dca.oil_col = 'LiquidsProd_BBL'
    l_dca.gas_col = 'GasProd_MCF'
    l_dca.water_col = 'WaterProd_BBL'
    l_dca.min_h_b = b_min
    l_dca.max_h_b = b_max
    l_dca.OUTLIER_CORRECTION = False

    # Use original mode
    l_dca.three_phase_mode = False

    l_dca.generate_oneline(denormalize=True)

    return l_dca.oneline_dataframe

def test_three_phase_mode():
    """Test the three-phase forecasting mode"""
    subset_path = Path(__file__).resolve().parent / "prod_df_subset.csv"
    if not subset_path.is_file():
        pytest.skip(f"Optional large fixture not found: {subset_path}")

    print("Testing three-phase forecasting mode...")

    # Load the existing test data
    print("Loading test data...")
    prod_df = pd.read_csv(subset_path)
    print(f"Loaded {len(prod_df)} records for {prod_df['API_UWI'].nunique()} wells")
    
    # Test original mode first
    print("\n--- Testing Original Mode ---")
    l_start = time.time()
    oneline_original = calculate_oneline_original(prod_df, b_min=0.9, b_max=1.3)
    l_duration = time.time() - l_start
    print(f"Original mode completed in {l_duration:.2f} seconds")
    print(f"Original mode: {len(oneline_original)} wells analyzed")
    print("Original mode columns:", list(oneline_original.columns))
    
    # Test three-phase mode
    print("\n--- Testing Three-Phase Mode ---")
    l_start = time.time()
    oneline_three_phase = calculate_oneline_three_phase(prod_df, b_min=0.9, b_max=1.3)
    l_duration = time.time() - l_start
    print(f"Three-phase mode completed in {l_duration:.2f} seconds")
    print(f"Three-phase mode: {len(oneline_three_phase)} wells analyzed")
    print("Three-phase mode columns:", list(oneline_three_phase.columns))
    
    # Compare the results
    print("\n--- Comparison ---")
    print(f"Original mode wells: {len(oneline_original)}")
    print(f"Three-phase mode wells: {len(oneline_three_phase)}")
    
    # Check for phase-specific columns in three-phase mode
    phase_columns = [col for col in oneline_three_phase.columns if col.startswith(('IPO', 'IPG', 'IPW', 'DO', 'DG', 'DW', 'BO', 'BG', 'BW', 'ARIES_DO', 'ARIES_DG', 'ARIES_DW'))]
    print(f"Phase-specific columns in three-phase mode: {len(phase_columns)}")
    print("Phase-specific columns:", phase_columns)
    
    # Save results for inspection
    oneline_original.to_csv('tests/oneline_original.csv', index=False)
    oneline_three_phase.to_csv('tests/oneline_three_phase.csv', index=False)
    print("\nResults saved to:")
    print("  tests/oneline_original.csv")
    print("  tests/oneline_three_phase.csv")
    
    # Show sample of three-phase results
    print("\n--- Sample Three-Phase Results ---")
    if len(oneline_three_phase) > 0:
        sample_cols = ['UID', 'OIL', 'GAS', 'WATER'] + phase_columns[:6]  # Show first 6 phase columns
        available_cols = [col for col in sample_cols if col in oneline_three_phase.columns]
        print(oneline_three_phase[available_cols].head())
    
    print("\nThree-phase mode test completed successfully!")

if __name__ == "__main__":
    test_three_phase_mode()
