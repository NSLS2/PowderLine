# TOPAS recipe for the textured LaB6 example (`topas.rietveld`, TOPAS 6)

`input.json` is `examples/example_LaB6/topas/input.json` (the native fixture
`tests/data/topas/native/lab6_rietveld.json`) with the simulated textured
pattern (`../data/lab6_textured.json`, March–Dollase r = 0.6 along `[001]`)
and the block

```json
"preferred_orientation": {"model": "march_dollase", "hkl": [0, 0, 1], "ratio": [0.8, true, null, null]}
```

The writer emits TOPAS.INC's `PO` macro in the phase's `str`:
`PO(p1_po_r, 0.8, , 0 0 1)`. With `null` bounds TOPAS keeps its own limits on
r (min 0.0001, max 2r + 0.5). TOPAS's `PO` is the March–Dollase correction in
GSAS-II's convention (checked to 1.4e-7 in
`tests/test_topas_preferred_orientation.py`); refined from 0.8 on this pattern
TOPAS 6 recovered r = 0.5982(14) (GSAS-II 0.5978(14), CrysPy 0.5976(14)). The
golden for this recipe comes from the next TOPAS machine session; until then
`tests/test_topas_exec.py` (TOPAS machine only) checks r within 0.01 of 0.6.
No TOPAS output is committed under `examples/`. Validate with `powderline
input.json --validate-only`; a run needs `tc.exe` on win-64 and a declared
version (`--topas-version 6`).
