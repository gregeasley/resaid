# Changelog

## 0.3.1

### Fixed
- **First-peak detection.** The default fit window now starts at the first production peak:
  the highest month up to and including the first local maximum. Previously it started at
  the first local maximum, which can never be a well's first month. A well that peaked in
  its first month was fit from a later minor bump, losing its early decline. The monotone
  method's fallback window uses the same peak.

## 0.3.0

### Added
- **Step-change detection** (`detect_step_changes`, on by default). After a sustained step up
  in rate (a restim, recompletion, or return from curtailment), only the latest regime is
  fit. Applies to both fit methods.
- `arps_decline(..., dmin=...)` to override the terminal decline.
- `decline_curve.close()` and context-manager support for the run log.

### Fixed
- `arps_decline`:
  - honors `t0` when the initial decline is below the terminal rate
  - treats b near 0 as exponential at `di`
  - no longer turns steep, low-b curves into a flat tail at `qi`
- `decline_solver`:
  - uses `dmin`, which was previously ignored
  - solves single variables in log space, so solutions no longer stall at the upper bound
  - sets its warning flag from the residual, so unreachable EUR targets are flagged
- Monotone fit: solved declines are no longer reported below the terminal rate.
- `DCA_LOG.txt` is opened on first write instead of at construction.

### Changed
- The database drivers (pyodbc, jpype1, pytopspeed-modernized) moved to an optional extra:
  `pip install "resaid[database]"`.
- Python 3.10 to 3.13 supported and tested.

See the README's Known Issues section for open items.
