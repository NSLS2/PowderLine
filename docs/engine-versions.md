# Engine versions: the compatibility procedure

PowderLine pins every refinement engine to one version:
the pixi manifest installs it, the gateway's `ENGINE_VERSION_SPEC` refuses any
other at run time (`EngineVersionError`), and the regression references under
`examples/*/output/` were produced with it. Refined values drift at the last
digit across engine, scipy and BLAS builds, so a new engine version is a change
to the reference set until proven otherwise. **Never widen a pin without the
record below.**

| Engine | Pin (install) | Spec (run time) | Suite |
|---|---|---|---|
| GSAS-II | `pixi.toml` `[feature.gsasii.dependencies] GSAS-II = { git = ..., rev = <commit> }` -- the pixi-build source revision | `src/powderline/gateways/gsasii/gateway.py` `ENGINE_VERSION_SPEC` (`GSASII.__version__`) | `pixi run -e gsasii test-gsasii` |
| easydiffraction | `pixi.toml` `[feature.easydiffraction.pypi-dependencies] easydiffraction = "==x.y.z"` | `src/powderline/gateways/easydiffraction/gateway.py` `ENGINE_VERSION_SPEC` | `pixi run -e easydiffraction test-easydiffraction` |
| TOPAS | not installable: the recipe declares `engine_version`, the installed version is declared in `.powderline_config.yaml` | `src/powderline/gateways/topas/schema.py` `SUPPORTED_ENGINE_VERSIONS` (the published `==6` is derived from it) | `pixi run test-topas` on the TOPAS machine (`topas_exec`) |

`tests/test_gateways.py` asserts the manifest pins lie inside the specs;
`tests/test_gateways_installed_engines.py` asserts the installed engine does.

## Checking a candidate version

`scripts/check_engine_version_candidate.py` prints the steps below for one
engine and candidate, filled in with the current spec and the exact files to
edit. It is dry: it runs no pixi command and edits nothing.

```bash
pixi run python scripts/check_engine_version_candidate.py --engine gsasii --version 5.8.0 --rev <commit>
pixi run python scripts/check_engine_version_candidate.py --engine easydiffraction --version 0.22.0
pixi run python scripts/check_engine_version_candidate.py --engine topas --version 7
```

1. **Throwaway environment.** In a scratch worktree (`git worktree add
   ../pl-candidate -b scratch/<engine>-<version>`), raise the pin in
   `pixi.toml` to the candidate and widen the gateway's spec to include it --
   the spec edit is the *test override*: the CLI and `powderline.run()` have no
   bypass (`allow_unsupported_engine_version` is reachable only on a gateway's
   own `run()`), so the regression suite can only drive the candidate
   through a spec that admits it. Then `pixi lock`, `pixi install -e <env>`,
   `pixi reinstall powderline`. Nothing from this worktree is pushed.
2. **Run that gateway's suite including `slow`** against the committed
   references: `pixi run -e <env> test-<engine>`. The regression tests compare
   within the tolerances of `docs/regression-tolerance.md`
   (`tests/subprocess_utils.py` `refined_params_match`, `unit_cell_match`).
3. **Record** the result in a compatibility report: pass / fail per test, and for every regression case the numeric deltas of the
   refined parameters (value and esd) and of Rwp against the committed
   references, even when within tolerance.
4. **Pass**: one PR that widens the spec, moves the pin, and updates the
   support matrix (`powderline.support_matrix()` reports the spec; the
   `docs/integration-guide.md` install notes name the version). The references
   are not regenerated.
   **Fail**: the behaviour change is recorded in the same report; decide
   between a schema bump (the engine's `engine_schema_version`, with a
   re-baseline, see [policies](policies.md#deliberate-behaviour-changes)) and
   staying pinned. Either way the pin stays
   where it is until that decision is taken.

### Per engine

- **GSAS-II.** The pin is the pixi-build source revision (`rev`), the spec is
  the runtime `GSASII.__version__` (the conda package version is the fork
  recipe's and unrelated). Both move together. The GSAS-II setup/execution
  modules are code-hashed (`tests/test_code_hash.py`); a candidate that needs an
  edit there goes through the maintainers' signed-off record of frozen-code
  edits first.
- **easydiffraction.** An exact pin. A new version also re-runs the settings
  verification for both calculators
  (`scripts/verify_easydiffraction_settings.py`, at most 4 workers, about 1.5 h;
  it regenerates `space_group_support.py`) and the maintainers' engine-issue
  reproductions for easydiffraction: an upstream fix may
  retire a PowderLine workaround. `tests/test_easydiffraction_space_groups.py`
  skips until `space_group_table.py` is regenerated for the installed version.
- **TOPAS.** Nothing to install; `SUPPORTED_ENGINE_VERSIONS` is `("6",)`
  (published as `==6`), and the goldens live under
  `tests/data/topas/native/golden/<version>/`, chosen by each fixture's
  `engine_version`. Widening
  to TOPAS 7 needs the TOPAS 7 machine for the `topas_exec` run and the
  TOPAS 7 convergence follow-up; it is post-refactor unless the
  maintainer says otherwise. The generation suite (`topas_gen`) runs
  anywhere and compares INPs byte-for-byte with the TOPAS 6 goldens, so a
  version change that alters what is written is visible without TOPAS.
