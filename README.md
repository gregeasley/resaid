# RESAID Package

Reservoir engineering tools for production forecasting, decline curve analysis, and well economics.

## Features

- **Decline Curve Analysis (DCA)**: Arps decline fitting (exponential, hyperbolic, harmonic) with a switch to a terminal exponential decline
- **Production Data Processing**: Normalization to a standard lateral length and days on, outlier screening, peak and step-change (restim) detection
- **Ratio Mode**: Fit the major phase (oil or gas) and derive the other phases from recent production ratios
- **Three-Phase Mode**: Independent decline fits for OIL, GAS, and WATER
- **Outputs**: Monthly flowstreams, per-well onelines, and probabilistic type curves
- **Exports**: ARIES, Mosaic, and PhdWin forecast files
- **Economic Analysis**: Monthly cashflows, NPV, IRR, payout, ROI, and breakeven price
- **Multi-Phase Economics**: Oil, gas, and NGL revenue; oil, gas, and water operating costs
- **Royalty & Interest Modeling**: Working interest, net revenue interest, and royalty calculations
- **Tax & Cost Modeling**: Severance taxes, ad valorem taxes, and fixed and variable operating costs
- **Database Interface**: Read production from ARIES Access databases (`.mdb`/`.accdb`); experimental PhdWin TopSpeed support

## Installation

```bash
pip install resaid
```

Database connectivity (ARIES `.mdb`/`.accdb`, PhdWin TopSpeed files) needs optional drivers:

```bash
pip install "resaid[database]"
```

Mosaic exports are written with pandas' Excel writer, which needs `openpyxl` (`pip install openpyxl`).

## Quick Start

### Working Examples

The `examples/` folder contains working examples. Run them from inside `examples/`
(their paths are relative to that folder); see `examples/README.md` for details.

- **`simple_example.py`**: Three-phase mode, generating ARIES, PhdWin, and Mosaic exports
- **`ratio_mode_example.py`**: Ratio mode, deriving gas and water from oil (or oil and water from gas)
- **`decline_solver_demo.py`**: Solving for a missing decline parameter with `decline_solver`
- **`database_example_flexible.py`**: Reading an ARIES database with custom table and column mappings (needs a local `.accdb`)

```bash
cd examples
python simple_example.py
python ratio_mode_example.py
python decline_solver_demo.py
python database_example_flexible.py
```

### Basic DCA Analysis (Ratio Mode)

```python
import pandas as pd
from resaid.dca import decline_curve

# One row per well per month
prod_df = pd.read_csv('production_data.csv')

dca = decline_curve()

# Configure data columns
dca.dataframe = prod_df
dca.date_col = 'ProducingMonth'
dca.uid_col = 'API_UWI'
dca.oil_col = 'LiquidsProd_BBL'
dca.gas_col = 'GasProd_MCF'
dca.water_col = 'WaterProd_BBL'
dca.length_col = 'LateralLength_FT'   # optional: normalize to 5,280 ft laterals
dca.dayson_col = 'DaysOn'             # optional: normalize to 30.4 producing days

# Analysis parameters
dca.min_h_b = 0.9
dca.max_h_b = 1.3
dca.backup_decline = True

# Step changes (restims, recompletions): fit only the latest regime after a
# sustained step up in rate (on by default)
dca.detect_step_changes = True
dca.step_change_ratio = 1.5       # 3-month median vs prior 6-month median
dca.step_change_min_points = 6    # months needed after the new peak to fit it

# Fit decline parameters for every well
dca.run_DCA()

# Generate outputs (each runs run_DCA() first if it has not been run)
dca.generate_flowstream(num_months=1200, denormalize=True)
dca.generate_oneline(num_months=1200, denormalize=True)
dca.generate_typecurve(num_months=1200, denormalize=True)

# Access results
params = dca.params_dataframe          # fitted qi, di, b, t0 per well
oneline_results = dca.oneline_dataframe
flowstream_results = dca.flowstream_dataframe
typecurve_results = dca.typecurve
```

`denormalize=True` scales forecasts back from the 5,280 ft standard lateral to each
well's actual lateral length. Leave it `False` to keep normalized volumes, for example
when building type curves.

`run_DCA()` appends a fit summary to `DCA_LOG.txt` in the working directory. Set
`dca.stat_file_path` to log elsewhere, `dca.STAT_FILE = None` to disable the log, and call
`dca.close()` (or use `with decline_curve() as dca:`) to close the file.

### Three-Phase Forecasting Mode

```python
dca.three_phase_mode = True
dca.run_DCA()

dca.generate_oneline(num_months=1200, denormalize=True)
dca.generate_flowstream(num_months=1200, denormalize=True)

# Each phase has its own IP, decline, and b-factor
oneline_3p = dca.oneline_dataframe
print(oneline_3p[['UID', 'IPO', 'DO', 'BO', 'IPG', 'DG', 'BG', 'IPW', 'DW', 'BW']])
```

### Ratio Mode Forecasting

With `three_phase_mode = False` (the default), each well's major phase is fit and the
other phases follow it:

- The major phase is `GAS` when the cumulative GOR exceeds `GAS_CUTOFF` (3.2 Mcf/bbl) or
  there is no oil; otherwise `OIL`. Set `dca.phase_col` to supply it instead.
- `MINOR_RATIO` is the minor/major ratio (gas/oil for oil wells, oil/gas for gas wells)
  over the last `MINOR_TAIL_MONTHS` (6) months. `WATER_RATIO` is water/major over the same months.
- Minor phase rate = major phase rate × `MINOR_RATIO`; water rate = major phase rate × `WATER_RATIO`.
  All phases therefore share the major phase's decline parameters.
- With `outlier_correction = True` (default), ratios above `iqr_limit` × IQR beyond the
  upper quartile of the oil (or gas) wells are replaced by the median ratio.

### Fit Methods

`decline_curve(fit_method=...)` selects how each well is fit:

- `"default"`: Starts at the production peak, or at the latest step-up regime. Removes zero
  months and statistical outliers, then runs a weighted `curve_fit` of Arps parameters.
  Finally it rescales to match the last three months of production.
- `"monotone_two_step"`: Fits the longest monotone decline segment. It then solves for EUR
  and re-solves the initial decline so the curve starts from the recent producing rate.

If a fit fails and `backup_decline = True`, the well gets a backup decline instead:
the last positive rate with `default_initial_decline` and `default_b_factor`. Otherwise
it gets NaN parameters.

### Economic Analysis

`resaid.econ` provides NPV/IRR calculations and monthly well cashflow modeling. All
periods are **months**: discount rates are monthly, and IRR is annualized.

#### Basic NPV and IRR Calculations

```python
import numpy as np
from resaid.econ import npv_calc

# Monthly cashflow (negative for outflows, positive for inflows)
monthly_cf = np.array([-1_000_000] + [60_000] * 36, dtype=float)

calc = npv_calc(monthly_cf)
npv10 = calc.get_npv(0.10 / 12)   # monthly discount rate
irr = calc.get_irr()              # annualized, as a fraction (0.59 = 59%)

print(f"NPV10: ${npv10:,.0f}  IRR: {irr:.1%}")
```

`get_irr()` returns 0 when the undiscounted cashflow sum is negative.

#### Well Economics Analysis

```python
import pandas as pd
from resaid.econ import well_econ

econ = well_econ(verbose=False)

# Flowstream: UID and T_INDEX must be columns, with OIL, GAS, WATER volumes
econ.flowstreams = dca.flowstream_dataframe.reset_index()
econ.flowstream_uwi_col = 'UID'
econ.flowstream_t_index = 'T_INDEX'

# Header data: one row per well
header_data = pd.DataFrame({
    'UID': ['WELL001', 'WELL002'],
    'WI': [1.0, 1.0],              # working interest
    'NRI': [0.8, 0.75],            # net revenue interest
    'CAPEX': [2_000_000, 1_800_000],
})
econ.header_data = header_data
econ.header_uwi_col = 'UID'
econ.wi_col = 'WI'
econ.nri_col = 'NRI'
econ.capex_col = 'CAPEX'

# Prices: scalars, or Python lists of monthly prices (last value is held)
econ.oil_pri = 70.0      # $/bbl
econ.gas_pri = 3.0       # $/Mcf

# Required: monthly discount rate
econ.discount_rate = 0.10 / 12

# Operating costs
econ.opc_t = 8000        # fixed, $/month
econ.opc_oil = 5.0       # $/bbl
econ.opc_gas = 0.5       # $/Mcf of sold (post-shrink) gas
econ.opc_water = 2.0     # $/bbl

# Taxes (fractions of revenue)
econ.sev_oil = 0.046
econ.sev_gas = 0.075
econ.atx = 0.02          # ad valorem

cashflow = econ.generate_cashflow()   # monthly rows for all wells, stacked
econ.generate_indicators()            # results in econ.indicators
print(econ.indicators[['UWI', 'IRR', 'DCF', 'ROI', 'PAYOUT', 'BREAKEVEN']])

well_df = econ.well_flowstream('WELL001')   # one well's monthly cashflow
```

#### Additional Economic Options

```python
# Gas processing and NGLs
econ.gas_shrink = 0.1            # fraction of gas lost to shrink
econ.ngl_yield = 0.05            # bbl NGL per Mcf of sold gas (50 bbl/MMcf)
econ.ngl_price_fraction = 0.6    # NGL price as a fraction of oil price

# Price differentials (added to every monthly price)
econ.oil_diff = -2.0             # $/bbl
econ.gas_diff = 0.5              # $/Mcf

# Scale oil and gas volumes by a header column relative to a base value
econ.scale_forecast = True
econ.scale_column = 'LateralLength_FT'
econ.scale_base = 5280

# CAPEX: capex_col takes priority; otherwise scale_capex uses
# capex_val * scale_column (e.g. $/ft when scale_column is in feet);
# otherwise capex_val is a flat amount. CAPEX is charged in the first month.
econ.capex_col = None
econ.scale_capex = True
econ.capex_val = 1000            # $/ft of lateral

# Royalty: from wi_col/nri_col (royalty = 1 - NRI/WI), a royalty_col,
# or the scalar econ.royalty. owned_royalty_col adds an owned royalty interest
# (used together with wi_col and nri_col).
econ.royalty_col = 'ROYALTY_RATE'
econ.owned_royalty_col = 'OWNED_ROY'

# Timing: months from spud to first production, and per-well start months
# (both need a MAJOR column in the flowstream; ratio-mode flowstreams have one)
econ.spud_to_online = 3
econ.t_start_column = 'FIRST_PROD_MONTH'   # integer month offsets in header_data
```

#### Economic Outputs

**Cashflow DataFrame** (`generate_cashflow()` / `well_flowstream()`). It has the input
flowstream columns plus:
- Volumes and prices: `gas_sold`, `ngl_volume`, `oil_price`, `gas_price`, `ngl_price`
- Revenue: `oil_revenue`, `gas_revenue`, `ngl_revenue`, `revenue`, `royalty`
- Costs: `fixed_expense`, `oil_variable_expense`, `gas_variable_expense`, `water_variable_expense`, `expense`
- Taxes: `severance_tax`, `ad_val_tax`, `taxes`
- Cashflow: `capex`, `cf` (undiscounted), `dcf` (discounted)
- Working interest: `wi_*` columns
- Net revenue interest: `net_*` and `wi_net_*` columns

Volumes and cashflows are zeroed after the economic limit, which is the last month with
positive discounted cashflow.

**Economic Indicators** (`econ.indicators`, one row per well):
- `UWI`: well identifier
- `EURO`, `EURG`, `EURW`: oil, gas, and water volumes to the economic limit
- `REVENUE`, `ROYALTY`, `OPEX`, `TAXES`, `CAPEX`, `FCF`: undiscounted totals
- `DCF`: discounted net cashflow at `discount_rate` (the NPV)
- `IRR`: annualized internal rate of return, as a fraction; 0 if it cannot be computed
- `ROI`: undiscounted `FCF / CAPEX + 1`
- `PAYOUT`: month index of the first positive cumulative cashflow; 0 also means "never pays out"
- `BREAKEVEN`: breakeven price estimate ($/bbl or $/Mcf): (discounted revenue − `DCF`) / phase volume
- `BREAKEVEN_PHASE`: `OIL` or `GAS`. It is `GAS` when the GOR exceeds 3.2 Mcf/bbl; set `econ.breakeven_phase` to override it.

## Data Requirements

Production data needs one row per well per month with:

- **Well identifier** (`uid_col`)
- **Date** (`date_col`): one row per producing month
- **Oil, gas, and water volumes** (`oil_col`, `gas_col`, `water_col`). Missing values are treated as 0.

Optional columns:

- **Lateral length** (`length_col`): wells longer than 1 ft are normalized to 5,280 ft and
  treated as horizontal
- **Producing days** (`dayson_col`): volumes are normalized to 30.4 days per month
  (default 30.4 when not given)
- **Major phase** (`phase_col`): `OIL` or `GAS`, overriding the GOR classification

The examples in `examples/input_data/` show the expected format:

```csv
DATE,WELL_ID,OIL,GAS,WATER,DAYS_ON,WELL_NAME,FIELD,OPERATOR
2020-01-01,WELL_001,150.5,500.0,250.0,31,Smith #1,Eagle Ford,ABC Oil Co
2020-02-01,WELL_001,145.2,480.0,245.0,29,Smith #1,Eagle Ford,ABC Oil Co
...
```

Columns that are not mapped are ignored.

## Configuration Options

### DCA Parameters

- `min_h_b`, `max_h_b`: b-factor bounds for the fit (all wells; defaults 0.99 and 2.0)
- `MIN_DECLINE_RATE`: terminal decline, nominal per month (default 8%/yr)
- `GAS_CUTOFF`: GOR (Mcf/bbl) above which a well's major phase is GAS (default 3.2)
- `STANDARD_LENGTH`: lateral length that horizontal wells are normalized to (default 5,280 ft)
- `MINOR_TAIL_MONTHS`: months used for minor-phase and water ratios (default 6)
- `default_initial_decline`, `default_b_factor`: used only for backup declines

### Analysis Settings

- `three_phase_mode`: fit each phase independently (default `False`)
- `backup_decline`: give failed fits a backup decline instead of NaN parameters (default `False`)
- `filter_bonfp`: Bonferroni p-value cutoff for removing outlier months before fitting (default 0.5)
- `outlier_correction`, `iqr_limit`: in ratio mode, cap high minor/water ratios using an IQR rule (defaults `True`, 1.5)
- `detect_step_changes`, `step_change_ratio`, `step_change_lookback`, `step_change_window`,
  `step_change_min_points`: step-change (restim) detection (defaults `True`, 1.5, 6, 3, 6)

### Economic Parameters

- `oil_pri`, `gas_pri`: prices (scalar or list of monthly prices)
- `discount_rate`: monthly discount rate (required)
- `opc_t`, `opc_oil`, `opc_gas`, `opc_water`: fixed ($/month) and variable operating costs
- `sev_oil`, `sev_gas`: severance tax rates; `atx`: ad valorem tax rate
- `gas_shrink`, `ngl_yield`, `ngl_price_fraction`: gas processing and NGL parameters
- `scale_forecast`, `scale_capex`, `scale_column`, `scale_base`, `capex_val`: scaling options

## Output Formats

### Oneline Results

One row per well. The columns depend on the mode.

| Column | Mode | Meaning |
|---|---|---|
| `UID` | both | Well identifier |
| `OIL`, `GAS`, `WATER` | both | Modeled volume over the horizon: the sum of the well's flowstream (`T_INDEX` 1 to `num_months - 1`) |
| `T0_DATE` | both | Date of the fitted decline start |
| `MAJOR` | ratio | Major phase (OIL/GAS) |
| `IPO`, `IPG` | ratio | Initial rates `qi` (monthly volume) of the oil and gas curves |
| `DE`, `B` | ratio | Nominal monthly initial decline and b-factor of the major phase |
| `MINOR_RATIO`, `WATER_RATIO` | ratio | Phase ratios (see Ratio Mode) |
| `ARIES_DE` | ratio | Initial decline as an ARIES-style secant effective annual % |
| `IPO`/`DO`/`BO`/`ARIES_DO` (and `G`, `W` equivalents) | three-phase | Initial rate, decline, b-factor, and ARIES decline per phase |

### Flowstream Results

Monthly forecasts from the start of each well's history (`T_INDEX` 1 to `num_months - 1`):

- DataFrame indexed by `[UID, T_INDEX]` (use `.reset_index()` for columns)
- Columns `OIL`, `GAS`, `WATER` (monthly volumes), plus `MAJOR` in ratio mode

### Typecurve Results

`generate_typecurve(num_months, denormalize, prob_levels=[0.1, 0.5, 0.9])` combines each
well's history (where available) with its forecast. It then computes, for each month:

- `dca.typecurve`: indexed by `T_INDEX`, with columns `(phase, level)` for OIL/GAS/WATER at each
  quantile in `prob_levels` and `'mean'`. Levels are quantiles of the well rates, so `0.1`
  is the low case (P90 in reserves terms) and `0.9` the high case (P10).
- With `return_params=True`: `dca.tc_params` holds Arps parameters for each phase and level
  (`rate_t0`, `peak_rate`, `time_to_peak_months`, `matched_b_factor`, nominal/tangent/secant
  declines, and `curve_eur`). The decline is tuned so `curve_eur` matches the same quantile
  of the per-well EURs.
- With `return_params_flowstream=True`: `dca.tc_params_flowstream` holds the monthly rates
  rebuilt from those parameters.

## Advanced Usage

### Decline Curve Solver

`decline_solver` solves for whichever of `qi`, `qf`, `de`, `eur`, or `t_max` are missing so
that the cumulative Arps volume (monthly, truncated at `qf`) matches `eur`:

```python
from resaid.dca import decline_solver

solver = decline_solver(
    qi=1000,       # initial rate (volume/month)
    qf=100,        # economic limit rate
    eur=50000,     # target cumulative volume
    b=1.0,         # Arps b-factor
    dmin=0.08/12,  # terminal decline, nominal per month (default MIN_DECLINE_RATE)
)

qi, t_max, qf, de, eur, warning, delta = solver.solve()
# warning is True when the solved curve misses the EUR target
# (delta = |cumulative - eur|), e.g. because the target is unreachable.
```

### Parameter Tuning

```python
dca.min_h_b = 0.5
dca.max_h_b = 2.0
dca.GAS_CUTOFF = 2.5           # Mcf/bbl
dca.backup_decline = True
dca.default_initial_decline = 0.6/12
dca.default_b_factor = 0.8
dca.run_DCA()
```

## Export Functionality

The `decline_curve` class writes forecasts for economic software. Each export runs
`run_DCA()` and `generate_oneline(denormalize=True)` first if they have not been run.
Forecasts start near the latest production, not at `T0_DATE`. The decline is advanced
along the fitted curve to that date. ARIES and Mosaic start at the last producing month:
ARIES uses the last-three-month average rate, and Mosaic the fitted rate. PhdWin starts
one month earlier, at the middle of the last three months, with the fitted rate. `dmin`
is the terminal decline as an annual percentage.

### ARIES Export

```python
dca.generate_aries_export(
    file_path="outputs/aries_forecast.txt",
    scenario="RSC425",
    dmin=6,              # % per year
    write_water=True,    # include WTR lines
)
```

Each phase line is hyperbolic with a terminal exponential at `dmin` when b > 0.05.
It is exponential when b is lower or the decline is already below `dmin`, and a flat
1-year line when the last three months produced nothing.

### Mosaic Export

```python
dca.generate_mosaic_export(
    file_path="outputs/mosaic_forecast.xlsx",
    reserve_category="USON ARO",
    dmin=8,
)
```

### PhdWin Export

```python
dca.generate_phdwin_export(
    file_path="outputs/phdwin_forecast.csv",
    dmin=6,
)
```

All three exports return `None` and write the file, creating parent directories as needed.

- **Three-phase mode**: each phase uses its own decline parameters.
- **Ratio mode**: gas and water use the major phase's decline, scaled by `MINOR_RATIO` and `WATER_RATIO`.

### Utility Functions

```python
# Last-three-month average volumes and the latest production date (L3M_START)
l3m_df = dca.qi_overwrite()

# GOR, yield, WOR, and WGR rows for ratio-based forecasting
ratio_df = dca.make_ratio_dfs(l3m_df)
```

### Database Interface

The database interface reads production from industry databases into the DCA workflow.
It requires `pip install "resaid[database]"`.

**ARIES** (`.mdb`/`.accdb`, via pyodbc and the Microsoft Access ODBC driver):

```python
from resaid.database import ARIESDatabase

with ARIESDatabase("path/to/database.accdb") as db:     # closes the connection on exit
    if not db.connect():                                # returns False rather than raising
        raise RuntimeError("Could not connect (pyodbc and the Access ODBC driver are required)")

    # DataFrame with WELL_ID, DATE, OIL, GAS, WATER (defaults read AC_PRODUCT)
    dca_data = db.prepare_data_for_dca(
        production_table="AC_PRODUCT",
        production_columns={"well_id": "PROPNUM", "date": "P_DATE",
                            "oil": "OIL", "gas": "GAS", "water": "WATER"},
        header_columns={},          # skip the AC_PROPERTY header read (see note below)
    )

    results = db.run_dca_analysis(dca_data, three_phase_mode=True)    # {well_id: decline_curve}
    files = db.export_results(results, export_format="aries", output_dir="outputs")
    db.export_results(results, export_format="mosaic", output_dir="outputs")
```

Notes on the current behavior:
- Every column in `header_columns` must exist in the header table, or the read fails.
- With the default mappings, header data (phase, lateral length, days on) is not merged
  into the production data, so it does not reach the DCA.
- `export_format="phdwin"` currently fails through this interface. Call
  `generate_phdwin_export()` on each `decline_curve` in `results` instead.
- `export_results` writes one file per well (`{well_id}_aries_export.txt`, etc.) and returns `{well_id: path}`.

**PhdWin** (experimental): TopSpeed files (`.phd`, `.mod`, `.tps`, `.phz`) are converted
to a temporary SQLite database with pytopspeed-modernized. The converted tables
(`phd_*`/`mod_*`, keyed on `LSE_ID`) do not match the ARIES defaults. Pass a
`production_table` with one row per well and date and explicit `production_columns`.
PhdWin's integer dates and per-product layouts need preprocessing first. See
`PhdWin_Database_Structure.md` and `PhdWin_Database_Relationships.md` for the converted
schema.

## Performance Considerations

- **Large Datasets**: Fitting is per well. Progress bars (tqdm, on stderr) show progress.
- **Three-Phase Mode**: Fits three curves per well, so it takes roughly three times as long.
- **Verbose Output**: `run_DCA(_verbose=True)` logs per-well filtering details (via `logging`)
  and step messages to the run log. It is useful for diagnosing individual wells.

## Validation

Run the test suite with pytest (install test extras with `pip install -e ".[test]"`):

```bash
python -m pytest tests
```

Some tests skip unless optional local fixtures are present (`tests/prod_df_subset.csv`,
ARIES databases under `reference/`).

Developer scripts for manual checks against local reference data live in `scripts/`
(run from the repository root), for example:

```bash
python scripts/dca_test.py
python scripts/validate_three_phase.py
```

## Known Issues

These are known in 0.3.0 and scheduled for a follow-up release:

- **Database header merge**: with the default mappings, `prepare_data_for_dca` does not merge
  header data (phase, lateral length, days on) into the production data, so it never
  reaches the DCA.
- **PhdWin export via the database interface**: `export_results(export_format="phdwin")` fails
  for every well. Call `generate_phdwin_export()` on each `decline_curve` instead.
- **Silent connection failure**: `connect()` returns `False` without saying why when pyodbc
  or the Microsoft Access ODBC driver is missing.
- **PAYOUT ambiguity**: `PAYOUT` is 0 both for wells that pay out in the first month and for
  wells that never pay out.
- **`discount_rate` has no default**: leaving it unset raises a `TypeError` in cashflow generation.
- **Price arrays**: `oil_pri`/`gas_pri` accept scalars or Python lists, but not numpy arrays.
- **`t_start_column` timing**: with `spud_to_online` also set, one non-producing month is
  charged the fixed operating cost (`opc_t`).

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests for new functionality
5. Submit a pull request

## License

This project is licensed under the MIT License - see the LICENSE file for details.
