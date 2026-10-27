# Building Recipes

A PowderLine recipe is a single, self-contained JSON (or YAML) document that
describes one refinement: the diffraction data, the instrument, the phases, and
which parameters to refine. PowderLine reads no other files — the data arrays,
instrument parameters, and crystal structures are all embedded in the recipe.

```{toctree}
:hidden:

recipe-helpers
```

## Why PowderLine has no recipe builder

PowderLine deliberately does **not** ship a recipe builder. Recipes are
constructed in many different ways — from GUIs, from scripts, through
interfaces to databases such as Materials Project, or with an LLM assistant —
and any one built-in builder would make choices (defaults, file formats, what
to refine first) that restrict the others. PowderLine instead defines the
recipe format precisely and checks it strictly, and gives you:

- a [blank template](#starting-points) and nine worked examples to copy;
- a [Materials Project builder](#from-materials-project) for simulated patterns;
- [validation](#validating-a-recipe) that names the missing or malformed field;
- [helper code and an LLM prompt template](recipe-helpers.md) for turning a CIF,
  a GSAS-II `.instprm` file, and a diffraction pattern into a recipe. These are
  guidance to adapt, not an authoritative builder.

What a recipe can express — and what it cannot yet — is summarized in
[Supported Features](capabilities.md).

## What a recipe contains

Every recipe has three top-level keys:

| Key | Value |
|---|---|
| `schema_name` | `"GSASII_Rietveld"` (structure-based refinement) or `"GSASII_SPF"` (single-peak fitting, no structure) |
| `schema_version` | `"0.26.0"` — must match the installed PowderLine exactly |
| `payload` | Everything else, in the sections below |

The `payload` sections:

| Section | Required | Holds |
|---|---|---|
| `xrd_data` | always | `tth` (2θ, degrees, strictly increasing), `Itth` (intensity), `Itth_weights` (1/σ²), optional `filename` |
| `refinement_controls` | always | `refinement_cycles` (default 5; `1` means simulation mode), and for SPF `single_peak_fitting_mode` |
| `instrument` | Rietveld and SPF | `description`, `initialization` (GSAS-II instrument parameters: exactly two dicts, the second `{}`), optional `parameterization` (what to refine) |
| `phases` | Rietveld only (forbidden for SPF) | One entry per phase, keyed by phase name: `structure` (starting model) and `parameterization` (what to refine) |
| `single_peaks` | SPF only | Parallel lists of peak positions, intensities, and widths |
| `background` | optional | `chebyshev` polynomial and/or `single_peaks` (background peaks) |
| `fit_range` | optional | `[min_2theta, max_2theta]` in degrees |

### Refinable parameters

Every refinable value is a four-element list:

```json
[4.15682, true, null, null]
```

The elements are `[value, refine_flag, min, max]`:

- **`value`** — the starting value. `null` keeps the value already set in the
  `structure` or `initialization` block or, where nothing is set there, the
  engine's default.
- **`refine_flag`** — `true` refines the parameter; `false` (or leaving the
  parameter out of `parameterization` entirely) holds it fixed.
- **`min` / `max`** — accepted by the schema, but ignored by the GSAS-II and
  TOPAS engines; only easydiffraction uses them, as fit bounds. Leave them
  `null` unless you need them.

In GSAS-II, symmetry-linked parameters refine as a group: for a cubic cell,
flagging any of `a`, `b`, `c` refines all three together, and the same holds
for coordinates and anisotropic displacement components tied by site symmetry.
Flags on symmetry-fixed parameters (e.g. cubic angles) have no effect. The
other engines differ: easydiffraction groups cell parameters the same way (and
does not refine atom parameters), but TOPAS only groups cell lengths. TOPAS
refines a flagged symmetry-fixed angle, site-restricted coordinate, or
displacement component as given, with a warning rather than a constraint, so
flag only the parameters the symmetry allows to vary. See
[Schema History](SCHEMA_HISTORY.md) for the full 0.26.0 refine-flag semantics
(GSAS-II).

### Units

PowderLine uses GSAS-II conventions throughout:

| Quantity | Unit |
|---|---|
| 2θ, `fit_range`, peak positions, instrument `Zero` | degrees |
| Wavelength (`Lam`), cell lengths | Å |
| Cell angles | degrees |
| Instrument `U`, `V`, `W` | centidegrees² |
| Instrument `X`, `Y`, `Z` | centidegrees |
| Isotropic crystallite size | µm |
| Isotropic strain | microstrain: (Δd/d) × 10⁶, so 1000 means Δd/d = 0.001 |
| `Uiso`, `U11`…`U23` | Å² |
| Data weights | 1/σ² |

For the complete list of fields, see the `powderline.schema` models in the
[API Reference](api.rst).

## Starting points

### Copy the template or an example

`examples/example_template/` is a fill-in-the-blanks skeleton covering every
section of a Rietveld recipe. It is not runnable as-is: `pixi run kicker` refuses
any recipe whose path contains `template`, so rename the directory when you
copy it.

The nine worked examples are complete recipes with real data, each with a
`DESCRIPTION.md` and (except `example_LaB6_easydiff`) committed reference
output:

| Example | Type | What it shows |
|---|---|---|
| `example_LaB6` | Rietveld | Instrument calibration on a LaB6 standard: phase scale, Chebyshev background, one background peak, and instrument profile U–Z |
| `example_LaB6_simulation` | Rietveld (simulation) | Calculating a pattern with every flag off and `refinement_cycles: 1` |
| `example_LaB6_singlepeakfit` | SPF | Fitting individual peaks without a crystal structure |
| `example_LaB6_easydiff` | Rietveld | The LaB6 recipe adapted to the easydiffraction engine: no background peak, `Z` fixed, lattice parameter refined |
| `example_DRX_33` | Rietveld | Two phases (cubic and monoclinic): scales, lattice parameters, isotropic size and strain with Lorentzian/Gaussian mixing, background |
| `example_DRX_33_atomrefine` | Rietveld | Adds atom coordinates, occupancies, and Uiso |
| `example_DRX_33_anisoADP` | Rietveld | Anisotropic displacement parameters (U11–U23) |
| `example_DRX_33_strainonly` | Rietveld | The same data with strain-only peak broadening |
| `example_DRX_33_simulation` | Rietveld (simulation) | A two-phase calculated pattern |

The usual workflow is to copy the example closest to your case and replace its
data, structure, and flags.

### From Materials Project

`pixi run mp-simulate` fetches a structure from Materials Project, builds a
simulation recipe for it, and calculates the pattern. Add `--keep-recipe` to
keep the generated recipe JSON as a starting point. The generated recipe is
in simulation mode, so to refine against your own data, replace its
`xrd_data` and instrument, set `payload.refinement_controls.refinement_cycles`
to a value greater than 1 (e.g. 5), and turn on the flags you need (see
[Simulating Patterns from Materials Project](mp-simulation.md)). From
Python, `SimulationRecipeBuilder().build_recipe_from_mp_structure(...)` (in
`powderline.simulation_builder`) builds the same recipe from the structure
returned by `MPInterface(api_key=...).get_structure(material_id)` (in
`powderline.mp_interface`).

### From your own files

To build a recipe from a CIF, a GSAS-II `.instprm` file, and a data file, see
[Recipe Helper Code and LLM Prompt](recipe-helpers.md).

### YAML recipes

`powderline.load_recipe_asset(path)` and `pixi run kicker` also read recipes
written in YAML (`.yaml`, `.yml`, or `.txt`), which can be easier to write by
hand. The structure is identical.

## Validating a recipe

Validate before you run. Each check reports the location of the problem:

```bash
pixi run kicker --validate-only my_recipe.json        # schema + simulation-mode checks
pixi run topas-kicker --validate-only my_recipe.json  # can the recipe be translated to TOPAS?
```

From Python:

```python
import powderline

powderline.validate(recipe)  # schema + simulation-mode checks

# Also check that a specific engine can translate the recipe, without running it:
powderline.run(recipe, "output", engine="easydiffraction", validate_only=True)
```

`powderline.validate` raises `pydantic.ValidationError` for schema problems,
`ValueError` for a simulation-mode recipe with a refine flag set, and
`NotImplementedError` for a peak-broadening model that is not implemented yet.
A `ValidationError` lists each problem with its path in the recipe, for
example:

```text
2 validation errors for RecipeModel
payload.xrd_data
  Value error, XRD 'tth' must be strictly increasing; tth[5]=0.6584157943757244 <= tth[4]=0.6621325357184655. Sort/deduplicate the pattern upstream.
payload.phases.LaB6.parameterization.unit_cell.a.3
  Field required [type=missing, input_value=[4.15682, True, None], input_type=list]
```

Here the data arrays are out of order, and the `a` parameter has three
elements instead of four.

If your tool cannot install GSAS-II, validate against the schema alone with
`powderline.schema.RecipeModel.model_validate(recipe)` (see the schema-only
track in [Using PowderLine in Other Projects](integration-guide.md)). This runs
the same schema checks as `powderline.validate`, without the simulation-mode
check.

### What validation does not catch

Passing validation means the recipe is well-formed, not that it describes the
model you intended. Keep the following in mind:

- **Unknown keys are ignored, not rejected.** A misspelled section
  (`"backgound"`) or a feature PowderLine does not have
  (`"preferred_orientation"`) passes validation and is silently skipped. Check
  key names against the examples or the schema reference.
- **Some errors appear only at run time.** Validation accepts these, and the
  run then fails — not always with a clear message:
  - an `initialization` dict with no `Type` entry;
  - an `instrument.parameterization` block without both `broadening` and
    `corrections` (each may contain only `null` entries);
  - an atom with `ADP: "Uaniso"` but no `Uaniso` values;
  - a phase key that differs from its `structure.phase_name`;
  - an unknown key under `instrument.parameterization.broadening` or
    `corrections`;
  - a two-wavelength (Kα₁/Kα₂, `Lam1`/`Lam2`) instrument.
- **Simulation-mode checks are incomplete.** A flagged `polarization`, or
  flagged SPF `single_peaks`, is not caught when `refinement_cycles` is 1.
- **Unset size and strain fall back to engine defaults, and the engines
  differ.** GSAS-II uses 1 µm and 1000 microstrain; TOPAS uses 10 µm and 0.
  Set `peak_broadening` explicitly if you compare engines.
- **Symmetry is your responsibility.** A fixed cell that breaks its space
  group's symmetry (for example, a cubic phase with `a ≠ b`) is used as given
  ([KI-01](known_issues.md)). For space groups with two origin choices,
  GSAS-II assumes origin choice 2, and PowderLine cannot check that your
  coordinates match ([KI-07](known_issues.md)).
- **Engines support different features.** A recipe valid for GSAS-II may be
  rejected by easydiffraction or only partly translated by TOPAS; run
  `validate_only=True` with the engine you plan to use, and see
  [Supported Features](capabilities.md).
