# LaB6 Single Peak Fitting with File-less Payload

> **Teaching example.** This refinement is ill-posed on purpose. Its one
> background peak refines all four parameters, and its σ² runs to about
> −2676 centideg², far below the 0.01 floor GSAS-II silently computes with
> (EB-35). The output recipe is therefore not valid (`output_recipe_valid:
> false`, warning `output_recipe_not_valid`). The well-posed variant holds the
> background peak's widths and the last Peak List peak's γ; see *Known
> Issues*. More in
> [Teaching examples](../../docs/examples/index.md#teaching-examples).

## Scientific Purpose

This example demonstrates **single peak fitting** capabilities in PowderLine using LaB6 calibrant data (NIST SRM 660c).
Unlike traditional Rietveld refinement that fits peaks based on crystal structure, single peak fitting refines individual peaks directly
with control over position, intensity, and pseudo-Voigt width parameters (Gaussian sigma_sq and Lorentzian gamma).

This approach is useful for:
- Fitting peaks without crystal structure constraints (e.g., amorphous materials, unknown phases)
- Refining individual peak shapes independently of instrument parameters
- Detailed peak shape analysis and width determination

The example uses both **background single peaks** (fitted as part of the background model) and **top-level single peaks** (fitted in the Peak List).
With `use_instrument_profile: false`, the peak widths are refined directly rather than being derived from instrument parameters (U, V, W, X, Y, Z).

## Input Parameters

- **Data source**: File-less payload carrying all necessary information including the diffraction data, instrument parameters, and structure information
- **Phases**: None - this is pure single peak fitting without phase structure
- **Background**:
  - Chebyshev polynomial with 6 coefficients (refined)
  - 1 background single peak (position, intensity, sigma, gamma all refined)
- **Single peaks (Peak List)**:
  - 36 peaks at different 2θ positions
  - All parameters refined: positions, intensities, Gaussian sigma_sq, Lorentzian gamma
  - `use_instrument_profile: false` - peak widths refined independently
- **Instrument parameters**: Provided but not refined in this example

## Expected Behavior

- The 36 Peak List peaks converge: the committed `single_peaks_report.txt`
  reports 36 of 36 peaks converged and none with aphysical values
- The background peak's σ² goes negative (see *Known Issues*)
- Output includes `single_peaks_report.txt` with refined peak parameters plus calculated:
  - FWHM values (Gaussian, Lorentzian, pseudo-Voigt)
  - Integral breadths (Gaussian, Lorentzian, pseudo-Voigt)
- Typical runtime: Less than 10 seconds
- Messages you may see: GSAS-II's report of highly correlated parameters

## Expected Output Files

- `single_peaks_report.txt`: tab-separated, one comment line (peaks converged / aphysical) then 14 columns per peak:
  - position_2theta, intensity, sigma, sigma_squared, gamma
  - fwhm_gaussian, fwhm_lorentzian, fwhm_pseudovoigt
  - integral_breadth_gaussian, integral_breadth_lorentzian, integral_breadth_pseudovoigt
  - fwhm_gsas_verification, converged, convergence_detail
- Standard outputs: `fit_profile.txt`, `single_peaks_report.txt`, `output_recipe.json` and `parameter_dispositions.csv` (plus `dummy.gpx`, gitignored; no `.lst` — see the note below)

## Schema Features Demonstrated

This example demonstrates single peak fitting capabilities:

- **Top-level single_peaks field**: Direct peak fitting without crystal structure (distinct from background.single_peaks)
- **Independent peak width refinement**: `use_instrument_profile: false` allows sigma and gamma refinement per peak
- **No `phases` block**: No crystal structure used (pure phenomenological peak fitting)
- **Schema name `gsasii.spf`**: the GSAS-II single peak fitting workflow
- **Single peak fitting mode**: `refinement_controls.refinement_cycles` controls iteration count for peak-only refinement
- **Coexisting peak models**: Background single peaks AND top-level single peaks in same recipe
- **Advanced peak metrics**: Calculated FWHM and integral breadths (Gaussian, Lorentzian, pseudo-Voigt)

## Schema

`gsasii.spf` 0.1.0 (core 0.1.0). Every parameter is `[value, refine_flag]`; the
Peak List (`payload.single_peaks`) and the background peaks
(`payload.background.single_peaks`) both state `pv_gaussian_sigma_sq`
(centideg²; the value is σ²) and `pv_lorentzian_gamma` (centideg).
With `use_instrument_profile: false` a refine flag on the instrument's U..Z is
an error (GSAS-II would ignore it silently). SH/L is 0.002, the smallest value
GSAS-II computes with.

## Output Files

This single peak fitting analysis produces:

- **dummy.gpx** - GSAS-II project file (reopenable in the GUI; gitignored)
- **single_peaks_report.txt** - Fitted peak parameters (position, intensity, FWHM, area) for each peak
- **peak_convergence_diagnostics.txt** - Per-peak convergence diagnostics, written only when a peak has a convergence issue (all 36 peaks of the committed reference converged cleanly, so the reference set has no such file)
- **fit_profile.txt** - Observed/calculated/background/difference intensities
- **output_recipe.json** - The resolved recipe with the refined values written back (KI-04; not valid as posed, see below); `metadata.powderline_provenance` names the run
- **parameter_dispositions.csv** - One row per refinable value: path, value, esd, disposition (`varied`, `held_by_user`, `held_by_symmetry`, `default_applied`, ...), at_limit

**Note**: Single peak fitting does not produce `refined_parameters.csv`, human-readable refinement log (.lst), unit cell reports, or peak list reports because there is no structural model - only empirical peak shapes are fitted.


## Known Issues

**The output recipe of this example is not valid as posed** (`output_recipe_valid:
false`, warning `output_recipe_not_valid`; KI-04): the one background
single peak refines all four of its parameters, and GSAS-II lets its σ² run far below
the 0.01 centideg² floor it silently computes with (EB-35) — the committed fit ends
near −2700 centideg² — which the schema refuses. The output recipe is written and
returned with that value and the warning names it; the 36 Peak List peaks and the
Chebyshev background come back with ESDs (`peak_fit`). The reference is kept
as posed.

The well-posed variant holds the background peak's widths
(`background.single_peaks.pv_gaussian_sigma_sq` and `pv_lorentzian_gamma`)
and the Lorentzian width of the last, weak Peak List peak at the window edge
(`single_peaks.pv_lorentzian_gamma` entry 36), which otherwise goes negative
once the background peak is physical. Its output recipe is valid and, fed back,
reproduces the fit with Rwp unchanged within 0.05 percentage points
(`tests/test_api_gsasii_run.py`).

## Per-engine recipes

`topas/input.json` (`topas.spf`, TOPAS 6) describes the same 36-peak fit in
TOPAS's terms; see `topas/README.md`. Only the GSAS-II recipe has committed
reference output.
