# PowderLine Developer Guide

This guide provides comprehensive context for developers working on PowderLine (and for AI coding assistants used alongside them). Read this first to understand the project architecture, design decisions, and development workflows.

## Project Overview

**What is PowderLine?**
PowderLine automates crystallographic refinement from a declarative JSON "recipe" and drives interchangeable refinement engines — GSAS-II by default, with Bruker TOPAS v7 and open-source easydiffraction as optional alternatives. It takes a recipe describing refinement parameters and produces standardized output reports. The goal is to make powder diffraction refinements reproducible, automatable, and accessible.

**Scope:**
- Command-line tool that runs refinements from JSON recipes, dispatching to interchangeable engines (GSAS-II by default; TOPAS v7 and easydiffraction optional)
- Schema 0.26.0: Simplified two-workflow system (Rietveld refinement or single peak fitting)
- Schema validation using Pydantic
- Single-phase and multi-phase Rietveld refinements; phase-less single peak fitting
- Standard output reports (fit profiles, unit cell parameters with ESDs, peak lists, `refined_parameters.csv`)
- Programmatic Python API: `powderline.run()` with DataFrame returns
- Example-driven design: schema evolves based on real refinement cases

**Design Philosophy:**
- **Example-driven**: Don't build features speculatively - add them when real examples need them
- **Schema-first**: Validate inputs before any GSAS-II operations
- **Fail fast**: Detect errors early with helpful messages
- **Reproducible**: Same JSON should produce identical refinement results

## Schema Structure

**Current schema**: 0.26.0 (payload-based structure with fixed output filenames)

### Top-Level Structure

All recipes use a three-key structure:

```json
{
  "schema_name": "GSASII_Rietveld",  // or "GSASII_SPF"
  "schema_version": "0.26.0",
  "payload": {
    // All refinement parameters here
  }
}
```

**Key field: `schema_name`** - Selects the workflow executor:
- `"GSASII_Rietveld"`: Full Rietveld structural refinement
- `"GSASII_SPF"`: Single peak fitting (peak-based analysis without crystal structure)

### Payload Structure

The `payload` contains all refinement parameters organized by concern:

```javascript
"payload": {
  "xrd_data": {...},           // Required: Diffraction pattern
  "instrument": {...},         // Required: Beamline/instrument config
  "phases": {...},             // Required for Rietveld, null for SPF
  "background": {...},         // Optional: Background model (defaults to empty if omitted)
  "refinement_controls": {...}, // Optional: Cycles, convergence
  "fit_range": [min, max],     // Optional: 2θ range limits
  "single_peaks": {...},       // Required for SPF, optional otherwise
  "single_peak_fitting_mode": {...} // For SPF workflows
}
```

**Required fields vary by `schema_name`**:
- **Rietveld** (`GSASII_Rietveld`): Must have `phases` defined
- **SPF** (`GSASII_SPF`): Must have `single_peaks` and `single_peak_fitting_mode`

### Output Files (Fixed Names)

PowderLine uses **fixed output filenames** independent of sample identity:

- `dummy.gpx`: GSAS-II project file (reopenable in GUI)
- `dummy.lst`: Human-readable refinement log (Rwp, parameter tables)
- `<phase>_unit_cell_report.csv`: Refined unit cell (one per phase)
- `<phase>_peak_list_report.csv`: Reflection list (one per phase)
- `fit_profile.txt`: Observed/calculated/difference intensities

**Rationale**: Fixed filenames eliminate variability in automation/testing. Sample identity should be managed externally (directory names, databases, metadata systems).

### Refined Parameters Export with ESDs

**File:** `refined_parameters.csv` (9 columns)

PowderLine exports all refined parameters with estimated standard deviations (ESDs) after each refinement. This provides a structured, machine-readable record of refinement results with uncertainty quantification.

**Column structure:**
1. `parameter_name`: GSAS-II internal parameter identifier (e.g., `::0:Scale`, `::A0`, `0::A0`)
2. `descriptive_name`: Human-readable description (e.g., "Scale factor for phase LaB6", "Background coefficient A0")
3. `phase_name`, `phase_idx`: Phase associations for phase-specific parameters (null otherwise)
4. `atom_name`, `atom_idx`: Atom associations for atom-specific parameters (null otherwise)
5. `value`: Refined parameter value
6. `esd`: Estimated standard deviation from covariance matrix
7. `category`: Parameter classification (instrument, background, cell, atom_position, atom_displacement, HAP, peak_broadening)

**Implementation:** `export_refined_parameters_csv()` in [kicker.py](../src/powderline/kicker.py)

**ESD calculation:**
- **Primary source**: GSAS-II covariance matrix (`proj.data['Covariance']`)
- **Fallback**: A `.lst`-parsing fallback exists in `kicker.py` (`extract_refined_params_from_lst`) but is **currently disabled at its call site**. It is preserved pending a test that confirms covariance matrix ESDs match what `.lst` parsing previously produced. Until that test exists, the covariance matrix is the **sole** ESD source.
  - **Note**: The `.lst` fallback was incomplete — it only covered instrument, background, and unit cell parameters, not atom or HAP parameters.
- **Unit cell ESDs**: Uses `G2lat.getCellEsd()` to convert reciprocal metric tensor ESDs to direct lattice parameters
  - Function: `calculate_cell_esds_from_A_matrix()` in [kicker.py](../src/powderline/kicker.py)
  - GSAS-II stores cell as reciprocal metric tensor (A-matrix); ESDs require conversion

**Parameter name parsing:**
- `parse_parameter_associations()` in [kicker.py](../src/powderline/kicker.py): Extracts phase/atom indices from GSAS-II parameter names
- `get_descriptive_param_name()` in [kicker.py](../src/powderline/kicker.py): Generates human-readable descriptions
- `build_phase_name_mapping()` in [kicker.py](../src/powderline/kicker.py): Maps phase indices to names
- `build_atom_name_mapping()` in [kicker.py](../src/powderline/kicker.py): Maps atom indices to labels

**Phase-specific unit cell reports:**
In addition to the comprehensive `refined_parameters.csv`, each phase generates `<phase>_unit_cell_report.csv` with 3 columns:
- `parameter`: a, b, c, alpha, beta, gamma, volume
- `value`: Refined unit cell parameter
- `esd`: Estimated standard deviation

**Note on simulations**: Simulation mode (all `refine_flag=false`) does not generate `refined_parameters.csv` since no parameters are refined. Unit cell reports are still generated, with an empty `esd` column (read as `NaN`).

### Schema Evolution

See [SCHEMA_HISTORY.md](SCHEMA_HISTORY.md) for historical context.

**IMPORTANT — Schema Version Discipline:**
The GSAS-II server caches `kicker.py` at startup. If `kicker.py` changes (even without recipe format changes), a running server will use stale code. The `schema_version` in recipes is validated against `EXPECTED_SCHEMA_VERSION` in `schema.py`, so bumping the version forces a server restart. **You MUST bump `EXPECTED_SCHEMA_VERSION` whenever `kicker.py` output behavior changes** (new output files, format changes, column additions, etc.), even if the recipe input format is unchanged. Update all `input.json` files to match.

## Domain Essentials

### Rietveld Refinement Basics

**What is Rietveld refinement?**
A method for refining crystal structures against powder diffraction data by fitting a calculated pattern to the observed pattern. The refinement adjusts parameters (unit cell, atom positions, peak shapes, background) to minimize the difference between calculated and observed intensities.

**Key Quality Metric: Rwp (weighted residual)**
$$R_{wp} = \sqrt{\frac{\sum w_i (y_{obs,i} - y_{calc,i})^2}{\sum w_i y_{obs,i}^2}} \times 100\%$$

Lower Rwp indicates better fit. Typical values: 5-15% for good refinements.

**Peak Profiles:**
GSAS-II uses Thompson-Cox-Hastings pseudo-Voigt profiles - a convolution of Gaussian and Lorentzian functions. Profile shape controlled by:
- **Instrument broadening** (U, V, W parameters) - due to instrumental effects
- **Sample broadening** (size, strain) - due to crystallite size and microstrain

### Parameter Types

PowderLine organizes refinement parameters into logical groups:

1. **Structural Parameters (Phase-specific):**
   - **Unit cell**: a, b, c, α, β, γ define crystal lattice dimensions
   - **Atom parameters**: positions (x, y, z), occupancy, thermal parameters
   - **Space group**: symmetry operations (defined in CIF, not refined)

2. **Intensity Parameters (Phase-specific):**
   - **Scale factor**: Converts calculated intensities to absolute scale
   - **Preferred orientation**: Non-random crystallite orientations (not implemented yet)

3. **Peak Shape Parameters (Phase-specific):**
   - **Sample broadening**: Crystallite size, microstrain

4. **Background Parameters:**
   - **Chebyshev polynomials**: Smooth curved background
   - **Single peaks**: Individual pseudo-Voigt peaks for known impurities

### Background Default Behavior

The `background` field is optional in the payload. If omitted (`background: null`):
- No Chebyshev coefficients are initialized
- No background single peaks are added
- GSAS-II uses an empty background (effectively zero)

This is useful when background has been pre-subtracted from XRD data.

5. **Instrument Parameters:**
   - **Instrument broadening**: U, V, W (Gaussian), X, Y, Z (Lorentzian)
   - **Profile asymmetry**: Axial divergence, sample transparency
   - **Wavelength**: X-ray or neutron wavelength
   - **Zero shift**: 2θ offset correction
   - **Polarization**: For synchrotron data

### The `[value, refine_flag, min, max]` Pattern

Throughout the JSON schema and code, you'll see parameters represented as 4-element lists:
```python
"wavelength": [0.45236, false, null, null]
```

- **value**: Current parameter value
- **refine_flag**: `true` = refine this parameter, `false` = hold fixed
- **min/max**: Parameter bounds (placeholders for future - GSAS-II may not support bounds)

This mirrors GSAS-II's internal parameter representation.

### Phase vs Histogram Parameters

**Critical distinction** (confusing in GSAS-II):
- **Phase parameters**: Belong to the crystal structure (scale, unit cell, atoms, space group, sample broadening)
- **Histogram parameters**: Belong to the measurement (instrument broadening, background)

In multi-phase refinements, each phase has its own structural parameters, but histogram parameters are shared across phases (except scale factors, which are phase-histogram pairs).

### Atom Parameter Refinement

**Refine Flags String Format:**
GSAS-II uses a single string at atom record index 2 to encode which parameters are refined:
- **'F'**: Refine occupancy (fraction)
- **'X'**: Refine fractional coordinates (x, y, z) - a single lumped flag for all three
- **'U'**: Refine displacement parameters (isotropic or anisotropic)
- **Combinations**: 'FXU' (all), 'XU' (coordinates + displacement), 'F' (occupancy only), etc.

**Per-Parameter Semantics (Schema 0.26):** Although GSAS-II exposes only the lumped 'X' flag (and one 'U' flag for all six anisotropic components), PowderLine honors the recipe's per-parameter flags: a coordinate or `Uij` component refines iff it is present with `refine_flag=true`; absent or false means fixed. This uses the same lumped-flag + "Hold"-constraint mechanism as unit-cell parameters — see [Unit Cell Refinement Semantics (Schema 0.26)](#unit-cell-refinement-semantics-schema-026) and `src/powderline/constraints.py`. For atoms, only site-symmetry-linked parameters remain coupled: e.g. `x` and `y` on an `(x,x,z)` site form one degree-of-freedom group that refines if either is requested; flags on symmetry-fixed parameters have no effect.

**Displacement Parameter Types (ADP field):**
Each atom has an atom-specific `ADP` field indicating which displacement type to use:
- **Structure**: `phases[phase]['structure']['atoms'][label]['ADP']` indicates which type is used
- **Parameterization**: `phases[phase]['parameterization']['atoms'][label]['ADP']` indicates which type to refine

Values:
- **'Uiso'**: Isotropic displacement (single scalar U value)
- **'Uaniso'**: Anisotropic displacement (6 values: U11, U22, U33, U12, U13, U23)

The parameterization ADP controls atom_record[9] ('I' or 'A') in GSAS-II.

**Dictionary Structure Examples:**

Structure (embedded in payload):
```json
"phases": {
  "LaB6": {
    "structure": {
      "atoms": {
        "La": {
          "element": "La",
          "x": 0.0, "y": 0.0, "z": 0.0,
          "occupancy": 1.0,
          "ADP": "Uiso",
          "Uiso": 0.00858,
          "Uaniso": null
        }
      }
    }
  }
}
```

Parameterization (refinement settings):
```json
"phases": {
  "LaB6": {
    "parameterization": {
      "atoms": {
        "La": {
          "x": [null, true, null, null],
          "y": [null, false, null, null],
          "z": [null, false, null, null],
          "occupancy": [null, true, null, null],
          "ADP": "Uiso",
          "Uiso": [null, true, null, null],
          "Uaniso": null
        }
      }
    }
  }
}
```

**Anisotropic Displacement Parameters:**
If using `ADP="Uaniso"`, all 6 anisotropic U values (U11, U22, U33, U12, U13, U23) must be provided in both structure and parameterization:

```javascript
"atoms": {
  "Li": {
    "ADP": "Uaniso",
    "Uiso": 0.01,  // Can provide both - ADP dictates which is used
    "Uaniso": {
      "U11": 0.012, "U22": 0.011, "U33": 0.010,
      "U12": 0.001, "U13": 0.001, "U23": 0.001
    }
  }
}
```

**Mixed ADP Types:** It is common (and allowed) for one atom to have `ADP="Uaniso"` while another has `ADP="Uiso"` in the same phase.

### Glossary

- **CIF**: Crystallographic Information File - standard format for crystal structures (In PowderLine, structural information is provided as embedded dictionaries, not CIF files)
- **GPX**: GSAS-II project file (binary format)
- **LST**: GSAS-II refinement log file with Rwp and parameter tables
- **CHI**: Two-column ASCII file (2θ, intensity) for powder diffraction data (Note: PowderLine uses embedded data arrays, not files. This format is for reference only)
- **INSTPRM**: GSAS-II instrument parameter file (Note: PowderLine uses embedded instrument parameters, not files. This format is for reference only)
- **Recipe**: PowderLine's JSON input describing a refinement workflow
- **Multiplicity**: Number of symmetry-equivalent reflections
- **d-spacing**: Interplanar spacing for an hkl reflection
- **2θ (two-theta)**: Diffraction angle in degrees
- **hkl**: Miller indices describing a crystallographic plane

## GSAS-II Integration

### Why Direct Dictionary Manipulation?

PowderLine manipulates the `proj.data` dictionary directly rather than using GSAS-II's phase/histogram objects. This decision was made because:
- **Phase object ambiguity**: Unclear how G2Phase initialization maps to parameter setting
- **Explicit control**: Direct dictionary access makes parameter locations clear
- **Less abstraction**: Easier to debug when you can see exact data structure
- **Trade-off**: More brittle if GSAS-II internal structure changes (acceptable risk for Phase 1)

### The `proj.data` Dictionary Structure

GSAS-II stores all project data in a nested dictionary. Key access patterns:

```python
# Instrument parameters (list format: [current_value, value, refine_flag]). See kicker.py for setting functions
curr_wavelength = proj.data[hist.name]['Instrument Parameters'][0]['Lam'][1] # before setting, can get value from initialization (e.g., when xrd_data is added)
proj.data[hist.name]['Instrument Parameters'][0]['Lam'][1] = wavelength
proj.data[hist.name]['Instrument Parameters'][0]['Lam'][2] = refine_flag

# Background parameters
proj.data[hist.name]['Background'] = [
    [chebyshev, no_peaks, background_type],  # Background metadata
    {'nDebye': 0, 'debyeTerms': [], ...},     # Debye-Scherrer params
    {'nPeaks': n, 'peaksList': [...]},        # Single peaks
]

# Histogram-atom parameters (HAP)
# Change phase intensity scale given a value and refine_flag from payload for a phase's parameterization:
proj.data['Phases'][phase_name]['Histograms'][hist.name]['Scale'][0] = value
proj.data['Phases'][phase_name]['Histograms'][hist.name]['Scale'][1] = refine_flag

# Change isotropic size broadening for a given phase from the payload for a phase's parameterization:
proj.data['Phases'][phase_name]['Histograms'][hist.name]['Size'][0] = model # assume model is "isotropic" in this example
proj.data['Phases'][phase_name]['Histograms'][hist.name]['Size'][1][0] = value # set isotropic crystallite size value
proj.data['Phases'][phase_name]['Histograms'][hist.name]['Size'][2][0] = refine_flag # set isotropic size value refinement flag (if not None)

# Change isotropic mustrain broadening for a given phase from the payload for a phase's parameterization:
proj.data['Phases'][phase_name]['Histograms'][hist.name]['Mustrain'][0] = model # assume model is "isotropic" in this example
proj.data['Phases'][phase_name]['Histograms'][hist.name]['Mustrain'][1][0] = value # set isotropic mustrain value
proj.data['Phases'][phase_name]['Histograms'][hist.name]['Mustrain'][2][0] = refine_flag # set isotropic mustrain value refinement flag (if not None)

# Phase parameters
proj.data['Phases'][phase_name]['General']['Cell'] = [refine_cell, a, b, c, alpha, beta, gamma, volume]
```


### Known GSAS-II Quirks

These inconsistencies exist in GSAS-II (as of 2025) and are documented in kicker.py comments:

1. **Size/Strain Documentation Conflict**:
   - GSAS-II API does not document structure of dicts / lists well
   - PowderLine uses correct extended format

2. **Unit Cell Refinement**:
   - GSAS-II natively exposes a single refine flag for all 6 unit cell parameters; since schema 0.26 PowderLine honors per-parameter flags instead.
   - See [Unit Cell Refinement Semantics (Schema 0.26)](#unit-cell-refinement-semantics-schema-026) for the full mechanism and symmetry-coupling rules.

3. **Reflection List Headers**:
   - GSAS-II provides 15-column reflection arrays without headers
   - PowderLine adds headers manually: h, k, l, multiplicity, d_spacing, 2theta, etc.

### Peak Broadening Models

**Schema Enhancement**: Size and strain broadening support model branching with schema-level validation.

#### Size Broadening Models

PowderLine supports three size broadening models matching GSAS-II's capabilities:

| Model | Parameters | GSAS-II Structure | Status |
|-------|-----------|-------------------|--------|
| **isotropic** | `isotropic_size`, `LG_eta` | `Size[0] = 'isotropic'`<br>`Size[1][0]` = size<br>`Size[1][2]` = LG_eta | ✅ **Implemented** |
| **uniaxial** | `uniaxial_equatorial`, `uniaxial_axial`, `hkl_direction`, `LG_eta` | `Size[0] = 'uniaxial'`<br>`Size[1][0:2]` = eq/ax sizes<br>`Size[3]` = [h,k,l] | ⚠️ **NotImplementedError** |
| **ellipsoidal** | `S11`, `S22`, `S33`, `S12`, `S13`, `S23`, `LG_eta` | `Size[0] = 'ellipsoidal'`<br>`Size[4][0:6]` = tensor params | ⚠️ **NotImplementedError** |

**Usage** (isotropic only):
```json
"size_broadening": {
  "model": "isotropic",
  "isotropic_size": [100.0, true, null, null],
  "LG_eta": [0.5, false, null, null]
}
```

**Future models** raise `NotImplementedError` at schema validation:
```python
# This will fail during recipe validation:
"size_broadening": {
  "model": "uniaxial",  # Error: Not yet implemented
  ...
}
```

#### Strain Broadening Models

Strain broadening supports three models with increasing complexity:

| Model | Parameters | GSAS-II Structure | Status |
|-------|-----------|-------------------|--------|
| **isotropic** | `isotropic_strain`, `LG_eta` | `Mustrain[0] = 'isotropic'`<br>`Mustrain[1][0]` = strain<br>`Mustrain[1][2]` = LG_eta | ✅ **Implemented** |
| **uniaxial** | `uniaxial_equatorial`, `uniaxial_axial`, `hkl_direction`, `LG_eta` | `Mustrain[0] = 'uniaxial'`<br>`Mustrain[1][0:2]` = eq/ax strains<br>`Mustrain[3]` = [h,k,l] | ⚠️ **NotImplementedError** |
| **generalized** (Stephens) | Symmetry-dependent parameters | Complex Laue class-specific | ⚠️ **NotImplementedError**<br>(Phase 2) |

**Usage** (isotropic only):
```json
"strain_broadening": {
  "model": "isotropic",
  "isotropic_strain": [0.001, true, null, null],
  "LG_eta": [0.8, false, null, null]
}
```

**Note on Stephens Model**: The `generalized` strain model uses Stephens formalism where the number and meaning of parameters depend on the crystal's Laue class (cubic, hexagonal, etc.). Implementation deferred to Phase 2 due to complexity.

#### Implementation Details

**Model Branching** (kicker.py):
```python
def set_phase_size_broadening(proj, hist, phase_name, size_dict, print_info=False):
    """Set size broadening with model-specific branching."""
    model = size_dict.get('model', 'isotropic')  # Default for backward compat

    # Set model type in GSAS-II
    proj.data['Phases'][phase_name]['Histograms'][hist.name]['Size'][0] = model

    # Branch on model
    if model == 'isotropic':
        _set_isotropic_size_broadening(...)  # Current implementation
    elif model in ['uniaxial', 'ellipsoidal']:
        raise NotImplementedError(f"{model} size broadening not yet supported")
```

**Schema Validation** (schema.py):
```python
class SizeBroadening(BaseModel):
    model: Literal["isotropic", "uniaxial", "ellipsoidal"] = "isotropic"
    # ... parameters for all models ...

    @model_validator(mode='after')
    def validate_model_implementation(self) -> Self:
        if self.model != 'isotropic':
            raise NotImplementedError(
                f"{self.model} size broadening not yet implemented. "
                "Use 'isotropic' model instead."
            )
        return self
```

**Design Rationale**:
- Schema documents complete API (all models) even if not implemented
- Clear error messages guide users to supported features
- Foundation for Phase 2 implementation without breaking changes
- Validation happens early (recipe parsing), not during refinement

## Architecture & Design Decisions

### Module Responsibilities

**src/powderline/kicker.py** (the refinement engine):
- CLI entry point via argparse
- Recipe loading, template detection, validation
- GSAS-II project initialization
- All parameter setting functions (background, phases, instrument, unit cell, etc.)
- Refinement execution
- Output generation (CSV reports, fit profiles)
- **Role**: Complete workflow orchestration + implementation

**src/powderline/schema.py**:
- Pydantic models matching JSON recipe structure
- Nested validation: RecipeModel → InstrumentModel, PhaseModel, BackgroundModel
- Custom validators for coefficient counts, list lengths, fit range
- **Role**: Input validation and type safety

**src/powderline/gsas_server.py / gsas_client.py**:
- Persistent FastAPI server keeping GSAS-II loaded in memory, and the HTTP client that talks to it (with in-process subprocess fallback)
- Per-user and authenticated by signed requests/responses (private state dir, loopback, ephemeral port, single instance via a kernel lock); `POWDERLINE_NO_SERVER=1` disables it
- **Role**: Execution backends for `run()`'s `server`/`auto` modes

**src/powderline/topas/ + src/powderline/easydiff/ + src/powderline/engine.py**:
- Alternate translation engines — TOPAS v7 (recipe → `.inp`/`.xye`, `tc.exe` runner, results round-trip; standalone `topas-kicker` CLI) and easydiffraction (recipe → easydiffraction `Project`, lmfit fit) — plus the engine dispatcher behind `powderline.run(recipe, output_dir, engine="gsasii"|"topas"|"easydiffraction")`. Both alternate paths import **zero** GSAS-II; the `gsasii` branch is a transparent pass-through to `kicker.run`.
- **Role**: Alternate refinement engines + engine dispatch

**tests/**:
- `test_example_LaB6_regression.py`: End-to-end regression test with exact output matching
- `conftest.py`: Pytest fixtures for paths and test data
- **Role**: Quality assurance - detect refinement result changes

**Monolithic Design Rationale:**
Phase 1 keeps all implementation in `kicker.py` intentionally:
- Simplifies development during schema evolution
- Easy to understand complete workflow in one file
- Refactoring to modules planned for Phase 2 when API stabilizes
- Comments saying "upstream" or "will be handled elsewhere" refer to future refactoring

### Adding a Refinement Engine

PowderLine's engine seam makes new backends cheap to add. The dispatcher
(`src/powderline/engine.py`) is a small `_ENGINES` tuple plus one lazy-import
branch per engine; every engine returns the **same result-dict shape**, locked
by `tests/test_api.py`. The TOPAS (`src/powderline/topas/`) and easydiffraction
(`src/powderline/easydiff/`) subpackages are the two reference implementations.

The established pattern:

1. **New subpackage** `src/powderline/<engine>/` holding all engine logic:
   translation (`builder`/`writer`), execution (`runner`), result parsing, unit
   conversions, and a `run_<engine>_recipe(recipe, output_dir, ...)` adapter that
   returns the locked result dict.
2. **One lazy-import branch** in `powderline/engine.py` (add the name to
   `_ENGINES`). Import the engine module only inside that branch so machines
   without the engine's dependencies can still use the others.
3. **No schema changes** — engines translate the existing `GSASII_*` recipes;
   they do not define their own recipe format.
4. **Reject unsupported features loudly** — a recipe feature the engine cannot
   represent raises a translation error (or, if it's a *fixed* unmappable value,
   is dropped with a recorded warning). Never silently ignore a refine flag.
5. **Optional pixi feature/environment** if the engine needs dependencies the
   default environment shouldn't carry (e.g. easydiffraction needs Python ≥3.12,
   so it lives in the optional `easydiff` environment).
6. **Keep it GSAS-II-free** if it can be — the alternate engines import zero
   GSAS-II, a property enforced by subprocess import-block tests.

**Simulation-mode semantics across engines.** The GSAS-II engine treats
`refinement_cycles == 1` as simulation and *rejects* any refine flag set in that
mode (`validate_simulation_mode_parameters` in `kicker.py`). The alternate
engines (TOPAS, easydiffraction) instead treat "no parameters flagged for
refinement" as simulation and do not enforce the `cycles == 1` lock. For
well-formed recipes the behavior matches; the two definitions only diverge on
inconsistent input (`cycles == 1` *with* a stray refine flag), which GSAS-II
refuses and the alternate engines would run. Uniform input-contract enforcement
across all engines is a tracked follow-up (see the PowderLine-devkit
easydiffraction dossier — a private maintainers' repo, access on request).

### Schema Design: Why `extra='allow'`?

Nearly all Pydantic models use `ConfigDict(extra='allow')` to permit fields not explicitly defined (the one exception is `RefinementParameterModel`, which uses `extra='forbid'`):

```python
class RecipeModel(BaseModel):
    model_config = ConfigDict(extra='allow')
```

**Rationale:**
- **Schema evolution**: Example-driven design means new fields emerge as examples are added
- **Backwards compatibility**: Old recipes continue working when new fields are added
- **Flexibility**: Users can add custom metadata without validation errors
- **Trade-off**: Typos in field names won't be caught (acceptable for Phase 1 iteration speed)

Future phases may tighten validation to `extra='forbid'` once schema stabilizes.

### The "Upstream" Pattern

You'll see several TODO markers like `# TODO: validation will be handled upstream` throughout kicker.py. This means:

- **Currently**: Validation happens in helper functions (e.g., check coefficient count in `set_chebyshev_background`)
- **Future**: Validation moves to Pydantic schema (separation of concerns)
- **Not implemented yet**: Still evolving what validation logic belongs where

The pattern reflects Phase 1's iterative approach - implement in helper functions first, refactor to schema later.

### File-less Schema Architecture

PowderLine uses file-less JSON payloads. All data (XRD patterns, structures, instrument parameters) is embedded directly in JSON. File handling (loading XRD data from .chi files, parsing CIF structures, reading instrument parameters) occurs upstream of PowderLine.

**Embedded Data Format:**
- **XRD data**: "xrd_data" contains "tth", "Itth", "Itth_weights" arrays
- **Structure**: "structure" contains "space_group", "unit_cell", "atoms" dictionaries
- **Instrument**: "instrument" contains "initialization" and optional "parameterization" dictionaries

This design enables PowderLine to focus on refinement logic while delegating file I/O to upstream tools.

### Phase Name Resolution

In PowderLine, phase names come from the `phase_name` field in the embedded structure dictionary:

```python
# Phase name is explicitly specified in structure
"phases": {
  "LaB6": {  # This becomes the phase identifier
    "structure": {
      "phase_name": "LaB6",  # Must match the key above
      "space_group": "P m -3 m",
      ...
    }
  }
}
```

The phase name is used consistently throughout:
- Phase dictionary keys
- Structure `phase_name` field (must match key)
- Parameterization references
- Output file naming

This ensures consistent phase identification throughout refinement and output generation.

### Server Architecture (Three-Layer Execution Stack)

`powderline.run()` dispatches through three layers:

```
powderline.run() / CLI
        │  validates recipe, normalises DataFrames
        ▼
GSASClient.submit_simulation()
        │  routes: HTTP server  ──or──  in-process fallback
        ▼
run_refinement()
        │  single execution engine, returns JSON-serializable primitives
        ▼
GSAS-II (GSASIIscriptable)
```

**`_submit_via_subprocess` is in-process, not an OS subprocess.**  Despite its name,
this method calls `run_refinement()` directly in the current interpreter. The name
has been retained for API stability; if crash-isolation is needed in a future phase
it can be upgraded to `multiprocessing` without changing callers.

**`execution_mode` vs `method` — two distinct concepts:**
- `powderline.run()` accepts `execution_mode=` (`'auto'` | `'server'` | `'subprocess'`) as its public input parameter.
- `run_refinement()` accepts `method=` as its internal parameter (values: `'server'` | `'subprocess'` | `'test'`).
- Both `run_refinement()` and `GSASClient` include `method` as a **result dict output key** (`result['method']`) recording which execution path was used.
- These are not a renamed pair — they serve different roles at different layers of the stack.

The FastAPI server (`gsas_server.py`) keeps GSAS-II imported in one persistent
process, amortising the ~2.6 s import cost across all requests. Requests are handled
synchronously (one-at-a-time) by design — concurrency is not needed for the current
single-user CLI and programmatic-API use cases.

**After modifying any Python source file** (`kicker.py`, `schema.py`, or any other
module under `src/`), restart the server so the running process loads the new code:

```bash
pixi run gsas-server restart
```

The server loads kicker.py at startup and caches it. Changes are invisible to the
running server until it is restarted.

---

### MP Pipeline Status

The Materials Project integration (`mp_interface.py` / `mp_simulate.py` /
`simulation_builder.py`) targets the current `mp-api` client (pinned
`>=0.46,<1` in `pixi.toml`) and recipe schema 0.26.0.

**Updated for mp-api 0.46.x (previously written against older client behavior):**

1. **Single summary fetch** — `get_structure()` uses
   `client.materials.summary.search(material_ids=[...], fields=[...])` (one
   request for structure + symmetry + energetics) instead of the legacy
   `get_structure_by_material_id()` convenience method.
2. **Conventional-cell standardization** — MP's computed structure is often a
   primitive cell; it is now standardized via
   `SpacegroupAnalyzer(...).get_conventional_standard_structure()` so the
   emitted space-group symbol matches the emitted cell. (Previously a
   centered-lattice primitive cell was paired with the conventional H-M
   symbol — wrong phase for anything non-primitive; LaB6 only worked because
   its primitive and conventional cells coincide.) The symbol is derived from
   the standardized structure itself (spglib condensed style with screw-axis
   underscores stripped, e.g. `Pm-3m`, `I41/amd`),
   which `kicker.py` normalizes via `G2spc.StandardizeSpcName`.
3. **`MPID` stringification** — search results now return `material_id` as
   `str`; previously raw `MPID` objects crashed `material_id.startswith('mp-')`
   on the `--formula` path.
4. **Polymorph selection** — `search_by_formula()` returns results sorted by
   `energy_above_hull` (None last); the CLI lists all candidates and
   auto-selects the most stable one, printing the choice.
5. **Partial occupancy support** — sites are extracted per species
   (`site.species.items()`), carrying real occupancies into the recipe
   (`AtomStructure.occupancy`); disordered structures no longer crash on
   `site.specie`. `get_structure()` reports `is_ordered`.
6. **Error taxonomy** — `MPInterfaceError` base with `MPAuthError`,
   `MPNotFoundError`, `MPConnectionError`; the CLI prints targeted hints
   instead of a generic wrapped exception.
7. **Metadata fixes** — `crystal_system` now holds the actual crystal system
   (previously the space-group number, now under `space_group_number`);
   `nelements` now holds the element count (previously atom count, now under
   `num_atoms`); `energy_above_hull` and `theoretical` added.
8. **Key handling** — API key resolution is config file first, then the
   `MP_API_KEY` environment variable (`ConfigLoader.get_mp_api_key()`);
   `MPInterface` is a context manager that closes the HTTP session.
9. **Server output-visibility guard** — a GSAS-II server can be reachable
   over localhost yet have a divergent filesystem view (another node; a
   sandbox with a private `/tmp`), reporting success while its output files
   are invisible to the client. `GSASClient` verifies `fit_profile.txt` was
   freshly written client-side after a "successful" server run (stat-compare
   before/after — a stale file from a previous run into the same output dir
   does not count) and falls back to in-process execution (or returns a
   structured error when fallback is disabled). `mp-simulate --no-server`
   skips the server entirely, and its `.chi` export is built from the
   in-band `fit_profile` result data rather than re-reading the file.
   Tests: `tests/test_gsas_client_visibility.py`, `tests/test_mp_simulate_cli.py`.
   KI-12 tracks the follow-up that removes the shared-filesystem assumption
   altogether (server returns output artifacts in-band).
10. **Strict config validation** — `SimulationRecipeBuilder` validates the
   `simulation_defaults` block against its allowed shape: unknown keys at any
   level (typos, the retired flat layout) and invalid values (null from an
   empty YAML key, strings where numbers belong) raise a `ValueError` naming
   the offending key path; the CLI exits with that message. These previously
   passed `RecipeModel` validation (the instrument block is `Any`-typed
   passthrough) and failed opaquely inside GSAS-II.

**Historical (schema 0.21 → 0.26 fixes, retained by the regression suite):**
payload wrapper, `schema_name`, `isotropic_size`/`isotropic_strain` renames,
`recipe=` keyword for `GSASClient.submit_simulation()`.

**Regression guard:** `tests/test_mp_interface.py` (mocked MPRester — real
pymatgen Structures, no live API) and `tests/test_mp_pipeline.py` run as part
of the standard test suite (`pixi run test`):

```bash
pixi run pytest tests/test_mp_interface.py tests/test_mp_pipeline.py -v
```

**Limitation:** `mp_simulate.py` requires a live Materials Project API key to
fetch structures. The test suite uses mocks and a synthetic LaB6 fixture
(`mp_lab6_structure_data` in `conftest.py`) so no API key is needed for testing.

---

### Future: File-less Output Design

Currently `run_refinement()` always writes output files to `output_dir`.  Two
options are under consideration for making file output optional:

**Option A — `save_files` flag (default `False`)**
```python
result = powderline.run(recipe, output_dir=None, save_files=False)
# Returns DataFrames; no files written
```
- Simplest API change; easy to add without breaking existing calls
- Requires `output_dir` to be optional throughout the stack

**Option B — optional `output_dir` (default `None`)**
```python
result = powderline.run(recipe)          # no files
result = powderline.run(recipe, output_dir=Path("/tmp/out"))  # files + DataFrames
```
- Slightly more discoverable ("no `output_dir` = no files")
- Requires `output_dir=None` guard at every write site in `run_refinement()`

Both options are backwards-compatible additions. This will be evaluated alongside
the Phase 2 module refactoring work.

---

## Development Workflow

### Environment Setup

PowderLine uses [pixi](https://pixi.sh) for reproducible conda environments:

```bash
# Install dependencies (first time)
pixi install

# Activate environment
pixi shell

# Run refinement
pixi run kicker examples/example_LaB6/input.json

# Run tests
pixi run test

# Validate recipe only (no refinement)
pixi run kicker --validate-only examples/example_LaB6/input.json
```

**PYTHONPATH Configuration:**
The `kicker` task in `pixi.toml` sets `PYTHONPATH=$PWD/src:$PYTHONPATH` to enable `from powderline.schema import RecipeModel` imports.

### Execution Modes

PowderLine supports three execution modes for running refinements:

#### 1. Auto-Detect Mode (Default)
```bash
pixi run kicker input.json
```
- **Behavior**: Tries server → auto-starts if needed → falls back to subprocess
- **Performance**: 0.1-0.3s per simulation (if server available), 1-2s (if fallback)
- **Use case**: Normal development workflow - "just works"
- **Output**: Shows "🚀 server mode" or "🐢 subprocess mode" at end

#### 2. Force Server Mode
```bash
pixi run kicker input.json --use-server
```
- **Behavior**: Uses server only, **fails if unavailable**, no fallback
- **Performance**: 0.1s per simulation (10x+ faster than subprocess)
- **Use case**: Batch processing, CI/CD where performance matters
- **Auto-start**: Attempts to start server automatically if not running
- **Error handling**: Exits with clear error if server can't be started

#### 3. Force Subprocess Mode
```bash
pixi run kicker input.json --no-server
```
- **Behavior**: Direct in-process execution using loaded GSAS-II libraries, skip server entirely
- **Performance**: 1-2s per simulation (slower; GSAS-II imported on first use)
- **Use case**: Debugging, HPC/Slurm batch jobs, environments where the server is not suitable
- **Output**: Returns the same full structured result (DataFrames) as server mode

#### Managing the Server

**Start server manually:**
```bash
pixi run gsas-server start   # Starts in background
pixi run gsas-server status  # Check if running
pixi run gsas-server stop    # Shutdown server
```

**Server state and security (per user):** the server binds `127.0.0.1` on a
free ephemeral port and writes its lock, PID, log, and an endpoint file (port +
random secret token) — all mode 0600 — to a private per-user state directory:
`$XDG_RUNTIME_DIR/powderline` (if it is a real directory owned by you), else
`<tempdir>/powderline-<uid>` on POSIX (mode 0700; refused if it is a symlink,
owned by someone else, or group/other-accessible, or if the temp directory
would let others replace it), and `%LOCALAPPDATA%\powderline` on Windows. On
POSIX the files are opened relative to a re-verified, no-follow directory
handle.

The token never travels over the wire: every request carries a fresh nonce, a
timestamp and an HMAC-SHA256 over method, path, nonce, timestamp and body, and
the server rejects anything unsigned, wrongly signed, stale, or replayed —
on every route, including 404/405/422 — before reading the body. Every
response is signed back over the nonce, status and body, and the client
discards unsigned responses. Other users on a shared host therefore can
neither submit jobs to your server nor impersonate it (e.g. by taking over the
port of a crashed server). `gsas-server start` takes a kernel-held lock
(`flock` / `msvcrt.locking` on `server.lock`) for the server's lifetime; the
OS releases it when the process exits, so concurrent auto-starts never spawn
duplicates and leftover PID files can never make a dead server look alive.

**Pin the server port** (only if needed — the default ephemeral port avoids
collisions between users):
```bash
export POWDERLINE_SERVER_PORT=19472
pixi run gsas-server start
pixi run kicker input.json  # client reads the port from your state directory
```

**Disable the server entirely** (shared workstations, locked-down deployments):
```bash
export POWDERLINE_NO_SERVER=1   # also: true / yes / on
```
With it set, `execution_mode='auto'` (and the CLI default) runs in-process and
never starts a server, `execution_mode='server'` / `--use-server` fail with a
clear error, and `pixi run gsas-server start|restart` refuse.

**View server logs** (`server.log` in the state directory; `status` prints the path):
```bash
pixi run gsas-server logs
```

**Server benefits:**
- GSAS-II libraries loaded once (2.6s startup amortized across requests)
- Direct function calls using pre-loaded libraries (no subprocess overhead)
- Persistent process (no repeated Python interpreter startup)
- Ideal for batch simulations (10+ recipes)
- Connection retry logic (3 attempts with exponential backoff) handles transient issues

**Server caching behavior:**

The server keeps Python modules loaded in memory for performance. This means:
- ✅ **Production benefit**: 4-6x speedup (first run ~12s, subsequent ~2-3s)
- ⚠️ **Development caveat**: Code changes require server restart to take effect

**During active development:**
```bash
# After making code changes to kicker.py or other modules:
pixi run gsas-server restart   # gracefully restart with updated code

# Next run will use the freshly started server with current code
pixi run kicker input.json
```

**For deterministic integration tests:**
```bash
# Restart the server first so tests run against current code
pixi run gsas-server restart
pixi run pytest tests/test_schema.py -q
```

See [TROUBLESHOOTING.md](TROUBLESHOOTING.md) ("Stale Server (Old Code Running)") for details on stale server issues.

**When to use each mode:**
- **Auto-detect**: Default for interactive use
- **--use-server**: Batch processing, automation, performance-critical
- **--no-server**: Debugging kicker.py, isolated testing, server issues

#### Performance Comparison (Post-Fix ✅)

| Mode | LaB6 Simulation | DRX_33 Multi-phase | Typical Use |
|------|----------------|-------------------|-------------|
| Server (--use-server) | 0.1s | 0.3s | Batch jobs |
| Auto-detect (default) | 0.1-2s | 0.3-3s | Interactive |
| Subprocess (--no-server) | 1.1s | 3s | Debugging |

**Speedup**: Server mode is **10.67x faster** than subprocess for LaB6 simulations.

*Times measured on NSLS-II workstation post-fix*

### Adding a New Refinement Parameter

Follow this pattern (using size broadening as example):

1. **Add to schema** (`schema.py`):
   ```python
   class PeakBroadening(BaseModel):
       size_broadening: dict[str, RefinementParameter | None] | None = None
   ```

2. **Create setter function** (`kicker.py`):
   ```python
   def set_phase_size_broadening(proj, hist, phase_name, size_dict, print_info=False):
       """Set crystallite size broadening for phase-histogram pair."""
       # Extract from size_dict
       size_val = size_dict['size']
       # Access proj.data dictionary
       hap = proj.data[hist.name]['Histograms'][phase_name]
       hap['Size'] = [size_val[0], size_val[1], 'isotropic', [0, 0], 1.0, size_val[1]]
   ```

3. **Integrate into parameterization** (in main execution):
   ```python
   if phase_param.peak_broadening and phase_param.peak_broadening.size_broadening:
       set_phase_size_broadening(proj, hist, phase_name,
                                  phase_param.peak_broadening.size_broadening)
   ```

4. **Add example** (create directory under `examples/`):
   - `input.json` with new parameter
   - `DESCRIPTION.md` explaining use case
   - Run refinement and commit output files

5. **Add test** (if example becomes reference):
   ```python
   def test_example_with_size_broadening(tmp_output_dir):
       # Run refinement, compare outputs
   ```

### Adding a New Example

Examples drive schema evolution. To contribute:

1. **Create directory**: `examples/example_N/`
2. **Add required files**:
   - `input.json` - complete recipe
   - `DESCRIPTION.md` - what refinement demonstrates, data source, expected results
3. **Run refinement**: `pixi run kicker examples/example_N/input.json`
4. **Commit outputs**: `output/` directory with .gpx, .lst, .csv files
5. **Update schema** if new fields needed
6. **Add regression test** if example becomes quality reference

See `examples/CONTRIBUTING_EXAMPLES.md` for detailed guidelines.

### Running Tests

```bash
# All tests
pixi run test

# Specific test file
pixi run pytest tests/test_example_LaB6_regression.py

# With verbose output
pixi run pytest -v

# See stdout/stderr
pixi run pytest -s
```

**Regression test strategy:**
- Exact matching of Rwp, unit cell parameters, peak counts
- Detects any changes in GSAS-II refinement algorithm
- Reference outputs committed to git for comparison
- If test fails: inspect .lst file to determine if change is expected or bug

**Note on test speed:** All tests currently run as a single suite (`pixi run test`). Introducing `@pytest.mark.slow` / `@pytest.mark.integration` markers to allow skipping GSAS-II-dependent tests in CI is planned.

### Template File Detection

PowderLine prevents users from accidentally running template files with three-level detection:

1. **Path check**: Filename/directory contains "template"
2. **Required fields check**: Missing `payload.xrd_data`, `payload.instrument`, or `payload.phases`
3. **Placeholder text check**: Fields contain `"XXXX"` or `"TODO"` or `"REPLACE"`

If detected, shows error with helpful message directing to real examples.

## Key Gotchas & Implementation Notes

### Output File Formats

After refinement, PowderLine generates (fixed filenames):
- **`dummy.gpx`**: GSAS-II project file (can reopen in GUI)
- **`dummy.bak0.gpx`**: Backup before refinement started
- **`dummy.lst`**: Human-readable refinement log with Rwp, parameter tables, correlations
- **`fit_profile.txt`**: 2θ, observed, calculated, background, difference intensities
- **`<phase>_unit_cell_report.csv`**: Refined unit cell parameters per phase
- **`<phase>_peak_list_report.csv`**: Reflection list (hkl, d-spacing, 2θ, intensities) per phase

For single peak fitting (SPF) mode:
- **`single_peaks_report.txt`**: Peak fit results (position, width, intensity per peak)
- **`peak_convergence_diagnostics.txt`**: Convergence warnings for aphysical parameters

**Note**: Output filenames are now fixed (`dummy.*`) regardless of sample name. This simplifies automation and testing by eliminating filename variability.

### Parameter Correlation Warnings

GSAS-II may print warnings about highly correlated parameters (e.g., background coefficients):
```
** Warning: parameters 0 and 1 are 99.8% correlated **
```
This is **normal** for over-parameterized models. Common causes:
- Too many Chebyshev background terms
- Refining both instrument and sample broadening simultaneously
- Limited 2θ range

Not necessarily a problem if Rwp is good and parameters are physically reasonable.

### Unit Cell Refinement Semantics (Schema 0.26)

GSAS-II natively refines all unit cell parameters together with a single lumped flag, but since schema 0.26 PowderLine honors per-parameter flags: a cell parameter refines iff it is present with `refine_flag=true`; absent or false means fixed. Internally, PowderLine sets the lumped GSAS-II flag when any parameter is requested and emits "Hold" constraints for the unrefined degrees of freedom (`src/powderline/constraints.py`):

```json
"unit_cell": {
  "a": [11.777, true, null, null],   // refines
  "c": [3.986, false, null, null]    // held fixed (e.g. a tetragonal phase)
}
```

Only symmetry-linked parameters refine together: parameters coupled by the phase's Laue class form one degree-of-freedom group with logical OR within the group. For example, cubic `a=b=c` is a single group (any true flag refines all three), and the oblique monoclinic parameters `a`/`c`/`beta` form one coupled group (see KI-02 in `docs/known_issues.md`). Flags on symmetry-fixed parameters (e.g. cubic angles) have no effect. PowderLine does not validate flag/symmetry consistency — producing symmetry-consistent flags is the recipe author's responsibility.

### Chebyshev Background Coefficients

Indexing starts from 0th order (constant term):
```json
"coefficients": [
  [100.0, true, null, null],    // 0th order (constant)
  [-50.0, true, null, null],    // 1st order (linear)
  [10.0, true, null, null]      // 2nd order (quadratic)
]
```

Number of coefficients must match `num_coefficients` field (validated in schema).

### Single Peak Background Format

Each single peak is a pseudo-Voigt with 4 parameters:
```json
"background": {
  "single_peaks": {
    "positions": [[35.5, false, null, null]],           // 2θ position
    "intensities": [[50.0, true, null, null]],          // Peak height
    "pv_gaussian_sigma": [[0.1, false, null, null]],    // Gaussian width (σ)
    "pv_lorentzian_gamma": [[0.05, false, null, null]]  // Lorentzian width (γ, HWHM)
  }
}
```

All lists must have same length (validated in schema). Useful for known impurity peaks that are part of the background.

**Note**: `pv_mixing_eta` parameter not currently implemented in schema.

### Single Peak Fitting (Peak List Mode)

Earlier schemas introduced dedicated single peak fitting capabilities via the top-level `single_peaks` field (distinct from `background.single_peaks`), maintained in the current schema.

This enables refining individual peaks with direct control over position, intensity, and pseudo-Voigt width parameters—useful for:
- Materials without crystal structure (amorphous, liquids, polymers)
- Unknown phases requiring peak characterization before structure solution
- Detailed peak shape analysis independent of structure
- Le Bail fitting (fit peak intensities without structural model)

**Key Features:**
- **Independent width refinement**: With `use_instrument_profile: false`, peak widths (σ, γ) refine directly rather than being derived from instrument parameters (U, V, W, X, Y, Z)
- **Coexistence**: Both `background.single_peaks` and `single_peaks` can be used in same recipe—they populate different GSAS-II structures
- **Extended output**: Generates `single_peaks_report.txt` with refined parameters plus calculated FWHM and integral breadths

**JSON Structure:**
```javascript
// use_instrument_profile lives in refinement_controls.single_peak_fitting_mode
// (false = direct width refinement), not inside single_peaks:
"single_peaks": {
  "positions": [[21.3, true, null, null], [...]],     // 2θ positions
  "intensities": [[100.0, true, null, null], [...]],  // Peak intensities
  "pv_gaussian_sigma_sq": [[0.15, true, null, null], [...]], // Gaussian width variances (σ²)
  "pv_lorentzian_gamma": [[0.08, true, null, null], [...]] // Lorentzian widths (γ, HWHM)
}
```

**Implementation Details:**
- **GSAS-II Location**: Peaks stored in `proj.data[hist.name]['Peak List']['peaks']` (not Background)
- **Format**: Each peak is `[pos, pos_flag, intensity, int_flag, σ², σ²_flag, γ, γ_flag]`
  - Note: GSAS-II uses **variance** (σ²) internally, not σ
- **Instrument mode**: Set via `G2pwd.setPeakInstPrmMode(use_instrument_profile)`
  - `False` (default): Peak widths refined independently
  - `True`: Widths constrained by instrument parameters (U, V, W, X, Y, Z)

**Output File: `single_peaks_report.txt`**

Tab-separated file with 10 columns per peak:
```
position_2theta  intensity  sigma  gamma  fwhm_gaussian  fwhm_lorentzian  fwhm_pseudovoigt  integral_breadth_gaussian  integral_breadth_lorentzian  integral_breadth_pseudovoigt
```

**Calculated Values:**
- **FWHM values**:
  - Gaussian: FWHM_G = 2√(2ln2) × σ ≈ 2.355σ
  - Lorentzian: FWHM_L = 2γ
  - Pseudo-Voigt: Thompson et al. (1987) approximation
- **Integral Breadths**: Area under peak / peak height
  - Gaussian: IB_G = FWHM_G × √(π/(4ln2)) ≈ 1.065 × FWHM_G
  - Lorentzian: IB_L = π × γ = (π/2) × FWHM_L
  - Pseudo-Voigt: Weighted combination using mixing parameter η

**Verification**: FWHM values are cross-checked against GSAS-II's `G2pwd.getgamFW(γ, σ)` with warning if >1% difference.

**Example**: See `examples/example_LaB6_singlepeakfit/` for complete demonstration.

**Schema Classes:**
- `SinglePeaksBackground`: For background-associated peaks (`background.single_peaks`)
- `SinglePeaks`: For Peak List fitting (`single_peaks` at top level) - includes `use_instrument_profile`

### Error Handling Strategy

PowderLine fails fast with actionable error messages:
- **File loading errors**: Check paths relative to JSON, file permissions
- **Template detection**: Redirect to real examples
- **Validation errors**: Show which field failed Pydantic validation
- **Histogram creation errors**: Check XRD data format, instrument file compatibility
- **Refinement errors**: Check parameter ranges, correlation warnings in .lst
- **Output errors**: Check directory permissions, disk space

All errors exit with code 1 for automation compatibility.

## Future Roadmap

**Phase 2 (Next)**: Recipe generation API
- Python functions to build JSON programmatically
- Template system for common refinement types
- Possible FastAPI wrapper for web service

**Phase 3**: Output parsing
- Structured extraction of all refined parameters to JSON/CSV/HDF5
- Quality metrics beyond Rwp (χ², GOF, R-Bragg)

**Phase 4**: Dash GUI for recipe building
- Visual parameter selection
- Live preview of refinement setup

**Phase 5**: Dash GUI for results visualization
- Interactive plots of fit profiles
- Parameter evolution across refinement cycles
- Comparison between refinements

## Contributing

Key principles for future work:
- Add features when real examples need them (not speculatively)
- Schema evolves based on examples
- Maintain backwards compatibility when possible
- Document GSAS-II quirks as you discover them
- Add regression tests for new examples

Questions? Open an issue or discussion on GitHub.
