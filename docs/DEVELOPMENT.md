# PowderLine Developer Guide

This guide provides context for developers working on PowderLine (and for AI
coding assistants used alongside them). Read this first to understand the
architecture, the design decisions, and the development workflows. The rules
that bind every change (versioning, deliberate changes, the frozen GSAS-II
code, the engine pins, review gates, "ask, don't assume") are on the
[policies page](policies.md); this guide shows where things are and how to
work on them.

## Project Overview

**What is PowderLine?**
PowderLine automates crystallographic refinement from a declarative JSON
"recipe" and drives interchangeable refinement engines — GSAS-II, Bruker
TOPAS 6 and the open-source easydiffraction — through one API and one CLI.
A recipe names its engine and workflow in `schema_name` and is written in
that engine's own conventions; PowderLine validates it strictly, hands it to
the engine's **gateway**, and returns standardized result tables with uniform
fit statistics. The goal is to make powder diffraction refinements
reproducible, automatable, and accessible.

**Scope:**
- One CLI (`powderline <recipe>`) and one Python API (`powderline.run`,
  `powderline.validate`) for every engine; the recipe decides where it runs
- A **core schema** (the shared frame and structural models) plus one
  **engine schema** per gateway, all pydantic, `extra='forbid'`, engine-free
- Three gateways under `src/powderline/gateways/`, discovered through entry
  points, each split into an engine-free schema layer and a lazily imported
  runtime layer
- Single-phase and multi-phase Rietveld refinement; single peak fitting
  (GSAS-II, TOPAS)
- Standard output reports plus each engine's native artifacts; uniform
  Rwp / Rexp / GoF computed once in core, the engine's own values alongside
- Example-driven design: real refinement cases drive the schemas and are the
  regression references

**Design Philosophy:**
- **Example-driven**: don't build features speculatively; add them when real examples need them
- **Schema-first**: every rule a recipe must obey lives in the schema models, so validation
  reports every problem at its field before any engine runs
- **Honest**: an engine's silent default, floor or conversion is either refused at
  validation (with the value to write) or reported as a structured warning; never papered over
- **Engine-native**: no translation between engines; each recipe states the numbers its engine computes with
- **Reproducible**: the same recipe produces the same refinement; the references are tracked

## Architecture (`src/powderline/`)

### Core (engine-free)

| Module | Role |
|---|---|
| `__init__.py` | the public API, `__all__`: `run`, `validate`, `ValidationResult`, `load_recipe_asset`, `support_matrix`, the exceptions. `import powderline` imports no engine |
| `api.py` | `validate()` and `run()`: resolve the gateway from `schema_name` (`<engine>.<workflow>`) through the registry and hand the recipe over; `ValidationResult` |
| `kicker.py` | the one CLI (`powderline <recipe>`; `pixi run kicker` runs the same `main`): loads the recipe, refuses templates, maps the engine flags onto the gateway's run options, prints the summary and the structured warnings |
| `registry.py` | gateway discovery from the `powderline.gateways` entry-point group, lazy loading, `Gateway` dataclass (`name`, `capabilities`, `validate`, `run`), `register_gateway` escape hatch, the engine-version check |
| `schema_core.py` | core schema 0.1.0: `CoreRecipe` (frame), `RefinableParameter` / `BoundedRefinableParameter`, `XRDData`, `FitRange`, `ChebyshevBackground`, `UnitCell`, `Atom`, `UanisoTensor`, `Phase[P]` (the phase block with every symmetry rule), `CoreFloat`/`CoreInt`/`CoreName`, `collect_warnings`, `parameters_requested`, `fit_limits_on_data`; the engine schema building blocks (P-37): `EngineRecipe`, `recipe_validator`, `refined_flags`, `custom_error` / `raise_problems`, `omit_absent`, `absent_not_null`, `unique_phase_names`, `fit_window`, `fit_range_problems`, `outside_window_problems`, `refined_flag_problems`, `unit_schema` |
| `symmetry.py` | gemmi-backed symmetry: canonical space-group names, cell tie groups and the cell check, special-position analysis, coupling groups for coordinates and Uij |
| `compat.py` | declared schema-version compatibility: `check_engine_schema_version`, `support_matrix()`, `schema_declarations()` (a gateway's `DECLARATIONS`) |
| `fitstats.py` | the uniform Rwp / Rexp / GoF / χ²_red over the fit window with positive weights |
| `reports.py` | the standardized report writers (`refined_parameters.csv`, unit-cell and peak-list reports, `fit_profile.txt`): one column order, UTF-8, LF; the fixed-name list PowderLine owns (`FIXED_OUTPUT_NAMES` / `FIXED_OUTPUT_PATTERNS`, `FAILURE_FILE`) and `clear_fixed_outputs()` |
| `recipes.py` | `load_recipe_asset` (JSON / YAML) |
| `exceptions.py` | `PowderLineError`, `SymmetryError`, `GatewayNotInstalledError`, `EngineNotAvailableError`, `EngineVersionError`, `EngineExecutionError`, `ExecutionBackendError` (both with `.reason` / `.result`), the `StructuredWarning` shape; `WARNING_CODES`, the registry of every structured-warning code with its owner and level (asserted against `src/` and the engine-behaviour table) |
| `results.py` | the run-result envelope (re/12): `ENVELOPE_VERSION`, the reason-code sets, `failure_envelope`, `generated_envelope`, `with_status_fields`, `raise_if_failed` |
| `config_loader.py` | `.powderline_config.yaml` (the `simulation_defaults` block; engine-free) |
| `_status.py` | console status glyphs |

### Gateways (`src/powderline/gateways/<engine>/`)

Each gateway is a package with the same two layers:

- **Schema layer** — `schema.py`: the engine schema models built on
  `schema_core` (the engine's `Phase` subclass, instrument, background,
  controls, payload and recipe models), the version declarations
  (`ENGINE_SCHEMA_VERSION`, `SUPPORTED_ENGINE_SCHEMAS`, `REQUIRES_CORE_SCHEMA`,
  exposed as `DECLARATIONS`), `SCHEMA_NAMES`, and `validate_recipe()`. Imports
  no engine; this is what `powderline.validate()` runs.
- **Runtime layer** — `gateway.py` (the entry-point factory: `capabilities()`,
  `validate()`, `run()`, `ENGINE_VERSION_SPEC`, and for pixi-installed engines
  `ENV` / `INSTALL_COMMAND`) plus the modules that import the engine, imported
  lazily from `run()`.

| Gateway | Runtime modules |
|---|---|
| `gsasii/` (GSAS-II 5.7.9) | the **frozen** setup/execution code moved verbatim from `kicker.py` at the re/01 baseline `daace24`: `helpers.py`, `project.py`, `setters.py`, `executors.py`, `extractors.py`, `constraints.py` (code-hashed; see [policies](policies.md#frozen-gsas-ii-code-and-the-edits-ledger)); non-frozen additions `routing.py` (one entry for in-process, server and client), `fit_report.py` (uniform statistics, `engine_details`, convergence, divergence), `sites.py` (GSAS-II's reading of each site vs core's), `report_rows.py`, `paths.py` (GSAS-II parameter names → recipe paths for the output recipe), `console.py` (the engine's console tail into a failed envelope), `scattering.py` (GSAS-II's ion table and spelling); `server.py` / `client.py` (the persistent FastAPI server and `GSASClient`: per-user, loopback, ephemeral port, signed requests and responses, `POWDERLINE_NO_SERVER=1` disables it — v0.1.2); `simulation_builder.py` (structure dict → simulation recipe; see [the builder](#the-simulation-recipe-builder)) |
| `topas/` (TOPAS 6) | `native_writer.py` (model → INP + `.xye`), `native_run.py` (run `tc.exe`, read TOPAS's files strictly, build the result; the background-only second run), `peak_list.py`, `runner.py` (find `tc.exe`, read `.powderline_config.yaml`) |
| `easydiffraction/` (0.21.1) | `native_builder.py` (model → easydiffraction `Project`; the CrysPy template rule; anisotropic atoms first), `native_run.py` (calculate or lmfit fit, the result), `space_group_table.py` / `space_group_support.py` (the 531 settings and the per-calculator verified sets), `scattering.py` (CrysPy's ion table) |

The entry points are declared in `pyproject.toml`
(`[project.entry-points."powderline.gateways"]`); the metadata is written at
install time, so after editing that table run `pixi reinstall powderline`
(every environment has its own install: `--all`). There is deliberately no
in-code fallback (KI-13): the in-repo gateways use exactly the mechanism a
third-party engine would.

### The execution stack

```
powderline <recipe>  /  powderline.run(recipe, output_dir, **engine_options)
        │  schema_name -> registry.get("<engine>") ; gateway.run(...)
        ▼
gateway.run()           validates (schema layer), checks the engine version,
        │               then the runtime layer:
        ├─ gsasii:   routing.run_refinement() in this process, or GSASClient
        │            -> the FastAPI server (GSAS-II resident) -> routing.run_refinement()
        │            -> executors.run_refinement() -> GSASIIscriptable
        │            -> fit_report (uniform statistics) ; reports (files)
        ├─ topas:    native_writer -> tc.exe (twice: fit, background) -> native_run reads the files
        └─ easydiffraction: native_builder -> lmfit / calculate() -> native_run
        ▼
the standardized result dict (tables as DataFrames) + the report files + native artifacts
```

`execution_mode` (gsasii only: `'auto'` | `'server'` | `'subprocess'`) is the
public option; `method` is the result key saying which path ran. The server
keeps GSAS-II imported in one process (~2.6 s import amortized); it caches
code, so **restart it after editing anything it runs**
(`pixi run -e gsasii gsas-server restart`).

## The schema layer

### Shape of a recipe

```
schema_name              "<engine>.<workflow>"
core_schema_version      "0.1.0"
engine_schema_version    "0.1.0"
metadata                 free-form, echoed, never read (<= 1 MiB)
payload                  the engine schema's payload model
```

Core owns the frame, `xrd_data`, `fit_range`, `ChebyshevBackground` and the
**phase block** (`space_group`, `unit_cell`, `atoms`), generic over the
parameter type `P` (`RefinableParameter` for gsasii, `BoundedRefinableParameter`
for topas and easydiffraction). The engine schema owns everything else
(instrument, background placement, controls, engine phase fields such as
`scale` and `peak_broadening`) and may add checks, but can never redefine,
skip or rewrite core's (guarded when the class is defined: no reuse of a
core field, validator or private-attribute name, no `'before'`/`'wrap'`
validator on a core field, `extra='forbid'` kept; `tests/test_phase_canary.py`
runs core's must-fail recipes through every engine phase model).

User-facing rules: [schemas](schemas.md), [fields](fields.md) (generated
tables), [input guidance](input-guidance.md), [SCHEMA_HISTORY](SCHEMA_HISTORY.md).

### Validation model

- Every recipe check is a pydantic validator raising `ValueError` (or
  `SymmetryError`), so an invalid recipe raises **one** `pydantic.ValidationError`
  listing every problem at its field path. There is no PowderLine wrapper
  exception for invalid recipes.
- **Validation never changes a recipe.** The validated model holds exactly the
  recipe's values plus documented defaults and the symmetry-derived values; a
  value an engine would silently replace (a floor, a snapped coordinate, a
  limit) is an **error naming the value to write**, never an adjustment.
- **Structured warnings** (`{code, message, field_path[, level]}`; `level` absent = `"warning"`, or `"info"`) are collected once
  from the validated model (`collect_warnings`) and travel with it: a default
  applied, a symmetry remark, a unit conversion the gateway will make. They
  never change what the recipe means, so re-validating reproduces them.
- Engine quirks that reach a user are recorded in the maintainers'
  engine-behaviour register and rendered on the
  [engine behaviour page](engine-behavior.md); a schema rule that exists
  because of a quirk cites its `EB-nn` in the error message.

## Adding a refinement engine

The gateway seam is the contract the refactor exists to provide. A new engine
is a package `src/powderline/gateways/<engine>/` (in-repo) or a separate
distribution (out of tree) that provides:

1. **A schema module** (`schema.py`), engine-free:
   - the engine's `Phase` subclass (`class MyPhase(Phase[BoundedRefinableParameter])`
     or `Phase[RefinableParameter]` if the engine has no usable bounds), adding
     the engine's phase fields with their own validator names and `'after'`
     validators only;
   - instrument, background and controls models in the **engine's native
     terms and units**, every quantity carrying `json_schema_extra={"unit": ...}`
     (the [fields page](fields.md) is generated from it), `extra='forbid'`,
     no `null` for a block that may be left out, and **no default that
     replaces an engine behaviour silently** (either the value is required, or
     the default is documented and reported by a warning);
   - the recipe model(s) subclassing `powderline.schema_core.EngineRecipe`
     with `schema_name` narrowed to a `Literal` and two class variables,
     `gateway_name` and `schema_declarations = DECLARATIONS`, where
     `DECLARATIONS = compat.schema_declarations(engine_schema_version="0.1.0",
     supported_engine_schemas="==0.1.0", requires_core_schema="==0.1.0")`
     (widened explicitly later, never by range); `EngineRecipe` runs the
     version check;
   - `validate_recipe = schema_core.recipe_validator({<schema_name>: <model>, ...},
     engine="<engine>", title="<Engine>Recipe")`: accepts a dict or an
     already-validated model (idempotent) and reports an unknown
     `schema_name` at `schema_name`;
   - every engine rule as a validator: refuse what the engine cannot express
     (settings, features) and what it would silently alter (floors, limits),
     naming the value to write; apply the three shared value rules
     (wavelength > 0, scale per engine, peak positions inside the window) and
     the fit window on data points (`fit_limits_on_data`). The shared pieces
     are core building blocks (P-37), not copies: `absent_not_null` for a
     block that may be left out but never be `null`, `omit_absent` in the
     wrap serializer that drops it from dumps, `unique_phase_names`,
     `fit_range_problems` / `fit_window` / `outside_window_problems` /
     `refined_flag_problems` for the payload rules, `refined_flags`,
     `custom_error` + `raise_problems` to report every problem at once;
   - every warning code the engine emits registered in
     `powderline.exceptions.WARNING_CODES` (owner, level) and listed in the
     engine-behaviour table; a core test holds the three in agreement.
2. **A gateway module** (`gateway.py`) exporting `get_gateway()` →
   `registry.Gateway(name, capabilities, validate, run)`:
   - `capabilities()` returns at least `name`, `workflows` (the schema names),
     `engine_version_spec` (PEP 440) and the schema `DECLARATIONS`;
   - `validate(recipe, *, verbose=False)` (exactly these keywords) returns the
     validated model;
   - `run(recipe, output_dir, *, verbose=False, validate_only=False,
     allow_unsupported_engine_version=False, **own_options)`: validates, checks
     the installed engine version against `engine_version_spec`
     (`registry.check_engine_version`; raise `EngineNotAvailableError` with
     `env` and `install_command` when the engine is missing — only on a real
     run, never for `validate_only`), imports the engine **lazily**, runs, and
     hands `powderline.roundtrip` its refined values by recipe path (`{path: (value, esd)}`
     in recipe units, plus the flagged paths it did not vary and those that ended at a
     limit; `roundtrip.build_output` / `attach` do the rest: tie propagation, the
     multiplicity invariant, `output_recipe`, `output_recipe_valid`, `parameter_dispositions`,
     the two files) and
     returns the standardized result dict with the same keys and types as the
     other gateways (`status`, `converged`, `envelope_version`, `run_id`, `rwp`, `r_exp`, `gof`, `chi2_red`,
     `simulation_mode`, `engine_details` with `parameters_requested` /
     `parameters_varied` / `n_points`, `warnings`, `elapsed_time`, `method`,
     `output_files`, `fit_profile`, `unit_cell_data`, `peak_list_data`,
     `refined_parameters`, `spf_peaks`, `spf_convergence_diagnostics`; gsasii adds
     `peak_fit` for a peak fit). A gateway **never returns a failed
     result**: it raises `EngineExecutionError` (the engine ran and failed) or
     `ExecutionBackendError` (it did not run) with a `reason` from
     `powderline.results.REASONS`, or returns
     `results.raise_if_failed(envelope)` on an envelope it received; the
     GSAS-II server/client show the wire form (`results.failure_envelope`,
     `results.with_status_fields`). Statistics come from `powderline.fitstats` over
     the window's weighted points with P read from the engine after the run;
     the engine's own values go under `engine_details`; divergence (a
     non-finite calculated pattern) raises `EngineExecutionError`.
   - report files through `powderline.reports`; native artifacts kept.
3. **An entry point** in `pyproject.toml`
   (`[project.entry-points."powderline.gateways"] <engine> = "...gateway:get_gateway"`),
   then `pixi reinstall powderline`. A pixi feature/environment for the
   engine's dependencies if the default environment must not carry them
   (every in-repo engine has one); `ENV` / `INSTALL_COMMAND` on the gateway.
4. **Tests**, in the pattern of the existing gateways: schema tests
   (`test_<engine>_schema.py`: every rule, every refusal, with the error
   path), the engine phase model registered in `tests/test_phase_canary.py`
   `ENGINE_PHASES`, an import-block test proving the schema layer and
   `import powderline` load no engine module, a space-group translation test
   over every setting the engine accepts (orbit / operator comparison against
   gemmi), fixtures + goldens for the runtime (hand-derived native recipes
   with a README of the derivations; goldens recording the engine's version),
   and the result-contract test (same keys and types as the other engines).
   Tests that need the engine are marked / skipped so the core-only suite
   stays green.
5. **Freeze-equivalent expectations**: the engine's goldens are the
   references; a change in what the engine is asked to do (the INP, the
   project, the input dictionary) is proved against them, and anything the
   engine does silently is written up in the engine-behaviour register with
   its policy before the gateway ships.
6. **Docs**: the schemas, fields (regenerate with
   `scripts/gen_schema_field_tables.py`), input-guidance and engine-behaviour
   pages; a SCHEMA_HISTORY section; the support matrix regenerates itself.

### Adding a capability to an existing engine

The same discipline, smaller: a new field or block goes into the engine
schema with its unit, its validators and its refusals; the gateway consumes it
from the validated model (for gsasii, an **input-side read in a frozen module
is a ledger row**, otherwise the read happens in the non-frozen modules); a
fixture and a golden prove it reaches the engine and does what the recipe
says; the engine-behaviour register records anything the engine does with it
silently; SCHEMA_HISTORY and the generated field tables record the field. If
the field changes what an existing recipe means, that is a deliberate change
(table row, CHANGELOG, migration note) — and if the engine's own behaviour
is unknown, that is a question for the maintainer, not an inference.

Worked example — March–Dollase preferred orientation (re/29, P-48):

1. **Ground truth first.** Read and run each engine: GSAS-II's HAP
   `Pref.Ori.` entry and `GetPrefOri`; easydiffraction's
   `preferred_orientation` rows, which only CrysPy reads, and only under the
   lowercase structure key (EB-97); CrysPy's un-normalised correction (EB-98).
2. **One core building block, engine fields.** `schema_core.MarchDollase[P]`
   carries the shape and the engine-independent rules (`hkl` not all zero,
   `ratio > 0`); each engine's phase model adds `preferred_orientation` in
   its own parameter shape (gsasii `[value, flag]`, easydiffraction bounded
   plus the required `march_random_fract`); topas declares the field and
   refuses it until its half is verified on a TOPAS machine.
3. **The gateway reads the model.** gsasii: an additive frozen setter and its
   call, two ledger rows with proofs (the project-dict diff shows only
   `Pref.Ori.`), and the refined name `p:h:MD` in `paths.py`;
   easydiffraction: the builder's row plus the `_free` bookkeeping that maps
   the refined value back to the recipe path.
4. **A gate, then a demonstration.** The pass/fail gate is a formula check on a
   simulated pattern (each engine's textured/untextured intensity ratio equals
   Dollase's correction over the reflection's equivalents); the example
   (`example_LaB6_textured`) is the demonstration that refinement recovers the
   programmed value, with its caveats written down (the start at exactly 1.0
   aborts, EB-99).
5. **Record.** Fields tables regenerated, SCHEMA_HISTORY per engine,
   engine-behaviour register rows, CHANGELOG, the T-list row for the TOPAS
   half, the P-row.

## GSAS-II integration notes

### The frozen modules and the project dictionary

The GSAS-II setup/execution code manipulates the `proj.data` dictionary of a
GSAS-II project directly (explicit control, debuggable, brittle to GSAS-II
internals). It moved verbatim out of `kicker.py` at the re/01 baseline
`daace24` (not on `main`) and is
frozen behind a code hash; input-side edits go through the maintainers'
signed-off edits ledger ([policies](policies.md#frozen-gsas-ii-code-and-the-edits-ledger)).
The module headers still read "moved verbatim"; the ledger, not the headers,
is the record of the additive edits made since (ionic types in `project.py`,
the preferred-orientation setter in `setters.py`, the simulation ESDs in
`extractors.py`).
Key access patterns, for reading the code:

```python
# Instrument parameters (list format: [current_value, value, refine_flag]); the native
# gateway builds Iparm1 from the recipe's instrument block (schema.gsasii_iparm1)
proj.data[hist.name]['Instrument Parameters'][0]['Lam'][1] = wavelength
proj.data[hist.name]['Instrument Parameters'][0]['Lam'][2] = refine_flag

# Background
proj.data[hist.name]['Background'] = [
    [chebyshev, no_peaks, background_type],  # Background metadata
    {'nDebye': 0, 'debyeTerms': [], ...},     # Debye-Scherrer params
    {'nPeaks': n, 'peaksList': [...]},        # Single peaks
]

# Histogram-atom parameters (HAP): phase scale, size, microstrain
proj.data['Phases'][phase_name]['Histograms'][hist.name]['Scale'][0] = value
proj.data['Phases'][phase_name]['Histograms'][hist.name]['Size'][1][0] = value       # isotropic size
proj.data['Phases'][phase_name]['Histograms'][hist.name]['Mustrain'][1][0] = value   # isotropic microstrain

# Phase parameters
proj.data['Phases'][phase_name]['General']['Cell'] = [refine_cell, a, b, c, alpha, beta, gamma, volume]
```

GSAS-II exposes lumped refine flags (one for the cell, `'X'` for all three
coordinates of an atom, `'U'` for all six Uij); `constraints.py` sets the
lumped flag and emits GSAS-II "Hold" constraints for the degrees of freedom
the recipe does not refine, so per-parameter flags are honoured. The native
schema has already refused any flag pattern GSAS-II could not honour (a strict
subset of a tie group or of a GSAS-II cell group), so no flag is ever silently
overridden.

### What the native gsasii path adds around the frozen code

- `sites.py` compares GSAS-II's `(site symmetry, multiplicity)` of every atom
  with core's after phase setup and stops with an error naming an equivalent
  position when GSAS-II misreads the site (some 2-fold sites of R32/R-3m/R-3c)
  or cannot name it while a coordinate / `Uaniso` is refined.
- `fit_report.py` computes the uniform statistics over the stated window,
  reads GSAS-II's stored messages into `gsasii_refinement_message` warnings,
  its convergence flag into `engine_details.converged`, counts
  `parameters_varied` from GSAS-II (`Nvars`; the Peak List count after
  singular drops), and raises on a non-finite calculated pattern.
- The documented defaults (size/strain 10 µm / 0 with a warning; background
  none) are pydantic defaults in `schema.py`, so the frozen setters receive
  explicit values and GSAS-II's own 1 µm / 1000 / constant-1.0 defaults are
  never used.

### Known GSAS-II quirks

All on the [engine behaviour page](engine-behavior.md); the ones a developer
meets first: the background-peak width `BkPksig` is a **variance** (the
schema names it `pv_gaussian_sigma_sq`); SH/L is floored at 0.002 in the
profile calculation; `Refine` returns nothing and stores its messages in the
project; `Nvars` counts parameters dropped as singular; `GOF` means two
different things in Rietveld and Peak List fits; limits are applied after the
cycles (why gsasii 0.1.0 exposes no bounds).

### Output files

Fixed filenames in every engine (`refined_parameters.csv`,
`<phase>_unit_cell_report.csv`, `<phase>_peak_list_report.csv`,
`fit_profile.txt`; single peak fitting adds a peak report), written by
`powderline.reports` with one column order and LF line endings so the files
are byte-stable across platforms. gsasii keeps `dummy.gpx`, `dummy.bak0.gpx`
and `dummy.lst`; topas keeps the INP, `.xye` and every file TOPAS wrote;
easydiffraction writes the reports only. Refinement runs add
`output_recipe.json` and `parameter_dispositions.csv`. `powderline.run()`
removes every PowderLine-owned fixed name (`reports.FIXED_OUTPUT_NAMES` /
`FIXED_OUTPUT_PATTERNS`) from the directory before dispatch and never the
engine's files; a failed run leaves the engine's files plus `failure.json`
(the envelope with a `powderline_provenance` block) and no result table —
in gsasii the checks run before the tables are written (ledger row R38).

 The `refined_parameters.csv`
columns: `parameter_name` (the engine's identifier), `descriptive_name`,
`phase_name`, `phase_idx`, `atom_name`, `atom_idx`, `value`, `esd`,
`category`. gsasii's ESDs come from GSAS-II's covariance matrix
(`proj.data['Covariance']`); unit-cell ESDs are converted from the
reciprocal-metric tensor with `extractors.calculate_cell_esds_from_A_matrix`.

## Domain essentials

**Rietveld refinement** fits a calculated powder pattern to the observed one
by adjusting structural, profile and background parameters. The headline
quality metric, in PowderLine's uniform form (percent, over the fit window's
points with positive weight):

$$R_{wp} = 100 \sqrt{\frac{\sum_i w_i (y_{obs,i} - y_{calc,i})^2}{\sum_i w_i y_{obs,i}^2}}, \quad
R_{exp} = 100 \sqrt{\frac{N - P}{\sum_i w_i y_{obs,i}^2}}, \quad
\mathrm{GoF} = R_{wp}/R_{exp}$$

with N the included points and P the engine's count of varied parameters.
Lower Rwp is a better fit of *that model* to *those points*; across engines
compare lattice parameters, not Rwp (the models differ: background peaks,
asymmetry treatment, sample broadening).

**Parameter types** (every one a `[value, flag]` or `[value, flag, min, max]`
list): structural (cell, coordinates, occupancies, ADPs: the core phase block,
identical across engines), intensity (phase `scale`), peak shape (sample
size/strain in gsasii and topas; the instrument profile in every engine),
background (Chebyshev; gsasii/topas peaks), instrument (profile terms,
wavelength, zero shift, polarization, asymmetry: the engine's own names and
units).

**Phase vs histogram parameters**: phase parameters belong to a crystal
structure (cell, atoms, scale, sample broadening); histogram parameters belong
to the measurement (instrument profile, background) and are shared across
phases in a multi-phase refinement.

**Glossary**: *Recipe* — PowderLine's JSON input. *Gateway* — the per-engine
package behind the registry. *Schema layer / runtime layer* — the engine-free
and engine-importing halves of a gateway. *Tie group* — parameters the
symmetry makes one parameter (cubic a, b, c). *Golden* — a committed engine
output a test compares against. *GPX / LST* — the GSAS-II project and log.
*INP / `.xye`* — TOPAS's input and data files.

## Development workflow

### Environments and tasks

```bash
pixi install -e dev          # every engine + docs/test tooling (contributors)
pixi install -e gsasii       # GSAS-II only
pixi run kicker <recipe> --validate-only          # default env: engine-free
pixi run -e gsasii kicker <recipe>                # run a gsasii.* recipe
pixi run -e easydiffraction kicker <recipe>       # run an easydiffraction.* recipe
pixi run test                # engine-free suites (core + topas_gen), any env
pixi run -e dev test-all     # every suite, the pre-merge gauntlet
pixi run -e gsasii pytest tests/test_example_LaB6_regression.py -q   # one engine's suite
pixi run docs                # Sphinx with -W (zero warnings is the standard)
pixi run -e gsasii gsas-server start|status|stop|restart|logs
pixi run update-code-hash    # after a signed edit to a frozen gsasii module
pixi reinstall powderline --all   # after editing entry points / [project.scripts]
```

The default feature carries only PowderLine's runtime dependencies plus
pytest; `gsasii`, `easydiffraction`, `all` and `dev` are features/environments
in `pixi.toml`. `test` and `update-code-hash` live in the default feature and run anywhere;
tasks only `dev` has (`test-all`, `docs`, `docs-clean`) resolve without `-e`; engine-bound tasks live in their engine's feature, so pixi
reports them as ambiguous without `-e` and prints the form to use. Tasks that
import PowderLine set `PYTHONPATH` through the task-level `env` dict (cross-platform;
[cross-platform guide](cross-platform-guide.md)).

### Execution modes (gsasii)

| Mode | Command | Behaviour |
|---|---|---|
| auto (default) | `pixi run -e gsasii kicker input.json` | tries the server, auto-starts it, falls back to in-process |
| server | `... --use-server` | server only; fails if it cannot be started |
| in-process | `... --no-server` | skips the server; GSAS-II imported in this process |

The server amortizes GSAS-II's import (~2.6 s) over many runs (batch jobs:
0.1–0.3 s per run against 1–2 s in-process). It **caches code**, so restart it
after editing anything under `src/` it executes; since re/17 a forgotten
restart is caught: `/health` reports the PowderLine version and an MD5 of the
source tree the server loaded (`server.source_tree_hash()`), the client
compares both with its own and treats a mismatch as a **stale** server —
`auto` mode says so and runs in-process, `--use-server` fails with
`server_unavailable` naming `gsas-server restart`, and `gsas-server status`
prints `Code: STALE`.

**No shared filesystem (re/19, KI-12):** the client sends the recipe inline and
the server runs each job in a private scratch directory under its state dir;
every output file comes back base64-encoded inside the signed response
(`files`, GSAS-II's `*.bak*.gpx` backups excepted) and the client writes it
into its own `output_dir` (atomic replace, retried on Windows). A server on
another node or in a container therefore behaves like a local one; a client
that cannot write its directory fails with `backend_error`, a malformed or
oversized transfer with `communication_failed` (auto mode then runs
in-process).

**Server state and security (per user, v0.1.2):** the server binds `127.0.0.1`
on a free ephemeral port and writes its lock, PID, log, and an endpoint file
(port + random secret token) — all mode 0600 — to a private per-user state
directory: `$XDG_RUNTIME_DIR/powderline` (if it is a real directory owned by
you), else `<tempdir>/powderline-<uid>` on POSIX (mode 0700; refused if it is a
symlink, owned by someone else, or group/other-accessible, or if the temp
directory would let others replace it), and `%LOCALAPPDATA%\powderline` on
Windows. On POSIX the files are opened relative to a re-verified, no-follow
directory handle.

The token never travels over the wire: every request carries a fresh nonce, a
timestamp and an HMAC-SHA256 over method, path, nonce, timestamp and body, and
the server rejects anything unsigned, wrongly signed, stale, or replayed — on
every route, including 404/405/422 — before reading the body. Every response
is signed back over the nonce, status and body, and the client discards
unsigned responses. Other users on a shared host therefore can neither submit
jobs to your server nor impersonate it (e.g. by taking over the port of a
crashed server). `gsas-server start` takes a kernel-held lock (`flock` /
`msvcrt.locking` on `server.lock`) for the server's lifetime; the OS releases
it when the process exits, so concurrent auto-starts never spawn duplicates
and leftover PID files can never make a dead server look alive.

**One refinement at a time:** the server runs `/simulate` requests strictly in
sequence (GSAS-II's module-level state is not thread-safe); concurrent clients
queue (up to the ASGI thread pool's size, 40 by default; `/health` is not
behind the lock). **Port problems are reported, not crashed:** a malformed
`POWDERLINE_SERVER_PORT` is refused up front by `gsas-server start` and by a
client about to auto-start (`ExecutionBackendError`, `server_unavailable`,
naming the variable); a busy port fails the start before GSAS-II is imported,
with the port named, and a client whose auto-started server exits at start
reports the exit and points at the server log.

**Pin the server port** (only if needed — the default ephemeral port avoids
collisions between users):
```bash
export POWDERLINE_SERVER_PORT=19472
pixi run -e gsasii gsas-server start
pixi run -e gsasii kicker input.json  # the client reads the port from your state directory
```

**Disable the server entirely** (shared workstations, locked-down deployments):
```bash
export POWDERLINE_NO_SERVER=1   # also: true / yes / on
```
With it set, `execution_mode='auto'` (and the CLI default) runs in-process and
never starts a server, `execution_mode='server'` / `--use-server` fail with a
clear error, and `pixi run -e gsasii gsas-server start|restart` refuse.

**View server logs** (`server.log` in the state directory; `status` prints the path):
```bash
pixi run -e gsasii gsas-server logs
```

### Adding a new recipe field (any engine)

1. **Schema**: add the field to the engine's `schema.py` (unit metadata,
   validators, refusals; for a structural quantity, to `schema_core`).
2. **Gateway**: consume it from the validated model in the runtime layer
   (gsasii: a non-frozen module, or a ledger row for a frozen read).
3. **Fixture + golden**: a native recipe stating it and the engine's output.
4. **Example** if it is a real case: `examples/<case>/` with `DESCRIPTION.md`
   and, for gsasii, the committed output (regression reference).
5. **Docs**: `scripts/gen_schema_field_tables.py`, SCHEMA_HISTORY, the
   input-guidance / engine-behaviour pages as needed, CHANGELOG.

### Adding a new example

Examples drive schema evolution; see `examples/CONTRIBUTING_EXAMPLES.md`.
Directory `examples/<case>/` with `input.json` (the `gsasii.*` recipe),
`DESCRIPTION.md`, `output/` (committed GSAS-II results as regression
references), and optionally `topas/input.json`, `easydiffraction/input.json`
with a README each (no TOPAS or easydiffraction output under `examples/`;
TOPAS 6 goldens live in `tests/data/topas/native/golden/`).

### Running tests

Every test carries exactly one suite marker (`pyproject.toml`
`[tool.pytest.ini_options] markers`; `tests/conftest.py` refuses a collection
where one is missing or doubled), and the pixi tasks select on them:

```bash
# Engine-free suites (core + topas_gen): any env, the default one included.
# Installs the core guard: an engine import or a tc.exe run fails loudly.
pixi run test

# Engine suites, each in its env (the slow regressions are part of test-gsasii)
pixi run -e gsasii test-gsasii
pixi run -e easydiffraction test-easydiffraction

# TOPAS: generation everywhere; topas_exec needs tc.exe (none exists yet)
pixi run test-topas

# Everything, in the dev env -- the pre-merge gauntlet
pixi run test-all

# Extra pytest arguments pass through
pixi run test -x -k schema
pixi run -e gsasii test-gsasii -m "gsasii and not slow"
```

Markers: `core` (imports no engine, runs no engine subprocess -- the schema
layer of every gateway included), `gsasii`, `topas_gen` (engine-free TOPAS
input generation), `topas_exec` (tc.exe), `easydiffraction`, plus the optional
`slow` (a full refinement runs). `POWDERLINE_CORE_GUARD=1` forces the guard on
for a path or `-k` selection; `=0` turns it off.

**Regression test strategy:**
- Rwp, unit cell parameters and refined values compared within the tolerances
  of `regression-tolerance.md`; peak lists by row count
- Detects any change in the engine's refinement result
- Reference outputs committed to git for comparison
- If a test fails: inspect the `.lst` file to determine whether the change is
  expected or a bug; a new engine version goes through `engine-versions.md`


Suite map: `test_schema_core`, `test_symmetry_core`,
`test_symmetry_characterization` (core rules; all 230 groups against
GSAS-II's site tables), `test_phase_canary` (engine phase models cannot
weaken core), `test_api`, `test_cli`, `test_registry`, `test_compat`,
`test_exceptions`, `test_fitstats`, `test_reports` (core), `test_gsasii_schema`,
`test_gsasii_schema_engine` (GSAS-II's reading of every setting),
`test_gsasii_native_run`, `test_example_LaB6_regression`, `test_esd_extraction`,
`test_per_parameter_flags`, `test_run_refinement_missing_keys`,
`test_constraints_mapping`, `test_code_hash`, the server/client tests
(gsasii), `test_topas_schema`, `test_topas_native`, `test_topas_native_golden`
(12 INPs byte-identical to the TOPAS 6 goldens),
`test_topas_runner` (topas),
`test_easydiffraction_schema`, `test_easydiffraction_native`,
`test_easydiffraction_space_groups` (easydiffraction),
`test_convert_recipe_026` (the migration tool), `test_cross_engine_comparison`,
`test_simulation_builder` (the structure → simulation-recipe builder).

**Regression strategy:** the gsasii examples' outputs are compared within
the tolerances of [regression-tolerance.md](regression-tolerance.md)
(`tests/subprocess_utils.py`: `refined_params_match`, `unit_cell_match`),
peak lists by row count, GSAS-II's own `.lst` wR as a freeze tripwire and the
uniform `rwp` against a recorded value; TOPAS and easydiffraction against
their goldens (easydiffraction cell rtol 1e-4, values 1e-3). If a regression
test fails, inspect the engine's log and the deliberate-changes policy before
touching a reference. Some gsasii cases need a working GSAS-II refinement
and can fail for environment reasons: compare against the baseline run.

### Documentation

`pixi run docs` builds with `-W --keep-going` and `nitpicky`; zero warnings
is the standard. Pages under `docs/_generated/` are written by scripts
(`gen_schema_field_tables.py`: field tables and support matrix;
`cross_engine_comparison.py`: the comparison tables) and pulled in with MyST
`{include}`; regenerate them with the change that affects them. `api.rst`
documents the public API; the schema contract is the generated field tables.

### Template file detection

The CLI refuses a recipe whose path contains `template` or whose payload lacks
the blocks its workflow needs (`xrd_data`, `instrument`, `refinement_controls`
and `phases` or `single_peaks`), pointing at the examples. It is a CLI-only
guard: `powderline.run()` trusts its caller.

## Key gotchas

- **Restart the GSAS-II server** after code changes; a stale server is the
  usual cause of "my fix has no effect".
- **`pixi reinstall powderline --all`** after touching entry points or
  `[project.scripts]`, or when the registry reports no gateways (KI-13).
- **Frozen modules** change only through the ledger; `test_code_hash` guards
  them; `pixi run update-code-hash` after a signed edit.
- **Generated docs** go stale silently unless regenerated
  (`gen_schema_field_tables.py --check`).
- **Parameter correlation warnings** from GSAS-II (`gsasii_refinement_message`:
  "parameters 0 and 1 are 99.8% correlated") are normal for
  over-parameterized models (background terms, U/V/W, size vs strain);
  they matter when a fit does not converge or values are unphysical.
- **Chebyshev coefficients** are indexed from the constant term; their basis
  spans the fit window's first and last data points in every engine.
- **Single peak fitting**: `gsasii.spf` widths are σ² (centidegree²) and γ
  (centidegree), each ≥ 0.001; with `use_instrument_profile: true` the
  widths come from U..Z and the peaks' own width flags must be `false`
  (GSAS-II would ignore them silently); `topas.spf` peaks are `xo_Is` with
  the instrument peak type convolved with their own `gauss_fwhm` / `lor_fwhm`.
  gsasii writes `single_peaks_report.txt` (position, intensity, σ, γ, FWHMs,
  integral breadths, convergence) and `peak_convergence_diagnostics.txt` only
  when a peak did not converge.
- **Error handling**: validation errors are pydantic's, listed together;
  PowderLine's own errors derive from `PowderLineError`; the CLI exits 1 on
  any failure.

## The simulation recipe builder

`powderline.gateways.gsasii.simulation_builder.SimulationRecipeBuilder` turns a
crystal-structure dict (`space_group`, `unit_cell`, `atoms`, `formula`) into a
`gsasii.rietveld` 0.1.0 simulation recipe: the conventional cell reduced to
symmetry-unique sites with an orbit self-check, two-origin groups moved to
origin choice 2, the canonical space-group name, every default stated, SH/L
0.002, instrument defaults from `.powderline_config.yaml`'s
`simulation_defaults`. The Materials Project fetch and `.chi` export that
drove it (`mp-simulate`) left PowderLine in 0.2.0 (P-36); RandomXRD carries
its own copy. The recipe's `metadata.materials_project` block (material id,
formula, the space group as stated) keeps its name: it is what the tests and
RandomXRD's copy read, and a source-neutral key is a shape decision for the
maintainer.

## Future roadmap

- The TOPAS halves of ionic scattering types (T7) and March–Dollase
  preferred orientation (T9) on a TOPAS 6 machine; a later minor gsasii
  schema version with bounds (clamp-freeze-refit); TOPAS 7 after a
  compatibility run on a TOPAS 7 machine; `unsafe_mode` for deliberately
  relaxed checks; a recipe builder / CIF importer upstream of the schemas;
  a structure-source plugin (Materials Project, CIF) upstream of the builder.

## Contributing

Key principles for future work:
- Add features when real examples need them (not speculatively)
- Every rule in the schema; every engine quirk refused or warned about, and
  recorded in the engine-behaviour register
- Behaviour changes are deliberate, recorded and reviewed; references move
  only with an equivalence record
- Frozen modules through the ledger; "ask, don't assume" on any open
  decision ([policies](policies.md))
- Add regression tests, fixtures and goldens for new capabilities

Questions? Open an issue or discussion on GitHub.
