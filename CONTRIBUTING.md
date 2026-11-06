# Contributing to PowderLine

Thanks for your interest. This page is the short version. The full guide is
the [Development section](https://nsls2.github.io/PowderLine/development/) of
the docs: architecture, setup, tests, the docs build, adding an engine, and
the policies.

## Set up

```bash
pixi install --frozen -e dev            # every engine + docs and test tooling
git config core.hooksPath scripts/hooks # the pre-commit guard, once per clone
pixi run test                           # the engine-free suites
```

[pixi](https://pixi.sh) is the only tool you install yourself.

## Ground rules

- Branch off `main` and keep commits reviewable and self-contained.
- Run the tests before and after your change, and compare against `main`:
  some GSAS-II regression cases can fail for environment reasons.
- Keep `pixi run docs` free of warnings. After editing a schema or a gateway's
  declarations, regenerate the field tables (`pixi run fields-check` tells you
  when they are stale).
- The frozen GSAS-II modules
  (`src/powderline/gateways/gsasii/{helpers,project,setters,executors,extractors,constraints}.py`)
  change behavior only with the maintainers' explicit consent. Comment and
  docstring edits are fine. After any edit, run `pixi run update-code-hash`.
- `examples/**/output/` is tracked on purpose (regression references). It
  moves only as a deliberate, reviewed change.
- If a decision is not written down, ask the maintainers rather than infer
  it.
- AI-assisted commits end with an `Assisted-by: <agent>:<model>` trailer.
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
