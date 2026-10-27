# PowderLine

[![Docs](https://img.shields.io/badge/docs-live-blue)](https://nsls2.github.io/PowderLine/)

Automated powder X-ray diffraction refinement. You describe a refinement in a
JSON "recipe"; PowderLine runs it through a refinement engine —
[GSAS-II](https://gsasii.github.io/) by default, or Bruker TOPAS v7 or the
open-source easydiffraction — and returns standardized result tables.

**Documentation:** [nsls2.github.io/PowderLine](https://nsls2.github.io/PowderLine/)
· **New here? Start with the [Quickstart](docs/quickstart.md).**

PowderLine gives you a programmatic, reproducible way to run Rietveld refinements
and single-peak fits without hand-driving the underlying refinement software.

- **Two workflow types:** Rietveld refinement (`GSASII_Rietveld`) and single-peak
  fitting (`GSASII_SPF`).
- **Refine what you need:** unit cell, atom coordinates, occupancies, isotropic and
  anisotropic displacement parameters, background, and peak broadening — each
  parameter individually flagged.
- **Three engines, one recipe:** GSAS-II by default, Bruker TOPAS v7
  (`engine="topas"`), or open-source easydiffraction
  (`engine="easydiffraction"`) — the TOPAS and easydiffraction paths import
  zero GSAS-II.
- **Materials Project integration:** simulate a pattern from a crystal structure.
- **Standardized outputs:** fixed-filename CSV/TXT reports plus a GSAS-II `.gpx`.

## 1. Install

PowderLine uses [pixi](https://pixi.sh) for reproducible conda environments.
GSAS-II is installed **automatically** by `pixi install` (it ships as a conda
package — no separate GSAS-II install).

```bash
git clone https://github.com/NSLS2/PowderLine.git
cd PowderLine
pixi install
```

Platforms: `linux-64`, `win-64`, `osx-arm64`. Running a recipe through TOPAS
additionally requires a Windows machine with `tc.exe` installed; generating the
TOPAS input files needs no TOPAS and no GSAS-II.

## 2. Getting started

Run the bundled LaB6 calibrant example:

```bash
pixi run kicker examples/example_LaB6/input.json
```

Results are written next to the recipe in `examples/example_LaB6/output/`:

| File | What it is |
|---|---|
| `refined_parameters.csv` | Every refined parameter with its ESD (9-column table) |
| `LaB6_unit_cell_report.csv` | Per-phase unit-cell parameters + ESDs |
| `LaB6_peak_list_report.csv` | Reflection list (hkl, d-spacing, 2θ, intensity) |
| `fit_profile.txt` | Observed / calculated / background / difference |
| `dummy.lst` | Human-readable GSAS-II refinement log (Rwp, parameter tables) |
| `dummy.gpx` | GSAS-II project — reopenable in the GSAS-II GUI |

> `examples/example_template/` is a fill-in-the-blanks skeleton, not a runnable
> recipe — copy it to start your own.

**Bringing your own CIF, instrument, and data files?** PowderLine has no
built-in recipe builder; see [Building Recipes](docs/building-recipes.md) for
starting points, validation, and helper code you can adapt.

## 3. Ways to use PowderLine

**Command line** — run or validate a recipe:

```bash
pixi run kicker <recipe.json>                  # run a refinement
pixi run kicker <recipe.json> --validate-only  # check a recipe without running it
pixi run topas-kicker <recipe.json>            # generate a TOPAS v7 .inp + .xye
```

Other flags: `--output DIR` (default: `output/` next to the recipe) and
`--verbose`.

**Python API** — load a recipe, run it, get pandas DataFrames back:

```python
import powderline, tempfile
from pathlib import Path

recipe = powderline.load_recipe_asset(Path("examples/example_LaB6/input.json"))

# run() writes its file reports into the directory you give it; if you only
# want the in-memory results, a throwaway temp dir works fine:
result = powderline.run(recipe, Path(tempfile.mkdtemp()))

print(result["rwp"])                 # weighted profile R-factor
print(result["refined_parameters"])  # DataFrame of refined values + ESDs

# Same recipe, TOPAS engine:
result = powderline.run(recipe, Path(tempfile.mkdtemp()), engine="topas")
```

The returned dict holds more than the two keys shown: the fit metadata
(`success`, `rwp`, elapsed time, which execution path ran, and the error +
traceback on failure) plus every tabular report in memory — the full
refined-parameter table with ESDs, the fit profile, per-phase unit-cell and
peak-list tables (dicts keyed by phase name), and the SPF peak/convergence
tables when single-peak fitting. Everything the CSV/TXT files contain, without
touching disk yourself.

The public API is `run`, `validate`, `load_recipe_asset`,
`validate_simulation_mode_parameters`, `RecipeModel`, and `GSASClient`.

**The GSAS-II server (used by default)** — refinements go through a persistent
server that keeps GSAS-II resident in memory (auto-started in the background as
needed), which is a large speedup across many refinements. Manage it directly,
or opt out per run with `--no-server`:

```bash
pixi run gsas-server status                 # start | status | stop | restart | logs
pixi run kicker <recipe.json> --no-server   # force an isolated one-shot subprocess
```

The server is per-user: it listens on loopback only and accepts only requests
signed with a secret token kept in a directory only you can read; your client
in turn only accepts results signed with that token, so other users on the
same machine can neither use your server nor impersonate it. To switch it off
— e.g. on a shared workstation — set `POWDERLINE_NO_SERVER=1`: default
(`auto`) runs then go in-process, explicit server mode (`--use-server` /
`execution_mode='server'`) fails, and nothing is auto-started.

**Simulate a pattern from Materials Project** (requires an MP API key in
`.powderline_config.yaml` — see `.powderline_config.yaml.example` — or in the
`MP_API_KEY` environment variable):

```bash
pixi run mp-simulate --material-id mp-2680 --output patterns/
```

## 4. Refinement Engines

PowderLine supports three refinement engines that all consume the same recipe format:

### GSAS-II (default)

The primary engine, installed automatically with `pixi install`. All workflow types
and refinement flags are supported.

### TOPAS v7 (optional)

Bruker's commercial refinement package. PowderLine generates a TOPAS `.inp` + `.xye`
from unmodified `GSASII_Rietveld` and `GSASII_SPF` recipes; running the `.inp` requires
a Windows machine with `tc.exe` installed. The TOPAS path imports zero GSAS-II.

```python
result = powderline.run(recipe, Path("output/"), engine="topas")
```

### easydiffraction (optional)

Open-source Rietveld engine. Requires the optional `easydiff` pixi environment
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
GSAS-II reaches Rwp 6.01% vs easydiffraction 9.63% (both χ² < 1), and the refined
lattice parameters agree to well under 0.001 Å. The remaining Rwp gap comes from
background peaks (not modeled) and residual profile-model differences, so **compare
lattice parameters, not Rwp, across engines** — Rwp is not an apples-to-apples metric.

For the engine architecture and how to add a backend, see
[Adding a Refinement Engine](docs/DEVELOPMENT.md#adding-a-refinement-engine).
The full design dossier and backend survey live in the private
[PowderLine-devkit](https://github.com/NSLS2/PowderLine-devkit) (maintainers can
request access).

## Documentation

- **[Quickstart](docs/quickstart.md)** — clone → install → run → read the output.
- **[Getting Started](docs/getting-started.rst)** — full recipe structure, output
  files, and the Python API.
- **[Building Recipes](docs/building-recipes.md)** — writing and validating your
  own recipes, with helper code and an LLM prompt template.
- **[Supported Features](docs/capabilities.md)** — what a recipe can describe,
  per engine, and what is not yet supported.
- **[Troubleshooting](docs/TROUBLESHOOTING.md)** — common errors and fixes.
- **[Schema History](docs/SCHEMA_HISTORY.md)** — recipe-schema changelog (current:
  **0.26.0**) and migration guidance.
- **[Using PowderLine as a library](docs/integration-guide.md)** — install it into
  another project.
- **[Developer Guide](docs/DEVELOPMENT.md)** — architecture and how PowderLine
  works internally, for contributors. See also the
  [known-issues register](docs/known_issues.md) (`KI-NN` ids referenced from
  code and docs).

## Citation

If you use PowderLine in your research, please cite the preprint:

> A. A. Corrao, J. A. Perez, J. D. Langhout, M. M. Butala, T. A. Caswell, and
> D. Olds. *PowderLine: a programmatic powder diffraction analysis application.*
> arXiv:2608.17009 (2026).
> [doi:10.48550/arXiv.2608.17009](https://doi.org/10.48550/arXiv.2608.17009)

Machine-readable metadata is in [`CITATION.cff`](CITATION.cff).

### Cite the refinement engine too

PowderLine drives an underlying refinement engine. If you use PowderLine in
your work, please cite the engine you used in addition to PowderLine:

- **GSAS-II** (default engine):
  > B. H. Toby and R. B. Von Dreele. *GSAS-II: the genesis of a modern
  > open-source all purpose crystallography software package.* J. Appl. Cryst.
  > **46**, 544–549 (2013).
  > [doi:10.1107/S0021889813003531](https://doi.org/10.1107/S0021889813003531)

  PowderLine drives GSAS-II through its scripting interface, so please also cite:
  > J. H. O'Donnell, R. B. Von Dreele, M. K. Y. Chan, and B. H. Toby. *A
  > scripting interface for GSAS-II.* J. Appl. Cryst. **51**, 1244–1250 (2018).
  > [doi:10.1107/S1600576718008075](https://doi.org/10.1107/S1600576718008075)
- **TOPAS** (`engine="topas"`):
  > A. A. Coelho. *TOPAS and TOPAS-Academic: an optimization program
  > integrating computer algebra and crystallographic objects written in C++.*
  > J. Appl. Cryst. **51**, 210–218 (2018).
  > [doi:10.1107/S1600576718000183](https://doi.org/10.1107/S1600576718000183)
- **easydiffraction** (`engine="easydiffraction"`): the easydiffraction
  project asks you to cite the specific version you used, through its
  [Zenodo archive](https://doi.org/10.5281/zenodo.16806521) (all versions).
  PowderLine's `easydiff` environment currently installs version 0.20.1:
  > A. Sazonov, E. Lindgren, P. Rozyczko, and M. Seth. *easydiffraction
  > 0.20.1.* Zenodo (2026).
  > [doi:10.5281/zenodo.21999827](https://doi.org/10.5281/zenodo.21999827)

If you simulate patterns from Materials Project data (`pixi run mp-simulate`),
please also cite Materials Project — see
[Simulating Patterns from Materials Project](docs/mp-simulation.md#citation).

## License

BSD 3-Clause — see [LICENSE](LICENSE).
