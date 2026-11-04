"""re/30: a failed run leaves the engine's own files and ``failure.json``, nothing else; ``powderline.run`` clears
PowderLine's own fixed-name outputs before every run so a reused directory holds one run's results (engine-free)."""
import json
from pathlib import Path

import pytest

import powderline
from powderline import registry, reports, roundtrip
from powderline.exceptions import EngineExecutionError, ExecutionBackendError
from powderline.results import failure_envelope

pytestmark = pytest.mark.core

RECIPE = {"schema_name": "fake.rietveld", "core_schema_version": "0.1.0", "engine_schema_version": "0.1.0", "payload": {}}


def _gateway(name, run):
    return registry.Gateway(name=name, capabilities=lambda: {"name": name, "workflows": [f"{name}.rietveld"]},
                            validate=lambda recipe, **opts: recipe, run=run)


@pytest.fixture
def fake(monkeypatch):
    """Register ``fake`` with a run() chosen per test; returns a setter."""
    holder = {}

    def run(recipe, output_dir, **kwargs):
        return holder["run"](recipe, Path(output_dir), **kwargs)
    registry.register_gateway("fake", lambda: _gateway("fake", run))
    try:
        yield lambda fn: holder.__setitem__("run", fn)
    finally:
        registry.unregister_gateway("fake")                 # never leak into the registry other modules read
        registry._instances.pop("fake", None)


def _seed(out: Path):
    out.mkdir(parents=True, exist_ok=True)
    for name in ("refined_parameters.csv", "Other_unit_cell_report.csv", "Other_peak_list_report.csv", "fit_profile.txt",
                 "output_recipe.json", "parameter_dispositions.csv", "failure.json", "single_peaks_report.txt"):
        (out / name).write_text("stale\n", encoding="utf-8")
    (out / "notes.txt").write_text("mine\n", encoding="utf-8")          # the user's; never touched
    (out / "dummy.lst").write_text("engine\n", encoding="utf-8")        # the engine's; never touched


def test_a_run_clears_powderlines_fixed_outputs_and_nothing_else(fake, tmp_path):
    out = tmp_path / "out"
    _seed(out)
    seen = {}

    def run(recipe, output_dir, **kwargs):
        seen["at_entry"] = sorted(p.name for p in output_dir.iterdir())
        (output_dir / "refined_parameters.csv").write_text("new\n", encoding="utf-8")
        return {"status": "ok"}
    fake(run)
    assert powderline.run(RECIPE, out) == {"status": "ok"}
    assert seen["at_entry"] == ["dummy.lst", "notes.txt"]
    assert sorted(p.name for p in out.iterdir()) == ["dummy.lst", "notes.txt", "refined_parameters.csv"]
    assert (out / "refined_parameters.csv").read_text(encoding="utf-8") == "new\n"


def test_a_failed_run_leaves_the_engines_files_and_failure_json(fake, tmp_path):
    out = tmp_path / "out"
    _seed(out)

    def run(recipe, output_dir, **kwargs):
        (output_dir / "dummy.gpx").write_bytes(b"\x00")
        env = failure_envelope("engine", "diverged", "it ran away", run_id="r-1", method="subprocess",
                               output_files=[str(output_dir / "dummy.gpx"), str(output_dir / "dummy.lst")])
        env["failure"]["console_tail"] = "ouch #4 stuck\n"
        raise EngineExecutionError("it ran away", reason="diverged", result=env)
    fake(run)
    with pytest.raises(EngineExecutionError) as info:
        powderline.run(RECIPE, out)
    assert sorted(p.name for p in out.iterdir()) == ["dummy.gpx", "dummy.lst", "failure.json", "notes.txt"]
    record = json.loads((out / "failure.json").read_text(encoding="utf-8"))
    assert record["status"] == "failed" and record["failure"]["reason"] == "diverged"
    assert record["failure"]["console_tail"] == "ouch #4 stuck\n"
    prov = record[roundtrip.PROVENANCE_KEY]
    assert prov["schema_name"] == "fake.rietveld" and prov["powderline_version"] == powderline.__version__
    assert prov["run_id"] == "r-1" and prov["created"].endswith("+00:00")
    assert prov["engine"] == "fake" and prov["engine_version"] is None   # A191: an unknown gateway's version is unknown
    assert str((out / "failure.json").resolve()) in info.value.result["output_files"]   # listed in the envelope too
    assert sorted(Path(f).name for f in info.value.result["output_files"]) == ["dummy.gpx", "dummy.lst", "failure.json"]


def test_a_gateway_raising_without_an_envelope_still_gets_a_record(fake, tmp_path):
    out = tmp_path / "out"
    out.mkdir()

    def run(recipe, output_dir, **kwargs):
        raise EngineExecutionError("TOPAS could not be started", reason="engine_crashed")   # no result attached
    fake(run)
    with pytest.raises(EngineExecutionError) as info:
        powderline.run(RECIPE, out)
    record = json.loads((out / "failure.json").read_text(encoding="utf-8"))
    assert record["failure"] == {"kind": "engine", "reason": "engine_crashed", "message": "TOPAS could not be started",
                                 **{k: v for k, v in record["failure"].items() if k not in ("kind", "reason", "message")}}
    assert info.value.result["status"] == "failed" and info.value.result["output_files"] == [str((out / "failure.json").resolve())]


def test_a_backend_failure_before_the_directory_exists_writes_nothing(fake, tmp_path):
    out = tmp_path / "never"

    def run(recipe, output_dir, **kwargs):
        raise ExecutionBackendError("server unavailable", reason="server_unavailable")
    fake(run)
    with pytest.raises(ExecutionBackendError):
        powderline.run(RECIPE, out)
    assert not out.exists()


def test_a_backend_failure_with_the_directory_present_is_recorded_as_backend(fake, tmp_path):
    out = tmp_path / "out"
    out.mkdir()

    def run(recipe, output_dir, **kwargs):
        raise ExecutionBackendError("server unavailable", reason="server_unavailable")
    fake(run)
    with pytest.raises(ExecutionBackendError):
        powderline.run(RECIPE, out)
    record = json.loads((out / "failure.json").read_text(encoding="utf-8"))
    assert record["failure"]["kind"] == "backend" and record["failure"]["reason"] == "server_unavailable"


def test_validate_only_touches_nothing(fake, tmp_path):
    out = tmp_path / "out"
    _seed(out)
    fake(lambda recipe, output_dir, **kwargs: {"method": "validate_only"})
    powderline.run(RECIPE, out, validate_only=True)
    assert (out / "refined_parameters.csv").read_text(encoding="utf-8") == "stale\n"      # untouched


def test_the_fixed_output_list_covers_every_core_writer(tmp_path):
    """Every file the core writers and the output-recipe writer produce is on the list the clearing removes."""
    out = tmp_path / "out"
    out.mkdir()
    reports.write_refined_parameters(out, [])
    reports.write_fit_profile(out, [])
    reports.write_unit_cell_report(out, "P", reports.unit_cell_rows({k: 1.0 for k in reports.UNIT_CELL_MEMBERS}, {}, fixed=set(reports.UNIT_CELL_MEMBERS), refined=set(), volume=1.0))
    reports.write_peak_list_report(out, "P", [], ["h"])
    (out / roundtrip.OUTPUT_RECIPE_FILE).write_text("{}", encoding="utf-8")
    (out / roundtrip.DISPOSITIONS_FILE).write_text("", encoding="utf-8")
    (out / reports.FAILURE_FILE).write_text("{}", encoding="utf-8")
    (out / "single_peaks_report.txt").write_text("", encoding="utf-8")       # the gsasii SPF report (frozen writer)
    (out / "single_peaks_report.csv").write_text("", encoding="utf-8")       # the topas SPF report (native_run)
    (out / "keep.me").write_text("", encoding="utf-8")
    written = sorted(p.name for p in out.iterdir())
    assert len(written) == 10, written
    removed = reports.clear_fixed_outputs(out)
    assert sorted(Path(r).name for r in removed) == sorted(n for n in written if n != "keep.me")
    assert [p.name for p in out.iterdir()] == ["keep.me"]
    assert reports.clear_fixed_outputs(tmp_path / "missing") == [] and not (tmp_path / "missing").exists()


def test_failure_json_records_the_engine_version_the_gateway_reported(fake, tmp_path):
    """A191: the failure record's provenance names the engine version from the envelope's engine_details."""
    out = tmp_path / "out"
    out.mkdir()

    def run(recipe, output_dir, **kwargs):
        env = failure_envelope("engine", "diverged", "it ran away", run_id="r-2",
                               engine_details={"engine": "Fake", "engine_version": "9.1"})
        raise EngineExecutionError("it ran away", reason="diverged", result=env)
    fake(run)
    with pytest.raises(EngineExecutionError):
        powderline.run(RECIPE, out)
    prov = json.loads((out / "failure.json").read_text(encoding="utf-8"))[roundtrip.PROVENANCE_KEY]
    assert prov["engine"] == "fake" and prov["engine_version"] == "9.1"
