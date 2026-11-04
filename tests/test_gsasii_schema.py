"""Tests for powderline.gateways.gsasii.schema (gsasii.* native schemas).

Covers the GSAS-II-specific validations: version compatibility (A65, A81),
space-group settings (A105, EB-03, EB-41), cell refinement groups (A95),
instrument/background/peak-list floors (A86, A90, A91, EB-35, EB-37),
simulation mode (A88), single-peak fitting (A90), documented defaults (A87, A107),
core rules inherited through GsasiiPhase (A103, A112), and gateway routing.
"""
import copy
import json

import pytest

from pydantic import ValidationError

import powderline
from powderline.gateways.gsasii import gateway
from powderline.gateways.gsasii.schema import (

    GsasiiRietveldRecipe,
    GsasiiSpfRecipe,
    gsasii_space_group,
    gsasii_cell_groups,
    validate_recipe,
)
from powderline.schema_core import collect_warnings

pytestmark = pytest.mark.core


# --- fixtures -----------------------------------------------------------------


def p(v, f=False):
    """Refinable parameter: [value, refine_flag]."""
    return [v, f]


def _xrd():
    return {"tth": [1.0, 2.0, 15.0], "Itth": [1.0, 2.0, 3.0], "Itth_weights": [1.0, 1.0, 1.0]}


def _instrument():
    return {
        "description": "28-ID-1",
        "radiation": {"type": "PXC", "wavelength": p(0.1665)},
        "geometry": {"bank": 1, "azimuth": 0.0},
        "corrections": {"zero_shift": p(0.0), "polarization": p(0.99), "axial_divergence": p(0.002)},
        "broadening": {k: p(v, True) for k, v in zip("UVWXYZ", (18.7, 0.6, 1.1, 0.28, 0.001, 0.0))},
    }


def _phase_lab6():
    return {
        "space_group": "P m -3 m",
        "unit_cell": {
            "a": p(4.15682, True), "b": p(4.15682, True), "c": p(4.15682, True),
            "alpha": p(90.0), "beta": p(90.0), "gamma": p(90.0)
        },
        "atoms": {
            "La": {"element": "La", "x": p(0.0), "y": p(0.0), "z": p(0.0),
                   "occupancy": p(1.0), "ADP": "Uiso", "Uiso": p(0.00858)},
            "B": {"element": "B", "x": p(0.2021, True), "y": p(0.5), "z": p(0.5),
                  "occupancy": p(1.0), "ADP": "Uiso", "Uiso": p(0.009)}
        },
        "scale": p(1.0, True)
    }


def _rietveld_recipe():
    """A minimal valid Rietveld recipe (deep-copy before editing)."""
    return {
        "schema_name": "gsasii.rietveld",
        "core_schema_version": "0.1.0",
        "engine_schema_version": "0.1.0",
        "payload": {
            "xrd_data": _xrd(),
            "instrument": _instrument(),
            "phases": {"LaB6": _phase_lab6()},
            "fit_range": [1, 15],
            # stated, so the "no warnings" assertions below stay meaningful (P-33 warns when left out)
            "background": {"chebyshev": {"num_coefficients": 1, "coefficients": [0.0], "refine_flag": False}},
            "refinement_controls": {"refinement_cycles": 5}
        }
    }


def _spf_recipe():
    """A minimal valid SPF recipe (deep-copy before editing): each peak's own widths, profile terms fixed (A127)."""
    instrument = _instrument()
    instrument["broadening"] = {k: p(v[0]) for k, v in instrument["broadening"].items()}
    return {
        "schema_name": "gsasii.spf",
        "core_schema_version": "0.1.0",
        "engine_schema_version": "0.1.0",
        "payload": {
            "xrd_data": _xrd(),
            "instrument": instrument,
            "single_peaks": {
                "positions": [p(2.29, True)],
                "intensities": [p(100.0, True)],
                "pv_gaussian_sigma_sq": [p(10.0, True)],
                "pv_lorentzian_gamma": [p(1.0, True)]
            },
            "fit_range": [1, 15],
            "refinement_controls": {
                "refinement_cycles": 5,
                "single_peak_fitting_mode": {"use_instrument_profile": False}
            }
        }
    }


def _errors(exc_info):
    """(location, type) of every error, for pinning field and error code."""
    return [(e["loc"], e["type"]) for e in exc_info.value.errors()]


# --- 1. Version checks --------------------------------------------------------


def test_version_engine_schema_version_wrong_rejected():
    recipe = copy.deepcopy(_rietveld_recipe())
    recipe["engine_schema_version"] = "0.1.1"
    with pytest.raises(ValidationError) as exc:
        validate_recipe(recipe)
    # The version check raises an error about unsupported version
    assert "not supported" in str(exc.value) or "0.1.1" in str(exc.value)


def test_version_core_schema_version_wrong_rejected():
    recipe = copy.deepcopy(_rietveld_recipe())
    recipe["core_schema_version"] = "2.0.0"
    with pytest.raises(ValidationError) as exc:
        validate_recipe(recipe)
    # The version check raises an error about unsupported version
    assert "not supported" in str(exc.value) or "2.0.0" in str(exc.value)


def test_version_unknown_schema_name_rejected():
    recipe = copy.deepcopy(_rietveld_recipe())
    recipe["schema_name"] = "gsasii.bogus"
    with pytest.raises(ValidationError) as exc:
        validate_recipe(recipe)
    assert _errors(exc) == [(("schema_name",), "schema_name")]
    assert "'gsasii.bogus' is not a gsasii workflow; expected one of gsasii.rietveld, gsasii.spf" in str(exc.value)


def test_mistyped_gsasii_name_reported_against_the_native_schema():
    """A gsasii.* typo gets the gsasii error at schema_name, not another schema's errors (re/04 PR review)."""
    recipe = copy.deepcopy(_rietveld_recipe())
    recipe["schema_name"] = "gsasii.reitveld"
    with pytest.raises(ValidationError) as exc:
        powderline.validate(recipe)
    assert _errors(exc) == [(("schema_name",), "schema_name")]


# --- 2. Space group validation ------------------------------------------------


def test_space_group_origin_choice_1_rejected():
    """Origin choice 1 is rejected (EB-03)."""
    with pytest.raises(ValueError, match="origin choice 1"):
        gsasii_space_group("F d -3 m:1")


def test_space_group_unreadable_p_21_n_m_rejected():
    """P 21 n m is in the unreadable list (EB-41)."""
    with pytest.raises(ValueError, match="cannot express"):
        gsasii_space_group("P 21 n m")


def test_space_group_unreadable_a_b_a_m_rejected():
    """A b a m is in the unreadable list (EB-41)."""
    with pytest.raises(ValueError, match="cannot express"):
        gsasii_space_group("A b a m")


def test_space_group_rhombohedral_R_translates():
    """R -3 m:R translates to R -3 m R."""
    assert gsasii_space_group("R -3 m:R") == "R -3 m R"


def test_space_group_origin_choice_2_translates():
    """F d -3 m:2 translates to F d -3 m."""
    assert gsasii_space_group("F d -3 m:2") == "F d -3 m"


def test_space_group_rhombohedral_H_translates():
    """R -3 m:H translates to R -3 m."""
    assert gsasii_space_group("R -3 m:H") == "R -3 m"


def test_space_group_monoclinic_canonical_unchanged():
    """P 1 21/c 1 remains unchanged."""
    assert gsasii_space_group("P 1 21/c 1") == "P 1 21/c 1"


def test_space_group_non_canonical_rejected():
    """A non-canonical space-group name is rejected."""
    with pytest.raises(ValueError, match="not a canonical"):
        gsasii_space_group("Pm-3m")


# --- 3. Cell refinement groups ------------------------------------------------


def test_cell_groups_monoclinic_b_unique():
    """C 1 2/m 1 (b-unique) has groups (b,) and (a, c, beta)."""
    groups = gsasii_cell_groups("C 1 2/m 1")
    assert groups == (("b",), ("a", "c", "beta"))


def test_cell_groups_monoclinic_c_unique():
    """P 1 1 21/b (c-unique) has groups (c,) and (a, b, gamma)."""
    groups = gsasii_cell_groups("P 1 1 21/b")
    assert groups == (("c",), ("a", "b", "gamma"))


def test_cell_groups_monoclinic_a_unique():
    """I 2/m 1 1 (a-unique) has groups (a,) and (b, c, alpha)."""
    groups = gsasii_cell_groups("I 2/m 1 1")
    assert groups == (("a",), ("b", "c", "alpha"))


def test_cell_groups_triclinic():
    """P -1 has all six in one group."""
    groups = gsasii_cell_groups("P -1")
    assert groups == (("a", "b", "c", "alpha", "beta", "gamma"),)


def test_cell_groups_rhombohedral_R():
    """R -3 m:R has all six in one group."""
    groups = gsasii_cell_groups("R -3 m:R")
    assert groups == (("a", "b", "c", "alpha", "beta", "gamma"),)


def test_cell_groups_tetragonal():
    """P 4/m m m has groups (a, b) and (c,)."""
    groups = gsasii_cell_groups("P 4/m m m")
    assert groups == (("a", "b"), ("c",))


def test_cell_groups_monoclinic_partial_refinement_rejected():
    """Refining only a (not c, beta) in C 1 2/m 1 is rejected."""
    recipe = copy.deepcopy(_rietveld_recipe())
    recipe["payload"]["phases"]["LaB6"]["space_group"] = "C 1 2/m 1"
    recipe["payload"]["phases"]["LaB6"]["unit_cell"] = {
        "a": p(5.0, True), "b": p(5.0, False), "c": p(5.0, False),
        "alpha": p(90.0), "beta": p(90.0), "gamma": p(90.0)
    }
    with pytest.raises(ValidationError) as exc:
        validate_recipe(recipe)
    errors = exc.value.errors()
    # Expect errors at unit_cell.c and unit_cell.beta
    locs = [e["loc"] for e in errors]
    assert ("payload", "phases", "LaB6", "unit_cell", "c") in locs
    assert ("payload", "phases", "LaB6", "unit_cell", "beta") in locs
    assert any(e["type"] == "gsasii_cell_group" for e in errors)


def test_cell_groups_monoclinic_full_group_refinement_accepted():
    """Refining a, c, beta together in C 1 2/m 1 is accepted."""
    recipe = copy.deepcopy(_rietveld_recipe())
    recipe["payload"]["phases"]["LaB6"]["space_group"] = "C 1 2/m 1"
    recipe["payload"]["phases"]["LaB6"]["unit_cell"] = {
        "a": p(5.0, True), "b": p(5.0, False), "c": p(5.0, True),
        "alpha": p(90.0), "beta": p(90.0, True), "gamma": p(90.0)
    }
    model = validate_recipe(recipe)
    assert model.payload.phases["LaB6"].unit_cell.a.refine_flag is True
    assert model.payload.phases["LaB6"].unit_cell.c.refine_flag is True
    assert model.payload.phases["LaB6"].unit_cell.beta.refine_flag is True


def test_cell_groups_triclinic_partial_refinement_rejected():
    """Refining only alpha in P -1 is rejected."""
    recipe = copy.deepcopy(_rietveld_recipe())
    recipe["payload"]["phases"]["LaB6"]["space_group"] = "P -1"
    recipe["payload"]["phases"]["LaB6"]["unit_cell"] = {
        "a": p(5.0, False), "b": p(5.0, False), "c": p(5.0, False),
        "alpha": p(90.0, True), "beta": p(90.0), "gamma": p(90.0)
    }
    with pytest.raises(ValidationError) as exc:
        validate_recipe(recipe)
    errors = exc.value.errors()
    # Expect errors at all cell parameters
    assert any(e["type"] == "gsasii_cell_group" for e in errors)


# --- 4. Scale validation ------------------------------------------------------


def test_scale_negative_rejected():
    recipe = copy.deepcopy(_rietveld_recipe())
    recipe["payload"]["phases"]["LaB6"]["scale"] = [-0.1, False]
    with pytest.raises(ValidationError) as exc:
        validate_recipe(recipe)
    errors = exc.value.errors()
    locs = [e["loc"] for e in errors]
    assert ("payload", "phases", "LaB6", "scale") in locs


def test_scale_zero_accepted():
    recipe = copy.deepcopy(_rietveld_recipe())
    recipe["payload"]["phases"]["LaB6"]["scale"] = [0.0, False]
    model = validate_recipe(recipe)
    assert model.payload.phases["LaB6"].scale.value == 0.0


def test_scale_missing_rejected():
    recipe = copy.deepcopy(_rietveld_recipe())
    del recipe["payload"]["phases"]["LaB6"]["scale"]
    with pytest.raises(ValidationError) as exc:
        validate_recipe(recipe)
    errors = exc.value.errors()
    locs = [e["loc"] for e in errors]
    assert ("payload", "phases", "LaB6", "scale") in locs


# --- 5. 4-element parameter rejection (A84) -----------------------------------


def test_refinable_parameter_4_element_rejected():
    """4-element parameter [value, refine_flag, min, max] is rejected (bounds not supported)."""
    recipe = copy.deepcopy(_rietveld_recipe())
    recipe["payload"]["phases"]["LaB6"]["scale"] = [1.0, True, None, None]
    with pytest.raises(ValidationError) as exc:
        validate_recipe(recipe)
    errors = exc.value.errors()
    # The error should mention bounds not being supported
    assert any("bounds are not supported" in e["msg"] for e in errors)


# --- 6. Instrument validation -------------------------------------------------


def test_instrument_radiation_type_pxa_rejected():
    recipe = copy.deepcopy(_rietveld_recipe())
    recipe["payload"]["instrument"]["radiation"]["type"] = "PXA"
    with pytest.raises(ValidationError) as exc:
        validate_recipe(recipe)
    errors = exc.value.errors()
    # The radiation type field should be in the error location
    assert any("radiation" in str(e["loc"]) and "type" in str(e["loc"]) for e in errors)


def test_instrument_radiation_extra_key_rejected():
    """Extra keys in radiation are forbidden."""
    recipe = copy.deepcopy(_rietveld_recipe())
    recipe["payload"]["instrument"]["radiation"]["Lam1"] = 0.1665
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        validate_recipe(recipe)


def test_instrument_axial_divergence_too_small_rejected():
    """Axial divergence 0.0015 is below the floor of 0.002 (EB-37)."""
    recipe = copy.deepcopy(_rietveld_recipe())
    recipe["payload"]["instrument"]["corrections"]["axial_divergence"] = [0.0015, False]
    with pytest.raises(ValidationError) as exc:
        validate_recipe(recipe)
    errors = exc.value.errors()
    # Should mention 0.002 and EB-37
    assert any("0.002" in e["msg"] and "EB-37" in e["msg"] for e in errors)


def test_instrument_axial_divergence_at_floor_accepted():
    """Axial divergence 0.002 is accepted."""
    recipe = copy.deepcopy(_rietveld_recipe())
    recipe["payload"]["instrument"]["corrections"]["axial_divergence"] = [0.002, False]
    model = validate_recipe(recipe)
    assert model.payload.instrument.corrections.axial_divergence.value == 0.002


def test_instrument_geometry_missing_rejected():
    recipe = copy.deepcopy(_rietveld_recipe())
    del recipe["payload"]["instrument"]["geometry"]
    with pytest.raises(ValidationError) as exc:
        validate_recipe(recipe)
    errors = exc.value.errors()
    locs = [e["loc"] for e in errors]
    assert ("payload", "instrument", "geometry") in locs


def test_instrument_description_can_be_omitted():
    recipe = copy.deepcopy(_rietveld_recipe())
    del recipe["payload"]["instrument"]["description"]
    model = validate_recipe(recipe)
    # Should validate and not include description in the dump
    dump = model.model_dump(mode="json")
    assert "description" not in dump["payload"]["instrument"]


def test_instrument_description_null_rejected():
    recipe = copy.deepcopy(_rietveld_recipe())
    recipe["payload"]["instrument"]["description"] = None
    with pytest.raises(ValidationError, match="must not be null"):
        validate_recipe(recipe)


# --- 7. Background validation -------------------------------------------------


def test_background_left_out_defaults():
    """Background left out gives one fixed Chebyshev term 0.0, no single_peaks."""
    recipe = copy.deepcopy(_rietveld_recipe())
    # Don't include background
    if "background" in recipe["payload"]:
        del recipe["payload"]["background"]
    model = validate_recipe(recipe)
    bg = model.payload.background
    assert bg.chebyshev.num_coefficients == 1
    assert bg.chebyshev.coefficients == [0.0]
    assert bg.chebyshev.refine_flag is False
    # Dump should not have single_peaks key
    dump = model.model_dump(mode="json")
    assert "single_peaks" not in dump["payload"]["background"]


def test_background_null_rejected():
    recipe = copy.deepcopy(_rietveld_recipe())
    recipe["payload"]["background"] = None
    with pytest.raises(ValidationError, match="must not be null"):
        validate_recipe(recipe)


def test_background_single_peaks_different_lengths_rejected():
    recipe = copy.deepcopy(_rietveld_recipe())
    recipe["payload"]["background"] = {
        "single_peaks": {
            "positions": [p(5.0)],
            "intensities": [p(10.0), p(20.0)],  # Different length
            "pv_gaussian_sigma_sq": [p(1.0)],
            "pv_lorentzian_gamma": [p(0.5)]
        }
    }
    with pytest.raises(ValidationError, match="same length"):
        validate_recipe(recipe)


def test_background_intensity_below_floor_rejected():
    """Intensity 0.05 is below the floor of 0.1 (EB-35)."""
    recipe = copy.deepcopy(_rietveld_recipe())
    recipe["payload"]["background"] = {
        "single_peaks": {
            "positions": [p(5.0)],
            "intensities": [p(0.05)],
            "pv_gaussian_sigma_sq": [p(1.0)],
            "pv_lorentzian_gamma": [p(0.5)]
        }
    }
    with pytest.raises(ValidationError) as exc:
        validate_recipe(recipe)
    errors = exc.value.errors()
    locs = [e["loc"] for e in errors]
    assert ("payload", "background", "single_peaks", "intensities", 0) in locs
    assert any("EB-35" in e["msg"] for e in errors)


def test_background_sigma_sq_below_floor_rejected():
    """Sigma_sq 0.005 is below the floor of 0.01."""
    recipe = copy.deepcopy(_rietveld_recipe())
    recipe["payload"]["background"] = {
        "single_peaks": {
            "positions": [p(5.0)],
            "intensities": [p(10.0)],
            "pv_gaussian_sigma_sq": [p(0.005)],
            "pv_lorentzian_gamma": [p(0.5)]
        }
    }
    with pytest.raises(ValidationError) as exc:
        validate_recipe(recipe)
    errors = exc.value.errors()
    locs = [e["loc"] for e in errors]
    assert ("payload", "background", "single_peaks", "pv_gaussian_sigma_sq", 0) in locs


def test_background_gamma_below_floor_rejected():
    """Gamma 0.05 is below the floor of 0.1."""
    recipe = copy.deepcopy(_rietveld_recipe())
    recipe["payload"]["background"] = {
        "single_peaks": {
            "positions": [p(5.0)],
            "intensities": [p(10.0)],
            "pv_gaussian_sigma_sq": [p(1.0)],
            "pv_lorentzian_gamma": [p(0.05)]
        }
    }
    with pytest.raises(ValidationError) as exc:
        validate_recipe(recipe)
    errors = exc.value.errors()
    locs = [e["loc"] for e in errors]
    assert ("payload", "background", "single_peaks", "pv_lorentzian_gamma", 0) in locs


def test_background_position_outside_fit_range_rejected():
    """Position 20.0 outside fit_range [1, 15] is rejected."""
    recipe = copy.deepcopy(_rietveld_recipe())
    recipe["payload"]["background"] = {
        "single_peaks": {
            "positions": [p(20.0)],
            "intensities": [p(10.0)],
            "pv_gaussian_sigma_sq": [p(1.0)],
            "pv_lorentzian_gamma": [p(0.5)]
        }
    }
    with pytest.raises(ValidationError) as exc:
        validate_recipe(recipe)
    errors = exc.value.errors()
    locs = [e["loc"] for e in errors]
    assert ("payload", "background", "single_peaks", "positions", 0) in locs


def test_background_position_without_fit_range_uses_data_limits():
    """Without fit_range, data limits [1, 15] apply."""
    recipe = copy.deepcopy(_rietveld_recipe())
    del recipe["payload"]["fit_range"]
    recipe["payload"]["background"] = {
        "single_peaks": {
            "positions": [p(20.0)],
            "intensities": [p(10.0)],
            "pv_gaussian_sigma_sq": [p(1.0)],
            "pv_lorentzian_gamma": [p(0.5)]
        }
    }
    with pytest.raises(ValidationError) as exc:
        validate_recipe(recipe)
    errors = exc.value.errors()
    locs = [e["loc"] for e in errors]
    assert ("payload", "background", "single_peaks", "positions", 0) in locs


def test_background_empty_list_rejected():
    recipe = copy.deepcopy(_rietveld_recipe())
    recipe["payload"]["background"] = {
        "single_peaks": {
            "positions": [],
            "intensities": [],
            "pv_gaussian_sigma_sq": [],
            "pv_lorentzian_gamma": []
        }
    }
    with pytest.raises(ValidationError, match="at least 1"):
        validate_recipe(recipe)


def test_background_old_key_rejected():
    """Old key pv_gaussian_sigma is rejected (extra forbidden)."""
    recipe = copy.deepcopy(_rietveld_recipe())
    recipe["payload"]["background"] = {
        "single_peaks": {
            "positions": [p(5.0)],
            "intensities": [p(10.0)],
            "pv_gaussian_sigma": [p(1.0)],  # Old key
            "pv_gaussian_sigma_sq": [p(1.0)],
            "pv_lorentzian_gamma": [p(0.5)]
        }
    }
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        validate_recipe(recipe)


# --- 8. fit_range validation --------------------------------------------------


def test_fit_range_outside_data_rejected():
    recipe = copy.deepcopy(_rietveld_recipe())
    recipe["payload"]["fit_range"] = [0.5, 15]
    with pytest.raises(ValidationError) as exc:
        validate_recipe(recipe)
    errors = exc.value.errors()
    locs = [e["loc"] for e in errors]
    assert ("payload", "fit_range") in locs


def test_fit_range_left_out_accepted():
    recipe = copy.deepcopy(_rietveld_recipe())
    del recipe["payload"]["fit_range"]
    model = validate_recipe(recipe)
    # Should be absent from dump
    dump = model.model_dump(mode="json")
    assert "fit_range" not in dump["payload"]


def test_fit_range_null_rejected():
    recipe = copy.deepcopy(_rietveld_recipe())
    recipe["payload"]["fit_range"] = None
    with pytest.raises(ValidationError, match="must not be null"):
        validate_recipe(recipe)


# --- 9. Peak broadening validation --------------------------------------------


def test_peak_broadening_left_out_gives_warnings():
    """Peak broadening left out gives two warnings (size and strain)."""
    recipe = copy.deepcopy(_rietveld_recipe())
    # Leave out peak_broadening entirely
    if "peak_broadening" in recipe["payload"]["phases"]["LaB6"]:
        del recipe["payload"]["phases"]["LaB6"]["peak_broadening"]
    model = validate_recipe(recipe)
    warnings = collect_warnings(model)
    size_warnings = [w for w in warnings if "size_broadening" in w["field_path"]]
    strain_warnings = [w for w in warnings if "strain_broadening" in w["field_path"]]
    assert len(size_warnings) == 1
    assert len(strain_warnings) == 1
    assert size_warnings[0]["code"] == "gsasii_broadening_default_applied"
    assert strain_warnings[0]["code"] == "gsasii_broadening_default_applied"
    assert "payload.phases.LaB6.peak_broadening.size_broadening" in size_warnings[0]["field_path"]
    assert "payload.phases.LaB6.peak_broadening.strain_broadening" in strain_warnings[0]["field_path"]
    # Check the defaults
    pb = model.payload.phases["LaB6"].peak_broadening
    assert pb.size_broadening.isotropic_size.value == 10.0
    assert pb.size_broadening.isotropic_size.refine_flag is False
    assert pb.strain_broadening.isotropic_strain.value == 0.0
    assert pb.strain_broadening.isotropic_strain.refine_flag is False


def test_peak_broadening_only_strain_stated_gives_size_warning():
    """Only strain stated gives exactly one warning (size)."""
    recipe = copy.deepcopy(_rietveld_recipe())
    recipe["payload"]["phases"]["LaB6"]["peak_broadening"] = {
        "strain_broadening": {
            "model": "isotropic",
            "isotropic_strain": p(1000.0, True),
            "LG_eta": p(1.0)
        }
    }
    model = validate_recipe(recipe)
    warnings = collect_warnings(model)
    assert len(warnings) == 1
    assert warnings[0]["code"] == "gsasii_broadening_default_applied"
    assert "size_broadening" in warnings[0]["field_path"]


def test_peak_broadening_both_stated_no_warning():
    """Both size and strain stated gives no warnings."""
    recipe = copy.deepcopy(_rietveld_recipe())
    recipe["payload"]["phases"]["LaB6"]["peak_broadening"] = {
        "size_broadening": {
            "model": "isotropic",
            "isotropic_size": p(5.0, True),
            "LG_eta": p(1.0)
        },
        "strain_broadening": {
            "model": "isotropic",
            "isotropic_strain": p(1000.0, True),
            "LG_eta": p(1.0)
        }
    }
    model = validate_recipe(recipe)
    warnings = collect_warnings(model)
    assert len(warnings) == 0


def test_peak_broadening_uniaxial_rejected():
    recipe = copy.deepcopy(_rietveld_recipe())
    recipe["payload"]["phases"]["LaB6"]["peak_broadening"] = {
        "size_broadening": {
            "model": "uniaxial",
            "isotropic_size": p(5.0),
            "LG_eta": p(1.0)
        }
    }
    with pytest.raises(ValidationError, match="isotropic"):
        validate_recipe(recipe)


def test_peak_broadening_idempotence():
    """Re-validating model.model_dump(mode='json') gives no warnings and equal dump."""
    recipe = copy.deepcopy(_rietveld_recipe())
    # Leave out peak_broadening to trigger defaults
    if "peak_broadening" in recipe["payload"]["phases"]["LaB6"]:
        del recipe["payload"]["phases"]["LaB6"]["peak_broadening"]
    model1 = validate_recipe(recipe)
    dump1 = model1.model_dump(mode="json")

    # Re-validate the dump
    model2 = validate_recipe(dump1)
    warnings2 = collect_warnings(model2)
    dump2 = model2.model_dump(mode="json")

    assert len(warnings2) == 0
    assert dump1 == dump2


# --- 10. Simulation mode (refinement_cycles == 1) -----------------------------


def test_simulation_instrument_correction_refine_rejected():
    """Simulation with instrument correction refine flag true is rejected."""
    recipe = copy.deepcopy(_rietveld_recipe())
    recipe["payload"]["refinement_controls"]["refinement_cycles"] = 1
    recipe["payload"]["instrument"]["corrections"]["polarization"] = [0.99, True]
    with pytest.raises(ValidationError) as exc:
        validate_recipe(recipe)
    errors = exc.value.errors()
    locs = [e["loc"] for e in errors]
    assert ("payload", "instrument", "corrections", "polarization") in locs
    assert any("simulation" in e["msg"].lower() for e in errors)


def test_simulation_instrument_broadening_refine_rejected():
    """Simulation with instrument broadening refine flag true is rejected."""
    recipe = copy.deepcopy(_rietveld_recipe())
    recipe["payload"]["refinement_controls"]["refinement_cycles"] = 1
    recipe["payload"]["instrument"]["broadening"]["U"] = [18.7, True]
    with pytest.raises(ValidationError) as exc:
        validate_recipe(recipe)
    errors = exc.value.errors()
    locs = [e["loc"] for e in errors]
    assert ("payload", "instrument", "broadening", "U") in locs


def test_simulation_phase_scale_refine_rejected():
    """Simulation with phase scale refine flag true is rejected."""
    recipe = copy.deepcopy(_rietveld_recipe())
    recipe["payload"]["refinement_controls"]["refinement_cycles"] = 1
    # scale already has refine_flag True in the fixture
    with pytest.raises(ValidationError) as exc:
        validate_recipe(recipe)
    errors = exc.value.errors()
    locs = [e["loc"] for e in errors]
    assert ("payload", "phases", "LaB6", "scale") in locs


def test_simulation_cell_length_refine_rejected():
    """Simulation with cell length refine flag true is rejected."""
    recipe = copy.deepcopy(_rietveld_recipe())
    recipe["payload"]["refinement_controls"]["refinement_cycles"] = 1
    # Make all flags false first, then set one to true
    phase = recipe["payload"]["phases"]["LaB6"]
    phase["scale"] = [1.0, False]
    phase["unit_cell"]["a"] = [4.15682, True]
    phase["unit_cell"]["b"] = [4.15682, False]
    phase["unit_cell"]["c"] = [4.15682, False]
    phase["atoms"]["B"]["x"] = [0.2021, False]
    with pytest.raises(ValidationError) as exc:
        validate_recipe(recipe)
    errors = exc.value.errors()
    # With cubic symmetry, a, b, c refine together, so all three should error
    assert any("unit_cell" in str(e["loc"]) for e in errors)


def test_simulation_atom_coordinate_refine_rejected():
    """Simulation with atom coordinate refine flag true is rejected."""
    recipe = copy.deepcopy(_rietveld_recipe())
    recipe["payload"]["refinement_controls"]["refinement_cycles"] = 1
    # Make all flags false
    phase = recipe["payload"]["phases"]["LaB6"]
    phase["scale"] = [1.0, False]
    phase["unit_cell"]["a"] = [4.15682, False]
    phase["unit_cell"]["b"] = [4.15682, False]
    phase["unit_cell"]["c"] = [4.15682, False]
    phase["atoms"]["B"]["x"] = [0.2021, True]
    with pytest.raises(ValidationError) as exc:
        validate_recipe(recipe)
    errors = exc.value.errors()
    locs = [e["loc"] for e in errors]
    assert ("payload", "phases", "LaB6", "atoms", "B", "x") in locs


def test_simulation_background_chebyshev_refine_flag_rejected():
    """Simulation with background chebyshev refine_flag true is rejected."""
    recipe = copy.deepcopy(_rietveld_recipe())
    recipe["payload"]["refinement_controls"]["refinement_cycles"] = 1
    # Make all other flags false
    phase = recipe["payload"]["phases"]["LaB6"]
    phase["scale"] = [1.0, False]
    phase["unit_cell"]["a"] = [4.15682, False]
    phase["unit_cell"]["b"] = [4.15682, False]
    phase["unit_cell"]["c"] = [4.15682, False]
    phase["atoms"]["B"]["x"] = [0.2021, False]
    recipe["payload"]["background"] = {
        "chebyshev": {
            "num_coefficients": 2,
            "coefficients": [0.0, 1.0],
            "refine_flag": True
        }
    }
    with pytest.raises(ValidationError) as exc:
        validate_recipe(recipe)
    errors = exc.value.errors()
    locs = [e["loc"] for e in errors]
    assert ("payload", "background", "chebyshev", "refine_flag") in locs


def test_simulation_background_peak_flags_rejected():
    """Simulation with background peak flags true is rejected."""
    recipe = copy.deepcopy(_rietveld_recipe())
    recipe["payload"]["refinement_controls"]["refinement_cycles"] = 1
    # Make all other flags false
    phase = recipe["payload"]["phases"]["LaB6"]
    phase["scale"] = [1.0, False]
    phase["unit_cell"]["a"] = [4.15682, False]
    phase["unit_cell"]["b"] = [4.15682, False]
    phase["unit_cell"]["c"] = [4.15682, False]
    phase["atoms"]["B"]["x"] = [0.2021, False]
    recipe["payload"]["background"] = {
        "single_peaks": {
            "positions": [p(5.0, True)],
            "intensities": [p(10.0)],
            "pv_gaussian_sigma_sq": [p(1.0)],
            "pv_lorentzian_gamma": [p(0.5)]
        }
    }
    with pytest.raises(ValidationError) as exc:
        validate_recipe(recipe)
    errors = exc.value.errors()
    locs = [e["loc"] for e in errors]
    assert ("payload", "background", "single_peaks", "positions", 0) in locs


def test_simulation_all_flags_false_accepted():
    """Simulation with all refine flags false is accepted."""
    recipe = copy.deepcopy(_rietveld_recipe())
    recipe["payload"]["refinement_controls"]["refinement_cycles"] = 1
    # Make all flags false
    phase = recipe["payload"]["phases"]["LaB6"]
    phase["scale"] = [1.0, False]
    phase["unit_cell"]["a"] = [4.15682, False]
    phase["unit_cell"]["b"] = [4.15682, False]
    phase["unit_cell"]["c"] = [4.15682, False]
    phase["atoms"]["La"]["Uiso"] = [0.00858, False]
    phase["atoms"]["B"]["x"] = [0.2021, False]
    phase["atoms"]["B"]["Uiso"] = [0.009, False]
    # Also set all instrument broadening flags to false
    inst = recipe["payload"]["instrument"]["broadening"]
    for k in "UVWXYZ":
        inst[k][1] = False
    model = validate_recipe(recipe)
    assert model.payload.refinement_controls.refinement_cycles == 1


def test_simulation_spf_single_peaks_flags_rejected():
    """SPF simulation with single_peaks flags true is rejected."""
    recipe = copy.deepcopy(_spf_recipe())
    recipe["payload"]["refinement_controls"]["refinement_cycles"] = 1
    # The fixture has flags true by default
    with pytest.raises(ValidationError) as exc:
        validate_recipe(recipe)
    errors = exc.value.errors()
    locs = [e["loc"] for e in errors]
    assert ("payload", "single_peaks", "positions", 0) in locs


# --- 11. SPF validation -------------------------------------------------------


def test_spf_phases_key_rejected():
    """SPF payload with phases key is rejected (extra forbidden)."""
    recipe = copy.deepcopy(_spf_recipe())
    recipe["payload"]["phases"] = {"LaB6": _phase_lab6()}
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        validate_recipe(recipe)


def test_spf_single_peaks_missing_rejected():
    recipe = copy.deepcopy(_spf_recipe())
    del recipe["payload"]["single_peaks"]
    with pytest.raises(ValidationError) as exc:
        validate_recipe(recipe)
    errors = exc.value.errors()
    locs = [e["loc"] for e in errors]
    assert ("payload", "single_peaks") in locs


def test_spf_single_peak_fitting_mode_missing_rejected():
    recipe = copy.deepcopy(_spf_recipe())
    del recipe["payload"]["refinement_controls"]["single_peak_fitting_mode"]
    with pytest.raises(ValidationError) as exc:
        validate_recipe(recipe)
    errors = exc.value.errors()
    locs = [e["loc"] for e in errors]
    assert ("payload", "refinement_controls", "single_peak_fitting_mode") in locs


def test_spf_sigma_sq_below_floor_rejected():
    """SPF sigma_sq 0.0005 is below the floor of 0.001 (EB-37)."""
    recipe = copy.deepcopy(_spf_recipe())
    recipe["payload"]["single_peaks"]["pv_gaussian_sigma_sq"] = [p(0.0005)]
    with pytest.raises(ValidationError) as exc:
        validate_recipe(recipe)
    errors = exc.value.errors()
    # Check the message mentions EB-37
    assert any("EB-37" in e["msg"] for e in errors)


def test_spf_gamma_below_floor_rejected():
    """SPF gamma 0.0005 is below the floor of 0.001."""
    recipe = copy.deepcopy(_spf_recipe())
    recipe["payload"]["single_peaks"]["pv_lorentzian_gamma"] = [p(0.0005)]
    with pytest.raises(ValidationError) as exc:
        validate_recipe(recipe)
    errors = exc.value.errors()
    locs = [e["loc"] for e in errors]
    assert ("payload", "single_peaks", "pv_lorentzian_gamma", 0) in locs


def test_rietveld_with_single_peaks_payload_key_rejected():
    """Rietveld payload with single_peaks key is rejected."""
    recipe = copy.deepcopy(_rietveld_recipe())
    recipe["payload"]["single_peaks"] = {
        "positions": [p(5.0)],
        "intensities": [p(10.0)],
        "pv_gaussian_sigma_sq": [p(1.0)],
        "pv_lorentzian_gamma": [p(0.5)]
    }
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        validate_recipe(recipe)


# --- 12. Phase names ----------------------------------------------------------


def test_phase_names_duplicate_case_insensitive_rejected():
    """Two phases 'LaB6' and 'lab6' are rejected (must be unique ignoring case)."""
    recipe = copy.deepcopy(_rietveld_recipe())
    recipe["payload"]["phases"]["lab6"] = copy.deepcopy(recipe["payload"]["phases"]["LaB6"])
    with pytest.raises(ValidationError, match="differ only in case"):
        validate_recipe(recipe)


def test_phase_name_starts_with_digit_rejected():
    """Phase name '1abc' is rejected."""
    recipe = copy.deepcopy(_rietveld_recipe())
    recipe["payload"]["phases"] = {"1abc": _phase_lab6()}
    with pytest.raises(ValidationError):
        validate_recipe(recipe)


# --- 13. Core rules inherited through GsasiiPhase -----------------------------


def test_core_space_group_compact_rejected():
    """Space group 'Pm-3m' (compact, not canonical) is rejected."""
    recipe = copy.deepcopy(_rietveld_recipe())
    recipe["payload"]["phases"]["LaB6"]["space_group"] = "Pm-3m"
    with pytest.raises(ValidationError) as exc:
        validate_recipe(recipe)
    errors = exc.value.errors()
    locs = [e["loc"] for e in errors]
    assert ("payload", "phases", "LaB6", "space_group") in locs


def test_core_atom_coordinate_symmetry_violation_rejected():
    """B at y=0.4999999 violates the allowed value (should be exactly 0.5)."""
    recipe = copy.deepcopy(_rietveld_recipe())
    recipe["payload"]["phases"]["LaB6"]["atoms"]["B"]["y"] = [0.4999999, False]
    with pytest.raises(ValidationError) as exc:
        validate_recipe(recipe)
    # The exact location might vary, but it should error on the atom coordinate
    errors = exc.value.errors()
    assert any("B" in str(e["loc"]) and "y" in str(e["loc"]) for e in errors)


def test_core_refining_symmetry_constrained_angle_rejected():
    """Refining alpha (fixed by symmetry to 90 in cubic) is rejected."""
    recipe = copy.deepcopy(_rietveld_recipe())
    recipe["payload"]["phases"]["LaB6"]["unit_cell"]["alpha"] = [90.0, True]
    with pytest.raises(ValidationError) as exc:
        validate_recipe(recipe)
    errors = exc.value.errors()
    # Should error about symmetry constraining it
    assert any("symmetry" in e["msg"].lower() or "constrained" in e["msg"].lower() for e in errors)


# --- 14. collect_warnings: Uaniso warnings ------------------------------------


def test_uaniso_not_positive_definite_warning():
    """Atom with non-positive-definite Uaniso gives a structured warning."""
    recipe = copy.deepcopy(_rietveld_recipe())
    recipe["payload"]["phases"]["LaB6"]["atoms"]["La"]["ADP"] = "Uaniso"
    # Remove Uiso when using Uaniso
    del recipe["payload"]["phases"]["LaB6"]["atoms"]["La"]["Uiso"]
    recipe["payload"]["phases"]["LaB6"]["atoms"]["La"]["Uaniso"] = {
        "U11": p(-0.01), "U22": p(-0.01), "U33": p(-0.01),
        "U12": p(0.0), "U13": p(0.0), "U23": p(0.0)
    }
    model = validate_recipe(recipe)
    warnings = collect_warnings(model)
    uaniso_warnings = [w for w in warnings if w["code"] == "uaniso_not_positive_definite"]
    assert len(uaniso_warnings) == 1
    assert "payload.phases.LaB6.atoms.La.Uaniso" in uaniso_warnings[0]["field_path"]


# --- 15. Idempotence ----------------------------------------------------------


def test_idempotence_validate_recipe_on_model():
    """validate_recipe(model) returns the same object (idempotent)."""
    recipe = copy.deepcopy(_rietveld_recipe())
    model1 = validate_recipe(recipe)
    model2 = validate_recipe(model1)
    assert model1 is model2


# --- 16. Gateway routing ------------------------------------------------------


def test_gateway_validate_returns_gsasii_rietveld_recipe():
    """gateway.validate(recipe) returns GsasiiRietveldRecipe."""
    recipe = copy.deepcopy(_rietveld_recipe())
    model = gateway.validate(recipe)
    assert isinstance(model, GsasiiRietveldRecipe)


def test_gateway_validate_returns_gsasii_spf_recipe():
    """gateway.validate(spf_recipe) returns GsasiiSpfRecipe."""
    recipe = copy.deepcopy(_spf_recipe())
    model = gateway.validate(recipe)
    assert isinstance(model, GsasiiSpfRecipe)


def test_gateway_capabilities_has_expected_keys():
    """gateway.capabilities() contains expected keys."""
    caps = gateway.capabilities()
    assert "engine_schema_version" in caps
    assert caps["engine_schema_version"] == "0.1.0"
    assert "supported_engine_schemas" in caps
    assert caps["supported_engine_schemas"] == "==0.1.0"
    assert "requires_core_schema" in caps
    assert caps["requires_core_schema"] == "==0.1.0"
    assert "workflows" in caps
    assert "gsasii.rietveld" in caps["workflows"]
    assert "gsasii.spf" in caps["workflows"]


def test_powderline_validate_returns_gsasii_rietveld_recipe():
    """powderline.validate(native_recipe).recipe is a GsasiiRietveldRecipe, with its warnings alongside."""
    recipe = copy.deepcopy(_rietveld_recipe())
    result = powderline.validate(recipe)
    assert isinstance(result, powderline.ValidationResult)
    assert isinstance(result.recipe, GsasiiRietveldRecipe)
    assert result.warnings == collect_warnings(result.recipe)


# --- re/04 PR review: value rules (A126), SPF width source (A127), never-null blocks ---------------


@pytest.mark.parametrize("value", [0.0, -0.1665])
def test_wavelength_not_positive_rejected(value):
    recipe = copy.deepcopy(_rietveld_recipe())
    recipe["payload"]["instrument"]["radiation"]["wavelength"] = p(value)
    with pytest.raises(ValidationError) as exc:
        validate_recipe(recipe)
    assert _errors(exc) == [(("payload", "instrument", "radiation", "wavelength"), "value_error")]
    assert "wavelength must be > 0" in str(exc.value)


@pytest.mark.parametrize("value", [0.0, -1.0])
def test_crystallite_size_not_positive_rejected(value):
    recipe = copy.deepcopy(_rietveld_recipe())
    recipe["payload"]["phases"]["LaB6"]["peak_broadening"] = {"size_broadening": {
        "model": "isotropic", "isotropic_size": p(value), "LG_eta": p(1.0)}}
    with pytest.raises(ValidationError) as exc:
        validate_recipe(recipe)
    assert _errors(exc) == [(("payload", "phases", "LaB6", "peak_broadening", "size_broadening", "isotropic_size"),
                             "value_error")]


def test_lg_eta_and_polarization_have_no_limits():
    """User decisions, not engine requirements (A126): GSAS-II runs LG_eta 2 and polarization 1.5."""
    recipe = copy.deepcopy(_rietveld_recipe())
    recipe["payload"]["instrument"]["corrections"]["polarization"] = p(1.5)
    recipe["payload"]["phases"]["LaB6"]["peak_broadening"] = {"size_broadening": {
        "model": "isotropic", "isotropic_size": p(1.0), "LG_eta": p(2.0)}}
    validate_recipe(recipe)


@pytest.mark.parametrize("path", [("peak_broadening",), ("peak_broadening", "size_broadening"),
                                  ("peak_broadening", "strain_broadening")])
def test_peak_broadening_null_rejected_with_leave_out_message(path):
    recipe = copy.deepcopy(_rietveld_recipe())
    phase = recipe["payload"]["phases"]["LaB6"]
    if len(path) == 2:
        phase["peak_broadening"] = {}
        phase["peak_broadening"][path[1]] = None
    else:
        phase["peak_broadening"] = None
    with pytest.raises(ValidationError) as exc:
        validate_recipe(recipe)
    assert _errors(exc) == [(("payload", "phases", "LaB6") + path, "value_error")]
    assert "must not be null; leave it out instead" in str(exc.value)


@pytest.mark.parametrize("model, pointer", [
    (GsasiiRietveldRecipe, ("$defs", "Instrument", "properties", "description")),
    (GsasiiRietveldRecipe, ("$defs", "Background", "properties", "single_peaks")),
    (GsasiiRietveldRecipe, ("$defs", "RietveldPayload", "properties", "fit_range")),
    (GsasiiSpfRecipe, ("$defs", "SpfPayload", "properties", "fit_range")),
])
def test_json_schema_shows_no_null_for_blocks_that_are_never_null(model, pointer):
    node = model.model_json_schema()
    for key in pointer:
        node = node[key]
    assert "null" not in json.dumps(node) and "default" not in node


def test_spf_peak_position_outside_fit_window_rejected():
    recipe = copy.deepcopy(_spf_recipe())
    recipe["payload"]["xrd_data"] = {"tth": [1.0, 2.0, 10.0, 15.0], "Itth": [1.0] * 4, "Itth_weights": [1.0] * 4}
    recipe["payload"]["fit_range"] = [3.0, 15.0]  # two weighted points inside (A154 N9); the peak at 2.29 is not
    with pytest.raises(ValidationError) as exc:
        validate_recipe(recipe)
    assert _errors(exc) == [(("payload", "single_peaks", "positions", 0), "outside_fit_window")]
    assert "Peak List peak position 2.29 is outside the fit window [3.0, 15.0]" in str(exc.value)


@pytest.mark.parametrize("term", list("UVWXYZ"))
def test_spf_own_widths_reject_refined_profile_term(term):
    """use_instrument_profile false: GSAS-II never varies U..Z (EB-53), so a refined one is an error (A127)."""
    recipe = copy.deepcopy(_spf_recipe())
    recipe["payload"]["instrument"]["broadening"][term][1] = True
    with pytest.raises(ValidationError) as exc:
        validate_recipe(recipe)
    assert _errors(exc) == [(("payload", "instrument", "broadening", term), "spf_width_source")]


@pytest.mark.parametrize("width", ["pv_gaussian_sigma_sq", "pv_lorentzian_gamma"])
def test_spf_instrument_profile_rejects_refined_peak_width(width):
    """use_instrument_profile true: a refined peak width would replace the profile for that peak (EB-53, A127)."""
    recipe = copy.deepcopy(_spf_recipe())
    payload = recipe["payload"]
    payload["refinement_controls"]["single_peak_fitting_mode"]["use_instrument_profile"] = True
    other = "pv_lorentzian_gamma" if width == "pv_gaussian_sigma_sq" else "pv_gaussian_sigma_sq"
    payload["single_peaks"][other][0][1] = False
    with pytest.raises(ValidationError) as exc:
        validate_recipe(recipe)
    assert _errors(exc) == [(("payload", "single_peaks", width, 0), "spf_width_source")]


def test_spf_instrument_profile_with_refined_profile_terms_accepted():
    recipe = copy.deepcopy(_spf_recipe())
    payload = recipe["payload"]
    payload["refinement_controls"]["single_peak_fitting_mode"]["use_instrument_profile"] = True
    for name in ("pv_gaussian_sigma_sq", "pv_lorentzian_gamma"):
        payload["single_peaks"][name][0][1] = False
    for term in "UVWXY":
        payload["instrument"]["broadening"][term][1] = True
    validate_recipe(recipe)



# --- P-33: the gsasii defaults a recipe may leave out are warned, like size/strain ------------------

def _codes(recipe, code):
    return [w for w in collect_warnings(validate_recipe(recipe)) if w["code"] == code]


def test_background_left_out_gives_warning():
    recipe = copy.deepcopy(_rietveld_recipe())
    recipe["payload"].pop("background", None)
    ws = _codes(recipe, "gsasii_background_default_applied")
    assert len(ws) == 1
    assert ws[0]["field_path"] == "payload.background" and ws[0].get("level", "warning") == "warning"
    assert "one fixed Chebyshev term" in ws[0]["message"] and "1.0" in ws[0]["message"]


def test_background_without_chebyshev_gives_warning_at_chebyshev():
    recipe = copy.deepcopy(_rietveld_recipe())
    recipe["payload"]["background"] = {}
    ws = _codes(recipe, "gsasii_background_default_applied")
    assert [w["field_path"] for w in ws] == ["payload.background.chebyshev"]


def test_background_stated_gives_no_background_warning():
    assert _codes(copy.deepcopy(_rietveld_recipe()), "gsasii_background_default_applied") == []


def test_refinement_cycles_left_out_gives_warning():
    recipe = copy.deepcopy(_rietveld_recipe())
    recipe["payload"]["refinement_controls"] = {}
    ws = _codes(recipe, "gsasii_refinement_cycles_default_applied")
    assert [w["field_path"] for w in ws] == ["payload.refinement_controls.refinement_cycles"]
    assert "5" in ws[0]["message"] and ws[0].get("level", "warning") == "warning"


def test_refinement_cycles_stated_gives_no_warning():
    assert _codes(copy.deepcopy(_rietveld_recipe()), "gsasii_refinement_cycles_default_applied") == []


def test_spf_refinement_cycles_left_out_gives_warning():
    import json
    from pathlib import Path
    path = Path(__file__).resolve().parent.parent / "examples" / "example_LaB6_singlepeakfit" / "input.json"
    recipe = json.loads(path.read_text(encoding="utf-8"))
    recipe["payload"]["refinement_controls"].pop("refinement_cycles", None)
    ws = _codes(recipe, "gsasii_refinement_cycles_default_applied")
    assert [w["field_path"] for w in ws] == ["payload.refinement_controls.refinement_cycles"]
