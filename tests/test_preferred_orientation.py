"""re/29 (P-48): March-Dollase preferred orientation -- the core block and the three engine rules (engine-free)."""
import copy
import json
from pathlib import Path

import pandas as pd
import pytest
from pydantic import ValidationError

from powderline.gateways.easydiffraction import schema as ed_schema
from powderline.gateways.gsasii import paths
from powderline.gateways.gsasii import schema as gsasii_schema
from powderline.gateways.topas import schema as topas_schema

pytestmark = pytest.mark.core
EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def _lab6(engine_dir=None):
    path = EXAMPLES / "example_LaB6" / (f"{engine_dir}/input.json" if engine_dir else "input.json")
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _errors(exc):
    return [(tuple(e["loc"]), e["msg"]) for e in exc.value.errors()]


PO_GSASII = {"model": "march_dollase", "hkl": [0, 0, 1], "ratio": [0.6, True]}
PO_ED = {"model": "march_dollase", "hkl": [0, 0, 1], "ratio": [0.6, True, 0.1, 5.0], "march_random_fract": [0.0, False, None, None]}


def _ed_cryspy(po):
    r = _lab6("easydiffraction"); r["payload"]["refinement_controls"]["calculator"] = "cryspy"
    r["payload"]["instrument"]["broadening"]["peak_type"] = "cwl-pseudo-voigt"
    for k in ("asym_fcj_1", "asym_fcj_2"):
        r["payload"]["instrument"]["broadening"]["parameters"].pop(k, None)
    if po is not None:
        r["payload"]["phases"]["LaB6"]["preferred_orientation"] = po
    return r


# --- gsasii ---

def test_gsasii_accepts_the_block_and_omits_it_when_absent():
    r = _lab6(); r["payload"]["phases"]["LaB6"]["preferred_orientation"] = PO_GSASII
    model = gsasii_schema.validate_recipe(r)
    po = model.payload.phases["LaB6"].preferred_orientation
    assert po.model == "march_dollase" and tuple(po.hkl) == (0, 0, 1) and po.ratio.value == 0.6 and po.ratio.refine_flag
    dumped = model.model_dump(mode="json")["payload"]["phases"]["LaB6"]
    assert dumped["preferred_orientation"] == {"model": "march_dollase", "hkl": [0, 0, 1], "ratio": [0.6, True]}
    assert "preferred_orientation" not in gsasii_schema.validate_recipe(_lab6()).model_dump(mode="json")["payload"]["phases"]["LaB6"]


@pytest.mark.parametrize("po, fragment", [
    (dict(PO_GSASII, hkl=[0, 0, 0]), "hkl must not be (0, 0, 0)"),
    (dict(PO_GSASII, ratio=[0.0, True]), "ratio must be > 0"),
    (dict(PO_GSASII, ratio=[-1.0, False]), "ratio must be > 0"),
    (dict(PO_GSASII, model="spherical_harmonics"), "march_dollase"),
    (dict(PO_GSASII, ratio=[0.6, True, 0.1, 5.0]), "expected [value, refine_flag]"),
    (dict(PO_GSASII, march_random_fract=[0.0, False]), "Extra inputs are not permitted"),
    (None, "must not be null"),
])
def test_gsasii_refuses_a_bad_block(po, fragment):
    r = _lab6(); r["payload"]["phases"]["LaB6"]["preferred_orientation"] = po
    with pytest.raises(ValidationError) as exc:
        gsasii_schema.validate_recipe(r)
    assert any(fragment in msg for _, msg in _errors(exc)), _errors(exc)


def test_gsasii_ratio_flag_counts_as_a_requested_parameter_and_md_maps_to_its_path():
    from powderline.schema_core import parameters_requested
    r = _lab6(); r["payload"]["phases"]["LaB6"]["preferred_orientation"] = PO_GSASII
    model = gsasii_schema.validate_recipe(r)
    assert parameters_requested(model) == parameters_requested(gsasii_schema.validate_recipe(_lab6())) + 1
    rows = pd.DataFrame([{"parameter_name": "0:0:MD", "descriptive_name": "phase_0_histogram_0_MD", "phase_name": "LaB6",
                          "phase_idx": 0, "atom_name": "", "atom_idx": None, "value": 0.58, "esd": 0.004, "category": "other"}])
    refined, not_varied, _, problems = paths.refined_by_path(model, {"refined_parameters": rows, "unit_cell_data": {}, "spf_peaks": pd.DataFrame()})
    assert not problems and refined["payload.phases.LaB6.preferred_orientation.ratio"] == (0.58, 0.004)
    assert "payload.phases.LaB6.preferred_orientation.ratio" not in not_varied


# --- easydiffraction ---

def test_easydiffraction_cryspy_accepts_and_requires_the_random_fraction():
    model = ed_schema.validate_recipe(_ed_cryspy(PO_ED))
    po = model.payload.phases["LaB6"].preferred_orientation
    assert po.ratio.value == 0.6 and po.march_random_fract.value == 0.0 and po.ratio.max == 5.0
    with pytest.raises(ValidationError) as exc:
        ed_schema.validate_recipe(_ed_cryspy({k: v for k, v in PO_ED.items() if k != "march_random_fract"}))
    assert any("march_random_fract" in "/".join(map(str, loc)) and "required" in msg.lower() for loc, msg in _errors(exc)), _errors(exc)
    with pytest.raises(ValidationError) as exc:
        ed_schema.validate_recipe(_ed_cryspy(dict(PO_ED, march_random_fract=[1.5, False, None, None])))
    assert any("within [0, 1]" in msg for _, msg in _errors(exc))
    assert "preferred_orientation" not in ed_schema.validate_recipe(_ed_cryspy(None)).model_dump(mode="json")["payload"]["phases"]["LaB6"]


def test_easydiffraction_crysfml_refuses_preferred_orientation():
    r = _lab6("easydiffraction"); r["payload"]["phases"]["LaB6"]["preferred_orientation"] = PO_ED
    assert r["payload"]["refinement_controls"]["calculator"] == "crysfml"
    with pytest.raises(ValidationError) as exc:
        ed_schema.validate_recipe(r)
    assert any("crysfml calculator ignores preferred orientation" in msg for _, msg in _errors(exc))


# --- topas (B1) ---

def test_topas_refuses_preferred_orientation_in_1_0_0():
    # the block is typed (MarchDollase, bounded) so a malformed one is told what it is; a well-formed one is refused
    r = _lab6("topas"); r["payload"]["phases"]["LaB6"]["preferred_orientation"] = {k: v for k, v in PO_ED.items() if k != "march_random_fract"}
    with pytest.raises(ValidationError) as exc:
        topas_schema.validate_recipe(r)
    assert any("not yet available for TOPAS" in msg and "PO(...)" in msg for _, msg in _errors(exc))
    assert "preferred_orientation" not in topas_schema.validate_recipe(_lab6("topas")).model_dump(mode="json")["payload"]["phases"]["LaB6"]


@pytest.mark.parametrize("po, fragment", [
    (dict(PO_ED, ratio=[0.6, True, 0.0, 5.0]), "ratio min 0"),
    (dict(PO_ED, ratio=[0.6, True, -1.0, None]), "ratio min -1"),
    (dict(PO_ED, march_random_fract=[0.5, True, -1.0, 2.0]), "march_random_fract min -1"),
    (dict(PO_ED, march_random_fract=[0.5, True, 0.0, 2.0]), "march_random_fract max 2"),
])
def test_easydiffraction_refuses_bounds_the_engine_refuses(po, fragment):
    """A stated bound easydiffraction's own RangeValidators would refuse (march_r > 0, fract in [0, 1]) is a validation
    error here, not a run-time engine failure (EB-71); null bounds stay open."""
    with pytest.raises(ValidationError) as exc:
        ed_schema.validate_recipe(_ed_cryspy(po))
    assert any(fragment in msg and "physical limit" in msg for _, msg in _errors(exc)), _errors(exc)
    ed_schema.validate_recipe(_ed_cryspy(dict(PO_ED, ratio=[0.6, True, None, None])))   # open bounds are fine
