"""Gateway registry: discovers PowderLine gateways from the ``powderline.gateways``
entry-point group (master plan A17, A7).

Discovery is lazy: entry points are listed on first use and a gateway's
factory is imported (``ep.load()``) only when that gateway is first requested,
so importing this module (or ``powderline``) never imports an engine.

Each entry point targets an engine-free ``get_gateway`` factory returning a
:class:`Gateway` with two layers: the **schema layer** (``validate``,
``capabilities``) runs with no engine installed; the **runtime layer**
(``run``) imports its engine lazily and raises
:class:`~powderline.exceptions.EngineNotAvailableError` when it is missing.

``register_gateway(name, factory)`` is the explicit-registration escape hatch
for tests and development; an explicit registration takes precedence over an
entry point of the same name.

Entry-point metadata is written when the package is installed: after editing
``[project.entry-points]`` in ``pyproject.toml``, re-install the editable
package (``pixi reinstall powderline``) or discovery finds nothing.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib.metadata import entry_points
from typing import Any, Callable, Dict, Optional

from packaging.specifiers import SpecifierSet
from packaging.version import InvalidVersion, Version

from powderline.exceptions import EngineVersionError, GatewayNotInstalledError

ENTRY_POINT_GROUP = "powderline.gateways"


@dataclass(frozen=True)
class Gateway:
    """A gateway's contract.

    - ``name``: registry name (``"gsasii"``, ``"topas"``, ``"easydiffraction"``).
    - ``capabilities()``: dict with at least ``name``, ``workflows`` and
      ``engine_version_spec`` (a PEP 440 specifier string).
    - ``validate(recipe, *, verbose=False)``: schema layer, engine-free. Takes a
      recipe dict or an already-validated model, raises on an invalid recipe,
      returns the validated model. The same explicit keywords on every
      gateway; new options are added to the contract deliberately.
    - ``run(recipe, output_dir, **opts)``: runtime layer; imports the engine
      lazily; returns the standardized result dict. With ``validate_only=True``
      it returns the ``validate_only_summary`` dict (the same keys on every gateway).
    """

    name: str
    capabilities: Callable[[], Dict[str, Any]]
    validate: Callable[..., Any]
    run: Callable[..., dict]


#: The keys of every gateway's ``validate_only`` summary (P-28).
VALIDATE_ONLY_KEYS = ("status", "rwp", "elapsed_time", "method", "schema_name", "core_schema_version",
                      "engine_schema_version", "phases", "simulation_mode", "parameters_requested", "warnings",
                      "engine", "output_recipe", "output_recipe_valid")


def validate_only_summary(model, warnings: list, *, phases: int, simulation_mode: bool, engine: dict,
                          validator=None) -> dict:
    """The ``validate_only`` result every gateway returns (P-28): no refinement, nothing written, no ``run_id``.

    Common keys: ``status`` (``"validated"``), ``rwp`` (None),
    ``elapsed_time`` (0.0), ``method`` (``"validate_only"``),
    ``schema_name``, ``core_schema_version``, ``engine_schema_version``, ``phases`` (0 for a peak-fit workflow),
    ``simulation_mode`` (the engine schema's rule), ``parameters_requested``
    (:func:`powderline.schema_core.parameters_requested`) and ``warnings`` (the structured warnings of
    validating the user's recipe, A115). Engine-specific items go under ``engine`` (gsasii
    ``refinement_cycles``; topas ``iters``, ``engine_version``; easydiffraction ``calculator``).
    ``output_recipe`` (re/20a, KI-04) is the *resolved* recipe -- what the engine would see: derived values
    exact, gateway defaults stated -- and ``output_recipe_valid`` whether it re-validates through ``validator``
    (the gateway's own ``validate_recipe``; default: :func:`powderline.api.validate`); nothing is written.
    """
    from powderline import roundtrip  # core; no engine import
    from powderline.schema_core import parameters_requested  # core; no engine import

    resolved = roundtrip.build_output(model, {}, parent_run_id=None, validator=validator)
    return {
        "status": "validated", "rwp": None, "elapsed_time": 0.0, "method": "validate_only",
        "schema_name": model.schema_name, "core_schema_version": model.core_schema_version,
        "engine_schema_version": model.engine_schema_version,
        "phases": phases, "simulation_mode": simulation_mode, "parameters_requested": parameters_requested(model),
        "warnings": warnings, "engine": dict(engine),
        "output_recipe": resolved.recipe, "output_recipe_valid": resolved.valid,
    }


_explicit: Dict[str, Callable[[], Gateway]] = {}
_entry_points: Optional[Dict[str, Any]] = None
_instances: Dict[str, Gateway] = {}


def _discovered() -> Dict[str, Any]:
    """Entry points of the ``powderline.gateways`` group, listed once (not loaded)."""
    global _entry_points
    if _entry_points is None:
        _entry_points = {ep.name: ep for ep in entry_points(group=ENTRY_POINT_GROUP)}
    return _entry_points


def register_gateway(name: str, factory: Callable[[], Gateway]) -> None:
    """Register a gateway factory explicitly (tests/dev escape hatch).

    Takes precedence over an entry point of the same name.
    """
    _explicit[name] = factory
    _instances.pop(name, None)


def unregister_gateway(name: str) -> None:
    """Remove an explicit registration (entry-point gateways are unaffected)."""
    _explicit.pop(name, None)
    _instances.pop(name, None)


def available() -> list[str]:
    """Sorted names of every registered gateway (explicit and entry-point)."""
    return sorted(set(_explicit) | set(_discovered()))


def get(name: str) -> Gateway:
    """Return the gateway registered as ``name``, loading its factory on first use.

    Raises:
        GatewayNotInstalledError: no gateway of that name is registered at all.
            When the entry-point group is empty the message says the install
            metadata is stale (the in-repo gateways are always declared).
    """
    if name in _instances:
        return _instances[name]
    if name in _explicit:
        factory = _explicit[name]
    else:
        eps = _discovered()
        if name not in eps:
            raise GatewayNotInstalledError(_not_installed_message(name, eps), gateway=name)
        factory = eps[name].load()
    gateway = factory()
    if not isinstance(gateway, Gateway):
        raise TypeError(f"gateway factory for {name!r} returned {type(gateway).__name__}, "
                        "expected powderline.registry.Gateway")
    _instances[name] = gateway
    return gateway


def _not_installed_message(name: str, eps: Dict[str, Any]) -> str:
    if not eps:
        return (
            f"no PowderLine gateway named {name!r}: no {ENTRY_POINT_GROUP!r} entry "
            "points were found at all, although powderline is importable. The "
            "package's install metadata is stale or missing; re-install it "
            "(`pixi reinstall powderline`, or `pip install -e .`)."
        )
    return (
        f"no PowderLine gateway named {name!r} is installed (available: "
        f"{', '.join(available())}). Gateways are discovered from the "
        f"{ENTRY_POINT_GROUP!r} entry-point group: install the package that "
        "provides it (e.g. `pip install <package>`), or register it with "
        "powderline.registry.register_gateway()."
    )


def check_engine_version(*, gateway: str, engine: str, installed, spec: str,
                         allow_unsupported: bool = False) -> None:
    """Raise :class:`~powderline.exceptions.EngineVersionError` unless ``installed`` satisfies ``spec``.

    A hard error. ``allow_unsupported=True`` is the explicit test-only bypass
    for compatibility testing of candidate engine versions; gateways
    expose it as ``allow_unsupported_engine_version`` on their ``run()``.
    """
    if allow_unsupported:
        return
    try:
        ok = Version(str(installed)) in SpecifierSet(spec)
    except InvalidVersion:
        ok = False
    if not ok:
        raise EngineVersionError(gateway=gateway, engine=engine, installed=str(installed),
                                 supported=spec)
