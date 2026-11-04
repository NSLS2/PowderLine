# LaB6 temperature series: sequential refinement through the output recipe (simulated)

## Scientific Purpose

A heated powder standard measured at successive temperatures is the simplest
sequential refinement: the structure does not change, the lattice expands and
the atoms vibrate more, and each pattern is best refined starting from the
previous one. This example runs that workflow end to end with PowderLine's
**output recipe** (KI-04): each step's result is a complete recipe with the
refined values written back, and the next step is that recipe with only the
`xrd_data` block swapped (`powderline.recipes.with_block`). Nothing is copied
by parameter name.

The data are **simulated**, so the truth is known. Six LaB6 (SRM 660a)
patterns from 25 to 500 °C were calculated with GSAS-II on the measured
2θ grid of `example_LaB6` (28-ID-1, λ = 0.1665 Å, 3821 points in 0.9–15.1°)
with:

- the lattice parameter of Akdoğan & Payzant, *J. Appl. Cryst.* **58** (2025)
  1635: a(T) = 4.15678 + 2.4645·10⁻⁵ ΔT + 1.0325·10⁻⁸ ΔT² Å, ΔT = T − 298 K
  (α ≈ 5.9·10⁻⁶ K⁻¹ at room temperature; the same paper notes LaB6 has no
  phase transition below 1805 °C), so a grows from 4.156784 to 4.170821 Å
  over the series;
- isotropic displacements growing with absolute temperature,
  Uiso(T) = Uiso(298 K)·T/298 K (the high-temperature harmonic limit; La
  0.0086 → 0.0223 Å², B 0.0090 → 0.0234 Å²);
- the instrument profile (U…Z), Chebyshev background and scale of the
  committed `example_LaB6` refinement, so the patterns look like that data set
  (peak maxima ≈ 2700 counts over a background ≈ 30);
- Poisson counting noise on GSAS-II's calculated profile, weights
  1/max(counts, 1), fixed seeds (`make_series.py`; `data/truth.json` records
  every programmed value).

Peak shifts over the series: −0.011° at the (110) reflection (3.25°, FWHM
0.028°) and −0.05° at the top of the window (14.9°, FWHM 0.040°); Δa = 0.014 Å
against a refined-a ESD of 5·10⁻⁵ Å.

## Input Parameters

- **Data**: `data/lab6_<T>C.json`, one `xrd_data` block per temperature
  (`tth`, `Itth`, `Itth_weights`, `filename`); `input.json` carries the 25 °C
  block and is the first step's recipe.
- **Phase**: LaB6, `P m -3 m`, La at (0,0,0), B at (½,½,z) with z = 0.2021.
- **Refined** (every step): the cubic cell (a, b, c one tie group; starts at
  the SRM 660c value 4.15682 Å), the phase scale (starts at 0.03), six
  Chebyshev coefficients (start 30, 0, 0, 0, 0, 0) and both Uiso (start at
  the room-temperature values). 10 parameters.
- **Held**: the instrument profile (the simulation's own values), wavelength,
  zero shift, polarization, axial divergence, coordinates and occupancies,
  size/strain at the gateway defaults (10 µm / 0).
- **Fit range** [1, 15]°; 5 cycles per step.

## Expected Behavior

`run_series.py` runs the six steps in sequence and stops at the first step
whose output recipe is not valid (none here). The committed reference
(`output/series_report.csv`):

| T (°C) | a programmed (Å) | a refined (Å) | ESD (Å) | Δ (ESD) | Rwp (%) | GoF |
|---|---|---|---|---|---|---|
| 25 | 4.156784 | 4.156789 | 0.000044 | 0.1 | 12.68 | 1.01 |
| 120 | 4.159218 | 4.159205 | 0.000047 | 0.3 | 12.89 | 1.02 |
| 215 | 4.161840 | 4.161824 | 0.000051 | 0.3 | 13.30 | 1.04 |
| 310 | 4.164647 | 4.164571 | 0.000053 | 1.5 | 13.21 | 1.02 |
| 405 | 4.167641 | 4.167670 | 0.000055 | 0.5 | 13.24 | 1.02 |
| 500 | 4.170821 | 4.170858 | 0.000058 | 0.6 | 13.55 | 1.02 |

- Every refined cell is within 1.5 ESD of the programmed value; both Uiso
  within 2 ESD (B's ESDs are about seven times La's).
- GoF ≈ 1.0 at every step: the fits are limited by the counting noise alone,
  which is what a correct model refined against Poisson data must give. Rwp
  near 13 % is high only because the background dominates the weighted sum
  (the measured `example_LaB6` refinement gives 6.5 % on the same grid with
  smoother data).
- The weighted quadratic through the six refined cells
  (`output/thermal_expansion_fit.json`) gives 2.42·10⁻⁵ Å/K and 1.14·10⁻⁸
  Å/K² against the programmed 2.46·10⁻⁵ and 1.03·10⁻⁸: the linear coefficient
  to 2 %, the curvature to 10 % from six points.
- Every step's `output_recipe_valid` is true; the chain's last output recipe is
  `output/final_output_recipe.json` (its provenance names the 500 °C run).
- Runtime: the six-step chain takes 20–30 s in-process (`--use-server` for
  the GSAS-II server).

## Output Files

- `output/series_report.csv` — one row per step: temperature, programmed and
  refined a with ESD, programmed and refined Uiso (La, B) with ESDs, Rwp,
  Rexp, GoF, parameters varied, `converged`, `output_recipe_valid`.
- `output/steps/<T>C_LaB6_unit_cell_report.csv`,
  `output/steps/<T>C_refined_parameters.csv` — the per-step references.
- `output/thermal_expansion_fit.json` — the quadratic a(T) fit against the
  programmed polynomial.
- `output/final_output_recipe.json` — the recipe the next step would start
  from.
- The full per-step GSAS-II output (`dummy.gpx`, `dummy.lst`,
  `fit_profile.txt`, `output_recipe.json`, `parameter_dispositions.csv`, …)
  is written to `--work` (a temporary directory by default) and is not
  committed.

## How to run

```bash
pixi run -e gsasii python examples/example_LaB6_temperature_series/make_series.py   # regenerate data/ and input.json (deterministic for a given GSAS-II build)
pixi run -e gsasii python examples/example_LaB6_temperature_series/run_series.py    # the chain; writes output/
pixi run -e gsasii kicker examples/example_LaB6_temperature_series/input.json --validate-only  # the first step alone
```

`tests/test_example_temperature_series.py` checks the data against
`data/truth.json`, the committed reference against the programmed expansion,
and (gsasii env) re-runs the chain against the reference within the
regression tolerance.

## Known Issues

- **Regenerating the data moves a regression reference.** `make_series.py`
  is deterministic for a given GSAS-II build, but the patterns are GSAS-II's
  calculated profile: a change of the GSAS-II pin changes every data file and
  therefore every number in `output/`. Regenerating is a deliberate change
  (`docs/policies.md`), not a refresh.
- **The copied instrument profile has a negative Lorentzian width above
  ≈ 10.7° 2θ.** The committed `example_LaB6` refinement gives Y = −10.26
  centideg, so γ = X/cos θ + Y tan θ + Z crosses zero near 10.7°; GSAS-II
  clamps γ at 0.001 centideg (`GSASIIstrMath.getPowderProfile`), so the
  simulated peaks above that angle are pure Gaussian. The series is
  self-consistent (the same engine refines with the same held profile), but
  the profile is not a physical description of the instrument at high angle.
- What the simulation does **not** contain: sample displacement, a furnace
  background, intensity loss beyond the programmed Uiso, or any change of
  peak shape with temperature. A measured series will need its instrument
  profile refined at least once.

## Schema Features Demonstrated

- **The output recipe as the step's result** (`output_recipe`,
  `output_recipe_valid`, `parameter_dispositions`; KI-04) and
  `powderline.recipes.with_block` as the one chaining operation.
- A refinement **warm-started** from the previous step: the cell moves by up
  to 60 ESD between temperatures and 5 cycles are enough.
- `metadata` as the user's space (`metadata.series`), next to the one key
  PowderLine writes (`metadata.powderline_provenance`).
- Simulation (one-cycle, all flags held) and refinement from the same recipe
  frame.

## Per-engine recipes: the easydiffraction leg

`easydiffraction/input.json` is the first step for easydiffraction (CrysFML,
Thompson–Cox–Hastings profile with FCJ asymmetry; the `example_LaB6`
easydiffraction recipe with the 25 °C block, both Uiso refined, and the TCH
Lorentzian `broad_lorentz_x` **held** at 10⁻⁵ — see `easydiffraction/README.md`).
The **same** `run_series.py` drives it (`--recipe easydiffraction/input.json`):
the loop does not know which engine it runs. Reference: the golden
`tests/data/easydiffraction/native/golden/lab6_temperature_series.json`
(no easydiffraction output is committed under `examples/`). About 30 s per
step.

| T (°C) | a programmed (Å) | a refined (Å) | ESD (Å) | Δ (ppm) | La Uiso refined / programmed (Å²) | GoF |
|---|---|---|---|---|---|---|
| 25 | 4.156784 | 4.156712 | 0.000033 | −17 | 0.00667 / 0.00858 | 1.03 |
| 120 | 4.159218 | 4.159107 | 0.000033 | −27 | 0.00907 / 0.01132 | 1.03 |
| 215 | 4.161840 | 4.161783 | none | −14 | 0.01246 / 0.01405 | 1.04 |
| 310 | 4.164647 | 4.164518 | 0.000032 | −31 | 0.01479 / 0.01679 | 1.03 |
| 405 | 4.167641 | 4.167570 | 0.000040 | −17 | 0.01724 / 0.01953 | 1.01 |
| 500 | 4.170821 | 4.170754 | 0.000040 | −16 | 0.02007 / 0.02226 | 1.02 |

What the leg shows:

- **The chain runs the same way in easydiffraction as in GSAS-II**: six
  steps, every output recipe valid, the chain's last output recipe is the
  next step's input (14 parameters varied against GSAS-II's 10: the profile
  is refined here). The *expansion* is recovered as well as by GSAS-II: the
  (unweighted) quadratic gives 2.445·10⁻⁵ Å/K and 1.08·10⁻⁸ Å/K² against the
  programmed 2.4645·10⁻⁵ and 1.0325·10⁻⁸ (0.8 % and 4 %).
- **The absolute cell is 14–31 ppm low** (1.7–4 ESD) at every temperature,
  and **La's Uiso 10–22 % low** (8–12 ESD; largest at the lowest
  temperatures) while B's Uiso is right (within 2 ESD wherever an ESD was
  reported). The data were calculated by GSAS-II: these are differences between
  the two engines' models of the same pattern, not refinement failures — GoF
  is 1.01–1.04 in both engines. The probe (EB-93) points to
  **profile shape**: with CrysPy's pseudo-Voigt the engines' integrated
  intensities agree (no angle trend once the integration window is wide) and
  its Uiso is still 17 % low (cell +68 ppm), so the offset is not an
  intensity difference; the trend is the same with Uiso = 0, dispersion is
  negligible and the polarization mapping is right. With CrysFML the trend
  shrinks with the window but was not shown to vanish, as its TCH tails
  predict — a few-percent high-angle intensity difference is not excluded
  for CrysFML alone. **The cause is this series' profile, and in it the
  clamped Lorentzian width**: Y = −10.26 centideg, which GSAS-II clamps to
  0.001 centideg above ≈ 10.7°, so the simulated high-angle peaks are pure
  Gaussian — the one part of the profile neither a symmetric pseudo-Voigt
  nor TCH with its FCJ terms held at 0.001 (the fit as posed; freed, they do
  not move, EB-90) can represent; the shape mismatch lands in the parameter
  that dominates the angle dependence of the intensities (holding Uiso at
  the truth costs GoF 1.030 → 1.045 only). Shown by a test: the
  25 °C pattern simulated with a GSAS-II profile easydiffraction can
  represent (the original `example_LaB6` posing, no clamp) gives CrysPy La
  Uiso 0.00863 vs 0.00858 programmed and GSAS-II itself 0.00868, while
  CrysFML lands at 0.00823 (−4 %; no ESD, 0.00817(18) with X free — the size
  of its own intensity drift, EB-78). On this pattern the axial asymmetry
  moves the cell for the symmetric profile (CrysPy +76 ppm, an EB-88-size
  shift), not Uiso. Compare cells (with the EB-88-size offsets in mind) and
  expansion across engines; absolute Uiso agrees only when the profile
  models do.
- **One step reports no ESDs** (215 °C): CrysFML's single-precision pattern
  leaves lmfit unable to estimate error bars at that start (EB-90, the
  `easydiffraction_crysfml_start_dependent` warning on every CrysFML
  refinement). The runner carries the step with empty ESD columns and fits
  the expansion unweighted.
- **With `broad_lorentz_x` refined** (the parent recipe's posing) the chain
  stops at step 1: X refines negative to fit the Gaussian-only high-angle
  peaks, the TCH Lorentzian FWHM X tan θ + Y/cos θ goes negative from 14.8°
  2θ (inside the window's last degree), the schema refuses the output recipe
  (EB-87) and `run_series.py` stops with the reason — the stop condition
  working as designed. That run is recorded in the golden under
  `free_lorentz_x_run`.
