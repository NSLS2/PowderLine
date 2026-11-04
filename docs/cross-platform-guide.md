# Platform Support: Windows, macOS, and Linux

PowderLine ships for **`linux-64`, `win-64`, and `osx-arm64`** (as declared in
`pixi.toml`). This page is the platform-support reference: which platforms are
supported, how each cross-platform concern is handled, and the authoring rules
to follow so pixi tasks and code stay portable.

> **Status**
>
> - `pixi.toml` declares `platforms = ["linux-64", "win-64", "osx-arm64"]`.
> - **GSAS-II build**: `gsas-ii` is built as a conda package via `pixi-build`
>   (`preview = ["pixi-build"]`) from the `tacaswell/GSAS-II` fork and declared
>   under `[dependencies]`, so it installs on **all** shipped platforms
>   (linux-64/win-64/osx-arm64; currently v5.7.9) — not linux-64-only and not a
>   from-source pip build. Windows installs and runs GSAS-II directly. The
>   win-64 TOPAS path imports zero GSAS-II by design. Section 2 covers the
>   build-from-source background for reference.
> - **PYTHONPATH in pixi tasks**: every task (`kicker`, `gsas-server`,
>   `test`) uses the cross-platform task-level `env` dict
>   (`{ cmd = "python -m powderline.kicker", env = { PYTHONPATH =
>   "$PIXI_PROJECT_ROOT/src" } }`); no task uses the inline
>   `PYTHONPATH=$PWD/src:` (Unix) form any more. Section 3 records the
>   analysis behind that pattern. The engine tasks live in their engine's
>   pixi feature (`-e gsasii`), see `pixi.toml`.
> - **Signal handling**: the GSAS-II server
>   (`src/powderline/gateways/gsasii/server.py`) uses `SIGTERM`/`SIGINT`/`SIGKILL` +
>   `os.kill` (`psutil` is used in `get_server_info`). The concrete win-64
>   breakage this implies (`signal.SIGKILL` `AttributeError` in the
>   `stop_server` force-kill escalation) is fixed with
>   `getattr(signal, "SIGKILL", signal.SIGTERM)`; a broader platform
>   abstraction remains future work. See Section 4.
> - **TOPAS**: writing `topas.*` input files works on every platform; running
>   `tc.exe` is Windows-only by nature. The default environment is core-only;
>   GSAS-II is in the `gsasii` environment (`pixi install -e gsasii`).
>   On a fresh checkout install with `pixi install --frozen -e <env>`: a plain
>   `pixi install` re-evaluates the pixi-build GSAS-II package's hash and
>   re-locks every platform (seen on the 2026-10-16 Windows run); the frozen
>   install uses the committed lock as is (KI-13).
>
> Sections 2–4 and 6 are the original analysis, kept as the reference for the
> patterns; the module paths they quote (`gsas_server.py`, `mp_simulate.py`)
> are the pre-refactor ones: now `gateways/gsasii/server.py`; the `mp-simulate`
> tool left PowderLine in 0.2.0.

---

## Table of Contents

1. [Root Causes Summary](#1-root-causes-summary)
2. [Issue A — GSAS-II Fortran Build](#2-issue-a--gsas-ii-fortran-build)
3. [Issue B — PYTHONPATH in pixi Tasks](#3-issue-b--pythonpath-in-pixi-tasks)
4. [Issue C — gsas_server.py Unix Signal Handling](#4-issue-c--gsas_serverpy-unix-signal-handling)
5. [macOS-Specific Notes](#5-macos-specific-notes)
6. [Implementation Guide](#6-implementation-guide)
7. [Viewing Server Logs](#7-viewing-server-logs)

---

## 1. Root Causes Summary

There are three independent compatibility problems, each affecting a different
part of the codebase.

| # | Component | Problem | Platforms affected |
|---|---|---|---|
| A | `pixi.toml` — GSAS-II dependency | No Fortran compiler in the pixi environment | Windows, macOS |
| B | `pixi.toml` — task definitions | `PYTHONPATH=$PWD/src:$PYTHONPATH` uses Unix path separator and shell syntax | Windows |
| C | the GSAS-II server (then `src/powderline/gsas_server.py`, now `gateways/gsasii/server.py`) | `os.kill(pid, signal.SIGTERM/SIGKILL)` not supported on Windows | Windows |

Issues A, B, and C are independent and can be implemented in any order.
Issue A is the one that surfaces immediately when running
`pixi workspace platform add win-64`.

---

## 2. Issue A — GSAS-II Fortran Build

### What fails

```
Error: Failed to build `gsas-ii @ git+https://github.com/AdvancedPhotonSource/GSAS-II?rev=main#...`
ERROR: Unknown compiler(s): [['ifort'], ['ifx'], ['gfortran'], ['flang-new'], ...]
```

GSAS-II is declared as a PyPI git-source dependency in `pixi.toml`:

```toml
[pypi-dependencies]
gsas-ii = { git = "https://github.com/AdvancedPhotonSource/GSAS-II", rev = "main" }
```

When pixi resolves this on a new platform, it builds GSAS-II from source using
the meson build system. GSAS-II contains Fortran code (approximately 4% of the
codebase), so meson searches for a Fortran compiler at build time.

- **Linux**: gfortran is assumed to be pre-installed on the system (or provided
  by the HPC environment). The GSAS-II pixi documentation explicitly states:
  *"on Linux, [gfortran] must be done before running pixi (typically with a
  Linux package manager such as apt or dnf)".*
- **Windows**: No Fortran compiler is present. The GSAS-II author documents:
  *"I was not able to get gfortran working properly with Windows in my most
  recent attempt."* — which refers to non-pixi pip installation. With pixi,
  gfortran **can** be installed automatically from conda-forge.
- **macOS**: No Fortran compiler is present unless Xcode command-line tools are
  installed. The conda-forge `compilers` metapackage provides a self-contained
  solution.

### Key evidence: GSAS-II's own pixi.toml

GSAS-II ships its own `pixi/pixi.toml` (in its git repository at
`GSAS-II/pixi/pixi.toml`) which solves exactly this problem. It declares
platform-specific compiler dependencies:

```toml
[target.win-64.dependencies]
gfortran = ">=14.2.0,<14.3"
gcc      = ">=14.2.0,<14.3"

[target.osx-arm64.dependencies]
compilers = ">=1.11.0,<2"
clang     = ">=19.1.7,<22"

# (for Linux, gcc/gfortran are assumed to be system-installed)
```

PowderLine's `pixi.toml` does not include these, which is the direct cause of
the build failure.

### Fix

**Step 1** — Expand `platforms` in `[workspace]`:

```toml
# Before
platforms = ["linux-64"]

# After
platforms = ["linux-64", "win-64", "osx-arm64"]
```

**Step 2** — Add compiler dependencies, mirroring GSAS-II's own pixi.toml:

```toml
[target.win-64.dependencies]
gfortran = ">=14.2.0,<14.3"
gcc      = ">=14.2.0,<14.3"

[target.osx-arm64.dependencies]
compilers = ">=1.11.0,<2"
clang     = ">=19.1.7,<22"
```

**Step 3** — Add `no-build-isolation` for GSAS-II:

```toml
[pypi-options]
no-build-isolation = ["gsas-ii"]
```

Without this, pixi builds GSAS-II in an isolated environment that cannot see
the conda-installed compilers. `no-build-isolation` tells pixi to build the
package with access to the full conda environment (including the gfortran/gcc
binaries installed above). This is the same approach used internally by GSAS-II's
pixi setup when it calls `pip install -ve . --no-build-isolation`.

#### Why not use a pre-built wheel or `gsas2pkg`?

Pre-built Windows wheels do not exist on PyPI. The `briantoby::gsas2pkg` conda
package (from the `briantoby` conda channel, not conda-forge) provides
pre-built binaries via a different mechanism — it downloads GSAS-II into an
existing conda installation rather than integrating it as a Python package.
This would require restructuring how GSAS-II is declared as a dependency
(removing it from `[pypi-dependencies]` entirely and using a separate
post-install step), which is a more invasive change. The compiler approach
above is lower-risk and consistent with how GSAS-II itself is distributed.

---

## 3. Issue B — PYTHONPATH in pixi Tasks

### What fails

On Windows, `pixi run test` and `pixi run kicker` silently use the wrong
`PYTHONPATH` or fail to find the `powderline` package.

### Root cause

Every main task in `[tasks]` prefixes `PYTHONPATH` using Unix shell syntax:

```toml
kicker      = "PYTHONPATH=$PWD/src:$PYTHONPATH python src/powderline/kicker.py"
mp-simulate = "PYTHONPATH=$PWD/src:$PYTHONPATH python src/powderline/mp_simulate.py"
gsas-server = "PYTHONPATH=$PWD/src:$PYTHONPATH python src/powderline/gsas_server.py"
test        = "PYTHONPATH=$PWD/src:$PYTHONPATH pytest -v"
```

Two specific problems:

1. **Path separator**: `:` separates entries on Unix; Windows uses `;`. Python
   on Windows will not parse a colon-delimited `PYTHONPATH` correctly.
2. **Shell semantics**: While pixi uses `deno_task_shell` (which handles `$VAR`
   cross-platform), prepending to an existing variable with `:` is
   Unix-specific syntax.

### What was done

Every task in the current `pixi.toml` uses the task-level `env` dict
(`{ cmd = "...", env = { PYTHONPATH = "$PIXI_PROJECT_ROOT/src" } }`), which
pixi expands on every platform; `docs-clean` is written in Python and `ui`
uses the `env` dict. The two alternatives analysed below were not adopted;
they are kept for reference.

### Alternative analysed: pixi activation.env with platform-specific targets

Pixi supports `[target.unix.activation.env]` and `[target.win.activation.env]`
for platform-specific environment variable configuration. Setting `PYTHONPATH`
here applies it to all tasks in the environment without repeating it per-task.

**For the default environment** — replace the per-task prefixes with:

```toml
[target.unix.activation.env]
PYTHONPATH = "$PIXI_PROJECT_ROOT/src"

[target.win.activation.env]
PYTHONPATH = "%PIXI_PROJECT_ROOT%\\src"
```

Then simplify all four tasks:

```toml
[tasks]
kicker      = "python src/powderline/kicker.py"
mp-simulate = "python src/powderline/mp_simulate.py"
gsas-server = "python src/powderline/gsas_server.py"
test        = "pytest -v"
```

**Also fix `docs-clean`** — replace Unix `rm -rf` with Python:

```toml
# Before
docs-clean = "rm -rf docs/_build"

# After
docs-clean = "python -c \"import shutil; shutil.rmtree('docs/_build', ignore_errors=True)\""
```

**Also fix the `ui` task** — replace the inline env var prefix with pixi's env dict:

```toml
# Before
ui = 'GSASII_NOPATHHACKING="true" python -m GSASII'

# After
ui = { cmd = "python -m GSASII", env = { GSASII_NOPATHHACKING = "true" } }
```

### Alternative option: per-task platform overrides

Instead of `activation.env`, tasks can be overridden per-platform using
`[target.win-64.tasks]`. This approach is more verbose but avoids changing the
activation environment, which could have unintended side effects if other
processes inherit it.

```toml
# Keep existing Unix tasks unchanged, add Windows-specific overrides:
[target.win-64.tasks]
kicker      = "python src/powderline/kicker.py"
mp-simulate = "python src/powderline/mp_simulate.py"
gsas-server = "python src/powderline/gsas_server.py"
test        = "pytest -v"
docs-clean  = "python -c \"import shutil; shutil.rmtree('docs/_build', ignore_errors=True)\""
```

**Recommendation**: The `activation.env` approach is preferred because it
eliminates duplication and correctly handles the path separator difference.
If it causes unexpected environment variable conflicts, the per-task override
approach is the safe fallback.

---

## 4. Issue C — `gsas_server.py` Unix Signal Handling

### What fails

On Windows, any attempt to start or stop the GSAS-II server crashes with an
`OSError` or silently does nothing.

### Root cause

`src/powderline/gsas_server.py` uses Unix-specific process signals in three
places:

```python
# Line 209–210 — GSASServer.start()
signal.signal(signal.SIGTERM, self._signal_handler)
signal.signal(signal.SIGINT, self._signal_handler)

# Line 306 — is_server_running()
os.kill(pid, 0)   # Probe whether process exists

# Lines 324, 335 — stop_server()
os.kill(pid, signal.SIGTERM)  # Graceful shutdown
os.kill(pid, signal.SIGKILL)  # Force kill
```

Windows does not support `SIGTERM` or `SIGKILL`. Specifically:

- `signal.SIGTERM` exists as a constant but `os.kill(pid, signal.SIGTERM)`
  raises `OSError: [WinError 6] The handle is invalid` for any external PID.
- `signal.SIGKILL` does not exist at all on Windows (`AttributeError`).
- `os.kill(pid, 0)` to check process existence also fails with `OSError`.

`SIGINT` (Ctrl+C) **is** supported on Windows and can remain.

> Note: `psutil` is already imported optionally in `get_server_info()` (inside
> a `try/except`) but it is **not** a declared dependency in `pixi.toml`.

> **Superseded (v0.1.2 / 0.2.0).** The fix below was written against the
> PID-file server of v0.1.1. The current server (`gateways/gsasii/server.py`)
> holds a kernel lock on `server.lock` for its lifetime and `status`/`stop`
> consult that lock, so none of the PID-file code shown here exists any more;
> see the last section of this page and KI-14 in the known issues. Kept as the
> record of the analysis.

### Fix: Platform-conditional process management (recommended)

Add `import platform as _platform` alongside the existing imports, then apply
targeted changes to three locations.

#### `is_server_running()` — line 306

```python
def is_server_running() -> bool:
    """Check if server is currently running."""
    if not PID_FILE.exists():
        return False

    try:
        pid = int(PID_FILE.read_text())
    except ValueError:
        PID_FILE.unlink(missing_ok=True)
        return False

    if _platform.system() == "Windows":
        try:
            output = subprocess.check_output(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                stderr=subprocess.DEVNULL,
                text=True,
            )
            return str(pid) in output
        except (subprocess.CalledProcessError, FileNotFoundError):
            PID_FILE.unlink(missing_ok=True)
            return False
    else:
        try:
            os.kill(pid, 0)
            return True
        except (ProcessLookupError, ValueError):
            PID_FILE.unlink(missing_ok=True)
            return False
```

#### `stop_server()` — lines 324 and 335

```python
def stop_server() -> bool:
    """Stop the running server."""
    if not is_server_running():
        print("Server is not running")
        return False

    pid = int(PID_FILE.read_text())
    print(f"Stopping server (PID {pid})...")

    if _platform.system() == "Windows":
        try:
            subprocess.run(["taskkill", "/PID", str(pid)],
                           check=True, capture_output=True)
        except subprocess.CalledProcessError:
            try:
                subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                               check=True, capture_output=True)
            except subprocess.CalledProcessError:
                print("Failed to stop server")
                return False
    else:
        try:
            os.kill(pid, signal.SIGTERM)
            for _ in range(50):
                time.sleep(0.1)
                if not is_server_running():
                    print("Server stopped")
                    return True
            print("Forcing shutdown...")
            os.kill(pid, signal.SIGKILL)
            time.sleep(0.5)
        except ProcessLookupError:
            print("Server process not found")
            PID_FILE.unlink(missing_ok=True)
            return False

    time.sleep(0.5)
    if not is_server_running():
        print("Server stopped")
        return True
    print("Failed to stop server")
    return False
```

#### `GSASServer.start()` — lines 209–210

```python
# Before
signal.signal(signal.SIGTERM, self._signal_handler)
signal.signal(signal.SIGINT, self._signal_handler)

# After
if _platform.system() != "Windows":
    signal.signal(signal.SIGTERM, self._signal_handler)
signal.signal(signal.SIGINT, self._signal_handler)  # SIGINT works on all platforms
```

`SIGTERM` is never raised by Windows for external processes, so omitting its
handler on Windows is safe.

### Alternative option: add `psutil` as an explicit dependency

`psutil` provides a fully cross-platform process management API and is already
used optionally (inside `try/except`) in `get_server_info()`. Adding it as an
explicit dependency in `pixi.toml` would allow unifying the process check and
kill logic without platform branches:

```python
import psutil

def is_server_running() -> bool:
    if not PID_FILE.exists():
        return False
    try:
        pid = int(PID_FILE.read_text())
        return psutil.pid_exists(pid)
    except ValueError:
        PID_FILE.unlink(missing_ok=True)
        return False

# In stop_server():
proc = psutil.Process(pid)
proc.terminate()   # SIGTERM on Unix, TerminateProcess() on Windows
proc.wait(timeout=5)
if proc.is_running():
    proc.kill()    # SIGKILL on Unix, TerminateProcess(force) on Windows
```

**Trade-off**: Adds a new dependency. `psutil` is well-maintained and widely
used; it is low-risk. If the team is open to it, this is the cleaner long-term
solution.

**Recommendation**: Use the platform-conditional approach to avoid adding a new
dependency now. Revisit `psutil` adoption as a separate decision.

---

## 5. macOS-Specific Notes

### Compiler requirement

The `compilers` conda-forge metapackage brings in LLVM clang and a Fortran
compiler for macOS. The toolchain is self-contained within the conda environment
and does **not** require Xcode to be installed.

However, the macOS **linker** (`ld`) is provided by the OS and is not bundled
in conda. On a fresh macOS machine that has never had Xcode installed, the
build will fail with a linker error rather than a compiler error. The fix is a
one-time system step:

```bash
xcode-select --install
```

This should be documented as a **prerequisite** for macOS users in
`docs/getting-started.rst` or `README.md`, not a `pixi.toml` fix.

### Apple Silicon (osx-arm64)

PowderLine ships `osx-arm64`, the dominant architecture for current Mac
hardware. Intel `osx-64` is **not** a shipped platform. (Apple Silicon can still
run `osx-64` builds via Rosetta 2 emulation.)

### Signal handling

macOS is Unix-based. `SIGTERM`, `SIGKILL`, and `os.kill(pid, 0)` all work
correctly on macOS. Issue C is Windows-only; no macOS changes are needed in
`gsas_server.py`.

### Bash scripts

macOS ships with bash (and zsh, with bash available), so any `.sh` scripts work
on macOS. Where a task is written in Python for Windows compatibility, macOS
users use the Python version transparently with no behaviour change.

---

## 6. Implementation Guide

All three issues are independent; they can be implemented in any order. The
order below prioritises testability (the GSAS-II build fix unlocks `pixi
install`, after which the other changes can be verified iteratively).

### Step 1 — pixi.toml: compiler dependencies and platforms (Issue A)

Edit `pixi.toml`:

```toml
# [workspace] — change platforms line
platforms = ["linux-64", "win-64", "osx-arm64"]

# After [pypi-dependencies] — add:
[pypi-options]
no-build-isolation = ["gsas-ii"]

# New sections:
[target.win-64.dependencies]
gfortran = ">=14.2.0,<14.3"
gcc      = ">=14.2.0,<14.3"

[target.osx-arm64.dependencies]
compilers = ">=1.11.0,<2"
clang     = ">=19.1.7,<22"
```

### Step 2 — pixi.toml: cross-platform task fixes (Issue B)

Edit `pixi.toml` — replace the `[tasks]` block and add activation env sections:

```toml
[tasks]
kicker           = "python src/powderline/kicker.py"
mp-simulate      = "python src/powderline/mp_simulate.py"
gsas-server      = "python src/powderline/gsas_server.py"
test             = "pytest -v"
docs             = "sphinx-build -b html docs docs/_build/html"
docs-clean       = "python -c \"import shutil; shutil.rmtree('docs/_build', ignore_errors=True)\""
ui               = { cmd = "python -m GSASII", env = { GSASII_NOPATHHACKING = "true" } }
update-code-hash = "python scripts/update_code_hash.py"

[target.unix.activation.env]
PYTHONPATH = "$PIXI_PROJECT_ROOT/src"

[target.win.activation.env]
PYTHONPATH = "%PIXI_PROJECT_ROOT%\\src"
```

### Step 3 — `gsas_server.py` signal handling (Issue C)

Edit `src/powderline/gsas_server.py`:

1. Add `import platform as _platform` alongside the existing imports at the top.
2. Replace `is_server_running()` with the platform-conditional version (§4).
3. Replace the signal-sending logic in `stop_server()` with the
   platform-conditional version (§4).
4. Wrap `signal.signal(signal.SIGTERM, ...)` in `GSASServer.start()` with
   `if _platform.system() != "Windows":` (§4).

---

## 7. Viewing Server Logs

The GSAS-II server writes to a log file. The portable way to follow it on any
platform is the built-in command (the task lives in the `gsasii` feature):

```
pixi run -e gsasii gsas-server logs
```

If you prefer native tools, the platform equivalents are:

- **Unix (Linux/macOS)**: `tail -f <log_file>`
- **Windows PowerShell**: `Get-Content <log_file> -Wait -Tail 50`

`<log_file>` is `server.log` in the per-user state directory
(`pixi run gsas-server status` prints it): `$XDG_RUNTIME_DIR/powderline` or
`<tempdir>/powderline-<uid>` on Linux/macOS (POSIX mode 0700, ownership
checked), `%LOCALAPPDATA%\powderline` on Windows. The server's port and token
live in the same directory, and the protocol is the same everywhere: loopback
TCP with requests and responses signed by a token only the owning user can
read. What protects that token differs: POSIX mode/ownership checks (enforced
by PowderLine) on Linux/macOS, the user-profile ACL of `%LOCALAPPDATA%` on
Windows (relied on, not checked — a profile whose ACL was loosened by an
administrator is not detected). The start lock uses `flock` on POSIX and
`msvcrt.locking` on Windows.
