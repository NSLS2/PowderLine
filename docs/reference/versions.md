# Versions and compatibility

PowderLine versions three things separately: the package, the recipe schemas
and the engines it drives.

| What | Version in PowderLine 0.2.0 | Where you see it |
|---|---|---|
| The `powderline` package | 0.2.0 | `powderline.__version__`, `powderline --doctor` |
| The core schema | 0.1.0 | `core_schema_version` in every recipe |
| The `gsasii`, `topas` and `easydiffraction` engine schemas | 0.1.0 each | `engine_schema_version` in every recipe |
| GSAS-II | 5.7.9 | pinned by the `gsasii` environment |
| easydiffraction | 0.21.1 | pinned by the `easydiffraction` environment |
| TOPAS | 6 | `engine_version` in every `topas.*` recipe |
| gemmi (space groups) | 0.7.5 | pinned in every environment |

## What a version promises

- **The package** follows [Semantic Versioning](https://semver.org/). Every
  release is in the [changelog](../about/changelog.md).
- **The schemas** are versioned apart from the package, each on its own. A
  recipe states two versions: the core schema's and its engine schema's.
- **The schemas are 0.x**, so they will still change. A breaking change (a
  recipe valid before is refused, or means something else) raises the minor
  version: 0.1.0 to 0.2.0. An additive change or a fix raises the patch
  version: 0.1.0 to 0.1.1.
- The process behind a new version is on
  [Policies](../development/policies.md).

## How compatibility is decided

PowderLine never works out from version numbers whether it accepts a recipe.
Every accepted version is **declared** in the code:

- the core declares the core-schema versions it accepts;
- each gateway declares the engine-schema versions it accepts, and the core
  versions each of them needs.

`powderline.validate()` checks a recipe's `core_schema_version`, then its
`engine_schema_version`, then the pair. The error names the accepted versions
and the PowderLine release:

```text
core_schema_version: Value error, core_schema_version '0.1.1' is not supported by PowderLine 0.2.0 (accepted: ==0.1.0; current: 0.1.0)
```

- A recipe with `core_schema_version: "0.1.0"` and
  `engine_schema_version: "0.1.0"` validates on every gateway below.
- Any other pair is refused, even `0.1.1`, until a release declares it.
- Declarations are exact (`==`). A release that accepts a second version lists
  it once it has been checked, never as a range.
- Which engine schema a recipe uses is read from `schema_name`, never from the
  version numbers.

## Support matrix

```{include} ../_generated/support_matrix.md
```

`powderline.support_matrix()` returns the same declarations, one dict per
gateway, with the keys `gateway`, `powderline_version`,
`core_schema_version`, `supported_core_schemas`, `engine_schema_version`,
`supported_engine_schemas`, `requires_core_schema`, `engine_version_spec`,
`workflows` and `declared`. A gateway that declares no versions is listed as
undeclared, and its recipes are refused.

## Engine versions

| Engine | How the version is fixed | When it is checked |
|---|---|---|
| GSAS-II | Pinned by the pixi environment. The gateway requires `==5.7.9`. | At run time, against the installed package. |
| easydiffraction | Pinned by the pixi environment (`==0.21.1`). Recipes state no engine version. | At run time, against the installed package. |
| TOPAS | Cannot be pinned. A recipe states `engine_version: "6"`; the gateway supports TOPAS 6 only. | At run time, against the version **you declare** (`--topas-version` or `topas.version`), because `tc.exe` carries no readable version. |

An installed engine outside its required version is a hard error,
`EngineVersionError`. `powderline --doctor` reports each engine's version
against its requirement ([Command line](cli.md#doctor)).

gemmi provides the canonical space-group names the core schema checks against,
so it is pinned exactly (`==0.7.5`).

:::{note}
**What has been run.** The TOPAS input writer is checked against files
produced on a TOPAS 6 machine. TOPAS execution is verified on TOPAS 6 on
Windows ({ref}`KI-16 <ki-16>`). GSAS-II and easydiffraction execution are
verified on Linux (`linux-64`) and Windows (`win-64`).
:::

## Schema history

Each schema starts at 0.1.0, in PowderLine 0.2.0. The field-by-field
definition is on [Fields](fields.md). What each engine does with its schema
is on its [engine page](../engines/index.md).

### Core schema 0.1.0

Introduced in PowderLine 0.2.0. Every engine schema builds on it.

- **The frame**: `schema_name`, `core_schema_version`,
  `engine_schema_version`, `metadata` (at most 1 MiB) and `payload`
  ([Recipe format](recipe-format.md#the-frame)).
- **Parameters**: `[value, refine_flag]`, or `[value, refine_flag, min, max]`
  in engines with bounds. `value` is a number and `refine_flag` a JSON
  boolean; neither is ever `null`.
- **Data and fit window**: `xrd_data` (2θ in degrees, intensities, weights
  1/σ²) and `fit_range` (`[min, max]` inside the data, with at least two
  points of positive weight).
- **Background**: the Chebyshev block (`num_coefficients`, `coefficients`,
  `refine_flag`).
- **The phase block**: `space_group`, `unit_cell` and `atoms`, with every
  structural quantity a parameter. Each engine schema adds its own phase
  fields next to them, and never changes the core's.
- **Space groups**: gemmi 0.7.5's canonical names, which state the setting
  (`"P m -3 m"`, `"F d -3 m:2"`).
- **Symmetry**: the cell must fit the space group; atoms on special
  positions, symmetry-tied values, flags and bounds follow the rules on
  [Validation](../concepts/validation.md).
- **Atoms**: `element` is the neutral atom (ions go in the engine's
  `scattering_types`); `occupancy` from 0 to 1; `ADP` is `"Uiso"` or
  `"Uaniso"`, with the matching values in Å²; `Multiplicity` is optional and,
  when stated, must equal the derived value.
- **Names, numbers and unknown keys** follow
  [Recipe format](recipe-format.md).
- **Also defined in the core**: the unit-cell report's row names, and the
  building blocks behind the engines' `scattering_types` and March–Dollase
  `preferred_orientation`.

### gsasii engine schema 0.1.0

Introduced in PowderLine 0.2.0, on core 0.1.0.

- **Workflows**: `gsasii.rietveld` (phases) and `gsasii.spf` (single peaks,
  no phases).
- **Parameters**: `[value, refine_flag]` only; no bounds
  ([why](recipe-format.md#gsas-ii-no-bounds)).
- **Phase fields**: `scale`, `peak_broadening` (isotropic size in µm and
  microstrain), `scattering_types` (ions GSAS-II 5.7.9 has a form factor
  for) and `preferred_orientation` (March–Dollase).
- **Instrument**: `radiation` (`type: "PXC"`, `wavelength`), `geometry`,
  `corrections` and `broadening` (`U` … `Z`), in GSAS-II's units.
- **Background**: Chebyshev and pseudo-Voigt background peaks.
- **Controls**: `refinement_cycles`; `1` is a simulation, with every flag
  `false`.
- **Defaults**, each with a warning: sample broadening 10 µm and 0
  microstrain, no background, 5 cycles.
- **Space groups**: the settings GSAS-II cannot read, or reads as another
  setting, are refused.

### topas engine schema 0.1.0

Introduced in PowderLine 0.2.0, on core 0.1.0. The numbers in a recipe are
the numbers TOPAS receives in its input file.

- **Workflows**: `topas.rietveld` (phases) and `topas.spf` (single peaks).
- **TOPAS version**: the recipe states `engine_version: "6"`. TOPAS 6 is the
  only supported version.
- **Parameters**: `[value, refine_flag, min, max]`, with TOPAS's default
  limits on each `null` side ([Bounds](recipe-format.md#topas-default-limits)).
- **Phase fields**: `scale`, `peak_broadening` (`CS_L`, `CS_G`, `Strain_L`,
  `Strain_G`), `scattering_types` (ions in TOPAS 6's table) and
  `preferred_orientation` (TOPAS's `PO` macro).
- **Instrument**: one emission line, optional goniometer radii, corrections
  keyed by TOPAS macro, and a peak type (`TCHZ_Peak_Type`, `PV_Peak_Type` or
  `PVII_Peak_Type`) with its parameters.
- **Background**: Chebyshev, `One_on_X` and background peaks.
- **Controls**: `iters`, `chi2_convergence_criteria`, `x_calculation_step`,
  all required; `iters: 0` is a simulation.
- **No defaults**: a block left out is not modelled.
- **Space groups**: 541 settings accepted; 23 that TOPAS cannot name, or reads
  as another setting, are refused.

### easydiffraction engine schema 0.1.0

Introduced in PowderLine 0.2.0, on core 0.1.0. Recipes use easydiffraction's
own names and units.

- **Workflow**: `easydiffraction.rietveld` (phases); no single-peak fitting.
- **Parameters**: `[value, refine_flag, min, max]`, with easydiffraction's
  physical limits on each `null` side
  ([Bounds](recipe-format.md#easydiffraction-physical-limits)).
- **Phase fields**: `scale`, `scattering_types` and `preferred_orientation`
  (with `march_random_fract`); the last two with the CrysPy calculator only.
- **Instrument**: `radiation` (with an optional Kα2 line), `polarization`,
  `corrections`, `absorption` and `broadening` (a peak type and its
  parameters).
- **Background**: Chebyshev.
- **Controls**: `calculator` (`cryspy` or `crysfml`), `minimizer`,
  `max_iterations` and three tolerances, all required. A recipe with no
  refine flag set is a simulation.
- **No defaults**: a block left out is not modelled.
- **Space groups**: each calculator accepts only the settings it was verified
  to compute: 428 for CrysPy, 230 for CrysFML.

## The split from the single schema

PowderLine 0.1.x read one recipe schema, versions 0.1 to 0.26.0, with
`schema_name` `GSASII_Rietveld` or `GSASII_SPF`. PowderLine 0.2.0 replaced it
with a core schema and one schema per engine, each starting again at 0.1.0. A
schema at 0.1.0 is not older than 0.26.0: it is a different schema, told apart
by `schema_name` and by its two version keys. PowderLine 0.2.0 does not read
0.26.0 recipes. To convert one, see
[Migrating from 0.1](../development/migrating-from-0.1.md).
