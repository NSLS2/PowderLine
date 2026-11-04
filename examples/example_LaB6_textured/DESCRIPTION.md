# LaB6 with March–Dollase preferred orientation (simulated)

## Scientific Purpose

**LaB6 powders do not texture; this is a mathematical demonstration** of
PowderLine's March–Dollase preferred orientation on the one
well-conditioned phase in the examples. The pattern is simulated with a known
texture, so the question the example asks has a known answer: *is the
programmed coefficient recovered by refinement?*

The truth is the `example_LaB6` structure (SRM 660a, a = 4.15682 Å, La at the
origin, B on 6f) with March–Dollase **r = 0.6 along [001]** — platy, in the
IUCr / GSAS-II convention (1 random, < 1 platy, > 1 needle; the correction
`A = 1/sqrt((r cos P)² + sin²P / r)` averaged over the symmetry equivalents of
the axis, Dollase 1986). GSAS-II calculated it in one cycle on the measured
28-ID-1 2θ grid (λ = 0.1665 Å, 3821 points in 0.9–15.1°) with the *original*
`example_LaB6` instrument profile (U 18.72, V 0.600, W 1.147, X 0.281, Y 0.001,
Z 0 centideg² — a positive-Y profile every engine can represent, EB-93), the
committed refinement's background and scale, and Poisson counting noise with
a fixed seed (`data/truth.json`; `make_textured.py` regenerates everything).

The pass/fail criterion for the capability itself is not this example but the
**Dollase-formula gate** (`tests/test_gsasii_preferred_orientation.py`,
`tests/test_easydiffraction_preferred_orientation.py`): each engine's
textured / untextured intensity ratio per resolved reflection equals Dollase's
correction computed from the stated r and axis over the reflection's cubic
equivalents (within 0.2 % in GSAS-II; in CrysPy up to a constant r^1.5,
EB-98). This example is the demonstration that follows — and the GSAS-II
half of it is partly circular (GSAS-II simulated the pattern with the same
`GetPrefOri` it refines with, so its recovery shows the plumbing and the
least squares, not the formula); the independent evidence is the gate's
hand-coded Dollase formula and the CrysPy leg.

## Input Parameters

`input.json` is `example_LaB6` with the simulation's own profile **held**, the
cell and atoms held, and three things refined: the scale (from 0.03), six
Chebyshev background coefficients (from 30, 0, 0, 0, 0, 0) and

```json
"preferred_orientation": {"model": "march_dollase", "hkl": [0, 0, 1], "ratio": [0.8, true]}
```

The start is **0.8, on the platy side, not 1.0**. In a cubic phase the
correction averaged over the equivalents of the axis is stationary at r = 1
(its derivative there sums to zero over the three cube axes), so from exactly
r = 1.0 GSAS-II's least squares cannot take a step that lowers χ²: its
damping reaches its limit and it aborts (`Rvals['Aborted']`), keeping the
last accepted values (here the start) but storing the rejected step's
calculated pattern — finite but worthless, wR printed at its 100 % cap — so no
statistic belongs to the parameters. GSAS-II's GUI keeps such a result behind
a "Minimizer halted" warning; PowderLine reports it as a `diverged` failure
(EB-99; before PowderLine 0.2.0 it returned `status: ok` with an astronomical Rwp). The same happens on the real,
untextured `example_LaB6` data. From 0.9 the pattern goes non-finite
(`diverged` as before); from 1.2 the refinement settles on the needle-side
minimum r = 1.73 (Rwp far above the true solution). Start on the side of 1
the sample suggests.

## Expected Behavior

| | GSAS-II (`output/`) | easydiffraction, CrysPy (`easydiffraction/input.json`) |
|---|---|---|
| r recovered (programmed 0.6) | 0.5978 (14) | 0.5976 (14) |
| uniform Rwp / GoF | 12.55 % / 1.02 | 12.78 % / 1.04 |
| output recipe valid | yes | yes |

Both engines recover r within two ESD of the truth, and agree with each other
within one. The residual 0.002 is the Poisson realisation (GoF ≈ 1). GSAS-II
refines `0:0:MD`; the output recipe carries it back as
`payload.phases.LaB6.preferred_orientation.ratio` (`parameter_dispositions.csv`
row `varied`).

## Output Files

The standard gsasii set (`refined_parameters.csv`, `LaB6_unit_cell_report.csv`,
`LaB6_peak_list_report.csv`, `fit_profile.txt`, `dummy.gpx` (gitignored), `dummy.lst`,
`output_recipe.json`, `parameter_dispositions.csv`).

## Known Issues

- Starting r at exactly 1.0 (GSAS-II aborts) or at 0.9 (non-finite) fails
  with `diverged`, at 1.2 finds the wrong minimum — see above; this is
  GSAS-II's refinement, not a PowderLine bug, and is recorded as EB-99.
- TOPAS does not accept `preferred_orientation` in schema 0.1.0 (its
  `PO(...)` half awaits a TOPAS 6 run), so there is no topas recipe.
- The example is simulated; no measured textured LaB6 exists here.

## Per-engine recipes

`easydiffraction/input.json`: the LaB6 CrysPy pseudo-Voigt fixture
(`tests/data/easydiffraction/native/lab6_cryspy_pv.json`) with the simulated
pattern as its `xrd_data` and the same block plus easydiffraction's required
`march_random_fract: [0.0, false, 0.0, 1.0]` (`ratio: [0.8, true, 0.1, 5.0]`).
The cryspy calculator is required: CrysFML ignores preferred orientation
(EB-97). No easydiffraction output is committed under `examples/`.
