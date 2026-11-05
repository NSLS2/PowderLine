# Contributing to PowderLine

Thanks for your interest! This page is the map; the detail lives in the linked
guides.

## Dev setup

```bash
git clone https://github.com/NSLS2/PowderLine.git
cd PowderLine
pixi install -e dev   # every engine + docs/test tooling (GSAS-II is built as a conda package)
pixi run test         # full suite (dev env) — run it before and after your change
pixi run docs         # Sphinx with -W; zero warnings is the standard
```

The default environment is core-only (it validates recipes for every engine
and runs none); `pixi install -e gsasii` / `-e easydiffraction` install one
engine. After pulling a change to `pyproject.toml`'s entry points, run
`pixi reinstall powderline --all`.

[pixi](https://pixi.sh) is the only tool you install yourself. See the
[README](README.md) for platforms and the [Quickstart](docs/quickstart.md) for
a first refinement run.

## Where things are

- **[docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)** — developer guide:
  architecture (core + gateways), the schema layer, **how to add a refinement
  engine or a capability**, GSAS-II integration, workflow.
- **[docs/policies.md](docs/policies.md)** — what binds every change:
  versioning and declared compatibility, deliberate behaviour changes, the
  frozen GSAS-II modules, engine-version pins, review, "ask, don't
  assume".
- **[docs/engine-behavior.md](docs/engine-behavior.md)** — what each engine
  does with a recipe and PowderLine's policy toward it.
- **[docs/known_issues.md](docs/known_issues.md)** — the known-issues register
  (`KI-NN` ids, referenced from code and docs): check it before "fixing" a
  quirk. See also [docs/regression-tolerance.md](docs/regression-tolerance.md)
  (why numeric comparisons are tolerance-based) and
  [docs/cross-platform-guide.md](docs/cross-platform-guide.md).
- **[examples/CONTRIBUTING_EXAMPLES.md](examples/CONTRIBUTING_EXAMPLES.md)** —
  how to contribute a new example recipe (examples drive schema evolution).

## Design records

Maintainers keep design records in a separate private repository.
`_dev/` is reserved and gitignored; never commit it.

Dev-doc scaffold paths (`docs/superpowers/`, `docs/plans/`, `docs/specs/`,
`docs/dev/`), `.gpx` binaries, `fort.*` scratch, and `_dev/` are all rejected by
the pre-commit guard so they never reach `main`.

## Ground rules

- Branch off `main`; keep commits reviewable and self-contained.
- Enable the pre-commit guard once per clone:
  `git config core.hooksPath scripts/hooks`. It blocks accidental commits of
  data files outside the sanctioned dirs, `.gpx` binaries, and the private
  `_dev/` workspace.
- Run `pixi run test` before opening a PR. Some regression cases need a working
  GSAS-II refinement — compare failures against a baseline run, don't assume
  they're yours.
- The frozen GSAS-II modules
  (`src/powderline/gateways/gsasii/{helpers,project,setters,executors,extractors,constraints}.py`)
  change only through the maintainers' signed-off record of frozen-code
  edits; after such an edit run `pixi run update-code-hash`. Restart the GSAS-II server after
  editing anything it runs (`pixi run -e gsasii gsas-server restart`).
- After editing a schema module or a gateway's version declarations, run
  `PYTHONPATH=src python scripts/gen_schema_field_tables.py` and commit the
  regenerated `docs/_generated/` fragments.
- If a decision is not written down (policies page, schema history), ask the maintainer rather than inferring it.
- `examples/**/output/` is tracked on purpose (regression references) — don't
  regenerate it casually.
- Questions and bug reports: open a GitHub issue.

## Changelog

[CHANGELOG.md](CHANGELOG.md) follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

- Every user-visible change adds a bullet under `## [Unreleased]`, in the
  right section: `Added`, `Changed`, `Deprecated`, `Removed`, `Fixed` or
  `Security`. Internal work (tests, CI, refactoring that changes nothing a
  user sees) gets no bullet.
- A bullet is one to three lines, written for users, and links the
  documentation page, `KI-NN` / `EB-NN` id or pull request where useful.
- No internal ids: no branch names, private design-record or review ids, and
  no names of people in decisions.
