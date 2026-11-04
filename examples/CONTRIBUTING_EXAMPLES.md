# JSON Examples for Schema Development

## Current Schemas

A recipe names its engine and workflow in `schema_name` and carries two
versions: `core_schema_version` (the engine-independent part: data, phase
blocks, fit window; **0.1.0**) and `engine_schema_version` (the engine's own
instrument, background and controls; **0.1.0** for every engine). The
committed examples use:

| `schema_name` | Engine | Where |
|---|---|---|
| `gsasii.rietveld`, `gsasii.spf` | GSAS-II (reference engine; has committed output) | `examples/<case>/input.json` |
| `topas.rietveld`, `topas.spf` | TOPAS 6 | `examples/<case>/topas/input.json` |
| `easydiffraction.rietveld` | easydiffraction | `examples/<case>/easydiffraction/input.json` |

### Key points

- **Parameters**: gsasii recipes write every refinable as `[value, refine_flag]`
  (GSAS-II applies limits only after a fit, so no bounds); topas and
  easydiffraction recipes write `[value, refine_flag, min, max]` (`null` for no
  bound). A parameter refines iff its flag is `true`.
- **Flags are checked against the symmetry** when the recipe is validated: a
  refined strict subset of a tie group (e.g. only `a` of a cubic cell), or a
  refined symmetry-fixed coordinate / Uij, is an error. Shipped examples use
  the **explicit style** - every parameter listed with a symmetry-consistent
  flag - so a reader sees the full intent; listing only what you refine is
  equally valid.
- **Space groups** are canonical gemmi names (`P m -3 m`, `C 1 2/m 1`,
  `F d -3 m:2`); the gsasii schema also refuses settings GSAS-II cannot read.
- **One phase block**: structure and parameterization are one `phases.<name>`
  block (`space_group`, `unit_cell`, `atoms`, plus the engine's fields such as
  gsasii `scale` and `peak_broadening`). The phase name is its key.
- **Native engine terms**: a topas recipe states TOPAS's keywords and units
  (`TCHZ_Peak_Type` U/V/W in degrees², `CS_L` in nm, ...), an easydiffraction
  recipe easydiffraction's (`broad_gauss_u`, `calculator`, ...). There is no
  converter between engines: each per-engine recipe is derived by hand, as
  `tests/data/topas/native/README.md` and
  `tests/data/easydiffraction/native/README.md` describe.
- **Fixed output filenames**: `dummy.gpx`, `dummy.lst`, `refined_parameters.csv`,
  `<phase>_unit_cell_report.csv`, `<phase>_peak_list_report.csv`, `fit_profile.txt`.

**Example structure (gsasii)**:
```json
{
  "schema_name": "gsasii.rietveld",
  "core_schema_version": "0.1.0",
  "engine_schema_version": "0.1.0",
  "payload": {
    "xrd_data": { ... },
    "instrument": { ... },
    "fit_range": [1.0, 15.0],
    "background": { ... },
    "phases": { ... },
    "refinement_controls": { ... }
  }
}
```

For the schema rules and the migration from schema 0.26.0 (the
`scripts/convert_recipe_026.py` converter), see
[docs/SCHEMA_HISTORY.md](../docs/SCHEMA_HISTORY.md).

### Validating a recipe

Every recipe validates in any environment, no engine needed:

```bash
powderline my_refinement_name/input.json --validate-only            # installed command
pixi run kicker my_refinement_name/input.json --validate-only       # from a checkout
```

This works the same for a `gsasii.*`, `topas.*` or `easydiffraction.*` recipe
(the engine comes from `schema_name`); it prints the schema, the phase count
and the structured warnings (e.g. a default that was applied). The template
files are refused on purpose (`template` in the path): copy the template into
your own directory first, then validate the copy. A *run* needs the engine's
environment: `pixi run -e gsasii kicker ...` for GSAS-II, `tc.exe` on win-64
for TOPAS (with `--topas-version 6`), `pixi run -e easydiffraction kicker ...`
for easydiffraction. The default environment validates but runs nothing.

## Purpose

This directory collects real-world refinement scenarios from collaborators. These examples drive the development of the recipe schemas (core + per engine) and are the regression references of the GSAS-II path.

The schemas evolve based on actual use cases rather than premature abstraction; a change in what an example computes is a deliberate change (see `docs/policies.md`).

## How to Contribute an Example

1. **Copy the template**:
   ```bash
   cd examples
   cp -r example_template/ my_refinement_name/
   ```
   `example_template/input.json` is a `gsasii.rietveld` skeleton;
   `example_template/topas/input.json` and
   `example_template/easydiffraction/input.json` are the per-engine skeletons.
   Delete the engine directories you do not fill in.

2. **Add your input**: Edit `input.json` with the parameters for your refinement
   case, then validate it (`powderline my_refinement_name/input.json --validate-only`)

3. **Add context**: Edit `DESCRIPTION.md` to explain:
   - Scientific purpose (what are you refining?)
   - Input parameters (constraints, starting values, what phases?)
   - Expected behavior (what should GSAS-II do?)
   - Known issues or special considerations

4. **Run the refinement**: `pixi run -e gsasii kicker my_refinement_name/input.json`
   writes `output/` next to the recipe; commit it (it becomes a regression
   reference). For an `easydiffraction.*` recipe, `pixi run -e easydiffraction
   kicker my_refinement_name/easydiffraction/input.json` writes
   `easydiffraction/output/`; commit it too. For a `topas.*` recipe, commit the
   recipe and its README only (its reference comes from the TOPAS machine).

5. **Submit your example via Pull Request**:
   ```bash
   # From a PowderLine checkout, create a new branch for your example
   git checkout -b add-example-<my_refinement_name>

   # Add your example files
   git add examples/my_refinement_name/
   git commit -m "Add example: <brief description>"

   # Push the branch and open a Pull Request
   git push origin add-example-<my_refinement_name>
   ```

## Directory Structure

Each example should follow this structure:

```
my_refinement_name/
├── input.json                 # the gsasii.* recipe (the reference engine)
├── output/                    # its GSAS-II results (regression references)
├── DESCRIPTION.md             # context and explanation
├── topas/input.json           # optional: the same case as a topas.* recipe (+ README.md)
└── easydiffraction/           # optional: the same case as an easydiffraction.* recipe
    ├── input.json             #   (+ README.md)
    └── output/                #   its easydiffraction results (regression references)
```

### File Descriptions

**`input.json`**: The recipe that defines this refinement; it must pass
`powderline input.json --validate-only`. Per-engine recipes live in the
`topas/` and `easydiffraction/` subdirectories with a short README saying how
they were derived. An easydiffraction recipe's results are committed in
`easydiffraction/output/` beside it (the same fixed filenames, no `dummy.*`);
no TOPAS output is committed under `examples/` yet (the TOPAS 6 goldens live in
`tests/data/topas/native/golden/`).

**`output/`**: After running the refinement, the GSAS-II output files go here. **These output files should be committed to the repository** (except `dummy.gpx`, which is gitignored) - they are the regression references, compared within the tolerances of `docs/regression-tolerance.md`; they move only as a recorded deliberate change.

PowderLine generates fixed output filenames:

**Standard outputs:**
- `dummy.gpx` - GSAS-II project file (reopenable in GUI)
- `dummy.lst` - Human-readable refinement log with Rwp and parameter tables
- `refined_parameters.csv` - All refined parameters with ESDs (9 columns: parameter_name, descriptive_name, phase_name, phase_idx, atom_name, atom_idx, value, esd, category)
- `<phase_name>_unit_cell_report.csv` - Unit cell parameters with ESDs (3 columns: parameter, value, esd; seven rows `cell_a` … `cell_volume`, the same for every engine — `docs/schemas.md`, "Two vocabularies, one bridge")
- `<phase_name>_peak_list_report.csv` - Reflection lists (hkl, d-spacing, 2θ, intensities) per phase
- `fit_profile.txt` - Observed/calculated/background/difference intensities
- `output_recipe.json` - The resolved recipe with the refined values written back (KI-04); its `metadata.powderline_provenance` block (run id, timestamp, engine version) is run-specific. When a refinement ends on a value the schema refuses, it is written anyway and is not valid as written (KI-15)
- `parameter_dispositions.csv` - One row per refinable value: path, value, esd, disposition, at_limit

**Single peak fitting mode (SPF) additional files:**
- `single_peaks_report.txt` - Peak fit results (position, width, intensity per peak)
- `peak_convergence_diagnostics.txt` - Convergence warnings for aphysical parameters; written **only when a peak has a convergence issue** (a clean fit, like the committed `example_LaB6_singlepeakfit` reference, has no such file)

**Note:** Simulation mode (all `refine_flag=false`) does not generate `refined_parameters.csv` since no parameters are refined. Unit cell reports still generated with `esd=0.0`.

**`DESCRIPTION.md`**: Explains the scientific purpose, input parameters, expected behavior, and any known issues for this specific refinement. Just fill in the template sections.

## Schema Evolution

As examples accumulate, patterns will emerge that define:
- Required fields vs optional fields
- Parameter naming conventions
- Data structure organization
- Common refinement workflows

The schemas live in `src/powderline/schema_core.py` (core) and each gateway's `schema.py` (`src/powderline/gateways/<engine>/`).

## Example Categories

Examples may cover:
- Simple single-phase refinements
- Multi-phase refinements
- Constrained parameter refinements
- Batch processing scenarios
- Edge cases and error handling

## Important Concepts for Contributors

### Scale Factors: Histogram vs Phase

When setting up your refinement, understand the distinction between scale factors:

**Phase Scale Factor**: Refines the absolute scale of intensities for that phase
- Set in `phases.<phase_name>.scale`
- Only one value per phase (shared across all histograms)
- Typically has largest refinement sensitivity
- Example: `"scale": [1.0, true]`

**Histogram Scale Factor**: Refines detector response (detector efficiency, air absorption)
- Set at histogram level (currently fixed in Phase 1B)
- One value per histogram (multiple phases can share one histogram)
- Typically kept fixed or refined last

**Multi-Phase Example**:
```json
{
  "schema_name": "gsasii.rietveld",
  "payload": {
    "phases": {
      "DRX_cubic": {
        "scale": [0.5, true]
      },
      "Li4MgWO6": {
        "scale": [0.3, true]
      }
    }
  }
}
```

Each phase scale refines independently to match its contribution to the observed pattern.

### Parameter Correlation in GSAS-II

When you see warnings like:
```
** Warning: parameters 0 and 1 are 99.8% correlated **
```

This is **usually normal** and doesn't indicate a problem. Common high-correlation pairs:
- Background Chebyshev coefficients (they share similar ranges)
- Instrument broadening parameters (U, V, W in Thompson-Cox-Hastings)
- Size and strain broadening (both affect peak width)

**When correlation IS a problem**:
- Correlation >99.95% AND parameter uncertainties are large
- Refinement oscillates without converging
- Parameter values become unphysical (negative sizes, unreasonable unit cells)

**How to reduce problematic correlations**:
1. Decrease number of background terms (reduce num_coefficients)
2. Expand fit range to include more data
3. Fix some parameters (set refine_flag to false)
4. Refine sequentially: background → scale → unit cell → peak broadening

## Simulation Mode Examples

Simulation examples are special cases where **all refinement parameters must be locked** (`refine_flag: false`) to produce deterministic output that doesn't vary between runs. These are useful for validating that the forward calculation (generating y_calc from structure parameters) works correctly, independently of the refinement algorithm.

### Requirements for Simulation Examples

If you're creating a simulation-mode example (all parameters fixed), you **MUST**:

1. **Set all refine_flags to false** (the gsasii schema rejects a refine flag
   when `refinement_cycles` is 1, so a mistake fails at validation):
   ```json
   {
     "schema_name": "gsasii.rietveld",
     "payload": {
       "refinement_controls": {
         "refinement_cycles": 1
       },
       "phases": {
         "YourPhase": {
           "scale": [0.5, false],
           "unit_cell": {
             "a": [5.0, false]
           },
           "peak_broadening": {
             "size_broadening": {
               "isotropic_size": [10.0, false],
               "LG_eta": [0.5, false]
             }
           }
         }
       },
       "background": {
         "chebyshev": {
           "num_coefficients": 3,
           "coefficients": [100.0, -50.0, 10.0],
           "refine_flag": false  // CRITICAL: Must be false
         }
       },
       "instrument": {
         "radiation": {"type": "PXC", "wavelength": [0.45236, false]},
         "broadening": {
           "U": [0.01, false]
         }
       }
     }
   }
   ```

2. **Document the constraint explicitly** in DESCRIPTION.md:
   ```markdown
   ## Simulation Mode Details

   **ALL structural and peak broadening parameters are locked** (`refine_flag=false`)
   for deterministic output. This example validates the forward calculation:

   - Refined parameters: NONE (all locked)
   - The result says `simulation_mode: true`; its `rwp` is the uniform statistic
     against the placeholder data and means nothing (GSAS-II's own 100 % is
     under `engine_details`)
   - Output y_calc should be IDENTICAL across multiple runs

   **Verification:** The test suite runs this simulation twice and verifies that
   y_calc values match exactly between runs. Any differences indicate non-determinism.
   ```

3. **Include a note about the fit statistics**:
   Simulation mode produces y_calc != y_obs since no optimization is done, so
   the reported statistics are **not** a measure of fit quality (GSAS-II itself
   reports 100 %, kept under `engine_details`). The run is a validation that the
   forward model is correctly implemented without influence from the observed pattern.

### Why This Matters

Simulation examples have two purposes:
- **Validation**: Verify that GSAS-II forward calculations work correctly
- **Regression testing**: Ensure code changes don't introduce numerical instability

If even one parameter has `refine_flag: true`, the output will vary between runs (depending on GSAS-II's convergence behavior), breaking regression tests that expect deterministic output. This is a **critical bug** if it occurs unintentionally.

### Testing Simulation Examples

When you add a simulation example, it will be automatically included in determinism tests:

```python
def test_simulation_determinism_YourExample(example_input, tmp_path):
    """Verify simulation example produces identical y_calc on multiple runs"""
    # Runs example twice in separate directories
    # Compares fit_profile.txt y_calc column with exact equality
    # Fails if any parameters are being refined
```

If this test fails:
1. Check DESCRIPTION.md for the constraint documentation
2. Verify ALL `refine_flag` values are `false`
3. Verify `refinement_cycles` is 1
4. Look for any background or instrument parameters that might have `refine_flag: true`

### Expected Parameter Correlation Warnings

Different refinement setups produce expected warning patterns:

**LaB6 single-phase synchrotron**:
- Background coefficients: 95-99% correlated (expected)
- Instrument broadening (U, V, W): 90-98% correlated (expected)
- Unit cell ↔ scale: <20% correlated (good - independent effects)

**Multi-phase DRX_33**:
- Phase scales: ~10-15% correlated (independent phases)
- Background coefficients: 95%+ correlated (expected with broad background)
- Phase 1 parameters ↔ Phase 2 parameters: <5% correlated (good separation)

**Hexagonal systems** (e.g. corundum-type oxides):
- Unit cell (a and c link through symmetry): 40-60% correlated (expected)
- Atom parameters: 70%+ correlated (expected for similar elements)
- These are NORMAL for hexagonal systems

### Documenting Expected Results

When adding your example, help future users by noting in your DESCRIPTION.md:

```markdown
## Expected Behavior

- **Target Rwp**: ~10.5%
  - ≤8%: Excellent fit, check for over-refinement
  - 8-12%: Good fit, typical for polycrystalline data
  - 12-20%: Acceptable, may indicate data quality issues
  - >20%: Investigate model or data issues

- **Parameter Correlations**:
  - Background terms: ~95% (expected, not a problem)
  - Scale ↔ Unit cell: <20% (expected, good independence)

- **Refinement Convergence**:
  - Converges in 5-7 cycles with step reduction
  - No oscillation observed
  - Rwp smoothly decreases

- **Known Issues**:
  - Space group normalization behavior (e.g., R-3m → R-3c)
  - Phase fractions vs mass fractions
  - Data quality limitations
```

This helps contributors and users understand whether their results are reasonable.

## Questions?

If you're unsure how to structure your example, just add it in whatever format makes sense and note your questions in the DESCRIPTION.md. The schema will adapt to real needs.

For technical questions about scale factors, parameter correlation, or expected results, see the "Important Concepts" section above.
