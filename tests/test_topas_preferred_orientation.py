"""March-Dollase preferred orientation for TOPAS: the ``PO`` line, its limits, the read-back, and the Dollase gate.

The gate reads reflection lists TOPAS 6 wrote (``tests/data/topas/native/po/``): the textured/untextured
per-reflection ratio equals the March-Dollase correction in GSAS-II's convention
(``tests/intensity_ratio.dollase_correction``) within 0.2 % (measured: 1.4e-7). Engine-free: TOPAS is not run.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from pydantic import ValidationError

from intensity_ratio import dollase_correction
from powderline.gateways.topas import native_run, native_writer, schema

pytestmark = pytest.mark.topas_gen

REPO = Path(__file__).resolve().parents[1]
PO = REPO / "tests" / "data" / "topas" / "native" / "po"
LAB6 = REPO / "examples" / "example_LaB6" / "topas" / "input.json"
TEXTURED = REPO / "examples" / "example_LaB6_textured" / "topas" / "input.json"


def _lab6(ratio=None, hkl=(0, 0, 1)):
    r = json.loads(LAB6.read_text(encoding="utf-8"))
    if ratio is not None:
        r["payload"]["phases"]["LaB6"]["preferred_orientation"] = {"model": "march_dollase", "hkl": list(hkl),
                                                                   "ratio": ratio}
    return r


def _errors(exc):
    return [(tuple(e["loc"]), e["msg"]) for e in exc.value.errors()]


def _po_line(recipe):
    native = native_writer.render_native(schema.validate_recipe(recipe), "x")
    (line,) = [ln.strip() for ln in native.inp_text.splitlines() if ln.strip().startswith("PO(")]
    return line, native


# --- the writer ---


@pytest.mark.parametrize("ratio, hkl, line", [
    ([0.8, True, None, None], (0, 0, 1), "PO(p1_po_r, 0.8, , 0 0 1)"),
    ([0.8, True, 0.3, 1.5], (0, 0, 1), "PO(p1_po_r, 0.8 min 0.3 max 1.5, , 0 0 1)"),
    ([0.8, True, None, 1.5], (1, 1, 0), "PO(p1_po_r, 0.8 max 1.5, , 1 1 0)"),
    ([0.6, False, None, None], (1, 1, 1), "PO(!p1_po_r, 0.6, , 1 1 1)"),
    ([0.6, False, 0.3, 1.5], (0, 0, 1), "PO(!p1_po_r, 0.6, , 0 0 1)"),  # a fixed value carries no bounds
])
def test_po_line(ratio, hkl, line):
    assert _po_line(_lab6(ratio, hkl))[0] == line


def test_po_sits_in_the_str_after_the_sites_and_nothing_else_changes():
    line, native = _po_line(_lab6([0.8, True, None, None]))
    lines = native.inp_text.splitlines()
    i = lines.index(f"      {line}")
    assert lines[i - 1].strip().startswith("site B ") and lines[i + 1].strip().startswith("TCHZ_Peak_Type(")
    plain = native_writer.render_native(schema.validate_recipe(_lab6()), "x").inp_text.splitlines()
    out = 'out_record out_eqn = p1_po_r; out_fmt "p1_po_r,%.12g," out_fmt_err "%.12g\\n"'
    assert [ln for ln in lines if ln.strip() not in (line, out)] == plain


def test_po_ratio_limits_are_recorded():
    """TOPAS.INC's PO macro: min 0.0001 by default; max twice the current r plus 0.5, recomputed as r changes, so there
    is no fixed maximum to report."""
    _, native = _po_line(_lab6([0.8, True, None, None]))
    info = native.params["p1_po_r"]
    assert info.path == "payload.phases.LaB6.preferred_orientation.ratio" and info.refined
    assert info.limits == (0.0001, None) and info.limit_source == ("TOPAS", None)
    _, native = _po_line(_lab6([0.8, True, 0.3, 1.5]))
    assert native.params["p1_po_r"].limits == (0.3, 1.5)
    assert native.params["p1_po_r"].limit_source == ("stated", "stated")


def test_po_start_below_topas_default_minimum_is_refused():
    with pytest.raises(ValidationError) as exc:
        schema.validate_recipe(_lab6([0.00005, True, None, None]))
    assert any("below TOPAS's default minimum 0.0001" in msg for _, msg in _errors(exc)), _errors(exc)
    schema.validate_recipe(_lab6([0.00005, True, 0.00001, None]))  # a stated min replaces TOPAS's
    schema.validate_recipe(_lab6([0.00005, False, None, None]))    # TOPAS's limits act on refined values only


def test_textured_example_validates_and_writes_po():
    """The TOPAS leg of example_LaB6_textured (generate-only): r refined from 0.8 along [001]."""
    model = schema.validate_recipe(json.loads(TEXTURED.read_text(encoding="utf-8")))
    text = native_writer.render_native(model, "example_LaB6_textured").inp_text
    assert "      PO(p1_po_r, 0.8, , 0 0 1)\n" in text


# --- the gate: TOPAS's PO is GSAS-II's March-Dollase ---


def _intensities(path: Path) -> dict:
    rows = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            t = line.split()
            rows[(int(t[0]), int(t[1]), int(t[2]))] = float(t[7])  # column 8: I_after_scale_pks
    return rows


@pytest.mark.parametrize("name, axis, r", [
    ("po_r06_001", (0, 0, 1), 0.6),
    ("po_r1667_001", (0, 0, 1), 1 / 0.6),
    ("po_r06_111", (1, 1, 1), 0.6),
    ("po_r06_110", (1, 1, 0), 0.6),
])
def test_topas_po_equals_dollase_correction(name, axis, r):
    none = _intensities(PO / "po_none_p1_peaks.txt")
    textured = _intensities(PO / f"{name}_p1_peaks.txt")
    assert textured.keys() == none.keys() and len(none) == 53
    worst = max(abs(textured[k] / none[k] / dollase_correction(k, axis, r) - 1) for k in none)
    assert worst < 0.002, worst
    assert worst < 1e-6  # the recorded agreement (1.4e-7)


# --- the read-back ---


def test_refined_ratio_reaches_the_output_recipe(tmp_path):
    """TOPAS's refined r and ESD (TOPAS 6, textured example refined from 0.8; recorded with the ratio named
    ``po_r``) go to refined_parameters, the output recipe and the dispositions."""
    model = schema.validate_recipe(json.loads(TEXTURED.read_text(encoding="utf-8")))
    base = "po_free_reference"
    native = native_writer.render_native(model, base)
    text = (PO / f"{base}_results.csv").read_text(encoding="utf-8")
    assert "\npo_r," in text
    (tmp_path / f"{base}_results.csv").write_text(text.replace("\npo_r,", "\np1_po_r,"), encoding="utf-8")
    for suffix in ("_profile.txt", "_p1_peaks.txt"):
        shutil.copy(PO / f"{base}{suffix}", tmp_path / f"{base}{suffix}")
    r = native_run.build_result(model, native, tmp_path, [], elapsed=0.0)
    row = r["refined_parameters"].set_index("parameter_name").loc["p1_po_r"]
    assert row["value"] == pytest.approx(0.598183704626, rel=1e-12)
    assert row["esd"] == pytest.approx(0.00143991190868, rel=1e-12)
    assert row["category"] == "preferred_orientation" and row["phase_name"] == "LaB6"
    ratio = r["output_recipe"]["payload"]["phases"]["LaB6"]["preferred_orientation"]["ratio"]
    assert ratio[0] == pytest.approx(0.598184, abs=5e-7) and ratio[1:] == [True, None, None]
    assert r["output_recipe_valid"] is True
    disp = r["parameter_dispositions"].set_index("path").loc["payload.phases.LaB6.preferred_orientation.ratio"]
    assert disp["disposition"] == "varied"
    assert not [w for w in r["warnings"] if w["code"] == "topas_parameter_at_limit"
                and w["field_path"].endswith("preferred_orientation.ratio")]
