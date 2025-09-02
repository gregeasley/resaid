# RESAID Export Examples

This folder contains working examples demonstrating how to use the RESAID library to generate forecasts and exports for ARIES, PhdWin, and Mosaic.

## Quick Start

1. **Install RESAID**: `pip install resaid`
2. **Choose your mode**:
   - **Three-phase mode**: `python simple_example.py` (independent decline curves for each phase)
   - **Ratio mode**: `python ratio_mode_example.py` (ratio-based forecasting)
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
├── input_data/                 # Sample input data
│   ├── production_data.csv     # Production data
│   └── well_data.csv          # Well metadata
└── outputs/                    # Generated export files
```

## Mode Differences

- **Three-Phase Mode** (`simple_example.py`): Generates independent decline curves for Oil, Gas, and Water phases
- **Ratio Mode** (`ratio_mode_example.py`): Uses ratios from the primary phase (Oil) to calculate Gas and Water production
