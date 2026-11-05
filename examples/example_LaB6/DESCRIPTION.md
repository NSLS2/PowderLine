# LaB6 instrument profile function fit with file-less payload

## Scientific Purpose

I am fitting a pattern collected on a LaB6 calibrant (NIST SRM 660c, cubic symmetry, space group number 221, Hermann-Mauguin symbol 'Pm-3m', a=4.15682 Angstroms).
I am refining the phase scale factor, a Chebyshev background with 6 terms, and instrument broadening parameters.
The instrument broadening parameters are described by terms U, V, W, X, Y, and Z that come from the Thompson-Cox-Hastings pseudo-Voigt approximation.
The intention is to capture the peak broadening that is contributed by the instrument (X-ray source, optics, geometry) so that sample-based broadening can be separately determined from data collected on samples in the same configuration.

## Schema Features Demonstrated

This example demonstrates fundamental refinement capabilities:

- **File-less JSON payload**: All data embedded directly in JSON (XRD data, CIF structure, instrument parameters)
- **Standard refinement parameter format**: Uses `[value, refine_flag]` throughout (gsasii 0.1.0 exposes no bounds)
- **Background modeling**: Chebyshev polynomial with 6 coefficients
- **Instrument parameter refinement**: Thompson-Cox-Hastings pseudo-Voigt broadening (U, V, W, X, Y, Z parameters)
- **Phase scale refinement**: Single-phase calibrant fitting for instrument profile characterization
- **Constrained structural parameters**: Lattice and atomic parameters fixed to known values (SRM certification)

## Input Parameters

- What data file(s) are you using?
    None - this is an example of the payload carrying all necessary information including the diffraction data, instrument parameters, and structure information.
- What phases are being refined?
    LaB6
- What parameters are constrained vs refined?
    Lattice parameters (known since it is a SRM), atomic positions, atomic occupancies, and atomic displacement parameters are constrained.
    Phase scale factor, Chebyshev background, and instrument broadening parameters are refined.
- Starting values for refinement
    Lattice parameters from NIST certification and atomic coordinates from CIF.
    Initial instrument broadening parameters come from a dictionary of values obtained from previous fitting of data collected in a similar configuration.
- Any special GSAS-II settings or options
    None.

## Expected Behavior

- What parameters should converge?
- Expected fit quality (Rwp, χ²)
    Rwp = 6.53%
- Typical runtime
    Less than 10 seconds.
- Any warnings or messages that are normal
    Correlated variables dropped (particularly for instrument parameters, bkg).

## Output Files

This Rietveld refinement produces:

- **dummy.gpx** - GSAS-II project file (reopenable in the GUI; gitignored)
- **dummy.lst** - Human-readable refinement log with Rwp and parameter tables
- **refined_parameters.csv** - All refined parameters with ESDs (9 columns: parameter_name, descriptive_name, phase_name, phase_idx, atom_name, atom_idx, value, esd, category)
- **LaB6_unit_cell_report.csv** - Unit cell parameters with ESDs (3 columns: parameter, value, esd)
- **LaB6_peak_list_report.csv** - Reflection list (hkl, d-spacing, 2θ, intensities)
- **fit_profile.txt** - Observed/calculated/background/difference intensities
- **output_recipe.json** - The resolved recipe with the refined values written back (KI-04); `metadata.powderline_provenance` names the run
- **parameter_dispositions.csv** - One row per refinable value: path, value, esd, disposition (`varied`, `held_by_user`, `held_by_symmetry`, `default_applied`, ...), at_limit


## Known Issues

None.

## History

- The schema-0.26.0 form of this recipe carried a single background peak at
  1.5° 2θ (position, intensity and widths refined). The data have no feature
  there (a flat ~30-count background; the first Bragg peak is at 2.29°), so the
  peak could not be determined: GSAS-II drove it out of the pattern with
  singular (zero) ESDs in every v0.1.1 reference. It was removed when the
  example migrated to `gsasii.rietveld` at PowderLine 0.2.0;
  every other refined value moved by less than 0.31 ESD.
- Converted with `scripts/convert_recipe_026.py`: SH/L 0.0005 → 0.002 (the
  value GSAS-II computed with anyway); size/strain broadening left out, so
  the documented default (10 µm / 0 microstrain, fixed) applies and is
  reported as a structured warning when the recipe is validated.

## Per-engine recipes

`topas/input.json` (`topas.rietveld`, TOPAS 6) and `easydiffraction/input.json`
(`easydiffraction.rietveld`, CrysFML with the Thompson-Cox-Hastings profile)
describe the same case in each engine's native terms; see the `README.md` in
each directory. Only the GSAS-II recipe has committed reference output.
