# TOPAS 6 ionic scattering: La3+ against neutral La

Reflection lists TOPAS-64 Version 6 wrote on 2026-11-04 (TOPAS machine
session; CRLF line ends converted to LF): the LaB6 recipe of
`examples/example_LaB6/topas/input.json` calculated with `iters 0`, once with
`occ La` (`ion_La_p1_peaks.txt`) and once with `occ La+3`
(`ion_Lap3_p1_peaks.txt`); the two INPs differ in that token only. TOPAS's own
`ATMSCAT.CPP` (sha256 `f8f01a90bbcb2d0db446817c6bc64da9040b45b9aa2981faaa64fd442b35f4c0`)
supplied the form factors; it is not in the repository.

Columns as the writer's `phase_out` asks for them: H K L M, d, 2θ,
`I_no_scale_pks`, `I_after_scale_pks`, ... Column 8 (`I_after_scale_pks`) is the
per-reflection intensity; its La+3/La ratio is compared with GSAS-II's
(`tests/data/ions/lab6_la3_over_la_gsasii.json`) in `tests/test_topas_scattering.py`.
