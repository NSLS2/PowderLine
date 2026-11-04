# Ionic scattering-type gate

`lab6_la3_over_la_gsasii.json` — GSAS-II 5.7.9's La3+/La per-reflection
integrated-intensity ratios for the `example_LaB6_simulation` recipe (one
cycle, nothing refined; the 28-ID-1 grid, λ = 0.1665 Å): the twelve resolved
reflections between 1.5 and 14.5° with no neighbour closer than 0.3°, as
`hkl`, `two_theta` and `ratio_ion_over_neutral` (±0.12° windows,
`tests/intensity_ratio.peak_areas`; `what` and `generated` inside the file
record how it was produced). The (100) ratio is 0.9854 (the three removed
5d/6s electrons scatter at low angle); the others lie within 0.998–1.005.

Consumers: `tests/test_gsasii_scattering.py` (recomputes the ratios through
the frozen project builder and compares them with the golden),
`tests/test_easydiffraction_scattering.py` (CrysPy's ratios agree within 0.5 %
and reproduce the (100) drop — the cross-engine gate), and
`tests/test_easydiffraction_preferred_orientation.py` (reuses the resolved
reflection list and 2θ positions for the March–Dollase gate).
