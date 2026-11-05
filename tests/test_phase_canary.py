"""Canary: core's must-fail recipes fail through every engine phase model (A122; re/03b PR review S2).

``Phase.__pydantic_init_subclass__`` rejects, when a class is defined, an engine subclass that could
replace, skip or rewrite core's validation. This is the behavioural check behind that structural guard:
each engine phase model must reject every core violation at the same location as core does, and must
hold the same values as core for a valid recipe (so no engine validator rewrites it, A115).

re/04-06 add each engine phase model to ``ENGINE_PHASES``, with the engine fields a valid phase needs;
``test_every_engine_phase_model_is_covered`` fails until they do.
"""

from __future__ import annotations

import importlib

import pytest

from pydantic import ValidationError

from powderline.schema_core import BoundedRefinableParameter, Phase, RefinableParameter

pytestmark = pytest.mark.core

#: ``(module, class name, parameter type, engine fields of a valid phase)`` of every engine phase model.
ENGINE_PHASES: list[tuple[str, str, type, dict]] = [
    ("powderline.gateways.gsasii.schema", "GsasiiPhase", RefinableParameter, {"scale": [1.0, False]}),
    ("powderline.gateways.topas.schema", "TopasPhase", BoundedRefinableParameter,
     {"scale": [1e-6, False, None, None]}),
    ("powderline.gateways.easydiffraction.schema", "EasydiffractionPhase", BoundedRefinableParameter,
     {"scale": [1e-6, False, None, None]}),
]


def _models():
    models = [(f"Phase[{p.__name__}]", Phase[p], p, {}) for p in (RefinableParameter, BoundedRefinableParameter)]
    for module, name, param, fields in ENGINE_PHASES:
        models.append((f"{module}.{name}", getattr(importlib.import_module(module), name), param, fields))
    return models


_MODELS = _models()


def _p(value, flag=False, bounded=False, lo=None, hi=None):
    return [value, flag, lo, hi] if bounded else [value, flag]


def _phase(bounded: bool, sg="P m -3 m", cell=(4.0, 4.0, 4.0, 90.0, 90.0, 90.0), atoms=None) -> dict:
    def atom(xyz, element="O"):
        return {"element": element, **{k: _p(v, bounded=bounded) for k, v in zip("xyz", xyz)},
                "occupancy": _p(1.0, bounded=bounded), "ADP": "Uiso", "Uiso": _p(0.01, bounded=bounded)}

    atoms = atoms or {"A": (0.0, 0.0, 0.0), "B": (0.5, 0.2, 0.2)}
    return {"space_group": sg,
            "unit_cell": {k: _p(v, bounded=bounded) for k, v in zip(("a", "b", "c", "alpha", "beta", "gamma"), cell)},
            "atoms": {label: atom(xyz) for label, xyz in atoms.items()}}


def _break(case: str, d: dict, bounded: bool) -> tuple:
    """Make ``d`` violate one core rule; return the location core reports it at."""
    if case == "space group not canonical (A105)":
        d["space_group"] = "Pm-3m"
        return ("space_group",)
    if case == "fixed parameter refined (F2)":
        d["unit_cell"]["alpha"][1] = True
        return ("unit_cell", "alpha")
    if case == "tied flags differ (F1)":
        d["unit_cell"]["a"][1] = True
        return ("unit_cell", "b")
    if case == "decimal special position not exact (A120)":
        d["atoms"]["B"]["x"][0] = 0.4999999
        return ("atoms", "B")
    if case == "ambiguous position (A73)":
        d["atoms"]["B"]["z"][0] = 0.2003
        return ("atoms", "B")
    if case == "Multiplicity wrong":
        d["atoms"]["A"]["Multiplicity"] = 2
        return ("atoms", "A", "Multiplicity")
    if case == "fixed Uij not exactly 0 (A121)":
        del d["atoms"]["A"]["Uiso"]
        d["atoms"]["A"]["ADP"] = "Uaniso"
        d["atoms"]["A"]["Uaniso"] = {k: _p(v, bounded=bounded) for k, v in
                                     zip(("U11", "U22", "U33", "U12", "U13", "U23"), (0.01, 0.01, 0.01, 1e-9, 0, 0))}
        return ("atoms", "A", "Uaniso")
    if case == "atom labels differ only in case (A112)":
        d["atoms"]["a"] = d["atoms"].pop("B")
        return ("atoms", "a")
    if case == "fixed parameter has bounds (A106)":
        d["unit_cell"]["alpha"][2:] = [89.0, 91.0]
        return ("unit_cell", "alpha")
    if case == "tied bounds differ (F4)":
        d["unit_cell"]["a"][2:] = [3.9, 4.1]
        return ("unit_cell", "b")
    raise AssertionError(case)  # pragma: no cover


_CASES = ["space group not canonical (A105)", "fixed parameter refined (F2)", "tied flags differ (F1)",
          "decimal special position not exact (A120)", "ambiguous position (A73)", "Multiplicity wrong",
          "fixed Uij not exactly 0 (A121)", "atom labels differ only in case (A112)"]
_BOUNDED_CASES = ["fixed parameter has bounds (A106)", "tied bounds differ (F4)"]


@pytest.mark.parametrize("label, model, param, fields", _MODELS, ids=[m[0] for m in _MODELS])
def test_core_rules_hold_in_every_phase_model(label, model, param, fields):
    bounded = param is BoundedRefinableParameter
    Phase.__dict__["__pydantic_init_subclass__"].__func__(model)  # the structural guard, whatever overrides it
    for case in _CASES + (_BOUNDED_CASES if bounded else []):
        d = {**_phase(bounded), **fields}
        loc = _break(case, d, bounded)
        with pytest.raises(ValidationError) as exc_info:
            model.model_validate(d)
        assert loc in [e["loc"] for e in exc_info.value.errors()], f"{label}: {case}"


@pytest.mark.parametrize("label, model, param, fields", _MODELS, ids=[m[0] for m in _MODELS])
def test_every_phase_model_holds_cores_values(label, model, param, fields):
    """Thirds and derived members read the same in every model (A120, A121): no engine rewrites them."""
    bounded = param is BoundedRefinableParameter
    d = _phase(bounded, "P 63/m m c", (3.2, 3.2, 5.2, 90.0, 90.0, 120.0),
               {"A": (0.333333, 0.666667, 0.25), "B": (0.833333, 0.666667, 0.25)})
    core = Phase[param].model_validate(d).model_dump()
    engine = model.model_validate({**d, **fields}).model_dump()
    assert {k: engine[k] for k in core} == core


def _subclasses(cls):
    for sub in cls.__subclasses__():
        yield sub
        yield from _subclasses(sub)


def test_every_engine_phase_model_is_covered():
    """Every concrete phase model in PowderLine's own modules is in ENGINE_PHASES."""
    covered = {model for _label, model, _param, _fields in _MODELS}
    found = {cls for cls in _subclasses(Phase)
             if cls.__module__.startswith("powderline.")
             and not cls.__pydantic_generic_metadata__["parameters"]
             and cls.__pydantic_generic_metadata__["origin"] is not Phase}
    assert found <= covered, sorted(f"{c.__module__}.{c.__qualname__}" for c in found - covered)
