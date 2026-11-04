# Migrating from PowderLine 0.1.x (schema 0.26.0) to PowderLine 0.2 (core + engine schemas 0.1.0)

<!-- Every statement below is traceable to docs/SCHEMA_HISTORY.md,
     scripts/convert_recipe_026.py or the maintainers' record of deliberate
     changes (docs/policies.md). -->

This guide is for anyone holding recipes written for **PowderLine 0.1.1**
(unified recipe schema **0.26.0**, `schema_name` `GSASII_Rietveld` or
`GSASII_SPF`). **PowderLine 0.2.0** reads **core schema 0.1.0** plus one
**engine schema 0.1.0** (`gsasii`, `topas` or `easydiffraction`). The new
schemas are separately versioned and start again at 0.1.0; they are told apart
from the old 0.1–0.26.0 line by `schema_name` (`gsasii.rietveld`, not
`GSASII_Rietveld`), not by the number (see
[SCHEMA_HISTORY](SCHEMA_HISTORY.md)). Two identifiers appear on every page of
these docs, so keep them apart:

| Identifier | 0.1.1 | 0.2.0 |
|---|---|---|
| PowderLine package version | `0.1.1` | `0.2.0` |
| Recipe schema version(s) | `"schema_version": "0.26.0"` | `"core_schema_version": "0.1.0"` **and** `"engine_schema_version": "0.1.0"` |

## 1. What changed, and why

<!-- Clean break, native conventions, no translation layer, migration guide
     + optional converter; declared compatibility; support_matrix -->

- **One recipe = one engine.** In 0.1.1 a single `GSASII_*` recipe ran on
  GSAS-II by default and could be *translated* to TOPAS or easydiffraction
  with `engine=`. In 0.2.0 the engine is named by the recipe's `schema_name`
  (`gsasii.rietveld`, `gsasii.spf`, `topas.rietveld`, `topas.spf`,
  `easydiffraction.rietveld`), and the recipe is written in **that engine's
  own conventions, names and units**. There is no translation layer: the
  numbers in a `topas.*` recipe are the numbers in the INP; an
  `easydiffraction.*` recipe states `broad_gauss_u` in deg², not GSAS-II's
  `U` in centideg². The 0.1.1 translations were lossy or, in places, wrong, and a translated recipe could never state what the target engine
  actually computed. A clean break was chosen over a compatibility layer.
- **Two schema versions, declared compatibility.** Every recipe states
  `core_schema_version` (the shared top level and structural models, owned by
  PowderLine) and `engine_schema_version` (that engine's payload). Each
  PowderLine release *declares* which versions it accepts; nothing is
  inferred from version arithmetic. Today every declaration is
  `==0.1.0`; see [the support matrix](support-matrix.md).
- **Unknown keys are errors** at every level of a 0.1.0 recipe; 0.26.0
  allowed extras and ignored them (SCHEMA_HISTORY, core 0.1.0 "Recipe
  frame").
- **The recipe is the record of the refinement intent.** Validation never
  changes what a recipe means: values fixed or tied by symmetry must be
  stated consistently (an inconsistent cubic cell, or `b` refined while `a`
  is not, is an error, not a silent fix), and GSAS-II's silent floors and
  defaults are now either stated in the recipe or applied with a structured
  warning (SCHEMA_HISTORY, core 0.1.0 "Phase block").

## 2. gsasii: use the converter

<!-- scripts/convert_recipe_026.py — module docstring, SPEC_026,
     canonical_space_group(), _Conversion.* -->

The script `scripts/convert_recipe_026.py` turns a 0.26.0 `GSASII_Rietveld` /
`GSASII_SPF` recipe into a `gsasii.rietveld` / `gsasii.spf` recipe. It is
engine-free (no GSAS-II import).

```bash
python scripts/convert_recipe_026.py IN.json -o OUT.json
```

It prints one line per change (`<path>: <what changed>`) and writes the
converted recipe; with no `-o` it only prints the report. It never edits the
input file.

Its guiding rule is that the converted recipe **states explicitly what 0.1.1
effectively refined**: structure and parameterization merge into one phase
block, every refinable becomes `[value, refine_flag]`, refine flags are
expanded to the groups GSAS-II refined together, and GSAS-II's own silent
defaults are written out. **Nothing is fixed silently**: wherever the result
would not validate, or the refinement 0.1.1 ran cannot be known, the
converter stops and lists every problem.

### 2.1 What the converter does, rule by rule

**Top level**
- `schema_name` `GSASII_Rietveld` → `gsasii.rietveld`; `GSASII_SPF` →
  `gsasii.spf`. `schema_version` → `core_schema_version: "0.1.0"` and
  `engine_schema_version: "0.1.0"`.
- `payload.asset_path` is dropped (not a gateway input).
- `xrd_data`: `tth`, `Itth`, `Itth_weights` and `filename` are kept; **every
  other key** (e.g. `UID`) moves to `metadata.xrd_data.<key>`.
- `fit_range` is carried as is; `null` / `[null, null]` is left out.
- Every populated `min`/`max` of a 4-element `[value, flag, min, max]` list is
  **dropped and reported**: gsasii 0.1.0 exposes no bounds (GSAS-II only
  clamps after the fit).
- Keys the 0.26.0 schema never defined (0.1.1 ignored them) are dropped and
  reported.

**Instrument** (0.26.0 `initialization[0]` + `parameterization` → one
`instrument` block)
- The value of each refinable is the `parameterization` value when it is not
  `null`, else the `initialization[0]` (Iparm1) value; the flag likewise
  (parameterization flag, else Iparm1's third element).
- `Type`, `Bank`, `Azimuth` become plain values (`radiation.type`,
  `geometry.bank`, `geometry.azimuth`).
- `SH/L` below **0.002** is raised to 0.002 and reported: GSAS-II computed
  with 0.002 whatever was stated (EB-37).
- `initialization[1]` (Iparm2) is dropped (0.1.1 never used it).

**Background**
- `chebyshev` is carried unchanged (`num_coefficients`, `coefficients`,
  `refine_flag`). Left out, it is reported: 0.1.0 means *no background* (one
  fixed term 0.0) where 0.1.1 used GSAS-II's constant 1.0.
- `single_peaks.pv_gaussian_sigma` is renamed **`pv_gaussian_sigma_sq`** (the
  value always was σ²). A peak with a `null` entry in any of the four
  lists is dropped and reported (0.1.1 dropped it silently).
- A Rietveld recipe's top-level `payload.single_peaks` (Peak List) is dropped:
  it took no part in a Rietveld refinement.

**Refinement controls**
- `refinement_cycles` is carried; `refinement_algorithm` is dropped and
  reported (0.1.1 ignored it); `single_peak_fitting_mode` is
  carried for `gsasii.spf`.

**Phases** (`structure` + `parameterization` → one block)
- The phase **key** is the name; `structure.phase_name` disappears.
- `space_group` is rewritten to gemmi's **canonical** name *as GSAS-II read
  it*: a bare two-origin symbol → `:2`; a bare rhombohedral symbol or `:H` →
  `:H`; a trailing `" R"` / `":R"` → `:R`; a short monoclinic symbol → the
  b-unique setting (e.g. `C2/m` → `C 1 2/m 1`). Each rewrite is reported.
- Cell `a`…`gamma`: value from `structure` unless the `parameterization`
  value differs (then the parameterization value wins, as in 0.1.1, and the
  difference is reported); `volume` is dropped (derived).
- Atoms: `x`, `y`, `z`, `occupancy` (absent → 1.0, 0.1.1's default), `Uiso`
  (absent → 0.0) and `Uaniso.U11…U23` (absent components → 0.0; the old
  `Uij` name is read as `Uaniso`) become `[value, flag]`. `element` and `ADP`
  stay plain. `ADP` is the one GSAS-II actually used: a `parameterization`
  `ADP` that supplied no values is reported and the structure's type kept.
- A stated `Multiplicity` is kept only if it equals the derived one;
  otherwise it is dropped and reported.
- **Refine flags are expanded to what 0.1.1 refined**: within a
  symmetry tie group (cubic `a, b, c`; `(x, 2x, 1/4)`; `U11 = U22`…) and
  within GSAS-II's cell groups (monoclinic `{a, c, β}` for b-unique, all six
  for triclinic / rhombohedral axes), one `true` makes every member `true`
  (reported per member); a `true` on a symmetry-fixed parameter becomes
  `false` (0.1.1 ignored it).
- A coordinate that 0.1.1 **snapped** to a special position (within 5e-6 of
  an exact 1/2, 1/4, 1/8, 0 …) is written exactly (`0.4999999` → `0.5`); a
  fixed `Uij` within 1e-6 Å² of 0 becomes `0.0`. Both are reported.
- `scale` with no value becomes `[1.0, flag]` (GSAS-II's default).
- `peak_broadening.size_broadening` / `strain_broadening` with no value are
  **left out** and reported: 0.1.0's documented default (10 µm / 0
  microstrain, fixed, no sample broadening) applies where 0.1.1 used GSAS-II's
  1 µm / 1000 microstrain. `LG_eta` with no value →
  `[1.0, flag]`. The uniaxial / ellipsoidal / Stephens fields are dropped and
  reported (the isotropic model 0.1.1 ran did not use them).

Finally the converted recipe is validated against gsasii 0.1.0; any error
there is added to the problem list and the conversion stops.

### 2.2 Where the converter stops, and what you must decide

Each of these raises `ConversionError` (exit status 1) with **every** problem
listed. The converter never guesses.

| It stops when … | Because … | You decide … |
|---|---|---|
| `schema_name` is not `GSASII_Rietveld` / `GSASII_SPF` | only the GSAS-II workflows have a converter | write a native `topas.*` / `easydiffraction.*` recipe (§3) |
| a `GSASII_SPF` recipe has `phases` | a peak fit has no phases | remove them, or convert a Rietveld recipe |
| `space_group` states origin choice **`:1`** | 0.1.1's GSAS-II read the coordinates as origin 2 (EB-03), so neither the stated structure nor the one 0.1.1 refined is known | transform the coordinates to origin choice 2 and state `:2` |
| gemmi cannot read the space-group symbol | there is no canonical name to write | state gemmi's canonical extended Hermann–Mauguin name |
| an atom is in the **ambiguous band** (5e-6 to 2e-3 off a special position) | `0.33` and `0.3333` are neither 1/3 nor a general position | state the position (`0.333333`) or move the atom at least 2e-3 off it |
| a `parameterization` `Uaniso` gives some but not all six `Uij` | 0.1.1 raised, so there is no refinement to reproduce | give all six, or use `Uiso` |
| `parameterization.corrections` has an unknown key | 0.1.1 raised for it | remove it |
| `initialization[0]` has GSAS-II keys gsasii 0.1.0 does not model (e.g. `Lam1`/`Lam2`, a Kα doublet), is missing a key, or `Type` is not `PXC` | gsasii 0.1.0 is single-wavelength PXC only (SCHEMA_HISTORY "Instrument") | a doublet, TOF or neutron recipe has no 0.1.0 equivalent today |
| `structure.phase_name` differs from the phase key | the key is the name | make them agree |
| `peak_broadening.*.model` is not `isotropic` | gsasii 0.1.0 supports isotropic only | drop the block (default applies) or state an isotropic value |
| the converted recipe fails gsasii 0.1.0 validation | the recipe states something GSAS-II silently replaced or could not do | see the message: it names the field and the value to write |

The last row is where the 0.26.0 LaB6 recipes stopped (the pre-conversion
recipes are kept as the converter's test fixtures in `tests/data/convert_026/`).
Their background peak has `pv_lorentzian_gamma = 1e-05`, below GSAS-II's floor
of 0.1 (EB-35):

```text
cannot convert the recipe:
  - payload.background.single_peaks.pv_lorentzian_gamma.0: pv_lorentzian_gamma[0] = 1e-05 is below 0.1,
    the smallest value GSAS-II computes with; it would silently use 0.1 (GSAS-II quirk EB-35)
```
<!-- output of `python scripts/convert_recipe_026.py tests/data/convert_026/example_LaB6/input.json`
     (run 2026-10-13), reflowed -->

Nothing can be inferred here: 0.1.1 computed with γ = 0.1, so "write 0.1" is
the faithful conversion, but whether that peak belongs in the model is a
modelling decision. For the shipped examples the maintainers'
decision was to **remove the peak** before converting: no γ rescues
it, the only converging variant degrades Rwp, and the data show no feature
there. The committed `examples/example_LaB6/input.json` therefore has no
`single_peaks`, and the regression references lost the four
`background_peak_0_*` rows. Your own recipe may warrant the other choice
(state the peak at the floor).

Other validation errors you may meet at this step, and what they mean:
a `scale` < 0; a wavelength ≤ 0 or crystallite size ≤ 0; a
background or Peak List peak outside the fit window; in a `gsasii.spf`
recipe, a refine flag on the width source not in use — the instrument U…Z
with `use_instrument_profile: false`, or a peak's σ²/γ with `true` — which
GSAS-II ignored silently (EB-53); a `fit_range` with no weighted data
point; a phase or atom **name** outside the rule *letter first, ASCII
letters/digits/underscore only, distinct ignoring case* (e.g.
`"2H-MoS2"` → `MoS2_2H`); a charged `element` (`"Fe3+"` belongs in `scattering_types`, §5); a
`Multiplicity`, cell or `Uaniso` inconsistent with the space group.

### 2.3 Field map: 0.26.0 `GSASII_*` → 0.1.0 `gsasii.*`

<!-- Derived from scripts/convert_recipe_026.py (SPEC_026, IPARM1, _Conversion)
     and checked against src/powderline/gateways/gsasii/schema.py (classes
     Radiation, Geometry, Corrections, InstrumentBroadening, Instrument,
     Background, BackgroundPeaks, SinglePeaks, SizeBroadening,
     StrainBroadening, PeakBroadening, GsasiiPhase, RietveldControls,
     SpfControls, _Payload, RietveldPayload, SpfPayload) and
     src/powderline/schema_core.py (CoreRecipe, XRDData, FitRange,
     ChebyshevBackground, UnitCell, Atom, UanisoTensor, Phase). -->

`[v, f]` = `[value, refine_flag]`. Where a 0.26.0 cell lists two sources, the
first non-`null` wins (parameterization over structure / Iparm1).

| 0.26.0 (`GSASII_Rietveld` / `GSASII_SPF`) | 0.1.0 (`gsasii.rietveld` / `gsasii.spf`) | Note |
|---|---|---|
| `schema_name: GSASII_Rietveld` / `GSASII_SPF` | `schema_name: gsasii.rietveld` / `gsasii.spf` | |
| `schema_version: "0.26.0"` | `core_schema_version: "0.1.0"`, `engine_schema_version: "0.1.0"` | two versions |
| — | `metadata` (optional, free-form, ≤ 1 MiB) | converter puts extra `xrd_data` keys here |
| `payload.asset_path` | — | dropped |
| `payload.xrd_data.{tth, Itth, Itth_weights, filename}` | same | |
| `payload.xrd_data.<other>` | `metadata.xrd_data.<other>` | |
| `payload.fit_range` | `payload.fit_range` | left out when null; must hold a weighted point |
| `payload.instrument.description` | `payload.instrument.description` | optional |
| `initialization[0].Type` | `instrument.radiation.type` | plain; `"PXC"` only |
| `initialization[0].Lam` / `parameterization.wavelength` | `instrument.radiation.wavelength` `[v, f]` | Å; > 0 |
| `initialization[0].Bank` | `instrument.geometry.bank` | plain integer |
| `initialization[0].Azimuth` | `instrument.geometry.azimuth` | plain, degrees |
| `initialization[0].Zero` / `parameterization.corrections.zero_shift` | `instrument.corrections.zero_shift` `[v, f]` | centideg |
| `initialization[0].Polariz.` / `parameterization.polarization` | `instrument.corrections.polarization` `[v, f]` | dimensionless |
| `initialization[0].SH/L` / `parameterization.corrections.axial_divergence` | `instrument.corrections.axial_divergence` `[v, f]` | ≥ 0.002 |
| `initialization[0].{U,V,W}` / `parameterization.broadening.{U,V,W}` | `instrument.broadening.{U,V,W}` `[v, f]` | centideg² |
| `initialization[0].{X,Y,Z}` / `parameterization.broadening.{X,Y,Z}` | `instrument.broadening.{X,Y,Z}` `[v, f]` | centideg |
| `initialization[1]` (Iparm2) | — | dropped |
| `background.chebyshev.{num_coefficients, coefficients, refine_flag}` | same | left out = one fixed 0.0 term |
| `background.single_peaks.positions` | `background.single_peaks.positions` `[v, f]` | deg 2θ, inside the window |
| `background.single_peaks.intensities` | `background.single_peaks.intensities` `[v, f]` | ≥ 0.1 |
| `background.single_peaks.pv_gaussian_sigma` | `background.single_peaks.pv_gaussian_sigma_sq` `[v, f]` | renamed; centideg², ≥ 0.01 |
| `background.single_peaks.pv_lorentzian_gamma` | `background.single_peaks.pv_lorentzian_gamma` `[v, f]` | centideg, ≥ 0.1 |
| `payload.single_peaks.*` (Rietveld) | — | dropped |
| `payload.single_peaks.{positions, intensities, pv_gaussian_sigma_sq, pv_lorentzian_gamma}` (SPF) | same, `[v, f]` | σ², γ ≥ 0.001; inside the window |
| `refinement_controls.refinement_cycles` | same | 1 = simulation, no flag may be true |
| `refinement_controls.refinement_algorithm` | — | dropped |
| `refinement_controls.single_peak_fitting_mode.use_instrument_profile` | same (SPF) | |
| `phases.<name>.structure.phase_name` | — | the key is the name |
| `phases.<name>.structure.space_group` | `phases.<name>.space_group` | canonical gemmi name |
| `structure.unit_cell.{a..gamma}` / `parameterization.unit_cell.{a..gamma}` | `phases.<name>.unit_cell.{a..gamma}` `[v, f]` | tied members same value and flag |
| `structure.unit_cell.volume` | — | dropped (derived) |
| `structure.atoms.<label>.element` | `phases.<name>.atoms.<label>.element` | bare symbol |
| `structure.atoms.<label>.{x,y,z}` / `parameterization.atoms.<label>.{x,y,z}` | `atoms.<label>.{x,y,z}` `[v, f]` | |
| `structure.atoms.<label>.occupancy` / `parameterization….occupancy` | `atoms.<label>.occupancy` `[v, f]` | required; 0–1 |
| `structure.atoms.<label>.Multiplicity` | `atoms.<label>.Multiplicity` | optional; must equal the derived value |
| `structure.atoms.<label>.ADP` / `parameterization….ADP` | `atoms.<label>.ADP` | `"Uiso"` or `"Uaniso"`; the other block must be absent |
| `structure.atoms.<label>.Uiso` / `parameterization….Uiso` | `atoms.<label>.Uiso` `[v, f]` | Å² |
| `structure.atoms.<label>.Uaniso.{U11..U23}` (or `Uij`) / `parameterization….Uaniso.{U11..U23}` | `atoms.<label>.Uaniso.{U11..U23}` `[v, f]` | Å²; all six |
| `parameterization.scale` | `phases.<name>.scale` `[v, f]` | required; ≥ 0 |
| `parameterization.peak_broadening.size_broadening.{model, isotropic_size, LG_eta}` | `phases.<name>.peak_broadening.size_broadening.{model, isotropic_size, LG_eta}` | `[v, f]`; left out = 10 µm fixed + warning |
| `parameterization.peak_broadening.strain_broadening.{model, isotropic_strain, LG_eta}` | `phases.<name>.peak_broadening.strain_broadening.{model, isotropic_strain, LG_eta}` | `[v, f]`; left out = 0 fixed + warning |
| `…uniaxial_*`, `hkl_direction`, `S11…S23`, `stephens_parameters` | — | dropped (isotropic only) |
| any `[v, f, min, max]` | `[v, f]` | bounds dropped |

## 3. TOPAS and easydiffraction: no converter

<!-- No 0.26.0 → topas.* converter; SCHEMA_HISTORY topas / easydiffraction
     0.1.0 sections ("There is no converter from 0.26.0 recipes") -->

A 0.26.0 recipe held GSAS-II's model of your sample. A `topas.*` or
`easydiffraction.*` recipe holds **that engine's** model — its own peak-shape
parameters, its own units, its own corrections — and a mechanical conversion
would only rebuild the GSAS-II translation the native schemas replace.
So there is no converter; you write the recipe in the engine's terms.

Start from the committed native fixtures, which are hand-derived from the
same LaB6 and DRX_33 data as the examples and documented beside the files:

- TOPAS 6: `tests/data/topas/native/` (`lab6_rietveld.json`, `lab6_spf.json`,
  `drx33_rietveld.json`, `ties_simulation.json`, `lab6_corrections.json`,
  `lab6_pv_full_axial.json`; its `README.md` works through the derivations,
  e.g. GSAS-II U, V, W in centideg² variance → TCHZ U, V, W in deg² FWHM², and
  the X/Y role swap).
- easydiffraction: `tests/data/easydiffraction/native/` (`lab6_cryspy_pv.json`,
  `lab6_crysfml_tch.json`, `lab6_crysfml_tch_calculation.json`,
  `drx33_two_phase_cryspy.json`, `lab6_slots_simulation.json`, with a
  `README.md`).

For the field-by-field meaning, units and validation rules read the
[`topas` 0.1.0](SCHEMA_HISTORY.md#topas-engine-schema) and
[`easydiffraction` 0.1.0](SCHEMA_HISTORY.md#easydiffraction-engine-schema)
entries of the schema history. Points that most often surprise someone coming
from a GSAS-II recipe:

- **No defaults** in either engine schema: a block left out means the feature
  is not modelled, and every value PowderLine would otherwise choose is
  required.
- **Bounds are 4-element lists** in both (`[value, flag, min, max]`); a stated
  bound replaces the engine's default/physical limit on that side, `null`
  keeps it.
- **TOPAS**: the recipe states `engine_version` (`"6"`; TOPAS 6 only in
  0.1.0), and a run needs the installed version declared
  (`topas_version` or `.powderline_config.yaml`), because `tc.exe` carries no
  version PowderLine could read. TCHZ U…Z are not GSAS-II's;
  `CS_L`/`CS_G`/`Strain_L`/`Strain_G` are not sizes or strains (LVol-IB and
  e0 are reported as TOPAS computes them).
- **easydiffraction**: the `calculator` (`cryspy` | `crysfml`) is stated;
  polarization is p with GSAS-II's P = 1 − p; GSAS-II's Lorentzian X and Y
  swap roles; a cell length over 30 Å cannot be modelled; `Uaniso` needs
  CrysPy.
- The phase block (`space_group`, `unit_cell`, `atoms`) is core's and is
  **identical** across engines, so the structural part of a converted
  `gsasii.*` recipe can be pasted into a native recipe (the TOPAS DRX_33
  fixture was built that way), adding the bounds slots the engine expects.

## 4. Statistics: `rwp` means something new

<!-- Uniform statistics in core, engine values under engine_details;
     percent, N = points inside the window with w > 0; standard keys;
     simulation_mode, None where undefined -->

- On every native run the result's `rwp`, `r_exp`, `gof` and `chi2_red` are
  **PowderLine's uniform statistics**, computed once in core: Rwp and Rexp in
  **percent**, over the data points inside the fit window with positive
  weight (zero-weight and out-of-window points are excluded from the sums and
  from N); P is the engine's own count of varied parameters. The same formula
  is applied to every engine, so the values compare how well each model fits
  the same points.
- **The engine's own values** (GSAS-II's wR, GOF, χ² and Nobs; TOPAS's;
  easydiffraction's) are kept under `engine_details`, together with
  `parameters_requested` (from the recipe) and `parameters_varied` (what the
  engine actually varied) — the visible trace of each engine's auto-applied
  constraints.
- How much this moves the headline number: for LaB6 core's Rwp is 6.5345
  against GSAS-II's 6.5346. Because the fit window is now exactly
  min ≤ 2θ ≤ max on the data points, GSAS-II's own Rwp equals core's on a
  native run.
- **Simulations** (`refinement_cycles` 1 in gsasii; `iters 0` in TOPAS; no
  refine flag in easydiffraction) get the same statistics (P = 0) and every
  native result carries `simulation_mode: true|false`. Against real data a
  one-cycle run tells you how good your starting values are; against
  placeholder data the statistics mean nothing — GSAS-II would have reported
  its 100 % cap.
- A statistic with no degrees of freedom is `None` (JSON `null`), never NaN.
- A refinement that **diverges** (non-finite calculated pattern) is a
  **failure** with a message, in every engine; 0.1.1 returned success with
  Rwp 100 % and a NaN profile.

## 5. Removed and still-unsupported features

- **Charged scattering types** moved out of `element` (always the neutral
  atom now) into the engine phase block's `scattering_types`, in the CIF
  spelling (`{"Fe": "Fe3+"}`). 0.1.1 passed GSAS-II's own
  spelling (`Fe+3`) through unchecked; the converter turns such an element
  into the neutral symbol plus the `scattering_types` entry and notes it. Each
  engine refuses an ion it has no form factor for; TOPAS accepts none in
  schema 0.1.0 (its half awaits a TOPAS run).
- **`refinement_algorithm`** is gone (0.1.1 accepted and ignored it); the
  `null`-valued `broadening`, `corrections` and phase `parameterization`
  blocks that crashed 0.1.1 at run time have no equivalent.
- **Bounds in gsasii recipes** are gone: GSAS-II applies limits only
  after the fit. Bounds live in `topas.*` and `easydiffraction.*` recipes.
- **Kα doublets, TOF, neutron** are not modelled by gsasii 0.1.0.
- **Package moves, no shims**: `powderline.topas` → `powderline.gateways.topas`
  and `powderline.easydiff` → `powderline.gateways.easydiffraction`. Code importing the old paths must be updated. An
  existing checkout needs **`pixi reinstall powderline`** so the gateway
  entry points are re-registered (KI-13).
- **pixi environments**: the default environment is
  **core-only** — it validates every recipe but runs no engine. Install the
  engine you use (`pixi install -e gsasii`, `pixi install -e easydiffraction`,
  or `-e all`) and run in it: `pixi run -e gsasii kicker <recipe>`. The
  `easydiff` environment is now `easydiffraction` (remove the stale
  `.pixi/envs/easydiff`); `pixi run gsas-server …` needs `-e gsasii`. A `gsasii.*` run in the default environment raises
  `EngineNotAvailableError` with the install and run commands in the message.
- **Public API and CLI**:
  - `powderline.run(recipe, output_dir, engine=...)` → `powderline.run(recipe,
    output_dir)`; the engine is the one `schema_name` names. Engine options
    are keywords (`execution_mode=` for gsasii; `topas_dir=`, `topas_version=`
    for topas).
  - `powderline.validate(recipe)` returns a `ValidationResult`: the validated
    model is `result.recipe`, the structured warnings `result.warnings`
    (0.1.1 returned the `RecipeModel` itself).
  - `validate_simulation_mode_parameters()` is gone: the gsasii schema rejects
    any refine flag in a `refinement_cycles: 1` recipe at validation.
  - `from powderline import RecipeModel` / `from powderline.schema import
    RecipeModel` have no replacement: the model classes are the gateways'
    (`powderline.gateways.gsasii.schema.GsasiiRietveldRecipe`, …), and you
    normally get an instance from `validate()`.
  - `from powderline import GSASClient` / `from powderline.gsas_client import
    GSASClient` → `from powderline.gateways.gsasii.client import GSASClient`
    (also `powderline.gateways.gsasii.server` for the server module).
  - One CLI for every engine: `powderline <recipe.json>` (installed console
    script) or `pixi run [-e <env>] kicker <recipe.json>`; `topas-kicker` is
    gone, a `topas.*` recipe goes through the same command with
    `--topas-dir DIR --topas-version 6` (or `topas.dir` / `topas.version`
    in `.powderline_config.yaml`; PowderLine never searches for `tc.exe`).
    The validate-only report prints the core and engine schema versions
    instead of `Schema version:`.

## 6. Checklist

1. Run the converter on each 0.26.0 GSAS-II recipe; read the report line by
   line — every line is a place where 0.1.1 did something your recipe did
   not say.
2. Where it stops, decide (§2.2); never paste a value you cannot justify.
3. Expect **different numbers** from 0.1.1 even for a clean conversion:
   the fit window, the size/strain and background defaults, SH/L 0.002, and `rwp` (§4). Compare against `engine_details`
   if you need GSAS-II's own statistics.
4. For TOPAS or easydiffraction, write a native recipe from the fixtures
   (§3).
5. On an existing checkout: `pixi install -e gsasii` (or the engine you use),
   then `pixi reinstall powderline --all` so every environment has the
   entry points (§5); run with `pixi run -e gsasii kicker <recipe>`.
6. In code: drop `engine=`, read `validate(...).recipe`, import `GSASClient`
   from `powderline.gateways.gsasii.client` (§5).
