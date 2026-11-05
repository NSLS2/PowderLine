# Fit to cathode material diffraction data with multiple phases using the file-less payload

> **Teaching example (GSAS-II recipe).** This refinement is ill-posed on
> purpose. It refines crystallite size and microstrain together for both
> phases over 1–15° 2θ, which the data cannot separate: the Li4MgWO6 size runs
> to about −1356 µm. The output recipe is therefore not valid
> (`output_recipe_valid: false`, warning `output_recipe_not_valid`). The
> well-posed variant is `example_DRX_33_strainonly` (size held, Rwp 8.46 %
> against 10.83 % here). More in
> [Teaching examples](../../docs/examples/index.md#teaching-examples).

Recipe: `input.json` (`gsasii.rietveld`, GSAS-II). Per-engine recipes for the
same case live next to it: `topas/input.json` (`topas.rietveld`, TOPAS 6) and
`easydiffraction/input.json` (`easydiffraction.rietveld`, CrysPy); see the
`README.md` in each directory. Neither refines crystallite size. The GSAS-II
and easydiffraction recipes have committed reference output (`output/`,
`easydiffraction/output/`); no TOPAS output is committed under `examples/`.

## Scientific Purpose

I am fitting a diffraction pattern collected on a disordered rocksalt battery material.
Both the main phase of interest and a secondary phase are being fit. The main phase is a disordered rock salt (face centered cubic, space group Fm-3m, space group number 225) and the secondary phase is Li4MgWO6 (monoclinic, space group C2/m, space group number 12).
I am refining the phase scale factors, lattice parameters, phase size broadening including the LG_eta (Lorentzian-Gaussian weighting) parameters, phase strain broadening including the Lg_eta parameters, and a Chebyshev background with 6 terms.
The intention is to quantify the relative phase fractions from the refined scale factors.

## Schema Features Demonstrated

This example demonstrates multi-phase refinement capabilities:

- **Multi-phase refinement**: Two phases with different crystal systems (cubic + monoclinic)
- **Phase-specific parameters**: Independent scale, lattice, and broadening parameters for each phase
- **Peak broadening modeling**: Both size and strain broadening with LG_eta (Lorentzian-Gaussian mixing)
- **Constrained atomic structure**: Atomic positions, occupancies, and ADPs fixed (structure-only refinement)
- **File-less payload**: Complete multi-phase dataset embedded in JSON
- **Phase fraction quantification**: Refined scale factors enable phase fraction determination

## Input Parameters

- **Data**: no data file. The payload carries everything: the diffraction
  data, the instrument parameters and the structures.
- **Phases**: DRX (space group Fm-3m, cubic) and Li4MgWO6 (space group C2/m,
  monoclinic).
- **Held**: instrument parameters, atomic positions, occupancies and
  displacement parameters.
- **Refined**: lattice parameters, phase scale factors, size broadening,
  strain broadening and the Chebyshev background.
- **Starting values**: lattice parameters and atomic coordinates from a CIF.
  Microstrain starts at 1 with an LG_eta of 1. The phase scale factor starts
  at 1, the crystallite size at 1 µm and the size LG_eta at 1.
- **Special GSAS-II settings**: none.

## Expected Behavior

- **Fit quality**: Rwp = 10.83 % (GSAS-II's wR in `dummy.lst`), GOF 1.10.
- **Typical runtime**: less than 10 seconds.
- **Messages from GSAS-II**: they show the ill-conditioning (see *Known
  Issues*):

  ```
  Warning: 2 soft (SVD) Hessian singularities
  SVD problem(s) likely from:
  0:0:Size;mx, 1:0:Size;i
  Note highly correlated parameters:
  ** 0:0:Mustrain;mx and 0:0:Mustrain;i (@100.00%)
  ** 1:0:Mustrain;mx and 1:0:Mustrain;i (@100.00%)
  ```

## Output Files

This two-phase Rietveld refinement produces:

- **dummy.gpx** - GSAS-II project file (reopenable in the GUI; gitignored)
- **dummy.lst** - Human-readable refinement log with Rwp and parameter tables
- **refined_parameters.csv** - All refined parameters with ESDs (9 columns: parameter_name, descriptive_name, phase_name, phase_idx, atom_name, atom_idx, value, esd, category)
- **DRX_33_unit_cell_report.csv** - Phase 1 unit cell parameters with ESDs (3 columns: parameter, value, esd)
- **DRX_33_peak_list_report.csv** - Phase 1 reflection list (hkl, d-spacing, 2θ, intensities)
- **Li4MgWO6_SG12_unit_cell_report.csv** - Phase 2 unit cell parameters with ESDs (3 columns: parameter, value, esd)
- **Li4MgWO6_SG12_peak_list_report.csv** - Phase 2 reflection list (hkl, d-spacing, 2θ, intensities)
- **fit_profile.txt** - Observed/calculated/background/difference intensities
- **output_recipe.json** - The resolved recipe with the refined values written back (KI-04; not valid as posed, see below); `metadata.powderline_provenance` names the run
- **parameter_dispositions.csv** - One row per refinable value: path, value, esd, disposition (`varied`, `held_by_user`, `held_by_symmetry`, `default_applied`, ...), at_limit

## Known Issues

**The output recipe of this example is not valid as posed** (`output_recipe_valid:
false`, warning `output_recipe_not_valid`; KI-04). The committed reference
refines both phases' isotropic crystallite size and microstrain over 1–15° 2θ, which
is ill-conditioned (see the SVD warnings above): the Li4MgWO6 size ends at
about −1356 µm (ESD ≈ 180 µm), which the schema refuses, so the output recipe is
written and returned with that value and the warning names it. The reference is
kept deliberately as the ill-conditioned posing; `example_DRX_33_strainonly` is the
physical re-parameterisation (size held at 10 µm; Rwp 8.46 % against 10.83 % here)
whose output recipe is valid and feeds back.

## Refine flags (gsasii 0.1.0)

Every refinable parameter is `[value, refine_flag]` (no bounds: GSAS-II applies
limits only after a fit); a parameter refines iff its flag is `true`. The gsasii
schema checks the flags against the symmetry and GSAS-II's own parameter groups
when the recipe is validated: a refined strict subset of a tie group (e.g. only
`a` of a cubic cell) or a refined symmetry-fixed parameter is an error, so the
recipe states exactly what GSAS-II refines. This example uses the **explicit
style** - every parameter is listed with a symmetry-consistent flag.

## Data citation

The diffraction data in this example (the disordered-rocksalt cathode
material, "DRX_33") is from the study available at
[doi:10.26434/chemrxiv.15003271/v1](https://doi.org/10.26434/chemrxiv.15003271/v1)
(preprint; to appear in a peer-reviewed publication). Please cite that work
when using this dataset.
