### LaB6

Fit window and points: 3767 points (every engine scores the same points).

| Engine (version) | Source | Model | Varied | Rwp % | Rexp % | GoF | Warnings |
|---|---|---|---:|---:|---:|---:|---|
| GSAS-II 5.7.9 | run | FCJ axial asymmetry (SH/L 0.002); no background peak; size 10 µm / strain 0 defaults, not refined | 14 | 6.000 | 12.455 | 0.482 | `gsasii_broadening_default_applied`, `gsasii_refinement_message` |
| TOPAS 6 (golden) | golden `lab6_cell_rietveld` | TCHZ; no axial-asymmetry model; Chebyshev + one pv background peak; CS_L 10000 nm fixed; cell refined | 17 | 7.447 | 12.450 | 0.598 | `topas_parameter_at_limit` |
| easydiffraction 0.21.1 | golden `lab6_crysfml_tch` | crysfml (`cwl-thompson-cox-hastings`): Thompson-Cox-Hastings + FCJ axial asymmetry (S/L = H/L = 0.001, fixed); no background peak; no sample broadening (start-dependent) | 13 | 6.765 | 12.456 | 0.543 | `easydiffraction_crysfml_start_dependent`, `easydiffraction_reflections_not_available` |
| easydiffraction 0.21.1 | golden `lab6_cryspy_pv` | cryspy (`cwl-pseudo-voigt`): pseudo-Voigt, no asymmetry; no background peak; no sample broadening | 13 | 6.815 | 12.456 | 0.547 | `easydiffraction_negative_width`, `output_recipe_not_valid` |

| Engine | Phase | Parameter | Value (ESD) | Δ vs GSAS-II (ppm) | Δ/σ | Δ vs NIST SRM 660c (ppm) | Δ/σ |
|---|---|---|---:|---:|---:|---:|---:|
| GSAS-II | LaB6 | a | 4.157217(21) Å | reference | — | +94 | +8.6 |
| TOPAS | LaB6 | a | 4.157579(19) Å | +87 | +12.7 | +181 | +17.0 |
| easydiffraction | LaB6 | a | 4.157175(18) Å | -10 | -1.5 | +84 | +8.0 |
| easydiffraction | LaB6 | a | 4.157495(17) Å | +67 | +10.2 | +161 | +15.4 |

Reference for the NIST columns: NIST SRM 660c, a = 4.156826 Å (certificate 2015-10-29: 0.4156826(8) nm, k = 2, 22.5 °C; standard uncertainty 4e-05 Å used for σ).

### DRX_33

Fit window and points: 3767 points (every engine scores the same points).

| Engine (version) | Source | Model | Varied | Rwp % | Rexp % | GoF | Warnings |
|---|---|---|---:|---:|---:|---:|---|
| GSAS-II 5.7.9 | run | FCJ axial asymmetry (SH/L 0.002); no background peak; isotropic size + microstrain refined per phase; not converged in 5 cycles | 21 | 10.829 | 9.814 | 1.103 | `gsasii_fit_not_converged`, `gsasii_refinement_message` |
| TOPAS 6 (golden) | golden `drx33_rietveld` | TCHZ instrument fixed; Chebyshev; Strain_L/Strain_G per phase; no size term | 17 | 7.305 | 9.820 | 0.744 | — |
| easydiffraction 0.21.1 | golden `drx33_two_phase_cryspy` | cryspy (`cwl-pseudo-voigt`): pseudo-Voigt, no asymmetry; U-V-W-X-Y refined instead of per-phase size/strain | 18 | 7.248 | 9.818 | 0.738 | — |

| Engine | Phase | Parameter | Value (ESD) | Δ vs GSAS-II (ppm) | Δ/σ |
|---|---|---|---:|---:|---:|
| GSAS-II | DRX_33 | a | 4.1715(33) Å | reference | — |
| GSAS-II | Li4MgWO6_SG12 | a | 5.1241(60) Å | reference | — |
| GSAS-II | Li4MgWO6_SG12 | b | 8.7912(14) Å | reference | — |
| GSAS-II | Li4MgWO6_SG12 | c | 5.0979(57) Å | reference | — |
| GSAS-II | Li4MgWO6_SG12 | β | 110.709(15)° | reference | — |
| TOPAS | DRX_33 | a | 4.18244(39) Å | +2614 | +3.3 |
| TOPAS | Li4MgWO6_SG12 | a | 5.13312(24) Å | +1766 | +1.5 |
| TOPAS | Li4MgWO6_SG12 | b | 8.78783(39) Å | -387 | -2.3 |
| TOPAS | Li4MgWO6_SG12 | c | 5.10453(22) Å | +1299 | +1.2 |
| TOPAS | Li4MgWO6_SG12 | β | 110.8212(38)° | +1014 | +7.1 |
| easydiffraction | DRX_33 | a | 4.18201(29) Å | +2511 | +3.2 |
| easydiffraction | Li4MgWO6_SG12 | a | 5.13261(24) Å | +1667 | +1.4 |
| easydiffraction | Li4MgWO6_SG12 | b | 8.78818(38) Å | -348 | -2.1 |
| easydiffraction | Li4MgWO6_SG12 | c | 5.10448(23) Å | +1289 | +1.2 |
| easydiffraction | Li4MgWO6_SG12 | β | 110.8182(37)° | +987 | +6.9 |

### easydiffraction goldens reproduced

| Fixture | Rwp % (rerun / golden) | Worst cell deviation (rel.) | Within 1e-4 | Run date |
|---|---:|---:|---|---|
| `lab6_crysfml_tch` | 6.765 / 6.765 | 0.0e+00 | yes | 2026-10-13 |
| `lab6_cryspy_pv` | 6.815 / 6.815 | 0.0e+00 | yes | 2026-10-13 |
| `drx33_two_phase_cryspy` | 7.248 / 7.248 | 0.0e+00 | yes | 2026-10-13 |

### Versions and dates

- GSAS-II 5.7.9: run 2026-10-13 (PowderLine 0.1.1, Python 3.13.15); `execution_mode='subprocess'`.
- TOPAS: TOPAS-64 Version 6 goldens (`tests/data/topas/native/golden/6/`, TOPAS machine runs of 2026-10-09); **not executed for this page**: the rows are the gateway's result built from the committed files.
- easydiffraction goldens (`tests/data/easydiffraction/native/golden/`, runs of 2026-10-09): easydiffraction 0.21.1, cryspy 0.13.0, crysfml 0.8.0, lmfit 1.3.4, numpy 2.4.6, scipy 1.18.0.
- Table generated 2026-11-04 by `scripts/cross_engine_comparison.py` at commit `4029d22` in `--no-run` mode (GSAS-II rows from the committed JSON record).
