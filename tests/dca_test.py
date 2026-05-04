import pandas as pd
from resaid.dca import decline_curve
import numpy as np
import time
import os

def calculate_oneline(production_df,b_min,b_max)->pd.DataFrame:

    l_dca = decline_curve()

    l_dca.backup_decline = True
    #l_dca.DEFAULT_DI = 2.75/12
    l_dca.SET_LENGTH = 10000
    l_dca.DEFAULT_B = (b_min+b_max)/2
    l_dca.dataframe = production_df
    l_dca.date_col = 'ProducingMonth'
    l_dca.phase_col = 'MAJOR'
    l_dca.length_col = 'LateralLength_FT'
    l_dca.uid_col = 'API_UWI'
    #l_dca.dayson_col = 'ProducingDays'
    l_dca.oil_col = 'LiquidsProd_BBL'
    l_dca.gas_col = 'GasProd_MCF'
    l_dca.water_col = 'WaterProd_BBL'
    l_dca.min_h_b = b_min
    l_dca.max_h_b = b_max
    l_dca.OUTLIER_CORRECTION = False

    l_dca.generate_oneline(denormalize=True)



    #l_dca.generate_typecurve()

    return l_dca.oneline_dataframe

def make_prod_df(prod_df:pd.DataFrame,header_df:pd.DataFrame)->pd.DataFrame:

    header_df = header_df[['API_UWI','CumOil_BBL','CumGas_MCF','LateralLength_FT']].groupby(['API_UWI']).agg({
        'LateralLength_FT':max,
        'CumGas_MCF':sum,
        'CumOil_BBL':sum,
    }).reset_index()

    header_df['MAJOR'] = np.where(
        header_df['CumGas_MCF']/header_df['CumOil_BBL']>3.2,
        'GAS',
        'OIL'
    )

    header_df['MAJOR'] = header_df['MAJOR'].fillna(value='GAS')

    header_df = header_df[['API_UWI','LateralLength_FT','MAJOR']]

    l_prod_df = prod_df.merge(header_df, left_on='API_UWI',right_on='API_UWI')

    l_prod_df = l_prod_df[[
        'API_UWI',
        'MAJOR',
        'ProducingMonth',
        'LateralLength_FT',
        'LiquidsProd_BBL',
        'GasProd_MCF',
        'WaterProd_BBL'
    ]]

    #print(l_prod_df.head())

    l_prod_df = l_prod_df.groupby(['API_UWI','MAJOR','ProducingMonth']).agg({
        'LateralLength_FT':max,
        'LiquidsProd_BBL':sum,
        'GasProd_MCF':sum,
        'WaterProd_BBL':sum
    }).reset_index()

    return l_prod_df


def main():
    """Performance / reference script — run from repo root: ``python tests/dca_test.py``."""
    # Check if we have a saved subset for faster debugging
    subset_file = "tests/prod_df_subset.csv"
    if os.path.exists(subset_file) and False:  # Set to False to use full dataset
        print("Loading saved subset for faster debugging...")
        prod_df = pd.read_csv(subset_file)
    else:
        print("Loading full dataset for performance testing...")
        prod_df = make_prod_df(
            prod_df=pd.read_csv("tests/env_csv-Production-b00bf_2025-08-25.zip"),
            header_df=pd.read_csv("tests/env_csv-Wells-fc2df_2025-08-25.zip"),
        )

        # Only create subset if we're debugging
        if False:  # Set to False for full dataset
            # Take only first 100 unique wells for faster debugging
            unique_wells = prod_df["API_UWI"].unique()[:100]
            prod_df = prod_df[prod_df["API_UWI"].isin(unique_wells)]

            # Save subset for future runs
            prod_df.to_csv(subset_file, index=False)
            print(f"Saved subset with {len(unique_wells)} wells for faster debugging")

    l_start = time.time()

    oneline_df = calculate_oneline(
        prod_df,
        b_min=0.9,
        b_max=1.3,
    )

    oneline_df.to_csv("tests/oneline.csv")

    l_duration = time.time() - l_start
    print(f"Oneline generation: {l_duration:.2f} seconds")

    # Compare with reference if it exists
    reference_file = "tests/oneline_reference.csv"
    if os.path.exists(reference_file):
        print("Comparing with reference...")
        reference_df = pd.read_csv(reference_file)

        # Filter reference to same wells for comparison
        reference_subset = reference_df[reference_df["UID"].isin(oneline_df["UID"])]

        if len(oneline_df) == len(reference_subset):
            print(f"✓ Row counts match: {len(oneline_df)}")

            # Check for any differences in key columns
            merged = oneline_df.merge(reference_subset, on="UID", suffixes=("_new", "_ref"))

            # Check each column for differences
            key_columns = ["OIL", "GAS", "WATER", "B", "DE", "ARIES_DE"]
            for col in key_columns:
                if col in merged.columns:
                    col_new = f"{col}_new"
                    col_ref = f"{col}_ref"
                    if col_new in merged.columns and col_ref in merged.columns:
                        differences = merged[abs(merged[col_new] - merged[col_ref]) > 1e-10]
                        if len(differences) > 0:
                            print(f"✗ Found {len(differences)} differences in {col}")
                            print("  Sample differences:")
                            for i in range(min(3, len(differences))):
                                print(
                                    f"    UID {differences.iloc[i]['UID']}: "
                                    f"{differences.iloc[i][col_new]:.6f} vs {differences.iloc[i][col_ref]:.6f}"
                                )
                        else:
                            print(f"✓ {col} matches exactly")

            # Check if any UIDs are missing
            missing_in_new = set(reference_subset["UID"]) - set(oneline_df["UID"])
            missing_in_ref = set(oneline_df["UID"]) - set(reference_subset["UID"])

            if missing_in_new:
                print(f"✗ {len(missing_in_new)} UIDs missing in new output")
            if missing_in_ref:
                print(f"✗ {len(missing_in_ref)} UIDs missing in reference")
            if not missing_in_new and not missing_in_ref:
                print("✓ All UIDs match")

        else:
            print(f"✗ Row count mismatch: {len(oneline_df)} vs {len(reference_subset)}")
    else:
        print("No reference file found for comparison")


if __name__ == "__main__":
    main()