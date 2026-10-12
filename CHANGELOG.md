# Changelog

## 0.4.0

### Added
- **Short post-workover regimes** (`short_regime_eur_match`, on by default). A step up too
  recent to fit (fewer than `step_change_min_points` months from its peak) previously left
  the earlier regime in use, with the step's months mixed into its fit. Now the previous
  regime is fit on its own months (up to the step's onset), and the new regime gets that
  regime's EUR: its actual production to the onset plus its fitted curve from the onset on.
  The new regime keeps the previous b, takes its IP from the current tail (`qi_tail_points`),
  and its decline is solved so production since the onset plus the remaining volume equals
  that EUR. Applies to both fit methods; the default method reports the path as
  `legacy_short_regime_eur_match`.
- `short_regime_max_ratio` (default 1.25). A step whose current rate exceeds this multiple of
  the previous regime's peak is treated as a new completion (recompletion to a new zone,
  restimulation), not a workover, and gets no EUR match. The previous regime must also have
  at least `step_change_min_points` producing months, so a young well's rising ramp is not
  treated as a workover.
- Database interface: `prepare_data_for_dca(skip_missing_header_columns=...)`, and the default
  ARIES mappings are exposed as `ARIES_DEFAULT_TABLES`, `ARIES_DEFAULT_PRODUCTION_COLUMNS`
  and `ARIES_DEFAULT_HEADER_COLUMNS`.

### Changed
- `_regime_steps` reports every detected step (peak, fittable, onset); `_latest_regime_start`
  is unchanged in behavior.
- Database interface: mapped table columns are checked before reading, and matched
  case-insensitively. A missing column raises a `ValueError` naming it and listing the
  table's columns, instead of an Access "Too few parameters" error.
- `run_dca_analysis` uses a header phase only when it is OIL or GAS; otherwise the well is
  classified by GOR, with a warning.

### Fixed
- **ARIES default header columns.** `ARIESDatabase.prepare_data_for_dca()` failed with "Too few
  parameters. Expected 2" whenever `AC_PROPERTY` lacked the default `LATERAL` or `DAYS_ON`
  fields, which are user-defined in ARIES. Default header columns a database lacks are now
  skipped with a warning. A mapping you supply is still checked strictly.
- **Header merge.** Header fields (phase, lateral length, days on) were never merged into the
  production data, so they never reached the DCA. They are now merged on the well ID.
- Table and column names with spaces or reserved words now work (identifiers are quoted).
- `prepare_data_for_dca` no longer converts mapped columns whose name contains "PROD" or
  "DATE" to datetimes. An oil column named `OIL_PROD`, for example, stays numeric; only the
  mapped date column is parsed.
- The pandas "only supports SQLAlchemy connectable" warning is no longer shown for pyodbc reads.

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
