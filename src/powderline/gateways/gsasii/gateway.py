"""Engine-free factory for the GSAS-II gateway (entry point ``powderline.gateways:gsasii``).

- **Schema layer** — ``validate`` / ``capabilities``: engine-free; runs with
  GSAS-II not installed. ``gsasii.rietveld`` / ``gsasii.spf`` recipes validate
  against the native schemas (``gateways.gsasii.schema``, A39); any other
  ``schema_name`` is a validation error at ``schema_name``.
- **Runtime layer** — ``run``: the GSAS-II refinement entry point (moved here
  from ``powderline.kicker.run`` in re/07, P-06, behaviour unchanged). It
  validates, enforces ``ENGINE_VERSION_SPEC`` against the installed GSAS-II,
  then executes in this process (``execution_mode='subprocess'``) or through
  the persistent server (``'server'`` / ``'auto'``, via ``GSASClient``), and
  returns the standardized result dict with its tables as DataFrames.

GSAS-II is imported lazily, by ``routing.run_refinement`` (the executors) and
``installed_engine_version``. Never import the gateway's runtime modules
(helpers, project, setters, executors, extractors) at module top: they import
GSAS-II. Enforced by an import-block test.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import pandas as pd

from powderline import results as envelopes
from powderline import roundtrip
from powderline.exceptions import EngineExecutionError, EngineNotAvailableError
from powderline.gateways.gsasii import schema
from powderline.gateways.gsasii.routing import run_refinement
from powderline.registry import Gateway, check_engine_version, validate_only_summary
from powderline.schema_core import collect_warnings

NAME = "gsasii"
#: Supported GSAS-II runtime versions (A41/A44). The pixi pin is the source
#: revision of the pixi-build fork (pixi.toml, feature ``gsasii``); this spec is
#: the drift guard, asserted against ``GSASII.__version__`` in that env.
ENGINE_VERSION_SPEC = "==5.7.9"
#: Workflows served (the native schemas).
WORKFLOWS = tuple(schema.SCHEMA_NAMES)
#: pixi environment providing GSAS-II + how to install it (re/08, A31).
ENV = "gsasii"
INSTALL_COMMAND = "pixi install --frozen -e gsasii"

EXECUTION_MODES = ('auto', 'server', 'subprocess')

#: The 9 ``refined_parameters`` columns, for the empty frame when nothing was refined.
REFINED_PARAMETER_COLUMNS = [
    'parameter_name', 'descriptive_name', 'phase_name', 'phase_idx',
    'atom_name', 'atom_idx', 'value', 'esd', 'category',
]


def capabilities() -> dict:
    return {"name": NAME, "workflows": WORKFLOWS, "engine_version_spec": ENGINE_VERSION_SPEC,
            **schema.DECLARATIONS}


def validate(recipe, *, verbose: bool = False):
    """Validate a recipe (dict or model); return the validated model (A50, A59).

    A ``gsasii.rietveld`` / ``gsasii.spf`` recipe gives its native model
    (``GsasiiRietveldRecipe`` / ``GsasiiSpfRecipe``); its simulation rule is
    part of the schema (A88). ``verbose`` is part of the uniform gateway
    contract; this gateway prints nothing extra.
    """
    return schema.validate_recipe(recipe)


def installed_engine_version() -> str:
    """The GSAS-II **runtime** version (``GSASII.__version__``), never distribution metadata.

    The pixi-built conda distribution reports ``gsas-ii 2.0.0`` (the fork recipe's
    version); the runtime reports ``5.7.9``. Fallback: ``GSASIIpath.GetVersionTag()``
    (``v5.7.9``) with the ``v`` stripped.
    """
    try:
        import GSASII
    except ImportError as exc:
        raise EngineNotAvailableError(gateway=NAME, dependency="GSAS-II", env=ENV,
                                      install_command=INSTALL_COMMAND) from exc
    version = getattr(GSASII, "__version__", None)
    if not version:
        from GSASII import GSASIIpath
        version = GSASIIpath.GetVersionTag().lstrip("v")
    return str(version)


def run(
    recipe,
    output_dir,
    *,
    verbose: bool = False,
    validate_only: bool = False,
    execution_mode: Literal['auto', 'server', 'subprocess'] = 'auto',
    server_timeout: float | None = None,
    allow_unsupported_engine_version: bool = False,
) -> dict:
    """Execute a GSAS-II refinement from an in-memory recipe.

    The full pipeline: schema validation, the engine version check,
    output directory creation, and refinement execution with automatic
    backend selection. Reached through ``powderline.run()`` for a ``gsasii.*``
    recipe, which forwards ``execution_mode``.

    Note: the CLI's template-file guard is **not** applied here. When calling
    programmatically the caller is responsible for ensuring the recipe
    contains real data in ``payload.xrd_data``.

    Args:
        recipe: a recipe dict or a validated model. XRD data must already be
            present in ``payload.xrd_data``.
        output_dir: directory where output files will be written
            (``dummy.gpx``, ``dummy.lst``, CSV reports, ``fit_profile.txt``).
            Created if it does not exist.
        verbose: if True, print detailed progress to stdout.
        validate_only: if True, validate the recipe and return a summary
            dict without running a refinement. No output files are written
            and the engine version is not checked.
        execution_mode: the backend used to execute the refinement:

            ``'auto'`` *(default)*
                Try the persistent GSAS-II server first (auto-starting it if
                needed); fall back to in-process execution if unavailable.
            ``'server'``
                Use the server only. Fails with an error result if the
                server cannot be started.
            ``'subprocess'``
                Skip the server entirely; always run in this process.
                Suitable for batch/HPC workflows where each refinement is
                isolated.

            Only the calling user's own server is used (per-user state
            directory, signed requests and responses; v0.1.2). If the
            ``POWDERLINE_NO_SERVER`` environment variable is truthy
            (``1``/``true``/``yes``/``on``), ``'auto'`` runs in-process without
            starting a server and ``'server'`` returns an error result.
        server_timeout: seconds to wait for the server's answer to a
            submitted job (``'auto'`` / ``'server'``). ``None`` (default) or
            ``0``: no limit, as for an in-process run. Past the limit the run
            raises ``ExecutionBackendError`` ``timeout`` and never falls back
            in-process: the job is still running on the server (one job at a
            time), so a second run would double the work.
        allow_unsupported_engine_version: test-only bypass of the engine
            version check. Not reachable through ``powderline.run()``.

    Returns:
        **Normal refinement** (``validate_only=False``) — the ``ok`` envelope
        (:mod:`powderline.results`); a failed run raises, see below:

        - ``status`` (``"ok"``), ``converged`` (bool, or ``None`` for a
          simulation and for single peak fitting), ``envelope_version``
          (``"1"``); there is no ``success`` key
        - ``run_id`` (str) — UUID4 string uniquely identifying this run
        - ``rwp`` (float | None) — final weighted-profile R factor
        - ``elapsed_time`` (float) — wall-clock seconds
        - ``method`` (str) — ``'server'`` or ``'subprocess'``
        - ``fit_profile`` (pd.DataFrame) — columns: two_theta, y_obs,
          y_weights, y_calc, y_diff, y_bkg, q_values, d_spacings
        - ``unit_cell_data`` (dict) — ``{phase_name: pd.DataFrame}``
          with columns: parameter, value, esd
        - ``peak_list_data`` (dict) — ``{phase_name: pd.DataFrame}``
          with columns: h, k, l, multiplicity, d_spacing, 2theta, …
        - ``refined_parameters`` (pd.DataFrame) — 9 columns:
          parameter_name, descriptive_name, phase_name, phase_idx,
          atom_name, atom_idx, value, esd, category
          (empty DataFrame with all 9 columns when nothing was refined)
        - ``spf_peaks`` (pd.DataFrame) — SPF peak report (empty for
          non-SPF runs)
        - ``spf_convergence_diagnostics`` (pd.DataFrame) — per-peak
          diagnostics for peaks with convergence issues (empty when all
          converged or for non-SPF runs)
        - ``peak_fit`` (dict | None) — SPF only: ``{"parameters": [{"name",
          "value", "esd"}]}``, every parameter GSAS-II's peak fit varied by
          its own name (``Back;0``, ``U``, ``pos3`` …) with its ESD; the
          source of the output recipe for a peak fit
        - ``output_files`` (list[str]) — paths written to ``output_dir``
        - ``r_exp``, ``gof``, ``chi2_red``, ``simulation_mode``,
          ``engine_details`` and the structured ``warnings`` list

        **Validate-only** (``validate_only=True``) — the summary every gateway
        returns (``powderline.registry.validate_only_summary``): no
        refinement executed, no output files written, no ``run_id``;
        ``engine`` holds ``refinement_cycles``.

    Raises:
        pydantic.ValidationError: the recipe fails schema validation.
        ValueError: an invalid ``execution_mode`` or ``server_timeout``.
        EngineNotAvailableError: GSAS-II is not importable (not for ``validate_only``).
        EngineVersionError: the installed GSAS-II is outside ``ENGINE_VERSION_SPEC``.
        EngineExecutionError: the engine ran and failed (``.reason``: ``diverged``,
            ``unusable_site``, ``peak_fit_failed``, ``engine_crashed``; ``.result`` is the
            failed envelope listing the engine's own files written so far, which are kept).
        ExecutionBackendError: the engine did not run (``.reason``: ``server_unavailable``,
            ``server_disabled``, ``communication_failed``,
            ``timeout``, ``backend_error``).
        OSError: ``output_dir`` cannot be created.
    """
    # 0. Validate execution_mode and server_timeout early to catch typos
    if execution_mode not in EXECUTION_MODES:
        raise ValueError(
            f"Invalid execution_mode={execution_mode!r}. "
            f"Must be one of: {', '.join(EXECUTION_MODES)}"
        )
    server_timeout = _server_timeout_seconds(server_timeout)

    # 1. The installed engine must be a supported version (skipped for validate_only)
    if not validate_only:
        check_engine_version(gateway=NAME, engine="GSAS-II", installed=installed_engine_version(),
                             spec=ENGINE_VERSION_SPEC,
                             allow_unsupported=allow_unsupported_engine_version)

    # 2. Validate (raises ValidationError on failure)
    recipe = validate(recipe, verbose=verbose)
    # The recipe's structured warnings come from validating the user's recipe
    # and are carried to the result (A115, A119): here for validate_only and
    # the in-process run, by GSASClient on its paths
    warnings = collect_warnings(recipe)

    # 3. Validate_only short-circuit
    if validate_only:
        controls = recipe.payload.refinement_controls
        phases = getattr(recipe.payload, 'phases', None)
        return validate_only_summary(
            recipe, warnings, phases=len(phases) if phases else 0,
            simulation_mode=controls.refinement_cycles == 1,  # A88
            engine={'refinement_cycles': controls.refinement_cycles}, validator=schema.validate_recipe)

    # 4. Ensure output directory exists
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # 5. Dispatch by execution_mode; every outcome is an envelope (powderline.results) and a failed one
    #    is raised (re/12 spec §6.2)
    if execution_mode == 'subprocess':
        from powderline.gateways.gsasii import console
        with console.capture_console() as tail:  # the engine's console text, kept for a failed run (KI-05)
            try:
                result = run_refinement(recipe, output_dir, verbose=verbose, method='subprocess')
            except EngineExecutionError as exc:  # R30: PowderLine's own failure, raised by the frozen executor
                import traceback
                result = exc.result or envelopes.failure_envelope(
                    "engine", exc.reason, str(exc), method="subprocess", traceback=traceback.format_exc(),
                    output_files=sorted(str(f) for f in output_dir.glob('*') if f.is_file()))
        if result.get('success') is False and 'status' not in result:  # a frozen catch-all's early exit
            result = envelopes.legacy_failure(result)
        console.attach_console(result, tail, verbose=verbose)
        result['warnings'] = warnings + list(result.get('warnings') or [])  # GSASClient adds them on its paths
    else:
        from powderline.gateways.gsasii.client import GSASClient
        client = GSASClient(fallback_to_subprocess=execution_mode != 'server', request_timeout=server_timeout)
        result = client.submit_simulation(
            recipe=recipe,
            output_dir=output_dir,
            verbose=verbose,
            auto_start_server=True,
        )

    envelopes.raise_if_failed(result)
    return _frames(result, recipe, output_dir)


def _server_timeout_seconds(value) -> float | None:
    """The ``server_timeout`` option as seconds for the client: ``None`` for no limit (``None`` or ``0``).

    Raises:
        ValueError: not a number, or negative.
    """
    if value is None:
        return None
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"Invalid server_timeout={value!r}: a number of seconds (0 = no limit)") from None
    if seconds != seconds or seconds < 0:  # NaN or negative
        raise ValueError(f"Invalid server_timeout={value!r}: seconds must be >= 0 (0 = no limit)")
    return None if seconds == 0 else seconds


def _frames(result: dict, model=None, output_dir=None) -> dict:
    """Normalise the structured fields to DataFrames and stamp the ``ok`` envelope fields.

    ``run_refinement()`` and the server return JSON-serializable primitives;
    converting here ensures callers always receive DataFrames regardless of
    ``execution_mode``, without touching the HTTP serialization boundary.
    """
    fit_profile_raw = result.get('fit_profile')
    result['fit_profile'] = (
        pd.DataFrame(fit_profile_raw) if fit_profile_raw else pd.DataFrame()
    )
    # `or {}` (not a .get default): early-failure results serialize these
    # tables as an explicit null, which .get(key, {}) passes through as None.
    result['unit_cell_data'] = {
        phase: pd.DataFrame(records)
        for phase, records in (result.get('unit_cell_data') or {}).items()
    }
    result['peak_list_data'] = {
        phase: pd.DataFrame(records)
        for phase, records in (result.get('peak_list_data') or {}).items()
    }
    refined_params_raw = result.get('refined_parameters')
    result['refined_parameters'] = (
        pd.DataFrame(refined_params_raw)
        if refined_params_raw
        else pd.DataFrame(columns=REFINED_PARAMETER_COLUMNS)
    )
    spf_peaks_raw = result.get('spf_peaks')
    result['spf_peaks'] = (
        pd.DataFrame(spf_peaks_raw) if spf_peaks_raw else pd.DataFrame()
    )
    spf_diag_raw = result.get('spf_convergence_diagnostics')
    result['spf_convergence_diagnostics'] = (
        pd.DataFrame(spf_diag_raw) if spf_diag_raw else pd.DataFrame()
    )

    # re/12: the ok envelope fields (status, converged, envelope_version);
    # the pre-0.2.0 top-level error/traceback keys are dropped (a failure never reaches here: it is raised).
    envelope = envelopes.with_status_fields(result, status="ok", converged=envelopes.converged_of(result))
    if model is None:
        return envelope
    # re/20b (KI-04): the output recipe from GSAS-II's own names (paths.py), built and written on the side that
    # owns output_dir (the client's, in server mode). A name the map does not know is never dropped silently:
    # the output recipe is then built from nothing refined and marked not valid, naming the parameter.
    from powderline.gateways.gsasii import paths
    refined, not_varied, at_limit, problems = paths.refined_by_path(model, envelope)
    bundle = roundtrip.build_output(model, refined, not_varied=not_varied, at_limit=at_limit,
                                    parent_run_id=envelope.get("run_id"), validator=schema.validate_recipe,
                                    engine_version=(envelope.get("engine_details") or {}).get("engine_version"))
    if problems:  # an unmapped name or a mode whose refined values GSAS-II does not report: said, not hidden
        bundle.valid = False
        bundle.problems[:0] = problems
    return roundtrip.attach(envelope, bundle, Path(output_dir) if output_dir is not None else None)


def get_gateway() -> Gateway:
    return Gateway(name=NAME, capabilities=capabilities, validate=validate, run=run)
