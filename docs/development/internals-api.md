# Internals API

The modules behind the public API, for contributors and gateway authors.
None of this is the public API: use [`powderline.run`](../reference/api.md)
and the [`powderline` command](../reference/cli.md) to run recipes.

## Command line

```{eval-rst}
.. py:module:: powderline.kicker
```

The `powderline` command ([reference](../reference/cli.md)). The pixi task
`kicker` runs the same `main`. The module imports no engine.

```{eval-rst}
.. autofunction:: powderline.kicker.main

.. autofunction:: powderline.kicker.is_template_file
```

## Doctor

```{eval-rst}
.. py:module:: powderline.doctor
```

`powderline --doctor`'s report. `report()` returns a dict with the keys
`powderline`, `python`, `platform`, `gateways`, `server` and `problems`. Each
entry of `gateways` has `workflows`, `engine_version_spec`,
`engine_installed`, `engine_status` and `problem`. `format_report()` renders
the dict, and `main()` prints it and returns 1 when `problems` is not empty.
The module imports no engine; it imports the gateway modules when the report
runs. The stale-install case it detects is {ref}`KI-13 <ki-13>`.

## Gateway registry

Gateways are discovered from the `powderline.gateways` entry-point group.
These are the hooks an out-of-tree engine uses.

```{eval-rst}
.. autoclass:: powderline.registry.Gateway

.. autofunction:: powderline.registry.available

.. autofunction:: powderline.registry.get

.. autofunction:: powderline.registry.register_gateway

.. autofunction:: powderline.registry.check_engine_version
```

## Gateway `run` functions

Each gateway's `run` is what `powderline.run` forwards to, after it has
validated the recipe and chosen the gateway. Their keyword options are exactly
the engine options `powderline.run` accepts for that engine.

:::{warning}
Run recipes with `powderline.run` or the `powderline` command, not with these.
Calling a gateway's `run` directly skips what `powderline.run` does on every
engine: PowderLine's fixed-name outputs are not cleared first, and a failed
run writes no `failure.json`.
:::

```{eval-rst}
.. autofunction:: powderline.gateways.gsasii.gateway.run

.. autofunction:: powderline.gateways.topas.gateway.run

.. autofunction:: powderline.gateways.easydiffraction.gateway.run
```

## GSAS-II gateway helpers

These functions belong to the frozen GSAS-II extraction and setup code
(`powderline.gateways.gsasii.extractors` and `.setters`).

### Output generation

```{eval-rst}
.. autofunction:: powderline.gateways.gsasii.extractors.export_refined_parameters_csv

.. autofunction:: powderline.gateways.gsasii.extractors.calculate_cell_esds_from_A_matrix

.. autofunction:: powderline.gateways.gsasii.extractors.extract_refined_params_from_project
```

:::{note}
ESDs are read from GSAS-II's covariance matrix (`proj.data['Covariance']`).
Unit-cell ESDs are converted from the reciprocal metric tensor (the A-matrix)
to the direct lattice parameters by `calculate_cell_esds_from_A_matrix()`.
:::

### Post-refinement extraction helpers (private)

The four private `_extract_*` helpers hold the post-refinement extraction and
file-writing logic.

```{eval-rst}
.. autofunction:: powderline.gateways.gsasii.extractors._extract_fit_profile

.. autofunction:: powderline.gateways.gsasii.extractors._extract_spf_peak_report

.. autofunction:: powderline.gateways.gsasii.extractors._extract_phase_reports

.. autofunction:: powderline.gateways.gsasii.extractors._extract_refined_parameters
```

### Background functions

```{eval-rst}
.. autofunction:: powderline.gateways.gsasii.setters.set_chebyshev_background

.. autofunction:: powderline.gateways.gsasii.setters.set_single_peak_background
```

### Fit range

```{eval-rst}
.. autofunction:: powderline.gateways.gsasii.setters.set_fit_range_hist
```
