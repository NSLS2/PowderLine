"""Run a native ``topas.*`` recipe and build the standard result (re/05; draft rev 3 §9-§11, A145-A148).

Steps: write the INP and ``.xye`` (:mod:`.native_writer`), run ``tc.exe`` with
the TOPAS folder as working directory, read the files the INP asked TOPAS to
write, and build the result dict every gateway returns.

TOPAS 6 facts this module is built on (devkit ``re05-topas6-compat.md``):

- the exit code says nothing: 3221226324 on success too (C13), so success is
  judged from the **expected output files**, removed before the run so that
  only this run's can exist (never by timestamps, A154);
- TOPAS's messages go to the console window only (C14), so everything
  reported comes from those files;
- ``Get(bkg)`` is 0 (C17) and ``phase_out_X`` is TOPAS 7 only (C34): the
  background column comes from a second TOPAS run, the background alone at
  the refined values (``render_background``, A152), so it carries every
  convolution TOPAS applies (and TOPAS's last-point behaviour, C33);
- ``_LIMIT_`` markers are unreliable (C21): limit hits are checked here
  against the fixed limits the writer recorded (A147 Q-L4);
- a non-finite term silently zeroes a phase (C23): a phase whose calculated
  intensities are all zero gets an informative warning, never an error
  (A147 Q-Z1);
- any non-finite number TOPAS writes (Python or MSVC spelling: ``nan``,
  ``1.#QNAN``, ``-nan(ind)``) is a divergence (A130, A154). The files are read
  strictly here.
"""

from __future__ import annotations

import csv
import math
import os
import re
import subprocess
import time
import uuid
from pathlib import Path

import numpy as np
import pandas as pd

from powderline import reports
from powderline import results as envelopes
from powderline import roundtrip
from powderline.exceptions import EngineExecutionError, ExecutionBackendError, StructuredWarning
from powderline.fitstats import compute_fit_statistics
from powderline.gateways.topas.native_writer import (
    PROFILE_SUFFIX,
    NativeInput,
    background_base,
    has_background,
    render_background,
    render_native,
)
from powderline.gateways.topas.peak_list import PEAK_LIST_COLUMNS, parse_peak_list
from powderline.gateways.topas.runner import discover_tc_exe
from powderline.gateways.topas.schema import TopasRietveldRecipe, validate_recipe
from powderline.registry import validate_only_summary
from powderline.schema_core import collect_warnings, parameters_requested

#: Columns of ``spf_peaks`` for ``topas.spf`` (A147 D13): core's shared columns, then TOPAS's.
SPF_COLUMNS = ("position_2theta", "position_2theta_esd", "intensity", "intensity_esd",
               "gauss_fwhm", "gauss_fwhm_esd", "lor_fwhm", "lor_fwhm_esd",
               "fwhm", "fwhm_esd", "integral_breadth", "integral_breadth_esd")
SPF_DIAG_COLUMNS = ("peak_index", "position_2theta", "status", "notes")
SPF_REPORT = "single_peaks_report.csv"
#: A final value within this relative distance of a stated or default limit is a limit hit (A147 Q-L4). TOPAS 6
#: stops a little past a bound, not on it: a March-Dollase r with min 0.7 ended at 0.700012 (1.7e-5 relative).
LIMIT_HIT_RTOL = 1e-4
#: Rows of the results CSV that are TOPAS's own fit statistics.
FIT_STATS = ("r_wp", "r_exp", "gof")
#: Non-finite numbers as Python or MSVC print them: ``nan``, ``-inf``, ``1.#QNAN``, ``-1.#IND``, ``-nan(ind)``.
_NON_FINITE = re.compile(r"[+-]?(?:nan(?:\(\w*\))?|inf(?:inity)?|1\.#(?:qnan|snan|ind|inf)\d*)", re.IGNORECASE)


def default_base_name(output_dir) -> str:
    """``examples/<name>/output`` -> ``<name>``; otherwise ``topas``."""
    out = Path(output_dir)
    return out.parent.name if out.name == "output" and out.parent.name else "topas"


def safe_base_name(base_name: str) -> tuple[str, StructuredWarning | None]:
    """The base name TOPAS gets: ``base_name`` when it is ASCII, else ``topas`` plus the warning
    ``topas_base_name_sanitized`` (A154 N10, P-04). TOPAS reads the file names in the INP
    (``xdd "<base>.xye"``, ``out "<base>_results.csv"``) in its console code page, not as UTF-8."""
    if base_name.isascii():
        return base_name, None
    return "topas", StructuredWarning(
        code="topas_base_name_sanitized",
        message=(f"the TOPAS base name {base_name!r} is not ASCII, which TOPAS cannot resolve in its file names: "
                 "the input, data and result files are written as topas.* instead"),
        field_path=None)


def write_input(model, output_dir, base_name: str | None = None) -> NativeInput:
    """Render and write ``<base>.inp`` and ``<base>.xye`` (UTF-8, LF); return the writer's map.
    A non-ASCII base name is replaced by ``topas`` (:func:`safe_base_name`)."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    native = render_native(model, safe_base_name(base_name or default_base_name(out))[0])
    base = native.results_file[: -len("_results.csv")]
    (out / f"{base}.inp").write_text(native.inp_text, encoding="utf-8", newline="\n")
    (out / f"{base}.xye").write_text(native.xye_text, encoding="utf-8", newline="\n")
    return native


#: Console text kept from one tc.exe run for a failure record (the end of it, like GSAS-II's tail, KI-05).
MAX_CONSOLE_CHARS = 64 * 1024


def _decoded(data) -> str:
    """Captured console bytes as text; anything that is not bytes or text (no capture) is nothing."""
    if isinstance(data, bytes):
        return data.decode("utf-8", errors="replace")
    return data if isinstance(data, str) else ""


def console_tail(proc) -> str | None:
    """What one tc.exe run printed (stdout, then stderr), its last :data:`MAX_CONSOLE_CHARS`; ``None`` if nothing."""
    out, err = _decoded(getattr(proc, "stdout", None)), _decoded(getattr(proc, "stderr", None))
    text = out + (("\n--- stderr ---\n" + err) if err.strip() else "")
    if not text.strip():
        return None
    return text if len(text) <= MAX_CONSOLE_CHARS else "[... earlier console text dropped ...]\n" + text[-MAX_CONSOLE_CHARS:]


def _on_windows() -> bool:
    return os.name == "nt"


def _ansi_encodable(text: str) -> bool:
    """Whether ``text`` survives the Windows ANSI code page exactly (``mbcs``, strict: no best-fit mapping)."""
    try:
        text.encode("mbcs", "strict")
    except UnicodeError:
        return False
    return True


def _short_path(path: str) -> str | None:
    """The Windows 8.3 short form of an existing ``path`` (``GetShortPathNameW``); ``None`` when there is none."""
    import ctypes
    from ctypes import wintypes

    get = ctypes.windll.kernel32.GetShortPathNameW
    get.argtypes = (wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD)
    get.restype = wintypes.DWORD
    size = get(path, None, 0)
    if not size:
        return None
    buf = ctypes.create_unicode_buffer(size)
    return buf.value if get(path, buf, size) else None


def tc_input_path(inp: Path) -> str:
    """The INP path as tc.exe gets it. TOPAS reads its command line in the ANSI code page: a folder outside it
    (Greek, say, on a Western-European Windows) makes TOPAS write nothing, while its 8.3 short path works
    (measured on TOPAS 6). So on Windows a path the ANSI code page cannot hold is passed in its short form; if the
    volume has no short name for it, the run is refused before tc.exe starts (``ExecutionBackendError``
    ``backend_error``)."""
    text = str(inp)
    if not _on_windows() or _ansi_encodable(text):
        return text
    short = _short_path(text)
    if short and _ansi_encodable(short):
        return short
    raise ExecutionBackendError(
        f"TOPAS cannot open {inp.name} in the folder {inp.parent}: TOPAS reads file paths in the Windows ANSI code "
        "page, which cannot hold this folder's name, and the volume gives it no 8.3 short name. Write the output "
        "to a folder whose path is plain ASCII (--output DIR)", reason="backend_error")


def run_tc(tc: Path, inp: Path, runner=subprocess.run, timeout: float | None = None):
    """Run ``tc "<inp>"`` in the TOPAS folder and return the completed process. The exit code is not used (C13).

    ``timeout`` (seconds; ``None`` = no limit, A195): past it ``tc.exe`` is stopped and the run fails with
    :class:`ExecutionBackendError` ``timeout`` -- a hung TOPAS (a licence dialog waiting for input, say) must
    not block forever. The INP path is passed as :func:`tc_input_path` gives it.
    """
    kwargs = {"cwd": str(tc.parent), "capture_output": True}
    if timeout:
        kwargs["timeout"] = timeout
    inp_arg = tc_input_path(inp)
    try:
        return runner([str(tc), inp_arg], **kwargs)
    except subprocess.TimeoutExpired as exc:  # subprocess.run has already stopped tc.exe
        raise ExecutionBackendError(
            f"TOPAS did not finish {inp.name} within {timeout:g} s and was stopped. A long refinement needs a larger "
            "limit (--topas-timeout SECONDS or topas.timeout in .powderline_config.yaml; 0 = no limit); a TOPAS "
            "waiting for input (a licence or dongle dialog) also ends this way", reason="timeout") from exc
    except (OSError, subprocess.SubprocessError) as exc:
        raise EngineExecutionError(f"TOPAS could not be started ({tc}): {exc}", reason="engine_crashed") from exc


def _failure(kind: str, reason: str, message: str, *, model, native, out: Path, tc: Path, started: float,
             warnings: list, proc=None) -> dict:
    """The failed envelope of a run that reached tc.exe (A195): the files kept for diagnosis (the INP, the data,
    whatever TOPAS wrote), the engine details, and what tc.exe printed."""
    env = envelopes.failure_envelope(
        kind, reason, message, run_id=str(uuid.uuid4()), elapsed=time.time() - started, method="topas_native",
        warnings=warnings, output_files=sorted(str(f) for f in out.glob("*") if f.is_file()),
        simulation_mode=native.simulation,
        engine_details={"engine": "TOPAS", "engine_version": model.engine_version, "tc_path": str(tc),
                        "exit_code": getattr(proc, "returncode", None)})
    env["failure"]["console_tail"] = console_tail(proc) if proc is not None else None
    return env


def run_native(model, output_dir, *, base_name: str | None = None, topas_dir=None, topas_version=None,
               engine_version_check=None, runner=subprocess.run, warnings_from=None,
               timeout: float | None = None) -> dict:
    """Generate, run and read back one native recipe; return the standard result dict.

    ``warnings_from`` is the model validated from the user's recipe (A115); by
    default ``model`` itself. ``engine_version_check(tc_path)`` is called only
    when TOPAS will actually run (A145); without ``tc.exe`` the run is
    generate-only. ``timeout`` bounds each tc.exe run in seconds (``None`` = no
    limit; the gateway resolves the option and the config, A195).
    """
    started = time.time()
    out = Path(output_dir)
    base_name, base_warning = safe_base_name(base_name or default_base_name(out))
    native = write_input(model, out, base_name)
    base = native.results_file[: -len("_results.csv")]
    validated_warnings = collect_warnings(warnings_from if warnings_from is not None else model)
    if base_warning is not None:
        validated_warnings.append(base_warning)

    tc = discover_tc_exe(topas_dir, topas_version)
    if tc is None:  # generate-only: a normal outcome, status "generated" (re/12 D6)
        note = StructuredWarning(
            code="topas_generate_only", level="info", field_path=None,
            message=(f"TOPAS is not configured, so only {base}.inp and {base}.xye were written (generate-only). "
                     "To run TOPAS, set --topas-dir (the folder containing tc.exe) or topas.dir in "
                     ".powderline_config.yaml and declare its version (--topas-version / topas.version), or run "
                     "the INP on the TOPAS machine; PowderLine never guesses where TOPAS is"))
        env = envelopes.generated_envelope(
            elapsed=time.time() - started, method="topas_generate_only", warnings=validated_warnings + [note],
            output_files=sorted(str(f) for f in out.glob("*") if f.is_file()), simulation_mode=native.simulation,
            engine_details={"engine": "TOPAS", "engine_version": model.engine_version, "tc_path": None})
        # the output recipe is the resolved input: nothing ran, so every flagged parameter was not varied (re/20a)
        flagged = {pp.path for pp in roundtrip.parameter_paths(model) if pp.refine_flag}
        return roundtrip.attach(env, roundtrip.build_output(model, {}, not_varied=flagged, parent_run_id=env["run_id"],
                                                            validator=validate_recipe,
                                                            engine_version=model.engine_version), out)
    if engine_version_check is not None:
        engine_version_check(tc)
    expected = (native.results_file, native.profile_file, *native.phase_files.values())
    for f in expected:  # a file left by an earlier run must never pass for this run's (A154)
        (out / f).unlink(missing_ok=True)
    try:
        proc = run_tc(tc, out / f"{base}.inp", runner=runner, timeout=timeout)
    except ExecutionBackendError as exc:  # timed out or refused: the record lists the INP and data kept
        exc.result = _failure("backend", exc.reason, str(exc), model=model, native=native, out=out, tc=tc,
                              started=started, warnings=validated_warnings)
        raise
    missing = [f for f in expected if not (out / f).is_file()]
    if missing:
        tail = console_tail(proc)
        where = ("what tc.exe printed is in the failure record (console_tail)" if tail else
                 "TOPAS reports the reason only in its console window; run the INP in a terminal to see it")
        message = (f"TOPAS stopped without writing its results ({', '.join(missing)} missing in {out}); {where}. "
                   f"The expanded input is in {tc.parent / 'tc.log'}.")
        raise EngineExecutionError(message, reason="output_missing", result=_failure(
            "engine", "output_missing", message, model=model, native=native, out=out, tc=tc, started=started,
            warnings=validated_warnings, proc=proc))
    _run_background(model, native, out, tc, runner, timeout)
    return build_result(model, native, out, validated_warnings, elapsed=time.time() - started, tc_path=str(tc))


def _run_background(model, native: NativeInput, out: Path, tc: Path, runner, timeout: float | None = None) -> None:
    """The background run (A152): the background alone at the refined values; its profile is ``y_bkg``.

    A stale background profile is removed first, so ``build_result`` reads only
    this run's. Skipped when nothing models a background or the fit diverged
    (``build_result`` then reports the divergence).
    """
    base = native.profile_file[: -len(PROFILE_SUFFIX)]
    bkg_base = background_base(base)
    (out / f"{bkg_base}{PROFILE_SUFFIX}").unlink(missing_ok=True)
    if not has_background(model):
        return
    stats, values = _read_results(out / native.results_file)
    if not all(math.isfinite(v) for v in [*stats.values(), *(v for v, _ in values.values())]):
        return
    bkg = render_background(model, base, {name: v for name, (v, _) in values.items()})
    (out / f"{bkg_base}.inp").write_text(bkg.inp_text, encoding="utf-8", newline="\n")
    run_tc(tc, out / f"{bkg_base}.inp", runner=runner, timeout=timeout)


# --- reading TOPAS's files --------------------------------------------------------------


def _topas_float(token: str, where: str) -> float:
    """A number TOPAS wrote; a non-finite one (any spelling) is NaN, anything else unreadable an error."""
    try:
        return float(token)
    except ValueError:
        if _NON_FINITE.fullmatch(token):
            return math.nan
        raise EngineExecutionError(f"TOPAS wrote {token!r} in {where}, which is not a number",
                                   reason="output_malformed") from None


def _read_results(path: Path) -> tuple[dict, dict]:
    """``parameter,value,esd`` rows: (TOPAS's fit statistics, {name: (value, esd)}).

    Strict (A130, A154): every row is kept, a non-finite value as NaN, so the
    caller sees the divergence. A non-finite ESD is ``None`` (TOPAS cannot
    determine the ESD of a degenerate parameter; not a divergence).
    """
    fit, values = {}, {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("parameter,"):
            continue
        parts = [p.strip() for p in line.split(",")]
        value = _topas_float(parts[1] if len(parts) > 1 else "", path.name)
        esd = _topas_float(parts[2], path.name) if len(parts) > 2 and parts[2] else None
        if esd is not None and not math.isfinite(esd):
            esd = None
        if parts[0] in FIT_STATS:
            fit[parts[0]] = value
        else:
            values[parts[0]] = (value, esd)
    return fit, values


def _read_profile(path: Path) -> np.ndarray:
    rows = [[_topas_float(tok, path.name) for tok in line.split()]
            for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    bad = [i + 1 for i, r in enumerate(rows) if len(r) != 3]
    if bad:
        raise EngineExecutionError(f"TOPAS wrote {len(bad)} malformed line(s) in {path.name} (first at line "
                                   f"{bad[0]}): expected three columns (X, Yobs, Ycalc)", reason="output_malformed")
    return np.array(rows, dtype=float).reshape(-1, 3)


def _read_peak_list(path: Path, phase: str) -> list[dict]:
    """A phase's reflection list; a non-finite number in it is a divergence (A130, A154)."""
    text = path.read_text(encoding="utf-8")
    if not all(math.isfinite(_topas_float(tok, path.name)) for tok in text.split()):
        raise _diverged(f"a value in {path.name}")
    return parse_peak_list(text, phase)


def _nearest(grid: np.ndarray, x: np.ndarray) -> np.ndarray:
    """Index of the grid point nearest each x (grid strictly increasing)."""
    hi = np.clip(np.searchsorted(grid, x), 1, len(grid) - 1)
    lo = hi - 1
    return np.where(np.abs(grid[lo] - x) <= np.abs(grid[hi] - x), lo, hi)


def _diverged(what: str) -> EngineExecutionError:
    return EngineExecutionError(f"the refinement diverged: {what} is not finite", reason="diverged")


def build_result(model, native: NativeInput, out: Path, validated_warnings: list, *, elapsed: float,
                 tc_path: str | None = None) -> dict:
    """The result dict from the files TOPAS wrote (tested without TOPAS from recorded files).

    ``tc_path`` is the executable that ran (``engine_details.tc_path``, P-35); ``None`` when the
    result is rebuilt from recorded files.
    """
    p = model.payload
    stats, values = _read_results(out / native.results_file)
    bad = [name for name, v in stats.items() if not math.isfinite(v)]
    bad += [name for name, (v, _) in values.items() if not math.isfinite(v)]
    if bad:
        raise _diverged(f"{', '.join(bad)} in {native.results_file}")
    profile = _read_profile(out / native.profile_file)
    if not np.isfinite(profile).all():
        raise _diverged(f"the calculated pattern in {native.profile_file}")

    # standard statistics over exactly the stated window (A131), the recipe's weights, TOPAS's Ycalc
    tth = np.asarray(p.xrd_data.tth, dtype=float)
    yobs = np.asarray(p.xrd_data.Itth, dtype=float)
    w = np.asarray(p.xrd_data.Itth_weights, dtype=float)
    lo, hi = p.window()
    mask = (tth >= lo) & (tth <= hi)
    ycalc = np.full_like(tth, np.nan)
    idx = _nearest(tth, profile[:, 0])  # TOPAS prints X to 10 significant digits
    near = np.abs(tth[idx] - profile[:, 0]) <= 1e-6 * np.maximum(np.abs(tth[idx]), 1.0)
    ycalc[idx[near]] = profile[near, 2]
    lacking = mask & (w > 0) & ~np.isfinite(ycalc)
    if lacking.any():
        raise EngineExecutionError(f"TOPAS did not calculate {int(lacking.sum())} weighted point(s) of the stated "
                                   f"fit window [{lo}, {hi}] (first at {tth[lacking][0]})", reason="output_malformed")
    ycalc_used = np.where(np.isfinite(ycalc), ycalc, 0.0)
    varied = int(round(values.get("number_independent_parameters", (0, None))[0]))
    fs = compute_fit_statistics(yobs, ycalc_used, w, varied, mask=mask)
    undefined = lambda x: None if x is None or not math.isfinite(x) else float(x)  # noqa: E731
    requested = parameters_requested(model)

    warnings = list(validated_warnings)
    if varied < requested:
        warnings.append(StructuredWarning(
            code="topas_parameters_not_varied",
            message=(f"the recipe requests {requested} independently refined parameter(s) but TOPAS varied "
                     f"{varied}: a flagged parameter that does not affect the pattern is not refined (C22)"),
            field_path=None))
    data_x = _weighted_points(p.xrd_data)
    warnings += _limit_hits(native, values, data_x)

    refined_rows = _refined_rows(model, native, values)
    unit_cells, peak_lists = {}, {}
    if isinstance(model, TopasRietveldRecipe):
        for i, name in enumerate(p.phases, start=1):
            unit_cells[name] = _cell_rows(model, i, name, values)
            peak_lists[name] = _read_peak_list(out / native.phase_files[name], name)
            if not any(r["I_after_scale_pks"] != 0 for r in peak_lists[name]):
                warnings.append(StructuredWarning(
                    code="topas_phase_contributes_nothing",
                    message=(f"phase {name!r} contributes nothing to the calculated pattern (all its calculated "
                             "intensities are zero): its scale is 0, or TOPAS discarded a calculation that was "
                             "not finite (TOPAS does not report that, C23)"),
                    field_path=f"payload.phases.{name}", level="info"))
    spf_rows, spf_diag = (_spf_rows(model, native, values, data_x) if not isinstance(model, TopasRietveldRecipe)
                          else ([], []))

    wavelength = _final(native, values, "lam_lo", p.instrument.radiation.lo.value)
    bkg, bkg_warning = _background_column(model, native, out, profile[:, 0])
    if bkg_warning is not None:
        warnings.append(bkg_warning)
    profile_rows = []
    for i, x, yo, yc, yb in zip(_nearest(tth, profile[:, 0]), profile[:, 0], profile[:, 1], profile[:, 2], bkg):
        weight = w[i]
        s = math.sin(math.radians(x / 2))
        profile_rows.append({"two_theta": x, "y_obs": yo, "y_weights": weight, "y_calc": yc, "y_diff": yo - yc,
                             "y_bkg": yb, "q_values": 4 * math.pi * s / wavelength,
                             "d_spacings": wavelength / (2 * s) if s else math.inf})

    reports.write_refined_parameters(out, refined_rows)
    reports.write_fit_profile(out, profile_rows)
    for name, rows in unit_cells.items():
        reports.write_unit_cell_report(out, name, rows)
    for name, rows in peak_lists.items():
        reports.write_peak_list_report(out, name, rows, PEAK_LIST_COLUMNS)
    if spf_rows:
        with open(out / SPF_REPORT, "w", encoding="utf-8", newline="\n") as fh:
            writer = csv.DictWriter(fh, fieldnames=SPF_COLUMNS, lineterminator="\n")
            writer.writeheader()
            writer.writerows(spf_rows)

    run_id = str(uuid.uuid4())
    refined, not_varied, at_limit = _output_inputs(native, values, warnings, varied < requested)
    envelope = envelopes.with_status_fields({
        "run_id": run_id,
        "rwp": undefined(fs.rwp),
        "r_exp": undefined(fs.rexp),
        "gof": undefined(fs.gof),
        "chi2_red": undefined(fs.chi2_red),
        "simulation_mode": native.simulation,
        "engine_details": {
            "engine": "TOPAS",
            "engine_version": model.engine_version,
            "rwp": stats.get("r_wp"),
            "r_exp": stats.get("r_exp"),
            "gof": stats.get("gof"),
            "n_points": fs.n_points,
            "parameters_requested": requested,
            "parameters_varied": varied,
            "tc_path": tc_path,
        },
        "warnings": warnings,
        "elapsed_time": elapsed,
        "method": "topas_simulation" if native.simulation else "topas",
        "output_files": sorted(str(f) for f in out.glob("*") if f.is_file()),
        "fit_profile": pd.DataFrame(profile_rows, columns=list(reports.FIT_PROFILE_COLUMNS)),
        "unit_cell_data": {k: pd.DataFrame(v, columns=list(reports.UNIT_CELL_COLUMNS)) for k, v in unit_cells.items()},
        "peak_list_data": {k: pd.DataFrame(v, columns=list(PEAK_LIST_COLUMNS)) for k, v in peak_lists.items()},
        "refined_parameters": pd.DataFrame(refined_rows, columns=list(reports.REFINED_PARAMETERS_COLUMNS)),
        "spf_peaks": pd.DataFrame(spf_rows, columns=list(SPF_COLUMNS)) if spf_rows else pd.DataFrame(),
        "spf_convergence_diagnostics": (pd.DataFrame(spf_diag, columns=list(SPF_DIAG_COLUMNS)) if spf_diag
                                        else pd.DataFrame()),
    }, status="ok", converged=None)  # TOPAS 6 exposes no convergence signal in its files (EB-85)
    return roundtrip.attach(envelope, roundtrip.build_output(model, refined, not_varied=not_varied, at_limit=at_limit,
                                                             parent_run_id=run_id, validator=validate_recipe,
                                                             engine_version=model.engine_version), out)


def validate_only_result(model, validated_warnings: list) -> dict:
    """The ``validate_only`` summary (:func:`powderline.registry.validate_only_summary`, P-28); ``engine`` holds
    ``iters`` and the recipe's ``engine_version``."""
    p = model.payload
    return validate_only_summary(
        model, validated_warnings, phases=len(p.phases) if isinstance(model, TopasRietveldRecipe) else 0,
        simulation_mode=p.refinement_controls.iters == 0,
        engine={"iters": p.refinement_controls.iters, "engine_version": model.engine_version},
        validator=validate_recipe)


# --- result pieces ------------------------------------------------------------------------


def _final(native: NativeInput, values: dict, name: str, fallback: float) -> float:
    """A parameter's value after the run (TOPAS units): refined value, else the recipe's."""
    return values[name][0] if name in values else fallback


def _weighted_points(xrd) -> np.ndarray:
    """The 2theta of the data points TOPAS fits (the ``.xye`` keeps only the weighted ones)."""
    tth = np.asarray(xrd.tth, dtype=float)
    return tth[np.asarray(xrd.Itth_weights, dtype=float) > 0]


def _at_limit(v: float, lim: float, side: str, source: str, data_x) -> bool:
    """Whether a final value ``v`` is at (or past) a fixed limit.

    A stated or TOPAS default limit: within :data:`LIMIT_HIT_RTOL` of it, either side (TOPAS stops a little past
    a bound). The fit window's edge (``source == "window"``, an SPF peak position): on or beyond the edge, or
    closer to it than the nearest data point, i.e. no data point lies strictly between the value and the edge
    (TOPAS 6 stopped an ``xo`` 1e-5 degree inside ``start_X``).
    """
    beyond = (v < lim) if side == "min" else (v > lim)
    if source == "window":
        if beyond or v == lim:
            return True
        lo, hi = (lim, v) if side == "min" else (v, lim)
        x = np.asarray(data_x if data_x is not None else (), dtype=float)
        return not bool(((x > lo) & (x < hi)).any())
    tol = LIMIT_HIT_RTOL * abs(lim) if lim != 0 else 1e-12
    return abs(v - lim) <= tol


def _limit_hits(native: NativeInput, values: dict, data_x=None) -> list:
    """``topas_parameter_at_limit`` for every refined parameter that ended at a fixed limit (:func:`_at_limit`);
    ``data_x`` are the fitted data points (the window-edge rule)."""
    found = []
    for name, info in native.params.items():
        if not info.refined or name not in values:
            continue
        v = values[name][0]
        for side, lim, source in zip(("min", "max"), info.limits, info.limit_source):
            if lim is None:
                continue
            if _at_limit(v, lim, side, source, data_x):
                topas = f", TOPAS value {lim:g}" if info.scale != 1.0 else ""  # e.g. Uiso written as beq
                if source == "window":
                    message = (f"{info.descriptive} ended at or beyond the fit window's {side} edge {lim:g} "
                               f"({'start_X' if side == 'min' else 'finish_X'}; final value {v:g}, no data point "
                               "between them): the peak is not fitted against the data it left")
                else:
                    whose = "the recipe's stated bound" if source == "stated" else "TOPAS's default limit"
                    message = (f"{info.descriptive} ended at its {side} limit {lim / info.scale:g} ({whose}{topas}): "
                               "the refinement may have been stopped by the limit")
                found.append(StructuredWarning(code="topas_parameter_at_limit", message=message,
                                               field_path=info.path))
    return found


def _output_inputs(native: NativeInput, values: dict, warnings: list, fewer_varied: bool) -> tuple:
    """What the output recipe needs from TOPAS (re/20a, KI-04): ``{recipe path: (value, esd)}`` in recipe units
    for every refined parameter the writer named (``ParamInfo.path`` / ``scale``), the flagged paths TOPAS did
    not vary (reported with no ESD, only when TOPAS varied fewer than requested), and the paths that ended at
    a limit (the ``topas_parameter_at_limit`` warnings)."""
    refined, not_varied = {}, set()
    for name, info in native.params.items():
        if not info.refined:
            continue
        if name in values:
            v, e = values[name]
            refined[info.path] = (v / info.scale, None if e is None else e / info.scale)
            if fewer_varied and e is None:
                not_varied.add(info.path)
        else:
            not_varied.add(info.path)
    at_limit = {w["field_path"] for w in warnings if w["code"] == "topas_parameter_at_limit" and w.get("field_path")}
    return refined, not_varied, at_limit


def _refined_rows(model, native: NativeInput, values: dict) -> list[dict]:
    phases = list(model.payload.phases) if isinstance(model, TopasRietveldRecipe) else []
    rows = []
    for name, info in list(native.params.items()) + list(native.derived.items()):
        if info.category in ("cell_volume",) or name not in values:
            continue
        if info.category != "derived" and not info.refined:
            continue
        v, e = values[name]
        atoms = list(model.payload.phases[info.phase].atoms) if info.phase in phases else []
        rows.append({
            "parameter_name": name, "descriptive_name": info.descriptive, "phase_name": info.phase,
            "phase_idx": phases.index(info.phase) if info.phase in phases else None,
            "atom_name": info.atom, "atom_idx": atoms.index(info.atom) if info.atom in atoms else None,
            "value": v / info.scale, "esd": None if e is None else e / info.scale, "category": info.category,
        })
    return rows


def _cell_rows(model, i: int, name: str, values: dict) -> list[dict]:
    """The unit-cell report rows (core vocabulary and ESD rule, ``reports.unit_cell_rows``): tied members take
    their group's refined value and ESD, fixed ones the model's; TOPAS's own volume and its ESD."""
    from powderline.symmetry import cell_tie_groups

    phase = model.payload.phases[name]
    ties = cell_tie_groups(phase.space_group)
    rep = {m: g.members[0] for g in ties.groups for m in g.members}
    cell_values, esds, refined = {}, {}, []
    for member in reports.UNIT_CELL_MEMBERS:
        key = f"p{i}_cell_{rep.get(member, member)}"
        if member not in ties.fixed and key in values:          # TOPAS reported the group's representative
            cell_values[member], esds[member] = values[key]
            refined.append(member)
        else:
            cell_values[member] = getattr(phase.unit_cell, member).value
    vol = values.get(f"p{i}_volume")
    return reports.unit_cell_rows(cell_values, esds, fixed=ties.fixed, refined=refined,
                                  volume=None if vol is None else vol[0], volume_esd=None if vol is None else vol[1])


def _spf_rows(model, native: NativeInput, values: dict, data_x=None) -> tuple[list[dict], list[dict]]:
    rows, diag = [], []
    for i, peak in enumerate(model.payload.single_peaks, start=1):
        row = {}
        for col, field_, recipe in (("position_2theta", "xo", peak.xo), ("intensity", "I", peak.I),
                                    ("gauss_fwhm", "gauss_fwhm", peak.gauss_fwhm),
                                    ("lor_fwhm", "lor_fwhm", peak.lor_fwhm),
                                    ("fwhm", "fwhm", None), ("integral_breadth", "integral_breadth", None)):
            key = f"spf{i}_{field_}"
            if key in values:
                row[col], row[f"{col}_esd"] = values[key]
            elif recipe is not None:
                row[col], row[f"{col}_esd"] = recipe.value, None
            else:
                row[col], row[f"{col}_esd"] = None, None
        rows.append(row)
        hits = [w for w in _limit_hits(native, values, data_x)
                if w["field_path"].startswith(f"payload.single_peaks.{i - 1}.")]
        if hits:
            diag.append({"peak_index": i - 1, "position_2theta": row["position_2theta"], "status": "at_limit",
                         "notes": "; ".join(w["message"] for w in hits)})
    return rows, diag


# --- background column (A152; C17, C34) ---------------------------------------------------


def _background_column(model, native: NativeInput, out: Path, x: np.ndarray):
    """``y_bkg`` at the profile's X: the background run's Ycalc (A152); 0 when no background is modelled.

    Returns ``(column, warning)``; without the background run's profile the
    column is empty (NaN) and the warning says so.
    """
    if not has_background(model):
        return np.zeros_like(x), None
    path = out / f"{background_base(native.profile_file[: -len(PROFILE_SUFFIX)])}{PROFILE_SUFFIX}"
    column = np.full_like(x, np.nan)
    if path.is_file():
        bkg = _read_profile(path)
        if len(bkg):
            idx = _nearest(bkg[:, 0], x) if len(bkg) > 1 else np.zeros(len(x), dtype=int)
            near = np.abs(bkg[idx, 0] - x) <= 1e-6 * np.maximum(np.abs(x), 1.0)
            column[near] = bkg[idx[near], 2]
    if np.isfinite(column).all():
        return column, None
    return column, StructuredWarning(
        code="topas_background_not_calculated",
        message=(f"the background column is empty where TOPAS's background run ({path.name}) gave no value: "
                 "TOPAS 6 cannot report the background of the fit itself"),
        field_path="payload.background")


def run_native_validate(model, warnings_from=None) -> dict:
    """``validate_only`` for a native recipe."""
    return validate_only_result(model, collect_warnings(warnings_from if warnings_from is not None else model))
