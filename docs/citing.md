# Citing PowderLine

If you use PowderLine in your research, please cite the preprint:

> A. A. Corrao, J. A. Perez, J. D. Langhout, M. M. Butala, T. A. Caswell, and
> D. Olds. *PowderLine: a programmatic powder diffraction analysis application.*
> arXiv:2608.17009 (2026).
> [doi:10.48550/arXiv.2608.17009](https://doi.org/10.48550/arXiv.2608.17009)

Machine-readable metadata is in
[`CITATION.cff`](https://github.com/NSLS2/PowderLine/blob/main/CITATION.cff).

## Cite the refinement engine too

PowderLine drives an underlying refinement engine. If you use PowderLine in
your work, please cite the engine you used in addition to PowderLine.

**GSAS-II** (default engine):

> B. H. Toby and R. B. Von Dreele. *GSAS-II: the genesis of a modern
> open-source all purpose crystallography software package.* J. Appl. Cryst.
> **46**, 544–549 (2013).
> [doi:10.1107/S0021889813003531](https://doi.org/10.1107/S0021889813003531)

PowderLine drives GSAS-II through its scripting interface, so please also cite:

> J. H. O'Donnell, R. B. Von Dreele, M. K. Y. Chan, and B. H. Toby. *A
> scripting interface for GSAS-II.* J. Appl. Cryst. **51**, 1244–1250 (2018).
> [doi:10.1107/S1600576718008075](https://doi.org/10.1107/S1600576718008075)

**TOPAS** (`engine="topas"`):

> A. A. Coelho. *TOPAS and TOPAS-Academic: an optimization program integrating
> computer algebra and crystallographic objects written in C++.* J. Appl.
> Cryst. **51**, 210–218 (2018).
> [doi:10.1107/S1600576718000183](https://doi.org/10.1107/S1600576718000183)

**easydiffraction** (`engine="easydiffraction"`): the easydiffraction project
asks you to cite the specific version you used, through its
[Zenodo archive](https://doi.org/10.5281/zenodo.16806521) (all versions).
PowderLine's `easydiff` environment currently installs version 0.20.1:

> A. Sazonov, E. Lindgren, P. Rozyczko, and M. Seth. *easydiffraction 0.20.1.*
> Zenodo (2026).
> [doi:10.5281/zenodo.21999827](https://doi.org/10.5281/zenodo.21999827)

## Materials Project

If you simulate patterns from Materials Project data (`pixi run mp-simulate`),
please also cite Materials Project — see
[Simulating Patterns from Materials Project](mp-simulation.md#citation).
