#!/usr/bin/env python3
"""
Validate that three-phase mode produces identical major phase results to original mode.
"""

import pandas as pd
import numpy as np
from resaid.dca import decline_curve
import time

def run_dca_analysis(mode='original'):
    """Run DCA analysis in specified mode"""
    print(f"\nRunning DCA analysis in {mode} mode...")
    
    # Load test data
    prod_df = pd.read_csv('tests/prod_df_subset.csv')
    print(f"Test data: {len(prod_df)} records for {prod_df['API_UWI'].nunique()} wells")
    
    # Setup DCA with exact same parameters
    l_dca = decline_curve()
    l_dca.backup_decline = True
    l_dca.SET_LENGTH = 10000
    l_dca.DEFAULT_B = 1.1  # (0.9 + 1.3) / 2
    l_dca.dataframe = prod_df
    l_dca.date_col = 'ProducingMonth'
    l_dca.phase_col = 'MAJOR'
    l_dca.length_col = 'LateralLength_FT'
    l_dca.uid_col = 'API_UWI'
    l_dca.oil_col = 'LiquidsProd_BBL'
    l_dca.gas_col = 'GasProd_MCF'
    l_dca.water_col = 'WaterProd_BBL'
    l_dca.min_h_b = 0.9
    l_dca.max_h_b = 1.3
    l_dca.OUTLIER_CORRECTION = False
    
    # Set mode
    if mode == 'three_phase':
        l_dca.three_phase_mode = True
    else:
        l_dca.three_phase_mode = False
    
    # Run analysis
    l_start = time.time()
    l_dca.generate_oneline(denormalize=True)
    l_duration = time.time() - l_start
    print(f"{mode.capitalize()} mode completed in {l_duration:.2f} seconds")
    
    return l_dca.oneline_dataframe

def compare_major_phase_results(original_df, three_phase_df):
    """Compare major phase parameters between original and three-phase modes"""
    print("\n--- Comparing Major Phase Results ---")
    
    # Ensure we have the same wells
    original_wells = set(original_df['UID'])
    three_phase_wells = set(three_phase_df['UID'])
    
    if original_wells != three_phase_wells:
        print("✗ Different wells in results!")
        missing_in_original = three_phase_wells - original_wells
        missing_in_three_phase = original_wells - three_phase_wells
        if missing_in_original:
            print(f"  Missing in original: {len(missing_in_original)} wells")
        if missing_in_three_phase:
            print(f"  Missing in three-phase: {len(missing_in_three_phase)} wells")
        return False
    
    print(f"✓ Same wells in both modes: {len(original_wells)}")
    
    # Compare major phase parameters
    comparison_results = []
    
    for uid in original_wells:
        orig_row = original_df[original_df['UID'] == uid].iloc[0]
        three_row = three_phase_df[three_phase_df['UID'] == uid].iloc[0]
        
        # Get major phase
        major_phase = orig_row['MAJOR']
        
        # Compare parameters based on major phase
        if major_phase == 'OIL':
            # Compare oil parameters
            orig_qi = orig_row['IPO']
            orig_di = orig_row['DE']
            orig_b = orig_row['B']
            orig_aries = orig_row['ARIES_DE']
            
            three_qi = three_row['IPO']
            three_di = three_row['DO']
            three_b = three_row['BO']
            three_aries = three_row['ARIES_DO']
            
        elif major_phase == 'GAS':
            # Compare gas parameters
            orig_qi = orig_row['IPG']
            orig_di = orig_row['DE']
            orig_b = orig_row['B']
            orig_aries = orig_row['ARIES_DE']
            
            three_qi = three_row['IPG']
            three_di = three_row['DG']
            three_b = three_row['BG']
            three_aries = three_row['ARIES_DG']
        
        # Check if parameters match exactly
        qi_match = abs(orig_qi - three_qi) < 1e-10
        di_match = abs(orig_di - three_di) < 1e-10
        b_match = abs(orig_b - three_b) < 1e-10
        aries_match = abs(orig_aries - three_aries) < 1e-10
        
        all_match = qi_match and di_match and b_match and aries_match
        
        comparison_results.append({
            'UID': uid,
            'MAJOR': major_phase,
            'QI_MATCH': qi_match,
            'DI_MATCH': di_match,
            'B_MATCH': b_match,
            'ARIES_MATCH': aries_match,
            'ALL_MATCH': all_match,
            'ORIG_QI': orig_qi,
            'THREE_QI': three_qi,
            'ORIG_DI': orig_di,
            'THREE_DI': three_di,
            'ORIG_B': orig_b,
            'THREE_B': three_b,
            'ORIG_ARIES': orig_aries,
            'THREE_ARIES': three_aries
        })
    
    # Create comparison dataframe
    comparison_df = pd.DataFrame(comparison_results)
    
    # Summary statistics
    total_wells = len(comparison_df)
    matching_wells = comparison_df['ALL_MATCH'].sum()
    match_rate = matching_wells / total_wells if total_wells > 0 else 0
    
    print(f"Total wells compared: {total_wells}")
    print(f"Wells with matching major phase parameters: {matching_wells}")
    print(f"Match rate: {match_rate:.2%}")
    
    # Show mismatches if any
    mismatches = comparison_df[~comparison_df['ALL_MATCH']]
    if len(mismatches) > 0:
        print(f"\n✗ Mismatches found ({len(mismatches)} wells):")
        for _, row in mismatches.head(10).iterrows():
            print(f"  {row['UID']} ({row['MAJOR']}): QI={row['QI_MATCH']}, DI={row['DI_MATCH']}, B={row['B_MATCH']}, ARIES={row['ARIES_MATCH']}")
        if len(mismatches) > 10:
            print(f"  ... and {len(mismatches) - 10} more")
        return False
    else:
        print("✓ All major phase parameters match exactly!")
        return True

def main():
    """Main validation function"""
    print("=== Three-Phase Mode Validation ===")
    
    # Run original mode analysis
    original_df = run_dca_analysis('original')
    
    # Run three-phase mode analysis
    three_phase_df = run_dca_analysis('three_phase')
    
    # Compare results
    success = compare_major_phase_results(original_df, three_phase_df)
    
    # Show three-phase specific features
    print("\n--- Three-Phase Mode Features ---")
    print(f"Original mode columns: {list(original_df.columns)}")
    print(f"Three-phase mode columns: {list(three_phase_df.columns)}")
    
    # Check for phase-specific columns
    phase_columns = [col for col in three_phase_df.columns if col.startswith(('IPO', 'IPG', 'IPW', 'DO', 'DG', 'DW', 'BO', 'BG', 'BW', 'ARIES_DO', 'ARIES_DG', 'ARIES_DW'))]
    print(f"Phase-specific columns in three-phase mode: {len(phase_columns)}")
    print("Phase-specific columns:", phase_columns)
    
    # Show sample of three-phase results
    print("\n--- Sample Three-Phase Results ---")
    if len(three_phase_df) > 0:
        sample_cols = ['UID', 'OIL', 'GAS', 'WATER'] + phase_columns[:6]
        available_cols = [col for col in sample_cols if col in three_phase_df.columns]
        print(three_phase_df[available_cols].head())
    
    if success:
        print("\n✓ Three-phase mode validation successful!")
        print("  - Major phase parameters match exactly")
        print("  - Additional phase-specific parameters available")
        print("  - No regression in existing functionality")
    else:
        print("\n✗ Three-phase mode validation failed!")
        print("  - Major phase parameters do not match")
        print("  - Regression detected in existing functionality")
    
    return success

if __name__ == "__main__":
    main()
