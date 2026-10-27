# Supported Features

This page summarizes what a PowderLine recipe can describe and which engines
can run it, and lists common refinement features that are **not yet
supported**. It reflects **PowderLine 0.1.2 / recipe schema 0.26.0**; check
[Schema History](SCHEMA_HISTORY.md) for changes in later versions. For how to
write the corresponding recipe fields, see [Building Recipes](building-recipes.md).

## Supported

✓ = supported (refinable where applicable). "Fixed only" = the value is used
but cannot be refined; flagging it for refinement is rejected with an error.
"Ignored" = the engine runs the recipe without this feature.

### Workflows and data

| Feature | GSAS-II (default) | TOPAS v7 | easydiffraction |
|---|---|---|---|
| Rietveld refinement (`GSASII_Rietveld`) | ✓ | ✓ | ✓ |
| Single-peak fitting (`GSASII_SPF`) | ✓ | ✓, except `use_instrument_profile: true` | Not supported |
| Simulation mode (`refinement_cycles: 1`, no flags) | ✓ | ✓ (relative intensities only) | ✓ |
| Multiple phases | ✓ | ✓ | ✓ |
| Constant-wavelength X-ray data on a 2θ axis, single wavelength | ✓ | ✓ | ✓ |
| Data weights (`Itth_weights`), `fit_range` | ✓ | ✓ | ✓ |

The TOPAS engine also requires a Rietveld recipe to include an
`instrument.parameterization` block (it may be empty).

### Instrument

| Parameter | GSAS-II | TOPAS v7 | easydiffraction |
|---|---|---|---|
| Wavelength | ✓ | ✓ | ✓ |
| Profile `U`, `V`, `W`, `X`, `Y` | ✓ | ✓ | ✓ |
| Profile `Z` | ✓ | ✓ | Fixed `Z` ignored; refining rejected |
| Zero shift | ✓ | Ignored (not refined, no warning) | ✓, but see note below |
| Axial divergence (`SH/L`) | ✓ | Ignored (no axial model) | Fixed only |
| Polarization | ✓ | Fixed `LP_Factor(90)`; refine flag ignored | Fixed only |

**Note on zero shift with easydiffraction:** the easydiffraction engine
currently converts the zero shift as if it were in centidegrees, but GSAS-II
(and the recipe) give it in degrees. A nonzero starting zero shift is
therefore passed to easydiffraction 100× too small, and a refined value is
reported 100× too large. Check zero-shift results from this engine against
GSAS-II.

### Background

| Feature | GSAS-II | TOPAS v7 | easydiffraction |
|---|---|---|---|
| Chebyshev polynomial | ✓ | ✓ | ✓ |
| Background peaks (`background.single_peaks`) | ✓ | ✓ | Ignored; refining positions or intensities is rejected |

### Phases

| Parameter | GSAS-II | TOPAS v7 | easydiffraction |
|---|---|---|---|
| Phase scale | ✓ | ✓ | ✓ |
| Unit cell, with symmetry-linked parameters refined together | ✓ | ✓, but see note below | ✓ |
| Atom coordinates, occupancies, Uiso | ✓ | ✓, but see note below | Fixed only |
| Anisotropic displacement (`U11`…`U23`) | ✓ | ✓, but see note below | Fixed values ignored; refining rejected |
| Isotropic crystallite size and microstrain, with Lorentzian/Gaussian mixing (`LG_eta`) | ✓ | ✓ | Ignored, with a warning (also when flagged) |

Intensity is scaled through each phase's `scale`; the histogram scale is
fixed at 1.

**Note on symmetry with TOPAS:** GSAS-II refines symmetry-linked parameters
together and ignores flags on symmetry-fixed ones. TOPAS only groups
symmetry-linked cell lengths. A flagged symmetry-fixed cell angle,
site-restricted coordinate, or anisotropic displacement component is refined
as given, with a warning rather than a constraint.

**Peak fitting alongside a structure.** A Rietveld recipe can fit individual
peaks together with the structural model through background peaks
(`background.single_peaks`) — for example, an impurity or unindexed peak.
`examples/example_LaB6` refines one background peak this way.

## Not yet supported

The following are not yet supported by any engine. Unless noted, a recipe
cannot express them; unknown keys are ignored rather than rejected, so
adding a field for one of these features will not make it take effect.

- **Pawley and Le Bail fitting** (whole-pattern fitting with unconstrained
  reflection intensities). For structure-free fitting, use single-peak fitting
  (`GSASII_SPF`).
- **Anisotropic peak broadening:** uniaxial or ellipsoidal crystallite size,
  and uniaxial or generalized (Stephens) microstrain. The schema names these
  models, but validation raises `NotImplementedError` if you select one.
- **Sample corrections:** preferred orientation, absorption, sample
  displacement, extinction, and surface roughness.
- **User-defined constraints, restraints, and rigid bodies** (for example,
  tying two sites' occupancies together, or restraining bond lengths).
  Symmetry constraints are applied automatically by GSAS-II (see the note on
  TOPAS above).
- **Parameter limits.** The `min`/`max` entries are ignored by GSAS-II and
  TOPAS; only easydiffraction uses them, as fit bounds.
- **Kα₁/Kα₂ doublets** and other multi-wavelength sources.
- **Other radiation and geometries:** neutron, time-of-flight, and
  energy-dispersive data. Data on a Q or d-spacing axis must be converted to 2θ
  before it goes in the recipe.
- **More than one pattern per recipe:** joint refinement of several
  histograms, and sequential refinement that carries results into the next
  recipe ([KI-04](known_issues.md)).
- **Choice of minimization algorithm.** `refinement_controls.refinement_algorithm`
  is reserved and currently unused.
- **Magnetic structures.**
