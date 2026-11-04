# Fields and features

Every field of every recipe schema, with its unit. The tables are **generated
from the schemas themselves** (each pydantic model's JSON Schema and the
`unit` metadata every quantity carries), so they cannot drift from the code.
Regenerate them after a schema change with

```bash
PYTHONPATH=src python scripts/gen_schema_field_tables.py          # rewrites docs/_generated/fields_*.md
PYTHONPATH=src python scripts/gen_schema_field_tables.py --check  # one line saying what matched; exit 1 naming a stale table
```

(engine-free; the default environment suffices). The same script writes the
table on the [support matrix](support-matrix.md) page.

## Conventions shared by every schema

- **Parameters.** A refinable quantity is a JSON list, never an object:
  `[value, refine_flag]` in `gsasii.*` (GSAS-II applies limits only after a
  fit, so gsasii 0.1.0 exposes no bounds), `[value, refine_flag, min, max]`
  in `topas.*` and `easydiffraction.*`. `value` is a number and never `null`;
  `refine_flag` is a JSON boolean (`true`/`false`, never `1` or `"true"`);
  `min`/`max` are numbers or `null` (open side). A parameter refines when its
  flag is `true`. Within an engine every parameter has that engine's one shape.
- **Bounds mean different things per engine.** In `topas.*` a stated bound
  replaces TOPAS's default limit on that side and `null` keeps TOPAS's own
  default limit; in `easydiffraction.*` a stated bound replaces the engine's
  physical limit and `null` keeps it. Details and the limit-hit warnings are
  on the [engine behaviour page](engine-behavior.md#bounds-and-limits).
- **Units are fixed per field** (the `Unit` column) and never written in a
  recipe. The vocabulary: `degree 2theta`, `degree`, `angstrom`,
  `angstrom^2`, `arbitrary`, `1/intensity^2` (core); `centidegree 2theta`,
  `centidegree^2 2theta`, `micrometre`, `microstrain`, `dimensionless`
  (gsasii); `milliangstrom`, `nanometre`, `millimetre`, `1/cm` (topas);
  `degree^2` (easydiffraction). The same physical quantity may have different
  units in different engines (GSAS-II's `U` is in centidegree², TOPAS's and
  easydiffraction's in degree²), because each recipe states the engine's own
  numbers.
- **Numbers are JSON numbers.** A quoted number (`"0.25"`) or a boolean where
  a number belongs is an error; integer fields (`Multiplicity`,
  `num_coefficients`, `bank`, `iters`) take a whole number (`4` or `4.0`).
- **Unknown keys are errors** at every level (`extra='forbid'`), and a block
  that may be left out is left out, never `null`.
- **Names.** Phase names (the `phases` keys) and atom labels (the `atoms`
  keys) start with a letter, contain only ASCII letters, digits and `_`, are at
  most 64 characters, are not Python keywords, and differ by more than case.
- **`metadata`** is free-form, never read by PowderLine, echoed into results;
  at most 1 MiB as UTF-8 JSON.
- **Left out means** what each table's *Notes* column says: in `gsasii.*` a
  few blocks have documented defaults (size/strain, background), applied with
  a structured warning; in `topas.*` and `easydiffraction.*` nothing has a
  default and a block left out is not modelled.

## Core fields (every schema)

The recipe frame and the structural models PowderLine owns: `xrd_data`, the
fit window, the Chebyshev background and the phase block (`space_group`,
`unit_cell`, `atoms`). The rules behind them (canonical space-group names,
symmetry-determined values, tie groups and flags, the name rule) are on the
[input guidance page](input-guidance.md) and in
[SCHEMA_HISTORY](SCHEMA_HISTORY.md#core-schema).

```{include} _generated/fields_core.md
```

## Features by schema

| Feature | `gsasii.rietveld` | `gsasii.spf` | `topas.rietveld` | `topas.spf` | `easydiffraction.rietveld` |
|---|---|---|---|---|---|
| Phases | one or more | none | one or more | none | one or more |
| Parameter bounds | no | no | yes (TOPAS limits) | yes | yes (physical limits) |
| Refinable cell, coordinates, occupancy, `Uiso`, `Uaniso` | yes | — | yes (`Uiso` written as `beq`) | — | yes (`Uaniso` with CrysPy only) |
| Sample size/strain broadening | isotropic (µm, microstrain) | — | `CS_L`/`CS_G`, `Strain_L`/`Strain_G` | — | none (profile is the instrument's) |
| Instrument profile | TCH U, V, W, X, Y, Z (GSAS-II letters) | same | `TCHZ_Peak_Type`, `PV_Peak_Type` or `PVII_Peak_Type` | same | `cwl-pseudo-voigt`, Bérar–Baldinozzi (CrysPy), Thompson–Cox–Hastings with FCJ (CrysFML) |
| Axial asymmetry | SH/L (≥ 0.002) | SH/L | `Simple_Axial_Model` / `Full_Axial_Model` | same | FCJ (CrysFML) or Bérar–Baldinozzi (CrysPy) |
| Zero shift | yes | yes | `Zero_Error` | yes | `calib_twotheta_offset` |
| Polarization | `polarization` (GSAS-II P) | yes | `LP_Factor` or `LP_Factor_Synchrotron` | yes | fixed `setup_polarization_coefficient` (p = 1 − P) |
| Other corrections | — | — | capillary absorption | same | displacement, transparency, cylinder absorption, Kα2 line |
| Background | Chebyshev + pseudo-Voigt peaks | same | Chebyshev, `One_on_X`, `xo_Is` peaks | same | Chebyshev |
| Simulation | `refinement_cycles: 1`, no flag set | same | `iters: 0`, no flag set | same | no flag set |
| Multi-phase | yes | — | yes | — | yes |
| Ionic scattering types (`scattering_types`, CIF spelling) | yes (GSAS-II's 114 ions) | — | refused in 0.1.0 | — | cryspy only (111 ions) |
| Preferred orientation (`preferred_orientation`, March–Dollase) | yes | — | refused in 0.1.0 | — | cryspy only, with `march_random_fract` |
| Engine version in the recipe | no (pinned by pixi) | no | `engine_version: "6"` | yes | no (pinned by pixi) |

## `gsasii.rietveld`

```{include} _generated/fields_gsasii_rietveld.md
```

## `gsasii.spf`

```{include} _generated/fields_gsasii_spf.md
```

## `topas.rietveld`

```{include} _generated/fields_topas_rietveld.md
```

## `topas.spf`

```{include} _generated/fields_topas_spf.md
```

## `easydiffraction.rietveld`

```{include} _generated/fields_easydiffraction_rietveld.md
```
