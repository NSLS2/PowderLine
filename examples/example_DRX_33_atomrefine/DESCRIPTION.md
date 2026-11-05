# Multi-phase refinement with atom parameter refinement (isotropic ADPs)

## Scientific Purpose

This example extends `example_DRX_33` to demonstrate **atom parameter refinement** capabilities. While the base example refines only lattice parameters, scale factors, and peak broadening, this example additionally refines:

- **Atomic coordinates** (x, y, z) - refining crystallographic positions
- **Isotropic displacement parameters (Uiso)** - refining thermal motion
- **Occupancies** - refining site occupancies (useful for disordered materials)

The refinement uses the same disordered rocksalt battery material with two phases:
1. **DRX_33** (main phase): Disordered rock salt (Fm-3m, cubic)
2. **Li4MgWO6_SG12** (secondary phase): Monoclinic (C2/m)

This example validates PowderLine's ability to refine structural parameters in multi-phase systems, which is critical for accurate structure determination.

## Input Parameters

- **Data source**: Same as example_DRX_33 (embedded XRD data in JSON payload)
- **Phases being refined**: DRX_33 (cubic) and Li4MgWO6_SG12 (monoclinic)

### Atom Parameters Being Refined:

**DRX_33 Phase (cubic):**
- **Coordinates (x, y, z)**: the DRX_33 atoms sit on the fixed special position 4a
  (0, 0, 0), so their coordinate flags are `false` in the gsasii recipe (the
  converter wrote the flags v0.1.1 effectively refined: a symmetry-fixed
  coordinate cannot carry `true`)
- **Isotropic displacement (Uiso)**: Li, Mg, Mn1, O1, W atoms all have Uiso=true
- **Occupancies**: Li, Mg, Mn1, O1, W atoms all have occupancy=true

**Li4MgWO6_SG12 Phase (monoclinic):**
- **Coordinates (x, y, z)**: the free components of Li1, Li2, Li3, Mg, O1, O2, W
  are refined (`true`); the components fixed by site symmetry (e.g. x and z of
  the 4g/4h sites) are `false`, as the schema requires
- **Isotropic displacement (Uiso)**: All atoms locked (Uiso=false)
- **Occupancies**: All atoms locked (occupancy=false)

### Parameters Constrained:
- **Instrument parameters**: Wavelength, polarization, broadening locked

### Parameters Refined:
- **Lattice parameters**: Both phases
- **Phase scale factors**: Both phases
- **Peak broadening**: Size and strain for both phases
- **Background**: Chebyshev with 6 terms
- **Atomic coordinates**: Li4MgWO6_SG12 (the symmetry-free components); DRX_33's atoms are on a fixed position
- **Displacement parameters**: DRX_33 phase only (isotropic Uiso for all 5 atoms)
- **Occupancies**: DRX_33 phase only (all 5 atoms)

### Starting Values:
- Atomic coordinates and Uiso from CIF structural data
- Other parameters: Same as example_DRX_33

## Expected Behavior

### Convergence:
- Refinement should converge after 5 cycles
- Atom parameters may show larger shifts in first few cycles
- Coordinate refinement is sensitive to starting values

### Fit Quality:
- **Expected Rwp**: 15.06% (39 refined parameters; GSAS-II's own wR in `dummy.lst`, PowderLine's uniform `rwp` 15.059)
- Higher Rwp than base example_DRX_33 (10.83%) due to increased parameter count and model complexity
- This 39-parameter refinement is sensitive to the fit window: with v0.1.1's window (one data point more at the high end, EB-54) it converged to another minimum at Rwp 19.35%; the native path fits exactly 1 ≤ 2θ ≤ 15
- χ² should still be reasonable given the added structural freedom

### Typical Runtime:
- **Subprocess mode**: 2-4 seconds
- **Server mode**: 0.4-0.6 seconds (10x faster)

### Normal Warnings/Messages:
Typical refinement output includes:
```
Warning: 2 soft (SVD) Hessian singularities
SVD problem(s) likely from:
0:0:Size;mx, 1:0:Size;i

Note highly correlated parameters:
** 0:0:Mustrain;mx and 0:0:Mustrain;i (@100.00%)
** 1:0:Mustrain;mx and 1:0:Mustrain;i (@100.00%)
```

Additional expected warnings with atom refinement:
- High correlations between atom coordinates and displacement parameters (>90% normal)
- Correlations between atomic coordinates of nearby atoms
- Correlations between occupancy and displacement (if both refined)

**These correlations are typical for structural refinements** and indicate that multiple parameters affect peak intensities similarly. As long as the refinement converges and parameters are physically reasonable, this is not a problem.

## Schema Features Demonstrated

This example highlights the schema's **required ADP specification** and the distinction between **ADP type indicator** and **refinement control**:

### Understanding ADP:

The `ADP` field serves two purposes:
1. **Type Indicator**: which displacement parameter the atom carries ("Uiso" or "Uaniso")
2. **NOT a refinement flag**: the `ADP` string itself doesn't control whether parameters are refined

**Refinement is controlled by the `refine_flag`** (second element in `[value, refine_flag]`):

### Phase block (gsasii 0.1.0):
Each atom states its values and flags together. DRX_33's Li (fixed position 4a)
refines occupancy and Uiso; Li4MgWO6_SG12's Li1 (site 4g: x and z fixed by
symmetry) refines only y:
```json
"atoms": {
  "Li": {
    "element": "Li",
    "x": [0.0, false], "y": [0.0, false], "z": [0.0, false],  // 4a: fixed by symmetry
    "occupancy": [0.6, true],                                  // REFINED
    "ADP": "Uiso",
    "Uiso": [0.0051, true]                                     // REFINED
  },
  "Li1": {
    "element": "Li",
    "x": [0.0, false], "y": [0.33, true], "z": [0.5, false],   // only y is free on 4g
    "occupancy": [1.0, false],
    "ADP": "Uiso",
    "Uiso": [0.0, false]
  }
}
```

**Key Points:**
- `ADP` is **required** for every atom and names the parameter the atom carries
- Actual refinement is controlled by the flag of each `[value, refine_flag]`
- The schema validates the flags against the site symmetry: a `true` on a
  symmetry-fixed coordinate is an error, so the recipe states what GSAS-II varies

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
false`, warning `output_recipe_not_valid`; KI-04): the committed reference
refines the DRX_33 Li occupancy to about −0.35 and the Li4MgWO6 crystallite size to
about −8 µm, which the schema refuses; the output recipe is written and returned with
those values and the warning names them. Holding the sizes at 10 µm does not rescue
this posing (GSAS-II then fails with an invalid metric tensor); the reference is kept
as posed.

## Comparison to Related Examples

| Example | DRX_33 Atom Parameters | Li4MgWO6 Atom Parameters | Key Feature |
|---------|------------------------|--------------------------|-------------|
| example_DRX_33 | ❌ None | ❌ None | Base multi-phase refinement |
| example_DRX_33_atomrefine | ✅ x, Uiso, occupancy (all 5 atoms) | ✅ x only (7 atoms) | Demonstrate comprehensive atom parameter refinement |
| example_DRX_33_anisoADP | ❌ None | ✅ Uaniso (O1 only, 6 components) | Demonstrate anisotropic displacement parameters |
| example_DRX_33_simulation | ❌ All locked | ❌ All locked | Validate forward calculation only |

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
