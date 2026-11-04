"""``scripts/cross_engine_comparison.py`` in ``--no-run`` mode (A173; re/10 §1 item 5).

The docs page includes the generated table, so the script must rebuild it from
committed files alone: the TOPAS 6 and easydiffraction goldens plus the JSON
record of the last GSAS-II run. No engine is run here. Skipped where a golden
or the committed record is absent.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.core  # reads committed goldens in --no-run mode; imports no engine

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "cross_engine_comparison.py"
RECORD = ROOT / "docs" / "_generated" / "cross_engine_comparison.json"
GOLDENS = [
    ROOT / "tests" / "data" / "topas" / "native" / "golden" / "lab6_rietveld__snapped_results.csv",
    ROOT / "tests" / "data" / "topas" / "native" / "golden" / "drx33_rietveld__snapped_results.csv",
    ROOT / "tests" / "data" / "easydiffraction" / "native" / "golden" / "lab6_crysfml_tch.json",
    ROOT / "tests" / "data" / "easydiffraction" / "native" / "golden" / "lab6_cryspy_pv.json",
    ROOT / "tests" / "data" / "easydiffraction" / "native" / "golden" / "drx33_two_phase_cryspy.json",
]


@pytest.fixture(scope="module")
def generated(tmp_path_factory):
    missing = [p for p in (*GOLDENS, RECORD) if not p.exists()]
    if missing:
        pytest.skip("committed inputs absent: " + ", ".join(str(p.relative_to(ROOT)) for p in missing))
    out = tmp_path_factory.mktemp("cross_engine")
    proc = subprocess.run([sys.executable, str(SCRIPT), "--no-run", "--out-dir", str(out), "--record", str(RECORD)],
                          cwd=ROOT, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    return ((out / "cross_engine_comparison.md").read_text(encoding="utf-8"),
            json.loads((out / "cross_engine_comparison.json").read_text(encoding="utf-8")))


def test_table_has_both_cases_and_all_engines(generated):
    md, data = generated
    assert "### LaB6" in md and "### DRX_33" in md
    for case in ("LaB6", "DRX_33"):
        engines = {row["engine"] for row in data["cases"][case]["rows"]}
        assert engines == {"GSAS-II", "TOPAS", "easydiffraction"}, (case, engines)
    assert "TOPAS 6 (golden)" in md  # the TOPAS rows are labelled as goldens
    assert "Versions and dates" in md


def test_statistics_are_uniform_over_the_same_points(generated):
    """A125/A149: one n_points for every row of a case; rwp/r_exp/gof present on every row."""
    _, data = generated
    for case, block in data["cases"].items():
        assert len({row["n_points"] for row in block["rows"]}) == 1, case
        for row in block["rows"]:
            assert all(isinstance(row[k], float) for k in ("rwp", "r_exp", "gof")), (case, row["engine"])
            assert isinstance(row["parameters_varied"], int)


def test_no_run_mode_imports_no_engine(generated):
    """The GSAS-II rows come from the record: their source says 'run', the others say 'golden'."""
    _, data = generated
    assert data["generated"]["no_run"] is True
    for block in data["cases"].values():
        for row in block["rows"]:
            assert row["source"] == "run" if row["engine"] == "GSAS-II" else row["source"].startswith("golden")


def test_missing_record_is_an_error(tmp_path):
    """An explicit --record that does not exist is a missing input: exit 1, no fallback to the committed one."""
    proc = subprocess.run([sys.executable, str(SCRIPT), "--no-run", "--out-dir", str(tmp_path / "out"),
                           "--record", str(tmp_path / "absent.json")], cwd=ROOT, capture_output=True, text=True)
    assert proc.returncode == 1
    assert "JSON record not found" in proc.stderr
    assert not (tmp_path / "out").exists()
