# Comparing engines

What happens when models are refined against the same data in different
engines? This page shows two reference cases, refined in every engine PowderLine drives and by
each profile model the engines offer, and explains why the numbers differ.
It does not rank the engines.

:::{important}
Rwp compares how well each **model** fits the same points. It does not say
which engine is right. A lower Rwp usually means a richer or a different
model, and sometimes an unphysical one.
:::

## How the comparison is made

- **Two cases.** `LaB6` (the NIST SRM 660c calibrant, one phase) and `DRX_33`
  (a cubic disordered rock-salt cathode phase plus monoclinic Li4MgWO6). They
  are two patterns measured on the same synchrotron setup (λ = 0.1665 Å, the
  same 2θ grid), each fitted over 1–15° 2θ.
- **The same points.** Every engine fits the same 3767 weighted points, and
  Rwp, Rexp and GoF are PowderLine's uniform statistics, computed the same way
  for every row.
- **Δ vs GSAS-II** is the difference from the GSAS-II row, in parts per
  million and in units of the combined uncertainty σ = √(ESD² + ESD_ref²).
  For LaB6, two more columns compare with the NIST certificate value.
- **Source.** `run` means the engine was run for this page. `golden` means
  the row is rebuilt from a stored reference run: the engine's committed
  output files, named after the recipe that produced them. The TOPAS rows
  are always stored runs, produced on a computer with a TOPAS license.
- **The LaB6 cell is refined** in every row here, unlike `example_LaB6`,
  which holds it at the certified value. That is why the GSAS-II LaB6 row
  differs from that example.

## The numbers

```{include} ../_generated/cross_engine_comparison.md
```

## LaB6: the peak-shape model moves the cell

LaB6 at this wavelength has sharp peaks with strongly asymmetric low-angle
tails (axial divergence). How a profile model handles that asymmetry decides
where it puts each peak, and so the refined cell:

| How the model treats asymmetry | Engines | Cell vs GSAS-II | Why |
|---|---|---|---|
| Physically (Finger–Cox–Jephcoat) | GSAS-II; easydiffraction with CrysFML's Thompson–Cox–Hastings + FCJ profile | within about 10 ppm (~1.5σ) | Same physics, same answer ({ref}`EB-88 <eb-88>`) |
| Not at all: a symmetric pseudo-Voigt | easydiffraction, either calculator | +67 to +91 ppm | The fit shifts the peaks to follow the tails |
| Not at all: TOPAS's TCHZ profile without an axial model | TOPAS | +87 ppm | The same kind of shift; also the highest Rwp of the LaB6 rows |
| Empirically (Bérar–Baldinozzi, refined) | easydiffraction with CrysPy | +915 ppm, Rwp 4.8 % | The correction correlates with the cell (not in the table: no committed recipe uses it) |

Two lessons:

- **A good Rwp can come from an unphysical model.** The CrysPy pseudo-Voigt
  fit, with no asymmetry model, reaches an Rwp close to the FCJ fits only by
  driving its Lorentzian `X` term negative, which makes the peak width
  negative at high angle
  ({ref}`EB-87 <eb-87>`, warning `easydiffraction_negative_width`).
- **Compare cells, and know what each model was free to do.**

**Against the NIST certificate.** Every refined LaB6 cell sits above the
certified a = 4.156826(80) Å: by +84 to +94 ppm with a physical asymmetry
model, and by +161 to +181 ppm with a symmetric profile (the shift above).
The common part is in the data, not in an engine: the pattern was integrated
from 2D detector images without a parallax correction, which shifts the
peaks. A zero shift has the wrong angular dependence to correct that and
only partly compensates, so the recipes leave it at 0.
The Δ vs GSAS-II columns are the ones that compare engines.

**CrysFML depends on its starting values.** CrysFML computes in single
precision, so a CrysFML refinement stops at a point that depends on where it
started ({ref}`EB-90 <eb-90>`). Its cell is stable to about 1e-5, but its Rwp
and ESDs can change between runs. Such results carry the warning
`easydiffraction_crysfml_start_dependent`.

## The temperature series: profile shape leaks into Uiso

The six patterns of `example_LaB6_temperature_series` were calculated by
GSAS-II with a known cell and Uiso. Refined by easydiffraction:

| easydiffraction profile | Cell | Thermal expansion | La Uiso |
|---|---|---|---|
| CrysFML, Thompson–Cox–Hastings + FCJ | 14–31 ppm low (1.7–4 ESD) | recovered to 0.8 % | 10–22 % low (8–12 ESD) |
| CrysPy, symmetric pseudo-Voigt | +68 ppm (the asymmetry shift above) | — | 17 % low |

The cause is the peak shape, not the intensities ({ref}`EB-93 <eb-93>`). The
simulated peaks carry a GSAS-II Lorentzian width that neither easydiffraction
profile can represent, and the mismatch lands in the parameter that most
affects intensity versus angle: Uiso. Simulated with a profile easydiffraction
*can* represent, the same pattern gives a La Uiso of 0.00863 with CrysPy and
0.00868 with GSAS-II, against 0.00858 programmed. CrysFML gives 0.00823, 4 %
low, a difference traced to its remaining profile mismatch, not to its
intensity model.

**Lesson:** compare cells and their changes across engines. Compare absolute
displacement parameters only when the profile models agree.

## DRX_33: different broadening models, and data that can't decide

The three recipes describe the broad, overlapping peaks of this sample in
three different ways:

| Engine | What broadens the peaks |
|---|---|
| GSAS-II | crystallite size and microstrain per phase, instrument fixed |
| TOPAS | Lorentzian and Gaussian strain per phase, no size term |
| easydiffraction | the instrument's U, V, W, X, Y, no per-phase term |

- TOPAS and easydiffraction agree on the cubic cell within about 100 ppm
  (~1σ), with similar Rwp (7.2–7.3 %).
- GSAS-II's cubic cell is about 0.26 % smaller, but its ESD is nearly ten
  times larger, so the gap is only about 3σ. The large ESD is the honest
  signal that these data don't pin the cell down. The GSAS-II recipe is the
  [teaching example](../examples/index.md#teaching-examples) `example_DRX_33`,
  which asks the data for more than they can determine. It stops before
  converging (`gsasii_fit_not_converged`), and its output recipe is not valid
  (`output_recipe_not_valid`: a crystallite size refines negative,
  {ref}`KI-15 <ki-15>`).
- The monoclinic Li4MgWO6 cell differs by up to 0.2 % in the axes and 0.1° in
  β, within the correlations of a minor phase with broad peaks.

**Lesson:** when a cell differs between engines by more than a few σ, look
first at what else each model was free to vary.

## What can and can't be compared

| Comparable between rows | Not directly comparable |
|---|---|
| Rwp, Rexp and GoF: same formula, same 3767 points | Scale factors: each engine has its own convention |
| Cells and their ESDs, in the same units and the same report rows | Whether a volume ESD is given: GSAS-II and TOPAS yes, easydiffraction no |
| The number of parameters each engine varied | Profile parameters: different definitions and units (see each engine's page) |

How these numbers are regenerated is described in
[Contributing](../development/contributing.md).
