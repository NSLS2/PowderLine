"""Schema-version compatibility: declared support sets, never version arithmetic (A40, A65).

Declarations:

- core (:mod:`powderline.schema_core`): ``CORE_SCHEMA_VERSION`` and
  ``SUPPORTED_CORE_SCHEMAS`` (a PEP 440 specifier);
- each gateway, as keys of its ``capabilities()`` dict (re/04-06):

  - ``engine_schema_version`` -- the version new recipes are written against;
  - ``supported_engine_schemas`` -- specifier of accepted engine schema versions;
  - ``requires_core_schema`` -- specifier of the core versions it needs, or a
    mapping ``{engine-schema specifier: core specifier}`` when different engine
    schema versions need different core versions.

A gateway that does not declare these yet is reported as undeclared by
:func:`support_matrix` and rejected by :func:`check_engine_schema_version`.
All checks raise ``ValueError`` so engine schema models can call them from a
pydantic validator and have them reported with the other validation errors.

Engine-free (enforced by an import-block test).
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Union

from packaging.specifiers import InvalidSpecifier, SpecifierSet

from powderline.schema_core import (
    CORE_SCHEMA_VERSION,
    SUPPORTED_CORE_SCHEMAS,
    check_core_schema_version,
    parse_version,
)

DECLARATION_KEYS = ("engine_schema_version", "supported_engine_schemas", "requires_core_schema")

RequiresCore = Union[str, Mapping[str, str]]


def _powderline_version() -> str:
    from powderline import __version__

    return __version__


def _specifier(what: str, spec: str) -> SpecifierSet:
    try:
        return SpecifierSet(spec)
    except InvalidSpecifier:
        raise ValueError(f"{what} {spec!r} is not a valid PEP 440 specifier") from None


def declarations(capabilities: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    """The schema declarations in a gateway's ``capabilities()``, or ``None`` if absent.

    Raises ``ValueError`` when only some of the keys are declared.
    """
    present = [k for k in DECLARATION_KEYS if k in capabilities]
    if not present:
        return None
    if len(present) != len(DECLARATION_KEYS):
        missing = sorted(set(DECLARATION_KEYS) - set(present))
        raise ValueError(f"gateway {capabilities.get('name')!r} declares {present} but not {missing}")
    return {k: capabilities[k] for k in DECLARATION_KEYS}


def schema_declarations(*, engine_schema_version: str, supported_engine_schemas: str,
                        requires_core_schema: RequiresCore, **extra: Any) -> Dict[str, Any]:
    """A gateway's ``DECLARATIONS``: the :data:`DECLARATION_KEYS` in order, then any engine extras."""
    out: Dict[str, Any] = {"engine_schema_version": engine_schema_version,
                           "supported_engine_schemas": supported_engine_schemas,
                           "requires_core_schema": requires_core_schema}
    out.update(extra)
    return out


def required_core_schemas(requires: RequiresCore, engine_schema_version: str) -> str:
    """The core specifier that ``engine_schema_version`` requires.

    ``requires`` is a single specifier, or a mapping whose first key (in
    declaration order) containing ``engine_schema_version`` applies.
    """
    if isinstance(requires, str):
        return requires
    if not isinstance(requires, Mapping):
        raise ValueError(
            "requires_core_schema must be a specifier string or a mapping "
            f"{{engine-schema specifier: core specifier}}, got {type(requires).__name__}"
        )
    version = parse_version("engine_schema_version", engine_schema_version)
    for engine_spec, core_spec in requires.items():
        if version in _specifier("requires_core_schema key", engine_spec):
            return core_spec
    raise ValueError(
        f"requires_core_schema has no entry for engine schema {engine_schema_version} "
        f"(keys: {', '.join(requires)})"
    )


def check_engine_schema_version(core_schema_version: str, engine_schema_version: str, *,
                                gateway: str, capabilities: Mapping[str, Any]) -> None:
    """Raise ``ValueError`` unless the recipe's version pair is accepted.

    Checks, in order: the core version against :data:`SUPPORTED_CORE_SCHEMAS`; the
    engine version against the gateway's ``supported_engine_schemas``; the core
    version against what that engine version ``requires_core_schema``.
    """
    check_core_schema_version(core_schema_version)
    decl = declarations(capabilities)
    if decl is None:
        raise ValueError(f"gateway {gateway!r} declares no supported engine schema versions")
    pair = (f"core_schema_version {core_schema_version!r}, "
            f"engine_schema_version {engine_schema_version!r}")
    engine_v = parse_version("engine_schema_version", engine_schema_version)
    supported = decl["supported_engine_schemas"]
    if engine_v not in _specifier("supported_engine_schemas", supported):
        raise ValueError(
            f"{pair}: the {gateway!r} gateway of PowderLine {_powderline_version()} accepts "
            f"engine schema {supported} (current: {decl['engine_schema_version']})"
        )
    needs = required_core_schemas(decl["requires_core_schema"], engine_schema_version)
    if parse_version("core_schema_version", core_schema_version) not in _specifier(
            "requires_core_schema", needs):
        raise ValueError(
            f"{pair}: {gateway!r} engine schema {engine_schema_version} requires core "
            f"schema {needs} (PowderLine {_powderline_version()})"
        )


def support_matrix() -> List[Dict[str, Any]]:
    """One row per registered gateway: its declarations plus core's.

    Loads each gateway's engine-free factory through the registry; imports no
    engine. Undeclared gateways get ``"declared": False``. A gateway whose
    declarations are malformed (only some keys present) raises ``ValueError``
    naming it, rather than being listed as undeclared. Consumed by the docs
    generation (``scripts/gen_schema_field_tables.py``).
    """
    from powderline import registry

    rows = []
    for name in registry.available():
        caps = registry.get(name).capabilities()
        decl = declarations(caps)
        rows.append({
            "gateway": name,
            "powderline_version": _powderline_version(),
            "core_schema_version": CORE_SCHEMA_VERSION,
            "supported_core_schemas": SUPPORTED_CORE_SCHEMAS,
            "workflows": tuple(caps.get("workflows", ())),
            "engine_version_spec": caps.get("engine_version_spec"),
            "declared": decl is not None,
            **(decl or {k: None for k in DECLARATION_KEYS}),
        })
    return rows
