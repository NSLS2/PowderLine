# Input guidance: data, structures, instruments

How to fill the three parts of a recipe that need the most care, and what
PowderLine will not do for you. The field-by-field tables are on the
[fields page](fields.md); the rules are summarized here with the reason
behind each. Validate early and often: `powderline <recipe> --validate-only`
needs no engine, lists **every** problem with its field path, and prints the
structured warnings (defaults applied, symmetry remarks).

## Building a recipe

PowderLine has no built-in recipe builder ([why](#structures-the-phase-block)),
so a recipe is written by you or by your own tooling. The usual path:

1. **Choose the engine, then start from an example or a template.** A recipe
   is written in one engine's terms and is never translated, so the engine
   comes first ([Recipe schemas](schemas.md)). Copy the example closest to
   your case (`examples/<case>/input.json` for GSAS-II and, where the case
   has them, `examples/<case>/topas/` and `examples/<case>/easydiffraction/`
   for the other engines; each case has a `DESCRIPTION.md`), or the
   engine's skeleton in `examples/example_template/` (`input.json` for
   `gsasii.rietveld`, `topas/input.json`, `easydiffraction/input.json`).
   A single-peak fit
   starts from `examples/example_LaB6_singlepeakfit/`. Copy into a directory
   of your own: the CLI refuses to run any recipe whose path contains
   `template`.
2. **Put in your data.** Your reader fills `xrd_data` with 2θ in degrees,
   the intensities and the weights 1/σ², and you choose the fit window
   ([Diffraction data](#diffraction-data-xrd_data)). PowderLine never
   repairs data.
3. **Take the structure from a CIF with your own tooling** (a CIF reader, a
   script, a notebook) and write the phase block: the space group as
   gemmi's canonical name, which states the setting
   ([Space group](#space-group-one-canonical-spelling)); all six cell values
   ([Unit cell](#unit-cell)); for each atom the neutral `element`,
   fractional coordinates, `occupancy`, and `Uiso` or all six `Uij` in Å²
   (a CIF's `B` is 8π²U); ions in `scattering_types`
   ([Atoms](#atoms)). Check special positions in particular: `0.3333` in a
   CIF is an error here; write `0.333333` (1/3 to six decimals) or the
   exact decimal.
4. **State every tie-group member, with the same flag.** A cubic cell
   states `a`, `b`, `c` and all three angles; an atom on `(x, x, x)`
   states x, y and z; a value fixed by symmetry has flag `false` and, where
   the engine has bounds, no bounds
   ([Refine flags and the symmetry](#refine-flags-and-the-symmetry)).
5. **State the instrument from a calibrant.** Refine a standard measured
   with the same wavelength and geometry (LaB6, Si, CeO2) **with the same
   engine**, as `examples/example_LaB6` does for GSAS-II, then copy the
   refined values from its `output_recipe.json` (`payload.instrument`) into
   your recipe with their flags `false`. The instrument block is the
   engine's own, in the engine's units, so it is copied within one engine
   only; for another engine it is converted by hand
   ([Instruments](#instruments-one-block-per-engine)).
6. **Choose what to refine and the controls**
   ([Background and controls](#background-and-controls)). In `gsasii.*` a
   few blocks have documented defaults (size/strain 10 µm / 0, no
   background, 5 cycles), each applied with a warning; in `topas.*` and
   `easydiffraction.*` nothing has a default and a block left out is not
   modelled.
7. **Validate, fix, repeat.** Run

   ```bash
   pixi run kicker my_recipe.json --validate-only
   ```

   in any environment, including the core-only default one. Every problem
   is listed with its field path, and most messages name the value to
   write (`stated b = 4.2, but by symmetry b = a; write b = 4.15682`);
   unknown keys are errors (`radiaton: Extra inputs are not permitted`).
   Fix them all and re-run until the recipe validates.
8. **Read the warnings.** A valid recipe can still carry structured
   warnings `{code, message, field_path[, level]}`, printed by
   `--validate-only` and returned by `powderline.validate(recipe).warnings`.
   Level `warning` means a default was applied or something deserves a look
   (`gsasii_broadening_default_applied`: state `peak_broadening` to choose);
   level `info` is a remark, such as `symmetry_value_derived` (a value is
   held in its exact symmetry-derived form). Passing validation means the
   recipe is well formed and consistent with its space group, not that it
   is the model you intended.
9. **Run it** in the engine's environment (the table in
   [Recipe schemas](schemas.md#the-five-schemas)).

## Diffraction data (`xrd_data`)

A recipe carries its pattern inline, as three equal-length arrays:

| Key | Meaning | Unit |
|---|---|---|
| `tth` | 2θ of each point, strictly increasing | degrees 2θ |
| `Itth` | measured intensity | arbitrary (counts, normalized, …) |
| `Itth_weights` | the least-squares weight of each point, **1/σ²** | 1/intensity² |
| `filename` | optional free text (the file the arrays came from) | — |

**PowderLine never repairs data**; it only accepts or rejects. Converting
units, deriving weights from counts, sorting, de-duplicating, trimming and
handling background-subtracted negatives are the job of the reader that
builds the block. Validation rejects: empty arrays, unequal lengths, any
non-finite value (a weight computed as 1/0² is `inf`), a `tth` that is not
strictly increasing, a negative weight, and all-zero weights.

- **A weight of 0 excludes a point** in every engine: it is handed to the
  engine with zero weight (GSAS-II), dropped from the `.xye` (TOPAS) or not
  handed over at all (easydiffraction), and it is never counted in the
  uniform statistics. Use it to mask a detector gap or an impurity peak; do
  not delete the points.
- **Negative intensities** are allowed by core (background-subtracted data
  dip below zero), but easydiffraction refuses them, so an
  `easydiffraction.*` recipe is rejected when a negative point would be handed
  to the engine (give it weight 0 or shift the data).
- **Very large weights** (above 1e8, i.e. σ < 1e-4) are rejected for
  `easydiffraction.*`, because easydiffraction silently replaces such a σ by
  1.0; rescale the intensities and weights together.

### The fit window (`fit_range`)

`[min, max]` in degrees 2θ, either end `null` (open). Both ends must lie
inside the data's 2θ span, `max > min`, and the window must contain at least
**two** points with a positive weight. Every engine fits **exactly** the data points
with min ≤ 2θ ≤ max and positive weight: PowderLine hands each engine its
limits moved onto the first and last such points, so GSAS-II, TOPAS and
easydiffraction score the same points, the uniform statistics use the same
N, and each engine's Chebyshev basis spans the same first and last points.
Left out, the window is the data's first to last weighted point. Background
peaks and single peaks must sit inside the window.

## Structures (the phase block)

A phase is one block, keyed by its name in `payload.phases`, holding
`space_group`, `unit_cell`, `atoms` and the engine's own phase fields
(`scale`, and for gsasii/topas `peak_broadening`). There is no separate
"structure" and "parameterization": every structural quantity (cell `a`–`γ`,
each atom's `x`, `y`, `z`, `occupancy`, `Uiso` or `U11`…`U23`) is a parameter
`[value, flag]` (or `[value, flag, min, max]`). The block is identical in every
engine schema, so a structure can be pasted from a `gsasii.*` recipe into a
`topas.*` or `easydiffraction.*` one, adding the two bound slots.

Two optional engine fields sit beside the structure and are **not** part of
it: `scattering_types` (an ion's form factor per atom label, CIF spelling,
`{"La": "La3+"}`; `element` stays the neutral atom) and `preferred_orientation`
(March–Dollase: `{"model": "march_dollase", "hkl": [0, 0, 1], "ratio": [0.8,
true]}`; `hkl` integers not all zero, `ratio` > 0 in the engine's parameter
shape; 1 is random, < 1 platy, > 1 needle, in GSAS-II's convention averaged
over the axis's symmetry equivalents). easydiffraction's block also requires
`march_random_fract` (`[f, flag, min, max]`, 0 ≤ f ≤ 1) and needs the cryspy
calculator; topas 0.1.0 refuses both fields (their TOPAS halves await a TOPAS
machine). Start `ratio` on the expected side of 1, not at exactly 1.0: in a cubic phase
the averaged correction is stationary at r = 1 and GSAS-II aborts the
refinement (EB-99, `example_LaB6_textured`).

PowderLine reads **formatted dictionaries, not CIF files**: there is no CIF
parser and no recipe builder in the package. Whatever produces the block
(a script, a notebook, a database export) owns the conversion; PowderLine
checks the result against the space group and refuses anything ambiguous.

This is deliberate. Recipes are built in many ways: from a GUI, from a
script, through an interface to a structure database, or with an LLM
assistant. A built-in builder would make choices that restrict all the
others: defaults, file formats, which parameters to refine first. A CIF
reader in particular would have to guess where the CIF is ambiguous: a
space-group symbol without its origin choice or axes, coordinates rounded
to four decimals on a special position (`0.3333`). Guessing silently is
exactly what validation refuses. So PowderLine defines the recipe format
precisely, checks it strictly, and leaves the conversion to the tool that
knows where its data came from.
[Building a recipe](#building-a-recipe) is the workflow.

### Space group: one canonical spelling

`space_group` must be gemmi's canonical extended Hermann–Mauguin name,
exactly: `"P m -3 m"`, `"C 1 2/m 1"`, `"P 1 21/c 1"`, `"R -3 m:H"`,
`"F d -3 m:2"`. The spelling states the **setting**: `:1`/`:2` for the 24
two-origin groups, `:H`/`:R` for rhombohedral groups, the full symbol for the
monoclinic unique axis and cell choice. Any other spelling is an error whose
message gives the canonical name; a bare `"R -3 m"` or `"F d -3 m"` lists
both settings; a short monoclinic symbol (`"C2/m"`) lists every setting of
that group by unique axis, because it states neither the axis nor the cell
choice.

Why so strict: a lenient lookup picks defaults silently (`"Fd-3m"` → origin
1 in one program, origin 2 in another; `"R-3m"` → hexagonal axes), and the
coordinates differ between settings, so a recipe that did not state the
setting could run on a different structure in different engines. The 564
accepted names are those of the pinned gemmi (`tests/data/canonical_space_groups.txt`).

Each engine then translates the canonical name into its own form and
**refuses the settings it cannot express**: GSAS-II origin choice 1 and 9
other settings; TOPAS 6 23 settings; easydiffraction's calculators the
settings each was verified to compute (the error names a setting of the same
group that works, or the other calculator). The per-engine lists are on the
[engine behaviour page](engine-behavior.md#space-group-spellings-and-settings-per-engine).
To use a refused setting, transform the structure to a standard setting.

### Unit cell

`a`, `b`, `c` in Å (> 0) and `alpha`, `beta`, `gamma` in degrees (strictly
between 0 and 180), **all six stated** in every space group. The cell must
fit the group: tied lengths and angles equal the first member (cubic
`b = a`, `c = a`), fixed angles are exactly 90 (or 120 for `gamma` on
hexagonal axes), within 1e-9. An inconsistent cell is an error naming each
value and the value to write (`stated b = 4.2, but by symmetry b = a; write
b = 4.15692`); nothing is adjusted. There is no `volume` field (every engine
derives it).

### Atoms

- **`element`**: the bare symbol, spelled exactly (`"Fe"`, not `"FE"`), and
  always the **neutral** atom — so the phase block means the same thing for
  every engine and moves between recipes.
- **Ionic scattering types** are stated per atom label in the engine's
  phase block, in the CIF spelling: `"scattering_types": {"La": "La3+"}`;
  an atom left out scatters as its neutral element. What each engine
  does with them, and the edge cases, are in
  [Scattering types by engine](#scattering-types-by-engine).
- **Coordinates** are fractional JSON numbers. On a special position the
  values fixed or tied by symmetry follow one rule (the full table with
  worked examples is in
  [SCHEMA_HISTORY, "Symmetry-determined values"](SCHEMA_HISTORY.md#core-schema)):
  the **first member** of each tie group (x before y before z) is free and kept
  as written; a **constant** of the site is written exactly when it has a
  decimal form (`0.5`, `0.25`, `0`; `0.4999999` is an error that says "write
  0.5") and to **at least 6 decimals** when it has none (`0.333333` for 1/3,
  `0.166667` for 1/6); a value **derived from another stated value** (`y = 2x`,
  `y = x + 1/2`) is stated within 5e-6 and read as the derived value. An atom
  between 5e-6 and 2e-3 (fractional) off a special position is an error
  (`0.33` and `0.3333` are neither 1/3 nor a general position): state the
  position, or move the atom at least 2e-3 off it. The validated model holds
  the exact derived values; a Python dump prints 1/3 as
  `0.3333333333333333`, which means the same and validates the same.
- **Values held in derived form** are reported: every coordinate, cell value
  or `Uij` the model holds as its exact symmetry-derived value gives one
  `symmetry_value_derived` warning at level `info` (stated value, held value,
  the relation): `y = 0.666667` on a 2c site gives one, `z = 0.25` gives none
  because it is already exact. The note is **evidence** that a value is
  symmetry-determined, never a statement of it — an exactly typed special
  position produces no note. Which sites are special is the symmetry
  analysis's answer, not the warnings list's.
- **`Multiplicity`** is optional; when stated it must equal the value derived
  from the space group (the converter drops a wrong one and reports it).
- **`occupancy`** is required and between 0 and 1 inclusive, even where an
  engine would compute with more.
- **`ADP`** selects the thermal parameter that is required: `"Uiso"` with
  `Uiso` (Å²), or `"Uaniso"` with all six `U11, U22, U33, U12, U13, U23`
  (Å²); the other must be left out. `Uij` must respect the site symmetry by
  the same rule as coordinates (a fixed component exactly `0`, a coupled one
  within 1e-6 Å² of its derived value). A tensor that is not positive
  definite is accepted with the warning `uaniso_not_positive_definite` (so is
  a negative `Uiso`): it can show that the parameter compensates for an
  unmodelled effect, and every engine carries the value as stated.
- **Atoms at the same position** (a mixed-occupancy site) are independent
  atoms with their own flags; PowderLine never ties them. User-defined ties
  between atoms are a future feature.

### Refine flags and the symmetry

Parameters tied by symmetry are **one** parameter, and every member is
stated (cubic `a, b, c` and all three angles; `(x, 2x, 1/4)` states x, y, z):

- tied members carry the **same** refine flag (the error is reported at the
  member whose flag differs from the first member's);
- a parameter **fixed** by symmetry (a cubic angle, `x` of an atom at the
  origin, `U12` on a mirror site) has flag `false` and, where the engine has
  bounds, no bounds (`null`, `null`);
- different groups are independent (orthorhombic `a` refined, `b` fixed);
- where the engine has bounds, tied members' bounds follow the tie like their
  values (`(x, x + 1/2, z)` with x in `[0, 0.2]` needs y in `[0.5, 0.7]`).

GSAS-II refines an oblique cell's parameters together (monoclinic
`{a, c, β}` for b-unique; all six for triclinic and rhombohedral axes), so a
`gsasii.*` recipe may not refine part of such a group. Each engine emits one
parameter per tie group; the result's `engine_details.parameters_requested`
counts a refined group once.

### Names

Phase names (the `phases` keys; the phase name is only the key, there is no
inner `phase_name`) and atom labels (the `atoms` keys) match
`^[A-Za-z][A-Za-z0-9_]*$`, are at most 64 characters, are not Python
keywords, and differ by more than case. This is the tightest form every
engine accepts as-is: GSAS-II renames phases with spaces or non-ASCII
characters and then skips their settings, easydiffraction accepts no other
atom label, TOPAS writes names into its input file, and phase names become
report file names (case-insensitive on Windows and macOS). So `"2H-MoS2"`
is written as `MoS2_2H`.

### Scattering types by engine

`element` is always the neutral atom, so a phase block means the same thing
for every engine. An ion is stated per atom label in the engine's phase
block:

```json
"scattering_types": {"La": "La3+"}
```

Ions are always written in the CIF spelling (`La3+`), whatever the engine.
An atom left out of `scattering_types` scatters as its neutral element.

| | GSAS-II 5.7.9 (`gsasii.*`) | easydiffraction 0.21.1, CrysPy (`calculator: "cryspy"`) | easydiffraction 0.21.1, CrysFML (`calculator: "crysfml"`) | TOPAS 6 (`topas.*`) |
|---|---|---|---|---|
| Engine's own spelling | `La+3` | `La3+` | none (charges stripped) | `La+3` |
| Ions with a form factor | 114 | 111 | none | 113 (`ATMSCAT.CPP`) |
| What the engine does with a wrong or unknown ion, silently | reads `La3+` as **hydrogen** (EB-94) | uses the **neutral** atom, log warning only (EB-95) | uses the **neutral** atom for every ion (EB-96) | stops without results; the reason appears only in its console window |
| What PowderLine does | writes GSAS-II's spelling into the atom record; refuses an ion GSAS-II has no form factor for | passes the CIF spelling through; refuses an ion CrysPy has no form factor for | refuses `scattering_types` (use the cryspy calculator) | refuses `scattering_types` for now: TOPAS's table and spelling are verified, the writer support is not yet released |

Verification: for LaB6 with `La3+`, the per-reflection intensity ratios
ion/neutral agree between GSAS-II and CrysPy within 1 %, and (measured
directly on TOPAS 6) between GSAS-II and TOPAS within 0.07 %.

Edge cases:

- **Coverage differs between engines.** `O2-`, `D1-` and `T1-` exist in
  GSAS-II's table but not CrysPy's. TOPAS has every GSAS-II ion except
  `T1-`. An oxide stated with `O2-` therefore validates for `gsasii.*`
  but **not for easydiffraction** (CrysPy has only `O1-`), and the
  error names the forms it does have.
- `T1-` cannot be stated at all, because gemmi has no element `T`.
- **Some atoms have no ion in any engine.** LaB6 is `La3+` with neutral
  `B`, because no engine has a boron ion.
- **Ions are per atom label.** Mixed valence on different sites is stated per
  site. A mixed site (two species at one position) is two atoms, each with
  its own label and type.
- **Spelling rules:**
  - a charge of 1–8 with an explicit sign;
  - `Fe+3` is an error that names `Fe3+`;
  - `Na+` (no number) is an error: write `Na1+`;
  - `element` must be the ion's element.
- **Moving a phase between engines** (`recipes.with_block`): the whole
  phase is copied, engine fields included. The target engine's schema then
  validates it, so an ion that engine has no form factor for is an error
  there. Engine fields written in another engine's form (gsasii
  `[value, flag]` against `[value, flag, min, max]`) must be rewritten for
  the target.
- **TOPAS's table can be changed by the user.** `ATMSCAT.CPP` sits in the
  TOPAS folder and can be edited; PowderLine's TOPAS table will be the
  shipped TOPAS 6 file.

### Atoms near a special position (disorder)

A common model for disorder is an atom displaced slightly from a special
position: a cation rattling off a 4a site, or an anion split over several
positions around a mirror. The atom is placed a little off the special
position, and its symmetry images then form the split site. Whether an
engine reads such an atom as **on** the special position or **off** it
depends on its own tolerance, and the engines do not agree. PowderLine
decides this once, in core, the same way for every engine. Anything an
engine would do silently becomes either a reported value or an error.

How far the atom is from the special position is measured as `d`: the
largest fractional-coordinate distance between the atom and one of its own
symmetry images. Fractional units make `d` independent of the cell, which
is itself refined. In ångström, `d` is roughly `d × a`. With a = 4 Å,
2e-3 is 0.008 Å; with a = 10 Å it is 0.02 Å; with a = 20 Å it is 0.04 Å.

| Stated position | GSAS-II 5.7.9 would… | easydiffraction / CrysPy would… | TOPAS 6 would… | PowderLine does |
|---|---|---|---|---|
| **exactly on** it (`0.5`, `0.25`; 1/3 needs 6 decimals, below) | read it as special | read it as special | read it as special (only an exact value or an equation) | special position; fixed coordinates cannot be refined (a refine flag on one is an error) |
| **within 5e-6** (`0.333333` for 1/3) | read it as special (its tolerance is 2e-5 + 1e-5·\|x\|) | read it as special and **move the coordinate** to its Wyckoff value | read it as a **general** position: `k` atoms almost on top of each other | holds the exact value, reports `symmetry_value_derived` (level `info`, stated and held values), and gives every engine the exact value (TOPAS as the equation `= 1/3;`) |
| **5e-6 to 2e-3** (`0.3333`, `0.33`, or an atom 0.001 off) | special up to about 2e-5, then general, with the multiplicity changing in between | special or general depending on how the decimals rationalise | general | **error** naming the atom, the special position it is near and the fix: state the position exactly, or move the atom at least 2e-3 off it |
| **2e-3 or more** | general | general | general | general position, used as stated; nothing is moved |

So every recipe PowderLine accepts is read the same way by all three
engines.

The 2e-3 band is wider than any engine's own tolerance on purpose. An atom
whose own symmetry image is closer than 2e-3 is not a resolvable separate
site in powder data. Accepting it would leave the result depending on which
engine read it.

**During a refinement** no engine moves a refined coordinate back onto a
special position:
- GSAS-II never snaps;
- easydiffraction detects Wyckoff positions only when the structure is built
  (EB-47);
- TOPAS compares exactly.

A disordered atom that refines towards its special position stays a general
position with near-coincident images. If it ends inside the 2e-3 band, the
**output recipe is marked not valid**: `output_recipe_valid: false`, and the
`output_recipe_not_valid` warning names the coordinate. A chained next step
then stops there instead of running on an ambiguous position (KI-18). Re-state the
atom on the special position (an ordered model), or restart it further off.

**Writing a split site:**

1. **Place the atom at least 2e-3 off** the special position in fractional
   units. Work it out from the displacement you expect: 0.1 Å in a 10 Å cell
   is 0.01.
2. **Divide the occupancy by `k`**: the number of symmetry images that
   coincide on the special position. `k` is the general multiplicity divided
   by the special one. Example: a 4a site of Fm-3m displaced along x
   becomes 24e, so k = 6. PowderLine does not check this (KI-17); a split
   atom left at full occupancy counts `k` atoms.
3. **For a mixed site, state each species as its own atom.** Atoms at the
   same coordinates are independent: each has its own values and flags, and
   PowderLine never ties them. One species can then move off the shared site
   while the other stays.
4. **Refine with care.** Coordinates, occupancy and displacement parameters
   of a split atom are strongly correlated; check the ESDs and the
   parameter-disposition report.

## Instruments (one block per engine)

The instrument is where the engines differ most, so each schema states its
engine's own terms. Convert once, by hand, from your calibration; the fixture
READMEs (`tests/data/topas/native/README.md`,
`tests/data/easydiffraction/native/README.md`) work through the conversions
from GSAS-II's parameters.

### gsasii

`instrument` is the **single source** of GSAS-II's instrument parameters:
`radiation {type: "PXC", wavelength}`, `geometry {bank, azimuth}`,
`corrections {zero_shift, polarization, axial_divergence}`,
`broadening {U, V, W, X, Y, Z}`, plus an optional `description`. The gateway
builds GSAS-II's native parameter dictionary from it; there is no pasted
GSAS-II parameter block, no `null` "take the engine's value", no second
parameter set. GSAS-II's units: `U, V, W` in centidegree² (the Gaussian
variance), `X, Y, Z` and `zero_shift` in centidegree, SH/L dimensionless.
`axial_divergence` (SH/L) must be ≥ 0.002, GSAS-II's own evaluation floor.
`type` is `"PXC"` only: Kα doublets, TOF and neutron data are not supported.

### topas (TOPAS 6)

`instrument` holds `radiation` (one `lam` emission line: `ymin_on_ymax`,
`la`, `lo` in Å, `lh` in mÅ, optionally `lg`; `lg` alone crashes TOPAS 6,
so `lh` is required), optional `geometry` (`Rp`, `Rs` in mm, stated exactly
when an axial model reads them), optional `corrections` keyed by TOPAS macro
(`Zero_Error`, `LP_Factor` *or* `LP_Factor_Synchrotron`, `Simple_Axial_Model`
*or* `Full_Axial_Model`, `capillary`), and `broadening {peak_type, parameters}`
with `TCHZ_Peak_Type` (U, V, W, Z, X, Y), `PV_Peak_Type` or `PVII_Peak_Type`
and exactly that type's parameters. The TCHZ letters are **not** GSAS-II's:
TOPAS's U, V, W give the Gaussian FWHM² in degree², and its Lorentzian term
is X tanθ + Y/cosθ where GSAS-II's is X/cosθ + Y tanθ (the roles swap).
Geometry corrections act on every peak (background and single peaks
included); Lorentz–polarization acts on Bragg peaks only. The recipe also
states `engine_version` (`"6"`), and a run needs the installed version
declared (`--topas-version 6` or `topas.version` in
`.powderline_config.yaml`): `tc.exe` carries no version PowderLine could read.

### easydiffraction

`instrument` exposes every correction easydiffraction models for
constant-wavelength X-ray powder data, each a slot that is not modelled when
left out: `radiation` (`setup_wavelength` in Å; optionally a Kα2 line
`setup_wavelength_2` + `setup_wavelength_2_to_1_ratio`, stated together),
`polarization` (fixed `setup_polarization_coefficient` p and
`setup_monochromator_twotheta`; GSAS-II's P is **1 − p**), `corrections`
(`calib_twotheta_offset` in degrees, optional `calib_sample_displacement`,
`calib_sample_transparency`), `absorption` (`cylinder-hewat`, `mu_r`), and
`broadening {peak_type, parameters}`: `cwl-pseudo-voigt` (both calculators),
`cwl-pseudo-voigt-berar-baldinozzi-asymmetry` (CrysPy) or
`cwl-thompson-cox-hastings` with FCJ `asym_fcj_1/2` (CrysFML), and
`cutoff_fwhm` (CrysPy only). Gaussian FWHM² = U tan²θ + V tanθ + W in
degree², Lorentzian FWHM = X tanθ + Y/cosθ in degrees (GSAS-II's X and Y swap
roles). The **calculator** is part of the recipe
(`refinement_controls.calculator`): CrysPy and CrysFML compute different
intensities and offer different peak types.

## Background and controls

`background.chebyshev` is the shared Chebyshev model (`num_coefficients`,
`coefficients`, one `refine_flag` for all terms); its basis spans the fit
window's first and last points in every engine. gsasii adds pseudo-Voigt
`single_peaks` (positions inside the window; values above GSAS-II's floors),
topas adds `One_on_X` and `xo_Is` `peaks`. A `gsasii.*` recipe without a
background has none (one fixed 0.0 term); a `topas.*` or `easydiffraction.*`
recipe without a background block has none, like every other left-out block.

`refinement_controls` is the engine's: gsasii `refinement_cycles` (1 =
simulation), topas `iters`, `chi2_convergence_criteria`, `x_calculation_step`
(all required; `iters: 0` = simulation), easydiffraction `calculator`,
`minimizer`, `max_iterations`, `chi_square_change_tolerance`,
`parameter_change_tolerance`, `gradient_tolerance` (all required; no flag set
= simulation).

## What is not supported

PowderLine states plainly what it does not do. None of these is silently
approximated; each is a validation error or simply absent.

- **CIF parsing** and **recipe building**: the structure arrives as a
  formatted dictionary (above). A builder or importer is future work.
- **Recipe translation between engines**: a recipe is written in one engine's
  terms; the structural block can be reused, the rest cannot.
- **Kα doublets and laboratory X-ray data**, **neutron** and **time-of-flight**
  data: gsasii 0.1.0 is `PXC` single-wavelength only; TOPAS recipes state one
  `lam` line; easydiffraction's Kα2 slot exists and reaches the engine, but
  PowderLine has no laboratory-data example or verification behind it yet.
- **Energy-dispersive data, and data on a Q or d-spacing axis**: `xrd_data`
  is constant-wavelength data on a 2θ axis in degrees; convert Q or d to 2θ
  in the reader that builds the block.
- **Pawley and Le Bail fitting** (whole-pattern fits with free reflection
  intensities): every phase is a structure. For a structure-free fit use
  single-peak fitting (`gsasii.spf`, `topas.spf`).
- **Fundamental-parameters profiles** (TOPAS `fp`): out of scope.
- **Bragg–Brentano and other 1D-geometry specimen corrections** (TOPAS
  `Specimen_Displacement`, `Absorption`, goniometer radii beyond the axial
  models): later; easydiffraction's displacement/transparency slots exist.
- **Sample absorption and sample displacement in gsasii 0.1.0**: GSAS-II's
  sample parameters are not exposed (easydiffraction has `absorption` and
  displacement slots, topas a `capillary` absorption correction).
- **Extinction** and **surface roughness** corrections: in no engine schema.
- **Multi-histogram** refinements and **sequential / iterative strategies**:
  one pattern, one refinement per recipe; chain runs yourself.
- **Anisotropic size/strain models** (uniaxial, ellipsoidal, Stephens):
  gsasii and topas accept `isotropic` only.
- **Preferred orientation beyond March–Dollase** (spherical harmonics, a
  second axis) and **March–Dollase in topas 0.1.0** (declared, refused).
- **Charged scattering types in topas 0.1.0** (declared, refused).
- **Parameter bounds in gsasii recipes**: GSAS-II clamps after the fit, so
  bounds are not exposed; they may come in a later gsasii schema version.
- **User-defined constraints** between atoms (shared occupancies, tied ADPs
  across sites): not in 0.1.0.
- **Restraints and rigid bodies** (bond-length or angle restraints, rigid
  groups): not in any engine schema; only the space-group symmetry ties
  parameters.
- **Magnetic structures**: X-ray data only, so no magnetic models.
- **Choice of minimizer**: each engine uses its own least squares (GSAS-II's
  with `refinement_cycles`, TOPAS's with `iters`); easydiffraction's
  `minimizer` must be stated and accepts only `"lmfit (leastsq)"`.
- **`unsafe_mode`** (relaxing checks such as the occupancy range without
  guaranteeing the recipe's intent): a named future feature, not present.
- **TOPAS 7**: `topas.*` 0.1.0 is verified against TOPAS 6 and declares TOPAS
  6 only; TOPAS 7 needs an explicit widening with a compatibility run.
- **A structure-source plugin** (Materials Project, CIF) upstream of the
  simulation recipe builder, with its own configuration: the Materials
  Project tool that drove the builder left PowderLine in 0.2.0.
