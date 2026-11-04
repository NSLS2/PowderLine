# LaB6 with ionic scattering types (La3+)

## Scientific Purpose

`example_LaB6` refined with lanthanum as the **La3+ ion** instead of the neutral
atom — the form factor of the ion, not of the atom. This is the reference case
for PowderLine's ionic scattering types: the recipe states them in
the engine's phase block, `scattering_types`, in the CIF spelling, and each
engine computes with the form factor it has for that ion. Boron stays neutral:
neither GSAS-II nor CrysPy has a boron ion, and mixed ionic / neutral types are
normal.

## Input Parameters

Identical to `example_LaB6` (28-ID-1 data, λ = 0.1665 Å, fit window 1–15°, cell
held, scale, background and instrument profile refined) plus

```json
"scattering_types": {"La": "La3+"}
```

`element` is still `"La"`: `element` is always the neutral atom in core, so the
phase block means the same thing for every engine and moves between recipes.

## Expected Behavior

- Rwp 6.49 % against 6.53 % for the neutral refinement (GSAS-II's wR in the two
  `dummy.lst` files; PowderLine's uniform Rwp 6.491 vs 6.534 % at run time): La3+
  fits these data marginally better. The lowest-angle reflection (100) loses 1.5 % of its
  calculated intensity with La3+ (the three removed 5d/6s electrons scatter
  mostly at low angle); the others move by less than 0.5 %.
- GSAS-II receives the type as `La+3` (its own spelling; it would read `La3+`
  as hydrogen, EB-94); the output recipe keeps `La3+`.
- The same calculation in easydiffraction's CrysPy calculator gives the same
  La3+/La intensity ratios within 1 % (`tests/data/ions/`,
  `tests/test_easydiffraction_scattering.py`).

## Output Files

The standard gsasii set (`refined_parameters.csv`, `LaB6_unit_cell_report.csv`,
`LaB6_peak_list_report.csv`, `fit_profile.txt`, `dummy.lst`, `output_recipe.json`,
`parameter_dispositions.csv`).

## Known Issues

None. TOPAS does not accept `scattering_types` in schema 0.1.0 (the TOPAS half
awaits a TOPAS 6 run), so this example has no topas recipe.

## Per-engine recipes

`easydiffraction/input.json`: the LaB6 CrysPy pseudo-Voigt fixture
(`tests/data/easydiffraction/native/lab6_cryspy_pv.json`) with the same
`scattering_types`; the cryspy calculator is required (CrysFML computes neutral
atoms only, EB-96). `easydiffraction/output/` is the committed reference of a run
of it (easydiffraction 0.21.1). Like the fixture's own golden, that refinement takes
`broad_lorentz_x` negative, so the Lorentzian FWHM is negative at the top of the
window (`easydiffraction_negative_width`, EB-87) and its output recipe is not valid
as written.
