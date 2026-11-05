# Messages

PowderLine speaks to you in three ways:

- a **validation error** stops a recipe before anything runs;
- a **warning** comes with a valid recipe or a finished run;
- a **failure reason** names why a run failed.

## Validation errors

An invalid recipe raises pydantic's `ValidationError`. It lists **every**
problem at once, each at its field path. Most messages name the value to
write.

```text
$ pixi run powderline my_recipe.json --validate-only

❌ Recipe validation failed: my_recipe.json

Validation errors:
  • payload -> instrument -> radiation: Field required
  • payload -> instrument -> radiaton: Extra inputs are not permitted
  • payload -> phases -> LaB6 -> unit_cell: Value error, unit cell is inconsistent with 'P m -3 m' (cubic): stated b = 4.2, but by symmetry b = a; write b = 4.15682

Please fix the errors above and try again.
See examples/example_LaB6/input.json for a working example.
```

The command exits with status 1.

In Python, catch the error and read its list:

```python
from pydantic import ValidationError

try:
    powderline.validate(recipe)
except ValidationError as e:
    for problem in e.errors():
        print(problem["loc"], problem["msg"])
```

- `loc` is the field path as a tuple, e.g.
  `('payload', 'phases', 'LaB6', 'unit_cell')`.
- Structural checks (the cell against the space group, special positions, tie
  groups) run once the individual fields are valid. Fix the first errors and
  validate again to see them.
- Validation needs no engine. It works in every environment.

Why the checks are strict, and what they check, is on
[Validation](../concepts/validation.md).

## Warning codes

A warning is a dict `{code, message, field_path[, level]}`. It comes back in
`result["warnings"]`, in `powderline.validate(recipe).warnings`, and in the
validate-only summary.

- `level: "warning"`: act on it, or decide about it. The CLI prints these.
- `level: "info"`: a record of something PowderLine did that changes no
  outcome. The CLI counts these, and lists them with `--verbose`.
- No `level` key means `"warning"`.

| Code | Engine | Level | Meaning |
|---|---|---|---|
| `gsasii_broadening_default_applied` | gsasii | warning | Sample size or strain left out: 10 µm and 0 microstrain applied, fixed. |
| `gsasii_background_default_applied` | gsasii | warning | `background` (or its `chebyshev`) left out: one fixed Chebyshev term 0.0 applied, instead of GSAS-II's refined constant 1.0. |
| `gsasii_refinement_cycles_default_applied` | gsasii | warning | `refinement_cycles` left out: the default 5 cycles run. |
| `gsasii_refinement_message` | gsasii | warning | A message GSAS-II stored with the refinement: correlations, singular parameters, SVD. |
| `gsasii_fit_not_converged` | gsasii | warning | The last cycle's χ² change was above GSAS-II's tolerance. The values are kept. |
| `gsasii_parameters_not_varied` | gsasii | warning | GSAS-II varied fewer parameters than the recipe refines. |
| `uaniso_not_positive_definite` | core | warning | The stated `Uaniso` has a principal value ≤ 0. It is used as stated. |
| `symmetry_value_derived` | core | info | A coordinate, cell value or Uij stated within tolerance of its exact symmetry-derived value is held in that form. The message gives both values. An exactly stated value gets no note. |
| `output_recipe_not_valid` | core | warning | The output recipe does not validate as written: an engine returned a value the schema refuses, or a symmetry tie came back inconsistent. It is still returned and written, with `output_recipe_valid: false`. |
| `topas_adp_converted` | topas | warning | `Uiso` was written to TOPAS as `beq = 8π²·Uiso`. |
| `topas_parameter_at_limit` | topas | warning | A refined value ended at a stated bound or a TOPAS default limit. |
| `topas_parameters_not_varied` | topas | warning | TOPAS varied fewer parameters than the recipe refines. |
| `topas_phase_contributes_nothing` | topas | info | A phase's calculated intensities are all zero: its scale is 0, or TOPAS discarded a non-finite calculation. |
| `topas_base_name_sanitized` | topas | warning | The base name is not ASCII-safe for TOPAS, so the files are written as `topas.*`. |
| `topas_background_not_calculated` | topas | warning | The background-only run wrote nothing or was stopped at the time limit. `y_bkg` is empty. |
| `topas_generate_only` | topas | info | No `tc.exe` declared: the INP and `.xye` were written and TOPAS did not run (`status: "generated"`). |
| `easydiffraction_parameter_at_limit` | easydiffraction | warning | A refined value ended at a bound or a physical limit. |
| `easydiffraction_parameters_not_varied` | easydiffraction | warning | lmfit varied fewer parameters than the recipe refines. |
| `easydiffraction_phase_contributes_nothing` | easydiffraction | info | A phase's calculated intensities are all zero. |
| `easydiffraction_fit_not_converged` | easydiffraction | warning | lmfit stopped without success. The values are reported. |
| `easydiffraction_negative_width` | easydiffraction | warning | The refined profile makes a peak width negative near the fit window. |
| `easydiffraction_reflections_not_available` | easydiffraction | warning | The CrysFML calculator reports no reflection list, so there are no peak lists. |
| `easydiffraction_position_translated` | easydiffraction | warning | easydiffraction holds an atom in another writing of the same position. Bounds and reports stay in the recipe's writing. |
| `easydiffraction_crysfml_start_dependent` | easydiffraction | warning | Every CrysFML refinement: CrysFML computes in single precision, so the result can depend on the starting values. |

This table lists the same codes as `powderline.exceptions.WARNING_CODES`,
with the same engine and level. What each engine does, and why PowderLine
warns, is on the engine pages: [GSAS-II](../engines/gsasii.md),
[TOPAS](../engines/topas.md) and [easydiffraction](../engines/easydiffraction.md).

## Failure reasons

A failed run raises `EngineExecutionError` (kind `engine`: the engine ran and
failed) or `ExecutionBackendError` (kind `backend`: the engine never ran). The
reason is `e.reason` on the error and `failure.reason` in the failed envelope
and in `failure.json` ([Outputs](outputs.md#when-a-run-fails)).

| Reason | Kind | Meaning |
|---|---|---|
| `diverged` | engine | A non-finite calculated pattern or value inside the fit window. For GSAS-II also a refinement GSAS-II itself aborted because no damped step lowered χ² ({ref}`EB-99 <eb-99>`). Simulations are exempt. |
| `unusable_site` | engine | The engine reads an atom's site or a symmetry tie differently from PowderLine's core ({ref}`EB-40 <eb-40>`, {ref}`EB-05 <eb-05>` for GSAS-II; {ref}`EB-47 <eb-47>` for easydiffraction). The run stops before refining. |
| `peak_fit_failed` | engine | GSAS-II's peak fit returned nothing ({ref}`EB-38 <eb-38>`). |
| `engine_crashed` | engine | The engine raised or exited abnormally: a GSAS-II crash, an lmfit, CrysPy or CrysFML error, or a `tc.exe` that could not start. |
| `output_missing` | engine | TOPAS wrote none of its expected files. |
| `output_malformed` | engine | An engine file could not be read strictly: a non-numeric token, a ragged row, missing points, or a pattern on other 2θ values. |
| `server_unavailable` | backend | Server mode: no GSAS-II server was running and none could be started. |
| `server_disabled` | backend | Server mode was requested while `POWDERLINE_NO_SERVER` is set. |
| `communication_failed` | backend | An HTTP or transport error after a GSAS-II server was found. |
| `timeout` | backend | GSAS-II: the server's answer took longer than `server_timeout`. The job is still running on the server, so there is no in-process fallback. TOPAS: `tc.exe` took longer than `topas_timeout` and was stopped. |
| `backend_error` | backend | Anything else on the execution path before the engine ran, such as a recipe the server could not validate. |

:::{note}
A TOPAS background-only run stopped at the time limit is not a failure. The
result has an empty `y_bkg` column and the warning
`topas_background_not_calculated`.
:::

The reason codes are `powderline.results.REASONS`, split into
`ENGINE_REASONS` and `BACKEND_REASONS`. Error messages by symptom, with their
fixes, are on [Troubleshooting](../how-to/troubleshooting.md).
