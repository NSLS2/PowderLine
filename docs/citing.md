# Citing PowderLine

If you use PowderLine in your research, please cite the preprint:

> A. A. Corrao, J. A. Perez, J. D. Langhout, M. M. Butala, T. A. Caswell, and
> D. Olds. *PowderLine: a programmatic powder diffraction analysis application.*
> arXiv:2608.17009 (2026).
> [doi:10.48550/arXiv.2608.17009](https://doi.org/10.48550/arXiv.2608.17009)

Machine-readable metadata, including every reference on this page, is in
[`CITATION.cff`](https://github.com/NSLS2/PowderLine/blob/main/CITATION.cff).

## Cite the refinement engine too

PowderLine drives an underlying refinement engine: the one your recipe's
`schema_name` names. Please cite the engine you used in addition to
PowderLine. The versions below are the ones PowderLine 0.2.0 supports (see
[Engine versions](engine-versions.md)).

**GSAS-II** (`gsasii.rietveld`, `gsasii.spf`; GSAS-II 5.7.9 in the `gsasii`
environment):

> B. H. Toby and R. B. Von Dreele. *GSAS-II: the genesis of a modern
> open-source all purpose crystallography software package.* J. Appl. Cryst.
> **46**, 544–549 (2013).
> [doi:10.1107/S0021889813003531](https://doi.org/10.1107/S0021889813003531)

PowderLine drives GSAS-II through its scripting interface, so please also cite:

> J. H. O'Donnell, R. B. Von Dreele, M. K. Y. Chan, and B. H. Toby. *A
> scripting interface for GSAS-II.* J. Appl. Cryst. **51**, 1244–1250 (2018).
> [doi:10.1107/S1600576718008075](https://doi.org/10.1107/S1600576718008075)

**TOPAS** (`topas.rietveld`, `topas.spf`; TOPAS 6):

> A. A. Coelho. *TOPAS and TOPAS-Academic: an optimization program integrating
> computer algebra and crystallographic objects written in C++.* J. Appl.
> Cryst. **51**, 210–218 (2018).
> [doi:10.1107/S1600576718000183](https://doi.org/10.1107/S1600576718000183)

**easydiffraction** (`easydiffraction.rietveld`): the easydiffraction project
asks you to cite the specific version you used, through its
[Zenodo archive](https://doi.org/10.5281/zenodo.16806521) (all versions).
PowderLine's `easydiffraction` environment installs version 0.21.1:

> A. Sazonov, E. Lindgren, P. Rozyczko, and M. Seth. *easydiffraction 0.21.1.*
> Zenodo (2026).
> [doi:10.5281/zenodo.22905049](https://doi.org/10.5281/zenodo.22905049)

An `easydiffraction.rietveld` recipe also names the calculator that computes
the pattern (`refinement_controls.calculator`); please cite it as well.

- **CrysPy** (`calculator: "cryspy"`; CrysPy 0.13.0 in PowderLine's lock
  file). CrysPy's own preferred citation is:

  > I. A. Kibalin and A. Gukasov. *Local magnetic anisotropy by polarized
  > neutron powder diffraction: Application of magnetically induced preferred
  > crystallite orientation.* Phys. Rev. Research **1**, 033100 (2019).
  > [doi:10.1103/PhysRevResearch.1.033100](https://doi.org/10.1103/PhysRevResearch.1.033100)

- **CrysFML** (`calculator: "crysfml"`): the CrysFML2008 crystallographic
  Fortran library by J. Rodríguez-Carvajal, J. Gonzalez-Platas and
  N. Ayape Katcho, which easydiffraction uses through the `crysfml` Python
  package (0.8.0 in PowderLine's lock file). Source:
  [code.ill.fr/scientific-software/CrysFML2008](https://code.ill.fr/scientific-software/CrysFML2008);
  Python package:
  [github.com/easyscience/deps-pycrysfml](https://github.com/easyscience/deps-pycrysfml).

## Space-group symmetry: gemmi

Every recipe, for every engine, is checked against the space group by
[gemmi](https://gemmi.readthedocs.io) (pinned to 0.7.5): the canonical
space-group names, the symmetry operations, special positions and tie groups.
If your work relies on those checks, please cite:

> M. Wojdyr. *GEMMI: A library for structural biology.* J. Open Source Softw.
> **7**(73), 4200 (2022).
> [doi:10.21105/joss.04200](https://doi.org/10.21105/joss.04200)
