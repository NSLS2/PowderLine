"""The public API: ``validate`` and ``run`` dispatch on the recipe's ``schema_name`` (re/07, P-06).

A recipe names its engine in ``schema_name`` (``<engine>.<workflow>``, e.g.
``gsasii.rietveld``); the engine prefix is the gateway's registry name
(:mod:`powderline.registry`). Both functions resolve the gateway from the
recipe and hand the recipe to it:

- :func:`validate` uses the gateway's **schema layer** only, so it works in an
  environment with no engine installed (the re/08 precondition). It returns a
  :class:`ValidationResult`: the gateway's validated model plus the structured
  warnings the validation produced.
- :func:`run` uses the gateway's **runtime layer**; engine options are
  forwarded to the gateway unchanged. Around the gateway it owns the output
  directory's PowderLine files (re/30): once the recipe has validated and the
  gateway's engine is importable here, it removes the fixed-name outputs before
  dispatch; when the run fails, it writes the failed envelope to
  ``failure.json`` beside the engine's own files before re-raising.

This module imports no engine and no gateway module at import time (enforced
by an import-block test). There is no engine argument: the recipe names its
engine (P-06).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from pydantic import ValidationError
from pydantic_core import InitErrorDetails, PydanticCustomError

from powderline import registry
from powderline.exceptions import EngineExecutionError, ExecutionBackendError, StructuredWarning
from powderline.schema_core import CoreRecipe, collect_warnings

#: Gateway ``run()`` options the public ``run()`` refuses to forward (A53: test-only).
_NOT_PUBLIC_RUN_OPTIONS = ("allow_unsupported_engine_version",)


@dataclass(frozen=True)
class ValidationResult:
    """What :func:`validate` returns: the validated recipe and its warnings.

    - ``recipe``: the gateway's validated model (e.g. ``GsasiiRietveldRecipe``,
      ``TopasRietveldRecipe``). Validation never changes a recipe, so
      the model is the recipe as written plus the schema's defaults.
    - ``warnings``: the structured warnings (:class:`~powderline.exceptions.StructuredWarning`
      dicts: ``code``, ``message``, ``field_path``) collected from that model
      once, in the same call -- a default applied, a symmetry remark
      (``Phase.warnings()``).

    Why a result object rather than the bare model: the warnings are a product
    of validating the user's recipe (what the recipe left out), which a dump of
    the validated model (which now states the default) no longer shows; so the
    only way to expose them without re-validating is to return them with the
    model. Frozen, because it is a record of one validation, not a mutable
    recipe builder: edit the recipe dict and validate again.
    """

    recipe: Any
    warnings: list[StructuredWarning] = field(default_factory=list)


def _schema_name_error(recipe, error_type: str, message: str | None = None) -> ValidationError:
    name = recipe.get("schema_name") if isinstance(recipe, dict) else getattr(recipe, "schema_name", None)
    if message is None:
        detail = InitErrorDetails(type=error_type, loc=("schema_name",), input=recipe)
    else:
        detail = InitErrorDetails(type=PydanticCustomError(error_type, message, {"name": name}),
                                  loc=("schema_name",), input=name)
    return ValidationError.from_exception_data("Recipe", [detail])


def schema_name_of(recipe) -> str:
    """The ``schema_name`` of a recipe dict or validated model.

    Raises pydantic's ``ValidationError`` (at ``schema_name``) when it is missing
    or not a string, so a caller sees the same error type as for any other
    invalid recipe.
    """
    if isinstance(recipe, dict):
        name = recipe.get("schema_name")
        if name is None:
            raise _schema_name_error(recipe, "missing")
    else:
        name = getattr(recipe, "schema_name", None)
        if name is None:
            raise _schema_name_error(recipe, "missing")
    if not isinstance(name, str):
        raise _schema_name_error(recipe, "string_type")
    return name


def gateway_name_for(schema_name: str) -> str:
    """The registry name of the gateway that serves ``schema_name``.

    ``<engine>.<workflow>`` gives ``<engine>`` (whether or not such a gateway is
    installed: :func:`powderline.registry.get` reports that). Anything else
    raises pydantic's ``ValidationError`` at ``schema_name``.
    """
    engine, sep, workflow = schema_name.partition(".")
    if not sep or not engine or not workflow:
        raise _schema_name_error(
            {"schema_name": schema_name}, "schema_name",
            "schema_name '{name}' does not name an engine: expected '<engine>.<workflow>', e.g. 'gsasii.rietveld'")
    return engine


def gateway_for(recipe) -> registry.Gateway:
    """The gateway serving ``recipe`` (dict or model); loads only its engine-free factory."""
    return registry.get(gateway_name_for(schema_name_of(recipe)))


def validate(recipe, *, verbose: bool = False) -> ValidationResult:
    """Validate a recipe with the gateway its ``schema_name`` names; return a :class:`ValidationResult`.

    Engine-free: only the gateway's schema layer runs, so this works where no
    engine is installed. A recipe that is already a validated model passes
    through (idempotent). Nothing is written and nothing is printed unless
    ``verbose`` (forwarded to the gateway).

    Args:
        recipe: a recipe dict (as loaded by :func:`powderline.load_recipe_asset`)
            or a validated model.
        verbose: print the gateway's validation progress, where it has any.

    Returns:
        ``ValidationResult(recipe=<validated model>, warnings=[...])``.

    Raises:
        pydantic.ValidationError: the recipe is invalid (every problem listed
            with its field location); also when ``schema_name`` is missing or
            malformed.
        GatewayNotInstalledError: no gateway of the name ``schema_name`` starts
            with is installed.
    """
    model = gateway_for(recipe).validate(recipe, verbose=verbose)
    # The in-repo models subclass CoreRecipe and carry warnings(); a third-party gateway's model may not.
    warnings = collect_warnings(model) if isinstance(model, CoreRecipe) else []
    return ValidationResult(recipe=model, warnings=warnings)


def run(recipe, output_dir, *, verbose: bool = False, validate_only: bool = False, **engine_options) -> dict:
    """Run a recipe with the engine its ``schema_name`` names; return the standardized result dict.

    The gateway is resolved from the recipe (``<engine>.<workflow>`` →
    ``powderline.registry.get("<engine>")``); the recipe, ``output_dir``,
    ``verbose`` and ``validate_only`` are handed to its ``run`` together with
    ``**engine_options``, unchanged and uninterpreted. Each gateway takes its
    options as explicit keywords, so an option it does not know is a
    ``TypeError`` naming it:

    - ``gsasii``: ``execution_mode`` (``'auto'`` | ``'server'`` | ``'subprocess'``)
      and ``server_timeout`` (seconds to wait for the GSAS-II server's answer;
      default none, as for an in-process run, 0 = none; past it the run raises
      ``ExecutionBackendError`` ``timeout`` and does not fall back in-process,
      the job being still on the server);
    - ``topas``: ``topas_dir`` (the folder holding ``tc.exe``), ``topas_version``
      (the installed TOPAS release, e.g. ``"6"``; a real run needs it declared,
      here or in ``.powderline_config.yaml``) and ``topas_timeout`` (seconds per
      ``tc.exe`` run, default 3600, 0 = no limit; past it the run raises
      ``ExecutionBackendError`` ``timeout``);
    - ``easydiffraction``: none.

    ``allow_unsupported_engine_version`` is the gateways' test-only bypass of the
    engine version check and is refused here (``TypeError``); call the
    gateway's ``run`` directly for compatibility testing.

    Before anything on disk changes, the recipe is validated and the gateway's
    engine is checked to be importable here: an invalid recipe or a run in an
    environment without the engine raises and leaves the output directory's
    previous results in place. Then PowderLine's own fixed-name outputs are
    removed from ``output_dir`` (the engine's files and anything else stay), so
    a reused directory holds one run's results (re/30).

    Args:
        recipe: a recipe dict or a validated model.
        output_dir: directory for the output files; created by the gateway.
        verbose: print the gateway's progress.
        validate_only: validate and return the gateway's summary dict (no
            engine needed, nothing written).

    Returns:
        The gateway's ``ok`` or ``generated`` envelope (:mod:`powderline.results`).
        Every engine returns the same keys and types: ``status`` (``"ok"``, or
        ``"generated"`` when TOPAS's input was written but no ``tc.exe`` is
        declared), ``converged`` (``True`` / ``False`` / ``None`` when the engine
        cannot report it or nothing was refined), ``envelope_version``,
        ``run_id``, ``rwp``, ``r_exp``, ``gof``, ``chi2_red``, ``simulation_mode``,
        ``engine_details``, ``warnings``, ``elapsed_time``, ``method``,
        ``output_files``, ``fit_profile``, ``unit_cell_data``, ``peak_list_data``,
        ``refined_parameters``, ``spf_peaks``, ``spf_convergence_diagnostics``.
        A failed run never returns: it raises (below). See docs/schemas.md.

    Raises:
        pydantic.ValidationError: the recipe is invalid, or ``schema_name`` is
            missing or malformed.
        GatewayNotInstalledError: no gateway of that name is installed.
        EngineNotAvailableError: the gateway's engine is not installed here.
        EngineVersionError: the installed engine is outside the supported versions.
        EngineExecutionError: the engine ran and failed. ``.reason`` is one of
            ``diverged``, ``unusable_site``, ``peak_fit_failed``, ``engine_crashed``,
            ``output_missing``, ``output_malformed``; ``.result`` is the failed
            envelope, listing the files kept for diagnosis (the engine's own files and ``failure.json``).
        ExecutionBackendError: the engine did not run. ``.reason`` is one of
            ``server_unavailable``, ``server_disabled``,
            ``communication_failed``, ``timeout``, ``backend_error``.
        TypeError: an option the gateway does not take, or
            ``allow_unsupported_engine_version``.
        ValueError: a gateway option with an invalid value.
    """
    for name in _NOT_PUBLIC_RUN_OPTIONS:
        if name in engine_options:
            raise TypeError(
                f"{name} is not a powderline.run() option: it is the gateway's test-only bypass of the "
                "engine version check; call the gateway's run() directly for compatibility testing")
    gateway = gateway_for(recipe)
    if validate_only:
        return gateway.run(recipe, output_dir, verbose=verbose, validate_only=True, **engine_options)
    # Nothing on disk changes until the run can start: an invalid recipe (ValidationError) or an engine that
    # is not importable here (EngineNotAvailableError) must not cost the directory its previous results.
    gateway.validate(recipe, verbose=verbose)
    _engine_importable(gateway)
    from powderline import reports
    reports.clear_fixed_outputs(output_dir)       # one run's results per directory (re/30); the engine's files stay
    try:
        return gateway.run(recipe, output_dir, verbose=verbose, validate_only=False, **engine_options)
    except (EngineExecutionError, ExecutionBackendError) as exc:
        _record_failure(output_dir, exc, _schema_name_of(recipe), engine_options)
        raise


def _engine_importable(gateway) -> None:
    """Raise ``EngineNotAvailableError`` when the gateway's engine is not importable here.

    Called before the output directory is touched. The probe is what the module that defines the
    gateway's ``run`` exposes as ``installed_engine_version`` (the in-tree gsasii and easydiffraction
    gateways; the same function :func:`_engine_version_of` reads). A gateway whose module has none
    (TOPAS, which needs no Python engine; a registered replacement; an out-of-tree gateway) is left
    to its own ``run``.
    """
    import sys

    module = sys.modules.get(getattr(gateway.run, "__module__", None) or "")
    probe = getattr(module, "installed_engine_version", None)
    if probe is not None:
        probe()


def _schema_name_of(recipe) -> str:
    if isinstance(recipe, dict):
        return str(recipe.get("schema_name", ""))
    return str(getattr(recipe, "schema_name", ""))


def _record_failure(output_dir, exc, schema_name: str, engine_options: Optional[dict] = None) -> None:
    """Write the failed envelope to ``<output_dir>/failure.json`` (re/30) and list it in ``exc.result``.

    Only when ``output_dir`` already exists (a backend failure before the gateway created it leaves nothing). The
    record is the envelope as the exception carries it -- or a minimal one built here when a gateway raised without
    one -- plus a ``powderline_provenance`` block in the output recipe's shape, so a directory found later says which
    recipe, which engine version and which PowderLine failed (A191).
    """
    import datetime as _dt
    import json
    from pathlib import Path

    from powderline import __version__, reports, results as envelopes
    from powderline.roundtrip import PROVENANCE_KEY, engine_of

    out = Path(output_dir)
    if not out.is_dir():
        return
    if not exc.result:
        kind = "engine" if isinstance(exc, EngineExecutionError) else "backend"
        exc.result = envelopes.failure_envelope(kind, exc.reason, str(exc))
    envelope = exc.result
    path = out / reports.FAILURE_FILE
    record = dict(envelope)
    engine = engine_of(schema_name)
    record[PROVENANCE_KEY] = {"schema_name": schema_name, "engine": engine,
                              "engine_version": _engine_version_of(engine, envelope, engine_options),
                              "powderline_version": __version__,
                              "created": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
                              "run_id": envelope.get("run_id")}
    path.write_text(json.dumps(record, indent=2, default=str) + "\n", encoding="utf-8")
    envelope["output_files"] = sorted(set(envelope.get("output_files") or []) | {str(path.resolve())})


def _engine_version_of(engine: str, envelope: dict, engine_options: Optional[dict]) -> Optional[str]:
    """The engine version for a failure record: the envelope's ``engine_details`` when the gateway put it there,
    else what the gateway module reports (``installed_engine_version``; TOPAS: the declared
    ``configured_engine_version``), else ``None``. Never raises: the failure being recorded is what matters."""
    import importlib

    details = (envelope.get("failure") or {}).get("engine_details") or envelope.get("engine_details") or {}
    if details.get("engine_version") is not None:
        return str(details["engine_version"])
    try:
        module = importlib.import_module(f"powderline.gateways.{engine}.gateway")
        if hasattr(module, "installed_engine_version"):
            return str(module.installed_engine_version())
        if hasattr(module, "configured_engine_version"):
            version = module.configured_engine_version((engine_options or {}).get("topas_version"))
            return None if version is None else str(version)
    except Exception:  # noqa: BLE001 - an out-of-tree gateway, an engine not importable here, a bad config
        return None
    return None
