"""Native ``topas.rietveld`` / ``topas.spf`` schemas (re/05; devkit draft rev 3, A138-A147).

Engine behaviour behind the rules: devkit ``tasks/re05-topas6-compat.md`` (C-numbers).
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import gemmi
import pytest

from pydantic import ValidationError

from powderline.gateways.topas.schema import (

    EIGHT_PI_SQ,
    TOPAS_UNREADABLE_SETTINGS,
    TopasRietveldRecipe,
    TopasSpfRecipe,
    topas_space_group,
    topas_symbol,
    validate_recipe,
)
from powderline.schema_core import collect_warnings, parameters_requested

pytestmark = pytest.mark.topas_gen

DATA = Path(__file__).resolve().parent / "data"


def P(value, flag=False, lo=None, hi=None):
    return [value, flag, lo, hi]


def _xrd():
    tth = [round(1.0 + 0.01 * i, 4) for i in range(1400)]
    return {"tth": tth, "Itth": [100.0] * len(tth), "Itth_weights": [0.01] * len(tth)}


def _instrument():
    return {
        "radiation": {"ymin_on_ymax": 0.0001, "la": P(1.0), "lo": P(0.1665), "lh": P(0.0001)},
        "geometry": {"Rs": 1000.0},
        "corrections": {"Zero_Error": {"th2_offset": P(0.0, True)},
                        "LP_Factor": {"monochromator_angle": P(90.0)},
                        "Simple_Axial_Model": {"axial_length_mm": P(1.0, True)}},
        "broadening": {"peak_type": "TCHZ_Peak_Type",
                       "parameters": {k: P(v, True) for k, v in
                                      dict(U=0.0001, V=-0.0002, W=0.0003, Z=0.0, X=0.002, Y=0.0001).items()}},
    }


def _controls(iters=100000):
    return {"iters": iters, "chi2_convergence_criteria": 0.001, "x_calculation_step": 0.001}


def _rietveld():
    return {
        "schema_name": "topas.rietveld", "core_schema_version": "0.1.0", "engine_schema_version": "0.1.0",
        "engine_version": "6",
        "payload": {
            "xrd_data": _xrd(), "fit_range": [2.0, 14.0], "instrument": _instrument(),
            "background": {
                "chebyshev": {"num_coefficients": 3, "coefficients": [10, 5, 1], "refine_flag": True},
                "One_on_X": P(100.0, True),
                "peaks": [{"xo": P(3.2, True), "I": P(50.0, True), "peak_type": "pv",
                           "parameters": {"pv_fwhm": P(0.8, True), "pv_lor": P(0.5, True)}}],
            },
            "phases": {"LaB6": {
                "space_group": "P m -3 m",
                "unit_cell": {"a": P(4.1569, True), "b": P(4.1569, True), "c": P(4.1569, True),
                              "alpha": P(90), "beta": P(90), "gamma": P(90)},
                "atoms": {
                    "La1": {"element": "La", "x": P(0), "y": P(0), "z": P(0), "occupancy": P(1),
                            "ADP": "Uiso", "Uiso": P(0.005, True)},
                    "B1": {"element": "B", "x": P(0.1993, True, 0.15, 0.25), "y": P(0.5), "z": P(0.5),
                           "occupancy": P(1), "ADP": "Uiso", "Uiso": P(0.006, True)},
                },
                "scale": P(1.5e-6, True),
                "peak_broadening": {"size_broadening": {"model": "isotropic", "CS_L": P(300.0, True)}},
            }},
            "refinement_controls": _controls(),
        },
    }


def _spf():
    instrument = _instrument()
    del instrument["geometry"], instrument["corrections"]["Simple_Axial_Model"]
    return {
        "schema_name": "topas.spf", "core_schema_version": "0.1.0", "engine_schema_version": "0.1.0",
        "engine_version": "6",
        "payload": {
            "xrd_data": _xrd(), "instrument": instrument,
            "single_peaks": [{"xo": P(5.0, True), "I": P(10.0, True), "gauss_fwhm": P(0.01, True)},
                             {"xo": P(7.0, True), "I": P(5.0, True)}],
            "refinement_controls": _controls(),
        },
    }


def _errors(exc) -> list[tuple]:
    return [(e["loc"], e["type"]) for e in exc.value.errors()]


def _fails(recipe, loc, kind=None):
    with pytest.raises(ValidationError) as exc:
        validate_recipe(recipe)
    errors = _errors(exc)
    assert any(e[0] == loc and (kind is None or e[1] == kind) for e in errors), errors
    return errors


# --- valid recipes, routing, versions ---------------------------------------------------


@pytest.mark.parametrize("build, model", [(_rietveld, TopasRietveldRecipe), (_spf, TopasSpfRecipe)])
def test_valid_recipe_round_trips(build, model):
    m = validate_recipe(build())
    assert isinstance(m, model)
    assert validate_recipe(m) is m  # idempotent (A50)
    assert validate_recipe(m.model_dump(mode="json")) == m


def test_unknown_topas_workflow_reported_at_schema_name():
    r = _rietveld()
    r["schema_name"] = "topas.reitveld"
    _fails(r, ("schema_name",), "schema_name")


def test_engine_version_required():
    r = _rietveld()
    del r["engine_version"]
    _fails(r, ("engine_version",), "missing")


@pytest.mark.parametrize("version", ["7", "5", "six"])
def test_engine_version_outside_supported_set(version):
    r = _rietveld()
    r["engine_version"] = version
    _fails(r, ("engine_version",))


# --- space groups (A105, C16) -------------------------------------------------------------


def test_space_group_table():
    """The committed table equals the rule over gemmi's canonical names.

    Regenerate after a deliberate change: write ``f"{xhm}\\t{topas_space_group(xhm)}"`` for every
    accepted name of ``gemmi.spacegroup_table()`` below the header of ``tests/data/topas_space_groups.txt``.
    """
    committed = {}
    for line in (DATA / "topas_space_groups.txt").read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#"):
            xhm, sym = line.split("\t")
            committed[xhm] = sym
    current = {}
    for sg in gemmi.spacegroup_table():
        try:
            current[sg.xhm()] = topas_space_group(sg.xhm())
        except ValueError:
            assert sg.xhm() in TOPAS_UNREADABLE_SETTINGS
    assert current == committed
    assert len(committed) == 541 and len(TOPAS_UNREADABLE_SETTINGS) == 23


@pytest.mark.parametrize("xhm, sym", [("P m -3 m", "pm-3m"), ("F d -3 m:1", "fd-3m"), ("F d -3 m:2", "fd-3m:2"),
                                      ("R -3 m:H", "r-3m"), ("R -3 m:R", "r-3mr"), ("P 1 21/c 1", "p121/c1")])
def test_symbol_rule(xhm, sym):
    assert topas_symbol(xhm) == sym


@pytest.mark.parametrize("xhm", ["C 1 21 1", "I 1 21 1", "C 4 2 21", "B 1 2 1", "A b a m"])
def test_unreadable_setting_rejected(xhm):
    with pytest.raises(ValueError, match="TOPAS cannot express"):
        topas_space_group(xhm)


# --- TOPAS's fixed default limits (A138, C20) --------------------------------------------


def test_uiso_start_above_topas_beq_limit_rejected():
    r = _rietveld()
    r["payload"]["phases"]["LaB6"]["atoms"]["La1"]["Uiso"] = P(21 / EIGHT_PI_SQ, True)
    _fails(r, ("payload", "phases", "LaB6", "atoms", "La1", "Uiso"), "topas_default_limit")


def test_stated_bound_replaces_topas_limit():
    r = _rietveld()
    r["payload"]["phases"]["LaB6"]["atoms"]["La1"]["Uiso"] = P(21 / EIGHT_PI_SQ, True, None, 0.5)
    validate_recipe(r)


def test_limits_act_only_on_refined_parameters():
    r = _rietveld()
    r["payload"]["phases"]["LaB6"]["atoms"]["La1"]["Uiso"] = P(21 / EIGHT_PI_SQ, False)
    validate_recipe(r)


@pytest.mark.parametrize("path, value", [
    (("phases", "LaB6", "scale"), 1e-12),
    (("phases", "LaB6", "peak_broadening", "size_broadening", "CS_L"), 0.2),
    (("instrument", "broadening", "parameters", "X"), -0.01),
    (("instrument", "corrections", "Simple_Axial_Model", "axial_length_mm"), 60.0),
    (("instrument", "corrections", "Zero_Error", "th2_offset"), 2.0),
    (("background", "One_on_X"), 0.0),
])
def test_refined_start_outside_fixed_limit_rejected(path, value):
    r = _rietveld()
    node = r["payload"]
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = P(value, True)
    _fails(r, ("payload",) + path, "topas_default_limit")


def test_refined_cell_length_below_topas_floor_rejected():
    r = _rietveld()
    for n in "abc":
        r["payload"]["phases"]["LaB6"]["unit_cell"][n] = P(1.2, True)
    _fails(r, ("payload", "phases", "LaB6", "unit_cell", "a"), "topas_default_limit")


# --- instrument (A140, A141, A143, C26, C30) ----------------------------------------------


def test_lh_required():
    r = _rietveld()
    r["payload"]["instrument"]["radiation"]["lg"] = r["payload"]["instrument"]["radiation"].pop("lh")
    _fails(r, ("payload", "instrument", "radiation", "lh"), "missing")


def test_lg_with_lh_accepted():
    r = _rietveld()
    r["payload"]["instrument"]["radiation"]["lg"] = P(0.001)
    validate_recipe(r)


def test_wavelength_positive():
    r = _rietveld()
    r["payload"]["instrument"]["radiation"]["lo"] = P(0.0)
    _fails(r, ("payload", "instrument", "radiation", "lo"), "topas_positive")


def test_axial_model_needs_rs():
    r = _rietveld()
    del r["payload"]["instrument"]["geometry"]
    _fails(r, ("payload", "instrument", "geometry", "Rs"), "topas_radius_needed")


def test_full_axial_model_needs_rp_and_rs():
    r = _rietveld()
    c = r["payload"]["instrument"]["corrections"]
    del c["Simple_Axial_Model"]
    c["Full_Axial_Model"] = {"filament_length": P(12.0), "sample_length": P(15.0),
                             "receiving_slit_length": P(12.0), "axial_n_beta": 20}
    _fails(r, ("payload", "instrument", "geometry", "Rp"), "topas_radius_needed")
    r["payload"]["instrument"]["geometry"]["Rp"] = 217.5
    validate_recipe(r)


def test_unused_radius_rejected():
    r = _rietveld()
    r["payload"]["instrument"]["geometry"]["Rp"] = 217.5
    _fails(r, ("payload", "instrument", "geometry", "Rp"), "topas_radius_unused")


def test_exclusive_corrections():
    r = _rietveld()
    r["payload"]["instrument"]["corrections"]["LP_Factor_Synchrotron"] = {"pp": P(0.05), "mono": P(90.0)}
    _fails(r, ("payload", "instrument", "corrections", "LP_Factor_Synchrotron"), "topas_exclusive")


def test_lp_factor_synchrotron_never_refines_both():
    r = _rietveld()
    c = r["payload"]["instrument"]["corrections"]
    del c["LP_Factor"]
    c["LP_Factor_Synchrotron"] = {"pp": P(0.05, True), "mono": P(90.0, True)}
    _fails(r, ("payload", "instrument", "corrections", "LP_Factor_Synchrotron", "mono"), "topas_lp_sync_correlated")


def test_capillary_v6_keywords_only():
    r = _rietveld()
    r["payload"]["instrument"]["corrections"]["capillary"] = {"diameter_mm": P(0.5), "u_cm_inv": P(10.0),
                                                              "beam": "parallel"}
    validate_recipe(r)
    r["payload"]["instrument"]["corrections"]["capillary"]["beam"] = "convergent"  # TOPAS 7 only (C4)
    _fails(r, ("payload", "instrument", "corrections", "capillary", "beam"))


def test_peak_type_parameter_names():
    r = _rietveld()
    params = r["payload"]["instrument"]["broadening"]["parameters"]
    del params["Y"]
    params["Q"] = P(1.0)
    errors = _fails(r, ("payload", "instrument", "broadening", "parameters"), "missing_parameter")
    assert (("payload", "instrument", "broadening", "parameters", "Q"), "unexpected_parameter") in errors


@pytest.mark.parametrize("peak_type, names", [("PV_Peak_Type", ("ha", "hb", "hc", "lora", "lorb", "lorc")),
                                              ("PVII_Peak_Type", ("ha", "hb", "hc", "ma", "mb", "mc"))])
def test_other_peak_types(peak_type, names):
    r = _rietveld()
    r["payload"]["instrument"]["broadening"] = {"peak_type": peak_type,
                                                "parameters": {n: P(0.01) for n in names}}
    validate_recipe(r)


# --- background, phase, SPF ----------------------------------------------------------------


def test_background_peak_outside_window():
    r = _rietveld()
    r["payload"]["background"]["peaks"][0]["xo"] = P(1.5, True)
    _fails(r, ("payload", "background", "peaks", 0, "xo"), "outside_fit_window")


def test_background_peak_type_parameters():
    r = _rietveld()
    r["payload"]["background"]["peaks"][0]["peak_type"] = "spvii"
    _fails(r, ("payload", "background", "peaks", 0, "parameters"), "missing_parameter")


def test_background_peak_width_positive():
    r = _rietveld()
    r["payload"]["background"]["peaks"][0]["parameters"]["pv_fwhm"] = P(0.0)
    _fails(r, ("payload", "background", "peaks", 0, "parameters", "pv_fwhm"), "topas_positive")


@pytest.mark.parametrize("path", [("background",), ("phases", "LaB6", "peak_broadening")])
def test_empty_optional_block_rejected(path):
    r = _rietveld()
    node = r["payload"]
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = {}
    with pytest.raises(ValidationError, match="states nothing"):
        validate_recipe(r)


@pytest.mark.parametrize("path", [("background",), ("fit_range",), ("instrument", "corrections"),
                                  ("phases", "LaB6", "peak_broadening")])
def test_optional_block_never_null(path):
    r = _rietveld()
    node = r["payload"]
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = None
    with pytest.raises(ValidationError, match="must not be null; leave it out instead"):
        validate_recipe(r)


def test_scale_positive():
    r = _rietveld()
    r["payload"]["phases"]["LaB6"]["scale"] = P(0.0)
    _fails(r, ("payload", "phases", "LaB6", "scale"), "topas_positive")


def test_negative_strain_rejected():
    r = _rietveld()
    r["payload"]["phases"]["LaB6"]["peak_broadening"]["strain_broadening"] = {"model": "isotropic",
                                                                            "Strain_L": P(-0.01)}
    _fails(r, ("payload", "phases", "LaB6", "peak_broadening", "strain_broadening", "Strain_L"), "topas_positive")


def test_spf_negative_width_rejected():
    r = _spf()
    r["payload"]["single_peaks"][0]["lor_fwhm"] = P(-0.01)
    _fails(r, ("payload", "single_peaks", 0, "lor_fwhm"), "topas_positive")


def test_spf_peak_outside_window():
    r = _spf()
    r["payload"]["fit_range"] = [6.0, 14.0]
    _fails(r, ("payload", "single_peaks", 0, "xo"), "outside_fit_window")


def test_simulation_refines_nothing():
    r = _rietveld()
    r["payload"]["refinement_controls"]["iters"] = 0
    errors = _fails(r, ("payload", "phases", "LaB6", "scale"), "simulation_refines")
    assert (("payload", "background", "chebyshev", "refine_flag"), "simulation_refines") in errors


def test_unreadable_space_group_in_phase():
    r = _rietveld()
    r["payload"]["phases"]["LaB6"]["space_group"] = "C 1 21 1"
    _fails(r, ("payload", "phases", "LaB6", "space_group"))


# --- warnings, counts, JSON Schema ---------------------------------------------------------


def test_adp_conversion_warning_per_atom():
    m = validate_recipe(_rietveld())
    warnings = [w for w in collect_warnings(m) if w["code"] == "topas_adp_converted"]
    assert [w["field_path"] for w in warnings] == ["payload.phases.LaB6.atoms.La1.Uiso",
                                                   "payload.phases.LaB6.atoms.B1.Uiso"]


def test_parameters_requested_counts_tie_groups_once():
    # th2_offset, axial, 6 TCHZ, 3 Chebyshev, One_on_X, 4 background peak, cubic cell (1), B1 x, 2 Uiso,
    # scale, CS_L
    assert parameters_requested(validate_recipe(_rietveld())) == 22


@pytest.mark.parametrize("model", [TopasRietveldRecipe, TopasSpfRecipe])
def test_json_schema_shows_null_only_where_core_allows_it(model):
    schema = model.model_json_schema()
    allowed = {"BoundedRefinableParameter", "FitRange", "XRDData"}  # core: open bounds, open ends, filename
    for name, node in schema["$defs"].items():
        if name not in allowed:
            assert "null" not in json.dumps(node), name


def test_recipe_dump_is_valid_json_round_trip():
    m = validate_recipe(_spf())
    text = json.dumps(m.model_dump(mode="json"))
    assert validate_recipe(json.loads(text)) == m
    assert copy.deepcopy(m) == m


def test_limit_message_prints_an_allowed_value():
    """The message's limit, written back, validates (re/05 PR review N1): Uiso max 20/8 pi^2."""
    from powderline.gateways.topas.schema import _limit_text
    hi = 20 / (8 * 3.141592653589793 ** 2)
    assert float(_limit_text(hi, "max")) <= hi and float(_limit_text(-10 / (8 * 3.141592653589793 ** 2), "min")) >= \
        -10 / (8 * 3.141592653589793 ** 2)
    assert _limit_text(2.0, "max") == "2" and _limit_text(1e-4, "min") == "0.0001"


# --- TCHZ total width (TOPAS writes no results where it is not positive; a negative Lorentzian part runs) ----


def _tchz(r, x, y, refined=False):
    params = r["payload"]["instrument"]["broadening"]["parameters"]
    lo = -1.0 if refined else None  # a stated min replaces TOPAS's default minimum 0.0001 on a refined X / Y
    params["X"], params["Y"] = P(x, refined, lo), P(y, refined, lo)
    return r


@pytest.mark.parametrize("build", [_rietveld, _spf])
@pytest.mark.parametrize("refined", [False, True])
def test_tchz_width_not_positive_in_the_window_is_refused(build, refined):
    """A197: X = -0.1, Y = 0 (as on TOPAS 6, where it wrote no results): the Thompson-Cox-Hastings polynomial is
    negative at the window's high end, X and Y fixed or refined: an error naming both values and the 2theta."""
    r = _tchz(build(), -0.1, 0.0, refined)
    with pytest.raises(ValidationError) as exc:
        validate_recipe(r)
    (err,) = [e for e in exc.value.errors() if e["type"] == "topas_tchz_width_not_positive"]
    assert err["loc"] == ("payload", "instrument", "broadening", "parameters")
    lo, hi = validate_recipe(build()).payload.window()
    assert "X = -0.1, Y = 0.0" in err["msg"] and f"2theta = {hi:g}" in err["msg"]
    assert "a negative Lorentzian part is allowed only while the total width stays positive" in err["msg"]


@pytest.mark.parametrize("build", [_rietveld, _spf])
@pytest.mark.parametrize("x, y", [(-0.01, 0.0001), (-0.05, 0.0), (0.01, -0.0005)])
def test_negative_lorentzian_part_with_a_positive_total_width_is_allowed(build, x, y):
    """A197: TOPAS 6 computes a pseudo-Voigt with a negative Lorentzian part as written (fixed X = -0.01 ran), so a
    negative X tan(theta) + Y / cos(theta) passes while the total width stays positive over the window."""
    validate_recipe(_tchz(build(), x, y))


def test_tchz_width_is_checked_over_the_window_only():
    """X = -0.1, Y = 0: the total width is positive below 2theta ~ 7.9 and not above it, so a window that ends at
    6 passes; X = 0, Y = -0.01 is not positive anywhere and is reported at the window's low end (its minimum)."""
    validate_recipe(_tchz(_rietveld(), 0.0, 0.0))
    r = _tchz(_rietveld(), -0.1, 0.0)
    r["payload"]["fit_range"] = [2.0, 6.0]
    validate_recipe(r)
    with pytest.raises(ValidationError) as exc:
        validate_recipe(_tchz(_rietveld(), 0.0, -0.01))
    lo, hi = validate_recipe(_rietveld()).payload.window()
    (err,) = [e for e in exc.value.errors() if e["type"] == "topas_tchz_width_not_positive"]
    assert f"2theta = {lo:g}" in err["msg"]


def test_lorentzian_width_rule_is_tchz_only():
    r = _rietveld()
    r["payload"]["instrument"]["broadening"] = {
        "peak_type": "PV_Peak_Type",
        "parameters": {k: P(v) for k, v in dict(ha=0.01, hb=0.0, hc=0.01, lora=0.5, lorb=-0.1, lorc=0.0).items()}}
    validate_recipe(r)


# --- engine_version: an explicit set -----------------------------------------------------------------------


def test_supported_engine_versions_is_an_explicit_tuple():
    from powderline.gateways.topas import gateway, schema

    assert schema.SUPPORTED_ENGINE_VERSIONS == ("6",)
    assert schema.SUPPORTED_ENGINE_VERSION_SPEC == "==6" == gateway.ENGINE_VERSION_SPEC
    assert schema.DECLARATIONS["supported_engine_versions"] == "==6"
    r = _rietveld()
    r["engine_version"] = "6.0"  # a recipe states the version as listed, not an equivalent spelling
    _fails(r, ("engine_version",))
