"""re/27 (KI-05): the engine's console text, captured into a failed envelope (engine-free)."""
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from powderline import results as envelopes
from powderline.exceptions import EngineExecutionError
from powderline.gateways.gsasii import console
from powderline.gateways.gsasii import gateway as gsasii_gateway

pytestmark = pytest.mark.core
REPO = Path(__file__).resolve().parents[1]


def _lab6():
    return json.loads((REPO / "examples" / "example_LaB6" / "input.json").read_text(encoding="utf-8-sig"))


def test_console_tail_keeps_the_end_and_says_it_truncated():
    tail = console.ConsoleTail(limit=10)
    tail.write("abcdef"); tail.write("ghij")
    assert tail.text() == "abcdefghij" and not tail.truncated
    tail.write("KLM")
    assert tail.text() == "defghijKLM" and tail.truncated          # the oldest characters go first
    tail.write("x" * 25)
    assert tail.text() == "x" * 10


def test_capture_console_tees_to_the_real_stdout_and_the_tail(capsys):
    with console.capture_console() as tail:
        print("GSAS-II says hello")
        print("and more", end="")
    print("after")
    out = capsys.readouterr().out
    assert "GSAS-II says hello\nand more" in out and out.endswith("after\n")   # the real stdout saw everything
    assert tail.text() == "GSAS-II says hello\nand more"                      # and so did the tail
    assert not tail.truncated


def test_attach_console_goes_to_the_failure_record_or_verbose_engine_details():
    tail = console.ConsoleTail(); tail.write("**** Refinement failed - singular matrix ****\n")
    failed = envelopes.failure_envelope("engine", "diverged", "m", method="subprocess")
    console.attach_console(failed, tail)
    assert failed["failure"]["console_tail"] == "**** Refinement failed - singular matrix ****\n"
    ok = {"status": "ok", "engine_details": {"engine": "GSAS-II"}}
    console.attach_console(ok, tail, verbose=False)
    assert "console_tail" not in ok["engine_details"]                         # quiet success: nothing added
    console.attach_console(ok, tail, verbose=True)
    assert ok["engine_details"]["console_tail"].startswith("**** Refinement failed")
    empty = envelopes.failure_envelope("engine", "diverged", "m", method="subprocess")
    console.attach_console(empty, console.ConsoleTail())
    assert empty["failure"]["console_tail"] is None                           # printed nothing: None, not ""
    truncated = console.ConsoleTail(limit=5); truncated.write("0123456789")
    env = envelopes.failure_envelope("engine", "diverged", "m", method="subprocess")
    console.attach_console(env, truncated)
    assert env["failure"]["console_tail"].startswith("[... earlier console text dropped ...]\n56789")


def test_gateway_failure_carries_the_console_tail_and_the_cli_prints_it(tmp_path, monkeypatch, capsys):
    """An in-process run whose frozen executor prints and then raises: the raised error's envelope has the
    text, and the CLI shows the last lines after 'Refinement failed'."""
    monkeypatch.setattr(gsasii_gateway, "installed_engine_version", lambda: "5.7.9")

    def fake_run(recipe, output_dir, verbose=False, method="subprocess"):
        print("Removing parameter: 0::A0")
        print("**** Refinement failed - singular matrix ****")
        raise EngineExecutionError("GSAS-II's refinement diverged", reason="diverged",
                                   result=envelopes.failure_envelope("engine", "diverged", "GSAS-II's refinement diverged",
                                                                     method="subprocess"))
    monkeypatch.setattr(gsasii_gateway, "run_refinement", fake_run)
    with pytest.raises(EngineExecutionError) as info:
        gsasii_gateway.run(_lab6(), tmp_path, execution_mode="subprocess")
    tail = info.value.result["failure"]["console_tail"]
    assert "Removing parameter: 0::A0" in tail and tail.rstrip().endswith("singular matrix ****")
    # the CLI
    from powderline import kicker
    recipe_path = tmp_path / "input.json"; recipe_path.write_text(json.dumps(_lab6()), encoding="utf-8")
    monkeypatch.setattr("powderline.api.run", lambda *a, **k: gsasii_gateway.run(_lab6(), tmp_path / "o", execution_mode="subprocess"))
    monkeypatch.setattr(kicker, "run", lambda *a, **k: gsasii_gateway.run(_lab6(), tmp_path / "o", execution_mode="subprocess"))
    code = kicker.main([str(recipe_path), "--no-server"])
    out = capsys.readouterr().out
    assert code == 1 and "The engine's last console lines:" in out and "| **** Refinement failed - singular matrix ****" in out


def test_gateway_success_keeps_the_tail_only_when_verbose(tmp_path, monkeypatch):
    monkeypatch.setattr(gsasii_gateway, "installed_engine_version", lambda: "5.7.9")

    def fake_run(recipe, output_dir, verbose=False, method="subprocess"):
        print("Hessian refinement: 5 cycles")
        return {"success": True, "method": method, "engine_details": {"engine": "GSAS-II"}}
    monkeypatch.setattr(gsasii_gateway, "run_refinement", fake_run)
    quiet = gsasii_gateway.run(_lab6(), tmp_path / "q", execution_mode="subprocess")
    assert "console_tail" not in quiet["engine_details"]
    loud = gsasii_gateway.run(_lab6(), tmp_path / "v", execution_mode="subprocess", verbose=True)
    assert loud["engine_details"]["console_tail"].strip() == "Hessian refinement: 5 cycles"


def test_client_in_process_fallback_captures_the_tail_too(tmp_path, monkeypatch):
    """The CLI's default path (auto -> the client's in-process fallback) carries the console tail like the
    gateway's --no-server path (re/27 review)."""
    from powderline.gateways.gsasii import routing
    from powderline.gateways.gsasii.client import GSASClient

    def stub(recipe, output_dir, verbose=False, method="subprocess"):
        print("**** Refinement failed - singular matrix ****")
        raise EngineExecutionError("diverged", reason="diverged")
    monkeypatch.setattr(routing, "run_refinement", stub)
    client = GSASClient(fallback_to_subprocess=True)
    result = client._submit_via_subprocess(_lab6(), tmp_path, verbose=False)
    assert result["status"] == "failed" and result["failure"]["reason"] == "diverged"
    assert result["failure"]["console_tail"].rstrip().endswith("singular matrix ****")

    def ok(recipe, output_dir, verbose=False, method="subprocess"):
        print("cycle 1")
        return {"success": True, "method": method, "engine_details": {"engine": "GSAS-II"}}
    monkeypatch.setattr(routing, "run_refinement", ok)
    quiet = client._submit_via_subprocess(_lab6(), tmp_path / "q", verbose=False)
    assert quiet["status"] == "ok" and "console_tail" not in quiet["engine_details"]
    loud = client._submit_via_subprocess(_lab6(), tmp_path / "v", verbose=True)
    assert loud["engine_details"]["console_tail"].strip() == "cycle 1"
