# Simulate a pattern

**Goal:** calculate the pattern a model gives, without fitting anything.
Use it to predict a pattern, to check what an instrument profile or a
structure change does to the peaks, or to make synthetic data for testing a
pipeline.

**You need:**
- A recipe for your engine with the model you want: structure, instrument,
  background ([Refine a structure](refine-structure.md)).
- An `xrd_data` block. Its `tth` array sets the 2θ grid of the calculated
  pattern.

A **simulation** is a run that refines nothing. It uses the same recipe
format as a refinement, with every refine flag `false`.

## 1. Set every flag to false and mark the run as a simulation

::::{tab-set}
:sync-group: engine

:::{tab-item} GSAS-II
:sync: gsasii

Set every refine flag to `false`, including the polarization and any
background peak flags, and run one cycle:

```json
"refinement_controls": {"refinement_cycles": 1}
```

`refinement_cycles: 1` is a simulation. A refine flag left `true` is a
validation error.
:::
:::{tab-item} TOPAS
:sync: topas

Set every refine flag to `false` and calculate only:

```json
"refinement_controls": {"iters": 0, "chi2_convergence_criteria": 0.001, "x_calculation_step": 0.001}
```

`iters: 0` is a simulation. A refine flag left `true` is a validation error.
The other controls are still stated.
:::
:::{tab-item} easydiffraction
:sync: easydiffraction

Set every refine flag to `false`. A recipe with no flag set is a
simulation: lmfit is not run. The controls stay as they are, all stated.
:::
::::

Background coefficients share one flag, `background.chebyshev.refine_flag`.
Set it to `false` too.

`examples/example_LaB6_simulation/` and `examples/example_DRX_33_simulation/`
are GSAS-II simulations of the LaB6 and DRX_33 refinement examples.

## 2. Validate

```bash
pixi run powderline my_sim/input.json --validate-only
```

**Check:** the report says `Mode: Simulation (all parameters locked)` and
`Parameters requested: 0`.

## 3. Run

::::{tab-set}
:sync-group: engine

:::{tab-item} GSAS-II
:sync: gsasii

```bash
pixi run -e gsasii powderline my_sim/input.json
```
:::
:::{tab-item} TOPAS
:sync: topas

```bash
pixi run powderline my_sim/input.json --topas-version 6 --topas-dir C:/TOPAS6
```
A TOPAS simulation still needs `tc.exe` to calculate the pattern. Without
it, the run only writes TOPAS's input ([Run TOPAS recipes](run-topas.md)).
:::
:::{tab-item} easydiffraction
:sync: easydiffraction

```bash
pixi run -e easydiffraction powderline my_sim/input.json
```
:::
::::

## 4. Read the simulated pattern

The calculated pattern is the `y_calc` column of `output/fit_profile.txt`,
on the `tth` grid of your `xrd_data`. A simulation differs from a refinement
in these ways:

| | Value in a simulation |
|---|---|
| `simulation_mode` | `true` |
| `converged` | `null`: nothing was optimized |
| `rwp`, `r_exp`, `gof`, `chi2_red` | PowderLine's uniform statistics with no refined parameters. Against real data they show how good the starting values are. Against placeholder intensities they mean nothing. |
| ESDs in `<phase>_unit_cell_report.csv` | `0.0` for every value |
| `refined_parameters.csv` | not written by GSAS-II; written with no rows by TOPAS and easydiffraction |
| `output_recipe.json` | the input's values, since nothing was refined |
| `parameter_dispositions.csv` | no row `varied`: each value is `held_by_user`, `held_by_symmetry` or `default_applied` |

A statistic with no degrees of freedom is `null`, never NaN. GSAS-II's own
Rwp, under `engine_details`, is capped at 100 %.

## In Python

This turns a refinement recipe into a simulation. `hold_all()` sets every
refine flag to `false`, including the background's `refine_flag`.

```python
from pathlib import Path
import powderline

def hold_all(node):
    """Return a copy of a recipe block with every refine flag set to False."""
    if isinstance(node, dict):
        return {k: (False if k == "refine_flag" else hold_all(v)) for k, v in node.items()}
    if isinstance(node, list) and len(node) >= 2 and isinstance(node[1], bool):
        return [node[0], False, *node[2:]]
    if isinstance(node, list):
        return [hold_all(v) for v in node]
    return node

recipe = powderline.load_recipe_asset(Path("my_refinement/input.json"))
recipe["payload"] = hold_all(recipe["payload"])
controls = recipe["payload"]["refinement_controls"]
if recipe["schema_name"].startswith("gsasii."):
    controls["refinement_cycles"] = 1
elif recipe["schema_name"].startswith("topas."):
    controls["iters"] = 0

result = powderline.run(recipe, Path("my_sim/output"))
y_calc = result["fit_profile"]["y_calc"]
```

**Next:** [Run a series](sequential-refinement.md),
[Use PowderLine from Python](python-pipelines.md).
