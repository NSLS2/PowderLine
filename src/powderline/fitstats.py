"""Uniform fit statistics computed once in core (master plan A23, A41, A45).

Every gateway reports the same standard keys (Rwp, Rexp, GoF, reduced χ²)
computed here from the observed/calculated profile, so the numbers mean the
same thing whichever engine ran. Engine-reported values are preserved
separately (``engine_details``); how and why they differ is documented, not
hidden.

Formulas (the user-docs formulas), with sums over the included points ``i``::

    Rwp    = 100 · sqrt( Σ w_i (yobs_i − ycalc_i)² / Σ w_i yobs_i² )      [%]
    Rexp   = 100 · sqrt( (N − P) / Σ w_i yobs_i² )                         [%]
    GoF    = Rwp / Rexp = sqrt( Σ w_i (yobs_i − ycalc_i)² / (N − P) )
    χ²_red = Σ w_i (yobs_i − ycalc_i)² / (N − P)          (= GoF²)

- **Included points / N**: inside the fit-range ``mask`` *and* with
  ``w_i > 0``. Excluded and out-of-range points are left out of N and the sums
  (the convention across GSAS-II, TOPAS and FullProf). Zero-weight points are
  also left out: they add no equation to the weighted least-squares problem, so
  they add no degree of freedom. GSAS-II counts in-range zero-weight points in
  its ``Nobs``; see ``tasks/fitstats-n-convention.md`` in the dossier.
- **P** (``n_params``): the engine's own count of independently varied
  parameters after engine-applied constraints, read from the engine **after the
  run** (A41, A45) — never derived from recipe refine flags. Each gateway
  supplies it.
- R factors are in percent; GoF and χ²_red are dimensionless.
- Undefined values are ``nan``: Rexp, GoF and χ²_red when ``N − P <= 0``;
  Rwp and Rexp when ``Σ w yobs² == 0``.

Pure numpy; imports no engine.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np


@dataclass(frozen=True)
class FitStatistics:
    """Standard fit statistics; see the module docstring for the formulas."""

    rwp: float
    rexp: float
    gof: float
    chi2_red: float
    n_points: int
    n_params: int


def compute_fit_statistics(yobs, ycalc, weights, n_params: int,
                           mask: Optional[np.ndarray] = None) -> FitStatistics:
    """Compute Rwp, Rexp, GoF and reduced χ² over the included points.

    Args:
        yobs, ycalc, weights: 1-D arrays of equal length (weights ``>= 0``).
        n_params: P, the engine-reported number of varied parameters.
        mask: optional boolean array, True = inside the fit range; default all
            points.

    Raises:
        ValueError: on mismatched shapes, negative weights, a negative
            ``n_params``, or non-finite values among the included points.
    """
    yobs = np.asarray(yobs, dtype=float)
    ycalc = np.asarray(ycalc, dtype=float)
    weights = np.asarray(weights, dtype=float)
    if yobs.ndim != 1 or yobs.shape != ycalc.shape or yobs.shape != weights.shape:
        raise ValueError("yobs, ycalc and weights must be 1-D arrays of equal length")
    if mask is None:
        mask = np.ones(yobs.shape, dtype=bool)
    else:
        mask = np.asarray(mask, dtype=bool)
        if mask.shape != yobs.shape:
            raise ValueError("mask must have the same length as yobs")
    if int(n_params) != n_params or n_params < 0:
        raise ValueError(f"n_params must be a non-negative integer, got {n_params!r}")
    n_params = int(n_params)
    # Check weights over the whole fit range *before* the w > 0 filter: NaN > 0
    # is False, so a NaN weight would otherwise be silently dropped from N.
    if not np.all(np.isfinite(weights[mask])):
        raise ValueError("yobs, ycalc and weights must be finite inside the fit range")
    if np.any(weights[mask] < 0):
        raise ValueError("weights must be >= 0")

    included = mask & (weights > 0)
    yo, yc, w = yobs[included], ycalc[included], weights[included]
    if not (np.all(np.isfinite(yo)) and np.all(np.isfinite(yc))):
        raise ValueError("yobs, ycalc and weights must be finite inside the fit range")

    n_points = int(included.sum())
    sum_wyo2 = float(np.sum(w * yo**2))
    sum_wr2 = float(np.sum(w * (yo - yc) ** 2))
    dof = n_points - n_params

    rwp = 100.0 * np.sqrt(sum_wr2 / sum_wyo2) if sum_wyo2 > 0 else float("nan")
    rexp = 100.0 * np.sqrt(dof / sum_wyo2) if (sum_wyo2 > 0 and dof > 0) else float("nan")
    chi2_red = sum_wr2 / dof if dof > 0 else float("nan")
    gof = float(np.sqrt(chi2_red)) if dof > 0 else float("nan")
    return FitStatistics(rwp=float(rwp), rexp=float(rexp), gof=gof, chi2_red=float(chi2_red),
                         n_points=n_points, n_params=n_params)
