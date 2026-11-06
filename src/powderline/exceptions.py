"""PowderLine exception hierarchy and the structured-warning shape (engine-free).

Every PowderLine-raised error derives from :class:`PowderLineError`. The
gateway errors split along the schema/runtime layers:

- :class:`GatewayNotInstalledError` — no gateway of that name is registered at
  all (an out-of-tree plugin that is not installed). The only case where
  ``validate()`` cannot run.
- :class:`EngineNotAvailableError` — the gateway is present but its engine
  dependency is missing from this environment. Raised at ``run()`` time only,
  never by ``validate()``/``validate_only``. Also an :class:`ImportError`, so
  callers that caught the underlying import failure keep working.
- :class:`EngineVersionError` — the installed engine is outside the gateway's
  supported ``ENGINE_VERSION_SPEC``. A hard error.
- :class:`EngineExecutionError` — the engine ran and failed (``.reason`` is a
  code from :mod:`powderline.results`, ``.result`` the failed envelope).
- :class:`ExecutionBackendError` — the engine did not run: the execution
  backend (the GSAS-II server, a transport, a configuration step) failed.
  Same ``.reason`` / ``.result`` shape. Both pickle (``ProcessPoolExecutor``).
- :class:`SymmetryError` — core symmetry helpers (``powderline.symmetry``)
  cannot interpret a space group or site. Gateways convert it to their own
  error type.

An invalid recipe raises pydantic's own ``ValidationError``, which lists every
problem with its field location. Recipe checks live in the schema models
(core + engine), so there is no PowderLine wrapper for it.

This module must never import an engine (enforced by an import-block test).
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Literal, Mapping, NamedTuple, Optional, TypedDict


class PowderLineError(Exception):
    """Base class for all PowderLine errors."""


class SymmetryError(PowderLineError, ValueError):
    """A space group or atomic site cannot be interpreted (``powderline.symmetry``).

    A ``ValueError`` so that, raised inside a pydantic validator, it is reported
    as a validation error with the field location. Gateways that call the
    symmetry helpers outside validation convert it to their own error type.
    """


class GatewayNotInstalledError(PowderLineError):
    """No gateway of this name is registered (the gateway package is absent)."""

    def __init__(self, message: str, *, gateway: str) -> None:
        super().__init__(message)
        self.gateway = gateway

    def __reduce__(self):
        return (_rebuild, (type(self), (str(self),), {"gateway": self.gateway}))


class EngineNotAvailableError(PowderLineError, ImportError):
    """The gateway is present, but its engine dependency is not installed here."""

    def __init__(self, *, gateway: str, dependency: str, env: str,
                 install_command: str) -> None:
        super().__init__(
            f"the {gateway!r} gateway needs {dependency}, which is not installed "
            f"in this environment; use the {env!r} pixi environment "
            f"(install it with: {install_command}; run with: pixi run -e {env} ...)"
        )
        self.gateway = gateway
        self.dependency = dependency
        self.env = env
        self.install_command = install_command

    def __reduce__(self):  # keyword-only constructor: make it picklable
        return (_rebuild, (type(self), (), {"gateway": self.gateway, "dependency": self.dependency,
                                           "env": self.env, "install_command": self.install_command}))


class EngineVersionError(PowderLineError):
    """The installed engine version is outside the gateway's supported range."""

    def __init__(self, *, gateway: str, engine: str, installed: str, supported: str,
                 message: Optional[str] = None) -> None:
        super().__init__(
            message or f"the {gateway!r} gateway supports {engine} {supported}, but {installed} "
            "is installed; install a supported version"
        )
        self.gateway = gateway
        self.engine = engine
        self.installed = installed
        self.supported = supported
        self._message = message

    def __reduce__(self):
        return (_rebuild, (type(self), (), {"gateway": self.gateway, "engine": self.engine,
                                           "installed": self.installed, "supported": self.supported,
                                           "message": self._message}))


class _RunFailure(PowderLineError):
    """Shared shape of the two run-failure classes: ``reason`` (a code from
    :mod:`powderline.results`) and ``result`` (the failed envelope, JSON-safe; ``{}`` when the error was
    raised before any run data existed)."""

    default_reason = "engine_crashed"

    def __init__(self, message: str, *, reason: Optional[str] = None, result: Optional[dict] = None) -> None:
        super().__init__(message)
        self.reason = reason or self.default_reason
        self.result = {} if result is None else result

    def __reduce__(self):
        return (_rebuild, (type(self), (str(self),), {"reason": self.reason, "result": self.result}))


class EngineExecutionError(_RunFailure):
    """The engine ran and failed (envelope ``failure.kind == "engine"``)."""

    default_reason = "engine_crashed"


class ExecutionBackendError(_RunFailure):
    """The engine did not run: the execution backend failed (``failure.kind == "backend"``) -- the GSAS-II
    server was unavailable or disabled, its output is not visible here, the request timed out, or a
    configuration error stopped the run before the engine started."""

    default_reason = "backend_error"


def _rebuild(cls, args, kwargs):
    return cls(*args, **kwargs)


class _StructuredWarningRequired(TypedDict):
    code: str
    message: str
    field_path: Optional[str]


class StructuredWarning(_StructuredWarningRequired, total=False):
    """One entry of the ``warnings`` list in results and ``validate()`` output.

    ``field_path`` is the dotted recipe path the warning refers to, or ``None``
    when it is not tied to one field. Every gateway carries these into its
    results.

    ``level`` is ``"warning"`` -- something the user should act on or
    decide about (a default applied, a parameter at a limit) -- or ``"info"``
    -- a record of something PowderLine did that changes no outcome, such as a
    coordinate held at its exact symmetry value. Absent means ``"warning"``;
    consumers read it as ``w.get("level", "warning")``. The CLI prints
    warnings and only counts info entries unless ``--verbose``; a GUI can show
    both.
    """

    level: Literal["warning", "info"]  # optional (total=False); absent means "warning"


class WarningCode(NamedTuple):
    """Who emits a structured-warning code and at which level (see :data:`WARNING_CODES`)."""

    owner: str  # "core", "gsasii", "topas" or "easydiffraction"
    level: Literal["warning", "info"]


# The vocabulary of structured warnings: every code PowderLine emits,
# its owner and its level. Nothing checks a code at emission; a test asserts
# that this registry, the ``code="..."`` literals under ``src/powderline`` and
# the warning-codes table in ``docs/reference/messages.md`` agree, so a
# new code is registered and documented or the suite fails.
WARNING_CODES: Mapping[str, WarningCode] = MappingProxyType({
    # core (schema_core)
    "uaniso_not_positive_definite": WarningCode("core", "warning"),
    "symmetry_value_derived": WarningCode("core", "info"),
    "output_recipe_not_valid": WarningCode("core", "warning"),
    # gsasii
    "gsasii_broadening_default_applied": WarningCode("gsasii", "warning"),
    "gsasii_background_default_applied": WarningCode("gsasii", "warning"),
    "gsasii_refinement_cycles_default_applied": WarningCode("gsasii", "warning"),
    "gsasii_refinement_message": WarningCode("gsasii", "warning"),
    "gsasii_fit_not_converged": WarningCode("gsasii", "warning"),
    "gsasii_parameters_not_varied": WarningCode("gsasii", "warning"),
    # topas
    "topas_adp_converted": WarningCode("topas", "warning"),
    "topas_parameter_at_limit": WarningCode("topas", "warning"),
    "topas_parameters_not_varied": WarningCode("topas", "warning"),
    "topas_phase_contributes_nothing": WarningCode("topas", "info"),
    "topas_base_name_sanitized": WarningCode("topas", "warning"),
    "topas_background_not_calculated": WarningCode("topas", "warning"),
    "topas_generate_only": WarningCode("topas", "info"),
    # easydiffraction
    "easydiffraction_parameter_at_limit": WarningCode("easydiffraction", "warning"),
    "easydiffraction_parameters_not_varied": WarningCode("easydiffraction", "warning"),
    "easydiffraction_phase_contributes_nothing": WarningCode("easydiffraction", "info"),
    "easydiffraction_fit_not_converged": WarningCode("easydiffraction", "warning"),
    "easydiffraction_negative_width": WarningCode("easydiffraction", "warning"),
    "easydiffraction_reflections_not_available": WarningCode("easydiffraction", "warning"),
    "easydiffraction_position_translated": WarningCode("easydiffraction", "warning"),
    "easydiffraction_crysfml_start_dependent": WarningCode("easydiffraction", "warning"),
})
