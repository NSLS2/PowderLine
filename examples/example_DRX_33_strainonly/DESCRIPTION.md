# Strain-only variant of DRX_33: crystallite size fixed, microstrain refined

## Scientific Purpose

This example is a re-parameterization of `example_DRX_33` (the same two-phase
disordered-rocksalt battery material — a face-centred-cubic DRX main phase,
space group Fm-3m / No. 225, plus a monoclinic Li4MgWO6 secondary phase, space
group C2/m / No. 12). Everything about the data, structures, and instrument is
identical; only the **peak-broadening parameterization** changes.

In the base example both **size** and **strain** broadening are refined per
phase. That refinement is ill-conditioned over this limited 1-15 deg 2-theta,
low-Q synchrotron range (lambda = 0.1665 A): size and strain broadening are
strongly correlated, so the isotropic size parameters run away. In the
committed base reference the DRX size ends near 253 um with a runaway
LG-mixing coefficient (about 15 000), and the Li4MgWO6 size goes negative
(about −1356 um). Neither refined crystallite size is physically meaningful.
The base example is kept as a teaching example of this posing.

This variant removes that degeneracy: **crystallite size is fixed** (10 um,
LG_eta = 1.0, both held) so no size broadening is refined, and **only the strain
broadening is refined** per phase. The goal is a well-conditioned width
determination and a defensible microstrain value for each phase, for use in a
publication table / fit figure.

## Change in parameterization (vs. `example_DRX_33`)

| Parameter | `example_DRX_33` | this example |
|---|---|---|
| Size `isotropic_size` | refined (starts 1 um) | **fixed at 10 um** |
| Size `LG_eta` | refined (starts 1) | **fixed at 1.0** |
| Strain `isotropic_strain` | refined | refined |
| Strain `LG_eta` | refined | refined |
| Lattice parameters | refined | refined |
| Phase scale factors | refined | refined |
| Chebyshev background (6 terms) | refined | refined |
| Atomic coords / occ / ADP | fixed | fixed |
| Instrument parameters | fixed | fixed |

Concretely, each phase's `peak_broadening.size_broadening` is set to
`isotropic_size = [10, false]` and `LG_eta = [1, false]`;
`strain_broadening` is unchanged from the base recipe.

## Input Parameters

- **Data source**: file-less payload — the JSON carries the diffraction data,
  instrument parameters, and structures (same embedded data as `example_DRX_33`).
- **Phases refined**: DRX (Fm-3m, cubic) and Li4MgWO6 (C2/m, monoclinic).
- **Refined**: lattice parameters, phase scale factors, phase strain broadening
  (`isotropic_strain` + strain `LG_eta`), and a 6-term Chebyshev background.
- **Fixed**: crystallite size (10 um) and size `LG_eta` (1.0), instrument
  parameters, atomic positions, occupancies, and ADPs.
- **Starting values**: lattice parameters and coordinates from the same CIFs as
  the base example; strain (mustrain) starts at 1 with strain `LG_eta` = 1.
- **Special GSAS-II settings**: none.

## Expected Behavior

- **Convergence**: the refinement converges in a few cycles. Because both the
  isotropic strain magnitude and the strain LG-mixing term are refined, the two
  are fully correlated and GSAS-II reports a soft (SVD) singularity — see
  *Known Issues*. The reported equatorial microstrain (which combines them) is
  stable regardless.
- **Fit quality**: **Rwp = 8.46%, GOF = 0.86** (chi**2 = 2781.62 on 3767
  observations: the native path fits exactly 1 ≤ 2θ ≤ 15). This is an improvement over the base example (Rwp = 10.83%,
  GOF = 1.10): removing the ill-conditioned size parameters yields a cleaner fit.
  GOF < 1 indicates the profile ESDs are mildly overestimated.
- **Refined values (with ESDs)**:

  Phase 1 — DRX (Fm-3m, cubic):
  - a = 4.1832(7) A;  V = 73.204(36) A^3
  - microstrain = 133.0(3.5) x10^-6  = 0.0133(4) %
  - weight fraction = 32.0(7) %
  - crystallite size = 10 um (fixed, not refined)

  Phase 2 — Li4MgWO6 (C2/m, monoclinic):
  - a = 5.1301(24) A;  b = 8.7881(5) A;  c = 5.1024(23) A;  beta = 110.791(6) deg;
    V = 215.057(16) A^3
  - microstrain = 109.8(0.9) x10^-6  = 0.0110(1) %
  - weight fraction = 68.0(7) %
  - crystallite size = 10 um (fixed, not refined)

  Compared with the base (size + strain) refinement, the DRX microstrain is
  consistent within ~1 sigma but far better constrained (sigma 20 -> 3.5 x10^-6),
  and the Li4MgWO6 microstrain increases from ~88 to ~110 x10^-6 because strain
  now accounts for the full peak width the railed size parameter had absorbed.

- **Typical runtime**: less than 10 seconds.
- **Normal warnings**: see *Known Issues* (the strain i/mx SVD singularity is
  expected and benign here).

## Output Files

Same standardized outputs as `example_DRX_33`:

- **dummy.gpx** - GSAS-II project file (reopenable in the GUI; gitignored).
- **dummy.lst** - human-readable refinement log with Rwp and parameter tables.
- **refined_parameters.csv** - all refined parameters with ESDs.
- **DRX_33_unit_cell_report.csv** / **Li4MgWO6_SG12_unit_cell_report.csv** -
  per-phase unit-cell parameters with ESDs.
- **DRX_33_peak_list_report.csv** / **Li4MgWO6_SG12_peak_list_report.csv** -
  per-phase reflection lists (hkl, d-spacing, 2-theta, intensities).
- **fit_profile.txt** - observed / calculated / background / difference intensities.
- **output_recipe.json** - The resolved recipe with the refined values written back (KI-04); `metadata.powderline_provenance` names the run
- **parameter_dispositions.csv** - One row per refinable value: path, value, esd, disposition (`varied`, `held_by_user`, `held_by_symmetry`, `default_applied`, ...), at_limit

## Reproduce

```bash
pixi run -e gsasii powderline examples/example_DRX_33_strainonly/input.json --no-server --output my_strainonly
```

Your results are then in `my_strainonly/`. Writing into
`examples/example_DRX_33_strainonly/output` regenerates the committed
reference; do that only as a deliberate, reviewed change.

## Known Issues

GSAS-II reports 2 soft (SVD) Hessian singularities:

```
SVD problem(s) likely from:
0:0:Mustrain;i, 1:0:Mustrain;i
Note highly correlated parameters:
 ** 0:0:Mustrain;mx and 0:0:Mustrain;i (@100.00%)
 ** 1:0:Mustrain;mx and 1:0:Mustrain;i (@100.00%)
```

These arise because each phase's isotropic strain magnitude (`Mustrain;i`) and
its Lorentzian-Gaussian mixing term (`Mustrain;mx`) are 100% correlated — the
strain LG-mixing is not independently determinable from this data. The reported
equatorial microstrain is stable. To eliminate the warning entirely, additionally
fix the strain `LG_eta` (set `strain_broadening.LG_eta = [1, false]`)
and refine only `isotropic_strain`.

## Refine flags (gsasii 0.1.0)

Every refinable parameter is `[value, refine_flag]` (no bounds: GSAS-II applies
limits only after a fit); a parameter refines iff its flag is `true`. The gsasii
schema checks the flags against the symmetry and GSAS-II's own parameter groups
when the recipe is validated: a refined strict subset of a tie group (e.g. only
`a` of a cubic cell) or a refined symmetry-fixed parameter is an error, so the
recipe states exactly what GSAS-II refines. This example uses that mechanism directly: the size parameters are
present with `refine_flag=false`, pinning crystallite size while strain refines.

## Data citation

The diffraction data in this example (the disordered-rocksalt cathode
material, "DRX_33") is from the study available at
[doi:10.26434/chemrxiv.15003271/v1](https://doi.org/10.26434/chemrxiv.15003271/v1)
(preprint; to appear in a peer-reviewed publication). Please cite that work
when using this dataset.
