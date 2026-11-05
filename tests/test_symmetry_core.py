"""Tests for powderline.symmetry core validation functions (check_cell, analyze_site).

Core-only: no GSAS-II needed; must run in a core-only environment.
"""
import pytest

from powderline.exceptions import SymmetryError
from powderline.symmetry import check_cell, analyze_site, SiteAnalysis
from fractions import Fraction

pytestmark = pytest.mark.core


# --- check_cell -------------------------------------------------------------


def test_check_cell_cubic_valid_returned():
    """check_cell: cubic P m -3 m (a=b=c, 90/90/90) returns symmetric cell."""
    sg = "P m -3 m"
    cell = (4.15692, 4.15692, 4.15692, 90.0, 90.0, 90.0)
    symmetric = check_cell(sg, cell)
    assert len(symmetric) == 6
    assert abs(symmetric[0] - cell[0]) < 1e-12


def test_check_cell_cubic_a_perturbed_rejected():
    """check_cell: cubic with b != a by 1e-6 relative rejected."""
    sg = "P m -3 m"
    a = 4.15692
    cell = (a, a * (1 + 1e-6), a, 90.0, 90.0, 90.0)
    with pytest.raises(SymmetryError, match="inconsistent"):
        check_cell(sg, cell)


def test_check_cell_cubic_gamma_perturbed_rejected():
    """check_cell: cubic with gamma != 90 by 1e-6 degree rejected."""
    sg = "P m -3 m"
    cell = (4.0, 4.0, 4.0, 90.0, 90.0, 90.0 + 1e-6)
    with pytest.raises(SymmetryError, match="inconsistent"):
        check_cell(sg, cell)


def test_check_cell_cubic_tiny_perturbation_accepted():
    """check_cell: cubic with perturbation below CELL_TOL (1e-12 relative) accepted."""
    sg = "P m -3 m"
    a = 4.0
    cell = (a, a * (1 + 1e-13), a, 90.0, 90.0, 90.0)
    symmetric = check_cell(sg, cell)
    assert symmetric is not None


def test_check_cell_tetragonal_valid_returned():
    """check_cell: tetragonal I 41/a m d:2 (a=b, c, 90/90/90) returns symmetric cell."""
    sg = "I 41/a m d:2"
    cell = (5.0, 5.0, 7.0, 90.0, 90.0, 90.0)
    symmetric = check_cell(sg, cell)
    assert abs(symmetric[0] - symmetric[1]) < 1e-12
    assert abs(symmetric[2] - 7.0) < 1e-12


def test_check_cell_tetragonal_a_neq_b_rejected():
    """check_cell: tetragonal with a != b by 1e-6 relative rejected."""
    sg = "I 41/a m d:2"
    cell = (5.0, 5.0 * (1 + 1e-6), 7.0, 90.0, 90.0, 90.0)
    with pytest.raises(SymmetryError, match="inconsistent"):
        check_cell(sg, cell)


def test_check_cell_hexagonal_valid_returned():
    """check_cell: hexagonal P 63/m m c (a=b, c, 90/90/120) returns symmetric cell."""
    sg = "P 63/m m c"
    cell = (3.2, 3.2, 5.2, 90.0, 90.0, 120.0)
    symmetric = check_cell(sg, cell)
    assert abs(symmetric[0] - symmetric[1]) < 1e-12
    assert abs(symmetric[5] - 120.0) < 1e-12


def test_check_cell_hexagonal_gamma_neq_120_rejected():
    """check_cell: hexagonal with gamma != 120 by 1e-6 degree rejected."""
    sg = "P 63/m m c"
    cell = (3.2, 3.2, 5.2, 90.0, 90.0, 120.0 + 1e-6)
    with pytest.raises(SymmetryError, match="inconsistent"):
        check_cell(sg, cell)


def test_check_cell_monoclinic_valid_returned():
    """check_cell: monoclinic C 1 2/m 1 (a!=b!=c, 90/beta/90) returns symmetric cell."""
    sg = "C 1 2/m 1"
    cell = (5.0, 6.0, 7.0, 90.0, 104.3, 90.0)
    symmetric = check_cell(sg, cell)
    assert abs(symmetric[4] - 104.3) < 1e-9


def test_check_cell_monoclinic_alpha_neq_90_rejected():
    """check_cell: monoclinic with alpha != 90 by 1e-6 degree rejected."""
    sg = "C 1 2/m 1"
    cell = (5.0, 6.0, 7.0, 90.0 + 1e-6, 104.3, 90.0)
    with pytest.raises(SymmetryError, match="inconsistent"):
        check_cell(sg, cell)


def test_check_cell_triclinic_valid_returned():
    """check_cell: triclinic P 1 (all free) returns cell unchanged."""
    sg = "P 1"
    cell = (5.0, 6.0, 7.0, 80.0, 85.0, 95.0)
    symmetric = check_cell(sg, cell)
    for i in range(6):
        assert abs(symmetric[i] - cell[i]) < 1e-12


def test_check_cell_rhombohedral_r_setting_valid_returned():
    """check_cell: rhombohedral R -3 m:R (a=b=c, alpha=beta=gamma!=90) returns symmetric cell."""
    sg = "R -3 m:R"
    alpha = 60.0
    cell = (5.0, 5.0, 5.0, alpha, alpha, alpha)
    symmetric = check_cell(sg, cell)
    assert abs(symmetric[0] - symmetric[1]) < 1e-12
    assert abs(symmetric[1] - symmetric[2]) < 1e-12
    assert abs(symmetric[3] - symmetric[4]) < 1e-12
    assert abs(symmetric[4] - symmetric[5]) < 1e-12


def test_check_cell_rhombohedral_r_setting_angle_perturbed_rejected():
    """check_cell: rhombohedral R -3 m:R with alpha != beta by 1e-6 degree rejected."""
    sg = "R -3 m:R"
    cell = (5.0, 5.0, 5.0, 60.0, 60.0 + 1e-6, 60.0)
    with pytest.raises(SymmetryError, match="inconsistent"):
        check_cell(sg, cell)


# --- analyze_site -----------------------------------------------------------


def test_analyze_site_general_position_multiplicity():
    """analyze_site: P m -3 m general position -> multiplicity 48 (number of operations)."""
    sg = "P m -3 m"
    xyz = (0.123, 0.456, 0.789)
    site = analyze_site(sg, xyz)
    assert site.multiplicity == 48


def test_analyze_site_adjusted_false_for_exact():
    """analyze_site: exact input -> adjusted=False."""
    sg = "P m -3 m"
    xyz = (0.0, 0.0, 0.0)
    site = analyze_site(sg, xyz)
    assert site.adjusted is False


def test_analyze_site_exact_fractions():
    """analyze_site: fixed coordinates in `exact` as Fraction(1, 3) etc."""
    sg = "P 63/m m c"
    xyz = (0.333333, 0.666667, 0.25)
    site = analyze_site(sg, xyz)
    # Check exact contains Fraction(1, 3), Fraction(2, 3), Fraction(1, 4)
    assert site.exact[0] == Fraction(1, 3)
    assert site.exact[1] == Fraction(2, 3)
    assert site.exact[2] == Fraction(1, 4)


def test_analyze_site_explicit_setting_required():
    """analyze_site: 'F d -3 m' without :1/:2 raises SymmetryError."""
    xyz = (0.125, 0.125, 0.125)
    with pytest.raises(SymmetryError, match="two origin choices"):
        analyze_site("F d -3 m", xyz)


def test_analyze_site_non_finite_raises():
    """analyze_site: non-finite xyz raises SymmetryError."""
    sg = "P 1"
    xyz = (float("nan"), 0.0, 0.0)
    with pytest.raises(SymmetryError, match="must be a finite 3-vector"):
        analyze_site(sg, xyz)


def test_analyze_site_cubic_origin_multiplicity_1():
    """analyze_site: P m -3 m origin (0,0,0) -> multiplicity 1."""
    sg = "P m -3 m"
    xyz = (0.0, 0.0, 0.0)
    site = analyze_site(sg, xyz)
    assert site.multiplicity == 1


def test_analyze_site_hexagonal_6h_multiplicity_6():
    """analyze_site: P 63/m m c (0.2,0.4,0.25) -> multiplicity 6 (site 6h)."""
    sg = "P 63/m m c"
    xyz = (0.2, 0.4, 0.25)
    site = analyze_site(sg, xyz)
    assert site.multiplicity == 6


# --- ambiguous-band message ----------------------------------------------------


def test_is_group_detects_closure():
    from powderline.symmetry import _expanded_ops, _is_group, resolve_space_group

    ops = _expanded_ops(resolve_space_group("P 63/m m c"))
    assert _is_group(ops)
    assert _is_group(ops[:1])  # identity alone
    two_fold = [op for op in ops if round(float(op[0].trace())) == -1][0]
    assert not _is_group([two_fold])  # missing the identity


def test_ambiguous_band_message_names_the_special_position():
    with pytest.raises(SymmetryError, match=r"from the special position \(1/3, 2/3, 1/4\) \(multiplicity 2\)"):
        analyze_site("P 63/m m c", (0.3333, 0.6667, 0.25))


# --- tie groups: coupling_groups, cell_tie_groups (re/03b; A94, A95, A98, A102) ---

import gemmi  # noqa: E402
import numpy as np  # noqa: E402

from powderline import symmetry as sym  # noqa: E402
from powderline.symmetry import cell_tie_groups, coupling_groups  # noqa: E402
from symmetry_sites import distinct_special_sites  # noqa: E402

_UIJ = ("U11", "U22", "U33", "U12", "U13", "U23")


def _ties(ties):
    """Ties -> ({members: (coefficients, offsets)}, fixed), with exact Fractions."""
    return {g.members: (g.coefficients, g.offsets) for g in ties.groups}, ties.fixed


def test_coupling_groups_are_one_dof_affine_relations_in_every_setting():
    """All 564 gemmi settings (incl. origin 1 and ':R'), every distinct special site on the
    1/24 grid: the fixed sets match analyze_site; moving the site along any coordinate group's
    relation keeps it fixed by the whole stabilizer; a Uij tensor built along any Uij group's
    relation is invariant under it. Proves each group is one DOF with the right relation."""
    settings = sites = groups = 0
    for sg in gemmi.spacegroup_table():
        name = sg.xhm()
        ops = sym._expanded_ops(sg)
        settings += 1
        for point in distinct_special_sites(sg):
            x = np.array(point) / 24
            stab = [(R, t) for R, t in ops if np.all(np.abs(sym._wrap_symmetric(R @ x + t - x)) < 1e-9)]
            site, ties = analyze_site(name, x), coupling_groups(name, x)
            sites += 1
            assert set(ties.xyz.fixed) == {a for a, c in zip("xyz", site.axes) if c == "FIXED"}
            assert set(ties.uij.fixed) == {u for u, c in zip(_UIJ, site.adp) if c == "FIXED"}
            for g in ties.xyz.groups:
                groups += 1
                moved = np.array(site.canonical)
                rep = moved["xyz".index(g.members[0])] + 0.0123
                for member, k, c in zip(g.members, g.coefficients, g.offsets):
                    moved["xyz".index(member)] = float(k) * rep + float(c)
                worst = max(np.max(np.abs(sym._wrap_symmetric(R @ moved + t - moved))) for R, t in stab)
                assert worst < 1e-12, (name, point, g)
            for g in ties.uij.groups:
                assert set(g.offsets) == {0}
                u = np.zeros(6)
                for member, k in zip(g.members, g.coefficients):
                    u[_UIJ.index(member)] = float(k) * 0.01
                tensor = sym._sym_from_vec(u)
                assert max(np.max(np.abs(R @ tensor @ R.T - tensor)) for R, _t in stab) < 1e-12, (name, point, g)
    assert (settings, sites, groups) == (564, 3451, 2792)


@pytest.mark.parametrize("space_group, xyz, expected", [
    # review B1: affine ties; the offset follows the stated lattice translate
    ("P -4 21 m", (0.1, 0.6, 0.3), {("x", "y"): ((1, 1), (0, Fraction(1, 2))), ("z",): ((1,), (0,))}),
    ("P -4 21 m", (0.1, 0.4, 0.3), {("x", "y"): ((1, -1), (0, Fraction(1, 2))), ("z",): ((1,), (0,))}),
    ("P -4 21 m", (0.1, -0.4, 0.3), {("x", "y"): ((1, 1), (0, Fraction(-1, 2))), ("z",): ((1,), (0,))}),
    ("P 42/m n m", (0.3, 0.7, 0.0), {("x", "y"): ((1, -1), (0, 1))}),
    ("P 63/m m c", (1 / 6, 1 / 3, 0.25), {("x", "y"): ((1, 2), (0, 0))}),
    ("R -3 m:H", (0.1, -0.1, 0.3), {("x", "y"): ((1, -1), (0, 0)), ("z",): ((1,), (0,))}),
    ("P m -3 m", (0.5, 0.5, 0.2021), {("z",): ((1,), (0,))}),
    ("R -3 m:R", (0.1, 0.1, 0.1), {("x", "y", "z"): ((1, 1, 1), (0, 0, 0))}),
])
def test_coupling_groups_coordinate_relations(space_group, xyz, expected):
    groups, _fixed = _ties(coupling_groups(space_group, xyz).xyz)
    assert groups == expected


@pytest.mark.parametrize("space_group, xyz, expected_groups, expected_fixed", [
    # several coupled Uij groups at one site; factor-2 and negative relations
    ("P 63/m m c", (1 / 6, 1 / 3, 0.25),
     {("U11",): ((1,), (0,)), ("U22", "U12"): ((1, Fraction(1, 2)), (0, 0)), ("U33",): ((1,), (0,))},
     ("U13", "U23")),
    ("P 6/m m m", (1 / 3, 2 / 3, 0.0),
     {("U11", "U22", "U12"): ((1, 1, Fraction(1, 2)), (0, 0, 0)), ("U33",): ((1,), (0,))}, ("U13", "U23")),
    ("P -4 21 m", (0.1, 0.4, 0.3),
     {("U11", "U22"): ((1, 1), (0, 0)), ("U33",): ((1,), (0,)), ("U12",): ((1,), (0,)),
      ("U13", "U23"): ((1, -1), (0, 0))}, ()),
    ("P m -3 m", (0.0, 0.0, 0.0), {("U11", "U22", "U33"): ((1, 1, 1), (0, 0, 0))}, ("U12", "U13", "U23")),
])
def test_coupling_groups_uij_relations(space_group, xyz, expected_groups, expected_fixed):
    assert _ties(coupling_groups(space_group, xyz).uij) == (expected_groups, expected_fixed)


@pytest.mark.parametrize("space_group, xyz, text", [
    ("P -4 21 m", (0.1, 0.6, 0.3), "y = x + 1/2"),
    ("P -4 21 m", (0.1, 0.4, 0.3), "y = -x + 1/2"),
    ("P 42/m n m", (0.3, 0.7, 0.0), "y = -x + 1"),
    ("P 63/m m c", (1 / 6, 1 / 3, 0.25), "y = 2x"),
    ("R -3 m:R", (0.1, 0.1, 0.1), ""),
])
def test_tie_group_relations_text(space_group, xyz, text):
    assert coupling_groups(space_group, xyz).xyz.groups[0].relations_text() == text


def test_tie_group_relations_text_uij():
    ties = coupling_groups("P 63/m m c", (1 / 6, 1 / 3, 0.25)).uij
    assert ties.group_of("U12").relations_text() == "U12 = U22/2"
    assert coupling_groups("P -4 21 m", (0.1, 0.4, 0.3)).uij.group_of("U23").relations_text() == "U23 = -U13"
    assert ties.group_of("U13") is None


def test_coupling_groups_ambiguous_position_raises():
    with pytest.raises(SymmetryError, match="without being on it"):
        coupling_groups("P 63/m m c", (0.3333, 0.6667, 0.25))


_ALL = ("a", "b", "c", "alpha", "beta", "gamma")


@pytest.mark.parametrize("space_group, groups, fixed, system, axis", [
    ("F m -3 m", [("a", "b", "c")], ("alpha", "beta", "gamma"), "cubic", None),
    ("I 41/a m d:2", [("a", "b"), ("c",)], ("alpha", "beta", "gamma"), "tetragonal", None),
    ("P 63/m m c", [("a", "b"), ("c",)], ("alpha", "beta", "gamma"), "hexagonal", None),
    ("R -3 m:H", [("a", "b"), ("c",)], ("alpha", "beta", "gamma"), "trigonal", None),
    ("R -3 m:R", [("a", "b", "c"), ("alpha", "beta", "gamma")], (), "trigonal", None),
    ("R 3:R", [("a", "b", "c"), ("alpha", "beta", "gamma")], (), "trigonal", None),
    ("P m m m", [("a",), ("b",), ("c",)], ("alpha", "beta", "gamma"), "orthorhombic", None),
    ("C 1 2/m 1", [("a",), ("b",), ("c",), ("beta",)], ("alpha", "gamma"), "monoclinic", "b"),
    ("P 1 c 1", [("a",), ("b",), ("c",), ("beta",)], ("alpha", "gamma"), "monoclinic", "b"),
    ("C c 1 1", [("a",), ("b",), ("c",), ("alpha",)], ("beta", "gamma"), "monoclinic", "a"),
    ("P 1 1 m", [("a",), ("b",), ("c",), ("gamma",)], ("alpha", "beta"), "monoclinic", "c"),
    ("P -1", [("a",), ("b",), ("c",), ("alpha",), ("beta",), ("gamma",)], (), "triclinic", None),
])
def test_cell_tie_groups(space_group, groups, fixed, system, axis):
    ties = cell_tie_groups(space_group)
    assert [g.members for g in ties.groups] == groups
    assert ties.fixed == fixed
    assert (ties.crystal_system, ties.unique_axis) == (system, axis)
    assert all(set(g.coefficients) == {1} and set(g.offsets) == {0} for g in ties.groups)


def test_cell_tie_groups_every_setting_agree_with_the_metric():
    """Every gemmi setting: each name is in one group or fixed; changing a whole group together
    keeps a symmetric cell symmetric, changing one member alone (or a fixed angle) breaks it."""
    for sg in gemmi.spacegroup_table():
        name = sg.xhm()
        ties = cell_tie_groups(name)
        names = [m for g in ties.groups for m in g.members] + list(ties.fixed)
        assert sorted(names) == sorted(_ALL), name
        rots = [R for R, _t in sym._expanded_ops(sg)]
        g0 = sym._metric((5.1, 6.2, 7.3, 81.0, 86.0, 97.0))
        cell = dict(zip(_ALL, sym._cell_from_metric(sum(R.T @ g0 @ R for R in rots) / len(rots))))
        check_cell(name, tuple(cell.values()))
        for group in ties.groups:
            together = {k: v + (0.01 if k in group.members else 0.0) for k, v in cell.items()}
            check_cell(name, tuple(together.values()))
            if len(group.members) > 1:
                alone = {k: v + (0.01 if k == group.members[-1] else 0.0) for k, v in cell.items()}
                with pytest.raises(SymmetryError, match="inconsistent"):
                    check_cell(name, tuple(alone.values()))
        for angle in ties.fixed:
            with pytest.raises(SymmetryError, match="inconsistent"):
                check_cell(name, tuple(v + (0.01 if k == angle else 0.0) for k, v in cell.items()))


def test_cell_tie_groups_require_an_explicit_setting():
    with pytest.raises(SymmetryError, match="rhombohedral; specify the setting"):
        cell_tie_groups("R -3 m")


# --- error cases shared by every caller (moved from the deleted test_topas_symmetry, re/17) ---


def test_unknown_symbol_errors():
    from powderline import symmetry as sym
    with pytest.raises(SymmetryError, match="unrecognized"):
        sym.resolve_space_group("NotASpaceGroup")


def test_symmetry_error_is_a_core_value_error():
    # A61: a ValueError (pydantic reports it with the field location inside a
    # validator) and a PowderLineError; no gateway error type involved.
    from powderline import symmetry as sym
    from powderline.exceptions import PowderLineError
    with pytest.raises(SymmetryError) as info:
        sym.resolve_space_group("NotASpaceGroup")
    assert isinstance(info.value, ValueError)
    assert isinstance(info.value, PowderLineError)
    assert type(info.value).__module__ == "powderline.exceptions"


def test_rhombohedral_R_setting_accepted_by_core():
    # A62: core resolves both rhombohedral settings; engines that cannot handle
    # :R (TOPAS, easydiffraction) reject it in their own layer.
    from powderline import symmetry as sym
    assert sym.resolve_space_group("R -3 m :R").ext == "R"
    assert analyze_site("R -3 m :R", (0.0, 0.0, 0.0)).multiplicity == 1
    assert analyze_site("R -3 m :H", (0.0, 0.0, 0.0)).multiplicity == 3


def test_monoclinic_unique_axis_failure_raises_symmetry_error():
    import numpy as np
    from powderline import symmetry as sym
    with pytest.raises(SymmetryError, match="monoclinic unique axis"):
        sym._monoclinic_unique_axis([(np.eye(3), np.zeros(3))])
