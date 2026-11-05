"""gemmi-backed crystallographic rules (engine-free core module).

Pure, engine-free capabilities:

* :func:`analyze_site` -- the core schema's site validation (KI-03; A35, A69,
  A73): multiplicity + DOF from the space group, the ambiguous-band error, and
  the canonical (exact) special-position coordinates every gateway sends to its
  engine. Policy and evidence: devkit ``tasks/re03-symmetry-tolerance.md``.
* :func:`canonical_space_group` -- the core schema's space-group rule: gemmi's
  canonical name only (A105).
* :func:`cell_tie_groups` / :func:`coupling_groups` -- which cell, coordinate
  and Uij parameters are one parameter by symmetry, with their exact relation
  (affine for coordinates), and which are fixed: the basis of the phase
  block's flag and bound rules (A94, A95, A98).

Space-group operations come from gemmi; the stabiliser / projector math is our
own (~small, spec in plan §5). ``gemmi`` is an approved runtime dependency (D3).

Errors are :class:`~powderline.exceptions.SymmetryError`; each gateway converts
it to its own error type and applies its engine's own restrictions (e.g. TOPAS
rejects the rhombohedral ``:R`` setting) (A61, A62).
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

import gemmi
import numpy as np

from powderline.exceptions import SymmetryError


# Fractional-coordinate tolerances (plan §5).
_MAT_TOL = 1e-6   # rotation-matrix / projector comparisons

#: Core schema special-position rules (A69, A73), as a fractional *image
#: distance* d = max_i |wrap(R x + t - x)_i|: d < SPECIAL_POSITION_TOL means x is
#: fixed by that operation (>= 6 decimals declare a special position);
#: SPECIAL_POSITION_TOL <= d < AMBIGUOUS_BAND is an error (ambiguous intent).
SPECIAL_POSITION_TOL = 5e-6
AMBIGUOUS_BAND = 2e-3
#: Canonical coordinates that differ from the stated ones by more than this are
#: reported as adjusted (floating-point noise is not).
ADJUSTMENT_REPORT_TOL = 1e-12
_MAX_DENOMINATOR = 48  # fixed special-position coordinates are multiples of 1/24

_AXIS_LETTERS = ("x", "y", "z")
_LENGTHS = ("a", "b", "c")
_ANGLES = ("alpha", "beta", "gamma")


# --- space-group resolution -------------------------------------------------


def resolve_space_group(space_group: str, *, explicit_setting: bool = False) -> gemmi.SpaceGroup:
    """Resolve a recipe space-group string to a gemmi ``SpaceGroup``.

    Tries the symbol verbatim, then whitespace-stripped (gemmi accepts both
    ``"P m -3 m"`` and ``"Pm-3m"``). Unresolvable symbols raise
    :class:`SymmetryError`. Two-origin groups passed without an explicit
    ``:1``/``:2`` selector also error rather than guess an origin (plan §5(6)).
    Both rhombohedral settings (``:H``, ``:R``) are accepted; engines that
    cannot handle ``:R`` reject it themselves (A62). With
    ``explicit_setting=True`` (the core schema rule, A62) a rhombohedral group
    must also name its setting (gemmi would otherwise assume ``:H``).
    """
    raw = str(space_group)
    sg = gemmi.find_spacegroup_by_name(raw)
    if sg is None:
        sg = gemmi.find_spacegroup_by_name(raw.replace(" ", ""))
    if sg is None:
        raise SymmetryError(
            f"unrecognized space-group symbol {space_group!r} (gemmi could not resolve it)"
        )
    if explicit_setting and sg.ext in ("H", "R") and ":" not in raw:
        raise SymmetryError(
            f"space group {space_group!r} is rhombohedral; specify the setting "
            "explicitly: append ':H' (hexagonal axes) or ':R' (rhombohedral axes)"
        )
    if sg.ext in ("1", "2") and ":" not in raw:
        raise SymmetryError(
            f"space group {space_group!r} has two origin choices; specify one "
            "explicitly (e.g. append ':2' for the GSAS-II origin-2 convention)"
        )
    return sg


def canonical_space_group(space_group: str) -> gemmi.SpaceGroup:
    """Return the gemmi group whose canonical name is exactly ``space_group`` (core rule, A105).

    The canonical name is gemmi's extended Hermann-Mauguin symbol ``xhm()``
    (``"P m -3 m"``, ``"C 1 2/m 1"``, ``"R -3 m:H"``, ``"F d -3 m:2"``); it is
    unique over gemmi's table and names the setting. Any other spelling raises
    :class:`SymmetryError` whose message names the canonical form. gemmi's
    lenient lookup is used only to build that suggestion, never to accept: it
    would silently pick a default (``"Fd-3m"`` -> origin 1, ``"R-3m"`` -> ``:H``,
    ``"C2/m"`` -> b-unique). A symbol without a setting lists the choices:
    ``:H``/``:R``, ``:1``/``:2``, or every monoclinic setting of the group, by
    unique axis. :func:`resolve_space_group` is the lenient reader (GSAS-II's
    own defaults), kept for callers that want them.
    """
    raw = str(space_group)
    sg = gemmi.find_spacegroup_by_name(raw)
    if sg is not None and sg.xhm() == raw:
        return sg
    if sg is None:
        sg = gemmi.find_spacegroup_by_name(raw.replace(" ", ""))
    if sg is None:
        raise SymmetryError(
            f"unrecognized space-group symbol {raw!r}; write gemmi's canonical name "
            "(e.g. 'P m -3 m', 'C 1 2/m 1', 'R -3 m:H', 'F d -3 m:2')"
        )
    if ":" not in raw and sg.ext in ("H", "R"):
        hexagonal, rhombohedral = (gemmi.find_spacegroup_by_name(f"{sg.hm}:{s}").xhm() for s in "HR")
        raise SymmetryError(
            f"space group {raw!r} does not name its setting; write {hexagonal!r} (hexagonal axes) "
            f"or {rhombohedral!r} (rhombohedral axes)"
        )
    if ":" not in raw and sg.ext in ("1", "2"):
        origin1, origin2 = (gemmi.find_spacegroup_by_name(f"{sg.hm}:{s}").xhm() for s in "12")
        raise SymmetryError(
            f"space group {raw!r} has two origin choices; write {origin1!r} or {origin2!r}"
        )
    if sg.crystal_system_str() == "monoclinic" and raw.replace(" ", "") != sg.hm.replace(" ", ""):
        # A short monoclinic symbol ("P21/c", "C2/m") leaves the unique axis and the cell
        # choice unstated; gemmi silently picks one, so list them all (review B3).
        by_axis: dict[str, list[str]] = {}
        for s in gemmi.spacegroup_table():
            if s.number == sg.number:
                by_axis.setdefault(_monoclinic_unique_axis(_expanded_ops(s)), []).append(repr(s.xhm()))
        choices = "; ".join(f"unique axis {axis}: {', '.join(names)}" for axis, names in sorted(
            by_axis.items(), key=lambda item: "bca".index(item[0])))
        raise SymmetryError(
            f"space group {raw!r} does not state its unique axis or cell choice (gemmi would read it "
            f"as {sg.xhm()!r}); write the setting you mean: {choices}"
        )
    raise SymmetryError(f"space group {raw!r} is not in the canonical form; write {sg.xhm()!r}")


def _expanded_ops(sg: gemmi.SpaceGroup) -> list[tuple[np.ndarray, np.ndarray]]:
    """All symmetry operations (centering expanded) as (R float 3x3, t float 3)."""
    den = float(gemmi.Op.DEN)
    ops = []
    for op in sg.operations():
        R = np.array(op.rot, dtype=float) / den
        t = np.array(op.tran, dtype=float) / den
        ops.append((R, t))
    return ops


# --- cell helpers --------------------------------------------------------


def _monoclinic_unique_axis(ops: list[tuple[np.ndarray, np.ndarray]]) -> str:
    """Unique axis of a monoclinic group: its 2-fold axis or its mirror/glide normal.

    Every operation of a monoclinic point group other than 1 and -1 is a proper
    2-fold (trace -1) or a mirror (trace +1). For either, ``det(R) R`` is a proper
    2-fold about the unique axis, whose invariant direction maps to the dominant
    cell axis a/b/c. Mirror-only groups (Pm, Pc, Cm, Cc) have no proper 2-fold,
    so the mirror normal is needed (A102).
    """
    for R, _t in ops:
        if abs(abs(np.trace(R)) - 1.0) < _MAT_TOL:
            evals, evecs = np.linalg.eig(np.sign(np.linalg.det(R)) * R)
            for i in range(3):
                if abs(evals[i].real - 1.0) < _MAT_TOL and abs(evals[i].imag) < _MAT_TOL:
                    direction = np.abs(evecs[:, i].real)
                    return _LENGTHS[int(np.argmax(direction))]
    raise SymmetryError(
        "could not determine the monoclinic unique axis (no 2-fold axis or mirror found)"
    )


# --- site helpers --------------------------------------------------------


def _wrap_symmetric(delta: np.ndarray) -> np.ndarray:
    """Map a fractional difference into (-0.5, 0.5] per component (mod-1 aware)."""
    return (delta + 0.5) % 1.0 - 0.5


def _classify(projector: np.ndarray) -> list[str]:
    """Per-component DOF from a projector ``P`` onto the allowed displacements.

    FIXED: row j of P is zero (no allowed displacement changes component j).
    FREE: ``P e_j == e_j`` (component j changes on its own). Otherwise COUPLED.
    Rows and columns of P differ when the rotations are not orthogonal in
    fractional coordinates (hexagonal/trigonal axes), so the FIXED test must use
    the row: e.g. 6h ``(x, 2x, 1/4)`` in P6_3/mmc has x COUPLED, not FIXED. The
    classification is checked against GSAS-II's site-symmetry tables for all 230
    space groups (``tests/test_symmetry_characterization.py``).
    """
    n = projector.shape[0]
    out = []
    for j in range(n):
        unit = np.zeros(n)
        unit[j] = 1.0
        if np.linalg.norm(projector[j, :]) < _MAT_TOL:
            out.append("FIXED")
        elif np.linalg.norm(projector[:, j] - unit) < _MAT_TOL:
            out.append("FREE")
        else:
            out.append("COUPLED")
    return out


def _adp_projector(stab_rots) -> np.ndarray:
    """Projector onto site-allowed U tensors (``U -> R U R^T``) in u11..u23 coordinates."""
    projector = np.zeros((6, 6))
    for R in stab_rots:
        for j in range(6):
            basis = np.zeros(6)
            basis[j] = 1.0
            projector[:, j] += _vec_from_sym(R @ _sym_from_vec(basis) @ R.T)
    return projector / len(stab_rots)


# --- Uij helpers ---------------------------------------------------------

def _sym_from_vec(v: np.ndarray) -> np.ndarray:
    return np.array([[v[0], v[3], v[4]], [v[3], v[1], v[5]], [v[4], v[5], v[2]]])


def _vec_from_sym(u: np.ndarray) -> np.ndarray:
    return np.array([u[0, 0], u[1, 1], u[2, 2], u[0, 1], u[0, 2], u[1, 2]])


# --- (d) core site validation (KI-03; A35, A69, A73) ------------------------


@dataclass(frozen=True)
class SiteAnalysis:
    """One atomic site, analyzed under the core schema rules.

    Attributes:
        stated: the coordinates as given.
        canonical: ``stated`` moved onto the special position by the least
            (orthogonal) change: equal to ``stated`` for a general position;
            on a special position, symmetry-fixed axes are exact (see
            ``exact``) and coupled axes satisfy their relation (to
            floating-point precision). Used here to find the stabilizer and
            the tie offsets. It is **not** what the engines receive: the
            validated core ``Phase`` holds those coordinates (A120), and keeps
            a tie group's first member as stated where ``canonical`` may move
            it (e.g. by ~1e-7 at a ``y = x + 1/3`` tie).
        exact: per axis, the exact rational value of a symmetry-fixed
            coordinate (``None`` for a free or coupled axis).
        axes: ``"FREE"`` / ``"FIXED"`` / ``"COUPLED"`` per axis.
        adp: the same classification for ``U11, U22, U33, U12, U13, U23``.
        multiplicity: site multiplicity in the conventional cell.
        stabilizer_order: number of operations fixing the site.
    """

    stated: tuple[float, float, float]
    canonical: tuple[float, float, float]
    exact: tuple[Fraction | None, Fraction | None, Fraction | None]
    axes: tuple[str, str, str]
    adp: tuple[str, str, str, str, str, str]
    multiplicity: int
    stabilizer_order: int

    @property
    def adjusted(self) -> bool:
        """True when ``canonical`` differs from ``stated`` beyond float noise."""
        return any(abs(c - s) > ADJUSTMENT_REPORT_TOL for c, s in zip(self.canonical, self.stated))


def _fmt_xyz(xyz) -> str:
    return "(" + ", ".join(f"{v:.6g}" for v in xyz) + ")"


def _fmt_exact(values, exact) -> str:
    return "(" + ", ".join(str(e) if e is not None else f"{v:.6f}" for v, e in zip(values, exact)) + ")"


def _barycenter(x: np.ndarray, ops) -> np.ndarray:
    """Mean of the stabilizer images of ``x``, each unwrapped next to ``x``.

    The barycenter of an orbit under a finite group is fixed by every element,
    so this is the nearest point fixed by all of ``ops``.
    """
    return x + np.mean([_wrap_symmetric(R @ x + t - x) for R, t in ops], axis=0)


def _is_group(ops) -> bool:
    """True when ``ops`` is closed under composition (translations mod 1)."""
    def key(R, t):
        return (tuple(np.rint(R).astype(int).ravel()), tuple(np.round(t % 1.0, 9) % 1.0))

    keys = {key(R, t) for R, t in ops}
    return all(key(R1 @ R2, R1 @ t2 + t1) in keys for R1, t1 in ops for R2, t2 in ops)


def _axes(stab_rots) -> list[str]:
    return _classify(sum(stab_rots) / len(stab_rots))


def _orthogonal_projector(reynolds: np.ndarray) -> np.ndarray:
    """Orthogonal projector onto the image of a (possibly oblique) Reynolds projector.

    The Reynolds average ``mean(R)`` projects onto the symmetric subspace, but not
    orthogonally when the rotations are not orthogonal (hexagonal/trigonal axes).
    The orthogonal projector gives the *least change* onto the same subspace, so
    a free component stays as stated and only inconsistent ones move (A73, A78).
    """
    u, sv, _vt = np.linalg.svd(reynolds)
    basis = u[:, sv > 0.5]  # a projector's nonzero singular values are >= 1 (1 if orthogonal)
    return basis @ basis.T


def analyze_site(space_group: str, xyz) -> SiteAnalysis:
    """Validate one site under the core schema rules and return its :class:`SiteAnalysis`.

    For every operation (centering expanded), the image distance ``d`` is
    computed. ``d < SPECIAL_POSITION_TOL`` puts the operation in the stabilizer.
    Any ``SPECIAL_POSITION_TOL <= d < AMBIGUOUS_BAND`` raises
    :class:`SymmetryError`: the site is near a special position without being on
    it (or is stated with too few decimals). The message names the special
    position and its multiplicity.

    ``space_group`` must name its setting explicitly (two-origin and
    rhombohedral groups, A62).
    """
    x = np.asarray(xyz, dtype=float)
    if x.shape != (3,) or not np.all(np.isfinite(x)):
        raise SymmetryError("xyz must be a finite 3-vector")
    ops = _expanded_ops(resolve_space_group(space_group, explicit_setting=True))
    dist = [float(np.max(np.abs(_wrap_symmetric(R @ x + t - x)))) for R, t in ops]

    ambiguous = [d for d in dist if SPECIAL_POSITION_TOL <= d < AMBIGUOUS_BAND]
    if ambiguous:
        near = [op for op, d in zip(ops, dist) if d < AMBIGUOUS_BAND]
        if _is_group(near):
            target = _barycenter(x, near)
            axes = _axes([R for R, _t in near])
            exact = [Fraction(float(v)).limit_denominator(_MAX_DENOMINATOR) if a == "FIXED" else None
                     for v, a in zip(target, axes)]
            where = (f"the special position {_fmt_exact(target, exact)} "
                     f"(multiplicity {len(ops) // len(near)})")
        else:  # near more than one special position: no single one to name
            where = "a special position"
        raise SymmetryError(
            f"position {_fmt_xyz(x)} is {max(ambiguous):.2g} from {where} in "
            f"{space_group!r} without being on it: state the special-position "
            f"coordinates to at least 6 decimals, or move the atom at least "
            f"{AMBIGUOUS_BAND:g} (fractional) off it"
        )

    stab = [op for op, d in zip(ops, dist) if d < SPECIAL_POSITION_TOL]
    if not stab:  # pragma: no cover - identity is always in the group
        raise SymmetryError("empty stabilizer (should be impossible)")
    axes = _axes([R for R, _t in stab])

    # Least change onto the stabilizer's fixed set: anchor at a fixed point (the
    # barycenter), then project the offset orthogonally onto the allowed directions.
    anchor = _barycenter(x, stab)
    canonical = anchor + _orthogonal_projector(sum(R for R, _t in stab) / len(stab)) @ (x - anchor)
    canonical = np.where(np.abs(canonical - x) <= ADJUSTMENT_REPORT_TOL, x, canonical)  # drop float noise
    exact: list[Fraction | None] = []
    for j in range(3):
        if axes[j] != "FIXED":
            exact.append(None)
            continue
        frac = Fraction(float(canonical[j])).limit_denominator(_MAX_DENOMINATOR)
        if abs(float(frac) - canonical[j]) > 1e-9:  # pragma: no cover - guards the 1/24 premise
            raise SymmetryError(
                f"fixed coordinate {canonical[j]!r} of {_fmt_xyz(x)} in {space_group!r} is not a "
                f"fraction with denominator <= {_MAX_DENOMINATOR}"
            )
        exact.append(frac)
        canonical[j] = float(frac)

    # Consistency: the canonical point is fixed exactly by the whole stabilizer,
    # and multiplicity x stabilizer order = group order.
    residual = max(float(np.max(np.abs(_wrap_symmetric(R @ canonical + t - canonical))))
                   for R, t in stab)
    if residual > 1e-9 or len(ops) % len(stab):  # pragma: no cover - internal invariant
        raise SymmetryError(
            f"inconsistent site analysis for {_fmt_xyz(x)} in {space_group!r} "
            f"(residual {residual:.2g}, |G|={len(ops)}, |stabilizer|={len(stab)})"
        )

    return SiteAnalysis(
        stated=(float(x[0]), float(x[1]), float(x[2])),
        canonical=(float(canonical[0]), float(canonical[1]), float(canonical[2])),
        exact=(exact[0], exact[1], exact[2]),
        axes=(axes[0], axes[1], axes[2]),
        adp=tuple(_classify(_adp_projector([R for R, _t in stab]))),
        multiplicity=len(ops) // len(stab),
        stabilizer_order=len(stab),
    )


# --- (e) cell and Uij consistency with symmetry (A76-A78) -------------------

#: Cell parameters must equal their symmetric values up to floating-point noise
#: (relative on lengths, degrees on angles): no adjustment, only an error (A77).
CELL_TOL = 1e-9
#: Uij within this of their site-symmetric values (Angstrom^2) are set to those
#: values and reported; beyond it is an error (A78). Allows for values printed
#: to ~6 decimals breaking relations such as U12 = U22/2.
UIJ_TOL = 1e-6

_CELL_NAMES = ("a", "b", "c", "alpha", "beta", "gamma")


def _metric(cell) -> np.ndarray:
    a, b, c, al, be, ga = cell
    ca, cb, cg = (np.cos(np.radians(v)) for v in (al, be, ga))
    return np.array([[a * a, a * b * cg, a * c * cb],
                     [a * b * cg, b * b, b * c * ca],
                     [a * c * cb, b * c * ca, c * c]])


def _cell_from_metric(g: np.ndarray) -> tuple[float, ...]:
    a, b, c = np.sqrt(np.diag(g))
    al = np.degrees(np.arccos(np.clip(g[1, 2] / (b * c), -1.0, 1.0)))
    be = np.degrees(np.arccos(np.clip(g[0, 2] / (a * c), -1.0, 1.0)))
    ga = np.degrees(np.arccos(np.clip(g[0, 1] / (a * b), -1.0, 1.0)))
    return tuple(float(v) for v in (a, b, c, al, be, ga))


def check_cell(space_group: str, cell) -> tuple[float, ...]:
    """Raise :class:`SymmetryError` unless ``cell`` (a, b, c, alpha, beta, gamma) fits the group.

    The cell's metric tensor must be invariant under every rotation of the
    space group (``R^T G R = G``). The check compares the stated cell with the
    cell of the group-averaged metric, within :data:`CELL_TOL`. Returns the
    symmetric cell. Covers every crystal system, including monoclinic unique
    axes and the rhombohedral ``:R`` setting.
    """
    rots = [R for R, _t in _expanded_ops(resolve_space_group(space_group, explicit_setting=True))]
    stated = tuple(float(v) for v in cell)
    g = _metric(stated)
    symmetric = _cell_from_metric(sum(R.T @ g @ R for R in rots) / len(rots))
    bad = []
    for name, v, s in zip(_CELL_NAMES, stated, symmetric):
        off = abs(v - s) / s if name in ("a", "b", "c") else abs(v - s)
        if off > CELL_TOL:
            bad.append(f"{name} = {v:g} (symmetric value {s:.10g})")
    if bad:
        system = resolve_space_group(space_group, explicit_setting=True).crystal_system_str()
        raise SymmetryError(
            f"unit cell is inconsistent with {space_group!r} ({system}): " + "; ".join(bad)
            + ". Symmetry-equivalent lengths must be equal and symmetry-fixed angles exact "
            "(e.g. 90 or 120 degrees)"
        )
    return symmetric


_UIJ_NAMES = ("U11", "U22", "U33", "U12", "U13", "U23")


# --- (f) tie groups: cell (A95) and site coupling groups (A94, A98, A102) ---


@dataclass(frozen=True)
class TieGroup:
    """Parameters that are one parameter by symmetry: ``member = k * rep + c``.

    The first member is the representative (``k = 1``, ``c = 0``). ``k`` and
    ``c`` are exact. Offsets are nonzero only for coordinates (affine ties such
    as ``(x, x+1/2, z)``); they come from the canonical position, so they
    reflect the lattice translate that was stated (A98). Cell ties are equalities.

    Attributes:
        members: parameter names, in canonical order (a..gamma, x/y/z, U11..U23).
        coefficients: ``k`` per member.
        offsets: ``c`` per member.
    """

    members: tuple[str, ...]
    coefficients: tuple[Fraction, ...]
    offsets: tuple[Fraction, ...]

    def relation(self, member: str) -> tuple[Fraction, Fraction]:
        """``(k, c)`` of ``member = k * rep + c``."""
        i = self.members.index(member)
        return self.coefficients[i], self.offsets[i]

    def relation_text(self, member: str) -> str:
        """``member``'s relation to the representative, e.g. ``"y = x + 1/2"`` or ``"b = a"``."""
        k, c = self.relation(member)
        return f"{member} = {_affine_text(k, self.members[0], c)}"

    def relations_text(self) -> str:
        """The non-trivial relations, e.g. ``"y = x + 1/2"`` or ``"U12 = U22/2"``; ``""`` for equal ties."""
        rep = self.members[0]
        parts = [f"{m} = {_affine_text(k, rep, c)}" for m, k, c in
                 zip(self.members[1:], self.coefficients[1:], self.offsets[1:]) if (k, c) != (1, 0)]
        return ", ".join(parts)


@dataclass(frozen=True)
class Ties:
    """Symmetry ties of one parameter set: tie groups of the free parameters, and the fixed ones.

    Every parameter is in exactly one group or in ``fixed``. A singleton group is
    an independent parameter.
    """

    groups: tuple[TieGroup, ...]
    fixed: tuple[str, ...]

    def group_of(self, name: str) -> TieGroup | None:
        return next((g for g in self.groups if name in g.members), None)


@dataclass(frozen=True)
class CellTies(Ties):
    """:class:`Ties` of the unit cell, with the crystal system and monoclinic unique axis."""

    crystal_system: str = ""
    unique_axis: str | None = None


@dataclass(frozen=True)
class SiteTies:
    """Coordinate and Uij :class:`Ties` of one atomic site (U11, U22, U33, U12, U13, U23)."""

    xyz: Ties
    uij: Ties


def _affine_text(k: Fraction, rep: str, c: Fraction) -> str:
    sign = "-" if k < 0 else ""
    k = abs(k)
    term = f"{sign}{k.numerator if k.numerator != 1 else ''}{rep}" + (f"/{k.denominator}" if k.denominator != 1 else "")
    if c == 0:
        return term
    return f"{term} {'+' if c > 0 else '-'} {abs(c)}"


def _equal_group(names) -> TieGroup:
    n = len(names)
    return TieGroup(tuple(names), (Fraction(1),) * n, (Fraction(0),) * n)


def cell_tie_groups(space_group: str) -> CellTies:
    """Cell tie groups for ``space_group``: equal lengths, tied free angles, fixed angles.

    Every free group is one parameter (A94): cubic ``{a, b, c}``; tetragonal and
    hexagonal axes ``{a, b}``, ``{c}``; rhombohedral axes (``:R``) ``{a, b, c}`` and
    ``{alpha, beta, gamma}``; monoclinic: each length plus the unique-axis angle
    (A102); triclinic: all six independent; ``:R`` is covered. The setting must
    be explicit (A62).
    """
    sg = resolve_space_group(space_group, explicit_setting=True)
    system = sg.crystal_system_str()
    lengths = [_equal_group((n,)) for n in _LENGTHS]
    if system == "cubic":
        return CellTies((_equal_group(_LENGTHS),), _ANGLES, system)
    if system in ("tetragonal", "hexagonal", "trigonal"):
        if sg.ext == "R":
            return CellTies((_equal_group(_LENGTHS), _equal_group(_ANGLES)), (), system)
        return CellTies((_equal_group(("a", "b")), _equal_group(("c",))), _ANGLES, system)
    if system == "orthorhombic":
        return CellTies(tuple(lengths), _ANGLES, system)
    if system == "monoclinic":
        unique = _monoclinic_unique_axis(_expanded_ops(sg))
        free = {"a": "alpha", "b": "beta", "c": "gamma"}[unique]
        return CellTies((*lengths, _equal_group((free,))), tuple(a for a in _ANGLES if a != free),
                        system, unique)
    if system == "triclinic":
        return CellTies((*lengths, *(_equal_group((a,)) for a in _ANGLES)), (), system)
    raise SymmetryError(  # pragma: no cover - gemmi has no other crystal system
        f"unsupported crystal system {system!r} for space group {space_group!r}"
    )


def _snap(value: float, max_denominator: int, what: str) -> Fraction:
    frac = Fraction(value).limit_denominator(max_denominator)
    if abs(float(frac) - value) > 1e-9:  # pragma: no cover - internal invariant
        raise SymmetryError(f"{what} {value!r} is not a simple fraction (internal error)")
    return frac


def _tie_groups(projector: np.ndarray, names, values=None) -> Ties:
    """Tie groups = connected components of the orthogonal projector's nonzero entries.

    Each component must have one degree of freedom (rank 1). Its relation comes
    from the component's basis vector; with ``values`` (the canonical
    coordinates) the affine offsets ``c = member - k * rep`` are added.
    """
    n = len(names)
    fixed = [np.linalg.norm(projector[j, :]) < _MAT_TOL for j in range(n)]
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            i = parent[i]
        return i

    for j in range(n):
        for k in range(j + 1, n):
            if not fixed[j] and not fixed[k] and abs(projector[j, k]) > _MAT_TOL:
                parent[find(k)] = find(j)
    components: dict[int, list[int]] = {}
    for j in range(n):
        if not fixed[j]:
            components.setdefault(find(j), []).append(j)
    groups = []
    for members in sorted(components.values()):
        block = projector[np.ix_(members, members)]
        if abs(np.trace(block) - 1.0) > 1e-6:  # pragma: no cover - checked exhaustively in the tests
            raise SymmetryError(f"tie group {[names[j] for j in members]} has "
                                f"{np.trace(block):.3g} degrees of freedom (internal error)")
        basis = block[:, int(np.argmax(np.diag(block)))]
        ks = tuple(_snap(float(b / basis[0]), 12, "tie coefficient") for b in basis)
        if values is None:
            cs = (Fraction(0),) * len(members)
        else:
            rep = values[members[0]]
            cs = tuple(_snap(float(values[j] - float(k) * rep), _MAX_DENOMINATOR, "tie offset")
                       for j, k in zip(members, ks))
        groups.append(TieGroup(tuple(names[j] for j in members), ks, cs))
    return Ties(tuple(groups), tuple(names[j] for j in range(n) if fixed[j]))


def coupling_groups(space_group: str, xyz) -> SiteTies:
    """Coordinate and Uij tie groups of the site at ``xyz`` (A94, A95, A98).

    The site is analyzed first (:func:`analyze_site`; ambiguous positions raise),
    and the groups are taken at its canonical position. Non-fixed components are
    grouped by connectivity of the **orthogonal** projector onto the allowed
    subspace (the oblique Reynolds average gives wrong Uij groups on hexagonal
    axes). Every group has one degree of freedom: one engine parameter.
    Coordinate relations are affine (``y = x + 1/2`` at P-42_1m 4e), with the
    offset taken from the canonical values; Uij relations are linear
    (``U12 = U22/2``, ``U13 = -U23``). Checked against GSAS-II's
    ``GetCSxinel``/``GetCSuinel`` over every distinct special site on the 1/24
    grid of every setting GSAS-II reads (``tests/test_symmetry_characterization.py``).
    """
    site = analyze_site(space_group, xyz)
    x = np.asarray(site.canonical)
    ops = _expanded_ops(resolve_space_group(space_group, explicit_setting=True))
    stab = [R for R, t in ops if np.max(np.abs(_wrap_symmetric(R @ x + t - x))) < SPECIAL_POSITION_TOL]
    return SiteTies(
        xyz=_tie_groups(_orthogonal_projector(sum(stab) / len(stab)), _AXIS_LETTERS, x),
        uij=_tie_groups(_orthogonal_projector(_adp_projector(stab)), _UIJ_NAMES),
    )


def orbit(space_group: str, xyz) -> list[tuple[float, float, float]]:
    """The positions equivalent to ``xyz`` in the conventional cell, in gemmi's operation order.

    Each image is reduced to [0, 1); an image within ``SPECIAL_POSITION_TOL``
    of an earlier one (mod 1) is the same position and left out, so the list
    has the site's multiplicity. The order is fixed by gemmi's operations, so
    "the first member that ..." is reproducible. Engine-free; the gsasii gateway
    uses it to name a position GSAS-II reads correctly (A117, EB-40, EB-05).
    """
    sg = resolve_space_group(space_group, explicit_setting=True)
    x = np.asarray(xyz, dtype=float)
    points: list[np.ndarray] = []
    for R, t in _expanded_ops(sg):
        y = (R @ x + t) % 1.0
        y[np.abs(y - 1.0) < 1e-12] = 0.0
        if not any(np.all(np.abs(_wrap_symmetric(y - p)) < SPECIAL_POSITION_TOL) for p in points):
            points.append(y)
    return [tuple(float(v) for v in p) for p in points]
