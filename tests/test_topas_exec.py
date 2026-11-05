"""TOPAS execution on the TOPAS machine: ``powderline.run()`` against a real ``tc.exe`` (marker ``topas_exec``).

Skipped unless ``POWDERLINE_TOPAS_DIR`` (the folder holding ``tc.exe``) and ``POWDERLINE_TOPAS_VERSION`` (the
installed TOPAS major version, e.g. ``6``) are set. On the TOPAS machine (PowerShell)::

    $env:POWDERLINE_TOPAS_DIR='C:\\TOPAS6'; $env:POWDERLINE_TOPAS_VERSION='6'; pixi run --frozen test-topas

The ``test-topas`` task selects ``topas_gen or topas_exec``, so the core guard (``tests/conftest.py``) is off
and tc.exe may run. What is checked:

- every golden fixture (``tests/test_topas_native_golden.py`` ``FIXTURES``): each file TOPAS writes equals the
  committed golden for the installed version (``golden/<engine_version>/``), text-identical up to line ends;
- the ionic example (``examples/example_LaB6_ionic/topas/``): calculated with ``iters 0`` with and without
  La3+, the per-reflection La+3/La ratio equals GSAS-II's within 1 %;
- the textured example (``examples/example_LaB6_textured/topas/``): the refined March-Dollase r is within
  0.01 of the programmed 0.6.
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path

import pytest

import powderline
from test_topas_native_golden import FIXTURES, GOLDENS, NATIVE, _base

TOPAS_DIR = os.environ.get("POWDERLINE_TOPAS_DIR")
TOPAS_VERSION = os.environ.get("POWDERLINE_TOPAS_VERSION")

pytestmark = [
    pytest.mark.topas_exec,
    pytest.mark.skipif(not (TOPAS_DIR and TOPAS_VERSION),
                       reason="TOPAS execution needs POWDERLINE_TOPAS_DIR (the folder with tc.exe) and "
                              "POWDERLINE_TOPAS_VERSION (the installed TOPAS major version); set both on the TOPAS "
                              "machine"),
]

REPO = Path(__file__).resolve().parents[1]
GSASII_GATE = REPO / "tests" / "data" / "ions" / "lab6_la3_over_la_gsasii.json"
IONIC = REPO / "examples" / "example_LaB6_ionic" / "topas" / "input.json"
TEXTURED = REPO / "examples" / "example_LaB6_textured" / "topas" / "input.json"


def _run(recipe: dict, out: Path) -> dict:
    return powderline.run(recipe, str(out), topas_dir=TOPAS_DIR, topas_version=TOPAS_VERSION)


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


@pytest.mark.parametrize("fixture", FIXTURES)
def test_fixture_reproduces_its_goldens(fixture, tmp_path):
    recipe = json.loads((NATIVE / f"{fixture}.json").read_text(encoding="utf-8"))
    if recipe["engine_version"] != TOPAS_VERSION:
        pytest.skip(f"{fixture} is written for TOPAS {recipe['engine_version']}, TOPAS {TOPAS_VERSION} is installed")
    golden = GOLDENS / recipe["engine_version"]
    out = tmp_path / _base(fixture) / "output"  # base name <fixture>__snapped, as the goldens
    result = _run(recipe, out)
    assert result["status"] == "ok"
    files = sorted(golden.glob(f"{_base(fixture)}*"))
    assert files, f"no goldens for {fixture} in {golden}"
    different = [f.name for f in files if not (out / f.name).is_file() or _text(out / f.name) != _text(f)]
    assert not different, f"{fixture}: differs from the TOPAS {TOPAS_VERSION} goldens: {different}"


def _fixed(node):
    """A copy with every refine flag false (a simulation, ``iters 0``, refines nothing)."""
    if isinstance(node, dict):
        return {k: (False if k == "refine_flag" else _fixed(v)) for k, v in node.items()}
    if isinstance(node, list):
        if len(node) == 4 and isinstance(node[1], bool) and not isinstance(node[0], (list, dict)):
            return [node[0], False, node[2], node[3]]
        return [_fixed(v) for v in node]
    return node


def _intensities(result: dict) -> dict:
    rows = result["peak_list_data"]["LaB6"]
    return {(int(h), int(k), int(l)): float(i)
            for h, k, l, i in zip(rows["h"], rows["k"], rows["l"], rows["I_after_scale_pks"])}


def test_ionic_example_la3_over_la_matches_gsasii(tmp_path):
    ionic = json.loads(IONIC.read_text(encoding="utf-8"))
    ionic["payload"]["refinement_controls"]["iters"] = 0
    ionic["payload"] = _fixed(ionic["payload"])
    neutral = copy.deepcopy(ionic)
    del neutral["payload"]["phases"]["LaB6"]["scattering_types"]
    with_ion = _intensities(_run(ionic, tmp_path / "ion" / "output"))
    without = _intensities(_run(neutral, tmp_path / "neutral" / "output"))
    gate = json.loads(GSASII_GATE.read_text(encoding="utf-8"))
    worst = max(abs(with_ion[key] / without[key] / expected - 1)
                for key, expected in ((tuple(int(c) for c in hkl), r)
                                      for hkl, r in zip(gate["hkl"], gate["ratio_ion_over_neutral"])))
    assert worst < 0.01, worst


def test_textured_example_recovers_r(tmp_path):
    result = _run(json.loads(TEXTURED.read_text(encoding="utf-8")), tmp_path / "example_LaB6_textured" / "output")
    assert result["status"] == "ok"
    ratio = result["output_recipe"]["payload"]["phases"]["LaB6"]["preferred_orientation"]["ratio"][0]
    assert abs(ratio - 0.6) < 0.01, ratio
    rows = result["refined_parameters"].set_index("parameter_name")
    assert rows.loc["p1_po_r", "value"] == pytest.approx(ratio) and rows.loc["p1_po_r", "esd"] > 0
