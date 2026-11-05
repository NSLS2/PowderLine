"""Characterization: core site analysis vs GSAS-II, all 230 space groups (re/03 T5, A69).

For every space group (two-origin groups in origin choice 2, rhombohedral groups
on hexagonal axes: the settings GSAS-II uses), many special and general
positions are analyzed by ``powderline.symmetry.analyze_site`` and by GSAS-II's
own ``SytSym`` / ``GetCSxinel`` / ``GetCSuinel``. They must agree on:

- multiplicity;
- per-axis coordinate DOF (FIXED / FREE / COUPLED);
- per-component Uij DOF.

GSAS-II is read only; nothing in it is changed. Skipped
where GSAS-II is not installed. A disagreement must be escalated, not
tolerated (A35).
"""

from __future__ import annotations

import json
import random
from collections import Counter
from pathlib import Path

import numpy as np
import pytest

pytestmark = pytest.mark.gsasii

G2spc = pytest.importorskip("GSASII.GSASIIspc")
gemmi = pytest.importorskip("gemmi")

from powderline.exceptions import SymmetryError  # noqa: E402
from powderline.symmetry import _expanded_ops, analyze_site  # noqa: E402

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
_POINTS_PER_PATTERN = 2  # per space group: 12 patterns x this many draws


def _gemmi_group(number: int):
    sg = gemmi.find_spacegroup_by_number(number)
    if sg.ext == "1":  # two-origin group: GSAS-II uses origin choice 2
        sg = gemmi.find_spacegroup_by_name(sg.hm + ":2")
    return sg  # rhombohedral groups default to ':H' in gemmi, as in GSAS-II


def _same_mod1(p, q, tol=1e-6) -> bool:
    return bool(np.all(np.abs(((p - q) + 0.5) % 1.0 - 0.5) < tol))


def _orbit(ops, x):
    pts = []
    for R, t in ops:
        y = (R @ x + t) % 1.0
        if not any(_same_mod1(y, p, 1e-8) for p in pts):
            pts.append(y)
    return pts


def _gsas_symbol(sg):
    """A GSAS-II symbol for the same group *and setting*: the general-position orbits must match."""
    x = np.array([0.1234, 0.2345, 0.3456])
    ref = _orbit(_expanded_ops(sg), x)
    parts = sg.hm.split()
    candidates = [sg.hm, G2spc.StandardizeSpcName(sg.short_name())]
    if len(parts) == 4 and parts[1] == "1" and parts[3] == "1":  # 'P 1 21/c 1' -> 'P 21/c'
        candidates.append(f"{parts[0]} {parts[2]}")
    for cand in candidates:
        err, sgdata = G2spc.SpcGroup(cand)
        if err:
            continue
        theirs = [np.array(e[0]) % 1.0 for e in G2spc.GenAtom(x, sgdata, All=False)]
        if len(theirs) == len(ref) and all(any(_same_mod1(p, q) for q in theirs) for p in ref):
            return cand, sgdata
    return None, None


def _gsas_classes(codes) -> tuple:
    """GSAS-II constraint codes -> FIXED (0) / FREE (own group) / COUPLED (shared group)."""
    groups = Counter(c for c in codes if c != 0)
    return tuple("FIXED" if c == 0 else ("FREE" if groups[c] == 1 else "COUPLED") for c in codes)


def _positions(rng):
    """Grid points (multiples of 1/24) in patterns that hit special positions, incl. coupled ones."""
    g = lambda: rng.randrange(24) / 24  # noqa: E731
    pts = []
    for _ in range(_POINTS_PER_PATTERN):
        a, b, c = g(), g(), g()
        pts += [(a, b, c), (a, a, c), (a, -a, c), (a, 2 * a, c), (2 * a, a, c), (a, a, a),
                (a, a + 0.5, c), (a, a + 0.25, c), (a, c, c), (a, c, -c), (a, -a + 0.5, c),
                (a, b, b + 0.25)]
    return sorted({tuple(round(v % 1.0, 12) for v in p) for p in pts})


@pytest.mark.parametrize("number", range(1, 231))
def test_site_analysis_matches_gsasii(number):
    sg = _gemmi_group(number)
    name = sg.xhm()
    symbol, sgdata = _gsas_symbol(sg)
    assert symbol is not None, f"no GSAS-II symbol reproduces {name!r}"

    rng = random.Random(number)
    disagreements = []
    for x in _positions(rng):
        site = analyze_site(name, x)  # exact grid points never fall in the ambiguous band
        sitesym, mult = G2spc.SytSym(list(x), sgdata)[0:2]
        ours = {"multiplicity": site.multiplicity}
        theirs = {"multiplicity": mult}
        try:
            xyz = _gsas_classes(G2spc.GetCSxinel(sitesym)[0])
            uij = _gsas_classes(G2spc.GetCSuinel(sitesym)[0])
        except KeyError:
            # GSAS-II could not name this site symmetry ('sp'), so it has no
            # constraint table entry (seen once over all 230 groups: F432 24e).
            # Multiplicity is still compared.
            pass
        else:
            ours.update({"xyz": site.axes, "uij": site.adp})
            theirs.update({"xyz": xyz, "uij": uij})
        for key in ours:
            if tuple(np.atleast_1d(ours[key])) != tuple(np.atleast_1d(theirs[key])):
                disagreements.append((x, sitesym, key, ours[key], theirs[key]))
    assert not disagreements, f"{name} (GSAS-II {symbol!r}): {disagreements[:5]}"


@pytest.mark.parametrize("space_group, rounded, expected", [
    # fully fixed sites: canonical == the exact special position
    ("P 63/m m c", (0.333333, 0.666667, 0.25), (1 / 3, 2 / 3, 0.25)),
    ("F d -3 m:2", (0.125, 0.125, 0.125), (0.125, 0.125, 0.125)),
    ("R -3 m:H", (0.5, 0.0, 0.0), (0.5, 0.0, 0.0)),
    # GSAS-II's cell-edge defect (misreads values just below an integer): the
    # canonical exact 0 avoids it
    ("F m -3 m", (-1e-9, 1e-9, 0.0), (0.0, 0.0, 0.0)),
    # free axis kept as stated, fixed axes exact
    ("P 63/m m c", (0.333333, 0.666667, 0.06), (1 / 3, 2 / 3, 0.06)),
])
def test_canonical_coordinates(space_group, rounded, expected):
    """6-decimal input is canonicalized exactly; GSAS-II reads the same site from it."""
    site = analyze_site(space_group, rounded)
    assert site.canonical == expected
    _symbol, sgdata = _gsas_symbol(gemmi.find_spacegroup_by_name(space_group))
    assert G2spc.SytSym(list(site.canonical), sgdata)[1] == site.multiplicity


def test_coupled_coordinates_canonicalized_by_least_change():
    """6h (x, 2x, 1/4): the relation is restored with the smallest change; z is exact."""
    site = analyze_site("P 63/m m c", (0.166667, 0.333333, 0.25))
    x, y, z = site.canonical
    assert site.axes == ("COUPLED", "COUPLED", "FIXED") and site.adjusted
    assert z == 0.25 and abs(y - 2 * x) < 1e-15
    # orthogonal projection onto (t, 2t): t = (x + 2y) / 5
    assert abs(x - (0.166667 + 2 * 0.333333) / 5) < 1e-15
    _symbol, sgdata = _gsas_symbol(gemmi.find_spacegroup_by_name("P 63/m m c"))
    assert G2spc.SytSym(list(site.canonical), sgdata)[1] == site.multiplicity == 6


@pytest.mark.parametrize("space_group, xyz", [
    ("P 63/m m c", (0.3333, 0.6667, 0.25)),
    ("P 63/m m c", (0.33333, 0.66667, 0.25)),
    ("P 63/m m c", (0.333, 0.667, 0.25)),
    ("F m -3 m", (1e-5, 0.0, 0.0)),
    ("F d -3 m:2", (0.12501, 0.125, 0.125)),
])
def test_ambiguous_band_is_rejected(space_group, xyz):
    with pytest.raises(SymmetryError, match="without being on it"):
        analyze_site(space_group, xyz)


def test_committed_examples_agree_with_gsasii():
    """Every atom of every committed example: same multiplicity from core and GSAS-II."""
    checked = 0
    for path in sorted(EXAMPLES.glob("*/input.json")):
        if path.parent.name == "example_template":
            continue
        recipe = json.loads(path.read_text(encoding="utf-8"))
        if not str(recipe.get("schema_name", "")).startswith("gsasii."):
            continue  # the GSAS-II comparison is for the gsasii.* examples
        phases = (recipe.get("payload") or {}).get("phases") or {}
        for phase in phases.values():  # native gsasii.rietveld phase block (A93): [value, flag] parameters
            sg = gemmi.find_spacegroup_by_name(phase["space_group"])
            _symbol, sgdata = _gsas_symbol(sg)
            for atom in phase["atoms"].values():
                xyz = (atom["x"][0], atom["y"][0], atom["z"][0])
                site = analyze_site(sg.xhm(), xyz)
                assert site.multiplicity == G2spc.SytSym(list(xyz), sgdata)[1]
                checked += 1
    assert checked >= 20


# --- coupling groups vs GSAS-II, exhaustive (re/03b; A94, A95, A98) ----------
#
# Every distinct site stabilizer met on the 1/24 grid, in every gemmi setting
# GSAS-II reads (522: all ':R' settings and every non-standard monoclinic and
# orthorhombic setting; origin-1 settings skipped, EB-03): the tie groups of
# coordinates and Uij (partition, fixed set) and each group's relation
# coefficients against GSAS-II's GetCSxinel/GetCSuinel ids and multipliers.
# Devkit probe: probes/re03b_review_symmetry_probe.py (review S2).

from powderline.symmetry import coupling_groups  # noqa: E402
from symmetry_sites import distinct_special_sites  # noqa: E402

#: GSAS-II sites it reads wrongly (core is right there). Points in 1/24 units.
#: EB-40: R-centred 2-fold sites GSAS-II calls general ('1', doubled
#: multiplicity). EB-05: sites it cannot name ('sp'; GetCSxinel raises).
#: Each must STILL differ: if one starts to agree, a GSAS-II upgrade fixed it,
#: and EB-40/EB-05 and the re/04 gateway check need revisiting.
GSASII_DEFECTS = {
    ("R 3 2:H", (0, 8, 4)): ("1", 18), ("R 3 2:H", (0, 16, 4)): ("1", 18),
    ("R 3 2:H", (16, 0, 8)): ("1", 18),
    ("R -3 m:H", (0, 8, 4)): ("1", 36), ("R -3 m:H", (0, 16, 4)): ("1", 36),
    ("R -3 m:H", (16, 0, 8)): ("1", 36),
    ("R -3 c:H", (0, 8, 10)): ("1", 36), ("R -3 c:H", (0, 16, 10)): ("1", 36),
    ("R -3 c:H", (16, 0, 2)): ("1", 36),
    ("R -3 m:R", (0, 12, 0)): ("sp", 3),
    ("P 4 3 2", (0, 1, 0)): ("sp", 6),
    ("F 4 3 2", (0, 1, 0)): ("sp", 24), ("F 4 3 2", (0, 1, 12)): ("sp", 24),
    ("I 4 3 2", (0, 1, 0)): ("sp", 12),
    ("P n -3 n:2", (6, 0, 6)): ("sp", 12),
    ("F m -3 c", (6, 1, 6)): ("sp", 48), ("F m -3 c", (6, 1, 18)): ("sp", 48),
}


def _gsas_symbol_any_setting(sg):
    """Like ``_gsas_symbol``, also for ':R' and spacing variants GSAS-II reads (review probe)."""
    x = np.array([0.1234, 0.2345, 0.3456])
    ref = _orbit(_expanded_ops(sg), x)
    parts = sg.hm.split()
    candidates = [sg.hm + " R"] if sg.ext == "R" else []
    candidates += [sg.hm, G2spc.StandardizeSpcName(sg.short_name()),
                   G2spc.StandardizeSpcName(sg.hm.replace(" ", ""))]
    if len(parts) == 4 and parts[1] == "1" and parts[3] == "1":
        candidates.append(f"{parts[0]} {parts[2]}")
    for cand in candidates:
        try:
            err, sgdata = G2spc.SpcGroup(cand)
        except Exception:  # noqa: BLE001 - GSAS-II raises on some spellings
            continue
        if err:
            continue
        theirs = [np.array(e[0]) % 1.0 for e in G2spc.GenAtom(x, sgdata, All=False)]
        if len(theirs) == len(ref) and all(any(_same_mod1(p, q) for q in theirs) for p in ref):
            return cand, sgdata
    return None, None


def _gsas_ties(ids, multipliers, names):
    """GSAS-II constraint ids + multipliers -> ({members: relative multipliers}, fixed names)."""
    groups: dict[int, list[int]] = {}
    for j, gid in enumerate(ids):
        if gid != 0:
            groups.setdefault(gid, []).append(j)
    ties = {tuple(names[j] for j in members): tuple(multipliers[j] / multipliers[members[0]] for j in members)
            for members in groups.values()}
    return ties, tuple(n for n, gid in zip(names, ids) if gid == 0)


def _core_ties(ties):
    return ({g.members: tuple(float(k) for k in g.coefficients) for g in ties.groups}, ties.fixed)


def _same_ties(ours, theirs) -> bool:
    (og, of), (tg, tf) = ours, theirs
    return of == tf and og.keys() == tg.keys() and all(
        all(abs(a - b) < 1e-9 for a, b in zip(og[k], tg[k])) for k in og)


@pytest.fixture(scope="module")
def coupling_comparison():
    """Compare every distinct special site; returns (settings, sites compared, disagreements)."""
    settings, sites, disagreements = 0, 0, {}
    for sg in gemmi.spacegroup_table():
        if sg.ext == "1":
            continue  # GSAS-II has no origin-1 settings (EB-03)
        _symbol, sgdata = _gsas_symbol_any_setting(sg)
        if sgdata is None:
            continue  # 9 settings GSAS-II cannot express
        settings += 1
        name = sg.xhm()
        for point in distinct_special_sites(sg):
            x = [v / 24 for v in point]
            sites += 1
            site, ties = analyze_site(name, x), coupling_groups(name, x)
            sitesym, mult = G2spc.SytSym(x, sgdata)[0:2]
            ours = {"multiplicity": site.multiplicity,
                    "xyz": _core_ties(ties.xyz), "uij": _core_ties(ties.uij)}
            try:
                theirs = {"multiplicity": mult,
                          "xyz": _gsas_ties(*G2spc.GetCSxinel(sitesym)[:2], ("x", "y", "z")),
                          "uij": _gsas_ties(*G2spc.GetCSuinel(sitesym)[:2],
                                            ("U11", "U22", "U33", "U12", "U13", "U23"))}
            except KeyError:  # GSAS-II cannot name the site ('sp', EB-05)
                disagreements[(name, point)] = (sitesym, mult)
                continue
            if not (ours["multiplicity"] == theirs["multiplicity"]
                    and _same_ties(ours["xyz"], theirs["xyz"]) and _same_ties(ours["uij"], theirs["uij"])):
                disagreements[(name, point)] = (sitesym, mult)
    return settings, sites, disagreements


def test_coupling_groups_match_gsasii_where_it_reads_the_site(coupling_comparison):
    """Partition, fixed set, one DOF per group and relation coefficients agree with GSAS-II."""
    settings, sites, disagreements = coupling_comparison
    assert settings == 522
    assert sites == 2928  # 2,920 GSAS-II names + 8 it cannot ('sp')
    unexpected = {k: v for k, v in disagreements.items() if k not in GSASII_DEFECTS}
    assert not unexpected, f"new disagreements with GSAS-II (escalate, A35): {unexpected}"


def test_known_gsasii_site_defects_still_differ(coupling_comparison):
    """The 17 known GSAS-II defects (EB-40, EB-05) are still there, exactly as recorded."""
    _settings, _sites, disagreements = coupling_comparison
    assert {k: disagreements.get(k) for k in GSASII_DEFECTS} == GSASII_DEFECTS
    for (name, point), (sitesym, mult) in GSASII_DEFECTS.items():
        core = analyze_site(name, [v / 24 for v in point]).multiplicity
        assert sitesym == "sp" or mult == 2 * core, (name, point)
