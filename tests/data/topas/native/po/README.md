# TOPAS 6 March–Dollase preferred orientation (`PO` macro)

Files TOPAS-64 Version 6 wrote on 2026-11-04 (TOPAS machine sessions; CRLF
line ends converted to LF). Used by `tests/test_topas_preferred_orientation.py`.

- `po_none_p1_peaks.txt`, `po_r06_001_p1_peaks.txt`, `po_r1667_001_p1_peaks.txt`,
  `po_r06_111_p1_peaks.txt`, `po_r06_110_p1_peaks.txt`: the LaB6 recipe of
  `examples/example_LaB6/topas/input.json` calculated with `iters 0`, without
  preferred orientation and with `PO(, r, , h k l)` for r = 0.6 along 001,
  r = 1/0.6 along 001, r = 0.6 along 111 and r = 0.6 along 110. Column 8
  (`I_after_scale_pks`) is the per-reflection intensity; the textured/untextured
  ratio is the March–Dollase correction.
- `po_free_reference_results.csv`, `_profile.txt`, `_p1_peaks.txt`: the recipe
  of `examples/example_LaB6_textured/topas/input.json` (textured pattern,
  r refined from 0.8) as the writer writes it, except that the ratio was named
  `po_r` (the writer names it `p1_po_r`) and `start_X` was written as
  1.000355998. TOPAS refined r = 0.598184(1440); the programmed value is 0.6.
