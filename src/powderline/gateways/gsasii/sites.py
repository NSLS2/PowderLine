"""GSAS-II gateway — check GSAS-II's reading of each atom's site after phase setup (A117).

GSAS-II misreads some orientations of the 2-fold sites in R32, R-3m and R-3c
(``:H``): it calls them general (``'1'``) with **double** the multiplicity, so the
site weight doubles and intensities are wrong even with nothing refined (EB-40;
probe ``re04_eb40_orientation_probe.py``: 4x the intensity). Some sites it cannot
name (``'sp'``), and then refining a coordinate or ``Uaniso`` crashes its
constraint setup (EB-05). Core is right at both, so the check is a run-time error
that names an equivalent position GSAS-II reads correctly: the first member of
the atom's orbit (core's order, :func:`powderline.symmetry.orbit`) that
GSAS-II's ``SytSym`` gives core's multiplicity and a name. Never a silent
substitution: the refined coordinates would differ from the recipe's.

Runtime layer: imports GSAS-II.
"""

from __future__ import annotations

from fractions import Fraction

from GSASII import GSASIIspc as G2spc

from powderline.exceptions import EngineExecutionError
from powderline.symmetry import orbit


def _coordinate(v: float) -> str:
    """A coordinate as a recipe states it (A120, A121): exactly when it has a finite decimal form, else to 6 decimals."""
    frac = Fraction(v).limit_denominator(48)
    if abs(float(frac) - v) < 1e-9:
        d = frac.denominator
        while d % 2 == 0:
            d //= 2
        while d % 5 == 0:
            d //= 5
        return repr(float(frac)) if d == 1 else f"{float(frac):.6f}"  # 1/5 -> 0.2; 1/3 -> 0.333333
    return repr(round(v, 10))


def site_problems(proj, phases) -> list[str]:
    """Every atom GSAS-II reads wrongly (EB-40) or cannot name while a coordinate/Uaniso is refined (EB-05).

    ``phases`` is the validated payload's ``phases`` (name -> ``GsasiiPhase``).
    """
    problems = []
    for name, phase in phases.items():
        data = proj.data["Phases"][name]
        sgdata = data["General"]["SGData"]
        records = {rec[0]: rec for rec in data["Atoms"]}
        for label, atom in phase.atoms.items():
            gsym, gmult = records[label][7], records[label][8]
            core = phase.site(label).multiplicity
            refined_xyz_or_uij = any(getattr(atom, k).refine_flag for k in ("x", "y", "z")) or (
                atom.Uaniso is not None and any(p.refine_flag for _, p in atom.Uaniso))
            xyz = (atom.x.value, atom.y.value, atom.z.value)
            if gmult != core:
                why = (f"GSAS-II reads it as site {gsym!r} with multiplicity {gmult}, but its multiplicity is {core}: "
                       "the site weight would be wrong, so the intensities would be (GSAS-II quirk EB-40)")
            elif gsym == "sp" and refined_xyz_or_uij:
                why = ("GSAS-II cannot name its site symmetry ('sp') and fails when a coordinate or Uaniso of such a "
                       "site is refined (GSAS-II quirk EB-05)")
            else:
                continue
            suggestion = next((p for p in orbit(phase.space_group, xyz)
                               if (lambda s: s[1] == core and s[0] != "sp")(G2spc.SytSym(list(p), sgdata)[:2])),
                              None)
            where = f"payload.phases.{name}.atoms.{label} at ({', '.join(_coordinate(v) for v in xyz)})"
            if suggestion is None:
                problems.append(f"{where}: {why}; no equivalent position GSAS-II reads correctly was found")
            else:
                aniso = ("; its Uaniso must be transformed by the same symmetry operation (U' = R U R^T), not just "
                         "made site-symmetric" if atom.Uaniso is not None else "")
                problems.append(f"{where}: {why}; state the equivalent position "
                                f"({', '.join(_coordinate(v) for v in suggestion)}) instead{aniso}")
    return problems


def check_sites(proj, recipe) -> None:
    """Raise ``EngineExecutionError`` listing every atom :func:`site_problems` finds."""
    phases = getattr(recipe.payload, "phases", None) or {}
    problems = site_problems(proj, phases)
    if problems:
        raise EngineExecutionError("GSAS-II cannot use these atom positions as stated:\n"
                                   + "\n".join(f"  - {p}" for p in problems), reason="unusable_site")
