"""re/29 (P-48): easydiffraction (CrysPy) and March-Dollase -- the row is keyed to the linked structure (EB-97), the
pattern follows Dollase's correction up to CrysPy's constant normalisation (EB-98), and CrysFML ignores it."""
import copy
import json
from pathlib import Path

import numpy as np
import pytest

pytestmark = [pytest.mark.easydiffraction, pytest.mark.slow]
pytest.importorskip("easydiffraction")

import powderline  # noqa: E402
from intensity_ratio import dollase_correction, peak_areas  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
GOLDEN = REPO / "tests" / "data" / "ions" / "lab6_la3_over_la_gsasii.json"     # the resolved LaB6 reflections and 2theta
R, AXIS = 0.6, (0, 0, 1)


def _cryspy(po):
    r = json.loads((REPO / "tests" / "data" / "easydiffraction" / "native" / "lab6_crysfml_tch_calculation.json").read_text(encoding="utf-8-sig"))
    r["payload"]["refinement_controls"]["calculator"] = "cryspy"
    r["payload"]["instrument"]["broadening"]["peak_type"] = "cwl-pseudo-voigt"
    for k in ("asym_fcj_1", "asym_fcj_2"):
        r["payload"]["instrument"]["broadening"]["parameters"].pop(k, None)
    if po:
        r["payload"]["phases"]["LaB6"]["preferred_orientation"] = po
    return r


def test_cryspy_follows_dollase_up_to_its_normalisation(tmp_path):
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    from intensity_ratio import resolved
    all_centres = np.asarray(golden["two_theta"], dtype=float)
    keep = resolved(all_centres, min_separation=0.45)             # clean peaks only (see the gsasii test)
    centres = all_centres[keep]
    hkls = [tuple(int(c) for c in golden["hkl"][i]) for i in keep]
    assert len(keep) >= 6
    plain = powderline.run(_cryspy(None), tmp_path / "plain")
    po = {"model": "march_dollase", "hkl": list(AXIS), "ratio": [R, False, None, None], "march_random_fract": [0.0, False, None, None]}
    textured = powderline.run(_cryspy(po), tmp_path / "po")
    a0 = peak_areas(plain["fit_profile"]["two_theta"], plain["fit_profile"]["y_calc"], plain["fit_profile"]["y_bkg"], centres)
    a1 = peak_areas(textured["fit_profile"]["two_theta"], textured["fit_profile"]["y_calc"], textured["fit_profile"]["y_bkg"], centres)
    ratio = a1 / a0
    expected = np.array([dollase_correction(h, AXIS, R) for h in hkls])
    norm = ratio / expected                                      # CrysPy's factor is not volume-normalised (EB-98)
    assert np.all(np.isfinite(norm)) and np.std(norm) / np.mean(norm) < 2e-3, norm
    assert np.mean(norm) == pytest.approx(R ** 1.5, rel=2e-3)   # the constant is r^(3/2) for this convention
    assert textured["output_recipe"]["payload"]["phases"]["LaB6"]["preferred_orientation"] == po


def test_builder_keys_the_row_to_the_structure_and_keeps_the_axis_order():
    """EB-97's key, and a non-palindromic axis in the recipe's order (the cubic gate cannot see a permutation)."""
    from powderline.gateways.easydiffraction import schema as ed_schema
    from powderline.gateways.easydiffraction.native_builder import build_project, structure_name
    po = {"model": "march_dollase", "hkl": [1, 2, 3], "ratio": [R, False, None, None], "march_random_fract": [0.0, False, None, None]}
    build = build_project(ed_schema.validate_recipe(_cryspy(po)))
    rows = list(build.experiment.preferred_orientation)
    assert len(rows) == 1 and rows[0].structure_id.value == structure_name("LaB6")
    assert (rows[0].index_h.value, rows[0].index_k.value, rows[0].index_l.value) == (1, 2, 3)
    assert rows[0].march_r.value == R and rows[0].march_random_fract.value == 0.0
