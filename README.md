# RESAID Package

A comprehensive collection of reservoir engineering tools for production forecasting and decline curve analysis.

## Features

- **Decline Curve Analysis (DCA)**: Arps decline curve fitting with exponential, hyperbolic, and harmonic decline models
- **Production Data Processing**: Normalization, outlier detection, and data preprocessing
- **Single-Phase Forecasting**: Traditional major phase analysis with ratio-based minor phase estimation
- **Three-Phase Forecasting**: Independent decline curve analysis for OIL, GAS, and WATER phases
- **Multiple Output Formats**: Flowstream, oneline, and typecurve generation
- **Economic Analysis**: NPV, IRR, and comprehensive cashflow modeling
- **Multi-Phase Economics**: Oil, gas, water, and NGL revenue calculations
- **Royalty & Interest Modeling**: Working interest, net revenue interest, and royalty calculations
- **Tax & Cost Modeling**: Severance taxes, ad valorem taxes, and operating costs
- **Vectorized Operations**: High-performance calculations for large datasets

## Installation

```bash
pip install resaid
```

## Quick Start

### Working Examples

The `examples/` folder contains working examples that demonstrate RESAID functionality:

- **`simple_example.py`**: Three-phase mode example generating ARIES, PhdWin, and Mosaic exports
- **`ratio_mode_example.py`**: Ratio mode example showing how to use ratios for multi-phase forecasting

Run these examples to see RESAID in action:
```bash
cd examples
python simple_example.py      # Three-phase mode
python ratio_mode_example.py  # Ratio mode
```

### Basic Single-Phase DCA Analysis

```python
import pandas as pd
from resaid.dca import decline_curve

# Load production data
prod_df = pd.read_csv('production_data.csv')

# Initialize DCA object
dca = decline_curve()

# Configure data columns
dca.dataframe = prod_df
dca.date_col = 'ProducingMonth'
dca.uid_col = 'API_UWI'
dca.oil_col = 'LiquidsProd_BBL'
dca.gas_col = 'GasProd_MCF'
dca.water_col = 'WaterProd_BBL'
dca.length_col = 'LateralLength_FT'

# Set analysis parameters
dca.min_h_b = 0.9
dca.max_h_b = 1.3
dca.backup_decline = True
dca.outlier_correction = False

# Run DCA analysis
dca.run_DCA()

# Generate outputs
dca.generate_oneline(num_months=1200, denormalize=True)
dca.generate_flowstream(num_months=1200, denormalize=True)
dca.generate_typecurve(num_months=1200, denormalize=True)

# Access results
oneline_results = dca.oneline_dataframe
flowstream_results = dca.flowstream_dataframe
typecurve_results = dca.typecurve
```

### Three-Phase Forecasting Mode

```python
# Enable three-phase mode
dca.three_phase_mode = True

# Run analysis (same as before)
dca.run_DCA()

# Generate outputs with independent phase analysis
dca.generate_oneline(num_months=1200, denormalize=True)
dca.generate_flowstream(num_months=1200, denormalize=True)
dca.generate_typecurve(num_months=1200, denormalize=True)

# Three-phase results include phase-specific parameters
oneline_3p = dca.oneline_dataframe
print("Phase-specific columns:", [col for col in oneline_3p.columns if col.startswith(('IPO', 'IPG', 'IPW', 'DO', 'DG', 'DW', 'BO', 'BG', 'BW'))])
```

### Ratio Mode Forecasting

```python
# Enable ratio mode for multi-phase forecasting using ratios
dca.three_phase_mode = False

# Run analysis (same as before)
dca.run_DCA()

# Generate outputs with ratio-based phase calculations
dca.generate_oneline(denormalize=True)

# Ratio mode uses MINOR_RATIO and WATER_RATIO from oneline data
# Gas production = MINOR_RATIO * OIL_QI
# Water production = WATER_RATIO * OIL_QI
# All phases use the same decline curve parameters
```

### Economic Analysis

RESAID provides comprehensive economic analysis tools for oil and gas projects, including NPV calculations, IRR analysis, and detailed cashflow modeling.

#### Basic NPV and IRR Calculations

```python
from resaid.econ import npv_calc

# Create cashflow array (negative for outflows, positive for inflows)
cashflow = np.array([-1000000, 500000, 400000, 300000, 200000])

# Initialize NPV calculator
npv = npv_calc(cashflow)

# Calculate NPV at 10% discount rate
npv_value = npv.get_npv(0.1)
print(f"NPV at 10%: ${npv_value:,.2f}")

# Calculate Internal Rate of Return
irr = npv.get_irr()
print(f"IRR: {irr:.1f}%")
```

#### Well Economics Analysis

```python
from resaid.econ import well_econ

# Initialize economics calculator
econ = well_econ(verbose=False)

# Set flowstream data (from DCA analysis)
econ.flowstreams = dca.flowstream_dataframe
econ.flowstream_uwi_col = 'UID'
econ.flowstream_t_index = 'T_INDEX'

# Set header data with well information
header_data = pd.DataFrame({
    'UID': ['WELL001', 'WELL002'],
    'NRI': [0.8, 0.75],  # Net Revenue Interest
    'WI': [1.0, 1.0],    # Working Interest
    'CAPEX': [2000000, 1800000]  # Capital expenditure
})
econ.header_data = header_data
econ.header_uwi_col = 'UID'
econ.wi_col = 'WI'
econ.nri_col = 'NRI'
econ.capex_col = 'CAPEX'

# Set economic parameters
econ.oil_pri = 50.0      # Oil price $/bbl
econ.gas_pri = 3.0       # Gas price $/MCF
econ.discount_rate = 0.1 # 10% discount rate

# Operating costs
econ.opc_t = 1000       # Fixed operating cost $/month
econ.opc_oil = 5.0      # Variable oil cost $/bbl
econ.opc_gas = 0.5      # Variable gas cost $/MCF
econ.opc_water = 2.0    # Variable water cost $/bbl

# Taxes
econ.sev_oil = 0.05     # Oil severance tax rate
econ.sev_gas = 0.05     # Gas severance tax rate
econ.atx = 0.02         # Ad valorem tax rate

# Generate cashflow for all wells
cashflow = econ.generate_cashflow()

# Generate economic indicators
econ.generate_indicators()
indicators = econ.indicators

print("Economic Indicators:")
print(indicators[['UID', 'IRR', 'DCF', 'PAYOUT', 'BREAKEVEN']])
```

#### Advanced Economic Modeling

```python
# Gas processing and NGL modeling
econ.gas_shrink = 0.1        # 10% gas shrinkage
econ.ngl_yield = 0.05        # 5 bbl NGL per MCF gas
econ.ngl_price_fraction = 0.6 # NGL price as fraction of oil price

# Price differentials
econ.oil_diff = -2.0         # Oil price differential $/bbl
econ.gas_diff = 0.5          # Gas price differential $/MCF

# Scaling and timing
econ.scale_forecast = True   # Scale forecast by well characteristics
econ.scale_column = 'LateralLength_FT'
econ.scale_base = 5280       # Base lateral length for scaling

# Generate well-specific cashflow
well_cashflow = econ.well_flowstream('WELL001')
print("Well cashflow columns:", list(well_cashflow.columns))
```

#### Economic Outputs

The economic analysis generates comprehensive outputs:

**Cashflow DataFrame** includes:
- Revenue streams: `oil_revenue`, `gas_revenue`, `ngl_revenue`
- Costs: `expense`, `royalty`, `taxes`, `capex`
- Cashflow: `cf` (undiscounted), `dcf` (discounted)
- Working interest: `wi_*` columns for WI calculations
- Net interest: `net_*` columns for NRI calculations

**Economic Indicators** include:
- `IRR`: Internal Rate of Return (%)
- `DCF`: Discounted Cash Flow ($)
- `ROI`: Return on Investment
- `PAYOUT`: Payback period (months)
- `BREAKEVEN`: Breakeven price ($/bbl or $/MCF)
- `EURO`, `EURG`, `EURW`: Estimated Ultimate Recovery by phase

## Data Requirements

### Input Data Format

Your production data should include the following columns:

- **Date Column**: Production date (e.g., 'ProducingMonth')
- **Well Identifier**: Unique well ID (e.g., 'API_UWI')
- **Production Data**: Oil, gas, and water production volumes
- **Well Characteristics**: Lateral length, hole direction, etc.

### Example Data Structure

The working examples in `examples/input_data/` show the expected format:

```csv
WELL_ID,DATE,OIL,GAS,WATER
WELL_001,2020-01-01,1500,2500,500
WELL_001,2020-02-01,1400,2400,480
...
```

For custom data, use these column names:
- **Date Column**: Production date (e.g., 'DATE')
- **Well Identifier**: Unique well ID (e.g., 'WELL_ID')
- **Production Data**: Oil, gas, and water production volumes
- **Well Characteristics**: Lateral length, hole direction, etc.

## Configuration Options

### DCA Parameters

- `min_h_b`, `max_h_b`: B-factor bounds for horizontal wells
- `default_initial_decline`: Default initial decline rate
- `default_b_factor`: Default Arps b-factor
- `MIN_DECLINE_RATE`: Minimum decline rate
- `GAS_CUTOFF`: Gas-oil ratio threshold for phase classification

### Analysis Settings

- `backup_decline`: Enable backup decline rate for failed fits
- `outlier_correction`: Enable outlier detection and filtering
- `iqr_limit`: Outlier detection threshold
- `filter_bonfp`: Bonferroni correction threshold
- `three_phase_mode`: Enable three-phase forecasting

### Economic Parameters

- `oil_pri`, `gas_pri`: Commodity prices ($/bbl, $/MCF)
- `discount_rate`: Discount rate for NPV calculations
- `opc_t`, `opc_oil`, `opc_gas`, `opc_water`: Operating costs
- `sev_oil`, `sev_gas`: Severance tax rates
- `atx`: Ad valorem tax rate
- `gas_shrink`, `ngl_yield`: Gas processing parameters
- `scale_forecast`: Enable production scaling by well characteristics

## Output Formats

### Oneline Results

Single-well summary with decline parameters and cumulative production:

- `UID`: Well identifier
- `MAJOR`: Major phase (OIL/GAS)
- `OIL`, `GAS`, `WATER`: Cumulative production
- `IPO`, `IPG`, `IPW`: Initial production rates
- `DE`, `DO`, `DG`, `DW`: Decline rates
- `B`, `BO`, `BG`, `BW`: Arps b-factors
- `ARIES_DE`, `ARIES_DO`, `ARIES_DG`, `ARIES_DW`: Aries-compatible decline rates

### Flowstream Results

Monthly production forecasts for each well:

- Multi-index DataFrame with `[UID, T_INDEX]`
- `OIL`, `GAS`, `WATER`: Monthly production rates
- Time series from T_INDEX=0 to specified number of months

### Typecurve Results

Statistical aggregation of decline parameters:

- Probability distributions (P10, P50, P90)
- Phase-specific parameter statistics
- Aggregated production forecasts

### Economic Results

Comprehensive economic analysis outputs:

- **Cashflow DataFrame**: Monthly cashflow with revenue, costs, and cashflow streams
- **Economic Indicators**: IRR, NPV, ROI, payback period, and breakeven analysis
- **Working Interest Calculations**: WI-adjusted cashflows and metrics
- **Net Revenue Interest**: NRI-adjusted cashflows and economic indicators

## Advanced Usage

### Custom Decline Curve Solver

```python
from resaid.dca import decline_solver

# Solve for missing parameters
solver = decline_solver(
    qi=1000,      # Initial rate
    qf=100,       # Final rate
    eur=50000,    # Estimated ultimate recovery
    b=1.0,        # Arps b-factor
    dmin=0.01/12  # Minimum decline rate
)

qi, t_max, qf, de, eur, warning, delta = solver.solve()
```

### Parameter Optimization

```python
# Customize analysis parameters
dca.min_h_b = 0.5
dca.max_h_b = 2.0
dca.default_initial_decline = 0.6/12
dca.default_b_factor = 0.8
dca.GAS_CUTOFF = 2.5  # MSCF/STB

# Run analysis with custom settings
dca.run_DCA()
```

### Advanced Economic Modeling

```python
# Price forecasting with time-varying prices
econ.oil_pri = [45.0, 50.0, 55.0, 60.0, 65.0]  # Price forecast
econ.gas_pri = [2.5, 3.0, 3.5, 4.0, 4.5]       # Gas price forecast

# Complex royalty structures
econ.royalty_col = 'ROYALTY_RATE'      # Column with well-specific royalty rates
econ.owned_royalty_col = 'OWNED_ROY'   # Column with owned royalty interest

# Scaled CAPEX based on well characteristics
econ.scale_capex = True
econ.scale_column = 'LateralLength_FT'
econ.capex_val = 250000  # Base CAPEX per 1000 ft

# Timing adjustments
econ.spud_to_online = 3  # Months from spud to first production
econ.t_start_column = 'FIRST_PROD_MONTH'  # Column with first production month

# Generate comprehensive economic analysis
cashflow = econ.generate_cashflow()
econ.generate_indicators()

# Access detailed results
print("Top performing wells by IRR:")
top_wells = econ.indicators.nlargest(5, 'IRR')
print(top_wells[['UID', 'IRR', 'DCF', 'PAYOUT']])
```

## Export Functionality

The `decline_curve` class includes integrated export capabilities for major economic software platforms.

### ARIES Export

Generate ARIES-compatible economic forecast files:

```python
from resaid.dca import decline_curve

# Initialize and run DCA
dca = decline_curve()
dca.dataframe = production_df
dca.date_col = 'DATE'
dca.uid_col = 'WELL_ID'
dca.oil_col = 'OIL'
dca.gas_col = 'GAS'
dca.water_col = 'WATER'
dca.phase_col = 'PHASE'

# Run DCA analysis first
dca.run_DCA()
dca.generate_oneline(denormalize=True)

# Generate ARIES export with error handling
try:
    dca.generate_aries_export(
        file_path="outputs/aries_forecast.txt",
        scenario="RSC425",
        dmin=6,
        write_water=True
    )
    print("✓ ARIES export completed")
except Exception as e:
    print(f"✗ ARIES export failed: {e}")
```

### Mosaic Export

Generate Mosaic-compatible Excel exports with all phases:

```python
# Generate Mosaic export with error handling
try:
    dca.generate_mosaic_export(
        file_path="outputs/mosaic_forecast.xlsx",
        reserve_category="USON ARO",
        dmin=8
    )
    print("✓ Mosaic export completed")
except Exception as e:
    print(f"✗ Mosaic export failed: {e}")
```

### PhdWin Export

Generate PhdWin-compatible CSV exports:

```python
# Generate PhdWin export with error handling
try:
    dca.generate_phdwin_export(
        file_path="outputs/phdwin_forecast.csv",
        dmin=6
    )
    print("✓ PhdWin export completed")
except Exception as e:
    print(f"✗ PhdWin export failed: {e}")
```

### Utility Functions

#### 3-Month Average Production Calculation

Calculate 3-month average production rates for initial rate estimation:

```python
# Calculate 3-month averages
l3m_df = dca.qi_overwrite()
print(l3m_df.head())
```

#### Ratio Analysis

Create ratio dataframes for specialized analysis:

```python
# Generate ratio dataframes (GOR, yield, WOR, WGR)
ratio_df = dca.make_ratio_dfs(l3m_df)
print(ratio_df.head())
```

### Export Features

- **Multi-Phase Support**: All exports include OIL, GAS, and WATER phases
- **Three-Phase Mode Integration**: When `three_phase_mode=True`, exports use the existing three-phase analysis instead of creating separate DCA objects
- **Ratio Mode Integration**: When `three_phase_mode=False`, exports use ratio-based calculations (MINOR_RATIO and WATER_RATIO) for gas and water phases
- **Automatic DCA Integration**: Exports automatically run DCA analysis if not already performed
- **Flexible Configuration**: Customizable parameters for each export format
- **Error Handling**: Robust error handling with default values for missing data
- **Directory Creation**: Automatically creates output directories as needed

## Performance Considerations

- **Large Datasets**: The module uses vectorized operations for optimal performance
- **Memory Usage**: For very large datasets, consider processing in batches
- **Three-Phase Mode**: Requires more computation time but provides independent phase analysis
- **Economic Analysis**: Cashflow generation is optimized for large well portfolios
- **Progress Tracking**: Use `verbose=True` for progress bars on large datasets

## Validation

The package includes comprehensive validation tests:

```bash
# Run validation tests
python tests/dca_test.py
python tests/test_econ.py
python tests/test_decline_solver.py
python tests/test_export_functions.py
python tests/test_export_consistency.py
python tests/test_export_date_logic.py
python tests/three_phase_test.py
python tests/validate_three_phase.py
```

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests for new functionality
5. Submit a pull request

## License

This project is licensed under the MIT License - see the LICENSE file for details.