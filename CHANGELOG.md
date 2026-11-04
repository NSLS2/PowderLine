# Changelog

All notable changes to the PowderLine **package** are recorded here. The format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and PowderLine
versions follow [Semantic Versioning](https://semver.org/).

The recipe **schemas** are versioned separately from the package and have their
own history, [`docs/SCHEMA_HISTORY.md`](docs/SCHEMA_HISTORY.md).

## [Unreleased]

## [0.2.0] - 2026-11-04

PowderLine 0.2.0 is a clean break from the unified recipe schema 0.26.0: a
recipe names one engine and is written in that engine's own conventions, and
nothing is translated between engines. Recipes written for 0.1.x do not
validate; see the [migration guide](docs/migration-0.1-to-0.2.md). Known
limitations are listed in the [known-issues register](docs/known_issues.md).

### Highlights

- **One recipe, one engine:** `gsasii.*`, `topas.*` and `easydiffraction.*`
  recipes, each in its engine's own names and units, through one API and one CLI.
- **New schemas, starting at 0.1.0:** a core schema plus one schema per engine
  replace the single 0.1–0.26.0 schema ([schemas](docs/schemas.md)).
- **Validation states what the engine computes:** symmetry, engine floors and
  silent defaults become errors or structured warnings, never silent changes.
- **Uniform fit statistics:** `rwp`, `r_exp`, `gof`, `chi2_red` are computed by
  PowderLine over the fit window, the same way for every engine.
- **The output recipe:** every result carries the recipe with refined values
  written back, ready to validate and run again (KI-04).
- **Ionic scattering types and March–Dollase preferred orientation**, and every
  failure raises an exception with a reason and a `failure.json` record.

### Upgrading

- Read the [migration guide](docs/migration-0.1-to-0.2.md): a 0.26.0 recipe
  (`GSASII_Rietveld` / `GSASII_SPF`) is refused at `schema_name`.
- Convert gsasii recipes with `python scripts/convert_recipe_026.py IN.json -o
  OUT.json`; it reports every change and stops where 0.1.1's refinement cannot
  be stated. TOPAS and easydiffraction recipes are written natively.
- API and CLI: `run()` has no `engine=`; failures raise instead of returning
  `success: False`; results have `status`, not `success` / `error`; `topas-kicker`
  is gone (use `powderline`); engine modules moved under `powderline.gateways`.
- Environments: the default pixi environment is core-only; install an engine
  with `pixi install -e gsasii`, `-e easydiffraction` (was `easydiff`), `-e all`
  or `-e dev`, then run `pixi reinstall powderline --all` and `powderline --doctor`.
- `rwp` is now PowderLine's uniform Rwp over the fit window, not the engine's
  own value (GSAS-II's wR is under `engine_details`); compare old values with care.

### Added

- Engine schemas `gsasii.rietveld` / `gsasii.spf` (GSAS-II 5.7.9),
  `topas.rietveld` / `topas.spf` (TOPAS 6) and `easydiffraction.rietveld`
  (easydiffraction 0.21.1), on a shared core phase block ([fields](docs/fields.md)).
- Declared schema compatibility: each gateway states the core and engine schema
  versions it accepts, `validate()` enforces them, and `powderline.support_matrix()`
  lists them ([support matrix](docs/support-matrix.md)).
- `powderline.validate()`, engine-free, returning `ValidationResult(recipe,
  warnings)`; an invalid recipe raises pydantic's `ValidationError` listing every
  problem at its field path.
- Structured warnings `{code, message, field_path, level}` in validation output
  and results (`level` `"warning"` or `"info"`); info `symmetry_value_derived`
  records a value held in its exact symmetry-derived form.
- The output recipe (KI-04): `output_recipe`, `output_recipe_valid` and
  `parameter_dispositions` in every result and validate-only summary, written to
  `output_recipe.json` and `parameter_dispositions.csv`.
- `metadata.powderline_provenance` in the output recipe and `failure.json`,
  naming the PowderLine version, the engine and its version; gsasii
  `engine_details` gains `engine_version`.
- `powderline.recipes.block` / `with_block` move core blocks (`xrd_data`,
  `fit_range`, a phase) between recipes, e.g. to chain a sequential refinement.
- A `gsasii.spf` result carries `peak_fit`: every parameter the peak fit varied,
  with value and ESD, by GSAS-II's own name.
- Ionic `scattering_types` (CIF spelling, e.g. `La3+`) per atom label in the
  gsasii and easydiffraction (`cryspy`) phase blocks, checked against each
  engine's ion table ([input guidance](docs/input-guidance.md); EB-94–EB-96).
- March–Dollase `preferred_orientation` (`hkl`, `ratio`) in the gsasii and
  easydiffraction (`cryspy`) phase blocks (EB-97, EB-98).
- TOPAS accepts ionic `scattering_types` (TOPAS 6's table, 113 ions, written as
  `La+3` in `occ`) and March–Dollase `preferred_orientation` (the `PO` macro;
  TOPAS's default lower limit on r, 0.0001).
- `powderline --doctor` (`pixi run doctor`): gateways found, engine versions
  against their pins and the GSAS-II server's state; non-zero exit on a stale
  install (KI-13).
- A failed run writes its failure envelope to `failure.json` in the output
  directory, and a failed `gsasii.*` run carries GSAS-II's console tail (KI-05).
- TOPAS time limit: `--topas-timeout SECONDS`, config `topas.timeout` or the
  `topas_timeout` option (default 3600 s per `tc.exe` run, 0 = none); past it
  `tc.exe` is stopped and the run raises `ExecutionBackendError(reason="timeout")`.
  The second run that only evaluates the background (`y_bkg`) does not fail a
  finished fit: stopped at the limit, it leaves the column empty with
  `topas_background_not_calculated`.
- `scripts/convert_recipe_026.py`, the 0.26.0 → `gsasii.*` converter.
- Examples: per-engine recipes under `examples/<case>/{topas,easydiffraction}/`,
  `example_LaB6_temperature_series` (sequential refinement), `example_LaB6_ionic`
  and `example_LaB6_textured`, with easydiffraction references.
- Documentation: [schemas](docs/schemas.md), [fields](docs/fields.md), [input
  guidance](docs/input-guidance.md), [engine behaviour](docs/engine-behavior.md),
  [cross-engine comparison](docs/cross-engine-comparison.md), [policies](docs/policies.md).
- Engine citations in `CITATION.cff` and on the [citing page](docs/citing.md) (#12).

### Changed

- The recipe schema is split: the single 0.1–0.26.0 schema is replaced by a
  core schema and one schema per engine, each starting at **0.1.0** and told
  apart by `schema_name`; the 0.x bump rule is in [policies](docs/policies.md).
- A recipe names its engine and workflow in `schema_name` (`<engine>.<workflow>`)
  and states that engine's own terms and units; unknown keys are errors at
  every level.
- The public API is `run`, `validate`, `ValidationResult`, `load_recipe_asset`,
  `support_matrix` and the exceptions; `run()` dispatches on `schema_name` and
  takes engine options as keywords; `import powderline` imports no engine.
- One CLI, `powderline <recipe.json>`, installed with the package, serves every
  schema (`--output`, `--validate-only`, `--verbose`, `--use-server` / `--no-server`,
  `--topas-dir`, `--topas-version`, `--topas-timeout`); `--validate-only` writes nothing.
- Every failure raises `EngineExecutionError` (the engine ran and failed) or
  `ExecutionBackendError` (it did not run), with `.reason` and `.result`, the
  failed envelope; the exceptions pickle.
- Every result carries `status` (`ok`, or `generated` for a TOPAS run without
  `tc.exe`), `converged`, `simulation_mode` and `envelope_version`; a statistic
  without degrees of freedom is `None`, never NaN.
- `rwp`, `r_exp`, `gof` and `chi2_red` are PowderLine's uniform statistics over
  the weighted points of the fit window; the engine's own values move to
  `engine_details` (LaB6: 6.5345 vs GSAS-II 6.5346).
- The fit window is exactly min ≤ 2θ ≤ max on the data points; a window with no
  weighted point is an error. A converted gsasii recipe fits one point fewer when
  its maximum falls between data points (EB-54).
- gsasii defaults are stated and warned about: size/strain left out means
  10 µm / 0 microstrain (was GSAS-II's 1 µm / 1000), background left out means
  none (was 1.0), and refinement cycles left out mean 5, each with a warning.
- New gsasii validation errors where GSAS-II used a floor silently or failed at
  run time: SH/L < 0.002, background or Peak List peaks below the floors, `scale`
  < 0, wavelength or size ≤ 0, and more (EB-35, EB-37, EB-38, EB-53).
- Space groups are gemmi's canonical names (`"P m -3 m"`, `"F d -3 m:2"`); gsasii
  refuses origin choice 1 and the settings GSAS-II cannot express (EB-03, EB-41).
- Refine flags and values must match the symmetry: a tie group is stated whole
  with one flag, a symmetry-fixed parameter is not refined, and a stated
  multiplicity must equal the derived one.
- A `topas.*` recipe whose total TCHZ peak width is not positive somewhere in
  the fit window is a validation error (TOPAS writes no results there); a
  negative Lorentzian part X·tanθ + Y/cosθ with a positive total width runs as
  written.
- A `gsasii.*` refinement that GSAS-II aborted (no step lowered χ²) raises a
  `diverged` failure instead of returning its rejected pattern (EB-99).
- A failed run leaves only the engine's own files and `failure.json`: a gsasii
  run no longer writes result tables before PowderLine's checks.
- `powderline.run()` removes PowderLine's own fixed-name outputs from the output
  directory before every run, so a reused directory holds one run's results.
- Every engine writes the same seven unit-cell report rows, `cell_a` …
  `cell_gamma`, `cell_volume`; a gsasii simulation writes ESD `0.0` (was empty).
- The GSAS-II server needs no shared filesystem: output files come back inside
  the signed response (KI-12); it runs one job at a time and a stale server is
  detected and refused.
- TOPAS runs only from a declared directory (`--topas-dir` or `topas.dir`);
  without one a run writes the INP and data and stops (`status: generated`).
  `topas.*` recipes state `engine_version: "6"` and the installed version is
  declared the same way (`"6"`, not `"6.0"`); TOPAS 7 is not supported.
- TOPAS execution is verified on TOPAS 6: the reference fixtures are reproduced
  byte for byte (KI-16).
- easydiffraction recipes state the calculator (`cryspy` or `crysfml`) and the
  engine's own instrument terms; anisotropic ADPs work with CrysPy (EB-23).
- Modules moved, without shims: `powderline.topas` → `powderline.gateways.topas`,
  `powderline.easydiff` → `powderline.gateways.easydiffraction`; `powderline.symmetry`
  raises `SymmetryError`.
- pixi environments: the default is core-only; engines live in `gsasii`,
  `easydiffraction`, `all` and `dev`; a run in an environment without its engine
  raises `EngineNotAvailableError` naming the install command.
- Pins: GSAS-II 5.7.9 and easydiffraction 0.21.1, checked at run time
  (`EngineVersionError`); gemmi `==0.7.5`; pixi ≥ 0.82.1.
- The regression references under `examples/*/output/` were regenerated once on
  the new path and gain `output_recipe.json` and `parameter_dispositions.csv`;
  the LaB6 examples drop their undeterminable background peak.
- The simulation recipe builder writes SH/L 0.002 (GSAS-II's floor) and emits a
  `gsasii.rietveld` 0.1.0 recipe.

### Removed

- The unified 0.26.0 schema and the cross-engine translation layer
  (`powderline.schema`, the legacy TOPAS writer and easydiffraction builder).
- From the API: `run(engine=...)`, `RecipeModel`, `validate_simulation_mode_parameters`,
  `powderline.engine`, top-level `GSASClient` and the shims `powderline.constraints`,
  `powderline.gsas_client`, `powderline.gsas_server`.
- The `topas-kicker` console script and pixi task.
- The result keys `success`, `error` and `traceback`, the reason
  `output_not_visible`, and `GSASClient.run_simulation`.
- gsasii fields with no effect: `refinement_algorithm`, the `null` instrument and
  phase forms, parameter bounds, `payload.asset_path` and `Iparm2`.
- The Materials Project simulation tool (`mp-simulate`) and its configuration;
  the simulation recipe builder stays.
- The `easydiff` pixi environment (now `easydiffraction`) and GSAS-II in the
  default environment.
- The TOPAS 7.25 references under `examples/*/output/topas/` and
  `example_LaB6_easydiff`.
- The pre-refactor TOPAS helpers (`topas/conversions.py`, `runner.run_topas`,
  `RunResult`) and symmetry API (`cell_constraints`, `site_dof`, `adp_dof`,
  `check_uij`).
- The unused dependencies `h5py`, `pybaselines` and `xmltodict`.

### Fixed

- A gsasii run no longer computes 4× the intensity for some 2-fold sites in R32,
  R-3m and R-3c, nor crashes on a site GSAS-II cannot name; both are errors
  naming a position to state (EB-40, EB-05).
- A diverged gsasii refinement (non-finite pattern) no longer returns success
  with Rwp 100 % and a NaN profile (EB-52).
- easydiffraction: 0.1.1's wrong polarization (p = P, not 1 − P), swapped
  Lorentzian X/Y, FCJ S/L and H/L, and 2θ rounded to 4 decimals are gone (EB-72,
  EB-75, EB-76).
- The simulation recipe builder counted a site *multiplicity* times and used
  origin choice 1 coordinates as origin 2 (EB-03); its grid now includes
  `max_2theta`.
- `powderline.symmetry` handles the monoclinic groups Pm, Pc, Cm and Cc in every
  setting, and classifies trigonal and hexagonal sites correctly.
- An exception while easydiffraction builds the project is
  `EngineExecutionError(reason="engine_crashed")`, like one in the fit.
- A TOPAS `output_missing` failure carries its envelope: the files kept,
  `tc_path`, the exit code and any console text.
- A TOPAS output folder outside the Windows ANSI code page is run through the
  folder's 8.3 short path (file names kept), or refused with a clear message
  before `tc.exe` starts.
- The TOPAS at-limit warning tolerates TOPAS stopping just past a bound or a fit
  window edge.
- A timed-out GSAS-II server request is a `timeout` failure and no longer falls
  back in-process into the same directory; a bad port, a busy port or a Windows
  sharing violation is reported instead of crashing.
- Recipe and `.powderline_config.yaml` files are read as UTF-8; malformed JSON
  or YAML is an error naming the file (the CLI says "Cannot read recipe").

### Security

- The GSAS-II server no longer writes into a client-chosen directory; the client
  writes returned files by bare name only, size-capped; a request body read
  before the signature check is capped at 4 KiB except on `/simulate` (KI-12).
- `pip >= 26.2.2` and refreshed `ca-certificates` / `certifi` after the emSign
  CA incident; pixi ≥ 0.82.1 is required.

## [0.1.2] - 2026-10-10

Tagged on `main` after the refactor branch was cut; merged into the 0.2.0
branch on 2026-10-14 (the server and client live at
`src/powderline/gateways/gsasii/server.py` / `client.py` there; the
known-issue entry is `KI-14` on 0.2.0 because `KI-13` was already taken).
<!-- git: b38c73e, tag v0.1.2 -->

### Fixed
- GSAS-II server made per-user and token-authenticated: per-user state
  directory, loopback bind on an ephemeral port, bearer token on every route,
  `POWDERLINE_NO_SERVER` to disable the server (#10).

## [0.1.1] - 2026-09-24

The pre-refactor baseline; unified recipe schema 0.26.0.
<!-- git: fb90228, tag v0.1.1; 43 commits since v0.1.0 -->

### Added
- easydiffraction engine (`engine="easydiffraction"`, optional `easydiff` pixi
  environment) with the SH/L → Thompson-Cox-Hastings/FCJ profile mapping (#2).
- Documentation published on GitHub Pages (#4–#7).

### Fixed
- GSAS-II's refinement failure message is surfaced instead of a silent
  no-Rwp result; `run()` normalisation no longer crashes on null tables from
  server failure responses (#3).

## [0.1.0] - 2026-08-17

Initial public release.

[Unreleased]: https://github.com/NSLS2/PowderLine/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/NSLS2/PowderLine/compare/v0.1.2...v0.2.0
[0.1.2]: https://github.com/NSLS2/PowderLine/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/NSLS2/PowderLine/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/NSLS2/PowderLine/releases/tag/v0.1.0
