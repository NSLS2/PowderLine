# AGENTS.md — PowderLine

A path map for coding agents (and a quick orientation for human
contributors). Tool-specific files (`CLAUDE.md`) only point here. This file
links the page that owns each topic instead of restating it.

PowderLine runs powder diffraction refinements from a **recipe** (structured
data: a dict, serialized as JSON). A recipe names one engine and one workflow
in `schema_name` (`gsasii.rietveld`, `gsasii.spf`, `topas.rietveld`,
`topas.spf`, `easydiffraction.rietveld`) and is written in that engine's own
terms and units. `powderline.run()` and the `powderline` CLI hand it to the
engine's **gateway** and return standardized tables with uniform fit
statistics. Nothing is translated between engines.

## Authoritative sources

- `docs/development/policies.md` — versioning, deliberate changes, frozen
  code, engine pins, review, "ask, don't assume".
- `docs/reference/versions.md` — schema versions, history, support matrix.
- `docs/engines/*.md` + `docs/catalog/engine_behaviour.yaml` — what each
  engine does and PowderLine's policy (`EB-NN`).
- `docs/reference/known-issues.md` + `docs/catalog/known_issues.yaml` —
  known, deliberately deferred behaviors (`KI-NN`). Check before "fixing" a
  quirk.
- The code under `src/` and `pixi.toml`: where a page and the code disagree,
  the code wins; report the discrepancy.

**If a decision is not written down, stop and ask the maintainer.** Do not
infer it from the code or from another engine. Maintainers working with the
private devkit also follow its own agent guidance.

## Code map (`src/powderline/`)

Core (engine-free; `import powderline` imports no engine):

- `__init__.py` — public API (`__all__`): `run`, `validate`, `ValidationResult`, `load_recipe_asset`, `support_matrix`, the exceptions.
- `api.py` — `validate()` / `run()`: `schema_name` → `registry.get(<engine>)`; clears fixed outputs, writes `failure.json`; refuses `allow_unsupported_engine_version`.
- `kicker.py` — the CLI (`powderline`); refuses templates; an engine flag for another engine's recipe exits 1.
- `doctor.py` — `powderline --doctor` (KI-13: stale install).
- `registry.py` — entry-point group `powderline.gateways`, `Gateway` dataclass, `register_gateway`, `check_engine_version`, `validate_only_summary`. No in-code fallback.
- `schema_core.py` — core schema 0.1.0: `CoreRecipe`, `RefinableParameter` / `BoundedRefinableParameter`, `XRDData`, `FitRange`, `ChebyshevBackground`, `Phase[P]`, `EngineRecipe`, `recipe_validator`, the building blocks.
- `symmetry.py` — gemmi: canonical space groups, cell ties, special positions.
- `compat.py` — declared schema compatibility, `schema_declarations`, `support_matrix`.
- `fitstats.py` — uniform Rwp / Rexp / GoF / χ²_red.
- `reports.py` — report writers, `FIXED_OUTPUT_NAMES` / `FIXED_OUTPUT_PATTERNS`, `clear_fixed_outputs`.
- `results.py` — result envelope, `REASONS`, `raise_if_failed`.
- `roundtrip.py` — output recipe and parameter dispositions.
- `exceptions.py` — exceptions and `WARNING_CODES`.
- `recipes.py`, `config_loader.py` (`.powderline_config.yaml`), `_status.py`, `_code_hash.json`.

Gateways (`src/powderline/gateways/<engine>/`): schema layer `schema.py`
(`DECLARATIONS`, `SCHEMA_NAMES`, `validate_recipe`; imports no engine) +
runtime layer `gateway.py` (`get_gateway()`, `ENGINE_VERSION_SPEC`, `ENV` /
`INSTALL_COMMAND`; engine imported lazily from `run()`).

- `gsasii/` (GSAS-II `==5.7.9`, env `gsasii`) — frozen: `helpers`, `project`, `setters`, `executors`, `extractors`, `constraints`; around them: `routing`, `fit_report`, `sites`, `paths`, `report_rows`, `console`, `scattering`, `server` / `client` (persistent server, `POWDERLINE_NO_SERVER=1` disables it), `simulation_builder`.
- `topas/` (TOPAS 6, no Python engine; generate-only without `tc.exe`) — `native_writer`, `native_run`, `peak_list`, `runner`, `scattering`.
- `easydiffraction/` (`==0.21.1`, env `easydiffraction`, Python ≥ 3.12) — `native_builder`, `native_run`, `space_group_table`, `space_group_support`, `scattering`.

Docs (`docs/`, MyST): `getting-started/`, `concepts/`, `how-to/`,
`examples/`, `engines/`, `reference/`, `development/`, `about/`;
`_generated/` (script output, never hand-edited); `catalog/` (EB/KI data).
`docs/reference/messages.md` holds the warning-codes table that
`tests/test_warning_codes.py` reads.

Scripts (`scripts/`): `gen_schema_field_tables.py`, `gen_catalog.py`,
`gen_example_figures.py`, `cross_engine_comparison.py`,
`convert_recipe_026.py` (0.26.0 → `gsasii.*`), `check_engine_version_candidate.py`,
`update_code_hash.py`, `verify_easydiffraction_settings.py`,
`generate_easydiffraction_space_groups.py`, `hooks/pre-commit`.

## Key commands

Environments: `default` (core only: validates everything, runs nothing),
`gsasii`, `easydiffraction`, `all`, `dev` (all + docs and test tooling).
Install with `pixi install --frozen -e <env>`.

- `pixi run powderline <recipe.json> --validate-only` — any env.
- `pixi run -e gsasii powderline <recipe.json> [--use-server|--no-server] [--server-timeout S] [--output DIR] [--verbose]`.
- `pixi run -e easydiffraction powderline <recipe.json>`.
- `pixi run powderline <recipe.json> --topas-version 6 [--topas-dir DIR] [--topas-timeout S]` — without `tc.exe`: status `generated`, exit 0.
- `pixi run powderline --doctor`. The tasks `kicker` and `doctor` run the same `main`.
- `pixi run test` (engine-free: `core or topas_gen`); `pixi run -e gsasii test-gsasii`; `pixi run -e easydiffraction test-easydiffraction`; `pixi run test-topas` (runs `tc.exe` only with `POWDERLINE_TOPAS_DIR` and `POWDERLINE_TOPAS_VERSION` set); `pixi run test-all` (`dev`).
- `pixi run -e gsasii gsas-server start|status|stop|restart|logs`. `start` and `restart` run the server in the foreground until stopped; to replace a stale server, `stop` it and the next run starts a fresh one.
- `pixi run docs` / `pixi run docs-clean` — Sphinx, `-W`, zero warnings.
- `pixi run fields-check`, `pixi run catalog-check`, `pixi run figures-check` — generated docs are current; regenerate with the matching script without `--check`.
- `pixi run update-code-hash` — after any edit to a frozen gsasii module.
- `pixi reinstall powderline --all` — after editing `[project.entry-points]` or `[project.scripts]` (KI-13).

Detail: `docs/development/contributing.md`.

## Frozen GSAS-II code

`src/powderline/gateways/gsasii/{helpers,project,setters,executors,extractors,constraints}.py`
do GSAS-II's project-dictionary work. Rules (`docs/development/policies.md#frozen-gsas-ii-code`):

- A behavior-changing edit needs the maintainers' explicit consent. An agent
  never makes one on its own: propose it, with its reason and proof.
- Comment and docstring edits need no consent. Don't leave outdated comments.
- After **any** edit, `pixi run update-code-hash` (the hash covers raw bytes;
  `tests/test_code_hash.py` guards it).
- New behavior goes into the non-frozen modules (`fit_report`, `sites`,
  `routing`, `paths`, `gateway`).
- Replace the GSAS-II server after any edit it runs (a stale server is
  detected: skipped in `auto` mode, refused in `server` mode):
  `gsas-server stop`; the next run starts a fresh one.
  `gsas-server restart` blocks in the foreground, so never chain a command
  after it.

## Environment notes

- GSAS-II is a conda package built by `pixi-build` from a fork pinned to a
  commit in `pixi.toml`; it resolves to v5.7.9. Use `--frozen` so it is not
  re-locked.
- Pins: GSAS-II `==5.7.9`, easydiffraction `==0.21.1`, gemmi `==0.7.5`. Moving
  a pin is a deliberate change with a compatibility run (policies page).
- Regression references: `examples/**/output/` (gsasii, easydiffraction),
  compared within tolerance (`tests/subprocess_utils.py`
  `refined_params_match` / `unit_cell_match`); goldens under
  `tests/data/{topas,easydiffraction}/native/golden/` (TOPAS by version).
- The schema layers, `powderline.api` and `powderline.kicker` import no engine;
  subprocess tests enforce it.
- Platforms: `linux-64`, `win-64`, `osx-arm64`. Everything works on Linux and
  Windows except TOPAS execution (`tc.exe`, Windows). pixi tasks set
  `PYTHONPATH` through the task-level `env` dict; no Unix-only shell syntax.
- Some GSAS-II regression and ESD tests can fail for environment reasons:
  compare against a baseline run on `main`.

## Conventions

- Parameter shapes, bounds, units, unknown keys, blocks left out (never
  `null`) — `docs/reference/recipe-format.md`.
- Validation never changes a recipe silently; space groups are gemmi's
  canonical names; tie groups are stated in full — `docs/concepts/validation.md`.
- Structured warnings `{code, message, field_path[, level]}`; every code in
  `exceptions.WARNING_CODES` and `docs/reference/messages.md`.
- Result keys, report files, `failure.json`, failure reasons —
  `docs/reference/outputs.md`; uniform statistics and the output recipe —
  `docs/concepts/results.md`.
- Every failure raises `EngineExecutionError` or `ExecutionBackendError`; a
  gateway never returns a failed result — `docs/development/adding-an-engine.md`.
- Every intentional behavior change is deliberate; references move only with
  an equivalence check — `docs/development/policies.md`.
- Docs follow the writing rules in
  `docs/development/contributing.md#writing-documentation`.
- Don't commit secrets: `.powderline_config.yaml` is gitignored.
- `_dev/` is reserved and gitignored. Never commit it or anything under it.
- Never commit TOPAS's own files (console text, `tc.log`, `TOPAS.INC`,
  `ATMSCAT.CPP`): they are licensed with TOPAS.

## Working rules for coding agents (NSLS-II)

PowderLine follows the NSLS-II policy for AI coding assistants:

- A human is responsible for every change, reviews every line, and confirms
  that the tests passed. AI output gets no shortcut through review.
- Agents work on a feature branch and commit unsigned, if they commit at all.
  They never sign, push, tag, force-push or rewrite published history; the
  maintainer signs and pushes.
- Commit messages follow Conventional Commits and end with one trailer line
  per model that contributed: `Assisted-by: <agent>:<model>` (e.g.
  `Assisted-by: claude-code:claude-opus-5-5`). Never `Co-authored-by` for
  an AI, never `Signed-off-by` on a human's behalf.
- Never put secrets, tokens or credentials in the repository or in a
  prompt.
- Re-run every reported test count yourself before stating it, and compare
  against the baseline rather than assuming a failure is new.
- Before calling documentation complete, grep for the old wording.
