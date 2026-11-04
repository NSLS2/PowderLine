"""GSAS-II parameter names -> recipe paths (re/20b, KI-04; non-frozen).

The frozen extractors report what GSAS-II varied by GSAS-II's own names
(``:0:Back;3``, ``0::dAx:4``, ``1:0:Mustrain;i`` ...). This module reads those
rows -- plus the unit-cell reports and the single-peak table -- back onto recipe
paths in recipe units, which is all :mod:`powderline.roundtrip` needs to build the
output recipe. Nothing here touches the project dictionary.

Facts the map rests on (GSAS-II 5.7.9, read-only):

* ``p::dAx:i`` / ``dAy`` / ``dAz`` are the varied **shifts** of atom ``i`` of phase
  ``p``; GSAS-II adds them to the coordinates once at the end
  (``GSASIIstrMath.ApplyXYZshifts``: ``Ax += dAx``), so the refined coordinate is
  the recipe's value plus the reported shift, with the shift's ESD.
* ``p::Afrac:i``, ``p::AUiso:i``, ``p::AU11:i`` ... ``AU23`` are absolute values in
  recipe units (occupancy; U in A^2).
* ``p::A0`` ... ``A5`` are the reciprocal-metric-tensor terms GSAS-II refines for the
  cell; the cell itself comes from the unit-cell report (``cell_a`` ... ``cell_gamma``
  with ESDs), which lists every member of a tie group consistently.
* ``p:h:Scale`` is the phase fraction; ``p:h:Size;i|mx`` and ``p:h:Mustrain;i|mx``
  the isotropic size (um) / microstrain and their Lorentzian fractions (``LG_eta``).
* ``:h:Back;N`` the Chebyshev coefficients; ``:h:BkPkpos|int|sig|gam;N`` the
  background peaks; ``:h:U`` ... ``Z``, ``Zero``, ``Polariz.``, ``SH/L``, ``Lam`` the
  instrument -- all in the units the recipe states (centideg, A).
* Single peak fitting (``gsasii.spf``) fills no covariance block, so there are no
  refined-parameter rows; the non-frozen fit report carries every parameter the peak
  fit varied under ``result['peak_fit']`` by GSAS-II's peak-fit names -- ``Back;n``
  (the Chebyshev coefficients), ``BkPkpos|int|sig|gam;i`` (background peaks), ``U`` ..
  ``Z`` (the instrument profile, with ``use_instrument_profile``), ``SH/L`` and
  ``pos|int|sig|gam<i>`` (the peaks) -- with the refined values and ESDs read from the
  project (``fit_report.peak_fit_parameters``, re/21). Without that block only the
  peak table (``position_2theta``, ``intensity``, ``sigma_squared``, ``gamma``) is
  available, by index, without ESDs, and the background / instrument values the peak
  fit refined are missing: that is stated as a problem.

A name this module does not know is reported as a *problem* (the mapped values are
still applied; the output recipe is then marked not valid naming the parameter): an
unmapped refined value must never be dropped silently.
"""
from __future__ import annotations

import math
import re
from typing import Any, Mapping

from powderline.reports import UNIT_CELL_ROW_OF
from powderline.schema_core import refined_flags

_INSTRUMENT = {
    "U": "broadening.U", "V": "broadening.V", "W": "broadening.W",
    "X": "broadening.X", "Y": "broadening.Y", "Z": "broadening.Z",
    "Zero": "corrections.zero_shift", "Polariz.": "corrections.polarization",
    "SH/L": "corrections.axial_divergence", "Lam": "radiation.wavelength",
}
_ATOM = {
    "Afrac": "occupancy", "AUiso": "Uiso",
    "AU11": "Uaniso.U11", "AU22": "Uaniso.U22", "AU33": "Uaniso.U33",
    "AU12": "Uaniso.U12", "AU13": "Uaniso.U13", "AU23": "Uaniso.U23",
}
_SHIFT = {"dAx": "x", "dAy": "y", "dAz": "z"}
_BROADENING = {
    "Size;i": "size_broadening.isotropic_size", "Size;mx": "size_broadening.LG_eta",
    "Mustrain;i": "strain_broadening.isotropic_strain", "Mustrain;mx": "strain_broadening.LG_eta",
}
_PEAK = {"pos": "positions", "int": "intensities", "sig": "pv_gaussian_sigma_sq", "gam": "pv_lorentzian_gamma"}
_CELL = ("a", "b", "c", "alpha", "beta", "gamma")
_SPF_COLUMNS = {"position_2theta": "positions", "intensity": "intensities",
                "sigma_squared": "pv_gaussian_sigma_sq", "gamma": "pv_lorentzian_gamma"}


def _float(v) -> float | None:
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) else f


def _records(table) -> list:
    if table is None:
        return []
    if hasattr(table, "to_dict"):
        return table.to_dict("records")
    return list(table)


def _text(v) -> str:
    """A table cell as text; empty for None / NaN (a CSV-loaded table)."""
    return v if isinstance(v, str) else ""


def _phase_name(model, row: Mapping, phase_index: str) -> str:
    name = _text(row.get("phase_name"))
    if name:
        return name
    names = list(model.payload.phases)
    return names[int(phase_index)]


def _atom_label(model, phase: str, row: Mapping, atom_index: str) -> str:
    label = _text(row.get("atom_name"))
    if label:
        return label
    return list(model.payload.phases[phase].atoms)[int(atom_index)]


def _peak_fit_path(payload, name: str) -> str | None:
    """The recipe path of a GSAS-II peak-fit parameter name, or ``None`` for one the recipe has no place for."""
    base, _, index = name.partition(";")
    background = getattr(payload, "background", None)
    if base == "Back" and index.isdigit():
        cheb = getattr(background, "chebyshev", None)
        if cheb is not None and int(index) < len(cheb.coefficients):
            return f"payload.background.chebyshev.coefficients.{int(index)}"
        return None
    if base.startswith("BkPk") and base[4:] in _PEAK and index.isdigit():
        bk = getattr(background, "single_peaks", None)
        if bk is not None and int(index) < len(getattr(bk, _PEAK[base[4:]])):
            return f"payload.background.single_peaks.{_PEAK[base[4:]]}.{int(index)}"
        return None
    if name in _INSTRUMENT:
        return f"payload.instrument.{_INSTRUMENT[name]}"
    peak = re.fullmatch(r"(pos|int|sig|gam)(\d+)", name)
    if peak and int(peak.group(2)) < len(getattr(payload.single_peaks, _PEAK[peak.group(1)])):
        return f"payload.single_peaks.{_PEAK[peak.group(1)]}.{int(peak.group(2))}"
    return None


def refined_by_path(model, result: Mapping[str, Any]) -> tuple:
    """``(refined, not_varied, at_limit, problems)`` for :func:`powderline.roundtrip.build_output`.

    ``refined`` maps recipe paths to ``(value, esd)`` in recipe units for everything GSAS-II varied;
    ``not_varied`` lists the flagged paths GSAS-II reported nothing for (a flagged parameter that does
    not affect the pattern, or one GSAS-II dropped); ``at_limit`` is empty: gsasii 0.1.0 has no bounds;
    ``problems`` are the reasons the output recipe cannot be trusted as the run's result (an unmapped
    name, a peak fit whose refined values were not reported back) -- the caller marks it not valid with them.
    """
    refined: dict = {}
    problems: list = []
    payload = model.payload
    phases = getattr(payload, "phases", None) or {}

    for row in _records(result.get("refined_parameters")):
        name = str(row["parameter_name"])
        value, esd = _float(row.get("value")), _float(row.get("esd"))
        if value is None:
            continue
        parts = name.split(":")
        if len(parts) < 3:
            problems.append(f"GSAS-II parameter {name!r} is not of the form p:h:key[:atom]; its refined value "
                            "is not in the output recipe")
            continue
        phase_idx, hist_idx, key = parts[0], parts[1], parts[2]
        path = None
        if phase_idx == "":                                   # histogram parameter
            base, _, index = key.partition(";")
            if base == "Back":
                path = f"payload.background.chebyshev.coefficients.{int(index)}"
            elif base.startswith("BkPk") and base[4:] in _PEAK:
                path = f"payload.background.single_peaks.{_PEAK[base[4:]]}.{int(index)}"
            elif key in _INSTRUMENT:
                path = f"payload.instrument.{_INSTRUMENT[key]}"
        elif hist_idx == "":                                  # phase parameter: atoms and the metric tensor
            if key in ("A0", "A1", "A2", "A3", "A4", "A5"):
                continue                                      # the cell comes from the unit-cell report
            phase = _phase_name(model, row, phase_idx)
            if len(parts) >= 4 and key in _SHIFT:
                label = _atom_label(model, phase, row, parts[3])
                atom = phases[phase].atoms[label]
                start = getattr(atom, _SHIFT[key]).value
                value = start + value                         # a shift (ApplyXYZshifts), not a coordinate
                path = f"payload.phases.{phase}.atoms.{label}.{_SHIFT[key]}"
            elif len(parts) >= 4 and key in _ATOM:
                label = _atom_label(model, phase, row, parts[3])
                path = f"payload.phases.{phase}.atoms.{label}.{_ATOM[key]}"
        else:                                                 # histogram-phase parameter
            phase = _phase_name(model, row, phase_idx)
            if key == "Scale":
                path = f"payload.phases.{phase}.scale"
            elif key == "MD":                                     # March-Dollase coefficient (re/29, P-48)
                path = f"payload.phases.{phase}.preferred_orientation.ratio"
            elif key in _BROADENING:
                path = f"payload.phases.{phase}.peak_broadening.{_BROADENING[key]}"
        if path is None:
            problems.append(f"GSAS-II parameter {name!r} has no recipe path (teach gateways/gsasii/paths.py the "
                            "name); its refined value is not in the output recipe")
            continue
        refined[path] = (value, esd)

    # the cell: every member from the unit-cell report, when the recipe refines the cell at all
    for phase, cells in (result.get("unit_cell_data") or {}).items():
        if phase not in phases:
            continue
        cell = phases[phase].unit_cell
        if not any(getattr(cell, k).refine_flag for k in _CELL):
            continue
        from powderline.symmetry import cell_tie_groups

        fixed = set(cell_tie_groups(phases[phase].space_group).fixed)  # symmetry-fixed angles: the model's, no ESD
        reported = {str(r["parameter"]): r for r in _records(cells)}
        for k in _CELL:
            r = reported.get(UNIT_CELL_ROW_OF[k])             # report vocabulary -> recipe member (reports.py)
            if k not in fixed and r is not None and _float(r.get("value")) is not None:
                refined[f"payload.phases.{phase}.unit_cell.{k}"] = (_float(r["value"]), _float(r.get("esd")))

    # single peak fitting: the peak fit's own parameter block (values and ESDs for everything it varied: the
    # background, the instrument profile with use_instrument_profile, the peaks), else the peak table by index
    peaks = getattr(payload, "single_peaks", None)
    if peaks is not None:
        peak_fit = result.get("peak_fit")
        if peak_fit is not None:
            for row in (peak_fit.get("parameters") or []):
                name = str(row["name"])
                value, esd = _float(row.get("value")), _float(row.get("esd"))
                path = _peak_fit_path(payload, name)
                if path is None:
                    problems.append(f"GSAS-II peak-fit parameter {name!r} has no recipe path (teach "
                                    "gateways/gsasii/paths.py the name); its refined value is not in the output recipe")
                elif value is None:
                    problems.append(f"GSAS-II peak-fit parameter {name!r} was varied but its refined value could not "
                                    "be read from the project; the output recipe keeps the starting value")
                else:
                    refined[path] = (value, esd)
        else:
            for i, r in enumerate(_records(result.get("spf_peaks"))):
                for column, field in _SPF_COLUMNS.items():
                    v = _float(r.get(column))
                    params = getattr(peaks, field)
                    if v is not None and i < len(params) and params[i].refine_flag:
                        refined[f"payload.single_peaks.{field}.{i}"] = (v, None)
            mode = getattr(payload.refinement_controls, "single_peak_fitting_mode", None)
            use_ip = mode is not None and mode.use_instrument_profile
            problems.append("GSAS-II's peak fit reports its refined values only inside the project, and this result "
                            "carries no peak_fit block: the peak table gives the peaks (without ESDs), but the "
                            "background coefficients" + (" and the instrument profile U..Z" if use_ip else "")
                            + " the peak fit refined keep their starting values in the output recipe")

    flagged = {".".join(str(x) for x in loc) for loc in refined_flags(model)}
    not_varied = {p for p in flagged if p not in refined and not p.endswith(".refine_flag")}
    return refined, not_varied, set(), problems
