"""re/30 (ledger row R38): a failed GSAS-II run leaves GSAS-II's own files and ``failure.json`` only -- the checks in
``fit_report`` now run before the executor writes any result table -- and a reused directory holds one run's results."""
import json
from pathlib import Path

import pytest

pytestmark = [pytest.mark.gsasii, pytest.mark.slow]
pytest.importorskip("GSASII.GSASIIscriptable")

import powderline  # noqa: E402
from powderline.exceptions import EngineExecutionError  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
TABLES = {"refined_parameters.csv", "LaB6_unit_cell_report.csv", "LaB6_peak_list_report.csv", "fit_profile.txt",
          "output_recipe.json", "parameter_dispositions.csv"}


def abort_recipe():
    """The textured example started at exactly r = 1.0: GSAS-II aborts (EB-99)."""
    r = json.loads((REPO / "examples" / "example_LaB6_textured" / "input.json").read_text(encoding="utf-8"))
    r["payload"]["phases"]["LaB6"]["preferred_orientation"]["ratio"] = [1.0, True]
    return r


def test_an_aborted_run_leaves_gsasii_files_and_failure_json_only(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    for name in ("refined_parameters.csv", "Old_unit_cell_report.csv", "output_recipe.json"):
        (out / name).write_text("stale\n", encoding="utf-8")                    # a previous run's tables
    (out / "notes.txt").write_text("mine\n", encoding="utf-8")
    with pytest.raises(EngineExecutionError) as info:
        powderline.run(abort_recipe(), out, execution_mode="subprocess")
    assert info.value.reason == "diverged" and "aborted" in str(info.value)
    names = {p.name for p in out.iterdir()}
    assert not (names & TABLES) and "Old_unit_cell_report.csv" not in names, sorted(names)
    assert {"dummy.gpx", "dummy.lst", "failure.json", "notes.txt"} <= names
    assert names - {"dummy.gpx", "dummy.lst", "failure.json", "notes.txt"} <= {"dummy.bak0.gpx"}   # GSAS-II's backup
    record = json.loads((out / "failure.json").read_text(encoding="utf-8"))
    assert record["status"] == "failed" and record["failure"]["reason"] == "diverged"
    assert "ouch #4" in record["failure"]["console_tail"] or "Final refinement wR = 100.00%" in record["failure"]["console_tail"]
    assert record["powderline_provenance"]["schema_name"] == "gsasii.rietveld"
    listed = {Path(f).name for f in info.value.result["output_files"]}        # the gateway lists the directory as it is
    assert {"dummy.gpx", "dummy.lst", "failure.json"} <= listed and not (listed & TABLES)


def test_a_successful_run_still_writes_every_table(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "failure.json").write_text("{}", encoding="utf-8")                   # a previous failure
    res = powderline.run(powderline.load_recipe_asset(REPO / "examples" / "example_LaB6_textured" / "input.json"),
                         out, execution_mode="subprocess")
    names = {p.name for p in out.iterdir()}
    assert res["status"] == "ok" and TABLES <= names and "failure.json" not in names
