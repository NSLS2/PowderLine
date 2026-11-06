# Fields

Every field of every recipe schema, with its type, unit and whether it is
required. These tables are generated from the schemas.

- The rules every recipe follows (parameter shapes, bounds, numbers, names,
  units) are on [Recipe format](recipe-format.md).
- Which features each schema offers is on the
  [Engines overview](../engines/index.md).
- Why the structural rules are as strict as they are is on
  [Validation](../concepts/validation.md).

How to read the tables:

- **Field** is the dotted path from the top of the recipe. `<phase>` and
  `<label>` stand for your phase names and atom labels.
- **Owner** is `core` for a [core block](recipe-format.md#core-blocks-and-engine-blocks),
  the same in every engine, and `engine` for the engine's own fields.
- **Unit** is fixed per field. A recipe never states it.
- **Notes** says what an optional field means when it is left out.

## Core fields (every schema)

The recipe frame, the data, the fit window, the Chebyshev background and the
phase block (`space_group`, `unit_cell`, `atoms`).

```{include} ../_generated/fields_core.md
```

## `gsasii.rietveld`

```{include} ../_generated/fields_gsasii_rietveld.md
```

## `gsasii.spf`

```{include} ../_generated/fields_gsasii_spf.md
```

## `topas.rietveld`

```{include} ../_generated/fields_topas_rietveld.md
```

## `topas.spf`

```{include} ../_generated/fields_topas_spf.md
```

## `easydiffraction.rietveld`

```{include} ../_generated/fields_easydiffraction_rietveld.md
```
