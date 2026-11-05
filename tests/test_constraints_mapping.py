"""Unit tests for powderline.gateways.gsasii.constraints — per-parameter flag translation.

Covers the DOF-group tables: cell plans for every Laue class
(incl. all monoclinic unique axes and both rhombohedral settings) and atom
plans for representative site symmetries (general position, fixed, partially
fixed, linked coordinates, linked Uij). Expected groupings were verified
empirically against the pinned GSAS-II (cell holds, coordinate holds, oblique
coupling, Uij holds).
"""
import pytest

pytestmark = pytest.mark.gsasii

G2spc = pytest.importorskip("GSASII.GSASIIspc")
from powderline.gateways.gsasii.constraints import (
    AtomPlan,
    CellPlan,
    atom_refinement_plan,
    cell_dof_groups,
    cell_refinement_plan,
)

ON = [None, True, None, None]
OFF = [None, False, None, None]


def sgdata(symbol):
    err, SG = G2spc.SpcGroup(symbol)
    assert not err, G2spc.SGErrors(err)
    return SG


# ---------------------------------------------------------------------------
# Laue-class sanity: our synthetic SGData shortcuts match real SpcGroup output
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("symbol,laue,uniq", [
    ("P m -3 m", "m3m", ""),
    ("P 4/m m m", "4/mmm", ""),
    ("P 6/m m m", "6/mmm", ""),
    ("R -3 c", "3m1", ""),
    ("R -3 c R", "3mR", ""),
    ("P n m a", "mmm", ""),
    ("P 2/m", "2/m", "b"),
    ("P -1", "-1", ""),
])
def test_laue_classes_match_spcgroup(symbol, laue, uniq):
    SG = sgdata(symbol)
    assert SG["SGLaue"] == laue
    assert SG.get("SGUniq", "") == uniq


def test_unknown_laue_raises():
    with pytest.raises(ValueError):
        cell_dof_groups({"SGLaue": "bogus"})


# ---------------------------------------------------------------------------
# Cell plans — one test block per Laue class
# ---------------------------------------------------------------------------

def plan(laue, requested, phase_idx=0, uniq="b"):
    SG = {"SGLaue": laue, "SGUniq": uniq}
    params = {p: ON for p in requested}
    return cell_refinement_plan(SG, params, phase_idx)


def test_cell_cubic():
    assert plan("m3m", []) == CellPlan(False, [])
    assert plan("m3m", ["a"]) == CellPlan(True, [])
    # group-OR: b alone refines the {a,b,c} DOF
    assert plan("m3m", ["b"]) == CellPlan(True, [])
    # symmetry-fixed angles carry no DOF: flags have no effect
    assert plan("m3m", ["alpha"]) == CellPlan(False, [])
    assert plan("m3", ["c"]) == CellPlan(True, [])


def test_cell_tetragonal():
    assert plan("4/mmm", ["a"]) == CellPlan(True, ["0::A2"])
    assert plan("4/mmm", ["c"]) == CellPlan(True, ["0::A0"])
    assert plan("4/mmm", ["a", "c"]) == CellPlan(True, [])
    # b is symmetry-equivalent to a: group-OR
    assert plan("4/mmm", ["b"]) == CellPlan(True, ["0::A2"])
    assert plan("4/m", ["c"], phase_idx=1) == CellPlan(True, ["1::A0"])


@pytest.mark.parametrize("laue", ["6/m", "6/mmm", "3", "3m1", "31m"])
def test_cell_hexagonal_trigonal(laue):
    assert plan(laue, ["a"]) == CellPlan(True, ["0::A2"])
    assert plan(laue, ["c"]) == CellPlan(True, ["0::A0"])
    assert plan(laue, ["a", "c"]) == CellPlan(True, [])
    # gamma is fixed at 120: no effect
    assert plan(laue, ["gamma"]) == CellPlan(False, [])


@pytest.mark.parametrize("laue", ["3R", "3mR"])
def test_cell_rhombohedral_axes_all_or_nothing(laue):
    # {a, alpha} couple through both A0 and A3: single group, never any holds
    assert plan(laue, ["a"]) == CellPlan(True, [])
    assert plan(laue, ["alpha"]) == CellPlan(True, [])
    assert plan(laue, []) == CellPlan(False, [])


def test_cell_orthorhombic():
    assert plan("mmm", ["a"]) == CellPlan(True, ["0::A1", "0::A2"])
    assert plan("mmm", ["b"]) == CellPlan(True, ["0::A0", "0::A2"])
    assert plan("mmm", ["a", "b", "c"]) == CellPlan(True, [])
    assert plan("mmm", ["b", "c"]) == CellPlan(True, ["0::A0"])


def test_cell_monoclinic_b_unique():
    # unique-axis length b is its own DOF; {a, c, beta} are one coupled group
    assert plan("2/m", ["b"], uniq="b") == CellPlan(True, ["0::A0", "0::A2", "0::A4"])
    assert plan("2/m", ["a"], uniq="b") == CellPlan(True, ["0::A1"])
    assert plan("2/m", ["beta"], uniq="b") == CellPlan(True, ["0::A1"])
    assert plan("2/m", ["a", "b", "c", "beta"], uniq="b") == CellPlan(True, [])


def test_cell_monoclinic_c_unique():
    assert plan("2/m", ["c"], uniq="c") == CellPlan(True, ["0::A0", "0::A1", "0::A3"])
    assert plan("2/m", ["gamma"], uniq="c") == CellPlan(True, ["0::A2"])


def test_cell_monoclinic_a_unique():
    assert plan("2/m", ["a"], uniq="a") == CellPlan(True, ["0::A1", "0::A2", "0::A5"])
    assert plan("2/m", ["alpha"], uniq="a") == CellPlan(True, ["0::A0"])


def test_cell_monoclinic_missing_sguniq_matches_cellvary_fallback():
    # cellVary dispatches anything other than 'a'/'b' (incl. a missing SGUniq,
    # unreachable with real SpcGroup output) to the unique-c branch; mirror it.
    assert cell_refinement_plan({"SGLaue": "2/m"}, {"gamma": ON}, 0) == CellPlan(
        True, ["0::A2"]
    )


def test_cell_triclinic_all_or_nothing():
    assert plan("-1", ["alpha"]) == CellPlan(True, [])
    assert plan("-1", ["a"]) == CellPlan(True, [])
    assert plan("-1", []) == CellPlan(False, [])


def test_cell_false_flags_and_absent_are_equivalent():
    SG = {"SGLaue": "4/mmm", "SGUniq": ""}
    explicit = cell_refinement_plan(
        SG, {"a": ON, "b": OFF, "c": OFF, "alpha": OFF, "beta": OFF, "gamma": OFF}, 0
    )
    sparse = cell_refinement_plan(SG, {"a": ON}, 0)
    assert explicit == sparse == CellPlan(True, ["0::A2"])
    assert cell_refinement_plan(SG, None, 0) == CellPlan(False, [])


# ---------------------------------------------------------------------------
# Atom plans — coordinates
# ---------------------------------------------------------------------------

def test_atom_general_position_coordinates():
    # P1 general position: three independent coordinate DOFs
    p = atom_refinement_plan({"x": ON}, "1", 0, 3)
    assert p == AtomPlan("X", ["0::dAy:3", "0::dAz:3"])
    p = atom_refinement_plan({"x": ON, "y": ON, "z": ON}, "1", 0, 0)
    assert p == AtomPlan("X", [])
    p = atom_refinement_plan({"x": OFF, "y": OFF, "z": OFF}, "1", 0, 0)
    assert p == AtomPlan("", [])


def test_atom_fully_fixed_site():
    # Pm-3m origin, site symmetry m3m: no coordinate DOFs at all
    p = atom_refinement_plan({"x": ON, "y": ON, "z": ON}, "m3m", 0, 0)
    assert p == AtomPlan("", [])


def test_atom_partially_fixed_site():
    # LaB6 B site '4mm(z)': only z free (xId=[0,0,1], verified live)
    p = atom_refinement_plan({"z": ON}, "4mm(z)", 0, 1)
    assert p == AtomPlan("X", [])
    # requesting only the fixed x: no free group requested -> nothing happens
    p = atom_refinement_plan({"x": ON}, "4mm(z)", 0, 1)
    assert p == AtomPlan("", [])


def test_atom_linked_coordinates():
    # P4/mmm (x,x,z) site 'm(+-0)': xId=[1,1,2] -> {x,y} linked, {z} free
    p = atom_refinement_plan({"x": ON}, "m(+-0)", 0, 2)
    assert p == AtomPlan("X", ["0::dAz:2"])
    # group-OR: requesting y alone also refines the {x,y} DOF
    p = atom_refinement_plan({"y": ON}, "m(+-0)", 0, 2)
    assert p == AtomPlan("X", ["0::dAz:2"])
    # requesting z holds BOTH members of the linked {x,y} group
    p = atom_refinement_plan({"z": ON}, "m(+-0)", 0, 2)
    assert p == AtomPlan("X", ["0::dAx:2", "0::dAy:2"])


def test_atom_site_sym_keyerror_patch():
    # blank/stale site symmetry: recomputed from coordinates when possible
    SG = sgdata("P m -3 m")
    p = atom_refinement_plan({"z": ON}, "", 0, 1, xyz=(0.5, 0.5, 0.2021), SGData=SG)
    assert p == AtomPlan("X", [])
    with pytest.raises(KeyError):
        atom_refinement_plan({"z": ON}, "", 0, 1)  # no xyz/SGData to recover with


# ---------------------------------------------------------------------------
# Atom plans — displacement and occupancy
# ---------------------------------------------------------------------------

def test_atom_uiso_and_occupancy():
    p = atom_refinement_plan({"ADP": "Uiso", "Uiso": ON, "occupancy": ON}, "1", 0, 0)
    assert p == AtomPlan("FU", [])
    p = atom_refinement_plan({"ADP": "Uiso", "Uiso": OFF}, "1", 0, 0)
    assert p == AtomPlan("", [])


def test_atom_uaniso_general_position():
    # P1: six independent Uij DOFs
    ua = {"U11": ON, "U22": OFF, "U33": OFF, "U12": OFF, "U13": OFF, "U23": OFF}
    p = atom_refinement_plan({"ADP": "Uaniso", "Uaniso": ua}, "1", 0, 4)
    assert p.refine_flags == "U"
    assert p.holds == ["0::AU22:4", "0::AU33:4", "0::AU12:4", "0::AU13:4", "0::AU23:4"]
    ua_all = {k: ON for k in ("U11", "U22", "U33", "U12", "U13", "U23")}
    p = atom_refinement_plan({"ADP": "Uaniso", "Uaniso": ua_all}, "1", 0, 4)
    assert p == AtomPlan("U", [])


def test_atom_uaniso_cubic_site():
    # m3m site: uId=[1,1,1,0,0,0] -> {U11,U22,U33} one group, off-diagonals fixed
    ua = {"U22": ON}
    p = atom_refinement_plan({"ADP": "Uaniso", "Uaniso": ua}, "m3m", 0, 0)
    assert p == AtomPlan("U", [])
    # requesting only a symmetry-zero component: no DOF -> nothing happens
    p = atom_refinement_plan({"ADP": "Uaniso", "Uaniso": {"U12": ON}}, "m3m", 0, 0)
    assert p == AtomPlan("", [])


def test_atom_uaniso_linked_groups():
    # R-3c (0,0,z) site '3': uId=[1,1,2,1,0,0] (verified live) ->
    # {U11,U22,U12} one group, {U33} another, U13/U23 fixed
    p = atom_refinement_plan({"ADP": "Uaniso", "Uaniso": {"U33": ON}}, "3", 0, 5)
    assert p.refine_flags == "U"
    assert p.holds == ["0::AU11:5", "0::AU22:5", "0::AU12:5"]
    p = atom_refinement_plan({"ADP": "Uaniso", "Uaniso": {"U11": ON}}, "3", 0, 5)
    assert p.holds == ["0::AU33:5"]


def test_atom_combined_coordinate_and_uij_holds():
    ua = {"U11": ON}
    p = atom_refinement_plan(
        {"x": ON, "ADP": "Uaniso", "Uaniso": ua, "occupancy": ON}, "1", 1, 2
    )
    assert p.refine_flags == "FXU"
    assert p.holds == [
        "1::dAy:2", "1::dAz:2",
        "1::AU22:2", "1::AU33:2", "1::AU12:2", "1::AU13:2", "1::AU23:2",
    ]
