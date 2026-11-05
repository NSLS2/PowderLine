# easydiffraction recipe for the textured LaB6 example

`input.json` is `tests/data/easydiffraction/native/lab6_cryspy_pv.json` (LaB6, CrysPy
calculator, pseudo-Voigt profile) with the simulated textured pattern
(`../data/lab6_textured.json`, via `powderline.recipes.with_block`) and the March–Dollase
block: `ratio: [0.8, true, 0.1, 5.0]` along `[0, 0, 1]` plus easydiffraction's required
`march_random_fract: [0.0, false, 0.0, 1.0]`. The cryspy calculator is required: CrysFML
ignores preferred orientation without a message (EB-97). CrysPy's March correction is
Dollase's times a constant r^1.5 (EB-98); with `march_random_fract` held at 0 the scale
absorbs it and the refined `ratio` is the same r as GSAS-II's (with f > 0 it is not): 0.5976(14) here against GSAS-II's 0.5978(14) and the programmed
0.6 (`tests/test_example_textured.py`). Validate anywhere with
`powderline input.json --validate-only`; a run needs the `easydiffraction` environment.
