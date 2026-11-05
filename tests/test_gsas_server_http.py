"""Tests for GSAS-II server HTTP endpoints.

These tests verify that the FastAPI server exposes the correct HTTP API,
handles requests properly, and rejects callers that do not hold its token.

These are integration tests: the module fixture starts a real server in a
private, per-test state directory (via ``XDG_RUNTIME_DIR`` / ``LOCALAPPDATA``),
so it never touches — or reuses — the developer's own server, and reads the
server's port and secret token from that directory. They skip if the server
cannot start (e.g. GSAS-II unavailable).
"""

import json
import secrets
import pytest

pytestmark = [pytest.mark.gsasii, pytest.mark.slow]
import time
import subprocess
import sys
from pathlib import Path
import os

from powderline.gateways.gsasii import server as gsas_server
from powderline.gateways.gsasii.client import GSASClient


def _endpoint_in(state_root: Path):
    """The endpoint (pid/port/token) the server wrote under ``state_root``."""
    try:
        return json.loads((state_root / 'powderline' / 'server.json').read_text())
    except (OSError, ValueError):
        return None


def _signed(port: int, token: str, method: str, path: str, payload=None):
    """Send a request signed with ``token``; the response signature is verified
    (raises ``ServerIdentityError`` otherwise)."""
    return GSASClient._signed_request({'pid': 0, 'port': port, 'token': token},
                                      method, path, payload, timeout=5.0)


def _health_ok(port: int, token: str) -> bool:
    try:
        return _signed(port, token, 'GET', '/health').status_code == 200
    except Exception:
        return False


@pytest.fixture(scope="module")
def server_state_root(tmp_path_factory):
    """A private (0700) directory standing in for this user's runtime dir."""
    root = tmp_path_factory.mktemp("server_state")
    root.chmod(0o700)
    return root


@pytest.fixture(scope="module")
def test_server(server_state_root):
    """Start a server in an isolated state dir; yield ``(port, token)``."""
    src_dir = Path(__file__).parent.parent / 'src'
    server_script = src_dir / 'powderline' / 'gateways' / 'gsasii' / 'server.py'

    if not server_script.exists():
        pytest.skip(f"Server script not found: {server_script}")

    env = os.environ.copy()
    env['PYTHONPATH'] = str(src_dir) + os.pathsep + env.get('PYTHONPATH', '')
    env['XDG_RUNTIME_DIR'] = str(server_state_root)   # POSIX state dir
    env['LOCALAPPDATA'] = str(server_state_root)      # Windows state dir
    env.pop('POWDERLINE_NO_SERVER', None)
    env.pop('POWDERLINE_SERVER_PORT', None)           # exercise the ephemeral port

    proc = subprocess.Popen(
        [sys.executable, str(server_script), 'start'],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    # Wait for server to start (up to 30 seconds for GSAS-II import)
    endpoint = None
    for attempt in range(300):
        time.sleep(0.1)
        endpoint = _endpoint_in(server_state_root)
        if endpoint and _health_ok(endpoint['port'], endpoint['token']):
            break
        if proc.poll() is not None:
            pytest.skip(f"Test server exited unexpectedly (exit code: {proc.returncode})")
    else:
        proc.kill()
        pytest.skip("Test server failed to start within 30 seconds")

    yield endpoint['port'], endpoint['token']

    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


def test_health_endpoint(test_server):
    """Test /health endpoint returns correct format."""
    import httpx

    port, token = test_server
    resp = _signed(port, token, 'GET', '/health')

    assert resp.status_code == 200, "Health endpoint should return 200"

    data = resp.json()
    assert "status" in data, "Response should contain 'status' field"
    assert data["status"] == "ok", "Status should be 'ok'"
    assert "pid" in data, "Response should contain 'pid' field"
    assert "uptime_seconds" in data, "Response should contain 'uptime_seconds' field"
    assert "request_count" in data, "Response should contain 'request_count' field"

    assert isinstance(data["pid"], int), "PID should be integer"
    assert data["pid"] > 0, "PID should be positive"
    assert data["uptime_seconds"] >= 0, "Uptime should be non-negative"
    assert data["request_count"] >= 0, "Request count should be non-negative"


def test_health_endpoint_format(test_server):
    """Verify health endpoint returns proper JSON structure."""
    import httpx

    port, token = test_server
    resp = _signed(port, token, 'GET', '/health')

    # Verify response is valid JSON
    data = resp.json()

    # Verify all expected fields are present
    required_fields = {"status", "pid", "uptime_seconds", "request_count", "powderline_version", "code_hash"}
    assert required_fields.issubset(data.keys()), \
        f"Missing required fields: {required_fields - data.keys()}"


def test_simulate_endpoint_missing_fields(test_server):
    """Test /simulate endpoint validates required fields."""
    import httpx

    port, token = test_server

    # Missing recipe_data
    resp = _signed(port, token, 'POST', '/simulate', {"verbose": True}
    )
    assert resp.status_code == 422, "Should return validation error for missing recipe_data"

    # output_dir is no longer part of the request (re/19, KI-12): the server's filesystem is not the client's
    resp = _signed(port, token, 'POST', '/simulate', {"recipe_data": {}, "output_dir": "/tmp/test"}
    )
    assert resp.status_code == 422, "Should refuse a request naming an output directory"

    # Empty request
    resp = _signed(port, token, 'POST', '/simulate', {}
    )
    assert resp.status_code == 422, "Should return validation error for empty request"


def test_simulate_endpoint_invalid_recipe(test_server):
    """Test /simulate endpoint handles invalid recipe_data gracefully."""
    import httpx

    port, token = test_server

    # Invalid (empty) recipe_data — server should return 200 with a failed envelope
    resp = _signed(port, token, 'POST', '/simulate', {"recipe_data": {}})

    assert resp.status_code == 200, "Should return 200 even for errors (error in response body)"
    data = resp.json()

    assert data["status"] == "failed" and data["envelope_version"] == "1"
    assert data["failure"]["kind"] == "backend" and data["failure"]["reason"] == "backend_error"
    msg = data["failure"]["message"].lower()
    assert "recipe" in msg or "validation" in msg, "the message should mention recipe validation failure"


def test_simulate_endpoint_optional_verbose(test_server):
    """Test /simulate endpoint accepts optional verbose parameter."""
    import httpx

    port, token = test_server

    # Request with verbose=true — should accept and return 200 (even if recipe invalid)
    resp = _signed(port, token, 'POST', '/simulate', {"recipe_data": {}, "verbose": True})
    assert resp.status_code == 200, "Should accept verbose parameter"

    # Request with verbose=false
    resp = _signed(port, token, 'POST', '/simulate', {"recipe_data": {}, "verbose": False})
    assert resp.status_code == 200, "Should accept verbose parameter"


def test_health_endpoint_performance(test_server):
    """Test that health endpoint responds quickly."""
    import httpx

    port, token = test_server

    start = time.time()
    resp = _signed(port, token, 'GET', '/health')
    elapsed = time.time() - start

    assert resp.status_code == 200
    assert elapsed < 0.1, f"Health check should be fast, took {elapsed:.2f}s"


def test_multiple_health_checks(test_server):
    """Test that multiple health checks work correctly."""
    import httpx

    port, token = test_server

    # Multiple rapid health checks
    for _ in range(10):
        resp = _signed(port, token, 'GET', '/health')
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"


def test_server_increments_request_count(test_server):
    """Test that server tracks request count correctly."""
    import httpx

    port, token = test_server

    # Get initial count (might not be 0 due to startup checks)
    resp = _signed(port, token, 'GET', '/health')
    initial_count = resp.json()["request_count"]

    # Make a simulation request (will fail validation but should still increment counter)
    _signed(port, token, 'POST', '/simulate', {"recipe_data": {}})

    # Check count increased
    resp = _signed(port, token, 'GET', '/health')
    new_count = resp.json()["request_count"]

    assert new_count > initial_count, "Request count should increment after simulation request"


# --- Multi-user safety: only the token holder can use the server ---

def _forged_headers(token: str, method: str, path: str, body: bytes) -> dict:
    """Headers signed with ``token`` (here: a token that is not the server's)."""
    nonce, ts = secrets.token_hex(16), str(int(time.time()))
    return {gsas_server.NONCE_HEADER: nonce, gsas_server.TIMESTAMP_HEADER: ts,
            gsas_server.SIGNATURE_HEADER: gsas_server.sign_request(
                token, method, path, b'', nonce, ts, body),
            "Content-Type": "application/json"}


def test_requests_without_token_rejected(test_server, server_state_root):
    """Unsigned, bearer-style, or wrongly signed requests -> 401 on every route,
    and no job directory is created."""
    import httpx

    port, token = test_server
    body = json.dumps({"recipe_data": {}}).encode()
    for headers in ({},
                    {"Authorization": f"Bearer {token}"},  # the old scheme: refused
                    _forged_headers("not-the-token", "POST", "/simulate", body)):
        resp = httpx.post(f"http://127.0.0.1:{port}/simulate", headers=headers,
                          content=body, timeout=5.0, trust_env=False)
        assert resp.status_code == 401
        resp = httpx.get(f"http://127.0.0.1:{port}/health", headers=headers,
                         timeout=2.0, trust_env=False)
        assert resp.status_code == 401
        assert "pid" not in resp.text
        assert gsas_server.RESPONSE_SIGNATURE_HEADER not in resp.headers
    assert not list((server_state_root / "powderline").glob("job-*")), \
        "an unauthenticated request must not start a job"


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
def test_state_files_are_owner_only(test_server, server_state_root):
    state = server_state_root / "powderline"
    assert (state.stat().st_mode & 0o777) == 0o700
    for name in ("server.json", "server.pid", "server.lock", "server.log"):
        assert (state / name).stat().st_mode & 0o777 == 0o600, name


def test_live_server_holds_start_lock(test_server, server_state_root, monkeypatch):
    """A second start is refused while the server runs; status sees it running."""
    monkeypatch.setattr(gsas_server, "state_dir", lambda: server_state_root / "powderline")
    assert gsas_server.is_server_running() is True
    assert gsas_server._claim_server_lock(attempts=2, delay=0) is False


def test_client_uses_own_server(test_server, server_state_root, monkeypatch):
    monkeypatch.delenv("POWDERLINE_NO_SERVER", raising=False)
    monkeypatch.setattr(gsas_server, "state_dir", lambda: server_state_root / "powderline")
    assert GSASClient().is_server_available() is True


def test_client_ignores_another_users_server(test_server, tmp_path, monkeypatch):
    """A client whose state dir lacks the token never treats the server as its own,
    even when it knows the port (here: a forged endpoint with a guessed token)."""
    port, _ = test_server
    monkeypatch.setattr(gsas_server, "state_dir", lambda: tmp_path)
    client = GSASClient()
    assert client.is_server_available() is False

    (tmp_path / "server.json").write_text(
        json.dumps({"pid": os.getpid(), "port": port, "token": "guessed"}))
    assert client.is_server_available() is False
    with pytest.raises(Exception):
        client._submit_to_server({})


def test_refinement_through_authenticated_server(test_server, server_state_root,
                                                 monkeypatch, recipe_LaB6_dict, tmp_path):
    """End to end: the owner's client runs a real refinement via the server."""
    monkeypatch.delenv("POWDERLINE_NO_SERVER", raising=False)
    monkeypatch.setattr(gsas_server, "state_dir", lambda: server_state_root / "powderline")
    client = GSASClient(fallback_to_subprocess=False)
    result = client.submit_simulation(recipe_LaB6_dict, tmp_path, auto_start_server=False)
    assert result["status"] == "ok", result.get("failure")
    assert result["envelope_version"] == "1" and result["converged"] in (True, False, None)
    assert result["method"] == "server"
    # re/19 (KI-12): the files came back in the response and were written here; the server kept nothing
    for name in ("fit_profile.txt", "refined_parameters.csv", "dummy.lst", "dummy.gpx"):
        assert (tmp_path / name).exists(), name
    assert "files" not in result
    assert all(Path(f).parent == tmp_path.resolve() for f in result["output_files"]), result["output_files"]
    assert not list((server_state_root / "powderline").glob("job-*")), "the server's scratch dir must be gone"


def test_engine_failure_through_authenticated_server(test_server, server_state_root, monkeypatch,
                                                     recipe_LaB6_dict, tmp_path):
    """R30 inside the server process: a site GSAS-II misreads (EB-40) raises in the server's run_refinement,
    the server answers a failed envelope, and the client returns it (no fallback) — re/12 spec §7."""
    import copy
    monkeypatch.delenv("POWDERLINE_NO_SERVER", raising=False)
    monkeypatch.setattr(gsas_server, "state_dir", lambda: server_state_root / "powderline")
    recipe = copy.deepcopy(recipe_LaB6_dict)
    recipe["payload"]["background"].pop("single_peaks", None)
    p = lambda v, f=False: [v, f]  # noqa: E731
    recipe["payload"]["phases"] = {"P": {
        "space_group": "R -3 m:H",
        "unit_cell": {k: p(v) for k, v in zip(("a", "b", "c", "alpha", "beta", "gamma"), (5.0, 5.0, 12.0, 90.0, 90.0, 120.0))},
        "atoms": {"Fe": {"element": "Fe", "x": p(0.0), "y": p(0.333333), "z": p(0.166667),
                         "occupancy": p(1.0), "ADP": "Uiso", "Uiso": p(0.01)}},
        "scale": p(1.0)}}
    client = GSASClient(fallback_to_subprocess=False)
    result = client.submit_simulation(recipe, tmp_path, auto_start_server=False)
    assert result["status"] == "failed" and result["method"] == "server"
    assert result["failure"]["kind"] == "engine" and result["failure"]["reason"] == "unusable_site"
    assert "state the equivalent position" in result["failure"]["message"]
    assert result["failure"]["traceback"]  # the raise site travels with the envelope
    assert not (tmp_path / "dummy.lst").exists()  # refused before GSAS-II refined anything


def test_a_failed_server_job_leaves_the_engine_files_and_failure_json_locally(test_server, server_state_root, monkeypatch, tmp_path):
    """re/30 through the server: the job's GSAS-II files travel back (re/19) and powderline.run() records the failure
    locally; no result table exists for the failed run."""
    import json
    import powderline
    from powderline.exceptions import EngineExecutionError
    monkeypatch.delenv("POWDERLINE_NO_SERVER", raising=False)
    monkeypatch.setattr(gsas_server, "state_dir", lambda: server_state_root / "powderline")
    repo = Path(__file__).parent.parent
    recipe = json.loads((repo / 'examples' / 'example_LaB6_textured' / 'input.json').read_text(encoding='utf-8'))
    recipe['payload']['phases']['LaB6']['preferred_orientation']['ratio'] = [1.0, True]      # GSAS-II aborts (EB-99)
    out = tmp_path / 'out'
    with pytest.raises(EngineExecutionError) as info:
        powderline.run(recipe, out, execution_mode='server')
    assert info.value.reason == 'diverged' and info.value.result['method'] == 'server'
    names = {p.name for p in out.iterdir()}
    assert {'dummy.gpx', 'dummy.lst', 'failure.json'} <= names
    assert not names & {'refined_parameters.csv', 'LaB6_unit_cell_report.csv', 'LaB6_peak_list_report.csv',
                        'fit_profile.txt', 'output_recipe.json', 'parameter_dispositions.csv'}, sorted(names)
    record = json.loads((out / 'failure.json').read_text(encoding='utf-8'))
    assert record['failure']['reason'] == 'diverged' and record['powderline_provenance']['schema_name'] == 'gsasii.rietveld'
