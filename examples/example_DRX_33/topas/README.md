# TOPAS recipe for this example (`topas.rietveld`, TOPAS 6)

`input.json` is a byte-for-byte copy of the committed native fixture
`tests/data/topas/native/drx33_rietveld.json` (DRX_33 + Li4MgWO6 (C 1 2/m 1): cells, scales, Chebyshev and isotropic microstrain refined). It was derived by hand from the
GSAS-II recipe of this example as described in `tests/data/topas/native/README.md`.
The TOPAS 6 goldens — the INP the writer produces
and what TOPAS wrote for it — live in one place, `tests/data/topas/native/golden/6/`
(`tests/test_topas_native_golden.py`); **no TOPAS output is committed under
`examples/`**. Validate with `powderline input.json --validate-only`; a run
needs `tc.exe` on win-64 and a declared version (`--topas-version 6`).
