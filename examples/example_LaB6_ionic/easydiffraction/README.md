# easydiffraction recipe for the ionic LaB6 example

`input.json` is `tests/data/easydiffraction/native/lab6_cryspy_pv.json` (LaB6, CrysPy
calculator, pseudo-Voigt profile) with `"scattering_types": {"La": "La3+"}` in the
phase block. CrysPy has the La3+ form factor; the crysfml calculator would strip the
charge (EB-96) and is refused with `scattering_types`. Validate anywhere with
`powderline input.json --validate-only`; a run needs the `easydiffraction`
environment. The engine-independent check that the ion does the same thing here as
in GSAS-II is `tests/test_easydiffraction_scattering.py`.
