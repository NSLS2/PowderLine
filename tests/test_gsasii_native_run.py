"""Native ``gsasii.*`` recipes run end to end (re/04): results, warnings, GSAS-II site check, SPF failure message.

Recipes come from the converter's 0.26.0 fixtures
(``tests/data/convert_026/``, re/07 P-23) through the converter
(``scripts/convert_recipe_026.py``), so the background-peak assertions (EB-33)
keep their subject after the examples lost that peak (P-01). The runs use GSAS-II in-process
(``execution_mode='subprocess'``); skipped where GSAS-II is not installed.
"""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest

pytestmark = [pytest.mark.gsasii, pytest.mark.slow]

pytest.importorskip("GSASII.GSASIIscriptable")

import powderline  # noqa: E402
from powderline.exceptions import EngineExecutionError  # noqa: E402
from powderline.gateways.gsasii.client import GSASClient  # noqa: E402
from powderline.gateways.gsasii.executors import execute_spf_refinement  # noqa: E402
from powderline.gateways.gsasii.fit_report import fit_report, parameters_requested  # noqa: E402
from powderline.gateways.gsasii.schema import validate_recipe  # noqa: E402
from powderline.symmetry import analyze_site, orbit  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("convert_recipe_026", ROOT / "scripts" / "convert_recipe_026.py")
conv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(conv)


def _lab6() -> dict:
    """The converted LaB6 example (its background peak raised to GSAS-II's floor first)."""
    old = json.loads((ROOT / "tests" / "data" / "convert_026" / "example_LaB6" / "input.json").read_text(encoding="utf-8"))
    old["payload"]["background"]["single_peaks"]["pv_lorentzian_gamma"][0][0] = 0.1
    return conv.convert(old)[0]


@pytest.fixture(scope="module")
def lab6_result(tmp_path_factory):
    return powderline.run(_lab6(), tmp_path_factory.mktemp("lab6"), execution_mode="subprocess")


def test_standard_fit_statistics_and_engine_details(lab6_result):
    r = lab6_result
    assert r["status"] == "ok", r.get("failure")
    for key in ("rwp", "r_exp", "gof", "chi2_red"):  # A125
        assert isinstance(r[key], float)
    d = r["engine_details"]
    assert d["engine"] == "GSAS-II"
    # scale, cell (cubic a = b = c is one parameter, A94), 6 Chebyshev, U..Z, 4 background-peak terms
    assert d["parameters_requested"] == 17
    assert d["parameters_varied"] == 17  # GSAS-II's Nvars: counts the 4 peak terms it then drops (EB-33)
    assert abs(r["rwp"] - d["rwp"]) < 0.05  # core Rwp vs GSAS-II's wR (same data; A23 documents differences)
    assert abs(r["gof"] - d["gof"]) / d["gof"] < 0.01  # Rietveld: GSAS-II's 'GOF' is sqrt(reduced chi^2) (EB-52)
    assert r["gof"] == pytest.approx(r["chi2_red"] ** 0.5)
    assert d["converged"] is True  # GSAS-II's Rvals['converged'] (A172)
    assert "gsasii_fit_not_converged" not in [w["code"] for w in r["warnings"]]
    json.dumps(d)  # crosses the server boundary



def test_gsasii_fits_exactly_the_stated_window(lab6_result):
    """A149/R17: limits on data points, so GSAS-II's slice is min <= 2theta <= max (EB-54) and its Rwp is core's."""
    d = lab6_result["engine_details"]
    payload = _lab6()["payload"]
    lo, hi = payload["fit_range"]
    inside = [t for t, w in zip(payload["xrd_data"]["tth"], payload["xrd_data"]["Itth_weights"]) if w > 0 and lo <= t <= hi]
    assert d["n_obs"] == len(inside) == 3767
    assert lab6_result["rwp"] == pytest.approx(d["rwp"], rel=1e-9)

def test_gsasii_open_ends_skip_zero_weight_edges(tmp_path):
    """A154: without fit_range GSAS-II gets the first/last weighted points as limits, so zero-weight edge points
    are outside its slice (it would count them in Nobs and map its Chebyshev over them)."""
    recipe = _lab6()
    recipe["payload"].pop("fit_range")
    w = recipe["payload"]["xrd_data"]["Itth_weights"]
    for i in list(range(20)) + list(range(len(w) - 20, len(w))):
        w[i] = 0.0
    r = powderline.run(recipe, tmp_path, execution_mode="subprocess")
    assert r["status"] == "ok", r.get("failure")
    assert r["engine_details"]["n_obs"] == sum(1 for v in w if v > 0) == len(w) - 40

def test_warnings_carried_with_full_paths(lab6_result):
    codes = {w["code"]: w for w in lab6_result["warnings"]}
    assert lab6_result["warnings"][0]["field_path"] == "payload.phases.LaB6.peak_broadening.size_broadening"
    assert "gsasii_broadening_default_applied" in codes  # A107, from validating the user's recipe
    msg = codes["gsasii_refinement_message"]  # EB-32: GSAS-II's message, EB-33: dropped count
    assert msg["field_path"] is None and "4 parameter(s) dropped as singular" in msg["message"]


def test_validate_only_summary():
    """The uniform summary (registry.validate_only_summary, P-28) with gsasii's engine item."""
    from powderline.registry import VALIDATE_ONLY_KEYS
    r = powderline.run(_lab6(), "unused", validate_only=True)
    assert (r["schema_name"], r["core_schema_version"], r["engine_schema_version"], r["phases"]) == \
        ("gsasii.rietveld", "0.1.0", "0.1.0", 1)
    assert tuple(r) == VALIDATE_ONLY_KEYS
    assert r["engine"] == {"refinement_cycles": 5} and r["simulation_mode"] is False
    assert r["parameters_requested"] == 17  # the example's 13 (re07-equivalence.md §3) + this fixture's background peak
    assert "schema_version" not in r and "refinement_cycles" not in r and len(r["warnings"]) == 2


def test_refined_corrections_are_varied(tmp_path):
    """zero_shift, polarization and axial_divergence flags reach GSAS-II (A103, review S1)."""
    recipe = _lab6()
    recipe["payload"]["background"].pop("single_peaks")
    for p in recipe["payload"]["instrument"]["corrections"].values():
        p[1] = True
    r = powderline.run(recipe, tmp_path, execution_mode="subprocess")
    assert r["status"] == "ok", r.get("failure")
    assert {":0:Zero", ":0:Polariz.", ":0:SH/L"} <= set(r["refined_parameters"]["parameter_name"])


def _single_atom(tmp_path, sg, cell, xyz, flags=(False, False, False)):
    recipe = _lab6()
    recipe["payload"]["background"].pop("single_peaks")
    p = lambda v, f=False: [v, f]
    recipe["payload"]["phases"] = {"P": {
        "space_group": sg,
        "unit_cell": {k: p(v) for k, v in zip(("a", "b", "c", "alpha", "beta", "gamma"), cell)},
        "atoms": {"Fe": {"element": "Fe", **{k: p(v, f) for k, v, f in zip("xyz", xyz, flags)},
                         "occupancy": p(1.0), "ADP": "Uiso", "Uiso": p(0.01)}},
        "scale": p(1.0)}}
    return powderline.run(recipe, tmp_path, execution_mode="subprocess")


RHOMB = ("R -3 m:H", (5.0, 5.0, 12.0, 90.0, 90.0, 120.0))
CUBIC = ("P 4 3 2", (5.0, 5.0, 5.0, 90.0, 90.0, 90.0))


def test_site_gsasii_misreads_is_an_error_naming_an_equivalent_position(tmp_path):
    """EB-40: GSAS-II doubles the multiplicity at (0, 1/3, 1/6); 4x the intensity, so always an error (A117).
    re/12 (R30): the error is raised through run(), before GSAS-II refines anything."""
    with pytest.raises(EngineExecutionError) as e:
        _single_atom(tmp_path / "a", *RHOMB, (0.0, 0.333333, 0.166667))
    assert e.value.reason == "unusable_site"
    assert ("payload.phases.P.atoms.Fe at (0.0, 0.333333, 0.166667): GSAS-II reads it as site '1' with multiplicity 36, "
            "but its multiplicity is 18") in str(e.value)
    assert "state the equivalent position (0.666667, 0.666667, 0.166667) instead" in str(e.value)
    assert not (tmp_path / "a" / "dummy.lst").exists()  # refused before the refinement ran
    assert _single_atom(tmp_path / "b", *RHOMB, (0.666667, 0.666667, 0.166667))["status"] == "ok"


def test_site_gsasii_cannot_name_is_an_error_only_when_refined(tmp_path):
    """EB-05: 'sp' at (0, 1/24, 0) in P432 crashes GSAS-II only when a coordinate is refined (A117)."""
    assert _single_atom(tmp_path / "fixed", *CUBIC, (0.0, 0.041667, 0.0))["status"] == "ok"
    with pytest.raises(EngineExecutionError) as e:
        _single_atom(tmp_path / "refined", *CUBIC, (0.0, 0.041667, 0.0), (False, True, False))
    assert e.value.reason == "unusable_site"
    assert "GSAS-II cannot name its site symmetry ('sp')" in str(e.value)
    assert "state the equivalent position (0.958333, 0.0, 0.0) instead" in str(e.value)


@pytest.mark.parametrize("sg, point", [("R -3 m:H", (0, 8, 4)), ("R 3 2:H", (16, 0, 8)), ("P 4 3 2", (0, 1, 0)),
                                       ("F m -3 c", (6, 1, 18)), ("P 63/m m c", (8, 16, 6)), ("P 1", (1, 2, 3))])
def test_orbit_has_the_multiplicity(sg, point):
    xyz = tuple(v / 24 for v in point)
    members = orbit(sg, xyz)
    assert len(members) == analyze_site(sg, xyz).multiplicity
    assert all(0.0 <= v < 1.0 for m in members for v in m)
    assert members == orbit(sg, xyz)  # a fixed order


def test_spf_peak_fit_failure_is_a_clear_engine_error():
    """EB-38: refine_peaks raises a bare TypeError when GSAS-II's DoPeakFit fails."""
    hist = MagicMock()
    hist.refine_peaks.side_effect = TypeError("'NoneType' object is not subscriptable")
    recipe = MagicMock()
    recipe.payload.refinement_controls.single_peak_fitting_mode.use_instrument_profile = False
    with pytest.raises(EngineExecutionError, match="GSAS-II's peak fit failed.*EB-38"):
        execute_spf_refinement(MagicMock(), hist, recipe, verbose=False)


def test_spf_runs_with_standard_statistics(tmp_path):
    old = json.loads((ROOT / "tests" / "data" / "convert_026" / "example_LaB6_singlepeakfit" / "input.json").read_text(encoding="utf-8"))
    r = powderline.run(conv.convert(old)[0], tmp_path, execution_mode="subprocess")
    assert r["status"] == "ok", r.get("failure")
    assert r["engine_details"]["parameters_varied"] > 0 and isinstance(r["r_exp"], float)
    assert not r["spf_peaks"].empty
    assert isinstance(r["engine_details"]["gof"], float)  # DoPeakFit's own reduced chi^2 (EB-52; ledger R16)
    assert r["rwp"] == pytest.approx(r["engine_details"]["rwp"], rel=1e-9)  # A149/R17: SPF fits the stated window too
    assert r["simulation_mode"] is False
    assert r["engine_details"]["converged"] is None  # DoPeakFit keeps no convergence flag (A172)



# --- re/04 PR review: divergence (A130), simulation statistics (A129), not-varied warning (A128) -------------


def _fake_run(recipe, ycalc, n_vars):
    """GSAS-II's post-run state as fit_report reads it: profile arrays, fit window, Rvals."""
    x = np.linspace(1.0, 15.0, 50)
    yobs = 100.0 + 10.0 * np.sin(x)
    hist = MagicMock()
    hist.data = {"data": [None, [np.ma.array(x), yobs, np.ones_like(x), ycalc(yobs)]], "Limits": [None, [1.0, 15.0]]}
    proj = MagicMock()
    proj.data = {"Covariance": {"data": {"Rvals": {"Nvars": n_vars, "GOF": 1.0, "chisq": 50.0, "Nobs": 50}}}}
    return proj, hist


def test_diverged_refinement_is_a_clear_engine_error():
    """GSAS-II does not flag a diverged run (NaN profile, wR shown as 100 %); PowderLine reports a failure."""
    recipe = validate_recipe(_lab6())
    proj, hist = _fake_run(recipe, lambda y: np.where(np.arange(y.size) < 5, np.nan, y), 17)
    with pytest.raises(EngineExecutionError, match=r"refinement diverged: the calculated pattern is not finite at "
                                                   r"5 of 50 points") as e:
        fit_report(proj, hist, recipe, engine_rwp=100.0)
    assert e.value.reason == "diverged"


def test_divergence_raises_through_run_in_subprocess_mode(tmp_path, monkeypatch):
    """R30: an EngineExecutionError from fit_report propagates out of the frozen executor to run()."""
    from powderline.gateways.gsasii import executors

    def diverged(*a, **k):
        raise EngineExecutionError("GSAS-II's refinement diverged: test", reason="diverged")
    monkeypatch.setattr(executors, "fit_report", diverged)
    with pytest.raises(EngineExecutionError) as e:
        powderline.run(_lab6(), tmp_path / "out", execution_mode="subprocess")
    assert e.value.reason == "diverged" and "diverged: test" in str(e.value)


def test_peak_fit_failure_carries_its_reason():
    """EB-38 (R12; the reason was added under R30)."""
    hist = MagicMock()
    hist.refine_peaks.side_effect = TypeError("'NoneType' object is not subscriptable")
    recipe = MagicMock()
    recipe.payload.refinement_controls.single_peak_fitting_mode.use_instrument_profile = False
    with pytest.raises(EngineExecutionError) as e:
        execute_spf_refinement(MagicMock(), hist, recipe, verbose=False)
    assert e.value.reason == "peak_fit_failed"


def test_fewer_parameters_varied_than_requested_warns():
    recipe = validate_recipe(_lab6())
    requested = parameters_requested(recipe)
    proj, hist = _fake_run(recipe, lambda y: y * 1.01, requested - 3)
    out = fit_report(proj, hist, recipe, engine_rwp=1.0)
    codes = [w["code"] for w in out["warnings"]]
    assert codes == ["gsasii_parameters_not_varied"]
    assert f"GSAS-II varied {requested - 3} parameter(s), but the recipe refines {requested}" in out["warnings"][0]["message"]
    proj, hist = _fake_run(recipe, lambda y: y * 1.01, requested)
    assert fit_report(proj, hist, recipe, engine_rwp=1.0)["warnings"] == []


@pytest.mark.parametrize("converged, cycles, warned", [(False, 5, True), (True, 5, False), (False, 1, False)])
def test_not_converged_is_reported_with_values_kept(converged, cycles, warned):
    """GSAS-II's Rvals['converged'] goes to engine_details; False warns, except in a simulation (A172, EB-85)."""
    raw = _lab6()
    raw["payload"]["refinement_controls"]["refinement_cycles"] = cycles
    if cycles == 1:  # a simulation refines nothing
        raw = json.loads(json.dumps(raw).replace("true", "false"))
    recipe = validate_recipe(raw)
    proj, hist = _fake_run(recipe, lambda y: y * 1.01, parameters_requested(recipe))
    proj.data["Covariance"]["data"]["Rvals"]["converged"] = converged
    out = fit_report(proj, hist, recipe, engine_rwp=1.0)
    assert out["engine_details"]["converged"] is converged
    hits = [w for w in out["warnings"] if w["code"] == "gsasii_fit_not_converged"]
    assert len(hits) == int(warned)
    if warned:
        assert hits[0]["field_path"] == "payload.refinement_controls.refinement_cycles"


def test_two_cycles_lab6_not_converged(tmp_path):
    """LaB6 with 2 cycles: GSAS-II stops before converging; a success with the warning (A172, EB-85)."""
    recipe = _lab6()
    recipe["payload"]["refinement_controls"]["refinement_cycles"] = 2
    r = powderline.run(recipe, tmp_path, execution_mode="subprocess")
    assert r["status"] == "ok", r.get("failure")
    assert r["engine_details"]["converged"] is False
    assert "gsasii_fit_not_converged" in [w["code"] for w in r["warnings"]]


def test_undefined_statistic_is_none_not_nan():
    """No degrees of freedom: r_exp, gof and chi2_red are undefined; None in every execution mode (JSON-safe)."""
    recipe = validate_recipe(_lab6())
    proj, hist = _fake_run(recipe, lambda y: y * 1.01, 60)
    out = fit_report(proj, hist, recipe, engine_rwp=1.0)
    assert isinstance(out["rwp"], float) and out["r_exp"] is None and out["gof"] is None and out["chi2_red"] is None


def test_simulation_reports_statistics_and_says_it_is_one(tmp_path):
    """A simulation gets the standard statistics, like a refinement, and simulation_mode True (A129)."""
    old = json.loads((ROOT / "tests" / "data" / "convert_026" / "example_DRX_33_simulation" / "input.json").read_text(encoding="utf-8"))
    r = powderline.run(conv.convert(old)[0], tmp_path, execution_mode="subprocess")
    assert r["status"] == "ok", r.get("failure")
    assert r["simulation_mode"] is True and isinstance(r["rwp"], float)
    assert r["engine_details"]["parameters_varied"] == 0


def test_other_type_error_in_peak_fit_keeps_its_traceback():
    """Ledger R15: only DoPeakFit's None result becomes the EB-38 message."""
    hist = MagicMock()
    hist.refine_peaks.side_effect = TypeError("unsupported operand type(s) for +: 'int' and 'str'")
    recipe = MagicMock()
    recipe.payload.refinement_controls.single_peak_fitting_mode.use_instrument_profile = False
    with pytest.raises(TypeError, match="unsupported operand"):
        execute_spf_refinement(MagicMock(), hist, recipe, verbose=False)


@pytest.mark.parametrize("given", ["dict", "model"])
def test_gsasclient_carries_validation_warnings(tmp_path, monkeypatch, given):
    """A115: a direct GSASClient call reports the A107 default too (kicker.run adds them only in-process)."""
    recipe = _lab6()
    recipe["payload"]["phases"]["LaB6"].pop("peak_broadening", None)
    if given == "model":
        recipe = validate_recipe(recipe)
    monkeypatch.setattr(GSASClient, "_dispatch", lambda self, *a: {"success": True, "warnings": [{"code": "x"}]})
    result = GSASClient().submit_simulation(recipe, tmp_path)
    assert [w["code"] for w in result["warnings"]] == ["gsasii_broadening_default_applied"] * 2 + ["x"]



@pytest.mark.parametrize("value, text", [(0.2, "0.2"), (0.5, "0.5"), (0.0625, "0.0625"), (1 / 3, "0.333333"),
                                         (23 / 24, "0.958333"), (0.1234567, "0.1234567")])
def test_site_message_coordinates_exact_where_a_decimal_form_exists(value, text):
    """A120/A121: a finite decimal is written exactly, a third (or 1/24) to 6 decimals."""
    from powderline.gateways.gsasii.sites import _coordinate
    assert _coordinate(value) == text


def test_site_message_says_uaniso_must_be_transformed():
    """Moving an anisotropic atom to an equivalent position also rotates its Uij (U' = R U R^T)."""
    from types import SimpleNamespace
    from GSASII import GSASIIspc as G2spc
    from powderline.gateways.gsasii.schema import GsasiiPhase, gsasii_space_group
    from powderline.gateways.gsasii.sites import site_problems
    u = {"U11": 0.011, "U22": 0.011, "U33": 0.023, "U12": 0.0085, "U13": 0.0031, "U23": -0.0031}
    phase = GsasiiPhase.model_validate({
        "space_group": "R -3 m:H", "scale": [1.0, False],
        "unit_cell": {k: [v, False] for k, v in zip(("a", "b", "c", "alpha", "beta", "gamma"),
                                                    (5.0, 5.0, 13.0, 90.0, 90.0, 120.0))},
        "atoms": {"Fe": {"element": "Fe", "x": [0.0, False], "y": [0.333333, False], "z": [0.166667, False],
                         "occupancy": [1.0, False], "ADP": "Uaniso",
                         "Uaniso": {k: [v, False] for k, v in u.items()}}}})
    _err, sgdata = G2spc.SpcGroup(gsasii_space_group("R -3 m:H"))
    xyz = [0.0, 1 / 3, 1 / 6]
    sym, mult = G2spc.SytSym(xyz, sgdata)[:2]
    proj = SimpleNamespace(data={"Phases": {"P": {"General": {"SGData": sgdata},
                                                  "Atoms": [["Fe", "Fe", "", *xyz, 1.0, sym, mult]]}}})
    (problem,) = site_problems(proj, {"P": phase})
    assert "its Uaniso must be transformed by the same symmetry operation (U' = R U R^T)" in problem
