"""The core building blocks an engine schema is assembled from (P-37).

Each gateway's ``schema.py`` composes its payload rules and recipe classes
from these; they are tested here on tiny local models, independent of any
engine schema.
"""
from typing import ClassVar, Literal, Optional

import pytest
from pydantic import Field, ValidationError, field_validator, model_serializer

from powderline.compat import DECLARATION_KEYS, schema_declarations
from powderline.schema_core import (
    BoundedRefinableParameter,
    CoreModel,
    CoreName,
    CoreRecipe,
    EngineRecipe,
    FitRange,
    RefinableParameter,
    XRDData,
    absent_not_null,
    custom_error,
    fit_range_problems,
    fit_window,
    omit_absent,
    outside_window_problems,
    raise_problems,
    recipe_validator,
    refined_flag_problems,
    refined_flags,
    unique_phase_names,
    unit_schema,
)

pytestmark = pytest.mark.core

DECL = schema_declarations(engine_schema_version="0.1.0", supported_engine_schemas="==0.1.0",
                           requires_core_schema="==0.1.0")


def _data(n=5):
    return XRDData(tth=[10.0 + i for i in range(n)], Itth=[1.0] * n, Itth_weights=[1.0] * n)


class _Inner(CoreModel):
    scale: RefinableParameter
    note: Optional[str] = None
    _not_null = field_validator("note", mode="before")(absent_not_null)

    @model_serializer(mode="wrap")
    def _omit(self, handler):
        return omit_absent(handler(self), self, ("note",))


class _Payload(CoreModel):
    xrd_data: XRDData
    fit_range: Optional[FitRange] = None
    inner: _Inner
    phases: dict[CoreName, _Inner] = Field(default_factory=dict)
    _phase_names = field_validator("phases")(unique_phase_names)


class _Recipe(EngineRecipe):
    gateway_name: ClassVar[str] = "demo"
    schema_declarations: ClassVar[dict] = DECL
    schema_name: Literal["demo.one"]
    payload: _Payload


class _Other(EngineRecipe):
    gateway_name: ClassVar[str] = "demo"
    schema_declarations: ClassVar[dict] = DECL
    schema_name: Literal["demo.two"]
    payload: _Payload


def _recipe(name="demo.one", **over):
    r = {"schema_name": name, "core_schema_version": "0.1.0", "engine_schema_version": "0.1.0",
         "payload": {"xrd_data": _data().model_dump(), "inner": {"scale": [1.0, True]}}}
    r.update(over)
    return r


def test_unit_schema():
    assert unit_schema("degree") == {"unit": "degree"}


def test_absent_not_null_refuses_explicit_null_and_passes_values():
    with pytest.raises(ValidationError, match="note must not be null; leave it out instead"):
        _Inner.model_validate({"scale": [1.0, False], "note": None})
    assert _Inner.model_validate({"scale": [1.0, False], "note": "x"}).note == "x"


def test_omit_absent_drops_left_out_keys_only():
    assert _Inner.model_validate({"scale": [1.0, False]}).model_dump() == {"scale": [1.0, False]}
    assert "note" in _Inner.model_validate({"scale": [1.0, False], "note": "x"}).model_dump()


def test_refined_flags_both_parameter_shapes():
    class T(CoreModel):
        a: RefinableParameter
        b: BoundedRefinableParameter
        more: list[RefinableParameter]
    t = T.model_validate({"a": [1.0, True], "b": [1.0, True, None, None], "more": [[1.0, False], [2.0, True]]})
    assert refined_flags(t) == [("a",), ("b",), ("more", 1)]
    assert refined_flags(t, ("payload",)) == [("payload", "a"), ("payload", "b"), ("payload", "more", 1)]


def test_custom_error_and_raise_problems():
    err = custom_error("kind", "value {v} bad", ("payload", "x"), 3, v=3)
    assert err["loc"] == ("payload", "x") and err["input"] == 3
    with pytest.raises(ValidationError) as exc:
        raise_problems("Demo", [err])
    (only,) = exc.value.errors()
    assert (only["type"], only["loc"], only["msg"]) == ("kind", ("payload", "x"), "value 3 bad")
    raise_problems("Demo", [])  # nothing to raise


def test_custom_error_without_context():
    err = custom_error("kind", "plain", ("x",), None)
    assert err["type"].context is None


def test_unique_phase_names_ignores_case():
    with pytest.raises(ValidationError, match="phase"):
        _Payload.model_validate({"xrd_data": _data().model_dump(), "inner": {"scale": [1.0, False]},
                                 "phases": {"A": {"scale": [1.0, False]}, "a": {"scale": [1.0, False]}}})


def test_fit_window_is_data_ends_overridden_by_stated_limits():
    d = _data()
    assert fit_window(None, d) == (10.0, 14.0)
    assert fit_window(FitRange.model_validate([11.0, None]), d) == (11.0, 14.0)
    assert fit_window(FitRange.model_validate([None, 12.5]), d) == (10.0, 12.5)


def test_fit_range_problems_empty_when_inside_and_one_when_outside():
    d = _data()
    assert fit_range_problems(FitRange.model_validate([11.0, 13.0]), d) == []
    far = FitRange.model_validate([100.0, 200.0])
    (p,) = fit_range_problems(far, d)
    assert p["loc"] == ("fit_range",) and p["input"] == far.model_dump()
    assert fit_range_problems(None, d) == []


def test_outside_window_problems_locates_each_offender():
    params = [RefinableParameter.model_validate([9.0, False]), RefinableParameter.model_validate([12.0, False]),
              RefinableParameter.model_validate([15.0, True])]
    out = outside_window_problems(params, (10.0, 14.0), lambda i: ("peaks", i, "pos"), "test peak")
    assert [p["loc"] for p in out] == [("peaks", 0, "pos"), ("peaks", 2, "pos")]
    assert out[0]["type"].message_template.startswith("{what} position {value} is outside the fit window")
    assert out[0]["input"] == [9.0, False]


def test_refined_flag_problems_one_per_flag():
    model = _Inner.model_validate({"scale": [1.0, True]})
    (p,) = refined_flag_problems(model, "nothing may be refined")
    assert (p["type"].type, p["loc"], p["input"]) == ("simulation_refines", ("scale",), True)
    assert refined_flag_problems(_Inner.model_validate({"scale": [1.0, False]}), "x") == []


def test_engine_recipe_checks_versions_against_its_declarations():
    assert _Recipe.model_validate(_recipe()).gateway_name == "demo"
    with pytest.raises(ValidationError, match="'demo' gateway of PowderLine .* accepts engine schema ==0.1.0"):
        _Recipe.model_validate(_recipe(engine_schema_version="2.0.0"))


def test_engine_recipe_without_declarations_is_a_type_error():
    class Bare(EngineRecipe):
        schema_name: Literal["demo.bare"]
        payload: dict
    with pytest.raises(TypeError, match="Bare must set gateway_name and schema_declarations"):
        Bare.model_validate(_recipe("demo.bare", payload={}))


def test_engine_recipe_adds_nothing_to_the_json_schema():
    props = _Recipe.model_json_schema()["properties"]
    assert set(props) == {"schema_name", "core_schema_version", "engine_schema_version", "metadata", "payload"}
    assert set(CoreRecipe.model_json_schema()["properties"]) == set(props)


def test_recipe_validator_two_models():
    validate = recipe_validator({"demo.one": _Recipe, "demo.two": _Other}, engine="demo", title="DemoRecipe")
    model = validate(_recipe())
    assert isinstance(model, _Recipe) and validate(model) is model
    assert isinstance(validate(_recipe("demo.two")), _Other)
    with pytest.raises(ValidationError) as exc:
        validate(_recipe("demo.three"))
    (only,) = exc.value.errors()
    assert only["loc"] == ("schema_name",) and only["type"] == "schema_name"
    assert only["msg"] == "schema_name 'demo.three' is not a demo workflow; expected one of demo.one, demo.two"
    assert exc.value.title == "DemoRecipe"
    with pytest.raises(ValidationError):
        validate("not a recipe")


def test_recipe_validator_one_model_and_vowel_article():
    validate = recipe_validator({"easy.one": _Recipe}, engine="easy", title="EasyRecipe")
    with pytest.raises(ValidationError, match="is not an easy workflow; expected one of easy.one"):
        validate(_recipe("easy.two"))
    with pytest.raises(ValidationError):
        validate(["not", "a", "recipe"])


def test_schema_declarations_keys_in_order_then_extras():
    assert tuple(DECL) == DECLARATION_KEYS
    d = schema_declarations(engine_schema_version="0.1.0", supported_engine_schemas="==0.1.0",
                            requires_core_schema="==0.1.0", supported_engine_versions="==6")
    assert tuple(d) == DECLARATION_KEYS + ("supported_engine_versions",) and d["supported_engine_versions"] == "==6"
