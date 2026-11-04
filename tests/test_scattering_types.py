"""re/28 (P-47, A63): ionic scattering types -- the core building block and the three engine rules (engine-free)."""
import copy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from powderline import schema_core
from powderline.gateways.easydiffraction import schema as ed_schema
from powderline.gateways.gsasii import schema as gsasii_schema
from powderline.gateways.gsasii.scattering import GSASII_IONS, gsasii_type
from powderline.gateways.easydiffraction.scattering import CRYSPY_IONS
from powderline.gateways.topas import schema as topas_schema

pytestmark = pytest.mark.core
EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def _lab6(engine_dir=None):
    path = EXAMPLES / "example_LaB6" / (f"{engine_dir}/input.json" if engine_dir else "input.json")
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _errors(exc):
    return [(tuple(e["loc"]), e["msg"]) for e in exc.value.errors()]


# --- the core building block ---

@pytest.mark.parametrize("symbol, parts", [("La3+", ("La", 3)), ("O2-", ("O", -2)), ("Fe2+", ("Fe", 2)), ("Cl1-", ("Cl", -1))])
def test_scattering_type_parts_reads_the_cif_spelling(symbol, parts):
    assert schema_core.scattering_type_parts(symbol) == parts


@pytest.mark.parametrize("symbol, fragment", [
    ("Fe+3", "write the ion as element, charge, sign: 'Fe3+'"),      # the engine spelling
    ("Fe", "is the neutral atom: leave the atom out"),
    ("Fe3", "not of the form element, charge 1-8, sign"),
    ("Fe9+", "not of the form element, charge 1-8, sign"),
    ("Xx3+", "'Xx' is not a known element symbol"),
    ("fe3+", "not of the form"),
])
def test_scattering_type_parts_refuses_other_spellings(symbol, fragment):
    import re
    with pytest.raises(ValueError, match=re.escape(fragment)):
        schema_core.scattering_type_parts(symbol)


def test_element_stays_neutral_in_core_and_points_at_scattering_types():
    r = _lab6(); r["payload"]["phases"]["LaB6"]["atoms"]["La"]["element"] = "La3+"
    with pytest.raises(ValidationError) as exc:
        gsasii_schema.validate_recipe(r)
    assert any("scattering_types" in msg and "neutral" in msg for _, msg in _errors(exc))


def test_gsasii_type_spelling_and_table():
    assert gsasii_type("La3+") == "La+3" and gsasii_type("O2-") == "O-2" and gsasii_type("B") == "B"
    assert len(GSASII_IONS) == 114 and {"La3+", "O2-", "W6+", "Li1+", "Mg2+", "Fe3+"} <= GSASII_IONS
    assert not any(s.startswith("B") and len(s) == 3 for s in GSASII_IONS)   # no boron ion
    assert len(CRYSPY_IONS) == 111 and "O2-" not in CRYSPY_IONS and "O1-" in CRYSPY_IONS
    assert GSASII_IONS - CRYSPY_IONS == {"D1-", "T1-", "O2-"}


# --- gsasii ---

def test_gsasii_accepts_an_ion_the_engine_has_and_keeps_it_in_the_dump():
    r = _lab6(); r["payload"]["phases"]["LaB6"]["scattering_types"] = {"La": "La3+"}
    model = gsasii_schema.validate_recipe(r)
    assert model.payload.phases["LaB6"].scattering_types == {"La": "La3+"}
    assert model.payload.phases["LaB6"].atoms["La"].element == "La"
    dumped = model.model_dump(mode="json")
    assert dumped["payload"]["phases"]["LaB6"]["scattering_types"] == {"La": "La3+"}
    plain = gsasii_schema.validate_recipe(_lab6()).model_dump(mode="json")
    assert "scattering_types" not in plain["payload"]["phases"]["LaB6"]   # left out stays left out


@pytest.mark.parametrize("types, loc_tail, fragment", [
    ({"La": "La+3"}, ("La",), "write the ion as element, charge, sign: 'La3+'"),
    ({"La": "Fe3+"}, ("La",), "not an ion of La's element 'La'"),
    ({"Xe": "La3+"}, ("Xe",), "not an atom of this phase"),
    ({"B": "B3+"}, ("B",), "no ionic form for B: use the neutral atom"),
    ({"La": "La2+"}, ("La",), "it has La3+ for La"),
    ({"La": "La"}, ("La",), "is the neutral atom"),
])
def test_gsasii_refuses_what_it_cannot_compute(types, loc_tail, fragment):
    r = _lab6(); r["payload"]["phases"]["LaB6"]["scattering_types"] = types
    with pytest.raises(ValidationError) as exc:
        gsasii_schema.validate_recipe(r)
    errs = _errors(exc)
    assert any(loc[-len(loc_tail):] == loc_tail and "scattering_types" in loc and fragment in msg for loc, msg in errs), errs


def test_gsasii_scattering_types_null_is_refused():
    r = _lab6(); r["payload"]["phases"]["LaB6"]["scattering_types"] = None
    with pytest.raises(ValidationError, match="must not be null"):
        gsasii_schema.validate_recipe(r)


# --- easydiffraction ---

def test_easydiffraction_cryspy_accepts_and_crysfml_refuses():
    r = _lab6("easydiffraction"); r["payload"]["phases"]["LaB6"]["scattering_types"] = {"La": "La3+"}
    assert r["payload"]["refinement_controls"]["calculator"] == "crysfml"
    with pytest.raises(ValidationError) as exc:
        ed_schema.validate_recipe(r)
    assert any("crysfml calculator computes neutral atoms only" in msg for _, msg in _errors(exc))
    r2 = copy.deepcopy(r); r2["payload"]["refinement_controls"]["calculator"] = "cryspy"
    r2["payload"]["instrument"]["broadening"]["peak_type"] = "cwl-pseudo-voigt"
    for k in ("asym_fcj_1", "asym_fcj_2"):
        r2["payload"]["instrument"]["broadening"]["parameters"].pop(k, None)
    model = ed_schema.validate_recipe(r2)
    assert model.payload.phases["LaB6"].scattering_types == {"La": "La3+"}


def test_easydiffraction_refuses_an_ion_cryspy_lacks():
    r = _lab6("easydiffraction"); r["payload"]["refinement_controls"]["calculator"] = "cryspy"
    r["payload"]["instrument"]["broadening"]["peak_type"] = "cwl-pseudo-voigt"
    for k in ("asym_fcj_1", "asym_fcj_2"):
        r["payload"]["instrument"]["broadening"]["parameters"].pop(k, None)
    r["payload"]["phases"]["LaB6"]["atoms"]["O"] = dict(r["payload"]["phases"]["LaB6"]["atoms"]["B"], element="O")
    r["payload"]["phases"]["LaB6"]["scattering_types"] = {"O": "O2-"}
    with pytest.raises(ValidationError) as exc:
        ed_schema.validate_recipe(r)
    assert any("easydiffraction 0.21.1 (CrysPy) has no X-ray form factor for 'O2-'; it has O1- for O" in msg for _, msg in _errors(exc))


# --- topas (B1) ---

def test_topas_refuses_ions_in_1_0_0_naming_the_topas_item():
    r = _lab6("topas"); r["payload"]["phases"]["LaB6"]["scattering_types"] = {"La": "La3+"}
    with pytest.raises(ValidationError) as exc:
        topas_schema.validate_recipe(r)
    errs = _errors(exc)
    assert any("not yet available for TOPAS" in msg and "verified on a TOPAS machine" in msg for _, msg in errs), errs
    plain = topas_schema.validate_recipe(_lab6("topas")).model_dump(mode="json")
    assert "scattering_types" not in plain["payload"]["phases"]["LaB6"]
