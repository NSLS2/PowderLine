"""Unit tests for GSASClient.submit_simulation.

Since re/19 (KI-12) the server never sees the client's filesystem: its output
files travel inside the signed response and submit_simulation writes them into
output_dir (names validated, size-capped, atomic). These tests cover that
transfer and its failure modes, the fallback rules (transport or transfer
problem → in-process when allowed; a local write failure or a timeout never
falls back), the use_server bypass, the keyword-signature
regression guard, server identity (a server must prove it holds this user's
token) and the POWDERLINE_NO_SERVER switch.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from powderline import results

from powderline.gateways.gsasii import client as gsas_client, server as gsas_server
from powderline.gateways.gsasii.client import GSASClient

pytestmark = pytest.mark.core

#: Never validated on these paths (the submit methods are monkeypatched); the shape is enough.
RECIPE = {"schema_name": "gsasii.rietveld", "payload": {}}


@pytest.fixture(autouse=True)
def _server_enabled(monkeypatch):
    """Tests assume server use is allowed unless they opt out explicitly."""
    monkeypatch.delenv("POWDERLINE_NO_SERVER", raising=False)


@pytest.fixture
def client(monkeypatch):
    c = GSASClient()
    monkeypatch.setattr(c, "is_server_available", lambda: True)
    return c


def test_use_server_false_skips_server_entirely(monkeypatch, tmp_path):
    c = GSASClient()
    monkeypatch.setattr(c, "is_server_available",
                        lambda: pytest.fail("server must not be consulted"))
    monkeypatch.setattr(c, "_submit_via_subprocess",
                        lambda rd, od, verbose: {"status": "ok"})

    result = c.submit_simulation(RECIPE, tmp_path, use_server=False)
    assert result["status"] == "ok"
    assert result["method"] == "subprocess"


def test_use_server_false_with_fallback_disabled_errors_honestly(monkeypatch, tmp_path):
    """Both execution paths disabled by the caller is a legal (if odd) state:
    it must return a structured error naming BOTH flags — not the misleading
    'Server not available' message (the server was never consulted)."""
    c = GSASClient(fallback_to_subprocess=False)
    monkeypatch.setattr(c, "is_server_available",
                        lambda: pytest.fail("server must not be consulted"))

    result = c.submit_simulation(RECIPE, tmp_path, use_server=False)
    assert result["status"] == "failed" and result["failure"]["kind"] == "backend"
    assert result["failure"]["reason"] == "server_unavailable"
    assert result["method"] == "none"
    assert "use_server=False" in result["failure"]["message"]
    assert "fallback_to_subprocess=False" in result["failure"]["message"]
    assert "Server not available" not in result["failure"]["message"]


def test_submit_simulation_wrong_keyword_raises():
    """Regression guard: 'recipe_path' keyword no longer exists on
    submit_simulation (the former mp_simulate tool once passed recipe_path=..., causing a
    runtime TypeError; the correct keyword is recipe=)."""
    client = GSASClient()
    with pytest.raises(TypeError, match="recipe_path"):
        client.submit_simulation(recipe_path=Path("dummy.json"), output_dir=Path("."))


# --- Server identity: only this user's server, proven by its token ---

class _FakeResponse:
    """Minimal httpx.Response stand-in."""

    def __init__(self, status_code, body, headers=None):
        self.status_code = status_code
        self._body = body
        self.content = json.dumps(body).encode()
        self.headers = headers or {}

    def json(self):
        return self._body

    def raise_for_status(self):
        pass


def _signed_response(token, request_headers, body, status_code=200):
    """A response signed with ``token`` for the request that carried ``request_headers``."""
    resp = _FakeResponse(status_code, body)
    resp.headers = {gsas_server.RESPONSE_SIGNATURE_HEADER: gsas_server.sign_response(
        token, request_headers[gsas_server.NONCE_HEADER], status_code, resp.content)}
    return resp


@pytest.fixture
def own_endpoint(monkeypatch, tmp_path):
    monkeypatch.setattr(gsas_server, "state_dir", lambda: tmp_path)
    # A live PID: endpoints of dead servers are ignored before any probe.
    (tmp_path / "server.json").write_text(
        json.dumps({"pid": os.getpid(), "port": 50123, "token": "my-token"}))
    return tmp_path


def _fake_health(monkeypatch, respond):
    """Patch httpx.get; ``respond(headers) -> _FakeResponse``. Returns call log."""
    import httpx
    calls = []

    def fake_get(url, headers=None, **kwargs):
        calls.append({"url": url, "headers": headers, **kwargs})
        return respond(headers)

    monkeypatch.setattr(httpx, "get", fake_get)
    return calls


def _assert_token_not_sent(call):
    sent = json.dumps({k: v for k, v in call.items() if k != "content"}, default=str)
    sent += str(call.get("content", b""))
    assert "my-token" not in sent, "the token itself must never be sent"


def test_server_unavailable_without_endpoint(monkeypatch, tmp_path):
    monkeypatch.setattr(gsas_server, "state_dir", lambda: tmp_path)
    calls = _fake_health(monkeypatch, lambda h: pytest.fail("must not probe"))
    assert GSASClient().is_server_available() is False
    assert calls == []


def test_endpoint_of_dead_server_is_not_probed(monkeypatch, own_endpoint):
    monkeypatch.setattr(gsas_server, "_pid_alive", lambda pid: False)
    calls = _fake_health(monkeypatch, lambda h: pytest.fail("must not probe"))
    assert GSASClient().is_server_available() is False
    assert calls == []


def test_server_available_when_response_signed_with_token(monkeypatch, own_endpoint):
    calls = _fake_health(monkeypatch, lambda h: _signed_response("my-token", h, {"status": "ok"}))
    assert GSASClient().is_server_available() is True
    (call,) = calls
    assert call["url"] == "http://127.0.0.1:50123/health"
    assert call["trust_env"] is False  # never sent through a proxy
    _assert_token_not_sent(call)
    h = call["headers"]
    assert h[gsas_server.SIGNATURE_HEADER] == gsas_server.sign_request(
        "my-token", "GET", "/health", b"", h[gsas_server.NONCE_HEADER],
        h[gsas_server.TIMESTAMP_HEADER], b"")


def test_nonce_is_fresh_per_request(monkeypatch, own_endpoint):
    calls = _fake_health(monkeypatch, lambda h: _signed_response("my-token", h, {}))
    client = GSASClient()
    client.is_server_available()
    client.is_server_available()
    assert calls[0]["headers"][gsas_server.NONCE_HEADER] != \
        calls[1]["headers"][gsas_server.NONCE_HEADER]


def _echo_impostor(headers):
    """A listener without the token that signs with whatever secret it was sent
    (a bearer token, if the client ever sent one again)."""
    key = headers.get("Authorization", "").removeprefix("Bearer ") \
        or headers.get(gsas_server.SIGNATURE_HEADER, "")
    return _signed_response(key, headers, {"status": "ok"})


@pytest.mark.parametrize("respond", [
    lambda h: _FakeResponse(200, {"status": "ok"}),                 # unsigned / old server
    lambda h: _FakeResponse(200, {"status": "ok"},
                            {gsas_server.RESPONSE_SIGNATURE_HEADER: "0" * 64}),
    lambda h: _signed_response("other-token", h, {"status": "ok"}),  # another user's server
    lambda h: _signed_response("my-token", {gsas_server.NONCE_HEADER: "replayed"}, {}),
    lambda h: _FakeResponse(401, {"detail": "Unauthorized"}),
    _echo_impostor,                                                  # port squatter
])
def test_server_unavailable_without_valid_response_signature(monkeypatch, own_endpoint, respond):
    _fake_health(monkeypatch, respond)
    assert GSASClient().is_server_available() is False


def test_unsafe_state_dir_means_no_server(monkeypatch, capsys):
    def unsafe():
        raise gsas_server.ServerStateError("unsafe state dir")

    monkeypatch.setattr(gsas_server, "state_dir", unsafe)
    _fake_health(monkeypatch, lambda h: pytest.fail("must not probe"))
    c = GSASClient()
    assert c.is_server_available() is False
    assert c.is_server_available() is False
    assert c._start_server_background() is False
    assert capsys.readouterr().out.count("unsafe state dir") == 1


def _fake_post(monkeypatch, respond):
    import httpx
    seen = {}

    def fake_post(url, content=None, headers=None, **kwargs):
        seen.update(url=url, content=content, headers=headers, **kwargs)
        return respond(headers)

    monkeypatch.setattr(httpx, "post", fake_post)
    return seen


def test_submit_is_signed_and_response_verified(monkeypatch, own_endpoint, tmp_path):
    seen = _fake_post(monkeypatch, lambda h: _signed_response("my-token", h, {"status": "ok"}))
    assert GSASClient()._submit_to_server(RECIPE) == {"status": "ok"}
    assert seen["url"] == "http://127.0.0.1:50123/simulate"
    assert seen["trust_env"] is False
    _assert_token_not_sent(seen)
    h = seen["headers"]
    assert h[gsas_server.SIGNATURE_HEADER] == gsas_server.sign_request(
        "my-token", "POST", "/simulate", b"", h[gsas_server.NONCE_HEADER],
        h[gsas_server.TIMESTAMP_HEADER], seen["content"])


def test_forged_server_result_is_never_trusted(monkeypatch, own_endpoint, tmp_path):
    """A listener that took over the port answers 'success' without the token:
    the run must not report success from it."""
    _fake_post(monkeypatch, lambda h: _FakeResponse(200, {"status": "ok", "rwp": 1.0}))
    monkeypatch.setattr(GSASClient, "is_server_available", lambda self: True)
    c = GSASClient(fallback_to_subprocess=False)
    with pytest.raises(gsas_client.ServerIdentityError):
        c._submit_to_server(RECIPE)
    result = c.submit_simulation(RECIPE, tmp_path / "out", auto_start_server=False)
    assert result["status"] == "failed" and result["failure"]["reason"] == "communication_failed"
    assert "did not prove" in result["failure"]["message"]


# --- POWDERLINE_NO_SERVER ---

@pytest.fixture
def no_server(monkeypatch):
    monkeypatch.setenv("POWDERLINE_NO_SERVER", "1")


def _forbid_server(monkeypatch, c):
    for name in ("is_server_available", "_submit_to_server"):
        monkeypatch.setattr(c, name, lambda *a, **k: pytest.fail(f"{name} called"))
    monkeypatch.setattr(c, "_start_server_background",
                        lambda *a, **k: pytest.fail("server auto-started"))


def test_no_server_env_auto_runs_in_process(no_server, monkeypatch, tmp_path, capsys):
    c = GSASClient()
    _forbid_server(monkeypatch, c)
    monkeypatch.setattr(c, "_submit_via_subprocess",
                        lambda rd, od, verbose: {"status": "ok"})
    result = c.submit_simulation(RECIPE, tmp_path, auto_start_server=True)
    assert result == {"status": "ok", "method": "subprocess"}
    assert "POWDERLINE_NO_SERVER" in capsys.readouterr().out


def test_no_server_env_server_mode_errors(no_server, monkeypatch, tmp_path):
    c = GSASClient(fallback_to_subprocess=False)
    _forbid_server(monkeypatch, c)
    monkeypatch.setattr(c, "_submit_via_subprocess",
                        lambda *a: pytest.fail("must not run in-process"))
    result = c.submit_simulation(RECIPE, tmp_path)
    assert result["status"] == "failed" and result["failure"]["reason"] == "server_disabled"
    assert "POWDERLINE_NO_SERVER" in result["failure"]["message"]


def test_no_server_env_blocks_background_start(no_server, monkeypatch):
    import subprocess as sp
    monkeypatch.setattr(sp, "Popen", lambda *a, **k: pytest.fail("server spawned"))
    assert GSASClient()._start_server_background() is False


def test_no_server_env_direct_probe_contacts_nothing(no_server, monkeypatch, own_endpoint):
    _fake_health(monkeypatch, lambda h: pytest.fail("must not contact a server"))
    assert GSASClient().is_server_available() is False


# --- re/12: the client returns envelopes; a failed one is never followed by an in-process re-run ------

def test_server_failed_envelope_is_raised_not_rerun(client, monkeypatch, tmp_path):
    """Review focus 3: a failed envelope from the server is returned as-is; the client never re-runs in-process."""
    from powderline import results
    failed = results.failure_envelope("engine", "diverged", "server says diverged", method="server")
    monkeypatch.setattr(client, "is_server_available", lambda: True)
    monkeypatch.setattr(client, "_submit_to_server", lambda *a, **k: dict(failed))
    calls = []
    monkeypatch.setattr(client, "_submit_via_subprocess", lambda *a, **k: calls.append(1) or {})
    result = client.submit_simulation(RECIPE, tmp_path)
    assert result["status"] == "failed" and result["failure"]["reason"] == "diverged"
    assert result["method"] == "server" and calls == []


def test_post_timeout_is_a_backend_failure_without_fallback(client, monkeypatch, tmp_path):
    import httpx
    monkeypatch.setattr(client, "is_server_available", lambda: True)

    def timeout(*a, **k):
        raise httpx.ReadTimeout("300 s")
    monkeypatch.setattr(client, "_submit_to_server", timeout)
    calls = []
    monkeypatch.setattr(client, "_submit_via_subprocess", lambda *a, **k: calls.append(1) or {})
    result = client.submit_simulation(RECIPE, tmp_path)   # fallback_to_subprocess=True by default
    assert result["status"] == "failed" and result["failure"]["reason"] == "timeout"
    assert calls == [], "a timed-out request must never fall back: the server may still be writing"


def test_post_timeout_in_auto_start_branch_never_falls_back(monkeypatch, tmp_path):
    """Review (re/12): the auto-start branch had its own bare except; a timeout there fell back in-process."""
    import httpx
    c = GSASClient()
    availability = iter([False, True])  # unavailable, then up after auto-start
    monkeypatch.setattr(c, "is_server_available", lambda: next(availability))
    monkeypatch.setattr(c, "_start_server_background", lambda verbose: True)
    monkeypatch.setattr("time.sleep", lambda s: None)

    def timeout(*a, **k):
        raise httpx.ReadTimeout("300 s")
    monkeypatch.setattr(c, "_submit_to_server", timeout)
    calls = []
    monkeypatch.setattr(c, "_submit_via_subprocess", lambda *a, **k: calls.append(1) or {})
    result = c.submit_simulation(RECIPE, tmp_path, auto_start_server=True)
    assert result["status"] == "failed" and result["failure"]["reason"] == "timeout"
    assert calls == []


def test_communication_failure_in_auto_start_branch_with_fallback_disabled(monkeypatch, tmp_path):
    c = GSASClient(fallback_to_subprocess=False)
    availability = iter([False, True])
    monkeypatch.setattr(c, "is_server_available", lambda: next(availability))
    monkeypatch.setattr(c, "_start_server_background", lambda verbose: True)
    monkeypatch.setattr("time.sleep", lambda s: None)

    def broken(*a, **k):
        raise RuntimeError("connection reset")
    monkeypatch.setattr(c, "_submit_to_server", broken)
    monkeypatch.setattr(c, "_submit_via_subprocess", lambda *a, **k: pytest.fail("must not fall back"))
    result = c.submit_simulation(RECIPE, tmp_path, auto_start_server=True)
    assert result["status"] == "failed" and result["failure"]["reason"] == "communication_failed"
    assert "connection reset" in result["failure"]["message"]


# --- re/14 items 2 and 3: a bad port never spawns a doomed server; unsigned rejections read as such ----

def test_auto_start_with_bad_port_env_fails_without_spawning(monkeypatch, tmp_path):
    import subprocess
    monkeypatch.delenv("POWDERLINE_NO_SERVER", raising=False)
    monkeypatch.setenv("POWDERLINE_SERVER_PORT", "auto")
    monkeypatch.setattr(gsas_server, "state_dir", lambda: tmp_path)
    monkeypatch.setattr(subprocess, "Popen",
                        lambda *a, **k: pytest.fail("a server that cannot bind must not be spawned"))
    c = GSASClient(fallback_to_subprocess=False)
    monkeypatch.setattr(c, "is_server_available", lambda: False)
    result = c.submit_simulation(RECIPE, tmp_path, auto_start_server=True)
    assert result["status"] == "failed" and result["failure"]["reason"] == "server_unavailable"
    assert "POWDERLINE_SERVER_PORT" in result["failure"]["message"]


def test_unsigned_413_is_reported_as_too_large(monkeypatch, own_endpoint, tmp_path):
    _fake_post(monkeypatch, lambda h: _FakeResponse(413, {"detail": "Request too large"}))
    monkeypatch.setattr(GSASClient, "is_server_available", lambda self: True)
    c = GSASClient(fallback_to_subprocess=False)
    result = c.submit_simulation(RECIPE, tmp_path / "out", auto_start_server=False)
    assert result["status"] == "failed" and result["failure"]["reason"] == "communication_failed"
    assert "too large" in result["failure"]["message"] and "did not prove" not in result["failure"]["message"]


def test_unsigned_401_is_reported_as_rejected(monkeypatch, own_endpoint, tmp_path):
    _fake_post(monkeypatch, lambda h: _FakeResponse(401, {"detail": "Unauthorized"}))
    monkeypatch.setattr(GSASClient, "is_server_available", lambda self: True)
    c = GSASClient(fallback_to_subprocess=False)
    result = c.submit_simulation(RECIPE, tmp_path / "out", auto_start_server=False)
    assert result["status"] == "failed" and result["failure"]["reason"] == "communication_failed"
    assert "rejected" in result["failure"]["message"] and "did not prove" not in result["failure"]["message"]


# --- re/14 review: a child that dies at start is noticed and explained ---------------------------------

def test_auto_start_notices_a_child_that_exits(monkeypatch, tmp_path):
    """A spawned server that exits during the start wait (e.g. a busy pinned port) ends the wait at once and
    the server_unavailable failure says so, pointing at the log."""
    import subprocess
    monkeypatch.delenv("POWDERLINE_NO_SERVER", raising=False)
    monkeypatch.delenv("POWDERLINE_SERVER_PORT", raising=False)
    monkeypatch.setattr(gsas_server, "state_dir", lambda: tmp_path)
    monkeypatch.setattr(gsas_server, "log_file", lambda: tmp_path / "server.log")
    monkeypatch.setattr("time.sleep", lambda s: None)

    class DeadChild:
        pid = 4242
        returncode = 1

        def poll(self):
            return 1
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: DeadChild())
    c = GSASClient(fallback_to_subprocess=False)
    monkeypatch.setattr(c, "is_server_available", lambda: False)
    result = c.submit_simulation(RECIPE, tmp_path, auto_start_server=True)
    assert result["status"] == "failed" and result["failure"]["reason"] == "server_unavailable"
    msg = result["failure"]["message"]
    assert "exited" in msg and "server.log" in msg


def test_start_error_is_reset_between_attempts(monkeypatch, tmp_path):
    c = GSASClient()
    c._start_error = "stale"
    monkeypatch.setenv("POWDERLINE_NO_SERVER", "1")
    assert c._start_server_background(verbose=False) is False
    assert c._start_error is None  # the disabled case is not an error worth repeating


# --- re/17 H7: a server running older code than this checkout is stale ------------------------------------

def _health_body(**over):
    import powderline
    body = {"status": "ok", "pid": 1, "uptime_seconds": 1.0, "request_count": 0,
            "powderline_version": powderline.__version__, "code_hash": gsas_server.source_tree_hash()}
    body.update(over)
    return body


def test_server_is_stale_only_when_version_or_hash_differ(monkeypatch, own_endpoint):
    _fake_health(monkeypatch, lambda h: _signed_response("my-token", h, _health_body()))
    assert GSASClient().server_is_stale() is False
    _fake_health(monkeypatch, lambda h: _signed_response("my-token", h, _health_body(code_hash="0" * 32)))
    assert GSASClient().server_is_stale() is True
    _fake_health(monkeypatch, lambda h: _signed_response("my-token", h, _health_body(powderline_version="0.0.1")))
    assert GSASClient().server_is_stale() is True


def test_server_without_the_fields_is_stale(monkeypatch, own_endpoint):
    """A server from before re/17 reports neither field: it is older than this code by definition."""
    _fake_health(monkeypatch, lambda h: _signed_response("my-token", h, {"status": "ok"}))
    assert GSASClient().server_is_stale() is True


def test_unreachable_health_is_unknown_not_stale(monkeypatch, tmp_path):
    monkeypatch.setattr(gsas_server, "state_dir", lambda: tmp_path)  # no endpoint at all
    assert GSASClient().server_is_stale() is None


def test_stale_server_falls_back_in_process_in_auto_mode(client, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(client, "server_is_stale", lambda: True)
    monkeypatch.setattr(client, "_submit_to_server", lambda rd: pytest.fail("a stale server must not run the job"))
    calls = []
    monkeypatch.setattr(client, "_submit_via_subprocess",
                        lambda rd, od, verbose: calls.append(1) or {"status": "ok"})
    result = client.submit_simulation(RECIPE, tmp_path)
    assert calls and result["method"] == "subprocess"
    out = capsys.readouterr().out
    assert "stale" in out and "gsas-server restart" in out


def test_stale_server_with_fallback_disabled_is_server_unavailable(monkeypatch, tmp_path):
    c = GSASClient(fallback_to_subprocess=False)
    monkeypatch.setattr(c, "is_server_available", lambda: True)
    monkeypatch.setattr(c, "server_is_stale", lambda: True)
    monkeypatch.setattr(c, "_submit_to_server", lambda rd: pytest.fail("a stale server must not run the job"))
    monkeypatch.setattr(c, "_submit_via_subprocess", lambda rd, od, verbose: pytest.fail("must not fall back"))
    result = c.submit_simulation(RECIPE, tmp_path)
    assert result["status"] == "failed" and result["failure"]["reason"] == "server_unavailable"
    assert "stale" in result["failure"]["message"] and "gsas-server restart" in result["failure"]["message"]


def test_current_server_is_used(client, monkeypatch, tmp_path):
    monkeypatch.setattr(client, "server_is_stale", lambda: False)
    monkeypatch.setattr(client, "_submit_to_server", lambda rd: {"status": "ok"})
    monkeypatch.setattr(client, "_submit_via_subprocess", lambda rd, od, verbose: pytest.fail("server was current"))
    assert client.submit_simulation(RECIPE, tmp_path)["method"] == "server"


# --- re/19 (KI-12, P-42): the server's files travel in the response; the client writes them locally ----------

def _b64(text):
    import base64
    return base64.b64encode(text.encode()).decode("ascii")


def _server_envelope(status="ok", files=None, **over):
    env = {"status": status, "method": "server", "envelope_version": "1"}
    if status == "failed":
        env = results.failure_envelope("engine", "diverged", "the pattern diverged", method="server")
    env["files"] = files if files is not None else {"dummy.lst": _b64("lst text"), "fit_profile.txt": _b64("profile")}
    env["output_files"] = sorted(env["files"])
    env.update(over)
    return env


def test_server_files_are_written_into_the_clients_output_dir(client, monkeypatch, tmp_path):
    monkeypatch.setattr(client, "_submit_to_server", lambda rd: _server_envelope())
    monkeypatch.setattr(client, "_submit_via_subprocess", lambda rd, od, verbose: pytest.fail("must not fall back"))
    out = tmp_path / "never" / "seen" / "by" / "the" / "server"
    result = client.submit_simulation(RECIPE, out)
    assert (out / "dummy.lst").read_text() == "lst text" and (out / "fit_profile.txt").read_text() == "profile"
    assert result["output_files"] == [str((out / n).resolve()) for n in ("dummy.lst", "fit_profile.txt")]
    assert "files" not in result and result["method"] == "server" and result["status"] == "ok"


def test_failed_server_envelope_still_materialises(client, monkeypatch, tmp_path):
    monkeypatch.setattr(client, "_submit_to_server", lambda rd: _server_envelope(status="failed",
                                                                                 files={"dummy.lst": _b64("why")}))
    monkeypatch.setattr(client, "_submit_via_subprocess", lambda rd, od, verbose: pytest.fail("a failed run is final"))
    result = client.submit_simulation(RECIPE, tmp_path / "out")
    assert result["status"] == "failed" and result["failure"]["reason"] == "diverged"
    assert (tmp_path / "out" / "dummy.lst").read_text() == "why"
    assert result["output_files"] == [str((tmp_path / "out" / "dummy.lst").resolve())] and "files" not in result


@pytest.mark.parametrize("name", ["../x", "a/b", "a\\b", "", ".", "/abs"])
def test_bad_file_names_are_refused(monkeypatch, tmp_path, name):
    c = GSASClient(fallback_to_subprocess=False)
    monkeypatch.setattr(c, "is_server_available", lambda: True)
    monkeypatch.setattr(c, "server_is_stale", lambda: False)
    monkeypatch.setattr(c, "_submit_to_server", lambda rd: _server_envelope(files={name: _b64("x"), "ok.txt": _b64("y")}))
    result = c.submit_simulation(RECIPE, tmp_path / "out")
    assert result["status"] == "failed" and result["failure"]["reason"] == "communication_failed"
    assert not (tmp_path / "out").exists(), "nothing may be written when any name is bad"


def test_bad_base64_is_communication_failed(monkeypatch, tmp_path):
    c = GSASClient(fallback_to_subprocess=False)
    monkeypatch.setattr(c, "is_server_available", lambda: True)
    monkeypatch.setattr(c, "server_is_stale", lambda: False)
    monkeypatch.setattr(c, "_submit_to_server", lambda rd: _server_envelope(files={"dummy.lst": "@@not base64@@"}))
    result = c.submit_simulation(RECIPE, tmp_path / "out")
    assert result["status"] == "failed" and result["failure"]["reason"] == "communication_failed"


def test_oversized_transfer_is_communication_failed(monkeypatch, tmp_path):
    from powderline.gateways.gsasii import client as client_module
    monkeypatch.setattr(client_module, "MAX_TRANSFER_BYTES", 4)
    c = GSASClient(fallback_to_subprocess=False)
    monkeypatch.setattr(c, "is_server_available", lambda: True)
    monkeypatch.setattr(c, "server_is_stale", lambda: False)
    monkeypatch.setattr(c, "_submit_to_server", lambda rd: _server_envelope())
    result = c.submit_simulation(RECIPE, tmp_path / "out")
    assert result["status"] == "failed" and result["failure"]["reason"] == "communication_failed"
    assert "MAX_TRANSFER_BYTES" in result["failure"]["message"] or "too large" in result["failure"]["message"]


def test_protocol_failure_falls_back_in_process_when_allowed(client, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(client, "_submit_to_server", lambda rd: _server_envelope(files={"../x": _b64("x")}))
    calls = []
    monkeypatch.setattr(client, "_submit_via_subprocess", lambda rd, od, verbose: calls.append(1) or {"status": "ok"})
    result = client.submit_simulation(RECIPE, tmp_path / "out")
    assert calls and result["method"] == "subprocess"


def test_unwritable_output_dir_is_backend_error(client, monkeypatch, tmp_path):
    monkeypatch.setattr(client, "_submit_to_server", lambda rd: _server_envelope())
    monkeypatch.setattr(client, "_submit_via_subprocess", lambda rd, od, verbose: pytest.fail("a local disk problem is not the server's"))
    blocker = tmp_path / "out"
    blocker.write_text("I am a file, not a directory")
    result = client.submit_simulation(RECIPE, blocker)
    assert result["status"] == "failed" and result["failure"]["reason"] == "backend_error"
    assert str(blocker) in result["failure"]["message"]


def test_output_not_visible_reason_is_gone():
    assert "output_not_visible" not in results.BACKEND_REASONS


# --- re/19 review fixes ---------------------------------------------------------------------------------------

@pytest.mark.parametrize("name", ["a\x00b", "CON", "con.txt", "x.", "x "])
def test_null_bytes_and_windows_reserved_names_are_refused(monkeypatch, tmp_path, name):
    c = GSASClient(fallback_to_subprocess=False)
    monkeypatch.setattr(c, "is_server_available", lambda: True)
    monkeypatch.setattr(c, "server_is_stale", lambda: False)
    monkeypatch.setattr(c, "_submit_to_server", lambda rd: _server_envelope(files={name: _b64("x")}))
    result = c.submit_simulation(RECIPE, tmp_path / "out")
    assert result["status"] == "failed" and result["failure"]["reason"] == "communication_failed"
    assert not (tmp_path / "out").exists()


def test_failed_write_leaves_no_part_file(client, monkeypatch, tmp_path):
    from powderline.gateways.gsasii import client as client_module
    monkeypatch.setattr(client, "_submit_to_server", lambda rd: _server_envelope(files={"dummy.lst": _b64("x")}))
    monkeypatch.setattr(client, "_submit_via_subprocess", lambda rd, od, verbose: pytest.fail("a local disk problem is not the server's"))

    def broken_replace(src, dst):
        raise OSError("disk full")
    monkeypatch.setattr(client_module.os, "replace", broken_replace)
    result = client.submit_simulation(RECIPE, tmp_path / "out")
    assert result["status"] == "failed" and result["failure"]["reason"] == "backend_error"
    assert not list((tmp_path / "out").glob("*.part")), "a half-written file must not be left behind"
