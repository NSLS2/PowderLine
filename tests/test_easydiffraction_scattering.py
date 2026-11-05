"""re/28 (P-47): easydiffraction and ionic scattering types -- the pinned CrysPy table, the builder handing the
CIF spelling through, and the gate: CrysPy's La3+/La per-reflection intensity ratios agree with GSAS-II's golden."""
import copy
import json
from pathlib import Path

import numpy as np
import pytest

pytestmark = [pytest.mark.easydiffraction, pytest.mark.slow]
pytest.importorskip("easydiffraction")

import powderline  # noqa: E402
from powderline.gateways.easydiffraction.scattering import CRYSPY_IONS  # noqa: E402
from intensity_ratio import peak_areas  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
GOLDEN = REPO / "tests" / "data" / "ions" / "lab6_la3_over_la_gsasii.json"


def test_table_is_the_installed_engines():
    import re
    from cryspy.A_functions_base.database import DATABASE
    engine = {k for k in DATABASE["Scattering amplitude"] if isinstance(k, str) and re.fullmatch(r"[A-Z][a-z]?[1-8][+-]", k)}
    assert engine == CRYSPY_IONS


def _cryspy_calc(ions):
    r = json.loads((REPO / "tests" / "data" / "easydiffraction" / "native" / "lab6_crysfml_tch_calculation.json").read_text(encoding="utf-8-sig"))
    r["payload"]["refinement_controls"]["calculator"] = "cryspy"
    r["payload"]["instrument"]["broadening"]["peak_type"] = "cwl-pseudo-voigt"
    for k in ("asym_fcj_1", "asym_fcj_2"):
        r["payload"]["instrument"]["broadening"]["parameters"].pop(k, None)
    if ions:
        r["payload"]["phases"]["LaB6"]["scattering_types"] = ions
    return r


def test_cryspy_ion_ratios_agree_with_gsasii_within_one_percent(tmp_path):
    """The gate (P-47): the same ion changes the same reflections by the same factor in both engines."""
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    neutral = powderline.run(_cryspy_calc(None), tmp_path / "n")
    ionic = powderline.run(_cryspy_calc({"La": "La3+"}), tmp_path / "i")
    centres = np.asarray(golden["two_theta"], dtype=float)
    an = peak_areas(neutral["fit_profile"]["two_theta"], neutral["fit_profile"]["y_calc"], neutral["fit_profile"]["y_bkg"], centres)
    ai = peak_areas(ionic["fit_profile"]["two_theta"], ionic["fit_profile"]["y_calc"], ionic["fit_profile"]["y_bkg"], centres)
    ratio = ai / an
    assert np.all(np.isfinite(ratio)) and len(ratio) >= 8
    assert ratio[0] < 0.99                                   # the (100) reflection: the ion is in effect, not ignored
    assert np.allclose(ratio, golden["ratio_ion_over_neutral"], rtol=0.005, atol=0.0), (ratio, golden["ratio_ion_over_neutral"])
    assert ionic["output_recipe"]["payload"]["phases"]["LaB6"]["scattering_types"] == {"La": "La3+"}
