#!/usr/bin/env python3
"""
RESAID Ratio Mode Example

This script demonstrates how to use the RESAID library in ratio mode
to generate forecasts and exports for ARIES, PhdWin, and Mosaic.
"""

import pandas as pd
import sys
from pathlib import Path

# Add the parent directory to the path to import resaid
sys.path.append(str(Path(__file__).parent.parent))

from resaid.dca import decline_curve

def main():
    """Main example function for ratio mode"""
    print("RESAID Ratio Mode Example")
    print("=" * 30)
    
    # Create output directory
    Path("outputs").mkdir(exist_ok=True)
    
    # Load sample data
    print("Loading sample data...")
    prod_df = pd.read_csv("input_data/production_data.csv")
    prod_df['DATE'] = pd.to_datetime(prod_df['DATE'])
    
    well_df = pd.read_csv("input_data/well_data.csv")
    well_df['COMPLETION_DATE'] = pd.to_datetime(well_df['COMPLETION_DATE'])
    
    print(f"Loaded {len(prod_df)} production records for {len(well_df)} wells")
    
    # Prepare data for DCA
    combined_df = prod_df.merge(well_df, on='WELL_ID', how='left')
    combined_df['PHASE'] = 'OIL'  # Use OIL as primary phase
    
    # Create DCA object
    print("\nRunning DCA analysis in ratio mode...")
    dca = decline_curve()
    
    # Enable ratio mode for multi-phase forecasting using ratios
    dca.three_phase_mode = False
    
    # Set data
    dca.dataframe = combined_df
    dca.date_col = 'DATE'
    dca.phase_col = 'PHASE'
    dca.uid_col = 'WELL_ID'
    dca.oil_col = 'OIL'
    dca.gas_col = 'GAS'
    dca.water_col = 'WATER'
    
    # Run DCA
    dca.run_DCA()
    dca.generate_oneline(denormalize=True)
    
    print(f"DCA completed for {len(dca._oneline)} wells")
    
    # Generate exports
    print("\nGenerating exports...")
    
    # ARIES Export
    try:
        dca.generate_aries_export("outputs/ratio_aries_export.txt", write_water=True)
        print("✓ ARIES export: outputs/ratio_aries_export.txt")
    except Exception as e:
        print(f"✗ ARIES export failed: {e}")
    
    # PhdWin Export
    try:
        dca.generate_phdwin_export("outputs/ratio_phdwin_export.csv")
        print("✓ PhdWin export: outputs/ratio_phdwin_export.csv")
    except Exception as e:
        print(f"✗ PhdWin export failed: {e}")
    
    # Mosaic Export
    try:
        dca.generate_mosaic_export("outputs/ratio_mosaic_export.xlsx")
        print("✓ Mosaic export: outputs/ratio_mosaic_export.xlsx")
    except Exception as e:
        print(f"✗ Mosaic export failed: {e}")
    
    print("\nRatio mode example completed! Check the 'outputs' directory for generated files.")

if __name__ == "__main__":
    main()
