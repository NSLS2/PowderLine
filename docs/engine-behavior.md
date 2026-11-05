# Engine behaviour notes

PowderLine drives three refinement engines it does not control. Each has
quirks, limits and silent conversions; PowderLine's rule is to **expose
them, never paper over them**: wherever an engine would silently compute
something other than what the recipe says, the recipe is refused at
validation with a message naming the value to write; wherever an engine
does something a user should know about but that does not change the
recipe's meaning, the result carries a structured warning. This page lists
every verified engine behaviour that reaches a user, grouped by topic, with
PowderLine's policy toward it. The identifiers in brackets (`EB-nn`) are the
entries of the maintainers' engine-behaviour register; how policies are
decided is on the [policies page](policies.md).

Versions: GSAS-II 5.7.9, TOPAS-64 Version 6 (TOPAS 7 noted where known),
easydiffraction 0.21.1 (CrysPy 0.13.0, CrysFML 0.8.0). An item marked
*unverified* is recorded from documentation or a model, not from a run.

## Space-group spellings and settings per engine

Core requires gemmi's canonical extended Hermann–Mauguin name (564
settings; [input guidance](input-guidance.md#space-group-one-canonical-spelling)).
Each gateway translates it and refuses what its engine cannot express.

**GSAS-II** reads spaced symbols; hexagonal axes and origin choice 2 are its
defaults; rhombohedral axes come from a trailing ` R`. Its own lookup
tolerates `:H` and `:2` and **silently ignores `:1`** (a recipe meant in
origin choice 1 runs in origin choice 2, on a different structure, EB-03),
returns nothing for `R-3m:H` or `Fd-3m:2` spellings, and reads two symbols
as another setting (`P 21 n m`, `A b a m`: the general position's orbit
differs, EB-41). *Policy:* the gsasii gateway translates the canonical name
(spaced symbol, ` R` for `:R`, `:H`/`:2` dropped) and refuses **origin
choice 1 (33 settings) and 9 further settings** (7 it does not parse, 2 it
misreads); the translation was proved by a general-position orbit test over
every accepted setting. To use a refused setting, transform the structure to
a standard setting.

**TOPAS** accepts the symbols of its own table (case-insensitive, spaces
allowed, or the number); `:2` selects origin choice 2 and a **bare two-origin
symbol is origin choice 1** (the opposite of GSAS-II's default, EB-11); a
bare rhombohedral symbol is hexagonal axes and a trailing `r` rhombohedral
axes (EB-43). Twenty of gemmi's settings have no TOPAS symbol, and TOPAS 6
reads three (`C 1 21 1`, `I 1 21 1`, `C 4 2 21`) as another setting,
dropping an origin shift (EB-68). *Policy:* the topas gateway writes the
explicit TOPAS form (`:2` kept, `:1` and `:H` dropped, `:R` → `r`) and refuses
**23 settings**; the other 541 were checked operator by operator against
TOPAS 6's own generated operator files.

**easydiffraction** takes one of 230 short names plus a separate setting
code (531 settings in all, EB-42), but each **calculator** computes only some
of them correctly: CrysFML is handed the short symbol alone and misreads
almost every non-default setting (unique axis, cell choice, `:R`, some
origin-1 groups) (EB-80); CrysPy misreads 41 settings, crashes on 53
(EB-84), computes `P 31` with `P 32`'s operators (EB-80), resets the unique
angle of c- and a-unique monoclinic cells to 90° (EB-83), and computes
special positions wrongly in nine origin-choice-1 settings (EB-77).
*Policy:* validation accepts, per calculator, only the settings a computation
passed for a general position **and** every special site — **CrysPy 428,
CrysFML 230** of the 531 — and the error names a setting of the same group
that calculator computes, or the other calculator.

## Special positions and site symmetry

How to state atoms on and near special positions, with a disordered atom as the
example and a per-engine comparison, is in
[input guidance, "Atoms near a special position"](input-guidance.md#atoms-near-a-special-position-disorder);
the ionic-type comparison is in
["Scattering types by engine"](input-guidance.md#scattering-types-by-engine).

- **Core decides special positions, not the engine.** An atom within 5e-6
  (fractional) of a special position is on it; 5e-6 to 2e-3 off is an error;
  derived values are held exactly in the validated model, so the engines'
  own tolerances never matter: GSAS-II compares images within 2e-5 + 1e-5·|x|
  and not modulo 1 (EB-01); TOPAS compares within 1e-15 and treats any
  decimal third as a general position, so PowderLine writes fixed special
  coordinates as exact equations (`= 1/3;`) (EB-08); CrysPy rationalizes
  coordinates to denominator ≤ 10⁵ and snaps 5-decimal thirds (EB-12).
- **GSAS-II's cell-edge defect** (a coordinate just below an integer gets
  multiplicity 0, just above 0 an invalid one, EB-02) cannot be reached:
  such coordinates are exact constants in the model.
- **GSAS-II misreads some orientations of 2-fold sites** in R32, R-3m and
  R-3c on hexagonal axes, e.g. (0, 1/3, 1/6): it reports a general position
  with **doubled multiplicity**, and with nothing refined computes **four
  times** the Bragg intensity of the equivalent (1/3, 0, 1/6) (EB-40). Some
  other site orientations it cannot name at all (`'sp'`, e.g. F432 at
  (0, y, 0)), and it crashes when a coordinate or `Uaniso` of such an atom is
  refined (EB-05). *Policy:* after phase setup the gsasii gateway compares
  GSAS-II's site symmetry and multiplicity with core's for every atom and
  **stops with an error naming an equivalent position GSAS-II reads
  correctly** (always for a wrong multiplicity, since the site weight
  doubles even in a simulation; for an unnamed site only when a coordinate
  or `Uaniso` is refined). PowderLine never substitutes the position
  silently, because refined coordinates would then differ from the recipe.
- **easydiffraction applies site symmetry itself**: it detects the Wyckoff
  position when the structure is built, marks fixed coordinates and ignores
  a `free` flag on them, re-detects on a user edit with tolerance 1e-3 (so an
  off-special coordinate can change the multiplicity), and never re-detects
  during a fit (EB-47, EB-74). *Policy:* the gateway hands over core's exact
  values and checks easydiffraction's multiplicity against core's for every
  atom after the build.
- **CrysPy computes wrong structure factors for some equivalent writings of a
  special position with a free coordinate** (LaB6's B written as
  (½, ½, x) instead of the template's (x, ½, ½): intensities off by up to
  ×2), while general positions and fixed special positions are right
  (EB-77). *Policy:* with `calculator: "cryspy"` an atom on such a site must
  be written in the pattern of easydiffraction's Wyckoff template; the
  builder refuses anything else before the run and names the position to
  write. A position easydiffraction merely stores translated by a
  lattice vector ((0.137, 0.863, z) held as (0.137, −0.137, z)) is the same
  atom: accepted, with the warning `easydiffraction_position_translated`;
  reports stay in the recipe's writing. CrysFML has no such rule.

## Unit cell and ADPs

- **GSAS-II enforces cell symmetry only when the cell is refined**; a fixed
  inconsistent cell is used as given and gives wrong peak positions (EB-06).
  **TOPAS** uses individual `a b c al be ga` as given (EB-09). *Policy:* core
  refuses a cell that does not fit the space group (within 1e-9), in every
  engine.
- **Uij and site symmetry.** GSAS-II applies the constraints when refining
  and stores the values as given (EB-07); TOPAS's `adps` keyword applies them
  (*unverified*; EB-10); core requires symmetric `Uij` up front.
- **Isotropic ADP conventions.** TOPAS's `beq = 8π²·Uiso` (EB-24): the recipe
  states `Uiso` in Å², the gateway converts value and bounds and warns
  `topas_adp_converted` once per atom; results report `Uiso`. Core's `Uiso`
  and `Uij` are Å² in every schema.
- **Anisotropic ADPs in easydiffraction**: supported, but **CrysFML is
  handed only B = 8π²·Ueq**, so a `Uaniso` would have no effect there (EB-23);
  with CrysPy, easydiffraction 0.21.1 wrote a refined Uij into the wrong
  atom's column whenever an isotropic atom preceded the anisotropic one, so
  the refined tensor had no effect (EB-86). *Policy:* `Uaniso` with CrysFML is
  a validation error; with CrysPy the gateway hands the anisotropic atoms
  first (reports keep the recipe's order), and a test proves a refined Uij
  moves.
- **Signs and definiteness.** GSAS-II carries negative `Uiso`/`Uij` and
  refines from them (EB-51) and has no positive-definiteness check (EB-50);
  easydiffraction computes a finite pattern for both (EB-46, EB-50); TOPAS
  *unverified*. *Policy:* core has no sign rule (a negative ADP can
  compensate for an unmodelled effect) and warns `uaniso_not_positive_definite`.
  easydiffraction **refuses** a negative `Uiso` or U11/U22/U33
  at input (its physical limit 0–10 Å², EB-46/EB-71), so an `easydiffraction.*`
  recipe may not state one.
- **Occupancy.** GSAS-II accepts any value (EB-20), TOPAS limits `occ` to
  0..2·value+1 per iteration (EB-21), easydiffraction refuses values outside
  [0, 1] (EB-22). *Policy:* core requires 0 ≤ occupancy ≤ 1 for every engine.
- **Element and ion notation** differs (GSAS-II/TOPAS `Fe+3`, CrysPy `Fe3+`;
  gemmi strips the charge, EB-13, EB-25; GSAS-II reads `Fe3+` as hydrogen).
  *Policy:* core accepts bare symbols only; ions are rejected, never
  stripped.

## Names

GSAS-II rewrites phase names (strips surrounding whitespace, replaces
non-ASCII with `_`) and the settings of a renamed phase were then skipped
silently; a `/` broke the report file write (EB-44). easydiffraction accepts
atom labels of the form `[A-Za-z_][A-Za-z0-9_]*` only and lowercases
datablock names (EB-45). TOPAS treats two `prm` of the same name as one
parameter, so composed names could collide silently (EB-49, *unverified
beyond the model*). *Policy:* the core name rule
(`^[A-Za-z][A-Za-z0-9_]*$`, ≤ 64 characters, no Python keyword, distinct
ignoring case) makes every such name invalid before an engine runs; the
TOPAS writer uses index-based parameter names.

## Bounds and limits

Each engine means something different by a bound, so each schema says what
it exposes.

**GSAS-II applies parameter limits only after all cycles of a `Refine`
call**: an out-of-range value is set to the limit with ESD 0 and frozen for
the *next* call, while the reported values, ESDs and Rwp belong to the
unclamped fit (EB-30); cell limits must be set on the reciprocal-metric
terms and map onto direct-cell boxes exactly for only four of the seven
crystal systems (EB-31). *Policy:* **gsasii 0.1.0 exposes no bounds**; a
4-element parameter list is a validation error. Bounds may come in a
later gsasii schema version with a clamp-freeze-refit scheme.

**TOPAS keywords carry default limits** (`scale` ≥ 1e-11, `beq` in [−10, 20],
cell lengths ≥ 1.5 Å, lattice ±0.5 % per iteration, …) and the TOPAS.INC
macros add their own to refined parameters (TCHZ U–Z in [−1, 2], X, Y in
[1e-4, 2], CS in [0.3, 10000] nm, Strain in [1e-4, 5], the March–Dollase
`PO` ratio min 1e-4 and max 2r + 0.5, …); a user `min`/`max`
overrides the default on that side, and a start outside a limit is moved
onto it silently (EB-58). The `_LIMIT_MIN/MAX` markers TOPAS 6 writes are
mislabelled or spurious (EB-62). *Policy:* a stated bound replaces
TOPAS's limit on that side; a `null` side keeps TOPAS's default limit, and a
**refined start outside a fixed default limit on a `null` side is a
validation error** (state a bound to override TOPAS, or start inside).
**TOPAS 6 stops a little past a bound, not on it**: a `PO` ratio with min 0.7
ended at 0.700012 (1.7e-5 relative), and an SPF peak position stopped 1e-5°
inside `start_X` (TOPAS holds `xo` at the fit window's edge). After a run every
refined parameter within 1e-4 (relative) of a stated bound or TOPAS default
limit gets `topas_parameter_at_limit`, and an SPF peak position counts as at
the window's edge when no data point lies between it and the edge (or it is
on or beyond the edge); judged from the final values and the limits the
writer knows, not from TOPAS's markers. At a limit of 0 the tolerance is 1e-12
absolute.

**easydiffraction gives an unbounded side its physical limit** when a fit
starts (cell lengths 0–30 Å, angles 0–180°, occupancy 0–1, `adp_iso` and
U11/U22/U33 0–10 Å², scale, wavelength and μR ≥ 0), refuses a value outside a
physical limit at input even when fixed (no cell over 30 Å can be modelled),
and lmfit moves a start outside its bounds onto the bound without a message
(EB-71). *Policy:* a stated bound replaces the physical limit on
its side, `null` keeps it, a value outside a physical limit is a validation
error, and `easydiffraction_parameter_at_limit` marks a refined value that
ended within 1e-6 (relative) of a bound or physical limit (for a limit of 0,
within 1e-6 of the starting value).

## Defaults, floors and silent substitutions

### gsasii

- **GSAS-II reads the CIF ion spelling as hydrogen** (EB-94): `GetAtomInfo("La3+")`
  gives Z = 1, silently; GSAS-II's own spelling is `La+3`, and its
  `atmdata.XrayFF` has 114 ions. *Policy:* the recipe states ions in the CIF
  spelling in `scattering_types`; the gateway writes GSAS-II's spelling into
  the atom record and refuses an ion GSAS-II has no form
  factor for.
- **March–Dollase in GSAS-II**: the HAP entry
  `'Pref.Ori.': ['MD', r, flag, [h,k,l], 0, {}, [], 0.1]`; the refinement
  reads `p:h:MD` and `MDAxis` and applies `GetPrefOri` — Dollase 1986,
  `A = 1/sqrt((r cosP)² + sin²P/r)`, averaged over the symmetry equivalents
  of the axis (1 random, < 1 platy, > 1 needle). *Policy:* the recipe's
  `preferred_orientation` block is written by a frozen setter (a recorded
  frozen-code edit) and the refined `MD` maps back to `…preferred_orientation.ratio`;
  the Dollase-formula gate is `tests/test_gsasii_preferred_orientation.py`.
  **Started at exactly r = 1.0 in a cubic phase the refinement aborts**
  (textured and real LaB6 alike): the correction averaged over a cubic axis
  set is stationary at r = 1, so no damped step lowers χ² and GSAS-II aborts
  (`Rvals['Aborted']`): the last accepted values stay (the start, in a
  first-cycle abort) but the stored pattern and wR are the rejected step's,
  finite but worthless, wR printed at 100 % (its cap) — now a `diverged`
  failure (EB-99, below). On the textured example 0.9 goes non-finite and 1.2 settles on the
  needle-side minimum r = 1.73. Start on the expected side of 1.
- **GSAS-II's own defaults add sample broadening and background the recipe
  never asked for**: a new project gets isotropic size 1 µm, microstrain 1000
  and a constant 1.0 Chebyshev background, all fixed (EB-36). *Policy:*
  size/strain left out means **10 µm / 0 microstrain, isotropic, fixed** (no
  sample broadening), applied with the warning
  `gsasii_broadening_default_applied` naming the phase and the values, so
  GSAS-II's default is never used silently; background left
  out means **none** (one fixed Chebyshev term 0.0). These are the only
  documented defaults in gsasii 0.1.0; state the blocks to silence the
  warning.
- **SH/L is floored at 0.002** in the Rietveld and Peak List profile
  calculations (and at 0.0005 in `GetFobsSq`; background peaks use it as
  stored) (EB-37). *Policy:* `axial_divergence` < 0.002 is a validation error.
  The converted LaB6 examples state 0.002 where they said 0.0005.
- **Background peaks are evaluated with silent floors**: intensity 0.1, σ²
  0.01 centideg², γ 0.1 centideg (EB-35); **Peak List peaks** floor σ² and γ
  at 0.001 (EB-37). *Policy:* a value below a floor is a validation error.
- **The background-peak width is a variance**: GSAS-II's `BkPksig` is σ² in
  centideg² although its GUI calls it `sig` and its prose "Gaussian width"
  (EB-34). *Policy:* the field is named `pv_gaussian_sigma_sq`.
- **Width-derived quantities**: GSAS-II's peak `int` is an integrated area;
  its exporters write σ in degrees while the project holds σ² in centideg²,
  and several exporter formulas are wrong (EB-39). PowderLine reads the
  project directly and uses none of those exporters.
- **Single peak fitting ignores some refine flags silently**: with the
  instrument profile in use a peak's own σ²/γ flags, with per-peak widths the
  U..Z flags; it even clears the U/V/W flags when any σ² is refined, and drops
  singular parameters without a message (EB-53). *Policy:* a refine flag on
  the width source not in use is a validation error, and
  `gsasii_parameters_not_varied` reports any remaining silent drop.
- **The peak fit fills no covariance block** (EB-92): `DoPeakFit` keeps its varied
  names and ESDs in `Peak List['sigDict']` and writes the refined values in
  place (`Background[0]`, `Background[1]['peaksList']`, `Instrument
  Parameters[0]`, `Peak List['peaks']`), so a peak fit has no
  refined-parameter rows. *Policy:* the result's `peak_fit` block reads them
  from there (`fit_report.peak_fit_parameters`), and the output recipe is
  built from it.
- **Validation errors that replace run-time failures**: wavelength ≤ 0 and
  crystallite size ≤ 0 (GSAS-II fails with "no reflections" / an SVD
  failure); a Peak List or background peak outside the fit window (GSAS-II's
  peak fit failed with a bare `TypeError`, EB-38).

### topas

- **No defaults**: a block left out is not modelled; everything PowderLine
  would otherwise choose is a required field.
- **TCHZ takes the absolute value of its Gaussian term**
  (ΓG = √|U tan²θ + V tanθ + W + Z/cos²θ|), so a negative sum is used as its
  magnitude without a message (EB-55); the TR's formula has no `|…|`.
  Documented, not validated: TOPAS carries the user's value consistently.
- **`PVII_Peak_Type` differs from the Technical Reference**: TOPAS 7's macro
  computes h = ha + hb/cosθ + hc·tanθ and m = 0.6 + ma + mb/cosθ + mc·tanθ (the
  TR prints the tanθ and 1/cosθ terms the other way round), and h1, h2 are
  half-widths (EB-56). The schema documents the macro's formula.
- **`CS_L`, `CS_G`, `Strain_L`, `Strain_G` are not sizes or strains**: TOPAS's
  own documentation says they "have no direct physical interpretation and
  should not be reported". The interpretable quantities are
  **LVol-IB** = k / IB with IB = Voigt_Integral_Breadth_GL(1/CS_G, 1/CS_L)
  (π/2·(1/CS_L) or 1.0645·(1/CS_G) with one component) and
  **e0** = Voigt_FWHM_GL(Strain_G, Strain_L)·0.25·π/360 (EB-57). *Policy:*
  PowderLine reports LVol-IB (k = 1) and e0 as derived rows computed by TOPAS
  and documents that the four input terms are not sizes/strains.
- **`lam` with `lg` alone crashes TOPAS 6** (EB-64): `lh` is required, `lg`
  only with it.
- **A negative TCHZ Lorentzian part is computed as written**: `TCHZ_Peak_Type`
  is a pseudo-Voigt whose FWHM is the Thompson–Cox–Hastings combination
  (G⁵ + 2.69269 G⁴L + 2.42843 G³L² + 4.47163 G²L³ + 0.07842 GL⁴ + L⁵)^1/5 of
  the Gaussian width G and the Lorentzian width L = X·tanθ + Y/cosθ. With a
  fixed X < 0 (Y = 0) TOPAS 6 neither takes |X| nor clamps it at 0: X = −0.01
  runs and gives a profile unlike X = 0 or X = +0.01 (the total width stays
  positive); X = −0.1 makes the polynomial negative at the top of the window
  and TOPAS writes no results (measured on TOPAS 6; a negative convolution
  FWHM stops TOPAS, EB-69). *Policy:* PowderLine honours what TOPAS computes:
  a negative Lorentzian part passes while the total width is positive. With
  `TCHZ_Peak_Type`, the total width at the recipe's starting values must be
  positive at every data point of the fit window, X..Z refined or fixed;
  otherwise a validation error (`topas_tchz_width_not_positive`) names X, Y
  and the 2θ where the width is not positive. An output recipe whose refined
  values break the rule is not valid.
- **Ions are spelled `La+3` in `occ`** and taken from TOPAS's `ATMSCAT.CPP`:
  TOPAS 6's file has 113 ions, GSAS-II 5.7.9's table without `T1-`. TOPAS
  rejects the CIF spelling `La3+`, a sign-only `Na+` and an unknown symbol by
  stopping without results (no neutral fallback). *Policy:* the recipe states
  ions in the CIF spelling in `scattering_types`; an ion outside the shipped
  table is a validation error, and the writer puts TOPAS's spelling into
  `occ`. For LaB6 the per-reflection La3+/La intensity ratios agree with
  GSAS-II's within 0.07 %. `ATMSCAT.CPP` is user-editable; PowderLine checks
  against the file as shipped with TOPAS 6.
- **March–Dollase is TOPAS.INC's `PO` macro**: `PO(c, r, , h k l)` is GSAS-II's
  March–Dollase correction, averaged over the axis's equivalents with the same
  r convention (agreement 1.4e-7 along 001, 111 and 110), and refined from 0.8
  on the textured example it recovers r = 0.5982(14) (programmed 0.6). Its
  default limits are min 0.0001 and max 2r + 0.5 (the max follows the value,
  so a start never exceeds it). *Policy:* the writer emits
  `PO(p1_po_r, r[ min a][ max b], , h k l)` (`!p1_po_r` when fixed) with only
  the stated bounds; a refined start below 0.0001 with no stated min is an
  error.
- **Numbers are written to the INP to 10 significant digits** (`%.10g`), as
  in the `.xye`.

### easydiffraction

- **No defaults** either: every control is stated (`calculator`, the lmfit
  tolerances, `max_iterations`); a left-out instrument slot is not modelled.
- **An ion CrysPy has no form factor for becomes the neutral atom with a log
  warning only** (EB-95): `atom_sites.create(type_symbol="O2-")` is accepted
  (6341 CIF symbols) and the calculator substitutes `O`, `Logger.Reaction.RAISE`
  notwithstanding; CrysPy has 111 ions (`DATABASE['Scattering amplitude']`;
  no `O2-`, only `O1-`). **CrysFML computes neutral atoms only** (EB-96):
  easydiffraction strips every charge before handing the type to it.
  *Policy:* `scattering_types` is refused with the crysfml calculator and for
  any ion outside CrysPy's table, naming the forms it has.
- **Preferred orientation reaches CrysPy only, and only under the right
  key** (EB-97): the experiment's `preferred_orientation` rows are read by the
  CrysPy calculator alone (`calculators/cryspy.py`, `texture_g1 = 1/march_r`);
  CrysFML's pattern does not change with `march_r`, without a message; and a
  row whose `structure_id` is not the lowercase linked structure name is
  ignored by CrysPy too, silently. **CrysPy's March correction is Dollase's
  times r^1.5** (EB-98): its texture is not volume-normalised, so every
  textured/untextured intensity ratio carries the constant r^1.5; with
  `march_random_fract = 0` the scale absorbs it and the refined `march_r` is
  the same r as GSAS-II's, while with f > 0 the correction is
  (1 − f)·r^1.5·A + f and the refined r and f are not GSAS-II's quantities
  (easydiffraction's own source notes the distorted correspondence). *Policy:* `preferred_orientation` with `calculator: crysfml` is a
  validation error; the builder keys the row by `structure_name(phase)`; the
  gate compares normalised ratios (`tests/test_easydiffraction_preferred_orientation.py`).
- **σ < 1e-4 becomes σ = 1.0 silently** on every input path (EB-73):
  weights above 1e8 on handed points are refused.
- **Negative measured intensities are refused** by the library (EB-91): a
  negative handed point is a validation error.
- **Negative peak widths give a wrong pattern without a message**: where
  U tan²θ + V tanθ + W < 0 CrysFML drops the peaks and CrysPy distorts them;
  where X tanθ + Y/cosθ < 0 both give a finite pattern 12–24 % off (EB-87).
  *Policy:* a stated profile that makes a width negative on the handed points
  or on a 0.01° grid over the window widened by 1° plus the position
  corrections is a validation error; a refined profile that does so gets
  `easydiffraction_negative_width`. It happens in practice: the
  LaB6 CrysPy pseudo-Voigt fit refines X to −0.098, negative from 11.2° on.
- **The ASCII data reader rounds 2θ to 4 decimals** (EB-72): the gateway hands
  the data as a CIF loop at full precision, every number positional because
  the CIF loop cannot read exponent notation (EB-89).
- **Errors can be downgraded to log messages** by the environment variable
  `ED_LOG_REACTION=WARN` (EB-48): the gateway sets the reaction to `RAISE`
  itself, whatever the environment.
- **Importing easydiffraction imports `diffpy.pdffit2`**, whose version
  module queries PyPI; offline this prints a warning and continues (EB-82).

## The fit window and the data points

GSAS-II fits and scores one point **past** the upper limit when the limit
falls between data points (EB-54) and starts at the first data point,
weighted or not, with no limit; TOPAS fits the points **nearest** `start_X`
and `finish_X` (EB-59); easydiffraction calculates only the points it is
handed (so reflection tails from beyond the window are lost: ≤ 3e-4 σ at the
refined scale, EB-70) and maps its Chebyshev basis over them. *Policy:*
every gateway hands its engine the fit limits moved onto the
first and last **weighted** data points inside the window, so every engine
fits exactly the points core scores and spans its Chebyshev basis over the
same points; GSAS-II's own Rwp then equals core's. easydiffraction receives
exactly those points. A window with no weighted point is an error.

**TOPAS 6 loses part of an `xo_Is` peak's value at the last fitted point**
(a background or single peak without an axial convolution: LaB6's background
peak 1.35 counts low, ≈ 4 %), wherever the window ends; no calculation range,
step or `exclude` avoids it (EB-66). Documented, no workaround; the
background-only run carries the same value, so `y_bkg` is consistent with
`y_calc`. TOPAS 7: *unverified*.

## Requested vs varied parameters, convergence, failures

Every result reports `engine_details.parameters_requested` (independently
refined parameters in the recipe, a tie group counted once) next to
`parameters_varied` (what the engine actually varied, read after the run).
That pair is the visible trace of each engine's auto-applied constraints and
silent drops; when varied < requested the result warns
`<engine>_parameters_not_varied`.

- **GSAS-II**: `Refine` returns nothing on success; its messages (frozen
  limits, parameters dropped as singular, SVD) are only printed and stored
  in the project (EB-32), so the gateway reads them into
  `gsasii_refinement_message` warnings. Its parameter count `Nvars` includes
  parameters it dropped as singular (EB-33), reported as a warning, not
  subtracted; the SPF count is taken after the drops. GSAS-II's own
  convergence flag is read into `engine_details.converged` and
  `gsasii_fit_not_converged` warns when the last cycle's χ² change was above
  its tolerance (values kept; a Peak List fit keeps no flag, so
  `converged` is `None` there). The committed DRX_33 examples report
  `converged: false` after their five cycles.
- **TOPAS 6**: `tc.exe` returns the same exit code on success and failure and
  prints its messages only to its console window (EB-60), so **success is
  judged from the expected output files**, removed before the run; a missing
  file is an `EngineExecutionError` (`output_missing`) whose failure record
  lists the INP and data kept, the `tc.exe` path and exit code, and whatever
  `tc.exe` printed (`console_tail`; otherwise look at its console window and
  `tc.log`). Each `tc.exe` run is limited by `--topas-timeout` /
  `topas.timeout` (default 3600 s, 0 = no limit): past it `tc.exe` is stopped
  and the run fails with `timeout`, so a TOPAS waiting for input cannot hang a
  run. Without a declared `tc.exe` the run is
  `status: "generated"` with the `topas_generate_only` note: the INP and `.xye`
  were written, nothing ran. `converged` is always `null` for TOPAS 6 (no
  convergence signal in its files, EB-85). A
  non-finite term silently zeroes a phase and the background absorbs the
  pattern (EB-63): a phase with all-zero calculated intensities gets the
  informative `topas_phase_contributes_nothing` (a zero contribution can be
  legitimate: a phase absent from the sample). `Get(number_independent_parameters)`
  works in TOPAS 6 although undocumented and excludes parameters with zero
  derivative (EB-65): it is `parameters_varied`. TOPAS 6 exposes no
  convergence signal in its files (EB-85); a TOPAS 7 follow-up is open.
- **easydiffraction**: lmfit's `success` and message are read; a fit that
  stops without success (e.g. `max_iterations` reached) is a **success with
  values reported** and the warning `easydiffraction_fit_not_converged`. `parameters_varied` is lmfit's count (easydiffraction's
  `n_free_parameters`); a parameter without effect gets no ESD (EB-81).
- **Failures raise, uniformly**: `powderline.run()` and every gateway
  raise `EngineExecutionError` when the engine ran and failed — `diverged` (a
  calculated pattern that is not finite inside the window, or any non-finite
  number the engine writes: `nan`, `1.#QNAN`, `-nan(ind)`; GSAS-II itself
  prints wR `nan` and reports 100 %, EB-52; v0.1.1 returned success; **and,
  since 0.2.0, a Rietveld refinement GSAS-II aborted**, `Rvals['Aborted']` — no
  step lowered χ² before its damping hit its limit; it keeps the last accepted
  values but stores the rejected step's finite, worthless pattern and a wR at
  the 100 % cap, so no statistic belongs to the parameters; GSAS-II's GUI keeps
  this behind "Minimizer halted because chi**2 increased", PowderLine is
  deliberately stricter, EB-99; simulations exempt),
  `unusable_site` (gsasii, before refining), `peak_fit_failed` (gsasii,
  EB-38), `engine_crashed` (any engine), `output_missing` / `output_malformed`
  (TOPAS files, easydiffraction's pattern) — and `ExecutionBackendError` when
  the engine did not run (the GSAS-II server unavailable, disabled, timed out). The exception's `.reason` names the case and
  `.result` is the failed envelope. A failed run's directory holds the
  engine's own files written so far (gsasii `dummy.gpx`/`dummy.lst`, topas's
  INP/`.xye` and whatever TOPAS wrote) and **`failure.json`**, the envelope
  with a provenance block, written by `powderline.run()`; **no PowderLine
  result table exists for a failed run** on any engine (gsasii's checks run
  before its tables are written). `powderline.run()`
  also removes PowderLine's own fixed-name outputs from the directory before
  every run, so a reused directory holds one run's results; the engine's files
  and anything else there are never touched. Every returned result carries `status`
  (`ok` / `generated`) and `converged` (`true` / `false` / `null`); see
  [schemas](schemas.md#outputs).
- **A phase that contributes nothing** gets the informative
  `<engine>_phase_contributes_nothing` (topas, easydiffraction), never an
  error; gsasii accepts `scale: 0` for the same reason (recipe reuse).

## Statistics: uniform vs engine-reported

The result's `rwp`, `r_exp`, `gof` and `chi2_red` are **PowderLine's**, computed
once in core over the points inside the fit window with positive weight
(N), with P = the engine's varied-parameter count read after the run; Rwp and
Rexp in percent, GoF = Rwp/Rexp, χ²_red = GoF². The same formula applies to
every engine, so the values compare how well each model fits the same
points. The engine's own values stay under `engine_details`, and they differ:

- **GSAS-II's `GOF` means two things**: √(reduced χ²) in a Rietveld refinement
  and the reduced χ² itself in a Peak List fit (EB-52). GSAS-II caps R and wR
  at 100 %, so a simulation against placeholder data and a diverged
  refinement both read 100 % (EB-52; an *aborted* refinement is a failure
  since 0.2.0, EB-99 — a poor fit at the cap is still reported, with core's
  uncapped Rwp beside it). Its `Nobs` counted one point past the
  window (EB-54); with limits on data points its Rwp now equals core's
  on the native path.
- **TOPAS's `r_wp`** equals core's Rwp once the window is on data points
  (EB-59).
- **easydiffraction's `prof_wr_factor`** is 1/σ²-weighted and unchanged
  between 0.20.1 and 0.21.1; some ESDs changed with lmfit's explicit
  tolerances (EB-81). **CrysFML's integrated intensities drift −4 % from 3°
  to 15° 2θ** relative to m·|F|²·Lorentz, biasing `Uiso` by about +0.001 Å²
  (EB-78); the calculator is recorded in every result.
- **Comparing engines**: the [cross-engine comparison](cross-engine-comparison.md)
  shows that lattice parameters agree between GSAS-II and easydiffraction
  when axial asymmetry is modelled physically (FCJ), and shift +67 to
  +91 ppm with a symmetric profile whichever calculator runs it (EB-88). Rwp
  compares models fitted to the same points, not engines.

## Simulations

A simulation is a run that refines nothing: `refinement_cycles: 1` in
gsasii (every refine flag must be `false`, including polarization and Peak
List flags), `iters: 0` in topas (every flag `false`), no refine flag set in
easydiffraction (lmfit is not run). Every native result says
`simulation_mode: true|false`, and a simulation gets the **same uniform
statistics** as any run, with P = 0: against real data a one-cycle run tells
you how good the starting values are; against placeholder data (the
`example_LaB6_simulation` and `example_DRX_33_simulation` recipes, which
carry flat observations) the statistics mean nothing, and are large on
purpose (GSAS-II would print its 100 % cap). A statistic without degrees of
freedom is `None`, never NaN. The gsasii simulation of a converted
recipe no longer carries GSAS-II's 1 µm / 1000 sample broadening, so
simulated peak heights changed at the 0.2.0 re-baseline.

## Calculators (easydiffraction)

- **CrysPy** (default) computes `cwl-pseudo-voigt` and the Bérar–Baldinozzi
  empirical asymmetry; **CrysFML** computes `cwl-pseudo-voigt` and the
  Thompson–Cox–Hastings profile with FCJ axial asymmetry. Both "pseudo-Voigts"
  are the TCH pseudo-Voigt with Caglioti Gaussian and X tanθ + Y/cosθ
  Lorentzian widths; `cutoff_fwhm` acts in CrysPy only (CrysFML uses a fixed
  30-FWHM window) (EB-76). The peak type must be one the calculator computes.
- **The CW X-ray corrections easydiffraction models, in both calculators**
  (EB-75): the Kα doublet (`setup_wavelength_2` with
  `setup_wavelength_2_to_1_ratio`; in easydiffraction one alone does
  nothing, so the schema requires both or neither), the
  Lorentz-polarization factor 1 − p + p cos²2θ_m cos²2θ
  (`setup_polarization_coefficient`, `setup_monochromator_twotheta`; fixed
  values, 2θ_m acts only with p > 0), the 2θ offset, sample displacement and
  transparency (refinable, degrees) and Hewat cylinder absorption (`mu_r`).
  **GSAS-II's polarization P is easydiffraction's 1 − p** (GSAS-II's factor
  at azimuth 0 is (1 − P) cos²2θ + P): P = 0.99 is p = 0.01; copying P to p
  is a 6.6 % intensity error at 15° 2θ. *Policy:* every correction is a
  recipe slot, left out means not modelled; the hand-derived
  per-engine recipes state p = 1 − P.
- **CrysFML reports no reflection list** (EB-79): no peak list reports are
  written with it, and the result warns
  `easydiffraction_reflections_not_available`.
- **CrysFML computes in single precision**, below lmfit's finite-difference
  step, so a CrysFML **refinement** stops at a point that depends on its
  starting values (starts changed by 1e-6 relative gave Rwp 6.79 vs 6.27 %,
  cells stable to ~1e-5) (EB-90). *Policy:* every CrysFML refinement carries
  `easydiffraction_crysfml_start_dependent`; the calculator stays available
  because the user chooses it and PowderLine states the difference.
- **On GSAS-II-calculated LaB6 patterns, easydiffraction refines La's Uiso
  10–22 % low** (CrysFML TCH + FCJ: cell 14–31 ppm low; CrysPy pseudo-Voigt:
  Uiso 17 % low, cell +68 ppm, the EB-88 symmetric-profile shift) while B's
  Uiso, the thermal expansion and GoF ≈ 1 agree — the
  `example_LaB6_temperature_series` easydiffraction leg (EB-93). A probe
  points to **profile shape**, not the intensity model: with CrysPy
  the engines' *integrated* intensities agree (the ln-ratio slope against
  sin²θ/λ² goes to zero as the integration window widens) and its Uiso is
  still 17 % low — the fitted offset is not an intensity difference; the
  slope is identical with Uiso = 0 (not the Debye–Waller implementation),
  dispersion is negligible (slope −0.003) and the polarization mapping
  p = 1 − P is confirmed. With CrysFML the slope shrinks with the window
  (−0.21 → −0.08 at ±0.4°) but was not shown to vanish, as its TCH tails
  predict; a residual intensity difference of a few percent at high angle is
  not excluded for CrysFML alone. **The cause is the series' profile, and
  in it the clamped Lorentzian width** (shown by a test): the simulated peaks
  have γ = X/cosθ + Y tanθ + Z with Y = −10.26 centideg, which GSAS-II
  clamps to 0.001 centideg above ≈ 10.7°, so the high-angle peaks are pure
  Gaussian — the one part of that profile neither a symmetric pseudo-Voigt
  nor TCH (FCJ terms held at 0.001; freed, they do not move, EB-90) can
  represent; the angle-dependent mismatch is absorbed by the parameter that
  dominates the angle dependence of the intensities (holding Uiso at the
  truth costs GoF 1.030 → 1.045 only). The same pattern simulated with a
  GSAS-II profile easydiffraction can represent (the original `example_LaB6`
  posing: U 18.7, V 0.60, W 1.15, X 0.28, Y 0.001, Z 0; no clamp) gives
  CrysPy pV La Uiso 0.00863 vs 0.00858 programmed (0.3 ESD) and GSAS-II
  0.00868 (0.6 ESD); CrysFML TCH lands at 0.00823 (−4 %; no ESD, 0.00817(18)
  with X free), the size of the CrysFML-only intensity difference above.
  What remains across engines: that CrysFML residual, and the axial
  asymmetry, which on this pattern moves the *cell* (CrysPy's symmetric pV
  +76 ppm, an EB-88-size shift), not Uiso. *Policy:* documented
  (`docs/cross-engine-comparison.md`), no code change; across engines
  compare cells (with the EB-88-size offsets in mind) and expansion;
  absolute Uiso agrees only when the profile models do.

## TOPAS platform facts

- `tc.exe` carries no version metadata and prints its version only to its
  console (EB-67): the installed version is **declared** (`--topas-version` /
  `topas.version` in `.powderline_config.yaml`) and required to run; the check
  compares declarations, not the binary.
- TOPAS 6 cannot output the fit's background (`Get(bkg)` is 0; `phase_out_X`
  is TOPAS 7 only, EB-61): PowderLine runs a second, background-only INP at
  the refined values and uses its calculated pattern as `y_bkg`, every
  convolution included; if that run writes nothing, or is stopped at the
  time limit (`topas_timeout`), the result stays a success with an empty
  `y_bkg` and `topas_background_not_calculated`: the fit's values,
  statistics and output recipe do not depend on it.
- **TOPAS reads file paths in the Windows ANSI code page.** A folder whose
  name the code page cannot hold (Greek on a Western-European Windows) makes
  TOPAS 6 write nothing, also when it is the working directory; a Latin-1 name
  and spaces work, and so does the folder's 8.3 short path. *Policy:* on
  Windows an INP path the ANSI code page cannot encode is passed to `tc.exe`
  with its folder in the short form and the file name as written (TOPAS
  names its own `.out` after the name it is given, so a shortened file name
  would leave e.g. `TOPAS_~1.out`); if the volume has no short name for the
  folder (8.3 names disabled), the run is
  refused before `tc.exe` starts (`ExecutionBackendError`, reason
  `backend_error`) with a message to use an ASCII output folder. A non-ASCII
  base name is still replaced by `topas` (`topas_base_name_sanitized`).
- TOPAS is never executed by PowderLine's default test suite or docs build;
  the committed goldens (`tests/data/topas/native/golden/<version>/`, TOPAS 6
  under `6/`) are what the TOPAS machine wrote, and the comparison page
  rebuilds its TOPAS rows from them. On the TOPAS machine `pixi run test-topas`
  with `POWDERLINE_TOPAS_DIR` and `POWDERLINE_TOPAS_VERSION` set runs
  `tc.exe` against those goldens (`topas_exec`).

## Warnings you may see

`level` is `warning` (act on it or decide about it; the CLI prints these) or `info` (a record of something PowderLine did that changes no outcome; the CLI counts these and lists them with `--verbose`). Absent in a result means `warning`.

| Code | Engine | Level | Meaning |
|---|---|---|---|
| `gsasii_broadening_default_applied` | gsasii | warning | size or strain left out; 10 µm / 0 applied, fixed |
| `gsasii_background_default_applied` | gsasii | warning | `background` (or its `chebyshev`) left out; one fixed Chebyshev term 0.0 applied instead of GSAS-II's refined constant 1.0 |
| `gsasii_refinement_cycles_default_applied` | gsasii | warning | `refinement_cycles` left out; the default 5 cycles run |
| `gsasii_refinement_message` | gsasii | warning | a message GSAS-II stored with the refinement (correlations, singular parameters, SVD) |
| `gsasii_fit_not_converged` | gsasii | warning | the last cycle's χ² change was above GSAS-II's tolerance; values kept |
| `gsasii_parameters_not_varied` | gsasii | warning | GSAS-II varied fewer parameters than requested |
| `uaniso_not_positive_definite` | core | warning | the stated `Uaniso` has a principal value ≤ 0; used as stated |
| `symmetry_value_derived` | core | info | a coordinate, cell value or Uij stated within tolerance of its exact symmetry-derived value is held in that form (stated and held values in the message); evidence of a symmetry relation, not a statement of one — an exactly stated value gets no note |
| `output_recipe_not_valid` | core | warning | the run's output recipe (KI-04) does not validate as written — an engine returned a value the schema refuses, or a symmetry tie came back inconsistent; it is still returned and written (`output_recipe_valid: false`) |
| `topas_adp_converted` | topas | warning | `Uiso` written as `beq = 8π²·Uiso` |
| `topas_parameter_at_limit` | topas | warning | a refined value ended at a stated bound or a TOPAS default limit |
| `topas_parameters_not_varied` | topas | warning | TOPAS varied fewer parameters than requested |
| `topas_phase_contributes_nothing` | topas | info | a phase's calculated intensities are all zero (its scale is 0, or TOPAS discarded a non-finite calculation) |
| `topas_base_name_sanitized` | topas | warning | the recipe's base name is not ASCII-safe for TOPAS; files are written as `topas.*` |
| `topas_background_not_calculated` | topas | warning | the background-only run wrote nothing or was stopped at the time limit; `y_bkg` empty |
| `topas_generate_only` | topas | info | no `tc.exe` declared: the INP and `.xye` were written, the engine did not run (`status: "generated"`) |
| `easydiffraction_parameter_at_limit` | easydiffraction | warning | a refined value ended at a bound or physical limit |
| `easydiffraction_parameters_not_varied` | easydiffraction | warning | lmfit varied fewer parameters than requested |
| `easydiffraction_phase_contributes_nothing` | easydiffraction | info | as for topas |
| `easydiffraction_fit_not_converged` | easydiffraction | warning | lmfit stopped without success; values reported |
| `easydiffraction_negative_width` | easydiffraction | warning | the refined profile makes a width negative near the window |
| `easydiffraction_reflections_not_available` | easydiffraction | warning | CrysFML: no peak lists |
| `easydiffraction_position_translated` | easydiffraction | warning | an atom held in another writing of the same position |
| `easydiffraction_crysfml_start_dependent` | easydiffraction | warning | every CrysFML refinement (single precision) |

The table is the registry `powderline.exceptions.WARNING_CODES`: a test asserts that the two list the same codes with the same engine and level, and that every code emitted under `src/powderline` is registered.

## Upstream status

Problems found in the engines are written up for their developers in the
maintainers' private records (one file per issue with a standalone
reproduction): 13 for GSAS-II (the σ² label, the
cell-edge multiplicity, `'sp'` sites, the R-centred 2-fold misread, symbol
spellings, limits applied after the cycles, the Peak List `TypeError`, the two
GOF meanings and the 100 % cap, ignored SPF flags, the window's extra point,
the SH/L floors, the background-peak floors, the convergence flag absent from
the messages), 10 for TOPAS (the PVII formula, e0/LVol-IB
formulas, the TCHZ absolute value, the `lg`-alone crash, silent zeroing and
the negative-FWHM abort, the limit markers, the last-point loss, the three
misread settings, exit code/messages/version, the undocumented `Get`) and 14
for easydiffraction (the Uani column bug, special-position
images, CrysFML's short-symbol setting, CrysFML ignoring `Uaniso`, `P 31`'s
hand, the monoclinic cell reset, the 53 crashes, silent negative widths, the
σ replacement, CIF exponent notation, the ASCII rounding, the CrysFML
intensity drift, starts moved onto bounds, the single-precision Jacobian).
**None has been posted yet**; whether and when to post is the maintainers'
call. Until an upstream fix lands and PowderLine's engine pin moves to it,
every behaviour above stands as documented.
