# Quickstart

This is the shortest path from a fresh clone to a finished refinement, on both
**Linux** and **Windows**. It takes a few minutes, most of which is the one-time
environment install.

## Prerequisites

- [pixi](https://pixi.sh) — the only tool you need to install yourself. It manages
  the environments, **including GSAS-II** (built as a conda package; you do not
  install GSAS-II separately).
- `git`.

The `pixi run ...` commands below are identical on Linux and Windows — run them in
your terminal (bash/zsh on Linux, PowerShell or Command Prompt on Windows) from
the repository root.

## 1. Clone and install

```bash
git clone https://github.com/NSLS2/PowderLine.git
cd PowderLine
pixi install -e gsasii
```

The default environment is core-only (it validates recipes but runs no
engine); `-e gsasii` adds GSAS-II. The first install downloads packages and
builds GSAS-II, which takes a few minutes; later runs are instant.

## 2. Run an example refinement

PowderLine ships real refinement cases under `examples/`. Run the LaB6 calibrant:

```bash
pixi run -e gsasii kicker examples/example_LaB6/input.json
```

You'll see progress and a final weighted-profile R-factor (Rwp). That's a
complete Rietveld refinement driven entirely by the JSON recipe.

> **One recipe, one engine.** The recipe's `schema_name` (`gsasii.rietveld`
> here) names the engine that runs it. The same case written for TOPAS 6 and
> for easydiffraction is in `examples/example_LaB6/topas/` and
> `examples/example_LaB6/easydiffraction/`; see
> [Recipe schemas](schemas.md) for the five schemas and the environment
> each runs in.

## 3. Read the output

Results are written to `examples/example_LaB6/output/`:

| File | What it is |
|---|---|
| `refined_parameters.csv` | Every refined parameter with its ESD (9-column table) |
| `LaB6_unit_cell_report.csv` | Unit-cell parameters + ESDs for the phase |
| `LaB6_peak_list_report.csv` | Reflection list (hkl, d-spacing, 2θ, intensity) |
| `fit_profile.txt` | Observed / calculated / background / difference intensities |
| `dummy.lst` | Human-readable GSAS-II log — open this first for GSAS-II's own Rwp and parameter tables |
| `dummy.gpx` | GSAS-II project file — reopen it in the GSAS-II GUI to inspect visually |

The Rwp the command prints is PowderLine's uniform statistic over the fit
window; GSAS-II's own value is in `dummy.lst` (they agree for this example).
Open `dummy.lst` in any text editor to see the refinement summary, or load
`dummy.gpx` in GSAS-II to explore the fit graphically.

## 4. Validate a recipe (no refinement)

To check that a recipe is well-formed without running it — this needs no
engine, so it works in the default environment and for every schema:

```bash
pixi run kicker --validate-only examples/example_LaB6/input.json
```

It prints the schema, the phase count and any structured warnings (for
example a default that was applied). This is the fastest way to confirm your
own recipe is valid before a full run.

## 5. Make it your own

- Copy an example directory (e.g. `examples/example_LaB6/`) and edit its
  `input.json` — replace the `xrd_data`, structure, and refinement flags with your
  own. `examples/example_template/` holds a blank skeleton per engine.
- Read [Input guidance](input-guidance.md) for how to fill the data,
  structure and instrument blocks, and [Fields and features](fields.md) for
  every field with its unit.
- Send results elsewhere with `--output DIR`.
- See more detail in each example's `DESCRIPTION.md`.

## Next steps

- **[Getting Started](getting-started.rst)** — recipe structure, every output
  file, and the `powderline.run()` Python API.
- **[Troubleshooting](TROUBLESHOOTING.md)** — if a run fails or a recipe is
  rejected.
- **[Migration guide](migration-0.1-to-0.2.md)** — if you have recipes from
  PowderLine 0.1.1 (schema 0.26.0).
