# Multi-Phase Powder Diffraction Pattern Simulation: DRX_33

## Overview

This example demonstrates **powder diffraction pattern simulation** for a **two-phase system** using PowderLine. The sample is a composite mixture of two crystalline phases with locked structural parameters. Unlike the refinement mode (which optimizes parameters to fit data), simulation mode calculates the theoretical diffraction pattern for a given structure at fixed parameters.

## Use Case: Multi-Phase Simulation

This example addresses scenarios where you need to:
- **Predict diffraction patterns** for known multi-phase compositions
- **Baseline calculation**: Generate clean calculated patterns for each phase separately and combined
- **Phase fraction verification**: Generate patterns at different scale factors to understand phase contributions
- **Method development**: Test analysis pipelines without refinement variability
- **Synthetic data generation**: Create reference datasets for testing and validation

## Schema Features Demonstrated

This example demonstrates multi-phase simulation capabilities:

- **Multi-phase simulation**: Two independent phases with all parameters locked
- **Simulation mode**: All `refine_flag: false` across both phases and background
- **Single-cycle execution**: `refinement_cycles: 1` (no iterative optimization)
- **Phase-specific outputs**: Separate reports for each phase (unit cell, peak lists)
- **Combined pattern calculation**: Theoretical pattern from superposition of both phases
- **Scale factor control**: Fixed relative phase intensities (both set to 1.0)
- **Meaningless fit statistics**: `rwp` compares the simulated pattern with the placeholder data (pure forward calculation, no fitting); GSAS-II's own 100 % is under `engine_details`

## Key Differences from Refinement

| Aspect | Refinement Mode | Simulation Mode |
|--------|-----------------|-----------------|
| `refine_flag` values | `true` for parameters to fit | `false` for all parameters |
| `refinement_cycles` | 5 (typical value) | 1 (all params locked, no optimization) |
| Output $R_{wp}$ | Quality of fit to data | meaningless (no fit performed; y_calc ≠ the placeholder y_obs) |
| Processing time | Minutes (GSAS-II iteration) | Seconds (single calculation) |
| Purpose | Parameter extraction | Pattern prediction |
| **Multi-phase focus** | Both phases refined | Both phases locked at fixed scales |

## How It Works

1. **Structure Input**: Two crystal structures (DRX_33 + Li4MgWO6_SG12) from CIF with known unit cell parameters
2. **Instrument Definition**: Same synchrotron beamline setup as refinement example (λ = 0.1665 Å)
3. **Parameter Locking**: All structural and peak broadening parameters set to `refine_flag = false`
4. **Scale Factors**: Each phase has a fixed scale factor (1.0 in this example - equal contributions)
5. **Single Cycle**: `refinement_cycles = 1` with all parameters locked = pure calculation (no optimization)
6. **Output**: Theoretical y_calc values representing the combined two-phase pattern

## Technical Details: Why This Works

**Parameter Locking Pattern:**
- Phase 1 (DRX_33): Scale = 1.0, Size/Strain locked, Unit cell frozen
- Phase 2 (Li4MgWO6_SG12): Scale = 1.0, Size/Strain locked, Unit cell frozen
- Instrument: Broadening parameters locked, wavelength fixed

With all parameters locked and `refinement_cycles = 1`:
- GSAS-II performs no iteration (all parameters frozen)
- Only calculates theoretical pattern ($y_{calc}$)
- Result is deterministic and reproducible
- The result says `simulation_mode: true`; its `rwp` is the uniform statistic against the placeholder data and means nothing (GSAS-II's own 100 % is under `engine_details`)
- Runs in < 2 seconds

**Multi-Phase Mechanics:**
- Each phase contributes reflections according to its crystal structure and intensity according to its scale factor
- Peak positions and intensities determined by lattice parameters and crystal structure
- Background remains constant (Chebyshev polynomial from initial setup)
- Final pattern = Phase1($S_1$) + Phase2($S_2$) + Background

## Running the Simulation

```bash
# Run simulation
pixi run -e gsasii powderline examples/example_DRX_33_simulation/input.json --output my_drx33_sim

# Validate without running
pixi run powderline examples/example_DRX_33_simulation/input.json --validate-only

# Verbose output (see all GSAS-II logs)
pixi run -e gsasii powderline examples/example_DRX_33_simulation/input.json --output my_drx33_sim --verbose
```

Expected runtime: **~1 second** (single cycle, all phases locked)

## Output Files

This two-phase simulation produces:

- **dummy.gpx** - GSAS-II project file (gitignored)
- **dummy.lst** - Log file (shows 1 cycle with no parameter changes)
- **DRX_33_unit_cell_report.csv** - Phase 1 unit cell parameters (unchanged from input; every `esd` is `0.0` — nothing refined, no covariance)
- **DRX_33_peak_list_report.csv** - Phase 1 reflection list (hkl, d-spacing, 2θ, intensities)
- **Li4MgWO6_SG12_unit_cell_report.csv** - Phase 2 unit cell parameters (unchanged from input; every `esd` is `0.0` — nothing refined, no covariance)
- **Li4MgWO6_SG12_peak_list_report.csv** - Phase 2 reflection list (hkl, d-spacing, 2θ, intensities)
- **fit_profile.txt** - Calculated pattern (2θ, Iobs, Iweight, Icalc, Ibackground, Idifference)
- **output_recipe.json** - The resolved recipe of the run (KI-04; nothing refined, so the values are the input's); `metadata.powderline_provenance` names the run
- **parameter_dispositions.csv** - One row per refinable value: path, value, esd, disposition (`varied`, `held_by_user`, `held_by_symmetry`, `default_applied`, ...), at_limit

**Note**: Simulation mode does NOT produce `refined_parameters.csv` because no parameters are refined (all `refine_flag: false`). The reported `rwp` is PowderLine's uniform statistic of the calculated pattern against the placeholder data and is meaningless in simulation mode; the result carries `simulation_mode: true`.

## Data Source

- **XRD Data**: Experimental synchrotron powder diffraction from a two-phase composite sample
- **Phases**: DRX_33 (face centered cubic, Fm-3m) and Li4MgWO6_SG12 (monoclinic structure)
- **Instrument**: Pair distribution function beamline 28-ID-2 at NSLS-II (λ = 0.1665 Å)
- **Temperature**: Room temperature

## Comparison with Single-Phase Simulation

See [example_LaB6_simulation/](../example_LaB6_simulation/) for a simple single-phase example (cubic LaB6). This DRX_33 example extends the pattern to show how multiple phases are handled in simulation mode - each phase contributes its reflections independently, and the scale factors control their relative intensities in the combined pattern.

## Advanced Usage: Scale Factor Variation

To study phase fractions, modify the scale factors in `input.json`:

```json
"DRX_33": {
  "scale": [0.7, false]  // 70% relative phase fraction by mass
},
"Li4MgWO6_SG12": {
  "scale": [0.3, false]  // 30% relative phase fraction by mass
}
```

Run multiple simulations with different scale factor combinations to map phase fraction effects on the diffraction pattern. This is useful for validation of quantitative phase analysis algorithms.

## Data citation

The diffraction data in this example (the disordered-rocksalt cathode
material, "DRX_33") is from the study available at
[doi:10.26434/chemrxiv.15003271/v1](https://doi.org/10.26434/chemrxiv.15003271/v1)
(preprint; to appear in a peer-reviewed publication). Please cite that work
when using this dataset.
