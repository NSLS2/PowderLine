"""Shared helper for the ionic-type gate (P-47): per-reflection net peak areas of a calculated pattern."""
from __future__ import annotations

import numpy as np


def peak_areas(two_theta, y_calc, y_bkg, centres, half_width=0.12):
    """Background-subtracted area under ``y_calc`` within ``centres +- half_width`` degrees, per centre.

    The window is narrow on purpose: the ionic gate compares *ratios* of two calculations with the same
    profile, so the tail fraction a window misses cancels exactly within an engine and nearly so between
    engines (both ratios are taken at the same centres)."""
    tth = np.asarray(two_theta, dtype=float)
    net = np.asarray(y_calc, dtype=float) - np.asarray(y_bkg, dtype=float)
    out = []
    for c in centres:
        m = (tth > c - half_width) & (tth < c + half_width)
        out.append(float(np.trapezoid(net[m], tth[m])) if m.any() else float("nan"))
    return np.array(out)


def resolved(centres, min_separation=0.3):
    """Indices of centres whose nearest neighbour is at least ``min_separation`` degrees away."""
    centres = np.asarray(centres, dtype=float)
    keep = []
    for i, c in enumerate(centres):
        others = np.delete(centres, i)
        if others.size == 0 or np.min(np.abs(others - c)) >= min_separation:
            keep.append(i)
    return keep


def cubic_equivalents(h, k, l):
    """All permutations and sign changes of (h, k, l): the m-3m equivalents (right for LaB6, P m -3 m)."""
    import itertools
    out = set()
    for perm in itertools.permutations((h, k, l)):
        for signs in itertools.product((1, -1), repeat=3):
            out.add(tuple(int(p) * s for p, s in zip(perm, signs)))
    return sorted(out)


def dollase_correction(hkl, axis, r, equivalents=cubic_equivalents):
    """March-Dollase correction for reflection ``hkl`` in GSAS-II's convention (``GSASIIstrMath.GetPrefOri``):
    ``A = 1 / sqrt((r cos P)^2 + sin^2 P / r)``, ``A^3`` averaged over the reflection's equivalents, ``P`` the
    angle between each equivalent and the texture ``axis`` (a cubic cell: direct = reciprocal directions).
    r = 1 gives 1 everywhere; r < 1 platy, r > 1 needle."""
    ax = np.asarray(axis, dtype=float); ax = ax / np.linalg.norm(ax)
    total = 0.0
    eq = equivalents(*hkl)
    for e in eq:
        v = np.asarray(e, dtype=float); cosp = abs(float(v @ ax)) / np.linalg.norm(v); cosp = min(cosp, 1.0)
        sinp = np.sqrt(1.0 - cosp * cosp)
        total += (1.0 / np.sqrt((r * cosp) ** 2 + sinp ** 2 / r)) ** 3
    return total / len(eq)
