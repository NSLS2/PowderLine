# Outputs

A run gives you two things:

- the **result dict** that `powderline.run()` returns, with the tables as
  pandas DataFrames;
- **files** in the output directory: the same tables as reports with fixed
  names, the output recipe, and the engine's own files.

Every engine returns the same keys and writes the same report files. What the
statistics, the output recipe and the dispositions mean is explained on
[Results](../concepts/results.md).

## The result dict

```python
result = powderline.run(recipe, "output/")
result["status"], result["rwp"], result["unit_cell_data"]["LaB6"]
```

| Key | Type | Value |
|---|---|---|
| `status` | str | `"ok"`, or `"generated"` when the TOPAS input was written but TOPAS was not run. |
| `converged` | bool or None | `True` or `False`. `None` for any simulation, when the engine cannot tell (TOPAS 6, a GSAS-II peak fit), and when TOPAS was not run. |
| `envelope_version` | str | `"1"`: the version of this result's shape. |
| `run_id` | str | A UUID4 that identifies this run. |
| `rwp`, `r_exp` | float or None | PowderLine's uniform Rwp and Rexp over the fit window, in percent. |
| `gof`, `chi2_red` | float or None | PowderLine's uniform GoF and reduced χ², dimensionless. |
| `simulation_mode` | bool | `True` for a simulation: `refinement_cycles: 1` (GSAS-II), `iters: 0` (TOPAS), or no refine flag set (easydiffraction). |
| `engine_details` | dict | The engine's own statistics and counts ([below](#engine-details)). |
| `warnings` | list of dict | Structured warnings from validation and from the run ([below](#warnings)). |
| `elapsed_time` | float | Wall-clock seconds. |
| `method` | str | Which execution path ran ([below](#method)). |
| `output_files` | list of str | The paths written to the output directory. |
| `output_recipe` | dict | The recipe with the refined values written back ([below](#the-output-recipe)). |
| `output_recipe_valid` | bool | Whether `output_recipe` validates as written. |
| `parameter_dispositions` | DataFrame | How each value of the output recipe came about ([below](#parameter-dispositions)). |
| `fit_profile` | DataFrame | The observed and calculated pattern ([columns](#report-files)). |
| `unit_cell_data` | dict of DataFrame | Per phase, keyed by phase name: the seven unit-cell rows. |
| `peak_list_data` | dict of DataFrame | Per phase, keyed by phase name: the reflection list. |
| `refined_parameters` | DataFrame | Every refined parameter with its ESD, by the engine's names. |
| `spf_peaks` | DataFrame | Single-peak fitting: the fitted peaks. Empty otherwise. |
| `spf_convergence_diagnostics` | DataFrame | Single-peak fitting: convergence diagnostics per peak. Empty otherwise. |
| `peak_fit` | dict or None | GSAS-II results only. For `gsasii.spf`, every parameter the peak fit varied; `None` for `gsasii.rietveld`. |

Statistics are `None` where they are undefined, for example when there are
no degrees of freedom. There is no `success` key: `status` is the outcome, and
a failed run raises instead of returning ([When a run fails](#when-a-run-fails)).

### Engine details

`engine_details` holds what the engine itself reports. The uniform statistics
above are PowderLine's; these are the engine's own.

| Key | Engines | Value |
|---|---|---|
| `engine`, `engine_version` | all | The engine and the version that ran. For TOPAS, the declared version. |
| `n_points` | all | The number of points in the fit window with a positive weight. |
| `parameters_requested` | all | The number of parameters the recipe refines, one per symmetry tie group. |
| `parameters_varied` | all | The number of parameters the engine varied. |
| `rwp` | all | The engine's own Rwp. |
| `gof`, `chi2`, `n_obs`, `message`, `converged` | GSAS-II | GSAS-II's own GoF, χ², point count, refinement message and convergence flag. `converged` is `None` for a peak fit. |
| `console_tail` | GSAS-II | The engine's console text, after a verbose run that succeeded. |
| `r_exp`, `gof`, `tc_path` | TOPAS | TOPAS's own Rexp and GoF, and the `tc.exe` that ran. |
| `calculator`, `peak_type`, `minimizer` | easydiffraction | The calculator, the peak type and the minimizer. |
| `r_exp`, `reduced_chi_square` | easydiffraction | easydiffraction's own Rexp and reduced χ². |

### Warnings

Each warning is a dict:

```python
{"code": "gsasii_broadening_default_applied",
 "message": "phase 'LaB6': size_broadening left out, so PowderLine applies ...",
 "field_path": "payload.phases.LaB6.peak_broadening.size_broadening"}
```

- `code` is one of the [warning codes](messages.md#warning-codes).
- `field_path` is the recipe path the warning refers to, or `None`.
- `level` is `"warning"` or `"info"`. When it is absent, read it as
  `"warning"`: `w.get("level", "warning")`.

### Method

| `method` | Meaning |
|---|---|
| `server` | GSAS-II ran in the persistent GSAS-II server. |
| `subprocess` | GSAS-II ran in the calling process. |
| `topas`, `topas_simulation` | TOPAS ran a refinement, or a simulation. |
| `topas_generate_only` | The TOPAS input was written; TOPAS did not run (`status` is `"generated"`). |
| `easydiffraction`, `easydiffraction_simulation` | easydiffraction ran a refinement, or a simulation. |
| `validate_only` | Nothing ran ([Validate-only summary](#validate-only-summary)). |

### The output recipe

`output_recipe` is a complete recipe with the same `schema_name`. It is
**resolved**:

- refined values are written back at their recipe paths;
- values derived from symmetry are in their exact form;
- defaults the gateway applied are stated;
- your flags, bounds, controls and data are unchanged.

It is ready to be the input of the next run. It is written to
`output_recipe.json`, about the size of the input recipe, because it repeats
the data arrays.

PowderLine writes one key into its `metadata`: `powderline_provenance`.

| Key | Value |
|---|---|
| `parent_run_id` | The `run_id` of the run that produced this recipe; `None` for a validate-only summary. |
| `schema_name`, `engine` | The recipe's schema and engine. |
| `engine_version` | The engine version the run used. For TOPAS, the declared version. `None` for a validate-only summary. |
| `powderline_version` | The PowderLine version. |
| `created` | When the recipe was written, in UTC (ISO 8601). |

`output_recipe_valid` is `False` when the output recipe does not validate as
written. This happens when an engine returned a value the schema refuses, or a
symmetry tie came back inconsistent. The recipe is still returned and written,
and the warning `output_recipe_not_valid` says why.

### Parameter dispositions

`parameter_dispositions` (and `parameter_dispositions.csv`) has one row per
refinable value of the recipe:

| Column | Value |
|---|---|
| `path` | The recipe path, e.g. `payload.phases.LaB6.unit_cell.a`. |
| `value`, `esd` | The value in the output recipe and its ESD. |
| `disposition` | How the value came about (below). |
| `at_limit` | `True` when the value ended on a stated bound or an engine's default limit. |

The disposition is the first of these that applies:

| `disposition` | Meaning |
|---|---|
| `default_applied` | PowderLine applied a documented default. |
| `held_by_symmetry` | Symmetry fixes the value, or ties it to another. |
| `held_by_user` | The refine flag is `false`. |
| `requested_not_varied` | The flag is `true`, but the engine did not vary the value. |
| `varied` | The engine refined the value. |

## Report files

`powderline.run()` writes these into the output directory with fixed names,
for every engine:

| File | Contents |
|---|---|
| `refined_parameters.csv` | Every refined parameter: `parameter_name, descriptive_name, phase_name, phase_idx, atom_name, atom_idx, value, esd, category`. |
| `<phase>_unit_cell_report.csv` | `parameter, value, esd` for the seven rows `cell_a`, `cell_b`, `cell_c`, `cell_alpha`, `cell_beta`, `cell_gamma`, `cell_volume`. |
| `<phase>_peak_list_report.csv` | The reflection list: `h, k, l`, d-spacing, 2θ and the engine's other columns. |
| `fit_profile.txt` | Tab-separated: `two_theta, y_obs, y_weights, y_calc, y_diff, y_bkg, q_values, d_spacings`. |
| `output_recipe.json` | The [output recipe](#the-output-recipe). |
| `parameter_dispositions.csv` | The [dispositions](#parameter-dispositions). |

Single-peak fitting adds:

| File | Engine | Contents |
|---|---|---|
| `single_peaks_report.txt` | GSAS-II | Each peak's position, intensity and widths, and whether it converged. |
| `peak_convergence_diagnostics.txt` | GSAS-II | Written only when a peak did not converge. |
| `single_peaks_report.csv` | TOPAS | Each peak's position, intensity, widths, FWHM and integral breadth, with ESDs. |

Exceptions:

- easydiffraction's CrysFML calculator reports no reflection list, so no
  `<phase>_peak_list_report.csv` is written with it.
- A GSAS-II simulation writes no `refined_parameters.csv`. TOPAS and
  easydiffraction write one with no rows.
- In a simulation, every unit-cell `esd` is `0.0`.

:::{note}
**One run per directory.** Before every run, `powderline.run()` removes these
fixed-name files and `failure.json` from the output directory. It never
removes the engine's own files. It does this only once the recipe has
validated and the engine is available, so an invalid recipe leaves the
previous results in place.
:::

### Unit-cell rows: two vocabularies

The same cell values appear under two kinds of name:

| Where | Name for the `a` axis |
|---|---|
| `<phase>_unit_cell_report.csv`, `unit_cell_data` | `cell_a` |
| `output_recipe`, `parameter_dispositions` | `payload.phases.<phase>.unit_cell.a` |

The report uses the same row names for every engine, so a row stays
self-describing when you concatenate tables from several runs.
`powderline.reports.UNIT_CELL_ROW_OF` and `UNIT_CELL_MEMBER_OF` convert
between the two.

`refined_parameters.csv` uses a third vocabulary on purpose: the **engine's**
names (`0::A0` in GSAS-II, `p1_cell_a` in TOPAS, `broad_gauss_u` in
easydiffraction). It is the engine's own table, with `descriptive_name`,
`phase_name` and `atom_name` beside each name. `parameter_dispositions` gives
the same values by recipe path.

### Uncertainties (ESD and s.u.)

:::{note}
PowderLine labels uncertainties `esd` (estimated standard deviation), the
term the refinement engines use. The quantity is what the IUCr calls the
*standard uncertainty* (s.u.) (Schwarzenbach et al.,
[Acta Cryst. A 51, 565–569 (1995)](https://doi.org/10.1107/S0108767395002340)),
in line with [NIST Technical Note 1297](https://www.nist.gov/pml/nist-technical-note-1297)
(Taylor & Kuyatt, 1994).
:::

The unit-cell report follows one rule on every engine:

| Cell value | `esd` |
|---|---|
| Refined, and the engine reported an ESD | the engine's ESD |
| Fixed by symmetry, or held by its flag | `0.0` |
| Refined, but the engine reported no ESD | empty |
| Volume, when the engine propagates its ESD (GSAS-II, TOPAS) | the engine's ESD |
| Volume of a cell with nothing refined | `0.0` |
| Volume otherwise (easydiffraction) | empty |

## Native artefacts

Each engine's own files stay in the output directory beside the reports.

| Engine | Files |
|---|---|
| GSAS-II | `dummy.gpx`, the GSAS-II project, which you can open in the GSAS-II GUI. `dummy.lst`, GSAS-II's refinement log with its own Rwp and parameter tables. |
| TOPAS | `<base>.inp` and `<base>.xye`, what TOPAS was given. `<base>_results.csv`, `<base>_profile.txt` and `<base>_p<n>_peaks.txt` per phase, what TOPAS wrote. `<base>_bkg.inp` and `<base>_bkg_profile.txt`, the background-only run that provides the `y_bkg` column. |
| easydiffraction | None. The data and structure are handed to the library in memory. |

`<base>` is the name of the directory above the output directory when the
output directory is called `output`, and `topas` otherwise. A base name that
is not ASCII is written as `topas`, with the warning
`topas_base_name_sanitized`.

Without a `tc.exe`, a TOPAS run writes `<base>.inp` and `<base>.xye`, plus
`output_recipe.json` and `parameter_dispositions.csv`, and returns
`status: "generated"`. This is a normal outcome, not a failure. The output
recipe is the resolved input. Every parameter with a refine flag set has the
disposition `requested_not_varied`.

## When a run fails

A failed run never returns a result. It raises one of two errors:

| Error | Meaning |
|---|---|
| `EngineExecutionError` | The engine ran and failed. |
| `ExecutionBackendError` | The engine never ran. |

Both carry `.reason`, a [failure reason](messages.md#failure-reasons), and
`.result`, the failed envelope:

| Key | Value |
|---|---|
| `status` | `"failed"` |
| `envelope_version`, `run_id`, `elapsed_time`, `method`, `warnings`, `simulation_mode` | As in a result. |
| `output_files` | The files kept for diagnosis: the engine's own files written so far, and `failure.json`. |
| `failure` | `kind` (`"engine"` or `"backend"`), `reason`, `message`, `traceback`, `engine_details`. GSAS-II and TOPAS runs add `console_tail`: the last 65,536 characters the engine printed, or `None`. |

```python
try:
    result = powderline.run(recipe, "output/")
except powderline.EngineExecutionError as e:
    print(e.reason)                       # e.g. "diverged"
    print(e.result["failure"]["message"])
```

`powderline.run()` also writes the envelope to `failure.json` in the output
directory, beside the engine's files. It adds a `powderline_provenance` block
with `schema_name`, `engine`, `engine_version`, `powderline_version`, `created`
and `run_id`, so a directory found later says what failed. No report file is
written for a failed run.

## Validate-only summary

`powderline.run(recipe, output_dir, validate_only=True)` and
`powderline <recipe.json> --validate-only` validate the recipe and write
nothing. The summary has the same keys for every engine:

| Key | Value |
|---|---|
| `status` | `"validated"` |
| `rwp` | `None` |
| `elapsed_time` | `0.0` |
| `method` | `"validate_only"` |
| `schema_name`, `core_schema_version`, `engine_schema_version` | From the recipe. |
| `phases` | The number of phases (0 for single-peak fitting). |
| `simulation_mode` | `True` for a simulation, by the same rule as in a result. |
| `parameters_requested` | The number of parameters the recipe refines. |
| `warnings` | The structured warnings of validation. |
| `engine` | The engine's own controls: `refinement_cycles` (GSAS-II), `iters` and `engine_version` (TOPAS), `calculator` (easydiffraction). |
| `output_recipe`, `output_recipe_valid` | The resolved recipe, as the engine would receive it, and whether it validates. |

`powderline.validate(recipe)` is the lighter check: it returns the validated
model and its warnings ([Python API](api.md)).
