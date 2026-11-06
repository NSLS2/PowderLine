# Policies

These rules bind every change to PowderLine: how versions are numbered, how
behavior changes on purpose, which code is frozen, how engine versions move,
and how changes are reviewed. They also tell users what a version number
promises.

## Versioning

- **The package** follows [Semantic Versioning](https://semver.org/). Every
  release has an entry in the [CHANGELOG](../about/changelog.md).
- **The recipe schemas** are versioned separately from the package. There is
  one core schema and one engine schema per gateway (`gsasii`, `topas`,
  `easydiffraction`), each with a three-part version. A recipe states both
  `core_schema_version` and `engine_schema_version`.
- **Bumping a 0.x schema.** A breaking change bumps the minor version
  (0.1.0 → 0.2.0). Breaking means a recipe that was valid is refused, or
  means something else. An additive change or a fix bumps the patch
  (0.1.0 → 0.1.1). Each schema is bumped on its own.
- **Compatibility is declared, never inferred.** Core declares the core
  schemas it accepts (`SUPPORTED_CORE_SCHEMAS`). Each gateway declares
  `engine_schema_version`, `supported_engine_schemas` and
  `requires_core_schema` as PEP 440 specifiers. Validation enforces them, and
  `powderline.support_matrix()` lists them.
- **Declarations are exact.** Every declaration is written with `==`. When a
  new version has been checked, it is added explicitly. A range is never
  written in advance.
- **gemmi is pinned exactly** (`==0.7.5`). Core's space-group names are
  gemmi's canonical names (`tests/data/canonical_space_groups.txt`), and the
  symmetry rules are characterized against that version. Moving gemmi means
  re-running the symmetry tests, regenerating the list and recording the
  change on [Versions](../reference/versions.md).

The current declarations and the schema history are on
[Versions](../reference/versions.md).

## Deliberate behavior changes

Refinement results are regression references, so a change in behavior is
never incidental.

- **Every intentional change is deliberate.** A default, a validation rule,
  the meaning of a statistic, a unit or a set of files: each change is written
  down before it merges (what changes, who notices, and why). It is reviewed,
  and it gets a CHANGELOG entry. Where a user must act, the entry says what to
  do.
- **References move only with an equivalence check.** The outputs under
  `examples/**/output/` are tracked. To move them, run the old and the new
  code on the same recipes. Attribute every difference to a listed deliberate
  change. Only then regenerate the references.
- **Comparisons are tolerance-based.** A GSAS-II, scipy or BLAS change can
  shift refined values at the last digits. The tests compare within a
  tolerance, with a looser class for correlated size and strain terms, and
  compare peak lists by row count ([Contributing](contributing.md#regression-references-and-tolerance)).

## Frozen GSAS-II code

Six modules hold the hand-written functions that set up and run a GSAS-II
refinement by manipulating GSAS-II's project dictionary:

`src/powderline/gateways/gsasii/{helpers,project,setters,executors,extractors,constraints}.py`

GSAS-II's project-dictionary conventions can't be fully pinned down by tests.
So these functions change only with the maintainers' explicit consent.

- **Behavior-changing edits** need the maintainers' explicit consent before
  they are made. Propose the edit with its reason and its proof (for example,
  a diff of the project dictionary before and after).
- **Comment and docstring edits** need no consent: they change no behavior.
  Don't leave an outdated comment in place.
- **New behavior** goes into the non-frozen modules around them
  (`fit_report.py`, `sites.py`, `routing.py`, `paths.py`, `gateway.py`).
- **After any edit**, run `pixi run update-code-hash` and commit
  `src/powderline/_code_hash.json` with the change. The hash covers the raw
  bytes, so a comment edit changes it too. `tests/test_code_hash.py` fails
  until the hash is updated.
- **Replace the GSAS-II server** after the edit. A server started earlier
  still runs the old code. Stop it with `pixi run -e gsasii gsas-server stop`,
  and the next run starts a fresh one. `gsas-server restart` also works, but
  it runs the new server in the foreground of that terminal until you stop
  it.

## Engine-version pins

Every engine is pinned to one version. The regression references and
goldens were produced with it.

| Engine | Pin | Run-time check | Suite |
|---|---|---|---|
| GSAS-II | `pixi.toml` `[feature.gsasii.dependencies]`: `GSAS-II = { git = …, rev = <commit> }`, the pixi-build source revision | `ENGINE_VERSION_SPEC` in `gateways/gsasii/gateway.py` (`==5.7.9`), against `GSASII.__version__` | `pixi run -e gsasii test-gsasii` |
| easydiffraction | `pixi.toml` `[feature.easydiffraction.pypi-dependencies]`: `easydiffraction = "==0.21.1"` | `ENGINE_VERSION_SPEC` in `gateways/easydiffraction/gateway.py` | `pixi run -e easydiffraction test-easydiffraction` |
| TOPAS | Not installable. A `topas.*` recipe states `engine_version` | `SUPPORTED_ENGINE_VERSIONS` in `gateways/topas/schema.py` (`==6`), against the declared installed version | `pixi run test-topas` on the TOPAS machine |

A version outside the specifier raises `EngineVersionError`.
`tests/test_gateways.py` checks that the pixi pins lie inside the specifiers,
and `tests/test_gateways_installed_engines.py` checks the installed engine.

```{note}
`tc.exe` carries no version PowderLine can read. So you declare the
installed TOPAS version with `--topas-version`, the `topas_version` option of
`powderline.run()`, or `topas.version` in `.powderline_config.yaml`. The
check compares declarations, not the binary.
```

### Try a newer engine

A pin moves only after a compatibility run. Never widen a pin without one.
`scripts/check_engine_version_candidate.py` prints the steps for one engine
and candidate, filled in with the current specifier and the files to edit.
It runs no pixi command and edits nothing:

```bash
pixi run python scripts/check_engine_version_candidate.py --engine gsasii --version 5.8.0 --rev <commit>
pixi run python scripts/check_engine_version_candidate.py --engine easydiffraction --version 0.22.0
pixi run python scripts/check_engine_version_candidate.py --engine topas --version 7
```

1. **Make a throwaway environment.** In a scratch worktree
   (`git worktree add ../pl-candidate -b scratch/<engine>-<version>`), raise
   the pin in `pixi.toml` and widen the gateway's specifier to admit the
   candidate. Then run `pixi lock`, `pixi install -e <env>` and
   `pixi reinstall powderline`. Nothing from this worktree is pushed.

   ```{note}
   Widening the specifier is the test override. The CLI and
   `powderline.run()` have no bypass. `allow_unsupported_engine_version=True`
   exists only on a gateway's own `run()`, for tests.
   ```

2. **Run that engine's suite, `slow` included**, against the committed
   references: `pixi run -e <env> test-<engine>`.
3. **Record the result** in the pull request: pass or fail per test, and for
   every regression case the deltas of the refined values, their ESDs and
   Rwp against the references, even when within tolerance.
4. **On a pass**, open one pull request that moves the pin and the specifier
   together and updates every page that names the engine version. The
   references are not regenerated.
5. **On a fail**, record the behavior change in the same report. Decide
   between a schema bump (with a re-baseline, see
   [Deliberate behavior changes](#deliberate-behavior-changes)) and staying
   pinned. The pin stays where it is until that decision is made.

Per engine:

- **GSAS-II.** The pin is the source revision; the specifier is the
  run-time `GSASII.__version__`. The conda package version comes from the
  fork's recipe and is unrelated. A candidate that needs an edit to a frozen
  module needs the maintainers' consent first
  ([Frozen GSAS-II code](#frozen-gsas-ii-code)).
- **easydiffraction.** A new version also re-runs the settings verification
  for both calculators (`scripts/verify_easydiffraction_settings.py`, about
  two hours of CPU; `--jobs N` runs N processes). It regenerates
  `space_group_support.py`. `tests/test_easydiffraction_space_groups.py`
  skips until `space_group_table.py` is regenerated for the installed version
  (`scripts/generate_easydiffraction_space_groups.py`). Re-check the
  behaviors on the [easydiffraction page](../engines/easydiffraction.md): an
  upstream fix may retire a workaround.
- **TOPAS.** The goldens live under
  `tests/data/topas/native/golden/<version>/`, chosen by each fixture's
  `engine_version`. Adding TOPAS 7 needs a TOPAS 7 installation for the
  `topas_exec` run, its own goldens, and a check of TOPAS 7's convergence. It
  also needs every behavior on the [TOPAS page](../engines/topas.md) marked
  unverified for TOPAS 7 to be checked on TOPAS 7. The
  generation suite (`topas_gen`) runs anywhere and compares INPs byte for byte
  with the TOPAS 6 goldens, so a change in what is written shows without
  TOPAS.

## Review

- A human is responsible for every change and reviews every line. CI runs
  the engine-free, GSAS-II and easydiffraction suites on Linux and Windows
  before merge. `test-all`, and `test-topas` for a TOPAS change, are run by
  hand.
- A change that moves a reference, a default, a pin or a frozen module is
  reviewed against its written reason, not against its diff alone.
- AI-assisted commits end with one `Assisted-by: <agent>:<model>` trailer per
  model that contributed. An AI is never listed as a co-author.

## Ask, don't assume

If a design decision is not written down (on this page, on
[Versions](../reference/versions.md) or on an [engine page](../engines/index.md)),
stop and ask the maintainers. Don't infer the answer from the code's current
behavior or from what another engine does. Write the answer down where the
next contributor will find it.

The reason is the project's whole stance. An engine's silent default is not a
decision. Plausible inferences about engine quirks have been wrong often
enough (origin choices, a variance read as a width, two parameters swapping
roles) that the written answer is the only safe one.
