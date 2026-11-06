# LaB6 instrument profile function fit with file-less payload

## Scientific Purpose

I am fitting a pattern collected on a LaB6 calibrant (NIST SRM 660c, cubic symmetry, space group number 221, Hermann-Mauguin symbol 'Pm-3m', a=4.15682 Angstroms).
I am refining the phase scale factor, a Chebyshev background with 6 terms, and instrument broadening parameters.
The instrument broadening parameters are described by terms U, V, W, X, Y, and Z that come from the Thompson-Cox-Hastings pseudo-Voigt approximation.
The intention is to capture the peak broadening that is contributed by the instrument (X-ray source, optics, geometry) so that sample-based broadening can be separately determined from data collected on samples in the same configuration.

## Schema Features Demonstrated

This example demonstrates fundamental refinement capabilities:

- **File-less JSON payload**: All data embedded directly in JSON (XRD data, structure, instrument parameters)
- **Standard refinement parameter format**: Uses `[value, refine_flag]` throughout (gsasii 0.1.0 exposes no bounds)
- **Background modeling**: Chebyshev polynomial with 6 coefficients
- **Instrument parameter refinement**: Thompson-Cox-Hastings pseudo-Voigt broadening (U, V, W, X, Y, Z parameters)
- **Phase scale refinement**: Single-phase calibrant fitting for instrument profile characterization
- **Held structural parameters**: Lattice parameter held at the certified SRM value; atomic parameters held at the stated values

## Input Parameters

- **Data**: no data file. The payload carries everything: the diffraction
  data, the instrument parameters and the structure.
- **Phase**: LaB6.
- **Held**: the lattice parameters (known, since it is a standard reference
  material), atomic positions, occupancies and displacement parameters.
- **Refined**: the phase scale factor, the Chebyshev background and the
  instrument broadening parameters.
- **Starting values**: the lattice parameters from the NIST certificate and
  the atomic coordinates from a CIF. The instrument broadening starts from
  values fitted earlier to data collected in a similar configuration.
- **Special GSAS-II settings**: none.
- **Background**: the recipe has no background peak. The data have no
  feature below the first Bragg peak at 2.29° 2θ (a flat background of about
  30 counts), so a peak there cannot be determined.
- **Size and strain broadening**: left out of the recipe, so the documented
  default applies (10 µm, 0 microstrain, both held). Validation reports it as
  a structured warning.
- **Axial divergence**: SH/L is 0.002, the smallest value GSAS-II computes
  with.

## Expected Behavior

- **Fit quality**: Rwp = 6.53 % (GSAS-II's wR in `dummy.lst`), GOF 0.52.
- **Typical runtime**: less than 10 seconds.
- **Messages you will see**: GSAS-II reports highly correlated parameters,
  mostly instrument profile terms (for example `X` and `Z`) and background
  terms. A strong correlation means the data cannot separate the parameters;
  see [Know which parameters fight each other](../../docs/concepts/refinement-practice.md#know-which-parameters-fight-each-other).

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

## Per-engine recipes

`topas/input.json` (`topas.rietveld`, TOPAS 6) and `easydiffraction/input.json`
(`easydiffraction.rietveld`, CrysFML with the Thompson-Cox-Hastings profile)
describe the same case in each engine's native terms; see the `README.md` in
each directory. The GSAS-II and easydiffraction recipes have committed
reference output (`output/`, `easydiffraction/output/`); no TOPAS output is
committed under `examples/`.
