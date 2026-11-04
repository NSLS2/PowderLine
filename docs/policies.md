# Policies and process

How PowderLine versions what it ships, how it changes behaviour on purpose,
which code is frozen, how engine versions move, and how changes are reviewed.
This page is for contributors and for users who need to know what a version
number promises.

## Versioning and compatibility

- **The package** follows [Semantic Versioning](https://semver.org/); every
  release has an entry in the root [`CHANGELOG.md`](changelog.md). v0.1.1 is
  the last release of the unified-schema era; **v0.2.0** is the multi-engine
  refactor and a clean break (one recipe = one engine; no translation layer).
- **The recipe schemas** are versioned separately from the package: a
  **core schema** (the shared frame and structural models) and one **engine
  schema** per gateway (`gsasii`, `topas`, `easydiffraction`), all `0.1.0`
  today (always three parts). A recipe states both versions. The schemas
  are pre-1.0 because PowderLine is pre-production and they will still
  evolve; they start at 0.1.0 in PowderLine 0.2.0 and are told apart from the
  old unified schema (0.1–0.26.0, `GSASII_Rietveld` / `GSASII_SPF`) by
  `schema_name`, not by number.
- **Bumping a schema version (0.x).** While a schema is 0.x, a **breaking**
  change (a recipe valid before is refused or means something else) bumps
  the minor (0.1.0 → 0.2.0); an **additive** change or a fix bumps the patch
  (0.1.0 → 0.1.1). Each schema (core and every engine schema) is bumped on
  its own. The support declarations stay exact (`==`): a release that accepts
  a second version lists it explicitly once it has been checked, never as a
  range.
- **Compatibility is declared, never inferred from version numbers.** Core
  declares the core-schema versions it accepts (`SUPPORTED_CORE_SCHEMAS`);
  each gateway declares `engine_schema_version`, `supported_engine_schemas`
  and `requires_core_schema` as PEP 440 specifiers in its `capabilities()`;
  `validate()` enforces the declarations, and
  `powderline.support_matrix()` lists them. The rendered matrix is on the
  [support matrix page](support-matrix.md). Every declaration today is
  `==0.1.0`; a declaration is **widened explicitly** when a new version has
  been checked, never by writing a range in advance.
- **Engine versions** are handled per engine:
  - GSAS-II and easydiffraction are **pinned by pixi** (GSAS-II as the source
    revision of the pixi-build fork, easydiffraction as `==0.21.1`) and the
    gateway's `ENGINE_VERSION_SPEC` is checked against the installed engine
    at run time; a mismatch is a hard `EngineVersionError`.
  - TOPAS cannot be pinned by PowderLine: a `topas.*` recipe states the
    TOPAS major version it is written for (`engine_version`), the gateway
    declares the versions it supports (`==6`: `topas.*` 0.1.0 is verified
    against TOPAS 6 only), and the user **declares** the installed version
    (`--topas-version` or `topas.version` in `.powderline_config.yaml`),
    because `tc.exe` carries no version PowderLine could read. The check
    compares declarations, not the binary.
  - `easydiffraction.*` recipes carry no engine version; the library's
    version is read at run time.
- **gemmi is pinned exactly** (`==0.7.5`): core's space-group contract is its
  canonical names (`tests/data/canonical_space_groups.txt`) and the symmetry
  rules are characterized against that version. Widening gemmi means
  re-running the symmetry tests, regenerating the list and recording the
  change in [SCHEMA_HISTORY](SCHEMA_HISTORY.md).
- The schema changelog ([SCHEMA_HISTORY](SCHEMA_HISTORY.md)) records every
  declaration change; the package changelog records the release that made
  it; the [migration guide](migration-0.1-to-0.2.md) covers the break from
  schema 0.26.0 (PowderLine 0.1.x) to the 0.2 schemas (0.1.0).

## Deliberate behaviour changes

Refinement results are regression references: `examples/**/output/` is
tracked, and the suite compares a fresh run against it within the
tolerances of [`regression-tolerance.md`](regression-tolerance.md). So a
change in behaviour is never incidental:

- Every intentional change relative to the previous release (a default, a
  validation rule, a statistic's meaning, a unit, a file set) is **recorded
  as a deliberate change** in the maintainers' table (one row per change:
  what changes, who notices, why, the decision), reviewed at a gate, and
  surfaces in the CHANGELOG and, where a user must act, in the migration
  guide.
- The references under `examples/**/output/` move only through a
  **re-baseline** with an equivalence record: the old path and the new path
  are run on the same recipes, every difference is attributed to a listed
  deliberate change, and only then are the references regenerated. 0.2.0 had
  exactly one such re-baseline (the native gsasii path).
- A GSAS-II (or scipy/BLAS) change can shift refined values at the last
  digit, so the comparisons are tolerance-based (`refined_params_match`,
  `unit_cell_match`), with a documented loose class for correlated
  size/strain terms; peak lists are compared by row count.

## Frozen GSAS-II code and the edits ledger

The code that sets up and executes a GSAS-II refinement, in
`src/powderline/gateways/gsasii/{helpers,project,setters,executors,extractors,constraints}.py`,
is **frozen**: it was moved verbatim out of `kicker.py` at the verified re/01
baseline `daace24` (the `require_phase` decorator in place of five inline phase
checks, A46; a refactor-branch commit, not on `main`), and
every statement that touches the GSAS-II project dictionary is protected.
`src/powderline/_code_hash.json` holds a hash of each module, and
`tests/test_code_hash.py` fails when a module changes without the hash being
regenerated.

- An edit to these modules happens only through the maintainers'
  **signed-off edits ledger** (one row per edit: the line, the reason, the
  proof, the signature); additive behaviour goes into new modules
  (`fit_report.py`, `sites.py`, `routing.py`, `gateway.py`) rather than into
  the frozen ones. What the ledger admits: additive or input-side edits
  (R31–R37), and output-side control flow that leaves the project-dictionary
  work untouched when the failure contract needs it (R30, the failure
  propagation; R38, the checks before any result table is written).
- After a signed edit, run `pixi run update-code-hash` and commit
  `_code_hash.json` with the change; the commit message cites the ledger
  row.
- A GSAS-II server started before the edit still runs the old code: restart
  it (`pixi run -e gsasii gsas-server restart`).

The freeze protects GSAS-II's project-dictionary conventions, which no test
can fully pin down; it does not protect the recipe reads, which the native
schema replaced under the ledger.

## Engine-version pins: how to try a newer engine

The pins (`pixi.toml` and each gateway's `ENGINE_VERSION_SPEC`; the
`supported_engine_versions` of the topas schema) move only after a
**compatibility run**:

1. Install the candidate engine in a scratch environment (for GSAS-II, a
   pixi feature pointing at the candidate revision; for easydiffraction, the
   candidate `==` pin; for TOPAS, the machine that has it).
2. Run the suite against it with the test-only bypass of the version check:
   the gateway's own `run(..., allow_unsupported_engine_version=True)`
   (deliberately **not** reachable through `powderline.run()`, which refuses
   the keyword). The regression references and goldens must pass within the
   documented tolerances, or every difference must be attributed to an
   engine change and recorded as a deliberate change.
3. Record the run (engine version, platform, counts, differences) in the
   branch report.
4. Move the pin and the specifier **together**, in one commit, and update
   [SCHEMA_HISTORY](SCHEMA_HISTORY.md) / the CHANGELOG. For TOPAS, widening
   `supported_engine_versions` (e.g. to TOPAS 7) also needs the TOPAS-7
   behaviours recorded as *unverified* on the
   [engine behaviour page](engine-behavior.md) to be checked.

The testing branch of the refactor (re/09) owns the per-environment suite
layout and may move this procedure onto a dedicated testing page; until then
this section is the reference.

## Review gates

The refactor was organized as a branch series with **gates** rather than
per-commit review: G1 (shared core and registry), G2 (the native gsasii
path and the removal of the unified schema: equivalence report, deliberate
changes, public API, suites per environment), G3 (packaging and tests), G4
(documentation, the full Linux + Windows matrix, the TOPAS smoke on a TOPAS
machine, the version bump). Each gate produces an evidence record in the
maintainers' devkit and needs the maintainer's sign-off; the final pull
request `refactor/multi-engine` → `main` is where CI first runs, and its
matrix must be green before the merge. After the refactor the same
principle holds for ordinary work: a change that moves a reference, a
default, a pin or a frozen module is reviewed against its record, not
against its diff alone.

## "Ask, don't assume"

For contributors (human or AI): if a design decision is not already made
(in the decision log, in a signed-off record, in this page or in the
schema history), **stop and ask the maintainer** rather than inferring an
answer from the code's current behaviour or from what another engine does.
Record the answer where the next contributor will find it. The reason is
the project's whole stance: an engine's silent default is not a decision,
and a plausible inference about a quirk has been wrong often enough
(origin choices, variance vs width, the X/Y role swap) that the written
answer is the only safe one.

## Provisional decisions

The maintainer's decision log is the authority for every policy above.
During October 2026 a set of decisions was taken while the maintainer was
away, to finish the refactor as a tested starting point; they are numbered
**P-01 onward** in the maintainers' record (the P-numbers quoted in the
CHANGELOG and the migration guide) and are **provisional, pending the
maintainer's review**: each may be accepted, amended or reverted. Where
this documentation describes a behaviour that rests on a P-row (the removal
of the LaB6 background peak, the per-engine example recipes, the rejection
of charged scattering types, the public API and single CLI, the pixi
environment layout, the generated field tables), it describes what the code
does today; the maintainer's answer may change it in a later release, and
the CHANGELOG will say so.
