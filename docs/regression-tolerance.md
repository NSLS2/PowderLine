# Regression tolerance study — cross-build drift

Purpose: choose the numeric tolerances for the GSAS-II regression tests
(`refined_parameters.csv`, `*_unit_cell_report.csv`) that absorb **cross-build /
cross-OS** floating-point drift while still catching real code regressions.

Key premise (established by the Windows/Linux cross-platform validation runs):
refinements are **byte-deterministic per machine** (same input → byte-identical
output on repeated runs). Therefore there is **no run-to-run scatter to measure**; the meaningful
quantity is the **cross-build delta** between a platform's output and the committed
reference (which was generated on Linux). This document tabulates that delta.

## Method

For each example with a committed `refined_parameters.csv`, run
`pixi run -e gsasii kicker --no-server examples/<name>/input.json --output out_drift/<name>`
and compare the generated `refined_parameters.csv` to the committed reference,
per-parameter, grouped by the `category` column. Metric: relative difference
`|gen - ref| / max(|ref|, 1e-30)` on the `value` and `esd` columns.

## Windows results (Python 3.13.14, GSASII 5.7.9, win-64 source build)

Reference = committed Linux output. Full example set at measurement time
(including several examples that are not part of the public example set); all shapes
matched exactly.

### Per-example overall `value` max relative drift

| Example | value max rel | worst parameter |
|---|---|---|
| example_DRX_33_atomrefine | **2.95e-3** | `0:0:Size;i` |
| example_DRX_33_anisoADP | 3.95e-4 | `1::AU22:4` |
| example_DRX_33 | 1.13e-4 | `0:0:Size;mx` |
| example_DRX_33_strainonly | 8.5e-6 | `:0:Back;2` |
| example_LaB6 | 0 | (identical) |

(The measurement covered a larger example set — several examples not part of the
public example set also reproduced the Linux reference **byte-for-byte**;
`example_LaB6` is the byte-identical case shown here.)

### Per parameter-class max relative drift (across all examples)

| Category | max `value` rel | max `esd` rel |
|---|---|---|
| `other` (size/strain: Size, Mustrain) | **2.95e-3** | 3.6e-4 |
| `atom_occupancy` (Afrac) | 6.2e-4 | 1.5e-4 |
| `atom_displacement_anisotropic` (Uaniso) | 3.9e-4 | 3.9e-6 |
| `atom_displacement_isotropic` (AUiso) | 3.1e-4 | 4.9e-4 |
| `scale` | 9.2e-5 | 1.1e-4 |
| `background` (Chebyshev/Back) | 5.7e-5 | 5.8e-6 |
| `phase_other` (coord shifts dA*) | 4.0e-5 | 2.0e-5 |
| `reciprocal_metric_tensor` (cell A0..A5) | 2.3e-7 | 1.3e-4 |
| `instrument_broadening` (U,V,W,X,Y,Z) | 0 | 1.3e-7 |
| `background_peak` | 0 | 0 |

### Reading

- **Size/strain broadening (`other`)** is the lone outlier at ~3e-3 — expected:
  crystallite-size and microstrain terms are strongly correlated and
  ill-conditioned. It drives the `atomrefine` example's overall drift.
- **Every other class is ≤ 6.2e-4** on `value`; **`esd` ≤ 4.9e-4** everywhere.
- **Cell / reciprocal-metric-tensor terms are ~2e-7** — effectively exact,
  confirming the `unit_cell` report tolerance (`rtol=1e-4`) has enormous margin.

## Chosen tolerances

Implemented in `tests/subprocess_utils.py`:

- `unit_cell_match`: `rtol=1e-4`, `atol=1e-6` — validated (all 30 unit-cell
  comparisons pass; cell drift ~2e-7 gives ~500x margin).
- `refined_params_match`: `rtol=1e-3`, `atol=1e-4` for **all** parameter classes,
  **except** correlated size/strain broadening (category `other`: Size, Mustrain),
  which uses `loose_rtol=1e-2`. Rationale: every non-size/strain class drifts
  <6.2e-4 (`value`) / <4.9e-4 (`esd`) across builds, so the tight default is a
  strong regression guard; correlated size/strain is ill-conditioned (the classic
  size-strain separation problem, plus the poorly-determined Lorentzian/Gaussian
  `;mx` mix terms) and is only reproducible to ~1% (observed max 2.95e-3), so it
  gets ~3.4x margin at 1e-2. The looser tolerance is scoped to that one class so
  well-conditioned parameters keep their tight guard.
- Rwp: `abs < 0.1` pp (observed delta ~0.00).

Validation: with these tolerances all 9 examples' `refined_parameters.csv` and all
30 `*_unit_cell_report.csv` comparisons pass on win-64.

### Follow-up (RESOLVED 2026-08-11): keep the loose tolerance

`example_DRX_33_atomrefine` is the only example needing the loose class tolerance.
Its recipe refines correlated size **and** strain broadening (+ the `;mx` mix terms)
on top of atom parameters, which is inherently ill-posed. Making it well-conditioned
was investigated on Linux and **not adopted as a design decision**; the baseline
recipe + `other → loose_rtol=1e-2` is kept. Evidence (all variants run on linux-64, GSASII
5.7.9):

| Variant | Outcome |
|---|---|
| Fix size = 10 µm, refine strain (mirrors `strainonly`) | **Diverges** — "Invalid cell metric tensor" for phase 0 (DRX_33), cell → −1.48e6 Å, refinement fails, no output |
| Fix size ≈ refined optimum (3.25 / 11.24 µm), refine strain | **Diverges** identically — not a value-tuning issue; removing the refined size DOF destabilizes the simultaneous atom+cell+strain refinement |
| Refine size, fix strain | Converges but Rwp degrades to **14.2%** and `Size;mx` stays pathological (−1352 ± 100) |
| Fix only the `;mx` LG-mix terms, keep size+strain | Converges, Rwp **11.25%** (fit preserved), worst mix terms gone — but size+strain remain co-refined (still needs *some* tolerance, unverifiable cross-build from Linux alone) |

Additionally, at the time **any** edit to this recipe broke two committed TOPAS
goldens of the then-existing unified-schema TOPAS path (a golden INP and a
round-trip against a real Windows TOPAS `_results.csv` under `output/topas/`).
Since the candidate change diverges and every variant entangled the
Windows-only TOPAS path while not cleanly achieving tight-and-good-fit, the
design decision was to keep the baseline recipe and the scoped loose tolerance.
*(Historical note: that TOPAS path and its goldens were removed in 0.2.0; the
native `topas.*` recipes have their own fixtures and TOPAS 6 goldens under
`tests/data/topas/native/`, and the examples carry no TOPAS output. The
tolerance decision stands on the GSAS-II evidence alone.)*

## Linux results (Python 3.13.14, GSASII 5.7.9, linux-64 conda-build)

Reference = committed Linux output. Same example set, run once each (refinements are
byte-deterministic per machine, so a single run fully characterizes the platform —
no N× repeat needed). All shapes/labels matched exactly.

### Per-example overall `value` / `esd` max relative drift (Linux gen vs committed ref)

| Example | value max rel | esd max rel | worst parameter |
|---|---|---|---|
| example_DRX_33_atomrefine | **4.61e-6** | 7.87e-7 | `0:0:Size;i` |
| example_DRX_33 | 0 | 0 | (identical) |
| example_DRX_33_anisoADP | 0 | 0 | (identical) |
| example_DRX_33_strainonly | 0 | 0 | (identical) |
| example_LaB6 | 0 | 0 | (identical) |

**Every measured example except one reproduces the committed reference
byte-for-byte.** The lone non-zero (`atomrefine`, 4.6e-6) is on `0:0:Size;i` —
the same correlated-size term that is worst on Windows — and is non-zero only
because the committed reference was minted on a slightly different Linux build.
All `*_unit_cell_report.csv` comparisons are **exactly 0** (global unit-cell
max rel drift = 0.00e+00).

### Windows-value vs Linux-value (cross-platform delta)

Because the current Linux output equals the committed Linux reference to within
≤4.6e-6, the Windows "vs reference" column above **is** effectively the
Windows↔Linux cross-platform delta. Restating per class:

| Category | Win↔Linux `value` rel (≈ Win vs ref) | Linux vs ref | tight guard (1e-3) margin |
|---|---|---|---|
| `other` (Size, Mustrain) | **2.95e-3** | 4.6e-6 | fails tight → uses `loose_rtol=1e-2` (3.4× margin) |
| `atom_occupancy` (Afrac) | 6.2e-4 | 1.1e-6 | 1.6× |
| `atom_displacement_anisotropic` | 3.9e-4 | 0 | 2.6× |
| `atom_displacement_isotropic` | 3.1e-4 | 7.7e-7 | 3.2× |
| `scale` | 9.2e-5 | 0 | 11× |
| `background` | 5.7e-5 | 1.9e-7 | 18× |
| `phase_other` | 4.0e-5 | 0 | 25× |
| `reciprocal_metric_tensor` (cell) | 2.3e-7 | 0 | 4300× |
| `instrument_broadening` | 0 | 0 | ∞ |
| `background_peak` | 0 | 0 | ∞ |

The drift is **one-sided** in magnitude (Linux≈exact, Windows carries all the
cross-build noise) but the *class ordering* is identical on both platforms:
correlated size/strain is the sole outlier; cell/metric terms are essentially exact.

### Sign-off on tolerances (Linux)

- **`unit_cell_match` `rtol=1e-4, atol=1e-6` — CONFIRMED.** Linux drift is exactly 0
  on all 13 unit-cell reports; Windows is ~2e-7. Margin is ~500× (Windows) to ∞
  (Linux). No change.
- **`refined_params_match` `rtol=1e-3, atol=1e-4` default — CONFIRMED.** Every
  non-`other` class drifts ≤6.2e-4 cross-platform (≥1.6× margin) and ≤1.1e-6 on
  Linux. Holds on both platforms.
- **`other` → `loose_rtol=1e-2` — CONFIRMED.** Windows size/strain drift 2.95e-3
  (3.4× margin); Linux 4.6e-6. The one-class exception is still the minimal loosening
  that admits the correlated size/strain noise without weakening any other guard.
- **Rwp `abs < 0.1` pp — CONFIRMED** (Δ ≈ 0 on Linux).

**Recommendation: keep the shared tolerances as-is; do not adopt a per-OS scheme.**
A per-OS tolerance would only help if the two platforms needed *different* values,
but Linux is a strict subset of Windows drift (Linux ≤ Windows for every class), so
the Windows-sized tolerance already covers both. A single cross-platform tolerance is
simpler and correct.

### LF byte-stability (Linux)

All Linux-generated `refined_parameters.csv`, `*_unit_cell_report.csv`,
`*_peak_list_report.csv`, and `fit_profile.txt` contain **zero** CRLF sequences (pure
LF). Diffs against the committed LF references appear only in numeric `value`/`esd`
fields (and only for `atomrefine`), never in line endings or structure — confirming
the `lineterminator="\n"` / `newline` hardening produces byte-stable output on Linux.
