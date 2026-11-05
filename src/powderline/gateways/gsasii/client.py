"""Client library for GSAS-II server communication.

Provides a simple API for submitting simulations to the GSAS-II server.
Automatically falls back to in-process execution when the server is not
running or is stale. The server never sees this process's filesystem: its
output files come back inside the signed response and are written into
``output_dir`` here (re/19, KI-12), so a server on another node or in a
container works like a local one.

Every outcome is an *envelope* (:mod:`powderline.results`): ``ok`` from the
server or the in-process run, ``failed`` for a backend problem (server
unavailable, disabled, timed out, a malformed transfer, a local write
failure) or an engine failure relayed from the server. The client never raises for an application outcome;
the gsasii gateway raises from the envelope (re/12).

Only the calling user's own server is ever used: its port and secret token
are read from the user's private state directory. The token itself is never
sent; every request is signed with it and every response must carry a valid
signature, so a listener that does not hold the token (e.g. another user's
process on the port of a crashed server) is never trusted — it learns nothing
it could replay and cannot fake a result. ``POWDERLINE_NO_SERVER`` disables
server use entirely (see :func:`powderline.gateways.gsasii.server.server_disabled`).
"""

import json
import secrets
import subprocess
import sys
import os
from pathlib import Path
from typing import Dict, Any, Optional

from powderline import results as envelopes
from powderline.exceptions import EngineExecutionError
from powderline.gateways.gsasii import server as gsas_server
from powderline.gateways.gsasii.server import (
    HOST,
    MAX_BODY_BYTES,
    NO_SERVER_ENV,
    NO_SERVER_MESSAGE,
    NONCE_HEADER,
    RESPONSE_SIGNATURE_HEADER,
    SIGNATURE_HEADER,
    TIMESTAMP_HEADER,
    ServerStateError,
    read_endpoint,
    server_disabled,
    sign_request,
    sign_response,
)


class ServerIdentityError(RuntimeError):
    """A response was not signed with this user's server token."""


class ServerRejectedRequest(RuntimeError):
    """The server refused the request before handling it (its 401/413 replies are deliberately unsigned)."""


#: The most a server may hand back in one response, decoded (re/19, KI-12); beyond it the run is a
#: ``communication_failed`` and nothing is written.
MAX_TRANSFER_BYTES = 512 * 1024 * 1024


_WINDOWS_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}


def _safe_file_name(name) -> bool:
    """A bare file name the server may send on every platform: no separators or NUL, not empty, not
    ``.``/``..``, no trailing dot or space, not a Windows device name (``CON``, ``LPT1`` ...)."""
    if not isinstance(name, str) or name in ("", ".", ".."):
        return False
    if "/" in name or "\\" in name or "\x00" in name or os.path.basename(name) != name:
        return False
    if name[-1] in ". " or name.split(".")[0].lower() in _WINDOWS_RESERVED:
        return False
    return True


def _write_file(path: Path, data: bytes) -> None:
    """Write ``data`` to ``path`` atomically: a temp file beside it, then replace (retried on Windows).
    A failure leaves no ``.part`` file behind."""
    tmp = path.with_name(path.name + ".part")
    try:
        tmp.write_bytes(data)
        gsas_server._retry_file_op(lambda: os.replace(tmp, path), f"replace {path.name}")
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


#: Time limit (s) on the connect, write and pool phases of a ``/simulate`` request: loopback, so generous.
#: The read phase is the refinement itself and is bounded only by ``GSASClient(request_timeout=...)``.
REQUEST_PHASE_TIMEOUT = 30.0


class GSASClient:
    """Client for communicating with GSAS-II server."""

    def __init__(self, fallback_to_subprocess: bool = True, request_timeout: Optional[float] = None):
        """Initialize client.

        Args:
            fallback_to_subprocess: If True, use subprocess when server unavailable
            request_timeout: seconds to wait for the server's answer to a submitted job
                (the read phase of the ``/simulate`` request). ``None``: no limit, as for
                an in-process run. A limit does not free the server: the job keeps running
                there, which is why a timeout never falls back in-process.
        """
        self.fallback_to_subprocess = fallback_to_subprocess
        self.request_timeout = request_timeout
        self._state_warning_shown = False
        self._start_error: Optional[str] = None  # why the last auto-start could not even be attempted

    def _endpoint(self) -> Optional[Dict[str, Any]]:
        """This user's live server endpoint (``pid``/``port``/``token``), or None.

        An endpoint whose recorded server process is gone is stale (the server
        crashed without cleaning up) and is ignored.
        """
        try:
            endpoint = read_endpoint()
        except ServerStateError as e:
            if not self._state_warning_shown:
                print(f"   WARNING: {e}")
                self._state_warning_shown = True
            return None
        if endpoint is not None and not gsas_server._pid_alive(endpoint['pid']):
            return None
        return endpoint

    @staticmethod
    def _signed_request(endpoint: Dict[str, Any], method: str, path: str,
                        payload: Optional[dict] = None, timeout: float = 2.0):
        """Send a request signed with the endpoint's token; verify the response.

        The token never leaves this process: the request carries a fresh
        nonce, a timestamp and an HMAC, and the response must be signed over
        that nonce, its status and its body.

        Raises:
            ServerIdentityError: If the response is not signed by the token holder.
            httpx.HTTPError: On connection/transport errors.
        """
        import httpx
        import time

        body = b'' if payload is None else json.dumps(payload).encode()
        nonce = secrets.token_hex(16)
        timestamp = str(int(time.time()))
        token = endpoint['token']
        headers = {
            NONCE_HEADER: nonce,
            TIMESTAMP_HEADER: timestamp,
            SIGNATURE_HEADER: sign_request(token, method, path, b'', nonce, timestamp, body),
        }
        url = f"http://{HOST}:{endpoint['port']}{path}"
        # trust_env=False: loopback only, never route via a proxy
        if method == 'GET':
            resp = httpx.get(url, headers=headers, timeout=timeout, trust_env=False)
        else:
            headers['Content-Type'] = 'application/json'
            resp = httpx.post(url, content=body, headers=headers, timeout=timeout,
                              trust_env=False)
        got = resp.headers.get(RESPONSE_SIGNATURE_HEADER, '')
        if not got and resp.status_code in (401, 413):
            # The middleware's own refusals are sent unsigned on purpose (nothing is served unauthenticated);
            # report them for what they are instead of as an impostor listener (re/14).
            if resp.status_code == 413:
                raise ServerRejectedRequest(
                    f"the GSAS-II server rejected the request as too large ({len(body)} bytes; the limit is "
                    f"{MAX_BODY_BYTES} bytes): reduce the recipe's embedded data, or run in-process")
            raise ServerRejectedRequest(
                "the GSAS-II server rejected the request as unauthenticated: its token does not match this "
                "client's (a restarted server? stop it with `pixi run -e gsasii gsas-server stop` and retry; the run starts a fresh one)")
        expected = sign_response(token, nonce, resp.status_code, resp.content)
        if not secrets.compare_digest(got.encode('utf-8', 'replace'), expected.encode()):
            raise ServerIdentityError(
                f"The listener on port {endpoint['port']} did not prove it is your "
                f"GSAS-II server (HTTP {resp.status_code}); not using it.")
        return resp

    def is_server_available(self) -> bool:
        """Check that THIS user's server is up and holds this user's token.

        ``/health`` is sent as a signed request and its response must be
        signed with the token, so a listener that does not know the token
        (e.g. another user's process on a recycled port) is never treated as
        available. Always False when ``POWDERLINE_NO_SERVER`` is set.
        """
        import httpx

        if server_disabled():
            return False
        endpoint = self._endpoint()
        if endpoint is None:
            return False
        try:
            resp = self._signed_request(endpoint, 'GET', '/health', timeout=2.0)
        except (httpx.HTTPError, OSError, ServerIdentityError, ServerRejectedRequest):
            return False  # a 401 on /health = a listener that does not hold our token: not available
        return resp.status_code == 200

    def _health(self) -> Optional[Dict[str, Any]]:
        """The signed ``/health`` body of this user's server, or None when it cannot be read."""
        import httpx

        if server_disabled():
            return None
        endpoint = self._endpoint()
        if endpoint is None:
            return None
        try:
            resp = self._signed_request(endpoint, 'GET', '/health', timeout=2.0)
            if resp.status_code != 200:
                return None
            body = resp.json()
        except (httpx.HTTPError, OSError, ValueError, ServerIdentityError, ServerRejectedRequest):
            return None
        return body if isinstance(body, dict) else None

    def server_is_stale(self) -> Optional[bool]:
        """Whether the server runs other code than this process (re/17 H7).

        True when its ``/health`` reports a different PowderLine version or source-tree hash
        (:func:`server.source_tree_hash`) -- or neither field, which only a server from before
        this check does; False when both match; None when ``/health`` cannot be read.
        """
        from powderline import __version__

        health = self._health()
        if health is None:
            return None
        return (health.get("code_hash") != gsas_server.source_tree_hash()
                or health.get("powderline_version") != __version__)

    STALE_SERVER_MESSAGE = (
        "GSAS-II server is stale: it runs other PowderLine code (version or source tree) than this "
        "process, and it caches its modules. Stop it with: pixi run -e gsasii gsas-server stop (the next run starts a fresh one)"
    )

    def _handle_stale_server(self) -> Dict[str, Any] | None:
        """Warn about a stale server; None when the caller may fall back in-process, else the failure envelope."""
        print("   WARNING: the GSAS-II server is stale (it runs other PowderLine code than this process).")
        if self.fallback_to_subprocess:
            print("   Falling back to in-process execution. To fix the server: pixi run -e gsasii gsas-server stop (the next run starts a fresh one)")
            return None
        print("   In-process fallback is disabled. To fix the server: pixi run -e gsasii gsas-server stop (the next run starts a fresh one)")
        return envelopes.failure_envelope("backend", "server_unavailable", self.STALE_SERVER_MESSAGE, method="none")

    def _server_attempt(self, recipe_dict: dict, output_dir: Path, verbose: bool) -> Dict[str, Any] | None:
        """One submission to a server that answered ``/health``; the same rules on every branch (re/12).

        Returns the envelope to hand back (``ok``, the server's own ``failed`` one, a ``timeout`` or
        ``communication_failed`` backend failure), or ``None`` when the caller may fall back in-process
        (a transport or transfer problem with fallback enabled). A timeout never falls back: the job is
        still running on the server, its late answer would be discarded and a second run would double
        the work.
        """
        import httpx

        try:
            result = self._submit_to_server(recipe_dict)
        except httpx.TimeoutException as e:
            return envelopes.failure_envelope(
                "backend", "timeout",
                f"the GSAS-II server did not answer within server_timeout ({e}); not falling back "
                f"in-process because the job is still running on the server (a second run would double the work)",
                method="server")
        except Exception as e:
            if not self.fallback_to_subprocess:
                return envelopes.failure_envelope("backend", "communication_failed",
                                                  f"Server communication failed: {e}", method="server")
            if verbose:
                print(f"Server communication failed: {e}")
                print("   Falling back to subprocess mode...")
            return None
        result['method'] = 'server'
        result = self._materialize(result, output_dir)
        if (result.get('status') == 'failed' and result['failure']['reason'] == 'communication_failed'
                and self.fallback_to_subprocess):
            print(f"   WARNING: {result['failure']['message']}")
            print("   Falling back to in-process execution.")
            return None  # a protocol problem with the server; the job itself can still run here
        return result

    def _materialize(self, result: Dict[str, Any], output_dir: Path) -> Dict[str, Any]:
        """Write the files a server envelope carries into ``output_dir`` (re/19, KI-12).

        The server never sees the client's filesystem: its envelope lists every output file under
        ``files`` (name -> base64). Names are checked (bare file names only), the contents decoded
        and size-capped before anything is written, then each file is written atomically (temp +
        replace, retried on Windows sharing violations). ``output_files`` becomes the local paths and
        ``files`` leaves the envelope. A bad name, bad base64 or an oversized transfer is
        ``communication_failed``; a local write failure is ``backend_error`` naming the directory.
        """
        import base64
        import binascii

        files = result.pop('files', None) or {}
        output_dir = Path(output_dir)
        decoded: Dict[str, bytes] = {}
        total = 0
        for name, blob in files.items():
            if not _safe_file_name(name):
                return envelopes.failure_envelope(
                    "backend", "communication_failed",
                    f"the GSAS-II server sent a file with an unacceptable name {name!r}; nothing was written",
                    method="server")
            try:
                data = base64.b64decode(blob, validate=True)
            except (binascii.Error, TypeError, ValueError) as e:
                return envelopes.failure_envelope(
                    "backend", "communication_failed",
                    f"the GSAS-II server's copy of {name!r} could not be decoded ({e}); nothing was written",
                    method="server")
            total += len(data)
            if total > MAX_TRANSFER_BYTES:
                return envelopes.failure_envelope(
                    "backend", "communication_failed",
                    f"the GSAS-II server's output is too large to transfer ({total} bytes so far, "
                    f"limit MAX_TRANSFER_BYTES = {MAX_TRANSFER_BYTES}); nothing was written", method="server")
            decoded[name] = data
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            for name, data in decoded.items():
                _write_file(output_dir / name, data)
        except (OSError, ServerStateError) as e:
            return envelopes.failure_envelope(
                "backend", "backend_error",
                f"the GSAS-II server's result could not be written into {output_dir}: {e}", method="server")
        result['output_files'] = [str((output_dir / name).resolve()) for name in sorted(decoded)]
        return result

    def submit_simulation(self, recipe, output_dir: Path,
                         verbose: bool = False, auto_start_server: bool = True,
                         use_server: bool = True) -> Dict[str, Any]:
        """Submit a simulation request.

        Args:
            recipe: Recipe to run. Accepts:
                - Path: path to a JSON/YAML recipe file (loaded automatically)
                - dict: pre-loaded recipe dictionary
                - a validated recipe model (``GsasiiRietveldRecipe`` / ``GsasiiSpfRecipe``)
            output_dir: Directory for output files
            verbose: If True, print detailed output
            auto_start_server: If True, start server automatically if not running
            use_server: If False, skip the server entirely and run in-process

        Returns:
            An envelope (:mod:`powderline.results`): ``ok`` with the result keys, or ``failed`` with a
            ``failure`` record; ``method`` says which path ran. The client never raises for an
            application outcome; the gateway does (``results.raise_if_failed``).

        Note:
            The server never sees ``output_dir``: its output files travel back
            inside the signed response and are written here (re/19, KI-12), so
            a server on another node or in a container works like a local one.

            With ``POWDERLINE_NO_SERVER`` set, the server is never probed or
            started: the run goes in-process, or — when fallback is disabled
            (``execution_mode='server'``) — returns a structured error.
        """
        result = self._dispatch(recipe, output_dir, verbose, auto_start_server, use_server)
        return _with_validation_warnings(recipe, result)

    def _dispatch(self, recipe, output_dir: Path, verbose: bool, auto_start_server: bool,
                  use_server: bool) -> Dict[str, Any]:
        """Run the recipe on the server or in this process (see :meth:`submit_simulation`)."""
        recipe_dict = self._normalize_recipe(recipe)

        if use_server and server_disabled():
            if not self.fallback_to_subprocess:
                return envelopes.failure_envelope("backend", "server_disabled", NO_SERVER_MESSAGE, method="none")
            print(f"   Using in-process mode ({NO_SERVER_ENV} is set)")
        elif not use_server:
            if not verbose:
                print("   Using in-process mode (use_server=False)")
        # Try server first
        elif self.is_server_available():
            if self.server_is_stale():
                error = self._handle_stale_server()
                if error is not None:
                    return error
                # fall through to in-process fallback below
            else:
                if not verbose:
                    print(f"   Using GSAS-II server mode")
                result = self._server_attempt(recipe_dict, output_dir, verbose)
                if result is not None:
                    return result
                # fall through to in-process fallback below

        # Try to start server if not available and auto_start_server enabled
        elif auto_start_server:
            if verbose:
                print("   Attempting to start server automatically...")
            if self._start_server_background(verbose):
                import time
                time.sleep(1)

                # Try again
                if self.is_server_available():
                    if not verbose:
                        print(f"   Using GSAS-II server mode")
                    result = self._server_attempt(recipe_dict, output_dir, verbose)
                    if result is not None:
                        return result
                    # fall through to in-process fallback below
                else:
                    if verbose:
                        print(f"   Server started but not responding")
                    if not verbose:
                        print(f"   Using subprocess mode (start server with: pixi run gsas-server start)")
            else:
                if not verbose:
                    print(f"   Using subprocess mode (start server with: pixi run gsas-server start)")
        else:
            if not verbose:
                print(f"   Using subprocess mode (start server with: pixi run gsas-server start)")

        # Fallback to subprocess
        if self.fallback_to_subprocess:
            result = self._submit_via_subprocess(recipe_dict, output_dir, verbose)
            result['method'] = 'subprocess'
            return result
        elif not use_server:
            # Explicitly requested state, kept honest: both execution paths
            # were disabled by the caller, so nothing ran.
            return envelopes.failure_envelope(
                "backend", "server_unavailable",
                'No execution path enabled: use_server=False and fallback_to_subprocess=False — enable one of them.',
                method="none")
        else:
            why = f": {self._start_error}" if self._start_error else ""
            return envelopes.failure_envelope("backend", "server_unavailable",
                                              f"Server not available and fallback disabled{why}", method="none")

    @staticmethod
    def _normalize_recipe(recipe) -> dict:
        """Normalize recipe input to a plain JSON-serializable dict.

        Accepts Path (loaded from disk), dict (used as-is), or a validated
        recipe model (serialized via .model_dump). Raises TypeError for unsupported inputs.
        """
        if isinstance(recipe, Path):
            from powderline.recipes import load_recipe_asset  # engine-free; the one loader (review item 28)
            return load_recipe_asset(recipe)
        if isinstance(recipe, dict):
            return recipe
        if hasattr(recipe, 'model_dump'):
            return recipe.model_dump(mode='json')
        raise TypeError(
            f"recipe must be a Path, dict, or validated recipe model, got {type(recipe).__name__}"
        )

    def _start_server_background(self, verbose: bool = False) -> bool:
        """Start server in background process.

        Returns:
            True if server was started, False if already running or failed
        """
        import subprocess
        import os
        import time

        self._start_error = None
        if server_disabled():
            return False
        try:
            gsas_server.state_dir()  # a server could not start with an unsafe state dir
            gsas_server._requested_port()  # nor with a bad POWDERLINE_SERVER_PORT (re/14)
        except ServerStateError as e:
            self._start_error = str(e)
            if verbose:
                print(f"   Could not auto-start server: {e}")
            return False

        # Check if already running
        if self.is_server_available():
            return True

        try:
            # Build command to start server
            src_dir = Path(__file__).parents[3]
            server_script = Path(__file__).parent / 'server.py'

            # Prepare environment
            env = os.environ.copy()
            env['PYTHONPATH'] = str(src_dir) + os.pathsep + env.get('PYTHONPATH', '')

            # Use subprocess to start server in background
            try:
                # Try with preexec_fn (Unix only)
                proc = subprocess.Popen(
                    [sys.executable, str(server_script), 'start'],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    stdin=subprocess.DEVNULL,
                    env=env,
                    preexec_fn=os.setpgrp,  # Detach from parent process group
                    start_new_session=False
                )
            except (TypeError, AttributeError):
                # Fallback for Windows or if preexec_fn not available
                proc = subprocess.Popen(
                    [sys.executable, str(server_script), 'start'],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    stdin=subprocess.DEVNULL,
                    env=env,
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == 'win32' else 0
                )

            # Give server time to start
            for attempt in range(30):  # Wait up to 3 seconds
                time.sleep(0.1)
                if proc.poll() is not None:  # the child died at start (busy port, import error, ...)
                    self._start_error = (f"the server exited at start (exit code {proc.returncode}); see its log: "
                                         f"{gsas_server.log_file()}")
                    if verbose:
                        print(f"   Could not auto-start server: {self._start_error}")
                    return False
                if self.is_server_available():
                    if verbose:
                        print("   Server started in background")
                    return True

            if verbose:
                print(f"   Server started (PID {proc.pid}) but not responding yet")
            return True  # Started even if not responding immediately

        except Exception as e:
            self._start_error = f"could not spawn the server: {e}"
            if verbose:
                print(f"   Could not auto-start server: {e}")
            return False

    def _simulate_timeout(self):
        """The ``/simulate`` request's httpx timeout: ``REQUEST_PHASE_TIMEOUT`` on connect, write and
        pool; ``request_timeout`` on the read phase (the refinement), ``None`` = no limit."""
        import httpx
        return httpx.Timeout(REQUEST_PHASE_TIMEOUT, read=self.request_timeout)

    def _submit_to_server(self, recipe_dict: dict) -> Dict[str, Any]:
        """Submit simulation to server via HTTP with retry logic.

        Retries up to 3 times on connection errors to handle transient network issues.
        """
        import httpx
        import time

        payload = {'recipe_data': recipe_dict}  # no output_dir: the files come back in the response (KI-12)

        # Retry logic for connection errors
        max_retries = 3
        retry_delay = 0.5  # seconds

        last_error = None
        for attempt in range(max_retries):
            # Re-read each attempt: a restarted server has a new port and token.
            endpoint = self._endpoint()
            try:
                if endpoint is None:
                    raise httpx.ConnectError("No GSAS-II server endpoint for this user")
                resp = self._signed_request(endpoint, 'POST', '/simulate',
                                            payload, timeout=self._simulate_timeout())
                resp.raise_for_status()
                return resp.json()
            except httpx.ConnectError as e:
                last_error = e
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                    retry_delay *= 2  # Exponential backoff
                    continue
            except httpx.HTTPStatusError as e:
                # Don't retry on HTTP errors (4xx, 5xx)
                raise
            except httpx.TimeoutException as e:
                # Don't retry on timeout (simulation is running)
                raise

        # If we exhausted all retries, raise the last error
        raise last_error

    def _submit_via_subprocess(self, recipe_dict: dict, output_dir: Path,
                               verbose: bool) -> Dict[str, Any]:
        """Run simulation in-process (fallback mode when server is unavailable).

        **Important**: Despite the method name, this does NOT spawn an OS subprocess.
        It calls ``run_refinement()`` directly in the current process. The name is
        retained for API stability. If hard crash-isolation is needed in a future
        phase, this method can be upgraded to use ``multiprocessing`` internally
        without changing any callers.

        Contrast with ``_start_server_background()``, which *does* spawn an OS
        subprocess to launch the FastAPI server.

        Calls run_refinement() directly in the current process, returning the
        same structured result dict as server mode (fit_profile, unit_cell_data,
        peak_list_data, refined_parameters, rwp, etc.).
        """
        import time
        from powderline.gateways.gsasii.routing import model_from_request, run_refinement
        from pydantic import ValidationError

        output_dir.mkdir(parents=True, exist_ok=True)

        try:
            recipe = model_from_request(recipe_dict)
        except ValidationError as e:
            error_lines = [
                f"{' -> '.join(str(loc) for loc in err['loc'])}: {err['msg']}"
                for err in e.errors()
            ]
            return envelopes.failure_envelope("backend", "backend_error",
                                              "Recipe validation failed:\n" + "\n".join(error_lines),
                                              method="subprocess")
        except Exception as e:
            return envelopes.failure_envelope("backend", "backend_error", f"Failed to parse recipe: {str(e)}",
                                              method="subprocess")

        from powderline.gateways.gsasii import console

        start_time = time.time()
        files = lambda: sorted(str(f) for f in output_dir.glob('*') if f.is_file())  # noqa: E731
        with console.capture_console() as tail:  # the engine's console text, kept for a failed run (KI-05)
            try:
                result = run_refinement(recipe, output_dir, verbose=verbose, method='subprocess')
            except EngineExecutionError as e:  # R30: PowderLine's own failure (divergence, site, peak fit)
                import traceback
                result = e.result or envelopes.failure_envelope("engine", e.reason, str(e), method="subprocess",
                                                                elapsed=time.time() - start_time, output_files=files(),
                                                                traceback=traceback.format_exc())
            except Exception as e:
                import traceback
                result = envelopes.failure_envelope("engine", "engine_crashed", str(e), method="subprocess",
                                                    elapsed=time.time() - start_time, traceback=traceback.format_exc(),
                                                    output_files=files())
        if result.get('success') is False and 'status' not in result:  # a frozen catch-all's early exit
            result = envelopes.legacy_failure(result)
        if result.get('status') != 'failed':
            result = envelopes.with_status_fields(result, status="ok", converged=envelopes.converged_of(result))
        return console.attach_console(result, tail, verbose=verbose)


def _with_validation_warnings(recipe, result: Dict[str, Any]) -> Dict[str, Any]:
    """Prepend a native ``gsasii.*`` recipe's validation warnings to the run's ``warnings`` (A115).

    They are collected from the recipe as given (the model the caller validated,
    or the dict / file validated here), so a default the recipe left out is
    reported even though the server receives the dumped model, which states it.
    A recipe that does not validate (the run already says why) gets none.
    """
    from pydantic import ValidationError
    from powderline.gateways.gsasii.schema import validate_recipe
    from powderline.schema_core import collect_warnings

    if isinstance(recipe, Path):
        try:
            recipe = GSASClient._normalize_recipe(recipe)
        except (OSError, ValueError):
            return result
    try:
        found = collect_warnings(validate_recipe(recipe))
    except ValidationError:
        return result
    result['warnings'] = found + list(result.get('warnings') or [])
    return result
