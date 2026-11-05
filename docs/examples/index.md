# Examples

Every example is a real recipe with its committed results. Run any of them
from a PowderLine checkout, into a folder of your own:

```bash
pixi run -e gsasii powderline examples/<name>/input.json --output my_run
```

Your results are then in `my_run/`.

:::{warning}
Always pass `--output` when you run a committed example. Without it, the
results go to the example's own `output/` folder and overwrite the committed
results there.
:::

Examples with a TOPAS or easydiffraction version keep it in a subfolder
(`topas/`, `easydiffraction/`). Run an easydiffraction recipe in the
`easydiffraction` environment. A TOPAS recipe needs TOPAS 6 (`tc.exe`) on
Windows:

```bash
pixi run -e easydiffraction powderline examples/<name>/easydiffraction/input.json --output my_run_ed
pixi run powderline examples/<name>/topas/input.json --topas-version 6 --topas-dir C:/TOPAS6 --output my_run_topas
```

Validate any of them without an engine. Validation writes nothing:
`pixi run powderline examples/<name>/input.json --validate-only`.

Each example folder has a `DESCRIPTION.md` that explains the case and the
results you should get. Its `output/` folder holds the committed results.
They are also the regression references, so a change to them is a
deliberate change.

The figures show the committed fit over the fit window: the observed pattern
in grey, the calculated pattern in blue and the difference curve in orange,
below.

## Starting points

::::{grid} 1 2 3 3
:gutter: 3

:::{grid-item-card} LaB6 calibration
:img-top: ../_generated/examples/example_LaB6.svg
:img-alt: Observed, calculated and difference curves of the LaB6 fit
:link: https://github.com/NSLS2/PowderLine/tree/main/examples/example_LaB6

Fit the NIST SRM 660c standard to measure the instrument profile.
Rwp 6.53 %.

{bdg-primary}`calibration` {bdg-secondary}`GSAS-II · TOPAS · easydiffraction`
:::

:::{grid-item-card} DRX_33, two phases
:img-top: ../_generated/examples/example_DRX_33_strainonly.svg
:img-alt: Observed, calculated and difference curves of the DRX_33 strain-only fit
:link: https://github.com/NSLS2/PowderLine/tree/main/examples/example_DRX_33_strainonly

A two-phase battery cathode material. Crystallite size is held and
microstrain is refined. Rwp 8.46 %.

{bdg-primary}`multi-phase` {bdg-secondary}`GSAS-II`
:::

:::{grid-item-card} Temperature series
:img-top: ../_generated/examples/example_LaB6_temperature_series_easydiffraction.svg
:img-alt: Observed, calculated and difference curves of the first temperature step
:link: https://github.com/NSLS2/PowderLine/tree/main/examples/example_LaB6_temperature_series

Six simulated patterns from 25 to 500 °C, refined in sequence through the
output recipe. The figure shows the first step in easydiffraction.

{bdg-primary}`sequential` {bdg-info}`simulated` {bdg-secondary}`GSAS-II · easydiffraction`
:::
::::

## By feature

"Recipes" lists the engines the example has a recipe for. "Results" lists the
engines whose results are committed with it. TOPAS results are not committed
under `examples/`.

| Example | Shows | Recipes | Results | Data |
|---|---|---|---|---|
| [`example_LaB6`](https://github.com/NSLS2/PowderLine/tree/main/examples/example_LaB6) | Instrument profile from a standard: scale, Chebyshev background and the U–Z profile refined | GSAS-II, TOPAS, easydiffraction | GSAS-II, easydiffraction | measured |
| [`example_LaB6_ionic`](https://github.com/NSLS2/PowderLine/tree/main/examples/example_LaB6_ionic) | Ionic scattering types (`La3+`) | GSAS-II, TOPAS, easydiffraction | GSAS-II, easydiffraction | measured |
| [`example_LaB6_textured`](https://github.com/NSLS2/PowderLine/tree/main/examples/example_LaB6_textured) | March–Dollase preferred orientation: r = 0.6 programmed, 0.5978(14) recovered by GSAS-II | GSAS-II, TOPAS, easydiffraction | GSAS-II, easydiffraction | simulated, known answer |
| [`example_LaB6_temperature_series`](https://github.com/NSLS2/PowderLine/tree/main/examples/example_LaB6_temperature_series) | Sequential refinement: each step starts from the previous output recipe | GSAS-II, easydiffraction | GSAS-II (series tables), easydiffraction (first step) | simulated, known answer |
| [`example_LaB6_simulation`](https://github.com/NSLS2/PowderLine/tree/main/examples/example_LaB6_simulation) | Calculating a pattern: every refine flag off, one cycle | GSAS-II | GSAS-II | calculation |
| [`example_LaB6_singlepeakfit`](https://github.com/NSLS2/PowderLine/tree/main/examples/example_LaB6_singlepeakfit) | Single-peak fitting of 36 peaks, no crystal structure | GSAS-II, TOPAS | GSAS-II | measured |
| [`example_DRX_33`](https://github.com/NSLS2/PowderLine/tree/main/examples/example_DRX_33) | Two phases (cubic and monoclinic), size and strain refined | GSAS-II, TOPAS, easydiffraction | GSAS-II, easydiffraction | measured |
| [`example_DRX_33_strainonly`](https://github.com/NSLS2/PowderLine/tree/main/examples/example_DRX_33_strainonly) | Two phases, size held and microstrain refined | GSAS-II | GSAS-II | measured |
| [`example_DRX_33_anisoADP`](https://github.com/NSLS2/PowderLine/tree/main/examples/example_DRX_33_anisoADP) | Anisotropic displacement parameters (`Uaniso`) on one atom | GSAS-II | GSAS-II | measured |
| [`example_DRX_33_atomrefine`](https://github.com/NSLS2/PowderLine/tree/main/examples/example_DRX_33_atomrefine) | Atom coordinates, occupancies and `Uiso` refined | GSAS-II | GSAS-II | measured |
| [`example_DRX_33_simulation`](https://github.com/NSLS2/PowderLine/tree/main/examples/example_DRX_33_simulation) | Calculating a two-phase pattern | GSAS-II | GSAS-II | calculation |

`example_DRX_33` (GSAS-II recipe), `example_DRX_33_anisoADP`,
`example_DRX_33_atomrefine`, `example_LaB6_singlepeakfit` and the
easydiffraction recipe of `example_LaB6_ionic` are teaching examples. See the
next section before you copy them.

(teaching-examples)=
## Teaching examples

These examples show what an ill-posed refinement looks like.


:::{admonition} These examples are ill-posed on purpose
:class: caution

They ask the data for more than it can determine. They are kept as they are,
so you can see what that looks like and which signals PowderLine gives. Each
one names its well-posed variant where one exists. Don't copy their
refinement choices.
:::

In each one the refinement ends on a value the schema refuses. PowderLine
still writes the output recipe, so you can see what the engine produced. The
result says `output_recipe_valid: false`, and the warning names the value.
{ref}`KI-15 <ki-15>` records the decision to keep them.

| Example | What goes wrong | What PowderLine reports | Well-posed alternative |
|---|---|---|---|
| `example_DRX_33` | Size and strain refined together: the Li4MgWO6 crystallite size runs to −1355.6 µm | `output_recipe_valid: false`, `output_recipe_not_valid` | `example_DRX_33_strainonly`: Rwp 8.46 % against 10.83 % |
| `example_DRX_33_anisoADP` | Anisotropic ADPs on top of the same size and strain refinement: the DRX_33 size runs to −9.7 µm | as above | Both sizes held at 10 µm (its `DESCRIPTION.md`): Rwp 8.58 % against 15.53 % |
| `example_DRX_33_atomrefine` | Atom parameters released: the DRX_33 Li occupancy runs to −0.35 (Mg −0.14), the Li4MgWO6 size to −8.0 µm | as above | None: with the sizes held, GSAS-II fails on an invalid metric tensor |
| `example_LaB6_singlepeakfit` | The background peak's σ² runs to −2676 centideg², below the 0.01 floor GSAS-II silently computes with ({ref}`EB-35 <eb-35>`) | as above | Background peak widths and the last peak's γ held (its `DESCRIPTION.md`): valid, Rwp unchanged |
| `example_LaB6_ionic`, easydiffraction recipe | CrysPy's Lorentzian `broad_lorentz_x` refines negative, so the Lorentzian FWHM is negative above 11.3° 2θ ({ref}`EB-87 <eb-87>`) | `easydiffraction_negative_width`, `output_recipe_valid: false` | None committed |

See [Good refinement practice](../concepts/refinement-practice.md) for why
these choices fail, and [Messages](../reference/messages.md) for the warning
codes.

## Templates

`examples/example_template/` holds a blank recipe for each engine. The
templates are not runnable: the `powderline` command refuses any recipe with
`template` in its path. Copy the folder to start your own example, as
[CONTRIBUTING_EXAMPLES.md](https://github.com/NSLS2/PowderLine/blob/main/examples/CONTRIBUTING_EXAMPLES.md)
describes.
