# Using PowderLine in Other Projects

PowderLine is not yet on conda-forge or PyPI. In the meantime, it can be used in
other local projects via an **editable install** that points directly at the repository.
Changes to PowderLine source are picked up immediately — no reinstall required.

Two usage tracks are documented here:

- **Full** — schema validation + refinement execution (requires GSAS-II)
- **Schema-only** — validation only (pydantic is the only non-trivial dependency)

Template pixi.toml files and runnable example scripts live in `docs/integration/`.

---

## Track A: Full (Schema + Refinement)

Use this track when your project needs to run Rietveld refinements or single peak
fitting, not just validate recipes.

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
GSAS-II = { git = "https://github.com/tacaswell/GSAS-II", rev = "enh/pixi_pkg" }

[pypi-dependencies]
powderline = { path = "/path/to/PowderLine", editable = true }  # ← change this path
```

`GSAS-II` is declared as a conda package built via `pixi-build` from the
`tacaswell/GSAS-II` fork (which adds the conda recipe), mirroring PowderLine's own
`pixi.toml`. This installs GSAS-II on all supported platforms
(linux-64/win-64/osx-arm64). It is not on PyPI or conda-forge, so it must be declared
in your own workspace rather than pulled in transitively by PowderLine.

> **Reproducibility tip**: pin `GSAS-II` to the same `rev` PowderLine uses (see the
> `[dependencies]` block in the repo's `pixi.toml`) rather than a moving upstream
> branch, because GSAS-II profile-calculation changes can shift refinement results.

### 3. Install

```bash
cd /path/to/your-project
pixi install
```

### 4. Verify

```bash
pixi run python -c "import powderline; print(powderline.__version__)"
```

---

## Track B: Schema-Only (Validation Without GSAS-II)

Use this track for tools that construct or validate recipe JSON files (recipe builders,
editors, CI pre-flight checks) without needing to run refinements. The environment
is dramatically smaller — GSAS-II, wxpython, and all related native packages are
not installed.

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
pixi run python -c "from powderline.schema import RecipeModel; print('OK')"
```

---

## API Surface

The imports a consuming project will use:

| Import | Purpose | Track |
|---|---|---|
| `from powderline.schema import RecipeModel` | Validate recipe dicts with Pydantic | Both |
| `powderline.validate()` | Validate a recipe dict (returns a `RecipeModel`); raises on invalid input. Adds the simulation-mode check to the schema validation | Full only |
| `powderline.load_recipe_asset()` | Load a recipe from a `.json`/`.yaml`/`.txt` file into a dict | Full only |
| `powderline.run()` | Primary programmatic entry point (validates + runs + returns DataFrames). Pass `validate_only=True` to validate without refining | Full only |
| `from powderline.gsas_client import GSASClient` | Run via the persistent GSAS-II server | Full only |

`powderline.validate()` and `powderline.load_recipe_asset()` are exported only
when GSAS-II is installed, so they are not available on the schema-only track.
There, validate with `RecipeModel.model_validate()` (below) and load JSON or
YAML yourself. `RecipeModel.model_validate()` runs the same schema checks but
not the simulation-mode check (no refine flag may be `true` when
`refinement_cycles` is 1).

### Schema validation

```python
import json
from pathlib import Path
from pydantic import ValidationError
from powderline.schema import RecipeModel

recipe_dict = json.loads(Path("input.json").read_text())

try:
    recipe = RecipeModel.model_validate(recipe_dict)
except ValidationError as exc:
    for error in exc.errors():
        loc = " -> ".join(str(l) for l in error["loc"])
        print(f"[{error['type']}] {loc}: {error['msg']}")
```

### Programmatic refinement (`powderline.run()`)

The recommended entry point for new callers. Validates the recipe, dispatches to the
GSAS-II server (or falls back to in-process execution), and returns results as pandas DataFrames.

```python
import json
from pathlib import Path
import powderline

recipe = json.loads(Path("input.json").read_text())
result = powderline.run(recipe, Path("output/"))

# result keys (tabular outputs are pandas DataFrames; per-phase tables are
# dicts of DataFrames keyed by phase name):
# result['success']                  bool
# result['rwp']                      float
# result['elapsed_time']             float
# result['method']                   str  (which execution path was used)
# result['fit_profile']              DataFrame
# result['unit_cell_data']           dict[str, DataFrame]  (keyed by phase name)
# result['peak_list_data']           dict[str, DataFrame]  (keyed by phase name)
# result['refined_parameters']       DataFrame  (9-column table with ESDs)
# result['spf_peaks']                DataFrame  (SPF mode; empty for Rietveld)
# result['spf_convergence_diagnostics'] DataFrame
# result['output_files']             list[str]
```

**Execution mode** can be controlled with the `execution_mode` parameter:

```python
# 'auto' (default): tries server first, falls back to subprocess
# 'server':         HTTP server only (fails if unavailable)
# 'subprocess':     in-process fallback (always available, slower for repeated calls)
result = powderline.run(recipe, Path("output/"), execution_mode='server')
```

### Server-based refinement (`GSASClient`)

```python
from powderline.gsas_client import GSASClient

client = GSASClient(fallback_to_subprocess=True)
result = client.submit_simulation(
    recipe=Path("input.json"),  # also accepts a dict or RecipeModel
    output_dir=Path("output/"),
    auto_start_server=True,
)
```

---

## Choosing an Execution Mode

Both `powderline.run()` and `GSASClient` produce identical output files and results.
The difference is startup overhead:

| Mode | When to use | GSAS-II startup cost |
|---|---|---|
| `powderline.run()` (auto) | Default for single scripts; tries server then falls back | Avoided if server is running |
| `GSASClient` (server) | Batch pipelines, interactive tools, repeated calls in one session | Paid once per server lifetime (~10 s) |

`GSASClient` with `auto_start_server=True` will start the server automatically if
not running and fall back to subprocess mode if the server fails to start.
`powderline.run()` uses `GSASClient` internally.

The server is per-user: it is started as, and only accepts jobs from, the
calling user (requests and responses signed with a secret token kept in a
private state directory; loopback only), so it is safe on shared hosts. Integrations that must never run a background server
can set `POWDERLINE_NO_SERVER=1`: `auto` then runs in-process, `server` mode
returns an error result, and no server is ever started.

---

## Example Scripts

`docs/integration/example_full.py` — runnable demonstration of the main import patterns.

`docs/integration/example_schema_only.py` — runnable demonstration of schema validation
and batch validation without importing GSAS-II.

Both scripts have a `POWDERLINE_REPO` constant at the top that you must edit to point
at your local clone.

---

## Using the easydiffraction Engine (Optional)

PowderLine supports the open-source easydiffraction Rietveld engine via
`engine="easydiffraction"`. This requires the optional `easydiff` pixi environment
(easydiffraction needs Python ≥3.12; the default environment stays at ≥3.10):

```bash
pixi install -e easydiff
```

```python
import powderline
result = powderline.run(recipe, "output", engine="easydiffraction")
```

**v1 capabilities:** translates unmodified `GSASII_Rietveld` recipes; supports unit-cell,
scale, wavelength, Chebyshev background, Caglioti U/V/W + Lorentzian X/Y broadening,
and zero-shift refinement; multi-phase; simulation mode (no refinement flags set).
Rejects loudly (translation error) atom-level refinement flags, Kα₁/Kα₂ two-wavelength
recipes, refined Z / polarization / axial divergence / background peaks, and SPF
recipes. Fixed anisotropic ADP values are not modeled and are dropped with a warning.

**Profile model:** a nonzero `SH/L` automatically selects the Thompson–Cox–Hastings
profile with fixed FCJ axial-divergence asymmetry (CrysFML calculator; hkl peak lists
are recovered with a post-fit CrysPy calculation). On the identical LaB6 recipe,
GSAS-II reaches Rwp 6.01% vs easydiffraction 9.63% (both χ² < 1); the remaining gap
comes from background peaks (not modeled) and residual profile differences, so
**compare lattice parameters, not Rwp, across engines** — Rwp is not an
apples-to-apples metric.

For the engine architecture and how to add a backend, see the
**Adding a Refinement Engine** section of the [developer guide](DEVELOPMENT.md).
The full design dossier and backend survey live in the private
[PowderLine-devkit](https://github.com/NSLS2/PowderLine-devkit) — a maintainers'
repository; access is available on request.

---

## Future: conda-forge Distribution

When PowderLine is published to conda-forge, the editable path dependency becomes a
version pin:

```toml
# pixi_full.toml — after conda-forge release
[dependencies]
powderline = ">=1.0"
# GSAS-II may still need to be declared here until it too is on conda-forge
GSAS-II = { git = "https://github.com/tacaswell/GSAS-II", rev = "enh/pixi_pkg" }
```
