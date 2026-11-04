# Fit to cathode material diffraction data with multiple phases using the file-less payload

Recipe: `input.json` (`gsasii.rietveld`, GSAS-II). Per-engine recipes for the
same case live next to it: `topas/input.json` (`topas.rietveld`, TOPAS 6) and
`easydiffraction/input.json` (`easydiffraction.rietveld`, CrysPy); see the
`README.md` in each directory.

## Scientific Purpose

I am fitting a diffraction pattern collected on a disordered rocksalt battery material.
Both the main phase of interest and a secondary phase are being fit. The main phase is a disordered rock salt (face centered cubic, space group Fm-3m, space group number 225) and the secondary phase is Li4MgWO6 (monoclinic, space group C2/m, space group number 12).
I am refining the phase scale factors, lattice parameterss, phase size broadening including the LG_eta (Lorentzian-Gaussian weighting) parameters, phase strain broadening including the Lg_eta parameters, and a Chebyshev background with 6 terms,
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

- What data file(s) are you using?
    None - this is an example of the payload carrying all necessary information including the diffraction data, instrument parameters, and structure information.
- What phases are being refined?
    DRX (space group Fm-3m, cubic) and Li4MgWO6 (space group C2/m, monoclinic)
- What parameters are constrained vs refined?
    Instrument parameters, atomic positions, atomic occupancies, and atomic displacement parameters are constrained.
    Lattice parameters, phase scale factors, phase size broadening, phase strain broadening, and Chebyshev background are refined.
- Starting values for refinement
    Lattice parameters and atomic coordinates from a CIF. Phase lattice strain (mustrain) set to 1 with an LG_eta parameter of 1.
    Phase scale factor defaulted to 1, crystallite size defaulted to 1 (meaning 1 micron crystallite size), and size LG_eta parameter starts at 1.
- Any special GSAS-II settings or options
    None.

## Expected Behavior

- What parameters should converge?
- Expected fit quality (Rwp, χ²)
    Rwp = 10.83%
- Typical runtime
    Less than 10 seconds.
- Any warnings or messages that are normal
    Reported from refinement:
    Warning: 2 soft (SVD) Hessian singularities
    SVD problem(s) likely from:
    0:0:Size;mx, 1:0:Size;i
    Note highly correlated parameters:
    ** 0:0:Mustrain;mx and 0:0:Mustrain;i (@100.00%)
    ** 1:0:Mustrain;mx and 1:0:Mustrain;i (@100.00%)

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


## Known Issues

**The output recipe of this example is not valid as posed** (`output_recipe_valid:
false`, warning `output_recipe_not_valid`; KI-04). The committed reference
refines both phases' isotropic crystallite size and microstrain over 1–15° 2θ, which
is ill-conditioned (see the SVD warnings above): the Li4MgWO6 size ends at
about −1355 µm (ESD ≈ 180 µm), which the schema refuses, so the output recipe is
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

The recipe was converted from its schema-0.26.0 form with
`scripts/convert_recipe_026.py` at PowderLine 0.2.0; the converter's
notes for each example are in `docs/SCHEMA_HISTORY.md`'s gsasii section.

## Data citation

The diffraction data in this example (the disordered-rocksalt cathode
material, "DRX_33") is from the study available at
[doi:10.26434/chemrxiv.15003271/v1](https://doi.org/10.26434/chemrxiv.15003271/v1)
(preprint; to appear in a peer-reviewed publication). Please cite that work
when using this dataset.
