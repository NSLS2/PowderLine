# Native `easydiffraction.*` test fixtures (easydiffraction 0.21.1)

Hand-derived recipes for the native easydiffraction schema.
They are not converted recipes: PowderLine ships no 0.26.0 →
`easydiffraction.*` converter. The data arrays are the committed LaB6 example's
(`examples/example_LaB6`; the 0.26.0 `example_LaB6_easydiff` recipe they were first written against is kept as `tests/data/convert_026/example_LaB6_easydiff/input.json`, a converter fixture); the values are worked out as below.

| Fixture | What it is |
|---|---|
| `lab6_crysfml_tch.json` | LaB6, CrysFML, Thompson-Cox-Hastings with FCJ axial asymmetry (fixed); U, V, W, X, Y, cell, scale and a 6-term Chebyshev refined; window [1, 15] |
| `lab6_crysfml_tch_calculation.json` | `lab6_crysfml_tch.json` with every refine flag cleared: a CrysFML calculation. Its golden carries CrysFML's numbers, because a CrysFML refinement stops at start-dependent points (EB-90) and the refinement's golden compares only the cell, counts and warnings |
| `lab6_cryspy_pv.json` | LaB6, CrysPy, pseudo-Voigt (no asymmetry); the same refinement |
| `lab6_slots_simulation.json` | Calculation only (no flag set), CrysPy, every instrument slot: Kα2 doublet, polarization with a monochromator angle, displacement, transparency, cylinder absorption, Bérar–Baldinozzi asymmetry, a peak cutoff. Exercises the builder; not a physical model |
| `drx33_two_phase_cryspy.json` | Two phases from the `example_DRX_33` data: cubic DRX_33 (`F m -3 m`, four cations sharing 4a) and monoclinic Li4MgWO6 (`C 1 2/m 1`); CrysPy, pseudo-Voigt; U, V, W, X, Y, 6-term Chebyshev, both scales and cells (cubic a; a, b, c, β) refined; window [1, 15] |
| `golden/lab6_temperature_series.json` (golden only, no fixture) | The reference of the `examples/example_LaB6_temperature_series` easydiffraction leg: six sequential CrysFML TCH refinements of GSAS-II-simulated patterns through the output recipe (`run_series.py --recipe easydiffraction/input.json`), plus the free-Lorentzian-X run that stops at step 1 (EB-87). `tests/test_example_temperature_series.py` checks the golden's record (cell < 40 ppm of truth, La Uiso below truth, the stop reason) and re-runs the chain against it (cell 1e-4 relative, counts, validity, expansion coefficient 5 %) |

## Derivations (from the example's GSAS-II instrument parameters)

- **Gaussian widths.** GSAS-II's U, V, W give the Gaussian *variance* σ² in
  centidegrees² (σ² = U tan²θ + V tanθ + W); easydiffraction's
  `broad_gauss_u/v/w` give the Gaussian *FWHM²* in degrees². So
  `broad_gauss_u` = 8 ln2 · U_GSAS / 10⁴ (V, W likewise).
- **Lorentzian widths.** GSAS-II's Lorentzian FWHM is X/cosθ + Y tanθ
  (centidegrees); easydiffraction's (CrysPy `calc_h_l`) is X tanθ + Y/cosθ
  (degrees). The roles swap: `broad_lorentz_x` = Y_GSAS / 100,
  `broad_lorentz_y` = X_GSAS / 100. (The legacy 0.26.0 builder copies X to X and
  Y to Y; a deliberate change.)
- **Polarization.** GSAS-II's factor at azimuth 0 is (1 − P) cos²2θ + P
  (`GSASIIpwd.Polarization`); easydiffraction's is 1 − p + p cos²2θ_m cos²2θ
  (`analysis/corrections/polarization.py`). With 2θ_m = 0 they agree for
  p = 1 − P: the example's P = 0.99 is p = 0.01. (The legacy builder sets
  p = P; a deliberate change.)
- **Zero.** GSAS-II's `Zero` (centidegrees) / 100 = `calib_twotheta_offset`
  (degrees); the example's is 0.
- **Axial asymmetry (TCH fixture).** GSAS-II's SH/L is (S + H)/L
  (`GSASIIpwd.getFCJVoigt3` docstring), floored at 0.002 in the Rietveld
  calculation (EB-37), so the example's stated 0.0005 ran as 0.002.
  The fixture splits that equally, S/L = H/L = 0.001 (`asym_fcj_1`,
  `asym_fcj_2`); the equal split is an assumption (GSAS-II's Fortran split is
  not visible). The legacy builder sets both to 0.0005.
- **Atoms.** B is written at easydiffraction's template orientation of site 6f,
  (0.2021, ½, ½); the example states the equivalent (½, ½, 0.2021). CrysPy
  computes wrong structure factors for some equivalent images of a site
  (EB-77).
- **Scale and background.** Starting values near the refined ones (scale
  5.4e-6; Chebyshev 30, 0.6, 0.7, −0.4, −0.8, 0.9 over the window).
- **Two phases (DRX_33).** Same instrument as LaB6 (the example's GSAS-II
  parameters are identical), so the same conversions. The example's per-phase
  size/strain broadening has no easydiffraction counterpart (the profile is the
  experiment's); U, V, W, X, Y are refined instead. Li4MgWO6's `C2/m` is written
  with gemmi's canonical name `C 1 2/m 1`; its 4g, 4h and 4i atoms are already in
  easydiffraction's template pattern (EB-77). Starting values are near the
  refined ones, from a first fit that started from the example's structure with
  the LaB6 profile and a linear least-squares estimate of the scales and
  background (Rwp 7.25 %).
- **Refinement controls.** easydiffraction 0.21.1's own lmfit defaults
  (`max_iterations` = lmfit `max_nfev` 1000; tolerances 1e-8, 1e-8, 0).

The script that wrote these files is not part of the repository; the
derivations above account for every value in them.
