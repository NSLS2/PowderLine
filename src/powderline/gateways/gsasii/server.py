"""GSAS-II persistent server for fast simulations.

This server keeps GSAS-II loaded in memory to eliminate startup overhead.
Listens on an HTTP port via FastAPI and processes simulation requests **sequentially** (a lock around
the refinement: GSAS-II's module-level state is not thread-safe; concurrent requests queue).

Security notes:
    - The server binds exclusively to ``127.0.0.1`` (loopback) on an ephemeral
      port (or ``POWDERLINE_SERVER_PORT`` if set). It is not accessible from
      remote hosts.
    - Every request must be signed with a per-start secret token (an HMAC over
      method, path, nonce, timestamp and body), and every response is signed
      back (see :class:`SignedRequestMiddleware`). The token is stored, with
      the port and PID, in a per-user state directory (see :func:`state_dir`)
      that only the owning user can read, and it never travels over the wire.
      Other local users therefore cannot submit jobs (which would write files
      as the server's owner) or even probe the server, and a client never
      trusts a listener that cannot sign with its token — e.g. another user's
      process that took over the port of a crashed server.
    - A kernel-held lock on ``server.lock`` (released by the OS when the server
      exits) ensures a single server per user, even with concurrent starts.
    - Set ``POWDERLINE_NO_SERVER=1`` (``true``/``yes``/``on``) to disable the
      server: ``auto`` mode runs in-process, ``server`` mode returns an error,
      and ``gsas-server start``/``restart`` refuse.
    - No rate limiting is applied.
    - The server needs no filesystem in common with its clients (re/19, KI-12):
      each job runs in a private scratch directory under the state dir and its
      output files travel back base64-encoded inside the signed response
      (``files``); the client writes them into its own ``output_dir``.

Performance:
- First simulation: ~12s (server startup + GSAS-II import)
- Subsequent simulations: ~2-3s each (no startup overhead)
- 4-6x speedup for batch operations

Usage:
    # Start server (daemon mode)
    pixi run gsas-server start

    # Stop server
    pixi run gsas-server stop

    # Check status (also prints the log file location)
    pixi run gsas-server status

    # View logs
    pixi run gsas-server logs

    # Restart server
    pixi run gsas-server restart
"""

import base64
import json
import sys
import os
import signal
import socket
import stat
import time
import subprocess
import logging
import hashlib
import hmac
import secrets
import threading
from pathlib import Path
from typing import Dict, Any, Optional, List
import shutil
import tempfile
import atexit
import contextlib
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from powderline import results as envelopes
from powderline.exceptions import EngineExecutionError

# Server configuration
HOST = "127.0.0.1"
PORT_ENV = 'POWDERLINE_SERVER_PORT'
NO_SERVER_ENV = 'POWDERLINE_NO_SERVER'
NO_SERVER_VALUES = ('1', 'true', 'yes', 'on')
NO_SERVER_MESSAGE = (
    f"The GSAS-II server is disabled ({NO_SERVER_ENV} is set). "
    f"Run in-process instead (execution_mode='subprocess' / --no-server), "
    f"or unset {NO_SERVER_ENV}."
)

# Request/response signing (see sign_request / sign_response)
NONCE_HEADER = 'X-PowderLine-Nonce'
TIMESTAMP_HEADER = 'X-PowderLine-Timestamp'
SIGNATURE_HEADER = 'X-PowderLine-Signature'
RESPONSE_SIGNATURE_HEADER = 'X-PowderLine-Response-Signature'
MAX_CLOCK_SKEW = 120                   # seconds a signed request stays valid
MAX_BODY_BYTES = 64 * 1024 * 1024      # /simulate: larger requests are refused unread
MAX_HEALTH_BODY_BYTES = 4096           # /health, and any path that is not /simulate (re/14)


def _body_limit(path: str) -> int:
    """How much request body a path may carry before the HMAC check: only ``/simulate`` carries a job (re/14).

    Every other path -- ``/health`` and anything unknown -- is capped small, so an unauthenticated
    sender can make the server buffer at most a few kilobytes; the request is still verified and
    answered with a *signed* 401/404 as before.
    """
    return MAX_BODY_BYTES if path == "/simulate" else MAX_HEALTH_BODY_BYTES

# File names inside the per-user state directory
PID_NAME = 'server.pid'
ENDPOINT_NAME = 'server.json'
LOG_NAME = 'server.log'
LOCK_NAME = 'server.lock'


class ServerStateError(RuntimeError):
    """The per-user server state directory is unsafe or unusable."""


def server_disabled() -> bool:
    """True if ``POWDERLINE_NO_SERVER`` is set to a truthy value (1/true/yes/on)."""
    return os.environ.get(NO_SERVER_ENV, '').strip().lower() in NO_SERVER_VALUES


def _private_parent(path: str) -> bool:
    """True if ``path`` is a real directory (not a symlink) owned by us that
    others cannot write to."""
    try:
        st = os.lstat(path)
    except OSError:
        return False
    return (stat.S_ISDIR(st.st_mode) and st.st_uid == os.getuid()
            and not st.st_mode & 0o022)


def _check_tempdir_parent(path: Path) -> None:
    """Refuse a parent in which other users could rename or replace our entry.

    Safe parents are owned by root or by us and are either not writable by
    group/other or sticky (like ``/tmp``). Symlinks are followed here on
    purpose (macOS ``/tmp`` -> ``/private/tmp``).
    """
    try:
        st = os.stat(path)
    except OSError as e:
        raise ServerStateError(
            f"Cannot use {path} for the GSAS-II server state directory: {e}") from e
    if not stat.S_ISDIR(st.st_mode):
        problem = "is not a directory"
    elif st.st_uid not in (0, os.getuid()):
        problem = f"is owned by uid {st.st_uid}"
    elif st.st_mode & 0o022 and not st.st_mode & stat.S_ISVTX:
        problem = "is writable by other users without the sticky bit"
    else:
        return
    raise ServerStateError(
        f"Refusing to keep the GSAS-II server state under {path}: it {problem}, "
        f"so other users could replace the state directory. Point TMPDIR (or "
        f"XDG_RUNTIME_DIR) at a private directory.")


def _state_dir_path() -> Path:
    """Location of the per-user state directory (not created or checked).

    POSIX: ``$XDG_RUNTIME_DIR/powderline`` when that directory is ours, else
    ``<tempdir>/powderline-<uid>`` — host-local, never the (possibly
    NFS-shared) home directory, because the server is per-host.
    Windows: ``%LOCALAPPDATA%\\powderline`` (protected by the profile ACL).
    """
    if os.name == 'nt':
        base = os.environ.get('LOCALAPPDATA') or str(Path.home() / 'AppData' / 'Local')
        return Path(base) / 'powderline'
    runtime_dir = os.environ.get('XDG_RUNTIME_DIR')
    if runtime_dir and _private_parent(runtime_dir):
        return Path(runtime_dir) / 'powderline'
    return Path(tempfile.gettempdir()) / f'powderline-{os.getuid()}'


def _unsafe_state_dir(st: os.stat_result) -> Optional[str]:
    """Why a stat of the state directory makes it unsafe, or None if it is fine."""
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
        return "is not a directory (or is a symlink)"
    if st.st_uid != os.getuid():
        return f"is owned by uid {st.st_uid}, not by you (uid {os.getuid()})"
    if st.st_mode & 0o077:
        return f"is accessible to other users (mode {stat.S_IMODE(st.st_mode):o})"
    return None


def _refuse(path: Path, problem: str) -> ServerStateError:
    return ServerStateError(
        f"Refusing to use GSAS-II server state directory {path}: it {problem}. "
        f"Remove it so it can be recreated privately."
    )


def state_dir() -> Path:
    """Return the per-user server state directory, creating it if needed.

    Holds the lock, PID, endpoint (port + token) and log files. On POSIX it is
    created with mode 0700 and refused if it is a symlink, not owned by the
    current user, or accessible to group/other, or if its parent would let
    another user replace it — a directory pre-created by another user in a
    shared /tmp must never be trusted. Files inside are then opened relative
    to a re-verified directory handle (see :func:`_open_state_file`).

    Raises:
        ServerStateError: If the directory exists but is unsafe to use.
    """
    path = _state_dir_path()
    if os.name == 'nt':
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise ServerStateError(
                f"Cannot create GSAS-II server state directory {path}: {e}") from e
        return path
    _check_tempdir_parent(path.parent)
    try:
        try:
            os.mkdir(path, 0o700)
            os.chmod(path, 0o700)  # umask may have stripped owner bits
        except FileExistsError:
            pass
        st = os.lstat(path)
    except OSError as e:
        raise ServerStateError(
            f"Cannot create GSAS-II server state directory {path}: {e}") from e
    problem = _unsafe_state_dir(st)
    if problem:
        raise _refuse(path, problem)
    return path


def _open_state_dir() -> int:
    """Open the verified state directory without following symlinks (POSIX).

    The returned descriptor is re-checked with ``fstat``, so the directory the
    caller works in is exactly the one verified — it cannot be swapped for a
    symlink between the check and the use.
    """
    path = state_dir()
    try:
        dfd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError as e:
        raise _refuse(path, f"cannot be opened safely ({e})") from e
    problem = _unsafe_state_dir(os.fstat(dfd))
    if problem:
        os.close(dfd)
        raise _refuse(path, problem)
    return dfd


def _open_state_file(name: str, flags: int, mode: int = 0o600) -> int:
    """``os.open`` a file in the state directory (never through a symlink)."""
    if os.name == 'nt':
        return os.open(state_dir() / name, flags | getattr(os, 'O_BINARY', 0), mode)
    dfd = _open_state_dir()
    try:
        return os.open(name, flags | os.O_NOFOLLOW, mode, dir_fd=dfd)
    finally:
        os.close(dfd)


def _read_state_file(name: str) -> Optional[str]:
    """Contents of a state file, or None if it does not exist."""
    try:
        fd = _open_state_file(name, os.O_RDONLY)
    except FileNotFoundError:
        return None
    with os.fdopen(fd, 'rb') as f:
        return f.read().decode('utf-8', 'replace')


def _retry_file_op(op, what: str, *, attempts: int = 10, delay: float = 0.05):
    """Run ``op()``; on ``PermissionError`` (Windows: another process holds the file open) retry briefly,
    then raise :class:`ServerStateError` naming the operation (re/14)."""
    for attempt in range(attempts):
        try:
            return op()
        except PermissionError as e:
            if attempt == attempts - 1:
                raise ServerStateError(f"could not {what}: {e} (another process holds the file open)") from e
            time.sleep(delay)


def _unlink_state_file(name: str) -> None:
    """Remove a state file if present."""
    try:
        if os.name == 'nt':
            _retry_file_op(lambda: (state_dir() / name).unlink(), f"remove {name}")
            return
        dfd = _open_state_dir()
        try:
            os.unlink(name, dir_fd=dfd)
        finally:
            os.close(dfd)
    except FileNotFoundError:
        pass


def _write_private(name: str, text: str) -> None:
    """Atomically write ``text`` to state file ``name``, readable by the owner only."""
    tmp = name + '.tmp'
    _unlink_state_file(tmp)
    fd = _open_state_file(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    with os.fdopen(fd, 'w') as f:
        f.write(text)
    if os.name == 'nt':
        d = state_dir()
        _retry_file_op(lambda: os.replace(d / tmp, d / name), f"replace {name}")
        return
    dfd = _open_state_dir()
    try:
        os.replace(tmp, name, src_dir_fd=dfd, dst_dir_fd=dfd)
    finally:
        os.close(dfd)


def log_file() -> Path:
    """Path of this user's server log file."""
    return state_dir() / LOG_NAME


def read_endpoint() -> Optional[Dict[str, Any]]:
    """Return this user's server endpoint ``{'pid', 'port', 'token'}``, or None.

    Raises:
        ServerStateError: If the state directory is unsafe to use.
    """
    try:
        data = json.loads(_read_state_file(ENDPOINT_NAME) or '')
        return {'pid': int(data['pid']), 'port': int(data['port']),
                'token': str(data['token'])}
    except (OSError, ValueError, KeyError, TypeError):
        return None


def read_pid() -> Optional[int]:
    """PID recorded by the server holding the start lock, or None."""
    try:
        return int(_read_state_file(PID_NAME) or '')
    except (OSError, ValueError):
        return None


# --- Request/response signing ---
#
# The token never travels over the wire. Each request carries a fresh nonce,
# a timestamp and an HMAC (keyed by the token) over the method, path, nonce,
# timestamp and body; the server answers with an HMAC over the nonce, status
# and response body. A listener that does not hold the token — e.g. another
# user's process that grabbed the port of a crashed server — can neither
# produce a valid response nor learn anything that would let it.

def _mac(token: str, *parts) -> str:
    msg = b'\n'.join(p if isinstance(p, bytes) else str(p).encode() for p in parts)
    return hmac.new(token.encode(), msg, hashlib.sha256).hexdigest()


def sign_request(token: str, method: str, path: str, query: bytes,
                 nonce: str, timestamp: str, body: bytes) -> str:
    """HMAC authenticating one request (method, target, nonce, time and body)."""
    return _mac(token, b'powderline-request-v1', method.upper(), path, query,
                nonce, timestamp, hashlib.sha256(body).hexdigest())


def sign_response(token: str, nonce: str, status_code: int, body: bytes) -> str:
    """HMAC proving a response came from the token holder, bound to the request nonce."""
    return _mac(token, b'powderline-response-v1', nonce, status_code,
                hashlib.sha256(body).hexdigest())


class SignedRequestMiddleware:
    """ASGI wrapper: only correctly signed requests reach the app; every
    response it produces is signed.

    It wraps the whole application, so 404/405/422 and error responses are
    covered too. Requests with malformed signing headers are refused before
    their body is read; any path but ``/simulate`` may carry at most
    ``MAX_HEALTH_BODY_BYTES`` of body, so only a real job can make the server
    buffer a large body before the HMAC check.
    """

    def __init__(self, app, token: str):
        self.app = app
        self.token = token
        self._seen_nonces: Dict[str, float] = {}

    async def __call__(self, scope, receive, send):
        if scope['type'] == 'lifespan':
            return await self.app(scope, receive, send)
        if scope['type'] != 'http':
            if scope['type'] == 'websocket':
                await send({'type': 'websocket.close', 'code': 1008})
            return

        headers = {k.decode('latin-1').lower(): v.decode('latin-1')
                   for k, v in scope.get('headers', [])}
        nonce = headers.get(NONCE_HEADER.lower(), '')
        timestamp = headers.get(TIMESTAMP_HEADER.lower(), '')
        signature = headers.get(SIGNATURE_HEADER.lower(), '')
        now = time.time()
        try:
            fresh = abs(now - int(timestamp)) <= MAX_CLOCK_SKEW
        except ValueError:
            fresh = False
        if not (fresh and 16 <= len(nonce) <= 128
                and all(c in '0123456789abcdef' for c in nonce)
                and signature and nonce not in self._seen_nonces):
            return await self._reject(send, 401)
        limit = _body_limit(scope['path'])

        parts, size, more = [], 0, True
        while more:
            message = await receive()
            if message['type'] == 'http.disconnect':
                return
            parts.append(message.get('body', b''))
            size += len(parts[-1])
            more = message.get('more_body', False)
            if size > limit:
                return await self._reject(send, 413)
        body = b''.join(parts)

        expected = sign_request(self.token, scope['method'], scope['path'],
                                scope.get('query_string', b''), nonce, timestamp, body)
        if not hmac.compare_digest(signature.encode('latin-1'), expected.encode()):
            return await self._reject(send, 401)
        # Another copy of this request may have claimed the nonce while this one
        # awaited its body; re-check and record it with no await in between.
        if nonce in self._seen_nonces:
            return await self._reject(send, 401)
        self._remember(nonce, now)

        body_sent = False

        async def replay_receive():
            nonlocal body_sent
            if not body_sent:
                body_sent = True
                return {'type': 'http.request', 'body': body, 'more_body': False}
            return await receive()

        start = None
        chunks = []

        async def signing_send(message):
            nonlocal start
            if message['type'] == 'http.response.start':
                start = message
                return
            if message['type'] != 'http.response.body':
                return await send(message)
            chunks.append(message.get('body', b''))
            if message.get('more_body', False):
                return
            data = b''.join(chunks)
            response_headers = [
                (k, v) for k, v in start.get('headers', [])
                if k.lower() not in (b'content-length',
                                     RESPONSE_SIGNATURE_HEADER.lower().encode())
            ]
            response_headers += [
                (b'content-length', str(len(data)).encode()),
                (RESPONSE_SIGNATURE_HEADER.lower().encode(),
                 sign_response(self.token, nonce, start['status'], data).encode()),
            ]
            await send({**start, 'headers': response_headers})
            await send({'type': 'http.response.body', 'body': data, 'more_body': False})

        await self.app(scope, replay_receive, signing_send)

    def _remember(self, nonce: str, now: float) -> None:
        """Record a used nonce (replay protection), forgetting expired ones."""
        if len(self._seen_nonces) > 1024:
            cutoff = now - 2 * MAX_CLOCK_SKEW
            self._seen_nonces = {n: t for n, t in self._seen_nonces.items() if t > cutoff}
        self._seen_nonces[nonce] = now

    @staticmethod
    async def _reject(send, status: int) -> None:
        detail = b'{"detail":"Unauthorized"}' if status == 401 else b'{"detail":"Request too large"}'
        await send({'type': 'http.response.start', 'status': status, 'headers': [
            (b'content-type', b'application/json'),
            (b'content-length', str(len(detail)).encode()),
        ]})
        await send({'type': 'http.response.body', 'body': detail})


def _requested_port() -> int:
    """Port from ``POWDERLINE_SERVER_PORT``, else 0 (an ephemeral port).

    Raises:
        ServerStateError: the variable is set but is not a port number (re/14: reported up front, before
            the start lock and the GSAS-II import, and by the client before it spawns a server).
    """
    value = os.environ.get(PORT_ENV, '').strip()
    if not value:
        return 0
    try:
        port = int(value)
    except ValueError:
        port = -1
    if not 1 <= port <= 65535:
        raise ServerStateError(f"{PORT_ENV}={value!r} is not a port number (1-65535); unset it for an "
                               "ephemeral port")
    return port


def _bind_listener(port: int) -> socket.socket:
    """Bind and listen on ``HOST:port`` (0 = ephemeral)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
        # Windows: forbid other sockets from binding the same port.
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    elif port:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind((HOST, port))
        sock.listen(128)
    except OSError:
        sock.close()
        raise
    return sock


# --- Start lock ---
#
# A kernel-held lock on server.lock, kept for the server's whole lifetime. The
# OS drops it when the process exits — however it exits — so there is no stale
# lock to reclaim, and holding it is the definition of "a server is running".
# The lock file itself is never deleted (deleting lock files reintroduces races).

_lock_fd: Optional[int] = None  # held by this process while it is the server


def _try_lock(fd: int) -> bool:
    try:
        if os.name == 'nt':
            import msvcrt
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def _unlock(fd: int) -> None:
    if os.name == 'nt':
        import msvcrt
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    else:
        import fcntl
        fcntl.flock(fd, fcntl.LOCK_UN)


def _claim_server_lock(attempts: int = 20, delay: float = 0.05) -> bool:
    """Take the start lock for the life of this process; False if a server holds it.

    A few retries absorb the instant during which ``is_server_running`` probes
    the lock. Once held, any PID/endpoint files left over are stale (their
    server is gone), so they are replaced.
    """
    global _lock_fd
    if _lock_fd is not None:
        return True
    fd = _open_state_file(LOCK_NAME, os.O_RDWR | os.O_CREAT)
    for attempt in range(attempts):
        if _try_lock(fd):
            _lock_fd = fd
            _unlink_state_file(ENDPOINT_NAME)
            _write_private(PID_NAME, str(os.getpid()))
            return True
        if attempt < attempts - 1:
            time.sleep(delay)
    os.close(fd)
    return False


@contextlib.contextmanager
def _probe_lock():
    """Open the lock file, try to take the lock without blocking, yield whether we got it, release and close.

    The one copy of the probe protocol (re/14); :func:`_claim_server_lock` keeps its descriptor for the
    server's lifetime and so stays separate.
    """
    fd = _open_state_file(LOCK_NAME, os.O_RDWR | os.O_CREAT)
    try:
        acquired = _try_lock(fd)
        try:
            yield acquired
        finally:
            if acquired:
                _unlock(fd)
    finally:
        os.close(fd)


def _lock_held() -> bool:
    """True if some process (this one included) holds the start lock."""
    if _lock_fd is not None:
        return True
    with _probe_lock() as acquired:
        return not acquired


def _clear_stale_state_files() -> bool:
    """Remove PID/endpoint files left by a server that is gone.

    Done while briefly holding the start lock, which proves no server is
    running or starting, so a live server's files are never touched. Needed
    where a server cannot clean up after itself — e.g. after ``stop`` on
    Windows, which terminates the process. Returns False if the lock is held.
    """
    if _lock_fd is not None:
        return False
    with _probe_lock() as acquired:
        if not acquired:
            return False
        _unlink_state_file(ENDPOINT_NAME)
        _unlink_state_file(PID_NAME)
        return True


def _release_state_files() -> None:
    """Remove the PID and endpoint files and drop the lock — only if we hold it."""
    global _lock_fd
    if _lock_fd is None:
        return
    try:
        _unlink_state_file(ENDPOINT_NAME)
        _unlink_state_file(PID_NAME)
    except (OSError, ServerStateError):
        pass
    try:
        _unlock(_lock_fd)
    except OSError:
        pass
    os.close(_lock_fd)
    _lock_fd = None


# --- job scratch directories and in-band files (re/19, KI-12) ---

JOB_PREFIX = 'job-'                    # scratch dirs under the state dir, one per job, removed after the response
BACKUP_GLOB = '*.bak*.gpx'             # GSAS-II's own backup copies: not part of PowderLine's output


def collect_output_files(directory: Path) -> Dict[str, str]:
    """``{name: base64}`` of every regular file in ``directory`` except GSAS-II's backup copies."""
    directory = Path(directory)
    backups = {p.name for p in directory.glob(BACKUP_GLOB)}
    files = {}
    for p in sorted(directory.iterdir()):
        if p.is_file():
            if p.name not in backups:
                files[p.name] = base64.b64encode(p.read_bytes()).decode('ascii')
        else:
            logging.getLogger('powderline.server').warning(f"job wrote a non-file {p.name!r}; not transferred")
    return files


def sweep_job_dirs() -> int:
    """Remove scratch directories a previous server left behind (a crash mid-job); the count removed."""
    removed = 0
    for path in state_dir().glob(JOB_PREFIX + '*'):
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
            removed += 1
    return removed


def _attach_files(envelope: Dict[str, Any], job: Path) -> Dict[str, Any]:
    """Put the job's files on the wire envelope; ``output_files`` becomes their bare names."""
    envelope['files'] = collect_output_files(job)
    envelope['output_files'] = sorted(envelope['files'])
    return envelope


# --- Pydantic request/response models ---

class SimulationRequest(BaseModel):
    """A job: the recipe inline. No ``output_dir`` (re/19, KI-12): the server's filesystem is not the
    client's; the job runs in a private scratch directory and its files travel back in the response."""
    model_config = ConfigDict(extra="forbid")

    recipe_data: dict
    verbose: bool = False


class SimulationResponse(BaseModel):
    """The wire envelope (re/12, ``powderline.results``, ``envelope_version`` 1): every application outcome
    is HTTP 200 with one of these; ``status`` is ``ok`` or ``failed`` (with ``failure``); 4xx/5xx are
    auth/transport only."""
    envelope_version: Optional[str] = None
    status: Optional[str] = None
    converged: Optional[bool] = None
    failure: Optional[dict] = None
    run_id: Optional[str] = None
    rwp: Optional[float] = None
    elapsed_time: Optional[float] = None
    method: Optional[str] = None
    output_files: Optional[List[str]] = None
    files: Optional[Dict[str, str]] = None  # name -> base64 content of every output file (re/19, KI-12)
    fit_profile: Optional[dict] = None
    unit_cell_data: Optional[dict] = None
    peak_list_data: Optional[dict] = None
    refined_parameters: Optional[list] = None
    spf_peaks: Optional[dict] = None
    spf_convergence_diagnostics: Optional[dict] = None
    peak_fit: Optional[dict] = None  # the peak fit's varied parameters by GSAS-II name, with ESDs (re/21)
    # native gsasii.* runs (re/04): standard fit statistics, GSAS-II's own values, structured warnings
    r_exp: Optional[float] = None
    gof: Optional[float] = None
    chi2_red: Optional[float] = None
    simulation_mode: Optional[bool] = None
    engine_details: Optional[dict] = None
    warnings: Optional[list] = None


# --- Logging ---

def setup_logging() -> logging.Logger:
    """Set up logging to both console and this user's server log file."""
    logger = logging.getLogger('powderline.server')
    logger.setLevel(logging.DEBUG)

    # File handler (always log everything); owner-only, opened in the
    # verified state directory
    log_fd = _open_state_file(LOG_NAME, os.O_WRONLY | os.O_CREAT | os.O_APPEND)
    file_handler = logging.StreamHandler(os.fdopen(log_fd, 'a', encoding='utf-8'))
    file_handler.setLevel(logging.DEBUG)

    # Console handler (info level for cleaner output)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)

    # Formatter with timestamps
    formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return logger



def source_tree_hash(root=None) -> str:
    """MD5 over every ``*.py`` under ``root`` (default: the installed ``powderline`` package): relative
    POSIX path and bytes, in sorted order (re/17 H7).

    The server computes it once at start, so it names the code the process loaded. A client whose
    own tree hashes differently runs other code than the server, which caches its modules: the
    server is *stale* and must be restarted (``gsas-server restart``).
    """
    if root is None:
        import powderline
        root = Path(powderline.__file__).parent
    root = Path(root)
    digest = hashlib.md5()
    for path in sorted(root.rglob("*.py"), key=lambda q: q.relative_to(root).as_posix()):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


# --- Server class ---

class GSASServer:
    """Persistent GSAS-II server for fast simulations."""

    def __init__(self, logger: logging.Logger = None):
        """Initialize server (GSAS-II import happens here).

        Args:
            logger: Optional logger instance. If not provided, one will be created.
        """
        self.running = False
        self.request_count = 0
        self.start_time = None
        # Per-start credential; clients read it from the owner-only state dir.
        self.token = secrets.token_urlsafe(32)
        # The code this process loaded (re/17 H7): /health reports it; a client on another tree sees a stale server.
        self.code_hash = source_tree_hash()

        # Set up logging
        self.logger = logger or setup_logging()

        # Import GSAS-II (this is the slow part we want to do once)
        self.logger.info("Loading GSAS-II libraries...")
        import_start = time.time()

        # Set PYTHONPATH to include src directory
        src_dir = Path(__file__).parents[3]
        if str(src_dir) not in sys.path:
            sys.path.insert(0, str(src_dir))

        try:
            # Import the GSAS-II executors (they import GSAS-II at module top)
            # once, so every request finds it loaded
            from powderline.gateways.gsasii import executors
            self.runtime = executors
            import_time = time.time() - import_start
            self.logger.info(f"GSAS-II loaded in {import_time:.1f}s")
        except ImportError as e:
            self.logger.error(f"Failed to import GSAS-II: {e}")
            sys.exit(1)

    def create_app(self):
        """Build and return the ASGI application.

        The FastAPI app is wrapped in :class:`SignedRequestMiddleware`: every
        route — including ``/health`` — requires a request signed with
        ``self.token`` (anything else gets 401), and every response is signed
        so the client can verify it reached the token holder.
        """
        from fastapi import FastAPI

        # No interactive docs/schema routes: nothing is served unauthenticated.
        app = FastAPI(title="PowderLine GSAS-II Server",
                      docs_url=None, redoc_url=None, openapi_url=None)
        server = self  # capture for closures
        # One refinement at a time (re/14): the handler is synchronous and FastAPI runs it in a thread
        # pool, but GSAS-II's module-level state is not thread-safe, so concurrent requests queue here.
        run_lock = threading.Lock()

        @app.post("/simulate", response_model=SimulationResponse)
        def simulate(req: SimulationRequest):
            with run_lock:
                server.request_count += 1
                number = server.request_count  # captured under the lock: the next job increments it as we log
                schema_name = (req.recipe_data.get('schema_name', 'unknown')
                               if isinstance(req.recipe_data, dict) else 'unknown')
                server.logger.info(f"Request #{number}: schema={schema_name}")
                result = server._run_simulation(req.model_dump())

            elapsed = result.get('elapsed_time') or 0
            run_id = result.get('run_id', 'n/a')
            if result.get('status') == 'ok':
                server.logger.info(f"Request #{number} (run_id={run_id}) completed in {elapsed:.1f}s")
            else:
                failure = result.get('failure') or {}
                server.logger.warning(
                    f"Request #{number} (run_id={run_id}) failed "
                    f"({failure.get('kind')}/{failure.get('reason')}): {failure.get('message', 'Unknown error')}"
                )
                if failure.get('traceback'):
                    server.logger.debug(f"Request #{number} traceback:\n{failure['traceback']}")
            return SimulationResponse(**result)

        @app.get("/health")
        def health():
            uptime = (datetime.now() - server.start_time).total_seconds() if server.start_time else 0
            from powderline import __version__

            return {
                "status": "ok",
                "pid": os.getpid(),
                "uptime_seconds": uptime,
                "request_count": server.request_count,
                "powderline_version": __version__,
                "code_hash": server.code_hash,
            }

        return SignedRequestMiddleware(app, self.token)

    def start(self, sock: Optional[socket.socket] = None):
        """Start the server with uvicorn on ``sock`` (bound by :func:`_listen`; bound here when not given)."""
        import uvicorn

        self.start_time = datetime.now()
        try:
            swept = sweep_job_dirs()
        except (OSError, ServerStateError) as e:
            self.logger.warning(f"could not sweep leftover job directories: {e}")
        else:
            if swept:
                self.logger.info(f"Removed {swept} leftover job director{'y' if swept == 1 else 'ies'}")
        self.logger.info("=" * 60)
        self.logger.info("GSAS-II Server Starting")
        self.logger.info("=" * 60)

        # The listener is bound before GSAS-II is imported (so a busy or bad port fails fast) and before
        # the endpoint file is written (so it records the real, possibly ephemeral, port).
        if sock is None:
            sock = _listen(self.logger)
        port = sock.getsockname()[1]
        _write_private(ENDPOINT_NAME, json.dumps(
            {'pid': os.getpid(), 'port': port, 'token': self.token}))

        # Register cleanup
        atexit.register(self.cleanup)
        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)

        self.running = True
        self.logger.info(f"GSAS-II server started")
        self.logger.info(f"   URL: http://{HOST}:{port}")
        self.logger.info(f"   Log file: {log_file()}")
        self.logger.info(f"   PID: {os.getpid()}")
        self.logger.info(f"   Started: {self.start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        self.logger.info(f"   Listening for simulation requests...")
        self.logger.info("-" * 60)

        app = self.create_app()
        uvicorn.Server(uvicorn.Config(app, log_level="warning")).run(sockets=[sock])

    def _run_simulation(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """Run a GSAS-II simulation with the loaded GSAS-II runtime.

        Args:
            request: Dictionary with 'recipe_data' (inline recipe dict) and optional 'verbose'

        Returns:
            An envelope (``powderline.results``): ``ok`` with the result keys ('run_id', 'rwp',
            'elapsed_time', 'method', 'output_files', 'fit_profile' (dict), 'unit_cell_data' (dict),
            'peak_list_data' (dict), 'refined_parameters' (list), 'spf_peaks' (dict),
            'spf_convergence_diagnostics' (dict), 'converged', ...), or ``failed`` with a 'failure' record.
        """
        from powderline.gateways.gsasii.routing import model_from_request, run_refinement
        from pydantic import ValidationError

        recipe_dict = request.get('recipe_data')
        verbose = request.get('verbose', False)

        if recipe_dict is None:
            return envelopes.failure_envelope("backend", "backend_error", "Missing recipe_data in request",
                                              method="server")

        # Validate recipe
        try:
            recipe = model_from_request(recipe_dict)
        except ValidationError as e:
            error_lines = [f"{' -> '.join(str(loc) for loc in err['loc'])}: {err['msg']}"
                          for err in e.errors()]
            return envelopes.failure_envelope("backend", "backend_error",
                                              "Recipe validation failed:\n" + "\n".join(error_lines),
                                              method="server")
        except Exception as e:
            return envelopes.failure_envelope("backend", "backend_error", f"Failed to parse recipe: {str(e)}",
                                              method="server")

        # The job runs in a private scratch dir (KI-12): whatever it writes travels back in the envelope,
        # on every branch, and the dir is removed afterwards. The client writes the files where it wants them.
        from powderline.gateways.gsasii import console

        job = Path(tempfile.mkdtemp(prefix=JOB_PREFIX, dir=state_dir()))
        try:
            # the engine's console text: into the envelope for a failed job (KI-05). The daemon's stdout is
            # discarded (DEVNULL), so this tail is its only record. Process-global; safe because one job
            # runs at a time (re/14)
            with console.capture_console() as tail:
                try:
                    result = run_refinement(recipe, job, verbose=verbose, method='server')
                except EngineExecutionError as e:  # R30: PowderLine's own failure (divergence, site, peak fit)
                    import traceback
                    result = e.result or envelopes.failure_envelope(
                        "engine", e.reason, str(e), method="server", traceback=traceback.format_exc())
                except Exception as e:  # a crash in the engine or the frozen code: an envelope, with the job's files
                    import traceback
                    result = envelopes.failure_envelope(
                        "engine", "engine_crashed", str(e), method="server", traceback=traceback.format_exc())
            if result.get('success') is False and 'status' not in result:  # a frozen catch-all's early exit
                result = envelopes.legacy_failure(result)
            if result.get('status') != 'failed':
                result = envelopes.with_status_fields(result, status="ok", converged=envelopes.converged_of(result))
            return _attach_files(console.attach_console(result, tail, verbose=verbose), job)
        finally:
            shutil.rmtree(job, ignore_errors=True)

    def _signal_handler(self, signum, frame):
        """Handle shutdown signals."""
        self.logger.info(f"Received signal {signum}, shutting down...")
        self.running = False
        self.cleanup()
        sys.exit(0)

    def cleanup(self):
        """Clean up the endpoint and PID files."""
        _release_state_files()

        if self.start_time:
            uptime = datetime.now() - self.start_time
            self.logger.info(f"Server stopped")
            self.logger.info(f"   Total requests: {self.request_count}")
            self.logger.info(f"   Uptime: {uptime}")
            self.logger.info("=" * 60)


def _pid_alive(pid: int) -> bool:
    """Return True if a process with ``pid`` exists (cross-platform).

    ``os.kill(pid, 0)`` is a valid liveness probe on POSIX but not on Windows,
    where ``os.kill`` terminates the target (or raises) rather than checking it;
    use the Win32 API there instead.
    """
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        try:
            code = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return False
            return code.value == STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def is_server_running() -> bool:
    """True if this user's server is running (or starting): it holds the start lock.

    The lock is released by the OS when the server exits, however it exits, so
    leftover PID files and recycled PIDs cannot make a dead server look alive.
    """
    return _lock_held()


def stop_server() -> bool:
    """Stop the running server."""
    if not is_server_running():
        print("Server is not running")
        return False

    pid = read_pid()
    if pid is None:
        print("Server is starting up (no PID recorded yet); try again in a moment")
        return False
    print(f"Stopping server (PID {pid})...")

    try:
        os.kill(pid, signal.SIGTERM)

        # Wait for graceful shutdown
        for _ in range(50):  # 5 seconds timeout
            time.sleep(0.1)
            if not is_server_running():
                _clear_stale_state_files()
                print("Server stopped")
                return True

        # Force kill if still running. SIGKILL does not exist on Windows;
        # there os.kill(pid, SIGTERM) maps to TerminateProcess (a hard kill),
        # which is the correct escalation.
        print("Forcing shutdown...")
        force_signal = getattr(signal, "SIGKILL", signal.SIGTERM)
        os.kill(pid, force_signal)
        time.sleep(0.5)

        if not is_server_running():
            _clear_stale_state_files()
            print("Server stopped (forced)")
            return True
        else:
            print("Failed to stop server")
            return False

    except ProcessLookupError:
        print("Server process not found")
        return False


def _server_url() -> str:
    endpoint = read_endpoint()
    if endpoint is None:
        return "(not listening yet)"
    return f"http://{HOST}:{endpoint['port']}"


def get_server_info() -> Optional[Dict[str, Any]]:
    """Get information about the running server.

    Returns:
        Dictionary with server info (pid, url, log_file, uptime) or None if not running
    """
    if not is_server_running():
        return None

    pid = read_pid()
    if pid is None:  # the lock is held but the PID is not written yet: the server is loading GSAS-II
        return {'pid': None, 'starting': True, 'url': _server_url(), 'log_file': str(log_file())}
    try:
        # Try to get process info
        import psutil
        proc = psutil.Process(pid)
        uptime = datetime.now() - datetime.fromtimestamp(proc.create_time())

        return {
            'pid': pid,
            'starting': False,
            'url': _server_url(),
            'log_file': str(log_file()),
            'uptime': str(uptime).split('.')[0],  # Remove microseconds
            'cpu_percent': proc.cpu_percent(interval=0.1),
            'memory_mb': proc.memory_info().rss / 1024 / 1024,
        }
    except Exception:
        # psutil not available: return basic info
        return {
            'pid': pid,
            'starting': False,
            'url': _server_url(),
            'log_file': str(log_file()),
        }


def _tail_lines(f, n: int) -> list:
    """The last ``n`` lines of an open binary file, read from the end (the server log is never rotated; re/14)."""
    f.seek(0, os.SEEK_END)
    size = f.tell()
    chunk = 8192
    data = b''
    while size > 0 and data.count(b'\n') <= n:
        step = min(chunk, size)
        size -= step
        f.seek(size)
        data = f.read(step) + data
        chunk *= 2
    lines = data.decode('utf-8', 'replace').splitlines()
    return lines[-n:]


def _listen(logger: logging.Logger) -> socket.socket:
    """Bind the listener on ``HOST`` and the requested port; a busy or bad port is a :class:`ServerStateError`."""
    requested = _requested_port()
    try:
        return _bind_listener(requested)
    except OSError as e:
        logger.error(f"cannot listen on {HOST}:{requested or '<ephemeral>'}: {e}")
        raise ServerStateError(f"cannot listen on {HOST}:{requested or '<ephemeral>'}: {e} (set {PORT_ENV} "
                               "to a free port, or unset it)") from e


def _start_foreground() -> None:
    """Take the start lock, bind the port, load GSAS-II and serve until stopped."""
    if not _claim_server_lock():
        print("Server is already running")
        print(f"   PID: {read_pid() or '(starting)'}")
        print(f"   URL: {_server_url()}")
        print(f"\n   To view logs: pixi run gsas-server logs")
        sys.exit(1)
    # Release the lock and state files even if the GSAS-II import below fails.
    atexit.register(_release_state_files)

    print("Starting GSAS-II server...")
    logger = setup_logging()
    sock = _listen(logger)  # bind first: a busy or bad port fails here, before GSAS-II is imported (re/14)
    server = GSASServer(logger)
    server.start(sock)


def main():
    """Main entry point for server management."""
    import argparse

    parser = argparse.ArgumentParser(description="GSAS-II persistent server")
    subparsers = parser.add_subparsers(dest='action', help='Server action')

    subparsers.add_parser('start', help='Start the server')
    subparsers.add_parser('stop', help='Stop the server')
    subparsers.add_parser('status', help='Show server status')
    subparsers.add_parser('restart', help='Restart the server')
    subparsers.add_parser('logs', help='Show recent server logs')

    args = parser.parse_args()
    action = args.action or 'status'  # Default to status if no action

    if action in ('start', 'restart') and server_disabled():
        print(f"Not starting: {NO_SERVER_MESSAGE}")
        sys.exit(1)

    try:
        if action in ('start', 'restart'):
            _requested_port()  # a bad POWDERLINE_SERVER_PORT is reported before the lock and the import
        _run_action(action)
    except ServerStateError as e:
        print(f"Error: {e}")
        sys.exit(1)


def _run_action(action: str) -> None:
    if action == 'start':
        _start_foreground()

    elif action == 'stop':
        stop_server()

    elif action == 'status':
        info = get_server_info()
        if info and info.get('starting'):
            print("Server is starting (loading GSAS-II; no PID recorded yet)")
            print(f"   URL: {info['url']}")
            print(f"   Log file: {info['log_file']}")
            print(f"\n   To view logs: pixi run gsas-server logs")
        elif info:
            print(f"Server is running")
            print(f"   PID: {info['pid']}")
            print(f"   URL: {info['url']}")
            print(f"   Log file: {info['log_file']}")
            if 'uptime' in info:
                print(f"   Uptime: {info['uptime']}")
            if 'cpu_percent' in info:
                print(f"   CPU: {info['cpu_percent']:.1f}%")
            if 'memory_mb' in info:
                print(f"   Memory: {info['memory_mb']:.1f} MB")
            from powderline.gateways.gsasii.client import GSASClient
            stale = GSASClient().server_is_stale()
            if stale is True:
                print("   Code: STALE - the server runs other PowderLine code than this checkout (it caches modules); "
                      "run: pixi run gsas-server restart")
            elif stale is False:
                print("   Code: current (matches this checkout)")
            print(f"\n   To view logs: pixi run gsas-server logs")
        else:
            print("Server is not running")
            print(f"\n   To start: pixi run gsas-server start")
            print(f"   Log file: {log_file()}")
            sys.exit(1)

    elif action == 'restart':
        if is_server_running():
            stop_server()
            time.sleep(1)

        _start_foreground()

    elif action == 'logs':
        path = log_file()
        try:
            fd = _open_state_file(LOG_NAME, os.O_RDONLY)  # never through a symlink, like every state-file read
        except FileNotFoundError:
            print(f"Log file not created yet: {path}")
            sys.exit(0)
        except OSError as e:
            print(f"Failed to read log file: {e}")
            sys.exit(1)

        print(f"Recent logs from {path}:")
        print("   (showing last 50 lines)")
        print("-" * 60)

        with os.fdopen(fd, 'rb') as f:
            for line in _tail_lines(f, 50):  # read from the end: the log is never rotated
                print(line.rstrip())

        print("-" * 60)
        print(f"   To follow logs in real-time: tail -f {path}")


if __name__ == '__main__':
    main()
