"""Native ``easydiffraction.rietveld`` schema tests (re/06).

Tests the easydiffraction gateway schema against the rules documented in
src/powderline/gateways/easydiffraction/schema.py module docstring.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import numpy as np
import pytest

from pydantic import ValidationError

from powderline.gateways.easydiffraction.schema import (

    easydiffraction_space_group,
    validate_recipe,
)
from powderline.schema_core import parameters_requested

pytestmark = pytest.mark.core

DATA = Path(__file__).resolve().parent / "data"


def P(value, flag=False, lo=None, hi=None):
    """Bounded refinable parameter [value, refine_flag, min, max]."""
    return [value, flag, lo, hi]


def _errors(exc) -> list[tuple]:
    return [(e["loc"], e["type"]) for e in exc.value.errors()]


def _fails(recipe, loc, kind=None):
    """Assert that validation fails with an error at the given location and optionally of a given type."""
    with pytest.raises(ValidationError) as exc:
        validate_recipe(recipe)
    errors = _errors(exc)
    assert any(e[0] == loc and (kind is None or e[1] == kind) for e in errors), errors
    return errors


def _load_fixture(name: str) -> dict:
    """Load a fixture from tests/data/easydiffraction/native/."""
    with open(DATA / "easydiffraction" / "native" / name, encoding="utf-8") as f:
        return json.load(f)


# --- valid recipes, round-trip, simulation mode (test 1) ---------------------------


@pytest.mark.parametrize("fixture_name,is_simulation", [
    ("lab6_crysfml_tch.json", False),
    ("lab6_cryspy_pv.json", False),
    ("lab6_slots_simulation.json", True),
])
def test_fixture_validates_and_round_trips(fixture_name, is_simulation):
    """Each fixture validates; model_dump(mode='json') round-trips; simulation_mode matches expectation."""
    recipe = _load_fixture(fixture_name)
    model = validate_recipe(recipe)
    assert validate_recipe(model) is model  # idempotent
    dumped = model.model_dump(mode="json")
    assert validate_recipe(dumped) == model
    assert model.payload.simulation_mode() == is_simulation


def test_unknown_easydiffraction_workflow_reported_at_schema_name():
    r = _load_fixture("lab6_crysfml_tch.json")
    r["schema_name"] = "easydiffraction.rietvel"
    _fails(r, ("schema_name",), "schema_name")


# --- space groups (test 3) ----------------------------------------------------------


@pytest.mark.parametrize("name,expected", [
    ("C 1 2/m 1", ("C 2/m", "b1")),
    ("R -3 m:R", ("R -3 m", "r")),
    ("F d -3 m:1", ("F d -3 m", "1")),
])
def test_easydiffraction_space_group_table(name, expected):
    assert easydiffraction_space_group(name) == expected


@pytest.mark.parametrize("bad_setting", ["A 1", "C 4 2 2"])
def test_space_group_not_in_table_rejected(bad_setting):
    r = _load_fixture("lab6_crysfml_tch.json")
    r["payload"]["phases"]["LaB6"]["space_group"] = bad_setting
    errors = _fails(r, ("payload", "phases", "LaB6", "space_group"))
    # Should mention EB-42 in the message
    exc_info = None
    with pytest.raises(ValidationError) as exc_info:
        validate_recipe(r)
    error_messages = [e["msg"] for e in exc_info.value.errors()]
    assert any("EB-42" in msg for msg in error_messages)


# --- physical limits (test 4) -------------------------------------------------------


def test_cell_length_outside_physical_limit():
    r = _load_fixture("lab6_crysfml_tch.json")
    # Cubic tie: set all three to 35 so core's cubic constraint is satisfied
    for axis in ["a", "b", "c"]:
        r["payload"]["phases"]["LaB6"]["unit_cell"][axis] = P(35, True)
    _fails(r, ("payload", "phases", "LaB6", "unit_cell", "a"), "easydiffraction_physical_limit")


def test_uiso_below_physical_limit():
    r = _load_fixture("lab6_crysfml_tch.json")
    r["payload"]["phases"]["LaB6"]["atoms"]["La"]["Uiso"] = P(-0.001, True)
    _fails(r, ("payload", "phases", "LaB6", "atoms", "La", "Uiso"), "easydiffraction_physical_limit")


def test_uiso_above_physical_limit():
    r = _load_fixture("lab6_crysfml_tch.json")
    r["payload"]["phases"]["LaB6"]["atoms"]["La"]["Uiso"] = P(10.5, True)
    _fails(r, ("payload", "phases", "LaB6", "atoms", "La", "Uiso"), "easydiffraction_physical_limit")


def test_occupancy_above_one_rejected():
    """Occupancy > 1 rejected by core (test that core's check works)."""
    r = _load_fixture("lab6_crysfml_tch.json")
    r["payload"]["phases"]["LaB6"]["atoms"]["La"]["occupancy"] = P(1.2, True)
    # Core rejects this, location somewhere in atoms
    with pytest.raises(ValidationError):
        validate_recipe(r)


def test_scale_negative_rejected():
    r = _load_fixture("lab6_crysfml_tch.json")
    r["payload"]["phases"]["LaB6"]["scale"] = P(-1, True)
    _fails(r, ("payload", "phases", "LaB6", "scale"), "easydiffraction_physical_limit")


def test_scale_zero_accepted():
    """scale = 0 is accepted (A161): a phase may contribute nothing."""
    r = _load_fixture("lab6_crysfml_tch.json")
    r["payload"]["phases"]["LaB6"]["scale"] = P(0, False)
    validate_recipe(r)


def test_mu_r_negative_rejected():
    r = _load_fixture("lab6_slots_simulation.json")
    r["payload"]["instrument"]["absorption"]["mu_r"] = P(-0.1, False)
    _fails(r, ("payload", "instrument", "absorption", "mu_r"), "easydiffraction_physical_limit")


# --- wavelength and doublet (test 5) ------------------------------------------------


def test_wavelength_zero_rejected():
    r = _load_fixture("lab6_crysfml_tch.json")
    r["payload"]["instrument"]["radiation"]["setup_wavelength"] = P(0.0, False)
    _fails(r, ("payload", "instrument", "radiation", "setup_wavelength"), "easydiffraction_positive")


def test_wavelength_negative_rejected():
    r = _load_fixture("lab6_crysfml_tch.json")
    r["payload"]["instrument"]["radiation"]["setup_wavelength"] = P(-1.5, False)
    _fails(r, ("payload", "instrument", "radiation", "setup_wavelength"), "easydiffraction_positive")


def test_ka2_wavelength_without_ratio_rejected():
    r = _load_fixture("lab6_crysfml_tch.json")
    r["payload"]["instrument"]["radiation"]["setup_wavelength_2"] = 1.544426
    # Missing setup_wavelength_2_to_1_ratio
    _fails(r, ("payload", "instrument", "radiation", "setup_wavelength_2_to_1_ratio"), "easydiffraction_doublet")


def test_ka2_ratio_without_wavelength_rejected():
    r = _load_fixture("lab6_crysfml_tch.json")
    r["payload"]["instrument"]["radiation"]["setup_wavelength_2_to_1_ratio"] = 0.5
    # Missing setup_wavelength_2
    _fails(r, ("payload", "instrument", "radiation", "setup_wavelength_2"), "easydiffraction_doublet")


def test_ka2_both_present_accepted():
    r = _load_fixture("lab6_crysfml_tch.json")
    r["payload"]["instrument"]["radiation"]["setup_wavelength_2"] = 1.544426
    r["payload"]["instrument"]["radiation"]["setup_wavelength_2_to_1_ratio"] = 0.5
    validate_recipe(r)


def test_ka2_ratio_zero_rejected():
    r = _load_fixture("lab6_crysfml_tch.json")
    r["payload"]["instrument"]["radiation"]["setup_wavelength_2"] = 1.544426
    r["payload"]["instrument"]["radiation"]["setup_wavelength_2_to_1_ratio"] = 0.0
    with pytest.raises(ValidationError):
        validate_recipe(r)


def test_ka2_ratio_above_one_rejected():
    r = _load_fixture("lab6_crysfml_tch.json")
    r["payload"]["instrument"]["radiation"]["setup_wavelength_2"] = 1.544426
    r["payload"]["instrument"]["radiation"]["setup_wavelength_2_to_1_ratio"] = 1.5
    with pytest.raises(ValidationError):
        validate_recipe(r)


# --- weights (test 6) ---------------------------------------------------------------


def test_heavy_weight_inside_window_rejected():
    """Weight > 1e8 on a point INSIDE fit_range rejected."""
    r = _load_fixture("lab6_crysfml_tch.json")
    # Find a point inside the window (fit_range is [1.0, 15.0])
    tth = r["payload"]["xrd_data"]["tth"]
    idx = None
    for i, t in enumerate(tth):
        if 5.0 <= t <= 10.0:
            idx = i
            break
    assert idx is not None

    r["payload"]["xrd_data"]["Itth_weights"][idx] = 2e8
    _fails(r, ("payload", "xrd_data", "Itth_weights", idx), "easydiffraction_weight")
    with pytest.raises(ValidationError) as exc:
        validate_recipe(r)
    msg = next(e["msg"] for e in exc.value.errors() if e["type"] == "easydiffraction_weight")
    assert "sigma 7.07e-05" in msg and "above 1e+08" in msg and "{" not in msg


def test_heavy_weight_outside_window_accepted():
    """Weight > 1e8 on a point OUTSIDE fit_range accepted."""
    r = _load_fixture("lab6_crysfml_tch.json")
    # Find a point outside the window (fit_range is [1.0, 15.0])
    tth = r["payload"]["xrd_data"]["tth"]
    idx = None
    for i, t in enumerate(tth):
        if t > 15.5:
            idx = i
            break
    assert idx is not None

    r["payload"]["xrd_data"]["Itth_weights"][idx] = 2e8
    validate_recipe(r)


def test_weight_exactly_1e8_accepted():
    """Weight exactly 1e8 is accepted."""
    r = _load_fixture("lab6_crysfml_tch.json")
    tth = r["payload"]["xrd_data"]["tth"]
    idx = None
    for i, t in enumerate(tth):
        if 5.0 <= t <= 10.0:
            idx = i
            break
    assert idx is not None

    r["payload"]["xrd_data"]["Itth_weights"][idx] = 1e8
    validate_recipe(r)


# --- peak type vs calculator (test 7) -----------------------------------------------


def test_tch_with_cryspy_rejected():
    r = _load_fixture("lab6_crysfml_tch.json")
    r["payload"]["refinement_controls"]["calculator"] = "cryspy"
    # TCH (cwl-thompson-cox-hastings) not computed by cryspy
    _fails(r, ("payload", "instrument", "broadening", "peak_type"), "easydiffraction_peak_type")


def test_berar_baldinozzi_with_crysfml_rejected():
    r = _load_fixture("lab6_cryspy_pv.json")
    r["payload"]["instrument"]["broadening"]["peak_type"] = "cwl-pseudo-voigt-berar-baldinozzi-asymmetry"
    r["payload"]["instrument"]["broadening"]["parameters"] = {
        "broad_gauss_u": P(0.01), "broad_gauss_v": P(0.01), "broad_gauss_w": P(0.01),
        "broad_lorentz_x": P(0.01), "broad_lorentz_y": P(0.01),
        "asym_beba_a0": P(0.0), "asym_beba_b0": P(0.0),
        "asym_beba_a1": P(0.0), "asym_beba_b1": P(0.0),
    }
    r["payload"]["refinement_controls"]["calculator"] = "crysfml"
    # Bérar-Baldinozzi not computed by crysfml
    _fails(r, ("payload", "instrument", "broadening", "peak_type"), "easydiffraction_peak_type")


def test_pseudo_voigt_with_both_calculators_accepted():
    # cryspy
    r = _load_fixture("lab6_cryspy_pv.json")
    assert r["payload"]["instrument"]["broadening"]["peak_type"] == "cwl-pseudo-voigt"
    assert r["payload"]["refinement_controls"]["calculator"] == "cryspy"
    validate_recipe(r)

    # crysfml
    r2 = copy.deepcopy(r)
    r2["payload"]["refinement_controls"]["calculator"] = "crysfml"
    validate_recipe(r2)


def test_cutoff_fwhm_with_crysfml_rejected():
    r = _load_fixture("lab6_crysfml_tch.json")
    r["payload"]["instrument"]["broadening"]["cutoff_fwhm"] = 10.0
    _fails(r, ("payload", "instrument", "broadening", "cutoff_fwhm"), "easydiffraction_cutoff")


def test_cutoff_fwhm_with_cryspy_accepted():
    r = _load_fixture("lab6_cryspy_pv.json")
    r["payload"]["instrument"]["broadening"]["cutoff_fwhm"] = 10.0
    validate_recipe(r)


def _b_uaniso(r: dict, u11: float = 0.009) -> dict:
    """LaB6's B (6f, x 1/2 1/2) with an anisotropic tensor respecting its site symmetry (U22 = U33, no cross terms)."""
    b = r["payload"]["phases"]["LaB6"]["atoms"]["B"]
    b.pop("Uiso")
    b["ADP"] = "Uaniso"
    b["Uaniso"] = {"U11": P(u11), "U22": P(0.009), "U33": P(0.009), "U12": P(0.0), "U13": P(0.0), "U23": P(0.0)}
    return r


def test_uaniso_with_crysfml_rejected():
    """CrysFML is handed B = 8 pi^2 Ueq only, so the tensor would have no effect (EB-23)."""
    r = _b_uaniso(_load_fixture("lab6_crysfml_tch.json"))
    errors = _fails(r, ("payload", "phases", "LaB6", "atoms", "B", "Uaniso"), "easydiffraction_uaniso_crysfml")
    assert len(errors) == 1


def test_uaniso_with_cryspy_accepted():
    validate_recipe(_b_uaniso(_load_fixture("lab6_cryspy_pv.json"), u11=0.03))


def _w_negative_below(two_theta: float, r: dict) -> float:
    """The W that makes the fixture's Gaussian FWHM^2 (U tan^2 + V tan + W) negative below ``two_theta``."""
    pars = r["payload"]["instrument"]["broadening"]["parameters"]
    t = np.tan(np.radians(two_theta / 2))
    return -(pars["broad_gauss_u"][0] * t ** 2 + pars["broad_gauss_v"][0] * t)


@pytest.mark.parametrize("fixture", ["lab6_cryspy_pv.json", "lab6_crysfml_tch.json"])
def test_negative_gaussian_width_in_window_rejected(fixture):
    """FWHM^2 < 0 below 5 deg: CrysFML would drop those peaks, CrysPy distort them (EB-87, A171)."""
    r = _load_fixture(fixture)
    r["payload"]["instrument"]["broadening"]["parameters"]["broad_gauss_w"][0] = _w_negative_below(5.0, r)
    with pytest.raises(ValidationError) as exc:
        validate_recipe(r)
    hits = [e for e in exc.value.errors() if e["type"] == "easydiffraction_negative_width"]
    assert [e["loc"] for e in hits] == [("payload", "instrument", "broadening", "parameters")]
    assert "Gaussian" in hits[0]["msg"] and "within 1 deg of the fit window" in hits[0]["msg"]
    assert "{" not in hits[0]["msg"]


def test_negative_lorentzian_width_rejected():
    r = _load_fixture("lab6_cryspy_pv.json")
    r["payload"]["instrument"]["broadening"]["parameters"]["broad_lorentz_y"][0] = -0.0028
    errors = _fails(r, ("payload", "instrument", "broadening", "parameters"), "easydiffraction_negative_width")
    assert len(errors) == 1


def _x_negative_above(two_theta: float, r: dict) -> float:
    """The Lorentzian X that makes the fixture's FWHM (X tan + Y / cos) negative above ``two_theta``."""
    y = r["payload"]["instrument"]["broadening"]["parameters"]["broad_lorentz_y"][0]
    return -y / np.sin(np.radians(two_theta / 2))


def test_negative_width_beyond_the_margin_accepted():
    """Only the window widened by WIDTH_MARGIN (1 deg) counts: window [1, 15], negative above 16.2 deg (A178)."""
    r = _load_fixture("lab6_cryspy_pv.json")
    r["payload"]["instrument"]["broadening"]["parameters"]["broad_lorentz_x"][0] = _x_negative_above(16.2, r)
    validate_recipe(r)


def test_negative_width_just_outside_the_window_rejected():
    """A reflection just outside the window is computed and reaches it (A178; the review's 12-sigma case)."""
    r = _load_fixture("lab6_cryspy_pv.json")
    r["payload"]["instrument"]["broadening"]["parameters"]["broad_lorentz_x"][0] = _x_negative_above(15.5, r)
    with pytest.raises(ValidationError) as exc:
        validate_recipe(r)
    msg = next(e["msg"] for e in exc.value.errors() if e["type"] == "easydiffraction_negative_width")
    assert "Lorentzian" in msg and "from 15.5" in msg and "to 15.9976 deg" in msg  # last handed point 14.9976 + 1


def test_negative_width_margin_widened_by_the_zero_shift():
    """The stated zero offset moves reflections, so it widens the checked range (A178)."""
    r = _load_fixture("lab6_cryspy_pv.json")
    r["payload"]["instrument"]["broadening"]["parameters"]["broad_lorentz_x"][0] = _x_negative_above(16.2, r)
    r["payload"]["instrument"]["corrections"]["calib_twotheta_offset"] = [0.5, False, None, None]
    _fails(r, ("payload", "instrument", "broadening", "parameters"), "easydiffraction_negative_width")


# --- negative intensities (A177, EB-91) --------------------------------------------


def _index_at(r: dict, lo: float, hi: float) -> int:
    return next(i for i, t in enumerate(r["payload"]["xrd_data"]["tth"]) if lo <= t <= hi)


def test_negative_intensity_in_window_rejected():
    """easydiffraction refuses a negative measured intensity on a point it is handed (EB-91)."""
    r = _load_fixture("lab6_crysfml_tch.json")
    i = _index_at(r, 10.0, 10.1)
    r["payload"]["xrd_data"]["Itth"][i] = -3.0
    with pytest.raises(ValidationError) as exc:
        validate_recipe(r)
    hits = [e for e in exc.value.errors() if e["type"] == "easydiffraction_negative_intensity"]
    assert [e["loc"] for e in hits] == [("payload", "xrd_data", "Itth", i)]
    assert "EB-91" in hits[0]["msg"] and "{" not in hits[0]["msg"]


@pytest.mark.parametrize("where", ["outside the window", "zero weight"])
def test_negative_intensity_not_handed_accepted(where):
    """A negative intensity outside the window, or on a zero-weight point, never reaches the engine."""
    r = _load_fixture("lab6_crysfml_tch.json")
    xrd = r["payload"]["xrd_data"]
    i = _index_at(r, 15.5, 16.0) if where == "outside the window" else _index_at(r, 10.0, 10.1)
    xrd["Itth"][i] = -3.0
    if where == "zero weight":
        xrd["Itth_weights"][i] = 0.0
    validate_recipe(r)


# --- per-type parameter sets (test 8) -----------------------------------------------


def test_tch_missing_asym_fcj_2_rejected():
    r = _load_fixture("lab6_crysfml_tch.json")
    del r["payload"]["instrument"]["broadening"]["parameters"]["asym_fcj_2"]
    with pytest.raises(ValidationError) as exc:
        validate_recipe(r)
    # Should be missing field error
    errors = _errors(exc)
    assert any("asym_fcj_2" in str(loc) for loc, _ in errors)


def test_pseudo_voigt_with_extra_asym_fcj_1_rejected():
    r = _load_fixture("lab6_cryspy_pv.json")
    r["payload"]["instrument"]["broadening"]["parameters"]["asym_fcj_1"] = P(0.0)
    # extra='forbid' should catch this
    with pytest.raises(ValidationError) as exc:
        validate_recipe(r)
    errors = _errors(exc)
    assert any("asym_fcj_1" in str(loc) for loc, _ in errors)


# --- optional blocks never null (test 9) --------------------------------------------


@pytest.mark.parametrize("path", [
    ("payload", "instrument", "polarization"),
    ("payload", "instrument", "absorption"),
    ("payload", "instrument", "description"),
    ("payload", "background"),
    ("payload", "fit_range"),
    ("payload", "instrument", "corrections", "calib_sample_displacement"),
    ("payload", "instrument", "radiation", "setup_wavelength_2"),
    ("payload", "instrument", "broadening", "cutoff_fwhm"),
])
def test_optional_block_never_null(path):
    r = _load_fixture("lab6_crysfml_tch.json")
    node = r
    for key in path[:-1]:
        if key not in node:
            # Need to add the parent structure
            if path[-1] == "cutoff_fwhm":
                # Already at broadening level
                pass
        node = node.setdefault(key, {}) if isinstance(node, dict) else node

    # Navigate to parent
    parent = r
    for key in path[:-1]:
        parent = parent[key]
    parent[path[-1]] = None

    with pytest.raises(ValidationError, match="must not be null; leave it out instead"):
        validate_recipe(r)


# --- refinement_controls (test 10) --------------------------------------------------


def test_minimizer_other_than_lmfit_leastsq_rejected():
    r = _load_fixture("lab6_crysfml_tch.json")
    r["payload"]["refinement_controls"]["minimizer"] = "scipy.optimize.minimize"
    with pytest.raises(ValidationError):
        validate_recipe(r)


def test_max_iterations_zero_rejected():
    r = _load_fixture("lab6_crysfml_tch.json")
    r["payload"]["refinement_controls"]["max_iterations"] = 0
    with pytest.raises(ValidationError):
        validate_recipe(r)


def test_chi_square_change_tolerance_zero_rejected():
    r = _load_fixture("lab6_crysfml_tch.json")
    r["payload"]["refinement_controls"]["chi_square_change_tolerance"] = 0.0
    with pytest.raises(ValidationError):
        validate_recipe(r)


def test_gradient_tolerance_zero_accepted():
    r = _load_fixture("lab6_crysfml_tch.json")
    r["payload"]["refinement_controls"]["gradient_tolerance"] = 0.0
    validate_recipe(r)


def test_calculator_fullprof_rejected():
    r = _load_fixture("lab6_crysfml_tch.json")
    r["payload"]["refinement_controls"]["calculator"] = "fullprof"
    with pytest.raises(ValidationError):
        validate_recipe(r)


# --- JSON Schema null constraints (test 11) -----------------------------------------


def test_json_schema_shows_null_only_where_core_allows_it():
    """Null only in BoundedRefinableParameter, FitRange, XRDData defs."""
    from powderline.gateways.easydiffraction.schema import EasydiffractionRietveldRecipe

    schema = EasydiffractionRietveldRecipe.model_json_schema()
    allowed = {"BoundedRefinableParameter", "FitRange", "XRDData"}
    for name, node in schema["$defs"].items():
        if name not in allowed:
            assert "null" not in json.dumps(node), name


# --- parameters_requested (test 12) -------------------------------------------------


def test_parameters_requested_counts_cubic_cell_once():
    """Cubic cell a,b,c refined counts ONCE; compute expected from fixture."""
    r = _load_fixture("lab6_crysfml_tch.json")
    model = validate_recipe(r)

    # Count from lab6_crysfml_tch manually:
    # - instrument.broadening.parameters: broad_gauss_u, v, w (3 params, all refined)
    # - instrument.broadening.parameters: broad_lorentz_x, y (2 params, both refined)
    # - instrument.broadening.parameters: asym_fcj_1, asym_fcj_2 (NOT refined in this fixture)
    # - background.chebyshev: num_coefficients=6, refine_flag=True (6 coefficients)
    # - phases.LaB6.unit_cell: cubic a,b,c all refined but tied -> counts as 1
    # - phases.LaB6.scale: refined (1)
    # Total: 3 + 2 + 6 + 1 + 1 = 13

    expected = 13
    actual = parameters_requested(model)
    assert actual == expected, f"Expected {expected} parameters, got {actual}"


# --- fit_limits_on_data and window_mask (test 13) -----------------------------------


def test_window_mask_selects_weighted_points_in_range():
    """window_mask() selects exactly the weighted points with 1.0 <= tth <= 15.0."""
    r = _load_fixture("lab6_cryspy_pv.json")
    model = validate_recipe(r)

    tth = np.asarray(model.payload.xrd_data.tth, dtype=float)
    weights = np.asarray(model.payload.xrd_data.Itth_weights, dtype=float)

    # Expected: weighted points (w > 0) within fit_range [1.0, 15.0]
    expected_mask = (tth >= 1.0) & (tth <= 15.0) & (weights > 0)

    actual_mask = model.payload.window_mask()

    np.testing.assert_array_equal(actual_mask, expected_mask)


# --- settings per calculator (EB-80) -------------------------------------------------


@pytest.mark.parametrize("setting, calculator, suggestion", [
    ("F d -3 m:1", "crysfml", "F d -3 m:2"),
    ("P n n n:1", "crysfml", "P n n n:2"),
    ("R -3 m:R", "cryspy", "R -3 m:H"),
    ("P 1 1 2", "cryspy", "P 1 2 1"),
    ("F d -3 m:1", "cryspy", "F d -3 m:2"),  # special positions computed wrongly (A174, EB-77)
    ("F d d d:1", "cryspy", "F d d d:2"),
    ("P n -3 m:1", "cryspy", "P n -3 m:2"),
])
def test_setting_the_calculator_misreads_rejected(setting, calculator, suggestion):
    from powderline.gateways.easydiffraction.schema import calculator_setting_problem

    why = calculator_setting_problem(setting, calculator)
    assert why is not None and "EB-80" in why and repr(suggestion) in why


def test_p31_cryspy_rejected_naming_crysfml():
    """CrysPy computes P 31 with P 32's operators (the other hand per reflection); CrysFML is fine (A170)."""
    from powderline.gateways.easydiffraction.schema import calculator_setting_problem

    why = calculator_setting_problem("P 31", "cryspy")
    assert why is not None and "use the crysfml calculator" in why


@pytest.mark.parametrize("setting, calculator", [("P m -3 m", "crysfml"), ("P m -3 m", "cryspy"),
                                                 ("P n -3:1", "cryspy"), ("C 1 2/m 1", "crysfml"),
                                                 ("P 31", "crysfml"), ("P 6/m", "crysfml"), ("F d -3 c:2", "crysfml")])
def test_setting_the_calculator_computes_accepted(setting, calculator):
    from powderline.gateways.easydiffraction.schema import calculator_setting_problem

    assert calculator_setting_problem(setting, calculator) is None


def test_setting_rule_reported_at_the_phase():
    r = _load_fixture("lab6_cryspy_pv.json")
    r["payload"]["refinement_controls"]["calculator"] = "crysfml"
    r["payload"]["phases"]["LaB6"]["space_group"] = "P 1 1 2"
    cell = r["payload"]["phases"]["LaB6"]["unit_cell"]
    cell["gamma"] = P(95.0)
    for label, xyz in (("La", (0.0, 0.0, 0.0)), ("B", (0.2021, 0.31, 0.47))):
        for k, v in zip("xyz", xyz):
            r["payload"]["phases"]["LaB6"]["atoms"][label][k] = P(v)
    _fails(r, ("payload", "phases", "LaB6", "space_group"), "easydiffraction_setting")
