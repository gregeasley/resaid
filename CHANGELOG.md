# Changelog

## 0.4.2

### Upgrade notes
This release changes outputs and makes several silent behaviors errors:
- The oneline `OIL`, `GAS` and `WATER` columns are replaced by `HIST_*`, `PROJ_*` and
  `EUR_*` (see Fixed). Scripts that read `OIL`/`GAS`/`WATER` from `oneline_dataframe`
  should use `EUR_*` (or `PROJ_*` for remaining volumes).
- `flowstream_dataframe` now holds actual production for history months and gains a
  `HISTORICAL` column. Econ run on it covers the whole well life by default; set
  `well_econ.projection_only = True` for the projection only.
- Type-curve parameters (`tc_params`) change, in some cases substantially: their EUR
  targets were taken from the incorrect oneline totals.
- `phase_col` must give each well a single OIL or GAS value; otherwise `run_DCA()` raises.
- Econ settings that would be ignored raise `ValueError`, and missing or blank header
  values warn (see Changed). `IRR`, `PAYOUT` and `ROI` are NaN, not 0 or infinite, when
  they cannot be computed. CAPEX is charged at spud, after any `t_start_column` delay.
- Database: `run_dca_analysis` exports are in actual volumes, its extra keyword
  arguments are applied, and `prepare_data_for_dca` rejects unknown arguments.
- `input_monthly = False` raises `NotImplementedError`.
- Forecasts change slightly where the L3M upside adjustment applies (rejoin point).

### Fixed
- **Flowstream history and projection.** The flowstream was the fitted curve evaluated
  from the well's first month, never actual production: over history it held the curve
  instead of actuals, and before the curve's `t0` (late fits after a step change or late
  peak) the curve projected backward, which grows without bound near its pole. The
  oneline `OIL`/`GAS`/`WATER` totals were sums of this, so they were not EURs (in the
  sample data, -20% to +160% off on the default method, and 0.9 million vs 0.33 million
  bbl on one `monotone_two_step` well), and econ run on the flowstream included the same
  months. The original design overlaid actuals on the curve; that step was lost in an
  earlier refactor. Now:
  - History months (through the last actual month) are actual production (0 for months
    missing from the data), marked `HISTORICAL`; the projection starts the month after
    and never extends before `t0`.
  - `T_INDEX` 1 is the first production month and the projection at `T_INDEX` t is the
    curve at well month t - 1, matching the history. Previously the curve at month t was
    placed at `T_INDEX` t, so the first production month was missing.
  - The oneline reports `HIST_*` (actual to date), `PROJ_*` (projection from the end of
    history) and `EUR_*` (their sum) for oil, gas and water.
  - `actual_dates=True` fills `P_DATE` on history rows (it had no effect).
- **Major phase is per well.** `phase_col` was read row by row, and ratio mode grouped a
  well's months by well *and* phase label, so a well whose phase label differed between
  months was split into one fit per label, each on only the months with that label, and
  appeared once per label in the oneline and exports. A value other than OIL/GAS dropped
  the well silently. `run_DCA()` now takes one phase per well (ignoring case and
  surrounding spaces; blank rows take the well's value) and raises a `ValueError` naming
  any well whose phase is missing, not OIL or GAS, or differs between rows.
- **Type curves.** They overlaid history on the curve but placed history one month later
  than the curve, skipping one projected month where they met, and filled months missing
  from the data with the backward projection. They now use the flowstream. Their EUR
  targets (`curve_eur` in `tc_params`) were quantiles of the broken oneline totals; they
  now use `EUR_*`. Type-curve parameters change, in some cases substantially.
- **Database exports in actual volumes.** `run_dca_analysis` built each well's oneline in
  volumes normalized to the 5,280 ft standard lateral, and `export_results` wrote those, so
  a 10,560 ft well exported about half its rate. Onelines are now denormalized to each
  well's `LENGTH`.
- `export_results(export_format="phdwin")` failed for every well; it now writes
  `{well_id}_phdwin_export.csv`.
- `export_results` creates nested `output_dir` folders, and an unsupported `export_format`
  raises `ValueError` up front instead of one warning per well and an empty result. The
  format is matched case-insensitively.
- A failed PhdWin conversion no longer leaves an empty temporary `.sqlite` file behind.
- `connect()` no longer starts a Java VM. The JPype/UCanAccess connection was a placeholder
  that never connected, and a JVM cannot be restarted in the same process; it is removed,
  along with the unused `jpype1` dependency in the `database` extra.
- **L3M upside rejoin point.** When the last-three-month average is above the fit, the
  re-solved curve rejoined the fit at twice the time from the fitted `t0` to the L3M
  midpoint, so equally good fits with different `t0` gave different forecasts. The rejoin
  point is now measured from the start of the fit window: same distance after the midpoint
  as the midpoint is after the window start. Unchanged when the fit puts `t0` at the window
  start; otherwise forecasts move by under 2% for most affected wells. Accuracy against
  synthetic truth is unchanged. Applies to both fit methods.
- **Economics timing.**
  - The economic limit (a row position) was compared with `T_INDEX`, which starts at 1 in
    `decline_curve` flowstreams, so the last month before the limit was zeroed. Every run
    lost one producing month.
  - `t_start_column` without `spud_to_online` shifted `T_INDEX` but inserted no delay
    months, so the start delay had no effect on cashflow or discounting. Both delays now
    insert months with no volume.
  - Delay months were charged the fixed operating cost (`opc_t`) in one month; they now
    carry no operating expense. `T_INDEX` stays contiguous (it could repeat a value).
  - CAPEX is charged at spud, the first month after the `t_start_column` delay, instead of
    the first month of the delay.
- `oil_pri` and `gas_pri` accept numpy arrays, tuples and Series as well as lists.
- A flat `capex_val` was charged only to wells in `header_data`; with no header data, or
  for a well missing from it, CAPEX was 0. It now applies to every well.

### Added
- `well_econ.projection_only` evaluates only the projection rows of a flowstream (e.g.
  remaining PDP value).
- Three-phase flowstreams and onelines have a `MAJOR` column: `phase_col` when set,
  otherwise from the well's EUR GOR. Econ's `spud_to_online` and `t_start_column`, which
  need it, now work with three-phase flowstreams.
- `run_dca_analysis(**settings)` applies `decline_curve` settings to every well (e.g.
  `fit_method="monotone_two_step"`); they were accepted and ignored.

### Changed
- **No silent fallbacks.**
  - Econ: a well missing from `header_data`, or a blank header value, now warns (naming
    the well) when it falls back to defaults. Settings that would be ignored raise a
    `ValueError`: `scale_forecast`/`scale_capex` without `scale_column`, `scale_capex`
    without `capex_val` or `capex_col`, `wi_col` without `nri_col` (or the reverse),
    `owned_royalty_col` without `wi_col`/`nri_col`/`royalty_col`, and `royalty_col` with
    `wi_col`/`nri_col` but no `owned_royalty_col`.
  - DCA: a failed outlier screen, short-regime EUR solve or type-curve decline match now
    warns, naming the fallback used. They were logged at debug level only.
  - `prepare_data_for_dca` no longer accepts (and ignores) unknown keyword arguments; a
    misspelled argument raises `TypeError`.
  - `input_monthly = False` raises `NotImplementedError`: daily production was never
    supported (see Future improvements in the README).
- `ROI` is NaN instead of infinite when a well has no CAPEX.
- `IRR` is NaN instead of 0 when it cannot be solved (e.g. no negative cashflow). If
  Newton's method does not converge, the rate is now found by bracketing (Brent's method)
  before giving up. `npv_calc.get_irr()` returns NaN instead of raising. It is still 0
  when the undiscounted cashflow sum is negative.
- `PAYOUT` is NaN instead of 0 for wells that never pay out, so 0 means only "pays out
  in the first month".
- `well_econ.generate_capex()` takes an optional `capex_point`.

### Internal
- No basedpyright errors anywhere in the repository: `well_econ` settings and
  `arps_decline` (float in, float out; array in, array out) are typed, so assigning a
  price or indexing a curve no longer shows as an error in editors; tests check optional
  results explicitly.
- `scripts/database/check_aries_interface.py` called reader methods that do not exist;
  it now uses `read_table_data`.
- CI adds a pandas 2.x job alongside pandas 3.

## 0.4.1

### Upgrade notes
This release changes behavior beyond bug fixes:
- Python 3.10 or newer is required.
- Setting an attribute name a class does not define now raises `AttributeError` (see Added);
  scripts that set misspelled or renamed settings will stop with the closest valid name.
- `monotone_two_step` forecasts change for most wells (see Fixed).
- Default-method forecasts change through the L3M placement and export START fixes.

### Added
- **Unknown settings are rejected.** Assigning an attribute name that `decline_curve`,
  `decline_solver`, `well_econ`, `npv_calc` or the database classes do not define raises
  `AttributeError` with the closest valid names (e.g. `OUTLIER_CORRECTION` suggests
  `outlier_correction`), instead of silently creating an unused attribute. Subclasses may add
  attributes in `__init__` or opt out with `_strict_attributes = False`.
- **Input checks with clear errors.** `decline_curve.run_DCA()` (and everything that calls
  it) checks `dataframe`, the required column names and that every configured column exists.
  `well_econ` checks `flowstreams`, its ID and time columns, `discount_rate`, and configured
  header columns. `decline_solver.solve()` names the parameter it is missing. Each raises
  `ValueError` naming the problem (and listing available columns) instead of an unrelated
  `TypeError`, `KeyError` or `AttributeError`.
- **Minor phases follow the major phase's window** (`minor_window_from_major`, on by default,
  three-phase mode). Each minor phase's fit window starts where the major phase's does (its
  first peak or latest regime), instead of running its own peak and step detection, so a spike
  in a minor phase no longer cuts its fit to a short recent window while the major phase is fit
  on its long-term decline. Zero months and outliers are still screened per phase. The major
  phase comes from the `phase_col` (or the GOR rule).

### Fixed
- **Repeated runs on one object.** Calling `generate_oneline` (directly, or through typecurves
  and exports) a second time without re-running DCA failed with `KeyError: 'MIN_DATE'`, and
  under pandas 3 a third `run_DCA()` failed with a `MergeError` (duplicate `MIN_DATE_MIN`).
  Both now work any number of times, e.g. after switching `three_phase_mode`. Results are
  unchanged.
- **`monotone_two_step` uses the default method's L3M adjustment.** After its stage-1 fit it
  re-solved the decline from the current tail rate so that the *remaining* volume equalled the
  curve's *full-life* EUR, counting production to date twice; about 20% of wells could not
  reach that target and fell to the terminal decline. Its EUR also depended on which of several
  equally good fits SciPy returned (up to 22% between pandas 2.3/SciPy 1.16 and pandas
  3.0/SciPy 1.18). It now follows its fit with exactly the default method's post-fit step: the
  L3M adjustment, or the short-regime EUR match. Against known synthetic truth, median
  full-life EUR error fell from 18.0% to 11.2% (default method: 8.9%), and median 5-year
  hold-out error from 18-27% to 10-14% by well type. Most `monotone_two_step` results change.
  The default method is unaffected.
- **ARIES minor phase in `aries_eco_gen`.** The ratio-mode ARIES writer built the minor-phase
  ratio line (`GAS/OIL ... TO LIFE LIN TIME` / `OIL/GAS ...`) but never wrote it; it is now
  written after the major phase. `generate_aries_export` was not affected.
- **L3M placement.** The default fit's L3M adjustment (`_adjust_default_fit_to_recent_l3m`)
  matched the last-three-month average at the last month, one month late. It now matches it at
  the midpoint (mean time) of those three months, as the monotone method already did; the
  solved path's convergence point moves with it. Zero months still count in the average.
- **Export starting rate.** ARIES (ratio and three-phase) and Mosaic exports start at the last
  actual month, with each phase's rate and decline taken from its fitted curve at that month;
  with the L3M fix that is one month past the midpoint where the curve meets the
  last-three-month average. The three-phase ARIES export previously wrote the raw
  last-three-month average as the starting rate (a phase whose last three months are all zero
  is still written FLAT).
- `_export_rate_at_tau` (Mosaic, PhdWin and fallback exports) returned the rate at T0 for
  exponential curves (b = 0); it now evaluates `arps_decline`, including the terminal decline.
- `well_econ.zero_below` used a hard-coded `T_INDEX` column, so a flowstream with a
  different `flowstream_t_index` failed; it now uses the configured name.
- Header columns configured on `well_econ` that do not exist (e.g. a misspelled
  `capex_col`, `scale_column` or `t_start_column`) were silently ignored; they now raise.
- Database `connect()` returned `True` when only the mdbtools probe succeeded, with no
  connection open; it now counts only an actual connection. Failures are reported with the
  reason for each method tried (e.g. pyodbc not installed, or the Access driver error).

### Changed
- `decline_solver.solve()` returns `qi`, `t_max`, `qf`, `de` and `eur` as floats
  (e.g. `t_max` is `1200.0`).

### Compatibility
- **Python 3.10 or newer is required** (`python_requires >= 3.10`), matching what CI tests;
  the code now uses 3.10 syntax (`X | None`, `itertools.pairwise`).
- Verified on pandas 3.0, NumPy 2.5, SciPy 1.18 and statsmodels 0.15 as well as pandas 2.3,
  NumPy 2.3, SciPy 1.16 and statsmodels 0.14: the test suite passes on both. Fitted curves are
  equivalent; forecasts agree within 0.4% EUR for the default method and 0.6% for
  `monotone_two_step`, except where the L3M upside path differs (see Known Issues).
- Outlier screening passes statsmodels a DataFrame instead of a dict (deprecated in
  statsmodels 0.15). Results are identical.
- Flowstream NaN handling and ratio capping no longer rely on pandas behaviors that changed
  in pandas 3 (object-dtype `fillna` downcasting, writes to a filtered slice). Results are
  identical.
- Database integration tests skip when pyodbc or the Microsoft Access ODBC driver is not
  installed.

### Internal
- Adopted ruff's default rule set (ruff 0.17) with a `ruff.toml` that pins the Python target.
  Broad `except Exception` handlers that are intentional fallbacks are annotated with the
  reason; others were narrowed or now log at debug level. `setup.py` reads the version without
  `exec`. No behavior change.
- Linter cleanup with no behavior change: `is None` comparisons, `except Exception` in place
  of bare `except`, unused imports and variables removed, and type annotations added for
  attributes initialized to `None` or empty dicts. `__version__` is listed in `resaid.__all__`.
- Added `pyrightconfig.json` (basedpyright/pyright "standard" mode); see the README's
  Validation section for the type stubs to install.
- Removed no-op `SET_LENGTH` and `DEFAULT_B` assignments (attributes that do not exist on
  `decline_curve`) from tests and developer scripts.

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
