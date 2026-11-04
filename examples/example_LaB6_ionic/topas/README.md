# TOPAS recipe for the ionic LaB6 example (`topas.rietveld`, TOPAS 6)

`input.json` is `examples/example_LaB6/topas/input.json` (itself the native
fixture `tests/data/topas/native/lab6_rietveld.json`) with
`"scattering_types": {"La": "La3+"}` in the phase block. The recipe states the
ion in the CIF spelling; the INP writer puts TOPAS's spelling into the site's
`occ` (`occ La+3`), from the ions in TOPAS 6's `ATMSCAT.CPP`. B stays neutral:
TOPAS has no boron ion.

The check that the ion does in TOPAS what it does in GSAS-II is
`tests/test_topas_scattering.py`: on reflection lists TOPAS 6 wrote for this
structure with `occ La` and `occ La+3`, the per-reflection La3+/La intensity
ratio agrees with GSAS-II's within 0.07 % (gate 1 %). On the TOPAS machine,
`tests/test_topas_exec.py` repeats it with this recipe. No TOPAS output is
committed under `examples/`. Validate with `powderline input.json
--validate-only`; a run needs `tc.exe` on win-64 and a declared version
(`--topas-version 6`).
