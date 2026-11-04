# TOPAS recipe for this example (`topas.rietveld`, TOPAS 6)

`input.json` is a byte-for-byte copy of the committed native fixture
`tests/data/topas/native/lab6_rietveld.json` (LaB6 calibrant: TCHZ instrument refined, Chebyshev + one pv background peak, scale refined, cell and ADPs fixed). It was derived by hand from the
GSAS-II recipe of this example as described in `tests/data/topas/native/README.md`
(no 0.26.0 → `topas.*` converter exists; no TOPAS recipe is authored
outside that fixture set). The TOPAS 6 goldens — the INP the writer produces
and what TOPAS wrote for it — live in one place, `tests/data/topas/native/golden/`
(`tests/test_topas_native_golden.py`); **no TOPAS output is committed under
`examples/`**. Validate with `powderline input.json --validate-only`; a run
needs `tc.exe` on win-64 and a declared version (`--topas-version 6`).
