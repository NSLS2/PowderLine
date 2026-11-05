"""Ionic scattering types for TOPAS: the table, the schema rule, the ``occ`` spelling, and the gate against GSAS-II.

The gate reads two reflection lists TOPAS 6 wrote (``tests/data/topas/native/ions/``): the per-reflection
La3+/La intensity ratio must agree with GSAS-II's (``tests/data/ions/lab6_la3_over_la_gsasii.json``) within 1 %.
Engine-free: TOPAS is not run here.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from powderline.gateways.gsasii.scattering import GSASII_IONS
from powderline.gateways.topas import native_writer, schema
from powderline.gateways.topas.scattering import TOPAS_IONS, topas_type

pytestmark = pytest.mark.topas_gen

REPO = Path(__file__).resolve().parents[1]
IONS = REPO / "tests" / "data" / "topas" / "native" / "ions"
GSASII_GATE = REPO / "tests" / "data" / "ions" / "lab6_la3_over_la_gsasii.json"
LAB6 = REPO / "examples" / "example_LaB6" / "topas" / "input.json"
IONIC = REPO / "examples" / "example_LaB6_ionic" / "topas" / "input.json"


def _lab6():
    return json.loads(LAB6.read_text(encoding="utf-8"))


def _errors(exc):
    return [(tuple(e["loc"]), e["msg"]) for e in exc.value.errors()]


def _intensities(path: Path) -> dict:
    """``{(h, k, l): I_after_scale_pks}`` (column 8) of a reflection list TOPAS wrote."""
    rows = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            t = line.split()
            rows[(int(t[0]), int(t[1]), int(t[2]))] = float(t[7])
    return rows


# --- the table ---


def test_topas_ions_are_atmscat_113():
    """TOPAS 6's ATMSCAT.CPP holds GSAS-II 5.7.9's ions without T1- (measured 2026-11-04)."""
    assert len(TOPAS_IONS) == 113
    assert TOPAS_IONS == GSASII_IONS - {"T1-"}


@pytest.mark.parametrize("symbol, topas", [("La3+", "La+3"), ("O2-", "O-2"), ("Cl1-", "Cl-1"), ("La", "La")])
def test_topas_type_spelling(symbol, topas):
    assert topas_type(symbol) == topas


# --- the schema rule ---


def _with_oxygen(types):
    r = _lab6()
    phase = r["payload"]["phases"]["LaB6"]
    phase["atoms"]["O"] = dict(copy.deepcopy(phase["atoms"]["B"]), element="O")
    phase["scattering_types"] = types
    return r


def test_o2_minus_is_accepted_for_topas():
    """O2- is in TOPAS's table (CrysPy has only O1-, so the easydiffraction schema refuses it)."""
    model = schema.validate_recipe(_with_oxygen({"O": "O2-"}))
    assert model.payload.phases["LaB6"].scattering_types == {"O": "O2-"}


def test_the_topas_spelling_is_refused_with_the_cif_hint():
    r = _lab6(); r["payload"]["phases"]["LaB6"]["scattering_types"] = {"La": "La+3"}
    with pytest.raises(ValidationError) as exc:
        schema.validate_recipe(r)
    assert any("write the ion as element, charge, sign: 'La3+'" in msg for _, msg in _errors(exc)), _errors(exc)


def test_an_ion_topas_lacks_is_refused():
    r = _lab6(); r["payload"]["phases"]["LaB6"]["scattering_types"] = {"B": "B3+"}
    with pytest.raises(ValidationError) as exc:
        schema.validate_recipe(r)
    errs = _errors(exc)
    assert any(loc[-2:] == ("scattering_types", "B") and "TOPAS 6 has no X-ray form factor for 'B3+'" in msg
               and "no ionic form for B" in msg for loc, msg in errs), errs
    r["payload"]["phases"]["LaB6"]["scattering_types"] = {"La": "La2+"}
    with pytest.raises(ValidationError) as exc:
        schema.validate_recipe(r)
    assert any("it has La3+ for La" in msg for _, msg in _errors(exc)), _errors(exc)


# --- the writer ---


def test_occ_carries_the_topas_spelling():
    r = _lab6(); r["payload"]["phases"]["LaB6"]["scattering_types"] = {"La": "La3+"}
    text = native_writer.render_native(schema.validate_recipe(r), "x").inp_text
    assert "occ La+3 !p1_a1_occ 1" in text
    assert "occ B !p1_a2_occ 1" in text  # an atom left out stays neutral
    plain = native_writer.render_native(schema.validate_recipe(_lab6()), "x").inp_text
    assert text.replace("occ La+3 ", "occ La ") == plain  # nothing else changes


def test_ionic_example_validates_and_writes_la_plus_3():
    """The TOPAS leg of example_LaB6_ionic (generate-only)."""
    model = schema.validate_recipe(json.loads(IONIC.read_text(encoding="utf-8")))
    assert model.payload.phases["LaB6"].scattering_types == {"La": "La3+"}
    assert "occ La+3 " in native_writer.render_native(model, "example_LaB6_ionic").inp_text


# --- the gate: TOPAS's La+3/La against GSAS-II's La3+/La ---


def test_topas_la3_over_la_matches_gsasii_within_1_percent():
    """Per reflection, I(La+3)/I(La) from TOPAS's reflection lists equals GSAS-II's ratio within 1 % (measured:
    0.069 %); an ion-blind calculator would be 1.5 % off at (100)."""
    gate = json.loads(GSASII_GATE.read_text(encoding="utf-8"))
    neutral = _intensities(IONS / "ion_La_p1_peaks.txt")
    ionic = _intensities(IONS / "ion_Lap3_p1_peaks.txt")
    assert len(gate["hkl"]) == 12
    worst = 0.0
    for hkl, expected in zip(gate["hkl"], gate["ratio_ion_over_neutral"]):
        key = tuple(int(c) for c in hkl)
        worst = max(worst, abs(ionic[key] / neutral[key] / expected - 1))
    assert worst < 0.01, worst
    assert worst < 1e-3  # the recorded agreement (6.9e-4): a regression in the files shows here first
