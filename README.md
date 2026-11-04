# PowderLine

[![Docs](https://img.shields.io/badge/docs-live-blue)](https://nsls2.github.io/PowderLine/)

Automated powder X-ray diffraction refinement. You describe a refinement in a
JSON "recipe"; PowderLine runs it through the refinement engine the recipe
names — [GSAS-II](https://gsasii.github.io/), Bruker TOPAS 6, or the
open-source [easydiffraction](https://easydiffraction.org) — and returns
standardized result tables.

**Documentation:** [nsls2.github.io/PowderLine](https://nsls2.github.io/PowderLine/)
· **New here? Start with the [Quickstart](docs/quickstart.md).**

PowderLine gives you a programmatic, reproducible way to run Rietveld refinements
and single-peak fits without hand-driving the underlying refinement software.

- **One recipe = one engine.** A recipe's `schema_name` names the engine and
  workflow (`gsasii.rietveld`, `gsasii.spf`, `topas.rietveld`, `topas.spf`,
  `easydiffraction.rietveld`) and is written in that engine's own
  conventions and units; nothing is translated between engines.
- **Refine what you need:** unit cell, atom coordinates, occupancies, isotropic and
  anisotropic displacement parameters, background, peak broadening and
  March–Dollase preferred orientation, with ionic scattering types per atom —
  each parameter individually flagged, and checked against the space-group
  symmetry before any engine runs.
- **Honest statistics:** every engine returns the same uniform Rwp / Rexp /
  GoF over the same data points, with the engine's own values kept alongside.
- **Strict validation, engine-free:** a recipe validates in a core-only
  environment; every problem is reported at its field, and engine quirks are
  refused or warned about, never papered over.
- **Standardized outputs:** fixed-filename CSV/TXT reports plus each engine's
  native artifacts (the GSAS-II `.gpx`, the TOPAS `.inp` and output files).

## 1. Install

PowderLine uses [pixi](https://pixi.sh) for reproducible conda environments.
The **default environment is core-only** (schema validation, the CLI, no
engine); each engine lives in its own environment:

```bash
git clone https://github.com/NSLS2/PowderLine.git
cd PowderLine
pixi install                      # core only: validate recipes, no engine
pixi install -e gsasii            # + GSAS-II (built as a conda package by pixi-build)
pixi install -e easydiffraction   # + easydiffraction (Python >= 3.12)
pixi install -e all               # every engine
# fresh checkout: add --frozen (e.g. `pixi install --frozen -e gsasii`) so the committed lock is used as is
```

Platforms: `linux-64`, `win-64`, `osx-arm64`. TOPAS has no Python package:
`topas.*` recipes validate everywhere and their input files are written
everywhere, but running them needs a Windows machine with TOPAS 6 (`tc.exe`).

## 2. Getting started

Run the bundled LaB6 calibrant example with GSAS-II:

```bash
pixi run -e gsasii kicker examples/example_LaB6/input.json
```

Results are written next to the recipe in `examples/example_LaB6/output/`:

| File | What it is |
|---|---|
| `refined_parameters.csv` | Every refined parameter with its ESD (9-column table) |
| `LaB6_unit_cell_report.csv` | Per-phase unit-cell parameters + ESDs |
| `LaB6_peak_list_report.csv` | Reflection list (hkl, d-spacing, 2θ, intensity) |
| `fit_profile.txt` | Observed / calculated / background / difference |
| `output_recipe.json`, `parameter_dispositions.csv` | The recipe with the refined values written back, and how each value came about |
| `dummy.lst` | Human-readable GSAS-II refinement log (Rwp, parameter tables) |
| `dummy.gpx` | GSAS-II project — reopenable in the GSAS-II GUI |

PowderLine removes its own fixed-name files from the output directory before
each run, so a reused directory holds one run's results. A failed run raises,
and its directory holds the engine's own files plus `failure.json` (the reason,
the message and the engine's last console lines) — never a result table.

The same case as a TOPAS and an easydiffraction recipe sits in
`examples/example_LaB6/topas/` and `examples/example_LaB6/easydiffraction/`.

> `examples/example_template/` holds fill-in-the-blanks skeletons for the
> three engines, not runnable recipes — copy one to start your own.

## 3. Ways to use PowderLine

**Command line** — one command for every engine; the recipe's `schema_name`
decides where it runs:

```bash
pixi run kicker <recipe.json> --validate-only     # check a recipe; needs no engine
pixi run -e gsasii kicker <recipe.json>           # run a gsasii.* recipe
pixi run -e easydiffraction kicker <recipe.json>  # run an easydiffraction.* recipe
pixi run kicker <recipe.json> --topas-dir C:/TOPAS6 --topas-version 6   # run a topas.* recipe (tc.exe on Windows)
pixi run -e gsasii doctor                                                  # what this environment can do (gateways, engines, server)
```

After `pixi reinstall powderline` the same program is the installed command
`powderline <recipe.json> …`. Flags: `--output DIR` (default: `output/` next
to the recipe), `--verbose`, `--validate-only`; gsasii `--use-server` /
`--no-server`; topas `--topas-dir DIR` / `--topas-version V` /
`--topas-timeout SECONDS` (default 3600; 0 = no limit). A flag given
for a recipe of another engine is an error.

**Python API** — load a recipe, run it, get pandas DataFrames back:

```python
import powderline, tempfile
from pathlib import Path

recipe = powderline.load_recipe_asset(Path("examples/example_LaB6/input.json"))

# Engine-free check: every problem at its field path; warnings for defaults applied
checked = powderline.validate(recipe)
print(checked.recipe.schema_name, checked.warnings)

# run() writes its file reports into the directory you give it; the engine is
# the one the recipe names, so this needs the gsasii environment:
result = powderline.run(recipe, Path(tempfile.mkdtemp()))

print(result["rwp"])                      # PowderLine's uniform Rwp (%)
print(result["engine_details"])           # GSAS-II's own statistics, parameters requested vs varied
print(result["refined_parameters"])       # DataFrame of refined values + ESDs
```

The returned dict holds the fit metadata (`status`, `converged`, `rwp`, `r_exp`,
`gof`, `chi2_red`, `simulation_mode`, `engine_details`, `warnings`, elapsed time,
which execution path ran, the output recipe with its parameter dispositions; a
failed run raises instead of returning) plus every
tabular report in memory — the refined-parameter table with ESDs, the fit
profile, per-phase unit-cell and peak-list tables (dicts keyed by phase
name), and the SPF peak tables when single-peak fitting. Everything the
CSV/TXT files contain, without touching disk yourself.

The public API (`powderline.__all__`) is `run`, `validate`,
`ValidationResult`, `load_recipe_asset`, `support_matrix` and the exceptions
`PowderLineError`, `GatewayNotInstalledError`, `EngineNotAvailableError`,
`EngineVersionError`, `EngineExecutionError`. `import powderline` imports no
engine.

**The GSAS-II server (used by default for gsasii recipes)** — refinements go
through a persistent server that keeps GSAS-II resident in memory
(auto-started as needed), a large speedup across many refinements. Manage it
directly, or opt out per run with `--no-server`:

```bash
pixi run -e gsasii gsas-server status                 # start | status | stop | restart | logs
pixi run -e gsasii kicker <recipe.json> --no-server   # force an isolated in-process run
```

The server is per-user: it listens on loopback only and accepts only requests
signed with a secret token kept in a directory only you can read; your client
in turn only accepts results signed with that token, so other users on the
same machine can neither use your server nor impersonate it. To switch it off
— e.g. on a shared workstation — set `POWDERLINE_NO_SERVER=1`: default
(`auto`) runs then go in-process, explicit server mode (`--use-server` /
`execution_mode='server'`) fails, and nothing is auto-started.

## 4. Refinement engines

| Engine | Schemas | Environment | Notes |
|---|---|---|---|
| **GSAS-II 5.7.9** | `gsasii.rietveld`, `gsasii.spf` | `gsasii` | The reference engine; the committed examples carry its outputs as regression references. |
| **TOPAS 6** (Bruker) | `topas.rietveld`, `topas.spf` | any (writing the INP); Windows + `tc.exe` (running) | The recipe states `engine_version: "6"`; the run needs the installed version and location declared (`--topas-version 6 --topas-dir DIR`, or `topas.version` / `topas.dir` in `.powderline_config.yaml`); PowderLine never guesses where `tc.exe` is. |
| **easydiffraction 0.21.1** | `easydiffraction.rietveld` | `easydiffraction` | The recipe states the calculator (`cryspy` or `crysfml`); no single-peak fitting. |

The structural part of a recipe (space group, cell, atoms) is identical in
every engine; the instrument, background and controls are each engine's
own, with its own units. The
[cross-engine comparison](docs/cross-engine-comparison.md) refines the same
two data sets with every engine and explains why the numbers differ:
**compare lattice parameters, and read Rwp as a property of the model, not
of the engine.** What each engine does with your recipe, and what PowderLine
refuses on its behalf, is on the
[engine behaviour page](docs/engine-behavior.md).

For the engine architecture and how to add a backend, see
[Adding a refinement engine](docs/DEVELOPMENT.md#adding-a-refinement-engine).
The design dossier and backend survey live in the private
[PowderLine-devkit](https://github.com/NSLS2/PowderLine-devkit) (maintainers can
request access).

## Documentation

- **[Quickstart](docs/quickstart.md)** — clone → install → run → read the output.
- **[Getting Started](docs/getting-started.rst)** — recipe structure, output
  files, and the Python API.
- **[Recipe schemas](docs/schemas.md)**, **[Fields and features](docs/fields.md)**,
  **[Input guidance](docs/input-guidance.md)** — the five schemas, every field
  with its unit, how to supply data / structures / instruments.
- **[Engine behaviour notes](docs/engine-behavior.md)** — what each engine
  does, and PowderLine's policy toward it.
- **[Troubleshooting](docs/TROUBLESHOOTING.md)** — common errors and fixes.
- **[Migration guide](docs/migration-0.26-to-1.0.md)** — from PowderLine 0.1.1
  (unified schema 0.26.0) to 0.2.0 (core + engine schemas 1.0.0).
- **[Schema History](docs/SCHEMA_HISTORY.md)** and the
  **[support matrix](docs/support-matrix.md)** — schema versions and declared
  compatibility.
- **[Using PowderLine as a library](docs/integration-guide.md)** — install it into
  another project.
- **[Developer Guide](docs/DEVELOPMENT.md)** and **[Policies](docs/policies.md)**
  — architecture, how to add an engine, versioning, frozen code, review
  gates. See also the [known-issues register](docs/known_issues.md)
  (`KI-NN` ids referenced from code and docs).

## Citation

If you use PowderLine in your research, please cite the preprint:

> A. A. Corrao, J. A. Perez, J. D. Langhout, M. M. Butala, T. A. Caswell, and
> D. Olds. *PowderLine: a programmatic powder diffraction analysis application.*
> arXiv:2608.17009 (2026).
> [doi:10.48550/arXiv.2608.17009](https://doi.org/10.48550/arXiv.2608.17009)

Machine-readable metadata is in [`CITATION.cff`](CITATION.cff).

## License

BSD 3-Clause — see [LICENSE](LICENSE).
