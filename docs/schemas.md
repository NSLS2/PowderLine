# Recipe schemas

A PowderLine recipe is a JSON document that names **one engine and one
workflow** in its `schema_name` and is written in that engine's own
conventions, names and units. There is no translation between engines: a
`topas.*` recipe holds what goes into the TOPAS input file, an
`easydiffraction.*` recipe holds easydiffraction's own parameters, a
`gsasii.*` recipe holds GSAS-II's. The structural part (space group, unit cell,
atoms) is the same in every engine, so it can be moved between recipes; the
instrument, background and controls are the engine's.

Every recipe states two schema versions, and PowderLine **declares** which
versions it accepts (see [the support matrix](support-matrix.md)):

| Key | Meaning | Today |
|---|---|---|
| `schema_name` | `<engine>.<workflow>` | one of the five below |
| `core_schema_version` | the shared top level and structural models (`xrd_data`, `fit_range`, the phase block, parameter lists, `metadata`) | `"0.1.0"` |
| `engine_schema_version` | that engine's payload (instrument, background, controls, engine-specific phase fields) | `"0.1.0"` for every engine |

Validation never needs an engine: `powderline <recipe> --validate-only` (or
`powderline.validate(recipe)`) works in the core-only default environment for
every schema. A **run** needs the engine's environment, named in the table.

## The five schemas

| `schema_name` | Engine (supported version) | Workflow | Parameter shape | Run in | Template |
|---|---|---|---|---|---|
| `gsasii.rietveld` | GSAS-II 5.7.9 | Rietveld refinement, one or more phases | `[value, refine_flag]` (no bounds) | `pixi run -e gsasii kicker <recipe>` | `examples/example_template/input.json` |
| `gsasii.spf` | GSAS-II 5.7.9 | single peak fitting (GSAS-II Peak List), no phases | `[value, refine_flag]` | `pixi run -e gsasii kicker <recipe>` | derive from `examples/example_LaB6_singlepeakfit/input.json` |
| `topas.rietveld` | TOPAS 6 (`engine_version: "6"`) | Rietveld refinement | `[value, refine_flag, min, max]` | `pixi run kicker <recipe> --topas-version 6` on a Windows machine with `tc.exe` | `examples/example_template/topas/input.json` |
| `topas.spf` | TOPAS 6 | single peak fitting (`xo_Is` peaks), no phases | `[value, refine_flag, min, max]` | as above | derive from `examples/example_LaB6_singlepeakfit/topas/input.json` |
| `easydiffraction.rietveld` | easydiffraction 0.21.1 | Rietveld refinement; calculator `cryspy` or `crysfml` | `[value, refine_flag, min, max]` | `pixi run -e easydiffraction kicker <recipe>` | `examples/example_template/easydiffraction/input.json` |

easydiffraction has no single-peak-fitting workflow. The templates are
fill-in-the-blanks skeletons that the CLI refuses to run (`template` in the
path): copy one into your own directory, fill the blanks (data arrays,
wavelength, element symbols), and validate the copy.

Field-by-field tables, with units, are on the [fields page](fields.md); how to
fill the blocks is on the [input guidance page](input-guidance.md); what each
engine does with them is on the [engine behaviour page](engine-behavior.md).
The schema changelog is [SCHEMA_HISTORY](SCHEMA_HISTORY.md).

## Minimum inputs

Every recipe has the frame `schema_name`, `core_schema_version`,
`engine_schema_version`, an optional free-form `metadata` block (echoed into
results, never read; at most 1 MiB), and `payload`. Unknown keys are errors
at every level. Inside `payload`:

### `gsasii.rietveld`

Required: `xrd_data` (`tth`, `Itth`, `Itth_weights`), `instrument` with all
four blocks (`radiation {type: "PXC", wavelength}`, `geometry {bank, azimuth}`,
`corrections {zero_shift, polarization, axial_divergence}`,
`broadening {U, V, W, X, Y, Z}`), at least one phase in `phases` (each with
`space_group`, `unit_cell`, `atoms` and `scale`), and `refinement_controls`
(`refinement_cycles`, default 5; `1` is a simulation in which nothing may be
refined). Optional: `fit_range`, `background` (left out: no background),
`peak_broadening` per phase (left out: 10 µm / 0 microstrain, fixed, with a
warning), `scattering_types` per phase (`{<atom label>: "La3+"}`, CIF spelling;
left out: neutral atoms; only ions GSAS-II 5.7.9 has a form factor for),
`preferred_orientation` per phase (March–Dollase: `{model: "march_dollase",
hkl: [h, k, l], ratio: [r, flag]}`, `hkl` integers not all zero, `r > 0`;
GSAS-II's convention, 1 random, < 1 platy, > 1 needle, averaged over the
axis's equivalents; left out: none), `instrument.description`.

### `gsasii.spf`

Required: `xrd_data`, `instrument` (as above), `single_peaks` (four lists of
the same length: `positions`, `intensities`, `pv_gaussian_sigma_sq`,
`pv_lorentzian_gamma`) and `refinement_controls` with
`single_peak_fitting_mode.use_instrument_profile`. No `phases`. Optional:
`fit_range`, `background`.

### `topas.rietveld`

Required at the top level: `engine_version` (`"6"`). In the payload:
`xrd_data`, `instrument` with `radiation` (`ymin_on_ymax`, `la`, `lo`, `lh`)
and `broadening` (`peak_type` and exactly that peak type's `parameters`),
at least one phase (`space_group`, `unit_cell`, `atoms`, `scale`), and
`refinement_controls` with every control stated (`iters`,
`chi2_convergence_criteria`, `x_calculation_step`; `iters: 0` is a
simulation). Nothing has a default: `fit_range`, `background`,
`instrument.corrections`, `instrument.geometry` and the phases'
`peak_broadening` are optional, and a block left out is **not modelled**.
`scattering_types` (ionic types, CIF spelling, written to TOPAS's `occ` as
`La+3`; only ions in TOPAS 6's `ATMSCAT.CPP`) and `preferred_orientation`
(March–Dollase, TOPAS's `PO` macro; a `null` bound keeps TOPAS's limit, min
0.0001, max 2r + 0.5) are optional phase fields. With `TCHZ_Peak_Type` the
total (Thompson–Cox–Hastings) peak width must be positive everywhere in the
fit window at the starting values; a negative Lorentzian part X·tanθ + Y/cosθ
is allowed while it is.

### `topas.spf`

As `topas.rietveld`, with `single_peaks` (a list of peaks, each `xo`, `I`
and optionally `gauss_fwhm`, `lor_fwhm`) instead of `phases`.

### `easydiffraction.rietveld`

Required: `xrd_data`, `instrument` with `radiation {setup_wavelength}`,
`corrections {calib_twotheta_offset}` and `broadening` (`peak_type` and its
`parameters`), at least one phase (`space_group`, `unit_cell`, `atoms`,
`scale`), and `refinement_controls` with every control stated
(`calculator`, `minimizer`, `max_iterations`, `chi_square_change_tolerance`,
`parameter_change_tolerance`, `gradient_tolerance`). A recipe with no refine
flag set is a simulation. Optional: `fit_range`, `background`,
`instrument.polarization`, `instrument.absorption`, a Kα2 line in
`radiation`, `scattering_types` per phase (cryspy calculator only, CIF
spelling, ions CrysPy has a form factor for), `preferred_orientation`
per phase (March–Dollase as in gsasii with a bounded `ratio` plus the
required `march_random_fract: [f, flag, min, max]` in [0, 1]; cryspy
calculator only — CrysFML ignores it, EB-97); left out means not
modelled.

## Outputs

### The result dict (`powderline.run()`)

Every engine returns the same keys. Tables are pandas DataFrames; per-phase
tables are dicts keyed by phase name.

| Key | Meaning |
|---|---|
| `status`, `converged`, `envelope_version` | outcome: `status` is `"ok"` or `"generated"` (a TOPAS run whose input was written but no `tc.exe` is declared); **a failed run never returns** — it raises `EngineExecutionError` (the engine ran and failed) or `ExecutionBackendError` (it did not run), each with `.reason` (table below) and `.result`, the failed envelope: `failure = {kind, reason, message, traceback, engine_details, console_tail (gsasii)}` plus `output_files` (the files kept for diagnosis: the engine's own files written so far and `failure.json`, the envelope written to the output directory with a `powderline_provenance` block naming the recipe, the engine and its version, and PowderLine's version; no PowderLine result table exists for a failed run), `warnings`, `run_id`, `method`, `elapsed_time`. `converged` is `true` / `false` / `null` (`null`: the engine cannot report it — TOPAS 6 — or nothing was refined). `envelope_version` is `"1"`: it names the shape of this Python-facing envelope (the GSAS-II client/server wire form is internal and version-locked by the stale-server check). There is no `success` key; the pre-0.2.0 `error` / `traceback` keys are gone |
| `run_id` | UUID4 of this run |
| `rwp`, `r_exp`, `gof`, `chi2_red` | PowderLine's **uniform** statistics over the fit window (percent / dimensionless); `None` where undefined |
| `simulation_mode` | `true` when nothing was refined |
| `engine_details` | the engine's own statistics and counts (gsasii, verbose run: also `console_tail`, the engine's console text): `parameters_requested` (from the recipe), `parameters_varied` (what the engine varied), `n_points`, the engine's own Rwp/GoF, and per engine `converged` (gsasii Rietveld), `calculator` / `peak_type` (easydiffraction), `tc_path` (topas: the executable that ran), `engine_version` |
| `warnings` | structured warnings `{code, message, field_path[, level]}` from validation and from the run; `level` is `"warning"` (absent means this) or `"info"` (a record of something PowderLine did that changes no outcome, e.g. `symmetry_value_derived`) |
| `elapsed_time`, `method` | wall-clock seconds; which execution path ran (`server` / `subprocess` for gsasii; `topas`, `easydiffraction`, or their `_simulation` variants) |
| `output_files` | paths written to the output directory |
| `output_recipe`, `output_recipe_valid` | **the next step's input** (KI-04): a complete recipe of the same `schema_name`, *resolved* — refined values written back at their recipe paths, symmetry-derived values in their exact (held) form, gateway defaults stated, the user's flags, bounds, controls and data unchanged, plus the one metadata key PowderLine writes, `metadata.powderline_provenance` (`parent_run_id`, `schema_name`, `engine`, `engine_version` — the version the run used, as `engine_details.engine_version` states it; TOPAS: the declared one; `null` for validate-only — `powderline_version`, `created`). Core propagates every symmetry tie group and checks that every atom keeps its multiplicity. `output_recipe_valid` says whether it re-validates as written; when it does not (an engine returned a value the schema refuses, a tie came back inconsistent) the recipe is still returned and written and the warning `output_recipe_not_valid` lists why. The validate-only summary carries the resolved recipe too |
| `parameter_dispositions` | one row per refinable leaf: `path, value, esd, disposition, at_limit`; `disposition` is `default_applied`, `held_by_symmetry`, `held_by_user`, `requested_not_varied` or `varied` (first that applies); `at_limit` marks a value that ended on a stated bound or an engine default limit |
| `fit_profile` | `two_theta, y_obs, y_weights, y_calc, y_diff, y_bkg, q_values, d_spacings` |
| `unit_cell_data` | per phase: `parameter, value, esd`, seven rows in the **report vocabulary** `cell_a, cell_b, cell_c, cell_alpha, cell_beta, cell_gamma, cell_volume` (see below) |
| `peak_list_data` | per phase: reflection list (`h, k, l, …, d_spacing, 2theta, …`; columns are the engine's) |
| `refined_parameters` | 9 columns: `parameter_name, descriptive_name, phase_name, phase_idx, atom_name, atom_idx, value, esd, category` |
| `spf_peaks`, `spf_convergence_diagnostics` | single peak fitting only (empty otherwise; the gsasii and topas column sets differ) |
| `peak_fit` | `gsasii.spf` only (`None` otherwise): `{"parameters": [{"name", "value", "esd"}]}`, every parameter GSAS-II's peak fit varied by GSAS-II's own name (`Back;0`, `BkPkpos;0`, `U` … `Z`, `pos3`, `int3` …) with its ESD — the source of the output recipe for a peak fit, whose fit fills no covariance block |

**The failure record** (`e.result["failure"]`, the GSAS-II server's envelope
alike): `kind` (`engine` / `backend`), `reason` (the table below), `message`,
`traceback`, `engine_details`, and for `gsasii.*` runs `console_tail` — the
last 64 KiB of what GSAS-II printed during the run (KI-05), `None`
when it printed nothing.

**Two vocabularies, one bridge**. The unit-cell report speaks the
*spreadsheet* vocabulary: its rows are `cell_a … cell_gamma, cell_volume`, the
same for every engine (`powderline.reports.UNIT_CELL_ROWS`; the writer refuses
any other row), so a row stays self-describing when tables are concatenated.
The same quantities appear in `output_recipe` and `parameter_dispositions` under
their *recipe* paths, `payload.phases.<name>.unit_cell.a`; `reports.UNIT_CELL_ROW_OF`
/ `UNIT_CELL_MEMBER_OF` convert between the two, and are the only non-frozen
places that do (gsasii's frozen extractor spells the same rows itself; a core
test holds the two lists equal). The ESD rule is the same for every engine: the engine's ESD for a refined
member; `0.0` for a member fixed by symmetry or held by the user; an empty field
when the engine refined the member but reported no ESD; the volume's ESD when
the engine propagates one (gsasii, topas), `0.0` for a cell with nothing refined,
else empty (easydiffraction). gsasii follows it in every mode: held cell →
`0.0` (`example_LaB6`), refined → propagated (`example_DRX_33`), a simulation
(nothing refined, no covariance) → `0.0` everywhere (`example_LaB6_simulation`;
since 0.2.0, through a recorded edit to the frozen GSAS-II code — before it a
simulation left every ESD field empty).
`refined_parameters.csv`, by contrast, deliberately
speaks the **engine's** names (`0::A0`, `broad_gauss_u`, `p1_cell_a`): it is the
engine's own table, with `descriptive_name`, `phase_name` and `atom_name` beside
each name; the recipe-path view of the same values is `parameter_dispositions`.

**Reason codes** (`powderline.results.REASONS`; `e.reason` on the exception,
`failure.reason` in the envelope):

| Reason | Kind | Meaning |
|---|---|---|
| `diverged` | engine | a non-finite calculated pattern or value inside the fit window, or a GSAS-II refinement GSAS-II itself aborted — no damped step lowered χ² (`Rvals['Aborted']`, EB-99; simulations exempt) |
| `unusable_site` | engine | the engine reads an atom's site or a symmetry tie differently from core (gsasii EB-40, EB-05; easydiffraction EB-47); the run stops before refining |
| `peak_fit_failed` | engine | GSAS-II's peak fit returned nothing (EB-38) |
| `engine_crashed` | engine | the engine raised or exited abnormally (GSAS-II crash, lmfit/CrysPy/CrysFML error, `tc.exe` could not start) |
| `output_missing` | engine | TOPAS wrote none of its expected files |
| `output_malformed` | engine | an engine file could not be read strictly (non-numeric token, ragged row, missing points, pattern on other 2θ) |
| `server_unavailable` | backend | server mode: no GSAS-II server and none could be started |
| `server_disabled` | backend | `POWDERLINE_NO_SERVER` with `execution_mode='server'` |
| `communication_failed` | backend | an HTTP/transport error after a server was found |
| `timeout` | backend | GSAS-II server mode: the server's answer outlived `server_timeout` / `--server-timeout` (no limit unless one is set); **no in-process fallback** (the job is still running on the server; a second run would double the work). TOPAS: `tc.exe` outlived `topas_timeout` (default 3600 s) and was stopped (the background-only run stopped at the limit is not a failure: `y_bkg` empty with `topas_background_not_calculated`) |
| `backend_error` | backend | anything else on the execution path before the engine ran (e.g. a recipe the server could not validate) |

With `validate_only=True` the result is a slim summary with the same keys on
every gateway: `status` (`"validated"`), `rwp` (`None`), `elapsed_time` (`0.0`), `method`
(`"validate_only"`), `schema_name`, `core_schema_version`,
`engine_schema_version`, `phases`, `simulation_mode`, `parameters_requested`,
`warnings`, and `engine` — a dict of the engine's own controls
(`refinement_cycles` for gsasii; `iters` and `engine_version` for topas;
`calculator` for easydiffraction). Nothing is written.

### Standardized report files

Written by every engine into the output directory, with fixed names:
`refined_parameters.csv`, `<phase>_unit_cell_report.csv`,
`<phase>_peak_list_report.csv` (not with the CrysFML calculator, which reports
no reflection list), `fit_profile.txt`, and `output_recipe.json` and
`parameter_dispositions.csv` (the output recipe and how each value came about;
the recipe repeats the data arrays, so it is about the size of the input).
`powderline.run()` removes these fixed-name files (and `failure.json`) from
the directory before every run and never the engine's own files, so a reused
directory holds one run's results; a failed run writes none of them and
leaves `failure.json` beside the engine's files. Single peak fitting adds a peak report
(`single_peaks_report.txt` for gsasii, `single_peaks_report.csv` for topas;
gsasii also writes `peak_convergence_diagnostics.txt` when a peak did not
converge).

### Native artifacts

Kept alongside the standardized reports, always:

- **gsasii**: `dummy.gpx` (the GSAS-II project, reopenable in the GUI) and
  `dummy.lst` (GSAS-II's refinement log with its own Rwp and parameter
  tables; the regression suite reads it).
- **topas**: `<base>.inp` and `<base>.xye` (what TOPAS was given), and what
  TOPAS wrote: `<base>_results.csv`, `<base>_profile.txt`,
  `<base>_p<n>_peaks.txt` per phase, plus the background-only run
  `<base>_bkg.inp` / `<base>_bkg_profile.txt` that provides the `y_bkg`
  column (TOPAS 6 cannot output the fit's background). `<base>` is the
  example directory's name when the output directory is `.../<name>/output`,
  else `topas`. Without `tc.exe` a run writes the `.inp` and `.xye` only and
  returns with `status: "generated"` (a normal outcome, exit 0).
- **easydiffraction**: none beyond the standardized reports; the data and
  structure are handed to the library in memory.
