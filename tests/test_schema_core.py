"""Direct tests for powderline.schema_core validators.

Pure pydantic, engine-free. Tests the core schema 1.0.0 models that every
engine schema shares (re/03).
"""
import json
from pathlib import Path

import pytest

from pydantic import ConfigDict, PrivateAttr, ValidationError, field_validator, model_validator

from powderline.schema_core import (

    CORE_SCHEMA_VERSION,
    METADATA_MAX_BYTES,
    SUPPORTED_CORE_SCHEMAS,
    UNIT_DEG_2THETA,
    ChebyshevBackground,
    CoreRecipe,
    FitRange,
    XRDData,
    check_core_schema_version,
    check_fit_range_within_data,
)

pytestmark = pytest.mark.core


# --- XRDData ----------------------------------------------------------------


def _errors(exc_info) -> list:
    """(location, type) of every error, so a test pins which field failed and why."""
    return [(e["loc"], e["type"]) for e in exc_info.value.errors()]


def test_xrd_arrays_same_length_mismatch_raises():
    with pytest.raises(ValidationError, match="same length"):
        XRDData(tth=[1.0, 2.0, 3.0], Itth=[10.0, 20.0], Itth_weights=[1.0, 1.0])


def test_xrd_arrays_same_length_ok():
    m = XRDData(tth=[1.0, 2.0], Itth=[10.0, 20.0], Itth_weights=[1.0, 1.0])
    assert len(m.tth) == 2


def test_xrd_empty_arrays_raise():
    with pytest.raises(ValidationError, match="non-empty"):
        XRDData(tth=[], Itth=[], Itth_weights=[])


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_xrd_non_finite_tth_raises(bad):
    with pytest.raises(ValidationError, match="non-finite"):
        XRDData(tth=[1.0, bad, 3.0], Itth=[10.0, 20.0, 30.0], Itth_weights=[1.0, 1.0, 1.0])


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_xrd_non_finite_intensity_raises(bad):
    with pytest.raises(ValidationError, match="non-finite"):
        XRDData(tth=[1.0, 2.0], Itth=[10.0, bad], Itth_weights=[1.0, 1.0])


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_xrd_non_finite_weight_raises(bad):
    with pytest.raises(ValidationError, match="non-finite"):
        XRDData(tth=[1.0, 2.0], Itth=[10.0, 20.0], Itth_weights=[1.0, bad])


@pytest.mark.parametrize(
    "tth",
    [
        [1.0, 1.0, 2.0],   # equal neighbors -> not strictly increasing
        [1.0, 3.0, 2.0],   # out of order
        [3.0, 2.0, 1.0],   # descending
    ],
)
def test_xrd_non_monotonic_tth_raises(tth):
    with pytest.raises(ValidationError, match="strictly increasing"):
        XRDData(tth=tth, Itth=[10.0, 20.0, 30.0], Itth_weights=[1.0, 1.0, 1.0])


def test_xrd_negative_weight_raises():
    with pytest.raises(ValidationError, match=">= 0"):
        XRDData(tth=[1.0, 2.0], Itth=[10.0, 20.0], Itth_weights=[1.0, -0.5])


def test_xrd_all_zero_weights_raise():
    with pytest.raises(ValidationError, match="all zero"):
        XRDData(tth=[1.0, 2.0], Itth=[10.0, 20.0], Itth_weights=[0.0, 0.0])


def test_xrd_negative_intensity_ok():
    # Background-subtracted data legitimately dips below zero.
    m = XRDData(tth=[1.0, 2.0, 3.0], Itth=[-5.0, 20.0, -1.0], Itth_weights=[1.0, 1.0, 1.0])
    assert m.Itth[0] == -5.0


def test_xrd_zero_weight_point_ok():
    # A single 0 weight is fine (excludes that point) as long as one weight is > 0.
    m = XRDData(tth=[1.0, 2.0], Itth=[10.0, 20.0], Itth_weights=[0.0, 1.0])
    assert m.Itth_weights == [0.0, 1.0]


def test_xrd_single_point_ok():
    # A one-point pattern is degenerate but well-formed: the strictly-increasing
    # check must be vacuously satisfied (np.diff of one element is empty).
    m = XRDData(tth=[10.0], Itth=[100.0], Itth_weights=[2.0])
    assert m.tth == [10.0]


def test_xrd_negative_zero_weight_ok():
    # -0.0 compares equal to 0.0: it is an exclusion marker, not a negative weight.
    m = XRDData(tth=[1.0, 2.0], Itth=[10.0, 20.0], Itth_weights=[-0.0, 1.0])
    assert m.Itth_weights[0] == 0.0


def test_xrd_all_negative_zero_weights_raise():
    # ... but all -0.0 weights still means nothing to fit.
    with pytest.raises(ValidationError, match="all zero"):
        XRDData(tth=[1.0, 2.0], Itth=[10.0, 20.0], Itth_weights=[-0.0, -0.0])


def test_xrd_extra_key_rejected():
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        XRDData(tth=[1.0, 2.0], Itth=[10.0, 20.0], Itth_weights=[1.0, 1.0], unknown_field="foo")


def test_xrd_unit_metadata():
    schema = XRDData.model_json_schema()
    assert schema["properties"]["tth"]["unit"] == UNIT_DEG_2THETA


# --- FitRange ---------------------------------------------------------------


def test_fit_range_roundtrip_model_dump():
    fr = FitRange.model_validate([5.0, 40.0])
    assert fr.model_dump() == [5.0, 40.0]


def test_fit_range_roundtrip_model_dump_json():
    fr = FitRange.model_validate([5.0, 40.0])
    assert json.loads(fr.model_dump_json()) == [5.0, 40.0]


def test_fit_range_null_ends_allowed():
    fr = FitRange.model_validate([None, None])
    assert fr.model_dump() == [None, None]


def test_fit_range_one_null_end_ok():
    fr1 = FitRange.model_validate([5.0, None])
    assert fr1.model_dump() == [5.0, None]
    fr2 = FitRange.model_validate([None, 40.0])
    assert fr2.model_dump() == [None, 40.0]


def test_fit_range_wrong_length_rejected():
    with pytest.raises(ValidationError, match="exactly 2 elements"):
        FitRange.model_validate([5.0, 10.0, 15.0])


def test_fit_range_non_list_rejected():
    with pytest.raises(ValidationError, match="must be a \\[min, max\\] list"):
        FitRange.model_validate({"min": 5.0, "max": 10.0})


def test_fit_range_max_equals_min_rejected():
    with pytest.raises(ValidationError, match="must be greater than"):
        FitRange.model_validate([10.0, 10.0])


def test_fit_range_max_less_than_min_rejected():
    with pytest.raises(ValidationError, match="must be greater than"):
        FitRange.model_validate([20.0, 10.0])


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_fit_range_non_finite_min_rejected(bad):
    with pytest.raises(ValidationError, match="must be finite"):
        FitRange.model_validate([bad, 40.0])


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_fit_range_non_finite_max_rejected(bad):
    with pytest.raises(ValidationError, match="must be finite"):
        FitRange.model_validate([5.0, bad])


def test_fit_range_json_schema():
    schema = FitRange.model_json_schema()
    assert schema["type"] == "array"
    assert schema["prefixItems"] == [{"anyOf": [{"type": "number"}, {"type": "null"}]},
                                      {"anyOf": [{"type": "number"}, {"type": "null"}]}]
    assert len(schema["prefixItems"]) == 2
    assert schema["unit"] == UNIT_DEG_2THETA


# --- check_fit_range_within_data --------------------------------------------


def test_check_fit_range_within_data_none_passes():
    data = XRDData(tth=[10.0, 20.0, 30.0], Itth=[100.0, 200.0, 150.0], Itth_weights=[1.0, 1.0, 1.0])
    check_fit_range_within_data(None, data)  # no error


def test_check_fit_range_within_data_inside_passes():
    data = XRDData(tth=[10.0, 15.0, 20.0, 25.0, 30.0], Itth=[100.0] * 5, Itth_weights=[1.0] * 5)
    fr = FitRange.model_validate([12.0, 27.0])  # three weighted points inside (two is the floor, A154 N9)
    check_fit_range_within_data(fr, data)  # no error


def test_check_fit_range_within_data_exactly_at_limits_passes():
    data = XRDData(tth=[10.0, 20.0, 30.0], Itth=[100.0, 200.0, 150.0], Itth_weights=[1.0, 1.0, 1.0])
    fr = FitRange.model_validate([10.0, 30.0])
    check_fit_range_within_data(fr, data)  # no error


def test_check_fit_range_within_data_below_min_raises():
    data = XRDData(tth=[10.0, 20.0, 30.0], Itth=[100.0, 200.0, 150.0], Itth_weights=[1.0, 1.0, 1.0])
    fr = FitRange.model_validate([5.0, 25.0])
    with pytest.raises(ValueError, match="min"):
        check_fit_range_within_data(fr, data)


def test_check_fit_range_within_data_above_max_raises():
    data = XRDData(tth=[10.0, 20.0, 30.0], Itth=[100.0, 200.0, 150.0], Itth_weights=[1.0, 1.0, 1.0])
    fr = FitRange.model_validate([15.0, 35.0])
    with pytest.raises(ValueError, match="max"):
        check_fit_range_within_data(fr, data)


def test_check_fit_range_within_data_open_ends_pass():
    data = XRDData(tth=[10.0, 20.0, 30.0], Itth=[100.0, 200.0, 150.0], Itth_weights=[1.0, 1.0, 1.0])
    fr1 = FitRange.model_validate([None, 25.0])
    check_fit_range_within_data(fr1, data)  # no error
    fr2 = FitRange.model_validate([15.0, None])
    check_fit_range_within_data(fr2, data)  # no error
    fr3 = FitRange.model_validate([None, None])
    check_fit_range_within_data(fr3, data)  # no error


# --- ChebyshevBackground ----------------------------------------------------


def test_chebyshev_coefficient_count_mismatch_rejected():
    with pytest.raises(ValidationError, match="must match num_coefficients"):
        ChebyshevBackground(num_coefficients=3, coefficients=[1.0, 2.0], refine_flag=False)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_chebyshev_non_finite_coefficient_rejected(bad):
    with pytest.raises(ValidationError, match=r"coefficients\[1\] must be finite") as exc_info:
        ChebyshevBackground(num_coefficients=2, coefficients=[1.0, bad], refine_flag=False)
    assert _errors(exc_info) == [(("coefficients",), "value_error")]


def test_chebyshev_coefficient_count_match_ok():
    m = ChebyshevBackground(num_coefficients=3, coefficients=[1.0, 2.0, 3.0], refine_flag=False)
    assert len(m.coefficients) == 3


def test_chebyshev_num_coefficients_must_be_positive():
    with pytest.raises(ValidationError, match="greater than 0"):
        ChebyshevBackground(num_coefficients=0, coefficients=[], refine_flag=False)


def test_chebyshev_refine_flag_null_rejected():
    with pytest.raises(ValidationError) as exc_info:
        ChebyshevBackground(num_coefficients=1, coefficients=[1.0], refine_flag=None)
    assert _errors(exc_info) == [(('refine_flag',), 'bool_type')]


def test_chebyshev_refine_flag_string_rejected():
    with pytest.raises(ValidationError) as exc_info:
        ChebyshevBackground(num_coefficients=1, coefficients=[1.0], refine_flag="true")
    assert _errors(exc_info) == [(('refine_flag',), 'bool_type')]


def test_chebyshev_refine_flag_int_rejected():
    with pytest.raises(ValidationError) as exc_info:
        ChebyshevBackground(num_coefficients=1, coefficients=[1.0], refine_flag=1)
    assert _errors(exc_info) == [(('refine_flag',), 'bool_type')]


def test_chebyshev_extra_key_rejected():
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ChebyshevBackground(num_coefficients=1, coefficients=[1.0], refine_flag=False, unknown="bar")


# --- CoreRecipe -------------------------------------------------------------


def test_core_recipe_minimal_valid():
    r = CoreRecipe(
        schema_name="gsasii.rietveld",
        core_schema_version="1.0.0",
        engine_schema_version="1.0.0",
        payload={}
    )
    assert r.schema_name == "gsasii.rietveld"


@pytest.mark.parametrize(
    "bad_name",
    [
        "GSASII_rietveld",   # uppercase, no dot
        "gsasii",            # missing workflow
        "Gsasii.rietveld",   # uppercase first letter
        "gsasii.rietveld.x", # too many dots
        "gsasii.Rietveld",   # uppercase in workflow
        "1gsasii.rietveld",  # starts with digit
    ],
)
def test_core_recipe_schema_name_pattern_rejected(bad_name):
    with pytest.raises(ValidationError, match="String should match pattern"):
        CoreRecipe(
            schema_name=bad_name,
            core_schema_version="1.0.0",
            engine_schema_version="1.0.0",
            payload={}
        )


def test_core_recipe_schema_name_pattern_ok():
    r = CoreRecipe(
        schema_name="topas.rietveld",
        core_schema_version="1.0.0",
        engine_schema_version="1.0.0",
        payload={}
    )
    assert r.schema_name == "topas.rietveld"


def test_core_recipe_core_schema_version_1_1_0_rejected():
    with pytest.raises(ValidationError) as exc_info:
        CoreRecipe(
            schema_name="gsasii.rietveld",
            core_schema_version="1.1.0",
            engine_schema_version="1.0.0",
            payload={}
        )
    err_msg = str(exc_info.value)
    assert SUPPORTED_CORE_SCHEMAS in err_msg
    assert "PowderLine" in err_msg


def test_core_recipe_core_schema_version_2_0_0_rejected():
    with pytest.raises(ValidationError) as exc_info:
        CoreRecipe(
            schema_name="gsasii.rietveld",
            core_schema_version="2.0.0",
            engine_schema_version="1.0.0",
            payload={}
        )
    err_msg = str(exc_info.value)
    assert SUPPORTED_CORE_SCHEMAS in err_msg
    assert "PowderLine" in err_msg


def test_core_recipe_core_schema_version_invalid_string_rejected():
    with pytest.raises(ValidationError, match="not a valid version"):
        CoreRecipe(
            schema_name="gsasii.rietveld",
            core_schema_version="abc",
            engine_schema_version="1.0.0",
            payload={}
        )


def test_core_recipe_engine_schema_version_invalid_string_rejected():
    with pytest.raises(ValidationError, match="not a valid version"):
        CoreRecipe(
            schema_name="gsasii.rietveld",
            core_schema_version="1.0.0",
            engine_schema_version="abc",
            payload={}
        )


def test_core_recipe_metadata_none_ok():
    r = CoreRecipe(
        schema_name="gsasii.rietveld",
        core_schema_version="1.0.0",
        engine_schema_version="1.0.0",
        metadata=None,
        payload={}
    )
    assert r.metadata is None


def test_core_recipe_metadata_nested_json_ok():
    r = CoreRecipe(
        schema_name="gsasii.rietveld",
        core_schema_version="1.0.0",
        engine_schema_version="1.0.0",
        metadata={"user": "test", "nested": {"key": "value"}},
        payload={}
    )
    assert r.metadata["nested"]["key"] == "value"


def test_core_recipe_metadata_non_serializable_set_rejected():
    with pytest.raises(ValidationError, match="JSON-serializable"):
        CoreRecipe(
            schema_name="gsasii.rietveld",
            core_schema_version="1.0.0",
            engine_schema_version="1.0.0",
            metadata={"bad": {1, 2, 3}},
            payload={}
        )


def test_core_recipe_metadata_non_serializable_object_rejected():
    with pytest.raises(ValidationError, match="JSON-serializable"):
        CoreRecipe(
            schema_name="gsasii.rietveld",
            core_schema_version="1.0.0",
            engine_schema_version="1.0.0",
            metadata={"bad": object()},
            payload={}
        )


def test_core_recipe_metadata_nan_rejected():
    with pytest.raises(ValidationError, match="JSON-serializable"):
        CoreRecipe(
            schema_name="gsasii.rietveld",
            core_schema_version="1.0.0",
            engine_schema_version="1.0.0",
            metadata={"bad": float("nan")},
            payload={}
        )


def test_core_recipe_metadata_over_size_rejected():
    # Build a string just over METADATA_MAX_BYTES.
    # JSON encoding of {"data": "x" * N} is roughly {"data":"xxx..."}.
    # Start with a string that's definitely over the limit.
    big_string = "x" * (METADATA_MAX_BYTES + 100)
    metadata = {"data": big_string}
    # Verify it's over the limit
    size = len(json.dumps(metadata, allow_nan=False, ensure_ascii=False).encode("utf-8"))
    assert size > METADATA_MAX_BYTES

    with pytest.raises(ValidationError) as exc_info:
        CoreRecipe(
            schema_name="gsasii.rietveld",
            core_schema_version="1.0.0",
            engine_schema_version="1.0.0",
            metadata=metadata,
            payload={}
        )
    err_msg = str(exc_info.value)
    assert "METADATA_MAX_BYTES" in err_msg or str(METADATA_MAX_BYTES) in err_msg


def test_core_recipe_metadata_exactly_at_limit_ok():
    # Build metadata that's exactly at the limit.
    # Start with a reasonable guess and adjust.
    base_overhead = len(json.dumps({"data": ""}, allow_nan=False, ensure_ascii=False).encode("utf-8"))
    target_string_size = METADATA_MAX_BYTES - base_overhead
    big_string = "x" * target_string_size
    metadata = {"data": big_string}

    # Fine-tune to get exactly at the limit
    while True:
        size = len(json.dumps(metadata, allow_nan=False, ensure_ascii=False).encode("utf-8"))
        if size == METADATA_MAX_BYTES:
            break
        elif size > METADATA_MAX_BYTES:
            big_string = big_string[:-1]
            metadata = {"data": big_string}
        else:
            big_string += "x"
            metadata = {"data": big_string}

    r = CoreRecipe(
        schema_name="gsasii.rietveld",
        core_schema_version="1.0.0",
        engine_schema_version="1.0.0",
        metadata=metadata,
        payload={}
    )
    assert r.metadata == metadata


def test_core_recipe_unknown_key_rejected():
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        CoreRecipe(
            schema_name="gsasii.rietveld",
            core_schema_version="1.0.0",
            engine_schema_version="1.0.0",
            payload={},
            unknown_field="bad"
        )


def test_core_recipe_multiple_errors_reported():
    # Create a recipe with multiple independent errors
    with pytest.raises(ValidationError) as exc_info:
        CoreRecipe(
            schema_name="INVALID_NAME",  # error 1: pattern mismatch
            core_schema_version="abc",    # error 2: invalid version
            engine_schema_version="xyz",  # error 3: invalid version
            payload={},
            unknown_key="bad"             # error 4: extra field
        )
    # pydantic reports every independent problem in one ValidationError.
    locs = {e["loc"] for e in exc_info.value.errors()}
    assert locs == {("schema_name",), ("core_schema_version",),
                    ("engine_schema_version",), ("unknown_key",)}


# --- check_core_schema_version ----------------------------------------------


def test_check_core_schema_version_accepts_current():
    check_core_schema_version(CORE_SCHEMA_VERSION)  # no error


def test_check_core_schema_version_rejects_unsupported():
    with pytest.raises(ValueError, match="not supported"):
        check_core_schema_version("2.0.0")


# --- parameter models (RefinableParameter, BoundedRefinableParameter, etc.) ----


from powderline.schema_core import (
    BoundedRefinableParameter,
    RefinableParameter,
    check_within_bounds,
)
from pydantic import BaseModel


# Wrapper models for testing error locs
class _WrapperRP(BaseModel):
    """Wrapper for RefinableParameter testing."""
    a: RefinableParameter


class _WrapperBRP(BaseModel):
    """Wrapper for BoundedRefinableParameter testing."""
    a: BoundedRefinableParameter


# --- 1. JSON shape round-trip -----------------------------------------------


def test_refinable_parameter_model_dump():
    rp = RefinableParameter.model_validate([1.5, True])
    assert rp.model_dump() == [1.5, True]


def test_refinable_parameter_model_dump_json():
    rp = RefinableParameter.model_validate([1.5, True])
    assert json.loads(rp.model_dump_json()) == [1.5, True]


def test_bounded_refinable_parameter_model_dump():
    brp = BoundedRefinableParameter.model_validate([1.5, True, 0.0, 2.0])
    assert brp.model_dump() == [1.5, True, 0.0, 2.0]


def test_bounded_refinable_parameter_model_dump_json():
    brp = BoundedRefinableParameter.model_validate([1.5, True, 0.0, 2.0])
    assert json.loads(brp.model_dump_json()) == [1.5, True, 0.0, 2.0]


# --- 2. RefinableParameter validation ---------------------------------------


def test_refinable_parameter_4_element_list_rejected():
    with pytest.raises(ValidationError) as exc_info:
        _WrapperRP(a=[1.5, True, 0.0, 2.0])
    err = exc_info.value
    assert any("bounds are not supported" in e["msg"] for e in err.errors())
    assert any(e["loc"] == ("a",) for e in err.errors())


def test_refinable_parameter_1_element_list_rejected():
    with pytest.raises(ValidationError, match="expected \\[value, refine_flag\\]"):
        _WrapperRP(a=[1.5])


def test_refinable_parameter_3_element_list_rejected():
    with pytest.raises(ValidationError, match="expected \\[value, refine_flag\\]"):
        _WrapperRP(a=[1.5, True, 0.0])


def test_refinable_parameter_dict_rejected():
    with pytest.raises(ValidationError) as exc_info:
        _WrapperRP(a={"value": 1.5, "refine_flag": True})
    err = exc_info.value
    assert any("got dict" in e["msg"] for e in err.errors())


def test_refinable_parameter_scalar_rejected():
    with pytest.raises(ValidationError, match="expected a \\[value, refine_flag\\] list"):
        _WrapperRP(a=1.5)


def test_refinable_parameter_null_value_rejected():
    with pytest.raises(ValidationError) as exc_info:
        _WrapperRP(a=[None, True])
    assert _errors(exc_info) == [(('a', 'value'), 'float_type')]


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_refinable_parameter_non_finite_value_rejected(bad):
    with pytest.raises(ValidationError, match="must be finite"):
        _WrapperRP(a=[bad, True])


def test_refinable_parameter_refine_flag_null_rejected():
    with pytest.raises(ValidationError) as exc_info:
        _WrapperRP(a=[1.5, None])
    assert _errors(exc_info) == [(('a', 'refine_flag'), 'bool_type')]


def test_refinable_parameter_refine_flag_string_rejected():
    with pytest.raises(ValidationError) as exc_info:
        _WrapperRP(a=[1.5, "true"])
    assert _errors(exc_info) == [(('a', 'refine_flag'), 'bool_type')]


def test_refinable_parameter_refine_flag_int_1_rejected():
    with pytest.raises(ValidationError) as exc_info:
        _WrapperRP(a=[1.5, 1])
    assert _errors(exc_info) == [(('a', 'refine_flag'), 'bool_type')]


def test_refinable_parameter_refine_flag_int_0_rejected():
    with pytest.raises(ValidationError) as exc_info:
        _WrapperRP(a=[1.5, 0])
    assert _errors(exc_info) == [(('a', 'refine_flag'), 'bool_type')]


def test_refinable_parameter_int_value_accepted_and_dumped_as_float():
    w = _WrapperRP(a=[2, True])
    assert w.model_dump()["a"] == [2.0, True]


# --- 3. BoundedRefinableParameter validation --------------------------------


def test_bounded_refinable_parameter_2_element_list_rejected():
    with pytest.raises(ValidationError, match="expected \\[value, refine_flag, min, max\\]"):
        _WrapperBRP(a=[1.5, True])


def test_bounded_refinable_parameter_null_min_accepted():
    brp = BoundedRefinableParameter.model_validate([1.5, True, None, 2.0])
    assert brp.min is None
    assert brp.max == 2.0


def test_bounded_refinable_parameter_null_max_accepted():
    brp = BoundedRefinableParameter.model_validate([1.5, True, 0.0, None])
    assert brp.min == 0.0
    assert brp.max is None


def test_bounded_refinable_parameter_null_both_bounds_accepted():
    brp = BoundedRefinableParameter.model_validate([1.5, True, None, None])
    assert brp.min is None
    assert brp.max is None


def test_bounded_refinable_parameter_min_greater_than_max_rejected():
    with pytest.raises(ValidationError, match="min .* must be <= max"):
        _WrapperBRP(a=[1.5, True, 2.0, 1.0])


def test_bounded_refinable_parameter_value_below_min_rejected():
    with pytest.raises(ValidationError, match="below min"):
        _WrapperBRP(a=[0.5, True, 1.0, 2.0])


def test_bounded_refinable_parameter_value_above_max_rejected():
    with pytest.raises(ValidationError, match="above max"):
        _WrapperBRP(a=[2.5, True, 1.0, 2.0])


def test_bounded_refinable_parameter_value_equals_min_accepted():
    brp = BoundedRefinableParameter.model_validate([1.0, True, 1.0, 2.0])
    assert brp.value == 1.0


def test_bounded_refinable_parameter_value_equals_max_accepted():
    brp = BoundedRefinableParameter.model_validate([2.0, True, 1.0, 2.0])
    assert brp.value == 2.0


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_bounded_refinable_parameter_non_finite_min_rejected(bad):
    with pytest.raises(ValidationError, match="must be finite"):
        _WrapperBRP(a=[1.5, True, bad, 2.0])


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_bounded_refinable_parameter_non_finite_max_rejected(bad):
    with pytest.raises(ValidationError, match="must be finite"):
        _WrapperBRP(a=[1.5, True, 0.0, bad])


def test_bounded_refinable_parameter_null_value_rejected():
    with pytest.raises(ValidationError) as exc_info:
        _WrapperBRP(a=[None, True, 0.0, 2.0])
    assert _errors(exc_info) == [(('a', 'value'), 'float_type')]


# --- 4. check_within_bounds -------------------------------------------------


def test_check_within_bounds_inside_passes():
    param = BoundedRefinableParameter.model_validate([1.5, True, 1.0, 2.0])
    check_within_bounds(1.5, param, "test_field")  # no error


def test_check_within_bounds_on_min_passes():
    param = BoundedRefinableParameter.model_validate([1.0, True, 1.0, 2.0])
    check_within_bounds(1.0, param, "test_field")  # no error


def test_check_within_bounds_on_max_passes():
    param = BoundedRefinableParameter.model_validate([2.0, True, 1.0, 2.0])
    check_within_bounds(2.0, param, "test_field")  # no error


def test_check_within_bounds_open_min_passes():
    param = BoundedRefinableParameter.model_validate([0.5, True, None, 2.0])
    check_within_bounds(0.5, param, "test_field")  # no error


def test_check_within_bounds_open_max_passes():
    param = BoundedRefinableParameter.model_validate([2.5, True, 1.0, None])
    check_within_bounds(2.5, param, "test_field")  # no error


def test_check_within_bounds_open_both_passes():
    param = BoundedRefinableParameter.model_validate([100.0, True, None, None])
    check_within_bounds(100.0, param, "test_field")  # no error


def test_check_within_bounds_below_min_raises():
    param = BoundedRefinableParameter.model_validate([1.5, True, 1.0, 2.0])
    with pytest.raises(ValueError, match="test_field.*below min"):
        check_within_bounds(0.5, param, "test_field")


def test_check_within_bounds_above_max_raises():
    param = BoundedRefinableParameter.model_validate([1.5, True, 1.0, 2.0])
    with pytest.raises(ValueError, match="test_field.*above max"):
        check_within_bounds(2.5, param, "test_field")


# --- 5. JSON schema ---------------------------------------------------------


def test_refinable_parameter_json_schema():
    schema = _WrapperRP.model_json_schema()
    param_schema = schema["$defs"]["RefinableParameter"]
    assert param_schema["type"] == "array"
    assert len(param_schema["prefixItems"]) == 2
    assert param_schema["minItems"] == 2
    assert param_schema["maxItems"] == 2
    assert param_schema["prefixItems"][0] == {"type": "number"}
    assert param_schema["prefixItems"][1] == {"type": "boolean"}


def test_bounded_refinable_parameter_json_schema():
    schema = _WrapperBRP.model_json_schema()
    param_schema = schema["$defs"]["BoundedRefinableParameter"]
    assert param_schema["type"] == "array"
    assert len(param_schema["prefixItems"]) == 4
    assert param_schema["minItems"] == 4
    assert param_schema["maxItems"] == 4
    assert param_schema["prefixItems"][0] == {"type": "number"}
    assert param_schema["prefixItems"][1] == {"type": "boolean"}
    assert param_schema["prefixItems"][2] == {"anyOf": [{"type": "number"}, {"type": "null"}]}
    assert param_schema["prefixItems"][3] == {"anyOf": [{"type": "number"}, {"type": "null"}]}


# --- 6. Identity preservation -----------------------------------------------


def test_refinable_parameter_instance_identity_preserved():
    p = RefinableParameter.model_validate([1.5, True])
    w = _WrapperRP(a=p)
    assert w.a is p


def test_bounded_refinable_parameter_instance_identity_preserved():
    p = BoundedRefinableParameter.model_validate([1.5, True, 0.0, 2.0])
    w = _WrapperBRP(a=p)
    assert w.a is p


# --- check_element_symbol (A32, A63) ----------------------------------------

from powderline.schema_core import check_element_symbol  # noqa: E402


@pytest.mark.parametrize("symbol", ["Fe", "O", "La", "B", "D", "Og"])
def test_element_symbol_accepted(symbol):
    assert check_element_symbol(symbol) == symbol


@pytest.mark.parametrize("symbol, canonical", [("fe", "Fe"), ("FE", "Fe"), ("la", "La"), ("Fe ", "Fe"), (" Fe", "Fe"), ("co", "Co")])
def test_element_symbol_misspelled_rejected_with_spelling(symbol, canonical):
    with pytest.raises(ValueError, match=f"write the element symbol as '{canonical}'"):
        check_element_symbol(symbol)


@pytest.mark.parametrize("symbol", ["Fe3+", "Fe+3", "O2-", "O-2", "Fe3"])
def test_charged_types_rejected_not_stripped(symbol):
    # A63: gemmi reduces e.g. "Fe3+" to Fe, which would change the scattering; core's element is always the
    # neutral atom -- an ion is stated in the engine phase block's scattering_types (P-47), never here.
    with pytest.raises(ValueError, match="element is the neutral atom; an ionic scattering type is stated"):
        check_element_symbol(symbol)


@pytest.mark.parametrize("symbol", ["X", "Xx", "", "Nax", "Fex"])
def test_unknown_element_rejected(symbol):
    # gemmi reads a prefix ("Nax" -> Na); that must not be offered as a spelling.
    with pytest.raises(ValueError, match="not a known element symbol") as exc_info:
        check_element_symbol(symbol)
    assert "write the element symbol" not in str(exc_info.value)


# --- phase structure ---

import pytest  # noqa: E402
from fractions import Fraction  # noqa: E402
from pydantic import ValidationError  # noqa: E402

from powderline.schema_core import UnitCell, Atom, Phase, RefinableParameter  # noqa: E402
from powderline.exceptions import SymmetryError  # noqa: E402


def _valid_pmm_lab6_phase_dict():
    """Helper: valid P m -3 m LaB6-like phase (cubic a=4.15692, La at origin, B at 0.5,0.5,0.2021)."""
    return {
        "space_group": "P m -3 m",
        "unit_cell": {
            "a": [4.15692, False],
            "b": [4.15692, False],
            "c": [4.15692, False],
            "alpha": [90.0, False],
            "beta": [90.0, False],
            "gamma": [90.0, False],
        },
        "atoms": {
            "La1": {
                "element": "La",
                "x": [0.0, False],
                "y": [0.0, False],
                "z": [0.0, False],
                "occupancy": [1.0, False],
                "ADP": "Uiso",
                "Uiso": [0.005, False],
            },
            "B1": {
                "element": "B",
                "x": [0.5, False],
                "y": [0.5, False],
                "z": [0.2021, False],
                "occupancy": [1.0, False],
                "ADP": "Uiso",
                "Uiso": [0.006, False],
            },
        },
    }


def test_phase_valid_validates():
    """A valid phase validates and holds exactly the stated values (validation never changes them)."""
    d = _valid_pmm_lab6_phase_dict()
    phase = Phase[RefinableParameter].model_validate(d)
    assert phase.model_dump() == d


def test_phase_site_multiplicity():
    """Site multiplicity: La (origin) -> 1, B (0.5,0.5,0.2021) -> 6 in P m -3 m."""
    phase = Phase[RefinableParameter].model_validate(_valid_pmm_lab6_phase_dict())
    assert phase.site("La1").multiplicity == 1
    assert phase.site("B1").multiplicity == 6


def test_unit_cell_length_zero_rejected():
    """UnitCell: a=0 rejected."""
    with pytest.raises(ValidationError, match="must be positive"):
        UnitCell[RefinableParameter](a=[0.0, False], b=[4.0, False], c=[4.0, False], alpha=[90, False], beta=[90, False], gamma=[90, False])


def test_unit_cell_length_negative_rejected():
    """UnitCell: b=-1 rejected."""
    with pytest.raises(ValidationError, match="must be positive"):
        UnitCell[RefinableParameter](a=[4.0, False], b=[-1.0, False], c=[4.0, False], alpha=[90, False], beta=[90, False], gamma=[90, False])


def test_unit_cell_length_non_finite_rejected():
    """UnitCell: c=nan rejected."""
    with pytest.raises(ValidationError, match="must be finite"):
        UnitCell[RefinableParameter](a=[4.0, False], b=[4.0, False], c=[float("nan"), False], alpha=[90, False], beta=[90, False], gamma=[90, False])


def test_unit_cell_angle_zero_rejected():
    """UnitCell: alpha=0 rejected."""
    with pytest.raises(ValidationError, match="must be between 0 and 180"):
        UnitCell[RefinableParameter](a=[4.0, False], b=[4.0, False], c=[4.0, False], alpha=[0.0, False], beta=[90, False], gamma=[90, False])


def test_unit_cell_angle_180_rejected():
    """UnitCell: beta=180 rejected."""
    with pytest.raises(ValidationError, match="must be between 0 and 180"):
        UnitCell[RefinableParameter](a=[4.0, False], b=[4.0, False], c=[4.0, False], alpha=[90, False], beta=[180.0, False], gamma=[90, False])


def test_unit_cell_angle_above_180_rejected():
    """UnitCell: gamma=181 rejected."""
    with pytest.raises(ValidationError, match="must be between 0 and 180"):
        UnitCell[RefinableParameter](a=[4.0, False], b=[4.0, False], c=[4.0, False], alpha=[90, False], beta=[90, False], gamma=[181.0, False])


def test_unit_cell_angle_non_finite_rejected():
    """UnitCell: alpha=inf rejected."""
    with pytest.raises(ValidationError, match="must be finite"):
        UnitCell[RefinableParameter](a=[4.0, False], b=[4.0, False], c=[4.0, False], alpha=[float("inf"), False], beta=[90, False], gamma=[90, False])


def test_unit_cell_extra_key_rejected():
    """UnitCell: 'volume' key rejected (extra='forbid')."""
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        UnitCell[RefinableParameter](a=[4.0, False], b=[4.0, False], c=[4.0, False], alpha=[90, False], beta=[90, False], gamma=[90, False], volume=64.0)


def test_atom_element_uppercase_rejected_with_suggestion():
    """Atom: 'FE' -> message suggests 'Fe'."""
    with pytest.raises(ValidationError, match="write the element symbol as 'Fe'"):
        Atom[RefinableParameter](element="FE", x=[0.0, False], y=[0.0, False], z=[0.0, False], occupancy=[1.0, False], ADP="Uiso", Uiso=[0.01, False])


def test_atom_element_charged_rejected():
    """Atom: 'Fe3+' rejected as charged (element is the neutral atom; ions go to scattering_types, P-47)."""
    with pytest.raises(ValidationError, match="element is the neutral atom"):
        Atom[RefinableParameter](element="Fe3+", x=[0.0, False], y=[0.0, False], z=[0.0, False], occupancy=[1.0, False], ADP="Uiso", Uiso=[0.01, False])


def test_atom_occupancy_zero_accepted():
    """Atom: occupancy=0 accepted."""
    atom = Atom[RefinableParameter](element="Fe", x=[0.0, False], y=[0.0, False], z=[0.0, False], occupancy=[0.0, False], ADP="Uiso", Uiso=[0.01, False])
    assert atom.occupancy.value == 0.0


def test_atom_occupancy_one_accepted():
    """Atom: occupancy=1 accepted."""
    atom = Atom[RefinableParameter](element="Fe", x=[0.0, False], y=[0.0, False], z=[0.0, False], occupancy=[1.0, False], ADP="Uiso", Uiso=[0.01, False])
    assert atom.occupancy.value == 1.0


def test_atom_occupancy_negative_rejected():
    """Atom: occupancy=-0.01 rejected."""
    with pytest.raises(ValidationError, match="occupancy must be between 0 and 1"):
        Atom[RefinableParameter](element="Fe", x=[0.0, False], y=[0.0, False], z=[0.0, False], occupancy=[-0.01, False], ADP="Uiso", Uiso=[0.01, False])


def test_atom_occupancy_above_one_rejected():
    """Atom: occupancy=1.01 rejected."""
    with pytest.raises(ValidationError, match="occupancy must be between 0 and 1"):
        Atom[RefinableParameter](element="Fe", x=[0.0, False], y=[0.0, False], z=[0.0, False], occupancy=[1.01, False], ADP="Uiso", Uiso=[0.01, False])


_U6 = {"U11": [0.01, False], "U22": [0.01, False], "U33": [0.01, False],
       "U12": [0.0, False], "U13": [0.0, False], "U23": [0.0, False]}


def _adp_atom(**adp):
    return {"element": "Fe", "x": [0.0, False], "y": [0.0, False], "z": [0.0, False],
            "occupancy": [1.0, False], **adp}


def _adp_errors(exc_info) -> list:
    return [(e["loc"], e["type"], e["msg"]) for e in exc_info.value.errors()]


def test_atom_adp_uiso_without_value_rejected():
    """ADP selects the required thermal parameter: 'Uiso' without Uiso is missing at Uiso."""
    with pytest.raises(ValidationError) as exc_info:
        Atom[RefinableParameter].model_validate(_adp_atom(ADP="Uiso"))
    assert _adp_errors(exc_info) == [(("Uiso",), "missing", "Uiso is required when ADP is 'Uiso'")]


def test_atom_adp_uiso_with_uaniso_rejected():
    """ADP 'Uiso': Uaniso must be left out (error at Uaniso)."""
    with pytest.raises(ValidationError) as exc_info:
        Atom[RefinableParameter].model_validate(_adp_atom(ADP="Uiso", Uiso=[0.01, False], Uaniso=_U6))
    assert _adp_errors(exc_info) == [
        (("Uaniso",), "extra_forbidden", "Uaniso must be left out when ADP is 'Uiso'")]


def test_atom_adp_uaniso_missing_component_rejected():
    """ADP 'Uaniso' needs all six components; a missing one is reported at that component."""
    u = {k: v for k, v in _U6.items() if k != "U23"}
    with pytest.raises(ValidationError) as exc_info:
        Atom[RefinableParameter].model_validate(_adp_atom(ADP="Uaniso", Uaniso=u))
    assert _adp_errors(exc_info) == [(("Uaniso", "U23"), "missing", "Field required")]


def test_atom_adp_uaniso_unknown_key_rejected():
    """ADP 'Uaniso' with U14: an unknown component, reported at it."""
    with pytest.raises(ValidationError) as exc_info:
        Atom[RefinableParameter].model_validate(_adp_atom(ADP="Uaniso", Uaniso={**_U6, "U14": [0.0, False]}))
    assert _adp_errors(exc_info) == [(("Uaniso", "U14"), "extra_forbidden", "Extra inputs are not permitted")]


def test_atom_adp_uaniso_with_uiso_rejected():
    """ADP 'Uaniso': Uiso must be left out (error at Uiso)."""
    with pytest.raises(ValidationError) as exc_info:
        Atom[RefinableParameter].model_validate(_adp_atom(ADP="Uaniso", Uiso=[0.01, False], Uaniso=_U6))
    assert _adp_errors(exc_info) == [
        (("Uiso",), "extra_forbidden", "Uiso must be left out when ADP is 'Uaniso'")]


def test_atom_adp_wrong_value_rejected():
    """ADP 'Uaniso' but only Uiso given: Uaniso missing and Uiso not allowed, both reported."""
    with pytest.raises(ValidationError) as exc_info:
        Atom[RefinableParameter].model_validate(_adp_atom(ADP="Uaniso", Uiso=[0.01, False]))
    assert _adp_errors(exc_info) == [
        (("Uaniso",), "missing", "Uaniso is required when ADP is 'Uaniso'"),
        (("Uiso",), "extra_forbidden", "Uiso must be left out when ADP is 'Uaniso'"),
    ]


def test_atom_adp_errors_located_inside_the_phase():
    """Nested in a phase, the ADP pairing error is at atoms.<label>.<field> (A70)."""
    d = _valid_pmm_lab6_phase_dict()
    del d["atoms"]["La1"]["Uiso"]
    with pytest.raises(ValidationError) as exc_info:
        Phase[RefinableParameter].model_validate(d)
    assert _adp_errors(exc_info) == [(("atoms", "La1", "Uiso"), "missing", "Uiso is required when ADP is 'Uiso'")]


def test_atom_json_schema_states_the_adp_pairing():
    """The JSON Schema says ADP selects the required one of Uiso / Uaniso and forbids the other;
    UanisoTensor requires all six components."""
    schema = Phase[RefinableParameter].model_json_schema()["$defs"]
    assert schema["Atom"]["allOf"] == [
        {"if": {"properties": {"ADP": {"const": "Uiso"}}},
         "then": {"required": ["Uiso"], "not": {"required": ["Uaniso"]}}},
        {"if": {"properties": {"ADP": {"const": "Uaniso"}}},
         "then": {"required": ["Uaniso"], "not": {"required": ["Uiso"]}}},
    ]
    assert schema["Atom"]["properties"]["Uaniso"]["$ref"] == "#/$defs/UanisoTensor"
    assert schema["UanisoTensor"]["required"] == ["U11", "U22", "U33", "U12", "U13", "U23"]
    assert schema["UanisoTensor"]["additionalProperties"] is False


def test_atom_xyz_non_finite_rejected():
    """Atom: x=nan rejected."""
    with pytest.raises(ValidationError, match="must be finite"):
        Atom[RefinableParameter](element="Fe", x=[float("nan"), False], y=[0.0, False], z=[0.0, False], occupancy=[1.0, False], ADP="Uiso", Uiso=[0.01, False])


def test_phase_space_group_no_origin_rejected():
    """Phase: 'F d -3 m' (no :1/:2) rejected."""
    d = _valid_pmm_lab6_phase_dict()
    d["space_group"] = "F d -3 m"
    with pytest.raises(ValidationError) as exc_info:
        Phase[RefinableParameter].model_validate(d)
    errors = exc_info.value.errors()
    assert len(errors) == 1
    assert errors[0]["loc"] == ("space_group",)
    assert "space group 'F d -3 m' has two origin choices" in errors[0]["msg"]
    assert "write 'F d -3 m:1' or 'F d -3 m:2'" in errors[0]["msg"]


def test_phase_space_group_no_rhombohedral_setting_rejected():
    """Phase: 'R -3 m' (no :H/:R) rejected."""
    d = _valid_pmm_lab6_phase_dict()
    d["space_group"] = "R -3 m"
    with pytest.raises(ValidationError) as exc_info:
        Phase[RefinableParameter].model_validate(d)
    errors = exc_info.value.errors()
    assert len(errors) == 1
    assert errors[0]["loc"] == ("space_group",)
    assert "space group 'R -3 m' does not name its setting" in errors[0]["msg"]
    assert "write 'R -3 m:H'" in errors[0]["msg"]
    assert "or 'R -3 m:R'" in errors[0]["msg"]


def test_phase_space_group_fd3m_origin2_accepted():
    """Phase: 'F d -3 m:2' (cubic) accepted."""
    d = _valid_pmm_lab6_phase_dict()
    d["space_group"] = "F d -3 m:2"
    # Adjust cell to cubic (already is in the helper, but be explicit)
    d["unit_cell"] = {"a": [8.0, False], "b": [8.0, False], "c": [8.0, False], "alpha": [90, False], "beta": [90, False], "gamma": [90, False]}
    # Put an atom at a general position to avoid special-position complications
    d["atoms"] = {
        "A1": {"element": "O", "x": [0.125, False], "y": [0.125, False], "z": [0.125, False], "occupancy": [1.0, False], "ADP": "Uiso", "Uiso": [0.01, False]}
    }
    phase = Phase[RefinableParameter].model_validate(d)
    assert phase.space_group == "F d -3 m:2"


def test_phase_space_group_r3m_hexagonal_accepted():
    """Phase: 'R -3 m:H' (hexagonal a=b, gamma=120) accepted."""
    d = {
        "space_group": "R -3 m:H",
        "unit_cell": {"a": [3.2, False], "b": [3.2, False], "c": [5.0, False], "alpha": [90, False], "beta": [90, False], "gamma": [120, False]},
        "atoms": {
            "A1": {"element": "O", "x": [0.2, False], "y": [0.4, False], "z": [0.1, False], "occupancy": [1.0, False], "ADP": "Uiso", "Uiso": [0.01, False]}
        },
    }
    phase = Phase[RefinableParameter].model_validate(d)
    assert phase.space_group == "R -3 m:H"


def test_phase_special_position_thirds_read_from_6_decimals():
    """A120: 1/3 and 2/3 have no exact decimal form, so 6 decimals state them: (0.333333,
    0.666667, 0.25) on 2c is read as (1/3, 2/3, 1/4), with no warning; the caller's dict is
    untouched, and a dump writes the exact floats, which validate as themselves."""
    d = {
        "space_group": "P 63/m m c",
        "unit_cell": {"a": [3.2, False], "b": [3.2, False], "c": [5.2, False], "alpha": [90, False], "beta": [90, False], "gamma": [120, False]},
        "atoms": {
            "A1": {"element": "O", "x": [0.333333, False], "y": [0.666667, False], "z": [0.25, False], "occupancy": [1.0, False], "ADP": "Uiso", "Uiso": [0.01, False]}
        },
    }
    phase = Phase[RefinableParameter].model_validate(d)
    assert (phase.atoms["A1"].x.value, phase.atoms["A1"].y.value, phase.atoms["A1"].z.value) == (1 / 3, 2 / 3, 0.25)
    # P-34: each value that moved is reported once, at level "info"; z = 0.25 is exact and gets nothing
    notes = phase.warnings()
    assert [(w["code"], w["field_path"], w["level"]) for w in notes] == [
        ("symmetry_value_derived", "atoms.A1.x", "info"), ("symmetry_value_derived", "atoms.A1.y", "info")]
    assert "stated 0.333333" in notes[0]["message"] and "held as 0.3333333333333333" in notes[0]["message"]
    assert "x = 1/3" in notes[0]["message"] and "not a statement" in notes[0]["message"]
    assert d["atoms"]["A1"]["x"] == [0.333333, False]
    assert Phase[RefinableParameter].model_validate(phase.model_dump()).model_dump() == phase.model_dump()


def test_phase_special_position_with_a_decimal_form_must_be_exact():
    """A120: 1/2 and 1/4 have an exact decimal form, so 0.4999999 and 0.2499999 are errors; in one
    atom the thirds are still read and only the decimal ones are asked for."""
    d = {
        "space_group": "P 63/m m c",
        "unit_cell": {"a": [3.2, False], "b": [3.2, False], "c": [5.2, False], "alpha": [90, False], "beta": [90, False], "gamma": [120, False]},
        "atoms": {
            "A1": {"element": "O", "x": [0.333333, False], "y": [0.666667, False], "z": [0.2499999, False], "occupancy": [1.0, False], "ADP": "Uiso", "Uiso": [0.01, False]}
        },
    }
    with pytest.raises(ValidationError) as exc_info:
        Phase[RefinableParameter].model_validate(d)
    assert _errs(exc_info) == [(("atoms", "A1"),
                                "atom 'A1' (multiplicity 2 in 'P 63/m m c'): (0.333333, 0.666667, 0.2499999) is "
                                "1e-07 from a special position, not on it (x = 1/3, y = 2/3, z = 1/4); write z = 0.25")]


_R3M_CELL = {"a": [4.0, False], "b": [4.0, False], "c": [20.0, False],
             "alpha": [90, False], "beta": [90, False], "gamma": [120, False]}


def test_coupled_coordinate_with_a_third_offset_read_from_6_decimals():
    """A120: R-3m:H at (x, x + 1/3, 1/6): y has no exact decimal form, so 6 decimals state it."""
    atom = {"element": "O", "x": [0.1, True], "y": [0.433333, True], "z": [0.166667, False],
            "occupancy": [1.0, False], "ADP": "Uiso", "Uiso": [0.01, False]}
    phase = Phase[RP].model_validate({"space_group": "R -3 m:H", "unit_cell": _R3M_CELL, "atoms": {"O1": atom}})
    assert (phase.atoms["O1"].x.value, phase.atoms["O1"].y.value, phase.atoms["O1"].z.value) == (0.1, 0.1 + 1 / 3, 1 / 6)
    assert phase.atoms["O1"].y.refine_flag is True


def test_tied_bounds_with_a_third_offset_read_from_6_decimals():
    """A120 for F4: y = x + 1/3 maps x in [0.05, 0.15] to [0.383333.., 0.483333..]; 6 decimals are
    read as those, 4 decimals are an error giving them to 6 decimals."""
    cell = {k: [*v, None, None] for k, v in _R3M_CELL.items()}

    def phase(y_bounds):
        atom = {"element": "O", "x": [0.1, True, 0.05, 0.15], "y": [0.433333, True, *y_bounds],
                "z": [0.166667, False, None, None], "occupancy": [1.0, False, None, None],
                "ADP": "Uiso", "Uiso": [0.01, False, None, None]}
        return {"space_group": "R -3 m:H", "unit_cell": cell, "atoms": {"O1": atom}}

    y = Phase[BRP].model_validate(phase((0.383333, 0.483333))).atoms["O1"].y
    third = Fraction(1, 3)  # the model holds the float nearest each exact value (A120, A121)
    assert y.model_dump() == [float(Fraction(0.1) + third), True, float(Fraction(0.05) + third),
                              float(Fraction(0.15) + third)]
    with pytest.raises(ValidationError) as exc_info:
        Phase[BRP].model_validate(phase((0.3833, 0.4833)))
    assert _errs(exc_info) == [(("atoms", "O1", "y"),
                                "atom 'O1' (multiplicity 18 in 'R -3 m:H'): the bounds of y must follow y = x + 1/3 "
                                "from the bounds of x [0.05, 0.15]: write [0.383333, 0.483333] (to at least 6 "
                                "decimals), not [0.3833, 0.4833]")]


def test_phase_special_position_ambiguous_rejected():
    """Phase: atom at (0.3333,0.6667,0.25) in P 63/m m c rejected (ambiguous)."""
    d = {
        "space_group": "P 63/m m c",
        "unit_cell": {"a": [3.2, False], "b": [3.2, False], "c": [5.2, False], "alpha": [90, False], "beta": [90, False], "gamma": [120, False]},
        "atoms": {
            "A1": {"element": "O", "x": [0.3333, False], "y": [0.6667, False], "z": [0.25, False], "occupancy": [1.0, False], "ADP": "Uiso", "Uiso": [0.01, False]}
        },
    }
    with pytest.raises(ValidationError, match="without being on it") as exc_info:
        Phase[RefinableParameter].model_validate(d)
    # Check that the atom label appears in the error
    assert "A1" in str(exc_info.value)


def test_phase_multiplicity_match_accepted():
    """Phase: stated Multiplicity equal to derived accepted."""
    d = _valid_pmm_lab6_phase_dict()
    d["atoms"]["La1"]["Multiplicity"] = 1
    d["atoms"]["B1"]["Multiplicity"] = 6
    phase = Phase[RefinableParameter].model_validate(d)
    assert phase.site("La1").multiplicity == 1
    assert phase.site("B1").multiplicity == 6


def test_phase_multiplicity_mismatch_rejected():
    """Phase: stated Multiplicity != derived rejected."""
    d = _valid_pmm_lab6_phase_dict()
    d["atoms"]["B1"]["Multiplicity"] = 12  # should be 6
    with pytest.raises(ValidationError) as exc_info:
        Phase[RefinableParameter].model_validate(d)
    msg = str(exc_info.value)
    assert "stated Multiplicity" in msg
    assert "derived" in msg


def test_phase_cell_cubic_b_neq_a_rejected():
    """Phase: cubic with b != a rejected."""
    d = _valid_pmm_lab6_phase_dict()
    d["unit_cell"]["b"] = [4.2, False]
    with pytest.raises(ValidationError) as exc_info:
        Phase[RefinableParameter].model_validate(d)
    assert _errs(exc_info) == [(("unit_cell",), "unit cell is inconsistent with 'P m -3 m' (cubic): stated b = 4.2, "
                                                 "but by symmetry b = a; write b = 4.15692")]


def test_phase_cell_cubic_gamma_91_rejected():
    """Phase: cubic with gamma=91 rejected."""
    d = _valid_pmm_lab6_phase_dict()
    d["unit_cell"]["gamma"] = [91.0, False]
    with pytest.raises(ValidationError, match="inconsistent"):
        Phase[RefinableParameter].model_validate(d)


def test_phase_cell_hexagonal_gamma_90_rejected():
    """Phase: hexagonal with gamma=90 rejected."""
    d = {
        "space_group": "P 63/m m c",
        "unit_cell": {"a": [3.2, False], "b": [3.2, False], "c": [5.2, False], "alpha": [90, False], "beta": [90, False], "gamma": [90, False]},
        "atoms": {
            "A1": {"element": "O", "x": [0.2, False], "y": [0.4, False], "z": [0.1, False], "occupancy": [1.0, False], "ADP": "Uiso", "Uiso": [0.01, False]}
        },
    }
    with pytest.raises(ValidationError, match="inconsistent"):
        Phase[RefinableParameter].model_validate(d)


def test_phase_cell_monoclinic_accepted():
    """Phase: valid monoclinic C 1 2/m 1 with beta=104.3 accepted."""
    d = {
        "space_group": "C 1 2/m 1",
        "unit_cell": {"a": [5.0, False], "b": [6.0, False], "c": [7.0, False], "alpha": [90, False], "beta": [104.3, False], "gamma": [90, False]},
        "atoms": {
            "A1": {"element": "O", "x": [0.2, False], "y": [0.0, False], "z": [0.1, False], "occupancy": [1.0, False], "ADP": "Uiso", "Uiso": [0.01, False]}
        },
    }
    phase = Phase[RefinableParameter].model_validate(d)
    assert phase.space_group == "C 1 2/m 1"


def test_phase_uaniso_cubic_m3m_isotropic_accepted():
    """Phase: La at (0,0,0) in P m -3 m with isotropic Uaniso (U11=U22=U33, off-diag 0) accepted."""
    d = _valid_pmm_lab6_phase_dict()
    d["atoms"]["La1"]["ADP"] = "Uaniso"
    d["atoms"]["La1"]["Uaniso"] = {"U11": [0.01, False], "U22": [0.01, False], "U33": [0.01, False], "U12": [0, False], "U13": [0, False], "U23": [0, False]}
    del d["atoms"]["La1"]["Uiso"]
    phase = Phase[RefinableParameter].model_validate(d)
    assert phase.atoms["La1"].Uaniso.model_dump() == d["atoms"]["La1"]["Uaniso"]


def test_phase_uaniso_cubic_m3m_anisotropic_rejected():
    """Phase: La at (0,0,0) in P m -3 m with U11!=U22 rejected (breaks symmetry); the values to write
    are derived from the first member (A121)."""
    d = _valid_pmm_lab6_phase_dict()
    d["atoms"]["La1"]["ADP"] = "Uaniso"
    d["atoms"]["La1"]["Uaniso"] = {"U11": [0.01, False], "U22": [0.02, False], "U33": [0.01, False], "U12": [0, False], "U13": [0, False], "U23": [0, False]}
    del d["atoms"]["La1"]["Uiso"]
    with pytest.raises(ValidationError) as exc_info:
        Phase[RefinableParameter].model_validate(d)
    assert _errs(exc_info) == [(("atoms", "La1", "Uaniso"),
                                "atom 'La1' (multiplicity 1 in 'P m -3 m'): Uaniso is not site-symmetric "
                                "(U12 = 0, U13 = 0, U23 = 0, U22 = U11, U33 = U11); write U22 = 0.01")]


def test_phase_uaniso_hexagonal_6h_coupled_member_read_within_1e_6():
    """A121: at 6h U12 = U22/2 is derived from the stated U22. A U12 stated within 1e-6 A^2 (A78) is
    read as the derived value (0.006174 -> 0.0061735); further off is an error giving it."""
    d = {
        "space_group": "P 63/m m c",
        "unit_cell": {"a": [3.2, False], "b": [3.2, False], "c": [5.2, False], "alpha": [90, False], "beta": [90, False], "gamma": [120, False]},
        "atoms": {
            "A1": {
                "element": "O", "x": [0.2, False], "y": [0.4, False], "z": [0.25, False],
                "occupancy": [1.0, False], "ADP": "Uaniso",
                "Uaniso": {"U11": [0.012, False], "U22": [0.012347, False], "U33": [0.02, False],
                           "U12": [0.006174, False], "U13": [0.0, False], "U23": [0.0, False]},
            }
        },
    }
    phase = Phase[RefinableParameter].model_validate(d)
    assert phase.atoms["A1"].Uaniso.U12.value == 0.0061735
    assert [(w["code"], w["field_path"], w["level"]) for w in phase.warnings()] == [
        ("symmetry_value_derived", "atoms.A1.Uaniso.U12", "info")]  # P-34
    assert "U12 = U22/2" in phase.warnings()[0]["message"]
    d["atoms"]["A1"]["Uaniso"]["U12"][0] = 0.006176
    with pytest.raises(ValidationError) as exc_info:
        Phase[RefinableParameter].model_validate(d)
    assert _errs(exc_info) == [(("atoms", "A1", "Uaniso"),
                                "atom 'A1' (multiplicity 6 in 'P 63/m m c'): Uaniso is not site-symmetric "
                                "(U13 = 0, U23 = 0, U12 = U22/2); write U12 = 0.0061735")]


def test_phase_uaniso_fixed_component_must_be_exactly_zero():
    """A121: a symmetry-fixed Uij is a constant of the site, 0, which has a decimal form: 1e-9 is an
    error ("write U13 = 0.0"), never read as 0."""
    d = {
        "space_group": "P 63/m m c",
        "unit_cell": {"a": [3.2, False], "b": [3.2, False], "c": [5.2, False], "alpha": [90, False], "beta": [90, False], "gamma": [120, False]},
        "atoms": {
            "A1": {
                "element": "O", "x": [0.2, False], "y": [0.4, False], "z": [0.25, False],
                "occupancy": [1.0, False], "ADP": "Uaniso",
                "Uaniso": {"U11": [0.012, False], "U22": [0.012, False], "U33": [0.02, False],
                           "U12": [0.006, False], "U13": [1e-9, False], "U23": [0.0, False]},
            }
        },
    }
    with pytest.raises(ValidationError) as exc_info:
        Phase[RefinableParameter].model_validate(d)
    assert _errs(exc_info) == [(("atoms", "A1", "Uaniso"),
                                "atom 'A1' (multiplicity 6 in 'P 63/m m c'): Uaniso is not site-symmetric "
                                "(U13 = 0, U23 = 0, U12 = U22/2); write U13 = 0.0")]


def test_phase_multiple_atom_problems_all_reported():
    """Phase: two atoms with wrong Multiplicity -> both labels appear in one error."""
    d = _valid_pmm_lab6_phase_dict()
    d["atoms"]["La1"]["Multiplicity"] = 2
    d["atoms"]["B1"]["Multiplicity"] = 12
    with pytest.raises(ValidationError) as exc_info:
        Phase[RefinableParameter].model_validate(d)
    msg = str(exc_info.value)
    assert "La1" in msg
    assert "B1" in msg


# --- Phase: error locations, reporting, no side effects (A70) -------


def _uaniso(u11, u22, u33, u12=0.0, u13=0.0, u23=0.0):
    return {"U11": [u11, False], "U22": [u22, False], "U33": [u33, False], "U12": [u12, False], "U13": [u13, False], "U23": [u23, False]}


def test_phase_all_problems_of_one_atom_reported():
    """A wrong Multiplicity does not hide the same atom's Uaniso error."""
    d = _valid_pmm_lab6_phase_dict()
    la = d["atoms"]["La1"]
    la["Multiplicity"] = 2
    la["ADP"] = "Uaniso"
    del la["Uiso"]
    la["Uaniso"] = _uaniso(0.01, 0.02, 0.01)
    with pytest.raises(ValidationError) as exc_info:
        Phase[RefinableParameter].model_validate(d)
    assert _errors(exc_info) == [
        (("atoms", "La1", "Multiplicity"), "value_error"),
        (("atoms", "La1", "Uaniso"), "value_error"),
    ]


def test_phase_problems_reported_at_their_locations():
    """Cell, position and multiplicity problems: one error each, at its own field."""
    d = _valid_pmm_lab6_phase_dict()
    d["unit_cell"]["b"] = [4.2, False]
    d["atoms"]["La1"]["x"] = [0.001, False]  # ambiguous band
    d["atoms"]["B1"]["Multiplicity"] = 12
    with pytest.raises(ValidationError) as exc_info:
        Phase[RefinableParameter].model_validate(d)
    assert _errors(exc_info) == [
        (("unit_cell",), "value_error"),
        (("atoms", "La1"), "value_error"),
        (("atoms", "B1", "Multiplicity"), "value_error"),
    ]
    msgs = [e["msg"] for e in exc_info.value.errors()]
    assert "b = 4.2" in msgs[0]
    assert "without being on it" in msgs[1]
    assert "stated Multiplicity 12, derived 6" in msgs[2]


def test_phase_locations_nest_in_enclosing_models():
    """Engine schemas embed Phase: the locations get the enclosing path, also from JSON."""
    from pydantic import BaseModel

    class Payload(BaseModel):
        structure: Phase[RefinableParameter]

    d = _valid_pmm_lab6_phase_dict()
    d["atoms"]["B1"]["Multiplicity"] = 12
    with pytest.raises(ValidationError) as exc_info:
        Payload.model_validate_json(json.dumps({"structure": d}))
    assert _errors(exc_info) == [(("structure", "atoms", "B1", "Multiplicity"), "value_error")]


def test_phase_holds_the_callers_atoms_unchanged():
    """Validation never changes a value, so the validated phase holds the caller's atom as given."""
    atom = Atom[RefinableParameter].model_validate({"element": "C", "x": [1 / 3, False], "y": [2 / 3, False], "z": [0.25, False],
                                "occupancy": [1.0, False], "ADP": "Uiso", "Uiso": [0.01, False]})
    phase = Phase[RefinableParameter].model_validate({
        "space_group": "P 63/m m c",
        "unit_cell": {"a": [3.2, False], "b": [3.2, False], "c": [5.2, False], "alpha": [90, False], "beta": [90, False], "gamma": [120, False]},
        "atoms": {"C1": atom},
    })
    assert phase.atoms["C1"] is atom


# --- Phase[P]: the phase block (re/03b; A93-A96, A100, A105) -----------------

from powderline.schema_core import (  # noqa: E402
    RESERVED_PHASE_FIELDS,
    BoundedRefinableParameter,
    CoreModel,
)

RP, BRP = RefinableParameter, BoundedRefinableParameter


def _bounded(d: dict, lo=None, hi=None) -> dict:
    """The phase dict with every [value, flag] made [value, flag, lo, hi]."""
    def conv(v):
        if isinstance(v, list):
            return [*v, lo, hi]
        if isinstance(v, dict):
            return {k: conv(x) for k, x in v.items()}
        return v
    return conv(d)


@pytest.mark.parametrize("space_group, cell, xyz", [
    ("P m -3 m", (4.0, 4.0, 4.0, 90, 90, 90), (0.1, 0.2, 0.3)),
    ("C 1 2/m 1", (9.0, 5.0, 7.0, 90, 105.0, 90), (0.1, 0.2, 0.3)),
    ("P 1 21/c 1", (5.0, 6.0, 7.0, 90, 98.0, 90), (0.1, 0.2, 0.3)),
    ("P 1 1 21/a", (5.0, 6.0, 7.0, 90, 90, 98.0), (0.1, 0.2, 0.3)),
    ("A 1 1 2/a", (5.0, 6.0, 7.0, 90, 90, 98.0), (0.1, 0.2, 0.3)),
    ("C c 1 1", (5.0, 6.0, 7.0, 98.0, 90, 90), (0.1, 0.2, 0.3)),
    ("P 1 c 1", (5.0, 6.0, 7.0, 90, 98.0, 90), (0.1, 0.2, 0.3)),
    ("R -3 m:H", (4.0, 4.0, 20.0, 90, 90, 120), (0.1, 0.2, 0.3)),
    ("R -3 m:R", (5.0, 5.0, 5.0, 70.0, 70.0, 70.0), (0.1, 0.2, 0.3)),
    ("F d -3 m:2", (8.0, 8.0, 8.0, 90, 90, 90), (0.125, 0.125, 0.125)),
    ("F d -3 m:1", (8.0, 8.0, 8.0, 90, 90, 90), (0.0, 0.0, 0.0)),
    ("P 63/m m c", (3.2, 3.2, 5.2, 90, 90, 120), (1 / 3, 2 / 3, 0.25)),
])
def test_phase_canonical_space_group_accepted(space_group, cell, xyz):
    """Canonical names validate, incl. non-standard settings, ':R' and both origins (A105)."""
    d = {"space_group": space_group,
         "unit_cell": dict(zip(("a", "b", "c", "alpha", "beta", "gamma"), ([v, False] for v in cell))),
         "atoms": {"A1": {"element": "Fe", **{k: [v, False] for k, v in zip("xyz", xyz)},
                          "occupancy": [1.0, False], "ADP": "Uiso", "Uiso": [0.01, False]}}}
    assert Phase[RP].model_validate(d).space_group == space_group


@pytest.mark.parametrize("symbol, message", [
    ("Pm-3m", "space group 'Pm-3m' is not in the canonical form; write 'P m -3 m'"),
    ("p m -3 m", "space group 'p m -3 m' is not in the canonical form; write 'P m -3 m'"),
    ("C2/m", "space group 'C2/m' does not state its unique axis or cell choice (gemmi would read it as "
             "'C 1 2/m 1'); write the setting you mean: unique axis b: 'C 1 2/m 1', 'A 1 2/m 1', "
             "'I 1 2/m 1', 'F 1 2/m 1'; unique axis c: 'A 1 1 2/m', 'B 1 1 2/m', 'I 1 1 2/m'; "
             "unique axis a: 'B 2/m 1 1', 'C 2/m 1 1', 'I 2/m 1 1'"),
    ("C 2/m", "space group 'C 2/m' does not state its unique axis or cell choice (gemmi would read it as "
              "'C 1 2/m 1'); write the setting you mean: unique axis b: 'C 1 2/m 1', 'A 1 2/m 1', "
              "'I 1 2/m 1', 'F 1 2/m 1'; unique axis c: 'A 1 1 2/m', 'B 1 1 2/m', 'I 1 1 2/m'; "
              "unique axis a: 'B 2/m 1 1', 'C 2/m 1 1', 'I 2/m 1 1'"),
    ("P 21/c", "space group 'P 21/c' does not state its unique axis or cell choice (gemmi would read it as "
               "'P 1 21/c 1'); write the setting you mean: unique axis b: 'P 1 21/c 1', 'P 1 21/n 1', "
               "'P 1 21/a 1'; unique axis c: 'P 1 1 21/a', 'P 1 1 21/n', 'P 1 1 21/b'; "
               "unique axis a: 'P 21/b 1 1', 'P 21/n 1 1', 'P 21/c 1 1'"),
    ("Pc", "space group 'Pc' does not state its unique axis or cell choice (gemmi would read it as "
           "'P 1 c 1'); write the setting you mean: unique axis b: 'P 1 c 1', 'P 1 n 1', 'P 1 a 1'; "
           "unique axis c: 'P 1 1 a', 'P 1 1 n', 'P 1 1 b'; unique axis a: 'P b 1 1', 'P n 1 1', 'P c 1 1'"),
    ("P121/c1", "space group 'P121/c1' is not in the canonical form; write 'P 1 21/c 1'"),
    ("R-3m:H", "space group 'R-3m:H' is not in the canonical form; write 'R -3 m:H'"),
    ("R -3 m", "space group 'R -3 m' does not name its setting; write 'R -3 m:H' (hexagonal axes) "
               "or 'R -3 m:R' (rhombohedral axes)"),
    ("Fd-3m", "space group 'Fd-3m' has two origin choices; write 'F d -3 m:1' or 'F d -3 m:2'"),
    ("F d -3 m", "space group 'F d -3 m' has two origin choices; write 'F d -3 m:1' or 'F d -3 m:2'"),
    ("P2_1/c", "unrecognized space-group symbol 'P2_1/c'; write gemmi's canonical name "
               "(e.g. 'P m -3 m', 'C 1 2/m 1', 'R -3 m:H', 'F d -3 m:2')"),
])
def test_phase_non_canonical_space_group_rejected(symbol, message):
    """Any other spelling is an error at space_group naming the canonical form (A105)."""
    d = _valid_pmm_lab6_phase_dict()
    d["space_group"] = symbol
    with pytest.raises(ValidationError) as exc_info:
        Phase[RP].model_validate(d)
    assert _errors(exc_info) == [(("space_group",), "value_error")]
    assert exc_info.value.errors()[0]["msg"] == "Value error, " + message


def test_canonical_space_group_every_gemmi_name_round_trips():
    """gemmi's xhm() names are unique over its table and each validates as itself (A105)."""
    import gemmi
    from powderline.symmetry import canonical_space_group

    names = [sg.xhm() for sg in gemmi.spacegroup_table()]
    assert len(names) == len(set(names)) == 564
    assert all(canonical_space_group(n).xhm() == n for n in names)


def test_canonical_space_group_names_match_the_committed_list():
    """The accepted spellings are gemmi's names, pinned: a gemmi change that renames, adds or
    drops one fails here before it can invalidate recipes (gemmi is pinned exactly; review B4).
    On a deliberate gemmi upgrade, regenerate the file and record the change in SCHEMA_HISTORY."""
    import gemmi

    committed = (Path(__file__).parent / "data" / "canonical_space_groups.txt").read_text(encoding="utf-8")
    assert [sg.xhm() for sg in gemmi.spacegroup_table()] == committed.splitlines()


@pytest.mark.parametrize("field", RESERVED_PHASE_FIELDS)
def test_phase_reserved_field_cannot_be_redeclared(field):
    """An engine subclass may not redefine space_group, unit_cell or atoms (A93)."""
    with pytest.raises(TypeError) as exc_info:
        type("EnginePhase", (Phase[RP],), {"__annotations__": {field: int}, "__module__": __name__})
    assert str(exc_info.value) == (f"EnginePhase redeclares the core phase field(s) {field}; "
                                   "core owns space_group, unit_cell and atoms")


def test_phase_reserved_fields_guarded_below_an_engine_subclass():
    class EnginePhase(Phase[RP]):
        scale: RP

    with pytest.raises(TypeError, match=r"^Child redeclares the core phase field\(s\) atoms;"):
        class Child(EnginePhase):
            atoms: dict


def test_phase_reserved_members_are_core_validators_private_attributes_and_methods():
    """Pinned, so a new core validator or method is seen to be reserved too (review A1)."""
    from powderline.schema_core import _reserved_phase_members

    assert _reserved_phase_members() == {"_parameter_type_chosen", "_space_group", "_sites_check", "_sites",
                                         "_warnings", "site", "warnings"}


@pytest.mark.parametrize("name, body", [
    ("_space_group", "@field_validator('space_group')\n@classmethod\ndef _space_group(cls, v):\n    return v"),
    ("_sites_check", "@model_validator(mode='after')\ndef _sites_check(self):\n    return self"),
    ("site", "def site(self, label):\n    return None"),
    ("_sites", "_sites: dict = PrivateAttr(default_factory=dict)"),
])
def test_phase_core_validator_or_method_cannot_be_reused(name, body):
    """A same-named engine validator would silently replace core's (pydantic collects them by name)."""
    namespace = {"field_validator": field_validator, "model_validator": model_validator,
                 "PrivateAttr": PrivateAttr, "Phase": Phase, "RP": RP}
    source = "class EnginePhase(Phase[RP]):\n    scale: RP\n" + "\n".join(
        "    " + line for line in body.splitlines())
    with pytest.raises(TypeError) as exc_info:
        exec(source, namespace)
    assert str(exc_info.value) == (
        f"EnginePhase reuses the core phase name(s) {name}; a same-named validator, method or "
        "private attribute would replace core's silently; rename it")


_OPEN_TYPE = ("has no parameter type: subclass Phase[RefinableParameter] (no bounds) or "
              "Phase[BoundedRefinableParameter] (bounds); a deliberately generic subclass declares "
              "Generic[P] and is parametrized before use")


def test_phase_without_parameter_type_cannot_validate():
    """Unparametrized, one phase could mix [value, flag] and [value, flag, min, max] (review A2)."""
    d = _valid_pmm_lab6_phase_dict()
    d["unit_cell"]["a"] = [4.15692, False, 4.0, 4.3]
    with pytest.raises(TypeError) as exc_info:
        Phase.model_validate(d)
    assert str(exc_info.value) == f"Phase {_OPEN_TYPE}"


def test_engine_subclass_must_choose_a_parameter_type():
    with pytest.raises(TypeError) as exc_info:
        class EnginePhase(Phase):
            pass
    assert str(exc_info.value) == f"EnginePhase {_OPEN_TYPE}"


def test_generic_engine_subclass_validates_once_parametrized():
    from typing import Generic

    from powderline.schema_core import P

    class EnginePhase(Phase[P], Generic[P]):
        scale: P

    d = {**_valid_pmm_lab6_phase_dict(), "scale": [1.0, True]}
    with pytest.raises(TypeError) as exc_info:
        EnginePhase.model_validate(d)
    assert str(exc_info.value) == f"EnginePhase {_OPEN_TYPE}"
    assert EnginePhase[RP].model_validate(d).scale.model_dump() == [1.0, True]


def test_phase_engine_subclass_must_keep_extra_forbid():
    with pytest.raises(TypeError) as exc_info:
        class EnginePhase(Phase[RP]):
            model_config = ConfigDict(extra="allow")
    assert str(exc_info.value) == "EnginePhase must keep extra='forbid'"


def test_phase_engine_validators_with_their_own_names_run_with_core_rules():
    """An engine adds its own rule (gsasii rejects origin 1, EB-03) without replacing core's."""
    class EnginePhase(Phase[RP]):
        scale: RP

        @field_validator("space_group")
        @classmethod
        def _gsasii_origin(cls, v):
            if v.endswith(":1"):
                raise ValueError("gsasii: origin choice 1 is not supported")
            return v

    d = {**_valid_pmm_lab6_phase_dict(), "scale": [1.0, True]}
    d["space_group"] = "Pm-3m"
    with pytest.raises(ValidationError) as exc_info:
        EnginePhase.model_validate(d)
    assert exc_info.value.errors()[0]["msg"] == (
        "Value error, space group 'Pm-3m' is not in the canonical form; write 'P m -3 m'")


def test_phase_engine_subclass_adds_flat_fields_and_keeps_core_validation():
    """The gsasii shape: engine fields flat in the phase; core rules still run; locs nest."""
    class EnginePhase(Phase[RP]):
        scale: RP

    d = _valid_pmm_lab6_phase_dict()
    phase = EnginePhase.model_validate({**d, "scale": [1.0, True]})
    assert phase.scale.model_dump() == [1.0, True]
    d["atoms"]["B1"]["x"] = [0.4999999, False]
    with pytest.raises(ValidationError) as exc_info:
        EnginePhase.model_validate({**d, "scale": [1.0, True]})
    assert _errors(exc_info) == [(("atoms", "B1"), "value_error")]  # the core symmetry rule runs
    d["atoms"]["B1"]["x"] = [0.5, False]
    d["atoms"]["B1"]["Multiplicity"] = 12
    with pytest.raises(ValidationError) as exc_info:
        EnginePhase.model_validate({**d, "scale": [1.0, True]})
    assert _errors(exc_info) == [(("atoms", "B1", "Multiplicity"), "value_error")]
    with pytest.raises(ValidationError) as exc_info:
        EnginePhase.model_validate(d)
    assert _errors(exc_info) == [(("scale",), "missing")]


def test_phase_has_no_phase_name():
    """The phase name is the key of the payload's phases dict (A100)."""
    d = {"phase_name": "LaB6", **_valid_pmm_lab6_phase_dict()}
    with pytest.raises(ValidationError) as exc_info:
        Phase[RP].model_validate(d)
    assert _errors(exc_info) == [(("phase_name",), "extra_forbidden")]


def test_atom_occupancy_required():
    """No default: occupancy must be stated (A96)."""
    d = _valid_pmm_lab6_phase_dict()
    del d["atoms"]["La1"]["occupancy"]
    with pytest.raises(ValidationError) as exc_info:
        Phase[RP].model_validate(d)
    assert _errors(exc_info) == [(("atoms", "La1", "occupancy"), "missing")]


@pytest.mark.parametrize("field", ["Multiplicity", "Uiso", "Uaniso"])
def test_atom_optional_fields_are_never_null(field):
    """A field that may be left out is never null (A96); leaving it out is the way."""
    d = _valid_pmm_lab6_phase_dict()
    d["atoms"]["B1"][field] = None
    with pytest.raises(ValidationError) as exc_info:
        Phase[RP].model_validate(d)
    assert _errors(exc_info) == [(("atoms", "B1", field), "value_error")]
    assert exc_info.value.errors()[0]["msg"] == f"Value error, {field} must not be null; leave it out instead"


@pytest.mark.parametrize("param", [[None, False], [0.5, None]])
def test_phase_parameter_value_and_flag_never_null(param):
    d = _valid_pmm_lab6_phase_dict()
    d["atoms"]["B1"]["z"] = param
    with pytest.raises(ValidationError) as exc_info:
        Phase[RP].model_validate(d)
    slot = "value" if param[0] is None else "refine_flag"
    assert _errors(exc_info) == [(("atoms", "B1", "z", slot), "float_type" if slot == "value" else "bool_type")]


def test_phase_dump_round_trips_and_leaves_absent_fields_out():
    d = _valid_pmm_lab6_phase_dict()
    d["atoms"]["B1"]["Multiplicity"] = 6
    phase = Phase[RP].model_validate(d)
    dump = phase.model_dump(mode="json")
    assert dump == d
    assert "Uaniso" not in dump["atoms"]["La1"] and "Multiplicity" not in dump["atoms"]["La1"]
    assert Phase[RP].model_validate_json(phase.model_dump_json()).model_dump() == phase.model_dump()


def test_phase_json_schema_names_and_no_null():
    """Readable $defs (no 'Atom_RefinableParameter_'); optional fields are not nullable (A96)."""
    class EnginePhase(Phase[RP]):
        scale: RP

    schema = EnginePhase.model_json_schema()
    assert sorted(schema["$defs"]) == ["Atom", "RefinableParameter", "UanisoTensor", "UnitCell"]
    atom = schema["$defs"]["Atom"]
    assert atom["required"] == ["element", "x", "y", "z", "occupancy", "ADP"]
    assert atom["properties"]["Uiso"] == {"$ref": "#/$defs/RefinableParameter", "unit": "angstrom^2",
                                          "description": "Isotropic ADP; required when ADP is 'Uiso', else left out"}
    assert atom["properties"]["Multiplicity"]["type"] == "integer"
    assert "null" not in json.dumps(schema)
    assert schema["$defs"]["RefinableParameter"]["prefixItems"] == [{"type": "number"}, {"type": "boolean"}]


def test_phase_json_schema_two_parameter_types_in_one_document_stay_distinct():
    """If two parametrizations ever share a document, the names fall back and the refs stay right."""
    class Both(CoreModel):
        g: Phase[RP]
        t: Phase[BRP]

    defs = Both.model_json_schema()["$defs"]
    atom_refs = {k: v["properties"]["atoms"]["additionalProperties"]["$ref"].rsplit("/", 1)[1]
                 for k, v in defs.items() if "Phase" in k}
    assert len(set(atom_refs.values())) == 2
    for name, ref in atom_refs.items():
        expected = "BoundedRefinableParameter" if "Bounded" in name else "RefinableParameter"
        assert defs[ref]["properties"]["x"]["$ref"] == f"#/$defs/{expected}"


def test_phase_rejects_bounds_where_the_parameter_type_has_none():
    d = _valid_pmm_lab6_phase_dict()
    d["unit_cell"]["a"] = [4.15692, False, 4.0, 4.3]
    with pytest.raises(ValidationError) as exc_info:
        Phase[RP].model_validate(d)
    assert _errors(exc_info) == [(("unit_cell", "a"), "value_error")]
    assert "bounds are not supported" in exc_info.value.errors()[0]["msg"]


def test_phase_value_rules_act_on_value():
    """Cell, occupancy and element rules read .value; each error at its own field (A70)."""
    d = _valid_pmm_lab6_phase_dict()
    d["unit_cell"]["a"] = [-4.0, False]
    d["atoms"]["La1"]["occupancy"] = [1.5, False]
    d["atoms"]["B1"]["element"] = "b"
    with pytest.raises(ValidationError) as exc_info:
        Phase[RP].model_validate(d)
    assert _errors(exc_info) == [(("unit_cell", "a"), "value_error"),
                                 (("atoms", "La1", "occupancy"), "value_error"),
                                 (("atoms", "B1", "element"), "value_error")]
    assert [e["msg"] for e in exc_info.value.errors()] == [
        "Value error, cell length a must be positive, got -4.0",
        "Value error, occupancy must be between 0 and 1 inclusive, got 1.5",
        "Value error, element 'b': write the element symbol as 'B'",
    ]


# --- numbers are JSON numbers: no strings, no booleans (A80) -----------------

import numpy as np  # noqa: E402

from powderline.schema_core import FitRange, XRDData  # noqa: E402


def _cell(**kw):
    base = {"a": [4.0, False], "b": [4.0, False], "c": [4.0, False], "alpha": [90, False], "beta": [90, False], "gamma": [90, False]}
    base.update(kw)
    return base


def _atom(**kw):
    base = {"element": "Na", "x": [0.1, False], "y": [0.2, False], "z": [0.3, False], "occupancy": [1.0, False], "ADP": "Uiso", "Uiso": [0.01, False]}
    base.update(kw)
    return base


def _xrd(**kw):
    return {"tth": [10.0, 20.0], "Itth": [1.0, 2.0], "Itth_weights": [1.0, 1.0], **kw}


# (label, build(v) -> validated model, error location); every numeric core field
_NUMERIC_FIELDS = [
    ("RefinableParameter.value", lambda v: RefinableParameter.model_validate([v, True]), ("value",)),
    ("BoundedRefinableParameter.value", lambda v: BoundedRefinableParameter.model_validate([v, True, None, None]), ("value",)),
    ("BoundedRefinableParameter.min", lambda v: BoundedRefinableParameter.model_validate([1.0, True, v, None]), ("min",)),
    ("BoundedRefinableParameter.max", lambda v: BoundedRefinableParameter.model_validate([0.5, True, None, v]), ("max",)),
    ("FitRange.min", lambda v: FitRange.model_validate([v, None]), ("min",)),
    ("FitRange.max", lambda v: FitRange.model_validate([None, v]), ("max",)),
    ("XRDData.tth", lambda v: XRDData.model_validate(_xrd(tth=[v, 20.0])), ("tth", 0)),
    ("XRDData.Itth", lambda v: XRDData.model_validate(_xrd(Itth=[v, 2.0])), ("Itth", 0)),
    ("XRDData.Itth_weights", lambda v: XRDData.model_validate(_xrd(Itth_weights=[v, 1.0])), ("Itth_weights", 0)),
    ("ChebyshevBackground.coefficients",
     lambda v: ChebyshevBackground(num_coefficients=1, coefficients=[v], refine_flag=False), ("coefficients", 0)),
    *[(f"UnitCell.{k}", (lambda k: lambda v: UnitCell[RefinableParameter].model_validate(_cell(**{k: [v, False]})))(k), (k, "value"))
      for k in ("a", "b", "c", "alpha", "beta", "gamma")],
    *[(f"Atom.{k}", (lambda k: lambda v: Atom[RefinableParameter].model_validate(_atom(**{k: [v, False]})))(k), (k, "value"))
      for k in ("x", "y", "z", "occupancy", "Uiso")],
    ("Atom.Uaniso", lambda v: Atom[RefinableParameter].model_validate({
        "element": "Na", "x": [0.1, False], "y": [0.2, False], "z": [0.3, False], "occupancy": [1.0, False], "ADP": "Uaniso",
        "Uaniso": {"U11": [v, False], "U22": [0.01, False], "U33": [0.01, False], "U12": [0.0, False], "U13": [0.0, False], "U23": [0.0, False]}}), ("Uaniso", "U11", "value")),
]
_FLOAT_IDS = [f[0] for f in _NUMERIC_FIELDS]


@pytest.mark.parametrize("label, build, loc", _NUMERIC_FIELDS, ids=_FLOAT_IDS)
@pytest.mark.parametrize("bad", ["0.5", "1", True, False], ids=["str-float", "str-int", "true", "false"])
def test_numeric_field_rejects_strings_and_booleans(label, build, loc, bad):
    with pytest.raises(ValidationError) as exc_info:
        build(bad)
    assert _errors(exc_info) == [(loc, "float_type")]


@pytest.mark.parametrize("label, build, loc", _NUMERIC_FIELDS, ids=_FLOAT_IDS)
@pytest.mark.parametrize("good", [1, np.float64(0.5), np.int64(1)], ids=["int", "numpy-float", "numpy-int"])
def test_numeric_field_accepts_numbers(label, build, loc, good):
    model = build(good)  # no error; the value is kept as a float
    value = model
    for part in loc:
        value = value[part] if isinstance(value, (list, dict)) else getattr(value, part)
    assert value == float(good) and type(value) is float


def test_numeric_json_strings_rejected():
    """From JSON too: a quoted number is not a number."""
    with pytest.raises(ValidationError) as exc_info:
        Atom[RefinableParameter].model_validate_json(json.dumps(_atom(x=["0.25", False])))
    assert _errors(exc_info) == [(("x", "value"), "float_type")]
    assert Atom[RefinableParameter].model_validate_json(json.dumps(_atom(x=[1, False]))).x.value == 1.0


@pytest.mark.parametrize("good", [4, 4.0, np.int64(4), np.float64(4.0)])
def test_integer_fields_accept_whole_numbers(good):
    assert Atom[RefinableParameter].model_validate(_atom(Multiplicity=good)).Multiplicity == 4
    assert ChebyshevBackground(num_coefficients=good, coefficients=[0.0] * 4, refine_flag=False).num_coefficients == 4


@pytest.mark.parametrize("bad, error_type", [
    (4.5, "int_from_float"), ("4", "int_type"), (True, "int_type"), (False, "int_type"), (b"4", "int_type"),
])
def test_integer_fields_reject_fractions_strings_and_booleans(bad, error_type):
    with pytest.raises(ValidationError) as exc_info:
        Atom[RefinableParameter].model_validate(_atom(Multiplicity=bad))
    assert _errors(exc_info) == [(("Multiplicity",), error_type)]
    with pytest.raises(ValidationError) as exc_info:
        ChebyshevBackground(num_coefficients=bad, coefficients=[0.0] * 4, refine_flag=False)
    assert _errors(exc_info)[0] == (("num_coefficients",), error_type)


def test_integer_json_whole_float_accepted():
    assert Atom[RefinableParameter].model_validate_json(json.dumps(_atom(Multiplicity=4.0))).Multiplicity == 4


# --- flag and bound rules F1-F4 (re/03b; A95, A98, A104, A106, A108) ---------

_CELL_NAMES = ("a", "b", "c", "alpha", "beta", "gamma")
_U_NAMES = ("U11", "U22", "U33", "U12", "U13", "U23")
_N = [None, None]


def _cellp(values, flags=(False,) * 6, bounds=None):
    """unit_cell dict; with ``bounds`` (a dict of name -> (min, max), default open) 4-element lists."""
    if bounds is None:
        return {n: [v, f] for n, v, f in zip(_CELL_NAMES, values, flags)}
    return {n: [v, f, *bounds.get(n, _N)] for n, v, f in zip(_CELL_NAMES, values, flags)}


def _atomp(xyz, flags=(False,) * 3, bounds=None, uaniso=None, element="O"):
    """atom dict; ``uaniso`` = {U: [value, flag(, min, max)]} switches ADP to Uaniso."""
    tail = (lambda n: list(bounds.get(n, _N))) if bounds is not None else (lambda n: [])
    d = {"element": element, **{k: [v, f, *tail(k)] for k, v, f in zip("xyz", xyz, flags)},
         "occupancy": [1.0, False, *tail("occupancy")]}
    if uaniso is None:
        d.update(ADP="Uiso", Uiso=[0.01, False, *tail("Uiso")])
    else:
        d.update(ADP="Uaniso", Uaniso=uaniso)
    return d


def _phasep(space_group, cell, atoms):
    return {"space_group": space_group, "unit_cell": cell, "atoms": atoms}


def _errs(exc_info) -> list:
    """(location, message without pydantic's prefix) of every error."""
    return [(e["loc"], e["msg"].removeprefix("Value error, ")) for e in exc_info.value.errors()]


_GENERAL = (0.1234, 0.2345, 0.3456)

# (space group, cell values, members after the first of each tie group, fixed angles)
_CELL_SYSTEMS = [
    ("P m -3 m", (4, 4, 4, 90, 90, 90), ["b", "c"], ["alpha", "beta", "gamma"]),
    ("P 4/m m m", (4, 4, 6, 90, 90, 90), ["b"], ["alpha", "beta", "gamma"]),
    ("P 63/m m c", (3, 3, 5, 90, 90, 120), ["b"], ["alpha", "beta", "gamma"]),
    ("R -3 m:H", (4, 4, 20, 90, 90, 120), ["b"], ["alpha", "beta", "gamma"]),
    ("R -3 m:R", (5, 5, 5, 70, 70, 70), ["b", "c", "beta", "gamma"], []),
    ("P m m m", (4, 5, 6, 90, 90, 90), [], ["alpha", "beta", "gamma"]),
    ("C 1 2/m 1", (9, 5, 7, 90, 105, 90), [], ["alpha", "gamma"]),
    ("P 1 c 1", (5, 6, 7, 90, 98, 90), [], ["alpha", "gamma"]),     # Pc, b-unique (A102)
    ("P 1 1 m", (5, 6, 7, 90, 90, 98), [], ["alpha", "beta"]),      # Pm, c-unique
    ("C m 1 1", (5, 6, 7, 98, 90, 90), [], ["beta", "gamma"]),      # Cm, a-unique
    ("C 1 c 1", (5, 6, 7, 90, 98, 90), [], ["alpha", "gamma"]),     # Cc
    ("P -1", (5, 6, 7, 80, 85, 95), [], []),
]


@pytest.mark.parametrize("sg, cell, _tied, fixed", _CELL_SYSTEMS, ids=[c[0] for c in _CELL_SYSTEMS])
def test_cell_flags_consistent_accepted(sg, cell, _tied, fixed):
    """Every free cell parameter refined, every fixed one not: valid in every crystal system."""
    flags = tuple(n not in fixed for n in _CELL_NAMES)
    Phase[RP].model_validate(_phasep(sg, _cellp(cell, flags), {"A": _atomp(_GENERAL)}))


_CELL_SYSTEMS_WITH_RULES = [c for c in _CELL_SYSTEMS if c[2] or c[3]]  # P -1 has nothing to violate


@pytest.mark.parametrize("sg, cell, tied, fixed", _CELL_SYSTEMS_WITH_RULES,
                         ids=[c[0] for c in _CELL_SYSTEMS_WITH_RULES])
def test_cell_flag_rules_f1_f2(sg, cell, tied, fixed):
    """Only the first member of each tie group refined (F1) and every fixed angle refined (F2):
    one error at each fixed angle, then one at every member whose flag differs (review N1)."""
    flags = tuple(n not in tied for n in _CELL_NAMES)
    with pytest.raises(ValidationError) as exc_info:
        Phase[RP].model_validate(_phasep(sg, _cellp(cell, flags), {"A": _atomp(_GENERAL)}))
    assert [loc for loc, _m in _errs(exc_info)] == [("unit_cell", n) for n in fixed + tied]


def test_cell_flag_messages_name_the_group_and_the_fix():
    d = _phasep("P m -3 m", _cellp((4, 4, 4, 90, 90, 90), (True, False, True, False, False, True)),
                {"A": _atomp(_GENERAL)})
    with pytest.raises(ValidationError) as exc_info:
        Phase[RP].model_validate(d)
    assert _errs(exc_info) == [
        (("unit_cell", "gamma"), "cubic cell ('P m -3 m'): gamma is fixed by symmetry (= 90); "
                                 "set its refine flag to false"),
        (("unit_cell", "b"), "cubic cell ('P m -3 m'): a, b, c are one parameter; "
                             "set the same refine flag on all three"),
    ]


def test_rhombohedral_cell_ties_lengths_and_angles():
    d = _phasep("R -3 m:R", _cellp((5, 5, 5, 70, 70, 70), (False, False, False, True, True, False)),
                {"A": _atomp(_GENERAL)})
    with pytest.raises(ValidationError) as exc_info:
        Phase[RP].model_validate(d)
    assert _errs(exc_info) == [
        (("unit_cell", "gamma"), "trigonal cell ('R -3 m:R'): alpha, beta, gamma are one parameter; "
                                 "set the same refine flag on all three"),
    ]


def test_independent_groups_may_differ_f3():
    """F3: orthorhombic a refined, b and c fixed; general-position x refined, y and z fixed."""
    d = _phasep("P m m m", _cellp((4, 5, 6, 90, 90, 90), (True, False, False, False, False, False)),
                {"A": _atomp(_GENERAL, (True, False, False))})
    Phase[RP].model_validate(d)


@pytest.mark.parametrize("sg, cell, xyz, flags, expected", [
    ("P m -3 m", (4, 4, 4, 90, 90, 90), (0, 0, 0), (True, False, False),
     [("x", "atom 'A' (multiplicity 1 in 'P m -3 m'): x is fixed by symmetry (= 0); "
            "set its refine flag to false")]),
    ("P 63/m m c", (3, 3, 5, 90, 90, 120), (1 / 3, 2 / 3, 0.25), (False, True, False),
     [("y", "atom 'A' (multiplicity 2 in 'P 63/m m c'): y is fixed by symmetry (= 2/3); "
            "set its refine flag to false")]),
    ("P 63/m m c", (3, 3, 5, 90, 90, 120), (1 / 6, 1 / 3, 0.25), (True, False, False),
     [("y", "atom 'A' (multiplicity 6 in 'P 63/m m c'): x, y are one parameter (y = 2x); "
            "set the same refine flag on both")]),
    ("P 63/m m c", (3, 3, 5, 90, 90, 120), (1 / 6, 1 / 3, 0.25), (True, True, True),
     [("z", "atom 'A' (multiplicity 6 in 'P 63/m m c'): z is fixed by symmetry (= 1/4); "
            "set its refine flag to false")]),
    ("P -4 21 m", (5, 5, 4, 90, 90, 90), (0.1, 0.6, 0.3), (False, True, True),
     [("y", "atom 'A' (multiplicity 4 in 'P -4 21 m'): x, y are one parameter (y = x + 1/2); "
            "set the same refine flag on both")]),
    ("R -3 m:R", (5, 5, 5, 70, 70, 70), (0.1, 0.1, 0.1), (True, False, True),
     [("y", "atom 'A' (multiplicity 2 in 'R -3 m:R'): x, y, z are one parameter; "
            "set the same refine flag on all three")]),
    ("P 63/m m c", (3, 3, 5, 90, 90, 120), (1 / 6, 1 / 3, 0.25), (True, True, False), []),
    ("P 1 c 1", (5, 6, 7, 90, 98, 90), _GENERAL, (True, True, True), []),
])
def test_site_coordinate_flag_rules(sg, cell, xyz, flags, expected):
    d = _phasep(sg, _cellp(cell), {"A": _atomp(xyz, flags)})
    if not expected:
        Phase[RP].model_validate(d)
        return
    with pytest.raises(ValidationError) as exc_info:
        Phase[RP].model_validate(d)
    assert _errs(exc_info) == [(("atoms", "A", name), message) for name, message in expected]


def _u(values, flags=(False,) * 6, bounds=None):
    """Uaniso dict; with ``bounds`` (name -> (min, max), default open) 4-element lists."""
    tail = (lambda n: list(bounds.get(n, _N))) if bounds is not None else (lambda n: [])
    return {n: [v, f, *tail(n)] for n, v, f in zip(_U_NAMES, values, flags)}


def test_uij_flag_rules_several_groups_at_one_site():
    """6h in P6_3/mmc: U11 | U22=2*U12 | U33 free groups, U13 and U23 fixed (0)."""
    values = (0.01, 0.012, 0.009, 0.006, 0.0, 0.0)
    ok = _atomp((1 / 6, 1 / 3, 0.25), uaniso=_u(values, (True, True, False, True, False, False)), element="C")
    Phase[RP].model_validate(_phasep("P 63/m m c", _cellp((3, 3, 5, 90, 90, 120)), {"C": ok}))
    bad = _atomp((1 / 6, 1 / 3, 0.25), uaniso=_u(values, (False, True, False, False, True, False)), element="C")
    with pytest.raises(ValidationError) as exc_info:
        Phase[RP].model_validate(_phasep("P 63/m m c", _cellp((3, 3, 5, 90, 90, 120)), {"C": bad}))
    context = "atom 'C' (multiplicity 6 in 'P 63/m m c')"
    assert _errs(exc_info) == [
        (("atoms", "C", "Uaniso", "U13"), f"{context}: U13 is fixed by symmetry (= 0); set its refine flag to false"),
        (("atoms", "C", "Uaniso", "U12"), f"{context}: U22, U12 are one parameter (U12 = U22/2); "
                                          "set the same refine flag on both"),
    ]


def test_uij_negative_relation_group():
    """P-42_1m (0.1, 0.4, 0.3): U13 and U23 are one parameter with U23 = -U13."""
    values = (0.01, 0.01, 0.012, 0.001, 0.002, -0.002)
    a = _atomp((0.1, 0.4, 0.3), uaniso=_u(values, (False, False, False, False, True, False)))
    with pytest.raises(ValidationError) as exc_info:
        Phase[RP].model_validate(_phasep("P -4 21 m", _cellp((5, 5, 4, 90, 90, 90)), {"A": a}))
    assert _errs(exc_info) == [
        (("atoms", "A", "Uaniso", "U23"), "atom 'A' (multiplicity 4 in 'P -4 21 m'): U13, U23 are one "
                                          "parameter (U23 = -U13); set the same refine flag on both"),
    ]


def test_co_located_atoms_are_independent():
    """A104: atoms on the same site keep their own flags; nothing ties them."""
    cell = _cellp((4, 5, 6, 90, 90, 90))
    atoms = {"Li": _atomp(_GENERAL, (True, True, True), element="Li"),
             "Mg": _atomp(_GENERAL, (False, False, False), element="Mg")}
    phase = Phase[RP].model_validate(_phasep("P m m m", cell, atoms))
    assert phase.atoms["Li"].x.refine_flag is True and phase.atoms["Mg"].x.refine_flag is False


def test_flag_and_value_problems_reported_together():
    """One ValidationError lists the cell, coordinate and Uij rule violations (A70)."""
    cell = _cellp((3, 3, 5, 90, 90, 120), (True, False, False, False, False, False))
    atoms = {"A": _atomp((1 / 3, 2 / 3, 0.25), (True, False, False)),
             "B": _atomp((1 / 6, 1 / 3, 0.25), uaniso=_u((0.01, 0.012, 0.009, 0.006, 0, 0),
                                                         (False, False, False, False, False, True))),
             "C": _atomp(_GENERAL, element="Fe") | {"Multiplicity": 4}}
    with pytest.raises(ValidationError) as exc_info:
        Phase[RP].model_validate(_phasep("P 63/m m c", cell, atoms))
    assert [loc for loc, _m in _errs(exc_info)] == [
        ("unit_cell", "b"), ("atoms", "A", "x"), ("atoms", "B", "Uaniso", "U23"), ("atoms", "C", "Multiplicity")]


# --- F4: bounds follow the tie (affine; A98, A108) and A106 -------------------

_HEX = (3, 3, 5, 90, 90, 120)


def _bounded_phase(sg, cell, xyz, flags, bounds, **kw):
    return _phasep(sg, _cellp(cell, bounds={}), {"A": _atomp(xyz, flags, bounds=bounds, **kw)})


@pytest.mark.parametrize("xyz, x_bounds, y_bounds", [
    ((0.1, 0.6, 0.3), (0.0, 0.2), (0.5, 0.7)),        # y = x + 1/2
    ((0.1, 0.4, 0.3), (0.0, 0.2), (0.3, 0.5)),        # y = -x + 1/2: swapped
    ((0.1, -0.4, 0.3), (0.0, 0.2), (-0.5, -0.3)),     # y = x - 1/2: the stated translate counts
    ((0.1, 0.4, 0.3), (0.0, None), (None, 0.5)),      # open ends map to the matching side
    ((0.1, 0.4, 0.3), (None, 0.2), (0.3, None)),
    ((0.1, 0.4, 0.3), (None, None), (None, None)),
])
def test_affine_bounds_follow_the_tie_p_421m_4e(xyz, x_bounds, y_bounds):
    """Review B1: at P-42_1m 4e equal bounds would be wrong; the affine map is right."""
    d = _bounded_phase("P -4 21 m", (5, 5, 4, 90, 90, 90), xyz, (True, True, False),
                       {"x": x_bounds, "y": y_bounds})
    phase = Phase[BRP].model_validate(d)
    assert phase.atoms["A"].y.model_dump()[2:] == list(y_bounds)


def test_affine_bounds_p42mnm_4f():
    """P4_2/mnm (0.3, 0.7, 0): y = -x + 1; z fixed (A106: no bounds)."""
    d = _bounded_phase("P 42/m n m", (5, 5, 3, 90, 90, 90), (0.3, 0.7, 0.0), (True, True, False),
                       {"x": (0.25, 0.35), "y": (0.65, 0.75)})
    Phase[BRP].model_validate(d)
    d["atoms"]["A"]["y"][2:] = [0.25, 0.35]  # equal bounds: wrong for an affine tie
    with pytest.raises(ValidationError) as exc_info:
        Phase[BRP].model_validate(d)
    assert _errs(exc_info) == [(("atoms", "A", "y"), "value (0.7) is above max (0.35)")]


def test_bounds_not_following_the_tie_rejected_at_the_member():
    d = _bounded_phase("P -4 21 m", (5, 5, 4, 90, 90, 90), (0.1, 0.4, 0.3), (True, True, False),
                       {"x": (0.0, 0.2), "y": (0.3, 0.51)})
    with pytest.raises(ValidationError) as exc_info:
        Phase[BRP].model_validate(d)
    assert _errs(exc_info) == [(("atoms", "A", "y"),
                                "atom 'A' (multiplicity 4 in 'P -4 21 m'): the bounds of y must follow "
                                "y = -x + 1/2 from the bounds of x [0.0, 0.2]: write [0.3, 0.5], not [0.3, 0.51]")]


def test_bounds_open_side_must_match():
    d = _bounded_phase("P -4 21 m", (5, 5, 4, 90, 90, 90), (0.1, 0.4, 0.3), (True, True, False),
                       {"x": (0.0, 0.2), "y": (None, 0.5)})
    with pytest.raises(ValidationError) as exc_info:
        Phase[BRP].model_validate(d)
    assert _errs(exc_info)[0][1].endswith("write [0.3, 0.5], not [null, 0.5]")


def test_tied_coordinate_bounds_read_within_6_decimals():
    """A121 (replaces A115's exact tied bounds): a tied member's bounds are derived from the first
    member's like its value; 4e-6 off is read as [0.3, 0.5], 1e-5 off is an error giving them."""
    def phase(y_bounds):
        return _bounded_phase("P -4 21 m", (5, 5, 4, 90, 90, 90), (0.1, 0.4, 0.3), (True, True, False),
                              {"x": (0.0, 0.2), "y": y_bounds})

    assert Phase[BRP].model_validate(phase((0.300004, 0.5))).atoms["A"].y.model_dump() == [0.4, True, 0.3, 0.5]
    with pytest.raises(ValidationError) as exc_info:
        Phase[BRP].model_validate(phase((0.30001, 0.5)))
    assert _errs(exc_info) == [(("atoms", "A", "y"),
                                "atom 'A' (multiplicity 4 in 'P -4 21 m'): the bounds of y must follow "
                                "y = -x + 1/2 from the bounds of x [0.0, 0.2]: write [0.3, 0.5], not [0.30001, 0.5]")]


def test_tied_uij_bounds_factor_two():
    """6h: U12 = U22/2, so U22 in [0, 0.02] gives U12 in [0, 0.01]; within 1e-6 A^2 read as those (A98,
    A121), further off an error giving them."""
    values = (0.01, 0.012, 0.009, 0.006, 0.0, 0.0)
    flags = (True, True, True, True, False, False)

    def phase(u12_bounds):
        bounds = {"U22": (0.0, 0.02), "U12": u12_bounds}
        a = _atomp((1 / 6, 1 / 3, 0.25), bounds={}, uaniso=_u(values, flags, bounds), element="C")
        return _phasep("P 63/m m c", _cellp(_HEX, bounds={}), {"C": a})

    assert Phase[BRP].model_validate(phase((0.0, 0.01))).atoms["C"].Uaniso.U12.model_dump() == [0.006, True, 0.0, 0.01]
    assert Phase[BRP].model_validate(phase((0.0, 0.0100009))).atoms["C"].Uaniso.U12.model_dump() == [0.006, True, 0.0, 0.01]
    with pytest.raises(ValidationError) as exc_info:
        Phase[BRP].model_validate(phase((0.0, 0.010002)))
    assert _errs(exc_info) == [(("atoms", "C", "Uaniso", "U12"),
                                "atom 'C' (multiplicity 6 in 'P 63/m m c'): the bounds of U12 must follow "
                                "U12 = U22/2 from the bounds of U22 [0.0, 0.02]: write [0.0, 0.01], "
                                "not [0.0, 0.010002]")]


def test_tied_cell_bounds_follow_the_first_member():
    """Cell ties are equalities: a member's bounds are the first member's, within CELL_TOL (1e-9, relative
    on lengths; A77, A123), and the model holds them exactly; further off is an error giving them."""
    def phase(b_max):
        cell = _cellp((4, 4, 4, 90, 90, 90), (True, True, True, False, False, False),
                      {"a": (3.9, 4.2), "b": (3.9, b_max), "c": (3.9, 4.2)})
        return _phasep("P m -3 m", cell, {"A": _atomp(_GENERAL, bounds={})})

    for b_max in (4.2 + 1e-15, 4.200000001):
        assert Phase[BRP].model_validate(phase(b_max)).unit_cell.b.model_dump() == [4.0, True, 3.9, 4.2]
    with pytest.raises(ValidationError) as exc_info:
        Phase[BRP].model_validate(phase(4.20001))
    assert _errs(exc_info) == [(("unit_cell", "b"),
                                "cubic cell ('P m -3 m'): the bounds of b must follow b = a from the bounds "
                                "of a [3.9, 4.2]: write [3.9, 4.2], not [3.9, 4.20001]")]


def test_symmetry_fixed_parameters_have_no_bounds_a106():
    """A fixed parameter must have null bounds; a refine flag on it is F2 (two errors, one field)."""
    cell = _cellp((4, 4, 4, 90, 90, 90), bounds={"alpha": (89.0, 91.0)})
    atom = _atomp((0.0, 0.0, 0.0), (True, False, False), bounds={"x": (-0.1, 0.1)},
                  uaniso=_u((0.01, 0.01, 0.01, 0.0, 0.0, 0.0), bounds={"U12": (None, 0.001)}), element="La")
    with pytest.raises(ValidationError) as exc_info:
        Phase[BRP].model_validate(_phasep("P m -3 m", cell, {"La": atom}))
    context = "atom 'La' (multiplicity 1 in 'P m -3 m')"
    assert _errs(exc_info) == [
        (("unit_cell", "alpha"), "cubic cell ('P m -3 m'): alpha is fixed by symmetry (= 90); "
                                 "give it no bounds (min and max null)"),
        (("atoms", "La", "x"), f"{context}: x is fixed by symmetry (= 0); set its refine flag to false"),
        (("atoms", "La", "x"), f"{context}: x is fixed by symmetry (= 0); give it no bounds (min and max null)"),
        (("atoms", "La", "Uaniso", "U12"), f"{context}: U12 is fixed by symmetry (= 0); "
                                           "give it no bounds (min and max null)"),
    ]


# --- names and cell bound domain (re/03b review C5, C6) ----------------------


_NAME_RULE = "must start with a letter and contain only ASCII letters, digits and '_' (e.g. 'O1', 'LaB6_a')"


@pytest.mark.parametrize("label, message", [
    ("", "a name must not be empty or blank"),
    ("  ", "a name must not be empty or blank"),
    ("O.1", f"name 'O.1' {_NAME_RULE}"),
    (" O1", f"name ' O1' {_NAME_RULE}"),
    ("O 1", f"name 'O 1' {_NAME_RULE}"),
    ("O-1", f"name 'O-1' {_NAME_RULE}"),
    ("1O", f"name '1O' {_NAME_RULE}"),
    ("_O1", f"name '_O1' {_NAME_RULE}"),
    ("Oé", f"name 'Oé' {_NAME_RULE}"),
    ("O/1", f"name 'O/1' {_NAME_RULE}"),
])
def test_atom_label_follows_the_name_rule(label, message):
    """Atom labels: a letter, then ASCII letters, digits or '_' (every engine can use it; review C6)."""
    d = _valid_pmm_lab6_phase_dict()
    d["atoms"][label] = d["atoms"].pop("B1")
    with pytest.raises(ValidationError) as exc_info:
        Phase[RP].model_validate(d)
    assert _errs(exc_info) == [(("atoms", label, "[key]"), message)]


def test_atom_labels_following_the_rule_accepted():
    d = _valid_pmm_lab6_phase_dict()
    d["atoms"]["B_site2"] = d["atoms"].pop("B1")
    assert "B_site2" in Phase[RP].model_validate(d).atoms


def test_names_unique_ignoring_case():
    from powderline.schema_core import check_names_unique_ignoring_case

    check_names_unique_ignoring_case(["LaB6", "Si", "Al2O3"], "phase")
    with pytest.raises(ValueError) as exc_info:
        check_names_unique_ignoring_case(["LaB6", "Si", "lab6"], "phase")
    assert str(exc_info.value) == "phase 'LaB6' and 'lab6' differ only in case; rename one"


@pytest.mark.parametrize("label, message", [
    ("None", "name 'None' is a Python keyword; choose another name"),
    ("class", "name 'class' is a Python keyword; choose another name"),
    ("O" * 65, f"name {'O' * 20!r}... has 65 characters; the limit is 64"),
])
def test_atom_label_is_an_identifier_of_bounded_length(label, message):
    """Names are Python identifiers (no keywords) and at most 64 characters (file names)."""
    d = _valid_pmm_lab6_phase_dict()
    d["atoms"][label] = d["atoms"].pop("B1")
    with pytest.raises(ValidationError) as exc_info:
        Phase[RP].model_validate(d)
    assert _errs(exc_info) == [(("atoms", label, "[key]"), message)]


def test_atom_label_of_64_characters_accepted():
    d = _valid_pmm_lab6_phase_dict()
    d["atoms"]["B" * 64] = d["atoms"].pop("B1")
    assert "B" * 64 in Phase[RP].model_validate(d).atoms


def test_core_name_json_schema_constrains_every_key():
    import keyword

    from powderline.schema_core import NAME_PATTERN

    atoms = Phase[RP].model_json_schema()["properties"]["atoms"]
    assert atoms["propertyNames"] == {"pattern": NAME_PATTERN, "maxLength": 64,
                                      "not": {"enum": keyword.kwlist}}
    assert atoms["additionalProperties"] == {"$ref": "#/$defs/Atom"}
    assert "patternProperties" not in atoms


@pytest.mark.parametrize("name, bounds, message", [
    ("a", (0.0, 10.0), "cell length a: min must be positive (a cell length is), got 0.0; use null for no lower bound"),
    ("c", (-1.0, None), "cell length c: min must be positive (a cell length is), got -1.0; use null for no lower bound"),
    ("beta", (0.0, 120.0), "cell angle beta: min must be between 0 and 180 degrees (a cell angle is), got 0.0; "
                           "use null for no min bound"),
    ("beta", (90.0, 180.0), "cell angle beta: max must be between 0 and 180 degrees (a cell angle is), got 180.0; "
                            "use null for no max bound"),
])
def test_cell_bounds_lie_in_the_cell_domain(name, bounds, message):
    """A stated bound outside where a cell parameter exists is an error (lengths > 0, angles in (0, 180))."""
    values = (9.0, 5.0, 7.0, 90, 105.0, 90)
    cell = _cellp(values, flags=(True, True, True, False, True, False), bounds={name: bounds})
    d = _phasep("C 1 2/m 1", cell, {"O": _atomp(_GENERAL, bounds={})})
    with pytest.raises(ValidationError) as exc_info:
        Phase[BRP].model_validate(d)
    assert _errs(exc_info) == [(("unit_cell", name), message)]


def test_cell_open_bounds_and_positive_bounds_accepted():
    values = (9.0, 5.0, 7.0, 90, 105.0, 90)
    cell = _cellp(values, flags=(True, True, True, False, True, False),
                  bounds={"a": (8.0, 10.0), "b": (None, 6.0), "beta": (95.0, 115.0)})
    phase = Phase[BRP].model_validate(_phasep("C 1 2/m 1", cell, {"O": _atomp(_GENERAL, bounds={})}))
    assert phase.unit_cell.a.model_dump() == [9.0, True, 8.0, 10.0]


# --- non-positive-definite Uaniso (A118) -------------------------------------


def _p1_uaniso_phase(u):
    keys = ("U11", "U22", "U33", "U12", "U13", "U23")
    atom = {"element": "O", "x": [0.1, False], "y": [0.2, False], "z": [0.3, False], "occupancy": [1.0, False],
            "ADP": "Uaniso", "Uaniso": {k: [v, False] for k, v in zip(keys, u)}}
    return {"space_group": "P 1",
            "unit_cell": {k: [v, False] for k, v in zip(_CELL_NAMES, (5.0, 6.0, 7.0, 80.0, 85.0, 95.0))},
            "atoms": {"O1": atom}}


def test_uaniso_not_positive_definite_warns_and_keeps_the_values():
    """A118: informative, never an error or a change; the same recipe gives the same warning again."""
    d = _p1_uaniso_phase((0.01, 0.01, 0.01, 0.02, 0.0, 0.0))  # Uij matrix eigenvalues -0.01, 0.01, 0.03
    phase = Phase[RP].model_validate(d)
    assert phase.model_dump() == d
    expected = [{"code": "uaniso_not_positive_definite",
                 "message": "atom 'O1' (multiplicity 1 in 'P 1'): Uaniso is not positive definite (principal "
                            "mean-square displacements -0.0112, 0.00981, 0.0288 A^2), so it describes no thermal "
                            "ellipsoid; it is used as stated",
                 "field_path": "atoms.O1.Uaniso"}]
    assert phase.warnings() == expected
    assert Phase[RP].model_validate(phase.model_dump()).warnings() == expected


def test_uaniso_positive_definite_gives_no_warning():
    phase = Phase[RP].model_validate(_p1_uaniso_phase((0.01, 0.012, 0.009, 0.002, -0.001, 0.0005)))
    assert phase.warnings() == []


from powderline.schema_core import _principal_msd  # noqa: E402
from powderline.symmetry import _metric, check_cell  # noqa: E402


def _isotropic_uij(cell, u_iso):
    """U^ij of an isotropic U in ``cell``: u_iso * G*^ij / (a*_i a*_j)."""
    g = np.linalg.inv(_metric(cell))
    rec = np.sqrt(np.diag(g))
    u = u_iso * g / np.outer(rec, rec)
    return (u[0, 0], u[1, 1], u[2, 2], u[0, 1], u[0, 2], u[1, 2])


@pytest.mark.parametrize("cell", [(5.0, 6.0, 7.0, 80.0, 85.0, 95.0), (3.2, 3.2, 5.2, 90.0, 90.0, 120.0)])
def test_principal_mean_square_displacements_are_cartesian(cell):
    """A118 (re/03b PR review N4): the warning gives the Cartesian principal values; an isotropic U has
    three equal ones in any cell, although its Uij matrix does not (hexagonal U12 = U11/2)."""
    assert np.allclose(_principal_msd(cell, _isotropic_uij(cell, -0.01)), -0.01)


def test_uaniso_not_positive_definite_isotropic_hexagonal_message():
    """N4: a negative isotropic tensor on hexagonal axes reports -0.01 three times, not the Uij matrix's
    -0.015, -0.01, -0.005."""
    d = _p1_uaniso_phase(_isotropic_uij((3.2, 3.2, 5.2, 90.0, 90.0, 120.0), -0.01))
    d["unit_cell"] = {k: [v, False] for k, v in zip(_CELL_NAMES, (3.2, 3.2, 5.2, 90.0, 90.0, 120.0))}
    (warning,) = Phase[RP].model_validate(d).warnings()
    assert "principal mean-square displacements -0.01, -0.01, -0.01 A^2" in warning["message"]


def test_uaniso_semidefinite_always_warns():
    """N4: a zero principal value is <= 0 whatever the floating-point noise (rank-1 tensor)."""
    for v in (0.01, 0.03, 0.07, 0.11, 0.013):
        (warning,) = Phase[RP].model_validate(_p1_uaniso_phase((v,) * 6)).warnings()
        assert warning["code"] == "uaniso_not_positive_definite"



# --- one rule for symmetry-determined values (A121; re/03b PR review S1, S3, Q1) ----------------

_HEX_CELL = (3.2, 3.2, 5.2, 90.0, 90.0, 120.0)
_SPECIAL_VALUE_CASES = [
    # (case, space group, cell, stated xyz, model xyz or the error) -- the table in SCHEMA_HISTORY
    ("fixed 1/2 written 0.4999999", "P m -3 m", (4.0, 4.0, 4.0, 90.0, 90.0, 90.0), (0.4999999, 0.0, 0.0),
     "write x = 0.5"),
    ("fixed 1/3 written 0.333333", "P 63/m m c", _HEX_CELL, (0.333333, 0.666667, 0.25), (1 / 3, 2 / 3, 0.25)),
    ("fixed 1/3 written to 13 digits", "P 63/m m c", _HEX_CELL, (0.3333333333333, 0.6666666666667, 0.25),
     (1 / 3, 2 / 3, 0.25)),
    ("ideal C14 6h (x, 2x - 1, 1/4)", "P 63/m m c", _HEX_CELL, (0.833333, 0.666667, 0.25),
     (0.833333, float(2 * Fraction(0.833333) - 1), 0.25)),
    ("y = 2x written 0.2000001", "P 6/m m m", _HEX_CELL, (0.1, 0.2000001, 0.0), (0.1, 0.2, 0.0)),
    ("y = x/2 of a 6-decimal x", "P 6/m m m", _HEX_CELL, (0.333333, 0.166667, 0.0),
     (0.333333, float(Fraction(0.333333) / 2), 0.0)),
    ("y = x + 1/3 written 0.4", "R -3 m:H", (4.0, 4.0, 20.0, 90.0, 90.0, 120.0), (0.066667, 0.4, 0.166667),
     (0.066667, float(Fraction(0.066667) + Fraction(1, 3)), 1 / 6)),
]


@pytest.mark.parametrize("case, sg, cell, xyz, expected", _SPECIAL_VALUE_CASES, ids=[c[0] for c in _SPECIAL_VALUE_CASES])
def test_symmetry_determined_values_follow_one_rule(case, sg, cell, xyz, expected):
    """A121: a constant with a decimal form is exact; a third is read from 6 decimals; a value derived from
    another stated value is read within 6 decimals; the model holds the derived value, and its dump
    validates as itself."""
    d = {"space_group": sg, "unit_cell": dict(zip(_CELL_NAMES, ([v, False] for v in cell))),
         "atoms": {"A": {"element": "O", **{k: [v, False] for k, v in zip("xyz", xyz)},
                         "occupancy": [1.0, False], "ADP": "Uiso", "Uiso": [0.01, False]}}}
    if isinstance(expected, str):
        with pytest.raises(ValidationError) as exc_info:
            Phase[RP].model_validate(d)
        assert exc_info.value.errors()[0]["msg"].endswith(expected)
        return
    phase = Phase[RP].model_validate(d)
    assert tuple(getattr(phase.atoms["A"], k).value for k in "xyz") == expected
    # P-34: one info note per coordinate the model holds in derived form; none for one stated exactly
    moved = {f"atoms.A.{k}" for k, stated_v, held in zip("xyz", xyz, expected) if stated_v != held}
    assert {(w["code"], w["level"]) for w in phase.warnings()} <= {("symmetry_value_derived", "info")}
    assert {w["field_path"] for w in phase.warnings()} == moved
    assert Phase[RP].model_validate(phase.model_dump()).model_dump() == phase.model_dump()


def test_equal_ties_are_named_in_the_message():
    """N3: an equal tie is a relation too (12j (1/2, y, y): z = y)."""
    d = {"space_group": "P m -3 m", "unit_cell": dict(zip(_CELL_NAMES, ([v, False] for v in (4.0, 4.0, 4.0, 90, 90, 90)))),
         "atoms": {"A": {"element": "O", "x": [0.4999999, False], "y": [0.2, False], "z": [0.2, False],
                         "occupancy": [1.0, False], "ADP": "Uiso", "Uiso": [0.01, False]}}}
    with pytest.raises(ValidationError) as exc_info:
        Phase[RP].model_validate(d)
    assert _errs(exc_info) == [(("atoms", "A"), "atom 'A' (multiplicity 12 in 'P m -3 m'): (0.4999999, 0.2, 0.2) is "
                                                "1e-07 from a special position, not on it (x = 1/2, z = y); write x = 0.5")]


def test_cell_holds_the_first_members_values():
    """A123: tied cell values within CELL_TOL are the first member's in the model (b = a exactly), and fixed
    angles are exact; the error states the stated values and gives the ones to write."""
    d = _valid_pmm_lab6_phase_dict()
    d["unit_cell"]["b"] = [4.15692 * (1 + 5e-10), False]
    d["unit_cell"]["gamma"] = [90 + 5e-10, False]
    cell = Phase[RP].model_validate(d).unit_cell
    assert (cell.b.value, cell.gamma.value) == (4.15692, 90.0)
    d["unit_cell"]["b"] = [4.15692 * (1 + 5e-9), False]
    d["unit_cell"]["gamma"] = [90.1, False]
    with pytest.raises(ValidationError) as exc_info:
        Phase[RP].model_validate(d)
    assert _errs(exc_info) == [(("unit_cell",), "unit cell is inconsistent with 'P m -3 m' (cubic): stated "
                                                f"b = {4.15692 * (1 + 5e-9)!r}, gamma = 90.1, but by symmetry "
                                                "gamma = 90, b = a; write b = 4.15692, gamma = 90.0")]


def test_fixed_cell_angles_are_exact_in_every_setting():
    """A123: every gemmi setting's fixed angles are 90, or 120 for gamma on hexagonal axes; a cell built
    from them passes the metric check (A77)."""
    import gemmi

    from powderline.schema_core import _fixed_cell_angle
    from powderline.symmetry import cell_tie_groups

    for sg in gemmi.spacegroup_table():
        ties = cell_tie_groups(sg.xhm())
        cell = {"a": 5.1, "b": 6.2, "c": 7.3, "alpha": 81.0, "beta": 86.0, "gamma": 97.0}
        for group in ties.groups:
            for member in group.members[1:]:
                cell[member] = cell[group.members[0]]
        cell.update({name: float(_fixed_cell_angle(ties, name)) for name in ties.fixed})
        check_cell(sg.xhm(), tuple(cell[k] for k in _CELL_NAMES))


def test_tied_values_and_bounds_derived_together_stay_ordered():
    """N1: a member's value and bounds are both derived from the first member's, so a value at its bound
    stays within it, and the dump validates."""
    cell = {k: [*v, None, None] for k, v in _R3M_CELL.items()}
    atom = {"element": "O", "x": [0.2, False, 0.0, 0.2], "y": [0.5333333333333334, False, 0.333333, 0.533334],
            "z": [0.166667, False, None, None], "occupancy": [1.0, False, None, None],
            "ADP": "Uiso", "Uiso": [0.01, False, None, None]}
    phase = Phase[BRP].model_validate({"space_group": "R -3 m:H", "unit_cell": cell, "atoms": {"O1": atom}})
    y = phase.atoms["O1"].y
    assert y.min <= y.value <= y.max
    assert Phase[BRP].model_validate(phase.model_dump()).model_dump() == phase.model_dump()


def test_uij_within_floating_point_precision_held_exactly():
    """N2: no message without a value to write; the model holds the derived tensor."""
    keys = ("U11", "U22", "U33", "U12", "U13", "U23")
    values = (0.01, 0.01 + 9.5e-13, 0.02, 0.005 - 9.5e-13, 0.0, 0.0)
    d = {"space_group": "P 6/m m m", "unit_cell": dict(zip(_CELL_NAMES, ([v, False] for v in _HEX_CELL))),
         "atoms": {"A": {"element": "O", "x": [0.0, False], "y": [0.0, False], "z": [0.0, False],
                         "occupancy": [1.0, False], "ADP": "Uaniso", "Uaniso": {k: [v, False] for k, v in zip(keys, values)}}}}
    u = Phase[RP].model_validate(d).atoms["A"].Uaniso
    assert (u.U22.value, u.U12.value) == (0.01, 0.005)


# --- names (A112 amended: atom labels unique ignoring case; re/03b PR review N8) ----------------


def test_atom_labels_unique_ignoring_case():
    d = _valid_pmm_lab6_phase_dict()
    d["atoms"]["la1"] = d["atoms"]["La1"]
    with pytest.raises(ValidationError) as exc_info:
        Phase[RP].model_validate(d)
    assert _errs(exc_info) == [(("atoms", "la1"), "atom labels 'La1' and 'la1' differ only in case; rename one")]


# --- engine subclass guard layers (A122; re/03b PR review S2, N5) -------------------------------


def test_phase_parameter_type_must_be_a_core_parameter_type():
    from typing import Generic

    from powderline.schema_core import P

    with pytest.raises(TypeError, match=r"the parameter type must be RefinableParameter or BoundedRefinableParameter, "
                                        r"not <class 'float'>"):
        Phase[float]

    class EnginePhase(Phase[P], Generic[P]):
        pass

    with pytest.raises(TypeError, match="not <class 'int'>"):
        EnginePhase[int]


def test_phase_mixin_cannot_replace_a_core_validator():
    """A mixin placed before Phase is collected first by pydantic; its same-named validator would win."""
    from pydantic import BaseModel

    class Mixin(BaseModel):
        @field_validator("space_group", check_fields=False)
        @classmethod
        def _space_group(cls, v):
            return v

    class PlainMixin:
        @model_validator(mode="after")
        def _sites_check(self):
            return self

    for mixin, name in ((Mixin, "_space_group"), (PlainMixin, "_sites_check")):
        with pytest.raises(TypeError, match=f"^{mixin.__name__} reuses the core phase name\\(s\\) {name};"):
            type("EnginePhase", (mixin, Phase[RP]), {"__module__": __name__})


def test_phase_mixin_cannot_redeclare_a_core_field():
    from pydantic import BaseModel

    class Mixin(BaseModel):
        space_group: str = "P 1"

    with pytest.raises(TypeError, match=r"^Mixin redeclares the core phase field\(s\) space_group;"):
        class EnginePhase(Mixin, Phase[RP]):
            pass


@pytest.mark.parametrize("name, body", [
    ("_engine_wrap", "@model_validator(mode='wrap')\n@classmethod\ndef _engine_wrap(cls, data, handler):\n    return handler(data)"),
    ("_engine_before", "@model_validator(mode='before')\n@classmethod\ndef _engine_before(cls, data):\n    return data"),
    ("_snap", "@field_validator('atoms', mode='before')\n@classmethod\ndef _snap(cls, v):\n    return v"),
    ("_all", "@field_validator('*', mode='wrap')\n@classmethod\ndef _all(cls, v, handler):\n    return handler(v)"),
    ("_sg", "@field_validator('space_group', mode='plain')\n@classmethod\ndef _sg(cls, v):\n    return v"),
])
def test_phase_validators_that_could_rewrite_the_recipe_rejected(name, body):
    """A122: a 'before', 'wrap' or 'plain' validator could rewrite the recipe before core reads it (e.g.
    round 0.4999999 to 0.5, A115) or skip core's validation."""
    namespace = {"field_validator": field_validator, "model_validator": model_validator, "Phase": Phase, "RP": RP}
    source = "class EnginePhase(Phase[RP]):\n    scale: RP\n" + "\n".join("    " + line for line in body.splitlines())
    with pytest.raises(TypeError, match=f"^EnginePhase: validator\\(s\\) {name} must be 'after' validators"):
        exec(source, namespace)


def test_phase_engine_before_validator_on_its_own_field_allowed():
    class EnginePhase(Phase[RP]):
        scale: RP

        @field_validator("scale", mode="before")
        @classmethod
        def _scale_shape(cls, v):
            return v

        @model_validator(mode="after")
        def _engine_check(self):
            return self

    assert EnginePhase.model_validate({**_valid_pmm_lab6_phase_dict(), "scale": [1.0, True]}).scale.value == 1.0


@pytest.mark.parametrize("name, body", [
    ("__init__", "def __init__(self, **data):\n    super().__init__(**data)"),
    ("model_post_init", "def model_post_init(self, context):\n    pass"),
    ("model_validate", "@classmethod\ndef model_validate(cls, obj, **kw):\n    return cls.model_construct(**obj)"),
    ("__get_pydantic_core_schema__", "@classmethod\ndef __get_pydantic_core_schema__(cls, source, handler):\n    return handler(source)"),
    ("__pydantic_init_subclass__", "@classmethod\ndef __pydantic_init_subclass__(cls, **kw):\n    pass"),
])
def test_phase_entry_points_cannot_be_overridden(name, body):
    """A122: an override could skip or replace core's validation without reusing a core name."""
    namespace = {"Phase": Phase, "RP": RP}
    source = "class EnginePhase(Phase[RP]):\n" + "\n".join("    " + line for line in body.splitlines())
    with pytest.raises(TypeError, match=f"^EnginePhase defines {name}; a phase model may not override"):
        exec(source, namespace)


def test_phase_guard_sees_a_replaced_core_validator():
    """A122 layer 2: whatever the route, every core validator must still be core's own function."""
    import dataclasses

    class EnginePhase(Phase[RP]):
        pass

    validators = EnginePhase.__pydantic_decorators__.field_validators
    validators["_space_group"] = dataclasses.replace(validators["_space_group"], func=lambda cls, v: v)
    with pytest.raises(TypeError, match=r"^EnginePhase replaces the core validator\(s\) _space_group"):
        EnginePhase.__pydantic_init_subclass__()


def test_fit_limits_on_data_snap_to_weighted_points_inside():
    """A149: each stated end moves onto the first/last weighted data point inside the window."""
    from powderline.schema_core import FitRange, XRDData, fit_limits_on_data
    xrd = XRDData(tth=[1.0, 1.5, 2.0, 2.5, 3.0, 3.5], Itth=[1.0] * 6, Itth_weights=[1, 0, 1, 1, 0, 1])
    assert fit_limits_on_data(FitRange.model_validate([1.2, 3.2]), xrd) == (2.0, 2.5)  # zero-weight 1.5, 3.0 skipped
    assert fit_limits_on_data(FitRange.model_validate([2.0, 3.5]), xrd) == (2.0, 3.5)  # ends on points stay
    assert fit_limits_on_data(FitRange.model_validate([None, 3.2]), xrd) == (1.0, 2.5)  # open end: the data's first
    assert fit_limits_on_data(None, xrd) == (1.0, 3.5)


def test_fit_limits_on_data_open_ends_skip_zero_weight_edges():
    """A154: an open end is the first/last weighted point, so zero-weight edge points never widen an engine's window."""
    from powderline.schema_core import FitRange, XRDData, fit_limits_on_data
    xrd = XRDData(tth=[1.0, 1.5, 2.0, 2.5, 3.0, 3.5], Itth=[1.0] * 6, Itth_weights=[0, 0, 1, 1, 1, 0])
    assert fit_limits_on_data(None, xrd) == (2.0, 3.0)
    assert fit_limits_on_data(FitRange.model_validate([None, None]), xrd) == (2.0, 3.0)
    assert fit_limits_on_data(FitRange.model_validate([1.2, None]), xrd) == (2.0, 3.0)


def test_fit_range_without_a_weighted_point_rejected():
    from powderline.schema_core import FitRange, XRDData, check_fit_range_within_data
    xrd = XRDData(tth=[1.0, 1.5, 2.0], Itth=[1.0] * 3, Itth_weights=[1, 0, 1])
    with pytest.raises(ValueError, match=r"fit_range \[1.2, 1.8\] holds 0 data point\(s\) with a positive weight"):
        check_fit_range_within_data(FitRange.model_validate([1.2, 1.8]), xrd)


def test_fit_limits_on_data_one_weighted_point_rejected():
    """A154 N9 (P-04): a one-point window is refused; the message names the count and the window."""
    from powderline.schema_core import FitRange, XRDData, fit_limits_on_data
    xrd = XRDData(tth=[1.0, 1.5, 2.0, 2.5], Itth=[1.0] * 4, Itth_weights=[1, 1, 0, 1])
    with pytest.raises(ValueError, match=r"fit_range \[1.4, 2.2\] holds 1 data point\(s\) with a positive weight; "
                                         r"at least 2 are required"):
        fit_limits_on_data(FitRange.model_validate([1.4, 2.2]), xrd)  # 1.5 only: 2.0 has zero weight
    with pytest.raises(ValueError, match=r"fit_range \[None, None\] holds 1 data point"):
        fit_limits_on_data(None, XRDData(tth=[1.0], Itth=[1.0], Itth_weights=[1.0]))  # a one-point pattern


def test_fit_limits_on_data_two_weighted_points_ok():
    """A154 N9: two weighted points are the floor; the limits land on them."""
    from powderline.schema_core import FitRange, XRDData, fit_limits_on_data
    xrd = XRDData(tth=[1.0, 1.5, 2.0, 2.5], Itth=[1.0] * 4, Itth_weights=[1, 1, 0, 1])
    assert fit_limits_on_data(FitRange.model_validate([1.4, 2.6]), xrd) == (1.5, 2.5)
    assert fit_limits_on_data(FitRange.model_validate([None, 1.5]), xrd) == (1.0, 1.5)
    assert fit_limits_on_data(None, XRDData(tth=[1.0, 2.0], Itth=[1.0, 1.0], Itth_weights=[1.0, 1.0])) == (1.0, 2.0)


def test_check_fit_range_within_data_open_window_needs_two_weighted_points():
    """A154 N9: the two-point rule holds for the open window too (no fit_range), so validation refuses it."""
    from powderline.schema_core import XRDData, check_fit_range_within_data
    with pytest.raises(ValueError, match=r"holds 1 data point\(s\)"):
        check_fit_range_within_data(None, XRDData(tth=[1.0, 2.0], Itth=[1.0, 1.0], Itth_weights=[0.0, 1.0]))
    check_fit_range_within_data(None, XRDData(tth=[1.0, 2.0], Itth=[1.0, 1.0], Itth_weights=[1.0, 1.0]))  # ok


# --- structured warning level (P-34) -------------------------------------------------------------

from powderline.exceptions import StructuredWarning as _SW  # noqa: E402
from powderline.schema_core import collect_warnings as _collect  # noqa: E402


def test_collect_warnings_preserves_level_and_leaves_it_absent_otherwise():
    class Leaf(BaseModel):
        def warnings(self):
            return [_SW(code="c", message="m", field_path="x", level="info"),
                    {"code": "d", "message": "n", "field_path": None}]

    class Root(BaseModel):
        leaf: Leaf

    found = _collect(Root(leaf=Leaf()))
    assert [w["code"] for w in found] == ["c", "d"]
    assert found[0]["level"] == "info" and found[0]["field_path"] == "leaf.x"
    assert "level" not in found[1]  # absent means "warning"; consumers use .get("level", "warning")
