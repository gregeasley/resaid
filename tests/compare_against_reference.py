#!/usr/bin/env python3
"""
Compare original and three-phase mode results against reference file
to ensure major phase parameters haven't changed.
"""

import pandas as pd
import numpy as np
from resaid.dca import decline_curve
import time

def load_reference_data():
    """Load the reference oneline data"""
    print("Loading reference data...")
    reference_df = pd.read_csv('tests/oneline_reference.csv')
    print(f"Reference data: {len(reference_df)} wells")
    return reference_df

def run_dca_analysis(mode='original'):
    """Run DCA analysis in specified mode"""
    print(f"\nRunning DCA analysis in {mode} mode...")
    
    # Load test data
    prod_df = pd.read_csv('tests/prod_df_subset.csv')
    print(f"Test data: {len(prod_df)} records for {prod_df['API_UWI'].nunique()} wells")
    
    # Setup DCA with exact same parameters as original test
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
    l_dca.min_h_b = 0.9  # Exact same as original test
    l_dca.max_h_b = 1.3  # Exact same as original test
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

def compare_major_phase_parameters(reference_df, test_df, mode_name):
    """Compare major phase parameters between reference and test results"""
    print(f"\n--- Comparing {mode_name} mode against reference ---")
    
    # Get common wells
    common_wells = set(reference_df['UID']) & set(test_df['UID'])
    print(f"Common wells between reference and {mode_name}: {len(common_wells)}")
    
    if len(common_wells) == 0:
        print("No common wells found!")
        return
    
    # Filter to common wells
    ref_common = reference_df[reference_df['UID'].isin(common_wells)].copy()
    test_common = test_df[test_df['UID'].isin(common_wells)].copy()
    
    # Sort by UID for consistent comparison
    ref_common = ref_common.sort_values('UID').reset_index(drop=True)
    test_common = test_common.sort_values('UID').reset_index(drop=True)
    
    # Compare major phase parameters
    comparison_results = []
    
    for i, (_, ref_row) in enumerate(ref_common.iterrows()):
        test_row = test_common.iloc[i]
        
        # Get major phase from reference
        major_phase = ref_row['MAJOR']
        
        # Compare parameters based on major phase
        if major_phase == 'OIL':
            ref_qi = ref_row['IPO']
            ref_di = ref_row['DE']
            ref_b = ref_row['B']
            ref_aries = ref_row['ARIES_DE']
            
            if mode_name == 'three_phase':
                test_qi = test_row['IPO']
                test_di = test_row['DO']
                test_b = test_row['BO']
                test_aries = test_row['ARIES_DO']
            else:
                test_qi = test_row['IPO']
                test_di = test_row['DE']
                test_b = test_row['B']
                test_aries = test_row['ARIES_DE']
                
        elif major_phase == 'GAS':
            ref_qi = ref_row['IPG']
            ref_di = ref_row['DE']
            ref_b = ref_row['B']
            ref_aries = ref_row['ARIES_DE']
            
            if mode_name == 'three_phase':
                test_qi = test_row['IPG']
                test_di = test_row['DG']
                test_b = test_row['BG']
                test_aries = test_row['ARIES_DG']
            else:
                test_qi = test_row['IPG']
                test_di = test_row['DE']
                test_b = test_row['B']
                test_aries = test_row['ARIES_DE']
        
        # Check if parameters match exactly
        qi_match = abs(ref_qi - test_qi) < 1e-10
        di_match = abs(ref_di - test_di) < 1e-10
        b_match = abs(ref_b - test_b) < 1e-10
        aries_match = abs(ref_aries - test_aries) < 1e-10
        
        all_match = qi_match and di_match and b_match and aries_match
        
        comparison_results.append({
            'UID': ref_row['UID'],
            'MAJOR': major_phase,
            'QI_MATCH': qi_match,
            'DI_MATCH': di_match,
            'B_MATCH': b_match,
            'ARIES_MATCH': aries_match,
            'ALL_MATCH': all_match,
            'REF_QI': ref_qi,
            'TEST_QI': test_qi,
            'REF_DI': ref_di,
            'TEST_DI': test_di,
            'REF_B': ref_b,
            'TEST_B': test_b,
            'REF_ARIES': ref_aries,
            'TEST_ARIES': test_aries
        })
    
    # Create comparison dataframe
    comparison_df = pd.DataFrame(comparison_results)
    
    # Summary statistics
    total_wells = len(comparison_df)
    matching_wells = comparison_df['ALL_MATCH'].sum()
    match_rate = matching_wells / total_wells if total_wells > 0 else 0
    
    print(f"Total wells compared: {total_wells}")
    print(f"Wells with matching parameters: {matching_wells}")
    print(f"Match rate: {match_rate:.2%}")
    
    # Show mismatches if any
    mismatches = comparison_df[~comparison_df['ALL_MATCH']]
    if len(mismatches) > 0:
        print(f"\nMismatches found ({len(mismatches)} wells):")
        for _, row in mismatches.head(10).iterrows():  # Show first 10 mismatches
            print(f"  {row['UID']} ({row['MAJOR']}): QI={row['QI_MATCH']}, DI={row['DI_MATCH']}, B={row['B_MATCH']}, ARIES={row['ARIES_MATCH']}")
        if len(mismatches) > 10:
            print(f"  ... and {len(mismatches) - 10} more")
    else:
        print("✓ All major phase parameters match exactly!")
    
    return comparison_df

def main():
    """Main comparison function"""
    print("=== Three-Phase Mode Validation Against Reference ===")
    
    # Load reference data
    reference_df = load_reference_data()
    
    # Run original mode analysis
    original_df = run_dca_analysis('original')
    
    # Run three-phase mode analysis
    three_phase_df = run_dca_analysis('three_phase')
    
    # Compare original mode against reference
    original_comparison = compare_major_phase_parameters(reference_df, original_df, 'original')
    
    # Compare three-phase mode against reference
    three_phase_comparison = compare_major_phase_parameters(reference_df, three_phase_df, 'three_phase')
    
    # Save comparison results
    if original_comparison is not None:
        original_comparison.to_csv('tests/original_vs_reference_comparison.csv', index=False)
        print("\nOriginal mode comparison saved to: tests/original_vs_reference_comparison.csv")
    
    if three_phase_comparison is not None:
        three_phase_comparison.to_csv('tests/three_phase_vs_reference_comparison.csv', index=False)
        print("Three-phase mode comparison saved to: tests/three_phase_vs_reference_comparison.csv")
    
    print("\n=== Comparison Complete ===")

if __name__ == "__main__":
    main()
