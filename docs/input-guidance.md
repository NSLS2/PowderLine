# Input guidance: data, structures, instruments

How to fill the three parts of a recipe that need the most care, and what
PowderLine will not do for you. The field-by-field tables are on the
[fields page](fields.md); the rules are summarized here with the reason
behind each. Validate early and often: `powderline <recipe> --validate-only`
needs no engine, lists **every** problem with its field path, and prints the
structured warnings (defaults applied, symmetry remarks).

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
- **Ionic scattering types** are stated in the engine's phase block, beside
  `scale`: `"scattering_types": {"La": "La3+", "O": "O2-"}` — the atom label,
  then the ion in the CIF spelling (element, charge 1–8, sign; `"La+3"` is an
  error naming `"La3+"`). An atom left out scatters as its neutral element,
  which is normal where no ion exists (neither engine has a boron ion: LaB6
  is `La3+` with neutral `B`). Each engine refuses an ion it has no form
  factor for, naming the forms it has: GSAS-II 5.7.9 has 114 ions, CrysPy
  111 (no `O2-`, only `O1-`), CrysFML computes neutral atoms only (use the
  cryspy calculator), and **TOPAS does not accept `scattering_types` in
  schema 0.1.0** (its half awaits a TOPAS run). PowderLine spells the ion
  the engine's way itself; GSAS-II would read `"La3+"` as hydrogen (EB-94).
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
- **Fundamental-parameters profiles** (TOPAS `fp`): out of scope.
- **Bragg–Brentano and other 1D-geometry specimen corrections** (TOPAS
  `Specimen_Displacement`, `Absorption`, goniometer radii beyond the axial
  models): later; easydiffraction's displacement/transparency slots exist.
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
- **`unsafe_mode`** (relaxing checks such as the occupancy range without
  guaranteeing the recipe's intent): a named future feature, not present.
- **TOPAS 7**: `topas.*` 0.1.0 is verified against TOPAS 6 and declares TOPAS
  6 only; TOPAS 7 needs an explicit widening with a compatibility run.
- **A structure-source plugin** (Materials Project, CIF) upstream of the
  simulation recipe builder, with its own configuration: the Materials
  Project tool that drove the builder left PowderLine in 0.2.0.
