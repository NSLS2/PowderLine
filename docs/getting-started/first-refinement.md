# Your first refinement

In this tutorial you run a complete Rietveld refinement of LaB6, a
calibration standard, with GSAS-II. Then you look at what came back. It
takes about five minutes after [installing](install.md) the `gsasii`
environment.

## 1. Look at the recipe

The example is in `examples/example_LaB6/`. Its recipe, `input.json`, holds
everything the refinement needs:

- the measured pattern: 2θ, intensities and weights;
- the instrument: wavelength, peak-shape parameters and corrections;
- the structure: space group `P m -3 m`, the cell, and the La and B atoms;
- the background, and which values to refine.

Every value that can be refined carries a flag. Here the cell is held at the
certified value and the peak shape is refined:

```json
"a": [4.15682, false],
"U": [18.71740850558368, true]
```

## 2. Check it

Validation reads the recipe and checks it without running any engine:

```bash
pixi run powderline examples/example_LaB6/input.json --validate-only
```

You should see `✅ Recipe validation successful`, followed by a summary and
two warnings. The warnings say PowderLine applied its default sample
broadening, because the recipe leaves it out. That is intended for a
calibrant, which has negligible sample broadening.

## 3. Run it

```bash
pixi run -e gsasii powderline examples/example_LaB6/input.json --output my_lab6
```

`--output` sends the results to a folder of your own. Without it they go
next to the recipe, into `examples/example_LaB6/output/`, which holds the
example's committed reference results.

GSAS-II prints its progress for each refinement cycle. The run takes a few
seconds and ends like this (long lines shortened):

```text
⚠️ 3 warning(s):
   - gsasii_broadening_default_applied: phase 'LaB6': size_broadening left out, …
   - gsasii_broadening_default_applied: phase 'LaB6': strain_broadening left out, …
   - gsasii_refinement_message: GSAS-II reported: Warning: Soft (SVD) singularity
     in the Hessian … Note highly correlated parameters: ** :0:X and :0:Z (@99.99%)
✅ Refinement complete. Final Rwp: 6.534%
```

Rwp is the weighted-profile R-factor, here 6.5 %. The third warning comes
from GSAS-II itself: the peak-shape terms `X` and `Z` change the pattern in
almost the same way, so the data can't separate them. PowderLine passes the
warning on rather than hiding it. [Good refinement practice](../concepts/refinement-practice.md)
explains what to do about correlated parameters.

## 4. Look at the results

The results are in `my_lab6/`:

| File | What it holds |
|---|---|
| `refined_parameters.csv` | Every refined value with its uncertainty (ESD) |
| `LaB6_unit_cell_report.csv` | The cell parameters and volume, with ESDs |
| `LaB6_peak_list_report.csv` | The reflections: hkl, d-spacing, 2θ, intensity |
| `fit_profile.txt` | Observed, calculated, background and difference curves |
| `output_recipe.json` | Your recipe with the refined values written in |
| `parameter_dispositions.csv` | For every refinable value: refined, held, or fixed by symmetry |
| `dummy.gpx`, `dummy.lst` | GSAS-II's own project file and log; open the `.gpx` in the GSAS-II GUI |

Every engine writes the same tables with the same names. The engine's own
files are kept alongside. [Outputs](../reference/outputs.md) describes each
one.

### Plot the fit

Always look at a fit, not just its Rwp. In the same environment:

```python
import pandas as pd
import matplotlib.pyplot as plt

fit = pd.read_csv("my_lab6/fit_profile.txt", sep="\t")
plt.plot(fit.two_theta, fit.y_obs, ".", ms=2, label="observed")
plt.plot(fit.two_theta, fit.y_calc, label="calculated")
plt.plot(fit.two_theta, fit.y_diff - fit.y_obs.max() * 0.1, label="difference")
plt.xlabel("2θ (°)")
plt.legend()
plt.show()
```

Save it as `plot_fit.py` and run it with `pixi run -e gsasii python plot_fit.py`.

### Run it from Python instead

The command line and Python do the same thing. In Python you get the tables
back as pandas DataFrames:

```python
from pathlib import Path
import powderline

recipe = powderline.load_recipe_asset(Path("examples/example_LaB6/input.json"))
result = powderline.run(recipe, Path("my_lab6_py"))

print(result["rwp"])                  # PowderLine's Rwp, in percent
print(result["unit_cell_data"]["LaB6"])
```

## 5. Try the other engines

The same refinement written for the other engines is in
`examples/example_LaB6/easydiffraction/` and `examples/example_LaB6/topas/`:

```bash
pixi install --frozen -e easydiffraction
pixi run -e easydiffraction powderline examples/example_LaB6/easydiffraction/input.json --output my_lab6_ed
```

Each recipe is written in its own engine's terms, so the instrument blocks
differ. The structure block is the same. [Comparing engines](../concepts/comparing-engines.md)
explains why the results differ slightly.

## What you did

You checked a recipe, ran it, and read standard results. Next, see
[how PowderLine works](../concepts/how-powderline-works.md), or go straight to
[refining your own data](your-own-data.md).
