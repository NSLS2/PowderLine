#!/usr/bin/env python3
"""Convert a 0.26.0 recipe (``GSASII_Rietveld`` / ``GSASII_SPF``) to gsasii 0.1.0.

The converted recipe states explicitly what v0.1.1 effectively refined (master
plan A95, A101, re/04 subplan §3): structure and parameterization merge into one
phase block, every refinable becomes ``[value, refine_flag]``, refine flags are
expanded to the groups GSAS-II refined together, and GSAS-II's own silent
defaults are written out. Every change is reported. Nothing is fixed silently:
a value the gsasii 0.1.0 schema rejects stops the conversion with every
problem listed (e.g. a background peak below GSAS-II's floor, an ambiguous
special position, a name outside the A112 rule).

Engine-free (no GSAS-II import). Used by the re/04 equivalence runs and the
re/07 example migration; the user-facing migration guide is written in re/10.

Usage::

    python scripts/convert_recipe_026.py IN.json [-o OUT.json]

API: :func:`convert` returns ``(recipe, report)`` or raises :class:`ConversionError`.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import gemmi
from pydantic import ValidationError

from powderline.gateways.gsasii.schema import AXIAL_DIVERGENCE_MIN, gsasii_cell_groups, validate_recipe
from powderline.symmetry import SPECIAL_POSITION_TOL, UIJ_TOL, analyze_site, cell_tie_groups, coupling_groups

SCHEMA_NAMES = {"GSASII_Rietveld": "gsasii.rietveld", "GSASII_SPF": "gsasii.spf"}
CELL = ("a", "b", "c", "alpha", "beta", "gamma")
UIJ = ("U11", "U22", "U33", "U12", "U13", "U23")
#: Iparm1 key -> (block, field) in the gsasii instrument (A103) and the 0.26.0 parameterization path.
IPARM1 = {
    "Lam": ("radiation", "wavelength", ("wavelength",)),
    "Polariz.": ("corrections", "polarization", ("polarization",)),
    "Zero": ("corrections", "zero_shift", ("corrections", "zero_shift")),
    "SH/L": ("corrections", "axial_divergence", ("corrections", "axial_divergence")),
    **{k: ("broadening", k, ("broadening", k)) for k in "UVWXYZ"},
}
IPARM1_PLAIN = ("Type", "Bank", "Azimuth")
PEAK_LISTS_026 = ("positions", "intensities", "pv_gaussian_sigma", "pv_lorentzian_gamma")


class Each:
    """Spec of a name-keyed dict (phases, atoms): every value has ``spec``."""

    def __init__(self, spec):
        self.spec = spec


ANY = object()  # carried whole (xrd_data extras are moved to metadata; Iparm1/Iparm2 are read by key)
UNUSED = object()  # a 0.26.0 field the conversion does not carry (reported when it holds a value)
_FLAT = dict.fromkeys
_UIJ_SPEC = _FLAT(UIJ)
_SIZE_UNUSED = ("uniaxial_equatorial", "uniaxial_axial", "hkl_direction", "S11", "S22", "S33", "S12", "S13", "S23")
_STRAIN_UNUSED = ("uniaxial_equatorial", "uniaxial_axial", "hkl_direction", "stephens_parameters")
#: The 0.26.0 schema's fields (``powderline.schema``), for the unknown-key report (A132).
SPEC_026 = {
    "schema_name": None, "schema_version": None,
    "payload": {
        "xrd_data": ANY, "asset_path": None, "fit_range": None, "phases": None, "single_peaks": None,
        "instrument": {"description": None, "initialization": ANY, "parameterization": {
            "wavelength": None, "polarization": None, "broadening": _FLAT("UVWXYZ"),
            "corrections": _FLAT(("zero_shift", "axial_divergence"))}},
        "background": {"chebyshev": _FLAT(("num_coefficients", "coefficients", "refine_flag")),
                       "single_peaks": _FLAT(PEAK_LISTS_026)},
        "refinement_controls": {"refinement_cycles": None, "refinement_algorithm": None,
                                "single_peak_fitting_mode": _FLAT(("use_instrument_profile",))},
    },
}
SPEC_026["payload"]["single_peaks"] = _FLAT(("positions", "intensities", "pv_gaussian_sigma_sq", "pv_lorentzian_gamma"))
SPEC_026["payload"]["phases"] = Each({
    "structure": {"phase_name": None, "space_group": None, "unit_cell": _FLAT(CELL + ("volume",)),
                  "atoms": Each({**_FLAT(("element", "x", "y", "z", "occupancy", "Multiplicity", "ADP", "Uiso")),
                                 "Uaniso": _UIJ_SPEC, "Uij": _UIJ_SPEC})},
    "parameterization": {
        "scale": None, "unit_cell": _FLAT(CELL),
        "atoms": Each({**_FLAT(("x", "y", "z", "occupancy", "ADP", "Uiso")), "Uaniso": _UIJ_SPEC}),
        "peak_broadening": {
            "size_broadening": {"model": None, "isotropic_size": None, "LG_eta": None,
                                **dict.fromkeys(_SIZE_UNUSED, UNUSED)},
            "strain_broadening": {"model": None, "isotropic_strain": None, "LG_eta": None,
                                  **dict.fromkeys(_STRAIN_UNUSED, UNUSED)}}},
})


class ConversionError(ValueError):
    """The recipe cannot be converted as it stands; ``problems`` lists every reason."""

    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("cannot convert the recipe:\n" + "\n".join(f"  - {p}" for p in problems))


def _value(param) -> Any:
    return None if param is None else param[0]


def _flag(param) -> bool:
    return bool(param[1]) if param is not None and param[1] is not None else False


def canonical_space_group(symbol: str) -> str:
    """The canonical (gemmi ``xhm``) name of a 0.26.0 symbol, as GSAS-II read it (A105, A132).

    GSAS-II reads a trailing ``" R"`` or ``":R"`` as rhombohedral axes and a bare
    (or ``":H"``) rhombohedral symbol as hexagonal axes, uses origin choice 2 for
    a two-origin group, and reads a short monoclinic symbol as b-unique (gemmi's
    choice too). Raises ``ValueError`` if gemmi cannot read the symbol, and for an
    explicit origin choice 1: v0.1.1's GSAS-II read such coordinates as origin 2
    (EB-03), so neither the stated structure nor the one v0.1.1 refined is known.
    """
    text = symbol.strip()
    rhombohedral_axes = text.endswith((" R", ":R"))
    base, _, setting = (text[:-2], "", "") if rhombohedral_axes else text.partition(":")
    if setting.strip() == "1":
        raise ValueError(
            f"space group {symbol!r} states origin choice 1, but v0.1.1's GSAS-II read the coordinates in origin "
            "choice 2 (EB-03), so the converter cannot tell which structure is meant; transform the coordinates to "
            "origin choice 2 and state ':2'")
    sg = gemmi.find_spacegroup_by_name(base.strip())
    if sg is None:
        raise ValueError(f"space group {symbol!r} is not a symbol gemmi reads")
    if sg.ext in ("H", "R"):
        name = f"{sg.hm}:{'R' if rhombohedral_axes else 'H'}"
    elif sg.ext in ("1", "2"):
        name = f"{sg.hm}:2"
    else:
        name = sg.hm
    return gemmi.find_spacegroup_by_name(name).xhm()


class _Conversion:
    def __init__(self) -> None:
        self.report: list[str] = []
        self.problems: list[str] = []

    def note(self, path: str, text: str) -> None:
        self.report.append(f"{path}: {text}")

    # --- top level -----------------------------------------------------------

    def recipe(self, old: dict) -> dict:
        name = old.get("schema_name")
        if name not in SCHEMA_NAMES:
            raise ConversionError([f"schema_name: {name!r} is not a 0.26.0 GSAS-II workflow ({', '.join(SCHEMA_NAMES)})"])
        new_name = SCHEMA_NAMES[name]
        payload = old.get("payload") or {}
        out: dict[str, Any] = {"schema_name": new_name, "core_schema_version": "0.1.0",
                               "engine_schema_version": "0.1.0"}
        self.note("schema_name", f"{name} -> {new_name}; schema_version {old.get('schema_version')!r} -> "
                                 "core_schema_version 0.1.0, engine_schema_version 0.1.0")
        if payload.get("asset_path") is not None:
            self.note("payload.asset_path", f"dropped ({payload['asset_path']!r}; not a gateway input, A50)")
        new: dict[str, Any] = {}
        metadata: dict[str, Any] = {}
        new["xrd_data"] = self.xrd_data(payload.get("xrd_data") or {}, metadata)
        new["instrument"] = self.instrument(payload.get("instrument") or {})
        if payload.get("fit_range") not in (None, [None, None]):
            new["fit_range"] = list(payload["fit_range"])
        background = self.background(payload.get("background"))
        if background:
            new["background"] = background
        if new_name == "gsasii.rietveld":
            self.unused_peak_list(payload.get("single_peaks"))
            new["phases"] = {k: self.phase(k, v) for k, v in (payload.get("phases") or {}).items()}
        else:
            if payload.get("phases"):
                self.problems.append("payload.phases: a GSASII_SPF recipe has no phases")
            new["single_peaks"] = self.peak_list(payload.get("single_peaks") or {})
        new["refinement_controls"] = self.controls(payload.get("refinement_controls") or {}, new_name)
        out["payload"] = new
        if metadata:
            out["metadata"] = metadata
        self.dropped_bounds(payload)
        self.unknown_keys(old, SPEC_026, "")
        return out

    def unknown_keys(self, old, spec, path: str) -> None:
        """Report every key the 0.26.0 schema did not define (``extra='allow'``: v0.1.1 ignored it) and every
        defined field the conversion does not carry that holds a value (A132)."""
        if not isinstance(old, dict) or spec is ANY or spec is None:
            return
        if isinstance(spec, Each):
            for k, v in old.items():
                self.unknown_keys(v, spec.spec, f"{path}.{k}")
            return
        for k, v in old.items():
            where = f"{path}.{k}".lstrip(".")
            if k not in spec:
                if path.endswith("parameterization.corrections") and v is not None:
                    self.problems.append(f"{where}: not a 0.26.0 correction; v0.1.1 raised for it")
                else:
                    self.note(where, "dropped: not a 0.26.0 field (v0.1.1 ignored it)")
            elif spec[k] is UNUSED:
                if v is not None:
                    self.note(where, f"dropped ({v!r}): the isotropic model v0.1.1 ran did not use it")
            else:
                self.unknown_keys(v, spec[k], where)

    def xrd_data(self, old: dict, metadata: dict) -> dict:
        kept = ("tth", "Itth", "Itth_weights", "filename")
        for key in old:
            if key not in kept:
                metadata.setdefault("xrd_data", {})[key] = old[key]
                self.note(f"payload.xrd_data.{key}", f"moved to metadata.xrd_data.{key}")
        return {k: old[k] for k in kept if k in old}

    # --- instrument (A99, A103) ------------------------------------------------

    def instrument(self, old: dict) -> dict:
        init = old.get("initialization") or [{}]
        iparm1 = init[0] if init else {}
        param = old.get("parameterization") or {}
        if len(init) > 1 and init[1]:
            self.note("payload.instrument.initialization[1]", "Iparm2 dropped (v0.1.1 never used it)")
        extra = sorted(set(iparm1) - set(IPARM1) - set(IPARM1_PLAIN))
        missing = sorted((set(IPARM1) | set(IPARM1_PLAIN)) - set(iparm1))
        if extra:
            self.problems.append(f"payload.instrument.initialization[0]: GSAS-II keys {extra} are not supported "
                                 "(e.g. a Kα doublet); gsasii 0.1.0 is single-wavelength PXC only")
        if missing:
            self.problems.append(f"payload.instrument.initialization[0]: missing GSAS-II keys {missing}")
        if extra or missing:
            return {}
        if iparm1["Type"][1] != "PXC":
            self.problems.append(f"payload.instrument.initialization[0].Type: {iparm1['Type'][1]!r}; gsasii 0.1.0 "
                                 "supports 'PXC' only")
        new: dict[str, Any] = {}
        if old.get("description") is not None:
            new["description"] = old["description"]
        new["radiation"] = {"type": "PXC"}
        new["geometry"] = {"bank": int(iparm1["Bank"][1]), "azimuth": iparm1["Azimuth"][1]}
        for key, (block, field, path) in IPARM1.items():
            entry = param
            for part in path:
                entry = (entry or {}).get(part)
            value = entry[0] if entry is not None and entry[0] is not None else iparm1[key][1]
            flag = bool(entry[1]) if entry is not None and entry[1] is not None else bool(iparm1[key][2])
            new.setdefault(block, {})[field] = [value, flag]
        shl = new["corrections"]["axial_divergence"]
        if shl[0] < AXIAL_DIVERGENCE_MIN:
            self.note("payload.instrument.corrections.axial_divergence",
                      f"SH/L {shl[0]} -> {AXIAL_DIVERGENCE_MIN} (GSAS-II computed with {AXIAL_DIVERGENCE_MIN} "
                      "anyway, EB-37; A91, deliberate change)")
            shl[0] = AXIAL_DIVERGENCE_MIN
        return new

    # --- background and peak lists ---------------------------------------------

    def background(self, old) -> dict:
        new: dict[str, Any] = {}
        cheb = (old or {}).get("chebyshev")
        if cheb is None:
            self.note("payload.background.chebyshev", "left out: no background (one fixed 0.0 term), where v0.1.1 "
                                                      "used GSAS-II's constant 1.0 (D1, A119; deliberate change)")
        else:
            new["chebyshev"] = {k: cheb[k] for k in ("num_coefficients", "coefficients", "refine_flag")}
        peaks = (old or {}).get("single_peaks")
        if peaks is not None:
            lists = [peaks.get(k) or [] for k in PEAK_LISTS_026]
            kept, dropped = [], 0
            for i in range(max(map(len, lists))):
                entries = [lst[i] if i < len(lst) else None for lst in lists]
                if any(e is None or e[0] is None or e[1] is None for e in entries):
                    dropped += 1
                else:
                    kept.append([[e[0], bool(e[1])] for e in entries])
            if dropped:
                self.note("payload.background.single_peaks", f"{dropped} peak(s) with a null entry dropped "
                                                             "(v0.1.1 dropped them silently, D4)")
            if kept:
                new["single_peaks"] = {k: [peak[j] for peak in kept] for j, k in
                                       enumerate(("positions", "intensities", "pv_gaussian_sigma_sq",
                                                  "pv_lorentzian_gamma"))}
                self.note("payload.background.single_peaks", "pv_gaussian_sigma renamed pv_gaussian_sigma_sq "
                                                             "(the value always was σ², A89)")
        return new

    def unused_peak_list(self, old) -> None:
        if old and any(e is not None and any(v is not None for v in e)
                       for k in ("positions", "intensities", "pv_gaussian_sigma_sq", "pv_lorentzian_gamma")
                       for e in (old.get(k) or [])):
            self.note("payload.single_peaks", "dropped: Peak List peaks take no part in a Rietveld refinement")

    def peak_list(self, old: dict) -> dict:
        return {k: [[e[0], _flag(e)] for e in (old.get(k) or [])]
                for k in ("positions", "intensities", "pv_gaussian_sigma_sq", "pv_lorentzian_gamma")}

    def controls(self, old: dict, schema_name: str) -> dict:
        new: dict[str, Any] = {}
        if "refinement_cycles" in old:
            new["refinement_cycles"] = old["refinement_cycles"]
        if old.get("refinement_algorithm") is not None:
            self.note("payload.refinement_controls.refinement_algorithm",
                      f"dropped ({old['refinement_algorithm']!r}; v0.1.1 ignored it, D17)")
        if schema_name == "gsasii.spf" and old.get("single_peak_fitting_mode") is not None:
            new["single_peak_fitting_mode"] = old["single_peak_fitting_mode"]
        return new

    def dropped_bounds(self, payload: dict) -> None:
        """Report every populated min/max (A84: gsasii 0.1.0 has no bounds)."""
        def walk(obj, path):
            if isinstance(obj, dict):
                for k, v in obj.items():
                    if k not in ("xrd_data", "initialization"):
                        walk(v, f"{path}.{k}")
            elif isinstance(obj, list):
                if len(obj) == 4 and isinstance(obj[1], bool) and (obj[2] is not None or obj[3] is not None):
                    self.note(path, f"bounds [{obj[2]}, {obj[3]}] dropped (gsasii 0.1.0 exposes no bounds, A84)")
                else:
                    for i, v in enumerate(obj):
                        walk(v, f"{path}[{i}]")
        walk(payload, "payload")

    # --- phases (A93-A96, A100, A101, A105) ----------------------------------

    def phase(self, name: str, old: dict) -> dict:
        path = f"payload.phases.{name}"
        structure = old.get("structure") or {}
        param = old.get("parameterization") or {}
        if structure.get("phase_name") != name:
            self.problems.append(f"{path}.structure.phase_name: {structure.get('phase_name')!r} differs from the "
                                 f"phase key {name!r} (the key is the name, A100)")
        try:
            sg = canonical_space_group(structure.get("space_group", ""))
        except ValueError as exc:
            self.problems.append(f"{path}.structure.space_group: {exc}")
            return {}
        if sg != structure.get("space_group"):
            self.note(f"{path}.space_group", f"{structure.get('space_group')!r} -> {sg!r} (canonical name, as "
                                             "GSAS-II read it; A105)")
        new: dict[str, Any] = {"space_group": sg}
        new["unit_cell"] = self.cell(path, sg, structure.get("unit_cell") or {}, param.get("unit_cell") or {})
        new["atoms"] = {label: self.atom(f"{path}.atoms.{label}", sg, atom, (param.get("atoms") or {}).get(label))
                        for label, atom in (structure.get("atoms") or {}).items()}
        ions = {}
        for label, atom in new["atoms"].items():  # v0.1.1 passed GSAS-II's ion spelling through unchecked (P-03)
            m = re.fullmatch(r"([A-Z][a-z]?)([+-])([1-8])", str(atom.get("element") or ""))
            if m:
                atom["element"], ions[label] = m.group(1), f"{m.group(1)}{m.group(3)}{m.group(2)}"
                self.note(f"{path}.atoms.{label}.element", f"{m.group(0)!r} -> neutral {m.group(1)!r} + "
                          f"scattering_types[{label!r}] = {ions[label]!r} (P-47; GSAS-II spelling -> recipe spelling)")
        if ions:
            new["scattering_types"] = ions
        for label in sorted(set(param.get("atoms") or {}) - set(structure.get("atoms") or {})):
            self.note(f"{path}.parameterization.atoms.{label}", "dropped: the structure has no atom of that label "
                                                                 "(v0.1.1 skipped it)")
        scale = param.get("scale")
        if scale is None or scale[0] is None:
            self.note(f"{path}.scale", "no value: [1.0, flag] (GSAS-II's default, D9)")
        new["scale"] = [1.0 if _value(scale) is None else scale[0], _flag(scale)]
        broadening = self.broadening(path, param.get("peak_broadening") or {})
        if broadening:
            new["peak_broadening"] = broadening
        return new

    def merged(self, path: str, structure_value, param) -> Any:
        if param is not None and param[0] is not None:
            if structure_value is not None and param[0] != structure_value:
                self.note(path, f"{structure_value} -> {param[0]} (the parameterization value won in v0.1.1)")
            return param[0]
        return structure_value

    def expand(self, path: str, params: dict, ties, extra_groups=()) -> None:
        """Group-OR flags within tie groups (and GSAS-II's coarser groups); fixed parameters fixed (A95)."""
        for members in [g.members for g in ties.groups] + list(extra_groups):
            if any(params[m][1] for m in members):
                for m in members:
                    if not params[m][1]:
                        params[m][1] = True
                        self.note(f"{path}.{m}", "refine flag false -> true (refined together with "
                                                 f"{', '.join(members)} in v0.1.1)")
        for m in ties.fixed:
            if params[m][1]:
                params[m][1] = False
                self.note(f"{path}.{m}", "refine flag true -> false (fixed by symmetry; v0.1.1 ignored it)")

    def cell(self, path: str, sg: str, structure: dict, param: dict) -> dict:
        cell = {k: [self.merged(f"{path}.unit_cell.{k}", structure.get(k), param.get(k)), _flag(param.get(k))]
                for k in CELL}
        if structure.get("volume") is not None:
            self.note(f"{path}.unit_cell.volume", "dropped (derived from a..gamma, A75)")
        self.expand(f"{path}.unit_cell", cell, cell_tie_groups(sg), gsasii_cell_groups(sg))
        return cell

    def atom(self, path: str, sg: str, structure: dict, param) -> dict:
        param = param or {}
        new: dict[str, Any] = {"element": structure.get("element")}
        for k in ("x", "y", "z"):
            new[k] = [self.merged(f"{path}.{k}", structure.get(k), param.get(k)), _flag(param.get(k))]
        occupancy = self.merged(f"{path}.occupancy", structure.get("occupancy"), param.get("occupancy"))
        if occupancy is None:
            occupancy = 1.0
            self.note(f"{path}.occupancy", "absent: 1.0 (v0.1.1's default)")
        new["occupancy"] = [occupancy, _flag(param.get("occupancy"))]
        xyz = tuple(new[k][0] for k in ("x", "y", "z"))
        try:
            site = analyze_site(sg, xyz)
            ties = coupling_groups(sg, xyz)
        except ValueError as exc:  # e.g. the ambiguous band (A73): stop, never fix
            self.problems.append(f"{path}: {exc}")
            return new
        self.expand(path, new, ties.xyz)
        for i, k in enumerate(("x", "y", "z")):  # a fixed constant v0.1.1 snapped (A121)
            exact = site.exact[i]
            if exact is not None and exact.denominator in (1, 2, 4, 8) and new[k][0] != float(exact) \
                    and abs(new[k][0] - float(exact)) <= SPECIAL_POSITION_TOL:
                self.note(f"{path}.{k}", f"{new[k][0]} -> {float(exact)} (the exact special-position value; "
                                         "v0.1.1 snapped it, validation reads constants exactly, A121)")
                new[k][0] = float(exact)
        if structure.get("Multiplicity") is not None:
            if structure["Multiplicity"] == site.multiplicity:
                new["Multiplicity"] = structure["Multiplicity"]
            else:
                self.note(f"{path}.Multiplicity", f"stated {structure['Multiplicity']}, derived "
                                                  f"{site.multiplicity}: dropped (A101)")
        self.adp(path, structure, param, new, ties)
        return new

    def adp(self, path: str, structure: dict, param: dict, new: dict, ties) -> None:
        """ADP type, values and flags as v0.1.1 used them (re/04 subplan §3)."""
        p_adp, p_uiso, p_uaniso = param.get("ADP"), param.get("Uiso"), param.get("Uaniso") or {}
        supplied_aniso = all(_value(p_uaniso.get(k)) is not None for k in UIJ)
        given = [k for k in UIJ if _value(p_uaniso.get(k)) is not None]
        if p_adp == "Uaniso" and 0 < len(given) < len(UIJ):
            self.problems.append(f"{path}.Uaniso: the parameterization gives {', '.join(given)} only; v0.1.1 raised "
                                 "unless all six are given (so there is no v0.1.1 refinement to reproduce)")
        if p_adp == "Uiso" and _value(p_uiso) is not None:
            adp = "Uiso"
        elif p_adp == "Uaniso" and supplied_aniso:
            adp = "Uaniso"
        else:
            adp = structure.get("ADP")
        if p_adp is not None and p_adp != adp:
            self.note(f"{path}.ADP", f"{adp} (the structure's): the parameterization's {p_adp} supplied no values, "
                                     f"so GSAS-II kept {adp} and its {p_adp} flags applied to it")
        new["ADP"] = adp
        if adp == "Uiso":
            value = self.merged(f"{path}.Uiso", structure.get("Uiso"), p_uiso)
            if value is None:
                value = 0.0
                self.note(f"{path}.Uiso", "absent: 0.0 (v0.1.1's default)")
            flag = _flag(p_uiso) if p_adp != "Uaniso" else any(_flag(p_uaniso.get(k)) for k in UIJ)
            new["Uiso"] = [value, flag]
            return
        old_u = structure.get("Uaniso") or structure.get("Uij") or {}
        if not structure.get("Uaniso") and structure.get("Uij"):
            self.note(f"{path}.Uij", "read as Uaniso (v0.1.1's reader accepted the old name)")
        uaniso = {}
        for k in UIJ:
            value = self.merged(f"{path}.Uaniso.{k}", old_u.get(k), p_uaniso.get(k))
            if value is None:
                value = 0.0
                self.note(f"{path}.Uaniso.{k}", "absent: 0.0")
            flag = _flag(p_uiso) if p_adp == "Uiso" else _flag(p_uaniso.get(k))
            uaniso[k] = [value, flag]
        self.expand(f"{path}.Uaniso", uaniso, ties.uij)
        for k in ties.uij.fixed:  # a fixed Uij v0.1.1 snapped (A121)
            if uaniso[k][0] != 0.0 and abs(uaniso[k][0]) <= UIJ_TOL:
                self.note(f"{path}.Uaniso.{k}", f"{uaniso[k][0]} -> 0.0 (fixed by symmetry, A121)")
                uaniso[k][0] = 0.0
        new["Uaniso"] = uaniso

    def broadening(self, path: str, old: dict) -> dict:
        new: dict[str, Any] = {}
        for part, field, default_026, default_new in (
                ("size_broadening", "isotropic_size", "1 um", "10 um"),
                ("strain_broadening", "isotropic_strain", "1000 microstrain", "0")):
            block = old.get(part)
            if block is None or _value(block.get(field)) is None:
                self.note(f"{path}.peak_broadening.{part}", f"left out: the documented default {default_new} "
                                                            f"applies, where v0.1.1 used GSAS-II's {default_026} "
                                                            "(A87, A107; deliberate change)")
                continue
            if block.get("model") != "isotropic":
                self.problems.append(f"{path}.peak_broadening.{part}.model: {block.get('model')!r}; gsasii 0.1.0 "
                                     "supports 'isotropic' only")
                continue
            eta = block.get("LG_eta")
            if _value(eta) is None:
                self.note(f"{path}.peak_broadening.{part}.LG_eta", "no value: [1.0, flag] (GSAS-II's default)")
            new[part] = {"model": "isotropic", field: [block[field][0], _flag(block[field])],
                         "LG_eta": [1.0 if _value(eta) is None else eta[0], _flag(eta)]}
        return new


def convert(recipe: dict) -> tuple[dict, list[str]]:
    """Convert a 0.26.0 recipe dict; return ``(gsasii recipe, report)``.

    Raises :class:`ConversionError` listing every problem, including every error
    the gsasii 0.1.0 schema reports for the converted recipe.
    """
    run = _Conversion()
    new = run.recipe(recipe)
    if not run.problems:
        try:
            validate_recipe(new)
        except ValidationError as exc:
            run.problems += [f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()]
    if run.problems:
        raise ConversionError(run.problems)
    return new, run.report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Convert a 0.26.0 GSAS-II recipe to gsasii 0.1.0.")
    parser.add_argument("input", type=Path, help="0.26.0 recipe (JSON)")
    parser.add_argument("-o", "--output", type=Path, help="write the converted recipe here (JSON)")
    args = parser.parse_args(argv)
    try:
        new, report = convert(json.loads(args.input.read_text(encoding="utf-8")))
    except ConversionError as exc:
        print(exc, file=sys.stderr)
        return 1
    print("\n".join(report))
    if args.output:
        with args.output.open("w", encoding="utf-8", newline="\n") as f:
            json.dump(new, f, indent=2, ensure_ascii=False)
            f.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
