# RESAID Export Examples

This folder contains working examples demonstrating how to use the RESAID library to generate forecasts and exports for ARIES, PhdWin, and Mosaic.

## Quick Start

1. **Install RESAID**: `pip install resaid`
2. **Choose your mode**:
   - **Three-phase mode**: `python simple_example.py` (independent decline curves for each phase)
   - **Ratio mode**: `python ratio_mode_example.py` (ratio-based forecasting)
   - **Database interface**: `python database_example.py` (read from ARIES/PhdWin databases)
3. **Check outputs**: Look in the `outputs/` directory

## What You'll Get

After running the example, you'll have:
- **ARIES export**: `aries_export.txt` for ARIES software
- **PhdWin export**: `phdwin_export.csv` for PhdWin software  
- **Mosaic export**: `mosaic_export.xlsx` for Mosaic software

## Input Data

The example uses sample data in `input_data/`:
- `production_data.csv`: Production history for 3 wells
- `well_data.csv`: Well metadata (location, completion date, etc.)

## Customization

To use your own data:
1. Replace the CSV files in `input_data/` with your data
2. Update column names in `simple_example.py` if needed
3. Run the script

## File Structure

```
examples/
├── README.md                    # This file
├── simple_example.py           # Three-phase mode example
├── ratio_mode_example.py       # Ratio mode example
├── database_example.py         # Database interface example
├── input_data/                 # Sample input data
│   ├── production_data.csv     # Production data
│   └── well_data.csv          # Well metadata
└── outputs/                    # Generated export files
```

## Mode Differences

- **Three-Phase Mode** (`simple_example.py`): Generates independent decline curves for Oil, Gas, and Water phases
- **Ratio Mode** (`ratio_mode_example.py`): Uses ratios from the primary phase (Oil) to calculate Gas and Water production
- **Database Interface** (`database_example.py`): Reads production and header data directly from ARIES/PhdWin databases

## Database Interface

The new `database_example.py` demonstrates how to:

1. **Connect to ARIES/PhdWin databases** (.mdb/.accdb files)
2. **Read production data** from `AC_PRODUCT` table
3. **Read header data** from `AC_PROPERTY` table
4. **Automatically prepare data** for DCA analysis
5. **Run DCA analysis** on multiple wells
6. **Export results** in all supported formats

### Requirements

- **ARIES/PhdWin database** (.mdb or .accdb file)
- **Database tables**: `AC_PRODUCT` (production data) and `AC_PROPERTY` (header data)
- **Required columns**: Production data must have `PROPNUM`, `P_DATE`, `OIL`, `GAS`, `WATER`

### Usage

```python
from resaid.database import ARIESDatabase

# Create database interface
aries_db = ARIESDatabase("path/to/database.mdb")

# Connect and read data
aries_db.connect()
dca_data = aries_db.prepare_data_for_dca()

# Run DCA analysis
results = aries_db.run_dca_analysis(dca_data, three_phase_mode=True)

# Export results
aries_db.export_results(results, export_format='aries', output_dir='outputs')
```

This provides a seamless workflow from database to DCA analysis to export generation.
