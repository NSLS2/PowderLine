# easydiffraction recipe for this example (`easydiffraction.rietveld`)

`input.json` is a byte-for-byte copy of the committed native fixture
`tests/data/easydiffraction/native/drx33_two_phase_cryspy.json` (two phases, CrysPy calculator, pseudo-Voigt; U, V, W, X, Y, 6-term Chebyshev, both scales and cells refined). It was derived by hand from
the GSAS-II recipe of this example as described in
`tests/data/easydiffraction/native/README.md` (unit conversions, polarization
p = 1 − P, Lorentzian X/Y swapped, FCJ S/L = H/L; no 0.26.0 → `easydiffraction.*`
converter exists). Its golden result lives in
`tests/data/easydiffraction/native/golden/` (`tests/test_easydiffraction_native.py`).
`output/` is the committed reference of a run of this recipe (easydiffraction
0.21.1); `tests/test_example_easydiffraction_references.py` checks its tables
against the golden without running the engine. Validate in any
environment with `powderline input.json --validate-only`; a run needs the
`easydiffraction` pixi environment (Python ≥ 3.12).
