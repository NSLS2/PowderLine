# Native `topas.*` test fixtures (TOPAS 6)

Hand-derived recipes for the native TOPAS schemas. They are not converted
recipes: PowderLine ships no 0.26.0 → `topas.*` converter. The data arrays are
the committed examples' data; the starting values are worked out as below.

| Fixture | What it is |
|---|---|
| `lab6_rietveld.json` | LaB6 calibrant: TCHZ instrument refined (Z fixed), Chebyshev + one pv background peak, scale refined, cell and ADPs fixed |
| `lab6_cell_rietveld.json` | `lab6_rietveld.json` with the cell refined (`a`, `b`, `c` tied, flags true): the TOPAS cell value and ESD for the cross-engine comparison |
| `lab6_spf.json` | LaB6 single peak fitting: 36 peaks; the LaB6 TCHZ instrument fixed; each peak refines position, intensity and its sample `gauss_fwhm`/`lor_fwhm` |
| `drx33_rietveld.json` | DRX_33 + Li4MgWO6 (C 1 2/m 1): cells, scales, Chebyshev and isotropic microstrain refined |
| `ties_simulation.json` | `iters 0`: 1/3 constants, `y = 2x`, `y = x + 1/2`, coupled Uij, `b = a` |
| `lab6_corrections.json` | LaB6 plus Zero_Error, Simple_Axial_Model (`Rs`), capillary, LP_Factor_Synchrotron, One_on_X, an spvii background peak, CS_L + CS_G (exercises the writer; not a physical model) |
| `lab6_pv_full_axial.json` | LaB6 with PV_Peak_Type, Full_Axial_Model (`Rp`, `Rs`), refined LP_Factor, an spv background peak, a zero error with one stated bound (exercises the writer; not a physical model) |

## Derivations

- **Instrument (TCHZ from the examples' GSAS-II instrument parameters).**
  GSAS-II's U, V, W give the Gaussian *variance* in centidegrees²; TOPAS's TCHZ
  U, V, W give the Gaussian *FWHM²* in degrees². So U_TOPAS = 8 ln2 · U_GSAS /
  10⁴ (V, W likewise), Z_TOPAS = 0. GSAS-II's Lorentzian FWHM is X/cosθ + Y
  tanθ (centidegrees), TCHZ's X tanθ + Y/cosθ (degrees): X_TOPAS = Y_GSAS / 100,
  Y_TOPAS = X_GSAS / 100 (the role swap of devkit TOPAS findings §C.2). A refined
  X or Y starts at least at 0.0001, TOPAS.INC's floor (A138).
- **Background.** The 0.26.0 TOPAS path already used TOPAS's own `bkg` over the
  same fit window, so its refined coefficients are TOPAS-native starting values
  (LaB6, DRX_33). LaB6's broad background peak: the legacy fit's Gaussian and
  Lorentzian FWHM (12.0° and 1.74°) give a pseudo-Voigt FWHM ≈ 13.0° and η ≈ 0.18.
- **Scales and DRX_33 cells.** From the 0.26.0 TOPAS path's refined values
  (TOPAS magnitude, about 1e-6 × GSAS-II's).
- **Sample broadening.** LaB6: the legacy 10 µm Lorentzian size is CS_L =
  10000 nm (0.1 Rad λ/(cosθ·CS) = 0.018 λ/(π D cosθ) with D in µm). DRX_33: the
  legacy fit drove both sizes to 10⁶–10¹⁰ µm, i.e. no size broadening, so size is
  left out. Microstrain (µs, η) becomes Strain_L = 1.8e-4 η µs / π and Strain_G =
  1.8e-4 (1 − η) µs / π (degrees 2θ; findings §C.1 bijection).
- **Structures.** DRX_33's two phases come from the re/04 converter's
  `gsasii.*` output (core-valid: canonical space group, no stated multiplicity);
  Uiso values as in the example.

The generator that wrote these files (with the numbers above) is in the devkit:
`dossiers/multi-engine/probes/re05_topas/make_native_fixtures.py`.

## TOPAS goldens (`golden/<engine_version>/`)

What TOPAS wrote for each fixture, in the directory of the fixture's
`engine_version` (TOPAS-64 Version 6 under `golden/6/`; base name
`<fixture>__snapped`): the INP the writer produced (fit limits on data points,
A149), `_results.csv`, `_profile.txt`, the reflection lists, and the
background run (A152: `_bkg.inp`, `_bkg_profile.txt`). The six original
fixtures come from devkit probe packs 3 and 5 (2026-10-09); `lab6_cell_rietveld`
from the TOPAS 6 session of 2026-11-04 (written by a PowderLine whose schemas
were numbered 1.0.0: the fixture's two version strings and line 1 of its two
INPs were changed to 0.1.0, and the background INP header lost a trailing
design-record id; nothing else differs; CRLF line ends converted to LF).
`tests/test_topas_native_golden.py` checks that the writer still emits those
INPs and builds the result from TOPAS's files; on the TOPAS machine
`tests/test_topas_exec.py` reruns them with `tc.exe`. Regenerate them on a
TOPAS machine whenever the writer's output changes.

Other TOPAS output used by the tests: `ions/` (La3+ against La,
`tests/test_topas_scattering.py`) and `po/` (the `PO` macro,
`tests/test_topas_preferred_orientation.py`); each has a README.
