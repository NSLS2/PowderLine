"""Tests for the one CLI, ``powderline.kicker.main`` (re/07, P-06).

The CLI dispatches on the recipe's ``schema_name`` like ``powderline.run``;
these tests drive ``main()`` in-process on ``--validate-only`` (no engine
needed) and check the flag-to-option mapping, the template guard and the exit
statuses. The ``pixi run kicker`` regression suites cover the real runs.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

import pytest

from powderline import kicker
from powderline.exceptions import EngineExecutionError, ExecutionBackendError
from subprocess_utils import run_subprocess_utf8

pytestmark = pytest.mark.core

REPO = Path(__file__).resolve().parent.parent
LAB6 = REPO / "examples" / "example_LaB6" / "input.json"  # gsasii.rietveld
TOPAS_LAB6 = REPO / "tests" / "data" / "topas" / "native" / "lab6_rietveld.json"
TOPAS_SPF = REPO / "tests" / "data" / "topas" / "native" / "lab6_spf.json"
EASY_LAB6 = REPO / "tests" / "data" / "easydiffraction" / "native" / "lab6_crysfml_tch.json"


# --- --validate-only, every engine ------------------------------------------------------------


def test_validate_only_gsasii_native_recipe(capsys):
    rc = kicker.main([str(LAB6), "--validate-only", "--no-server"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Recipe validation successful" in out
    assert "Schema name: gsasii.rietveld" in out
    assert "Core schema version: 1.0.0" in out and "Engine schema version: 1.0.0" in out
    assert "gsasii_broadening_default_applied" in out  # the structured warnings are shown


def test_validate_only_topas_native_recipe(capsys):
    rc = kicker.main([str(TOPAS_LAB6), "--validate-only", "--topas-version", "6"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Schema name: topas.rietveld" in out
    assert "Core schema version: 1.0.0" in out and "Engine schema version: 1.0.0" in out  # uniform summary (P-28)
    assert "Engine version: 6" in out and "Iterations: " in out and "Parameters requested: " in out
    assert "warning(s):" in out and "topas_adp_converted" in out  # the structured warnings are shown


def test_validate_only_easydiffraction_native_recipe(capsys):
    rc = kicker.main([str(EASY_LAB6), "--validate-only"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Schema name: easydiffraction.rietveld" in out
    assert "Core schema version: 1.0.0" in out  # uniform summary (P-28)
    assert "Calculator: crysfml" in out


def test_validate_only_writes_nothing(tmp_path):
    out = tmp_path / "out"
    rc = kicker.main([str(TOPAS_LAB6), "--validate-only", "--output", str(out)])
    assert rc == 0
    assert not out.exists()


# --- a TOPAS run through the one CLI (moved from test_topas_cli, re/07 H) ------------------------


def _no_tc_exe(monkeypatch):
    monkeypatch.setattr("powderline.gateways.topas.native_run.discover_tc_exe", lambda *a, **kw: None)


def test_cli_topas_generate_only_exits_0(tmp_path, monkeypatch, capsys):
    """No --output: the run writes to <recipe dir>/output, the base name is the recipe's directory.

    Without a declared TOPAS location the native runner generates the INP and xye
    only; that is a normal outcome (status "generated", re/12 D6): the CLI exits 0,
    lists the files and says how to run them (review focus 4).
    """
    _no_tc_exe(monkeypatch)
    case_dir = tmp_path / "example_case"
    case_dir.mkdir()
    shutil.copy(TOPAS_LAB6, case_dir / "input.json")
    rc = kicker.main([str(case_dir / "input.json"), "--topas-version", "6"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Generated" in out and "TOPAS is not configured" in out and "--topas-dir" in out
    assert "example_case.inp" in out and "Refinement failed" not in out
    assert (case_dir / "output" / "example_case.inp").exists()
    assert (case_dir / "output" / "example_case.xye").exists()
    assert "Output recipe:" in out and (case_dir / "output" / "output_recipe.json").exists()  # re/20a


def test_cli_topas_output_dir_flag(tmp_path, monkeypatch):
    """--output DIR: the INP and xye land in DIR (base name ``topas`` unless DIR is a case's ``output``)."""
    _no_tc_exe(monkeypatch)
    out = tmp_path / "lab6_run"
    rc = kicker.main([str(TOPAS_LAB6), "--output", str(out)])
    assert rc == 0  # generate-only is a normal outcome (re/12 D6)
    assert (out / "topas.inp").exists() and (out / "topas.xye").exists()


# --- engine flags ---------------------------------------------------------------------------------


def _args(**kw) -> argparse.Namespace:
    ns = kicker.build_parser().parse_args([str(LAB6)])
    for key, value in kw.items():
        setattr(ns, key, value)
    return ns


def test_engine_options_default_is_empty():
    assert kicker.engine_options_from_args(_args(), "gsasii") == {}
    assert kicker.engine_options_from_args(_args(), "topas") == {}


def test_engine_options_gsasii_server_flags():
    assert kicker.engine_options_from_args(_args(no_server=True), "gsasii") == {"execution_mode": "subprocess"}
    assert kicker.engine_options_from_args(_args(use_server=True), "gsasii") == {"execution_mode": "server"}


def test_engine_options_topas_flags():
    opts = kicker.engine_options_from_args(_args(topas_dir=Path("/t"), topas_version="6"), "topas")
    assert opts == {"topas_dir": Path("/t"), "topas_version": "6"}
    parsed = kicker.build_parser().parse_args([str(LAB6), "--topas-timeout", "0"])   # A195; 0 = no limit
    assert kicker.engine_options_from_args(parsed, "topas") == {"topas_timeout": 0.0}


@pytest.mark.parametrize("flag,gateway", [
    ({"no_server": True}, "topas"), ({"use_server": True}, "easydiffraction"),
    ({"topas_dir": Path("/t")}, "gsasii"), ({"topas_version": "6"}, "gsasii"),
    ({"topas_timeout": 0.0}, "gsasii"), ({"topas_timeout": 600.0}, "easydiffraction"),
])
def test_engine_options_flag_for_another_engine_is_an_error(flag, gateway):
    with pytest.raises(ValueError, match="applies to"):
        kicker.engine_options_from_args(_args(**flag), gateway)


def test_cli_rejects_gsasii_flag_on_topas_recipe(capsys):
    rc = kicker.main([str(TOPAS_LAB6), "--validate-only", "--no-server"])
    out = capsys.readouterr().out
    assert rc == 1
    assert "--no-server applies to 'gsasii' recipes only" in out and "'topas'" in out


def test_cli_use_server_and_no_server_are_exclusive():
    with pytest.raises(SystemExit):
        kicker.build_parser().parse_args([str(LAB6), "--use-server", "--no-server"])


# --- errors -----------------------------------------------------------------------------------------


def test_cli_missing_recipe_file_exits_1(tmp_path, capsys):
    rc = kicker.main([str(tmp_path / "nope.json")])
    assert rc == 1
    assert "Cannot read recipe" in capsys.readouterr().out


def test_cli_malformed_json_exits_1_without_traceback(tmp_path, capsys):
    bad = tmp_path / "bad.json"
    bad.write_text('{"schema_name": "gsasii.rietveld",}', encoding="utf-8")
    rc = kicker.main([str(bad), "--validate-only"])
    out = capsys.readouterr()
    assert rc == 1
    assert "Cannot read recipe" in out.out and "not valid JSON" in out.out
    assert "Traceback" not in out.out + out.err


def test_cli_yaml_list_exits_1(tmp_path, capsys):
    bad = tmp_path / "bad.yaml"
    bad.write_text("- 1\n", encoding="utf-8")
    rc = kicker.main([str(bad), "--validate-only"])
    assert rc == 1
    assert "mapping" in capsys.readouterr().out


def test_cli_verbose_prints_traceback_on_unexpected_error(tmp_path, capsys, monkeypatch):
    """--verbose promises 'more details': the traceback of an unexpected error is printed."""
    def boom(*a, **k):
        raise RuntimeError("engine exploded")
    monkeypatch.setattr(kicker, "run", boom)
    rc = kicker.main([str(LAB6), "--verbose", "--no-server", "--output", str(tmp_path / "o")])
    out = capsys.readouterr().out
    assert rc == 1 and "engine exploded" in out and "Traceback" in out


def test_cli_quiet_hides_traceback_on_unexpected_error(tmp_path, capsys, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("engine exploded")
    monkeypatch.setattr(kicker, "run", boom)
    rc = kicker.main([str(LAB6), "--no-server", "--output", str(tmp_path / "o")])
    out = capsys.readouterr().out
    assert rc == 1 and "engine exploded" in out and "Traceback" not in out


def test_cli_template_path_exits_1(capsys):
    rc = kicker.main([str(REPO / "examples" / "example_template" / "input.json"), "--validate-only"])
    assert rc == 1
    assert "appears to be a template file" in capsys.readouterr().out


def test_cli_reports_validation_errors_as_bullets(tmp_path, capsys):
    recipe = json.loads(TOPAS_LAB6.read_text(encoding="utf-8"))
    recipe["payload"]["refinement_controls"]["iters"] = "many"
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(recipe))
    rc = kicker.main([str(bad), "--validate-only"])
    out = capsys.readouterr().out
    assert rc == 1
    assert "Recipe validation failed" in out and "Validation errors:" in out
    assert "payload -> refinement_controls -> iters" in out


def test_cli_unknown_engine_exits_1_with_the_registry_message(tmp_path, capsys):
    recipe = json.loads(TOPAS_LAB6.read_text(encoding="utf-8"))
    recipe["schema_name"] = "bogus.rietveld"
    bad = tmp_path / "bogus.json"
    bad.write_text(json.dumps(recipe))
    rc = kicker.main([str(bad), "--validate-only"])
    out = capsys.readouterr().out
    assert rc == 1
    assert "no PowderLine gateway named 'bogus'" in out


# --- template guard ------------------------------------------------------------------------------


@pytest.mark.parametrize("schema_name", ["gsasii.rietveld", "topas.rietveld", "easydiffraction.rietveld"])
def test_is_template_file_rietveld_needs_phases(schema_name):
    payload = {"xrd_data": {}, "instrument": {}, "refinement_controls": {}}
    is_template, reason = kicker.is_template_file({"schema_name": schema_name, "payload": payload}, Path("in.json"))
    assert is_template and "phases" in reason
    payload["phases"] = {}
    assert kicker.is_template_file({"schema_name": schema_name, "payload": payload}, Path("in.json")) == (False, None)


@pytest.mark.parametrize("schema_name", ["gsasii.spf", "topas.spf"])
def test_is_template_file_spf_needs_single_peaks(schema_name):
    payload = {"xrd_data": {}, "instrument": {}, "refinement_controls": {}}
    is_template, reason = kicker.is_template_file({"schema_name": schema_name, "payload": payload}, Path("in.json"))
    assert is_template and "single_peaks" in reason


def test_is_template_file_real_fixtures_are_not_templates():
    for path in (LAB6, TOPAS_LAB6, TOPAS_SPF, EASY_LAB6):
        assert kicker.is_template_file(json.loads(path.read_text(encoding="utf-8")), path) == (False, None)


# --- engine-free -------------------------------------------------------------------------------------


def test_cli_module_imports_no_engine_and_validates_with_engines_blocked():
    """``powderline.kicker`` imports no engine; ``--validate-only`` works with GSASII/easydiffraction/cryspy blocked."""
    script = f"""
import sys, importlib.abc
BLOCKED = ("GSASII", "easydiffraction", "cryspy")
class _Block(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path, target=None):
        if name in BLOCKED or name.startswith(tuple(b + "." for b in BLOCKED)):
            raise ImportError(name + " blocked")
        return None
sys.meta_path.insert(0, _Block())
from powderline import kicker
for recipe in (r'{LAB6}', r'{TOPAS_LAB6}', r'{EASY_LAB6}'):
    assert kicker.main([recipe, "--validate-only"]) == 0, recipe
for mod in BLOCKED:
    assert mod not in sys.modules, mod
print("OK")
"""
    proc = run_subprocess_utf8([sys.executable, "-c", script], capture_output=True, text=True)
    assert proc.returncode == 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    assert "OK" in proc.stdout



# --- POWDERLINE_NO_SERVER (v0.1.2): --use-server is refused before any engine is touched ----------

def test_use_server_with_no_server_env_exits(tmp_path, monkeypatch, capsys):
    """`powderline <gsasii recipe> --use-server` exits 1 with a clear message when the server is disabled."""
    monkeypatch.setenv("POWDERLINE_NO_SERVER", "1")
    out_dir = tmp_path / "out"
    rc = kicker.main([str(LAB6), "--use-server", "--output", str(out_dir)])
    assert rc == 1
    assert "POWDERLINE_NO_SERVER" in capsys.readouterr().out
    assert not out_dir.exists()


# --- warning levels (P-34): info-level entries are counted, listed only with --verbose -----------

def test_print_warnings_summarises_info_level(capsys):
    kicker._print_warnings([
        {"code": "a_warning", "message": "act on this", "field_path": "p.x"},
        {"code": "an_info", "message": "for your information", "field_path": "p.y", "level": "info"},
    ])
    out = capsys.readouterr().out
    assert "1 warning(s)" in out and "a_warning: act on this (p.x)" in out
    assert "an_info" not in out
    assert "1 informative note(s)" in out and "--verbose" in out


def test_print_warnings_verbose_lists_info_level(capsys):
    kicker._print_warnings([{"code": "an_info", "message": "fyi", "field_path": None, "level": "info"}],
                           verbose=True)
    out = capsys.readouterr().out
    assert "an_info: fyi" in out and "warning(s)" not in out


# --- re/12: the CLI reports by outcome class ----------------------------------------------------------

def _patched_run(monkeypatch, outcome):
    def fake_run(*a, **k):
        if isinstance(outcome, Exception):
            raise outcome
        return outcome
    monkeypatch.setattr(kicker, "run", fake_run)


def test_cli_engine_failure_prints_reason_and_exits_1(tmp_path, monkeypatch, capsys):
    from powderline import results
    env = results.failure_envelope("engine", "diverged", "the pattern is not finite", output_files=["o/dummy.lst"])
    _patched_run(monkeypatch, EngineExecutionError("the pattern is not finite", reason="diverged", result=env))
    rc = kicker.main([str(LAB6), "--no-server", "--output", str(tmp_path / "o")])
    out = capsys.readouterr().out
    assert rc == 1 and "Refinement failed (diverged)" in out and "not finite" in out and "dummy.lst" in out


def test_cli_backend_failure_prints_reason_and_exits_1(tmp_path, monkeypatch, capsys):
    _patched_run(monkeypatch, ExecutionBackendError("no server", reason="server_unavailable"))
    rc = kicker.main([str(LAB6), "--use-server", "--output", str(tmp_path / "o")])
    out = capsys.readouterr().out
    assert rc == 1 and "Could not run the engine (server_unavailable)" in out and "no server" in out


def test_cli_unconverged_result_says_so(tmp_path, monkeypatch, capsys):
    _patched_run(monkeypatch, {"status": "ok", "converged": False, "rwp": 7.1, "method": "subprocess",
                               "elapsed_time": 1.0, "warnings": [], "output_files": []})
    rc = kicker.main([str(LAB6), "--no-server", "--output", str(tmp_path / "o")])
    out = capsys.readouterr().out
    assert rc == 0 and "Final Rwp: 7.100%" in out and "did not converge" in out
