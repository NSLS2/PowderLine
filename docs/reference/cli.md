# Command line

One command runs or validates a recipe with every engine. The engine is the
one the recipe's `schema_name` names.

## Synopsis

```text
powderline <recipe.json> [--output DIR] [--validate-only] [--verbose]
                         [--use-server | --no-server] [--server-timeout SECONDS]
                         [--topas-dir DIR] [--topas-version V] [--topas-timeout SECONDS]
powderline --doctor
```

Run it in the pixi environment of the recipe's engine:

```bash
pixi run -e gsasii powderline examples/example_LaB6/input.json --output my_lab6
pixi run -e easydiffraction powderline examples/example_LaB6/easydiffraction/input.json --output my_lab6_ed
pixi run powderline examples/example_LaB6/topas/input.json --topas-version 6 --topas-dir C:/TOPAS6 --output my_lab6_topas
pixi run powderline my_recipe.json --validate-only
pixi run powderline --doctor
```

Validation needs no engine, so `--validate-only` works in every environment.
The pixi task `kicker` runs the same command.

## Options for every recipe

| Option | Effect |
|---|---|
| `<recipe.json>` | The recipe to run, saved as JSON. Required unless `--doctor` is given. |
| `--output DIR` | The output directory. Default: `output/` next to the recipe. |
| `--validate-only` | Validate the recipe, print its summary and warnings, and run nothing. No engine needed; nothing is written. |
| `-v`, `--verbose` | Print the engine's progress, the recipe, the run ID, the informative notes (`level: "info"`) and the disposition counts. |
| `--doctor` | Report what this environment can do, and exit. No recipe needed ([below](#doctor)). |
| `-h`, `--help` | Print the usage and exit. |

## Engine options

Each engine option belongs to one engine. Given for a recipe of another engine,
it is an error and the command exits with status 1.

| Option | Engine | Effect |
|---|---|---|
| *(neither server option)* | GSAS-II | Try the GSAS-II server, start it if needed, and fall back to running in-process. |
| `--use-server` | GSAS-II | Run in the GSAS-II server only. Fail if it cannot be started. |
| `--no-server` | GSAS-II | Run in-process only. Skip the server. |
| `--server-timeout SECONDS` | GSAS-II | Stop waiting for the server's answer after this long. Default: no limit; `0` means no limit. The job itself keeps running on the server. |
| `--topas-dir DIR` | TOPAS | The directory that holds `tc.exe`. |
| `--topas-version V` | TOPAS | The installed TOPAS version, e.g. `6`. A run that executes TOPAS needs it. |
| `--topas-timeout SECONDS` | TOPAS | Stop each `tc.exe` run after this long. Default: 3600; `0` means no limit. |

`--use-server` and `--no-server` cannot be given together. easydiffraction
has no engine options. How the GSAS-II server works is on
[Run at a beamline](../how-to/beamline-operation.md). How TOPAS runs are set
up is on [Run TOPAS recipes](../how-to/run-topas.md).

:::{note}
PowderLine cannot read a version from `tc.exe`. You declare the installed
TOPAS version, and it must equal the recipe's `engine_version`. When no
`tc.exe` is found, a TOPAS run writes the input files only and returns
`status: "generated"`.
:::

## Exit status

| Status | When |
|---|---|
| 0 | The run finished with `status` `"ok"`, or `"generated"` (TOPAS input written, TOPAS not run). |
| 0 | `--validate-only`: the recipe is valid. Warnings do not change the status. |
| 0 | `--doctor` found no problem, or `--help` printed the usage. |
| 1 | An unreadable or invalid recipe, a template, an engine option for another engine, a missing engine, a failed run, or a problem found by `--doctor`. |
| 2 | A usage error, reported before anything runs: no recipe and no `--doctor`, both `--use-server` and `--no-server`, an unknown option, or a timeout that is not a number. |

A failed run prints its [failure reason](messages.md#failure-reasons) and the
files kept for diagnosis. For GSAS-II it also prints the engine's last console
lines.

## Templates are refused

The command refuses to run a recipe that looks like a template:

- its path contains `template` (in any case);
- or its `payload` is missing, or lacks a block the workflow needs:
  `xrd_data`, `instrument`, `refinement_controls`, and `phases` (Rietveld) or
  `single_peaks` (single-peak fitting).

Copy a template into your own directory and fill it in before you run it.

:::{note}
Only the command refuses templates. `powderline.run()` does not check for
them: it runs any recipe that validates, whatever its path.
:::

## Doctor

`powderline --doctor` reports what this environment can do:

- the PowderLine version, the Python and the platform;
- every gateway it finds, with its workflows and the engine version it
  requires;
- whether that engine is installed here, and at which version;
- for TOPAS, the version you declared;
- the GSAS-II server's state directory, and whether a server is running.

It exits with status 1 when it finds a problem:

- no gateway at all;
- an installed engine outside its required version;
- an engine whose version cannot be read;
- a `.powderline_config.yaml` that cannot be read.

An engine that is not installed is reported but is not a problem. The default
environment validates every recipe and runs none by design.

## Environment variables

| Variable | Effect |
|---|---|
| `POWDERLINE_NO_SERVER` | Set to `1`, `true`, `yes` or `on` to never use the GSAS-II server. The default mode then runs in-process, and `--use-server` is an error. |
| `POWDERLINE_SERVER_PORT` | The port the GSAS-II server listens on (1–65535). Default: a free port chosen at start. |

## Configuration file

The TOPAS options can also come from `.powderline_config.yaml`. PowderLine
reads the first one it finds: in the current directory, then in your home
directory. An option given on the command line wins.

```yaml
topas:
  dir: C:/TOPAS6      # the directory that holds tc.exe (--topas-dir)
  version: "6"        # the installed TOPAS version (--topas-version)
  timeout: 3600       # seconds per tc.exe run; 0 = no limit (--topas-timeout)
```

PowderLine looks for `tc.exe` only in `--topas-dir` or `topas.dir`. A
malformed file is an error, not an empty configuration.
