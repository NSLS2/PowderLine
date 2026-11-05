"""The output recipe (KI-04, P-43): every step emits the next step's input.

A result carries ``output_recipe`` -- a complete recipe of the same ``schema_name``
as the input, *resolved*: the engine's refined values written back at their recipe
paths, symmetry-derived values in their exact (held) form, gateway defaults stated,
the user's flags, bounds, controls and data unchanged -- together with
``output_recipe_valid`` and ``parameter_dispositions`` (one row per refinable
leaf: value, ESD, how the value came about, whether it ended at a limit).

Engine-free. The gateways supply the engine-specific part: which recipe path each
engine parameter stands for and what value it ended with (``refined``); core does
the rest here: tie propagation (``member = k * rep + c`` from
:func:`powderline.symmetry.cell_tie_groups` / :func:`~powderline.symmetry.coupling_groups`),
the dump, the provenance block, re-validation through the gateway's own schema,
and the **multiplicity invariant**: validation alone accepts a half-updated tie
as a general position of a different multiplicity, so every atom must keep the
multiplicity it had in the input or the output is not valid.

Validity never hides anything: the output recipe is always built and written;
``output_recipe_valid`` is false and the warning ``output_recipe_not_valid`` lists
why (an engine returned a value the schema refuses -- a negative Uiso under a
bounded schema -- or a tie disagreement beyond tolerance).
"""
from __future__ import annotations

import copy
import datetime as _dt
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Optional

import pandas as pd

from powderline import reports
from powderline.exceptions import StructuredWarning
from powderline.schema_core import (
    BoundedRefinableParameter,
    ChebyshevBackground,
    CoreModel,
    RefinableParameter,
    collect_warnings,
)
from powderline.symmetry import CELL_TOL, SPECIAL_POSITION_TOL, UIJ_TOL, cell_tie_groups, coupling_groups

#: How a value in the output recipe came about, in precedence order (the first that applies wins).
DISPOSITIONS = ("default_applied", "held_by_symmetry", "held_by_user", "requested_not_varied", "varied")
#: Columns of ``parameter_dispositions`` and ``parameter_dispositions.csv`` (:data:`powderline.reports.DISPOSITION_COLUMNS`).
DISPOSITION_COLUMNS = reports.DISPOSITION_COLUMNS
OUTPUT_RECIPE_FILE = "output_recipe.json"
DISPOSITIONS_FILE = "parameter_dispositions.csv"
PROVENANCE_KEY = "powderline_provenance"


def engine_of(schema_name: str) -> str:
    """The engine a ``<engine>.<workflow>`` schema name names (the gateway name: ``gsasii``, ``topas``, ...)."""
    return str(schema_name).split(".", 1)[0]

_CELL = ("a", "b", "c", "alpha", "beta", "gamma")
_XYZ = ("x", "y", "z")
_UIJ = ("U11", "U22", "U33", "U12", "U13", "U23")


@dataclass(frozen=True)
class ParameterPath:
    """One refinable leaf of a recipe and what symmetry says about it."""

    path: str                      # dotted recipe path, list indices as ".N"
    loc: tuple                     # the same as a tuple of keys / indices
    value: float
    refine_flag: bool
    bounds: Optional[tuple]        # (min, max) for a bounded parameter, else None
    tie: str                       # "free" | "representative" | "member" | "fixed"
    relation: Optional[tuple]      # (k, c, representative_path) when tie == "member"
    default_applied: bool
    kind: str = "parameter"        # "parameter" ([value, flag, ...]) or "coefficient" (a Chebyshev float)


@dataclass
class OutputBundle:
    """What :func:`build_output` returns."""

    recipe: dict
    dispositions: list = field(default_factory=list)
    valid: bool = True
    problems: list = field(default_factory=list)


def _dotted(loc: tuple) -> str:
    return ".".join(str(x) for x in loc)


def _leaves(obj: Any, loc: tuple = ()) -> list:
    """``(loc, value, flag, bounds, kind)`` of every refinable leaf, in model order (the walk of ``refined_flags``)."""
    if isinstance(obj, RefinableParameter):
        return [(loc, obj.value, obj.refine_flag, None, "parameter")]
    if isinstance(obj, BoundedRefinableParameter):
        return [(loc, obj.value, obj.refine_flag, (obj.min, obj.max), "parameter")]
    if isinstance(obj, ChebyshevBackground):
        return [(loc + ("coefficients", i), c, obj.refine_flag, None, "coefficient") for i, c in enumerate(obj.coefficients)]
    if isinstance(obj, CoreModel):
        return [hit for name in type(obj).model_fields for hit in _leaves(getattr(obj, name), loc + (name,))]
    if isinstance(obj, dict):
        return [hit for k, v in obj.items() for hit in _leaves(v, loc + (k,))]
    if isinstance(obj, list):
        return [hit for i, v in enumerate(obj) for hit in _leaves(v, loc + (i,))]
    return []


def _tie_table(model) -> dict:
    """``path -> (tie, relation)`` for every cell, coordinate and Uij parameter of every phase."""
    table: dict = {}
    phases = getattr(getattr(model, "payload", None), "phases", None)
    if not phases:
        return table

    def enter(prefix: str, ties, names: Iterable[str]) -> None:
        for name in names:
            group = ties.group_of(name)
            if name in ties.fixed or group is None:
                table[prefix + name] = ("fixed", None)
            elif group.members[0] == name:
                table[prefix + name] = ("representative" if len(group.members) > 1 else "free", None)
            else:
                k, c = group.relation(name)
                table[prefix + name] = ("member", (k, c, prefix + group.members[0]))

    for pname, phase in phases.items():
        base = f"payload.phases.{pname}."
        enter(base + "unit_cell.", cell_tie_groups(phase.space_group), _CELL)
        for label, atom in phase.atoms.items():
            site = coupling_groups(phase.space_group, (atom.x.value, atom.y.value, atom.z.value))
            enter(base + f"atoms.{label}.", site.xyz, _XYZ)
            if getattr(atom, "Uaniso", None) is not None:
                enter(base + f"atoms.{label}.Uaniso.", site.uij, _UIJ)
    return table


def _default_prefixes(model) -> list:
    """Field paths of the gateway defaults the recipe left out (``*_default_applied`` warnings)."""
    return [w["field_path"] for w in collect_warnings(model)
            if w["code"].endswith("_default_applied") and w.get("field_path")]


def parameter_paths(model) -> list:
    """Every refinable leaf of a validated recipe with its symmetry role and whether a default filled it."""
    ties = _tie_table(model)
    defaults = _default_prefixes(model)
    out = []
    for loc, value, flag, bounds, kind in _leaves(model):
        path = _dotted(loc)
        tie, relation = ties.get(path, ("free", None))
        out.append(ParameterPath(path=path, loc=loc, value=float(value), refine_flag=bool(flag), bounds=bounds,
                                 tie=tie, relation=relation,
                                 default_applied=any(path == d or path.startswith(d + ".") for d in defaults),
                                 kind=kind))
    return out


def _tolerance(path: str) -> float:
    if ".unit_cell." in path:
        return CELL_TOL
    if ".Uaniso." in path:
        return UIJ_TOL
    return SPECIAL_POSITION_TOL


def _set(dump: dict, pp: ParameterPath, value: float) -> None:
    node: Any = dump
    for key in pp.loc[:-1]:
        node = node[key]
    if pp.kind == "coefficient":
        node[pp.loc[-1]] = value
    else:
        node[pp.loc[-1]][0] = value


def _get(dump: dict, pp: ParameterPath) -> float:
    node: Any = dump
    for key in pp.loc:
        node = node[key]
    return node if pp.kind == "coefficient" else node[0]


def _validate(validator: Optional[Callable], recipe: dict):
    if validator is not None:
        return validator(recipe)
    from powderline.api import validate  # engine-free dispatch on schema_name; lazy: api imports nothing of ours

    return validate(recipe).recipe


def _multiplicities(model) -> dict:
    phases = getattr(getattr(model, "payload", None), "phases", None) or {}
    return {(pname, label): phase.site(label).multiplicity
            for pname, phase in phases.items() for label in phase.atoms}


def build_output(model, refined: Mapping[str, tuple], *, not_varied: Iterable[str] = (), at_limit: Iterable[str] = (),
                 parent_run_id: Optional[str] = None, validator: Optional[Callable] = None,
                 engine_version: Optional[str] = None) -> OutputBundle:
    """The output recipe and dispositions of a run.

    ``refined`` maps a recipe path to ``(value, esd)`` in recipe units -- what the engine ended with
    for the parameters it varied (a tie group's representative suffices; reported members are checked).
    ``not_varied``: flagged paths the engine did not vary; ``at_limit``: paths that ended on a limit.
    ``validator`` is the gateway's ``validate_recipe`` (default: :func:`powderline.api.validate`).
    ``engine_version`` is the engine version the run used, as the result's ``engine_details`` states it (TOPAS: the
    declared version; ``None`` for validate-only); it goes into the provenance block with the engine's name (A191).
    """
    paths = parameter_paths(model)
    by_path = {pp.path: pp for pp in paths}
    unknown = sorted(set(refined) - set(by_path))
    problems: list = [f"refined path not in the recipe: {p}" for p in unknown]
    refined = {p: v for p, v in refined.items() if p in by_path}

    dump = model.model_dump(mode="json")
    values = {pp.path: (float(refined[pp.path][0]) if pp.path in refined else pp.value) for pp in paths}
    for pp in paths:  # an engine may only move what the user let it vary (formatting noise is not a move)
        if pp.path in refined and not pp.refine_flag and \
                abs(values[pp.path] - pp.value) > max(_tolerance(pp.path), 1e-9 * abs(pp.value)):
            problems.append(f"{pp.path} is held (refine flag false) but the engine reports it changed "
                            f"{pp.value!r} -> {values[pp.path]!r}")

    # tie propagation: representatives first (from a reported member if the representative was not reported),
    # then every member from its representative; a reported member must agree within tolerance
    members_of: dict = {}
    for pp in paths:
        if pp.tie == "member":
            members_of.setdefault(pp.relation[2], []).append(pp)
    refined = dict(refined)
    not_varied, at_limit = set(not_varied), set(at_limit)
    for rep_path, members in members_of.items():
        if rep_path not in refined:
            reported = [m for m in members if m.path in refined]
            if reported:  # the engine freed a member instead (easydiffraction does): derive the representative,
                m0 = reported[0]  # which inherits the ESD (scaled by the relation) and the member's markers
                k, c, _ = m0.relation
                values[rep_path] = float((Fraction(values[m0.path]) - c) / k)
                esd = refined[m0.path][1]
                refined[rep_path] = (values[rep_path], None if esd is None else abs(esd / float(k)))
                if m0.path in not_varied:
                    not_varied.add(rep_path)
                if m0.path in at_limit:
                    at_limit.add(rep_path)
        for m in members:
            k, c, _ = m.relation
            expected = float(k * Fraction(values[rep_path]) + c)  # exact, as the schema derives it
            if m.path in refined and abs(values[m.path] - expected) > _tolerance(m.path):
                problems.append(f"{m.path} = {values[m.path]!r} disagrees with its symmetry tie "
                                f"({m.path.rsplit('.', 1)[1]} = {m.relation[0]} * {rep_path.rsplit('.', 1)[1]} + {m.relation[1]} "
                                f"= {expected!r})")
            values[m.path] = expected
    for pp in paths:
        if values[pp.path] != pp.value:
            _set(dump, pp, values[pp.path])

    # provenance: the one key PowderLine writes into the user's metadata (P-43 D7)
    from powderline import __version__

    meta = dump.get("metadata") or {}
    meta[PROVENANCE_KEY] = {"parent_run_id": parent_run_id, "schema_name": dump["schema_name"],
                            "engine": engine_of(dump["schema_name"]),
                            "engine_version": None if engine_version is None else str(engine_version),
                            "powderline_version": __version__,
                            "created": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")}
    dump["metadata"] = meta

    # validity: the gateway's own schema, silence on re-validation, and the multiplicity invariant
    try:
        again = _validate(validator, copy.deepcopy(dump))
    except Exception as exc:  # pydantic.ValidationError or a gateway's own error: reported, never raised
        errors = getattr(exc, "errors", None)
        if callable(errors):  # pydantic: every error with its location and message
            for err in errors():
                problems.append(f"{'.'.join(str(x) for x in err.get('loc', ()))}: {err.get('msg', '')}".strip(": "))
        else:
            text = str(exc).strip()
            problems.append(text.splitlines()[0] if text else type(exc).__name__)
    else:
        for w in collect_warnings(again):
            if w["code"] == "symmetry_value_derived" or w["code"].endswith("_default_applied"):
                problems.append(f"the output recipe would re-validate with {w['code']} at {w.get('field_path')}")
        before, after = _multiplicities(model), _multiplicities(again)
        for key, mult in before.items():
            if after.get(key) != mult:
                problems.append(f"atom {key[1]!r} of phase {key[0]!r} would change multiplicity "
                                f"{mult} -> {after.get(key)}: a symmetry tie was not kept")

    rows = []
    for pp in paths:
        if pp.default_applied:
            disposition = "default_applied"
        elif pp.tie in ("member", "fixed"):
            disposition = "held_by_symmetry"
        elif not pp.refine_flag:
            disposition = "held_by_user"
        elif pp.path in not_varied:
            disposition = "requested_not_varied"
        else:
            disposition = "varied"
        esd = refined[pp.path][1] if pp.path in refined else None
        rows.append({"path": pp.path, "value": values[pp.path], "esd": None if esd is None else float(esd),
                     "disposition": disposition, "at_limit": pp.path in at_limit})
    return OutputBundle(recipe=dump, dispositions=rows, valid=not problems, problems=problems)


def _not_valid_warning(problems: list) -> StructuredWarning:
    shown = "; ".join(problems[:5]) + (f"; and {len(problems) - 5} more" if len(problems) > 5 else "")
    return StructuredWarning(code="output_recipe_not_valid",
                             message=f"the output recipe does not validate as written ({shown}); it is still "
                                     "returned and written so you can see what the engine produced",
                             field_path=None)


def attach(result: dict, bundle: OutputBundle, output_dir: Optional[Path] = None) -> dict:
    """Put the bundle on an envelope (``output_recipe``, ``output_recipe_valid``, ``parameter_dispositions``, the
    warning when invalid) and, with ``output_dir``, write ``output_recipe.json`` and ``parameter_dispositions.csv``."""
    result["output_recipe"] = bundle.recipe
    result["output_recipe_valid"] = bool(bundle.valid)
    result["parameter_dispositions"] = pd.DataFrame(bundle.dispositions, columns=list(DISPOSITION_COLUMNS))
    if not bundle.valid:
        result.setdefault("warnings", []).append(_not_valid_warning(bundle.problems))
    if output_dir is not None:
        written = [reports.write_output_recipe(output_dir, bundle.recipe),
                   reports.write_parameter_dispositions(output_dir, bundle.dispositions)]
        files = result.setdefault("output_files", [])
        for path in written:
            if str(path) not in files:
                files.append(str(path))
    return result

