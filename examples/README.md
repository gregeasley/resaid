# RESAID examples

| Script | What it exercises |
|--------|-------------------|
| `simple_example.py` | `decline_curve`, **three-phase** mode, CSV inputs under `input_data/`, ARIES / PhdWin / Mosaic exports |
| `ratio_mode_example.py` | Same data as `simple_example.py`, **ratio** mode (`three_phase_mode=False`) |
| `decline_solver_demo.py` | Standalone `decline_solver` numeric solve (no production CSV) |
| `database_example_flexible.py` | `ARIESDatabase`, custom table/column maps (needs a local `.accdb`) |

Run examples from the **repository root** so paths to `input_data/` resolve. Install the package first (`pip install -e .`).
