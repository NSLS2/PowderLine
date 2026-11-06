# Multi-phase refinement with anisotropic displacement parameters (ADPs)

> **Teaching example.** This refinement is ill-posed on purpose. It adds
> anisotropic ADPs to the size and strain refinement of `example_DRX_33`,
> which the data cannot separate: the DRX_33 crystallite size runs to about
> −9.7 µm. The negative size makes the output recipe not valid
> (`output_recipe_valid: false`, warning `output_recipe_not_valid`). The O1
> tensor also ends unphysical, with U11 = −0.170(12) Å². Holding both sizes at 10 µm, as
> `example_DRX_33_strainonly` does, gives a valid output recipe and Rwp 8.58 %
> against 15.53 % here; see *Known Issues*. More in
> [Teaching examples](../../docs/examples/index.md#teaching-examples).

## Scientific Purpose

This example demonstrates **anisotropic atomic displacement parameter refinement** in PowderLine. While `example_DRX_33_atomrefine` uses isotropic displacement (single Uiso value per atom), this example refines **full anisotropic displacement tensors** with six independent components (U11, U22, U33, U12, U13, U23).

Anisotropic ADPs are critical for:
- **High-resolution structural analysis** - capturing directional thermal motion
- **Materials with anisotropic bonding** - different thermal motion along different crystal axes
- **Low-temperature refinements** - where anisotropic effects become significant
- **Publication-quality structures** - anisotropic ADPs are standard for single-crystal refinements

The refinement uses the same disordered rocksalt battery material (DRX_33 + Li4MgWO6_SG12); the **O1 atom of the Li4MgWO6_SG12 phase** (general position 8j of C 1 2/m 1) is refined with anisotropic ADPs while every other atom stays isotropic and fixed.

## Input Parameters

- **Data source**: Same as example_DRX_33 (embedded XRD data in JSON payload)
- **Phases being refined**: DRX_33 (cubic) and Li4MgWO6_SG12 (monoclinic)

### Atom Parameters Being Refined:

**Li4MgWO6_SG12 Phase (monoclinic):**
- **Anisotropic displacement (O1 atom only)**:
  - U11, U22, U33 (diagonal elements) - thermal motion along a, b, c axes
  - U12, U13, U23 (off-diagonal elements) - thermal motion correlations between axes
  - All 6 components have `refine_flag=true` (O1 sits on the general position, so
    all six are independent; on a special position the schema would require the
    symmetry-tied components to carry the same flag)
  - Coordinates: All locked (x=false, y=false, z=false)
  - Occupancy: Locked (occupancy=false)

- **Other atoms (Li1, Li2, Li3, Mg, O2, W)**: All parameters locked (isotropic Uiso)

**DRX_33 Phase (cubic):**
- All atomic parameters locked (isotropic Uiso, no atom refinement)

### Parameters Constrained:
- **All atomic coordinates**: Locked in both phases
- **All occupancies**: Locked in both phases
- **Displacement parameters**: All locked except the Li4MgWO6_SG12 O1 atom's Uaniso
- **Instrument parameters**: Wavelength, polarization, broadening locked

### Parameters Refined:
- **Lattice parameters**: both phases (DRX_33: `a`, `b`, `c`, one cubic tie group; Li4MgWO6_SG12: `a`, `b`, `c`, `beta`)
- **Phase scale factors**: Both phases
- **Peak broadening**: Size and strain for both phases
- **Background**: Chebyshev with 6 terms
- **Anisotropic displacement**: Li4MgWO6_SG12 O1 atom (all 6 Uij components)

### Starting Values:
- **Anisotropic ADPs**: Initialized with reasonable values reflecting expected anisotropy
  - U11 = 0.010, U22 = 0.012, U33 = 0.008 (diagonal)
  - U12 = 0.002, U13 = 0.001, U23 = 0.003 (off-diagonal)
- Other parameters: Same as example_DRX_33

## Expected Behavior

### Convergence:
- Refinement should converge after 5 cycles
- The six Uij components of one atom can correlate strongly on powder data
- In this run the O1 tensor ends unphysical: U11 = −0.170(12) Å² and
  U23 = −0.101(17) Å² (see *Positive-Definite Constraint* below)

### Fit Quality:
- **Expected Rwp**: 15.53% (27 refined parameters; GSAS-II's own wR in `dummy.lst`, PowderLine's uniform `rwp` 15.530)
- Rwp is higher than the 10.83 % of `example_DRX_33` although more parameters
  are free: the fit has moved to a worse, unphysical minimum (see the banner
  above), not a better model
- Powder data carry little information about anisotropy; single-crystal data
  resolve it better

### Typical Runtime:
- **Subprocess mode**: 2-4 seconds
- **Server mode**: 0.4-0.6 seconds

### Normal Warnings/Messages:
Typical refinement output with anisotropic ADPs:
```
Warning: Highly correlated parameters:
** O1:U11 and O1:U22
** O1:U11 and O1:U33
** O1:U12 and O1:U13
```

Read these correlations as a warning. A strong correlation means the data
cannot separate the parameters. Here they go with an O1 tensor that is not
positive definite, so it describes no thermal ellipsoid. See
[Know which parameters fight each other](../../docs/concepts/refinement-practice.md#know-which-parameters-fight-each-other).

Additional warnings may include:
```
Warning: 2 soft (SVD) Hessian singularities
SVD problem(s) likely from: 0:0:Size;mx, 1:0:Size;i
```
These are related to peak broadening parameters and are independent of the anisotropic ADP refinement.

## Schema Features Demonstrated

This example showcases **anisotropic ADP support** and clarifies the distinction between **ADP type** and **refinement flags**:

### Understanding ADP:

The `ADP` field is a **type indicator**, not a refinement flag:
- `"ADP": "Uiso"` → the atom carries a `Uiso` parameter
- `"ADP": "Uaniso"` → the atom carries a `Uaniso` dict with U11-U23 parameters
- **Refinement is controlled** by the flag in each `[value, refine_flag]`

### Phase block (gsasii 0.1.0):
Each atom states its values and flags in one place. Li4MgWO6_SG12's O1 declares
anisotropic displacement with every component refined; Li1 stays isotropic and fixed:
```json
"atoms": {
  "O1": {
    "element": "O",
    "x": [0.238, false], "y": [0.343, false], "z": [0.234, false],
    "occupancy": [1.0, false],
    "ADP": "Uaniso",
    "Uaniso": {
      "U11": [0.01, true],   "U22": [0.012, true],  "U33": [0.008, true],
      "U12": [0.002, true],  "U13": [0.001, true],  "U23": [0.003, true]
    }
  },
  "Li1": {
    "element": "Li",
    "x": [0.0, false], "y": [0.33, false], "z": [0.5, false],
    "occupancy": [1.0, false],
    "ADP": "Uiso",
    "Uiso": [0.0, false]
  }
}
```

**Key Points:**
- When `ADP="Uaniso"`, all 6 Uij values are given as `[value, refine_flag]`; an atom has either `Uiso` or `Uaniso`
- Mixed ADP types allowed: O1 uses anisotropic, every other atom isotropic
- The schema ties the Uij flags to the site symmetry (a symmetry-fixed component cannot be refined; tied components refine together)
- `ADP` string is a **type indicator**, `refine_flag` controls actual refinement

## Physical Interpretation

### Thermal Ellipsoid:
The refined Uij values define a thermal ellipsoid representing the atom's vibrational motion:
- **Diagonal terms (U11, U22, U33)**: Motion along crystallographic axes a, b, c
- **Off-diagonal terms (U12, U13, U23)**: Correlations between axes

For a general-position oxygen in the monoclinic Li4MgWO6_SG12 phase (C 1 2/m 1) all six
components are independent; a physically reasonable result has:
- U11, U22, U33 positive and of similar magnitude
- U12, U13, U23 small compared with the diagonal terms

Significant deviations suggest:
- Anisotropic bonding environment
- Static disorder (atoms displaced from ideal positions)
- Incorrect structural model

### Positive-Definite Constraint:
The Uij tensor must be **positive-definite** (all eigenvalues > 0) to represent
physical thermal motion. GSAS-II does not enforce this during refinement
(EB-50). PowderLine's core warns with `uaniso_not_positive_definite` when a
recipe states a `Uaniso` with a principal value ≤ 0, and uses the tensor as
stated.

This example's refined O1 tensor is not physical. U11 is −0.170(12) Å², and
two of the tensor's three principal values are negative. A non-positive-definite
tensor indicates:
- Over-parameterization (too many refined ADPs for available data)
- Poor starting values
- Model errors

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
false`, warning `output_recipe_not_valid`; KI-04): the committed reference
refines the DRX_33 isotropic crystallite size to about −9.7 µm (ESD ≈ 1.3 µm), which
the schema refuses; the output recipe is written and returned with that value and
the warning names it. Holding both sizes at 10 µm (the `example_DRX_33_strainonly`
posing: `isotropic_size` and its `LG_eta` fixed, strain refined) gives Rwp 8.58 %
against 15.53 % here with a valid output recipe; the reference is kept as posed.

If anisotropic refinement fails to converge or produces unphysical Uij values:
1. Check that starting values are reasonable (diagonal > 0, off-diagonal small)
2. Consider fixing off-diagonal terms (U12, U13, U23) initially
3. Ensure sufficient data quality (high-resolution powder data required for anisotropic ADPs)

## Comparison to Related Examples

| Example | DRX_33 Atom Parameters | Li4MgWO6 Atom Parameters | Key Feature |
|---------|------------------------|--------------------------|-------------|
| example_DRX_33 | ❌ None | ❌ None | Base multi-phase refinement |
| example_DRX_33_atomrefine | ✅ Uiso, occupancy (all 5 atoms; coordinates fixed by symmetry) | ✅ free coordinates only (5 atoms) | Comprehensive atom parameter refinement |
| example_DRX_33_anisoADP | ❌ None | ✅ Uaniso (O1 only, 6 components) | **Full anisotropic displacement tensors** |
| example_DRX_33_simulation | ❌ All locked | ❌ All locked | Validate forward calculation only |

## When to Use Anisotropic ADPs

**Use anisotropic ADPs when:**
- High-resolution data available (d-spacing resolution < 1 Å)
- Publication-quality structure refinement needed
- Anisotropic bonding expected (layered materials, molecular crystals)
- Low-temperature data (thermal effects dominate)

**Use isotropic ADPs when:**
- Routine refinements (phase identification, quantification)
- Limited data resolution (powder diffraction with broad peaks)
- Early refinement stages (converge structure first, then add anisotropy)
- Highly disordered materials (anisotropy not physically meaningful)

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
