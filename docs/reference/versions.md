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

Every schema below starts at 0.1.0 and was introduced in PowderLine 0.2.0.
Each field is on [Fields](fields.md).

| Schema | Summary | Details |
|---|---|---|
| Core 0.1.0 | The frame, the parameter shapes, `xrd_data`, `fit_range`, the Chebyshev background and the phase block (`space_group`, `unit_cell`, `atoms`) with its symmetry rules. Every engine schema builds on it. | [Recipe format](recipe-format.md), [Validation](../concepts/validation.md) |
| `gsasii` 0.1.0, on core 0.1.0 | `gsasii.rietveld` and `gsasii.spf`; `[value, refine_flag]`, no bounds; documented defaults, each with a warning. | [GSAS-II](../engines/gsasii.md) |
| `topas` 0.1.0, on core 0.1.0 | `topas.rietveld` and `topas.spf`; `[value, refine_flag, min, max]` with TOPAS's default limits; `engine_version: "6"`; no defaults. | [TOPAS](../engines/topas.md) |
| `easydiffraction` 0.1.0, on core 0.1.0 | `easydiffraction.rietveld` with the `cryspy` or `crysfml` calculator; `[value, refine_flag, min, max]` with physical limits; no defaults. | [easydiffraction](../engines/easydiffraction.md) |

## The split from the single schema

PowderLine 0.1.x read one recipe schema, versions 0.1 to 0.26.0, with
`schema_name` `GSASII_Rietveld` or `GSASII_SPF`. PowderLine 0.2.0 replaced it
with a core schema and one schema per engine, each starting again at 0.1.0. A
schema at 0.1.0 is not older than 0.26.0: it is a different schema, told apart
by `schema_name` and by its two version keys. PowderLine 0.2.0 does not read
0.26.0 recipes. To convert one, see
[Migrating from 0.1](../development/migrating-from-0.1.md).
