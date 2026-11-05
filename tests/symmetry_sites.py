"""Test helper: enumerate every distinct special site of a space group on the 1/24 grid."""

from __future__ import annotations

import itertools

import gemmi
import numpy as np


def distinct_special_sites(sg: gemmi.SpaceGroup) -> list[tuple[int, int, int]]:
    """One grid point (in 1/24 units) per distinct site stabilizer met on the 1/24 grid.

    Exact: integer arithmetic mod 24 (gemmi's ``Op.DEN`` is 24). Every fixed
    special-position coordinate is a multiple of 1/24, so each stabilizer
    (each orientation of each Wyckoff site) is met.
    """
    grid = np.array(list(itertools.product(range(24), repeat=3)), dtype=np.int64)
    ops = list(sg.operations())
    rots = np.array([op.rot for op in ops], dtype=np.int64) // gemmi.Op.DEN
    trans = np.array([op.tran for op in ops], dtype=np.int64) * 24 // gemmi.Op.DEN
    fixed = np.all((np.einsum("nij,pj->pni", rots, grid) + trans[None]) % 24 == grid[:, None, :], axis=2)
    special = np.nonzero(fixed.sum(axis=1) > 1)[0]
    _, first = np.unique(fixed[special], axis=0, return_index=True)
    return [tuple(int(v) for v in grid[p]) for p in special[np.sort(first)]]
