# easydiffraction

| | |
|---|---|
| Version | 0.21.1, with CrysPy 0.13.0 and CrysFML 0.8.0, installed by `pixi install --frozen -e easydiffraction` (Python 3.12 or later) |
| Workflow | `easydiffraction.rietveld` (Rietveld refinement); no single-peak fitting |
| Calculators | `cryspy` or `crysfml`, stated in the recipe |
| Parameters | `[value, flag, min, max]` |
| Platforms | Linux, Windows, macOS |
| Run | `pixi run -e easydiffraction powderline <recipe.json>` |
| Cite | easydiffraction 0.21.1 (Zenodo) and the calculator you used, see [Citing](../about/citing.md) |

## What you write

A minimal `easydiffraction.rietveld` recipe for LaB6. It validates as shown;
your measured pattern replaces the three data points.

```json
{
  "schema_name": "easydiffraction.rietveld",
  "core_schema_version": "0.1.0",
  "engine_schema_version": "0.1.0",
  "payload": {
    "xrd_data": {
      "tth": [1.000, 1.004, 1.008],
      "Itth": [30.7, 29.8, 31.2],
      "Itth_weights": [0.0326, 0.0335, 0.0320]
    },
    "instrument": {
      "radiation": {"setup_wavelength": [0.1665, false, null, null]},
      "corrections": {"calib_twotheta_offset": [0.0, false, null, null]},
      "broadening": {
        "peak_type": "cwl-pseudo-voigt",
        "parameters": {
          "broad_gauss_u": [0.0104, true, null, null], "broad_gauss_v": [0.00033, true, null, null],
          "broad_gauss_w": [0.00064, true, null, null], "broad_lorentz_x": [0.0, false, null, null],
          "broad_lorentz_y": [0.0028, true, null, null]
        }
      }
    },
    "phases": {
      "LaB6": {
        "space_group": "P m -3 m",
        "unit_cell": {
          "a": [4.15682, true, null, null], "b": [4.15682, true, null, null],
          "c": [4.15682, true, null, null], "alpha": [90.0, false, null, null],
          "beta": [90.0, false, null, null], "gamma": [90.0, false, null, null]
        },
        "atoms": {
          "La": {"element": "La", "x": [0.0, false, null, null], "y": [0.0, false, null, null],
                 "z": [0.0, false, null, null], "occupancy": [1.0, false, null, null],
                 "ADP": "Uiso", "Uiso": [0.0086, false, null, null]},
          "B": {"element": "B", "x": [0.2021, false, null, null], "y": [0.5, false, null, null],
                "z": [0.5, false, null, null], "occupancy": [1.0, false, null, null],
                "ADP": "Uiso", "Uiso": [0.009, false, null, null]}
        },
        "scale": [5.4e-06, true, null, null]
      }
    },
    "refinement_controls": {
      "calculator": "cryspy",
      "minimizer": "lmfit (leastsq)",
      "max_iterations": 1000,
      "chi_square_change_tolerance": 1e-08,
      "parameter_change_tolerance": 1e-08,
      "gradient_tolerance": 0.0
    }
  }
}
```

LaB6's B is written as (x, ½, ½) here, the pattern of easydiffraction's
Wyckoff template. With CrysPy, another writing of that site is refused
({ref}`EB-77 <eb-77>`).

**Required:**

- `xrd_data`: `tth`, `Itth`, `Itth_weights`.
- `instrument` with `radiation` (`setup_wavelength`), `corrections`
  (`calib_twotheta_offset`) and `broadening` (`peak_type` and its
  `parameters`).
- At least one phase, with `space_group`, `unit_cell`, `atoms` and `scale`.
- `refinement_controls`, every control stated: `calculator`, `minimizer`,
  `max_iterations`, `chi_square_change_tolerance`,
  `parameter_change_tolerance`, `gradient_tolerance`.

**Optional:** `fit_range`, `background`, `instrument.polarization`,
`instrument.absorption`, a Kα2 line in `radiation`, and per phase
`scattering_types` and `preferred_orientation` (both with the cryspy
calculator only).

Every field, with its unit: [Fields: `easydiffraction.rietveld`](../reference/fields.md#easydiffractionrietveld).

### Units that differ from other engines

| Quantity | easydiffraction unit |
|---|---|
| `broad_gauss_u`, `_v`, `_w` (Gaussian FWHM² = U tan²θ + V tanθ + W) | degree² |
| `broad_lorentz_x`, `_y` (Lorentzian FWHM = X tanθ + Y/cosθ) | degree |
| `setup_wavelength` | Å |
| `calib_twotheta_offset`, sample displacement, transparency | degree |

GSAS-II's X and Y swap roles: its Lorentzian width is X/cosθ + Y tanθ.

`setup_polarization_coefficient` is p, and GSAS-II's polarization P is
1 − p. GSAS-II's P = 0.99 is p = 0.01. Copying P into p is a 6.6 % intensity
error at 15° 2θ ({ref}`EB-75 <eb-75>`).

### Nothing has a default

Every control is stated, and an instrument slot you leave out is not
modelled. A recipe without `background` has no background. A recipe with no
refine flag set is a simulation: lmfit is not run.

### Bounds

`[value, flag, min, max]`: a stated `min` or `max` replaces easydiffraction's
physical limit on that side, and `null` keeps it ({ref}`EB-71 <eb-71>`).

- The physical limits: cell lengths 0–30 Å, angles 0–180°, occupancy 0–1,
  `Uiso` and U11, U22, U33 0–10 Å², and scale, wavelength and μR ≥ 0.
- A value outside a physical limit is a validation error, even when it is
  fixed. So no cell over 30 Å can be modelled.
- A refined value that ends within 1e-6 (relative) of a bound or a physical
  limit gets `easydiffraction_parameter_at_limit`. For a limit of 0, the test
  is within 1e-6 of the starting value.

Bounds in every engine: [Recipe format](../reference/recipe-format.md#bounds).

## The instrument block

Each correction easydiffraction models for constant-wavelength X-ray powder
data is a slot. A slot you leave out is not modelled.

| Block | Fields |
|---|---|
| `radiation` | `setup_wavelength` (Å). Optionally a Kα2 line: `setup_wavelength_2` and `setup_wavelength_2_to_1_ratio`, stated together. |
| `polarization` (optional) | Fixed `setup_polarization_coefficient` (p) and `setup_monochromator_twotheta`. 2θ_m acts only with p > 0. |
| `corrections` | `calib_twotheta_offset` (degree); optionally `calib_sample_displacement`, `calib_sample_transparency` |
| `absorption` (optional) | `cylinder-hewat`, with `mu_r` |
| `broadening` | `peak_type`, its `parameters`, and `cutoff_fwhm` (CrysPy only) |

The peak types are `cwl-pseudo-voigt` (both calculators),
`cwl-pseudo-voigt-berar-baldinozzi-asymmetry` (CrysPy) and
`cwl-thompson-cox-hastings` with FCJ `asym_fcj_1` and `asym_fcj_2`
(CrysFML).

Because the peak types depend on the calculator, an instrument block moves
only between recipes that use the same calculator. Calibrate with the
calculator you will use for your samples.

A stated profile that makes a peak width negative anywhere near the fit
window is a validation error ({ref}`EB-87 <eb-87>`).

## Background and controls

- `background.chebyshev` is the shared Chebyshev model: `num_coefficients`,
  `coefficients`, and one `refine_flag` for all terms. Its basis spans the
  fit window's first and last points. It is the only background model.
- `refinement_controls`: `calculator`, `minimizer`, `max_iterations`,
  `chi_square_change_tolerance`, `parameter_change_tolerance`,
  `gradient_tolerance`. All are required. `minimizer` accepts only
  `"lmfit (leastsq)"`.
- `preferred_orientation` is March–Dollase, as in GSAS-II, with a bounded
  `ratio` plus a required `march_random_fract: [f, flag, min, max]` in
  [0, 1]. With f > 0, the refined r and f are not GSAS-II's quantities
  ({ref}`EB-98 <eb-98>`).

## Calculators

The calculator is part of the recipe (`refinement_controls.calculator`).
CrysPy and CrysFML compute different intensities and offer different peak
types. Every result records the calculator in `engine_details`.

| | CrysPy (`"cryspy"`) | CrysFML (`"crysfml"`) |
|---|---|---|
| Peak types | `cwl-pseudo-voigt`, Bérar–Baldinozzi asymmetry | `cwl-pseudo-voigt`, Thompson–Cox–Hastings with FCJ axial asymmetry |
| `cutoff_fwhm` | acts | fixed 30-FWHM window |
| Space-group settings accepted | 428 of 531 | 230 of 531 |
| `Uaniso` | yes | no: validation error ({ref}`EB-23 <eb-23>`) |
| `scattering_types` (ions) | yes, 111 ions | no: validation error ({ref}`EB-96 <eb-96>`) |
| `preferred_orientation` | yes | no: validation error ({ref}`EB-97 <eb-97>`) |
| Reflection list and peak-list reports | yes | none, with `easydiffraction_reflections_not_available` ({ref}`EB-79 <eb-79>`) |
| Single precision | — | yes: every refinement warns `easydiffraction_crysfml_start_dependent` ({ref}`EB-90 <eb-90>`) |

Both "pseudo-Voigts" are the TCH pseudo-Voigt, with Caglioti Gaussian and
X tanθ + Y/cosθ Lorentzian widths ({ref}`EB-76 <eb-76>`). Both calculators
model the Kα doublet, Lorentz–polarization, the 2θ offset, sample
displacement and transparency, and Hewat cylinder absorption
({ref}`EB-75 <eb-75>`).

- **Space-group settings.** Validation accepts, per calculator, only the
  settings whose computation passed for a general position and for every
  special site. The error names a setting of the same group that the
  calculator computes, or the other calculator ({ref}`EB-80 <eb-80>`).
- **CrysFML's intensities drift** by −4 % from 3° to 15° 2θ, which biases
  `Uiso` by about +0.001 Å² ({ref}`EB-78 <eb-78>`).
- **Absolute `Uiso` agrees across engines only when the profile models
  agree.** On the LaB6 temperature series, easydiffraction refines La's
  `Uiso` 10–22 % low ({ref}`EB-93 <eb-93>`). Compare cells and expansion
  instead: [Comparing engines](../concepts/comparing-engines.md).

## How PowderLine runs easydiffraction

easydiffraction runs in the same process as PowderLine.

- **The data** are handed over as a CIF loop at full precision, every number
  in positional notation ({ref}`EB-72 <eb-72>`, {ref}`EB-89 <eb-89>`). Only
  the weighted points inside the fit window are handed over
  ({ref}`EB-70 <eb-70>`).
- **Errors stay errors.** The gateway sets easydiffraction's log reaction to
  `RAISE`, whatever `ED_LOG_REACTION` says ({ref}`EB-48 <eb-48>`).
- **Atoms are checked after the build.** The gateway compares
  easydiffraction's multiplicity with core's for every atom
  ({ref}`EB-47 <eb-47>`).
- **Convergence.** PowderLine reads lmfit's success flag and message. A fit
  that stops without success, for example at `max_iterations`, is still a
  success with its values reported, plus the warning
  `easydiffraction_fit_not_converged`.
- **Parameters varied** is lmfit's count. A parameter without effect gets no
  ESD ({ref}`EB-81 <eb-81>`).
- **Offline,** importing easydiffraction prints a warning about a PyPI
  version check and continues ({ref}`EB-82 <eb-82>`).

## Behaviours

Each entry says what easydiffraction does on its own and what PowderLine
does about it. Messages and the changelog cite these IDs.

```{include} ../_generated/eb_easydiffraction.md
```
