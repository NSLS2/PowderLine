# Changelog

All notable changes to the PowderLine **package** are recorded here. The format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); PowderLine
versions follow [Semantic Versioning](https://semver.org/)
<!-- master plan A12/A16: SemVer + root CHANGELOG; v0.1.1 = pre-refactor tag, v0.2.0 = the refactor -->.

The recipe **schemas** are versioned separately from the package (core schema +
one schema per engine) and have their own changelog,
[`docs/SCHEMA_HISTORY.md`](docs/SCHEMA_HISTORY.md). Where a bullet below cites
"(row N, A…)" it refers to the maintainers' deliberate-behaviour-changes table
(row N) and decision-log entry (A…); "(P-NN)" is a provisional decision taken
while the maintainer was away, to be confirmed.

## 0.2.0 — 2026-10-16

<!-- The version in src/powderline/__init__.py, CITATION.cff and pixi.toml is
     set to 0.2.0 at the release step (G4), together with the date below. -->

PowderLine 0.2.0 is a **clean break** from the unified recipe schema 0.26.0
(A4, A14): one recipe now targets one engine, in that engine's own
conventions, and nothing is translated between engines. Existing 0.26.0
recipes do not validate; see the
[migration guide](docs/migration-0.1-to-0.2.md).

### Added

- **The output recipe** (KI-04, re/20a, P-43): every result and the validate-only
  summary carry `output_recipe`, a complete recipe of the same schema, *resolved*
  (refined values written back at their recipe paths, symmetry-derived values in
  their exact form, gateway defaults stated, the user's flags/bounds/controls/data
  unchanged, one reserved `metadata.powderline_provenance` key), that validates
  unchanged and reproduces the step when fed back; `output_recipe_valid` and the
  warning `output_recipe_not_valid` say when an engine returned something the
  schema refuses; `parameter_dispositions` labels every refinable leaf
  (`varied`, `held_by_user`, `held_by_symmetry`, `requested_not_varied`,
  `default_applied`; ESD; `at_limit`). Core propagates every symmetry tie group
  and asserts every site keeps its multiplicity. Files `output_recipe.json` and
  `parameter_dispositions.csv`. All three engines fill it: TOPAS and
  easydiffraction from their builders' path bookkeeping, GSAS-II from a
  name-to-path map over its refined-parameter rows, unit-cell reports and, for
  a peak fit, the fit's own parameter block (`gateways/gsasii/paths.py`;
  coordinates are the recipe's plus GSAS-II's shift). A GSAS-II peak fit fills
  no covariance block, so a `gsasii.spf` result carries `peak_fit`
  (`{"parameters": [{name, value, esd}]}`, every parameter the fit varied by
  GSAS-II's own name, read from the project: the background, the instrument
  profile with `use_instrument_profile`, the peaks) and the output recipe is
  built from it with ESDs (re/21; before it the peak-fit output recipe kept
  the starting background, marked `requested_not_varied`, and the
  instrument-profile mode was a stated gap). What it exposed: the committed
  DRX_33 atom-refinement and anisotropic references refined occupancies below
  zero and negative crystallite sizes, and the LaB6 single-peak fitting
  reference's background peak refines its σ² far below GSAS-II's silent floor,
  so their output recipes are `output_recipe_valid: false` — the references
  are unchanged; the output recipe reports what they contain.
  `powderline.recipes.block` /
  `with_block` move core blocks (`xrd_data`, `fit_range`, a phase) between
  recipes, the only parts shared across engines. **Sequential refinement
  example** (`examples/example_LaB6_temperature_series/`, re/22): six LaB6
  patterns simulated with GSAS-II from 25 to 500 °C on the measured 28-ID-1
  grid, with the SRM 660a thermal expansion of Akdoğan & Payzant (2025), a
  temperature-dependent Uiso and Poisson noise (`make_series.py`, seeded),
  refined in sequence by swapping only the `xrd_data` block into each step's
  output recipe (`run_series.py`); the reference `output/series_report.csv`
  recovers the programmed a(T) within 1.5 ESD, and the regression test
  re-runs the chain. The same runner drives the **easydiffraction leg**
  (`easydiffraction/input.json`, CrysFML TCH; golden
  `tests/data/easydiffraction/native/golden/lab6_temperature_series.json`):
  six valid steps, the expansion to 0.8 %, with the absolute cell 14–31 ppm
  and La's Uiso 10–22 % below the GSAS-II-calculated truth (an inter-engine
  profile difference, EB-93: the series' GSAS-II profile has its Lorentzian
  width clamped to 0.001 centideg above ≈ 10.7°, which easydiffraction's
  profiles cannot represent; shown by the re/24–25 probes) and the
  free-Lorentzian-X posing stopping honestly at step 1 on a negative width
  (EB-87).
  Regression reference: the easydiffraction `lab6_cryspy_pv` golden's warning
  list gains `output_recipe_not_valid` — that fit ends with a profile the schema
  refuses (a negative width near the window, EB-87), the case D5 is for.
- **One unit-cell report vocabulary** (re/23, P-45): every engine's
  `<phase>_unit_cell_report.csv` / `unit_cell_data` has the seven rows
  `cell_a … cell_gamma, cell_volume` with one ESD rule (the engine's ESD for a
  refined member; `0.0` for a member fixed by symmetry or held; empty when the
  engine refined it but reported none; the volume's ESD when propagated).
  A gsasii *simulation* (no covariance) wrote every ESD empty; it now writes
  `0.0` (frozen-edits ledger row R34, re/24) — the two simulation references'
  unit-cell reports change in their ESD column only (deliberate change 33).
  Core owns the vocabulary and builds the rows (`reports.UNIT_CELL_ROWS`,
  `unit_cell_rows`); the writer refuses any other row; `UNIT_CELL_ROW_OF` /
  `UNIT_CELL_MEMBER_OF` are the one bridge to the recipe paths of
  `output_recipe` / `parameter_dispositions`. topas and easydiffraction, which
  wrote `a … volume`, now write the vocabulary (their goldens' unit-cell keys
  renamed; no example reference moves — gsasii already wrote it).
- **Ionic scattering types** (re/28, P-47; closes A63): `element` stays the
  neutral atom in core (the phase block stays portable, D4); each engine's
  phase block gains `scattering_types: {<atom label>: "La3+"}` in the CIF
  spelling (element, charge 1–8, sign), validated by core (the engine spelling
  `La+3` is an error naming `La3+`) and by the engine's own table of ions it
  has form factors for (GSAS-II 5.7.9: 114; CrysPy: 111; an ion the engine
  lacks is an error naming the forms it has). gsasii translates to GSAS-II's
  `La+3` where the frozen project builder writes the atom type (ledger R35;
  GSAS-II reads `La3+` as hydrogen, EB-94); easydiffraction hands the CIF
  spelling to CrysPy, and refuses ions with the crysfml calculator (it strips
  every charge, EB-96) or outside CrysPy's table (its silent neutral fallback,
  EB-95); **topas refuses `scattering_types` in 0.1.0** (TOPAS spells `Fe+3`
  and reports an unknown ion only on its console; no TOPAS run here, P-08,
  T7). Gate: the La3+/La per-reflection intensity ratios of the LaB6
  calculation agree between GSAS-II and CrysPy within 1 % (golden
  `tests/data/ions/`). The 0.26.0 converter turns a GSAS-II-spelled ion
  (`Fe+3`, passed through unchecked by v0.1.1) into neutral `element` +
  `scattering_types`. New example `example_LaB6_ionic` (La3+, B neutral: no
  boron ion exists in either table) with an easydiffraction (cryspy) leg.
- **Preferred orientation, March–Dollase** (re/29, P-48; Adam's re/11 for
  gsasii and easydiffraction): the core building block `MarchDollase`
  (`{model: "march_dollase", hkl: [h, k, l], ratio}`; `hkl` not all zero,
  `ratio > 0`; GSAS-II's convention, 1 random, < 1 platy, > 1 needle) behind an
  optional `preferred_orientation` in each engine's phase block. gsasii writes
  the HAP `Pref.Ori.` entry through a new frozen setter (ledger rows R36/R37)
  and maps the refined `p:h:MD` back to the recipe path; easydiffraction adds
  the experiment's `preferred_orientation` row (bounded `ratio` plus the
  required `march_random_fract` in [0, 1]), **cryspy calculator only**
  (CrysFML ignores the row silently, EB-97; the row must be keyed by the
  lowercase structure name or CrysPy ignores it too, EB-97); **topas refuses
  it in 0.1.0** (`PO(...)` awaits a TOPAS 6 run, T9). Gate (C1): on a
  simulated textured LaB6, each engine's textured/untextured intensity ratio
  per resolved reflection equals Dollase's correction averaged over the
  reflection's cubic equivalents within 0.2 % (CrysPy's correction carries a
  constant r^1.5, EB-98; compared normalised). New example
  `example_LaB6_textured` — a **mathematical demonstration** (LaB6 does not
  texture): r = 0.6 along [001] programmed, 0.5978(14) recovered by GSAS-II
  from a start of 0.8, with an easydiffraction (cryspy) leg.
- **A refinement GSAS-II aborted is a divergence** (re/29, EB-99;
  deliberate change 35): a `gsasii.*` *refinement* whose `Rvals['Aborted']`
  is set (no damped step lowered χ² before its Marquardt limit) now raises
  `EngineExecutionError(reason="diverged")`. GSAS-II then keeps the last
  accepted parameter values (the start, in a first-cycle abort) but stores
  the rejected step's calculated pattern — finite but worthless, wR printed at
  its 100 % cap — so no statistic belongs to the parameters; the non-finite
  check (EB-52) passed it as `status: ok` with an astronomical uniform Rwp
  (seen with the March–Dollase coefficient started at exactly 1.0 in a cubic
  phase, where the averaged correction is stationary). GSAS-II's own GUI keeps
  such a result behind a "Minimizer halted" warning; PowderLine is
  deliberately stricter. A poor but honest fit (wR at the cap, no abort) is
  still reported; simulations are exempt.
- **A failed run leaves the engine's own files and `failure.json`, nothing
  else** (re/30; deliberate change 36; ledger row R38): the GSAS-II executor
  now runs PowderLine's checks (divergence, abort, convergence) *before* it
  writes any result table, as TOPAS and easydiffraction already did, so a
  diverged or aborted gsasii run no longer leaves `refined_parameters.csv`,
  the two reports or `fit_profile.txt` describing a result that does not
  exist (the pattern stays in `dummy.gpx`). `powderline.run()` writes the
  failed envelope — reason, message, traceback, console tail, the file list —
  plus a `powderline_provenance` block to `failure.json` in the output
  directory, for both failure classes, when the directory exists. The CLI
  lists "Files kept for diagnosis".
- **`powderline.run()` clears PowderLine's own fixed-name outputs before
  every run** (re/30; deliberate change 37): `refined_parameters.csv`,
  `*_unit_cell_report.csv`, `*_peak_list_report.csv`, `fit_profile.txt`,
  `single_peaks_report.txt` / `.csv`, `output_recipe.json`, `parameter_dispositions.csv`
  and `failure.json` (`reports.FIXED_OUTPUT_NAMES` / `FIXED_OUTPUT_PATTERNS`);
  never the engine's files or anything else in the directory. A reused
  directory therefore holds one run's results: a renamed phase no longer
  leaves its old report behind, a failed run's directory is not padded with
  the previous run's tables, and a success does not sit beside a stale
  `failure.json`. Validate-only runs touch nothing.
- **`powderline --doctor`** (`pixi run doctor`; re/27, KI-13 implemented): the
  PowderLine version, the gateways the registry finds with their workflows
  and engine requirements, each engine's installed version against its
  requirement, the GSAS-II server's state directory and status; non-zero exit
  for a missing registry (the stale editable install) or an engine outside
  its requirement, naming the repair.
- **The engine's console text on a failed `gsasii.*` run** (re/27, KI-05
  implemented): `gateways/gsasii/console.py` tees GSAS-II's stdout for the
  run (in-process and per server job) into a 64 KiB tail; a failed envelope
  carries it as `failure.console_tail`, a verbose success under
  `engine_details["console_tail"]`, and the CLI prints the last lines after
  "Refinement failed". Nothing parsed, no new warning code.
- **Known-issues second pass** (re/26, P-46): every `KI-NN` re-read against
  the 0.2.0 tip; KI-11 (orphaned server after its runtime directory is
  deleted) is `accepted`, KI-05's open half (GSAS-II's console-only messages)
  has a concrete non-frozen plan, KI-13/KI-14 record what the refactor added,
  and two entries are new — KI-15 (four example references are unphysical as
  posed, their output recipes invalid by design, P-44) and KI-16 (TOPAS
  execution unverified for 0.2.0: generate-only and the goldens are the
  contract on the fork, a blocker for the upstream merge; the support matrix
  now states the verification status per engine).

**Schemas and versioning**
- **Core schema 0.1.0** (`src/powderline/schema_core.py`): the shared top level
  (`schema_name`, `core_schema_version`, `engine_schema_version`, `metadata`,
  `payload`) and the structural models every engine uses — `xrd_data`,
  `fit_range`, Chebyshev background, parameter lists, and one **phase block**
  per phase (`space_group`, `unit_cell`, `atoms`) whose every structural
  quantity is a refinable parameter and whose flags, values and bounds are
  checked against the symmetry (A93; `SCHEMA_HISTORY.md` "Core schema").
- **Engine schemas 0.1.0** on core 0.1.0: `gsasii.rietveld` / `gsasii.spf`,
  `topas.rietveld` / `topas.spf` (TOPAS 6), `easydiffraction.rietveld`
  (`SCHEMA_HISTORY.md`, one section per engine). Core and engine schemas are
  versioned separately and all start at **0.1.0**; they replace the single
  0.1–0.26.0 schema line (`GSASII_Rietveld` / `GSASII_SPF`), which ends at
  0.26.0 and is told apart by `schema_name`, not by number
  (`SCHEMA_HISTORY.md` "Version numbering"). While the schemas are 0.x, a
  breaking change bumps the minor and an additive change or fix the patch
  (`docs/policies.md`).
- **Declared compatibility** (A40, A65): core declares the core-schema
  versions it accepts; each gateway declares `engine_schema_version`,
  `supported_engine_schemas` and `requires_core_schema`. `validate()` enforces
  the declarations; `powderline.support_matrix()` lists them. See
  [`docs/support-matrix.md`](docs/support-matrix.md).
- **`scripts/convert_recipe_026.py`**: converts a 0.26.0 `GSASII_Rietveld` /
  `GSASII_SPF` recipe to `gsasii.rietveld` / `gsasii.spf`, writing out
  explicitly what v0.1.1 effectively refined and reporting every change; it
  stops, listing every problem, where a refinement cannot be stated (row 21,
  A132). No converter exists for TOPAS or easydiffraction (A137).
- **Structured warnings** (`warnings: [{code, message, field_path}]`) in
  results and validation output (A23), e.g. `gsasii_broadening_default_applied`,
  `gsasii_parameters_not_varied` (row 20, A128), `uaniso_not_positive_definite`
  (A118), `topas_parameter_at_limit`, `easydiffraction_parameter_at_limit`,
  `*_phase_contributes_nothing`. Each entry may carry a `level` (P-34):
  `"warning"` (absent means this) or `"info"`; the CLI prints warnings and
  counts info entries (listed with `--verbose`). Info-level
  `symmetry_value_derived` records every coordinate, cell value or Uij the
  validated model holds in its exact symmetry-derived form because it was
  stated within tolerance of it (stated and held values in the message);
  an exactly stated value gets none, so the note is evidence of a symmetry
  relation, not a statement of one. gsasii adds
  `gsasii_background_default_applied` and
  `gsasii_refinement_cycles_default_applied` when those blocks are left out
  (P-33), alongside the size/strain warning. `topas_phase_contributes_nothing`
  and `easydiffraction_phase_contributes_nothing` are level `info`.
- **Exceptions** in `powderline.exceptions`: `SymmetryError`,
  `GatewayNotInstalledError`, `EngineNotAvailableError`, `EngineVersionError`,
  `EngineExecutionError` (A23; row 1, A56/A57/A61).

**Results (all engines)**
- Uniform fit statistics computed once in core: `rwp`, `r_exp`, `gof`,
  `chi2_red`, in percent / dimensionless, over the points inside the fit
  window with positive weight (A23, A55, A125). The engine's own values, plus
  `parameters_requested` / `parameters_varied` and (gsasii Rietveld)
  `converged`, sit under `engine_details` (A45). Every native result carries
  `simulation_mode` (bool); a statistic without degrees of freedom is `None`,
  never NaN (row 20, A129).

**gsasii**
- New validation errors, each at the field it concerns, where v0.1.1 ran
  anyway or failed at run time: SH/L below 0.002 (row 8, A91); background
  peaks below GSAS-II's evaluation floors (intensity 0.1, σ² 0.01 centideg²,
  γ 0.1 centideg) and Peak List peaks below σ²/γ 0.001, or with a `null`
  entry (row 9, A86/A90); any refine flag in a simulation
  (`refinement_cycles` 1) (row 10, A88); a refined strict subset of a
  symmetry tie group or GSAS-II cell group, or a refined symmetry-fixed
  parameter (row 11, A95); a stated `Multiplicity` that differs from the
  derived one (row 12, A101); a non-canonical space-group spelling, origin
  choice 1, or one of the 9 settings GSAS-II cannot express (row 13, A105);
  `scale` < 0 or absent (row 14, A96); wavelength ≤ 0, crystallite size ≤ 0, a
  Peak List peak outside the fit window, and an SPF refine flag on the width
  source not in use (row 19, A126/A127); a `fit_range` holding no weighted
  point (row 24, A149).
- A run **fails with a message** when GSAS-II reads an atom's site with the
  wrong multiplicity or cannot name it while a coordinate/`Uaniso` is refined
  (row 17, A117), and when the refinement diverges (non-finite calculated
  pattern) (row 18, A130).

**topas**
- Native `topas.*` schemas (hand-derived fixtures in `tests/data/topas/native/`;
  A137): TOPAS's own keywords, macro parameters and units; a required
  `engine_version` checked against the gateway's declared support set and,
  at run time, against the installed version the user declares (A144, A145).
  Bounds replace TOPAS's default limits side by side (A138). Results report
  TOPAS's own statistics under `engine_details`, and the background column
  comes from a second background-only run (A152).

**easydiffraction**
- Native `easydiffraction.rietveld` schema (fixtures in
  `tests/data/easydiffraction/native/`): easydiffraction's own names and units,
  a stated `calculator` (`cryspy` | `crysfml`), per-atom refinement including
  anisotropic ADPs with CrysPy, physical limits as bounds (row 26, A157–A162,
  A169).

**Examples**
- Per-engine recipes for the two reference cases, `examples/<case>/topas/input.json`
  and `examples/<case>/easydiffraction/input.json` (LaB6, LaB6 single peak
  fitting, DRX_33), byte-for-byte copies of the native fixtures, each with a
  README; per-engine templates `examples/example_template/{topas,easydiffraction}/input.json`
  (P-02, P-20, provisional).

**Project**
- This `CHANGELOG.md` (A12/A16), the migration guide
  [`docs/migration-0.1-to-0.2.md`](docs/migration-0.1-to-0.2.md), and the
  new documentation pages: recipe schemas, fields and features (tables
  generated from the schemas by `scripts/gen_schema_field_tables.py`, P-27),
  input guidance, engine behaviour notes (from the engine-behaviour register,
  A79), cross-engine comparison (A173; `scripts/cross_engine_comparison.py`),
  support matrix (generated from `powderline.support_matrix()`), policies.
- The `powderline` console script (`[project.scripts]`), installed with the
  package (`pixi reinstall powderline`).

### Changed

- **Failures raise; results carry `status` and `converged`** (re/12). `powderline.run()`
  and every gateway raise `EngineExecutionError` (the engine ran and failed:
  `diverged`, `unusable_site`, `peak_fit_failed`, `engine_crashed`, `output_missing`,
  `output_malformed`) or the new `ExecutionBackendError` (the engine did not run:
  `server_unavailable`, `server_disabled`, `communication_failed`, `timeout`,
  `backend_error`), each with `.reason` and
  `.result` (the failed envelope, listing the files kept for diagnosis — since
  re/30 the engine's own files and `failure.json`, no result table). gsasii no longer returns `success: False` dicts (ledger R30).
  Every returned result has `status` (`"ok"`, or `"generated"` for a TOPAS run
  without a declared `tc.exe`, on which the CLI now exits 0), `converged`
  (`true`/`false`/`null`) and `envelope_version` (`"1"`, the GSAS-II server's wire
  contract); `success` is a deprecated always-`true` alias (removed later in this release, see Removed);
  the top-level `error` and `traceback` keys are **removed** -- a consumer
  reading `result["error"]` now gets `KeyError`. A timed-out server request is
  a `timeout` failure and no longer falls back in-process into the same output
  directory. `GSASClient.run_simulation` (unused) is removed. All five
  exception classes pickle (`ProcessPoolExecutor`).
- **GSAS-II server robustness** (re/14). Requests to `/simulate` run one at a
  time (a lock; GSAS-II's module state is not thread-safe); a malformed
  `POWDERLINE_SERVER_PORT` is refused before the lock and the GSAS-II import,
  a busy port fails the start before the import with the port named, and a
  client reports an auto-started server that exits at start (pointing at its
  log) or a malformed variable (`server_unavailable`); the server's unsigned 401
  and 413 refusals are reported as a rejected or too-large request rather than
  as an impostor listener; only `/simulate` may carry a large body before the
  HMAC check (4 KiB elsewhere); Windows sharing violations on the state files
  are retried then reported; `gsas-server status` says "starting" while
  GSAS-II loads and `logs` reads only the tail of the log.
- **TOPAS runs only from a declared location** (P-35): `--topas-dir` or
  `topas.dir` in `.powderline_config.yaml`. The former sweep of
  `C:/TOPAS8 … 5` and the `C:/TOPAS<version>` guess are gone, because TOPAS
  carries no readable version and a guessed directory could silently run a
  different TOPAS than the recipe's `engine_version` (A145). With no
  directory declared a run is generate-only and says so; a real run records
  the executable in `engine_details.tc_path`.

**Statistics and fit window (all engines)**
- **`rwp` means something different.** On a native run it is PowderLine's
  uniform Rwp over the fit window (zero-weight points excluded), not the
  engine's own value; GSAS-II's wR moves to `engine_details`. For LaB6 the two
  agree to the fourth decimal (6.5345 vs 6.5346); for a simulation GSAS-II
  reports its 100 % cap while the uniform Rwp compares the simulated pattern
  with the stated observation (row 16, A23/A125/A129/A131).
- **The fit window is exactly min ≤ 2θ ≤ max on the data points.** GSAS-II
  gets the first and last weighted points inside `fit_range` as its limits.
  With a maximum between data points v0.1.1 also fitted the next point above
  it, so `Nobs` drops by one and refined values move slightly (LaB6: scale
  5e-6 relative, U 7e-4, highest Chebyshev term 1 %); without a `fit_range`
  zero-weight edge points are no longer counted (row 23, A149/A150/A154).

**gsasii**
- **Size/strain left out** now means 10 µm / 0 microstrain, isotropic, fixed,
  with a structured warning — no sample broadening — instead of GSAS-II's own
  1 µm / 1000 microstrain (row 6, A87/A107/A119).
- **Background left out** now means one fixed Chebyshev term 0.0 (no
  background) instead of GSAS-II's constant 1.0 (row 7, D1/A119).
- **Space groups** must be gemmi's canonical extended Hermann–Mauguin name
  (`"P m -3 m"`, `"C 1 2/m 1"`, `"F d -3 m:2"`); the converter rewrites old
  symbols as GSAS-II read them (row 13, A105).
- **The LaB6 examples** (`example_LaB6`, `example_LaB6_simulation`) lose their
  single background peak at the example migration: its γ = 1e-5 is below
  GSAS-II's floor and no variant of it converges; the regression references
  lose the four `background_peak_0_*` rows (P-01, provisional).
- **The simulation recipe builder** (`simulation_builder.SimulationRecipeBuilder`;
  the `mp-simulate` tool that drove it was removed later in this release, see
  Removed) writes SH/L 0.002 (the gsasii floor) instead of 0.001 (P-05,
  provisional) and emits a `gsasii.rietveld` 0.1.0 recipe. Its structures are now reduced to the
  symmetry-unique sites (v0.1.1 handed GSAS-II every atom of the conventional
  cell, so a site was counted *multiplicity* times) and two-origin groups are
  moved to origin choice 2; the simulated grid includes `max_2theta` (row 31,
  P-17, provisional).
- **The regression references** under `examples/*/output/` were regenerated
  once, on the native path, after the legacy and native paths were shown to
  agree exactly on every example once the deliberate changes above are pinned
  (row 30). The four DRX_33 refinements now report `converged: false` after
  their five cycles (they always ran that way; now it is said).

**easydiffraction**
- **Native results differ from the v0.1.1 easydiffraction path**: data reach
  the engine at full precision; the instrument terms are the engine's own,
  derived correctly (polarization p = 1 − P, Lorentzian X/Y swapped, FCJ
  S/L = H/L = SH/L/2); the calculator is stated, not inferred from SH/L;
  easydiffraction is pinned at 0.21.1; anisotropic ADPs are used (CrysPy).
  LaB6 Rwp: v0.1.1 9.63 %, native 6.77 % (CrysFML) / 6.81 % (CrysPy)
  (row 26, A116/A158–A162/A169).

**Symmetry helpers (core)**
- `powderline.symmetry` (formerly `powderline.topas.symmetry`) raises
  `powderline.exceptions.SymmetryError` instead of `TopasTranslationError`
  (row 1, A56/A57/A61); `resolve_space_group` accepts rhombohedral `:R`
  (row 2, A62; the pre-refactor `cell_constraints` / `site_dof` / `adp_dof`
  that this row also covered were removed later in this release, see
  Removed); trigonal/hexagonal sites are classified
  correctly, so TOPAS-writer warnings for those groups change wording or
  appear/disappear (emitted INP values unchanged) (row 3, A74).
- **gemmi is pinned exactly** (`==0.7.5`); the locked version is unchanged
  (row 5, A110).

**Packaging**
- `powderline.topas` → `powderline.gateways.topas` and `powderline.easydiff` →
  `powderline.gateways.easydiffraction`, **no shims**; an existing checkout
  needs `pixi reinstall powderline` for the entry points (rows 22 and 25,
  A136).
- **pixi environments** (A31, A42; P-21, provisional): the **default
  environment is core-only** (schema layer, registry, the engine-free CLI; no
  engine). Engines live in named environments: `gsasii` (GSAS-II via
  pixi-build, the server), `easydiffraction` (renamed from
  `easydiff`; Python ≥ 3.12, no GSAS-II), `all` (every engine) and `dev` (all
  plus docs/test tooling). `pixi install -e gsasii` installs an engine;
  `pixi run -e gsasii kicker <recipe>` runs in it; engine-bound tasks
  (`gsas-server`, `ui`) live in their engine's feature, so
  pixi asks for `-e` when the task is ambiguous; `pixi run test` and
  `pixi run docs` resolve to `dev`. A `gsasii.*` recipe validates in the
  default environment but a run there raises `EngineNotAvailableError`
  naming the environment and the install command. After the re-lock, every
  environment needs its own editable install (`pixi reinstall powderline
  --all`; KI-13).

**Public API and CLI** (P-06, P-11–P-15, provisional)
- `powderline.__all__` is `run`, `validate`, `ValidationResult`,
  `load_recipe_asset`, `support_matrix`, and the exceptions `PowderLineError`,
  `GatewayNotInstalledError`, `EngineNotAvailableError`, `EngineVersionError`,
  `EngineExecutionError`. `import powderline` imports no engine.
- `run(recipe, output_dir, *, verbose=False, validate_only=False,
  **engine_options)` dispatches on the recipe's `schema_name`; engine options
  are the gateway's explicit keywords (gsasii `execution_mode`; topas
  `topas_dir`, `topas_version`; easydiffraction none), an unknown one is a
  `TypeError`. There is no `engine=` keyword.
- `validate(recipe, *, verbose=False)` is engine-free and returns a frozen
  `ValidationResult(recipe=<the gateway's validated model>, warnings=[...])`;
  an invalid recipe raises pydantic's `ValidationError` listing every problem
  at its field path.
- One CLI, `powderline <recipe.json> [--output DIR] [--validate-only]
  [--verbose] [--use-server | --no-server] [--topas-dir DIR]
  [--topas-version V]`, serving every schema; an engine flag given for a
  recipe of another engine exits 1; `--validate-only` writes nothing. The
  pixi task `kicker` runs the same `main`.
- `GSASClient` lives at `powderline.gateways.gsasii.client`; the GSAS-II
  `run` body is `powderline.gateways.gsasii.gateway.run`.
- **The schema layer is assembled from core building blocks** (P-37, review
  finding 13): the ~230 lines the three `schema.py` modules had each written
  for themselves are now public functions of `powderline.schema_core`
  (`EngineRecipe`, `recipe_validator`, `refined_flags`, `custom_error` /
  `raise_problems`, `omit_absent`, `absent_not_null`, `unique_phase_names`,
  `fit_window`, `fit_range_problems`, `outside_window_problems`,
  `refined_flag_problems`, `unit_schema`) and
  `powderline.compat.schema_declarations`. Nothing a recipe author sees
  changes: the generated field tables, every example's validate-only output
  and the invalid-recipe error lists (type, location, message) are
  byte-identical; the unused `json_schema()` helpers of the topas and
  easydiffraction schema modules are gone (`Model.model_json_schema()` is the
  route). `powderline.exceptions.WARNING_CODES` registers every
  structured-warning code with its owner and level; a test holds it, the
  codes emitted under `src/` and the engine-behaviour table in agreement.

- **The GSAS-II server tells you when it is stale** (re/17, review finding 5):
  `/health` reports the PowderLine version and an MD5 of the source tree the
  server loaded; the client compares both with its own and refuses a
  mismatching server — `auto` mode says so and runs in-process, `--use-server`
  fails with `server_unavailable` naming `gsas-server restart`, `gsas-server
  status` prints `Code: STALE`. No new reason code.
- **Frozen GSAS-II modules, housekeeping through the ledger** (P-38, rows
  R31–R32): the dead `.lst` parameter extractor and the unused imports the
  verbatim move carried along are gone; the code hash is regenerated; the
  baseline wording in policies, DEVELOPMENT and CLAUDE.md names the verified
  re/01 commit `daace24`. Nothing the modules do to the project dictionary
  changes.

- **The GSAS-II server needs no shared filesystem** (KI-12, re/19, P-42):
  each job runs in a private scratch directory under the server's state dir
  and its output files come back base64-encoded inside the signed response;
  the client writes them into its own `output_dir` (bare names only, size
  cap, atomic replace) and lists them in `output_files`. The request no
  longer carries `output_dir`; a client that cannot write its directory fails
  with `backend_error`, a malformed or oversized transfer with
  `communication_failed`. A server on another node or in a container now
  works like a local one.

### Removed

- **The Materials Project simulation tool** (`mp-simulate`, `mp_simulate.py`,
  `pattern_exporter.py`, `mp_interface.py`, the `materials_project` config
  block, `docs/mp-simulation.md`) (P-36). It was part of how RandomXRD was set
  up; RandomXRD vendors its own PowderLine snapshot and keeps its copy. Its
  `.chi` export was not a Fit2D CHI file and carried an unannounced
  background. What stays: `simulation_builder.SimulationRecipeBuilder`
  (`build_recipe_from_structure`, was `build_recipe_from_mp_structure`) and the
  `simulation_defaults` config block. `mp-api` / `emmet-core` leave the `gsasii`
  pixi feature at the next re-lock.
- **The unified 0.26.0 schema** (`schema_name` `GSASII_Rietveld` /
  `GSASII_SPF`, `schema_version`) and the cross-engine translation layer
  (`powderline.schema`, the legacy GSAS-II executor, the TOPAS writer /
  round-trip / `topas-kicker`, the easydiffraction builder / policy): a 0.26.0
  recipe is no longer accepted by any engine (A4, A14; row 32). From
  `powderline.validate()`, `powderline.run()` and the CLI it fails at
  `schema_name` with "does not name an engine: expected `<engine>.<workflow>`";
  the message names the expected form, not the converter — the
  [migration guide](docs/migration-0.1-to-0.2.md) does.
- `refinement_controls.refinement_algorithm` (v0.1.1 accepted and ignored it)
  and the `null`-valued `broadening` / `corrections` / phase
  `parameterization` forms that crashed v0.1.1 at run time: the gsasii
  instrument and phase blocks are explicit (row 15, D17/A92/A99).
- Parameter bounds in gsasii recipes: gsasii 0.1.0 exposes none (GSAS-II
  clamps after the fit); a 4-element list is a validation error and the
  converter reports every bound it drops (A84).
- `payload.asset_path` (not a gateway input, A50) and the second GSAS-II
  instrument-parameter dict `Iparm2` (never used) — both dropped by the
  converter.
- The legacy TOPAS 7.25 goldens `examples/*/output/topas/` (P-02,
  provisional; TOPAS 6 goldens live in `tests/data/topas/native/golden/`).
- From the public namespace (P-06, row 32): the `engine=` argument of
  `run()` (the recipe names its engine); `validate_simulation_mode_parameters`
  (the rule is in the gsasii schema: a refine flag in a one-cycle recipe is a
  validation error); `RecipeModel` and `powderline.schema` (the gateways'
  models come back from `validate().recipe`); `GSASClient` (now
  `powderline.gateways.gsasii.client.GSASClient`); the `powderline.engine`
  dispatcher module; the re/01 shims `powderline.constraints`,
  `powderline.gsas_client`, `powderline.gsas_server` (import
  `powderline.gateways.gsasii.{constraints,client,server}`); the
  `topas-kicker` console script and pixi task (the one CLI serves `topas.*`
  recipes).
- The `easydiff` pixi environment name (now `easydiffraction`) and GSAS-II
  from the default environment (now the `gsasii` environment).

- **Code only tests called** (re/17, review finding 14): the legacy TOPAS
  conversion/equation helpers (`topas/conversions.py`; `fmt` lives in
  `native_writer`), `topas/runner.run_topas` and `RunResult` (production runs
  TOPAS through `native_run.run_tc`), the two unused `errors.py` exception
  modules, and the pre-refactor `symmetry` API (`cell_constraints`,
  `site_dof`, `adp_dof`, `check_uij`); their tests with them.
- **Three unused dependencies**: `h5py`, `pybaselines`, `xmltodict` leave
  `pyproject.toml` and the pixi manifest.

- **The `success` key** of results and of the validate-only summary (it was
  an always-`true` alias of `status`, announced for removal in 0.3.0; removed
  now since 0.2.0 is the first release with `status`). **The reason code
  `output_not_visible`** and the fit-profile freshness check it belonged to:
  the server's files travel in-band (KI-12).

### Fixed

- `powderline.symmetry` finds the monoclinic unique axis of the mirror-only
  groups Pm, Pc, Cm, Cc (space groups 6–9) in every setting (today through
  `cell_tie_groups`; before, all 41 settings failed with "could not determine
  the monoclinic unique axis") (row 4, A102).
- Site-symmetry classification for trigonal and hexagonal groups (the
  column-only test was wrong when rotations are not orthogonal in fractional
  coordinates; checked against GSAS-II for all 230 groups) (row 3, A74).
- A gsasii run no longer computes 4× the intensity silently for some 2-fold
  sites in R32, R-3m, R-3c, nor crashes with a `KeyError` on a site GSAS-II
  cannot name: both are errors naming an equivalent position to state
  (row 17, A117, EB-40/EB-05).
- A diverged gsasii refinement no longer returns success with Rwp 100 % and a
  NaN profile (row 18, A130).
- The v0.1.1 easydiffraction path's unit conversions (polarization sign,
  Lorentzian X/Y, FCJ S/L and H/L) and its 4-decimal 2θ rounding (row 26,
  EB-72/EB-75/EB-76).
- Recipe files are read as UTF-8 (BOM tolerated); malformed JSON/YAML or a
  non-mapping document is a `ValueError` naming the file, and the CLI reports
  it as "Cannot read recipe" instead of a traceback. `--verbose` prints the
  traceback of an unexpected error.
- `.powderline_config.yaml` is read as UTF-8; a malformed file is an error
  (previously: defaults / "TOPAS not configured" silently).
- Documentation corrected to the code: TOPAS 6 (not v7), no default engine,
  nothing translated between engines; a fit window needs two weighted points;
  a gsasii simulation writes no `refined_parameters.csv`; example commands
  name the `gsasii` env; the getting-started recipe validates (and is tested).

- CI runs `scripts/gen_schema_field_tables.py --check` (pixi task
  `fields-check`) in the core job, so a schema edit without regenerated field
  tables fails; `probes/` is ignored; one unused test fixture removed (re/17).
  The check prints one line on success naming what it compared (the file
  count and the schema versions), so a smoke test or a CI log can tell a
  pass from a no-op (re/29).

### Known limitations carried into 0.2.0

- **TOPAS 7** is out of scope: `topas.*` 0.1.0 supports TOPAS 6 only (P-07,
  A143).

## 0.1.2 — 2026-10-10

Tagged on `main` after the refactor branch was cut; merged into the 0.2.0
branch on 2026-10-14 (the server and client live at
`src/powderline/gateways/gsasii/server.py` / `client.py` there; the
known-issue entry is `KI-14` on 0.2.0 because `KI-13` was already taken).
<!-- git: b38c73e, tag v0.1.2 -->

### Fixed
- GSAS-II server made per-user and token-authenticated: per-user state
  directory, loopback bind on an ephemeral port, bearer token on every route,
  `POWDERLINE_NO_SERVER` to disable the server (#10).

## 0.1.1 — 2026-09-24

The pre-refactor baseline (A16); unified recipe schema 0.26.0.
<!-- git: fb90228, tag v0.1.1; 43 commits since v0.1.0 -->

### Added
- easydiffraction engine (`engine="easydiffraction"`, optional `easydiff` pixi
  environment) with the SH/L → Thompson-Cox-Hastings/FCJ profile mapping (#2).
- Documentation published on GitHub Pages (#4–#7).

### Fixed
- GSAS-II's refinement failure message is surfaced instead of a silent
  no-Rwp result; `run()` normalisation no longer crashes on null tables from
  server failure responses (#3).

## 0.1.0 — 2026-08-17

Initial public release.
