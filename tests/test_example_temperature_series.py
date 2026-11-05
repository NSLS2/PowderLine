"""The simulated LaB6 temperature series (examples/example_LaB6_temperature_series, re/22): a sequential
refinement chained through the output recipe, checked against the programmed truth and the committed reference."""
import csv
import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
EXAMPLE = REPO / "examples" / "example_LaB6_temperature_series"


def _module(name):
    spec = importlib.util.spec_from_file_location(name, EXAMPLE / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _report(path):
    with open(path, newline="", encoding="utf-8") as f:
        return [{k: (v == "True" if k in ("converged", "output_recipe_valid") else None if v == "" else float(v))
                 for k, v in row.items()} for row in csv.DictReader(f)]


@pytest.mark.core
def test_series_data_are_valid_xrd_blocks_consistent_with_the_truth():
    import powderline
    truth = json.loads((EXAMPLE / "data" / "truth.json").read_text(encoding="utf-8"))
    recipe = powderline.load_recipe_asset(EXAMPLE / "input.json")
    assert len(truth["steps"]) == 6 and [s["temperature_C"] for s in truth["steps"]] == [25, 120, 215, 310, 405, 500]
    a = [s["a"] for s in truth["steps"]]
    assert all(x < y for x, y in zip(a, a[1:])) and a[-1] - a[0] == pytest.approx(0.01404, abs=2e-4)  # Akdoğan & Payzant 2025
    from powderline import recipes
    for step in truth["steps"]:
        data = json.loads((EXAMPLE / "data" / f"lab6_{int(step['temperature_C']):03d}C.json").read_text(encoding="utf-8"))
        assert len(data["tth"]) == len(data["Itth"]) == len(data["Itth_weights"]) == step["points"]
        assert min(data["Itth"]) >= 0 and max(data["Itth"]) == step["max_counts"]
        powderline.validate(recipes.with_block(recipe, "payload.xrd_data", data))  # every step's recipe validates
    assert recipe["payload"]["xrd_data"]["filename"] == "simulated_LaB6_025C"


@pytest.mark.core
def test_committed_series_reference_recovers_the_programmed_expansion():
    """The committed reference: every refined cell within 3 ESD of the programmed a(T) and the fitted quadratic
    within 10 % of the programmed coefficients; every step's output recipe valid."""
    rows = _report(EXAMPLE / "output" / "series_report.csv")
    assert len(rows) == 6 and all(r["output_recipe_valid"] for r in rows)
    for r in rows:
        assert abs(r["a_refined"] - r["a_true"]) <= 3 * r["a_esd"], r
        assert abs(r["Uiso_La_refined"] - r["Uiso_La_true"]) <= 3 * r["Uiso_La_esd"], r
    fit = json.loads((EXAMPLE / "output" / "thermal_expansion_fit.json").read_text(encoding="utf-8"))
    c, p = fit["coefficients"], fit["programmed"]
    assert c[0] == pytest.approx(p[0], abs=2e-5) and c[1] == pytest.approx(p[1], rel=0.1)


@pytest.mark.gsasii
@pytest.mark.slow
def test_series_runs_sequentially_through_the_output_recipe(tmp_path):
    """Re-run the chain (GSAS-II) and compare with the committed reference within the regression tolerance."""
    pytest.importorskip("GSASII.GSASIIscriptable")
    run_series = _module("run_series")
    rows = run_series.run_series(tmp_path / "out", tmp_path / "work")
    reference = _report(EXAMPLE / "output" / "series_report.csv")
    assert len(rows) == len(reference) == 6
    for got, ref in zip(rows, reference):
        assert got["output_recipe_valid"] is True
        assert got["a_refined"] == pytest.approx(ref["a_refined"], abs=3 * ref["a_esd"])
        assert got["rwp"] == pytest.approx(ref["rwp"], abs=0.1)  # docs/regression-tolerance.md
        assert abs(got["a_refined"] - got["a_true"]) <= 3 * got["a_esd"]
    final = json.loads((tmp_path / "out" / "final_output_recipe.json").read_text(encoding="utf-8"))
    assert final["payload"]["xrd_data"]["filename"] == "simulated_LaB6_500C"
    assert final["metadata"]["powderline_provenance"]["parent_run_id"]


# --- the easydiffraction leg (re/22b): same data, same runner, its own first-step recipe; golden under tests/data ---

ED_RECIPE = EXAMPLE / "easydiffraction" / "input.json"
ED_GOLDEN = REPO / "tests" / "data" / "easydiffraction" / "native" / "golden" / "lab6_temperature_series.json"


@pytest.mark.core
def test_easydiffraction_leg_recipe_validates_with_every_step_and_the_golden_says_what_happened():
    import powderline
    from powderline import recipes
    recipe = powderline.load_recipe_asset(ED_RECIPE)
    assert recipe["schema_name"] == "easydiffraction.rietveld"
    assert recipe["payload"]["instrument"]["broadening"]["parameters"]["broad_lorentz_x"][1] is False  # held: see DESCRIPTION
    truth = json.loads((EXAMPLE / "data" / "truth.json").read_text(encoding="utf-8"))
    for step in truth["steps"]:
        data = json.loads((EXAMPLE / "data" / f"lab6_{int(step['temperature_C']):03d}C.json").read_text(encoding="utf-8"))
        powderline.validate(recipes.with_block(recipe, "payload.xrd_data", data))
    golden = json.loads(ED_GOLDEN.read_text(encoding="utf-8"))
    rows = golden["series_report"]
    assert len(rows) == 6 and all(r["output_recipe_valid"] for r in rows)
    assert all(abs(r["a_refined"] - r["a_true"]) / r["a_true"] < 4e-5 for r in rows)      # the cell: within 40 ppm
    assert all(r["Uiso_La_refined"] < r["Uiso_La_true"] for r in rows)                      # the recorded La Uiso offset
    c, p = golden["thermal_expansion_fit"]["coefficients"], golden["thermal_expansion_fit"]["programmed"]
    assert c[1] == pytest.approx(p[1], rel=0.05)                                             # the expansion itself
    free = golden["free_lorentz_x_run"]
    assert len(free["series_report"]) == 2 and free["series_report"][1]["output_recipe_valid"] is False
    assert "Lorentzian FWHM" in free["stop_reason"]


@pytest.mark.easydiffraction
@pytest.mark.slow
def test_easydiffraction_leg_runs_sequentially_and_matches_its_golden(tmp_path):
    """Re-run the easydiffraction chain and compare with the golden as the CrysFML goldens are compared (cell within
    1e-4 relative, counts, validity; no Rwp or ESD assertion): CrysFML's single-precision pattern makes its fits
    start-dependent (EB-90), Rwp has moved 0.5 pp between builds."""
    pytest.importorskip("easydiffraction")
    run_series = _module("run_series")
    rows = run_series.run_series(tmp_path / "out", tmp_path / "work", recipe_path=ED_RECIPE)
    golden = json.loads(ED_GOLDEN.read_text(encoding="utf-8"))["series_report"]
    assert len(rows) == len(golden) == 6
    for got, ref in zip(rows, golden):
        assert got["output_recipe_valid"] is True
        assert got["a_refined"] == pytest.approx(ref["a_refined"], rel=1e-4)
        assert got["parameters_varied"] == ref["parameters_varied"] == 14
    fit = run_series.expansion_fit(rows)
    assert fit["coefficients"][1] == pytest.approx(2.4645e-5, rel=0.05)  # the programmed linear coefficient (truth.json XI)
