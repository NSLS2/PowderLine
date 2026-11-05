# Run at a beamline

**Goal:** run many refinements unattended on a beamline workstation, often
one shared by several users. Keep GSAS-II loaded between runs, run batches
of recipes, and find out what failed without watching every run.

**You need:**
- The environment of your engine ([Install](../getting-started/install.md)).
- Recipes that validate, with the instrument calibrated
  ([Calibrate the instrument](calibrate-instrument.md)).

## 1. Check the environment

```bash
pixi run -e gsasii powderline --doctor
```

The report lists the PowderLine version, the gateways it finds, each
engine's installed version against the version PowderLine supports, and the
GSAS-II server's state. In the core-only environment it looks like this:

```
PowderLine 0.2.0  (Python 3.13.15, Linux-…)
  python: …/.pixi/envs/default/bin/python
  gateways (3, from the powderline.gateways entry points):
    easydiffraction  workflows easydiffraction.rietveld requires ==0.21.1
                     engine: not installed in this environment
    gsasii           workflows gsasii.rietveld, gsasii.spf requires ==5.7.9
                     engine: not installed in this environment
    topas            workflows topas.rietveld, topas.spf requires ==6
                     engine: no installed version declared (topas_version / .powderline_config.yaml)
  GSAS-II server: not running  (state dir /tmp/powderline-1000)
  no problems found
```

An engine that is not installed is not a problem: the core-only environment
runs no engine by design. The command exits non-zero only when no gateway is
found, or an installed engine has the wrong version. It names the repair.

## 2. Use the GSAS-II server

Starting GSAS-II takes a few seconds. The **GSAS-II server** is a
background process that keeps GSAS-II loaded, so a series of runs pays that
start-up once. It serves only `gsasii.*` recipes.

```mermaid
flowchart TB
    R["gsasii recipe"] --> M{"execution mode"}
    M -- "auto or server" --> U{"server usable?<br/>running or started,<br/>and current"}
    U -- yes --> SV["run in the server"]
    U -- "no (auto)" --> IP["run in this process"]
    U -- "no (server)" --> F["fail:<br/>ExecutionBackendError"]
    M -- "in-process" --> IP
```

| Mode | Command line | Python | What happens |
|---|---|---|---|
| auto (default) | none | `execution_mode="auto"` | uses the server, starting it if needed; runs in this process if the server cannot be used |
| server | `--use-server` | `execution_mode="server"` | uses the server, starting it if needed; fails if it cannot |
| in-process | `--no-server` | `execution_mode="subprocess"` | never uses the server; GSAS-II is loaded in this process |

All three modes give the same results and files. The command line prints
which one ran (`Executed using server mode` or `subprocess mode`), and
`result["method"]` says `"server"` or `"subprocess"`.

### Manage the server

```bash
pixi run -e gsasii gsas-server status     # running? its PID, URL, log file, and whether its code is current
pixi run -e gsasii gsas-server stop
pixi run -e gsasii gsas-server restart
pixi run -e gsasii gsas-server logs       # the last 50 lines of its log
pixi run -e gsasii gsas-server start
```

You rarely need `start`: a run in auto or server mode starts the server in
the background by itself. `gsas-server start` runs the server in that
terminal until you stop it, which shows its messages as they happen.

The server runs one refinement at a time. Requests from several processes
wait their turn.

### Restart it after an update

The server loads PowderLine's code once and keeps it. After you update
PowderLine (a `git pull`, another checkout), the running server still has
the old code. PowderLine detects this and calls the server **stale**:

- `gsas-server status` prints `Code: STALE`;
- an auto-mode run prints `WARNING: the GSAS-II server is stale` and runs in
  this process instead;
- a `--use-server` run fails with reason `server_unavailable`.

Restart the server:

```bash
pixi run -e gsasii gsas-server restart
```

### On a shared workstation

The server is per user:

- It listens on the loopback interface (`127.0.0.1`) only, on a free port.
- Its port, process ID and a random secret token live in a private
  directory that only you can read: `$XDG_RUNTIME_DIR/powderline` or
  `<tempdir>/powderline-<uid>` on Linux and macOS, `%LOCALAPPDATA%\powderline`
  on Windows.
- Every request and every answer is signed with that token. The token itself
  never travels.

Other users therefore cannot use your server, and cannot pose as it. Each
user who runs `gsasii.*` recipes gets a server of their own.

To switch the server off, for example in a facility launcher or a locked-down
deployment, set:

```bash
export POWDERLINE_NO_SERVER=1        # also: true, yes, on
```

Then auto-mode runs go in-process and never start a server, `--use-server`
fails, and `gsas-server start` and `restart` refuse to start.

:::{note}
The server picks a free port by itself, so users never collide. Pin a port
only if a firewall rule needs one: set `POWDERLINE_SERVER_PORT` before
`gsas-server start`. Clients find the port in your private directory.
:::

### Set a time limit

By default a run waits for the server's answer as long as it takes. To set a
limit:

```bash
pixi run -e gsasii powderline my_sample/input.json --server-timeout 600
```

In Python, pass `server_timeout=600`. Past the limit the run fails with
`ExecutionBackendError`, reason `timeout`. It does **not** fall back to
running in-process: the job is still running in the server, and a second run
would double the work.

## 3. Run a batch of recipes

A short Python script runs a folder of recipes and keeps going when one
fails:

```python
from pathlib import Path
import powderline

for path in sorted(Path("batch").glob("*/input.json")):
    try:
        recipe = powderline.load_recipe_asset(path)
        result = powderline.run(recipe, path.parent / "output")
    except (ValueError, powderline.PowderLineError) as exc:
        reason = getattr(exc, "reason", type(exc).__name__)
        print(f"{path}: not run ({reason})")
        continue
    print(f"{path}: {result['status']}, Rwp {result['rwp']}")
```

Run it in the engine's environment: `pixi run -e gsasii python batch.py`.
In auto mode the first `gsasii.*` recipe starts the server and the rest
reuse it.

`ValueError` covers a recipe that cannot be read or does not validate.
`PowderLineError` covers every PowderLine error, including a failed run.

## 4. Run unattended

Nothing in a failed run looks like a success:

- A failed run raises `EngineExecutionError` (the engine ran and failed) or
  `ExecutionBackendError` (it never ran), with a `.reason` code.
- The command line prints the reason and exits with status 1. A successful
  run exits 0. So does a TOPAS run that only wrote its input (status
  `generated`).
- The output directory of a failed run holds `failure.json`, the full
  failure record, beside the engine's own files. No result table is written.
- Each run first removes PowderLine's own fixed-name result files from its
  output directory, so a reused directory holds one run's results. This
  happens only once the recipe has validated and the engine is available.
  The engine's own files and anything else in the directory stay.

A result can also succeed with warnings you should read, such as
`gsasii_fit_not_converged` or `output_recipe_not_valid`. Log
`result["warnings"]` with each run.
[Use PowderLine from Python](python-pipelines.md#4-handle-failures) shows
how to catch and record failures.

**Check:**
- `pixi run -e gsasii gsas-server status` says `Server is running` and
  `Code: current (matches this checkout)`.
- In a batch, `result["method"]` is `"server"` for every `gsasii.*` run.
  On the command line, a run prints `Executed using server mode`.

**Next:** [Run a series](sequential-refinement.md),
[Troubleshoot](troubleshooting.md#the-gsas-ii-server).
