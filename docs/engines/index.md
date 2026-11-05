# Engines

An **engine** is the refinement program that computes the pattern and runs
the least squares: GSAS-II, TOPAS or easydiffraction. PowderLine does not
refine anything itself. For each engine, a **gateway** checks a recipe in
that engine's own terms and units, runs the engine, and returns the results
in one standard form. A recipe names one engine and one workflow in its
`schema_name`, and nothing is translated between engines. The whole picture
is in [How PowderLine works](../concepts/how-powderline-works.md).

| Engine | Page |
|---|---|
| GSAS-II 5.7.9 | [GSAS-II](gsasii.md) |
| TOPAS 6 | [TOPAS](topas.md) |
| easydiffraction 0.21.1 (CrysPy 0.13.0, CrysFML 0.8.0) | [easydiffraction](easydiffraction.md) |

```{toctree}
:hidden:

gsasii
topas
easydiffraction
```

## The five schemas

| `schema_name` | Engine | Workflow | Parameters | Run with |
|---|---|---|---|---|
| `gsasii.rietveld` | GSAS-II 5.7.9 | Rietveld refinement, one or more phases | `[value, flag]`, no bounds | `pixi run -e gsasii powderline <recipe.json>` |
| `gsasii.spf` | GSAS-II 5.7.9 | Single-peak fitting (GSAS-II's Peak List), no phases | `[value, flag]`, no bounds | `pixi run -e gsasii powderline <recipe.json>` |
| `topas.rietveld` | TOPAS 6 | Rietveld refinement, one or more phases | `[value, flag, min, max]` | `pixi run powderline <recipe.json> --topas-version 6 --topas-dir C:/TOPAS6` |
| `topas.spf` | TOPAS 6 | Single-peak fitting (`xo_Is` peaks), no phases | `[value, flag, min, max]` | `pixi run powderline <recipe.json> --topas-version 6 --topas-dir C:/TOPAS6` |
| `easydiffraction.rietveld` | easydiffraction 0.21.1 | Rietveld refinement; calculator `cryspy` or `crysfml` | `[value, flag, min, max]` | `pixi run -e easydiffraction powderline <recipe.json>` |

easydiffraction has no single-peak-fitting workflow.

You can validate any recipe in any environment, with no engine installed:

```bash
pixi run powderline <recipe.json> --validate-only
```

A TOPAS run needs `tc.exe`, on Windows. Without it, PowderLine writes TOPAS's
input files and stops there (see [TOPAS](topas.md#how-powderline-runs-topas)).

Fill-in templates are in `examples/example_template/`: `input.json` for
GSAS-II, and `topas/input.json` and `easydiffraction/input.json`. Copy one
into your own folder before you fill it in. The command line refuses to run
a recipe whose path contains `template`.

## Features by schema

| Feature | `gsasii.rietveld` | `gsasii.spf` | `topas.rietveld` | `topas.spf` | `easydiffraction.rietveld` |
|---|---|---|---|---|---|
| Phases | one or more | none | one or more | none | one or more |
| Parameter bounds | no | no | yes (TOPAS limits) | yes | yes (physical limits) |
| Refinable cell, coordinates, occupancy, `Uiso`, `Uaniso` | yes | — | yes (`Uiso` written as `beq`) | — | yes (`Uaniso` with CrysPy only) |
| Sample size/strain broadening | isotropic (µm, microstrain) | — | `CS_L`/`CS_G`, `Strain_L`/`Strain_G` | — | none (the profile is the instrument's) |
| Instrument profile | TCH U, V, W, X, Y, Z (GSAS-II letters) | same | `TCHZ_Peak_Type`, `PV_Peak_Type` or `PVII_Peak_Type` | same | `cwl-pseudo-voigt`, Bérar–Baldinozzi (CrysPy), Thompson–Cox–Hastings with FCJ (CrysFML) |
| Axial asymmetry | SH/L (≥ 0.002) | SH/L | `Simple_Axial_Model` / `Full_Axial_Model` | same | FCJ (CrysFML) or Bérar–Baldinozzi (CrysPy) |
| Zero shift | yes | yes | `Zero_Error` | yes | `calib_twotheta_offset` |
| Polarization | `polarization` (GSAS-II's P) | yes | `LP_Factor` or `LP_Factor_Synchrotron` | yes | fixed `setup_polarization_coefficient` (p = 1 − P) |
| Other corrections | — | — | capillary absorption | same | displacement, transparency, cylinder absorption, Kα2 line |
| Background | Chebyshev + pseudo-Voigt peaks | same | Chebyshev, `One_on_X`, `xo_Is` peaks | same | Chebyshev |
| Simulation | `refinement_cycles: 1`, no flag set | same | `iters: 0`, no flag set | same | no flag set |
| Ionic scattering types (`scattering_types`, CIF spelling) | yes (GSAS-II's 114 ions) | — | yes (TOPAS 6's 113 ions, `occ La+3`) | — | cryspy only (111 ions) |
| Preferred orientation (`preferred_orientation`, March–Dollase) | yes | — | yes (`PO` macro) | — | cryspy only, with `march_random_fract` |
| Engine version in the recipe | no (pinned by pixi) | no | `engine_version: "6"` | yes | no (pinned by pixi) |

Every field of every schema, with its unit, is in [Fields](../reference/fields.md).

## Scattering types by engine

`element` is always the neutral atom, so a phase block means the same thing
in every engine. You state an ion per atom label, in the engine's phase
block:

```json
"scattering_types": {"La": "La3+"}
```

You always write ions in the CIF spelling, `La3+`, whatever the engine. An
atom left out of `scattering_types` scatters as its neutral element.

| | GSAS-II 5.7.9 (`gsasii.*`) | easydiffraction 0.21.1, CrysPy (`calculator: "cryspy"`) | easydiffraction 0.21.1, CrysFML (`calculator: "crysfml"`) | TOPAS 6 (`topas.*`) |
|---|---|---|---|---|
| Engine's own spelling | `La+3` | `La3+` | none (charges stripped) | `La+3` |
| Ions with a form factor | 114 | 111 | none | 113 (`ATMSCAT.CPP`) |
| What the engine does with a wrong or unknown ion | reads `La3+` as **hydrogen**, silently ({ref}`EB-94 <eb-94>`) | uses the **neutral** atom, with a log warning only ({ref}`EB-95 <eb-95>`) | uses the **neutral** atom for every ion ({ref}`EB-96 <eb-96>`) | stops without results; the reason appears only in its console window |
| What PowderLine does | writes GSAS-II's spelling into the atom record; refuses an ion GSAS-II has no form factor for | passes the CIF spelling through; refuses an ion CrysPy has no form factor for | refuses `scattering_types` (use the cryspy calculator) | writes TOPAS's spelling into the site's `occ` (`occ La+3 …`); refuses an ion TOPAS has no form factor for |

For LaB6 with `La3+`, the per-reflection ion-to-neutral intensity ratios agree
between GSAS-II and CrysPy within 1 %. Between GSAS-II and TOPAS 6, measured
directly, they agree within 0.07 %.

Edge cases:

- **Coverage differs between engines.** `O2-`, `D1-` and `T1-` are in
  GSAS-II's table but not in CrysPy's. TOPAS's table is the `ATMSCAT.CPP`
  shipped with TOPAS 6: every GSAS-II ion except `T1-`. An oxide stated
  with `O2-` therefore validates for `gsasii.*` and `topas.*` but not for
  easydiffraction, which has only `O1-`. The error names the forms CrysPy
  has.
- **`T1-` cannot be stated at all,** because gemmi has no element `T`.
- **Some atoms have no ion in any engine.** LaB6 is `La3+` with neutral `B`,
  because no engine has a boron ion.
- **Ions are per atom label.** State mixed valence on different sites per
  site. A mixed site, with two species at one position, is two atoms, each
  with its own label and type.
- **Spelling rules:**
  - a charge of 1–8, with an explicit sign;
  - `Fe+3` is an error that names `Fe3+`;
  - `Na+`, with no number, is an error: write `Na1+`;
  - `element` must be the ion's element.
- **Moving a phase between engines** (`powderline.recipes.with_block`)
  copies the whole phase, engine fields included. The target engine's schema
  then validates it, so an ion that engine has no form factor for is an
  error there. Engine fields written in another engine's form, such as
  gsasii's `[value, flag]` against `[value, flag, min, max]`, must be
  rewritten for the target.
- **TOPAS's table can be edited.** `ATMSCAT.CPP` sits in the TOPAS folder,
  and you can change it. PowderLine checks against the file as shipped with
  TOPAS 6.

## Choosing an engine

PowderLine does not rank the engines. What each one needs and offers:

- **GSAS-II** runs on Linux, Windows and macOS, installed by pixi. It does
  Rietveld refinement and single-peak fitting. Its recipes have no bounds,
  and a few documented defaults.
- **TOPAS** recipes validate, and generate TOPAS's input files, on any
  platform. Running them needs TOPAS 6 and its `tc.exe`, on Windows. TOPAS
  does Rietveld refinement and single-peak fitting, with bounds.
- **easydiffraction** runs on Linux, Windows and macOS, installed by pixi,
  with Python 3.12 or later. It does Rietveld refinement only, with bounds,
  and you choose one of two calculators.

The same data refined in every engine, and why the numbers differ, is in
[Comparing engines](../concepts/comparing-engines.md).

## How PowderLine treats engine quirks

Every refinement program has quirks: values it silently rounds, settings it
misreads, defaults it applies without saying so. PowderLine follows one
rule:

- **If an engine would silently change what your recipe means**, PowderLine
  refuses the recipe and tells you what to write instead.
- **If an engine does something you should know about** but your model is
  unchanged, PowderLine runs and adds a warning to the result.

The pages for [GSAS-II](gsasii.md), [TOPAS](topas.md) and
[easydiffraction](easydiffraction.md) list each behaviour PowderLine has
found, with what it does about it. Each behaviour has a permanent ID,
`EB-NN`, that messages and the changelog cite. Every ID is listed in the
[ID index](../reference/ids.md), and every warning code in
[Messages](../reference/messages.md).

Each entry carries a status:

| Status | Meaning |
|---|---|
| {bdg-success}`handled` | PowderLine prevents or corrects it: a validation error, a translation, or a check that stops the run. |
| {bdg-warning}`warned` | The run goes ahead, and the result carries a warning that names it. |
| {bdg-secondary}`open` | Documented only. The engine's behaviour stands, and the entry tells you what to expect. |
| {bdg-info}`fixed upstream` | Fixed in the engine version PowderLine pins. |

The behaviours were established on GSAS-II 5.7.9, TOPAS 6 (TOPAS 7 where
noted) and easydiffraction 0.21.1 with CrysPy 0.13.0 and CrysFML 0.8.0. An
entry marked *unverified* is recorded from documentation or a model, not
from a run. How PowderLine decides a policy is in
[Policies](../development/policies.md).

## Behaviours that concern every engine

```{include} ../_generated/eb_all.md
```
