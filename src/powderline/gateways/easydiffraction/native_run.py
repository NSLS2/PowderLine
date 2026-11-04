"""easydiffraction gateway — run a native ``easydiffraction.rietveld`` recipe (re/06).

Builds the project (:mod:`.native_builder`), then either calculates the pattern
(no refine flag set: a simulation) or fits with lmfit's Levenberg-Marquardt
using the recipe's stopping criteria (A162), and returns the standard result
dict with the shared report files (``refined_parameters.csv``,
``<phase>_unit_cell_report.csv``, ``fit_profile.txt``,
``<phase>_peak_list_report.csv``).

- **Statistics** (A23, A125, A131): ``rwp``, ``r_exp``, ``gof``, ``chi2_red``
  from core ``fitstats`` over the window's weighted points (exactly the
  points handed to the engine, A149, A158), with ``P`` = lmfit's number of
  varied parameters (easydiffraction's ``n_free_parameters``: the parameters
  handed to lmfit, which varies every one of them; A41). easydiffraction's own
  values go under ``engine_details``; an undefined statistic is ``None``.
- **Strict reading** (A130, A154): a non-finite calculated point, background
  point, refined value or reflection-list value is the divergence error; an
  undetermined ESD is left empty.
- **Background column** (A152's principle): easydiffraction's own
  ``intensity_bkg`` on the fitted points.
- **Reflection lists**: CrysPy's per phase; CrysFML provides none, and the
  result says so (EB-79).
- **Warnings**: the recipe's (core ``collect_warnings``), and
  ``easydiffraction_parameters_not_varied`` (A128),
  ``easydiffraction_parameter_at_limit`` (A157 B4: PowderLine's own check
  against the limits acting in the fit), ``easydiffraction_phase_contributes_nothing``
  (A157 B7), ``easydiffraction_fit_not_converged`` (informative, A166: lmfit stopped without
  success; the values are reported), ``easydiffraction_reflections_not_available`` (CrysFML, A165),
  ``easydiffraction_negative_width`` (the refined profile makes a peak width
  negative within the checked range, A171, A178),
  ``easydiffraction_position_translated`` (an atom easydiffraction holds in
  another writing of the same position; reports use the recipe's, A176),
  ``easydiffraction_crysfml_start_dependent`` (every CrysFML refinement: its
  single-precision pattern is flat at lmfit's finite-difference step, so the
  result depends on the starting values, EB-90, A175).

Runtime layer: imports easydiffraction.
"""

from __future__ import annotations

import math
import time
import uuid
from importlib.metadata import version
from pathlib import Path

import numpy as np
import pandas as pd

from powderline import reports
from powderline import results as envelopes
from powderline import roundtrip
from powderline.exceptions import EngineExecutionError, StructuredWarning
from powderline.fitstats import compute_fit_statistics
from powderline.gateways.easydiffraction.native_builder import Build, build_project, structure_name
from powderline.gateways.easydiffraction.schema import profile_negative_widths, validate_recipe, width_check_points
from powderline.registry import validate_only_summary
from powderline.schema_core import collect_warnings, parameters_requested
from powderline.symmetry import cell_tie_groups

#: A refined value within this relative distance of a limit acting in the fit "ended at the limit"; for a
#: limit of 0, relative to the parameter's starting value (A181: a phase scale is ~1e-6, a Uiso ~1e-2, so no
#: absolute tolerance fits every parameter; with a starting value of 0 too, 1e-12 absolute).
LIMIT_HIT_RTOL = 1e-6
PEAK_LIST_COLUMNS = ("h", "k", "l", "d_spacing", "2theta", "F_calc_squared", "phase")


def _diverged(what: str) -> EngineExecutionError:
    return EngineExecutionError(f"the refinement diverged: easydiffraction returned a non-finite value ({what})",
                                reason="diverged")


def _float(v) -> float | None:
    return None if v is None else float(v)


def run_native(model, output_dir, *, validated_warnings: list | None = None) -> dict:
    """Run a validated ``easydiffraction.rietveld`` model; write the reports into ``output_dir``."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    warnings = list(validated_warnings if validated_warnings is not None else collect_warnings(model))
    t0 = time.time()
    p = model.payload
    simulation = p.simulation_mode()
    fit_info = {}
    stage = "while building the project"
    try:
        # the builder's own refusals are EngineExecutionError (re-raised below); anything else easydiffraction
        # raises while the project is built is an engine failure like one in the fit (A192 Q7)
        build = build_project(model)
        warnings += _translations(model, build)
        analysis = build.project.analysis
        stage = "during the calculation" if simulation else "during the fit"
        if simulation:
            analysis.calculate()
        else:
            rc = p.refinement_controls
            analysis.minimizer.type = rc.minimizer
            analysis.minimizer.max_iterations = rc.max_iterations
            analysis.minimizer.chi_square_change_tolerance = rc.chi_square_change_tolerance
            analysis.minimizer.parameter_change_tolerance = rc.parameter_change_tolerance
            analysis.minimizer.gradient_tolerance = rc.gradient_tolerance
            analysis.fit()
    except EngineExecutionError:
        raise
    except Exception as exc:  # lmfit / CrysPy / CrysFML: the engine failed (re/12 §6.4)
        raise EngineExecutionError(f"easydiffraction failed {stage}: {type(exc).__name__}: {exc}",
                                   reason="engine_crashed") from exc
    if not simulation:
        results = analysis.fit_results
        fit_info = {"success": bool(results.success), "message": str(results.message),
                    "iterations": results.iterations}
        if rc.calculator == "crysfml":
            warnings.append(StructuredWarning(
                code="easydiffraction_crysfml_start_dependent",
                message=("the CrysFML calculator computes in single precision: its pattern does not change for "
                         "parameter steps below about 1e-7 relative, smaller than lmfit's finite-difference step, so "
                         "the refined values, Rwp and ESDs can depend on the starting values (EB-90). Check by "
                         "refining again from slightly different starts, or use the cryspy calculator"),
                field_path="payload.refinement_controls.calculator"))
        if not results.success:
            warnings.append(StructuredWarning(
                code="easydiffraction_fit_not_converged",
                message=(f"lmfit stopped without converging ({results.message}); the values are reported as "
                         "they stand. Likely causes: too few iterations (max_iterations) or poorly conditioned "
                         "parameters (strong correlations, a parameter without effect); check the ESDs"),
                field_path="payload.refinement_controls"))
    return build_result(model, build, out, warnings, elapsed=time.time() - t0, fit_info=fit_info)


def build_result(model, build: Build, out: Path, warnings: list, *, elapsed: float, fit_info: dict) -> dict:
    """The result dict from a calculated or fitted project."""
    p = model.payload
    simulation = p.simulation_mode()
    expt = build.experiment
    arrays = {k: np.asarray(v, dtype=float) for k, v in expt.data.fit_data_arrays().items()}
    for key, what in (("calc", "the calculated pattern"), ("bkg", "the background")):
        if not np.isfinite(arrays[key]).all():
            raise _diverged(what)
    for fp in build.free:
        if not math.isfinite(fp.parameter.value):
            raise _diverged(fp.path)
    x_window = build.tth[build.mask]
    if not np.array_equal(arrays["x"], x_window):
        raise EngineExecutionError("easydiffraction returned a pattern on other 2theta points than it was given",
                                   reason="output_malformed")

    tth = build.tth
    yobs = np.asarray(p.xrd_data.Itth, dtype=float)
    w = np.asarray(p.xrd_data.Itth_weights, dtype=float)
    ycalc = np.zeros_like(tth)
    ycalc[build.mask] = arrays["calc"]
    varied = 0 if simulation else int(build.project.analysis.fit_result.n_free_parameters.value)
    fs = compute_fit_statistics(yobs, ycalc, w, varied, mask=build.mask)
    undefined = lambda v: None if v is None or not math.isfinite(v) else float(v)  # noqa: E731
    requested = parameters_requested(model)

    if varied < requested and not simulation:
        warnings.append(StructuredWarning(
            code="easydiffraction_parameters_not_varied",
            message=(f"the recipe requests {requested} independently refined parameter(s) but lmfit varied {varied}"),
            field_path=None))
    warnings += _limit_hits(build)
    warnings += _empty_phases(model, build)
    shifts = [getattr(expt.instrument, n).value for n in
              ("calib_twotheta_offset", "calib_sample_displacement", "calib_sample_transparency")]
    points, pad = width_check_points(x_window, shifts)
    for kind, (lo, hi) in profile_negative_widths(lambda n: getattr(expt.peak, n).value, points).items():
        warnings.append(StructuredWarning(
            code="easydiffraction_negative_width",
            message=(f"with the refined profile the {kind} is negative from {lo:g} to {hi:g} deg 2theta (within "
                     f"{pad:g} deg of the fit window): easydiffraction computed those peaks wrongly without a "
                     "message (CrysFML drops them, CrysPy distorts them; EB-87); the values are reported as they "
                     "stand"),
            field_path="payload.instrument.broadening.parameters"))

    refined_rows = _refined_rows(model, build)
    unit_cells = {name: _cell_rows(model, build, name) for name in p.phases}
    peak_lists = {}
    if expt.refln is not None:
        refln = _refln_arrays(expt.refln)
        for key in ("d_spacing", "two_theta", "f_squared_calc"):
            if not np.isfinite(refln[key].astype(float)).all():
                raise _diverged(f"the reflection list ({key})")
        for name in p.phases:
            sel = refln["structure_id"] == structure_name(name)
            peak_lists[name] = [
                {"h": int(h), "k": int(k), "l": int(l), "d_spacing": float(d), "2theta": float(t),
                 "F_calc_squared": float(f2), "phase": name}
                for h, k, l, d, t, f2 in zip(*(refln[a][sel] for a in (
                    "index_h", "index_k", "index_l", "d_spacing", "two_theta", "f_squared_calc")))]
    else:
        warnings.append(StructuredWarning(
            code="easydiffraction_reflections_not_available",
            message=("the CrysFML calculator reports no reflection list (easydiffraction 0.21.1, EB-79): "
                     "no peak list reports are written"),
            field_path="payload.refinement_controls.calculator"))

    wavelength = expt.instrument.setup_wavelength.value
    profile_rows = []
    for x, yo, sigma, yc, yb in zip(arrays["x"], arrays["meas"], arrays["meas_su"], arrays["calc"], arrays["bkg"]):
        s = math.sin(math.radians(x / 2))
        profile_rows.append({"two_theta": x, "y_obs": yo, "y_weights": 1.0 / sigma ** 2, "y_calc": yc,
                             "y_diff": yo - yc, "y_bkg": yb, "q_values": 4 * math.pi * s / wavelength,
                             "d_spacings": wavelength / (2 * s) if s else math.inf})

    reports.write_refined_parameters(out, refined_rows)
    reports.write_fit_profile(out, profile_rows)
    for name, rows in unit_cells.items():
        reports.write_unit_cell_report(out, name, rows)
    for name, rows in peak_lists.items():
        reports.write_peak_list_report(out, name, rows, PEAK_LIST_COLUMNS)

    fr = build.project.analysis.fit_result
    engine = {
        "engine": "easydiffraction",
        "engine_version": version("easydiffraction"),
        "calculator": p.refinement_controls.calculator,
        "peak_type": p.instrument.broadening.peak_type,
        "minimizer": None if simulation else p.refinement_controls.minimizer,
        "rwp": None if simulation else undefined(_percent(fr.prof_wr_factor.value)),
        "r_exp": None if simulation else undefined(_percent(fr.prof_wr_expected.value)),
        "reduced_chi_square": None if simulation else undefined(_float(build.project.analysis.fit_results
                                                                        .reduced_chi_square)),
        "n_points": fs.n_points,
        "parameters_requested": requested,
        "parameters_varied": varied,
        **({f"fit_{k}": v for k, v in fit_info.items()}),
    }
    run_id = str(uuid.uuid4())
    refined, not_varied, at_limit = ({}, set(), set()) if simulation else \
        _output_inputs(build, warnings, fewer_varied=varied < requested)
    envelope = envelopes.with_status_fields({
        "run_id": run_id,
        "rwp": undefined(fs.rwp),
        "r_exp": undefined(fs.rexp),
        "gof": undefined(fs.gof),
        "chi2_red": undefined(fs.chi2_red),
        "simulation_mode": simulation,
        "engine_details": engine,
        "warnings": warnings,
        "elapsed_time": elapsed,
        "method": "easydiffraction_simulation" if simulation else "easydiffraction",
        "output_files": sorted(str(f) for f in out.glob("*") if f.is_file()),
        "fit_profile": pd.DataFrame(profile_rows, columns=list(reports.FIT_PROFILE_COLUMNS)),
        "unit_cell_data": {k: pd.DataFrame(v, columns=list(reports.UNIT_CELL_COLUMNS)) for k, v in unit_cells.items()},
        "peak_list_data": {k: pd.DataFrame(v, columns=list(PEAK_LIST_COLUMNS)) for k, v in peak_lists.items()},
        "refined_parameters": pd.DataFrame(refined_rows, columns=list(reports.REFINED_PARAMETERS_COLUMNS)),
    }, status="ok", converged=None if simulation else fit_info.get("success"))
    return roundtrip.attach(envelope, roundtrip.build_output(model, refined, not_varied=not_varied, at_limit=at_limit,
                                                             parent_run_id=run_id, validator=validate_recipe,
                                                             engine_version=engine["engine_version"]), out)


def _output_inputs(build: Build, warnings: list, fewer_varied: bool) -> tuple:
    """What the output recipe needs from easydiffraction (re/20a, KI-04): ``{recipe path: (value, esd)}`` in the
    recipe's writing (``report_offset`` added back, A176) for every free parameter (a Chebyshev term's path gains
    its coefficient index), the flagged paths lmfit did not vary (no uncertainty, only when it varied fewer than
    requested), and the paths that ended at a limit (the ``easydiffraction_parameter_at_limit`` warnings)."""
    refined, not_varied = {}, set()
    for fp in build.free:
        path = fp.path
        if path == "payload.background.chebyshev" and fp.name.startswith("background_coefficient_"):
            path = f"payload.background.chebyshev.coefficients.{fp.name.rsplit('_', 1)[1]}"
        esd = _esd(fp.parameter)
        refined[path] = (float(fp.parameter.value) + fp.report_offset, esd)
        if fewer_varied and esd is None:
            not_varied.add(path)
    at_limit = {w["field_path"] for w in warnings
                if w["code"] == "easydiffraction_parameter_at_limit" and w.get("field_path")}
    return refined, not_varied, at_limit


def _refln_arrays(refln) -> dict:
    """easydiffraction's reflection list as arrays, one per column the reports use."""
    return {a: np.asarray(getattr(refln, a)) for a in (
        "structure_id", "index_h", "index_k", "index_l", "d_spacing", "two_theta", "f_squared_calc")}


def _percent(v):
    return None if v is None else 100.0 * float(v)


def _esd(param) -> float | None:
    e = param.uncertainty
    return None if e is None or not math.isfinite(e) else float(e)


def _translations(model, build: Build) -> list:
    """Atoms easydiffraction holds in another writing of the stated position (a lattice translation, A176)."""
    found = []
    for (name, label), shift in build.translations.items():
        site = build.structures[name].atom_sites[label]
        atom = model.payload.phases[name].atoms[label]
        held = (site.fract_x.value, site.fract_y.value, site.fract_z.value)
        found.append(StructuredWarning(
            code="easydiffraction_position_translated",
            message=(f"easydiffraction holds {label} at {tuple(round(v, 10) for v in held)}, the stated "
                     f"{(atom.x.value, atom.y.value, atom.z.value)} moved by the lattice vector {shift} (its own "
                     "writing of the Wyckoff position, EB-74): the same atom and the same pattern. Refined "
                     "coordinates are reported in the recipe's writing"),
            field_path=f"payload.phases.{name}.atoms.{label}"))
    return found


def _limit_hits(build: Build) -> list:
    found = []
    for fp in build.free:
        v = fp.parameter.value
        for side, lim, source in zip(("min", "max"), fp.limits, fp.limit_source):
            if lim is None:
                continue
            scale = abs(lim) if lim != 0 else abs(fp.start)
            tol = LIMIT_HIT_RTOL * scale if scale else 1e-12
            if abs(v - lim) <= tol:
                whose = "the recipe's stated bound" if source == "stated" else "easydiffraction's physical limit"
                found.append(StructuredWarning(
                    code="easydiffraction_parameter_at_limit",
                    message=(f"{fp.descriptive} ended at its {side} limit {lim + fp.report_offset:g} ({whose}): the refinement may "
                             "have been stopped by the limit"),
                    field_path=fp.path))
    return found


def _empty_phases(model, build: Build) -> list:
    """Phases whose calculated pattern is zero everywhere (A157 B7): informative, never an error."""
    found = []
    calculator = build.experiment.calculator.calculator
    for name in model.payload.phases:
        scale = build.experiment.linked_structures[structure_name(name)].scale.value
        pattern = np.asarray(calculator.calculate_pattern(build.structures[name], build.experiment), dtype=float)
        contribution = scale * pattern
        if not np.isfinite(contribution).all():
            raise _diverged(f"phase {name!r}'s calculated pattern")
        if not np.any(contribution):
            found.append(StructuredWarning(
                code="easydiffraction_phase_contributes_nothing",
                message=(f"phase {name!r} contributes nothing to the calculated pattern (its scale is 0, or all "
                         "its calculated intensities are zero)"),
                field_path=f"payload.phases.{name}", level="info"))
    return found


def _refined_rows(model, build: Build) -> list[dict]:
    phases = list(model.payload.phases)
    rows = []
    for fp in build.free:
        atoms = list(model.payload.phases[fp.phase].atoms) if fp.phase in phases else []
        rows.append({
            "parameter_name": fp.name, "descriptive_name": fp.descriptive, "phase_name": fp.phase or "",
            "phase_idx": phases.index(fp.phase) if fp.phase in phases else None,
            "atom_name": fp.atom or "", "atom_idx": atoms.index(fp.atom) if fp.atom in atoms else None,
            "value": float(fp.parameter.value) + fp.report_offset, "esd": _esd(fp.parameter), "category": fp.category,
        })
    return rows


def _cell_rows(model, build: Build, name: str) -> list[dict]:
    """The unit-cell report rows (core vocabulary and ESD rule, ``reports.unit_cell_rows``): easydiffraction's
    values; a tied member takes its group's ESD scaled to it."""
    from powderline.gateways.easydiffraction.native_builder import _CELL

    phase = model.payload.phases[name]
    cell = build.structures[name].cell
    ties = cell_tie_groups(phase.space_group)
    esd = {}
    for fp in build.free:
        if fp.phase == name and fp.category == "unit_cell":
            for member, k, _c in fp.members:
                e = _esd(fp.parameter)
                esd[member] = None if e is None else abs(float(k)) * e
    values = {m: float(getattr(cell, _CELL[m]).value) for m in reports.UNIT_CELL_MEMBERS}
    refined = [m for m in reports.UNIT_CELL_MEMBERS if getattr(phase.unit_cell, m).refine_flag]
    return reports.unit_cell_rows(values, esd, fixed=ties.fixed, refined=refined)   # easydiffraction propagates no volume ESD


def validate_only_result(model, validated_warnings: list) -> dict:
    """The ``validate_only`` summary (:func:`powderline.registry.validate_only_summary`, P-28); ``engine`` holds
    ``calculator``."""
    p = model.payload
    return validate_only_summary(
        model, validated_warnings, phases=len(p.phases), simulation_mode=p.simulation_mode(),
        engine={"calculator": p.refinement_controls.calculator}, validator=validate_recipe)


def run_native_validate(model, warnings_from=None) -> dict:
    """``validate_only`` for a native recipe."""
    return validate_only_result(model, collect_warnings(warnings_from if warnings_from is not None else model))
