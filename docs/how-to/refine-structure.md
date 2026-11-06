# Refine a structure

**Goal:** refine the crystal structure of one or more phases: the cell, the
atom positions, occupancies and displacement parameters, with ionic
scattering factors and texture where your sample needs them.

**You need:**
- A recipe that validates, with the instrument from a standard held
  ([Calibrate the instrument](calibrate-instrument.md)).
- Your structure, written as a phase block. PowderLine reads no CIF files:
  your own tooling (a script, a notebook, a database export) writes the
  block, and validation checks it against the space group.
  [Where recipes come from](../concepts/recipes.md#where-recipes-come-from)
  explains why.

## 1. Write the phase block

A phase is one entry in `payload.phases`, keyed by its name. This is the
LaB6 phase of `examples/example_LaB6/input.json`:

```json
"phases": {
  "LaB6": {
    "space_group": "P m -3 m",
    "unit_cell": {
      "a": [4.15682, false], "b": [4.15682, false], "c": [4.15682, false],
      "alpha": [90.0, false], "beta": [90.0, false], "gamma": [90.0, false]
    },
    "atoms": {
      "La": {"element": "La", "x": [0.0, false], "y": [0.0, false], "z": [0.0, false],
             "occupancy": [1.0, false], "ADP": "Uiso", "Uiso": [0.00858, false]},
      "B":  {"element": "B", "x": [0.5, false], "y": [0.5, false], "z": [0.2021, false],
             "occupancy": [1.0, false], "ADP": "Uiso", "Uiso": [0.009, false]}
    },
    "scale": [1, true]
  }
}
```

- `space_group` is gemmi's canonical name, which states the setting:
  `"P m -3 m"`, `"F d -3 m:2"`, `"R -3 m:H"`, `"C 1 2/m 1"`.
- `unit_cell` states all six values, in Å and degrees, in every space group.
- `element` is the neutral atom. Ions go in `scattering_types` (step 4).
- Coordinates on a special position are written exactly: `0.5`, `0.25`, and
  a third to at least six decimals (`0.333333`).
- `ADP` is `"Uiso"` with `Uiso`, or `"Uaniso"` with all six `U11` … `U23`,
  in Å².

The block is the same in every engine, apart from the parameter shape:
`[value, flag]` in GSAS-II recipes, `[value, flag, min, max]` in TOPAS and
easydiffraction recipes ([Recipes](../concepts/recipes.md#every-refinable-value-carries-its-flag)).
[Recipe format](../reference/recipe-format.md#bounds) says what a bound
means in each engine, and [Fields](../reference/fields.md) lists every field.

## 2. Choose what to refine

Set a parameter's flag to `true` to refine it. Parameters tied by symmetry
count as **one** parameter, so every member of a tie group is stated and
carries the **same** flag. A parameter fixed by symmetry keeps `false`.

| To refine | Set to `true` | Keep `false` |
|---|---|---|
| A cubic cell | `a`, `b`, `c` together | the three angles |
| A monoclinic cell (b unique) | `a`, `b`, `c`, `beta` as you choose; in `gsasii.*`, `a`, `c` and `beta` together | `alpha`, `gamma` |
| An atom on a general position | `x`, `y`, `z` | |
| An atom on `(0, y, 1/2)` | `y` | `x`, `z` |
| An atom on `(x, x, x)` | `x`, `y`, `z` together | |
| An occupancy | `occupancy` (stays between 0 and 1) | |
| A displacement parameter | `Uiso`, or the free `Uaniso` components | components fixed by the site symmetry |

GSAS-II refines an oblique cell as a group: `a`, `c` and `beta` for a
b-unique monoclinic cell, all six values for triclinic cells and rhombohedral
axes. A `gsasii.*` recipe refines the whole group or none of it.

Validation names any flag that breaks these rules, and the fix:

```
• payload -> phases -> DRX_33 -> unit_cell -> b: Value error, cubic cell ('F m -3 m'): a, b, c are one parameter; set the same refine flag on all three
• payload -> phases -> DRX_33 -> atoms -> O1 -> x: Value error, atom 'O1' (multiplicity 4 in 'F m -3 m'): x is fixed by symmetry (= 1/2); set its refine flag to false
• payload -> phases -> Li4MgWO6_SG12 -> unit_cell -> c: GSAS-II refines a, c, beta together (it varies the reciprocal metric tensor), but only a is refined; refine all of a, c, beta or none
```

In TOPAS and easydiffraction recipes, a parameter fixed by symmetry also has
no bounds (`null`, `null`). The bounds of tied members follow the tie, like
their values.

:::{important}
Some parameters change the pattern in nearly the same way. Releasing the
occupancy and the displacement parameter of the same site together, or
crystallite size and microstrain together, often gives large, correlated
uncertainties and unphysical values. Read
[Good refinement practice](../concepts/refinement-practice.md) before you do.
:::

## 3. Use anisotropic displacement parameters

Write `"ADP": "Uaniso"` and all six components. The O1 atom of phase
`Li4MgWO6_SG12` in `examples/example_DRX_33_anisoADP/input.json` sits on a
general position, so
all six are free:

```json
"O1": {"element": "O", "x": [0.238, false], "y": [0.343, false], "z": [0.234, false],
       "occupancy": [1.0, false], "ADP": "Uaniso",
       "Uaniso": {"U11": [0.01, true], "U22": [0.012, true], "U33": [0.008, true],
                  "U12": [0.002, true], "U13": [0.001, true], "U23": [0.003, true]}}
```

On a special position the site symmetry fixes or couples some components.
Write a fixed component as exactly `0`, and a coupled one at its derived
value. Validation names any component that does not fit.

:::{note}
A `Uaniso` tensor that is not positive definite is accepted with the
warning `uaniso_not_positive_definite` and used as stated. A negative `Uiso`
is accepted without a warning in GSAS-II and TOPAS recipes.
easydiffraction recipes refuse it at validation: there `Uiso`, `U11`, `U22`
and `U33` must lie between 0 and 10 Å².
:::

## 4. Use ionic scattering factors

State the ion per atom label in the phase's `scattering_types`, in the CIF
spelling. `element` stays the neutral atom. In
`examples/example_LaB6_ionic/input.json` the LaB6 phase carries, beside its
`space_group`, `unit_cell`, `atoms` and `scale`:

```json
"scattering_types": {"La": "La3+"}
```

- An atom left out of `scattering_types` scatters as its neutral element.
- Write the charge as a number and a sign: `"La3+"`, `"O2-"`, `"Na1+"`.
  `"W+6"` is an error that names `"W6+"`.
- Each engine has its own table of ions. PowderLine refuses an ion the
  engine has no form factor for, so `"O2-"` validates for GSAS-II and TOPAS
  but not for easydiffraction.
- In easydiffraction, `scattering_types` needs `"calculator": "cryspy"`.

The table of ions by engine is on the [Engines](../engines/index.md)
overview.

## 5. Model preferred orientation

PowderLine offers the March–Dollase model, one axis per phase. The ratio `r`
is 1 for a random powder, below 1 for platy crystals and above 1 for
needles. These blocks are from `examples/example_LaB6_textured/`:

::::{tab-set}
:sync-group: engine

:::{tab-item} GSAS-II
:sync: gsasii

```json
"preferred_orientation": {"model": "march_dollase", "hkl": [0, 0, 1], "ratio": [0.8, true]}
```
:::
:::{tab-item} TOPAS
:sync: topas

```json
"preferred_orientation": {"model": "march_dollase", "hkl": [0, 0, 1], "ratio": [0.8, true, null, null]}
```
A `null` bound keeps TOPAS's own limit on that side: minimum 0.0001,
maximum 2r + 0.5. A refined start below 0.0001 with no stated minimum is an
error.
:::
:::{tab-item} easydiffraction
:sync: easydiffraction

```json
"preferred_orientation": {"model": "march_dollase", "hkl": [0, 0, 1],
                          "ratio": [0.8, true, 0.1, 5.0],
                          "march_random_fract": [0.0, false, 0.0, 1.0]}
```
`march_random_fract` is required: the fraction of the sample with no
preferred orientation, between 0 and 1. The block needs
`"calculator": "cryspy"`.
:::
::::

:::{tip}
Start `ratio` on the side of 1 you expect, not at exactly 1.0. In a cubic
phase the correction does not change at r = 1, and GSAS-II then aborts the
refinement ({ref}`EB-99 <eb-99>`).
:::

## 6. Add sample broadening

Peak broadening from the sample is an engine field of the phase:

::::{tab-set}
:sync-group: engine

:::{tab-item} GSAS-II
:sync: gsasii

```json
"peak_broadening": {
  "size_broadening": {"model": "isotropic", "isotropic_size": [1.0, true], "LG_eta": [1.0, false]},
  "strain_broadening": {"model": "isotropic", "isotropic_strain": [1000.0, false], "LG_eta": [1.0, false]}
}
```
Size is in µm, strain in microstrain. Left out, PowderLine applies 10 µm and
0 microstrain, fixed, and warns `gsasii_broadening_default_applied`.
:::
:::{tab-item} TOPAS
:sync: topas

```json
"peak_broadening": {
  "size_broadening": {"model": "isotropic", "CS_L": [100.0, true, null, null]},
  "strain_broadening": {"model": "isotropic", "Strain_L": [0.1, false, null, null]}
}
```
`CS_L` and `CS_G` are in nm, `Strain_L` and `Strain_G` in degrees 2θ. Each
block states at least one of its two. Left out, the phase has no sample
broadening.
:::
:::{tab-item} easydiffraction
:sync: easydiffraction

An easydiffraction phase has no `peak_broadening` block. The peak widths
come from the instrument's `broadening` block.
:::
::::

The values above show the shape only. Choose your own starting values.

## 7. Refine several phases

Add one entry per phase to `payload.phases`. Each phase has its own space
group, cell, atoms and `scale`. `examples/example_DRX_33/input.json` refines
two phases, `DRX_33` and `Li4MgWO6_SG12`.

- Phase names and atom labels start with a letter, then letters, digits or
  `_`, up to 64 characters. Write `"2H-MoS2"` as `MoS2_2H`.
- Two names may not differ only by case.
- Each phase gets its own reports, `<phase>_unit_cell_report.csv` and
  `<phase>_peak_list_report.csv`.

Two species sharing one site are two atoms, each with its own label, values
and flags. PowderLine never ties them together.

## 8. Validate and run

```bash
pixi run powderline my_sample/input.json --validate-only
```

Then run it with your engine:

::::{tab-set}
:sync-group: engine

:::{tab-item} GSAS-II
:sync: gsasii

```bash
pixi run -e gsasii powderline my_sample/input.json
```
:::
:::{tab-item} TOPAS
:sync: topas

```bash
pixi run powderline my_sample/input.json --topas-version 6 --topas-dir C:/TOPAS6
```

TOPAS runs on Windows only. See [Run TOPAS recipes](run-topas.md).
:::
:::{tab-item} easydiffraction
:sync: easydiffraction

```bash
pixi run -e easydiffraction powderline my_sample/input.json
```
:::
::::

**Check:**
- The validate-only report says `Parameters requested: N`, with a tie group
  counted once.
- In `my_sample/output/parameter_dispositions.csv`, each parameter you
  released reads `varied`, and none reads `requested_not_varied`. If the
  engine varied fewer parameters than you asked for, the run also warns
  `<engine>_parameters_not_varied`.
- `my_sample/output/refined_parameters.csv` lists each refined value with
  its ESD, under the engine's own parameter names.
- The run prints `Output recipe: …/output_recipe.json` with no
  `(not valid as written …)` after it. If it does, the engine returned a
  value the recipe format refuses, such as an occupancy above 1. The
  `output_recipe_not_valid` warning names it.

**Next:** [Model disorder near special positions](disorder.md),
[Run a series](sequential-refinement.md).
