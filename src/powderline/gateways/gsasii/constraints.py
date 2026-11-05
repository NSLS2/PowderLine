"""Per-parameter refine-flag translation for GSAS-II.

GSAS-II exposes only lumped refine flags for three parameter classes: one flag
for the whole unit cell (``General['Cell'][0]``), one ``'X'`` flag per atom for
all three coordinates, and one ``'U'`` flag per atom for all six anisotropic
displacement components. PowderLine recipes carry *per-parameter* flags. This
module computes, for each class, (a) whether the lumped GSAS-II flag must be
set and (b) which GSAS-II "Hold" constraints must be emitted so that only the
requested parameters actually refine.

Normative semantics:

- A parameter is *requested* iff it is present with ``refine_flag=true``.
- Absent, ``None``, or ``refine_flag=false`` means fixed (held).
- Parameters partition into degree-of-freedom (DOF) groups; a group refines iff
  ANY member is requested (group-OR). Flags on symmetry-fixed parameters have
  no effect (there is no degree of freedom to control).
- PowderLine performs no flag/symmetry consistency validation - producing
  symmetry-consistent flags is the upstream recipe builder's job. For a
  well-formed recipe the translation is exact; for mixed flags within a group
  the group-OR interpretation is deterministic and documented
  (docs/known_issues.md, KI-02).

The DOF-group structure mirrors GSAS-II's own machinery at the pinned commit:

- Unit cell: ``GSASIIstrIO.cellVary``'s per-Laue-class A-term dispatch, plus
  direct<->reciprocal coupling analysis - oblique cells couple direct
  parameters, so monoclinic {a, c, oblique angle} and the whole triclinic /
  rhombohedral-axes cell each form a single group (verified empirically
  against the pinned GSAS-II).
- Coordinates / anisotropic Uij: the site-symmetry tables
  ``GSASIIspc.GetCSxinel`` / ``GetCSuinel``, used exactly as
  ``GSASIIstrIO.GetPhaseData`` uses them, including the KeyError ->
  ``SytSym``-recompute patch for stale/blank site-symmetry strings.

Hold variable names follow GSAS-II conventions: ``{p}::A{n}`` for cell terms,
``{p}::dAx:{i}`` / ``dAy`` / ``dAz`` for coordinate shifts, and
``{p}::AU11:{i}`` ... ``AU23:{i}`` for anisotropic components (verified by
probes 2, 3, and 5).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

from GSASII import GSASIIspc as G2spc


@dataclass
class CellPlan:
    """Result of translating unit-cell per-parameter flags."""
    refine_cell: bool
    holds: list[str] = field(default_factory=list)


@dataclass
class AtomPlan:
    """Result of translating one atom's per-parameter flags.

    ``refine_flags`` is the GSAS-II atom flag string ('F', 'X', 'U' pieces in
    that order); ``holds`` are GSAS-II variable names to Hold.
    """
    refine_flags: str
    holds: list[str] = field(default_factory=list)


_CELL_PARAMS = ("a", "b", "c", "alpha", "beta", "gamma")
_COORD_PARAMS = ("x", "y", "z")
_DA_NAMES = ("dAx", "dAy", "dAz")
_UIJ_PARAMS = ("U11", "U22", "U33", "U12", "U13", "U23")
_AU_NAMES = ("AU11", "AU22", "AU33", "AU12", "AU13", "AU23")


def _is_requested(param: Any) -> bool:
    """True iff a [value, refine_flag, min, max] entry requests refinement."""
    return (
        param is not None
        and isinstance(param, (list, tuple))
        and len(param) >= 2
        and bool(param[1])
    )


def cell_dof_groups(SGData: dict) -> list[tuple[tuple[str, ...], tuple[int, ...]]]:
    """DOF-groups for the unit cell of a phase with symmetry ``SGData``.

    Returns a list of ``(direct_parameters, independent_A_term_indices)``
    pairs. Holding all listed A-terms of a group fixes exactly that group's
    direct parameters (slaved A-terms - e.g. A1 for tetragonal - are covered
    by GSAS-II's symmetry-equivalence cascade and need no explicit hold).

    The dispatch mirrors ``GSASIIstrIO.cellVary`` (pinned commit, lines
    997-1024); the grouping of oblique parameters follows findings.md
    section C.6.
    """
    laue = SGData["SGLaue"]
    if laue in ("m3m", "m3"):
        return [(("a", "b", "c"), (0,))]
    if laue in ("4/m", "4/mmm"):
        return [(("a", "b"), (0,)), (("c",), (2,))]
    if laue in ("6/m", "6/mmm", "3", "3m1", "31m"):
        return [(("a", "b"), (0,)), (("c",), (2,))]
    if laue in ("3R", "3mR"):
        # Rhombohedral axes: a(=b=c) and alpha(=beta=gamma) are coupled through
        # both independent A-terms (A0 and A3) -> one all-or-nothing group.
        return [(_CELL_PARAMS, (0, 3))]
    if laue == "mmm":
        return [(("a",), (0,)), (("b",), (1,)), (("c",), (2,))]
    if laue == "2/m":
        uniq = SGData.get("SGUniq")
        if uniq == "a":
            return [(("a",), (0,)), (("b", "c", "alpha"), (1, 2, 5))]
        if uniq == "b":
            return [(("b",), (1,)), (("a", "c", "beta"), (0, 2, 4))]
        # cellVary's else-branch: anything other than 'a'/'b' (SpcGroup always
        # emits a/b/c for 2/m) dispatches as unique axis c (oblique gamma, A3)
        return [(("c",), (2,)), (("a", "b", "gamma"), (0, 1, 3))]
    if laue == "-1":
        return [(_CELL_PARAMS, (0, 1, 2, 3, 4, 5))]
    raise ValueError(f"Unrecognized Laue class {laue!r} in SGData")


def cell_refinement_plan(
    SGData: dict, unit_cell_params: dict | None, phase_idx: int
) -> CellPlan:
    """Translate per-parameter unit-cell flags into (Cell flag, holds).

    Args:
        SGData: the phase's GSAS-II space-group data dict
            (``proj.data['Phases'][name]['General']['SGData']``).
        unit_cell_params: the recipe's ``parameterization.unit_cell`` dict
            mapping parameter names to ``[value, refine_flag, min, max]``
            lists (entries and the dict itself may be None/absent).
        phase_idx: the phase's index in the project (for variable naming).

    Returns:
        CellPlan. ``refine_cell`` is True iff at least one DOF-group has a
        requested member; ``holds`` lists the independent A-term variables of
        the *unrefined* groups (empty when ``refine_cell`` is False - a fixed
        cell needs no holds).
    """
    unit_cell_params = unit_cell_params or {}
    requested = {
        p for p in _CELL_PARAMS if _is_requested(unit_cell_params.get(p))
    }
    groups = cell_dof_groups(SGData)
    refining = [any(p in requested for p in params) for params, _ in groups]
    if not any(refining):
        return CellPlan(refine_cell=False)
    holds = [
        f"{phase_idx}::A{n}"
        for (params, a_terms), on in zip(groups, refining)
        if not on
        for n in a_terms
    ]
    return CellPlan(refine_cell=True, holds=holds)


def _site_ids(
    table_lookup,
    site_sym: str,
    xyz: Sequence[float] | None,
    SGData: dict | None,
):
    """Site-symmetry table lookup with GSAS-II's own KeyError patch.

    Mirrors GSASIIstrIO.GetPhaseData (pinned commit, lines 1742-1747): valid
    keys are the *oriented* strings SytSym emits (e.g. '4mm(z)'); on a stale
    or blank key, recompute the site symmetry from the coordinates.
    """
    try:
        return table_lookup(site_sym)[0]
    except KeyError:
        if xyz is None or SGData is None:
            raise
        recomputed = G2spc.SytSym(list(xyz), SGData)[0]
        return table_lookup(recomputed)[0]


def _free_groups(ids: Sequence[int]) -> list[list[int]]:
    """Group parameter indices by shared nonzero site-symmetry id.

    Id 0 means fixed-by-symmetry (no DOF); equal nonzero ids are one coupled
    DOF-group (e.g. x=y on an (x,x,z) site).
    """
    groups: dict[int, list[int]] = {}
    for i, gid in enumerate(ids):
        if gid > 0:
            groups.setdefault(gid, []).append(i)
    return list(groups.values())


def atom_refinement_plan(
    atom_params: dict,
    site_sym: str,
    phase_idx: int,
    atom_idx: int,
    xyz: Sequence[float] | None = None,
    SGData: dict | None = None,
) -> AtomPlan:
    """Translate one atom's per-parameter flags into (flag string, holds).

    Args:
        atom_params: the recipe's per-atom parameterization dict (keys 'x',
            'y', 'z', 'occupancy', 'ADP', 'Uiso', 'Uaniso').
        site_sym: the atom's oriented site-symmetry string
            (``atom_record[7]``).
        phase_idx / atom_idx: for GSAS-II variable naming.
        xyz / SGData: coordinates and space-group data, used only to recompute
            a stale/blank ``site_sym`` (GSAS-II's own patch behavior).

    Returns:
        AtomPlan. Flag characters appear in GSAS-II's 'F','X','U' order. Holds
        are emitted only for *free* (symmetry-allowed) DOF-groups with no
        requested member, and only when the corresponding lumped flag is set.
    """
    flags = ""
    holds: list[str] = []

    # Occupancy ('F') is a single parameter - already faithful, no holds.
    if _is_requested(atom_params.get("occupancy")):
        flags += "F"

    # Coordinates ('X'): group by site symmetry, group-OR, hold the rest.
    requested_coords = {
        i for i, p in enumerate(_COORD_PARAMS)
        if _is_requested(atom_params.get(p))
    }
    if requested_coords:
        ids = _site_ids(G2spc.GetCSxinel, site_sym, xyz, SGData)
        groups = _free_groups(ids)
        refining = [any(i in requested_coords for i in g) for g in groups]
        if any(refining):
            flags += "X"
            holds += [
                f"{phase_idx}::{_DA_NAMES[i]}:{atom_idx}"
                for g, on in zip(groups, refining)
                if not on
                for i in g
            ]

    # Displacement ('U'): Uiso is a single parameter; Uaniso groups like coords.
    adp_type = atom_params.get("ADP")
    if adp_type == "Uiso":
        if _is_requested(atom_params.get("Uiso")):
            flags += "U"
    elif adp_type == "Uaniso":
        uaniso = atom_params.get("Uaniso") or {}
        requested_uij = {
            i for i, p in enumerate(_UIJ_PARAMS)
            if isinstance(uaniso, dict) and _is_requested(uaniso.get(p))
        }
        if requested_uij:
            ids = _site_ids(G2spc.GetCSuinel, site_sym, xyz, SGData)
            groups = _free_groups(ids)
            refining = [any(i in requested_uij for i in g) for g in groups]
            if any(refining):
                flags += "U"
                holds += [
                    f"{phase_idx}::{_AU_NAMES[i]}:{atom_idx}"
                    for g, on in zip(groups, refining)
                    if not on
                    for i in g
                ]

    return AtomPlan(refine_flags=flags, holds=holds)
