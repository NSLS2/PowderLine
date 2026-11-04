# Known issues & documented failure routes

**Repo-wide register.** This page is a register of known, deliberately-deferred
behaviors and documented failure routes: behaviors we have *discovered and
understood* but are (for now) choosing not to prevent, plus quirks worth keeping
in mind. Each entry carries a stable `KI-NN` id — a permanent identifier
(e.g. `KI-01`) that is referenced from code, tests, and docs (e.g. "pass-through
per KI-01") so a behavior can be pointed to from a single canonical place.

**Scope.** Entries describe bugs, tripping hazards, codebase/convention
oddities, and in general issues that need dedicated development work
(refactoring, cleanup, new features) or a standing decision. **Small transient
issues do not belong here** — e.g. doc-sweep leftovers or other nits are fixed
directly rather than registered (keeps the register lean).

**Conventions:**
- IDs are permanent and never reused. Add new issues with the next free
  `KI-NN`; do not renumber existing ones.
- **Status vocabulary:** `accepted` = known, intentionally not prevented now;
  `planned-fix` = slated for a named branch; `watch` = quirk to keep in mind, no
  action yet; `implemented` = addressed by a shipped change (kept for history);
  `blocker` = must be resolved before the relevant branch can merge.
- **Severity vocabulary** (impact if encountered, orthogonal to status):
  `critical` = silent wrong/empty output or data loss; `major` = breaks a real
  flow or compounds technical debt; `minor` = works but fragile /
  incorrect-in-edge-cases; `nit` = cleanup. A `nit` is registered only when
  fixing it now is genuinely out of scope — otherwise fix it directly instead of
  filing it.
- Entry headings carry status and severity: `` `status · severity` ``.
- Each entry states: what, evidence (`file:line` where applicable), current
  decision, revisit trigger. Reference related issues by id.

**0.2.0 dispositions are confirmed.** The multi-engine refactor (PowderLine
0.2.0, native schemas 0.1.0) changed the ground under several entries. Each
affected entry below carries a *Disposition (0.2.0, confirmed 2026-10-16)*
paragraph that cites the decision which changed it; the heading status is
amended with the outcome. Dispositions are confirmed by the maintainers,
each one as written; no id is retired silently, and every
id stays listed. The user-facing account of what the
engines do is the [engine behaviour page](engine-behavior.md).

**Second pass, 2026-10-20.** Every entry re-read against the
0.2.0 tip: KI-04 gains its round-trip demonstration;
KI-05's open half gets a scoped plan; KI-11 moves from `watch` to
`accepted` (its residual needs the user to delete their own runtime
directory); KI-13 schedules the check command that would retire it; KI-10
names the one thing its Windows branch still lacks (a live run); KI-14
records what the in-band file transfer (KI-12) removed; KI-15 (example references that are unphysical
as posed) and KI-16 (TOPAS execution unverified for 0.2.0, a **blocker for
the upstream merge**) are registered. No id is closed by this pass.

---

## KI-01 — Malformed fixed cell computes a wrong pattern silently `accepted · critical` → resolved for native recipes (0.2.0)

**What.** A metrically symmetry-illegal cell (e.g. cubic phase with `a≠b≠c`) that
is *not* refined is used verbatim: GSAS-II computes peak positions from the raw,
non-symmetric reciprocal metric tensor and returns a "successful" refinement with
no error or warning.

**Evidence.** Verified against the pinned GSAS-II: a distorted cubic cell with
cell-refine off → d-spacings follow the distorted metric (Rwp 65.8%, reported as
a successful refinement).

**Decision.** Pass-through, do not prevent. Preventing symmetry-illegal
*cell values* is the future recipe builder's job. This behavior is also arguably
*useful* — e.g. deliberately simulating symmetry-breaking/strain effects with a
fixed distorted cell.

**Revisit.** When a recipe builder exists, or if a cell-vs-symmetry metric
validation option is added. If added, it should be *opt-in / warn* so the
legitimate symmetry-breaking-simulation use survives.

**Disposition (0.2.0, confirmed 2026-10-16: resolved).** Core schema 0.1.0 refuses a cell that does not fit the space group
(tied lengths and angles equal the first member, fixed angles exact, within
1e-9), in every engine schema, with a message giving the value to write. The
pass-through no longer exists for native recipes; the "deliberate
symmetry-breaking simulation" use would need the future `unsafe_mode`.
GSAS-II's own behaviour is recorded as EB-06.

---

## KI-02 — Oblique (monoclinic/triclinic) per-parameter cell holds are limited `implemented (schema 0.26, historical) · minor` → retired (0.2.0)

**What.** Holding a reciprocal-metric A-term equals holding a *direct* cell
parameter only for orthogonal cells. For monoclinic, only the unique-axis length
is independently holdable; `a`, `c`, and the oblique angle are coupled. For
triclinic, no direct parameter is individually holdable.

**Evidence.** Verified against the pinned GSAS-II: holding `A2` in a monoclinic
cell → `c` still moves (6.000→6.032).

**Decision (implemented in schema 0.26).** PowderLine models the cell as
Laue-class **DOF-groups** (coupled oblique parameters form a single group) and
applies **group-OR**: a group refines if any member is requested, and only
whole unrefined groups are held (`powderline/constraints.py`,
`cell_dof_groups`). PowderLine does **not** validate or reject mixed flags
within a group — it is the engine/translator; symmetry-consistent flags are
the upstream recipe builder's responsibility. Consequence for a *malformed*
recipe: a `false` flag inside a group with a `true` member is not honored
(deterministic, documented here). Not a GSAS-II limitation we can work around:
a direct-parameter hold on an oblique cell is a nonlinear constraint outside
GSAS-II's linear constraint system.

**Revisit.** Transparency (which groups refined together) arrives with the
provenance work. True independent oblique direct-parameter holds would
require a fundamentally different (nonlinear) constraint approach — unlikely to
change.

**Disposition (0.2.0, confirmed 2026-10-16: retired, a recorded deliberate change).** The group-OR no longer exists: a `gsasii.*` recipe
that refines a strict subset of a GSAS-II cell group (monoclinic `{a, c, β}`
for b-unique; all six for triclinic and rhombohedral axes) or of a symmetry
tie group is a **validation error** at the offending field, so a flag is never
silently overridden. The 0.26.0 converter writes v0.1.1's effective flags
explicitly and reports each change. The GSAS-II limitation itself (the
reciprocal-metric parameterization) is documented on the engine behaviour
page; `engine_details.parameters_requested` / `parameters_varied` give the
transparency this entry asked for.

---

## KI-03 — Site symmetry & multiplicity are derived, and failures are swallowed `planned-fix · major` → resolved (0.2.0)

**What.** PowderLine derives each atom's site symmetry and multiplicity at load
via `G2spc.SytSym`, inside a bare `except Exception: pass`, defaulting to `""`
and `1` on failure. The recipe never states these, and a derivation failure is
invisible.

**Evidence.** `kicker.py:1170-1176` at the time (the `SytSym` call now lives in `gateways/gsasii/project.py`).

**Decision.** Candidate for dedicated work: make site symmetry and multiplicity
explicit, validated recipe fields, with an immediate safety patch to stop
swallowing the exception. Improves resilience and decouples structural
interpretation from GSAS-II for future multi-engine support.

**Revisit.** At minimum, stop swallowing the exception when the surrounding area
is next touched.

**Disposition (0.2.0, confirmed 2026-10-16: resolved).** Core derives each atom's site symmetry, multiplicity and tie
groups with gemmi (engine-free), cross-checks a stated `Multiplicity`, and the gsasii gateway compares GSAS-II's reading of every site with
core's after phase setup, stopping with a clear error that names an
equivalent position when GSAS-II misreads or cannot name the site (EB-40,
EB-05). Nothing is swallowed; the recipe does not state site symmetry
(it is derived and checked, not an input).

---

## KI-04 — Recipe→output provenance is implicit; no round-trip `planned-fix · major` → resolved (0.2.0)

**What.** Outputs are CSV/txt keyed by GSAS-II parameter names. Which parameters
were *actually* varied vs held-by-user vs held-by-symmetry vs frozen-by-limit is
implicit (inferred from absence in `varyList`). No recipe-shaped output exists, so
sequential/multi-step refinement needs external output→input mapping.

**Evidence.** GSAS-II outputs are keyed by parameter name only; per-parameter
disposition is inferred from absence in `varyList`, with no recipe-shaped output.

**Decision.** Add explicit per-parameter disposition and a JSON recipe-style
output enabling round-trip / sequential refinement. Deferred to dedicated work.

**Revisit.** When designing sequential-refinement support, or when a downstream
data-management consumer needs machine-readable provenance.

**Disposition (0.2.0, confirmed 2026-10-16: open, partly addressed).** Results now report `engine_details.parameters_requested` (from the
recipe) against `parameters_varied` (what the engine varied) and a structured
`warnings` list (parameters not varied, limits hit, convergence).
**Update (0.2.0):** every result carries `output_recipe` (the resolved
recipe with the refined values written back; validates unchanged) and
`parameter_dispositions` (`varied` / `held_by_user` / `held_by_symmetry` /
`requested_not_varied` / `default_applied`, with ESDs and `at_limit`); topas and
easydiffraction fill them from their own path bookkeeping, GSAS-II from a
name-to-path map over its refined-parameter rows, unit-cell reports and, for a
peak fit (which fills no covariance block), the fit's own parameter block
`peak_fit` read from the project — the background, the instrument profile with
`use_instrument_profile`, the peaks, with ESDs (`gateways/gsasii/paths.py`;
`fit_report.peak_fit_parameters`). **Resolved.** Note what it
exposed: the committed DRX_33 atom-refinement and anisotropic references hold
occupancies below zero and negative crystallite sizes, and the LaB6 single-peak
fitting reference's background peak refines its σ² far below GSAS-II's silent
floor (EB-35); their output recipes are honestly `output_recipe_valid: false`
(each example's DESCRIPTION says so; KI-15). The round trip is demonstrated
end to end by `examples/example_LaB6_temperature_series/`: six
simulated LaB6 patterns refined in sequence by swapping only the `xrd_data`
block into each step's output recipe, with GSAS-II and with easydiffraction,
recovering the programmed thermal expansion.

---

## KI-05 — GSAS-II refinement failures & constraint warnings don't raise `planned-fix · major` → resolved for refinement failures (0.2.0); console text implemented (0.2.0)

**What.** `proj.refine()` does not raise on refinement failure (singular matrix,
etc.); constraint cascades/conflicts and frozen-variable notices go to stdout /
`Rvals['msg']` only. PowderLine currently inspects none of these, inferring
success solely from `hist.residuals['wR']` being non-None.

**Evidence.** Verified against GSAS-II internals: `proj.refine()` does not raise
on failure, and constraint/frozen-variable notices go to stdout / `Rvals['msg']`
only, which PowderLine does not currently inspect.

**Decision.** Surface diagnostics via `proj.data` structures + captured console
text, *without* adopting `do_refinements`. Minimal failure-detection may land
early; fuller provenance later.

**Revisit.** Bundle with the provenance work.

**Disposition (0.2.0, confirmed 2026-10-16: resolved for refinement failures).** The native gsasii path reads GSAS-II's stored refinement
messages into `gsasii_refinement_message` warnings (EB-32), reads its
convergence flag into the result's top-level `converged` with
`gsasii_fit_not_converged`, treats a non-finite calculated pattern as a
**failure** (v0.1.1 returned success with Rwp 100 %), and reports a
clear `EngineExecutionError` where GSAS-II's peak fit failed with a bare
`TypeError` (EB-38). Since 0.2.0 these failures **raise through
`powderline.run()`** (a recorded edit to the frozen executor re-raises
`EngineExecutionError` instead of returning `success: False`), with reasons
`diverged`, `unusable_site`, `peak_fit_failed`, `engine_crashed`. Captured
console text is still not collected; keep the id open for that.

**Second pass (2026-10-20): the open half, `planned-fix · minor`, scoped
down.** Most of what GSAS-II prints is already carried in a better form: a
peak fit that ends on a singular matrix reports its ESDs as undetermined
(EB-92), a parameter GSAS-II dropped as singular appears as
`requested_not_varied` in `parameter_dispositions` by recipe path (KI-04),
`Rvals['msg']` is a structured warning (EB-32) and divergence raises.
What is console-only after that is small — the constraint-generation notices
and the explanatory text around failures that already raise — so no phrase
list and no new warning code. The plan: the non-frozen gateway captures
`sys.stdout` for the duration of the engine run (a stream that writes to
both the real stdout and a bounded buffer, in-process and per job in the
server) and carries the buffer's tail in the **failure envelope** (where a
user is debugging) and, in verbose runs, under `engine_details`. Two facts
that shape it: in the auto-started server the process's stdout is
`DEVNULL` (`client.py`), so today the console text is discarded, not merely
uncollected, and the per-job buffer would be its only record; and
`redirect_stdout` is process-global, safe per job only because the server
runs one job at a time. GSAS-II prints through Python's `print`
(`GSASIIfiles.G2Print`), so a Python-level capture sees it; output from
compiled code on file descriptor 1 is not captured and is not claimed.

**Implemented (0.2.0)** as planned: `gateways/gsasii/console.py` tees
`sys.stdout` for the engine run (the in-process path in `gateway.py`, the
job in `server.py`) into a bounded tail (64 KiB); a failed envelope carries
it as `failure.console_tail`, a verbose run that succeeded under
`engine_details["console_tail"]`, and the CLI prints the last lines after
"Refinement failed". Under the auto-started daemon (stdout discarded) the
tail is the only record of that text; the client's in-process fallback and
`--no-server` capture it too. Nothing is parsed; no warning code was added.
Since 0.2.0 the failed envelope, tail included, is also on disk as
`failure.json` in the output directory. **Resolved**; the id stays listed.

**Revisit.** Closed; kept for history.

---

## KI-06 — GSAS-II parameter-limit (min/max) semantics are clamp-and-freeze `watch · minor` → not exposed (0.2.0)

**What.** GSAS-II enforces `parmMin/parmMaxDict` not as in-loop box constraints
but by resetting out-of-range variables to the limit *after* a refine and
freezing them from the next one. Frozen state persists in the `.gpx`. Coordinate
limits must target `Ax/Ay/Az` even though the varied variable is `dAx/dAy/dAz`.

**Evidence.** Verified against GSAS-II internals (`parmMin`/`parmMaxDict`
clamp-and-freeze semantics; coordinate limits target `Ax/Ay/Az` while the varied
variable is `dAx/dAy/dAz`).

**Decision.** min/max deferred to the general constraints & limits work. When
implemented, document the semantics honestly and surface frozen variables; do
not imply hard bounds.

**Revisit.** With the general constraints & limits work.

**Disposition (0.2.0, confirmed 2026-10-16: not exposed).** A spike during the refactor confirmed the clamp-and-freeze semantics in detail
(EB-30: the reported values, ESDs and Rwp belong to the unclamped fit; EB-31:
direct-cell boxes map onto A-term limits exactly for four of seven crystal
systems). gsasii 0.1.0 therefore exposes **no bounds**: a 4-element parameter
list is a validation error, and the converter reports every bound it drops.
Bounds may come in a later gsasii schema version with a clamp-freeze-refit
scheme. `topas.*` and `easydiffraction.*` have bounds with their own,
documented semantics.

---

## KI-07 — Space-group setting (hexagonal vs rhombohedral, origin choice) is unvalidated `watch · critical` → resolved (0.2.0)

**What.** `R -3 c` (hexagonal axes) and `R -3 c R` (rhombohedral axes) are both
accepted but imply different cell parameterizations and A-term equivalence sets.
Two-origin space groups default to origin 2; a recipe with origin-1 coordinates
under such a symbol is silently wrong (no CIF symops exist to trigger GSAS-II's
auto-shift, since PowderLine is file-less).

**Evidence.** Verified against GSAS-II internals: two-origin space groups default
to origin 2, and the CIF-only auto-shift never fires because PowderLine is
file-less (no CIF symops).

**Decision.** Candidate for the convention-validation work: at minimum echo the
inferred Laue class / setting back to the user. Origin-1 detection is hard
without symmetry operators and better handled in the recipe builder.

**Revisit.** Convention-validation branch, or recipe-builder work.

**Disposition (0.2.0, confirmed 2026-10-16: resolved, EB-03).** Core requires gemmi's canonical extended Hermann–Mauguin name,
which states the setting (`:1`/`:2`, `:H`/`:R`, the monoclinic axis); any
other spelling is an error naming the canonical form, and a bare two-origin
or rhombohedral symbol lists both choices. The gsasii gateway **refuses origin
choice 1** (GSAS-II silently reads it as origin 2) and 9 further settings; the
converter stops on a 0.26.0 recipe with `:1`. No setting is inferred any more.

---

## KI-08 — Sphinx build emits reST warnings from the unified schema's `RecipeModel` docstring `fixed · nit` (historical)

**What.** A clean `pixi run docs` (which runs `sphinx-build -W --keep-going`,
so this *did* already fail the build) printed **266 warnings**
(re-measured 2026-08-27), all pre-existing or cosmetic:
- ~230 autodoc cross-reference warnings (`py:class`/`py:obj` reference target
  not found) for pydantic internals — `PlainSerializer`, `ConfigDict`, and
  the fully-expanded `Annotated[..., PlainSerializer(lambda ...)]` field
  types in `schema.py` that autodoc can't resolve (the renderer additionally
  mis-splits the `PlainSerializer(func=..., return_type=..., when_used=...)`
  repr into several bogus sub-references);
- ~15 docutils WARNING/ERROR lines from the `RecipeModel` docstring, whose
  embedded markdown-style ```json migration examples don't parse as reST
  (unexpected indentation, inline-literal start without end);
- ~19 myst warnings (header-level jumps in `known_issues.md`, and slug-style
  anchor cross-refs in `cross-platform-guide.md`'s table of contents);
- ~12 Pygments highlighting-failure warnings from ```json fences in
  `DEVELOPMENT.md`/`TROUBLESHOOTING.md` containing `//`/`#` comments and
  `...` ellipses (illustrative, not strictly valid JSON);
- one stray `pandas.core.frame.DataFrame` cross-reference (pandas' own
  intersphinx inventory only indexes the public `pandas.DataFrame` path);
- one `html_static_path entry '_static' does not exist` warning.

**Evidence.** Reproduced by `pixi run docs-clean && pixi run docs`.

**Decision.** Fixed. Most of the ~230 pydantic-internals warnings were traced
to a real, fixable root cause rather than papered over:
- `RefinementParameter = Annotated[tuple[...], PlainSerializer(lambda ...)]`
  fields were expanding to their full runtime type in generated docs because
  `schema.py` lacked `from __future__ import annotations` (PEP 563); without
  it, autodoc evaluates each field's annotation back to the real
  `Annotated[..., PlainSerializer(...)]` object instead of keeping the
  written `RefinementParameter` name. Adding the import keeps annotations
  as their literal source text, so every field now renders (and links) as
  the clean `RefinementParameter` alias.
- `autodoc_typehints` was set to `'description'`, which routes type info
  through `sphinx.ext.autodoc.typehints.record_typehints` — a path that
  re-stringifies each annotation independently of `autodoc_type_aliases` and
  hands the result to the Python domain's `make_xrefs` helper to turn into
  cross-references. This is a known, kindly-acknowledged rough edge in
  Sphinx itself, not a pydantic quirk:
  [sphinx-doc/sphinx#9641](https://github.com/sphinx-doc/sphinx/issues/9641)
  ("`make_xrefs` should be consistent with `_parse_annotation`"). A Sphinx
  maintainer confirmed the inconsistency in the thread, and explained the
  tradeoff behind it: `make_xrefs` still has to support old-style, pre-typing
  narrative `:type:` text (e.g. `"int or float"`), which isn't valid Python
  and can't go through the same `ast.parse()`-based path (`_parse_annotation`,
  used for real signatures) that degrades gracefully instead of splitting
  unexpected input apart. That legacy-compatibility split is exactly what
  trips up comma-bearing `Annotated` metadata like
  `PlainSerializer(func=, return_type=, when_used=)`, turning it into several
  unresolvable sub-references. It's an open, unscheduled enhancement rather
  than a regression, so we've worked around it locally: switching to
  Sphinx's own default, `'signature'`, sidesteps `make_xrefs` for our case by
  rendering types inline in the signature via `_parse_annotation` instead.
- A `missing-reference` hook in `docs/conf.py` retries unresolved `py:class`
  references as `py:obj` only for the explicit
  `RefinementParameter`/`powderline.schema.RefinementParameter` alias targets.
  Type-hint rendering emits a `class`-role xref for the alias, but the alias is
  documented as `py:data`, which the `class` role's objtype search cannot
  match. Retrying only this known alias set as `obj` makes each
  `RefinementParameter` field a real hyperlink while preserving nitpicky
  warnings for genuine missing or wrong-role class references.
- `model_config` (identical `ConfigDict(...)` boilerplate on every model)
  is now excluded from `autodoc_default_options`, removing ~24 warnings for
  an attribute that isn't part of the public schema anyway.
- also: added `docs/_static/.gitkeep` (and un-ignored `docs/_static/` in
  `.gitignore`) so the configured `html_static_path` exists; reworded the
  `RecipeModel` docstring to use a proper `.. code-block:: javascript`
  directive and double-backtick literals instead of markdown
  fences/single-backticks; relabeled the illustrative, comment-bearing
  ```json fences as ```javascript (tolerant of `//` comments and `...`) in
  `DEVELOPMENT.md`/`TROUBLESHOOTING.md`; fixed a handful of `kicker.py`
  docstrings whose `Returns:` sections (e.g. `is_template_file`,
  `extract_refined_params_from_project`, `calculate_cell_esds_from_A_matrix`,
  `_extract_fit_profile`) were misparsed by Napoleon as bogus `name (type):`
  pairs; fixed the `pydandtic` intersphinx key typo; set
  `myst_heading_anchors = 4` so `cross-platform-guide.md`'s TOC anchors
  resolve; and promoted `known_issues.md`'s `### KI-NN` headers to `##` (the
  file had no other H2, so H1→H3 was a level skip).

What's left is a 4-entry `nitpick_ignore` for targets that genuinely aren't
documented anywhere Sphinx can link to: `pandas.core.frame.DataFrame`
(pandas' intersphinx inventory only indexes the public `pandas.DataFrame`
path), `annotated_types.Gt`/`Ge` (the package publishes no Sphinx inventory),
and the literal `lambda` fragment inside `RefinementParameter`'s
auto-generated "alias of ..." line (which, accurately, spells out its real
`PlainSerializer(func=<lambda>, ...)` metadata).

**Revisit.** Closed; kept for history. The `schema.py` / `RecipeModel` named
above belonged to the unified 0.26.0 schema, removed in 0.2.0; the
`missing-reference` hook went with it. The docs build still runs
`sphinx-build -W` with `nitpicky = True` (`pixi run docs`).

---

## KI-09 — Withdrawn

Filed during the PR #23 review; withdrawn 2026-07-16 (the reported behavior
was intentional, not a defect). Id retained so it is never reused.

---

## KI-10 — `stop_server()` force-kill escalation raises on Windows and is untested `implemented · minor`

**What.** `stop_server()` escalates to `os.kill(pid, signal.SIGKILL)` when the
server has not exited 5 s after SIGTERM. `signal.SIGKILL` does not exist on
Windows, so the escalation branch raises `AttributeError` there instead of
force-killing. The branch is rarely reached on Windows (Python maps
`os.kill(pid, SIGTERM)` to `TerminateProcess`, a hard kill, so the graceful
loop usually succeeds), and no test on any platform drives the timeout path —
the unit tests cover only the graceful sequence
(`tests/test_gsas_server_unit.py`, `alive_states = iter([True, False])`).

**Evidence.** `src/powderline/gsas_server.py:371` at the time (now
`src/powderline/gateways/gsasii/server.py`); `tests/test_gsas_server_unit.py:157`.

**Decision.** Fixed: the escalation now uses
`getattr(signal, "SIGKILL", signal.SIGTERM)` — on Windows,
`os.kill(pid, SIGTERM)` maps to `TerminateProcess`, the correct hard kill — and
unit tests drive the escalation path (`tests/test_gsas_server_unit.py`).

**Second pass (2026-10-20).** The unit tests mock the process; the Windows
escalation branch has never run live. It belongs in the maintainers' Windows
matrix (`gsas-server start`, then `stop` against a server made unresponsive),
not here.

**Revisit.** Closed; kept for history.

---

## KI-11 — Server discovery is split between PID file and port probe; an orphaned server is unmanageable `watch · minor` → accepted (2026-10-20)

**What.** `gsas-server status|stop` trust the PID file
(`<tempdir>/powderline_gsas_server.pid`), while `GSASClient` trusts an HTTP
`/health` probe on the port-file/default port (19471). If the PID file is lost
(crash, tempdir cleanup, or the starting process group being killed) the server
keeps serving: clients silently use it while `status` reports "not running" and
`stop` cannot stop it (there is no HTTP shutdown endpoint). A related latent
bug in the auto-start path — the child env joined `PYTHONPATH` with a
hardcoded `':'` instead of `os.pathsep` (wrong separator on Windows; benign in
the pixi env, where powderline is pip-installed) — has since been fixed; the
discovery/lifecycle mismatch below remains open.

**Evidence.** Reproduced live: `/health` on 19471 answered
(`uptime_seconds≈13261`) with no
`.pid`/`.port` files present and `status` reporting "not running".
`src/powderline/gsas_server.py:332-347` (`is_server_running` = PID file),
`src/powderline/gsas_client.py:40-49` (`is_server_available` = port probe),
`gsas_client.py:180` (the former hardcoded `':'`, now `os.pathsep`). Since
0.2.0 the two modules are `src/powderline/gateways/gsasii/server.py` and
`client.py`.

**Decision.** File for a server-lifecycle robustness pass: align `status`/
`stop` with the client's probe (e.g. `status` also checks `/health`; add an
HTTP shutdown endpoint, or have `stop` fall back to the PID reported by
`/health`).

**Update (v0.1.2, KI-14).** The split discovery is resolved. Server state
moved to a per-user directory (`server.lock`, `server.pid`, `server.json` =
port + token; ephemeral port), and `status`/`stop` and clients now agree:
"running" means holding the kernel lock on `server.lock` (released by the OS
on exit, so a leftover PID file or a recycled PID no longer fools `status` or
`stop`), and clients use only the endpoint in `server.json`, verified by
signed responses. **Residual (why this stays open):** if the state directory
itself is deleted while a server runs (e.g. `$XDG_RUNTIME_DIR` removed at
logout, or a tempdir cleaner), that server keeps running unused — clients can
no longer find or authenticate to it — but `status`/`stop` cannot see it
either; it must be killed by hand (`pkill -u "$USER" -f "gsasii[/.]server"`).

**Revisit.** Next branch touching `gateways/gsasii/server.py` / `client.py`.

**Second pass (2026-10-20): `accepted`.** Two 0.2.0 changes (KI-12 among
them) touched `server.py` without changing the picture: the residual needs the
user's own runtime directory to be deleted under a running server, and the
recovery is one documented command. A fallback was considered and declined:
`status`/`stop` could look for a process whose command line is the server
module when the state directory is missing (what the manual recovery does by
hand), but that identifies a process, not *our* server (no lock, no token to
verify), so it would be a guess dressed as a status. The KI-12 fix added the job scratch directories under the same
state directory (`job-*`, swept at the next server start), so a deleted state
directory also loses a running job's files — the same failure, same
recovery. Accepted as a documented failure route; the id stays listed.

**Revisit.** If the HTTP transport is replaced by a Unix-domain-socket /
named-pipe transport (KI-14's revisit), which would give OS-level discovery.

---

## KI-12 — Server mode assumes a shared filesystem; output files should travel in-band `planned-fix · major` → resolved (0.2.0)

**What.** The GSAS-II server writes output files into `output_dir` in **its
own** filesystem view and returns only result *data* over HTTP. A server
without a shared view (another cluster node; a sandbox/container with a
private `/tmp`) therefore cannot deliver the file outputs at all. The client's
output-visibility guard (stat-compare of `fit_profile.txt` before/after the
run) detects the mismatch and falls back to in-process execution — a
mitigation, not a fix, and it keeps a (cheap) filesystem check in the client.

**Evidence.** `gateways/gsasii/server.py` security notes (server resolves
`output_dir` in its own view); `gateways/gsasii/client.py`
`_server_output_visible` / `_submit_to_server_guarded`;
`tests/test_gsas_client_visibility.py`.
The (since removed) `.chi` export consumed the in-band `fit_profile` dict,
showing the in-band path works.

**Decision.** Planned fix in a future server-protocol branch: the server runs
in a server-local scratch directory and returns **all output artifacts
in-band** (gpx/lst as base64/text, CSVs as text) and the client materializes
the files locally. This dissolves the divergent-view failure instead of
detecting it, deletes the guard, and makes cross-node servers (HPC: client on
a login/worker node, GSAS-II server elsewhere, no shared filesystem) a
supported topology. Needs protocol versioning for already-running servers.

**Update (0.2.0).** The server's response is now a versioned envelope
(`envelope_version: "1"`, `status`, `converged`, `failure`; HTTP 200 for every
application outcome), so the protocol versioning this entry asks for exists;
the shared-filesystem assumption itself is unchanged.

**Revisit.** Next branch touching the server protocol, or when the HPC
deployment work starts.

**Disposition (0.2.0, confirmed 2026-10-19: resolved).** The
server runs each job in a private scratch directory under its per-user state
dir and returns every PowderLine output file base64-encoded inside the signed
response (`files`); the client writes them into its own `output_dir`
(bare names only, size-capped, atomic replace) and lists them in
`output_files`. The request no longer carries `output_dir`; the freshness
check, its fallback and the reason code `output_not_visible` are gone. A
server on another node or in a container now works like a local one.

---

## KI-13 — Engine dispatch depends on install-time entry-point metadata `watch · minor` → implemented (0.2.0: `powderline --doctor`)

**What.** Since 0.2.0, `powderline.run()` and `powderline.validate()` resolve
the engine a recipe's `schema_name` names through the gateway registry,
including the three in-repo gateways. The registry reads the
`powderline.gateways` entry points from the installed distribution's
metadata. If a checkout's editable install predates
the `[project.entry-points]` table, is half-installed, or powderline is
imported from source (`PYTHONPATH=src`) with no dist-info at all, then every
`run()` call fails with `GatewayNotInstalledError`. Before 0.2.0 the
dispatcher imported the backends directly and did not depend on install
metadata. The error message is clear and names the fix. However, each existing
dev environment has to be re-installed once (`pixi reinstall powderline`).
During the 0.2.0 work a developer's `easydiff` env was left half-installed with no
error shown, and it failed this way.

**Install health.** Every pixi environment carries its own editable
install, so the entry-point metadata is per env: after editing
`[project.entry-points]` or `[project.scripts]`, run `pixi reinstall
powderline -e <env>` for each env you use (or `pixi reinstall --all`). If pixi
cannot rebuild the editable install (offline, or the `hatchling.build` failure
seen during the 0.2.0 work), restore it with that env's own python:
`pip install --no-deps --no-build-isolation --no-index -e .`. Check with
`pixi run -e <env> python -c "from powderline import registry; print(registry.available())"`
— an empty list means the metadata is missing.

**Evidence.** `src/powderline/api.py` (`gateway_for` → `registry.get(...)`
for every engine); `src/powderline/registry.py` `get` /
`_not_installed_message`; `AGENTS.md` (the `pixi reinstall powderline` note).

**Decision.** Keep entry points as the **only** discovery path: the
in-repo gateways use exactly the plugin mechanism a third-party engine will
use, and a hard-coded fallback would add a second discovery path and hide a
stale install. The registry's error already names the fix. 0.2.0 added the
install-health guidance above; the re-install step is documented for users in
the [migration guide](migration-0.1-to-0.2.md) and for contributors on the
[policies page](policies.md) and in `AGENTS.md`.

**Disposition (0.2.0, confirmed 2026-10-16: stays `watch`).**

**Second pass (2026-10-20): still `watch`, with the refactor's own evidence.**
The failure mode is real and recurs: during the 0.2.0 work the `default` and
`gsasii` environments each lost their editable install once (2026-10-16 and
2026-10-19, after unrelated `pixi` operations; `registry.available()` returned
`[]`), repaired with that env's own python,
`python -m pip install --no-deps --no-build-isolation --no-index -e .`. A
fresh checkout installs with `pixi install --frozen -e <env>` (a plain install
re-locks on the pixi-build GSAS-II hash and re-installs; see the
[cross-platform guide](cross-platform-guide.md)). The entry-point decision
stands; the one thing that would retire this id is the check command, and
after two losses in two weeks it is scheduled rather than wished for: a
`powderline doctor` (or `--doctor`) that prints the registry's gateways, each
installed engine's version against its pin, the server state directory and
the Python environment, exiting non-zero when a gateway is missing. Half a
day; a branch of its own.

**Implemented (0.2.0).** `powderline --doctor` (`pixi run doctor`;
`src/powderline/doctor.py`) prints the PowderLine version, the gateways the
registry finds with their workflows and engine requirements, each engine's
installed version against its requirement, and the GSAS-II server's state
directory and status; it exits non-zero for a missing registry or an engine
outside its requirement, naming the repair. The entry-point decision is
unchanged; the stale install is now a one-command diagnosis.

**Revisit.** If a second discovery path is ever considered.

---

## KI-14 — GSAS-II server was shared across users on multi-user hosts `implemented · critical`

*(Registered on `main` as KI-13 in v0.1.2; renumbered here because KI-13 was
already taken on the 0.2.0 branch. IDs are permanent from this merge on.)*

**What.** Through v0.1.1 the server kept machine-global state
(`<tempdir>/powderline_gsas_server.{port,pid,log}`), listened on a fixed port
(19471) and had no authentication. On a shared workstation: user B's client
found user A's server and ran B's job as A (files owned by A, possibly written
where B could not write); any local user could POST a job with an
`output_dir` inside another user's directories and have it written with that
user's identity; users collided on the port and the shared files; and there
was no global way to keep `powderline.run()` from auto-starting a server.

**Evidence.** `gsas_server.py` (v0.1.1) `PORT_FILE`/`PID_FILE`/`LOG_FILE`,
`DEFAULT_PORT = 19471`, unauthenticated `/simulate`; `gsas_client.py` probed
`/health` on that port and submitted to whatever answered.

**Decision.** Fixed in v0.1.2 (#10); carried into 0.2.0 at the merge of
`main` into the candidate on 2026-10-14, where the two modules are
`src/powderline/gateways/gsasii/server.py` and `client.py`:

- *Per-user state.* Lock, PID, log and endpoint (port + token), all mode
  0600, live in `$XDG_RUNTIME_DIR/powderline` (only if that is a real
  directory owned by the user) or `<tempdir>/powderline-<uid>` (POSIX: 0700;
  refused if a symlink, foreign-owned or group/other-accessible, or if the
  temp directory would let other users replace it; files opened via a
  re-verified `O_NOFOLLOW` directory handle), or `%LOCALAPPDATA%\powderline`
  (Windows, protected by the profile ACL).
- *Authentication both ways, token never on the wire.* The server binds
  `127.0.0.1` on an ephemeral port. Every request must carry a fresh nonce, a
  timestamp and an HMAC-SHA256 (keyed by a per-start `secrets.token_urlsafe(32)`
  token) over method, path, nonce, timestamp and body; unsigned, wrongly
  signed, stale or replayed requests get 401 on every route before the body is
  read. Every response is signed over the nonce, status and body, and the
  client discards unsigned ones — so a process that takes over the port of a
  crashed server learns nothing reusable and cannot fake a result. Clients
  also ignore an endpoint whose server process is gone.
- *Single instance.* A kernel-held lock (`flock` / `msvcrt.locking`) on
  `server.lock` for the server's lifetime replaces the PID-file lock, which a
  stale PID file let several concurrent starters win.
- *Off switch.* `POWDERLINE_NO_SERVER=1|true|yes|on` disables the server:
  `auto` runs in-process without starting or contacting one, `server` mode /
  `--use-server` error (the CLI refuses before any engine is touched),
  `gsas-server start|restart` refuse.
- *Upgrade.* A v0.1.1 server still running after the upgrade is never used,
  but is invisible to `gsas-server status|stop`; stop it by hand (see
  TROUBLESHOOTING).
- *Since 0.2.0 (KI-12).* The request carries no `output_dir` at all: the
  server writes into its own private scratch directory and the files travel
  back inside the signed response, so the "write into another user's
  directory" surface no longer exists even in principle.

**Evidence.** `src/powderline/gateways/gsasii/server.py` (`state_dir`,
`_open_state_file`, `sign_request` / `sign_response`,
`SignedRequestMiddleware`, `_claim_server_lock`, `is_server_running`);
`src/powderline/gateways/gsasii/client.py` (`GSASClient._endpoint`,
`_signed_request`, `is_server_available`). Tests:
`tests/test_gsas_server_unit.py` (state-dir checks, lock incl. a concurrent
start race, signing on every route), `tests/test_gsas_server_http.py` (live
server), `tests/test_gsas_client_visibility.py` (impostor listeners, forged
results, `POWDERLINE_NO_SERVER`), `tests/test_api.py`,
`tests/test_api_gsasii_run.py`, `tests/test_cli.py`.

**Revisit.** Closed; kept for history. A Unix-domain-socket / named-pipe
transport would give OS-level peer authentication but needs separate POSIX and
Windows code paths; revisit if the HTTP transport is replaced (see KI-12).

---

## KI-15 — Four committed example references refine unphysical values; their output recipes are invalid by design `accepted · minor`

**What.** `example_DRX_33` (Li4MgWO6 crystallite size ≈ −1355 µm),
`example_DRX_33_anisoADP` (DRX_33 size ≈ −9.7 µm), `example_DRX_33_atomrefine`
(Li occupancy ≈ −0.35, a size ≈ −8 µm) and `example_LaB6_singlepeakfit` (its
background peak's σ² ≈ −2700 centideg², below GSAS-II's silent 0.01 floor,
EB-35) end their committed refinements on values the schemas refuse. Since
0.2.0 every result carries the output recipe (KI-04), so these runs return
`output_recipe_valid: false` with the warning `output_recipe_not_valid`
naming the value — the recipe is still written so the user sees
what the engine produced. A user running the examples will meet that warning.

**Evidence.** The three DRX_33 references' `output/refined_parameters.csv`
(`Size;i` −1.355638e+03 and −9.677202e+00, `Afrac` −3.514487e-01); the
single-peak fit writes no refined-parameter table — its value comes from the
`peak_fit` block of a run and is stated in its `DESCRIPTION.md` and
asserted in `tests/test_api_gsasii_run.py`. `tests/test_gsasii_paths.py`
and `tests/test_api_gsasii_run.py` assert the invalidity and the named value
for DRX_33, atomrefine and the single-peak fit (the anisoADP test checks the
Uij mapping only). Each example's `DESCRIPTION.md` "Known Issues" section
gives the physical re-posing's result where one exists (size held at 10 µm
as in `example_DRX_33_strainonly`: DRX_33 Rwp 8.46 vs 10.83 %, anisoADP 8.58
vs 15.53 %; atomrefine then fails on the metric tensor; the single-peak fit
with the background peak's widths and the last peak's γ held feeds back with
Rwp unchanged within the test's 0.05 pp).

**Decision.** The references stay as posed: they are the regression
references and, deliberately, the ill-conditioned teaching cases (the SVD
warnings, the railed sizes); `example_DRX_33_strainonly` is the physical
DRX_33 variant. Re-posing any of them is a deliberate change with an
equivalence record and regenerated outputs.

**Revisit.** If a re-posed reference is wanted for a tutorial, or when a
GSAS-II pin move regenerates the references anyway.

---

## KI-16 — TOPAS execution of 0.2.0 recipes is unverified; only INP generation is exercised `blocker (for the upstream merge) · major`

**What.** No machine in the 0.2.0 work had TOPAS. The `topas.*` gateway's
INP/XYE writer is pinned text-for-text to goldens produced on a TOPAS 6
machine before the refactor (`tests/data/topas/native/golden/`,
`test_topas_native_golden.py`, which also runs the current result parser on
the committed TOPAS output), and on a machine without `tc.exe` a run writes
the files and returns `status: generated`. Everything that needs a real run
— the parser on output the current writer's INP produced, the background-only second run, the
`topas_parameter_at_limit` warning against a real drift, non-ASCII output
directories, the failure contract when `tc.exe` dies or rejects an INP,
and the cell-refined LaB6 row of the cross-engine comparison page — has not
run since the refactor. TOPAS 7 is out of scope for 0.2.0.

**Evidence.** The maintainers keep the deferred list (nine items:
the native-runner smoke on both workflows, a cell-refined LaB6 fixture for
the comparison page, the at-limit warning and the non-ASCII output directory
against real runs, the ionic scattering types, the failure contract when
`tc.exe` dies or rejects an INP, the March–Dollase preferred orientation); `docs/cross-engine-comparison.md` (the
TOPAS LaB6 row keeps the cell fixed); `docs/support-matrix.md` states the
verification status.

**Decision.** On the fork, keep shipping generate-only with the goldens as
the contract, and say so where support is claimed (`docs/support-matrix.md`).
For the **upstream merge this is a blocker**: an engine the support matrix
lists must have had its execution path run at least once on the release's
code — the deferred items run on the first machine with TOPAS 6, and
recorded, move this entry to `watch`. The goldens move only with an
equivalence record (INP bytes must match).

**Revisit.** The first session on a machine with `tc.exe`; before the
upstream PR in any case.

**Update (2026-11-04).** A first session on a TOPAS 6 machine ran the native
runner on six fixtures. Every file each run produced matched its golden byte
for byte: INP, background INP, results, profiles and reflection lists. The
same session checked the version checks, generate-only, the command line,
the config file, `powderline --doctor`, and the failure route when `tc.exe`
is stopped. It also found three things now being addressed:
- a peak position that stops just inside the fit window's edge is not
  always reported;
- an output folder outside the Windows ANSI code page makes TOPAS fail;
- a fixed negative Lorentzian `X` runs without complaint.

The entry moves to `watch` after the confirming run on the release's code.

---

## KI-17 — A split atom's occupancy is not checked against its coinciding images `accepted · minor`

**What.** An atom placed off a special position to model disorder (a split
site) has `k` symmetry images where the ordered atom had one, `k` being the
general multiplicity divided by the special one. Unless its occupancy is
divided by `k`, the site holds `k` atoms. PowderLine validates the position
(it must be at least 2e-3 off the special position) but not the occupancy,
because a full occupancy is also a legitimate model: a genuinely general
site.

**Evidence.** `schema_core` derives the multiplicity of every site and
checks a stated `Multiplicity`. Nothing relates `occupancy` to the special
position the atom is near. The guidance is in
[input guidance, "Atoms near a special position"](input-guidance.md#atoms-near-a-special-position-disorder).

**Decision.** Documented, not checked: there is no rule that tells a split
site from a general one.

**Revisit.** If users report split sites refined at full occupancy, consider
an informative note when an atom lies within, say, 0.05 of a special
position at occupancy 1.

---

## KI-18 — A coordinate that refines into the ambiguous band near a special position is reported only through the output recipe `accepted · minor`

**What.** Validation refuses an atom stated 5e-6 to 2e-3 (fractional) from
a special position. During a refinement, though, no engine moves a refined
coordinate back onto one: GSAS-II never snaps, easydiffraction detects
Wyckoff positions only when the structure is built (EB-47), and TOPAS
compares exactly. So a split atom can refine into that band. The result is
still returned. Its output recipe fails validation
(`output_recipe_valid: false`), and the warning `output_recipe_not_valid`
names the coordinate, so a chained next step stops there.

**Evidence.** `powderline.roundtrip` re-validates every output recipe;
[input guidance, "Atoms near a special position"](input-guidance.md#atoms-near-a-special-position-disorder).

**Decision.** The run is not failed: its numbers are what the engine
computed, and the warning says what to do (state the atom on the special
position, or restart it further off).

**Revisit.** If a dedicated warning naming the special position proves
clearer than the generic output-recipe one.
