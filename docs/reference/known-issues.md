# Known issues

A **known issue** is a behavior of PowderLine itself that is understood and
recorded: a limit it accepts, a failure route it documents, or a problem it
has resolved. Each has a permanent ID, `KI-NN`, that the code, messages and
the changelog cite. An ID is never reused, so a withdrawn or resolved issue
stays listed.

What the engines do on their own, and what PowderLine does about it, is on
the [Engines](../engines/index.md) pages, under `EB-NN` IDs. Every ID is
listed in the [ID index](ids.md).

| Status | Meaning |
|---|---|
| {bdg-danger}`open` | Known, and not yet addressed. |
| {bdg-warning}`accepted` | Known, and deliberately not prevented. The entry says what to do. |
| {bdg-info}`watch` | A quirk to keep in mind. No action planned. |
| {bdg-success}`resolved` | Addressed in the current release. |
| {bdg-secondary}`withdrawn` | Not a defect. |

Severity is the impact if you meet the issue: **critical** (silent wrong or
empty output, or data loss), **major** (breaks a real workflow), **minor**
(works, but fragile or wrong in edge cases) or **nit** (cleanup).

```{include} ../_generated/known_issues.md
```
