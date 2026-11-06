"""The run-result envelope every gateway produces and every caller receives.

Errors are values on the wire and raised in the local API: a gateway (or the
GSAS-II server, or a future worker) builds a *failed* envelope with
:func:`failure_envelope`; :func:`raise_if_failed` turns it into
:class:`~powderline.exceptions.EngineExecutionError` (the engine ran and
failed) or :class:`~powderline.exceptions.ExecutionBackendError` (the engine
did not run) with the envelope on ``.result``. An ``ok`` or ``generated``
envelope is what ``powderline.run()`` returns; a ``failed`` one is never
returned. Engine-free.
"""

from __future__ import annotations

import uuid
from typing import Optional

import pandas as pd

from powderline import reports
from powderline.exceptions import EngineExecutionError, ExecutionBackendError

# ENVELOPE_VERSION is the wire contract's own version (KI-12): bump it when the envelope's keys or
# meanings change. A returned result's status is "ok" or "generated"; "failed" is raised. The two
# reason sets are failure.kind == "engine" (the engine ran and failed) and "backend" (it did not run).
ENVELOPE_VERSION = "1"
# The envelope has two parts. The *base* every tool returns: status, envelope_version, run_id,
# warnings, elapsed_time, method, output_files, engine_details, output_recipe, output_recipe_valid. The
# *refinement section* a refinement workflow fills: converged, rwp, r_exp, gof, chi2_red, simulation_mode,
# fit_profile, unit_cell_data, peak_list_data, refined_parameters, parameter_dispositions, spf_peaks,
# spf_convergence_diagnostics. Keys stay flat; a transform tool (none yet) fills the base only.
STATUSES = ("ok", "generated", "failed")
ENGINE_REASONS = frozenset({"diverged", "unusable_site", "peak_fit_failed", "engine_crashed",
                            "output_missing", "output_malformed"})
BACKEND_REASONS = frozenset({"server_unavailable", "server_disabled",
                             "communication_failed", "timeout", "backend_error"})
REASONS = ENGINE_REASONS | BACKEND_REASONS
_KINDS = {"engine": (ENGINE_REASONS, EngineExecutionError), "backend": (BACKEND_REASONS, ExecutionBackendError)}


def _empty_tables() -> dict:
    return {"fit_profile": pd.DataFrame(), "unit_cell_data": {}, "peak_list_data": {},
            "refined_parameters": pd.DataFrame(columns=list(reports.REFINED_PARAMETERS_COLUMNS)),
            "spf_peaks": pd.DataFrame(), "spf_convergence_diagnostics": pd.DataFrame()}


def failure_envelope(kind: str, reason: str, message: str, *, run_id: Optional[str] = None, elapsed: float = 0.0,
                     method: str = "none", warnings: Optional[list] = None, output_files: Optional[list] = None,
                     traceback: Optional[str] = None, engine_details: Optional[dict] = None,
                     simulation_mode: Optional[bool] = None) -> dict:
    """A ``failed`` envelope. ``kind`` is ``"engine"`` (the engine ran and failed) or ``"backend"`` (it did not run).

    ``output_files`` lists the files kept for diagnosis: the engine's own files written so far and, once
    :func:`powderline.run` has recorded the failure, ``failure.json``. PowderLine's result tables are never
    written for a failed run.
    """
    if kind not in _KINDS:
        raise ValueError(f"unknown failure kind {kind!r}; expected one of {sorted(_KINDS)}")
    allowed = _KINDS[kind][0]
    if reason not in allowed:
        raise ValueError(f"unknown {kind} failure reason {reason!r}; expected one of {sorted(allowed)}")
    return {
        "envelope_version": ENVELOPE_VERSION, "status": "failed", "run_id": run_id, "elapsed_time": elapsed,
        "method": method, "warnings": list(warnings or []), "output_files": list(output_files or []),
        "simulation_mode": simulation_mode,
        "failure": {"kind": kind, "reason": reason, "message": message, "traceback": traceback,
                    "engine_details": engine_details},
    }


def generated_envelope(*, run_id: Optional[str] = None, elapsed: float, method: str, warnings: list,
                       output_files: list, simulation_mode: bool, engine_details: dict) -> dict:
    """A ``generated`` envelope: the engine's input was written but the engine did not run (TOPAS without tc.exe)."""
    return {"envelope_version": ENVELOPE_VERSION, "status": "generated",
            "run_id": run_id or str(uuid.uuid4()), "rwp": None, "r_exp": None, "gof": None, "chi2_red": None,
            "converged": None, "simulation_mode": simulation_mode, "engine_details": dict(engine_details),
            "warnings": list(warnings), "elapsed_time": elapsed, "method": method,
            "output_files": list(output_files), **_empty_tables()}


def with_status_fields(result: dict, *, status: str, converged: Optional[bool]) -> dict:
    """Stamp an engine's ``ok``/``generated`` result with the envelope fields.

    ``status`` is the outcome, so any ``success``, ``error`` or ``traceback`` key is removed.
    """
    if status not in ("ok", "generated"):
        raise ValueError(f"with_status_fields takes 'ok' or 'generated', not {status!r}")
    result["status"] = status
    result["converged"] = converged
    result["envelope_version"] = ENVELOPE_VERSION
    result.pop("success", None)
    result.pop("error", None)
    result.pop("traceback", None)
    return result


def converged_of(result: dict) -> Optional[bool]:
    """The uniform ``converged`` of an engine result: ``None`` for every simulation (nothing was optimized,
    whatever the engine's own flag says), else the engine's flag under ``engine_details.converged``
    (``None`` when the engine cannot report it)."""
    if result.get("simulation_mode"):
        return None
    value = (result.get("engine_details") or {}).get("converged")
    return None if value is None else bool(value)


def legacy_failure(result: dict, *, kind: str = "engine", reason: str = "engine_crashed") -> dict:
    """Turn a ``{'success': False, 'error', 'traceback', ...}`` dict (what the frozen GSAS-II
    executor's catch-alls return) into a ``failed`` envelope."""
    return failure_envelope(kind, reason, str(result.get("error") or "the engine failed without a message"),
                            run_id=result.get("run_id"), elapsed=float(result.get("elapsed_time") or 0.0),
                            method=str(result.get("method") or "none"), warnings=result.get("warnings"),
                            output_files=result.get("output_files"), traceback=result.get("traceback"),
                            engine_details=result.get("engine_details"), simulation_mode=result.get("simulation_mode"))


def raise_if_failed(envelope: dict) -> dict:
    """Raise the exception a ``failed`` envelope stands for; return any other envelope unchanged."""
    if envelope.get("status") != "failed":
        return envelope
    failure = envelope["failure"]
    _, cls = _KINDS[failure["kind"]]
    raise cls(failure["message"], reason=failure["reason"], result=envelope)
