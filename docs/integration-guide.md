# Using PowderLine in Other Projects

PowderLine is not yet on conda-forge or PyPI. In the meantime, it can be used in
other local projects via an **editable install** that points directly at the repository.
Changes to PowderLine source are picked up immediately — no reinstall required,
except after a change to `pyproject.toml`'s entry points (see below).

Two usage tracks are documented here; they mirror PowderLine's own
environments:

- **Validation-only** — the schema layer of every engine, no engine installed
  (what PowderLine's default environment is).
- **Full** — validation + refinement execution with GSAS-II (what PowderLine's
  `gsasii` environment is). For easydiffraction, add its dependencies the same
  way (its feature in PowderLine's `pixi.toml`); TOPAS has no Python package.

Template pixi.toml files and runnable example scripts live in `docs/integration/`.

---

## Track A: Validation-only (no engine)

Use this track for tools that construct or validate recipe JSON files (recipe
builders, editors, CI pre-flight checks) without running refinements. The
environment is small: PowderLine's own runtime dependencies (pydantic, numpy,
scipy, gemmi, …) and nothing of GSAS-II, wxPython or easydiffraction.
`powderline.validate()` works for **every** schema here, because each gateway's
schema layer is engine-free.

### 1. Copy the template

```bash
cp /path/to/PowderLine/docs/integration/pixi_schema_only.toml /path/to/your-project/pixi.toml
```

### 2. Edit the required fields

```toml
[workspace]
name = "your-project-name"   # ← change this

[pypi-dependencies]
powderline = { path = "/path/to/PowderLine", editable = true }  # ← change this path
```

### 3. Install and verify

```bash
pixi install
pixi run python -c "import powderline; print(powderline.support_matrix())"
```

The matrix lists the three gateways with their declared schema versions. An
empty list means the editable install's metadata is missing (the gateways are
discovered through entry points; re-run `pixi install` or
`pixi reinstall powderline`).

---

## Track B: Full (validation + GSAS-II refinement)

Use this track when your project needs to run `gsasii.*` recipes (Rietveld
refinements or single peak fitting), not just validate them.

### 1. Copy the template

```bash
cp /path/to/PowderLine/docs/integration/pixi_full.toml /path/to/your-project/pixi.toml
```

### 2. Edit the required fields

Open your new `pixi.toml` and set:

```toml
[workspace]
name = "your-project-name"   # ← change this
preview = ["pixi-build"]     # required to build the GSAS-II conda package

[dependencies]
GSAS-II = { git = "https://github.com/tacaswell/GSAS-II", rev = "e0910fc19bdd829a10f0204e3e4f4eaa38ad5e0f" }

[pypi-dependencies]
powderline = { path = "/path/to/PowderLine", editable = true }  # ← change this path
```

`GSAS-II` is declared as a conda package built via `pixi-build` from the
`tacaswell/GSAS-II` fork (which adds the conda recipe), mirroring PowderLine's own
`pixi.toml` (feature `gsasii`). This installs GSAS-II on all supported platforms
(linux-64/win-64/osx-arm64). It is not on PyPI or conda-forge, so it must be declared
in your own workspace rather than pulled in transitively by PowderLine.

> **Reproducibility tip**: pin `GSAS-II` to the same `rev` PowderLine uses (the
> commit in the `[feature.gsasii.dependencies]` block of the repo's `pixi.toml`)
> rather than a moving upstream branch. The gsasii gateway checks the installed
> GSAS-II against its supported version (`==5.7.9`) at run time and refuses
> another one; GSAS-II profile-calculation changes can shift refinement results.

### 3. Install

```bash
cd /path/to/your-project
pixi install
```

### 4. Verify

```bash
pixi run python -c "import powderline; print(powderline.__version__)"
pixi run python -c "import GSASII; print(GSASII.__version__)"
```

---

## API Surface

The imports a consuming project will use (`powderline.__all__`):

| Import | Purpose | Track |
|---|---|---|
| `powderline.validate(recipe)` | Validate a recipe dict for the engine its `schema_name` names; returns a `ValidationResult` (the gateway's validated model + structured warnings); raises pydantic's `ValidationError` on invalid input | Both |
| `powderline.load_recipe_asset(path)` | Load a recipe from a `.json`/`.yaml`/`.txt` file into a dict | Both |
| `powderline.support_matrix()` | The schema versions every installed gateway declares | Both |
| `powderline.run(recipe, output_dir, **engine_options)` | Primary programmatic entry point (validates + runs + returns DataFrames). Pass `validate_only=True` to validate without refining | Full (for the engine the recipe names) |
| `powderline.PowderLineError` and its subclasses `GatewayNotInstalledError`, `EngineNotAvailableError`, `EngineVersionError`, `EngineExecutionError` | Error handling | Both |
| `from powderline.gateways.gsasii.client import GSASClient` | Run `gsasii.*` recipes via the persistent GSAS-II server | Full |

`import powderline` imports no engine; GSAS-II is imported when a `gsasii.*`
recipe runs.

### Recipe validation

```python
import json
from pathlib import Path
from pydantic import ValidationError
import powderline

recipe_dict = json.loads(Path("input.json").read_text())

try:
    checked = powderline.validate(recipe_dict)
except ValidationError as exc:
    for error in exc.errors():
        loc = " -> ".join(str(l) for l in error["loc"])
        print(f"[{error['type']}] {loc}: {error['msg']}")
else:
    model = checked.recipe            # e.g. GsasiiRietveldRecipe, TopasRietveldRecipe
    for w in checked.warnings:        # {code, message, field_path[, level]}: defaults applied, symmetry remarks
        print(w["code"], w["field_path"])
```

### Programmatic refinement (`powderline.run()`)

The recommended entry point for new callers. Validates the recipe, dispatches to
the gateway its `schema_name` names, and returns results as pandas DataFrames.

```python
import json
from pathlib import Path
import powderline

recipe = json.loads(Path("input.json").read_text())
result = powderline.run(recipe, Path("output/"))

# result keys (tabular outputs are pandas DataFrames; per-phase tables are
# dicts of DataFrames keyed by phase name); the same for every engine:
# result['status']                   "ok" | "generated"   (a failed run raises; see below)
# result['converged']                True | False | None  (None: the engine cannot report it, or a simulation)
# result['envelope_version']         "1"
# result['rwp'], ['r_exp'], ['gof'], ['chi2_red']   PowderLine's uniform statistics (None where undefined)
# result['simulation_mode']          bool
# result['engine_details']           dict: the engine's own statistics, parameters_requested / parameters_varied, ...
# result['warnings']                 list of {code, message, field_path[, level]}  (level absent = "warning", or "info")
# result['elapsed_time']             float
# result['method']                   str  (which execution path was used)
# result['fit_profile']              DataFrame
# result['unit_cell_data']           dict[str, DataFrame]  (keyed by phase name; rows cell_a … cell_volume, see schemas.md "Two vocabularies")
# result['peak_list_data']           dict[str, DataFrame]  (keyed by phase name)
# result['refined_parameters']       DataFrame  (9-column table with ESDs)
# result['spf_peaks']                DataFrame  (single peak fitting; empty for Rietveld)
# result['spf_convergence_diagnostics'] DataFrame
# result['peak_fit']                 gsasii.spf only: {'parameters': [{name, value, esd}]}, every parameter GSAS-II's peak fit varied, by its own name
# result['output_files']             list[str]
```

A failed run **raises**. Catch the two classes separately when the
distinction matters, or `PowderLineError` for both:

```python
from powderline import EngineExecutionError, ExecutionBackendError

try:
    result = powderline.run(recipe, Path("output/"))
except EngineExecutionError as e:      # the engine ran and failed: diverged, unusable_site, engine_crashed, ...
    print(e.reason, e.result["output_files"])   # the engine's own files and failure.json; no result tables
except ExecutionBackendError as e:     # the engine did not run: server_unavailable, timeout, ...
    print(e.reason)
```

**Engine options** are keyword arguments forwarded to the gateway; an option
another engine does not take is a `TypeError`:

```python
# gsasii: 'auto' (default) tries the server first, falls back to in-process;
#         'server' requires the server; 'subprocess' runs in-process
result = powderline.run(recipe, Path("output/"), execution_mode='server')
# topas:  the installed TOPAS version must be declared to run (tc.exe has none)
result = powderline.run(topas_recipe, Path("output/"), topas_version="6", topas_dir=Path(r"C:\TOPAS6"))
```

A `gsasii.*` or `easydiffraction.*` run in an environment without the engine
raises `EngineNotAvailableError`, whose message names the environment and the
install command.

### Sequential refinement: feed the output recipe back

Every result carries `output_recipe`: the recipe the engine actually saw, with
its refined values written back, that validates unchanged (KI-04). A
sequential series is therefore a loop over data, not over parameter names:

```python
import powderline
from powderline.recipes import with_block

recipe = powderline.load_recipe_asset("step_000/input.json")
for i, xrd_data in enumerate(series):            # each a core xrd_data block: tth, Itth, Itth_weights
    result = powderline.run(recipe, f"step_{i:03d}")
    if not result["output_recipe_valid"]:        # an engine value the schema refuses: look, then decide
        print(result["warnings"][-1]["message"]); break
    recipe = with_block(result["output_recipe"], "payload.xrd_data", xrd_data)
```

`parameter_dispositions` (also `parameter_dispositions.csv`) tells you, per
recipe path, whether the value was `varied`, `held_by_user`, `held_by_symmetry`,
`requested_not_varied` or `default_applied`, with its ESD and whether it ended
at a limit. `powderline.recipes.block` / `with_block` move only core blocks
(`payload.xrd_data`, `payload.fit_range`, `payload.phases.<name>`) between
recipes; an engine's own blocks stay in that engine's terms.

A complete, runnable instance of this loop is
`examples/example_LaB6_temperature_series/`: six simulated LaB6
patterns from 25 to 500 °C with a programmed thermal expansion (Akdoğan &
Payzant, J. Appl. Cryst. 2025) and Poisson noise, refined in sequence through the
output recipe by `run_series.py`; its committed `output/series_report.csv`
shows every refined cell within 1.5 ESD of the programmed value, and the
regression test re-runs the chain. The same runner drives the easydiffraction
leg of the series from `easydiffraction/input.json`: the loop never looks at
the engine, because only the core `xrd_data` block moves.

### Server-based refinement (`GSASClient`)

```python
from pathlib import Path
from powderline.gateways.gsasii.client import GSASClient

client = GSASClient(fallback_to_subprocess=True)
result = client.submit_simulation(
    recipe=Path("input.json"),  # also accepts a dict or a validated gsasii model
    output_dir=Path("output/"),
    auto_start_server=True,
)
```

---

## Choosing an Execution Mode (gsasii)

Both `powderline.run()` and `GSASClient` produce identical output files and results.
The difference is startup overhead:

| Mode | When to use | GSAS-II startup cost |
|---|---|---|
| `powderline.run()` (auto) | Default for single scripts; tries server then falls back | Avoided if server is running |
| `GSASClient` (server) | Batch pipelines, interactive tools, repeated calls in one session | Paid once per server lifetime (~10 s) |

`GSASClient` with `auto_start_server=True` will start the server automatically if
not running and fall back to in-process execution if the server fails to start.
`powderline.run()` uses `GSASClient` internally for `execution_mode='auto'` and
`'server'`.

The server is per-user: it is started as, and only accepts jobs from, the
calling user (requests and responses signed with a secret token kept in a
private state directory; loopback only), so it is safe on shared hosts. Integrations that must never run a background server
can set `POWDERLINE_NO_SERVER=1`: `auto` then runs in-process, `server` mode
returns an error result, and no server is ever started.

---

## Example Scripts

`docs/integration/example_schema_only.py` — validates one recipe, then every
committed example recipe of every engine, with no engine installed. Runs as is
from a PowderLine checkout: `pixi run python docs/integration/example_schema_only.py`.

`docs/integration/example_full.py` — validation, a `powderline.run()` refinement
and a `GSASClient` run of the LaB6 example; needs GSAS-II:
`pixi run -e gsasii python docs/integration/example_full.py`.

Both scripts default `POWDERLINE_REPO` to the clone they sit in; edit the
constant if you copy them elsewhere.

---

## Entry points and re-installs

The gateways are discovered from the `powderline.gateways` entry-point group of
the installed distribution. Entry-point metadata is written at install time, so
after PowderLine changes its `pyproject.toml` entry points (or
`[project.scripts]`), re-run `pixi install` or `pixi reinstall powderline` in
your project; a `GatewayNotInstalledError` saying no entry points were found
means exactly that (PowderLine's known issue KI-13). Importing PowderLine from
source with `PYTHONPATH` and no installed distribution has the same effect.

---

## Future: conda-forge Distribution

When PowderLine is published to conda-forge, the editable path dependency becomes a
version pin:

```toml
# pixi_full.toml — after conda-forge release
[dependencies]
powderline = ">=0.2"
# GSAS-II may still need to be declared here until it too is on conda-forge
GSAS-II = { git = "https://github.com/tacaswell/GSAS-II", rev = "e0910fc19bdd829a10f0204e3e4f4eaa38ad5e0f" }
```
