# Quickstart

This is the shortest path from a fresh clone to a finished refinement, on both
**Linux** and **Windows**. It takes a few minutes, most of which is the one-time
environment install.

## Prerequisites

- [pixi](https://pixi.sh) — the only tool you need to install yourself. It manages
  the whole environment, **including GSAS-II** (installed automatically; you do
  not install GSAS-II separately).
- `git`.

The `pixi run ...` commands below are identical on Linux and Windows — run them in
your terminal (bash/zsh on Linux, PowerShell or Command Prompt on Windows) from
the repository root.

## 1. Clone and install

```bash
git clone https://github.com/NSLS2/PowderLine.git
cd PowderLine
pixi install
```

`pixi install` creates the environment and installs GSAS-II. The first run
downloads packages and takes a few minutes; later runs are instant.

## 2. Run an example refinement

PowderLine ships real refinement cases under `examples/`. Run the LaB6 calibrant:

```bash
pixi run kicker examples/example_LaB6/input.json
```

You'll see progress and a final weighted-profile R-factor (Rwp). That's a
complete Rietveld refinement driven entirely by the JSON recipe.

> **One recipe, multiple engines.** GSAS-II is the default engine, but the same
> recipe also runs through Bruker TOPAS v7 or the open-source easydiffraction.
> See [Getting Started](getting-started.rst) for `engine="topas"` /
> `engine="easydiffraction"`.

## 3. Read the output

Results are written to `examples/example_LaB6/output/`:

| File | What it is |
|---|---|
| `refined_parameters.csv` | Every refined parameter with its ESD (9-column table) |
| `LaB6_unit_cell_report.csv` | Unit-cell parameters + ESDs for the phase |
| `LaB6_peak_list_report.csv` | Reflection list (hkl, d-spacing, 2θ, intensity) |
| `fit_profile.txt` | Observed / calculated / background / difference intensities |
| `dummy.lst` | Human-readable GSAS-II log — open this first for Rwp and parameter tables |
| `dummy.gpx` | GSAS-II project file — reopen it in the GSAS-II GUI to inspect visually |

Open `dummy.lst` in any text editor to see the refinement summary, or load
`dummy.gpx` in GSAS-II to explore the fit graphically.

## 4. Validate a recipe (no refinement)

To check that a recipe is well-formed without running it:

```bash
pixi run kicker --validate-only examples/example_LaB6/input.json
```

This is the fastest way to confirm your own recipe is valid before a full run.

## 5. Make it your own

- Copy an example directory (e.g. `examples/example_LaB6/`) and edit its
  `input.json` — replace the `xrd_data`, structure, and refinement flags with your
  own. `examples/example_template/` is a blank skeleton to start from.
- Starting from your own CIF, instrument, and data files? See
  [Building Recipes](building-recipes.md).
- Send results elsewhere with `--output DIR`.
- See more detail in each example's `DESCRIPTION.md`.

## Next steps

- **[Getting Started](getting-started.rst)** — full recipe structure, every output
  file, and the `powderline.run()` Python API.
- **[Troubleshooting](TROUBLESHOOTING.md)** — if a run fails or a recipe is
  rejected.
- **[Schema History](SCHEMA_HISTORY.md)** — the recipe schema (current: 0.26.0) and
  how to migrate older recipes.
