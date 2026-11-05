"""easydiffraction gateway — build an easydiffraction project from a validated ``easydiffraction.rietveld`` model.

The builder consumes the validated model (A39): every value it sets is the
model's, so special-position coordinates and tied values are exact (A120,
A121) and easydiffraction's Wyckoff detection (1e-3 tolerance, EB-47, EB-74)
never moves one.

- **Data** (A149, A154, A158): the weighted points within core's
  ``fit_limits_on_data``, handed over as a CIF data loop at full precision
  (easydiffraction's ASCII reader rounds 2theta to 4 decimals, EB-72).
- **Order**: calculator, then peak type, then the profile values (switching
  either resets the profile, EB-76).
- **Free parameters**: one easydiffraction parameter per refined symmetry tie
  group (A94), the member easydiffraction leaves free; its bounds are the
  recipe's (F4 keeps the group consistent). A stated bound becomes
  ``fit_min``/``fit_max``; a ``null`` side keeps easydiffraction's physical
  limit, which the minimizer applies (A157 B4, EB-71). Fixed parameters are
  never freed (F2).
- **Atom order**: anisotropic atoms are handed over first (A169). easydiffraction
  0.21.1's CrysPy update during a fit writes a refined anisotropic tensor into
  the column of its place among the anisotropic atoms, not its own, so an
  anisotropic atom after an isotropic one would keep its starting tensor
  (EB-86). Order is not physics; everything is keyed by label.
- **Preferred orientation** (P-48): a phase's ``preferred_orientation`` block becomes one
  ``preferred_orientation`` row of the experiment, keyed by the lowercase linked structure
  name (a row keyed otherwise is ignored silently, EB-97), with ``march_r`` and
  ``march_random_fract`` freed when flagged.
- **Checks after the build** (errors, never substitutions): easydiffraction's
  multiplicity of every atom equals core's and no coordinate moved (EB-47),
  except by a lattice translation: easydiffraction stores a template-pattern
  position in its own writing, e.g. (0.137, 0.863, z) on (x, -x, z) as
  (0.137, -0.137, z), the same atom (EB-74, A176). Such a translation is kept
  per atom: stated bounds of a free coordinate are moved with it, reports give
  the recipe's writing, and the run warns;
  with CrysPy, an atom on a special position with a free coordinate is
  written in the pattern of easydiffraction's template for its site, since
  CrysPy computes wrong structure factors for the other images (EB-77).

Runtime layer: imports easydiffraction.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from powderline.exceptions import EngineExecutionError
from powderline.gateways.easydiffraction.schema import PHYSICAL_LIMITS, easydiffraction_space_group
from powderline.schema_core import BoundedRefinableParameter
from powderline.symmetry import cell_tie_groups, coupling_groups, orbit

EXPERIMENT_NAME = "powderline"
_CELL = {"a": "length_a", "b": "length_b", "c": "length_c",
         "alpha": "angle_alpha", "beta": "angle_beta", "gamma": "angle_gamma"}
_XYZ = {"x": "fract_x", "y": "fract_y", "z": "fract_z"}
_UIJ = {"U11": "adp_11", "U22": "adp_22", "U33": "adp_33", "U12": "adp_12", "U13": "adp_13", "U23": "adp_23"}


@dataclass
class FreeParameter:
    """One parameter handed to lmfit, and where it comes from in the recipe."""

    parameter: object
    name: str
    path: str
    descriptive: str
    category: str
    phase: Optional[str] = None
    atom: Optional[str] = None
    #: (min, max) acting in the fit and who set each side: "stated", "physical" or None.
    limits: tuple = (None, None)
    limit_source: tuple = (None, None)
    #: The recipe members this parameter stands for (a tie group), each with its relation k, c.
    members: tuple = ()
    #: Added to easydiffraction's value to give the recipe's writing (a lattice translation, A176).
    report_offset: float = 0.0
    #: The recipe's starting value: the scale of "at a zero limit" (A181).
    start: float = 0.0


@dataclass
class Build:
    project: object
    experiment: object
    structures: dict
    free: list = field(default_factory=list)
    mask: np.ndarray = None
    tth: np.ndarray = None
    #: (phase, label) -> (stated - held) per coordinate, integers: positions easydiffraction holds translated.
    translations: dict = field(default_factory=dict)


def structure_name(phase: str) -> str:
    """easydiffraction datablock name: the phase name lowercased (unique by A112; uppercase is refused, EB-45)."""
    return phase.lower()


def _cif_number(v) -> str:
    """``v`` at full precision without an exponent: easydiffraction's CIF loop cannot read ``5e-05`` (EB-89)."""
    return np.format_float_positional(float(v), unique=True, trim="-")


def data_cif(tth: np.ndarray, yobs: np.ndarray, sigma: np.ndarray) -> str:
    """An experiment CIF holding only the experiment type and the data, numbers at full precision (EB-72, EB-89)."""
    lines = ["data_" + EXPERIMENT_NAME, "_experiment_type.sample_form powder",
             '_experiment_type.beam_mode "constant wavelength"', "_experiment_type.radiation_probe xray",
             "_experiment_type.scattering_type bragg", "", "loop_", "_data.two_theta", "_data.intensity_meas",
             "_data.intensity_meas_su"]
    lines += [f"{_cif_number(x)} {_cif_number(y)} {_cif_number(s)}" for x, y, s in zip(tth, yobs, sigma)]
    return "\n".join(lines) + "\n"


def _bounds(p: BoundedRefinableParameter, physical: tuple) -> tuple[tuple, tuple]:
    """The limits acting in the fit: stated bounds, else easydiffraction's physical limit (A157 B4)."""
    limits, source = [], []
    for stated, phys in zip((p.min, p.max), physical):
        if stated is not None:
            limits.append(stated)
            source.append("stated")
        elif phys is not None:
            limits.append(phys)
            source.append("physical")
        else:
            limits.append(None)
            source.append(None)
    return tuple(limits), tuple(source)


def _free(build: Build, param, p: BoundedRefinableParameter, *, name: str, path: str, descriptive: str,
          category: str, physical: tuple = (None, None), phase=None, atom=None, members=(), offset: float = 0.0) -> None:
    """Free ``param`` with the recipe's bounds; ``offset`` = recipe writing - easydiffraction's (A176)."""
    param.free = True
    if p.min is not None:
        param.fit_min = p.min - offset
    if p.max is not None:
        param.fit_max = p.max - offset
    limits, source = _bounds(p, physical)
    limits = tuple(None if v is None else (v - offset if src == "stated" else v) for v, src in zip(limits, source))
    build.free.append(FreeParameter(param, name, path, descriptive, category, phase, atom, limits, source,
                                    members or ((name, 1, 0),), offset, float(p.value)))


def _set(obj, name: str, value) -> None:
    setattr(obj, name, value)


def engine_atom_order(phase) -> list[tuple[str, object]]:
    """The phase's ``(label, atom)`` pairs in the order handed to easydiffraction: anisotropic first (A169, EB-86)."""
    return sorted(phase.atoms.items(), key=lambda item: item[1].Uaniso is None)  # stable: recipe order otherwise


def build_project(model) -> Build:
    """The easydiffraction project for a validated ``easydiffraction.rietveld`` model (see the module docstring)."""
    from easydiffraction import ExperimentFactory, Project, StructureFactory
    from easydiffraction.utils.logging import Logger

    Logger.configure(reaction=Logger.Reaction.RAISE)  # a refused value never becomes a silent default (EB-48)
    p = model.payload
    rc = p.refinement_controls

    mask = p.window_mask()
    tth = np.asarray(p.xrd_data.tth, dtype=float)
    yobs = np.asarray(p.xrd_data.Itth, dtype=float)
    w = np.asarray(p.xrd_data.Itth_weights, dtype=float)
    expt = ExperimentFactory.from_cif_str(data_cif(tth[mask], yobs[mask], 1.0 / np.sqrt(w[mask])))
    build = Build(project=None, experiment=expt, structures={}, mask=mask, tth=tth)

    # calculator, then peak type, then the profile (EB-76)
    expt.calculator.type = rc.calculator
    profile = p.instrument.broadening
    expt.peak.type = profile.peak_type
    if profile.cutoff_fwhm is not None:
        expt.peak.cutoff_fwhm = profile.cutoff_fwhm
    for name in type(profile.parameters).model_fields:
        _set(expt.peak, name, getattr(profile.parameters, name).value)

    inst = p.instrument
    radiation = inst.radiation
    expt.instrument.setup_wavelength = radiation.setup_wavelength.value
    if radiation.setup_wavelength_2 is not None:
        expt.instrument.setup_wavelength_2 = radiation.setup_wavelength_2
        expt.instrument.setup_wavelength_2_to_1_ratio = radiation.setup_wavelength_2_to_1_ratio
    if inst.polarization is not None:
        expt.instrument.setup_polarization_coefficient = inst.polarization.setup_polarization_coefficient
        expt.instrument.setup_monochromator_twotheta = inst.polarization.setup_monochromator_twotheta
    corrections = inst.corrections
    for name in ("calib_twotheta_offset", "calib_sample_displacement", "calib_sample_transparency"):
        if getattr(corrections, name) is not None:
            _set(expt.instrument, name, getattr(corrections, name).value)
    if inst.absorption is not None:
        expt.absorption.type = inst.absorption.type
        expt.absorption.mu_r = inst.absorption.mu_r.value

    if p.background is not None:
        cheb = p.background.chebyshev
        expt.background.type = "chebyshev"
        for k, c in enumerate(cheb.coefficients):
            expt.background.create(id=str(k), order=k, coef=c)

    for name, phase in p.phases.items():
        s = StructureFactory.from_scratch(name=structure_name(name))
        sg_name, code = easydiffraction_space_group(phase.space_group)
        s.space_group.name_h_m = sg_name
        if code:
            s.space_group.coord_system_code = code
        for member, attr in _CELL.items():
            _set(s.cell, attr, getattr(phase.unit_cell, member).value)
        for label, atom in engine_atom_order(phase):
            s.atom_sites.create(id=label, type_symbol=(phase.scattering_types or {}).get(label, atom.element),  # P-47
                                fract_x=atom.x.value, fract_y=atom.y.value,
                                fract_z=atom.z.value, occupancy=atom.occupancy.value)
            site = s.atom_sites[label]
            if atom.ADP == "Uiso":
                site.adp_type = "Uiso"
                site.adp_iso = atom.Uiso.value
            else:
                site.adp_type = "Uani"
                aniso = s.atom_site_aniso[label]
                for key, attr in _UIJ.items():
                    _set(aniso, attr, getattr(atom.Uaniso, key).value)
        expt.linked_structures.create(structure_id=structure_name(name), scale=phase.scale.value)
        build.structures[name] = s

    project = Project()
    for s in build.structures.values():
        project.structures.add(s)
    project.experiments.add(expt)
    build.project = project
    for s in build.structures.values():
        s._update_categories()  # Wyckoff detection and symmetry constraints, as at the first calculation
    check_sites(model, build)
    _free_parameters(model, build)
    return build


def _free_parameters(model, build: Build) -> None:
    p = model.payload
    expt = build.experiment
    inst = p.instrument
    pre = "payload.instrument"
    if inst.radiation.setup_wavelength.refine_flag:
        _free(build, expt.instrument.setup_wavelength, inst.radiation.setup_wavelength, name="setup_wavelength",
              path=f"{pre}.radiation.setup_wavelength", descriptive="wavelength", category="instrument",
              physical=PHYSICAL_LIMITS["nonnegative"])
    for name in ("calib_twotheta_offset", "calib_sample_displacement", "calib_sample_transparency"):
        q = getattr(inst.corrections, name)
        if q is not None and q.refine_flag:
            _free(build, getattr(expt.instrument, name), q, name=name, path=f"{pre}.corrections.{name}",
                  descriptive=name, category="corrections")
    if inst.absorption is not None and inst.absorption.mu_r.refine_flag:
        _free(build, expt.absorption.mu_r, inst.absorption.mu_r, name="mu_r", path=f"{pre}.absorption.mu_r",
              descriptive="absorption mu R", category="corrections", physical=PHYSICAL_LIMITS["nonnegative"])
    parameters = inst.broadening.parameters
    for name in type(parameters).model_fields:
        q = getattr(parameters, name)
        if q.refine_flag:
            _free(build, getattr(expt.peak, name), q, name=name, path=f"{pre}.broadening.parameters.{name}",
                  descriptive=name, category="instrument_broadening")
    if p.background is not None and p.background.chebyshev.refine_flag:
        for k, term in enumerate(expt.background):
            term.coef.free = True
            build.free.append(FreeParameter(term.coef, f"background_coefficient_{k}", "payload.background.chebyshev",
                                            f"Chebyshev coefficient {k}", "background", members=((str(k), 1, 0),)))

    for name, phase in p.phases.items():
        s = build.structures[name]
        ppath = f"payload.phases.{name}"
        if phase.scale.refine_flag:
            _free(build, expt.linked_structures[structure_name(name)].scale, phase.scale, name=f"{name}_scale",
                  path=f"{ppath}.scale", descriptive=f"{name} scale", category="scale", phase=name,
                  physical=PHYSICAL_LIMITS["nonnegative"])
        po = phase.preferred_orientation
        if po is not None:                                       # March-Dollase row for this structure (P-48)
            # the row is keyed by the *linked structure's* name (the lowercased phase name): a row with any other
            # structure_id is silently ignored by the CrysPy calculator (EB-97)
            expt.preferred_orientation.create(structure_id=structure_name(name), march_r=po.ratio.value,
                                              march_random_fract=po.march_random_fract.value,
                                              index_h=int(po.hkl[0]), index_k=int(po.hkl[1]), index_l=int(po.hkl[2]))
            row = next(r for r in expt.preferred_orientation if r.structure_id.value == structure_name(name))
            if po.ratio.refine_flag:
                _free(build, row.march_r, po.ratio, name=f"{name}_march_r", path=f"{ppath}.preferred_orientation.ratio",
                      descriptive=f"{name} March-Dollase r", category="preferred_orientation", phase=name,
                      physical=(0.0, None))
            if po.march_random_fract.refine_flag:
                _free(build, row.march_random_fract, po.march_random_fract, name=f"{name}_march_random_fract",
                      path=f"{ppath}.preferred_orientation.march_random_fract",
                      descriptive=f"{name} March-Dollase random fraction", category="preferred_orientation",
                      phase=name, physical=(0.0, 1.0))
        for group in cell_tie_groups(phase.space_group).groups:
            _free_group(build, s.cell, _CELL, phase.unit_cell, group, path=f"{ppath}.unit_cell", phase=name,
                        category="unit_cell",
                        physical=PHYSICAL_LIMITS["cell_length" if group.members[0] in "abc" else "cell_angle"])
        for label, atom in phase.atoms.items():
            site = s.atom_sites[label]
            apath = f"{ppath}.atoms.{label}"
            ties = coupling_groups(phase.space_group, (atom.x.value, atom.y.value, atom.z.value))
            shift = dict(zip("xyz", build.translations.get((name, label), (0, 0, 0))))
            for group in ties.xyz.groups:
                _free_group(build, site, _XYZ, atom, group, path=apath, phase=name, atom=label, category="atom_xyz",
                            offsets=shift)
            if atom.occupancy.refine_flag:
                _free(build, site.occupancy, atom.occupancy, name=f"{name}_{label}_occupancy",
                      path=f"{apath}.occupancy", descriptive=f"{label} occupancy", category="atom_occupancy",
                      phase=name, atom=label, physical=PHYSICAL_LIMITS["occupancy"])
            if atom.Uiso is not None and atom.Uiso.refine_flag:
                _free(build, site.adp_iso, atom.Uiso, name=f"{name}_{label}_Uiso", path=f"{apath}.Uiso",
                      descriptive=f"{label} Uiso", category="atom_adp", phase=name, atom=label,
                      physical=PHYSICAL_LIMITS["adp"])
            if atom.Uaniso is not None:
                for group in ties.uij.groups:
                    physical = PHYSICAL_LIMITS["adp"] if group.members[0] in ("U11", "U22", "U33") else (None, None)
                    _free_group(build, s.atom_site_aniso[label], _UIJ, atom.Uaniso, group, path=f"{apath}.Uaniso",
                                phase=name, atom=label, category="atom_adp", physical=physical)


def _free_group(build: Build, holder, attrs: dict, recipe, group, *, path: str, phase: str, category: str,
                atom: Optional[str] = None, physical: tuple = (None, None), offsets: Optional[dict] = None) -> None:
    """Free one tie group: the member easydiffraction leaves free (its constraints tie the others, EB-47)."""
    members = group.members
    if not getattr(recipe, members[0]).refine_flag:  # F1: the whole group shares the flag
        return
    unconstrained = [m for m in members if not getattr(holder, attrs[m]).symmetry_constrained]
    if len(unconstrained) != 1:
        where = f"{path} ({', '.join(members)})"
        raise EngineExecutionError(
            f"easydiffraction does not tie {where} as core does: it leaves {unconstrained or 'none'} free where "
            "core has one parameter (EB-47); the refinement would not be the recipe's", reason="unusable_site")
    m = unconstrained[0]
    owner = f"{atom} " if atom else ""
    _free(build, getattr(holder, attrs[m]), getattr(recipe, m), name=f"{phase}_{atom + '_' if atom else ''}{m}",
          path=f"{path}.{m}", descriptive=f"{phase} {owner}{m}", category=category, phase=phase, atom=atom,
          physical=physical if m in ("a", "b", "c", "alpha", "beta", "gamma", "U11", "U22", "U33") else (None, None),
          members=tuple((name, k, c) for name, k, c in zip(members, group.coefficients, group.offsets)),
          offset=(offsets or {}).get(m, 0))


# --- checks after the build ---------------------------------------------------------------


def _template_exprs(template: str) -> list[str]:
    """``"(2x,x,-z+1/2)"`` -> ``["2*x", "x", "-z+1/2"]`` (implicit products made explicit)."""
    return [re.sub(r"(\d)([xyz])", r"\1*\2", e.strip()) for e in template.strip("()").split(",")]


def _matches_template(template: str, xyz: tuple) -> bool:
    """True when ``xyz`` has the pattern of easydiffraction's template, e.g. ``(x,1/2,1/2)`` (any x)."""
    exprs = _template_exprs(template)
    values: dict = {}
    for expr, v in zip(exprs, xyz):
        if expr in ("x", "y", "z"):
            if expr in values and abs(((values[expr] - v) + 0.5) % 1.0 - 0.5) > 1e-9:
                return False
            values.setdefault(expr, v)
    for expr, v in zip(exprs, xyz):
        try:
            want = float(eval(expr, {"__builtins__": {}}, values))  # template arithmetic: x, -x, 2x, x+1/2, 1/4
        except NameError:
            return False
        if abs(((want - v) + 0.5) % 1.0 - 0.5) > 1e-9:
            return False
    return True


def site_problems(model, build: Build) -> list[str]:
    """Atoms easydiffraction reads differently from core (EB-47), or CrysPy computes wrongly (EB-77).

    A position easydiffraction holds translated by a lattice vector is the same atom: it is recorded in
    ``build.translations`` (EB-74, A176), not a problem.
    """
    import easydiffraction.crystallography.crystallography as ecr

    problems = []
    cryspy = model.payload.refinement_controls.calculator == "cryspy"
    for name, phase in model.payload.phases.items():
        s = build.structures[name]
        sg_name, code = easydiffraction_space_group(phase.space_group)
        table = ecr.space_group_wyckoff_table(sg_name, code or None) or {}
        for label, atom in phase.atoms.items():
            site = s.atom_sites[label]
            stated = (atom.x.value, atom.y.value, atom.z.value)
            held = (site.fract_x.value, site.fract_y.value, site.fract_z.value)
            where = f"payload.phases.{name}.atoms.{label}"
            core_mult = phase.site(label).multiplicity
            shift = tuple(a - b for a, b in zip(stated, held))
            translated = all(abs(d - round(d)) <= 1e-9 for d in shift)
            if site.multiplicity.value != core_mult:
                problems.append(f"{where}: easydiffraction reads the position {stated} as Wyckoff "
                                f"{site.wyckoff_letter.value!r} with multiplicity {site.multiplicity.value} at "
                                f"{held}; core has multiplicity {core_mult} (EB-47)")
                continue
            if not translated:
                problems.append(f"{where}: easydiffraction moved the position {stated} to {held} (Wyckoff "
                                f"{site.wyckoff_letter.value!r}), not by a lattice translation; state the position "
                                "exactly (EB-47, EB-74)")
                continue
            if any(round(d) for d in shift):
                build.translations[(name, label)] = tuple(int(round(d)) for d in shift)
            entry = table.get(site.wyckoff_letter.value)
            free_coordinate = entry is not None and any(c in entry["coords_xyz"][0] for c in "xyz")
            if not (cryspy and free_coordinate and core_mult < len(orbit(phase.space_group, (0.1371, 0.2713, 0.3893)))):
                continue
            template = entry["coords_xyz"][0]
            if _matches_template(template, stated):
                continue
            suggestion = next((pos for pos in orbit(phase.space_group, stated) if _matches_template(template, pos)),
                              None)
            hint = ("" if suggestion is None else
                    f"; state the equivalent position ({', '.join(f'{v:.10g}' for v in suggestion)}) instead"
                    + ("; transform its Uaniso by the same symmetry operation (U' = R U R^T)"
                       if atom.Uaniso is not None else ""))
            problems.append(f"{where}: CrysPy computes wrong structure factors for this image of Wyckoff "
                            f"{site.wyckoff_letter.value} {stated}: write it in the pattern {template} (EB-77){hint}")
    return problems


def check_sites(model, build: Build) -> None:
    problems = site_problems(model, build)
    if problems:
        raise EngineExecutionError("easydiffraction cannot use these atom positions as stated:\n"
                                   + "\n".join(f"  - {p}" for p in problems), reason="unusable_site")
