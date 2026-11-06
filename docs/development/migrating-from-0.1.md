# Migrating from 0.1

This page is for developers who hold recipes or code written for PowderLine
0.1.x, which used the single recipe schema 0.1–0.26.0 (`GSASII_Rietveld`,
`GSASII_SPF`). PowderLine 0.2.0 refuses those recipes at `schema_name`.

## What changed

| Topic | 0.1.x | 0.2.0 |
|---|---|---|
| `schema_name` | `GSASII_Rietveld`, `GSASII_SPF` | `gsasii.rietveld`, `gsasii.spf`, `topas.rietveld`, `topas.spf`, `easydiffraction.rietveld` |
| Engine choice | `run(recipe, output_dir, engine=...)`, translated from GSAS-II's terms | The recipe names one engine and is written in its own terms and units; nothing is translated |
| Schema versions | `"schema_version": "0.26.0"` | `"core_schema_version": "0.1.0"` and `"engine_schema_version": "0.1.0"` |
| Parameters | `structure` and `parameterization` blocks; optional bounds | One phase block; `[value, flag]` in gsasii (no bounds); `[value, flag, min, max]` in topas and easydiffraction |
| Unknown keys | Ignored | Errors |
| Result outcome | `success`, `error` keys | `status` (`ok`, `generated`); a failure raises `EngineExecutionError` or `ExecutionBackendError` |
| `rwp` | The engine's own value | PowderLine's uniform Rwp over the fit window; the engine's value is under `engine_details` |
| `validate()` | Returned the model | Returns `ValidationResult` (`.recipe`, `.warnings`) |
| Command | A separate `topas-kicker` for TOPAS | `powderline` for every engine |
| Environments | GSAS-II in the default environment; `easydiff` | Default is core-only; `gsasii`, `easydiffraction`, `all`, `dev`. Remove a stale `.pixi/envs/easydiff`; `gsas-server` needs `-e gsasii` |
| Imports | `powderline.topas`, `powderline.easydiff`, `powderline.RecipeModel`, `powderline.schema`, `powderline.GSASClient` | `powderline.gateways.topas`, `powderline.gateways.easydiffraction`; the recipe models are the gateways' (`powderline.gateways.gsasii.schema.GsasiiRietveldRecipe`, …), and you normally get one from `validate(...).recipe`; `powderline.gateways.gsasii.client.GSASClient`. There are no compatibility aliases: the old imports raise `ModuleNotFoundError` or `ImportError` |
| Simulation check | `validate_simulation_mode_parameters()` | Gone: a `gsasii.*` recipe with `refinement_cycles: 1` and a refine flag set fails validation |

The full list is in the [CHANGELOG](../about/changelog.md) entry for 0.2.0.
The current schemas are on [Versions](../reference/versions.md).

## Convert GSAS-II recipes

`scripts/convert_recipe_026.py` turns a `GSASII_Rietveld` or `GSASII_SPF`
recipe into a `gsasii.rietveld` or `gsasii.spf` recipe:

```bash
pixi run python scripts/convert_recipe_026.py old.json -o new.json
```

It prints one line per change (`<path>: <what changed>`) and writes the new
recipe. Without `-o` it only prints the report. It never edits the input.

The converted recipe states explicitly what 0.1.x refined. Refine flags are
expanded to the groups GSAS-II refined together, and GSAS-II's silent
defaults are written out.

```{important}
Where the result would not validate, or the refinement 0.1.x ran cannot be
known, the converter stops with exit status 1 and lists every problem. It
never guesses. Each message names the field and, where there is one, the
value to write.
```

Typical stops: origin choice `:1`, an atom 5e-6 to 2e-3 off a special
position, a `Uaniso` with only some of its six components, a Kα doublet, TOF
or neutron instrument, non-isotropic broadening, and a value below a GSAS-II
floor. The 0.26.0 LaB6 recipes stop on their background peak's width, which
is below GSAS-II's floor ({ref}`EB-35 <eb-35>`).

## TOPAS and easydiffraction recipes

There is no converter for these engines. A `topas.*` or `easydiffraction.*`
recipe holds that engine's model of your sample, in its own parameters and
units. Write it natively, starting from the engine pages
([TOPAS](../engines/topas.md), [easydiffraction](../engines/easydiffraction.md))
and the committed fixtures in `tests/data/topas/native/` and
`tests/data/easydiffraction/native/`. Each fixture folder has a README that
works through the derivations.

The phase block (`space_group`, `unit_cell`, `atoms`) is identical in every
engine. You can paste it from a converted `gsasii.*` recipe and add the bounds
slots the engine expects.

## Leftover servers from before 0.1.2

GSAS-II servers from PowderLine 0.1.1, or from a 0.2.0 checkout older than
the 0.1.2 merge, used fixed shared files, port 19471, and accepted
unauthenticated requests ({ref}`KI-14 <ki-14>`). The current client never
uses them. `gsas-server status` and `stop` cannot see them, so one may still
be running unnoticed, perhaps auto-started. It runs as `gsas_server.py`
(0.1.1) or `gateways/gsasii/server.py`.

Stop your current server first. Then list your remaining server processes,
check the list, and end each one by its process ID.

::::{tab-set}

:::{tab-item} Linux and macOS

```bash
pixi run -e gsasii gsas-server stop
ps -u "$(id -un)" -o pid=,args= | grep -E "python[^ ]* .*(gsas_server\.py|gsasii[/.]server)"
kill <PID>        # for each process listed
```

:::

:::{tab-item} Windows

```powershell
pixi run -e gsasii gsas-server stop
Get-CimInstance Win32_Process -Filter "Name LIKE 'python%'" |
  Where-Object CommandLine -match 'gsas_server\.py|gsasii[/\\.]server' |
  Where-Object { (Invoke-CimMethod -InputObject $_ -MethodName GetOwner).User -eq $env:USERNAME } |
  Select-Object ProcessId, CommandLine
Stop-Process -Id <ProcessId>    # for each process listed
```

You can also end the `python … gsas_server.py start` or `… server.py start`
processes in Task Manager.

:::

::::

## Checklist

1. Run the converter on each GSAS-II recipe. Read every report line: each is
   a place where 0.1.x did something your recipe did not say.
2. Where it stops, decide from the message. Never paste a value you can't
   justify.
3. Expect different numbers from 0.1.x, even for a clean conversion: the fit
   window, the sample-broadening and background defaults, and `rwp` all
   differ. GSAS-II's own statistics are under `engine_details`.
4. Write TOPAS and easydiffraction recipes natively.
5. On an existing checkout, install the engine you use
   (`pixi install --frozen -e gsasii`), then run
   `pixi reinstall powderline --all` and `pixi run powderline --doctor`.
6. In code: drop `engine=`, read `validate(...).recipe`, catch the two
   exceptions instead of checking `success`, and update the imports in the
   table above (`powderline.gateways.<engine>`, `GSASClient` from
   `powderline.gateways.gsasii.client`).
