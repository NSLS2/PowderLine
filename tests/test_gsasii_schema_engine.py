"""The gsasii schema's engine-free GSAS-II rules, proven against GSAS-II itself (re/04).

- Space-group translation (A105, EB-03, EB-41): every canonical name the schema
  accepts reads in GSAS-II as the same setting (a general position's orbit from
  ``G2spc.SpcGroup`` + ``GenAtom`` equals gemmi's), and every name it refuses is
  an origin-1 setting or one GSAS-II does not read as itself.
- Cell refinement groups (A95): ``gsasii_cell_groups`` equals the frozen
  ``constraints.cell_dof_groups`` (GSAS-II's own ``cellVary`` dispatch) for
  every accepted setting.

Needs GSAS-II; skipped where it is not installed.
"""

from __future__ import annotations

from pathlib import Path

import gemmi
import numpy as np
import pytest

pytestmark = pytest.mark.gsasii

G2spc = pytest.importorskip("GSASII.GSASIIspc")

from powderline.gateways.gsasii.constraints import cell_dof_groups  # noqa: E402
from powderline.gateways.gsasii.schema import (  # noqa: E402
    GSASII_UNREADABLE_SETTINGS,
    gsasii_cell_groups,
    gsasii_space_group,
)

CANONICAL = [line.strip() for line in
             (Path(__file__).parent / "data" / "canonical_space_groups.txt").read_text(encoding="utf-8").splitlines()
             if line.strip()]
GENERAL = (0.1234, 0.2718, 0.3141)


def _same_set(a, b) -> bool:
    def has(points, p):
        return any(np.allclose(((p - q + 0.5) % 1.0) - 0.5, 0.0, atol=1e-6) for q in points)
    return len(a) == len(b) and all(has(b, p) for p in a)


def _gemmi_orbit(name: str) -> list:
    points = []
    for op in gemmi.find_spacegroup_by_name(name).operations():
        p = np.array(op.apply_to_xyz(list(GENERAL))) % 1.0
        if not any(np.allclose(((p - q + 0.5) % 1.0) - 0.5, 0.0, atol=1e-6) for q in points):
            points.append(p)
    return points


def _gsasii_reads_as_itself(symbol: str, name: str) -> bool:
    err, sgdata = G2spc.SpcGroup(symbol)
    if err:
        return False
    return _same_set(_gemmi_orbit(name), [np.array(r[0]) % 1.0 for r in G2spc.GenAtom(GENERAL, sgdata)])


def _accepted(name: str) -> str | None:
    try:
        return gsasii_space_group(name)
    except ValueError:
        return None


def test_every_canonical_name_is_accepted_or_refused_for_a_reason():
    accepted = [n for n in CANONICAL if _accepted(n) is not None]
    refused = sorted(set(CANONICAL) - set(accepted))
    assert len(CANONICAL) == 564 and len(accepted) == 522
    assert refused == sorted([n for n in CANONICAL if n.endswith(":1")] + list(GSASII_UNREADABLE_SETTINGS))


@pytest.mark.parametrize("name", [n for n in CANONICAL if _accepted(n) is not None])
def test_accepted_setting_reads_as_itself_in_gsasii(name):
    assert _gsasii_reads_as_itself(gsasii_space_group(name), name)


@pytest.mark.parametrize("name", sorted(GSASII_UNREADABLE_SETTINGS))
def test_refused_setting_is_not_read_as_itself_by_gsasii(name):
    symbol = gemmi.find_spacegroup_by_name(name).hm
    assert not _gsasii_reads_as_itself(symbol, name)


@pytest.mark.parametrize("name", [n for n in CANONICAL if _accepted(n) is not None])
def test_cell_groups_match_gsasii(name):
    err, sgdata = G2spc.SpcGroup(gsasii_space_group(name))
    assert not err
    gsasii = {tuple(sorted(group)) for group, _terms in cell_dof_groups(sgdata)}
    assert {tuple(sorted(group)) for group in gsasii_cell_groups(name)} == gsasii
