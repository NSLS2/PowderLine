"""re/28 (P-47): GSAS-II and ionic scattering types -- the pinned table, the spelling GSAS-II reads, the frozen
builder writing it (R35), and the gate golden: La3+/La per-reflection intensity ratios of the LaB6 calculation."""
import json
import re
from pathlib import Path

import numpy as np
import pytest

pytestmark = [pytest.mark.gsasii, pytest.mark.slow]
pytest.importorskip("GSASII.GSASIIscriptable")

import powderline  # noqa: E402
from powderline.gateways.gsasii.scattering import GSASII_IONS, gsasii_type  # noqa: E402
from intensity_ratio import peak_areas, resolved  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
GOLDEN = REPO / "tests" / "data" / "ions" / "lab6_la3_over_la_gsasii.json"


def test_table_is_the_installed_engines():
    from GSASII import atmdata
    engine = {f"{m.group(1)}{m.group(3)}{m.group(2)}" for m in
              (re.fullmatch(r"([A-Z][a-z]?)([+-])(\d)", k) for k in atmdata.XrayFF) if m}
    assert engine == GSASII_IONS


def test_gsasii_reads_the_translated_spelling_as_the_ion_and_the_recipe_spelling_as_hydrogen():
    """EB-94: the reason the translation is the gateway's."""
    from GSASII import GSASIIElem as G2elem
    assert G2elem.GetAtomInfo(gsasii_type("La3+"))["Z"] == 57
    assert G2elem.GetAtomInfo("La3+")["Z"] == 1          # hydrogen, silently


def _calc(recipe_path, ions):
    recipe = json.loads((REPO / "examples" / "example_LaB6_simulation" / "input.json").read_text(encoding="utf-8-sig"))
    if ions:
        recipe["payload"]["phases"]["LaB6"]["scattering_types"] = ions
    return recipe


def test_frozen_builder_writes_the_ion_and_the_gate_golden_holds(tmp_path):
    """R35: the GSAS-II project's atom type is 'La+3' for a stated 'La3+'; the output recipe keeps the recipe
    spelling; and the La3+/La per-reflection intensity ratios equal the committed golden (the gate's GSAS-II side)."""
    from GSASII import GSASIIscriptable as G2sc
    neutral = powderline.run(_calc(None, None), tmp_path / "n", execution_mode="subprocess")
    ionic = powderline.run(_calc(None, {"La": "La3+"}), tmp_path / "i", execution_mode="subprocess")
    proj = G2sc.G2Project(gpxfile=str(tmp_path / "i" / "dummy.gpx"))
    types = {a.label: a.type for a in proj.phases()[0].atoms()}
    assert types["La"] == "La+3" and types["B"] == "B"
    assert ionic["output_recipe"]["payload"]["phases"]["LaB6"]["scattering_types"] == {"La": "La3+"}
    assert ionic["output_recipe"]["payload"]["phases"]["LaB6"]["atoms"]["La"]["element"] == "La"
    peaks = neutral["peak_list_data"]["LaB6"]
    centres = np.asarray(peaks["2theta"], dtype=float)
    keep = [i for i in resolved(centres) if 1.5 < centres[i] < 14.5]
    an = peak_areas(neutral["fit_profile"]["two_theta"], neutral["fit_profile"]["y_calc"], neutral["fit_profile"]["y_bkg"], centres[keep])
    ai = peak_areas(ionic["fit_profile"]["two_theta"], ionic["fit_profile"]["y_calc"], ionic["fit_profile"]["y_bkg"], centres[keep])
    ratio = ai / an
    assert np.all(np.isfinite(ratio)) and len(ratio) >= 8
    assert ratio[0] < 0.99                                  # La3+ scatters less than La at the lowest angle: a real change
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert [round(float(c), 4) for c in centres[keep]] == golden["two_theta"]
    assert np.allclose(ratio, golden["ratio_ion_over_neutral"], rtol=1e-6, atol=1e-6)
