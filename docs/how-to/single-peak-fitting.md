# Fit single peaks

**Goal:** fit individual peaks, each with its own position, intensity and
width, without a crystal structure. Use it for peaks of an unknown phase, or
to measure peak positions and widths directly.

**You need:**
- Your pattern and a starting position for each peak.
- The instrument for your engine, ideally from a standard
  ([Calibrate the instrument](calibrate-instrument.md)).
- GSAS-II or TOPAS. easydiffraction has no single-peak workflow.

Single-peak fitting has its own workflow: `gsasii.spf` or `topas.spf`. A
recipe of that workflow has `single_peaks` instead of `phases`. If you know
the structure, refine it instead ([Refine a structure](refine-structure.md)).
A peak fit followed by a Rietveld refinement is two recipes and two runs.

## 1. Start from the example

Copy the single-peak example for your engine into a folder of your own and
put your pattern into its `xrd_data` block.

::::{tab-set}
:sync-group: engine

:::{tab-item} GSAS-II
:sync: gsasii

`examples/example_LaB6_singlepeakfit/input.json` (`gsasii.spf`): 36 LaB6
peaks, a Chebyshev background and one background peak.
:::
:::{tab-item} TOPAS
:sync: topas

`examples/example_LaB6_singlepeakfit/topas/input.json` (`topas.spf`): the
same 36 peaks in TOPAS's terms.
:::
:::{tab-item} easydiffraction
:sync: easydiffraction

Not available: easydiffraction has no single-peak workflow.
:::
::::

## 2. List the peaks

Every peak must lie inside the fit window (`fit_range`). The two engines
write peaks differently:

::::{tab-set}
:sync-group: engine

:::{tab-item} GSAS-II
:sync: gsasii

Four lists of the same length, one entry per peak:

```json
"single_peaks": {
  "positions": [[2.29, true], [3.25, true]],
  "intensities": [[3000, true], [3000, true]],
  "pv_gaussian_sigma_sq": [[1.0, true], [1.0, true]],
  "pv_lorentzian_gamma": [[0.5, true], [0.5, true]]
}
```

- `positions` in degrees 2θ.
- `pv_gaussian_sigma_sq` is the Gaussian variance σ² in centidegrees².
- `pv_lorentzian_gamma` is the Lorentzian width γ in centidegrees.
- Each width is at least 0.001, GSAS-II's own floor.

`refinement_controls` chooses where the widths come from:

```json
"refinement_controls": {
  "refinement_cycles": 5,
  "single_peak_fitting_mode": {"use_instrument_profile": false}
}
```

- `false`: each peak has its own widths, which you may refine. The
  instrument's `U` … `Z` must then be held.
- `true`: the widths come from the instrument's `U` … `Z`, which you may
  refine. The peaks' own width flags must then be `false`.

GSAS-II ignores a flag on the side not in use without saying so
({ref}`EB-53 <eb-53>`), so such a flag is a validation error.
:::
:::{tab-item} TOPAS
:sync: topas

A list of peaks. Each is a TOPAS `xo_Is` peak, the instrument's peak type
convolved with the peak's own widths:

```json
"single_peaks": [
  {"xo": [2.29, true, null, null], "I": [3000, true, null, null],
   "gauss_fwhm": [0.001, true, 0.0, null], "lor_fwhm": [0.001, true, 0.0, null]},
  {"xo": [3.25, true, null, null], "I": [3000, true, null, null],
   "gauss_fwhm": [0.001, true, 0.0, null], "lor_fwhm": [0.001, true, 0.0, null]}
]
```

- `xo` is the position in degrees 2θ, `I` the intensity.
- `gauss_fwhm` and `lor_fwhm` are the peak's own Gaussian and Lorentzian
  FWHM in degrees 2θ, at least 0. Leave one out and it is not convolved.
- `refinement_controls` states `iters`, `chi2_convergence_criteria` and
  `x_calculation_step`.
:::
::::

The background works as in a Rietveld recipe. In `gsasii.spf` it can also
hold background peaks (`background.single_peaks`), written like the Peak
List peaks above.

## 3. Validate and run

::::{tab-set}
:sync-group: engine

:::{tab-item} GSAS-II
:sync: gsasii

```bash
pixi run powderline my_peaks/input.json --validate-only
pixi run -e gsasii powderline my_peaks/input.json
```
:::
:::{tab-item} TOPAS
:sync: topas

```bash
pixi run powderline my_peaks/input.json --validate-only
pixi run powderline my_peaks/input.json --topas-version 6 --topas-dir C:/TOPAS6
```
See [Run TOPAS recipes](run-topas.md).
:::
:::{tab-item} easydiffraction
:sync: easydiffraction

Not available.
:::
::::

## 4. Read the results

::::{tab-set}
:sync-group: engine

:::{tab-item} GSAS-II
:sync: gsasii

- `single_peaks_report.txt`: tab-separated, one row per peak. A comment line
  says how many peaks converged and how many have aphysical values. The
  columns are `position_2theta`, `intensity`, `sigma`, `sigma_squared`,
  `gamma`, the Gaussian, Lorentzian and pseudo-Voigt FWHM and integral
  breadths, `fwhm_gsas_verification`, `converged` and `convergence_detail`.
- `peak_convergence_diagnostics.txt`: written only when a peak did not
  converge cleanly. One row per such peak: `peak_index`, `position_2theta`,
  `final_sigma_sq`, `final_gamma`, `status`, `notes`.
- `fit_profile.txt`, `output_recipe.json` and `parameter_dispositions.csv`,
  as for every run.

A `gsasii.spf` run writes no `refined_parameters.csv`, no unit-cell report
and no reflection list. In Python, `result["peak_fit"]` lists every
parameter GSAS-II's peak fit varied, by GSAS-II's own name, with its value
and ESD.
:::
:::{tab-item} TOPAS
:sync: topas

- `single_peaks_report.csv`: one row per peak, with `position_2theta`,
  `intensity`, `gauss_fwhm`, `lor_fwhm`, `fwhm` and `integral_breadth`, each
  followed by its ESD.
- `refined_parameters.csv`, `fit_profile.txt`, `output_recipe.json` and
  `parameter_dispositions.csv`, and TOPAS's own files.

No unit-cell report and no reflection list.
:::
:::{tab-item} easydiffraction
:sync: easydiffraction

Not available.
:::
::::

In Python, `result["spf_peaks"]` holds the peak table and
`result["spf_convergence_diagnostics"]` the peaks that need a look.
[Outputs](../reference/outputs.md) describes every key and file.

**Check:** in `single_peaks_report.txt` (GSAS-II) the comment line reads
`N of N peaks converged; 0 peaks have aphysical values`. Plot `y_obs` and
`y_calc` from `fit_profile.txt` to see that each peak is matched.

:::{note}
The committed GSAS-II example is a teaching example. Its background peak
refines its σ² far below GSAS-II's floor, so its output recipe is not valid
as posed ({ref}`KI-15 <ki-15>`). The 36 Peak List peaks converge cleanly.
:::

## If the fit misbehaves

### A peak has aphysical widths (GSAS-II)

GSAS-II can refine a peak to a negative or zero σ², or a negative γ. A width
cannot be negative. The peak's `convergence_detail` then reads
`negative_gamma_warning`, `zero_or_negative_sigma_sq_warning` or
`negative_sigma_sq_and_gamma_warning`, and the peak appears in
`peak_convergence_diagnostics.txt`.

Common causes:
- a starting position far from the true peak, or unreasonable intensity or
  widths;
- two peaks too close together, fitted as one;
- a peak on a steep background slope, or a background model that is too
  simple;
- a weak, noisy peak.

One weak peak with a tiny negative value (about −0.001) is often numerical
noise. Several flagged peaks, or large negative values, point to a problem
with the model.

What helps:
1. Start each peak at the visible maximum, with sensible widths.
2. Take the widths from the instrument: set `use_instrument_profile` to
   `true` and the peaks' width flags to `false`.
3. Fit the strong, well-separated peaks first. Add the others later.
4. Give the background more Chebyshev terms.
5. Raise `refinement_cycles`.

### A peak did not converge (GSAS-II)

A peak with status `NaN_failed` ended with σ² or γ not a number. Common
causes are a peak near the edge of the fit window, too few data points
around it, or extreme starting values.

What helps:
1. Keep each peak well inside the fit window, not within a degree or two of
   its edge.
2. Check the data around the peak.
3. Start the peak at the visible maximum.
4. Raise `refinement_cycles`.

### A TOPAS peak ends at a limit

A refined value that ends at a stated bound or at a TOPAS default limit
gets the warning `topas_parameter_at_limit`. The peak also appears in
`spf_convergence_diagnostics` with status `at_limit`. Widen the bound, or
start the peak closer to the data.

**Next:** [Simulate a pattern](simulate.md),
[Troubleshoot](troubleshooting.md).
