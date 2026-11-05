"""The simulated textured LaB6 (examples/example_LaB6_textured, re/29, P-48): a mathematical demonstration of the
March-Dollase block -- the programmed r = 0.6 along [001] recovered by refinement in GSAS-II (the committed reference)
and in easydiffraction's CrysPy calculator (the leg). The pass/fail gate for the capability itself is the Dollase-formula
check in tests/test_gsasii_preferred_orientation.py and tests/test_easydiffraction_preferred_orientation.py (C1)."""
import csv
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
EXAMPLE = REPO / "examples" / "example_LaB6_textured"
RATIO = "payload.phases.LaB6.preferred_orientation.ratio"


def _dispositions(path):
    with open(path, newline="", encoding="utf-8") as f:
        return {row["path"]: row for row in csv.DictReader(f)}


@pytest.mark.core
def test_data_truth_and_recipes_agree():
    import powderline
    truth = json.loads((EXAMPLE / "data" / "truth.json").read_text(encoding="utf-8"))
    data = json.loads((EXAMPLE / "data" / "lab6_textured.json").read_text(encoding="utf-8"))
    assert truth["march_dollase_r"] == 0.6 and truth["axis"] == [0, 0, 1]
    assert len(data["tth"]) == len(data["Itth"]) == len(data["Itth_weights"]) == truth["points"] == 3821
    assert min(data["Itth"]) >= 0 and max(data["Itth"]) == truth["max_counts"]
    for leg in ("input.json", "easydiffraction/input.json"):
        recipe = powderline.load_recipe_asset(EXAMPLE / leg)
        po = recipe["payload"]["phases"]["LaB6"]["preferred_orientation"]
        assert po["model"] == "march_dollase" and po["hkl"] == [0, 0, 1] and po["ratio"][:2] == [0.8, True]
        assert recipe["payload"]["xrd_data"]["tth"] == data["tth"]
        codes = {w["code"] for w in powderline.validate(recipe).warnings}
        assert codes <= {"gsasii_broadening_default_applied"}, codes  # nothing held, nothing else defaulted
    ed = powderline.load_recipe_asset(EXAMPLE / "easydiffraction" / "input.json")
    assert ed["payload"]["refinement_controls"]["calculator"] == "cryspy"  # CrysFML ignores PO (EB-97)
    assert ed["payload"]["phases"]["LaB6"]["preferred_orientation"]["march_random_fract"] == [0.0, False, 0.0, 1.0]


@pytest.mark.core
def test_committed_reference_recovers_the_programmed_r():
    """The GSAS-II reference: r within 3 ESD of 0.6 (it is 0.5978(14)), refined and written back, valid output recipe."""
    rows = _dispositions(EXAMPLE / "output" / "parameter_dispositions.csv")
    r = rows[RATIO]
    assert r["disposition"] == "varied"
    assert abs(float(r["value"]) - 0.6) <= 3 * float(r["esd"]) and float(r["esd"]) < 0.005
    out = json.loads((EXAMPLE / "output" / "output_recipe.json").read_text(encoding="utf-8"))
    assert out["payload"]["phases"]["LaB6"]["preferred_orientation"]["ratio"][0] == pytest.approx(float(r["value"]))
    assert out["metadata"]["powderline_provenance"]["schema_name"] == "gsasii.rietveld"
    import powderline
    powderline.validate(out)  # the committed output recipe is a valid recipe (chaining currency, KI-04)


@pytest.mark.gsasii
@pytest.mark.slow
def test_gsasii_recovers_r_again(tmp_path):
    pytest.importorskip("GSASII.GSASIIscriptable")
    import powderline
    res = powderline.run(powderline.load_recipe_asset(EXAMPLE / "input.json"), tmp_path / "out", execution_mode="subprocess")
    ref = _dispositions(EXAMPLE / "output" / "parameter_dispositions.csv")[RATIO]
    got = res["parameter_dispositions"].set_index("path").loc[RATIO]
    assert res["status"] == "ok" and res["output_recipe_valid"] is True
    assert float(got["value"]) == pytest.approx(float(ref["value"]), abs=3 * float(ref["esd"]))
    assert res["rwp"] == pytest.approx(12.55, abs=0.1)  # the series test's cross-build allowance


@pytest.mark.easydiffraction
@pytest.mark.slow
def test_cryspy_recovers_r_too(tmp_path):
    """The demonstration's cross-engine half: CrysPy's refined March r for the same pattern lies within 2 % of the
    programmed 0.6 (its March correction is Dollase's times a normalisation, EB-98 -- the refined r is unaffected)."""
    pytest.importorskip("easydiffraction")
    import powderline
    res = powderline.run(powderline.load_recipe_asset(EXAMPLE / "easydiffraction" / "input.json"), tmp_path / "out")
    got = res["parameter_dispositions"].set_index("path").loc[RATIO]
    assert res["status"] == "ok" and res["output_recipe_valid"] is True
    assert float(got["value"]) == pytest.approx(0.6, rel=0.02)
