# LaB6 Powder Diffraction Pattern Simulation

## Overview

This example demonstrates **powder diffraction pattern simulation** using PowderLine's kicker workflow. Instead of refining parameters against experimental data, this recipe generates a calculated powder diffraction pattern using a fixed crystal structure and instrument configuration.

## What is Simulation Mode?

In simulation mode, all refinement parameters have `refine_flag: false`:
- **Background**: Chebyshev coefficients are fixed
- **Instrument**: Broadening parameters (U, V, W, X, Y, Z) are locked
- **Phase structure**: Unit cell parameters and atomic positions are fixed
- **Scale factor**: Not refined
- **Result**: Single calculation pass → calculated pattern with no iterative fitting

This is useful for:
- **Pattern prediction**: Predict what a powder diffraction pattern should look like for a given structure
- **Instrument validation**: Test if instrument broadening parameters produce expected peak shapes
- **Educational use**: Demonstrate how crystal structure and instrument parameters combine to create observed patterns
- **Baseline calculation**: Generate clean calculated pattern without noise from refinement fitting
- **Synthetic data generation**: Create synthetic XRD data for testing analysis pipelines

## Schema Features Demonstrated

This example demonstrates simulation mode capabilities:

- **Pure simulation mode**: All parameters have `refine_flag: false` (no optimization)
- **Single-cycle execution**: `refinement_cycles: 1` with locked parameters (pure calculation)
- **Complete parameter specification**: All structural, background, and instrument parameters provided
- **Meaningless fit statistics**: `rwp` compares the simulated pattern with the placeholder data (Ycalc not optimized to Yobs); GSAS-II's own 100 % is under `engine_details`
- **Forward calculation**: Demonstrates theoretical pattern generation from known structure
- **Same schema as refinement**: Uses identical JSON structure with different refine_flag values

## Key Differences from Refinement

| Aspect | Refinement Mode | Simulation Mode |
|--------|-----------------|-----------------|
| `refine_flag` values | `true` for parameters to fit | `false` for all parameters |
| `refinement_cycles` | 5 (typical value) | 1 (all params locked, no optimization) |
| Output $R_{wp}$ | Quality of fit to data | meaningless (no fit is attempted; Ycalc not optimized to Yobs) |
| Processing time | Minutes (GSAS-II iteration) | Seconds (single calculation) |
| Purpose | Parameter extraction | Pattern prediction |

## How It Works

1. **Structure Input**: Same LaB6 crystal structure as refinement example (cubic, Pm-3m)
2. **Parameter Lock**: All parameters set to fixed values from previous refinements
3. **Pattern Calculation**: GSAS-II generates theoretical powder pattern
4. **Output**: Fit profile, unit cell report, peak list (all calculated, no residuals)

## Running the Simulation

```bash
# Standard invocation
pixi run -e gsasii kicker examples/example_LaB6_simulation/input.json

# With verbose output
pixi run -e gsasii kicker examples/example_LaB6_simulation/input.json --verbose

# Validate without running
pixi run kicker examples/example_LaB6_simulation/input.json --validate-only
```

## Output Files

This simulation produces:

- **dummy.gpx** - GSAS-II project file (gitignored)
- **dummy.lst** - Log file (shows 1 cycle with no parameter changes)
- **LaB6_unit_cell_report.csv** - Unit cell parameters (unchanged from input; every `esd` is `0.0` — nothing refined, no covariance)
- **LaB6_peak_list_report.csv** - Reflection list (hkl, d-spacing, 2θ, intensities)
- **fit_profile.txt** - Calculated pattern (2θ, Iobs, Iweight, Icalc, Ibackground, Idifference)

**Note**: Simulation mode does NOT produce `refined_parameters.csv` because no parameters are refined (all `refine_flag: false`). The reported `rwp` is PowderLine's uniform statistic of the calculated pattern against the placeholder data and is meaningless in simulation mode; the result carries `simulation_mode: true`.

## Comparison with Refinement Example

This example is based on the refinement example (`examples/example_LaB6/`), but with:
- All `refine_flag: false` (locked parameters)
- `refinement_cycles: 1` (schema requires ≥1; with all params locked, no optimization occurs)
- Same LaB6 structure, instrument setup, and XRD data
- Same background model (Chebyshev coefficients)
- Like `example_LaB6`, the background peak of the schema-0.26.0 recipe was removed at the conversion to `gsasii.rietveld` (PowderLine 0.2.0): invisible here (0.0126 counts high), undeterminable there

To convert any refinement recipe to simulation mode:
1. Recursively set all `refine_flag` values to `false` (structure, background, instrument, broadening)
2. Set `refinement_cycles` to 1 (schema minimum; with all parameters locked, no optimization occurs)
3. Keep all parameter values and XRD data unchanged
4. Verify all parameters are locked before running

## Technical Details

**Simulation Method**: all `refine_flag` are `false` and `refinement_cycles` is 1, so the gsasii gateway runs one GSAS-II pass with nothing varied; `y_calc` is the theoretical pattern and the fit statistics against the placeholder data are meaningless (`simulation_mode: true`).

**Why Reuse the Refinement Workflow**:
- GSAS-II's pattern calculation is part of the refinement cycle
- Setting `refine_flag=false` naturally prevents parameter updates
- Output extraction (y_calc, background, residuals) works identically
- Maintains Phase 1 philosophy: features via examples, not separate tools

## Data Source

- **XRD Data**: LaB6 standard reference material (660c), collected at beam line 28-ID-2 (Pair Distribution Function, National Synchrotron Light Source II)
- **Crystal Structure**: LaB6, cubic, space group Pm-3m, a ≈ 4.15682 Å
- **Instrument**: High-energy X-rays (74.46 keV, λ ≈ 0.1665 Å)

## Extensions

Simulation mode enables several uses, some already demonstrated:
1. **Batch Simulation**: Generate patterns for parameter space surveys
2. **Noise Addition**: Add synthetic noise to calculated patterns — done: `example_LaB6_temperature_series` and `example_LaB6_textured` (Poisson counts, seeded)
3. **Preferred Orientation**: Simulate textured samples — done: `example_LaB6_textured` (March–Dollase)
4. **Strain/Size Broadening**: Demonstrate how microstructure affects peak shapes
5. **Phase Mixtures**: Simulate multi-phase assemblages at various proportions

## See Also

- [Refinement Example](../example_LaB6/DESCRIPTION.md) - Extracting parameters from experimental data
- [DEVELOPMENT.md](../../docs/DEVELOPMENT.md) - Architecture and parameter format documentation
- [TROUBLESHOOTING.md](../../docs/TROUBLESHOOTING.md) - Common issues and solutions
