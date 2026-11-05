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
| Environments | GSAS-II in the default environment; `easydiff` | Default is core-only; `gsasii`, `easydiffraction`, `all`, `dev` |

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
   exceptions instead of checking `success`, and import `GSASClient` from
   `powderline.gateways.gsasii.client`.
