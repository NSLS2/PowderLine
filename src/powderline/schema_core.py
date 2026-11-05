"""Core recipe schema (core schema 0.1.0): the models every engine schema shares.

Engine-free and pure pydantic. Engine schemas (``gsasii.*``, ``topas.*``,
``easydiffraction.*``; re/04-06) build their payloads from these models; nothing
at runtime routes through this module until then (re/03).

Conventions (master plan A19-A21, A32):

- every model is ``extra='forbid'``;
- units are fixed per field in the schema (``json_schema_extra={"unit": ...}``),
  never carried by a recipe;
- a refinable quantity is a :class:`RefinableParameter` (JSON
  ``[value, refine_flag]``) or, where the engine honors bounds, a
  :class:`BoundedRefinableParameter` (JSON ``[value, refine_flag, min, max]``);
- plain (non-refinable) values get field-specific validation;
- numbers are JSON numbers (:data:`CoreFloat`, :data:`CoreInt`): a string or a
  boolean is never read as a number.

This module must never import an engine (enforced by an import-block test).
"""

from __future__ import annotations

import inspect
import json
import keyword
import math
import re
from fractions import Fraction
from dataclasses import dataclass
from typing import Annotated, Any, Callable, ClassVar, Generic, Literal, Mapping, Optional, Sequence, TypeVar, Union

import gemmi
import numpy as np
from packaging.specifiers import SpecifierSet
from packaging.version import InvalidVersion, Version
from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    PrivateAttr,
    Strict,
    StrictBool,
    TypeAdapter,
    ValidationError,
    WithJsonSchema,
    field_validator,
    model_serializer,
    model_validator,
)
from pydantic.json_schema import DEFAULT_REF_TEMPLATE, GenerateJsonSchema, JsonSchemaMode
from pydantic_core import InitErrorDetails, PydanticCustomError

from powderline.exceptions import StructuredWarning, SymmetryError
from powderline.symmetry import (
    ADJUSTMENT_REPORT_TOL,
    CELL_TOL,
    SPECIAL_POSITION_TOL,
    UIJ_TOL,
    Ties,
    analyze_site,
    canonical_space_group,
    cell_tie_groups,
    check_cell,
    coupling_groups,
)

# --- versions (A40, A65) ---------------------------------------------------

#: The core schema version new recipes are written against.
CORE_SCHEMA_VERSION = "0.1.0"
#: Core schema versions this PowderLine accepts (PEP 440 specifier). Widened
#: explicitly when a new core version is compatible; never inferred (A40).
SUPPORTED_CORE_SCHEMAS = "==0.1.0"

#: Size cap on the serialized ``metadata`` block, in bytes of UTF-8 JSON (A64).
#: A sanity limit against accidents (e.g. a pasted pattern); amend here and in
#: docs/SCHEMA_HISTORY.md.
METADATA_MAX_BYTES = 1024 * 1024

#: ``schema_name`` format: ``"<engine>.<workflow>"`` (A1, A18).
SCHEMA_NAME_PATTERN = r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$"


def parse_version(field: str, value: str) -> Version:
    """Parse a PEP 440 version string, raising ``ValueError`` naming ``field``."""
    try:
        return Version(value)
    except InvalidVersion:
        raise ValueError(f"{field} {value!r} is not a valid version (PEP 440, e.g. '0.1.0')") from None


def check_core_schema_version(version: str) -> None:
    """Raise ``ValueError`` unless ``version`` is in :data:`SUPPORTED_CORE_SCHEMAS`."""
    if parse_version("core_schema_version", version) not in SpecifierSet(SUPPORTED_CORE_SCHEMAS):
        from powderline import __version__

        raise ValueError(
            f"core_schema_version {version!r} is not supported by PowderLine {__version__} "
            f"(accepted: {SUPPORTED_CORE_SCHEMAS}; current: {CORE_SCHEMA_VERSION})"
        )


# --- units (A19) ------------------------------------------------------------

#: Unit strings used in ``json_schema_extra={"unit": ...}``.
UNIT_DEG_2THETA = "degree 2theta"
UNIT_DEGREE = "degree"
UNIT_ANGSTROM = "angstrom"
UNIT_ANGSTROM2 = "angstrom^2"
UNIT_ARBITRARY = "arbitrary"
UNIT_INV_INTENSITY2 = "1/intensity^2"


def unit_schema(unit: str) -> dict:
    return {"unit": unit}


def _array_schema(title: str, items: list[dict], description: str, **extra) -> dict:
    """JSON Schema for a model whose recipe JSON shape is a fixed-length list."""
    return {"title": title, "description": description, "type": "array",
            "prefixItems": items, "minItems": len(items), "maxItems": len(items), **extra}


_NUMBER = {"type": "number"}
_NUMBER_OR_NULL = {"anyOf": [{"type": "number"}, {"type": "null"}]}
_BOOLEAN = {"type": "boolean"}


_STRICT = ConfigDict(extra="forbid")


class CoreJsonSchema(GenerateJsonSchema):
    """JSON Schema generator that names a parametrized core model after its origin.

    pydantic names ``Atom[RefinableParameter]`` ``Atom_RefinableParameter_`` in
    ``$defs``; a recipe document holds one engine's schema (one parameter type),
    so plain ``Atom`` is unambiguous and readable. Only the short candidate names
    (no module path, no id) are shortened: pydantic's content-based dedup then
    falls back to its qualified names if two parametrizations ever share one
    document, and the id-bearing name it needs unique is left intact (devkit
    ``tasks/re03b-spike-generics.md``).
    """

    def normalize_name(self, name: str) -> str:
        if "." not in name and ":" not in name:
            name = re.sub(r"\[[^\]]*\]", "", name)
        return super().normalize_name(name)


class CoreModel(BaseModel):
    """Base of the core models: ``extra='forbid'`` and :class:`CoreJsonSchema` by default.

    Engine schemas build on it (directly, or through :class:`CoreRecipe` and
    :class:`Phase`), so their generated JSON Schema is readable too.
    """

    model_config = _STRICT

    @classmethod
    def model_json_schema(cls, by_alias: bool = True, ref_template: str = DEFAULT_REF_TEMPLATE,
                          schema_generator: type[GenerateJsonSchema] = CoreJsonSchema,
                          mode: JsonSchemaMode = "validation", **kwargs) -> dict[str, Any]:
        return super().model_json_schema(by_alias, ref_template, schema_generator, mode, **kwargs)


# --- numbers -----------------------------------------------------------------


def _integer_not_text_or_bool(v: Any) -> Any:
    if isinstance(v, (bool, str, bytes, bytearray)):
        raise PydanticCustomError("int_type", "Input should be a valid integer, got {kind}",
                                  {"kind": type(v).__name__})
    return v


#: A float field: any number (int or float, incl. numpy scalars), never a
#: string or a boolean (the JSON Schema says ``number``; pydantic's default
#: would accept ``"0.25"`` and ``true``). Engine schemas use it too.
CoreFloat = Annotated[float, Strict()]
#: An integer field: a whole number (``4`` or ``4.0``, as JSON Schema's
#: ``integer``), never a string or a boolean; ``4.5`` is rejected.
CoreInt = Annotated[int, BeforeValidator(_integer_not_text_or_bool)]


# --- names ------------------------------------------------------------------

#: A phase name or atom label: an ASCII letter, then ASCII letters, digits or ``_``.
NAME_PATTERN = r"^[A-Za-z][A-Za-z0-9_]*$"
#: Longest phase name or atom label. Phase names become file names with a suffix of
#: up to 21 characters (``_unit_cell_report.csv``); file systems allow 255 per name
#: and Windows 260 per path by default, so a name stays well inside both.
NAME_MAX_LENGTH = 64
#: Python's (hard) keywords: valid by the pattern but not identifiers (``None``, ``class``).
NAME_KEYWORDS = tuple(keyword.kwlist)
#: JSON Schema of a name (also the ``propertyNames`` of a name-keyed object).
NAME_JSON_SCHEMA = {"type": "string", "pattern": NAME_PATTERN, "maxLength": NAME_MAX_LENGTH,
                    "not": {"enum": list(NAME_KEYWORDS)}}


def _check_name(name: str) -> str:
    """The name rule every engine can honor, which is also a Python identifier (re/03b review C6).

    - GSAS-II renames a phase whose name has surrounding spaces or non-ASCII
      characters, and the parameterization then skips that phase silently.
    - easydiffraction accepts atom labels only of the form ``[A-Za-z_][A-Za-z0-9_]*``.
    - TOPAS emits phase names inside quotes and builds parameter names from them.
    - Phase names become report file names (``<phase>_unit_cell_report.csv``), so
      no character a file system rejects (``/``, ``:``, ...) and a bounded length.
    - Field paths are joined with ``.`` (``atoms.O1.Uiso``).
    """
    if not name.strip():
        raise ValueError("a name must not be empty or blank")
    if re.fullmatch(NAME_PATTERN, name) is None:
        raise ValueError(f"name {name!r} must start with a letter and contain only ASCII letters, digits "
                         "and '_' (e.g. 'O1', 'LaB6_a')")
    if len(name) > NAME_MAX_LENGTH:
        raise ValueError(f"name {name[:20]!r}... has {len(name)} characters; the limit is {NAME_MAX_LENGTH}")
    if keyword.iskeyword(name):
        raise ValueError(f"name {name!r} is a Python keyword; choose another name")
    return name


#: A phase name or an atom label (a dict key), see :func:`_check_name`. Core uses
#: it for the atom labels; engine schemas use it for their ``phases`` keys (with
#: :func:`name_keyed`, and :func:`check_names_unique_ignoring_case` for phases).
CoreName = Annotated[str, AfterValidator(_check_name), WithJsonSchema(NAME_JSON_SCHEMA)]


def check_names_unique_ignoring_case(names, what: str) -> None:
    """Raise ``ValueError`` if two of ``names`` differ only in case.

    Phase names become file names, and Windows and macOS file systems ignore
    case, so ``LaB6`` and ``lab6`` would overwrite each other's reports (and
    easydiffraction lowercases them). Engine payloads call it on their phases.
    """
    seen: dict[str, str] = {}
    for name in names:
        other = seen.setdefault(name.lower(), name)
        if other != name:
            raise ValueError(f"{what} {other!r} and {name!r} differ only in case; rename one")


def name_keyed(schema: dict) -> None:
    """``json_schema_extra`` for a ``dict[CoreName, ...]`` field: state the key rule as ``propertyNames``.

    pydantic writes a key rule as ``patternProperties`` (pattern only), which
    leaves other keys unchecked in JSON Schema; this checks every key against
    :data:`NAME_JSON_SCHEMA`.
    """
    pattern_properties = schema.pop("patternProperties", None)
    if pattern_properties:
        ((_pattern, value),) = pattern_properties.items()
        schema["propertyNames"] = {k: v for k, v in NAME_JSON_SCHEMA.items() if k != "type"}
        schema["additionalProperties"] = value


# --- parameter models (A20, A32, A93) ---------------------------------------


def _finite(name: str, v: Optional[float]) -> Optional[float]:
    if v is not None and not math.isfinite(v):
        raise ValueError(f"{name} must be finite, got {v!r}")
    return v


class RefinableParameter(BaseModel):
    """A refinable value with no bounds concept: JSON ``[value, refine_flag]``.

    Used where the engine has no native bounds for the quantity. A 4-element
    list here is an error, never silently truncated (A20). ``value`` is
    required (never ``null``, A93/A96).
    """

    model_config = _STRICT

    value: CoreFloat
    refine_flag: StrictBool

    @model_validator(mode="before")
    @classmethod
    def _from_list(cls, data: Any) -> Any:
        if isinstance(data, (list, tuple)):
            if len(data) == 4:
                raise ValueError(
                    "bounds are not supported for this parameter in this engine schema: "
                    "expected [value, refine_flag], got a 4-element "
                    "[value, refine_flag, min, max] list"
                )
            if len(data) != 2:
                raise ValueError(
                    f"expected [value, refine_flag], got a {len(data)}-element list"
                )
            return {"value": data[0], "refine_flag": data[1]}
        raise ValueError(
            f"expected a [value, refine_flag] list, got {type(data).__name__}"
        )

    @field_validator("value")
    @classmethod
    def _value_finite(cls, v):
        return _finite("value", v)

    @model_serializer
    def _to_list(self) -> list:
        return [self.value, self.refine_flag]

    @classmethod
    def __get_pydantic_json_schema__(cls, core_schema, handler) -> dict:
        return _array_schema(cls.__name__, [_NUMBER, _BOOLEAN], "[value, refine_flag]")


class BoundedRefinableParameter(BaseModel):
    """A refinable value with optional bounds: JSON ``[value, refine_flag, min, max]``.

    ``min``/``max`` may each be ``null`` (unbounded on that side). When given,
    ``min <= max`` and ``min <= value <= max``. Used only where the engine
    honors the bounds natively (A20, A33). ``value`` is required (never
    ``null``, A93/A96).
    """

    model_config = _STRICT

    value: CoreFloat
    refine_flag: StrictBool
    min: Optional[CoreFloat] = None
    max: Optional[CoreFloat] = None

    @model_validator(mode="before")
    @classmethod
    def _from_list(cls, data: Any) -> Any:
        if isinstance(data, (list, tuple)):
            if len(data) != 4:
                raise ValueError(
                    "expected [value, refine_flag, min, max] (min/max may be null), "
                    f"got a {len(data)}-element list"
                )
            return {"value": data[0], "refine_flag": data[1], "min": data[2], "max": data[3]}
        raise ValueError(
            f"expected a [value, refine_flag, min, max] list, got {type(data).__name__}"
        )

    @field_validator("value", "min", "max")
    @classmethod
    def _finite(cls, v, info):
        return _finite(info.field_name, v)

    @model_validator(mode="after")
    def _bounds(self) -> "BoundedRefinableParameter":
        lo, hi = self.min, self.max
        if lo is not None and hi is not None and lo > hi:
            raise ValueError(f"min ({lo}) must be <= max ({hi})")
        check_within_bounds(self.value, self, "value")
        return self

    @model_serializer
    def _to_list(self) -> list:
        return [self.value, self.refine_flag, self.min, self.max]

    @classmethod
    def __get_pydantic_json_schema__(cls, core_schema, handler) -> dict:
        return _array_schema(cls.__name__, [_NUMBER, _BOOLEAN, _NUMBER_OR_NULL, _NUMBER_OR_NULL],
                             "[value, refine_flag, min, max]; min/max may be null")


def check_within_bounds(value: float, param: BoundedRefinableParameter, field: str) -> None:
    """Raise ``ValueError`` unless ``param.min <= value <= param.max`` (open ends pass)."""
    if param.min is not None and value < param.min:
        raise ValueError(f"{field} ({value}) is below min ({param.min})")
    if param.max is not None and value > param.max:
        raise ValueError(f"{field} ({value}) is above max ({param.max})")


# --- plain-value checks (A32) ----------------------------------------------

#: An ionic scattering type in the recipe spelling (CIF/IUCr ``_atom_site_type_symbol``): element, charge 1-8, sign.
_SCATTERING_TYPE = re.compile(r"([A-Z][a-z]?)([1-8])([+-])")


def scattering_type_parts(symbol: str) -> tuple[str, int]:
    """``("La", 3)`` for ``"La3+"``, ``("O", -2)`` for ``"O2-"`` (P-47).

    The recipe spelling is the CIF/IUCr one: element, charge magnitude 1-8, then the sign. The engine
    spelling (GSAS-II's and TOPAS's ``La+3``) is an error naming the recipe form -- GSAS-II reads
    ``Fe3+`` as hydrogen and TOPAS reports a wrong symbol only on its console, so the translation is the
    gateway's, never the user's. A bare element is an error too: the neutral atom is stated by leaving
    the atom out of ``scattering_types``. Raises ``ValueError``.
    """
    m = _SCATTERING_TYPE.fullmatch(symbol)
    if m is None:
        alt = re.fullmatch(r"([A-Z][a-z]?)([+-])([1-8])", symbol)
        if alt:
            raise ValueError(f"scattering type {symbol!r}: write the ion as element, charge, sign: "
                             f"'{alt.group(1)}{alt.group(3)}{alt.group(2)}'")
        if gemmi.Element(symbol).atomic_number > 0 and gemmi.Element(symbol).name == symbol:
            raise ValueError(f"scattering type {symbol!r} is the neutral atom: leave the atom out of "
                             "scattering_types instead")
        raise ValueError(f"scattering type {symbol!r} is not of the form element, charge 1-8, sign (e.g. 'Fe3+', 'O2-')")
    element, charge, sign = m.group(1), int(m.group(2)), m.group(3)
    if not (gemmi.Element(element).atomic_number > 0 and gemmi.Element(element).name == element):
        raise ValueError(f"scattering type {symbol!r}: {element!r} is not a known element symbol")
    return element, charge if sign == "+" else -charge


def scattering_type_problems(types: Mapping[str, str], atoms: Mapping[str, Any], available: Optional[frozenset],
                             engine: str, loc: tuple = ("scattering_types",)) -> list:
    """The engine-schema rule for ``scattering_types`` (P-47): every key an atom label of the phase, every
    value an ion of that atom's element in the recipe spelling, and -- when ``available`` is given -- one the
    engine has a form factor for (the error names the forms it has for that element, in the recipe
    spelling, or says there is none). Returns ``InitErrorDetails``; the caller raises them."""
    problems = []
    for label, symbol in types.items():
        if label not in atoms:
            problems.append(custom_error("scattering_type_label",
                                         "scattering_types names '{label}', which is not an atom of this phase",
                                         loc + (label,), symbol, label=label))
            continue
        try:
            element, _charge = scattering_type_parts(str(symbol))
        except ValueError as exc:
            problems.append(custom_error("scattering_type_spelling", "{why}", loc + (label,), symbol, why=str(exc)))
            continue
        atom_element = getattr(atoms[label], "element", None)
        if atom_element is not None and element != atom_element:
            problems.append(custom_error(
                "scattering_type_element",
                "scattering type '{symbol}' is not an ion of {label}'s element '{element}'",
                loc + (label,), symbol, symbol=symbol, label=label, element=atom_element))
            continue
        if available is not None and symbol not in available:
            forms = sorted(s for s in available if re.match(rf"^{re.escape(element)}[1-8][+-]$", s))
            problems.append(custom_error(
                "scattering_type_unavailable",
                "{engine} has no X-ray form factor for '{symbol}'; " + (
                    "it has {forms} for {element}" if forms else "it has no ionic form for {element}: use the neutral atom"),
                loc + (label,), symbol, engine=engine, symbol=symbol, element=element, forms=", ".join(forms)))
    return problems


def check_element_symbol(symbol: str) -> str:
    """Return ``symbol`` if it is a bare element symbol in gemmi's table, exactly spelled.

    Raises ``ValueError`` otherwise. gemmi's own lookup is too lenient to use
    alone: it accepts any case (``"FE"``), reduces charged types to the neutral
    atom (``"Fe3+"`` -> Fe, which would change the X-ray scattering), and maps
    unknown symbols to ``X``. ``element`` is always the neutral atom (A63; the
    phase block stays portable across engines, P-43 D4): an ionic scattering type
    is stated in the engine's own phase block, ``scattering_types`` (P-47,
    :func:`scattering_type_parts`), never here.
    """
    element = gemmi.Element(symbol)
    if element.atomic_number > 0 and element.name == symbol:
        return symbol
    if any(c in symbol for c in "+-") or (symbol[-1:].isdigit()):
        raise ValueError(
            f"element {symbol!r}: element is the neutral atom; an ionic scattering type is stated in the "
            f"engine's phase block as scattering_types: {{<atom label>: \"Fe3+\"}} (element, charge, sign)"
        )
    # Suggest a spelling only for case/whitespace differences. gemmi also reads
    # a prefix (' Fe' -> F, 'Nax' -> Na), which must never be offered as a fix.
    stripped = gemmi.Element(symbol.strip())
    if stripped.atomic_number > 0 and stripped.name.lower() == symbol.strip().lower():
        raise ValueError(f"element {symbol!r}: write the element symbol as {stripped.name!r}")
    raise ValueError(f"element {symbol!r} is not a known element symbol")


# --- diffraction data -------------------------------------------------------


class XRDData(BaseModel):
    """Measured pattern: 2theta, intensity, weights.

    Every engine consumes ``tth`` in degrees 2theta and ``Itth_weights`` as
    1/sigma^2, as-is. (The rules are those of the unified schema's
    ``XRDDataModel``, see ``docs/SCHEMA_HISTORY.md``.)
    """

    model_config = _STRICT

    tth: list[CoreFloat] = Field(description="Two-theta values", json_schema_extra=unit_schema(UNIT_DEG_2THETA))
    Itth: list[CoreFloat] = Field(description="Intensity values", json_schema_extra=unit_schema(UNIT_ARBITRARY))
    Itth_weights: list[CoreFloat] = Field(description="Intensity weights (1/sigma^2)",
                                      json_schema_extra=unit_schema(UNIT_INV_INTENSITY2))
    filename: str | None = Field(default=None, description="Original filename for reference")

    @model_validator(mode='after')
    def validate_all_arrays_same_length(self):
        """Ensure tth, Itth, and Itth_weights have the same length."""
        lengths = [len(self.tth), len(self.Itth), len(self.Itth_weights)]
        if len(set(lengths)) > 1:
            raise ValueError(
                f"XRD data arrays must have the same length. "
                f"Got tth={len(self.tth)}, Itth={len(self.Itth)}, Itth_weights={len(self.Itth_weights)}"
            )
        return self

    @model_validator(mode='after')
    def validate_arrays_wellformed(self):
        """Reject ill-formed XRD data. PowderLine never repairs data — it rejects it.

        Transforming raw data (unit conversion, weight derivation, handling
        background-subtracted negatives) is the job of the reader/parser that builds
        this block, not PowderLine. Here we only enforce that what arrives is usable:

        * arrays must be non-empty;
        * every tth / Itth / Itth_weights value must be finite (no NaN or inf) —
          this catches, e.g., a weight computed as 1/esd**2 with esd == 0 (inf);
        * tth must be strictly increasing (a powder pattern is monotonic in 2-theta);
        * weights must be >= 0 (a 0 weight legitimately excludes a point; a negative
          weight is nonsensical) and at least one weight must be > 0 (all-zero =
          nothing to fit).

        A negative *intensity* is explicitly allowed: background-subtracted data
        legitimately dips below zero, so Itth is checked for finiteness only, not sign.
        """
        if len(self.tth) == 0:
            raise ValueError(
                "XRD data arrays must be non-empty (tth/Itth/Itth_weights have length 0)."
            )

        tth = np.asarray(self.tth, dtype=float)
        Itth = np.asarray(self.Itth, dtype=float)
        weights = np.asarray(self.Itth_weights, dtype=float)

        # All values finite (rejects NaN and +/-inf across all three arrays).
        for name, arr in (("tth", tth), ("Itth", Itth), ("Itth_weights", weights)):
            bad = np.where(~np.isfinite(arr))[0]
            if bad.size:
                i = int(bad[0])
                raise ValueError(
                    f"XRD data '{name}' contains non-finite values (NaN/inf); first at "
                    f"index {i} (value {float(arr[i])!r}). Fix the data upstream — "
                    "PowderLine does not repair xrd_data."
                )

        # tth must be strictly increasing.
        bad = np.where(np.diff(tth) <= 0)[0]
        if bad.size:
            i = int(bad[0])
            raise ValueError(
                f"XRD 'tth' must be strictly increasing; tth[{i + 1}]={float(tth[i + 1])!r} "
                f"<= tth[{i}]={float(tth[i])!r}. Sort/deduplicate the pattern upstream."
            )

        # Weights: non-negative, with at least one strictly positive.
        bad = np.where(weights < 0)[0]
        if bad.size:
            i = int(bad[0])
            raise ValueError(
                f"XRD 'Itth_weights' must be >= 0; first negative at index {i} "
                f"(value {float(weights[i])!r}). A 0 weight excludes a point; "
                "negative weights are invalid."
            )
        if not np.any(weights > 0):
            raise ValueError(
                "XRD 'Itth_weights' are all zero — nothing to fit. At least one "
                "weight must be > 0."
            )

        return self


class FitRange(BaseModel):
    """Fit window in 2theta: JSON ``[min, max]``; either end may be ``null`` (open)."""

    model_config = _STRICT

    min: Optional[CoreFloat] = None
    max: Optional[CoreFloat] = None

    @model_validator(mode="before")
    @classmethod
    def _from_list(cls, data: Any) -> Any:
        if isinstance(data, (list, tuple)):
            if len(data) != 2:
                raise ValueError(
                    f"fit_range must be a list of exactly 2 elements [min, max], got {len(data)}"
                )
            return {"min": data[0], "max": data[1]}
        raise ValueError(f"fit_range must be a [min, max] list, got {type(data).__name__}")

    @field_validator("min", "max")
    @classmethod
    def _finite(cls, v, info):
        return _finite(info.field_name, v)

    @model_validator(mode="after")
    def _ordered(self) -> "FitRange":
        if self.min is not None and self.max is not None and not self.max > self.min:
            raise ValueError(f"fit_range max ({self.max}) must be greater than min ({self.min})")
        return self

    @model_serializer
    def _to_list(self) -> list:
        return [self.min, self.max]

    @classmethod
    def __get_pydantic_json_schema__(cls, core_schema, handler) -> dict:
        return _array_schema("FitRange", [_NUMBER_OR_NULL, _NUMBER_OR_NULL],
                             "[min, max]; either end may be null (open)",
                             unit=UNIT_DEG_2THETA)


#: The fewest weighted data points a fit window may hold (A154 N9, P-04).
MIN_WEIGHTED_POINTS_IN_WINDOW = 2


def check_fit_range_within_data(fit_range: Optional[FitRange], xrd_data: XRDData) -> None:
    """Raise ``ValueError`` unless both ``fit_range`` ends lie within the data's 2theta span
    and the window holds at least two points with a positive weight (A154 N9).

    A payload-level check (it needs the pattern): engine payload models call it
    from a model validator (A68). ``None`` (or an open end) means "the data limit";
    the two-point rule applies to the open window too, so a one-point pattern is
    refused here rather than by the engine.
    """
    if fit_range is not None:
        lo, hi = xrd_data.tth[0], xrd_data.tth[-1]
        for name, end in (("min", fit_range.min), ("max", fit_range.max)):
            if end is not None and not lo <= end <= hi:
                raise ValueError(
                    f"fit_range {name} ({end}) is outside the data's 2theta range [{lo}, {hi}]"
                )
    fit_limits_on_data(fit_range, xrd_data)  # the window holds two weighted points


def fit_limits_on_data(fit_range: Optional[FitRange], xrd_data: XRDData) -> tuple[float, float]:
    """The limits a gateway hands its engine: the window's first and last weighted data points (A149, A154).

    A stated ``min`` becomes the first weighted point with 2theta >= min, a
    stated ``max`` the last weighted point with 2theta <= max; an open end (or
    no ``fit_range``) becomes the first or last weighted point of the data, so
    zero-weight points at the data's edges never stretch an engine's window.
    With its limits on these points every engine fits exactly the points
    min <= 2theta <= max that core scores (A131), and maps its Chebyshev basis
    over the same first and last points: GSAS-II's slice ends one point past a
    limit between points (EB-54) and starts at the first data point, weighted
    or not, when no limit is set; TOPAS takes the point nearest each limit
    (EB-59) of an ``.xye`` without zero-weight points. Raises ``ValueError``
    when fewer than two weighted points lie in the window (A154 N9, P-04): a
    one-point window would give an engine coincident limits (TOPAS
    ``start_X == finish_X``) and nothing to fit.
    """
    lo = None if fit_range is None else fit_range.min
    hi = None if fit_range is None else fit_range.max
    inside = [t for t, w in zip(xrd_data.tth, xrd_data.Itth_weights)
              if w > 0 and (lo is None or t >= lo) and (hi is None or t <= hi)]
    if len(inside) < MIN_WEIGHTED_POINTS_IN_WINDOW:
        raise ValueError(f"fit_range [{lo}, {hi}] holds {len(inside)} data point(s) with a positive weight; "
                         f"at least {MIN_WEIGHTED_POINTS_IN_WINDOW} are required")
    return inside[0], inside[-1]


# --- background -------------------------------------------------------------


class ChebyshevBackground(BaseModel):
    """Chebyshev polynomial background: ``num_coefficients``, ``coefficients``, ``refine_flag``.

    Coefficient semantics (scaling, which polynomial basis) are engine-specific
    and documented in each engine schema (A22.7), not here. (The shape is the
    unified schema's, see ``docs/SCHEMA_HISTORY.md``.)
    """

    model_config = _STRICT

    num_coefficients: CoreInt = Field(gt=0, description="Number of Chebyshev coefficients")
    coefficients: list[CoreFloat] = Field(description="Coefficient values")
    refine_flag: StrictBool = Field(description="Whether to refine background")

    @field_validator('coefficients')
    @classmethod
    def validate_coefficients_length(cls, v, info):
        """Ensure number of coefficients matches num_coefficients."""
        num_coef = info.data.get('num_coefficients')
        if num_coef is not None and len(v) != num_coef:
            raise ValueError(f"Number of coefficients ({len(v)}) must match num_coefficients ({num_coef})")
        return v

    @field_validator('coefficients')
    @classmethod
    def _coefficients_finite(cls, v):
        for i, c in enumerate(v):
            _finite(f"coefficients[{i}]", c)
        return v


# --- phase block (A93-A96, A100, A105; values: A63, A69, A73, A76-A78) -------

#: The parameter type of a phase block: :class:`RefinableParameter`, or
#: :class:`BoundedRefinableParameter` for an engine that honors bounds (A20).
#: One type for every structural field, cell and atoms (review N6).
P = TypeVar("P", RefinableParameter, BoundedRefinableParameter)


def absent_not_null(v: Any, info) -> Any:
    """A field that may be left out is never ``null`` (A96): reject an explicit null."""
    if v is None:
        raise ValueError(f"{info.field_name} must not be null; leave it out instead")
    return v


def absent_not_null_schema(unit: Optional[str] = None):
    """JSON Schema of a field that may be left out but is never null (A96).

    The field is ``Optional`` only so that "left out" can be held as ``None``;
    the schema shows the non-null type, no ``"default": null``, and the unit.
    """
    def extra(schema: dict) -> None:
        schema.pop("default", None)
        any_of = schema.pop("anyOf", None)
        if any_of:
            schema.update(next(s for s in any_of if s.get("type") != "null"))
        if unit:
            schema.update(unit_schema(unit))
    return extra


class UnitCell(CoreModel, Generic[P]):
    """Cell constants, each a refinable parameter. No ``volume``: every engine
    derives it from a..gamma (A75). The values must fit the space group (A77,
    checked by :class:`Phase`)."""

    a: P = Field(json_schema_extra=unit_schema(UNIT_ANGSTROM))
    b: P = Field(json_schema_extra=unit_schema(UNIT_ANGSTROM))
    c: P = Field(json_schema_extra=unit_schema(UNIT_ANGSTROM))
    alpha: P = Field(json_schema_extra=unit_schema(UNIT_DEGREE))
    beta: P = Field(json_schema_extra=unit_schema(UNIT_DEGREE))
    gamma: P = Field(json_schema_extra=unit_schema(UNIT_DEGREE))

    @field_validator("a", "b", "c")
    @classmethod
    def _length(cls, v, info):
        if not v.value > 0:
            raise ValueError(f"cell length {info.field_name} must be positive, got {v.value}")
        if isinstance(v, BoundedRefinableParameter) and v.min is not None and not v.min > 0:
            raise ValueError(f"cell length {info.field_name}: min must be positive (a cell length is), "
                             f"got {v.min}; use null for no lower bound")
        return v

    @field_validator("alpha", "beta", "gamma")
    @classmethod
    def _angle(cls, v, info):
        if not 0 < v.value < 180:
            raise ValueError(f"cell angle {info.field_name} must be between 0 and 180 degrees, got {v.value}")
        if isinstance(v, BoundedRefinableParameter):
            for side, bound in (("min", v.min), ("max", v.max)):
                if bound is not None and not 0 < bound < 180:
                    raise ValueError(f"cell angle {info.field_name}: {side} must be between 0 and 180 degrees "
                                     f"(a cell angle is), got {bound}; use null for no {side} bound")
        return v


_UANISO_KEYS = ("U11", "U22", "U33", "U12", "U13", "U23")


class UanisoTensor(CoreModel, Generic[P]):
    """Anisotropic ADPs: all six of U11, U22, U33, U12, U13, U23, each a parameter (A^2)."""

    U11: P = Field(json_schema_extra=unit_schema(UNIT_ANGSTROM2))
    U22: P = Field(json_schema_extra=unit_schema(UNIT_ANGSTROM2))
    U33: P = Field(json_schema_extra=unit_schema(UNIT_ANGSTROM2))
    U12: P = Field(json_schema_extra=unit_schema(UNIT_ANGSTROM2))
    U13: P = Field(json_schema_extra=unit_schema(UNIT_ANGSTROM2))
    U23: P = Field(json_schema_extra=unit_schema(UNIT_ANGSTROM2))


#: JSON Schema of the ADP pairing (A96): ``ADP`` selects which one of ``Uiso`` /
#: ``Uaniso`` is required; the other must be left out.
_ADP_PAIRING_SCHEMA = {"allOf": [
    {"if": {"properties": {"ADP": {"const": adp}}},
     "then": {"required": [adp], "not": {"required": [other]}}}
    for adp, other in (("Uiso", "Uaniso"), ("Uaniso", "Uiso"))
]}


class Atom(CoreModel, Generic[P]):
    """One atom of a phase: coordinates, occupancy and ADPs are refinable parameters.

    Coordinates are fractional JSON numbers. On a special position, the values
    fixed or tied by symmetry follow :class:`Phase`'s rule (A73, A120, A121): a
    fixed value with a decimal form exactly (``0.5``), a third to at least 6
    decimals (``0.333333``), a coupled one within 6 decimals of the value
    derived from its group's first member. ``occupancy`` is required
    and 0 to 1 inclusive (A76, A96). ``Multiplicity`` is optional and, when
    stated, must match the derived value (A69 T3). ``ADP`` selects which
    thermal parameter is **required**: ``Uiso``, or ``Uaniso`` with all six of
    U11..U23; the other must be left out (an error at that field otherwise, and
    the JSON Schema states the rule). ``Uaniso`` follows the site symmetry by
    the same rule: a fixed component exactly 0, a coupled one within 1e-6 A^2
    (A78, A121). Nothing is ``null`` (A96).
    """

    model_config = ConfigDict(extra="forbid", json_schema_extra=_ADP_PAIRING_SCHEMA)

    element: str = Field(description="Bare element symbol, exactly as in the periodic table (e.g. 'Fe')")
    x: P = Field(description="Fractional x coordinate")
    y: P = Field(description="Fractional y coordinate")
    z: P = Field(description="Fractional z coordinate")
    occupancy: P = Field(description="Site occupancy, 0 to 1 inclusive")
    Multiplicity: Optional[CoreInt] = Field(default=None, json_schema_extra=absent_not_null_schema(),
                                            description="Site multiplicity; optional, cross-checked when stated")
    ADP: Literal["Uiso", "Uaniso"] = Field(description="Displacement-parameter type")
    Uiso: Optional[P] = Field(default=None, json_schema_extra=absent_not_null_schema(UNIT_ANGSTROM2),
                              description="Isotropic ADP; required when ADP is 'Uiso', else left out")
    Uaniso: Optional[UanisoTensor[P]] = Field(
        default=None, json_schema_extra=absent_not_null_schema(),
        description="All six of U11, U22, U33, U12, U13, U23; required when ADP is 'Uaniso', else left out")

    _not_null = field_validator("Multiplicity", "Uiso", "Uaniso", mode="before")(absent_not_null)

    @field_validator("element")
    @classmethod
    def _element(cls, v: str) -> str:
        return check_element_symbol(v)

    @field_validator("occupancy")
    @classmethod
    def _occupancy(cls, v):
        if not 0.0 <= v.value <= 1.0:
            raise ValueError(f"occupancy must be between 0 and 1 inclusive, got {v.value}")
        return v

    @model_serializer(mode="wrap")
    def _omit_absent(self, handler):
        """Leave out absent optional fields, so a dump validates again (no ``null``, A96)."""
        data = handler(self)
        for name in ("Multiplicity", "Uiso", "Uaniso"):
            if getattr(self, name) is None:
                data.pop(name, None)
        return data

    @model_validator(mode="after")
    def _adp_block(self) -> "Atom":
        """``ADP`` selects the required thermal parameter; errors at the field concerned."""
        required, other = ("Uiso", "Uaniso") if self.ADP == "Uiso" else ("Uaniso", "Uiso")
        problems = []
        if getattr(self, required) is None:
            problems.append(InitErrorDetails(
                type=PydanticCustomError("missing", "{field} is required when ADP is '{adp}'",
                                         {"field": required, "adp": self.ADP}),
                loc=(required,), input=None))
        if getattr(self, other) is not None:
            problems.append(InitErrorDetails(
                type=PydanticCustomError("extra_forbidden", "{field} must be left out when ADP is '{adp}'",
                                         {"field": other, "adp": self.ADP}),
                loc=(other,), input=getattr(self, other).model_dump()))
        if problems:
            raise ValidationError.from_exception_data(type(self).__name__, problems)
        return self


_OPEN_PARAMETER_TYPE = (
    "{name} has no parameter type: subclass Phase[RefinableParameter] (no bounds) or "
    "Phase[BoundedRefinableParameter] (bounds); a deliberately generic subclass declares "
    "Generic[P] and is parametrized before use"
)

#: Phase fields owned by core; an engine subclass may not redeclare them (A93).
RESERVED_PHASE_FIELDS = ("space_group", "unit_cell", "atoms")


class MarchDollase(CoreModel, Generic[P]):
    """March-Dollase preferred orientation (P-48, re/29): a building block the engine phase models adopt.

    ``hkl`` is the texture axis (integers, not all zero); ``ratio`` the March coefficient in the IUCr / GSAS-II
    convention -- 1 random, < 1 platy, > 1 needle -- strictly positive. The parameter type is the engine's
    (gsasii ``[value, flag]``, easydiffraction ``[value, flag, min, max]``). An engine adds its own extras beside
    it (easydiffraction's ``march_random_fract``). Not a core ``Phase`` field: preferred orientation is an engine
    capability, and a core field would reserve the name for engines that do not have it yet (A93, A109).
    """

    model: Literal["march_dollase"] = Field(description="The only model in 0.1.0")
    hkl: tuple[CoreInt, CoreInt, CoreInt] = Field(description="Texture axis as Miller indices, not all zero")
    ratio: P = Field(description="March coefficient r: 1 = random, < 1 platy, > 1 needle; > 0")

    @field_validator("hkl")
    @classmethod
    def _axis(cls, v):
        if all(int(x) == 0 for x in v):
            raise ValueError("hkl must not be (0, 0, 0): the texture axis has no direction")
        return v

    @field_validator("ratio")
    @classmethod
    def _positive(cls, v):
        if v.value <= 0:
            raise ValueError(f"ratio must be > 0 (1 = no preferred orientation), got {v.value}")
        return v


class Phase(CoreModel, Generic[P]):
    """A phase block's core part: space group, cell and atoms (A93).

    Engine schemas subclass ``Phase[TheirParameterType]`` and add their own
    phase fields flat (gsasii: ``scale``, ``peak_broadening``); the phase name
    is the key of the payload's ``phases`` dict (A100). Core's field names are
    reserved (:data:`RESERVED_PHASE_FIELDS`): redeclaring one raises
    ``TypeError`` when the subclass is defined.

    ``space_group`` is gemmi's canonical name (A105). Validation derives each
    atom's site (multiplicity, DOF) from it (:func:`powderline.symmetry.analyze_site`)
    and rejects ambiguous positions and stated multiplicities that don't match.

    **One rule for symmetry-determined values** (A115, A120, A121, A123): the
    first member of each tie group is an independent parameter, kept exactly as
    stated. Every other value is *derived* from the space group and those
    parameters in exact rational arithmetic, and the validated model holds the
    derived value (the float nearest it), so every tie holds exactly and every
    engine receives one structure. The recipe states every derived value; how
    closely is checked per kind:

    - a **constant** of the space group (a fixed coordinate, a fixed Uij = 0)
      with an exact decimal form must be written exactly (to floating-point
      precision, :data:`~powderline.symmetry.ADJUSTMENT_REPORT_TOL`): ``0.5``,
      not ``0.4999999``; ``0``, not ``1e-9``. One with none (a third) is
      written to at least 6 decimals (within 5e-6, A73) and read;
    - a value **derived from another stated value** (a coupled coordinate
      ``y = 2x``, ``y = x + 1/3``; a coupled Uij ``U12 = U22/2``; a tied
      member's bounds) is read within the stated precision of its family:
      coordinates 5e-6 (A73), Uij 1e-6 A^2 (A78);
    - the **cell** (A77, A123): tied lengths and angles equal the first
      member's, and fixed angles are 90 or 120, within ``CELL_TOL``
      (1e-9, relative on lengths).

    Anything else is an error that gives the values to write. Reading carries
    no warning: within these tolerances the recipe has only that meaning (A73's
    band rule excludes "just off" positions), and a dump of the model validates
    as itself.

    Refine flags and bounds must agree with the symmetry ties
    (:func:`~powderline.symmetry.cell_tie_groups`,
    :func:`~powderline.symmetry.coupling_groups`; A94, A95, A98, A106):
    the members of one tie group carry the same flag (F1); a symmetry-fixed
    parameter has flag false (F2) and no bounds (A106); different groups are
    independent (F3); with bounds, each member's bounds follow the tie's
    relation from the first member's (F4: ``member = k*rep + c`` maps
    ``[min, max]`` to ``[k*min + c, k*max + c]``, swapped for k < 0). Atoms on
    the same site are independent (A104).

    Every problem is reported at its own location (A70): ``unit_cell``,
    ``atoms.<label>`` (the position), ``atoms.<label>.Multiplicity``,
    ``atoms.<label>.Uaniso``; a flag or bound rule at the parameter
    (``unit_cell.b``, ``atoms.<label>.y``, ``atoms.<label>.Uaniso.U12``), for F1
    at every member whose flag differs from the group's first member (review
    N1); all of them together, in one ``ValidationError``.
    These checks run only once every field is valid: pydantic does not run
    model-level validators after a field error, so e.g. an unknown element is
    reported first, and the symmetry checks follow once it is fixed.

    :meth:`warnings` holds informative findings that change nothing: a
    ``Uaniso`` that is not positive definite (A118).
    """

    space_group: str = Field(description="gemmi's canonical extended Hermann-Mauguin name, e.g. "
                                         "'P m -3 m', 'C 1 2/m 1', 'R -3 m:H', 'F d -3 m:2'")
    unit_cell: UnitCell[P]
    atoms: dict[CoreName, Atom[P]] = Field(
        min_length=1, json_schema_extra=name_keyed,
        description="Atoms keyed by unique label: a letter, then ASCII letters, digits or '_'")

    _sites: dict = PrivateAttr(default_factory=dict)
    _warnings: list = PrivateAttr(default_factory=list)

    @classmethod
    def __pydantic_init_subclass__(cls, **kwargs: Any) -> None:
        """Guard core's contract in every engine subclass (A93, A109, A114, A122).

        A subclass may add fields and validators that *check*, but nothing that
        replaces, skips or rewrites core's validation:

        1. no class in its MRO besides core's own (a subclass or a mixin) may
           redeclare core's fields, reuse the name of a core validator, private
           attribute or method, or define a pydantic entry point
           (:data:`_RESERVED_ENTRY_POINTS`); pydantic collects validators by
           name, so a same-named validator would silently replace core's;
        2. every core validator must still be core's own function (catches any
           route the names miss);
        3. its own validators run in ``'after'`` mode only (a model validator,
           or a field validator on a core field): a ``'before'``, ``'wrap'`` or
           ``'plain'`` one could rewrite the recipe before core reads it, or
           skip core entirely;
        4. ``extra`` stays ``'forbid'`` (A19), and the parameter type is
           :class:`RefinableParameter` or :class:`BoundedRefinableParameter`.

        A canary test runs core's must-fail recipes through every engine phase
        model (``tests/test_phase_canary.py``).
        """
        super().__pydantic_init_subclass__(**kwargs)
        generic = cls.__pydantic_generic_metadata__
        if generic["origin"] is not None:
            wrong = [a for a in generic["args"] if not isinstance(a, TypeVar)
                     and not (isinstance(a, type) and issubclass(a, (RefinableParameter, BoundedRefinableParameter)))]
            if wrong:
                raise TypeError(f"{cls.__name__}: the parameter type must be RefinableParameter or "
                                f"BoundedRefinableParameter, not {', '.join(map(repr, wrong))}")
        core_ancestry = set(Phase.__mro__)
        for klass in cls.__mro__:
            if klass in core_ancestry:
                continue
            if issubclass(klass, Phase) and klass.__pydantic_generic_metadata__["origin"] is not None:
                continue  # a parametrization (e.g. Phase[RefinableParameter]); its origin is checked itself
            annotations = inspect.get_annotations(klass)
            redeclared = [n for n in RESERVED_PHASE_FIELDS if n in annotations]
            if redeclared:
                raise TypeError(
                    f"{klass.__name__} redeclares the core phase field(s) {', '.join(redeclared)}; "
                    "core owns space_group, unit_cell and atoms"
                )
            reused = sorted(n for n in _reserved_phase_members() if n in klass.__dict__ or n in annotations)
            if reused:
                raise TypeError(
                    f"{klass.__name__} reuses the core phase name(s) {', '.join(reused)}; a same-named "
                    "validator, method or private attribute would replace core's silently; rename it"
                )
            entry = sorted(n for n in _RESERVED_ENTRY_POINTS
                           if n in klass.__dict__ and _defined_outside_pydantic(klass.__dict__[n]))
            if entry:
                raise TypeError(
                    f"{klass.__name__} defines {', '.join(entry)}; a phase model may not override pydantic's "
                    "entry points, which could skip or replace core's validation"
                )
        decorators = cls.__pydantic_decorators__
        replaced = sorted(name for kind, name, func in _core_decorators()
                          if _underlying(getattr(decorators, kind).get(name)) is not func)
        if replaced:
            raise TypeError(f"{cls.__name__} replaces the core validator(s) {', '.join(replaced)}")
        core_names = {name for _kind, name, _func in _core_decorators()}
        rewriting = sorted(
            [n for n, d in decorators.model_validators.items() if n not in core_names and d.info.mode != "after"]
            + [n for n, d in decorators.field_validators.items()
               if n not in core_names and d.info.mode != "after"
               and ({"*", *RESERVED_PHASE_FIELDS} & set(d.info.fields))]
            + list(decorators.validators) + list(decorators.root_validators))
        if rewriting:
            raise TypeError(
                f"{cls.__name__}: validator(s) {', '.join(rewriting)} must be 'after' validators (pydantic v2 "
                "@model_validator / @field_validator): a 'before', 'wrap' or 'plain' validator could rewrite "
                "the recipe before core reads it, or skip core's validation"
            )
        if cls.model_config.get("extra") != "forbid":
            raise TypeError(f"{cls.__name__} must keep extra='forbid'")
        if cls.__pydantic_generic_metadata__["parameters"] and "__orig_bases__" not in cls.__dict__:
            # ``class EnginePhase(Phase)`` forgot the parameter type. A deliberately generic
            # subclass declares ``Generic[P]`` and is checked again when it is validated.
            raise TypeError(_OPEN_PARAMETER_TYPE.format(name=cls.__name__))

    @model_validator(mode="before")
    @classmethod
    def _parameter_type_chosen(cls, data: Any) -> Any:
        """Refuse to validate without a parameter type (re/03b review A2).

        Unparametrized, ``P`` would accept both parameter shapes, so one phase could
        mix ``[value, flag]`` and ``[value, flag, min, max]``. An engine schema fixes
        one type; this is a programming error, so it is a ``TypeError``, not a
        validation error.
        """
        if cls.__pydantic_generic_metadata__["parameters"]:
            raise TypeError(_OPEN_PARAMETER_TYPE.format(name=cls.__name__))
        return data

    @field_validator("space_group")
    @classmethod
    def _space_group(cls, v: str) -> str:
        canonical_space_group(v)  # SymmetryError is a ValueError
        return v

    @model_validator(mode="after")
    def _sites_check(self) -> "Phase":
        problems: list[InitErrorDetails] = []

        def problem(loc: tuple, message: str, value: Any) -> None:
            problems.append(InitErrorDetails(type="value_error", loc=loc, input=value,
                                             ctx={"error": ValueError(message)}))

        def tie_rules(loc: tuple, params: dict, ties: Ties, family: "_Family", context: str,
                      fixed_text) -> dict:
            errors, bounds = _tie_rules(params, ties, family, context, fixed_text)
            for name, message in errors:
                problem((*loc, name), message, params[name].model_dump())
            return bounds

        sg = self.space_group
        seen: dict[str, str] = {}
        for label in self.atoms:  # A112 (amended): an atom label is unique ignoring case
            other = seen.setdefault(label.lower(), label)
            if other != label:
                problem(("atoms", label), f"atom labels {other!r} and {label!r} differ only in case; rename one",
                        label)

        cell = self.unit_cell
        cell_params = {k: getattr(cell, k) for k in _CELL_FIELDS}
        cell_ties = cell_tie_groups(sg)
        fixed_angle = lambda name: _fixed_cell_angle(cell_ties, name)  # noqa: E731
        derived_cell, write = _derive(cell_ties, {k: p.value for k, p in cell_params.items()}, fixed_angle, _CELL)
        cell_ok = not write
        if write:  # A77, A123
            problem(("unit_cell",),
                    f"unit cell is inconsistent with {sg!r} ({cell_ties.crystal_system}): stated "
                    f"{', '.join(f'{k} = {cell_params[k].value!r}' for k in write)}, but by symmetry "
                    f"{_ties_text(cell_ties, fixed_angle, only=write)}; write {_write_text(write)}",
                    cell.model_dump())
        else:
            try:  # the metric must then be invariant (A77); the tie groups are checked against it exhaustively
                check_cell(sg, tuple(derived_cell[k] for k in _CELL_FIELDS))
            except SymmetryError as exc:  # pragma: no cover - cell_tie_groups agrees with the metric
                problem(("unit_cell",), str(exc), cell.model_dump())
                cell_ok = False
        if cell_ok:  # flag and bound rules need a valid cell (A95, A98)
            bounds = tie_rules(("unit_cell",), cell_params, cell_ties, _CELL,
                               f"{cell_ties.crystal_system} cell ({sg!r})", lambda name: f"{fixed_angle(name)}")
            updates = _updated(cell_params, derived_cell, bounds)
            _note_derived(self._warnings, "unit_cell", cell_params, derived_cell, cell_ties, fixed_angle,
                               f"{cell_ties.crystal_system} cell ({sg!r})")
            if updates:
                self.unit_cell = cell.model_copy(update=updates)  # the caller's cell stays as given
        model_cell = tuple(getattr(self.unit_cell, k).value for k in _CELL_FIELDS)

        for label, atom in self.atoms.items():
            try:
                site = analyze_site(sg, (atom.x.value, atom.y.value, atom.z.value))
            except SymmetryError as exc:
                problem(("atoms", label), str(exc), atom.model_dump())
                continue  # the checks below need the site
            self._sites[label] = site
            context = f"atom {label!r} (multiplicity {site.multiplicity} in {sg!r})"
            ties = coupling_groups(sg, site.canonical)
            exact_xyz = lambda name: site.exact["xyz".index(name)]  # noqa: E731
            xyz = {k: getattr(atom, k) for k in "xyz"}
            stated = dict(zip("xyz", site.stated))
            derived_xyz, write = _derive(ties.xyz, stated, exact_xyz, _COORDINATES)
            if write:  # A73, A120, A121: within 5e-6 of a special position, but not stated as it
                off = max(abs(stated[name] - value) for name, (value, _tol) in write.items())
                problem(("atoms", label),
                        f"{context}: {site.stated} is {off:.2g} from a special position, not on it "
                        f"({_ties_text(ties.xyz, exact_xyz)}); write {_write_text(write)}", atom.model_dump())
            if atom.Multiplicity is not None and atom.Multiplicity != site.multiplicity:
                problem(("atoms", label, "Multiplicity"),
                        f"stated Multiplicity {atom.Multiplicity}, derived {site.multiplicity} "
                        f"({sg!r}, site {site.stated})", atom.Multiplicity)
            updates = _updated(xyz, derived_xyz, tie_rules(("atoms", label), xyz, ties.xyz, _COORDINATES, context,
                                                            lambda name: str(exact_xyz(name))))
            _note_derived(self._warnings, f"atoms.{label}", xyz, derived_xyz, ties.xyz, exact_xyz, context)
            if atom.Uaniso is not None:
                uij = {k: getattr(atom.Uaniso, k) for k in _UANISO_KEYS}
                derived_u, write_u = _derive(ties.uij, {k: p.value for k, p in uij.items()},
                                             lambda _name: Fraction(0), _UIJ)
                if write_u:  # A78, A115, A121
                    problem(("atoms", label, "Uaniso"),
                            f"{context}: Uaniso is not site-symmetric ({_ties_text(ties.uij, lambda _n: 0)}); "
                            f"write {_write_text(write_u)}", atom.model_dump()["Uaniso"])
                elif cell_ok:
                    principal = _principal_msd(model_cell, tuple(derived_u[k] for k in _UANISO_KEYS))
                    scale = float(np.max(np.abs(principal)))
                    if principal[0] <= 1e-12 * scale:  # informative, not an error (A118): changes nothing
                        shown = ", ".join("0" if abs(v) <= 1e-12 * scale else f"{v:.3g}" for v in principal)
                        self._warnings.append(StructuredWarning(
                            code="uaniso_not_positive_definite",
                            message=(f"{context}: Uaniso is not positive definite (principal mean-square "
                                     f"displacements {shown} A^2), so it describes no thermal ellipsoid; "
                                     "it is used as stated"),
                            field_path=f"atoms.{label}.Uaniso",
                        ))
                u_updates = _updated(uij, derived_u, tie_rules(("atoms", label, "Uaniso"), uij, ties.uij, _UIJ,
                                                                context, lambda _name: "0"))
                _note_derived(self._warnings, f"atoms.{label}.Uaniso", uij, derived_u, ties.uij, lambda _name: 0, context)
                if u_updates:
                    updates["Uaniso"] = atom.Uaniso.model_copy(update=u_updates)
            if updates:
                self.atoms[label] = atom.model_copy(update=updates)  # the caller's atom stays as given
        if problems:
            raise ValidationError.from_exception_data(type(self).__name__, problems)
        return self

    def site(self, label: str):
        """The :class:`~powderline.symmetry.SiteAnalysis` of atom ``label`` (its symmetry, not its values:
        the model's atom holds the coordinates the engines receive)."""
        return self._sites[label]

    def warnings(self) -> list:
        """Structured warnings from validating this phase (paths relative to it).

        Informative: the recipe itself is never changed (A115), and validating
        the same recipe again gives the same warnings. ``symmetry_value_derived``
        (level ``info``, P-34) records each value the model holds in its exact
        symmetry-derived form because it was stated within tolerance of it.
        """
        return list(self._warnings)


def _reserved_phase_members() -> frozenset[str]:
    """Names core's :class:`Phase` defines besides its fields: validators, private attributes, methods."""
    decorators = Phase.__pydantic_decorators__
    validators = {n for kind in ("validators", "field_validators", "root_validators", "field_serializers",
                                 "model_serializers", "model_validators", "computed_fields")
                  for n in getattr(decorators, kind)}
    # Methods written in Phase itself (not the ones pydantic or abc generate, e.g. model_post_init).
    methods = {n for n, v in Phase.__dict__.items()
               if inspect.isfunction(v) and not n.startswith("__") and v.__qualname__.startswith("Phase.")}
    return frozenset(validators | methods | set(Phase.__private_attributes__))


#: pydantic entry points a phase model (or a mixin in its MRO) may not define: each could
#: skip or replace core's validation without reusing a core name (A122).
_RESERVED_ENTRY_POINTS = ("__init__", "model_post_init", "model_validate", "model_validate_json",
                          "model_validate_strings", "model_construct", "__get_pydantic_core_schema__",
                          "__pydantic_init_subclass__", "__class_getitem__")


def _underlying(obj: Any) -> Any:
    """The plain function behind a pydantic decorator, classmethod or bound method."""
    func = getattr(obj, "func", obj)
    return getattr(func, "__func__", func)


def _defined_outside_pydantic(obj: Any) -> bool:
    """False for the members pydantic generates in every model (e.g. ``model_post_init``)."""
    func = _underlying(obj)
    func = getattr(func, "__wrapped__", func)
    return not (getattr(func, "__module__", None) or "").startswith("pydantic")


def _core_decorators() -> list[tuple[str, str, Any]]:
    """``(kind, name, function)`` of every validator and serializer core's :class:`Phase` defines."""
    decorators = Phase.__pydantic_decorators__
    return [(kind, name, _underlying(info))
            for kind in ("validators", "field_validators", "root_validators", "field_serializers",
                         "model_serializers", "model_validators")
            for name, info in getattr(decorators, kind).items()]


_CELL_FIELDS = ("a", "b", "c", "alpha", "beta", "gamma")


def _uij_matrix(u) -> np.ndarray:
    """The symmetric 3x3 matrix of (U11, U22, U33, U12, U13, U23)."""
    u11, u22, u33, u12, u13, u23 = u
    return np.array([[u11, u12, u13], [u12, u22, u23], [u13, u23, u33]], dtype=float)


def _principal_msd(cell: tuple, u) -> np.ndarray:
    """The principal mean-square displacements (A^2, ascending) of ``u`` in ``cell`` (A118).

    The Cartesian tensor is ``A N U N A^T`` (``A`` the orthogonalization matrix,
    ``N = diag(a*, b*, c*)``). It is a congruence transform of the Uij matrix, so
    the signs are the Uij matrix's (Sylvester's law of inertia), but the values
    are only right in Cartesian axes (an isotropic hexagonal U has U12 = U11/2).
    """
    unit_cell = gemmi.UnitCell(*cell)
    orth = np.array(unit_cell.orth.mat.tolist())
    reciprocal = unit_cell.reciprocal()
    n = np.diag([reciprocal.a, reciprocal.b, reciprocal.c])
    return np.linalg.eigvalsh(orth @ n @ _uij_matrix(u) @ n @ orth.T)


def _same(got: float, want: float) -> bool:
    """Equal to floating-point precision (``ADJUSTMENT_REPORT_TOL``, relative above 1)."""
    return abs(got - want) <= ADJUSTMENT_REPORT_TOL * max(1.0, abs(want))


def _within(got: float, want: float, tol: float) -> bool:
    """``got`` states ``want`` within ``tol`` (never tighter than floating-point precision)."""
    return _same(got, want) or abs(got - want) <= tol


def _has_decimal_form(value: Fraction) -> bool:
    """True when ``value`` has a finite decimal form (1/2, 1/4, 3/8), False for 1/3, 1/6, 1/12.

    Symmetry only produces denominators 1, 2, 3, 4, 6, 8, 12 for fixed
    coordinates (all settings, every distinct special site), so "no decimal
    form" means "a third".
    """
    d = value.denominator
    for p in (2, 5):
        while d % p == 0:
            d //= p
    return d == 1


@dataclass(frozen=True)
class _Family:
    """How closely a recipe must state the derived values of one kind of parameter (A121, A123).

    ``fixed(name, exact)`` and ``member(name, derived)`` give the tolerance for a
    symmetry-fixed parameter and for a tied member (0 = floating-point precision).
    """

    fixed: Callable[[str, Fraction], float]
    member: Callable[[str, float], float]


#: Coordinates: a fixed one with a decimal form exactly, a third to 6 decimals (A73, A120);
#: a coupled one within 6 decimals of the value derived from its group's first member (A121).
_COORDINATES = _Family(fixed=lambda _n, exact: 0.0 if _has_decimal_form(exact) else SPECIAL_POSITION_TOL,
                       member=lambda _n, _v: SPECIAL_POSITION_TOL)
#: Uij: a fixed one is exactly 0; a coupled one within 1e-6 A^2 (A78, A121).
_UIJ = _Family(fixed=lambda _n, _exact: 0.0, member=lambda _n, _v: UIJ_TOL)


def _cell_tol(name: str, value) -> float:
    return CELL_TOL * abs(float(value)) if name in ("a", "b", "c") else CELL_TOL


#: Cell: within CELL_TOL, relative on lengths, degrees on angles (A77, A123).
_CELL = _Family(fixed=_cell_tol, member=_cell_tol)


def _fixed_cell_angle(ties, name: str) -> Fraction:
    """The exact value of a symmetry-fixed cell angle: 120 for gamma on hexagonal axes, else 90."""
    return Fraction(120) if name == "gamma" and ties.crystal_system in ("hexagonal", "trigonal") else Fraction(90)


def _derive(ties: Ties, stated: dict, exact, family: _Family) -> tuple[dict, dict]:
    """``(derived, write)`` for one parameter set (a cell, a site's x/y/z, or its Uij; A121).

    Each tie group's first member is the independent parameter and keeps its
    stated value. Every other value is derived in exact rational arithmetic:
    a fixed one is its exact value ``exact(name)``, a member ``k * rep + c``.
    ``derived`` maps every name to the float nearest its derived value (what
    the model holds); ``write`` maps the names stated beyond ``family``'s
    tolerance to ``(derived, tolerance)``.
    """
    targets: dict[str, tuple[Fraction, float]] = {}
    for name in ties.fixed:
        value = Fraction(exact(name))
        targets[name] = (value, family.fixed(name, value))
    for group in ties.groups:
        rep = Fraction(stated[group.members[0]])
        targets[group.members[0]] = (rep, 0.0)
        for name, k, c in zip(group.members[1:], group.coefficients[1:], group.offsets[1:]):
            value = k * rep + c
            targets[name] = (value, family.member(name, float(value)))
    derived, write = {}, {}
    for name, value in stated.items():
        target, tol = targets[name]
        derived[name] = float(target)
        if not _within(value, derived[name], tol):
            write[name] = (derived[name], tol)
    return derived, write


def _note_derived(notes: list, prefix: str, params: dict, derived: dict, ties: Ties, exact, context: str) -> None:
    """Append one ``symmetry_value_derived`` note (level ``info``) per value the model holds in its exact
    symmetry-derived form instead of as stated (P-34).

    Only values that actually moved are reported: a value stated exactly (``0.25`` for a quarter)
    is held as stated and gets no note. The note is therefore *evidence* that a site is special
    or a parameter tied, never a statement of it; the symmetry analysis itself
    (:meth:`Phase.site`) is the reliable source for that.
    """
    for name, param in params.items():
        if derived[name] == param.value:
            continue
        notes.append(StructuredWarning(
            code="symmetry_value_derived",
            message=(f"{context}: {name} stated {param.value!r} is held as {derived[name]!r}, the exact "
                     f"value its symmetry relation requires ({_ties_text(ties, exact, only=[name])}); "
                     f"the recipe is unchanged; this is evidence of a symmetry relation, not a statement "
                     f"of one (an exactly stated value is held as stated and gets no note)"),
            field_path=f"{prefix}.{name}",
            level="info",
        ))


def _updated(params: dict, derived: dict, bounds: dict) -> dict:
    """``model_copy`` updates for the parameters whose value or bounds the model holds derived."""
    updates = {}
    for name, param in params.items():
        update = {} if derived[name] == param.value else {"value": derived[name]}
        if name in bounds and bounds[name] != (param.min, param.max):
            update["min"], update["max"] = bounds[name]
        if update:
            updates[name] = param.model_copy(update=update)
    return updates


def _ties_text(ties: Ties, exact, only=None) -> str:
    """The symmetry relations of a parameter set, e.g. ``"x = 1/3, y = 2/3"``, ``"y = 2x"``, ``"b = a"``."""
    parts = [f"{name} = {exact(name)}" for name in ties.fixed]
    parts += [g.relation_text(m) for g in ties.groups for m in g.members[1:]]
    if only is not None:
        parts = [p for p in parts if p.split(" = ")[0] in only]
    return ", ".join(parts)


def _fmt_value(value: float, tol: float) -> str:
    """A value to write: exactly when its decimal form is short (``0.5``, ``0.0061735``), else the
    fewest decimals (at least 6) that state it within ``tol`` (``0.333333 (to at least 6 decimals)``)."""
    text = repr(value)
    if "e" not in text and len(text.partition(".")[2]) <= 8:
        return text
    for n in range(6, 17):
        rounded = f"{value:.{n}f}"
        if abs(float(rounded) - value) <= tol / 10:
            return f"{rounded} (to at least {n} decimals)"
    return text


def _write_text(write: dict) -> str:
    return ", ".join(f"{name} = {_fmt_value(value, tol)}" for name, (value, tol) in write.items())


def _fmt_bounds(lo: Optional[float], hi: Optional[float], tol: Optional[float] = None) -> str:
    """``[min, max]`` as stated (``repr``), or, with ``tol``, as values to write (:func:`_fmt_value`)."""
    texts = ["null" if v is None else repr(v) if tol is None else _fmt_value(v, tol) for v in (lo, hi)]
    values, notes = zip(*(t.partition(" (")[::2] for t in texts))
    note = max(notes)
    return f"[{', '.join(values)}]" + (f" ({note}" if note else "")


_HOW_MANY = {2: "both", 3: "all three"}


def _tie_rules(params: dict, ties: Ties, family: _Family, context: str,
               fixed_value) -> tuple[list[tuple[str, str]], dict]:
    """The flag and bound rules of one parameter set (cell, a site's x/y/z, or its Uij).

    - **F2** (A95): a symmetry-fixed parameter has refine flag false.
    - **A106**: a symmetry-fixed parameter has no bounds (min and max null).
    - **F1** (A95): the members of a tie group carry the same flag. The error is
      reported at every member whose flag differs from the group's first
      member, naming the whole group (review N1).
    - **F4** (A98, A121): with bounds, each member's bounds are derived from the
      first member's like its value: ``member = k*rep + c`` maps ``[min, max]``
      to ``[k*min + c, k*max + c]``, swapped for k < 0; a null side stays null on
      the matching side. Stated within ``family``'s member tolerance, they are
      read as the derived bounds; otherwise an error gives them.
    - **F3**: different groups are independent (nothing to check).

    Returns ``([(name, message)], {name: (min, max) derived})``.
    """
    errors: list[tuple[str, str]] = []
    bounds: dict[str, tuple] = {}
    for name in ties.fixed:
        param = params[name]
        if param.refine_flag:
            errors.append((name, f"{context}: {name} is fixed by symmetry (= {fixed_value(name)}); "
                                 "set its refine flag to false"))
        if isinstance(param, BoundedRefinableParameter) and (param.min is not None or param.max is not None):
            errors.append((name, f"{context}: {name} is fixed by symmetry (= {fixed_value(name)}); "
                                 "give it no bounds (min and max null)"))
    for group in ties.groups:
        if len(group.members) < 2:
            continue
        rep = params[group.members[0]]
        flag_words = _HOW_MANY.get(len(group.members), f"all {len(group.members)}")
        relations = group.relations_text()
        for name in group.members[1:]:
            if params[name].refine_flag != rep.refine_flag:
                errors.append((name, f"{context}: {', '.join(group.members)} are one parameter"
                                     f"{f' ({relations})' if relations else ''}; "
                                     f"set the same refine flag on {flag_words}"))
        if not isinstance(rep, BoundedRefinableParameter):
            continue
        for name in group.members[1:]:
            param = params[name]
            k, c = group.relation(name)
            lo, hi = (None if v is None else float(k * Fraction(v) + c) for v in (rep.min, rep.max))
            if k < 0:
                lo, hi = hi, lo
            tol = family.member(name, max(abs(v) for v in (lo, hi, 0.0) if v is not None))
            if all((got is None) == (want is None) and (got is None or _within(got, want, tol))
                   for got, want in ((param.min, lo), (param.max, hi))):
                bounds[name] = (lo, hi)
                continue
            errors.append((name, f"{context}: the bounds of {name} must follow "
                                 f"{group.relation_text(name)} from the bounds of {group.members[0]} "
                                 f"{_fmt_bounds(rep.min, rep.max)}: write {_fmt_bounds(lo, hi, tol)}, "
                                 f"not {_fmt_bounds(param.min, param.max)}"))
    return errors, bounds


# --- top-level recipe frame (A1, A18, A21, A40) ------------------------------


def _check_metadata(v: Optional[dict]) -> Optional[dict]:
    if v is None:
        return v
    try:
        text = json.dumps(v, allow_nan=False, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"metadata must be JSON-serializable: {exc}") from None
    size = len(text.encode("utf-8"))
    if size > METADATA_MAX_BYTES:
        raise ValueError(
            f"metadata is {size} bytes as JSON; the limit is {METADATA_MAX_BYTES} "
            "(schema_core.METADATA_MAX_BYTES)"
        )
    return v


class CoreRecipe(CoreModel):
    """The core-owned top level of every recipe; engine schemas subclass it.

    An engine schema narrows ``schema_name`` to its own names, types ``payload``,
    and checks ``engine_schema_version`` against its declarations
    (:mod:`powderline.compat`). ``metadata`` is never interpreted: it is checked
    for JSON-serializability and size, and echoed into results (A21, A64).
    """

    schema_name: str = Field(pattern=SCHEMA_NAME_PATTERN,
                             description='Engine and workflow, e.g. "gsasii.rietveld"')
    core_schema_version: str = Field(description="Core schema version the recipe is written against")
    engine_schema_version: str = Field(description="Engine schema version the recipe is written against")
    metadata: Optional[dict[str, Any]] = Field(
        default=None, description="Free-form, JSON-serializable; echoed into results")
    payload: Any = Field(description="Engine-specific; typed by the engine schema")

    @field_validator("core_schema_version")
    @classmethod
    def _core_version(cls, v: str) -> str:
        check_core_schema_version(v)
        return v

    @field_validator("engine_schema_version")
    @classmethod
    def _engine_version(cls, v: str) -> str:
        parse_version("engine_schema_version", v)
        return v

    @field_validator("metadata")
    @classmethod
    def _metadata(cls, v):
        return _check_metadata(v)


# --- engine schema building blocks (P-37) -------------------------------------
# What every engine schema needs and none should write twice: the pieces a
# gateway's ``schema.py`` composes its payload rules and recipe classes from.


def refined_flags(obj: Any, loc: tuple = ()) -> list[tuple]:
    """Locations of every refine flag set to true in a validated model tree (A88)."""
    if isinstance(obj, (RefinableParameter, BoundedRefinableParameter)):
        return [loc] if obj.refine_flag else []
    if isinstance(obj, ChebyshevBackground):
        return [loc + ("refine_flag",)] if obj.refine_flag else []
    if isinstance(obj, CoreModel):
        return [hit for name in type(obj).model_fields for hit in refined_flags(getattr(obj, name), loc + (name,))]
    if isinstance(obj, dict):
        return [hit for k, v in obj.items() for hit in refined_flags(v, loc + (k,))]
    if isinstance(obj, list):
        return [hit for i, v in enumerate(obj) for hit in refined_flags(v, loc + (i,))]
    return []


def custom_error(kind: str, message: str, loc: tuple, input_: Any, **ctx) -> InitErrorDetails:
    """One located problem for :func:`raise_problems` (pydantic's own error shape, A70)."""
    return InitErrorDetails(type=PydanticCustomError(kind, message, ctx or None), loc=loc, input=input_)


def raise_problems(title: str, problems: list) -> None:
    """Raise every collected problem at once as one ``ValidationError`` titled ``title``; nothing if none."""
    if problems:
        raise ValidationError.from_exception_data(title, problems)


def omit_absent(data: dict, model: BaseModel, names: tuple) -> dict:
    """Drop from a dump the optional blocks the recipe left out (held as ``None``; A96)."""
    for name in names:
        if getattr(model, name) is None:
            data.pop(name, None)
    return data


def unique_phase_names(v: dict) -> dict:
    """``field_validator("phases")`` body: names unique ignoring case."""
    check_names_unique_ignoring_case(v, "phase")
    return v


def fit_window(fit_range: Optional[FitRange], xrd_data: XRDData) -> tuple:
    """The fit window as stated: the data's ends, each overridden by a stated limit (open ends stay).

    Not :func:`fit_limits_on_data`, which snaps the limits to data points.
    """
    lo, hi = xrd_data.tth[0], xrd_data.tth[-1]
    if fit_range is not None:
        lo = lo if fit_range.min is None else fit_range.min
        hi = hi if fit_range.max is None else fit_range.max
    return lo, hi


def fit_range_problems(fit_range: Optional[FitRange], xrd_data: XRDData) -> list:
    """:func:`check_fit_range_within_data` as a located problem at ``fit_range``."""
    try:
        check_fit_range_within_data(fit_range, xrd_data)
    except ValueError as exc:
        return [custom_error("fit_range", str(exc), ("fit_range",),
                             None if fit_range is None else fit_range.model_dump())]
    return []


def outside_window_problems(params: Sequence, window: tuple, loc: Callable, what: str) -> list:
    """Peak positions outside the fit window (A86, A126).

    ``params`` are parameter models (``.value``), ``window`` is :func:`fit_window`,
    ``loc(i)`` the location of the i-th position.
    """
    lo, hi = window
    return [custom_error("outside_fit_window", "{what} position {value} is outside the fit window [{lo}, {hi}] "
                         "(fit_range; open ends are the data limits)", loc(i), p.model_dump(),
                         what=what, value=p.value, lo=lo, hi=hi)
            for i, p in enumerate(params) if not lo <= p.value <= hi]


def refined_flag_problems(model: BaseModel, message: str) -> list:
    """A simulation refines nothing (A88): one ``simulation_refines`` problem per refine flag set."""
    return [custom_error("simulation_refines", message, loc, True) for loc in refined_flags(model)]


class EngineRecipe(CoreRecipe):
    """The top level of an engine's recipes: the core frame plus the engine's version check.

    A subclass states ``gateway_name`` and ``schema_declarations`` (the module's
    ``DECLARATIONS``), narrows ``schema_name`` and types ``payload``. Both are
    class variables: they add nothing to the JSON Schema.
    """

    gateway_name: ClassVar[str]
    schema_declarations: ClassVar[Mapping[str, Any]]

    @model_validator(mode="after")
    def _versions(self) -> "EngineRecipe":
        from powderline.compat import check_engine_schema_version  # compat imports this module

        cls = type(self)
        if not hasattr(cls, "gateway_name") or not hasattr(cls, "schema_declarations"):
            raise TypeError(f"{cls.__name__} must set gateway_name and schema_declarations")
        check_engine_schema_version(self.core_schema_version, self.engine_schema_version,
                                    gateway=cls.gateway_name, capabilities=cls.schema_declarations)
        return self


def recipe_validator(models: Mapping[str, type], *, engine: str, title: str) -> Callable:
    """The ``validate_recipe`` of an engine: ``schema_name`` -> model (A50, idempotent).

    A dict is dispatched on ``schema_name`` (an unknown one is reported at
    ``schema_name``); a model is returned as is; anything else is validated by
    the union of ``models`` so that pydantic reports it.
    """
    kinds = tuple(models.values())
    if len(kinds) == 1:
        adapter = TypeAdapter(kinds[0])
    else:
        adapter = TypeAdapter(Annotated[Union[kinds], Field(discriminator="schema_name")], config={"title": title})
    article = "an" if engine[:1] in "aeiou" else "a"
    names = ", ".join(models)

    def validate_recipe(recipe):
        if isinstance(recipe, kinds):
            return recipe
        if not isinstance(recipe, dict):
            return adapter.validate_python(recipe)
        model = models.get(recipe.get("schema_name"))
        if model is None:
            raise ValidationError.from_exception_data(title, [custom_error(
                "schema_name", "schema_name '{name}' is not " + article + " {engine} workflow; expected one of "
                "{names}", ("schema_name",), recipe.get("schema_name"), name=recipe.get("schema_name"),
                engine=engine, names=names)])
        return model.model_validate(recipe)

    validate_recipe.__doc__ = (f"Validate {article} ``{engine}.*`` recipe (dict or model); return the model "
                               "(idempotent).")
    return validate_recipe


# --- warnings (A23, A115) ----------------------------------------------------


def collect_warnings(model: BaseModel, path: str = "") -> list[StructuredWarning]:
    """Every structured warning in a validated model tree, with full field paths.

    Each model in the tree that has a ``warnings()`` method (:meth:`Phase.warnings`,
    an engine payload's documented defaults) contributes its warnings, whose
    paths are relative to it; ``path`` names ``model`` itself. Called on a
    validated recipe, a phase warning reads ``payload.phases.<name>.atoms.<label>.Uaniso``.

    Collect once, from the model validated from the user's recipe, and carry the
    list to the result: a warning about a default applied reflects what the
    recipe left out, which a dump of the model (stating the default) no longer
    shows.
    """
    found: list[StructuredWarning] = []

    def join(prefix: str, name) -> str:
        return f"{prefix}.{name}" if prefix else str(name)

    def visit(obj: Any, prefix: str) -> None:
        if isinstance(obj, BaseModel):
            own = getattr(obj, "warnings", None)
            if callable(own):
                for w in own():
                    rel = w["field_path"]
                    entry = StructuredWarning(code=w["code"], message=w["message"],
                                              field_path=join(prefix, rel) if rel else (prefix or None))
                    if "level" in w:  # absent means "warning" (P-34); keep it absent
                        entry["level"] = w["level"]
                    found.append(entry)
            for name in type(obj).model_fields:
                visit(getattr(obj, name), join(prefix, name))
        elif isinstance(obj, dict):
            for key, value in obj.items():
                visit(value, join(prefix, key))
        elif isinstance(obj, (list, tuple)):
            for i, value in enumerate(obj):
                visit(value, join(prefix, i))

    visit(model, path)
    return found


# --- refined-parameter count (A41, A45, A94) ----------------------------------


def parameters_requested(recipe) -> int:
    """Independently refined parameters a validated recipe asks for (``engine_details``, A45).

    One per refine flag, except that a refined symmetry tie group (cell, atom
    coordinates, Uij) counts once: an engine emits one parameter per group
    (A94). A refined core Chebyshev background counts its coefficients. Works for
    both parameter shapes (``[value, flag]`` and ``[value, flag, min, max]``), so
    every engine gateway reports it the same way (re/05 D12).
    """
    count = 0

    def walk(obj) -> None:
        nonlocal count
        if isinstance(obj, (RefinableParameter, BoundedRefinableParameter)):
            count += obj.refine_flag
        elif isinstance(obj, ChebyshevBackground):
            count += obj.num_coefficients if obj.refine_flag else 0
        elif isinstance(obj, dict):
            for v in obj.values():
                walk(v)
        elif isinstance(obj, list):
            for v in obj:
                walk(v)
        elif isinstance(obj, BaseModel):
            for name in type(obj).model_fields:
                walk(getattr(obj, name))
            if isinstance(obj, Phase):  # a refined tie group is one engine parameter
                tied = [(obj.unit_cell, g.members) for g in cell_tie_groups(obj.space_group).groups]
                for atom in obj.atoms.values():
                    ties = coupling_groups(obj.space_group, (atom.x.value, atom.y.value, atom.z.value))
                    tied += [(atom, g.members) for g in ties.xyz.groups]
                    if atom.Uaniso is not None:
                        tied += [(atom.Uaniso, g.members) for g in ties.uij.groups]
                for holder, members in tied:
                    refined = sum(getattr(holder, m).refine_flag for m in members)
                    count -= max(refined - 1, 0)

    walk(recipe.payload)
    return count
