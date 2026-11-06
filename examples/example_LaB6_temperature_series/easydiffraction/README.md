# easydiffraction leg of the temperature series (`easydiffraction.rietveld`)

`input.json` is the first step's recipe for easydiffraction: the committed
`examples/example_LaB6/easydiffraction/input.json` (CrysFML calculator,
Thompson–Cox–Hastings profile with fixed FCJ axial asymmetry, derived by hand
from the GSAS-II LaB6 recipe as `tests/data/easydiffraction/native/README.md`
describes) with

- the `xrd_data` block replaced by the simulated 25 °C pattern
  (`../data/lab6_025C.json`, via `powderline.recipes.with_block`);
- both Uiso refined (the series programs Uiso(T)), the scale and six
  Chebyshev coefficients refined from 30, 0, 0, 0, 0, 0;
- the cell (one tie group) and the TCH profile U, V, W, Y refined as in the
  parent recipe: the profile must be refined here because easydiffraction's
  TCH model is not GSAS-II's (the simulation's own profile is held in the
  GSAS-II leg);
- the TCH Lorentzian `broad_lorentz_x` **held** at its starting 10⁻⁵ (the
  parent recipe refines it): the simulated peaks above ≈ 10.7° 2θ are pure
  Gaussian, so a free X refines negative and the Lorentzian FWHM goes
  negative inside the window, which the schema refuses — the chain then
  stops at step 1 (recorded in the golden as `free_lorentz_x_run`).

The chain is the same `../run_series.py` with `--recipe` pointing here; the
loop does not know which engine it drives, because only the core `xrd_data`
block moves between steps. Run in the `easydiffraction` environment:

```bash
pixi run -e easydiffraction python examples/example_LaB6_temperature_series/run_series.py \
    --recipe examples/example_LaB6_temperature_series/easydiffraction/input.json --output <dir>
```

`output/` is the committed reference of a single run of `input.json` (the
first step alone, easydiffraction 0.21.1). The chain's reference table is the
golden
`tests/data/easydiffraction/native/golden/lab6_temperature_series.json`,
compared by `tests/test_example_temperature_series.py`. The results and what
they show about the two engines are in `../DESCRIPTION.md`.
