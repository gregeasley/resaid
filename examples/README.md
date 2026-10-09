# RESAID examples

| Script | What it exercises |
|--------|-------------------|
| `simple_example.py` | `decline_curve`, **three-phase** mode, CSV inputs under `input_data/`, ARIES / PhdWin / Mosaic exports |
| `ratio_mode_example.py` | Same data as `simple_example.py`, **ratio** mode (`three_phase_mode=False`) |
| `decline_solver_demo.py` | Standalone `decline_solver` numeric solve (no production CSV) |
| `database_example_flexible.py` | `ARIESDatabase` only, custom table/column maps (needs a local `.accdb` at `../reference/`) |

Install the package first (`pip install -e .` from the repository root; add `openpyxl` for
Mosaic exports and `".[database]"` for the database example), then run the scripts from
**this folder** so the relative paths resolve:

```bash
cd examples
python simple_example.py
```

The scripts read `input_data/` and write to `outputs/` relative to the working directory.
The files committed under `outputs/` are what `simple_example.py` and
`ratio_mode_example.py` produce, for reference.

In `database_example_flexible.py`, the `phdwin` export step currently reports a failure.
This is a known issue with `export_results(export_format="phdwin")`; the ARIES and Mosaic
exports work.
