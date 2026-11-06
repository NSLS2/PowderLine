# Contributing

This page gets you from a fresh clone to a reviewed pull request: set up, run
the tests, build the docs, and write a change that fits the project. The
rules that bind every change are on [Policies](policies.md).

## Set up

```bash
git clone https://github.com/NSLS2/PowderLine.git
cd PowderLine
pixi install --frozen -e dev
git config core.hooksPath scripts/hooks
pixi run test
```

[pixi](https://pixi.sh) is the only tool you install yourself. The `dev`
environment holds every engine plus the docs and test tooling. `--frozen`
installs from the committed lock as is, so the GSAS-II package is not
re-locked. The other environments are described in
[Install](../getting-started/install.md).

The `git config` line turns on the pre-commit guard, once per clone. It
blocks commits of the private maintainer workspace, GSAS-II `.gpx` binaries,
Fortran `fort.*` scratch files, design scaffolds under `docs/`, and data files
outside `examples/`, `tests/data/` and `docs/`.

Run a recipe with the command users run:

```bash
pixi run powderline examples/example_LaB6/input.json --validate-only
pixi run -e gsasii powderline examples/example_LaB6/input.json --output my_lab6
```

The pixi task `kicker` runs the same command. Every option is on
[Command line](../reference/cli.md).

## Run the tests

| Command | What it runs | Where |
|---|---|---|
| `pixi run test` | The engine-free suites (`core`, `topas_gen`), with a guard that fails on any engine import | any environment |
| `pixi run -e gsasii test-gsasii` | The GSAS-II suite, slow regressions included | `gsasii` |
| `pixi run -e easydiffraction test-easydiffraction` | The easydiffraction suite (about 18 minutes) | `easydiffraction` |
| `pixi run test-topas` | TOPAS input generation, and `tc.exe` runs where TOPAS is installed | any; runs TOPAS only on its machine |
| `pixi run test-all` | Every suite | `dev` |

Extra pytest arguments pass through: `pixi run test -x -k schema`. A later
`-m` replaces the task's own, so this runs the GSAS-II suite without its slow
regressions:

```bash
pixi run -e gsasii test-gsasii -m "gsasii and not slow"
```

Every test carries exactly one suite marker (`core`, `gsasii`, `topas_gen`,
`topas_exec`, `easydiffraction`), plus the optional `slow`. The markers are
declared in `pyproject.toml`, and `tests/conftest.py` refuses a test with
none or two.

The `topas_exec` tests run `tc.exe` only when two variables name the TOPAS
installation. Otherwise they skip with a reason. In PowerShell:

```powershell
$env:POWDERLINE_TOPAS_DIR = 'C:\TOPAS6'
$env:POWDERLINE_TOPAS_VERSION = '6'
pixi run test-topas
```

```{important}
Some GSAS-II regression and ESD tests need a working GSAS-II refinement and
can fail for environment reasons. Run the suite on `main` first, then on your
branch, and compare. Don't assume a failure is yours, and don't assume it
isn't.
```

CI runs on every pull request to `NSLS2/PowderLine` and on every push to
`main`. On Linux and Windows it runs `test`, `fields-check`, `catalog-check`,
`figures-check`, `test-gsasii` and `test-easydiffraction`. The docs build
(`pixi run docs`) runs on Linux, for pushes to `main` and for pull requests
from forks. `test-all`, and `test-topas` on the TOPAS machine, are run by
hand.

### Regression references and tolerance

The example outputs under `examples/**/output/` are committed on purpose. The
regression tests run each example again and compare against them.
Refinements are byte-deterministic on one machine. Between builds and
platforms, GSAS-II, scipy or BLAS can shift refined values at the last
digits. So refined values are compared within a tolerance. Peak lists are
compared by row count. TOPAS and easydiffraction are compared against their
goldens under `tests/data/{topas,easydiffraction}/native/golden/`.

A value passes when |test − reference| ≤ atol + rtol·|reference|.

| Comparison | Where | Tolerance |
|---|---|---|
| Unit-cell reports | `unit_cell_match`, `tests/subprocess_utils.py` | rtol 1e-4, atol 1e-6 |
| `refined_parameters.csv`, output recipe, dispositions | `refined_params_match` and its siblings, `tests/subprocess_utils.py` | rtol 1e-3, atol 1e-4 |
| Correlated size and strain broadening (category `other`: Size, Mustrain) | the same functions, `loose_rtol` | rtol 1e-2, atol 1e-4 |
| GSAS-II uniform Rwp | `UNIFORM_RWP_TOLERANCE`, `tests/test_example_LaB6_regression.py` | within 0.1 percentage point |
| GSAS-II's own wR in `dummy.lst` | `tests/test_esd_extraction.py`, a tripwire on the frozen code | within 0.1 percentage point of the same reference |
| easydiffraction goldens: values, ESDs, Rwp, Rexp, GoF, χ²_red | `GOLDEN_RTOL`, `tests/test_easydiffraction_native.py` | rtol 1e-3; a value near zero also passes within 1 % of its ESD |
| easydiffraction goldens: unit cell | `GOLDEN_CELL_RTOL` | rtol 1e-4 |

Size and strain get the loose tolerance because they are ill-conditioned:
the two separate poorly, and they reproduce across builds only to about 1 %.
Every other class keeps the tight guard. CrysFML refinements stop at
start-dependent points ({ref}`EB-90 <eb-90>`), so their goldens compare only
the counts, the warnings and the cell.

A reference moves only as a deliberate change, with an equivalence check
([Policies](policies.md#deliberate-behavior-changes)).

## Build the docs

```bash
pixi run docs
```

The build runs Sphinx with `-W --keep-going` and nitpicky mode. Zero warnings
is the standard. The output is in `docs/_build/html`; `pixi run docs-clean`
removes it.

Some fragments under `docs/` are written by scripts. Regenerate them in the
same change that affects them, and commit the result.

| Script | Writes | Check |
|---|---|---|
| `scripts/gen_schema_field_tables.py` | The field tables and support matrix in `docs/_generated/` | `pixi run fields-check` |
| `scripts/gen_catalog.py` | The engine-behavior entries, the ID index and the known-issue entries, from `docs/catalog/*.yaml` | `pixi run catalog-check` |
| `scripts/gen_example_figures.py` | The example gallery's figures, from each example's committed `fit_profile.txt` | `pixi run figures-check` |
| `scripts/cross_engine_comparison.py` | The cross-engine comparison tables in `docs/_generated/` | none; `--no-run` rebuilds from committed results |

Run the field-table generator after editing a schema module or a gateway's
declarations:

```bash
pixi run python scripts/gen_schema_field_tables.py
```

The engine-behavior entries, the [ID index](../reference/ids.md) and
[Known issues](../reference/known-issues.md) are generated from
`docs/catalog/engine_behaviour.yaml` and `docs/catalog/known_issues.yaml`.
Edit the YAML, never the generated pages, then run
`pixi run python scripts/gen_catalog.py`.

### Regenerate the cross-engine comparison

The tables on [Comparing engines](../concepts/comparing-engines.md) come from
`scripts/cross_engine_comparison.py`:

```bash
pixi run -e gsasii python scripts/cross_engine_comparison.py
pixi run -e easydiffraction python scripts/cross_engine_comparison.py --no-run --rerun-easydiffraction
pixi run python scripts/cross_engine_comparison.py --no-run
```

1. The first command runs GSAS-II on the committed examples. It rebuilds the
   TOPAS and easydiffraction rows from the goldens.
2. The second re-runs the easydiffraction fixtures, keeps the GSAS-II rows
   just recorded, and reports how close the rerun is to its golden.
3. The third rebuilds the tables from committed files only: the goldens and
   the JSON record of the last GSAS-II run.

The TOPAS rows come from the committed TOPAS 6 goldens
(`tests/data/topas/native/golden/6/`). They change only when the goldens are
regenerated on a TOPAS machine. The docs build never runs an engine.
`tests/test_cross_engine_comparison.py` runs the `--no-run` path and checks
that both cases and all three engines are present.

### Writing documentation

These rules keep the pages consistent. They apply to every page under
`docs/`, the README and the examples' descriptions.

- **Voice.** Write to "you", in the present tense and the active voice. One
  idea per sentence; paragraphs of one to four sentences. Lead with what the
  reader does, then the caveat.
- **Caveats in admonitions.** Use `{note}`, `{warning}`, `{important}` or
  `{tip}` instead of chains of parentheses. If a caveat doesn't merit one,
  cut it.
- **Current state only.** Describe PowderLine as it is. No "now", "since",
  "no longer" or "previously". History belongs in the CHANGELOG.
- **One home per fact.** Write a fact on the page that owns it. Everywhere
  else, write one sentence and link it.
- **A recipe is structured data.** It is a dictionary, serialized as JSON.
  Don't define it as a file.
- **Engine differences in tabs.** Use a sphinx-design `tab-set` with
  `:sync-group: engine` and the keys `gsasii`, `topas` and `easydiffraction`.
- **Show, then tell.** Put the snippet, table or diagram first. Diagrams are
  ` ```mermaid ` blocks with one idea each.
- **Headings in sentence case.** "Choose the fit window", not "Choose The
  Fit Window".
- **User commands.** Teach `pixi install --frozen -e <env>` and
  `pixi run [-e <env>] powderline …`. `kicker` and `pixi reinstall` belong on
  contributor pages only.
- **IDs.** `EB-NN` and `KI-NN` are public; link them with
  `` {ref}`EB-87 <eb-87>` ``. No internal tracking IDs, no private paths and
  no names attached to decisions.
- **Accuracy.** Check every field name, flag, warning code and file name
  against `src/`. Run every snippet you can.

## Write portable pixi tasks

PowderLine ships for `linux-64`, `win-64` and `osx-arm64`. Everything must
work on Linux and Windows, where it is tested; macOS is not routinely
tested. The one exception is TOPAS execution, which needs
`tc.exe` on Windows.

- Set environment variables through the task-level `env` dict, which pixi
  expands on every platform:

  ```toml
  test = { cmd = 'pytest -m "core or topas_gen"', env = { PYTHONPATH = "$PIXI_PROJECT_ROOT/src" } }
  ```

- Don't write `PYTHONPATH=$PWD/src:$PYTHONPATH cmd`. The `:` separator is
  Unix-only, and Windows Python misreads it.
- Don't call Unix tools such as `rm -rf`. Write the step in Python, as
  `docs-clean` does.
- Put an engine-bound task in its engine's feature (`[feature.gsasii.tasks]`).
  Without `-e`, pixi then reports it as ambiguous and prints the form to use.
- In Python, guard POSIX-only APIs. `signal.SIGKILL` and `fcntl` don't exist
  on Windows. The GSAS-II server shows the pattern: `os.name == 'nt'`
  branches, `msvcrt.locking` beside `fcntl.flock`, and
  `getattr(signal, "SIGKILL", signal.SIGTERM)`.
- Write text output as UTF-8 with LF line endings
  (`encoding="utf-8", newline="\n"`), so files are byte-identical across
  platforms.

## Add an example

Examples are real refinement cases. They drive the schemas and serve as
regression references. Each lives in `examples/<case>/` with its recipe, a
`DESCRIPTION.md` and, for GSAS-II, the committed output. How to contribute
one is in
[examples/CONTRIBUTING_EXAMPLES.md](https://github.com/NSLS2/PowderLine/blob/main/examples/CONTRIBUTING_EXAMPLES.md).

## Record the change in the CHANGELOG

`CHANGELOG.md` follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

- Every user-visible change adds a bullet under `## [Unreleased]`, in the
  right section: `Added`, `Changed`, `Deprecated`, `Removed`, `Fixed` or
  `Security`.
- Internal work (tests, CI, refactoring that changes nothing a user sees)
  gets no bullet.
- A bullet is one to three lines, written for users. Link the docs page, the
  `KI-NN` or `EB-NN` ID, or the pull request where useful.
- No internal IDs: no branch names, private design-record or review IDs, and
  no names of people attached to decisions.

## Troubleshooting for contributors

### `ModuleNotFoundError: No module named 'powderline'`

You ran Python outside pixi. Use `pixi run …`; every task sets `PYTHONPATH`.
With `PYTHONPATH=src` alone and no installed package, the gateway entry
points are missing and `GatewayNotInstalledError` follows. Fix that with
`pixi reinstall powderline --all`.

### A test fails

1. Run the same test on `main`. If it fails there too, the cause is the
   environment, not your change.
2. For a GSAS-II regression, compare the engine's log:
   `diff output/dummy.lst examples/example_LaB6/output/dummy.lst`.
3. If your change moves a result on purpose, it is a deliberate change
   ([Policies](policies.md#deliberate-behavior-changes)). Regenerate the
   reference only then, for example:

   ```bash
   pixi run -e gsasii powderline examples/example_LaB6/input.json --no-server --output examples/example_LaB6/output
   ```

### `test_code_hash` fails

A frozen GSAS-II module changed. If the edit is a comment or docstring edit,
or a behavior change the maintainers agreed to, run
`pixi run update-code-hash` and commit `src/powderline/_code_hash.json` with
it. Otherwise revert the edit and put the behavior in a non-frozen module
([Architecture](architecture.md#the-frozen-gsas-ii-modules)).

### A generated-docs check fails

`fields-check`, `catalog-check` or `figures-check` names the stale file. Run
the script from [Build the docs](#build-the-docs) without `--check`, then
`pixi run docs`.

### My fix has no effect on a GSAS-II run

A GSAS-II server started before your edit still runs the old code.
`pixi run -e gsasii gsas-server status` prints `Code: STALE` when the
server's code differs from the working tree. Stop it, or run with
`--no-server`:

```bash
pixi run -e gsasii gsas-server stop
```

The next run in `auto` or `server` mode starts a fresh server in the
background. `gsas-server restart` and `start` run the server in the
foreground of that terminal until you stop it, so run them in a terminal of
their own.
