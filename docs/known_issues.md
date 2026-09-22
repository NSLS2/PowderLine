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

---

## KI-01 — Malformed fixed cell computes a wrong pattern silently `accepted · critical`

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

---

## KI-02 — Oblique (monoclinic/triclinic) per-parameter cell holds are limited `implemented (0.26), limitation inherent · minor`

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

---

## KI-03 — Site symmetry & multiplicity are derived, and failures are swallowed `planned-fix · major`

**What.** PowderLine derives each atom's site symmetry and multiplicity at load
via `G2spc.SytSym`, inside a bare `except Exception: pass`, defaulting to `""`
and `1` on failure. The recipe never states these, and a derivation failure is
invisible.

**Evidence.** `kicker.py:1170-1176`.

**Decision.** Candidate for dedicated work: make site symmetry and multiplicity
explicit, validated recipe fields, with an immediate safety patch to stop
swallowing the exception. Improves resilience and decouples structural
interpretation from GSAS-II for future multi-engine support.

**Revisit.** At minimum, stop swallowing the exception when the surrounding area
is next touched.

---

## KI-04 — Recipe→output provenance is implicit; no round-trip `planned-fix · major`

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

---

## KI-05 — GSAS-II refinement failures & constraint warnings don't raise `planned-fix · major`

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

---

## KI-06 — GSAS-II parameter-limit (min/max) semantics are clamp-and-freeze `watch · minor`

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

---

## KI-07 — Space-group setting (hexagonal vs rhombohedral, origin choice) is unvalidated `watch · critical`

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

---

## KI-08 — Sphinx build emits reST warnings from `RecipeModel` docstring `fixed · nit`

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
- A `missing-reference` hook in `docs/conf.py` retries any unresolved
  `py:class` type-hint reference as a `py:obj` lookup: type-hint rendering
  always emits a `class`-role xref for bare identifiers, but a type alias
  like `RefinementParameter` is documented as `py:data`, which the
  `class` role's objtype search can never match — regardless of aliasing. `obj`
  matches every objtype, so this is a legitimate, narrowly-scoped fallback
  (not a suppression) and makes every `RefinementParameter` field a real
  hyperlink to its `#:`-documented definition.
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

**Revisit.** Closed; kept for history.

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

**Evidence.** `src/powderline/gsas_server.py:371`;
`tests/test_gsas_server_unit.py:157`.

**Decision.** Fixed: the escalation now uses
`getattr(signal, "SIGKILL", signal.SIGTERM)` — on Windows,
`os.kill(pid, SIGTERM)` maps to `TerminateProcess`, the correct hard kill — and
unit tests drive the escalation path (`tests/test_gsas_server_unit.py`).

**Revisit.** Closed; kept for history.

---

## KI-11 — Server discovery is split between PID file and port probe; an orphaned server is unmanageable `watch · minor`

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
`gsas_client.py:180` (the former hardcoded `':'`, now `os.pathsep`).

**Decision.** File for a server-lifecycle robustness pass: align `status`/
`stop` with the client's probe (e.g. `status` also checks `/health`; add an
HTTP shutdown endpoint, or have `stop` fall back to the PID reported by
`/health`).

**Revisit.** Next branch touching `gsas_server.py`/`gsas_client.py`.

---

## KI-12 — Server mode assumes a shared filesystem; output files should travel in-band `planned-fix · major`

**What.** The GSAS-II server writes output files into `output_dir` in **its
own** filesystem view and returns only result *data* over HTTP. A server
without a shared view (another cluster node; a sandbox/container with a
private `/tmp`) therefore cannot deliver the file outputs at all. The client's
output-visibility guard (stat-compare of `fit_profile.txt` before/after the
run) detects the mismatch and falls back to in-process execution — a
mitigation, not a fix, and it keeps a (cheap) filesystem check in the client.

**Evidence.** `gsas_server.py` security notes (server resolves `output_dir`
in its own view); `gsas_client.py` `_server_output_visible` /
`_submit_to_server_guarded`; `tests/test_gsas_client_visibility.py`.
mp-simulate's `.chi` export already consumes the in-band `fit_profile` dict,
showing the in-band path works.

**Decision.** Planned fix in a future server-protocol branch: the server runs
in a server-local scratch directory and returns **all output artifacts
in-band** (gpx/lst as base64/text, CSVs as text) and the client materializes
the files locally. This dissolves the divergent-view failure instead of
detecting it, deletes the guard, and makes cross-node servers (HPC: client on
a login/worker node, GSAS-II server elsewhere, no shared filesystem) a
supported topology. Needs protocol versioning for already-running servers.

**Revisit.** Next branch touching the server protocol, or when the HPC
deployment work starts.
