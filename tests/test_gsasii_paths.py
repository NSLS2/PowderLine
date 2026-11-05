"""re/20b, re/21 (KI-04): GSAS-II parameter names -> recipe paths, proven on the committed regression outputs (engine-free)."""
import json
from pathlib import Path

import pandas as pd
import pytest

from powderline import roundtrip
from powderline.gateways.gsasii import paths, schema

pytestmark = pytest.mark.core

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def _case(name):
    """(model, result-like dict) from a committed example and its tracked output."""
    model = schema.validate_recipe(json.loads((EXAMPLES / name / "input.json").read_text(encoding="utf-8-sig")))
    out = EXAMPLES / name / "output"
    result = {"refined_parameters": pd.read_csv(out / "refined_parameters.csv") if (out / "refined_parameters.csv").exists()
              else pd.DataFrame(columns=["parameter_name", "descriptive_name", "phase_name", "phase_idx", "atom_name",
                                         "atom_idx", "value", "esd", "category"]),
              "unit_cell_data": {}, "spf_peaks": pd.DataFrame()}
    phases = getattr(model.payload, "phases", None) or {}
    for phase in phases:
        f = out / f"{phase}_unit_cell_report.csv"
        if f.exists():
            result["unit_cell_data"][phase] = pd.read_csv(f)
    spf = out / "single_peaks_report.txt"
    if spf.exists():
        result["spf_peaks"] = pd.read_csv(spf, sep="\t", comment="#")
    return model, result


def _value(recipe, path):
    node = recipe
    for key in path.split("."):
        node = node[int(key) if key.isdigit() else key]
    return node if "chebyshev.coefficients" in path else node[0]


def test_lab6_background_instrument_and_scale_map_to_their_paths():
    model, result = _case("example_LaB6")
    refined, not_varied, at_limit, problems = paths.refined_by_path(model, result)
    assert refined["payload.background.chebyshev.coefficients.0"] == (pytest.approx(30.02431), pytest.approx(6.768e-2, rel=1e-3))
    assert refined["payload.instrument.broadening.U"][0] == pytest.approx(49.11908, rel=1e-6)
    assert refined["payload.phases.LaB6.scale"][0] == pytest.approx(3.773081e-02, rel=1e-6)
    assert at_limit == set()
    assert not problems
    out = roundtrip.build_output(model, refined, not_varied=not_varied, validator=schema.validate_recipe)
    assert out.valid, out.problems
    rows = {r["path"]: r for r in out.dispositions}
    assert rows["payload.instrument.broadening.U"]["disposition"] == "varied"
    assert rows["payload.phases.LaB6.unit_cell.a"]["disposition"] == "held_by_user"


def test_drx33_cell_comes_from_the_unit_cell_report():
    model, result = _case("example_DRX_33")
    refined, not_varied, _, problems = paths.refined_by_path(model, result)
    assert refined["payload.phases.DRX_33.unit_cell.a"] == (pytest.approx(4.17153245), pytest.approx(0.00330186))
    assert "payload.phases.DRX_33.unit_cell.alpha" not in refined  # symmetry-fixed: the model's value, no ESD
    out = roundtrip.build_output(model, refined, not_varied=not_varied, validator=schema.validate_recipe)
    assert _value(out.recipe, "payload.phases.DRX_33.unit_cell.c") == pytest.approx(4.17153245)
    # the committed reference refined the second phase's crystallite size to -1355 um: the schema refuses it,
    # so the output recipe is written but not valid, and says exactly that (P-43 D5)
    assert not out.valid and any("Li4MgWO6_SG12.peak_broadening.size_broadening.isotropic_size" in p for p in out.problems)


def test_atomrefine_coordinates_are_recipe_plus_shift_and_unphysical_values_are_flagged():
    """GSAS-II varies dAx/dAy/dAz, the shift from the starting coordinate (ApplyXYZshifts adds it once at the
    end); occupancies refined below 0 make the output recipe honestly invalid (P-43 D5)."""
    model, result = _case("example_DRX_33_atomrefine")
    refined, not_varied, _, problems = paths.refined_by_path(model, result)
    o2_x = model.payload.phases["Li4MgWO6_SG12"].atoms["O2"].x.value
    assert refined["payload.phases.Li4MgWO6_SG12.atoms.O2.x"][0] == pytest.approx(o2_x + 8.903197e-02)
    assert refined["payload.phases.DRX_33.atoms.Li.occupancy"][0] == pytest.approx(-3.514487e-01)
    out = roundtrip.build_output(model, refined, not_varied=not_varied, validator=schema.validate_recipe)
    assert _value(out.recipe, "payload.phases.Li4MgWO6_SG12.atoms.O2.x") == pytest.approx(o2_x + 8.903197e-02)
    assert not out.valid and any("occupancy" in p for p in out.problems)


def test_anisoadp_uij_and_broadening_map():
    model, result = _case("example_DRX_33_anisoADP")
    refined, not_varied, _, problems = paths.refined_by_path(model, result)
    uij = {k: v for k, v in refined.items() if ".Uaniso." in k}
    assert uij, "the anisotropic example refines Uij"
    # units: every mapped name is written by setters.py from the recipe value and read back unconverted, so no
    # scale applies here (A^2, um, microstrain, centideg); the values below are the committed reference's
    size = {k: v for k, v in refined.items() if "peak_broadening" in k}
    assert any(k.endswith("size_broadening.isotropic_size") for k in size) or any(k.endswith("strain_broadening.isotropic_strain") for k in size)
    out = roundtrip.build_output(model, refined, not_varied=not_varied, validator=schema.validate_recipe)
    u11 = next(k for k in refined if k.endswith(".Uaniso.U11"))
    assert _value(out.recipe, u11) == pytest.approx(refined[u11][0])
    # the reference's DRX_33 crystallite size came out at -9.68 um: not valid, and named
    assert not out.valid and any("DRX_33.peak_broadening.size_broadening.isotropic_size" in p for p in out.problems)


def test_singlepeakfit_peaks_map_by_index_without_the_peak_fit_block_and_say_what_is_missing():
    """A result without ``peak_fit`` (the peak table only): the peaks map by index without ESDs, and the
    background the peak fit refined is named as missing -- never silently kept at its starting value (re/21)."""
    model, result = _case("example_LaB6_singlepeakfit")
    refined, not_varied, _, problems = paths.refined_by_path(model, result)
    n = len(model.payload.single_peaks.positions)
    assert sum(1 for k in refined if k.startswith("payload.single_peaks.positions.")) == n
    assert refined["payload.single_peaks.positions.0"] == (pytest.approx(2.29520897), None)
    assert refined["payload.single_peaks.pv_gaussian_sigma_sq.0"][0] == pytest.approx(1.09898814)
    assert refined["payload.single_peaks.pv_lorentzian_gamma.0"][0] == pytest.approx(0.58135191)
    assert len(problems) == 1 and "peak_fit" in problems[0] and "background coefficients" in problems[0]
    assert "U..Z" not in problems[0]  # per-peak widths: the instrument profile is not in use
    out = roundtrip.build_output(model, refined, not_varied=not_varied, validator=schema.validate_recipe)
    assert out.valid, out.problems


def _peak_fit(rows):
    return {"parameters": [{"name": n, "value": v, "esd": e} for n, v, e in rows]}


def test_singlepeakfit_peak_fit_block_maps_background_profile_and_peaks_with_esds():
    """re/21: ``result['peak_fit']`` (fit_report.peak_fit_parameters) carries everything GSAS-II's peak fit varied by
    its own names; each lands on its recipe path with its ESD, in recipe units (GSAS-II's)."""
    model, result = _case("example_LaB6_singlepeakfit")
    result = dict(result, peak_fit=_peak_fit([("Back;0", 27.2139, 0.31), ("Back;5", -0.4, 0.05),
                                              ("BkPkpos;0", 1.81, 0.002), ("BkPkint;0", 95.0, 3.0),
                                              ("BkPksig;0", 9.5, 0.4), ("BkPkgam;0", 1.1, 0.1),
                                              ("pos0", 2.2952038, 2.6e-5), ("int0", 5050.63, 12.0),
                                              ("sig0", 1.09376, 0.02), ("gam0", 0.58410, 0.01), ("pos35", 14.1, 1e-4)]))
    refined, not_varied, _, problems = paths.refined_by_path(model, result)
    assert not problems
    assert refined["payload.background.chebyshev.coefficients.0"] == (27.2139, 0.31)
    assert refined["payload.background.chebyshev.coefficients.5"] == (-0.4, 0.05)
    assert refined["payload.background.single_peaks.positions.0"] == (1.81, 0.002)
    assert refined["payload.background.single_peaks.pv_lorentzian_gamma.0"] == (1.1, 0.1)
    assert refined["payload.single_peaks.positions.0"] == (2.2952038, 2.6e-5)
    assert refined["payload.single_peaks.pv_gaussian_sigma_sq.0"] == (1.09376, 0.02)
    assert refined["payload.single_peaks.positions.35"] == (14.1, 1e-4)
    assert "payload.single_peaks.positions.1" not in refined  # only what the block carries
    assert "payload.background.chebyshev.coefficients.0" not in not_varied
    out = roundtrip.build_output(model, refined, not_varied=not_varied, validator=schema.validate_recipe)
    assert out.valid, out.problems
    rows = {r["path"]: r for r in out.dispositions}
    assert rows["payload.background.chebyshev.coefficients.0"]["disposition"] == "varied"
    assert rows["payload.background.chebyshev.coefficients.0"]["esd"] == 0.31
    assert _value(out.recipe, "payload.background.chebyshev.coefficients.0") == 27.2139


def test_peak_fit_names_without_a_place_or_a_value_are_problems_not_silence():
    model, result = _case("example_LaB6_singlepeakfit")
    result = dict(result, peak_fit=_peak_fit([("DebyeA;0", 1.0, 0.1), ("pos99", 5.0, 0.1), ("Back;7", 1.0, 0.1),
                                              ("pos0", None, 1e-4), ("int0", 100.0, 2.0)]))
    refined, _, _, problems = paths.refined_by_path(model, result)
    assert refined == {"payload.single_peaks.intensities.0": (100.0, 2.0)}
    assert len(problems) == 4
    assert any("'DebyeA;0'" in p and "no recipe path" in p for p in problems)
    assert any("'pos99'" in p and "no recipe path" in p for p in problems)
    assert any("'Back;7'" in p for p in problems)
    assert any("'pos0'" in p and "could not be read" in p for p in problems)


def test_peak_fit_parameters_read_the_project_where_dopeakfit_wrote_them():
    """fit_report.peak_fit_parameters (engine-free: it reads ``hist.data``): names and ESDs from ``sigDict``, values
    from Background[0][3+n], Background[1]['peaksList'], Instrument Parameters[0][name][1] and Peak List['peaks']."""
    from types import SimpleNamespace
    from powderline.gateways.gsasii.fit_report import peak_fit_parameters
    hist = SimpleNamespace(data={
        "Background": [["chebyschev-1", True, 3, 27.2, 2.25, -0.4],
                       {"nPeaks": 1, "peaksList": [[1.81, True, 95.0, True, 9.5, True, 1.1, True]]}],
        "Instrument Parameters": [{"U": [49.1, 66.39, True], "V": [11.2, 0.547, True], "Lam": [0.1665, 0.1665, False],
                                   "Type": ["PXC", "PXC", False]}, {}],
        "Peak List": {"peaks": [[2.2952, 1, 5050.6, 1, 1.0938, 0, 0.5841, 0]],
                      "sigDict": {"Back;0": 0.31, "Back;2": 0.05, "BkPkpos;0": 0.002, "BkPkgam;0": 0.1,
                                  "U": 5.03, "V": 0.547, "pos0": 2.6e-5, "int0": 12.0, "Back;9": 0.1, "DebyeA;0": 0.2,
                                  "pos7": float("nan"), "gam0": 0}}})
    rows = {r["name"]: (r["value"], r["esd"]) for r in peak_fit_parameters(hist)}
    assert rows["Back;0"] == (27.2, 0.31) and rows["Back;2"] == (-0.4, 0.05)
    assert rows["BkPkpos;0"] == (1.81, 0.002) and rows["BkPkgam;0"] == (1.1, 0.1)
    assert rows["U"] == (66.39, 5.03) and rows["V"] == (0.547, 0.547)
    assert rows["pos0"] == (2.2952, 2.6e-5) and rows["int0"] == (5050.6, 12.0)
    assert rows["Back;9"] == (None, 0.1) and rows["DebyeA;0"] == (None, 0.2) and rows["pos7"] == (None, None)
    assert rows["gam0"] == (0.5841, None)  # a zero ESD is DoPeakFit's "singular matrix", undetermined, not exact
    assert all(type(v) is float for v, e in rows.values() if v is not None)  # plain floats: the block crosses JSON


def test_background_peak_rows_map_by_index():
    model, _ = _case("example_LaB6")
    rows = pd.DataFrame([{"parameter_name": ":0:BkPkpos;0", "descriptive_name": "", "phase_name": "", "phase_idx": None,
                          "atom_name": "", "atom_idx": None, "value": 10.5, "esd": 0.01, "category": "background_peak"},
                         {"parameter_name": ":0:BkPksig;0", "descriptive_name": "", "phase_name": "", "phase_idx": None,
                          "atom_name": "", "atom_idx": None, "value": 2.0, "esd": None, "category": "background_peak"}])
    refined, _, _, problems = paths.refined_by_path(model, {"refined_parameters": rows, "unit_cell_data": {}, "spf_peaks": pd.DataFrame()})
    assert not problems
    assert refined["payload.background.single_peaks.positions.0"] == (10.5, 0.01)
    assert refined["payload.background.single_peaks.pv_gaussian_sigma_sq.0"] == (2.0, None)


def test_unknown_name_is_reported_not_silently_dropped():
    model, _ = _case("example_LaB6")
    rows = pd.DataFrame([{"parameter_name": ":0:Mystery", "descriptive_name": "", "phase_name": "", "phase_idx": None,
                          "atom_name": "", "atom_idx": None, "value": 1.0, "esd": None, "category": "other"}])
    refined, _, _, problems = paths.refined_by_path(model, {"refined_parameters": rows, "unit_cell_data": {}, "spf_peaks": pd.DataFrame()})
    assert refined == {} and len(problems) == 1 and "Mystery" in problems[0]


def test_instrument_profile_peak_fit_maps_the_refined_profile_from_the_peak_fit_block():
    """use_instrument_profile: GSAS-II overwrites the peak widths from U..Z (held in the recipe) and refines U..Z.
    Without the peak_fit block only flagged peak parameters are mapped and the missing profile is a problem (D5);
    with it (re/21) U..Z land on their paths with ESDs and the output recipe is valid."""
    import copy
    r = json.loads((EXAMPLES / "example_LaB6_singlepeakfit" / "input.json").read_text(encoding="utf-8-sig"))
    r = copy.deepcopy(r)
    r["payload"]["refinement_controls"]["single_peak_fitting_mode"]["use_instrument_profile"] = True
    for k in ("pv_gaussian_sigma_sq", "pv_lorentzian_gamma"):
        for p in r["payload"]["single_peaks"][k]:
            p[1] = False
    for k in ("U", "V", "W", "X", "Y", "Z"):
        r["payload"]["instrument"]["broadening"][k][1] = True
    model = schema.validate_recipe(r)
    _, result = _case("example_LaB6_singlepeakfit")
    refined, not_varied, _, problems = paths.refined_by_path(model, result)
    assert not any(".pv_" in k for k in refined) and any(k.startswith("payload.single_peaks.positions.") for k in refined)
    assert len(problems) == 1 and "peak_fit" in problems[0] and "U..Z" in problems[0]
    assert {f"payload.instrument.broadening.{k}" for k in "UVWXYZ"} <= not_varied
    out = roundtrip.build_output(model, refined, not_varied=not_varied, validator=schema.validate_recipe)
    assert not [p for p in out.problems if "is held" in p], out.problems  # no spurious "held but changed"
    # with the peak fit block (U..Z, the background and the peaks with ESDs), the mode is served
    result = dict(result, peak_fit=_peak_fit([("U", 66.39, 5.03), ("V", 0.547, 0.547), ("W", 1.056, 0.0128),
                                              ("X", 45.67, 10.7), ("Y", -0.236, 0.578), ("Z", -45.09, 10.7),
                                              ("Back;0", 27.2, 0.31), ("pos0", 2.2952038, 2.6e-5), ("int0", 5050.6, 12.0)]))
    refined, not_varied, _, problems = paths.refined_by_path(model, result)
    assert not problems
    assert refined["payload.instrument.broadening.U"] == (66.39, 5.03) and refined["payload.single_peaks.positions.0"][1] == 2.6e-5
    assert not any(".pv_" in k for k in refined) and not any("broadening" in p for p in not_varied)
    out = roundtrip.build_output(model, refined, not_varied=not_varied, validator=schema.validate_recipe)
    assert out.valid, out.problems
    rows = {r["path"]: r for r in out.dispositions}
    assert rows["payload.instrument.broadening.Z"]["disposition"] == "varied" and rows["payload.instrument.broadening.Z"]["esd"] == 10.7
