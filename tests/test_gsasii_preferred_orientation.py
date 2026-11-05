"""re/29 (P-48): GSAS-II and March-Dollase preferred orientation -- the frozen setter writes the HAP entry (R36/R37),
the refined coefficient reaches the output recipe, and the C1 gate: the textured/untextured intensity ratio of every
resolved LaB6 reflection equals Dollase's correction in GSAS-II's convention."""
import json
from pathlib import Path

import numpy as np
import pytest

pytestmark = [pytest.mark.gsasii, pytest.mark.slow]
pytest.importorskip("GSASII.GSASIIscriptable")

import powderline  # noqa: E402
from intensity_ratio import dollase_correction, peak_areas, resolved  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
R, AXIS = 0.6, (0, 0, 1)


def _calc(po):
    recipe = json.loads((REPO / "examples" / "example_LaB6_simulation" / "input.json").read_text(encoding="utf-8-sig"))
    if po:
        recipe["payload"]["phases"]["LaB6"]["preferred_orientation"] = po
    return recipe


def test_setter_writes_the_hap_entry_and_the_gate_holds(tmp_path):
    from GSASII import GSASIIscriptable as G2sc
    plain = powderline.run(_calc(None), tmp_path / "plain", execution_mode="subprocess")
    textured = powderline.run(_calc({"model": "march_dollase", "hkl": list(AXIS), "ratio": [R, False]}),
                              tmp_path / "po", execution_mode="subprocess")
    # R36/R37: the project's HAP entry is GSAS-II's default with the three slots overwritten (plumbing)
    proj = G2sc.G2Project(gpxfile=str(tmp_path / "po" / "dummy.gpx"))
    hist = proj.histograms()[0]
    entry = proj.phases()[0].data["Histograms"][hist.name]["Pref.Ori."]
    assert entry[0] == "MD" and entry[1] == R and entry[2] is False and list(entry[3]) == list(AXIS)
    assert entry[4:] == [0, {}, [], 0.1]
    plain_proj = G2sc.G2Project(gpxfile=str(tmp_path / "plain" / "dummy.gpx"))
    plain_hap = plain_proj.phases()[0].data["Histograms"][plain_proj.histograms()[0].name]
    hap = proj.phases()[0].data["Histograms"][hist.name]
    assert {k: repr(v) for k, v in hap.items() if k != "Pref.Ori."} == {k: repr(v) for k, v in plain_hap.items() if k != "Pref.Ori."}
    assert plain_hap["Pref.Ori."][:4] == ["MD", 1.0, False, [0, 0, 1]]           # GSAS-II's default without the block
    # a non-palindromic axis reaches slot 3 in the recipe's order (the cubic gate below cannot see a permutation)
    powderline.run(_calc({"model": "march_dollase", "hkl": [1, 2, 3], "ratio": [R, False]}), tmp_path / "axis", execution_mode="subprocess")
    axis_proj = G2sc.G2Project(gpxfile=str(tmp_path / "axis" / "dummy.gpx"))
    assert list(axis_proj.phases()[0].data["Histograms"][axis_proj.histograms()[0].name]["Pref.Ori."][3]) == [1, 2, 3]
    assert textured["output_recipe"]["payload"]["phases"]["LaB6"]["preferred_orientation"] == \
        {"model": "march_dollase", "hkl": list(AXIS), "ratio": [R, False]}
    # C1: Dollase's correction, reflection by reflection
    peaks = plain["peak_list_data"]["LaB6"]
    centres = np.asarray(peaks["2theta"], dtype=float)
    keep = [i for i in resolved(centres, min_separation=0.45) if 1.5 < centres[i] < 14.5]   # clean peaks: tails of a strong neighbour would bias a weak one
    a0 = peak_areas(plain["fit_profile"]["two_theta"], plain["fit_profile"]["y_calc"], plain["fit_profile"]["y_bkg"], centres[keep])
    a1 = peak_areas(textured["fit_profile"]["two_theta"], textured["fit_profile"]["y_calc"], textured["fit_profile"]["y_bkg"], centres[keep])
    ratio = a1 / a0
    expected = np.array([dollase_correction((int(peaks["h"][i]), int(peaks["k"][i]), int(peaks["l"][i])), AXIS, R) for i in keep])
    assert len(ratio) >= 6 and np.all(np.isfinite(ratio))
    assert np.allclose(ratio, expected, rtol=2e-3, atol=0.0), np.column_stack([centres[keep], ratio, expected])
    assert expected.min() < 0.8 < 1.8 < expected.max()         # a real texture: (hk0) suppressed, (00l)/(h00) enhanced


def test_refined_coefficient_reaches_the_output_recipe_with_an_esd(tmp_path):
    recipe = json.loads((REPO / "examples" / "example_LaB6" / "input.json").read_text(encoding="utf-8-sig"))
    # from exactly 1.0 GSAS-II aborts (cubic phase: the averaged correction is stationary at r = 1, EB-99); start beside it
    recipe["payload"]["phases"]["LaB6"]["preferred_orientation"] = {"model": "march_dollase", "hkl": [0, 0, 1], "ratio": [0.95, True]}
    result = powderline.run(recipe, tmp_path, execution_mode="subprocess")
    assert result["status"] == "ok"
    rows = result["refined_parameters"].set_index("parameter_name")
    assert "0:0:MD" in rows.index and float(rows.loc["0:0:MD", "esd"]) > 0
    disp = result["parameter_dispositions"].set_index("path").loc["payload.phases.LaB6.preferred_orientation.ratio"]
    assert disp["disposition"] == "varied" and float(disp["value"]) == pytest.approx(float(rows.loc["0:0:MD", "value"]))
    assert result["output_recipe_valid"] is True
    assert 0.9 < float(disp["value"]) < 1.1                      # a real, untextured standard: r stays near 1 (1.07(2) from 0.95)
