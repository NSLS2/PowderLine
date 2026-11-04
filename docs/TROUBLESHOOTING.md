# PowderLine Troubleshooting Guide

Common errors and solutions when working with PowderLine. Every recipe problem
is reported by validation with its field path, so the first move is always

```bash
pixi run kicker --validate-only path/to/input.json
```

which needs no engine and lists **every** problem at once.

## Template File Errors

**Error:**
```
❌ Error: This appears to be a template file (filename or path contains 'template').
Template files are not meant to be run directly.
```

**Cause:** Trying to run one of the skeletons under `examples/example_template/`
(or a recipe whose payload lacks the blocks its workflow needs).

**Solution:**
- Copy the template directory to a name without "template", or start from a
  real example such as `examples/example_LaB6/`
- Fill in the blanks (the data arrays, the wavelength, the element `X`)
- Validate the copy: `pixi run kicker --validate-only my_case/input.json`

**Why it matters:** the templates deliberately do not validate (empty data,
wavelength 0, element `X`); they document the shape, not a runnable recipe.

---

## `schema_name` does not name an engine

**Error:**
```
❌ Recipe validation failed: input.json
Validation errors:
  • schema_name: schema_name 'GSASII_Rietveld' does not name an engine: expected '<engine>.<workflow>', e.g. 'gsasii.rietveld'
```

**Cause:** the recipe is written for the unified schema 0.26.0 of PowderLine
0.1.1 (`GSASII_Rietveld` / `GSASII_SPF` with a `schema_version`), which 0.2.0
no longer reads; or `schema_name` is misspelled.

**Solution:** for a GSAS-II recipe run the converter and read its report:

```bash
python scripts/convert_recipe_026.py old_input.json -o input.json
```

For TOPAS or easydiffraction write a native recipe (there is no converter).
The [migration guide](migration-0.1-to-0.2.md) explains every change. A
mistyped engine name (`gsasii.reitveld`) is reported against that engine's
workflow names; an unknown engine prefix (`gsas2.rietveld`) raises
`GatewayNotInstalledError` listing the installed gateways.

---

## Missing Required Fields

**Error:**
```
❌ Recipe validation failed: input.json
Validation errors:
  • payload -> instrument -> geometry: Field required
  • payload -> phases -> LaB6 -> scale: Field required
```

**Cause:** a required block or field is absent. Nothing in a native recipe is
inferred: the frame (`schema_name`, `core_schema_version`,
`engine_schema_version`, `payload`), `xrd_data`, the whole `instrument` block
in the engine's layout, every phase's `space_group`, `unit_cell`, `atoms` and
`scale`, and `refinement_controls` are required; `fit_range`, `background` and
(gsasii) `peak_broadening` may be left out.

**Solution:** the [schemas page](schemas.md) lists the minimum inputs per
schema, the [fields page](fields.md) every field; copy the block from the
matching example (`examples/example_LaB6/input.json` for gsasii,
`examples/example_LaB6/topas/`, `examples/example_LaB6/easydiffraction/`).

---

## Unknown or `null` fields

**Error:**
```
  • payload -> instrument -> initialization: Extra inputs are not permitted
  • payload -> phases -> LaB6 -> peak_broadening: peak_broadening must not be null; leave it out instead
```

**Cause:** unknown keys are errors at every level of a native recipe (the
0.26.0 schema ignored them), and a block that may be left out is left out,
never written as `null`.

**Solution:** remove the key, or correct its spelling against the
[fields page](fields.md). Old 0.26.0 names (`initialization`,
`parameterization`, `schema_version`, `pv_gaussian_sigma`, `volume`,
`phase_name`) are the usual culprits; the converter renames them.

---

## Schema version errors

**Error:**
```
  • core_schema_version: Value error, core_schema_version '1.1.0' is not supported by PowderLine 0.2.0 (accepted: ==0.1.0; current: 0.1.0)
  • engine_schema_version: ... the 'gsasii' gateway of PowderLine 0.2.0 accepts engine schema ==0.1.0 (current: 0.1.0)
```

**Cause:** PowderLine **declares** the schema versions it accepts and does not
infer compatibility from version numbers; today every declaration is
`==0.1.0`.

**Solution:** write `"core_schema_version": "0.1.0"` and
`"engine_schema_version": "0.1.0"`. The [support matrix](support-matrix.md)
lists the declarations of every installed gateway.

---

## Parameter format errors

**Error:**
```
  • payload -> instrument -> broadening -> U: Value error, bounds are not supported for this parameter in this engine schema: expected [value, refine_flag], got a 4-element [value, refine_flag, min, max] list
  • payload -> phases -> LaB6 -> unit_cell -> a: Value error, expected [value, refine_flag, min, max] (min/max may be null), got a 2-element list
```

**Cause:** every refinable quantity is a list of the engine's one shape:
`[value, refine_flag]` in `gsasii.*` (no bounds), `[value, refine_flag, min,
max]` in `topas.*` and `easydiffraction.*` (`null` = no bound on that side).
A quoted number, a `null` value, or `1`/`"true"` as a flag are errors too.

```json
"U": [0.01, true]                 // gsasii
"U": [0.01, true, null, null]     // topas, easydiffraction
```

---

## Symmetry errors (space group, cell, special positions, flags)

**Error (spelling):**
```
  • payload -> phases -> LaB6 -> space_group: Value error, unrecognized space-group symbol 'Pm-3m'; write gemmi's canonical name 'P m -3 m'
```
Write gemmi's canonical extended Hermann–Mauguin name exactly, including the
setting (`"F d -3 m:2"`, `"R -3 m:H"`, `"C 1 2/m 1"`); the message gives it. A
bare two-origin or rhombohedral symbol lists both settings, a short
monoclinic symbol every setting of the group.

**Error (setting an engine cannot use):**
```
  • ... space_group: Value error, GSAS-II cannot use origin choice 1 ('F d -3 m:1'); state the structure in origin choice 2 (F d -3 m:2) (GSAS-II quirk EB-03)
  • ... space_group: Value error, the cryspy calculator does not compute the setting 'P 1 1 2/m' correctly ...: transform the structure to 'P 1 2/m 1', or use the crysfml calculator
```
Transform the structure to the suggested setting; the per-engine lists are on
the [engine behaviour page](engine-behavior.md#space-group-spellings-and-settings-per-engine).

**Error (cell):**
```
  • ... unit_cell: Value error, stated b = 4.2, but by symmetry b = a; write b = 4.15692
```
Every cell parameter is stated, and tied ones equal the first member exactly;
fixed angles are exactly 90 (or 120).

**Error (special position):**
```
  • ... atoms -> B: Value error, ... x = 0.4999999 ...; write x = 0.5
  • ... atoms -> O1: Value error, position (0.3333, 0.6667, 0.25) is 3.3e-05 from the special position (1/3, 2/3, 1/4) ... without being on it: state the special-position coordinates to at least 6 decimals, or move the atom at least 0.002 (fractional) off it
```
A constant with a decimal form is written exactly (`0.5`), a third to at
least 6 decimals (`0.333333`); an atom meant to sit off a special position
must be at least 2e-3 away. See
[input guidance](input-guidance.md#atoms) and the table in
[SCHEMA_HISTORY](SCHEMA_HISTORY.md#core-schema).

**Error (flags):**
```
  • ... unit_cell -> b: Value error, ... a, b, c are one parameter; set the same refine flag on all three
  • ... unit_cell -> c: Value error, GSAS-II refines a, c, beta together (it varies the reciprocal metric tensor), but only a is refined; refine all of a, c, beta or none
  • ... atoms -> La -> x: Value error, ... x is fixed by symmetry (= 0); set its refine flag to false
```
Tied members carry the same flag, a symmetry-fixed parameter is not refined,
and a `gsasii.*` recipe refines GSAS-II's oblique cell groups whole.

---

## Engine floors and limits

**Error (gsasii):**
```
  • payload -> instrument -> corrections -> axial_divergence: Value error, axial_divergence (SH/L) must be at least 0.002, got 0.0005: GSAS-II computes Bragg and Peak List profiles with SH/L >= 0.002 whatever is stated (GSAS-II quirk EB-37)
  • payload -> background -> single_peaks -> pv_lorentzian_gamma -> 0: pv_lorentzian_gamma[0] = 1e-05 is below 0.1, the smallest value GSAS-II computes with ...
```
GSAS-II would silently compute with the floor; state the floor value (or
reconsider the peak). The floors are listed on the
[engine behaviour page](engine-behavior.md#defaults-floors-and-silent-substitutions).

**Error (topas):**
```
  • ... atoms -> La -> Uiso: Value error, Uiso (TOPAS beq = 8 pi^2 Uiso, limits -10..20) is refined from 0.3, above TOPAS's default maximum 0.2533: TOPAS would move it to the limit without saying so; start at or below 0.2533, or state max to replace TOPAS's limit
```
A refined start outside a TOPAS default limit on a `null` side is refused;
state a bound to override TOPAS, or start inside.

**Error (easydiffraction):**
```
  • ... unit_cell -> a: Value error, a 35.0 is outside easydiffraction's physical limit [0, 30]: the engine refuses it (EB-71)
  • payload -> xrd_data -> Itth_weights -> 1203: weight 2e+09 (sigma 2.24e-05) is above 1e+08: easydiffraction would replace sigma < 1e-4 by 1.0 without saying so (EB-73); rescale the intensities and weights
  • payload -> instrument -> broadening -> parameters: Value error, the Lorentzian FWHM (X tan + Y / cos) is negative from 11.2 to 15 deg 2theta ...
```
easydiffraction's physical limits, weight ceiling, negative-intensity refusal
and negative-width behaviour are refused at validation; see the engine
behaviour page for each.

---

## Engine Not Available

**Error:**
```
❌ the 'gsasii' gateway needs GSAS-II, which is not installed in this environment; use the 'gsasii' pixi environment (install it with: pixi install -e gsasii; run with: pixi run -e gsasii ...)
```

**Cause:** the default environment is core-only. It validates every recipe but
runs no engine; `gsasii.*` recipes run in the `gsasii` environment,
`easydiffraction.*` recipes in the `easydiffraction` environment.

**Solution:**
```bash
pixi install -e gsasii
pixi run -e gsasii kicker input.json
# or, for easydiffraction:
pixi install -e easydiffraction
pixi run -e easydiffraction kicker input.json
```

**Related:** `ModuleNotFoundError: No module named 'GSASII'` from your own
script means the same thing: run it with `pixi run -e gsasii python ...`.

---

## Engine Version Errors

**Error:**
```
❌ the 'gsasii' gateway supports GSAS-II ==5.7.9, but 5.8.0 is installed; install a supported version
❌ the TOPAS version to run is not declared: PowderLine cannot read it from tc.exe, so set topas_version (run argument) or topas.version in .powderline_config.yaml; this recipe is written for TOPAS 6
```

**Cause:** engine versions are pinned and checked. GSAS-II and easydiffraction
come from the pixi lock, so a mismatch means the environment was modified by
hand; TOPAS cannot be pinned, so a `topas.*` run needs the installed version
**declared** (`--topas-version 6`, or `topas: {version: "6"}` in
`.powderline_config.yaml`), equal to the recipe's `engine_version`.

**Solution:** `pixi install -e gsasii` restores the pinned GSAS-II; for TOPAS
pass `--topas-dir` (the folder holding `tc.exe`) and `--topas-version 6`, or
set both in `.powderline_config.yaml`; PowderLine never searches for TOPAS.
`topas.*` 0.1.0 supports TOPAS 6 only.

---

## No gateway / stale install (`GatewayNotInstalledError`)

**Error:**
```
❌ no PowderLine gateway named 'gsasii': no 'powderline.gateways' entry points were found at all, although powderline is importable. The package's install metadata is stale or missing; re-install it (`pixi reinstall powderline`, or `pip install -e .`).
```

**Cause:** the gateways are discovered from entry points written at install
time. The editable install predates the entry-point table, is half-installed,
or PowderLine is imported from `src/` with no installed distribution
(KI-13). Each pixi environment carries its own install.

**Solution:**
```bash
pixi run -e gsasii doctor                  # or: powderline --doctor — what this environment can do
pixi reinstall powderline --all            # every environment
```
`powderline --doctor` prints the PowderLine version, the gateways the
registry finds, each engine's installed version against its gateway's
requirement, and the GSAS-II server's state; it exits non-zero when no gateway
is registered or an installed engine is outside its requirement, and names
the repair. An engine that is simply not installed is reported, not a
problem: the `default` environment runs nothing by design. If pixi cannot
rebuild the editable install (offline), use that environment's own python:
`python -m pip install --no-deps --no-build-isolation --no-index -e .`.

---

## Engine flag for the wrong engine

**Error:**
```
❌ --no-server applies to 'gsasii' recipes only; this recipe's schema_name names the 'topas' engine
```

**Cause:** the CLI's engine flags are checked against the recipe's engine:
`--use-server` / `--no-server` belong to `gsasii.*`, `--topas-dir` /
`--topas-version` to `topas.*`.

---

## Refinement Failed

**Error:**
```
❌ Refinement failed (unusable_site): GSAS-II cannot use these atom positions as stated: ... state the equivalent position (1/3, 0, 1/6) ...
❌ Refinement failed (diverged): GSAS-II's refinement diverged: the calculated pattern is not finite at 212 of 3767 points in the fit window, so no result is reported ...
❌ Refinement failed (diverged): GSAS-II aborted the refinement: no step lowered chi-squared before its damping reached its limit (a parameter the data cannot move, or a model far from the data) ...
   Files kept for diagnosis (the engine's own files and failure.json): .../dummy.gpx, .../dummy.lst, .../failure.json
❌ Could not run the engine (server_unavailable): Server not available and fallback disabled
ℹ️ Generated the engine input only (topas_generate_only, 0.0s): .../LaB6.inp, .../LaB6.xye
```

The word in parentheses is the **reason code** (`e.reason` in the API; the
table is in [schemas](schemas.md#outputs)). "Refinement failed" means the
engine ran and failed; "Could not run the engine" means it never ran
(server, configuration); "Generated" is not a failure at all (exit 0).

For a `gsasii.*` failure the CLI also prints **the engine's last console
lines**, and the failed envelope carries them as `failure.console_tail`
(`e.result["failure"]["console_tail"]` in the API; the last 64 KiB of what
GSAS-II printed, in-process or inside the server). That is where
GSAS-II says what it did not return: "Refinement failed - singular matrix",
"Removing parameter: …", the constraint notices. A verbose run that succeeded
keeps the same text under `engine_details["console_tail"]`.

**Causes and solutions:**
1. **A site GSAS-II misreads** (some 2-fold sites in R32, R-3m, R-3c, or a
   site it cannot name while a coordinate or `Uaniso` is refined): write the
   equivalent position the message names. GSAS-II would otherwise compute
   four times the intensity silently.
2. **Divergence** (a non-finite calculated pattern): a **failure** in every
   engine (0.1.1 returned success with Rwp 100 %). Reduce the refined set,
   start closer, check correlations in `dummy.lst` (gsasii).
3. **TOPAS not configured** (PowderLine never guesses where `tc.exe` is, P-35): the INP and `.xye` were written; run them on a
   machine with TOPAS 6, or pass `--topas-dir`. This is `status: "generated"`, not a failure.
4. **TOPAS wrote no output** (`output_missing`): TOPAS 6 reports nothing through its exit code,
   so a missing output file is the error. Whatever `tc.exe` printed is in
   `failure.json` (`failure.console_tail`); otherwise its messages are in its
   console window and `tc.log`. A file it did write but PowderLine cannot read strictly is `output_malformed`.
5. **The engine did not run** (`Could not run the engine (…)`): `server_unavailable` /
   `server_disabled` / `communication_failed` / `timeout` are the
   GSAS-II server's cases (see "Server Not Starting" below), and `timeout` is
   also a `tc.exe` run that outlived `--topas-timeout` / `topas.timeout`
   (default 3600 s: raise it for a long refinement, or look for a TOPAS dialog
   waiting for input); `timeout` deliberately does
   **not** fall back in-process, because the job is still running on the server and a
   second run would double the work

Then, as always: validate first, run with `--verbose`, and read the engine's
log (`dummy.lst` for gsasii; the TOPAS console; the printed lmfit report for
easydiffraction).

---

## Warnings after a run

A result (and the validate-only report) prints structured warnings; none of
them changes what the recipe says. The common ones:

- `gsasii_broadening_default_applied` — size or strain was left out, so
  10 µm / 0 microstrain, fixed, was applied (not GSAS-II's own 1 µm / 1000).
  State `peak_broadening` to silence it.
- `gsasii_refinement_message` — a message GSAS-II stored with the refinement
  (highly correlated parameters, a soft singularity, SVD). Usually normal;
  see "Parameter Correlation Warnings" below.
- `gsasii_fit_not_converged`, `easydiffraction_fit_not_converged` — the
  refinement stopped before the engine's convergence criterion; the values
  are reported. Add cycles / iterations or fix poorly determined parameters.
- `<engine>_parameters_not_varied` — the engine varied fewer parameters than
  the recipe requests (a silent drop); compare
  `engine_details.parameters_requested` with `parameters_varied`.
- `topas_parameter_at_limit`, `easydiffraction_parameter_at_limit` — a refined
  value ended at a bound or an engine limit.
- `easydiffraction_crysfml_start_dependent` — every CrysFML refinement
  (single precision): the stopping point depends on the starting values.
- `uaniso_not_positive_definite` — the stated anisotropic tensor has no
  thermal ellipsoid; used as stated.

The full list, with what each engine does, is on the
[engine behaviour page](engine-behavior.md#warnings-you-may-see).

---

## Rwp differs from what the engine prints

The `rwp` PowderLine reports is its **uniform** statistic: computed once, in
percent, over the data points inside the fit window with positive weight, with
the engine's own count of varied parameters. The engine's own value is under
`engine_details`. On a native run GSAS-II's `.lst` wR equals it; GSAS-II's
`GOF` is √(reduced χ²) in a Rietveld refinement but the reduced χ² itself in a
peak fit; a simulation against placeholder data gets a meaningless (large)
uniform Rwp where GSAS-II prints its 100 % cap. Across engines, compare
lattice parameters, and read Rwp as a property of the model (background peaks,
asymmetry model) rather than of the engine — see the
[cross-engine comparison](cross-engine-comparison.md).

---

## Output File Permission Error

**Error:**
```
PermissionError: [Errno 13] Permission denied: 'output/fit_profile.txt'
```

**Cause:** Cannot write to output directory.

**Solution:**
1. **Check directory permissions:**
   ```bash
   ls -ld examples/example_LaB6/output/
   chmod 755 examples/example_LaB6/output/
   ```
2. **Check disk space:** `df -h`
3. **Close files in other programs:** spreadsheets with CSV files open,
   editors with `.lst` files open.
4. **Choose another directory:** `--output DIR`.

---

## Parameter Correlation Warnings

**Warning in `dummy.lst` / `gsasii_refinement_message`:**
```
** Warning: parameters 0 and 1 are 99.8% correlated **
```

**Is this a problem?**
Not necessarily! High correlation is common and often acceptable.

**When it's okay:**
- Rwp is good (<15% typically)
- Parameters are physically reasonable
- Refinement converged
- Example: background coefficients are often highly correlated

**When to worry:**
- Correlation >99.9% (essentially identical effects)
- Parameters have unphysical values (negative sizes, unreasonable unit cell)
- The result warns `gsasii_fit_not_converged`
- Large parameter uncertainties

**Solutions if problematic:**
1. **Reduce background terms** (`num_coefficients`: try 3–4 instead of 6)
2. **Fix some parameters:** `"U": [0.01, false]`
3. **Expand the fit range** to include more data
4. **Refine sequentially:** background first, then scale, then instrument

---

## Slow Refinement Performance (gsasii)

**Problem:** Refinements taking 1+ seconds when they should be faster.

**Cause:** Using in-process mode instead of server mode.

**Solution:**

1. **Check which mode you're using:**
   - Look at the end of the output for "🚀 server mode" or "🐢 subprocess mode"

2. **Start the server for faster performance:**
   ```bash
   pixi run -e gsasii gsas-server start
   pixi run -e gsasii gsas-server status  # Verify it's running
   ```

3. **Force server mode explicitly:**
   ```bash
   pixi run -e gsasii kicker input.json --use-server
   ```

4. **Check server logs if it's not working** — `server.log` lives in your
   private per-user state directory (`pixi run -e gsasii gsas-server status`
   prints the path):
   ```bash
   pixi run -e gsasii gsas-server logs
   ```

5. **Check that the server isn't disabled** — if `POWDERLINE_NO_SERVER` is set
   (e.g. by a facility launcher), default (`auto`) runs are in-process by
   design, explicit server mode (`--use-server` / `execution_mode='server'`)
   fails, and `gsas-server start` refuses.

6. **Upgrading from v0.1.1 or a pre-merge 0.2.0 checkout?** Older servers used
   fixed, shared files in the temp directory and port 19471, and accepted
   unauthenticated requests. The current client never uses them, but
   `gsas-server status|stop` cannot see them either, so one may still be
   running (it may have been auto-started without you noticing). The old
   server ran as `gsas_server.py` (v0.1.1) or `gateways/gsasii/server.py`
   (0.2.0 before the v0.1.2 merge), so stop your current server first and
   then kill every remaining server process of yours once:
   ```bash
   pixi run -e gsasii gsas-server stop
   pkill -u "$USER" -f "gsas_server.py|gsasii[/.]server"     # Linux/macOS
   ```
   On Windows, end the `python ... gsas_server.py start` / `... server.py
   start` processes in Task Manager (or `Get-CimInstance Win32_Process |
   Where-Object CommandLine -match 'gsas_server.py|gsasii[/\\.]server' |
   ForEach-Object { Stop-Process -Id $_.ProcessId }`).

**Note on connection reliability:** The client automatically retries connections up to
3 times with exponential backoff (0.5s, 1s, 2s delays) to handle transient network issues.
If you see "Server communication failed" errors, check the server logs.

---

## Server Not Starting

**Error:**
```
❌ Server mode failed: Server not available and fallback disabled
```

**Cause:** Server process failed to start (a bad or busy `POWDERLINE_SERVER_PORT`
is named in the message), the server is disabled (`POWDERLINE_NO_SERVER`), or
your per-user state directory is unusable.

**How the server is found:** each user's server binds `127.0.0.1` on a free
(ephemeral) port and records its port, PID and a random secret token in a
private per-user state directory — `$XDG_RUNTIME_DIR/powderline` or
`<tempdir>/powderline-<uid>` on Linux/macOS, `%LOCALAPPDATA%\powderline` on
Windows. Clients read only their own user's directory, sign every request
with the token (the token itself is never sent), and only accept responses
signed with it — so another user's server, or another process that took over
the port of a crashed server, is never used. An endpoint whose server process
is gone is ignored.

**Solution:**

1. **Check if server is already running:**
   ```bash
   pixi run -e gsasii gsas-server status
   ```

2. **Stop any hung server processes:**
   ```bash
   pixi run -e gsasii gsas-server stop
   # Or manually kill your own server (started by the task or auto-started by a client):
   pkill -u "$USER" -f "gsasii[/.]server"
   ```

3. **"Refusing to use GSAS-II server state directory ..."** — the directory is
   a symlink, owned by another user, or readable/writable by others (e.g.
   pre-created in a shared `/tmp`). The server and auto-start are skipped:
   default runs fall back to in-process, explicit server mode fails. Remove the
   directory named in the message (if it is not yours, ask an administrator)
   and it is recreated privately on the next start. **"Refusing to keep the
   GSAS-II server state under ..."** means the parent (your `TMPDIR`) would let
   other users replace that directory — world-writable without the sticky bit,
   or owned by someone else; point `TMPDIR` (or `XDG_RUNTIME_DIR`) at a private
   directory.

4. **Pin a port only if you must** (e.g. a firewall rule): by default the
   server uses a free ephemeral port, so users never collide. To force one:
   ```bash
   export POWDERLINE_SERVER_PORT=19472
   pixi run -e gsasii gsas-server start
   pixi run -e gsasii kicker input.json  # the client finds the port automatically
   ```

5. **Start server in foreground to see errors:**
   ```bash
   pixi run -e gsasii python -m powderline.gateways.gsasii.server start
   ```

6. **Use in-process mode as workaround:**
   ```bash
   pixi run -e gsasii kicker input.json --no-server
   ```

---

## Server Reports Success but Output Files Are Missing (resolved in 0.2.0)

**Historical.** Through the first 0.2.0 development builds the GSAS-II server
wrote its output files into `output_dir` in *its own* filesystem view, so a
server on another node or inside a container reported success while the
files never appeared; a freshness check on `fit_profile.txt` caught it and
fell back in-process. Since 0.2.0 (KI-12) the files travel back inside the
signed response and the client writes them into its own `output_dir`, so the
server never needs to see the client's filesystem. If files are missing now,
the run itself failed (see "Refinement Failed") or the client could not write
`output_dir` (`backend_error` naming the directory in the message).

---

## Output Recipe Is Not Valid

**Problem:** the result (or the CLI) says `Output recipe: … (not valid as
written)` and carries the warning `output_recipe_not_valid`.

**Cause:** the engine returned a value the recipe schema refuses — an
occupancy outside [0, 1], a negative crystallite size or Uiso, a profile that
makes a width negative (easydiffraction, EB-87) — or a symmetry tie came back
inconsistent. The refinement result itself is unaffected; the output recipe is
still written (`output_recipe.json`) so you can see exactly what the engine
produced. `parameter_dispositions.csv` shows each value with its ESD.

**Solution:** read the warning (it lists each offending path with the
schema's message), decide whether the fit is physical, then fix the output
recipe by hand (or hold the parameter) before feeding it back.

---

## Server Is Stale (runs older code)

**Problem:** `WARNING: the GSAS-II server is stale`, a `--use-server` run that
fails with reason `server_unavailable` and a message naming the stale server,
or `gsas-server status` printing `Code: STALE`.

**Cause:** The persistent server imports PowderLine and GSAS-II once and keeps
them; after `git pull`, a checkout switch or an edit under `src/`, the running
server still executes the old code. Its `/health` reports the PowderLine
version and an MD5 of the source tree it loaded; the client compares both with
its own and refuses to use a mismatching server (`auto` mode falls back to
in-process execution; `server` mode fails honestly). A server started before
this check existed reports neither field and is treated as stale.

**Solution:**

```bash
pixi run -e gsasii gsas-server restart
```

---

## Environment Issues

**Problem:** Mixing conda environments or system Python, or running an engine
recipe in the wrong pixi environment.

**Solution:**
Always use pixi, in the environment that has the engine:
```bash
# DON'T mix approaches
conda activate some-env                       # DON'T
python src/powderline/kicker.py input.json    # DON'T

# DO use pixi exclusively, naming the environment
pixi run kicker input.json --validate-only    # DO (any env; no engine needed)
pixi run -e gsasii kicker input.json          # DO
pixi run test                                 # DO (resolves to the dev env)
pixi shell -e gsasii                          # DO (then run commands)
```

`pixi run gsas-server status` without `-e` is reported as ambiguous by pixi
(the task exists in `gsasii`, `all` and `dev`); pixi prints the
`--environment` form to use.

---

## Single Peak Fitting Issues

### Aphysical Peak Parameters (gsasii)

**Warning in `peak_convergence_diagnostics.txt`:**
```
Peak 5 at 2θ=45.234° - Status: negative_gamma_warning
  sigma_sq: 0.0234, gamma: -0.0012
  Warning: Negative/zero Lorentzian gamma detected
```

**What it means:**
GSAS-II refined a peak to have physically impossible parameters:
- **Negative σ²** (sigma squared / variance) - peak width cannot be negative
- **Negative γ** (Lorentzian gamma / HWHM) - peak width cannot be negative
- **Zero values** - infinitely sharp peak (unphysical)

**Common Causes:**
1. **Poor initial guesses:** position far from the true peak, intensity or
   widths unreasonable
2. **Peak overlap:** two peaks too close together; GSAS-II fits one peak
   trying to capture both
3. **Background interference:** peak on a steep background slope or
   inadequate background model
4. **Weak/noisy peaks:** low signal-to-noise

**When to Worry:**
- Multiple peaks flagged (systematic problem)
- Large negative values (< -0.01)
- Rwp poor despite aphysical parameters

**When it's Okay:**
- A single weak peak flagged
- Very small negative value (≈ -0.001) due to numerical noise
- Rwp good and other peaks converged normally

**Solutions:**

1. **Improve initial guesses** (`gsasii.spf`; widths are σ² in centidegree²
   and γ in centidegree, each at least 0.001):
   ```json
   "single_peaks": {
     "positions": [[21.5, true]],
     "intensities": [[150.0, true]],
     "pv_gaussian_sigma_sq": [[0.01, true]],
     "pv_lorentzian_gamma": [[0.05, true]]
   }
   ```

2. **Use the instrument profile for the widths:**
   ```json
   "refinement_controls": {
     "refinement_cycles": 5,
     "single_peak_fitting_mode": {
       "use_instrument_profile": true
     }
   }
   ```
   With `true` the widths come from U..Z (which may be refined) and the peaks'
   own σ²/γ flags must be `false`; with `false` the reverse. GSAS-II silently
   ignored the flag on the side not in use, so a flag there is now a
   validation error.

3. **Remove problematic peaks:** focus on well-separated, strong peaks first.

4. **Improve the background model:** more Chebyshev terms.

5. **Adjust refinement cycles:** more cycles for difficult peaks.

**Checking Results:**
- Open `single_peaks_report.txt` - check `converged` column (should be `true`)
- Open `peak_convergence_diagnostics.txt` - written only when a peak has issues
- Inspect `fit_profile.txt` visually - do peaks match observed data?

---

### Peak Fitting Convergence Failures

**Error:**
```
Peak 10 at 2θ=67.890° - Status: NaN_failed
  sigma_sq: nan, gamma: nan
```

**Cause:** Peak refinement did not converge, produced NaN.

**Common Causes:**
- Peak at the edge of the fitted region with poor constraint
- Numerical instability from extreme parameter values
- Insufficient data points around the peak

**Solutions:**
1. **Check the fit range covers the peak** — a peak outside the window is a
   validation error, but a peak within 1–2° of the boundary is often poorly
   constrained.
2. **Check data quality near the peak.**
3. **Adjust initial parameters** to the visible peak maximum.
4. **Increase refinement cycles.**

---

### Schema Selection Guidance

**Question:** Which schema should I use for my refinement?

1. **Do you have crystal structure information (space group, unit cell, atoms)?**
   - **No** → single peak fitting: `gsasii.spf` or `topas.spf`
   - **Yes** → Rietveld refinement: `gsasii.rietveld`, `topas.rietveld` or
     `easydiffraction.rietveld`
2. **Which engine?** The one you have and trust for the case: GSAS-II is the
   reference engine with committed outputs; TOPAS needs a Windows licence;
   easydiffraction is open source and chooses between two calculators. The
   [cross-engine comparison](cross-engine-comparison.md) shows the same data
   in all three.

| Schema | Purpose | Requirements | Output |
|---|---|---|---|
| `gsasii.rietveld`, `topas.rietveld`, `easydiffraction.rietveld` | Full structural refinement | structure block, XRD pattern, the engine's instrument | Refined unit cell, atomic positions, fit statistics, peak lists |
| `gsasii.spf`, `topas.spf` | Individual peak fitting | XRD pattern, peak positions, the engine's instrument | Peak positions, widths, intensities (no structure) |

**Important Notes:**
- **One refinement per recipe:** there are no sequential or iterative
  strategies and no multi-histogram recipes. If you need peak fitting followed
  by Rietveld refinement, run two PowderLine jobs.
- **One engine per recipe:** a recipe is written in its engine's terms; the
  structure block can be reused across engines, the instrument cannot.

---

## For contributors

The material in this section is for people working **on** PowderLine — modifying its
source, updating regression references, or running the development server — not for people
who are only running refinements. If you are just using PowderLine, everything you need is
in the sections above.

### PowderLine Module Import Error

**Error:**
```
ModuleNotFoundError: No module named 'powderline'
```

**Cause:** running python outside pixi, or in an environment where the
editable install is missing.

**Solution:**
1. **Use pixi run commands** (every task sets `PYTHONPATH` to `src/`):
   ```bash
   pixi run -e gsasii kicker input.json
   ```
2. **Or set PYTHONPATH manually:**
   ```bash
   export PYTHONPATH=$PWD/src:$PYTHONPATH     # Linux/macOS
   python -m powderline.kicker input.json
   ```
   Note that with `PYTHONPATH` alone and no installed distribution the gateway
   entry points are missing (`GatewayNotInstalledError`, KI-13):
   `pixi reinstall powderline` fixes it.

---

### Test Failures

**Error:**
```
FAILED tests/test_example_LaB6_regression.py::test_example_LaB6_regression
AssertionError: Final Rwp mismatch: expected 6.534%, got 6.538%
```

**Cause:** Refinement results changed from the committed reference.

**Solution:**
1. **Determine if change is expected:**
   - Did you modify refinement parameters, a default, or a frozen module?
   - Did GSAS-II (or numpy/scipy) change? Compare with the baseline run
     before assuming the failure is yours.
   - Is the difference beyond the tolerances of
     [regression-tolerance.md](regression-tolerance.md)?

2. **Check `dummy.lst` for details:**
   ```bash
   diff output/dummy.lst examples/example_LaB6/output/dummy.lst
   ```

3. **Update references only as a deliberate change** (see
   [policies](policies.md#deliberate-behaviour-changes)): record what changes
   and why, then regenerate:
   ```bash
   pixi run -e gsasii kicker examples/example_LaB6/input.json --no-server --output examples/example_LaB6/output
   git add examples/example_LaB6/output/
   git commit -m "examples: LaB6 reference regenerated after <reason>"
   ```

4. **If unexpected, investigate:** `pixi list -e gsasii | grep -i gsas`,
   look for code changes that might affect refinement, compare parameter
   values in the `.lst` files.

---

### Stale Server (Old Code Running)

**Problem:** Tests fail or code changes don't take effect, but code looks correct.

**Cause:** A long-running GSAS-II server started before your code changes still
has the old code loaded in memory. Python caches imported modules for
performance - the server doesn't automatically reload code when files change.

**Symptoms:**
- Tests pass right after a server restart (or a `--no-server` run works) but fail against a long-running server
- Code changes don't seem to have any effect
- Errors mention bugs you've already fixed

**Solution:**

1. **Restart or stop the server:**
   ```bash
   pixi run -e gsasii gsas-server restart   # or: stop
   # or kill every server:
   pkill -9 -f "powderline.gateways.gsasii.server"
   ```

2. **Verify no servers are running:**
   ```bash
   pixi run -e gsasii gsas-server status
   ```

3. **Run tests again:** `pixi run test`

**Best Practices:**
- **During development:** restart the server after code changes, or use `--no-server`
- **For integration tests:** restart (or stop) the server before running the test suite
- **Production use:** server caching is beneficial - just restart after deployments

---

### Code hash mismatch (`test_code_hash`)

**Error:**
```
FAILED tests/test_code_hash.py ... hash of gateways/gsasii/setters.py changed
```

**Cause:** one of the frozen GSAS-II modules
(`gateways/gsasii/{helpers,project,setters,executors,extractors,constraints}.py`)
changed. These modules move only through the signed-off edits ledger
([policies](policies.md#frozen-gsas-ii-code-and-the-edits-ledger)).

**Solution:** if the edit is a signed ledger row, `pixi run update-code-hash`
and commit `src/powderline/_code_hash.json` with it; otherwise revert the edit
and put the behaviour in a non-frozen module.

---

### Stale generated docs (`gen_schema_field_tables.py --check`)

The field tables and the support matrix under `docs/_generated/` are
generated from the schemas. `pixi run fields-check` compares them with the
code and prints one line on success:
```
fields-check: 7 files under docs/_generated match the schema declarations (core 0.1.0; easydiffraction 0.1.0, gsasii 0.1.0, topas 0.1.0)
```
A non-zero exit names the stale file. After changing a schema module or a
gateway's declarations:
```bash
PYTHONPATH=src python scripts/gen_schema_field_tables.py
pixi run docs
```

---

## Getting More Help

1. **Validate before running:** `pixi run kicker --validate-only input.json`
2. **Enable verbose output:** `pixi run -e gsasii kicker --verbose input.json`
3. **Check the engine's log:** `output/dummy.lst` (gsasii); the TOPAS console
   and `tc.log`; the lmfit report (easydiffraction)
4. **Compare with a working example:**
   `diff -u examples/example_LaB6/input.json my_example/input.json`
5. **Open an issue on GitHub** with:
   - Error message (full output)
   - Recipe JSON file
   - PowderLine commit: `git log --oneline -1`
   - Engine version: `pixi list -e gsasii | grep -i gsas` (or `pixi list -e easydiffraction | grep easydiffraction`; the TOPAS version you declared)
