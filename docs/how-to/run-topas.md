# Run TOPAS recipes

**Goal:** run a `topas.rietveld` or `topas.spf` recipe with TOPAS 6, or
write TOPAS's input on any machine and run it later.

**You need:**
- A recipe that states `"engine_version": "6"` at its top level.
- To run TOPAS: a Windows machine with TOPAS 6 installed, and the folder
  that holds `tc.exe`.
- To write the input only: any PowderLine environment, on any platform.

TOPAS has no Python package. PowderLine writes TOPAS's input file (`.inp`)
and data file (`.xye`), runs `tc.exe` and reads what TOPAS writes back.

## 1. Validate

```bash
pixi run powderline my_sample/input.json --validate-only
```

Validation needs no TOPAS. It works in every environment, on every
platform.

## 2. Tell PowderLine where TOPAS is and which version it is

PowderLine never searches for TOPAS. `tc.exe` carries no version
PowderLine could read, so you **declare** both the folder and the version.
Give them on the command line:

```bash
pixi run powderline my_sample/input.json --topas-version 6 --topas-dir C:/TOPAS6
```

Or set them once in `.powderline_config.yaml`, in the folder you run from
or in your home folder:

```yaml
topas:
  dir: "C:/TOPAS6"
  version: 6
  timeout: 3600
```

The command-line flags win over the file. PowderLine reads only the first
file it finds: a file in the folder you run from replaces the one in your
home folder. The template
`.powderline_config.yaml.example` in the repository shows the block.

The declared version must equal the recipe's `engine_version`, written as
the release number: `6`, not `6.0`. PowderLine 0.2.0 supports TOPAS 6 only.

In Python:

```python
result = powderline.run(recipe, Path("out"), topas_version="6", topas_dir=Path(r"C:\TOPAS6"))
```

## 3. Run

```bash
pixi run powderline my_sample/input.json --topas-version 6 --topas-dir C:/TOPAS6
```

When the recipe models a background, `tc.exe` runs twice: once for the fit,
then once for the background alone, at the refined values. TOPAS 6 cannot
output the fit's background, so the second run provides the `y_bkg` column of
`fit_profile.txt`. The second run is skipped when the fit's values are not
finite.

**Check:** the command line ends with `Refinement complete. Final Rwp: …`,
and `output/` holds `fit_profile.txt` and the other report files.

## Write the input only, anywhere

With no TOPAS folder declared, or none holding `tc.exe`, PowderLine writes
TOPAS's input and stops. This works on Linux and macOS too:

```bash
pixi run powderline my_sample/input.json
```

```
ℹ️ Generated the engine input only (topas_generate_only, 0.0s):
   my_sample/output/my_sample.inp
   my_sample/output/my_sample.xye
   my_sample/output/output_recipe.json
   my_sample/output/parameter_dispositions.csv
```

This is not a failure. The result has `status: "generated"`, the command
exits 0, and the `topas_generate_only` note says how to run it. Run the
`.inp` on the TOPAS machine yourself, or run the recipe there.

## Set a time limit

Each `tc.exe` run is stopped after 3600 seconds by default, so a TOPAS
waiting for input (a licence dialog, for example) cannot hang a run. Change
the limit with `--topas-timeout SECONDS`, `topas.timeout` in
`.powderline_config.yaml`, or `topas_timeout` in Python. `0` means no limit.

Past the limit, the run fails with `ExecutionBackendError`, reason
`timeout`. If only the background run is stopped, the fit still succeeds.
`y_bkg` is then empty, with the warning `topas_background_not_calculated`.

## Use plain folder names

TOPAS reads file paths in the Windows ANSI code page. A folder name that
code page cannot hold, such as Greek on a Western-European Windows, makes
TOPAS write nothing. Latin-1 names and spaces work.

PowderLine handles this for you where it can. It passes such a folder to
`tc.exe` by its short 8.3 name. If the drive has no short names, the run
stops before TOPAS starts, with reason `backend_error` and a message to use
an ASCII output folder (`--output DIR`).

## What a run writes

Beside the report files every engine writes, a TOPAS run keeps TOPAS's own
files. When the output path ends in a folder named `output`, `<base>` is
the name of the folder above it (`my_sample/output` gives `my_sample`).
Otherwise it is `topas`.

| File | What it is |
|---|---|
| `<base>.inp`, `<base>.xye` | what TOPAS was given |
| `<base>_results.csv` | TOPAS's refined values and statistics |
| `<base>_profile.txt` | TOPAS's calculated pattern |
| `<base>_p<n>_peaks.txt` | the reflection list of phase `n` |
| `<base>_bkg.inp`, `<base>_bkg_profile.txt` | the background-only run |

A base name that is not ASCII is replaced by `topas`, with the warning
`topas_base_name_sanitized`.

[Outputs](../reference/outputs.md) describes the report files and the result.

## What to expect in the result

- `converged` is always `null`: TOPAS 6 writes no convergence signal
  ({ref}`EB-85 <eb-85>`).
- `engine_details["tc_path"]` names the `tc.exe` that ran.
- TOPAS reports success and failure with the same exit code, so PowderLine
  judges a run by its output files. If TOPAS wrote none, the run fails with
  reason `output_missing`. Whatever `tc.exe` printed is in `failure.json`,
  under `failure.console_tail`. Otherwise its messages are in its console
  window and in `tc.log`, in the TOPAS folder.
- A file TOPAS wrote that PowderLine cannot read strictly fails with reason
  `output_malformed`.

The [TOPAS page](../engines/topas.md) lists what TOPAS does with a recipe
and what PowderLine refuses on its behalf.

**Next:** [Troubleshoot](troubleshooting.md),
[Run at a beamline](beamline-operation.md).
