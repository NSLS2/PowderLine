# Schema Evolution History

PowderLine recipes are validated against a **core schema** (the shared top level
and structural models, owned by PowderLine) plus one **engine schema** per
gateway (`gsasii`, `topas`, `easydiffraction`), each in its engine's native
conventions. Every schema has its own version. A recipe states both
(`core_schema_version`, `engine_schema_version`), and each PowderLine release
**declares** which versions it accepts. Compatibility is never inferred from the
version numbers (`powderline.support_matrix()` lists the declarations).

> **PowderLine 0.2.0** reads these schemas only. The unified 0.26.0 schema of
> PowderLine 0.1.1 is documented in the archive at the bottom of this page and
> is no longer accepted; `scripts/convert_recipe_026.py` converts a 0.26.0
> GSAS-II recipe (see the [migration guide](migration-0.1-to-0.2.md)). The
> field tables generated from these schemas are on the [fields page](fields.md).

## Version numbering: a new line starting at 0.1.0

PowderLine 0.2.0 replaces the single recipe schema of PowderLine 0.1.x —
versions 0.1 to **0.26.0**, `schema_name` `GSASII_Rietveld` / `GSASII_SPF` —
with a **core schema** and **one schema per engine** (`gsasii`, `topas`,
`easydiffraction`). Each is versioned separately, and each starts at
**0.1.0** in PowderLine 0.2.0 (`"core_schema_version": "0.1.0"`,
`"engine_schema_version": "0.1.0"`).

- The old line **ends at 0.26.0**. It is told apart from the new schemas by
  `schema_name` (`GSASII_Rietveld` versus `gsasii.rietveld`) and by the split
  into `core_schema_version` + `engine_schema_version` (instead of one
  `schema_version`), **not by the number**: a new schema at 0.1.0 is not
  older than 0.26.0, it is a different schema.
- The new schemas are 0.x because PowderLine is pre-production and they will
  still evolve; the bump rule for 0.x versions is in
  [policies](policies.md#versioning-and-compatibility).
- `scripts/convert_recipe_026.py` migrates a 0.26.0 GSAS-II recipe to
  `gsasii.*` 0.1.0; there is no converter to `topas.*` or `easydiffraction.*`
  (see the [migration guide](migration-0.1-to-0.2.md)).

---

## Core schema

### 0.1.0 — introduced in PowderLine 0.2.0

Defined in `src/powderline/schema_core.py`; every engine schema builds on it.

> **Pre-release revision (re/03b, not a new version).** Before its first
> release, core 0.1.0 replaced its structure-only phase model (`PhaseStructure`
> with plain values, plus `null`-valued "structure" parameters) with the
> **phase block** described below: one block per phase, every structural
> quantity a refinable parameter, flags and bounds checked against the symmetry,
> and `space_group` in gemmi's canonical spelling. No recipe was ever written
> against the earlier draft.

- **Recipe frame** (`CoreRecipe`): `schema_name` (`"<engine>.<workflow>"`),
  `core_schema_version`, `engine_schema_version`, `metadata`, `payload` (typed
  by the engine schema). Unknown keys are errors at every level.
- **`metadata`**: free-form and never interpreted; must be JSON-serializable and
  at most **1 MiB** as UTF-8 JSON. The cap is the constant
  `schema_core.METADATA_MAX_BYTES`; change it there and record the change here.
- **Parameters**: `[value, refine_flag]` (no bounds) or
  `[value, refine_flag, min, max]` (bounds the engine honors; `min`/`max` may
  be `null` = open). A bounded list where bounds aren't supported is an error.
  `value` is always a number and `refine_flag` a JSON boolean; neither is ever
  `null`.
- **Data and ranges**: `xrd_data` (2θ in degrees, weights 1/σ², validated as in
  0.26.0); `fit_range` `[min, max]`, with `max > min`, inside the data's 2θ range, holding at least two points with a positive weight (re/05).
- **Background**: Chebyshev (`num_coefficients`, `coefficients`, `refine_flag`).
  Coefficient semantics are documented per engine.
- **Units** are fixed per field in the schema, never written in a recipe.
- **Numbers** are JSON numbers: a quoted number (`"0.25"`) or a boolean is an
  error, never converted. Integer fields (`Multiplicity`, `num_coefficients`)
  take a whole number (`4` or `4.0`), not `4.5`.
- **Accepted core versions** (this release): `==0.1.0`. Compatibility is
  declared, never inferred ([support matrix](support-matrix.md)).

- **Phase block** (`Phase`): one block per phase, keyed by the phase name in
  the engine payload's `phases` (no `phase_name` field). Core owns
  `space_group`, `unit_cell` and `atoms`; each engine schema adds its own phase
  fields next to them (e.g. gsasii `scale`, `peak_broadening`) and may add
  its own checks, but never redefine, skip or rewrite core's fields and
  validation (checked when the engine schema is defined, and by a test). Every structural quantity is a parameter (`[value, flag]`,
  or `[value, flag, min, max]` in engines with bounds): cell `a`–`gamma`; atom
  `x`, `y`, `z`, `occupancy`, `Uiso` or `U11`…`U23`. `element`, `ADP`,
  `Multiplicity` and `space_group` are plain values. Nothing is `null` and
  nothing has a default: `occupancy` must be stated; `Multiplicity` (derived,
  so optional) is left out when not stated, never `null`.
  **Names:** atom labels (the `atoms` keys) and phase names (the engine
  payload's `phases` keys) start with a letter and contain only ASCII letters,
  digits and `_` (`O1`, `LaB6_a`); phase names, and the atom labels of a
  phase, must also differ by more than case. This is the form every engine can use as-is: GSAS-II renames a phase
  with surrounding spaces or non-ASCII characters (and its settings were then
  skipped), easydiffraction accepts no other atom label, TOPAS writes the names
  into its input file, phase names become report file names (which ignore case
  on Windows and macOS), and problems are reported at `.`-joined paths
  (`atoms.O1.Uiso`). So `"2H-MoS2"` is written e.g. `MoS2_2H`.
  Structural interpretation is checked once, in core, so every engine gets the
  same structure. **The recipe is the record of the refinement intent**, and
  validation never changes what it means. Values fixed or tied by symmetry
  follow one rule (see *Symmetry-determined values* below): the first member
  of each tie group is stated freely and kept as written; every other value is
  derived from the symmetry and must be stated, either exactly (a constant
  with a decimal form, such as `0.5` or `0`) or to the precision that states it
  beyond doubt (a third, `0.333333`; a value derived from another stated
  value). The validated model, which every engine receives, holds the derived
  values. PowderLine never rewrites a recipe file; only a Python dump of a
  validated model shows a derived value's full spelling
  (`0.3333333333333333`), which means the same and validates the same. All problems
  are reported together, each at its own field
  (`unit_cell`, `atoms.<label>` for the position, `atoms.<label>.Multiplicity`,
  `atoms.<label>.Uaniso`, or the parameter a flag/bound rule concerns, e.g.
  `unit_cell.b`, `atoms.<label>.y`, `atoms.<label>.Uaniso.U12`); they are checked
  once the individual fields are valid:
  - **Space group**: gemmi's canonical extended Hermann–Mauguin name, exactly:
    `"P m -3 m"`, `"C 1 2/m 1"`, `"P 1 21/c 1"`, `"R -3 m:H"`, `"F d -3 m:2"`.
    Every setting has exactly one such name, and it states the setting
    (two-origin groups `:1`/`:2`, rhombohedral groups `:H`/`:R`, the monoclinic
    unique axis). Any other spelling (`"Pm-3m"`, `"C2/m"`, `"p m -3 m"`) is an
    error whose message gives the canonical name; a symbol without a setting
    (`"R -3 m"`, `"F d -3 m"`) lists both choices, and a short monoclinic
    symbol (`"P21/c"`, `"C2/m"`) lists every setting of that space group by
    unique axis, because it states neither the unique axis nor the cell choice.
    Each engine translates the name to its own convention, and may accept fewer
    settings. The accepted names are those of gemmi 0.7.5, which PowderLine pins
    exactly; the list is `tests/data/canonical_space_groups.txt`, and any change
    to it is recorded here.
  - **Unit cell**: `a`, `b`, `c` (Å, > 0), `alpha`, `beta`, `gamma` (degrees,
    0–180). In engines with bounds, a stated bound must lie in the same range
    (a length's `min` > 0; an angle's `min`/`max` strictly between 0 and 180);
    `null` means no bound. No `volume` (every engine derives it). The cell must fit the
    space group: tied lengths and angles equal the first one (cubic
    `b = a`, `c = a`), and fixed angles are exactly 90° (or 120° for `gamma`
    on hexagonal axes), to within 1e-9 (relative on lengths, degrees on
    angles), the floating-point noise of a cell computed by a program. The
    validated model holds the first member's value and the exact angles. A
    mismatch is an error stating each value and the value to write
    (`stated b = 4.2, but by symmetry b = a; write b = 4.15692`). (GSAS-II
    alone would silently apply the symmetry only when the cell is refined.)
  - **Elements**: a bare element symbol spelled exactly (`"Fe"`, not `"FE"`),
    always the neutral atom. A charged symbol here is an error pointing at the
    engine block's `scattering_types`, where an ion is stated in the CIF
    spelling (`"Fe3+"`; re/28, P-47) — never reduced to the neutral atom.
  - **Occupancy**: 0 to 1 inclusive, even where an engine would accept more.
  - **Symmetry-determined values** (special positions, anisotropic ADPs,
    tied bounds). Within 5e-6 of a special position an atom is on it; from
    5e-6 to 2e-3 off is an error (state the position, or move the atom at least
    2e-3 off it: `0.33` and `0.3333` are neither). On a special position:
    - the **first member of each tie group** (x before y before z; U11 before
      U22 …) is the free parameter: it is kept exactly as written, whatever its
      value;
    - a **constant** of the site, i.e. a coordinate fixed by symmetry or a
      Uij that must be 0, is written **exactly** when it has a decimal form
      (`0.5`, `0.25`, `0.125`, `0`), and to **at least 6 decimals** when it has
      none, i.e. when it is a third (`0.333333` for 1/3, `0.166667` for 1/6);
    - a value **derived from another stated value**, i.e. a coupled
      coordinate (`(x, 2x, 1/4)`, `(x, x + 1/2, z)`, `(x, x + 1/3, 1/6)`), a
      coupled Uij (`U22 = U11`, `U12 = U22/2`) or a tied member's bounds, is
      stated to the precision of its kind (coordinates within 5e-6, i.e. 6
      decimals; Uij within 1e-6 Å²) and read as the value derived from the
      first member;
    - anything else is an **error** whose message gives the values to write.

    The validated model holds the derived values, so every tie holds exactly
    and every engine starts from the same structure. How PowderLine reads
    some typical statements:

    | Stated | Symmetry | Validated model | Why |
    |---|---|---|---|
    | `x = 0.4999999` at (1/2, 0, 0) | x fixed = 1/2 | **error**: write `x = 0.5` | 1/2 has a decimal form: write it exactly |
    | `x, y = 0.333333, 0.666667` at (1/3, 2/3, 1/4) | fixed thirds | 1/3, 2/3 | a third has no decimal form; 6 decimals state it |
    | `x, y = 0.3333333333333, 0.6666666666667` | fixed thirds | 1/3, 2/3 | any precision beyond 6 decimals reads the same |
    | `x, y = 0.833333, 0.666667` at 6h (x, 2x, 1/4) | y = 2x − 1 | x = 0.833333, y = 0.666666 | x is free and kept; y follows it |
    | `x, y = 0.1, 0.2000001` at (x, 2x, 0) | y = 2x | x = 0.1, y = 0.2 | y follows x |
    | `x, y = 0.066667, 0.4` at (x, x + 1/3, 1/6) | y = x + 1/3 | x = 0.066667, y = 0.40000033… | y follows x, even where the stated y is a short decimal |
    | `U13 = 1e-9` at 6h | U13 fixed = 0 | **error**: write `U13 = 0.0` | 0 has a decimal form: write it exactly |
    | `U12 = 0.006174` with `U22 = 0.012347` at 6h | U12 = U22/2 | U12 = 0.0061735 | U12 follows U22 |
    | y bounds `[0.300004, 0.5]`, x bounds `[0, 0.2]` at (x, −x + 1/2, z) | y = −x + 1/2 | `[0.3, 0.5]` | bounds follow the first member's |

    Most crystallographic programs instead move any atom within a distance
    tolerance onto the special position (SHELXL 0.2 Å, cctbx 0.5 Å), and
    pymatgen reads `0.3333` as 1/3. PowderLine does not: a constant that can
    be written exactly must be, and `0.3333` is ambiguous.
  - **Multiplicity**: optional; when stated it must equal the multiplicity
    derived from the space group.
  - **ADPs**: `ADP` selects the thermal parameter that is **required**:
    `"Uiso"` requires `Uiso` (Å²); `"Uaniso"` requires `Uaniso` with all six of
    `U11 U22 U33 U12 U13 U23` (Å²). The other one must be left out. A missing
    or extra one is an error at that field (`atoms.<label>.Uiso`,
    `atoms.<label>.Uaniso.U23`), and the JSON Schema states the same rule.
    Anisotropic ADPs follow the site symmetry as described under
    *Symmetry-determined values*. A `Uaniso` that is not positive definite (a
    principal mean-square displacement ≤ 0, so no thermal ellipsoid exists) is
    **accepted with a structured warning** (`uaniso_not_positive_definite`,
    giving the principal values in Å² along Cartesian axes), like a negative
    `Uiso`: it can show that the parameter compensates for something the model
    lacks (e.g. absorption). Engines carry it as given.
  - **Refinement intent follows the symmetry.** Parameters tied by symmetry
    are **one** parameter, and every member is stated: cubic `a, b, c`;
    tetragonal/hexagonal `a, b`; rhombohedral axes (`:R`) `a, b, c` and
    `alpha, beta, gamma`; coordinates such as `(x, 2x, 1/4)` or
    `(x, x + 1/2, z)`; Uij such as `U11 = U22`, `U12 = U22/2`, `U13 = -U23`.
    - Tied members carry the **same refine flag**; the error is reported at
      every member whose flag differs from the first member's.
    - A parameter **fixed** by symmetry (a cubic angle, `x` of an atom at the
      origin, `U12` on a mirror site) has refine flag `false` and, where the
      engine has bounds, no bounds (`null`, `null`).
    - Different groups are independent (orthorhombic `a` refined, `b` fixed).
    - **Bounds** (engines with bounds) follow the tie like the values:
      `y = k·x + c` maps x's `[min, max]` to `[k·min + c, k·max + c]`
      (swapped for negative k; an open side stays open), e.g. `(x, x + 1/2, z)`
      with x in `[0, 0.2]` needs y in `[0.5, 0.7]`. They are derived values
      (see *Symmetry-determined values*): stated within 5e-6 for coordinates,
      1e-6 Å² for Uij and 1e-9 (relative) for the cell, and read as the mapped
      values; otherwise the error gives them.
    - Atoms at the same position are independent: their flags are never tied.

**Also in 0.1.0:** the unit-cell report's row vocabulary is fixed (an
output, not a recipe field); a building block sits behind the engines'
`scattering_types` — `element` stays the neutral atom; an ionic type is
engine content, and the error text for a charged `element` points at
`scattering_types`; and the `MarchDollase` building block (`model:
"march_dollase"`, `hkl` integers not all zero, `ratio > 0` in the engine's
parameter shape) sits behind the engines' `preferred_orientation`; it is not
a core `Phase` field (texture is a sample and engine matter, not a crystal
fact).

## gsasii engine schema

### 0.1.0 — introduced in PowderLine 0.2.0

Defined in `src/powderline/gateways/gsasii/schema.py` (engine-free), on core
0.1.0. Accepted versions are declared: engine schema `==0.1.0`, requiring
core `==0.1.0`. A 0.26.0 `GSASII_*` recipe is converted with
`scripts/convert_recipe_026.py`, which reports every change.

- **Workflows**: `gsasii.rietveld` (`phases`, no `single_peaks`) and
  `gsasii.spf` (`single_peaks`, no `phases`; `refinement_controls.single_peak_fitting_mode`
  required).
- **Parameters**: `[value, refine_flag]` only. GSAS-II applies parameter
  limits only after the fit, so gsasii 0.1.0 exposes no bounds; a 4-element
  list is an error.
- **Phase block**: core's `space_group`, `unit_cell`, `atoms`, plus `scale`
  (required, >= 0) and `peak_broadening` (isotropic size in µm and microstrain,
  each with `LG_eta`). The phase name is its key in `phases`.
  - Space group: GSAS-II cannot use origin choice 1 or 9 other settings (7 it
    does not read; `P 21 n m` and `A b a m` it reads as another setting), so
    they are errors.
  - Cell refinement: GSAS-II refines an oblique cell's parameters together
    (monoclinic {a, c, β} for b-unique, {b, c, α} a-unique, {a, b, γ}
    c-unique; all six for triclinic and rhombohedral axes). Refining part of
    such a group is an error.
  - **Size/strain left out**: 10 µm / 0 microstrain, isotropic, fixed, with a
    structured warning, instead of GSAS-II's own 1 µm / 1000 microstrain. A
    stated crystallite size must be > 0.
- **Instrument** (single source; GSAS-II's instrument parameters are built from
  it): `description` (optional), `radiation {type: "PXC", wavelength}`,
  `geometry {bank, azimuth}` (plain values), `corrections {zero_shift,
  polarization, axial_divergence}`, `broadening {U, V, W, X, Y, Z}`. GSAS-II
  units: U, V, W centideg²; X, Y, Z and zero centideg; SH/L dimensionless.
  SH/L below 0.002 is an error (GSAS-II computes with 0.002 anyway). The
  wavelength must be > 0. Kα doublets, TOF and neutron are not supported.
- **Background**: `chebyshev` (left out: one fixed term 0.0, no background,
  instead of GSAS-II's constant 1.0) and optional `single_peaks` (positions,
  intensities, `pv_gaussian_sigma_sq` in centideg², `pv_lorentzian_gamma` in
  centideg; all four lists the same length; each position inside the fit
  window). Values below GSAS-II's silent floors (intensity 0.1, σ² 0.01, γ 0.1)
  are errors. Peak List peaks (`gsasii.spf`): σ² and γ at least 0.001, each
  position inside the fit window.
- **Single peak fitting widths**: with `use_instrument_profile: true` the peak
  widths come from the instrument profile (U..Z may be refined; a peak's own
  σ²/γ may not); with `false` each peak has its own widths (they may be
  refined; U..Z may not). GSAS-II silently ignores a refine flag on the side
  not in use, so such a flag is an error.
- **Simulation** (`refinement_cycles` 1): every refine flag must be false.
- **Fit window** (re/05): GSAS-II gets the first and last weighted data
  points inside `fit_range` as its limits (an open end, or no `fit_range`: the
  data's first or last weighted point), so it fits exactly min ≤ 2θ ≤ max, the
  points every engine fits, and its Chebyshev basis spans the same points (with
  a limit between data points GSAS-II would also fit the next point above the
  maximum; with no limit it would start at a zero-weight edge point).
- **At run time**, after phase setup: an atom GSAS-II reads with the wrong
  multiplicity (some 2-fold sites in R32, R-3m, R-3c), or whose site it cannot
  name while a coordinate or Uaniso is refined, is an error naming an
  equivalent position to state instead.
- **Results**: `rwp`, `r_exp`, `gof`, `chi2_red` from PowderLine's uniform fit
  statistics over the stated fit window (`None` where undefined, e.g. no
  degrees of freedom); `simulation_mode` (a simulation gets the same
  statistics; against placeholder data they mean nothing); GSAS-II's own
  values, `parameters_requested`, `parameters_varied` and `converged`
  (Rietveld; GSAS-II keeps no such flag for a peak fit) under
  `engine_details`; structured `warnings` (defaults applied, GSAS-II's
  refinement messages, fewer parameters varied than requested, a Rietveld
  refinement that stopped before converging, values kept). A refinement
  that diverges (a non-finite calculated pattern) is a failure with a clear
  message; GSAS-II itself does not flag it.

#### The committed examples (PowderLine 0.2.0, re/07)

Every `examples/*/input.json` was converted in place with
`scripts/convert_recipe_026.py` (nothing hand-patched; the converter did not
stop on any example). What it changed, per example:

| Example | Converter notes |
|---|---|
| `example_LaB6`, `example_LaB6_simulation` | the background peak at 1.5° 2θ was removed **before** conversion (P-01: the data have no feature there and GSAS-II never determined it); `schema_version` → core/engine 0.1.0; `xrd_data.UID` → `metadata`; SH/L 0.0005 → 0.002 (A91); `unit_cell.volume` dropped (A75); size and strain broadening left out, so the documented default 10 µm / 0 microstrain applies with a structured warning (A87, A107) |
| `example_LaB6_singlepeakfit` | `GSASII_SPF` → `gsasii.spf`; `UID` → `metadata`; SH/L 0.0 → 0.002 (A91); background `pv_gaussian_sigma` → `pv_gaussian_sigma_sq` (A89) |
| `example_DRX_33`, `_anisoADP`, `_atomrefine`, `_simulation`, `_strainonly` | `UID` → `metadata`; SH/L 0.0005 → 0.002 (A91); one background peak with null entries dropped (D4); `unit_cell.volume` dropped (A75); `C2/m` → `C 1 2/m 1` (A105); the stated `Multiplicity: 1` of the seven Li4MgWO6_SG12 atoms dropped (derived 4/4/2/4/8/4/2; A101) |

The pre-conversion recipes are kept byte-identical in `tests/data/convert_026/`
as the converter's test fixtures (P-16, P-23); the 0.26.0 path itself is gone.

**Ionic scattering types and preferred orientation:** the phase block has
`scattering_types: {<atom label>: "<El n±>"}` (CIF spelling), optional, never
null; only ions GSAS-II 5.7.9 has a form factor for (114, pinned by a test);
written into the GSAS-II atom record in GSAS-II's own spelling (`La+3`,
ledger row R35). The converter maps a 0.26.0 `El±n` element onto it.
The phase block also has `preferred_orientation: {model:
"march_dollase", hkl, ratio: [r, flag]}`, optional, never null, `r > 0`;
written into the HAP `Pref.Ori.` entry (`['MD', r, flag, [h,k,l], …]`, ledger
rows R36/R37); the refined name `p:h:MD` maps back to `…preferred_orientation.ratio`.

## topas engine schema

### 0.1.0 — introduced in PowderLine 0.2.0

Defined in `src/powderline/gateways/topas/schema.py` (engine-free), on core
0.1.0. Accepted versions are declared: engine schema `==0.1.0`, requiring core
`==0.1.0`. Native recipes state TOPAS's own keywords, macro parameters and
units: the numbers in the recipe are the numbers in the INP. There is no
converter from 0.26.0 recipes (the 0.26.0 `GSASII_*` → TOPAS translation path
was removed with the unified schema).

- **Workflows**: `topas.rietveld` (`phases`) and `topas.spf` (`single_peaks`).
- **TOPAS version**: required `engine_version`, the TOPAS major version the
  recipe is written for; 0.1.0 supports `"6"` only (declared,
  `supported_engine_versions == "==6"`). A run needs the installed version
  declared (`topas_version` or `.powderline_config.yaml` `topas.version`) and
  equal to it; `tc.exe` carries no version PowderLine could read.
- **No defaults**: a block left out means the feature is not modelled; every
  value PowderLine would otherwise choose is a required field.
- **Parameters**: `[value, refine_flag, min, max]`. A stated bound replaces
  TOPAS's default limit on that side; `null` keeps TOPAS's default (keyword
  limits of the TOPAS Technical Reference, TOPAS.INC macro limits). A refined
  start outside a default limit on a `null` side is an error (TOPAS would move
  it silently).
- **Instrument**: `radiation` (one `lam` line: `ymin_on_ymax`, `la`, `lo` in Å,
  `lh` required, `lg` only with `lh`; `la`, `lo`, `lh`, `lg` > 0, since a line
  with no area, wavelength or width does not exist); `geometry` (`Rp`, `Rs` in mm, required
  exactly where an axial model reads them); `corrections` keyed by macro
  (`Zero_Error`, `LP_Factor` or `LP_Factor_Synchrotron`, `Simple_Axial_Model`
  or `Full_Axial_Model`, `capillary` with a `parallel` or `divergent` beam and
  a diameter > 0);
  `broadening` `{peak_type, parameters}` with `TCHZ_Peak_Type`, `PV_Peak_Type`
  or `PVII_Peak_Type` (TOPAS's TCHZ U..Z are not GSAS-II's; a **fixed**
  peak-type term is not checked, so fixed terms that make a width negative in
  the window, e.g. TCHZ X < 0 with Y = 0, validate, while TOPAS 6 stops on a
  negative FWHM: not yet verified for the peak types, documented only). Geometry
  corrections act on every peak, background and SPF peaks included;
  Lorentz-polarisation sits in each phase (Bragg peaks only); the peak type in
  each phase and each SPF peak.
- **Background**: `chebyshev` (TOPAS's basis over the fitted points),
  `One_on_X`, and `peaks` (`xo`, `I`, a `pv`/`spv`/`spvii` shape).
- **Phase block**: core's `space_group`, `unit_cell`, `atoms`, plus `scale`
  (> 0) and `peak_broadening` (`size_broadening` `CS_L`/`CS_G` in nm,
  `strain_broadening` `Strain_L`/`Strain_G`; these are not interpretable
  sizes or strains: LVol-IB and e0 are reported as TOPAS computes them). `Uiso`
  is written as `beq = 8π²·Uiso` (with a warning), `Uaniso` as `u11..u23`.
  Symmetry ties become one TOPAS parameter per tie group with exact equations.
- **Space groups**: the canonical name in TOPAS spelling; 541 settings
  accepted, 23 refused (20 TOPAS cannot name, 3 it reads as another setting).
- **Single peak fitting**: each peak is the instrument peak type convolved
  with its own `gauss_fwhm` / `lor_fwhm` (≥ 0).
- **Refinement controls** (required): `iters` (0 = simulation, every refine
  flag false), `chi2_convergence_criteria`, `x_calculation_step`.
- **Fit window**: TOPAS gets the first and last weighted data points inside
  `fit_range` as its limits (open ends: the data's first or last weighted
  point), so it fits exactly min ≤ 2θ ≤ max (the same points every engine
  fits); a window with no weighted point is an error. Numbers are written to
  the INP to 10 significant digits (`%.10g`), as in the `.xye`.
- **Results**: `rwp`, `r_exp`, `gof`, `chi2_red` from PowderLine's uniform fit
  statistics over the stated window (equal to TOPAS's own); TOPAS's values,
  `parameters_requested` and `parameters_varied` under `engine_details`. The
  background column comes from a second, background-only TOPAS run at the
  refined values (TOPAS 6 cannot output the background of the fit). Warnings:
  `topas_adp_converted`, `topas_parameter_at_limit` (naming the stated bound
  or TOPAS's default), `topas_parameters_not_varied`,
  `topas_phase_contributes_nothing` (informative: a phase absent from the
  sample legitimately contributes nothing), `topas_background_not_calculated`.
  Success is judged from the output files the INP asks for, removed before
  the run (TOPAS 6's exit code says nothing; timestamps are not used); any
  non-finite number in them (`nan`, `1.#QNAN`, `-nan(ind)`, …) is a divergence
  error, while an undetermined ESD is left empty.

**Ionic scattering types and preferred orientation:**
`scattering_types` and `preferred_orientation` are declared and **refused**
in 0.1.0 (the TOPAS halves — `occ Fe+3` and ATMSCAT's coverage, T7; the
`PO(...)` macro, T9 — await a TOPAS 6 run; P-08).

## easydiffraction engine schema

### 0.1.0 — introduced in PowderLine 0.2.0

Defined in `src/powderline/gateways/easydiffraction/schema.py` (engine-free),
on core 0.1.0. Accepted versions are declared: engine schema `==0.1.0`,
requiring core `==0.1.0`. Native recipes use easydiffraction's own names and
units (`setup_wavelength`, `calib_twotheta_offset`, `broad_gauss_u` in deg², …).
There is no converter from 0.26.0 recipes (the 0.26.0 `GSASII_*` →
easydiffraction translation path was removed with the unified schema).

- **Workflow**: `easydiffraction.rietveld` (`phases`); no single peak fitting.
- **easydiffraction version**: pinned (`==0.21.1`) and read at run time; a
  recipe states none.
- **No defaults**: a block left out means the feature is not modelled; every
  value PowderLine would otherwise choose is a required field.
- **Parameters**: `[value, refine_flag, min, max]`. A stated bound replaces
  easydiffraction's physical limit on that side; `null` keeps it (cell lengths
  0–30 Å, angles 0–180°, occupancy 0–1, Uiso and U11/U22/U33 0–10 Å², scale,
  wavelength and μR ≥ 0). A value outside a physical limit is an error, even
  when fixed (easydiffraction refuses it); a cell length over 30 Å cannot be
  modelled.
- **Instrument**: `radiation` (`setup_wavelength` > 0; a Kα2 line
  `setup_wavelength_2` + `setup_wavelength_2_to_1_ratio` stated together);
  `polarization` (`setup_polarization_coefficient` p, `setup_monochromator_twotheta`;
  GSAS-II's P is 1 − p); `corrections` (`calib_twotheta_offset`, and optionally
  `calib_sample_displacement`, `calib_sample_transparency`); `absorption`
  (`cylinder-hewat`, `mu_r`); `broadening` `{peak_type, parameters}` with
  `cwl-pseudo-voigt` (both calculators), `cwl-pseudo-voigt-berar-baldinozzi-asymmetry`
  (CrysPy) or `cwl-thompson-cox-hastings` (CrysFML, FCJ `asym_fcj_1/2`), and
  `cutoff_fwhm` (CrysPy only). Gaussian FWHM² = U tan²θ + V tanθ + W (deg²),
  Lorentzian FWHM = X tanθ + Y/cosθ (deg; GSAS-II's X and Y swap roles). A stated
  profile that makes either width negative within 1° of the fit window (widened
  by the size of the stated zero, displacement and transparency corrections) is
  an error: easydiffraction computes reflections just outside the window too,
  and would compute a wrong pattern without a message.
- **Background**: `chebyshev`, over the fit window's first and last points.
- **Phase block**: core's `space_group`, `unit_cell`, `atoms` (`Uiso` and
  `Uaniso` in Å², used as given), plus `scale` (≥ 0: a phase may contribute
  nothing). Symmetry ties become one easydiffraction parameter per tie group,
  the one easydiffraction leaves free.
- **Space groups**: the canonical name maps to one of easydiffraction's 230
  short names plus a setting code (531 settings); each calculator accepts only
  the settings it was verified to compute, for a general position and for every
  special Wyckoff site (CrysPy 428, CrysFML 230; CrysPy computes
  special positions wrongly in nine origin-choice-1 settings, which are refused
  for it; the error names one it computes, or the other calculator).
- **Calculator-specific rules**: `Uaniso` needs CrysPy (CrysFML is handed only
  B = 8π²·Ueq). With CrysPy, an atom on a special position with a free
  coordinate must be written in the pattern of easydiffraction's Wyckoff
  template for its site (CrysPy computes wrong intensities for other equivalent
  writings); the run refuses it before calculating and names the position to
  write. A position easydiffraction stores in another writing of the same site
  (a lattice translation, e.g. (0.137, 0.863, z) on (x, −x, z) held as
  (0.137, −0.137, z)) is accepted with the warning
  `easydiffraction_position_translated`; bounds and reports stay in the recipe's
  writing. CrysFML computes in single precision, below lmfit's finite-difference
  step, so a CrysFML refinement can depend on its starting values: every CrysFML
  refinement carries the warning `easydiffraction_crysfml_start_dependent`.
- **Refinement controls** (required): `calculator` (`cryspy` | `crysfml`),
  `minimizer` (`lmfit (leastsq)`), `max_iterations` (lmfit's maximum number of
  function evaluations), `chi_square_change_tolerance`,
  `parameter_change_tolerance`, `gradient_tolerance`. No refine flag set = a
  simulation (the pattern is calculated, lmfit is not run).
- **Fit window and data**: easydiffraction gets exactly the weighted points
  with min ≤ 2θ ≤ max (open ends: the data's first or last weighted point), as
  a CIF data loop at full precision; a weight above 1e8 (σ < 1e-4) on one of
  them is an error (easydiffraction would replace σ by 1.0 without saying so),
  and so is a negative intensity on one of them (easydiffraction refuses it).
- **Results**: `rwp`, `r_exp`, `gof`, `chi2_red` from PowderLine's uniform fit
  statistics over the window (Rwp equal to easydiffraction's); its values,
  calculator, peak type, `parameters_requested` and `parameters_varied`
  (lmfit's count) under `engine_details`. The background column is
  easydiffraction's own. CrysFML reports no reflection list, so no peak lists
  are written with it. Warnings: `easydiffraction_parameters_not_varied`,
  `easydiffraction_parameter_at_limit` (a value within 1e-6 relative of a stated bound
  or physical limit; for a limit of 0, within 1e-6 of the parameter's starting
  value), `easydiffraction_phase_contributes_nothing`
  (informative), `easydiffraction_fit_not_converged` (the values are reported),
  `easydiffraction_negative_width` (the refined profile makes a width negative
  within the checked range), `easydiffraction_reflections_not_available`
  (CrysFML), `easydiffraction_position_translated`,
  `easydiffraction_crysfml_start_dependent`. Any non-finite calculated value,
  refined value or reflection-list value is a divergence error.

**Ionic scattering types and preferred orientation:** the phase block has
`scattering_types` (CIF spelling), cryspy calculator only (CrysFML strips
charges, EB-96) and only ions CrysPy has a form factor for (111, pinned by a
test; CrysPy's silent neutral fallback for the others is EB-95), and
`preferred_orientation` — the `MarchDollase` block with a
bounded `ratio` (> 0) plus the required `march_random_fract` ([0, 1]) —
written as a `preferred_orientation` row of the experiment (keyed by the
lowercase linked structure name, EB-97); cryspy calculator only (CrysFML
ignores the row without a message, EB-97); CrysPy's March correction is
Dollase's times r^1.5 (EB-98), so with `march_random_fract = 0` the refined
`r` is the same quantity (with f > 0 it is not).

---

## Archive: unified-schema era (0.21–0.26)

The single schema shared by all engines up to PowderLine 0.1.1, kept verbatim
(headings moved one level down). Nothing below is current policy: the current
core and engine schema models (0.1.0) are `extra='forbid'`, parameters are
engine-shaped lists, and the sequential and multi-strategy text describes
removed code.

This document provides a concise summary of PowderLine's schema evolution for context. For detailed commit history, see the repository's git log. Current schema: **0.26.0**

---

### Schema 0.26.0: Per-Parameter Refinement Flags Honored (Current)

**Status**: Active (Q3 2026)

**Key Changes**:
- **Per-parameter refine flags are now honored** *(behavioral change, no shape change)* for the
  three parameter classes GSAS-II exposes only as lumped flags:
  - **Unit-cell parameters** (`a, b, c, alpha, beta, gamma`) — previously ANY true flag refined
    the whole symmetry-allowed cell; false flags on other cell parameters were silently ignored.
  - **Atomic coordinates** (`x, y, z`) — previously any true flag refined all three together.
  - **Anisotropic displacement components** (`U11..U23`) — previously any true flag refined all
    symmetry-allowed components together.
  A parameter now refines iff it is present with `refine_flag=true`; **absent or false means
  fixed**. Internally, PowderLine emits GSAS-II "Hold" constraints for the not-refined degrees
  of freedom (new module `powderline.constraints`).
- **Symmetry-linked parameters refine together (group-OR)**: parameters coupled by the phase's
  Laue class or site symmetry (e.g. cubic `a=b=c`; monoclinic `a`/`c`/`beta`; `x=y` on an
  `(x,x,z)` site) form one degree-of-freedom group that refines if any member is requested.
  Flags on symmetry-fixed parameters (e.g. cubic angles) have no effect. PowderLine does not
  validate flag/symmetry consistency — producing consistent flags is the recipe author's (or an
  upstream recipe builder's) responsibility (see KI-01/KI-02 in
  `docs/known_issues.md`).
- **Partial parameterization is equivalent to explicit flags**: listing only the parameters you
  wish to refine (absence = fixed) is equivalent to listing all with explicit true/false flags.
  Shipped examples use the explicit style for clarity.
- **Fix**: a phase `parameterization` that omits the `peak_broadening` section no longer raises
  (`set_phase_parameterization` previously called `.get` on the `None` that `model_dump` emits
  for an absent section); minimal recipes now run.

**Rationale**:
- The recipe is the point of truth: a `refine_flag: false` that is silently overridden (e.g.
  a hexagonal example's `c` refined despite `c: false` in schema 0.25) misrepresents what the
  refinement actually did. Schema 0.26 makes the flags mean what they say.

**Migration**: Update `"schema_version"` from `"0.25.4"` to `"0.26.0"` in all recipe JSON files,
then **review your refine flags**: any parameter previously piggy-backing on a lumped flag (e.g.
cubic `b`, `c` marked false next to `a: true`, or `y`/`z` false next to `x: true`) is now
genuinely held. Set every parameter you want refined to `true` explicitly (symmetry-linked
partners refine together regardless, but explicit flags keep the recipe honest).

**Breaking Changes**:
- No changes to recipe format.
- **Refinement behavior changes** for recipes whose per-parameter flags disagree within a
  symmetry-linked group or across a formerly-lumped class: previously-ignored false flags are
  now honored, so fewer parameters may vary than before.

**`xrd_data` validation hardening** *(within 0.26.0 — no version bump)*: `XRDDataModel` now
**rejects** ill-formed data instead of passing it through to GSAS-II. It requires: non-empty,
equal-length arrays; all-finite `tth`/`Itth`/`Itth_weights` (no NaN/inf — catches, e.g., a
weight of `1/esd²` with `esd=0`); strictly increasing `tth`; and weights `>= 0` with at least
one `> 0`. Negative **intensities** remain valid (background-subtracted data legitimately dips
below zero — `Itth` is checked for finiteness only, not sign). This is a validation tightening,
not a shape or `kicker.py` output change, so the version is unchanged and previously-valid
recipes are unaffected (the empty-array `example_template` skeleton is intentionally not a
runnable recipe). Rationale: PowderLine is strict and never repairs `xrd_data`; transforming
raw data (unit conversion, weight derivation, negative-intensity handling) is the job of the
file reader/parser that builds the block.

---

### Schema 0.25.4: Consistent Failure Metadata

**Status**: Superseded by 0.26.0

**Key Changes**:
- **Consistent `traceback` in all `run_refinement()` failure exits** *(behavioral change)*: failure
  exits 1 and 3 (histogram loading error, executor exception) now capture and return the Python
  traceback string under a `'traceback'` key. Exit 2 (executor returned `success=False`) forwards
  the executor's traceback if present, or `None`. Previously only the outermost unexpected-exception
  exit (exit 4) included a traceback.
- **`run()` normalizes `traceback` key**: `run()` now calls `result.setdefault('traceback', None)` so
  callers can always key into `result['traceback']` without a `KeyError`, regardless of which failure
  exit triggered.

**Rationale**:
- Consistent `traceback` across all failure exits simplifies debugging without requiring
  callers to handle multiple return shapes

**Migration**: Update `"schema_version"` from `"0.25.3"` to `"0.25.4"` in all recipe JSON files.
No other recipe changes required.

**Breaking Changes**:
- No changes to recipe format

---

### Schema 0.25.3: Refinement Failure Detection and Windows Support

**Status**: Superseded by 0.25.4

**Key Changes**:
- **Robust refinement failure detection** *(behavioral change)*: `execute_rietveld_refinement` and `execute_spf_refinement` now return `success=False` when the refinement produces no Rwp (convergence failure), instead of silently returning `success=True`. All `success=False` paths in `run_refinement()` now consistently include `'rwp': None` and forward the executor's error message rather than a generic fallback string.
- **Windows (win-64) platform support**: `pixi.toml` now targets both `linux-64` and `win-64`. Includes `flang`/`flang-rt_win-64` Fortran toolchain, an `ar.exe` wrapper (`scripts/ar_wrapper.c`) for MSVC archive compatibility, `scripts/win_activate.bat`. Shell scripts enforce LF line endings via `.gitattributes`.

**Rationale**:
- A refinement that produces no Rwp has not converged; returning `success=True` was misleading and caused silent data quality issues downstream
- Windows support is required for deployment on user workstations at partner institutions

**Migration**: Update `"schema_version"` from `"0.25.2"` to `"0.25.3"` in all recipe JSON files. No other recipe changes required.

**Breaking Changes**:
- No changes to recipe format
- Code that expected `success=True` when a refinement produced no Rwp must now handle `success=False`

---

### Schema 0.25.2: Programmatic Python API

**Status**: Superseded by 0.25.3

**Key Changes**:
- **`powderline.run()`**: Primary programmatic entry point. Accepts `dict | RecipeModel`, `output_dir: Path`, and `execution_mode` parameter (`'auto'` | `'server'` | `'subprocess'`). Eliminates the need for callers to manage raw JSON primitives or re-read output files.
- **`powderline.validate()`**: Standalone schema validation without GSAS-II execution. Returns a `RecipeModel` or raises `pydantic.ValidationError`. Enables fast CI-friendly recipe linting.
- **`run_id`**: UUID4 attached to every execution path. Enables log correlation and result tracing across concurrent or sequential runs. Not present when `validate_only=True`.
- **Structured DataFrame returns**: `run()` returns `pd.DataFrame` objects for all tabular outputs (`fit_profile`, `unit_cell_data`, `peak_list_data`, `refined_parameters`, `spf_peaks`, `spf_convergence_diagnostics`). Callers never receive raw dicts or lists. This eliminates column-index bugs that arose when callers parsed the 15-column reflection list by position.
- **DataFrame normalization boundary**: `run_refinement()` continues to return JSON-serializable primitives (required for HTTP transport). `run()` converts them to DataFrames at the public API boundary — keeping the server/client architecture intact.
- **`GSASClient` input polymorphism**: `submit_simulation()` now accepts `Path | dict | RecipeModel`. Previously only `Path` was accepted, requiring callers to serialize models back to disk before submitting.
- **`GSASClient` auto-start + retry**: Automatic server start on first call; 3-attempt exponential backoff (0.5 s → 1.0 s → 2.0 s) on `ConnectError` only. HTTP 4xx/5xx and timeout errors are not retried.
- **`SimulationResponse` (HTTP)**: FastAPI response model now carries all structured data fields (`fit_profile`, `unit_cell_data`, `peak_list_data`, `refined_parameters`, `spf_peaks`, `spf_convergence_diagnostics`), enabling rich API consumers without a separate file-read step.
- **`run(validate_only=True)`**: Fast validation path returns a slim summary dict (`success`, `schema_name`, `schema_version`, `phases`, `refinement_cycles`, `simulation_mode`) with no `run_id` and no GSAS-II invocation.

**Rationale**:
- Direct `run_refinement()` calls required callers to reconstruct results from files or parse raw primitive dicts; `run()` removes this boilerplate at the correct abstraction level
- Standalone `validate()` makes recipe linting a one-liner in CI pipelines without importing GSAS-II
- `run_id` makes it possible to correlate results, logs, and output files from batch or concurrent runs without relying on timestamps or output-directory names
- Returning DataFrames (not raw dicts) at the public API boundary is the correct place for this transformation: it keeps HTTP serialization clean while giving programmatic callers the right type immediately
- Polymorphic `GSASClient` input removes the most common adoption friction: having to write a `RecipeModel` to a file before calling `submit_simulation()`
- Auto-start + retry makes server mode transparent for new users and removes the need to manually manage server lifecycle in scripts

**Migration**: Update `"schema_version"` from `"0.25.1"` to `"0.25.2"` in all recipe JSON files. No other recipe changes required.

**Breaking Changes**:
- No changes to recipe format
- `run()` callers using the `method=` keyword argument must rename it to `execution_mode=`
- `GSASClient.submit_simulation()` callers passing `recipe` as a positional `Path` continue to work unchanged; passing as `dict` or `RecipeModel` is now also valid

**What NOT to do**:
- Do not add DataFrame conversion inside `run_refinement()` — it must remain JSON-serializable for HTTP transport
- Do not bypass `run()` for new programmatic callers; `run_refinement()` is an internal execution engine, not a public API
- Do not add retry logic for HTTP 4xx/5xx errors — these indicate recipe or server bugs that should surface immediately

---

### Schema 0.25.1: Refined Parameters Export + Extended SPF Returns

**Status**: Superseded by 0.25.2

**Key Changes**:
- **New output**: `refined_parameters.csv` with 9 columns including phase/atom associations and ESDs
- **Updated unit cell reports**: Now include `esd` column (3 total columns instead of 2)
- **Per-column float formatting**: Values use `%.6e`, ESDs use `%.8e` for appropriate precision
- **SPF DataFrames**: `powderline.run()` now returns `spf_peaks` and `spf_convergence_diagnostics` as pandas DataFrames; previously only written to files
- **Schema validator**: `GSASII_SPF` schema now validates `payload.refinement_controls.single_peak_fitting_mode` at parse time, not at runtime
- **`run_refinement()` signature**: `recipe_path` parameter removed (was accepted but never used); `method` default changed from `'direct'` to `'server'`
- **`SimulationResponse`**: Added `spf_peaks` and `spf_convergence_diagnostics` optional fields to FastAPI response model

**Rationale**:
- Comprehensive ESD reporting enables uncertainty quantification for all refined parameters
- Machine-readable CSV format enables automated downstream analysis
- Per-column formatting preserves significant figures for small ESDs while keeping values concise
- SPF DataFrame return makes single-peak-fitting results immediately usable programmatically without re-reading output files
- Schema-level SPF validation gives earlier and clearer error messages

**Migration**: Update `"schema_version"` from `"0.25"` to `"0.25.1"` in all recipe JSON files. No other recipe changes required.

**Breaking Changes**:
- `run_refinement()` callers that passed `recipe_path=` keyword argument must remove it
- `run_refinement()` callers that relied on `method='direct'` default must pass it explicitly (new default: `method='server'`)

---

### Schema 0.25: Simplification

**Status**: Superseded by 0.25.1

**Key Changes**:
- **Payload-based structure**: All recipe fields moved under `"payload"` key
- **Fixed output filenames**: `dummy.gpx`, `dummy.lst`, `<phase>_unit_cell_report.csv` (independent of sample names)
- **Removed metadata fields**: `sample_name`, `recipe_description` (manage externally)
- **Schema identification**: Required `"schema_name"` field (`"GSASII_Rietveld"` or `"GSASII_SPF"`)
- **Permanent removal of multi-strategy system**: Sequential and iterative refinement workflows removed (not planned for future development)
- **Peak broadening model field**: Added `"model"` field to support future extensibility (uniaxial, ellipsoidal)
- **Size/strain renaming**: `"size"` → `"isotropic_size"`, `"strain"` → `"isotropic_strain"`

**Rationale**:
- Payload structure separates schema metadata from recipe content
- Fixed filenames eliminate variability in testing/automation
- Multi-strategy refinement didn't work as intended; workflows now split into two schema_name options
- Sample identity belongs in external metadata (directory names, databases)

**Migration**: For recipes from schema 0.24 or earlier:
1. Add `"schema_name"` field (`"GSASII_Rietveld"` or `"GSASII_SPF"`)
2. Wrap all recipe fields in `"payload"` object
3. Remove `"sample_name"` and `"recipe_description"` fields
4. Update strategy field: remove `"strategy"` from `refinement_controls`, use `schema_name` instead

---

### Schema 0.24: Multi-Strategy Refinement System

**Status**: Deprecated (replaced by schema 0.25)

**Key Features**:
- Four refinement strategies: `peaks_only`, `structural_only`, `sequential`, `iterative`
- Single peak fitting (SPF) integrated with structural refinement
- Advanced convergence diagnostics with aphysical parameter detection
- Optional trajectory/comparison outputs

**Why Removed**: Multi-strategy system proved complex with limited benefit. Schema 0.25 simplified to two workflow types selected by `schema_name` field.

**Breaking Changes**:
- Required `refinement_controls` with `strategy` field
- Moved `refinement_cycles` from top-level to `refinement_controls`
- Renamed Gaussian parameter: `pv_gaussian_sigma` → `pv_gaussian_sigma_sq`
- Moved `use_instrument_profile` into `single_peak_fitting_mode` block

---

### Schema 0.23: Initial Multi-Strategy Exploration

**Status**: Deprecated

**Key Features**:
- Introduced basic strategy concept (peaks vs structural)
- Optional `refinement_controls` block
- Initial single peak fitting integration

**Notes**: Experimental implementation that led to full multi-strategy system in 0.24

---

### Schema 0.22: ADP Field Requirements

**Status**: Deprecated

**Key Change**: Made `ADP` (Atomic Displacement Parameter) field required in both structure and parameterization sections for all atoms.

**Rationale**: Eliminated ambiguity about which displacement parameters were active. Previously optional with complex fallback logic.

**Breaking Change**: Validation fails if `ADP` missing from atom definitions. No default value provided.

**Feature**: Structure and parameterization `ADP` values can differ (e.g., CIF provides `Uaniso`, but refinement uses `Uiso`).

---

### Schema 0.21 and Earlier

**Status**: Historical

Early development versions focused on basic Rietveld refinement capabilities:
- JSON recipe structure establishment
- GSAS-II G2scripts API integration
- Basic parameter setting/refinement
- CIF-based structure loading
- Single-phase refinements

---

### Origin (Schema 0.21–0.24)

PowderLine began as a minimal proof-of-concept to confirm that GSAS-II could be driven
from a JSON file via the G2scripts API. The initial scope established the directory
structure and documentation, a JSON schema derived from 3–5 real examples, JSON loading
and schema validation in `kicker.py`, output written to a directory, at least three
refinement types working end-to-end, and basic tests covering JSON loading and validation.

Features deferred from that initial scope (REST API, structured output parsing,
configuration system, programmatic Python API) were subsequently delivered in schema
0.25.1 and 0.25.2.

---

### Schema Design Philosophy

**Example-Driven Development**: Features are added when real refinement examples need them, not speculatively. Schema evolution is guided by committed examples in `examples/` directory.

**Schema-First Validation**: Pydantic models provide clear error messages before GSAS-II operations. Fail fast with helpful diagnostics.

**Progressive Enhancement**: Uses `ConfigDict(extra='allow')` to permit field additions without breaking existing recipes.

**Separation of Concerns**: Recipe JSON contains only refinement parameters. Sample identity, descriptions, and documentation live in external files (directory names, `DESCRIPTION.md`, databases).

---

### Migration Philosophy

- **Explicit schema versions**: Every recipe declares its `"schema_version"`. The code
  accepts one current version — **0.26.0** — and recipes written for older versions must
  be migrated to it following the per-version notes above.
- **Clean breaks with migration guidance**: Obsolete features are clearly deprecated, and
  each version entry documents the migration steps rather than maintaining indefinite
  compatibility shims.
- **Git history is source of truth**: This document provides high-level context only.
