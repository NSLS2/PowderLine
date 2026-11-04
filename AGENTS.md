# AGENTS.md — PowderLine

Guidance for coding agents (and a quick orientation for human contributors).
Tool-specific files (`CLAUDE.md`) only point here.

Automated powder X-ray diffraction refinement driven from a JSON "recipe".
PowderLine is the application layer over interchangeable refinement engines:
a recipe names **one engine and one workflow** in its `schema_name`
(`gsasii.rietveld`, `gsasii.spf`, `topas.rietveld`, `topas.spf`,
`easydiffraction.rietveld`), is written in that engine's own conventions and
units, and `powderline.run()` / the `powderline` CLI hand it to that engine's
**gateway** and return standardized tables with uniform fit statistics.
Nothing is translated between engines. Example-driven: real refinement cases
drive schema evolution and are the regression references.

**Authoritative sources for a change:** `docs/policies.md` (versioning,
deliberate changes, frozen code, engine pins, review, "ask, don't
assume"), `docs/SCHEMA_HISTORY.md` (schema facts), `docs/engine-behavior.md`
(what the engines do and PowderLine's policy), `docs/known_issues.md`
(`KI-NN`). Maintainers who work with the private design records (the devkit)
also follow the devkit's own agent guidance. **If a decision is not written down,
stop and ask the maintainer; do not infer it from the code or from another
engine.**

## Architecture (`src/powderline/`)

Core (engine-free; `import powderline` imports no engine):
- `__init__.py` — the public API, `__all__`: `run`, `validate`, `ValidationResult`,
  `load_recipe_asset`, `support_matrix`, `PowderLineError`,
  `GatewayNotInstalledError`, `EngineNotAvailableError`, `EngineVersionError`,
  `EngineExecutionError`, `ExecutionBackendError`.
- `api.py` — `validate(recipe)` → `ValidationResult(recipe=<gateway model>,
  warnings=[...])` through the gateway's engine-free schema layer;
  `run(recipe, output_dir, *, verbose, validate_only, **engine_options)`
  dispatches on `schema_name` (`<engine>.<workflow>` → `registry.get(engine)`);
  engine options are the gateway's explicit keywords (gsasii `execution_mode`;
  topas `topas_dir`, `topas_version`, `topas_timeout`); `allow_unsupported_engine_version` is
  refused (test-only, on the gateway's own `run`).
- `kicker.py` — the one CLI: `powderline <recipe.json> [--output DIR]
  [--validate-only] [--verbose] [--use-server|--no-server] [--topas-dir DIR]
  [--topas-version V] [--topas-timeout SECONDS]` and `powderline --doctor` (`doctor.py`: gateways,
  engine versions vs pins, server state; non-zero on a stale install, KI-13);
  `pixi run kicker` / `pixi run doctor` run the same `main`. Refuses
  templates; an engine flag for another engine's recipe exits 1.
- `registry.py` — gateways from the `powderline.gateways` entry-point group
  (lazy `ep.load`), the frozen `Gateway` dataclass (`name`, `capabilities`,
  `validate`, `run`), `register_gateway` escape hatch, `check_engine_version`.
  Entry points only; no in-code fallback (KI-13).
- `schema_core.py` — core schema **0.1.0**: `CoreRecipe` frame
  (`schema_name`, `core_schema_version`, `engine_schema_version`, `metadata`
  ≤ 1 MiB, `payload`), `RefinableParameter` `[value, flag]` /
  `BoundedRefinableParameter` `[value, flag, min, max]`, `XRDData`, `FitRange`,
  `ChebyshevBackground`, the phase block `Phase[P]` (`space_group` canonical
  gemmi name, `unit_cell`, `atoms`; every symmetry rule: cell check, special
  positions, tie groups and flags, derived values held exactly), `CoreName`,
  `collect_warnings`, `parameters_requested`, `fit_limits_on_data`, and the
  engine schema building blocks (`EngineRecipe`, `recipe_validator`,
  `refined_flags`, `custom_error`/`raise_problems`, `omit_absent`,
  `absent_not_null`, `unique_phase_names`, `fit_window`, `fit_range_problems`,
  `outside_window_problems`, `refined_flag_problems`, `unit_schema`) every
  gateway schema is composed from. Every
  model `extra='forbid'`; units in `json_schema_extra={"unit": ...}`.
- `symmetry.py` (gemmi), `compat.py` (declared schema compatibility,
  `support_matrix()`), `fitstats.py` (uniform Rwp/Rexp/GoF/χ²_red), `reports.py`
  (standardized report writers), `recipes.py`, `exceptions.py` (also
  `WARNING_CODES`: every warning code with owner and level, asserted against
  `src/` and the engine-behaviour table),
  `config_loader.py` (simulation defaults), `_status.py`.
- `results.py` — the run-result envelope (`ENVELOPE_VERSION`, `REASONS`, the
  failed/generated envelopes, `raise_if_failed`); `roundtrip.py` — the output
  recipe (`output_recipe`, `output_recipe_valid`, `parameter_dispositions`;
  tie propagation, KI-04); `doctor.py` — the `--doctor` report (KI-13).

Gateways (`src/powderline/gateways/<engine>/`), each a **schema layer**
(`schema.py`: the engine schema 0.1.0 on core 0.1.0, `DECLARATIONS`,
`SCHEMA_NAMES`, `validate_recipe`; imports no engine) plus a **runtime
layer** (`gateway.py` factory `get_gateway()` with `capabilities()`,
`validate()`, `run()`, `ENGINE_VERSION_SPEC`, `ENV`/`INSTALL_COMMAND`; engine
imported lazily from `run()`):
- `gsasii/` (GSAS-II `==5.7.9`, env `gsasii`): the **frozen** setup/execution
  code `helpers.py`, `project.py`, `setters.py`, `executors.py`,
  `extractors.py`, `constraints.py` (moved verbatim from `kicker.py` at the
  verified baseline `daace24`; code-hashed); non-frozen `routing.py`, `fit_report.py`
  (uniform statistics, `engine_details`, convergence, divergence = failure),
  `sites.py` (GSAS-II's reading of each site vs core's), `report_rows.py`,
  `paths.py` (GSAS-II parameter names → recipe paths for the output recipe),
  `console.py` (the engine's console tail into a failed envelope, KI-05),
  `scattering.py` (GSAS-II's ion table, `La3+` → `La+3`);
  `server.py` / `client.py` (persistent FastAPI server + `GSASClient`, the
  `auto`/`server` execution modes; per-user state dir, token-signed requests
  and responses, `POWDERLINE_NO_SERVER=1` disables it — v0.1.2, KI-14; output files travel
  back inside the response, no shared filesystem — KI-12); `simulation_builder.py`
  (a crystal-structure dict → a `gsasii.rietveld` simulation recipe; the Materials Project
  fetch/export tool that used it left PowderLine in 0.2.0; RandomXRD carries its own).
- `topas/` (TOPAS 6; recipes state `engine_version: "6"`, runs need the
  installed version declared): `native_writer.py` (model → INP + `.xye`;
  limits on data points; `= p/q;` constants), `native_run.py` (run `tc.exe`,
  strict file reads, the background-only second run, result), `peak_list.py`,
  `runner.py`, `scattering.py` (TOPAS 6's ion table, `La3+` → `occ La+3`).
  No Python engine: generate-only
  without `tc.exe`.
- `easydiffraction/` (`==0.21.1`, env `easydiffraction`, Python ≥ 3.12):
  `native_builder.py`, `native_run.py`, `space_group_table.py`,
  `space_group_support.py` (per-calculator verified settings), `scattering.py`
  (CrysPy's ion table).

Docs: `docs/schemas.md`, `docs/fields.md` (generated tables), `docs/input-guidance.md`,
`docs/engine-behavior.md`, `docs/policies.md`, `docs/migration-0.1-to-0.2.md`,
`docs/support-matrix.md`, `docs/cross-engine-comparison.md`, `docs/DEVELOPMENT.md`
("Adding a refinement engine"). Scripts: `scripts/gen_schema_field_tables.py`
(field tables + support matrix → `docs/_generated/`), `scripts/cross_engine_comparison.py`,
`scripts/convert_recipe_026.py` (0.26.0 → `gsasii.*` migration tool;
fixtures `tests/data/convert_026/`), `scripts/update_code_hash.py`.

## Key commands (pixi)

Environments: `default` = core only (validate anything, run nothing);
`gsasii`, `easydiffraction`, `all` (both engines), `dev` (all + docs/test
tooling). `pixi install -e <env>`.
- `pixi run kicker <recipe.json> --validate-only` — any env; engine-free.
- `pixi run -e gsasii kicker <recipe.json>` — run a `gsasii.*` recipe
  (`--use-server`/`--no-server`, `--output DIR`, `--verbose`);
  `pixi run -e easydiffraction kicker <recipe.json>` for `easydiffraction.*`;
  `pixi run kicker <recipe.json> --topas-version 6 [--topas-dir DIR]
  [--topas-timeout SECONDS]` for `topas.*` (runs `tc.exe` on Windows; when no
  `tc.exe` is found the run is generate-only: the INP and `.xye` are written,
  the result has status `generated` and the CLI exits 0).
  After `pixi reinstall powderline` the installed command is `powderline …`.
- `pixi run test` — the engine-free suites (`core or topas_gen`, any env);
  `pixi run -e gsasii test-gsasii`, `pixi run -e easydiffraction
  test-easydiffraction` per engine; `pixi run test-topas` — `topas_gen` +
  `topas_exec` (the exec tests run `tc.exe` only when `POWDERLINE_TOPAS_DIR`
  and `POWDERLINE_TOPAS_VERSION` are set, on the TOPAS Windows machine; else
  they skip); `pixi run test-all` — everything (`dev`).
- `pixi run -e gsasii gsas-server start|status|stop|restart|logs` — the
  persistent GSAS-II server (task in the `gsasii` feature; without `-e` pixi
  reports it ambiguous).
- `pixi run docs` / `pixi run docs-clean` — Sphinx HTML with `-W` (zero warnings).
- `PYTHONPATH=src python scripts/gen_schema_field_tables.py [--check]` — after
  editing a schema module or a gateway's declarations (regenerates
  `docs/_generated/fields_*.md`, `support_matrix.md`); `pixi run fields-check`
  runs the `--check` form (fails when the committed fragments are stale).
- `pixi reinstall powderline --all` — after editing `[project.entry-points]`
  or `[project.scripts]` in `pyproject.toml`: entry-point metadata is written
  at install time, per env; the registry finds nothing until the editable
  package is re-installed (KI-13).
- `pixi run update-code-hash` — regenerate `src/powderline/_code_hash.json`
  after a **signed** edit to a frozen gsasii module (guarded by `tests/test_code_hash.py`).

## Frozen GSAS-II code (the rule stays)

`src/powderline/gateways/gsasii/{helpers,project,setters,executors,extractors,constraints}.py`
are **move-only**: they do GSAS-II's project-dictionary work exactly as the
pre-refactor code did. Never change what they do to the GSAS-II project dict.
Additive or input-side edits — and output-side control flow that leaves the
project-dictionary work untouched (the failure propagation, the checks
before any result table is written) — go **only** through the maintainers'
signed-off record of frozen-code edits, each entry with its proof, then
`pixi run update-code-hash`. An agent never makes such an edit on its own:
propose it to the maintainer. New behaviour goes in
the non-frozen modules (`fit_report.py`, `sites.py`, `routing.py`,
`gateway.py`). Restart the GSAS-II server after any edit it runs (the client
compares the server's source-tree hash with its own and refuses a stale one).

## Engines / environment notes

- `GSAS-II` is built as a **conda package via `pixi-build`** from the
  `tacaswell/GSAS-II@enh/pixi_pkg` fork (pinned to a commit in `pixi.toml`,
  feature `gsasii`); it resolves to **v5.7.9**, which the gateway's
  `ENGINE_VERSION_SPEC` checks at run time. easydiffraction is pinned
  `==0.21.1`; gemmi `==0.7.5` (the canonical space-group names depend on it).
  Moving a pin is a deliberate change with a compatibility run
  (`docs/policies.md`): GSAS-II (or scipy/BLAS) changes shift refined values
  at the last digit, so `refined_parameters.csv` and the unit-cell reports are
  compared within tolerance (`docs/regression-tolerance.md`;
  `tests/subprocess_utils.py` `refined_params_match` / `unit_cell_match`) and
  peak lists by row count. TOPAS and easydiffraction goldens live under
  `tests/data/{topas,easydiffraction}/native/golden/` (TOPAS's by version,
  `golden/6/`); TOPAS runs only in the `topas_exec` tests on the TOPAS machine
  (goldens from the TOPAS machine).
- The schema layer of every gateway, `powderline.api` and `powderline.kicker`
  import no engine — enforced by subprocess tests that block the engine
  imports. Keep it that way: engine imports live inside `run()`-time code.
- Platforms: `linux-64`, `win-64`, `osx-arm64`. **All functionality must work
  on Linux and Windows** (sole exception: TOPAS *execution* needs `tc.exe` on
  win-64). Avoid Unix-only shell syntax in pixi tasks — tasks set `PYTHONPATH`
  through the task-level `env` dict; see `docs/cross-platform-guide.md`.
- **Testing caveat**: some `test_esd_extraction` / `test_example_*_regression`
  cases require a working GSAS-II refinement; they can fail for environment
  reasons unrelated to a given change. Compare against the baseline rather
  than assuming a failure is new.

## Conventions

- Parameters are lists: `[value, refine_flag]` in `gsasii.*`,
  `[value, refine_flag, min, max]` in `topas.*` and `easydiffraction.*`; the
  flag is a JSON boolean; `null` bounds mean open. Blocks that may be left out
  are left out, never `null`; unknown keys are errors.
- **Validation never changes a recipe beyond its stated tolerance, and never
  silently**: anything an engine would silently alter is a validation error
  naming the value to write; a value stated within tolerance of its exact
  symmetry-derived form is *held* in that form and reported
  (`symmetry_value_derived`, level `info`); documented defaults (gsasii
  size/strain 10 µm / 0, background none, 5 cycles) and informative findings
  are structured warnings `{code, message, field_path[, level]}` (`level` is
  `"warning"` when absent, or `"info"`).
- Space groups are gemmi's canonical names (`"P m -3 m"`, `"F d -3 m:2"`);
  every member of a symmetry tie group is stated, with the same flag.
- Results: uniform `rwp`/`r_exp`/`gof`/`chi2_red` from core `fitstats` over the
  window's weighted points; the engine's own values and
  `parameters_requested`/`parameters_varied` under `engine_details`; every
  result carries `status` (`ok` / `generated`), `converged`, `output_recipe` +
  `output_recipe_valid` + `parameter_dispositions` (KI-04: the resolved
  recipe with refined values written back, built by `powderline.roundtrip`) and
  `envelope_version` (no `success` key: `status` is the outcome); **every failure
  raises**: `EngineExecutionError` (the engine ran and failed) or
  `ExecutionBackendError` (it did not run), with `.reason` from
  `powderline.results.REASONS` and `.result` the failed envelope (the
  GSAS-II server speaks the same envelope).
- Output uses fixed filenames (`refined_parameters.csv`,
  `<phase>_unit_cell_report.csv`, `<phase>_peak_list_report.csv`,
  `fit_profile.txt`, `output_recipe.json`, `parameter_dispositions.csv`;
  gsasii `dummy.gpx`/`dummy.lst`; topas `<base>.inp` etc.).
  `unit_cell_data`/`peak_list_data` from `run()` are dicts keyed by phase name.
  `powderline.run()` removes PowderLine's own fixed-name files from the output
  directory before every run (`reports.clear_fixed_outputs`) and, when a run
  fails, writes the failed envelope to `failure.json` beside the engine's own
  files; no result table is written for a failed run on any engine.
- Known, deliberately-deferred behaviours are registered with stable `KI-NN`
  ids in `docs/known_issues.md` — check it before "fixing" a quirk; engine
  quirks and PowderLine's policy are on `docs/engine-behavior.md`.
- Every intentional behaviour change is a deliberate change (recorded,
  reviewed, in the CHANGELOG); regression references under
  `examples/**/output/` **are** tracked and move only with an equivalence
  record — do not gitignore or regenerate them casually.
- Don't commit secrets: `.powderline_config.yaml` is gitignored.
- `_dev/` is a reserved, gitignored path (the maintainers' private design
  records). Never `git add` it or anything under it.
- Never commit TOPAS's own files (console text, `tc.log`, `TOPAS.INC`,
  `ATMSCAT.CPP`): they are licensed with TOPAS.

## Working rules for coding agents (NSLS-II)

PowderLine follows the NSLS-II policy for AI coding assistants:

- A human is responsible for every change, reviews every line, and confirms
  that the tests passed. AI output gets no shortcut through review.
- Agents work on a feature branch, commit **unsigned** if they commit at all,
  and **never** sign, push, tag, force-push or rewrite published history; the
  maintainer signs and pushes.
- Commit messages follow Conventional Commits and end with one trailer line
  per model that contributed: `Assisted-by: <agent>:<model>` (e.g.
  `Assisted-by: claude-code:claude-opus-5-5`). Never `Co-authored-by` for
  an AI, never `Signed-off-by` on a human's behalf.
- Never put secrets, tokens or credentials in the repository or in a
  prompt; `.powderline_config.yaml` is gitignored for that reason.
- Re-run every reported test count yourself before stating it, and compare
  against the baseline rather than assuming a failure is new.
- Before calling documentation complete, grep for the old wording.
