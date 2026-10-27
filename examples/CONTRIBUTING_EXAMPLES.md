# JSON Examples for Schema Development

## Current Schema Version

**Schema 0.26.0** - Current stable version

### Key Changes from Previous Versions

- **Per-parameter refine flags honored (0.26)**: unit-cell parameters, atomic
  coordinates, and anisotropic Uij components refine iff present with
  `refine_flag=true`; absent or `false` means fixed. Symmetry-linked parameters
  (e.g. cubic a=b=c) refine together if any member is requested; flags on
  symmetry-fixed parameters have no effect.
- **Payload-based structure**: All recipe fields now under `"payload"` key
- **Fixed output filenames**: `dummy.gpx` and `dummy.lst` (independent of sample names)
- **Removed fields**: `sample_name` and `recipe_description` (metadata should be external)
- **Schema identification**: Required `"schema_name"` field (`"GSASII_Rietveld"` or `"GSASII_SPF"`)

### Refine-flag style for shipped examples

Shipped examples use the **explicit style**: every parameter of a class is
listed with a symmetry-consistent flag (e.g. a cubic phase that refines its
cell sets `a`, `b`, and `c` all `true`), so a reader sees the full intent
without knowing the symmetry rules. Listing only the parameters you wish to
refine (absence = fixed) is equally valid and more compact. PowderLine does not
validate flag/symmetry consistency - keep flags consistent within
symmetry-linked groups so the recipe honestly states what will refine.

**Example Structure**:
```json
{
  "schema_name": "GSASII_Rietveld",
  "schema_version": "0.26.0",
  "payload": {
    "xrd_data": { ... },
    "instrument": { ... },
    "phases": { ... },
    "background": { ... },
    "refinement_controls": { ... }
  }
}
```

For migrating examples from earlier schemas, see [docs/SCHEMA_HISTORY.md](../docs/SCHEMA_HISTORY.md).

## Purpose

This directory collects real-world GSAS-II refinement scenarios from collaborators. These examples drive the development of the JSON schema that PowderLine will use to define refinements.

The schema will evolve organically based on actual use cases rather than premature abstraction.

## How to Contribute an Example

1. **Copy the template**:
   ```bash
   cd examples
   cp -r example_template/ my_refinement_name/
   ```

2. **Add your input**: Edit `input.json` with the parameters for your refinement case

3. **Add context**: Edit `DESCRIPTION.md` to explain:
   - Scientific purpose (what are you refining?)
   - Input parameters (constraints, starting values, what phases?)
   - Expected behavior (what should GSAS-II do?)
   - Known issues or special considerations

4. **Run the refinement** (Phase 1 implementation): Once the kicker is implemented, run your example and capture output in `output/`

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
├── input.json          # JSON defining the refinement
├── output/             # GSAS-II results (logs, .gpx files, etc.)
└── DESCRIPTION.md      # Context and explanation
```

### File Descriptions

**`input.json`**: The JSON file that defines this refinement. This is what gets passed to the PowderLine kicker. Initially this may be freeform - add whatever fields make sense for your refinement. As examples accumulate, patterns will emerge that define the schema.

**`output/`**: After running the refinement, GSAS-II output files go here. **These output files should be committed to the repository** - they serve as reference outputs for validation and regression testing, allowing us to verify that code changes produce consistent results across different refinements.

PowderLine generates fixed output filenames:

**Standard outputs:**
- `dummy.gpx` - GSAS-II project file (reopenable in GUI)
- `dummy.lst` - Human-readable refinement log with Rwp and parameter tables
- `refined_parameters.csv` - All refined parameters with ESDs (9 columns: parameter_name, descriptive_name, phase_name, phase_idx, atom_name, atom_idx, value, esd, category)
- `<phase_name>_unit_cell_report.csv` - Unit cell parameters with ESDs (3 columns: parameter, value, esd)
- `<phase_name>_peak_list_report.csv` - Reflection lists (hkl, d-spacing, 2θ, intensities) per phase
- `fit_profile.txt` - Observed/calculated/background/difference intensities

**Single peak fitting mode (SPF) additional files:**
- `single_peaks_report.txt` - Peak fit results (position, width, intensity per peak)
- `peak_convergence_diagnostics.txt` - Convergence warnings for aphysical parameters

**Note:** Simulation mode (all `refine_flag=false`) does not generate `refined_parameters.csv` since no parameters are refined. Unit cell reports are still generated, with an empty `esd` column (read as `NaN`).

**`DESCRIPTION.md`**: Explains the scientific purpose, input parameters, expected behavior, and any known issues for this specific refinement. Just fill in the template sections.

## Schema Evolution

As examples accumulate, patterns will emerge that define:
- Required fields vs optional fields
- Parameter naming conventions
- Data structure organization
- Common refinement workflows

These patterns will be formalized into the v0.1 JSON schema in `src/powderline/schema.py`.

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
- Set in `phases.<phase_name>.parameterization.scale`
- Only one value per phase (shared across all histograms)
- Typically has largest refinement sensitivity
- Example: `"scale": [1.0, true, null, null]`

**Histogram Scale Factor**: Refines detector response (detector efficiency, air absorption)
- Set at histogram level (currently fixed in Phase 1B)
- One value per histogram (multiple phases can share one histogram)
- Typically kept fixed or refined last

**Multi-Phase Example**:
```json
{
  "schema_name": "GSASII_Rietveld",
  "payload": {
    "phases": {
      "DRX_cubic": {
        "parameterization": {
          "scale": [0.5, true, null, null]
        }
      },
      "Li4MgWO6": {
        "parameterization": {
          "scale": [0.3, true, null, null]
        }
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

1. **Set all refine_flags to false (payload structure)**:
   ```json
   {
     "schema_name": "GSASII_Rietveld",
     "payload": {
       "refinement_controls": {
         "refinement_cycles": 1
       },
       "phases": {
         "YourPhase": {
           "parameterization": {
             "scale": [0.5, false, null, null],
             "unit_cell": {
               "a": [5.0, false, null, null]
             },
             "peak_broadening": {
               "size_broadening": {
                 "isotropic_size": [10.0, false, null, null],
                 "LG_eta": [0.5, false, null, null]
               }
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
         "parameterization": {
           "wavelength": [0.45236, false, null, null],
           "broadening": {
             "U": [0.01, false, null, null]
           }
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
   - Rwp = 100% (y_calc != y_obs since no optimization is done, meaningless metric)
   - Output y_calc should be IDENTICAL across multiple runs

   **Verification:** The test suite runs this simulation twice and verifies that
   y_calc values match exactly between runs. Any differences indicate non-determinism.
   ```

3. **Include a note about Rwp**:
   Simulation mode produces y_calc != y obs since no optimization is done, so Rwp will be 100%. This is **not**
   a measure of fit quality. It's a validation that the
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
