# ⚠️ **This is a Template File**

**This template is NOT meant to be run directly.** Copy this directory and fill in your refinement details to create a working example. `input.json` is the `gsasii.rietveld` skeleton; `topas/input.json` and `easydiffraction/input.json` are the per-engine skeletons (delete the ones you do not fill in). Validate your copy with `powderline <your_dir>/input.json --validate-only` (or `pixi run kicker ... --validate-only`); the element `X` and the empty data arrays are the blanks you must fill.

---

# [Your Example Name Here]

## Scientific Purpose

Describe what you are trying to refine and what scientific question you are answering:
- What material/phase are you analyzing?
- What is the scientific goal (e.g., determining structure, measuring strain, refining instrument parameters)?
- What data collection conditions were used?

## Schema Features Demonstrated

List the schema features this example demonstrates:
- **[Feature category]**: Brief description (e.g., "Multi-phase refinement", "Anisotropic ADPs", "Simulation mode")
- **[Workflow type]**: Which schema_name is used? (`gsasii.rietveld` for structural refinement or `gsasii.spf` for single peak fitting; `topas.*` / `easydiffraction.*` for the per-engine recipes in `topas/` and `easydiffraction/`)
- **[Parameter patterns]**: Key refinement parameter patterns demonstrated (gsasii `[value, refine_flag]`; topas and easydiffraction `[value, refine_flag, min, max]`)
- **[Special capabilities]**: File-less payload? Background modeling? Single peak fitting?
- **[Data format]**: XRD data embedded or referenced? CIF structures?
- **[Validation]**: Expected Rwp range, convergence behavior

Examples of features you might highlight:
- Basic Rietveld refinement with instrument parameter fitting
- Multi-phase refinement (cubic + monoclinic systems)
- Atom parameter refinement (coordinates, Uiso, occupancy)
- Anisotropic displacement parameters (Uaniso with U11-U23)
- Simulation mode (all parameters locked, forward calculation)
- Single peak fitting without crystal structure
- Hexagonal/trigonal crystal systems
- Peak broadening with LG_eta mixing

## Input Parameters

Describe what goes in `input.json`:
- **Data file(s)**: Which XRD data files are being used? Format? Source?
- **Phases**: Which phase(s) are being refined? CIF files used?
- **Constrained vs refined parameters**: What is fixed? What is being optimized?
- **Starting values**: Where do initial parameter values come from?
- **Special GSAS-II settings**: Any specific options or unusual configurations?

## Expected Behavior

Describe what should happen when this refinement runs:
- **Parameters that converge**: Which refinement parameters should stabilize?
- **Expected fit quality**:
  - Rwp target: __%
  - Typical range: 8-12% for good quality powder data
  - >15%: May indicate data quality or model issues
- **Typical runtime**: How long does this refinement take?
- **Normal warnings/messages**: Are there expected warnings that can be ignored?

### Expected Parameter Correlations

Which parameters typically show high correlation (>90%)?
- Background coefficients: [Expected? Yes/No]
- Instrument broadening (U, V, W): [Expected? Yes/No]
- Phase scales (multi-phase only): [Expected? Yes/No]
- Any others specific to your refinement:

See [CONTRIBUTING_EXAMPLES.md](../CONTRIBUTING_EXAMPLES.md#expected-parameter-correlation-warnings) for details on interpreting correlation warnings.

## Known Issues

Document any quirks, edge cases, or special considerations:
- **GSAS-II version requirements**: Does this need a specific version?
- **Convergence issues**: Are there known problems with parameter correlations?
- **Data preparation**: Does the data need special processing before refinement?
- **Space group quirks**: Does normalization occur? (e.g., R-3m → R-3c for rhombohedral)
- **Workarounds**: Any tricks needed to make this work?

## Reference Files

After running this example successfully with `powderline input.json` (or `pixi run -e gsasii kicker input.json` for a gsasii recipe), the `output/` directory should contain:
- `.gpx`: GSAS-II project file (can be reopened in GUI)
- `.lst`: Refinement log with final parameters and Rwp
- `refined_parameters.csv`: every refined parameter with its ESD (9 columns); absent for a simulation
- `*_unit_cell_report.csv`: Refined unit cell parameters
- `*_peak_list_report.csv`: Reflection list with intensities
- `fit_profile.txt`: Observed/calculated/difference profile data
- `output_recipe.json` and `parameter_dispositions.csv`: the resolved recipe with the refined values written back, and each parameter's disposition (refinement runs)

These files (except `.gpx`, which is gitignored) are committed to git and used for regression testing to ensure code changes don't affect results.


