# Good refinement practice

:::{warning} PowderLine does not judge your refinement
PowderLine checks that a recipe is **well-formed** and **consistent with its
symmetry**. It does not decide whether your choices make sense for your data.

A recipe can validate, run, converge and report a low Rwp, and still be a
poor model. One example: refining crystallite size and microstrain together
when the data can't tell them apart. Which parameters to refine, in what
order, and whether the result is physically reasonable are your decisions.
:::

This page collects widely used rules of thumb, each with a source. It is a
starting point, not a substitute for the references at the end.

## Judge a fit by looking at it

- **Plot the observed, calculated and difference curves.** The most
  important test of a Rietveld fit is to look at it and check that the model
  is chemically plausible. R-factors alone can mislead
  ([Toby 2006](#ref-toby2006)).
- **Read Rwp next to Rexp.** Rexp is the best Rwp the data could support. A
  pattern dominated by background can give a low Rwp with a wrong structural
  model, and counting longer can *raise* χ² while improving the model
  ([Toby 2006](#ref-toby2006)).
- **Compare models on the same points.** PowderLine's uniform Rwp, Rexp and
  GoF use the same points for every engine, so two models of the same data
  can be compared directly. Comparing Rwp across *different* datasets says
  little.

## Refine in stages

- **Start with the parameters the data determine best**, and add others one
  group at a time, checking the fit at each step
  ([McCusker et al. 1999](#ref-mccusker1999)). A common order is scale and
  background, then cell and instrument corrections, then peak shape, then
  atomic coordinates, then displacement parameters.
- **Calibrate the instrument on a standard**, and hold it for your samples.
  Then sample broadening isn't confused with instrument broadening.
  See [Calibrate the instrument](../how-to/calibrate-instrument.md).
- **Keep the high-angle data.** Excluding it limited accuracy in the IUCr
  round robin, as did peak-shape and background functions that were too
  inflexible ([Hill 1992](#ref-hill1992)).

## Know which parameters fight each other

Some parameters change the pattern in nearly the same way, so the data can
pin down only a combination of them. Refining such parameters together gives
large, correlated uncertainties and values that can drift to unphysical ones.

| Parameters | Why they correlate | What helps |
|---|---|---|
| Crystallite size and microstrain | Both broaden peaks. They differ only in how the broadening changes with angle: size as 1/cos θ, strain as tan θ. | A wide angular range with well-resolved peaks. Otherwise refine one and hold the other. In the IUCr size–strain round robin, many Rietveld refinements wrongly attributed size broadening to strain ([Balzar et al. 2004](#ref-balzar2004)). |
| Occupancy and displacement parameter of a site | Both scale how strongly the site scatters. | Refine one at a time, or fix one from chemistry. Releasing both for oxygen limited accuracy with X-ray data in the IUCr round robin ([Hill 1992](#ref-hill1992)). |
| Scale, background and displacement parameters | All change overall intensity with angle. | A sensible number of background terms; check the correlation after the fit. |
| Light atoms with X-rays (Li, B, H) | They scatter weakly next to heavy atoms. | Expect large uncertainties; consider holding their parameters. |

## Check the result is physical

- Sizes are positive, occupancies lie between 0 and 1, displacement parameters
  are positive (or positive definite), and bond lengths and angles are
  chemically reasonable ([McCusker et al. 1999](#ref-mccusker1999)).
- Least-squares uncertainties from a Rietveld refinement usually
  **underestimate** the true uncertainty ([McCusker et al. 1999](#ref-mccusker1999)).
- The same data analysed by different people can give different answers, and
  the refinement strategy is a large part of why
  ([Hill 1992](#ref-hill1992); [Madsen et al. 2001](#ref-madsen2001)).
  Recording the strategy matters. A chain of recipes records it exactly.

## Signals PowderLine gives you

PowderLine doesn't judge the model, but it reports what it sees:

| Signal | Where | What it suggests |
|---|---|---|
| `output_recipe_valid: false` with `output_recipe_not_valid` | result, warnings | The engine returned a value the schema refuses, e.g. a negative size or an occupancy above 1 |
| `at_limit` | `parameter_dispositions` | A value ended on a bound |
| `requested_not_varied` | `parameter_dispositions` | You asked to refine it, but the engine did not vary it |
| `converged: false` | result | The engine did not reach its convergence criterion |
| `uaniso_not_positive_definite` | warnings | A displacement tensor that is not physical |

The [teaching examples](../examples/index.md#teaching-examples) show several
of these on real data.

## Further reading

(ref-mccusker1999)=
- L. B. McCusker, R. B. Von Dreele, D. E. Cox, D. Louër and P. Scardi.
  Rietveld refinement guidelines. *J. Appl. Cryst.* **32**, 36–50 (1999).
  [doi:10.1107/S0021889898009856](https://doi.org/10.1107/S0021889898009856).
  *The IUCr Commission on Powder Diffraction's practical guide, written for
  newcomers.*

(ref-toby2006)=
- B. H. Toby. R factors in Rietveld analysis: How good is good enough?
  *Powder Diffr.* **21**, 67–70 (2006).
  [doi:10.1154/1.2179804](https://doi.org/10.1154/1.2179804)

(ref-hill1992)=
- R. J. Hill. Rietveld refinement round robin. I. Analysis of standard X-ray
  and neutron data for PbSO₄. *J. Appl. Cryst.* **25**, 589–610 (1992).
  [doi:10.1107/S0021889892003649](https://doi.org/10.1107/S0021889892003649)

(ref-madsen2001)=
- I. C. Madsen, N. V. Y. Scarlett, L. M. D. Cranswick and T. Lwin. Outcomes of
  the IUCr CPD round robin on quantitative phase analysis: samples 1a to 1h.
  *J. Appl. Cryst.* **34**, 409–426 (2001).
  [doi:10.1107/S0021889801007476](https://doi.org/10.1107/S0021889801007476)

(ref-balzar2004)=
- D. Balzar et al. Size–strain line-broadening analysis of the ceria
  round-robin sample. *J. Appl. Cryst.* **37**, 911–924 (2004).
  [doi:10.1107/S0021889804022551](https://doi.org/10.1107/S0021889804022551)

- J. A. Kaduk et al. Powder diffraction. *Nat. Rev. Methods Primers* **1**
  (2021). [doi:10.1038/s43586-021-00074-7](https://doi.org/10.1038/s43586-021-00074-7).
  *A modern overview of the whole method.*
- R. E. Dinnebier, A. Leineweber and J. S. O. Evans. *Rietveld Refinement:
  Practical Powder Diffraction Pattern Analysis using TOPAS.* De Gruyter
  (2019). ISBN 978-3-11-045621-9.
- V. K. Pecharsky and P. Y. Zavalij. *Fundamentals of Powder Diffraction and
  Structural Characterization of Materials*, 2nd ed. Springer (2009).
  [doi:10.1007/978-0-387-09579-0](https://doi.org/10.1007/978-0-387-09579-0)
- [GSAS-II tutorials](https://advancedphotonsource.github.io/GSAS-II-tutorials/tutorials.html),
  worked refinements with data.
