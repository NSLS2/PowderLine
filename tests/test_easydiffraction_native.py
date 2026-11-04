"""Native ``easydiffraction.*`` runtime tests (re/06).

Tests the easydiffraction gateway builder, runner, and integration on the native
schema with easydiffraction 0.21.1. These tests require the easydiffraction
package and run full fits (slow).
"""

from __future__ import annotations

import json
import math
import sys
import textwrap
from pathlib import Path
from unittest.mock import Mock

import numpy as np
import pytest

easydiffraction = pytest.importorskip("easydiffraction")
from importlib.metadata import version

pytestmark = [
    pytest.mark.easydiffraction,
    pytest.mark.slow,  # the module-scoped fixtures run the engine; the goldens take ~18 min
    pytest.mark.skipif(version("easydiffraction") != "0.21.1", reason="native path is built for easydiffraction 0.21.1"),
]

from powderline.exceptions import EngineExecutionError
from powderline.gateways.easydiffraction import gateway, native_builder, native_run, schema
from powderline.schema_core import parameters_requested

DATA = Path(__file__).resolve().parent / "data"


def _load_fixture(name: str) -> dict:
    """Load a fixture from tests/data/easydiffraction/native/."""
    with open(DATA / "easydiffraction" / "native" / name, encoding="utf-8") as f:
        return json.load(f)


# ============================================================================
# Module-scoped fixtures: run each LaB6 fit once, reuse results
# ============================================================================


@pytest.fixture(scope="module")
def lab6_crysfml_tch_result(tmp_path_factory):
    """Run lab6_crysfml_tch.json once; return result dict."""
    recipe = _load_fixture("lab6_crysfml_tch.json")
    out = tmp_path_factory.mktemp("lab6_crysfml_tch")
    return gateway.run(recipe, str(out))


@pytest.fixture(scope="module")
def lab6_cryspy_pv_result(tmp_path_factory):
    """Run lab6_cryspy_pv.json once; return result dict."""
    recipe = _load_fixture("lab6_cryspy_pv.json")
    out = tmp_path_factory.mktemp("lab6_cryspy_pv")
    return gateway.run(recipe, str(out))


@pytest.fixture(scope="module")
def lab6_slots_simulation_result(tmp_path_factory):
    """Run lab6_slots_simulation.json once; return result dict."""
    recipe = _load_fixture("lab6_slots_simulation.json")
    out = tmp_path_factory.mktemp("lab6_slots_simulation")
    return gateway.run(recipe, str(out))


@pytest.fixture(scope="module")
def lab6_crysfml_tch_build():
    """Build lab6_crysfml_tch.json once; return Build object."""
    model = schema.validate_recipe(_load_fixture("lab6_crysfml_tch.json"))
    return native_builder.build_project(model)


@pytest.fixture(scope="module")
def lab6_cryspy_pv_build():
    """Build lab6_cryspy_pv.json once; return Build object."""
    model = schema.validate_recipe(_load_fixture("lab6_cryspy_pv.json"))
    return native_builder.build_project(model)


@pytest.fixture(scope="module")
def lab6_slots_simulation_build():
    """Build lab6_slots_simulation.json once; return Build object."""
    model = schema.validate_recipe(_load_fixture("lab6_slots_simulation.json"))
    return native_builder.build_project(model)


# ============================================================================
# Builder tests (build_project)
# ============================================================================


@pytest.mark.parametrize(
    "fixture_name,build_fixture,calculator,peak_type",
    [
        ("lab6_crysfml_tch.json", "lab6_crysfml_tch_build", "crysfml", "cwl-thompson-cox-hastings"),
        ("lab6_cryspy_pv.json", "lab6_cryspy_pv_build", "cryspy", "cwl-pseudo-voigt"),
        ("lab6_slots_simulation.json", "lab6_slots_simulation_build", "cryspy", "cwl-pseudo-voigt-berar-baldinozzi-asymmetry"),
    ],
)
def test_builder_calculator_and_peak_type(fixture_name, build_fixture, calculator, peak_type, request):
    """Calculator and peak type are set correctly."""
    build = request.getfixturevalue(build_fixture)
    expt = build.experiment
    assert expt.calculator.type == calculator
    assert expt.peak.type == peak_type


def test_builder_instrument_values_match_recipe(lab6_crysfml_tch_build):
    """Every instrument value in the recipe equals the easydiffraction value."""
    recipe = _load_fixture("lab6_crysfml_tch.json")
    model = schema.validate_recipe(recipe)
    build = lab6_crysfml_tch_build
    expt = build.experiment
    inst = model.payload.instrument

    # Wavelength
    assert expt.instrument.setup_wavelength.value == inst.radiation.setup_wavelength.value

    # Corrections
    assert expt.instrument.calib_twotheta_offset.value == inst.corrections.calib_twotheta_offset.value

    # Broadening parameters
    profile = inst.broadening.parameters
    assert expt.peak.broad_gauss_u.value == profile.broad_gauss_u.value
    assert expt.peak.broad_gauss_v.value == profile.broad_gauss_v.value
    assert expt.peak.broad_gauss_w.value == profile.broad_gauss_w.value
    assert expt.peak.broad_lorentz_x.value == profile.broad_lorentz_x.value
    assert expt.peak.broad_lorentz_y.value == profile.broad_lorentz_y.value

    # TCH asymmetry parameters
    assert expt.peak.asym_fcj_1.value == profile.asym_fcj_1.value
    assert expt.peak.asym_fcj_2.value == profile.asym_fcj_2.value


def test_builder_kα2_doublet(lab6_slots_simulation_build):
    """Kα2 wavelength and ratio are set when present."""
    recipe = _load_fixture("lab6_slots_simulation.json")
    model = schema.validate_recipe(recipe)
    build = lab6_slots_simulation_build
    expt = build.experiment

    assert expt.instrument.setup_wavelength_2.value == model.payload.instrument.radiation.setup_wavelength_2
    assert (
        expt.instrument.setup_wavelength_2_to_1_ratio.value
        == model.payload.instrument.radiation.setup_wavelength_2_to_1_ratio
    )


def test_builder_polarization(lab6_slots_simulation_build):
    """Polarization coefficient and monochromator angle are set."""
    recipe = _load_fixture("lab6_slots_simulation.json")
    model = schema.validate_recipe(recipe)
    build = lab6_slots_simulation_build
    expt = build.experiment

    assert (
        expt.instrument.setup_polarization_coefficient.value
        == model.payload.instrument.polarization.setup_polarization_coefficient
    )
    assert (
        expt.instrument.setup_monochromator_twotheta.value
        == model.payload.instrument.polarization.setup_monochromator_twotheta
    )


def test_builder_displacement_transparency(lab6_slots_simulation_build):
    """Displacement and transparency corrections are set."""
    recipe = _load_fixture("lab6_slots_simulation.json")
    model = schema.validate_recipe(recipe)
    build = lab6_slots_simulation_build
    expt = build.experiment

    assert (
        expt.instrument.calib_sample_displacement.value
        == model.payload.instrument.corrections.calib_sample_displacement.value
    )
    assert (
        expt.instrument.calib_sample_transparency.value
        == model.payload.instrument.corrections.calib_sample_transparency.value
    )


def test_builder_absorption(lab6_slots_simulation_build):
    """Absorption type and mu_r are set."""
    recipe = _load_fixture("lab6_slots_simulation.json")
    model = schema.validate_recipe(recipe)
    build = lab6_slots_simulation_build
    expt = build.experiment

    assert expt.absorption.type == model.payload.instrument.absorption.type
    assert expt.absorption.mu_r.value == model.payload.instrument.absorption.mu_r.value


def test_builder_cutoff_fwhm(lab6_slots_simulation_build):
    """CrysPy cutoff_fwhm is set."""
    recipe = _load_fixture("lab6_slots_simulation.json")
    model = schema.validate_recipe(recipe)
    build = lab6_slots_simulation_build
    expt = build.experiment

    assert expt.peak.cutoff_fwhm.value == model.payload.instrument.broadening.cutoff_fwhm


def test_builder_background_terms(lab6_crysfml_tch_build):
    """Background terms equal the recipe's."""
    recipe = _load_fixture("lab6_crysfml_tch.json")
    model = schema.validate_recipe(recipe)
    build = lab6_crysfml_tch_build
    expt = build.experiment

    cheb_recipe = model.payload.background.chebyshev.coefficients
    cheb_ed = list(expt.background)
    assert len(cheb_ed) == len(cheb_recipe)
    for term, coef in zip(cheb_ed, cheb_recipe):
        assert term.coef.value == coef


def test_builder_phase_scale(lab6_crysfml_tch_build):
    """Linked-structure scale equals the recipe's phase scale."""
    recipe = _load_fixture("lab6_crysfml_tch.json")
    model = schema.validate_recipe(recipe)
    build = lab6_crysfml_tch_build

    for name, phase in model.payload.phases.items():
        ed_name = native_builder.structure_name(name)
        assert build.experiment.linked_structures[ed_name].scale.value == phase.scale.value


def test_builder_structure_name_lowercased(lab6_crysfml_tch_build):
    """Structure name is the phase name lowercased."""
    recipe = _load_fixture("lab6_crysfml_tch.json")
    model = schema.validate_recipe(recipe)
    build = lab6_crysfml_tch_build

    for name in model.payload.phases:
        # build.structures is keyed by original phase name
        assert name in build.structures
        # The structure's datablock name is lowercased
        s = build.structures[name]
        assert s.name == native_builder.structure_name(name)
        assert native_builder.structure_name(name) == name.lower()


def test_builder_cell_values(lab6_crysfml_tch_build):
    """Cell values equal the recipe's."""
    recipe = _load_fixture("lab6_crysfml_tch.json")
    model = schema.validate_recipe(recipe)
    build = lab6_crysfml_tch_build

    for name, phase in model.payload.phases.items():
        s = build.structures[name]
        assert s.cell.length_a.value == phase.unit_cell.a.value
        assert s.cell.length_b.value == phase.unit_cell.b.value
        assert s.cell.length_c.value == phase.unit_cell.c.value
        assert s.cell.angle_alpha.value == phase.unit_cell.alpha.value
        assert s.cell.angle_beta.value == phase.unit_cell.beta.value
        assert s.cell.angle_gamma.value == phase.unit_cell.gamma.value


def test_builder_atom_values(lab6_crysfml_tch_build):
    """Atom positions, occupancy, and Uiso equal the recipe's."""
    recipe = _load_fixture("lab6_crysfml_tch.json")
    model = schema.validate_recipe(recipe)
    build = lab6_crysfml_tch_build

    for name, phase in model.payload.phases.items():
        s = build.structures[name]
        for label, atom in phase.atoms.items():
            site = s.atom_sites[label]
            assert site.fract_x.value == atom.x.value
            assert site.fract_y.value == atom.y.value
            assert site.fract_z.value == atom.z.value
            assert site.occupancy.value == atom.occupancy.value
            if atom.ADP == "Uiso":
                assert site.adp_iso.value == atom.Uiso.value


def test_builder_data_arrays_exact(lab6_crysfml_tch_build):
    """experiment.data.x equals the recipe's tth at window points exactly."""
    recipe = _load_fixture("lab6_crysfml_tch.json")
    model = schema.validate_recipe(recipe)
    build = lab6_crysfml_tch_build

    mask = model.payload.window_mask()
    tth = np.asarray(model.payload.xrd_data.tth, dtype=float)
    x_window = tth[mask]

    ed_x = np.asarray(build.experiment.data.x, dtype=float)
    np.testing.assert_array_equal(ed_x, x_window)


def test_builder_data_sigma(lab6_crysfml_tch_build):
    """sigma = 1/sqrt(weight)."""
    recipe = _load_fixture("lab6_crysfml_tch.json")
    model = schema.validate_recipe(recipe)
    build = lab6_crysfml_tch_build

    mask = model.payload.window_mask()
    w = np.asarray(model.payload.xrd_data.Itth_weights, dtype=float)
    sigma_expected = 1.0 / np.sqrt(w[mask])

    ed_sigma = np.asarray(build.experiment.data.intensity_meas_su, dtype=float)
    np.testing.assert_allclose(ed_sigma, sigma_expected, rtol=1e-15)


def test_builder_small_intensities_handed_exactly():
    """Normalized data (intensities ~1e-5, sigma >= 1e-4 as A159 requires) reach the engine exactly: the CIF
    loop is written without exponents, which easydiffraction's reader cannot parse (EB-89)."""
    recipe = _load_fixture("lab6_slots_simulation.json")
    xrd = recipe["payload"]["xrd_data"]
    xrd["Itth"] = [y * 1e-6 for y in xrd["Itth"]]
    xrd["Itth_weights"] = [1e8] * len(xrd["Itth"])  # sigma = 1e-4
    model = schema.validate_recipe(recipe)
    build = native_builder.build_project(model)
    mask = model.payload.window_mask()
    np.testing.assert_array_equal(np.asarray(build.experiment.data.intensity_meas, dtype=float),
                                  np.asarray(xrd["Itth"], dtype=float)[mask])
    np.testing.assert_array_equal(np.asarray(build.experiment.data.intensity_meas_su, dtype=float), 1e-4)
    assert "e-" not in native_builder.data_cif(np.array([5e-5]), np.array([1e16]), np.array([1e-4])).lower()


def test_builder_free_parameters_lab6_crysfml_tch(lab6_crysfml_tch_build):
    """Free parameters for lab6_crysfml_tch: exactly the expected set."""
    build = lab6_crysfml_tch_build

    # Expected: broad_gauss_u/v/w, broad_lorentz_x/y, 6 background coefficients, LaB6_scale, LaB6_a
    expected_names = {
        "broad_gauss_u",
        "broad_gauss_v",
        "broad_gauss_w",
        "broad_lorentz_x",
        "broad_lorentz_y",
        "background_coefficient_0",
        "background_coefficient_1",
        "background_coefficient_2",
        "background_coefficient_3",
        "background_coefficient_4",
        "background_coefficient_5",
        "LaB6_scale",
        "LaB6_a",
    }

    actual_names = {fp.name for fp in build.free}
    assert actual_names == expected_names, f"Expected {expected_names}, got {actual_names}"
    assert len(build.free) == 13


def test_builder_cubic_cell_one_parameter(lab6_crysfml_tch_build):
    """Cubic cell: one parameter (a), b and c are tied."""
    build = lab6_crysfml_tch_build

    cell_params = [fp for fp in build.free if fp.category == "unit_cell"]
    assert len(cell_params) == 1
    assert cell_params[0].name == "LaB6_a"


def test_builder_parameter_limits_physical(lab6_crysfml_tch_build):
    """Parameters with no stated bounds have physical limits as source."""
    build = lab6_crysfml_tch_build

    # LaB6_a has no stated bounds in the fixture, so it should have physical limits
    a_param = next(fp for fp in build.free if fp.name == "LaB6_a")
    assert a_param.limits == (0.0, 30.0)
    assert a_param.limit_source == ("physical", "physical")


def test_builder_parameter_limits_stated():
    """A stated bound becomes fit_min/fit_max and is marked 'stated'."""
    recipe = _load_fixture("lab6_cryspy_pv.json")
    # Set a's min/max to 4.1/4.2
    for axis in ("a", "b", "c"):
        recipe["payload"]["phases"]["LaB6"]["unit_cell"][axis] = [4.15682, True, 4.1, 4.2]
    model = schema.validate_recipe(recipe)
    build = native_builder.build_project(model)

    a_param = next(fp for fp in build.free if fp.name == "LaB6_a")
    assert a_param.limits == (4.1, 4.2)
    assert a_param.limit_source == ("stated", "stated")

    # Check easydiffraction's fit_min/fit_max
    s = build.structures["LaB6"]
    assert s.cell.length_a.fit_min == 4.1
    assert s.cell.length_a.fit_max == 4.2


def test_builder_scale_limits(lab6_crysfml_tch_build):
    """Scale has physical lower limit 0.0, no upper limit."""
    build = lab6_crysfml_tch_build

    scale_param = next(fp for fp in build.free if fp.name == "LaB6_scale")
    assert scale_param.limits == (0.0, None)
    assert scale_param.limit_source == ("physical", None)


def test_builder_fixed_parameters_not_free(lab6_crysfml_tch_build):
    """Fixed parameters are not in the free list."""
    build = lab6_crysfml_tch_build

    # asym_fcj_1/2, wavelength, Uiso should not be free in this fixture
    free_names = {fp.name for fp in build.free}
    assert "asym_fcj_1" not in free_names
    assert "asym_fcj_2" not in free_names
    assert "setup_wavelength" not in free_names
    assert "LaB6_La_Uiso" not in free_names


def test_builder_eb77_cryspy_pv_wrong_orientation_raises():
    """EB-77: CrysPy with B at (0.5, 0.5, 0.2021) raises with EB-77 in the message."""
    recipe = _load_fixture("lab6_cryspy_pv.json")
    # Change B's position to the wrong orientation
    recipe["payload"]["phases"]["LaB6"]["atoms"]["B"]["x"] = [0.5, False, None, None]
    recipe["payload"]["phases"]["LaB6"]["atoms"]["B"]["y"] = [0.5, False, None, None]
    recipe["payload"]["phases"]["LaB6"]["atoms"]["B"]["z"] = [0.2021, False, None, None]

    model = schema.validate_recipe(recipe)
    with pytest.raises(EngineExecutionError) as exc:
        native_builder.build_project(model)

    assert "EB-77" in str(exc.value)
    assert "0.2021, 0.5, 0.5" in str(exc.value) or "(0.2021, 0.5, 0.5)" in str(exc.value)


def test_builder_eb77_crysfml_accepts_both_orientations():
    """EB-77: CrysFML accepts either orientation."""
    recipe = _load_fixture("lab6_crysfml_tch.json")
    # Try both orientations
    for x, y, z in [(0.2021, 0.5, 0.5), (0.5, 0.5, 0.2021)]:
        r = json.loads(json.dumps(recipe))
        r["payload"]["phases"]["LaB6"]["atoms"]["B"]["x"] = [x, False, None, None]
        r["payload"]["phases"]["LaB6"]["atoms"]["B"]["y"] = [y, False, None, None]
        r["payload"]["phases"]["LaB6"]["atoms"]["B"]["z"] = [z, False, None, None]
        model = schema.validate_recipe(r)
        build = native_builder.build_project(model)  # Should not raise
        assert build is not None


def _b_uaniso(recipe: dict, refine: bool = False) -> dict:
    """LaB6's B (6f, x 1/2 1/2) anisotropic: U22 = U33 tied, no cross terms (site symmetry 4mm)."""
    b = recipe["payload"]["phases"]["LaB6"]["atoms"]["B"]
    b.pop("Uiso")
    b["ADP"] = "Uaniso"
    b["Uaniso"] = {k: [0.009 if k in ("U11", "U22", "U33") else 0.0, refine and k in ("U11", "U22", "U33"), None, None]
                   for k in ("U11", "U22", "U33", "U12", "U13", "U23")}
    return recipe


def test_builder_anisotropic_atoms_handed_first():
    """easydiffraction gets the anisotropic atoms first (A169, EB-86); the recipe lists La (Uiso) before B."""
    build = native_builder.build_project(schema.validate_recipe(_b_uaniso(_load_fixture("lab6_cryspy_pv.json"))))
    assert [a.id.value for a in build.structures["LaB6"].atom_sites] == ["B", "La"]
    build = native_builder.build_project(schema.validate_recipe(_load_fixture("lab6_cryspy_pv.json")))
    assert [a.id.value for a in build.structures["LaB6"].atom_sites] == ["La", "B"]  # recipe order otherwise


def _everything_refined(calculator: str) -> dict:
    """A LaB6 recipe with every refinable slot of the calculator's peak type flagged (cubic: a, b, c one group)."""
    if calculator == "cryspy":
        recipe = _b_uaniso(_load_fixture("lab6_slots_simulation.json"), refine=True)
    else:
        recipe = _load_fixture("lab6_crysfml_tch.json")
        recipe["payload"]["instrument"]["corrections"].update(
            {"calib_sample_displacement": [0.001, True, None, None], "calib_sample_transparency": [-0.0005, True, None, None]})
        recipe["payload"]["instrument"]["absorption"] = {"type": "cylinder-hewat", "mu_r": [0.3, True, None, None]}
    p = recipe["payload"]
    inst = p["instrument"]
    for q in (inst["radiation"]["setup_wavelength"], inst["absorption"]["mu_r"], *inst["corrections"].values(),
              *inst["broadening"]["parameters"].values()):
        q[1] = True
    p["background"] = {"chebyshev": {"num_coefficients": 3, "coefficients": [30.0, 0.6, 0.7], "refine_flag": True}}
    phase = p["phases"]["LaB6"]
    phase["scale"][1] = True
    for k in ("a", "b", "c"):
        phase["unit_cell"][k][1] = True
    phase["atoms"]["B"]["x"][1] = True
    for atom in phase["atoms"].values():
        atom["occupancy"][1] = True
        if "Uiso" in atom:
            atom["Uiso"][1] = True
    return recipe


@pytest.mark.parametrize("calculator", ["cryspy", "crysfml"])
def test_every_free_parameter_changes_the_pattern_the_minimizer_sees(calculator):
    """A127 principle: each parameter the builder frees changes the pattern computed on lmfit's own path.

    Each value is moved the way the minimizer moves it and the pattern recomputed the way its residual
    function does (structures, then the experiment, ``called_by_minimizer``): ``analysis.calculate()``
    rebuilds everything and so hides an update bug such as EB-86.
    """
    from easydiffraction.analysis.fitting import intensity_category_for

    model = schema.validate_recipe(_everything_refined(calculator))
    build = native_builder.build_project(model)
    build.project.analysis.calculate()  # the calculator's cached state, as at the start of a fit

    def minimizer_pattern():
        for s in build.structures.values():
            s._update_categories(called_by_minimizer=True)
        build.experiment._update_categories(called_by_minimizer=True)
        return np.array(intensity_category_for(build.experiment).intensity_calc, dtype=float)

    y0 = minimizer_pattern()
    assert len(build.free) == parameters_requested(model)
    dead = []
    for fp in build.free:
        v0 = float(fp.parameter.value)
        fp.parameter._set_value_from_minimizer(v0 + (0.01 if fp.category == "atom_xyz" else max(abs(v0) * 0.1, 1e-3)))
        if not np.max(np.abs(minimizer_pattern() - y0)) > 1e-10 * np.max(np.abs(y0)):
            dead.append(fp.path)
        fp.parameter._set_value_from_minimizer(v0)
    assert not dead, f"no effect on lmfit's path: {dead}"


def test_run_cryspy_refines_uaniso(tmp_path):
    """A refined Uij is varied and moves with CrysPy although La (Uiso) precedes B in the recipe (A169, EB-86)."""
    result = gateway.run(_b_uaniso(_load_fixture("lab6_cryspy_pv.json"), refine=True), str(tmp_path))
    d = result["engine_details"]
    assert result["status"] == "ok" and d["fit_success"], d
    assert d["parameters_varied"] == d["parameters_requested"]
    rows = result["refined_parameters"].set_index("parameter_name")
    for name in ("LaB6_B_U11", "LaB6_B_U22"):
        assert abs(rows.loc[name, "value"] - 0.009) > 1e-5
        assert np.isfinite(rows.loc[name, "esd"])
    assert rows.loc["LaB6_B_U11", "atom_idx"] == 1  # reports keep the recipe's atom order


def test_matches_template_unit_cases():
    """Unit tests for _matches_template."""
    from powderline.gateways.easydiffraction.native_builder import _matches_template

    # Positive cases
    assert _matches_template("(x,1/2,1/2)", (0.2, 0.5, 0.5))
    assert _matches_template("(x,x,x)", (0.1, 0.1, 0.1))
    assert _matches_template("(2x,x,z)", (0.2, 0.1, 0.3))
    assert _matches_template("(x,-x,z)", (0.1, 0.9, 0.3))

    # Negative cases
    assert not _matches_template("(x,1/2,1/2)", (0.5, 0.5, 0.2))
    assert not _matches_template("(2x,x,z)", (0.1, 0.2, 0.3))


# ============================================================================
# Run tests (gateway.run)
# ============================================================================


def test_run_lab6_crysfml_tch_success(lab6_crysfml_tch_result):
    """CrysFML TCH fit succeeds and says that its result can depend on the starting values (EB-90, A175)."""
    result = lab6_crysfml_tch_result
    assert result["status"] == "ok"
    assert result["simulation_mode"] is False
    hits = [w for w in result["warnings"] if w["code"] == "easydiffraction_crysfml_start_dependent"]
    assert len(hits) == 1 and hits[0]["field_path"] == "payload.refinement_controls.calculator"


def test_crysfml_calculation_has_no_start_warning(lab6_crysfml_calculation_result, lab6_cryspy_pv_result):
    """The start-dependence warning is for CrysFML refinements only, not a calculation or CrysPy (A175)."""
    for result in (lab6_crysfml_calculation_result, lab6_cryspy_pv_result):
        assert "easydiffraction_crysfml_start_dependent" not in [w["code"] for w in result["warnings"]]


def test_run_lab6_cryspy_pv_success(lab6_cryspy_pv_result):
    """CrysPy PV fit succeeds."""
    result = lab6_cryspy_pv_result
    assert result["status"] == "ok"
    assert result["simulation_mode"] is False


def test_run_rwp_matches_engine_details(lab6_crysfml_tch_result, lab6_cryspy_pv_result):
    """rwp equals engine_details['rwp'] within 1e-9 relative."""
    for result in [lab6_crysfml_tch_result, lab6_cryspy_pv_result]:
        rwp = result["rwp"]
        ed_rwp = result["engine_details"]["rwp"]
        assert rwp is not None
        assert ed_rwp is not None
        assert abs(rwp - ed_rwp) / abs(ed_rwp) < 1e-9


def test_run_parameters_varied_matches_requested(lab6_crysfml_tch_result, lab6_cryspy_pv_result):
    """parameters_varied == parameters_requested == 13."""
    for result in [lab6_crysfml_tch_result, lab6_cryspy_pv_result]:
        assert result["engine_details"]["parameters_varied"] == 13
        assert result["engine_details"]["parameters_requested"] == 13


def test_run_simulation_mode(lab6_slots_simulation_result):
    """Simulation: simulation_mode True, method easydiffraction_simulation, rwp present (from stats), ed rwp None."""
    result = lab6_slots_simulation_result
    assert result["simulation_mode"] is True
    assert result["method"] == "easydiffraction_simulation"
    assert result["engine_details"]["rwp"] is None
    assert result["rwp"] is not None  # From core stats


def test_run_simulation_parameters_varied_zero(lab6_slots_simulation_result):
    """Simulation: parameters_varied 0."""
    result = lab6_slots_simulation_result
    assert result["engine_details"]["parameters_varied"] == 0


def test_run_simulation_statistics_present(lab6_slots_simulation_result):
    """Simulation: statistics present (rwp not None)."""
    result = lab6_slots_simulation_result
    assert result["rwp"] is not None
    assert result["r_exp"] is not None
    assert result["gof"] is not None


def test_run_output_files_include_expected(lab6_crysfml_tch_result, lab6_cryspy_pv_result):
    """Output files include refined_parameters.csv, fit_profile.txt, LaB6_unit_cell_report.csv."""
    expected_files = {"refined_parameters.csv", "fit_profile.txt", "LaB6_unit_cell_report.csv"}
    for result in [lab6_crysfml_tch_result, lab6_cryspy_pv_result]:
        output_files = {Path(f).name for f in result["output_files"]}
        assert expected_files.issubset(output_files)


def test_run_cryspy_has_peak_list(lab6_cryspy_pv_result):
    """CrysPy run has LaB6_peak_list_report.csv and peak_list_data non-empty."""
    result = lab6_cryspy_pv_result
    output_files = {Path(f).name for f in result["output_files"]}
    assert "LaB6_peak_list_report.csv" in output_files
    assert "LaB6" in result["peak_list_data"]
    assert len(result["peak_list_data"]["LaB6"]) > 0


def test_run_crysfml_no_peak_list(lab6_crysfml_tch_result):
    """CrysFML run has warning easydiffraction_reflections_not_available and no peak list file."""
    result = lab6_crysfml_tch_result
    output_files = {Path(f).name for f in result["output_files"]}
    assert "LaB6_peak_list_report.csv" not in output_files

    warnings = [w for w in result["warnings"] if w["code"] == "easydiffraction_reflections_not_available"]
    assert len(warnings) == 1


def test_run_fit_profile_columns(lab6_crysfml_tch_result):
    """fit_profile has expected columns and y_diff == y_obs - y_calc."""
    result = lab6_crysfml_tch_result
    profile = result["fit_profile"]

    expected_cols = {"two_theta", "y_obs", "y_weights", "y_calc", "y_diff", "y_bkg", "q_values", "d_spacings"}
    assert set(profile.columns) == expected_cols

    # y_diff == y_obs - y_calc
    np.testing.assert_allclose(profile["y_diff"], profile["y_obs"] - profile["y_calc"], rtol=1e-12)


def test_run_fit_profile_y_bkg_finite(lab6_crysfml_tch_result):
    """y_bkg is finite."""
    result = lab6_crysfml_tch_result
    profile = result["fit_profile"]
    assert np.isfinite(profile["y_bkg"]).all()


def test_run_fit_profile_row_count_matches_window(lab6_crysfml_tch_result):
    """Number of rows == window points."""
    recipe = _load_fixture("lab6_crysfml_tch.json")
    model = schema.validate_recipe(recipe)
    mask = model.payload.window_mask()
    n_window = np.sum(mask)

    result = lab6_crysfml_tch_result
    assert len(result["fit_profile"]) == n_window


def test_run_unit_cell_report_cubic_ties(lab6_crysfml_tch_result):
    """b and c equal a with a's esd; alpha..gamma 90 with esd 0.0."""
    result = lab6_crysfml_tch_result
    uc = result["unit_cell_data"]["LaB6"]

    a_row = uc[uc["parameter"] == "cell_a"].iloc[0]
    b_row = uc[uc["parameter"] == "cell_b"].iloc[0]
    c_row = uc[uc["parameter"] == "cell_c"].iloc[0]

    assert b_row["value"] == a_row["value"]
    assert c_row["value"] == a_row["value"]
    assert b_row["esd"] == a_row["esd"]
    assert c_row["esd"] == a_row["esd"]

    for param in ["cell_alpha", "cell_beta", "cell_gamma"]:
        row = uc[uc["parameter"] == param].iloc[0]
        assert row["value"] == 90.0
        assert row["esd"] == 0.0


def test_run_unit_cell_volume(lab6_crysfml_tch_result):
    """Volume == a**3 (rel 1e-12)."""
    result = lab6_crysfml_tch_result
    uc = result["unit_cell_data"]["LaB6"]

    a = uc[uc["parameter"] == "cell_a"].iloc[0]["value"]
    vol = uc[uc["parameter"] == "cell_volume"].iloc[0]["value"]

    assert abs(vol - a**3) / a**3 < 1e-12


def test_run_simulation_phase_scale_zero_warning(tmp_path):
    """A phase with scale 0 in simulation → warning easydiffraction_phase_contributes_nothing."""
    recipe = _load_fixture("lab6_slots_simulation.json")
    recipe["payload"]["phases"]["LaB6"]["scale"] = [0.0, False, None, None]

    result = gateway.run(recipe, str(tmp_path))
    warnings = [w for w in result["warnings"] if w["code"] == "easydiffraction_phase_contributes_nothing"]
    assert len(warnings) == 1
    assert warnings[0]["field_path"] == "payload.phases.LaB6"
    assert warnings[0]["level"] == "info"  # informative (Dan, 2026-10-15): nothing to act on


def test_run_parameter_at_limit_warning(tmp_path):
    """Tight stated bound that the fit hits → warning easydiffraction_parameter_at_limit."""
    recipe = _load_fixture("lab6_cryspy_pv.json")
    # Set a max just above the starting value; the fit will hit it
    for axis in ("a", "b", "c"):
        recipe["payload"]["phases"]["LaB6"]["unit_cell"][axis] = [4.15682, True, None, 4.157]

    result = gateway.run(recipe, str(tmp_path))
    warnings = [w for w in result["warnings"] if w["code"] == "easydiffraction_parameter_at_limit"]
    assert len(warnings) >= 1
    assert any("payload.phases.LaB6.unit_cell.a" in w["field_path"] for w in warnings)


def test_run_max_iterations_3_fit_not_converged(tmp_path):
    """max_iterations = 3 (lmfit max_nfev) stops lmfit unconverged: a success with the not-converged warning."""
    recipe = _load_fixture("lab6_crysfml_tch.json")
    recipe["payload"]["refinement_controls"]["max_iterations"] = 3
    result = gateway.run(recipe, str(tmp_path))
    assert result["status"] == "ok"
    assert result["engine_details"]["fit_success"] is False
    warnings = [w for w in result["warnings"] if w["code"] == "easydiffraction_fit_not_converged"]
    assert len(warnings) == 1 and warnings[0]["field_path"] == "payload.refinement_controls"


def test_run_divergence_nan_in_calc(tmp_path, monkeypatch):
    """A non-finite calculated point is the divergence error (A130, A154)."""
    model = schema.validate_recipe(_load_fixture("lab6_cryspy_pv.json"))
    build = native_builder.build_project(model)
    build.project.analysis.calculate()
    data_class = type(build.experiment.data)  # the instance is guarded; patch its class
    original = data_class.fit_data_arrays

    def with_nan(self):
        arrays = {k: np.array(v, dtype=float) for k, v in original(self).items()}
        arrays["calc"][10] = np.nan
        return arrays

    monkeypatch.setattr(data_class, "fit_data_arrays", with_nan)
    with pytest.raises(EngineExecutionError, match="diverged"):
        native_run.build_result(model, build, tmp_path, [], elapsed=0.0, fit_info={})


def test_run_refined_negative_width_warns(tmp_path):
    """A refined profile that makes a width negative in the window is reported, values kept (A171, EB-87)."""
    model = schema.validate_recipe(_load_fixture("lab6_slots_simulation.json"))
    build = native_builder.build_project(model)
    build.project.analysis.calculate()
    build.experiment.peak.broad_gauss_w._set_value_from_minimizer(-0.01)  # as lmfit could leave it
    result = native_run.build_result(model, build, tmp_path, [], elapsed=0.0, fit_info={})
    hits = [w for w in result["warnings"] if w["code"] == "easydiffraction_negative_width"]
    assert len(hits) == 1 and hits[0]["field_path"] == "payload.instrument.broadening.parameters"
    assert "Gaussian" in hits[0]["message"]


def test_run_validate_only(tmp_path):
    """validate_only returns method 'validate_only' without importing easydiffraction's runtime."""
    recipe = _load_fixture("lab6_crysfml_tch.json")
    result = gateway.run(recipe, str(tmp_path), validate_only=True)

    assert result["method"] == "validate_only"
    assert result["status"] == "validated" and "success" not in result  # re/12 D3 (P-28 shape + status)
    assert result["rwp"] is None
    assert "schema_name" in result
    assert "engine_schema_version" in result
    # the uniform summary (P-28): the easydiffraction item under "engine", core_schema_version present
    from powderline.registry import VALIDATE_ONLY_KEYS
    assert tuple(result) == VALIDATE_ONLY_KEYS
    assert result["core_schema_version"] == "0.1.0"
    assert result["engine"] == {"calculator": "crysfml"} and "calculator" not in result
    assert isinstance(result["parameters_requested"], int) and result["parameters_requested"] > 0


# ============================================================================
# Safeguards without a test before the re/06 PR review (record N1, N5)
# ============================================================================


def test_builder_site_mismatch_raises(monkeypatch):
    """EB-47: an atom whose easydiffraction multiplicity differs from core's is refused before the run."""
    model = schema.validate_recipe(_load_fixture("lab6_crysfml_tch.json"))
    phase_class = type(model.payload.phases["LaB6"])
    core_site = phase_class.site

    def site(self, label):
        s = core_site(self, label)
        return Mock(multiplicity=s.multiplicity * 2) if label == "B" else s

    monkeypatch.setattr(phase_class, "site", site)
    with pytest.raises(EngineExecutionError, match=r"payload\.phases\.LaB6\.atoms\.B: .*core has multiplicity 12 \(EB-47\)") as e:
        native_builder.build_project(model)
    assert e.value.reason == "unusable_site"  # re/12: the engine's reading of a site differs from core's


def test_builder_interior_zero_weights_not_handed():
    """Zero-weight points inside the window (a masked region) are not handed to easydiffraction (A154, A158)."""
    recipe = _load_fixture("lab6_crysfml_tch.json")
    xrd = recipe["payload"]["xrd_data"]
    masked = [i for i, t in enumerate(xrd["tth"]) if 5.0 <= t <= 5.1]
    for i in masked:
        xrd["Itth_weights"][i] = 0.0
    model = schema.validate_recipe(recipe)
    mask = model.payload.window_mask()
    assert masked and not mask[masked].any()
    build = native_builder.build_project(model)
    np.testing.assert_array_equal(np.asarray(build.experiment.data.x, dtype=float),
                                  np.asarray(xrd["tth"], dtype=float)[mask])


def test_builder_sets_raise_reaction(monkeypatch):
    """EB-48: a value easydiffraction refuses raises, even when the user's environment asks it to warn."""
    from easydiffraction.utils.logging import Logger

    monkeypatch.setenv("ED_LOG_REACTION", "WARN")
    Logger.configure()
    try:
        build = native_builder.build_project(schema.validate_recipe(_load_fixture("lab6_crysfml_tch.json")))
        with pytest.raises(TypeError, match="outside"):
            build.structures["LaB6"].cell.length_a = 35.0  # above easydiffraction's 30 A limit (EB-71)
    finally:
        Logger.configure(reaction=Logger.Reaction.RAISE)


def test_run_not_varied_warning(tmp_path, monkeypatch):
    """A128: fewer parameters varied than the recipe requests gives easydiffraction_parameters_not_varied."""
    recipe = _load_fixture("lab6_crysfml_tch.json")
    recipe["payload"]["refinement_controls"]["max_iterations"] = 3
    requested = native_run.parameters_requested
    monkeypatch.setattr(native_run, "parameters_requested", lambda model: requested(model) + 1)
    result = gateway.run(recipe, str(tmp_path))
    hits = [w for w in result["warnings"] if w["code"] == "easydiffraction_parameters_not_varied"]
    assert len(hits) == 1 and "requests 14" in hits[0]["message"] and "varied 13" in hits[0]["message"]


def test_run_y_bkg_is_the_engines_chebyshev(lab6_crysfml_tch_result):
    """A157 B5: y_bkg is easydiffraction's Chebyshev at the refined coefficients over the handed points' range."""
    fp = lab6_crysfml_tch_result["fit_profile"]
    rows = lab6_crysfml_tch_result["refined_parameters"].set_index("parameter_name")
    x = fp["two_theta"].to_numpy(dtype=float)
    u = (x - x.min()) / (x.max() - x.min()) * 2 - 1
    coefficients = [rows.loc[f"background_coefficient_{k}", "value"] for k in range(6)]
    np.testing.assert_allclose(fp["y_bkg"].to_numpy(dtype=float), np.polynomial.chebyshev.chebval(u, coefficients),
                               rtol=1e-12, atol=1e-12)


def test_run_divergence_nan_refined_value(tmp_path):
    """A non-finite refined value is the divergence error (A130, A154)."""
    model = schema.validate_recipe(_load_fixture("lab6_cryspy_pv.json"))
    build = native_builder.build_project(model)
    build.project.analysis.calculate()
    build.free[0].parameter._set_value_from_minimizer(float("nan"))  # as lmfit could leave it
    with pytest.raises(EngineExecutionError, match=f"diverged.*{build.free[0].path}"):
        native_run.build_result(model, build, tmp_path, [], elapsed=0.0, fit_info={})


def test_run_divergence_nan_in_reflection_list(tmp_path, monkeypatch):
    """A non-finite value in the reflection list is the divergence error (A154)."""
    model = schema.validate_recipe(_load_fixture("lab6_slots_simulation.json"))
    build = native_builder.build_project(model)
    build.project.analysis.calculate()
    arrays = native_run._refln_arrays

    def with_nan(refln):
        out = arrays(refln)
        out["f_squared_calc"] = out["f_squared_calc"].astype(float)
        out["f_squared_calc"][0] = np.nan
        return out

    monkeypatch.setattr(native_run, "_refln_arrays", with_nan)
    with pytest.raises(EngineExecutionError, match=r"diverged.*reflection list \(f_squared_calc\)"):
        native_run.build_result(model, build, tmp_path, [], elapsed=0.0, fit_info={})


def _translated_recipe() -> dict:
    """P -3 m 1, Fe on 6i (x, -x, z) written as a database would, (0.137, 0.863, 0.389); xyz refined."""
    recipe = _load_fixture("lab6_cryspy_pv.json")
    p = recipe["payload"]
    for q in p["instrument"]["broadening"]["parameters"].values():
        q[1] = False
    p["background"]["chebyshev"]["refine_flag"] = False
    cell = dict(zip(("a", "b", "c", "alpha", "beta", "gamma"), (5.1, 5.1, 7.3, 90.0, 90.0, 120.0)))
    p["phases"] = {"FeHex": {
        "space_group": "P -3 m 1", "unit_cell": {k: [v, False, None, None] for k, v in cell.items()},
        "atoms": {"Fe1": {"element": "Fe", "x": [0.137, True, 0.1, 0.2], "y": [0.863, True, 0.8, 0.9],
                          "z": [0.389, True, None, None], "occupancy": [1.0, False, None, None], "ADP": "Uiso",
                          "Uiso": [0.005, False, None, None]}},
        "scale": [1e-6, False, None, None]}}
    return recipe


def test_builder_position_translated_accepted():
    """A176: easydiffraction holds (0.137, 0.863, z) on (x, -x, z) as (0.137, -0.137, z): accepted, recorded,
    and the free coordinate's bounds, value and reports stay in the recipe's writing."""
    model = schema.validate_recipe(_translated_recipe())
    build = native_builder.build_project(model)
    site = build.structures["FeHex"].atom_sites["Fe1"]
    assert (site.fract_x.value, site.fract_y.value) == (0.137, -0.137)
    assert build.translations == {("FeHex", "Fe1"): (0, 1, 0)}
    rows = {r["parameter_name"]: r["value"] for r in native_run._refined_rows(model, build)}
    stated = {"x": 0.137, "y": 0.863, "z": 0.389}
    for fp in build.free:
        member = fp.name.rsplit("_", 1)[1]
        assert rows[fp.name] == pytest.approx(stated[member], abs=1e-12)
        if member in ("x", "y"):
            lo, hi = {"x": (0.1, 0.2), "y": (0.8, 0.9)}[member]
            assert (fp.parameter.fit_min + fp.report_offset, fp.parameter.fit_max + fp.report_offset) == \
                pytest.approx((lo, hi))
    hits = native_run._translations(model, build)
    assert [w["code"] for w in hits] == ["easydiffraction_position_translated"]
    assert hits[0]["field_path"] == "payload.phases.FeHex.atoms.Fe1" and "(0, 1, 0)" in hits[0]["message"]


def test_builder_free_offset_moves_bounds_and_reports():
    """_free with an offset: easydiffraction's bounds are the recipe's minus the offset; reports add it back."""
    from powderline.schema_core import BoundedRefinableParameter

    build = native_builder.Build(project=None, experiment=None, structures={})
    param = Mock()
    native_builder._free(build, param, BoundedRefinableParameter.model_validate([0.863, True, 0.8, 0.9]),
                         name="y", path="p.y", descriptive="y", category="atom_xyz", offset=1)
    assert (param.fit_min, param.fit_max) == pytest.approx((-0.2, -0.1))
    fp = build.free[0]
    assert fp.limits == pytest.approx((-0.2, -0.1)) and fp.report_offset == 1


@pytest.mark.parametrize("start, value, hit", [
    (5.4e-6, 1e-12, True),   # a phase scale pinned at 0: within 1e-6 of its start
    (5.4e-6, 1.6e-9, False),  # statistically zero but not at the limit (the review's phantom phase)
    (0.005, 3e-9, True),     # a Uiso at 0
    (0.005, 1e-7, False),
    (0.0, 1e-13, True),      # started at 0: 1e-12 absolute
])
def test_limit_hit_at_zero_relative_to_the_start(start, value, hit):
    """A181 (N4): at a limit of 0, "ended at the limit" is relative to the parameter's starting value."""
    fp = native_builder.FreeParameter(Mock(value=value), "LaB6_scale", "payload.phases.LaB6.scale", "LaB6 scale",
                                      "scale", limits=(0.0, None), limit_source=("physical", None), start=start)
    build = native_builder.Build(project=None, experiment=None, structures={}, free=[fp])
    hits = native_run._limit_hits(build)
    assert [w["code"] for w in hits] == (["easydiffraction_parameter_at_limit"] if hit else [])


def test_zero_gsasii_imports_subprocess():
    """A subprocess that blocks GSASII imports can import native_run and schema."""
    import textwrap

    script = textwrap.dedent(
        """
        import sys, importlib.abc

        class _Block(importlib.abc.MetaPathFinder):
            def find_spec(self, name, path, target=None):
                if name == "GSASII" or name.startswith("GSASII."):
                    raise ImportError("GSASII blocked for easydiffraction native test")
                return None

        sys.meta_path.insert(0, _Block())
        import powderline.gateways.easydiffraction.native_run
        import powderline.gateways.easydiffraction.schema
        assert "GSASII" not in sys.modules, "easydiffraction native path pulled GSAS-II into sys.modules"
        print("OK")
        """
    )

    import subprocess

    proc = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
    assert proc.returncode == 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    assert "OK" in proc.stdout


@pytest.fixture(scope="module")
def drx33_two_phase_build():
    """Build drx33_two_phase_cryspy.json once; return Build object."""
    return native_builder.build_project(schema.validate_recipe(_load_fixture("drx33_two_phase_cryspy.json")))


@pytest.fixture(scope="module")
def drx33_two_phase_result(tmp_path_factory):
    """Run drx33_two_phase_cryspy.json once (two phases, CrysPy); return (result, output dir)."""
    out = tmp_path_factory.mktemp("drx33_two_phase")
    return gateway.run(_load_fixture("drx33_two_phase_cryspy.json"), str(out)), out


def test_two_phases_built_and_refined(drx33_two_phase_build, drx33_two_phase_result):
    """Two phases (cubic + C 1 2/m 1): one structure each, scales and cells refined per phase, reports per phase."""
    assert set(drx33_two_phase_build.structures) == {"DRX_33", "Li4MgWO6_SG12"}
    linked = drx33_two_phase_build.experiment.linked_structures
    assert {"drx_33", "li4mgwo6_sg12"} <= {ls.structure_id.value for ls in linked}
    result, out = drx33_two_phase_result
    d = result["engine_details"]
    assert result["status"] == "ok" and d["fit_success"] and d["parameters_varied"] == d["parameters_requested"] == 18
    rows = result["refined_parameters"].set_index("parameter_name")
    assert rows.loc["DRX_33_scale", "phase_idx"] == 0 and rows.loc["Li4MgWO6_SG12_scale", "phase_idx"] == 1
    assert np.isfinite(rows["esd"].astype(float)).all()
    assert set(result["unit_cell_data"]) == {"DRX_33", "Li4MgWO6_SG12"}
    for phase in ("DRX_33", "Li4MgWO6_SG12"):
        assert (out / f"{phase}_peak_list_report.csv").is_file() and (out / f"{phase}_unit_cell_report.csv").is_file()
    assert not [w for w in result["warnings"] if w["code"] == "easydiffraction_phase_contributes_nothing"]


# ============================================================================
# Goldens (A157 B8): regenerated only on a deliberate engine change
# (devkit probes/re06/make_goldens.py)
# ============================================================================

_GOLDEN_CASES = [("lab6_crysfml_tch.json", "lab6_crysfml_tch_build", "lab6_crysfml_tch_result"),
                 ("lab6_crysfml_tch_calculation.json", "lab6_crysfml_calculation_build",
                  "lab6_crysfml_calculation_result"),
                 ("lab6_cryspy_pv.json", "lab6_cryspy_pv_build", "lab6_cryspy_pv_result"),
                 ("lab6_slots_simulation.json", "lab6_slots_simulation_build", "lab6_slots_simulation_result"),
                 ("drx33_two_phase_cryspy.json", "drx33_two_phase_build", "drx33_two_phase_run")]

#: Cross-build tolerances (A179; docs/regression-tolerance.md: rtol 1e-3 for values, ESDs and statistics,
#: 1e-4 for the cell). A value near zero is also accepted within 1 % of its ESD (easydiffraction's scales are
#: ~1e-6, so GSAS-II's atol 1e-4 does not fit).
GOLDEN_RTOL, GOLDEN_CELL_RTOL, GOLDEN_ESD_FRACTION = 1e-3, 1e-4, 1e-2

#: CrysFML refinements stop at start-dependent points (EB-90, A175): their goldens compare only what does not
#: depend on the stop (counts, warnings, the cell within 1e-4); the calculation fixture covers CrysFML's numbers.
START_DEPENDENT = {"lab6_crysfml_tch.json"}


@pytest.fixture(scope="module")
def lab6_crysfml_calculation_build():
    return native_builder.build_project(schema.validate_recipe(_load_fixture("lab6_crysfml_tch_calculation.json")))


@pytest.fixture(scope="module")
def lab6_crysfml_calculation_result(tmp_path_factory):
    return gateway.run(_load_fixture("lab6_crysfml_tch_calculation.json"),
                       str(tmp_path_factory.mktemp("lab6_crysfml_calculation")))


@pytest.fixture(scope="module")
def drx33_two_phase_run(drx33_two_phase_result):
    return drx33_two_phase_result[0]


def _golden(name: str) -> dict:
    with open(DATA / "easydiffraction" / "native" / "golden" / name, encoding="utf-8") as f:
        return json.load(f)


def _finite_or_none(v):
    return None if v is None or (isinstance(v, float) and not math.isfinite(v)) else v


@pytest.mark.parametrize("name,build_fixture,_result", _GOLDEN_CASES)
def test_built_project_matches_golden(name, build_fixture, _result, request):
    """The built project's parameters (value, free, fit_min, fit_max) equal the golden exactly."""
    build = request.getfixturevalue(build_fixture)
    built = {}
    for p in build.project.parameters:
        value = getattr(p, "value", None)
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            continue
        built[p.unique_name] = {"value": _finite_or_none(value), "free": bool(getattr(p, "free", False)),
                                "fit_min": _finite_or_none(getattr(p, "fit_min", None)),
                                "fit_max": _finite_or_none(getattr(p, "fit_max", None))}
    assert built == _golden(name)["built_parameters"]


@pytest.mark.parametrize("name,_build,result_fixture", _GOLDEN_CASES)
def test_run_matches_golden(name, _build, result_fixture, request):
    """Statistics, refined values, ESDs, unit cell and warning codes match the golden within cross-build tolerance."""
    res = request.getfixturevalue(result_fixture)
    gold = _golden(name)["run"]
    assert sorted(w["code"] for w in res["warnings"]) == gold["warnings"]
    assert res["simulation_mode"] == gold["simulation_mode"]
    details = res["engine_details"]
    for key in ("calculator", "peak_type", "parameters_requested", "parameters_varied", "n_points"):
        assert details[key] == gold["engine_details"][key]
    rp = res["refined_parameters"]
    refined = {n: (v, _finite_or_none(e)) for n, v, e in zip(rp.parameter_name, rp.value, rp.esd)}
    assert refined.keys() == gold["refined"].keys()
    for phase, rows in gold["unit_cell"].items():
        got = res["unit_cell_data"][phase].to_dict("records")
        for g, r in zip(rows, got):
            assert r["parameter"] == g["parameter"]
            assert r["value"] == pytest.approx(g["value"], rel=GOLDEN_CELL_RTOL)
    if name in START_DEPENDENT:
        return
    for key in ("rwp", "r_exp", "gof", "chi2_red"):
        assert res[key] == pytest.approx(gold[key], rel=GOLDEN_RTOL)
    for n, (value, esd) in gold["refined"].items():
        floor = GOLDEN_ESD_FRACTION * esd if esd is not None else 1e-12
        assert refined[n][0] == pytest.approx(value, rel=GOLDEN_RTOL, abs=floor), n
        assert (refined[n][1] is None) == (esd is None), n
        if esd is not None:
            assert refined[n][1] == pytest.approx(esd, rel=GOLDEN_RTOL), n


# --- re/12: engine exceptions become engine_crashed; status and converged on every result -------------

def test_lmfit_error_is_engine_crashed(tmp_path, monkeypatch):
    """An exception inside easydiffraction's fit is reported as engine_crashed, chained, not as a raw error."""
    recipe = _load_fixture("lab6_cryspy_pv.json")
    model = schema.validate_recipe(recipe)
    build = native_run.build_project(model)

    def boom(*a, **k):
        raise ValueError("The model function generated NaN values")
    monkeypatch.setattr(type(build.project.analysis), "fit", boom)  # the class: Analysis refuses new instance attrs
    monkeypatch.setattr(native_run, "build_project", lambda m: build)
    with pytest.raises(EngineExecutionError) as e:
        native_run.run_native(model, tmp_path)
    assert e.value.reason == "engine_crashed" and isinstance(e.value.__cause__, ValueError)


def test_builder_exception_is_engine_crashed(tmp_path, monkeypatch):
    """An exception easydiffraction raises while the project is built is engine_crashed too, named as the
    build stage (A192 Q7: the builder used to run outside the wrapper, so the error escaped raw)."""
    model = schema.validate_recipe(_load_fixture("lab6_cryspy_pv.json"))

    def boom(m):
        raise KeyError("space_group")
    monkeypatch.setattr(native_run, "build_project", boom)
    with pytest.raises(EngineExecutionError) as e:
        native_run.run_native(model, tmp_path)
    assert e.value.reason == "engine_crashed" and isinstance(e.value.__cause__, KeyError)
    assert "while building the project" in str(e.value)


def test_builder_refusal_keeps_its_reason(tmp_path, monkeypatch):
    """The builder's own refusal (an EngineExecutionError, e.g. unusable_site) passes through unchanged."""
    model = schema.validate_recipe(_load_fixture("lab6_cryspy_pv.json"))

    def refuse(m):
        raise EngineExecutionError("easydiffraction reads this site differently", reason="unusable_site")
    monkeypatch.setattr(native_run, "build_project", refuse)
    with pytest.raises(EngineExecutionError) as e:
        native_run.run_native(model, tmp_path)
    assert e.value.reason == "unusable_site" and e.value.__cause__ is None


def test_converged_follows_lmfit_and_is_none_for_simulation(tmp_path):
    fitted = gateway.run(_load_fixture("lab6_cryspy_pv.json"), str(tmp_path / "fit"))
    assert fitted["status"] == "ok" and fitted["converged"] in (True, False)
    assert fitted["converged"] == fitted["engine_details"]["fit_success"]
    assert "error" not in fitted and "traceback" not in fitted and fitted["envelope_version"] == "1"
    sim = gateway.run(_load_fixture("lab6_slots_simulation.json"), str(tmp_path / "sim"))
    assert sim["converged"] is None and sim["simulation_mode"] is True and sim["status"] == "ok"


# --- re/20a (KI-04): the output recipe and its idempotence -----------------------------------------------------

def test_output_recipe_is_valid_and_feeds_back(lab6_crysfml_tch_result, tmp_path_factory):
    """re/20a: the output recipe carries the refined cell, re-validates silently, and a second run from it
    reproduces the fit (refinement-level idempotence, within the ESDs)."""
    result = lab6_crysfml_tch_result
    assert result["output_recipe_valid"] is True, [w for w in result["warnings"] if w["code"] == "output_recipe_not_valid"]
    out = result["output_recipe"]
    phase = next(iter(out["payload"]["phases"]))
    reported = dict(zip(result["unit_cell_data"][phase]["parameter"], result["unit_cell_data"][phase]["value"]))
    assert out["payload"]["phases"][phase]["unit_cell"]["a"][0] == pytest.approx(reported["cell_a"], rel=1e-9)
    again = schema.validate_recipe(out)
    from powderline.schema_core import collect_warnings
    assert not [w for w in collect_warnings(again) if w["code"] == "symmetry_value_derived" or w["code"].endswith("_default_applied")]
    second = gateway.run(out, str(tmp_path_factory.mktemp("crysfml_tch_again")))
    assert second["status"] == "ok" and abs(second["rwp"] - result["rwp"]) < 0.05
    # well-determined parameters (|value| > 10 ESD) stay within 3 ESD; a parameter consistent with zero (the
    # Lorentzian X here, -5e-5 +/- 2e-4) may wander between two converged fits and says nothing about the loop
    first_rows = result["parameter_dispositions"].set_index("path")
    second_rows = second["parameter_dispositions"].set_index("path")
    compared = 0
    for path, row in first_rows.iterrows():
        if row["disposition"] == "varied" and row["esd"] and row["esd"] > 0 and abs(row["value"]) > 10 * row["esd"]:
            assert abs(second_rows.loc[path, "value"] - row["value"]) <= 3 * row["esd"], path
            compared += 1
    assert compared >= 3, "the cell, the scale and the background at least"


def test_output_recipe_that_the_schema_refuses_is_still_written_and_flagged(lab6_cryspy_pv_result):
    """re/20a (P-43 D5): the cryspy_pv fit ends with a profile the schema refuses (a negative width near the
    window, EB-87): the output recipe is written and returned, output_recipe_valid is false, the warning names
    the field, and nothing pretends it can be fed back."""
    result = lab6_cryspy_pv_result
    assert result["output_recipe_valid"] is False and result["output_recipe"] is not None
    why = [w for w in result["warnings"] if w["code"] == "output_recipe_not_valid"]
    assert why and "payload.instrument.broadening.parameters" in why[0]["message"]
    assert any(f.endswith("output_recipe.json") for f in result["output_files"])
    with pytest.raises(Exception):
        schema.validate_recipe(result["output_recipe"])
