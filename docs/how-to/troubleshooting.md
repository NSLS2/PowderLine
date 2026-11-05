# Troubleshoot

**Goal:** find what an error message means and how to fix it.

Start every investigation with validation. It needs no engine and lists
**every** problem at once, each at its field:

```bash
pixi run powderline my_sample/input.json --validate-only
```

Then run with `--verbose` for more detail. The sections below follow what
you see: the recipe is refused, the command will not start, the run fails,
the run succeeds with warnings, or the GSAS-II server misbehaves.

## The recipe does not validate

Validation errors look like this, one line per problem:

```
❌ Recipe validation failed: my_sample/input.json

Validation errors:
  • payload -> instrument -> geometry: Field required
```

Most messages name the value to write. Fix them all and validate again.

### A required field is missing

```
  • payload -> instrument -> geometry: Field required
  • payload -> phases -> LaB6 -> scale: Field required
```

**Cause:** nothing in a recipe is guessed. Every recipe needs its frame
(`schema_name`, `core_schema_version`, `engine_schema_version`, `payload`),
`xrd_data`, the whole `instrument` block in the engine's layout and
`refinement_controls`. Every phase needs `space_group`, `unit_cell`, `atoms`
and `scale`.

**Fix:** copy the missing block from the matching example
(`examples/example_LaB6/input.json`, `examples/example_LaB6/topas/input.json`,
`examples/example_LaB6/easydiffraction/input.json`).
[Fields](../reference/fields.md) lists every field and whether it is
required.

### A field is unknown, or `null`

```
  • payload -> instrument -> radiaton: Extra inputs are not permitted
  • payload -> phases -> LaB6 -> peak_broadening: Value error, peak_broadening must not be null; leave it out instead
```

**Cause:** an unknown key is an error at every level, usually a typo. A block
that may be left out is left out, never written as `null`.

**Fix:** correct the spelling against [Fields](../reference/fields.md), or
delete the key.

### `schema_name` does not name an engine or workflow

```
  • schema_name: schema_name 'gsasii.reitveld' is not a gsasii workflow; expected one of gsasii.rietveld, gsasii.spf
❌ no PowderLine gateway named 'gsas2' is installed (available: easydiffraction, gsasii, topas). …
```

**Cause:** `schema_name` is `<engine>.<workflow>`, one of
`gsasii.rietveld`, `gsasii.spf`, `topas.rietveld`, `topas.spf` and
`easydiffraction.rietveld`. A misspelled workflow is reported against the
engine's workflows. An unknown engine name lists the engines installed.

**Fix:** correct the name.

A recipe whose `schema_name` is `GSASII_Rietveld` or `GSASII_SPF` is written
for PowderLine 0.1. See [Migrating from 0.1](../development/migrating-from-0.1.md).

### A schema version is not accepted

```
  • core_schema_version: Value error, core_schema_version '1.1.0' is not supported by PowderLine 0.2.0 (accepted: ==0.1.0; current: 0.1.0)
```

**Fix:** write `"core_schema_version": "0.1.0"` and
`"engine_schema_version": "0.1.0"`. [Versions](../reference/versions.md)
lists what each engine accepts.

### A parameter has the wrong shape

```
  • payload -> instrument -> broadening -> U: Value error, bounds are not supported for this parameter in this engine schema: expected [value, refine_flag], got a 4-element [value, refine_flag, min, max] list
  • payload -> phases -> LaB6 -> unit_cell -> a: Value error, expected [value, refine_flag, min, max] (min/max may be null), got a 2-element list
  • payload -> phases -> LaB6 -> scale -> refine_flag: Input should be a valid boolean
```

**Cause:** each engine has one parameter shape. `gsasii.*` uses
`[value, refine_flag]`. `topas.*` and `easydiffraction.*` use
`[value, refine_flag, min, max]`, with `null` for an open bound. The flag is
`true` or `false`, not `1` or `"true"`. The value is a number, not a string.

**Fix:**

```json
"U": [0.01, true]                  // gsasii
"U": [0.01, true, null, null]      // topas, easydiffraction
```

### The space group is refused

```
  • payload -> phases -> LaB6 -> space_group: Value error, space group 'Pm-3m' is not in the canonical form; write 'P m -3 m'
  • … space_group: Value error, GSAS-II cannot use origin choice 1 ('F d -3 m:1'); state the structure in origin choice 2 (F d -3 m:2) (GSAS-II quirk EB-03)
```

**Cause:** `space_group` must be gemmi's canonical name, which states the
setting: `"F d -3 m:2"`, `"R -3 m:H"`, `"C 1 2/m 1"`. A bare two-origin or
rhombohedral symbol, or a short monoclinic one, lists the settings it could
mean. Each engine also refuses the settings it cannot compute.

**Fix:** write the name the message gives. For a setting your engine
refuses, transform the structure to the setting the message suggests. The
engine pages list the refused settings: [GSAS-II](../engines/gsasii.md),
[TOPAS](../engines/topas.md), [easydiffraction](../engines/easydiffraction.md).

### The cell does not fit the space group

```
  • payload -> phases -> LaB6 -> unit_cell: Value error, unit cell is inconsistent with 'P m -3 m' (cubic): stated b = 4.2, but by symmetry b = a; write b = 4.15682
```

**Fix:** state all six values. Tied lengths equal the first member exactly.
Fixed angles are exactly 90, or 120.

### An atom is near a special position, but not on it

```
  • payload -> phases -> LaB6 -> atoms -> B: Value error, atom 'B' (multiplicity 6 in 'P m -3 m'): (0.4999999, 0.5, 0.2021) is 1e-07 from a special position, not on it (x = 1/2, y = 1/2); write x = 0.5
  • payload -> phases -> DRX_33 -> atoms -> Li: Value error, position (0.0005, 0, 0) is 0.001 from the special position (0, 0, 0) (multiplicity 4) in 'F m -3 m' without being on it: state the special-position coordinates to at least 6 decimals, or move the atom at least 0.002 (fractional) off it
```

**Fix:** write a constant with a decimal form exactly (`0.5`), and a third to
at least six decimals (`0.333333`). An atom meant to sit off a special
position must be at least 2e-3 away: see
[Model disorder near special positions](disorder.md).

### A refine flag breaks a symmetry tie

```
  • payload -> phases -> DRX_33 -> unit_cell -> b: Value error, cubic cell ('F m -3 m'): a, b, c are one parameter; set the same refine flag on all three
  • payload -> phases -> DRX_33 -> atoms -> O1 -> x: Value error, atom 'O1' (multiplicity 4 in 'F m -3 m'): x is fixed by symmetry (= 1/2); set its refine flag to false
  • payload -> phases -> Li4MgWO6_SG12 -> unit_cell -> c: GSAS-II refines a, c, beta together (it varies the reciprocal metric tensor), but only a is refined; refine all of a, c, beta or none
```

**Fix:** give every member of a tie group the same flag. Keep a parameter
fixed by symmetry at `false`. In `gsasii.*`, refine GSAS-II's oblique cell
groups whole. See [Refine a structure](refine-structure.md#2-choose-what-to-refine).

### A value is outside what the engine computes with

```
  • payload -> instrument -> corrections -> axial_divergence: Value error, axial_divergence (SH/L) must be at least 0.002, got 0.0005: GSAS-II computes Bragg and Peak List profiles with SH/L >= 0.002 whatever is stated (GSAS-II quirk EB-37)
  • payload -> phases -> LaB6 -> atoms -> La -> Uiso: Uiso (TOPAS beq = 8 pi^2 Uiso, limits -10..20) is refined from 0.3, above TOPAS's default maximum 0.25330295910584444: TOPAS would move it to the limit without saying so; start at or below 0.25330295910584444, or state max to replace TOPAS's limit
  • payload -> phases -> LaB6 -> unit_cell -> a: a 35.0 is outside easydiffraction's physical limit [0, 30]: the engine refuses it (EB-71)
  • payload -> xrd_data -> Itth_weights -> 1203: weight 2000000000.0 (sigma 2.24e-05) is above 1e+08: easydiffraction would replace sigma < 1e-4 by 1.0 without saying so (EB-73); rescale the intensities and weights
```

**Cause:** the engine would silently compute with another value: a floor, a
default limit, a replaced weight. PowderLine refuses the recipe instead.

**Fix:** write the value the message names. For a TOPAS or easydiffraction
limit, start inside it or state your own bound. The engine pages list every
floor and limit.

## The command will not start

### "This appears to be a template file"

```
❌ Error: This appears to be a template file (filename or path contains 'template').
```

**Cause:** the command line refuses a recipe whose path contains `template`,
or whose payload lacks the blocks its workflow needs. The skeletons in
`examples/example_template/` are deliberately incomplete.

**Fix:** copy the template, or a real example such as
`examples/example_LaB6/`, into a folder whose path has no `template` in it.
Fill in the blanks and validate.

### An engine flag for another engine

```
❌ --no-server applies to 'gsasii' recipes only; this recipe's schema_name names the 'topas' engine
```

**Fix:** use only the flags of the recipe's engine. `--use-server`,
`--no-server` and `--server-timeout` belong to `gsasii.*`. `--topas-dir`,
`--topas-version` and `--topas-timeout` belong to `topas.*`.
[Command line](../reference/cli.md) lists every flag.

### The engine is not installed in this environment

```
❌ the 'gsasii' gateway needs GSAS-II, which is not installed in this environment; use the 'gsasii' pixi environment (install it with: pixi install -e gsasii; run with: pixi run -e gsasii ...)
```

**Cause:** the default environment validates every recipe but runs no
engine. `gsasii.*` recipes run in the `gsasii` environment,
`easydiffraction.*` recipes in the `easydiffraction` environment.

**Fix:**

```bash
pixi install --frozen -e gsasii
pixi run -e gsasii powderline my_sample/input.json
```

A `ModuleNotFoundError: No module named 'GSASII'` from your own script means
the same thing: run it with `pixi run -e gsasii python …`.

### The engine version is not supported, or not declared

```
❌ the 'gsasii' gateway supports GSAS-II ==5.7.9, but 5.8.0 is installed; install a supported version
❌ the TOPAS version to run is not declared: PowderLine cannot read it from tc.exe, so set topas_version (run argument) or topas.version in .powderline_config.yaml; this recipe is written for TOPAS 6
```

**Cause:** PowderLine checks each engine's version. GSAS-II and
easydiffraction come from the pixi lock, so a mismatch means the environment
was changed by hand. TOPAS's version cannot be read, so you declare it.

**Fix:** `pixi install --frozen -e gsasii` restores the pinned GSAS-II. For
TOPAS, pass `--topas-version 6` and `--topas-dir`, or set them in
`.powderline_config.yaml` ([Run TOPAS recipes](run-topas.md)).

### No gateway is found

```
❌ no PowderLine gateway named 'gsasii': no 'powderline.gateways' entry points were found at all, …
```

**Fix:** run `pixi run -e gsasii powderline --doctor`. It reports what the
environment can do and names the repair. The cause is a stale install, see
{ref}`KI-13 <ki-13>`.

## The run fails

A failed run prints one of two lines. The word in parentheses is the
**reason**, `e.reason` in Python:

```
❌ Refinement failed (diverged): …          the engine ran and failed
❌ Could not run the engine (timeout): …    the engine never ran
```

The output directory keeps the engine's own files and `failure.json`, the
full failure record. For a `gsasii.*` run, the command line also prints
GSAS-II's last console lines. That is where GSAS-II says what went wrong:
"Refinement failed - singular matrix", "Removing parameter: …". In Python
the same text is `e.result["failure"]["console_tail"]`.

[Messages](../reference/messages.md#failure-reasons) says what each reason
means. What to do:

### The engine ran and failed

| Reason | What to do |
|---|---|
| `unusable_site` | Write the equivalent position the message names. |
| `diverged` | Refine fewer parameters, start closer to the data, check correlations in `dummy.lst` (GSAS-II). |
| `peak_fit_failed` | Check the peaks' starting values ([Fit single peaks](single-peak-fitting.md)). |
| `engine_crashed` | Read the message and the traceback in `failure.json`. |
| `output_missing` | Read `failure.console_tail` in `failure.json`, TOPAS's console window and `tc.log`. |
| `output_malformed` | Read the message: it names the file and the problem. |

### The engine never ran

| Reason | What to do |
|---|---|
| `server_unavailable` | See [The GSAS-II server](#the-gsas-ii-server). |
| `server_disabled` | Run in-process (`--no-server`), or unset `POWDERLINE_NO_SERVER`. |
| `communication_failed` | Read the server log: `pixi run -e gsasii gsas-server logs`. |
| `timeout` | Raise `--server-timeout` or `--topas-timeout`. For TOPAS, look for a dialog waiting for input. |
| `backend_error` | Read the message. |

:::{note}
`ℹ️ Generated the engine input only (topas_generate_only, …)` is not a
failure. No `tc.exe` was declared, so PowderLine wrote TOPAS's input and
stopped. See [Run TOPAS recipes](run-topas.md).
:::

## The run succeeds with warnings

Warnings never change what the recipe says. The command line prints those
of level `warning`; `--verbose` lists the `info` notes too.
[Messages](../reference/messages.md) explains every code. The ones you meet
most often:

- `gsasii_broadening_default_applied`: size or strain was left out, so
  10 µm and 0 microstrain, fixed, were applied. State `peak_broadening` to
  choose.
- `gsasii_refinement_message`: a message GSAS-II stored with the refinement,
  such as highly correlated parameters.
- `gsasii_fit_not_converged`, `easydiffraction_fit_not_converged`: the
  refinement stopped before the engine's convergence criterion. The values
  are reported. Add cycles or iterations, or hold poorly determined
  parameters.
- `<engine>_parameters_not_varied`: the engine varied fewer parameters than
  the recipe asked for. Compare `engine_details["parameters_requested"]`
  with `parameters_varied`.
- `topas_parameter_at_limit`, `easydiffraction_parameter_at_limit`: a
  refined value ended at a bound or an engine limit.

### "Output recipe … (not valid as written)"

The result says `output_recipe_valid: false`, with the warning
`output_recipe_not_valid`.

**Cause:** the engine returned a value the recipe format refuses: an
occupancy outside 0 to 1, a crystallite size of zero or below, a negative
`Uiso` in an easydiffraction recipe, a profile that makes a width negative
({ref}`EB-87 <eb-87>`), or a split atom inside the 2e-3 band of a special
position ({ref}`KI-18 <ki-18>`). The result itself is
unaffected. `output_recipe.json` is still written, so you can see what the
engine produced, and `parameter_dispositions.csv` shows each value with its
ESD.

**Fix:** read the warning; it names each offending value. Decide whether the
fit is physical. Then hold the parameter, or fix the output recipe, before
you run it again. Some committed examples do this on purpose, as teaching
examples ({ref}`KI-15 <ki-15>`).

### Highly correlated parameters

```
** Warning: parameters 0 and 1 are 99.8% correlated **
```

High correlation is common and often acceptable, for example between
background coefficients. It matters when the fit does not converge, values
are unphysical, or uncertainties are large. Then reduce the background
terms, hold a parameter, widen the fit window or refine in stages. See
[Good refinement practice](../concepts/refinement-practice.md).

### Rwp differs from what the engine prints

`rwp` is PowderLine's **uniform** statistic. It is computed the same way for
every engine, over the data points inside the fit window with a positive
weight. The engine's own value is under `engine_details`. GSAS-II's own R
values are capped at 100 %, and its `GOF` means √(reduced χ²) in a Rietveld
refinement but the reduced χ² itself in a peak fit.
[Comparing engines](../concepts/comparing-engines.md) explains how to
compare results across engines.

## The GSAS-II server

[Run at a beamline](beamline-operation.md) explains the server and its
modes.

### The run is slow

**Cause:** the run went in-process, so GSAS-II was loaded for this run
alone. The command line prints `Executed using subprocess mode`.

**Fix:**
1. Check the server: `pixi run -e gsasii gsas-server status`.
2. If `POWDERLINE_NO_SERVER` is set, for example by a facility launcher,
   in-process runs are by design.
3. If the status says `Code: STALE`, stop the server (below).
4. Read the server log: `pixi run -e gsasii gsas-server logs`.

### The server is stale

`WARNING: the GSAS-II server is stale`, a `--use-server` run that fails with
reason `server_unavailable`, or `gsas-server status` printing `Code: STALE`.

**Cause:** the server loads PowderLine's code once and keeps it. After an
update of PowderLine it still runs the old code, so PowderLine will not use
it.

**Fix:** stop the stale server.

```bash
pixi run -e gsasii gsas-server stop
```

The next run in auto or server mode starts a current server in the
background.

:::{note}
`gsas-server restart`, like `gsas-server start`, runs the server in the
terminal you type it in. The command does not return while the server runs.
Use it only in a terminal of its own.
:::

### The server will not start

```
❌ Could not run the engine (server_unavailable): Server not available and fallback disabled…
```

**Fix:**
1. Check whether a server is running: `pixi run -e gsasii gsas-server status`.
2. Stop a hung server: `pixi run -e gsasii gsas-server stop`.
3. Run `pixi run -e gsasii gsas-server start` in a terminal of its own to
   see its messages as it starts. The server then runs in that terminal
   until you press Ctrl+C.
4. Meanwhile, run in-process: add `--no-server`.

If the message names `POWDERLINE_SERVER_PORT`, the pinned port is malformed
or busy. Unset the variable, and the server picks a free port.

### "Refusing to use GSAS-II server state directory …"

**Cause:** the server keeps its state in a private per-user directory. This
one is a symbolic link, owned by another user, or open to other users, for
example because it was pre-created in a shared `/tmp`. PowderLine skips the
server: auto-mode runs go in-process, and `--use-server` fails.

**Fix:** remove the directory named in the message. It is recreated
privately at the next start. If it is not yours, ask an administrator.

"Refusing to keep the GSAS-II server state under …" means the parent
folder, your `TMPDIR`, would let other users replace the directory. Point
`TMPDIR`, or `XDG_RUNTIME_DIR`, at a private folder.

### A server keeps running that `gsas-server` cannot see

**Cause:** the state directory was deleted while the server ran, for example
by a temporary-file cleaner. Clients cannot reach the server any more, and
`status` and `stop` cannot find it ({ref}`KI-11 <ki-11>`).

**Fix:** end the process by hand. On Linux and macOS:

```bash
pkill -u "$USER" -f "gsasii[/.]server"
```

On Windows, end the Python process running `server.py start` in Task
Manager.

## Files and environment

### Permission denied in the output folder

```
PermissionError: [Errno 13] Permission denied: 'output/fit_profile.txt'
```

**Fix:** check that you can write the folder and that the disk is not full.
Close the report files in other programs, such as a spreadsheet. Or choose
another folder with `--output DIR`.

### A command runs in the wrong environment

**Cause:** mixing a conda environment or the system Python with pixi, or
running a recipe in an environment without its engine.

**Fix:** run everything through pixi and name the environment:

```bash
pixi run powderline my_sample/input.json --validate-only       # any environment
pixi run -e gsasii powderline my_sample/input.json
pixi shell -e gsasii                                           # then run commands inside it
```

`pixi run gsas-server status` without `-e` is reported as ambiguous by pixi.
Add `-e gsasii`.

## Getting more help

1. Validate: `pixi run powderline my_sample/input.json --validate-only`.
2. Run with `--verbose`.
3. Read the engine's log: `output/dummy.lst` for GSAS-II, the TOPAS console
   and `tc.log`, the lmfit report printed for easydiffraction.
4. Compare with a working example, such as `examples/example_LaB6/input.json`.
5. Open an issue on GitHub with the full output, the recipe, the output of
   `pixi run -e gsasii powderline --doctor` and, for TOPAS, the version you
   declared.
