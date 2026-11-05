# Python API

The public API is the names in `powderline.__all__`, plus the result
envelope, the warning shape and the recipe helpers below.

```python
import powderline

recipe = powderline.load_recipe_asset("examples/example_LaB6/input.json")
checked = powderline.validate(recipe)          # no engine needed
result = powderline.run(recipe, "output/")     # needs the recipe's engine
```

`import powderline` imports no engine. `validate` uses only each gateway's
engine-free schema layer. `run` imports the engine the recipe's `schema_name`
names, when it runs.

- Every recipe field, with its unit: [Fields](fields.md).
- Every key of the result: [Outputs](outputs.md).
- Using the API in scripts and pipelines:
  [Use PowderLine from Python](../how-to/python-pipelines.md).

## Run and validate

```{eval-rst}
.. py:module:: powderline

.. autofunction:: powderline.run

.. autofunction:: powderline.validate

.. autoclass:: powderline.ValidationResult
   :members:

.. autofunction:: powderline.load_recipe_asset

.. autofunction:: powderline.support_matrix
```

## Exceptions

Every PowderLine error derives from `PowderLineError`. An invalid recipe
raises pydantic's own `ValidationError` instead
([Validation errors](messages.md#validation-errors)).

```{eval-rst}
.. autoexception:: powderline.PowderLineError

.. autoexception:: powderline.GatewayNotInstalledError

.. autoexception:: powderline.EngineNotAvailableError

.. autoexception:: powderline.EngineVersionError

.. autoexception:: powderline.EngineExecutionError

.. autoexception:: powderline.ExecutionBackendError
```

## The result envelope

The exceptions carry the failed envelope as `.result`, and every gateway
builds its result with these functions. The module also defines
`ENVELOPE_VERSION` (`"1"`), `STATUSES` (`ok`, `generated`, `failed`), and
`ENGINE_REASONS` and `BACKEND_REASONS`, the
[failure reasons](messages.md#failure-reasons).

```{eval-rst}
.. automodule:: powderline.results
   :members: failure_envelope, generated_envelope, with_status_fields, raise_if_failed
```

## Structured warnings

The shape of each entry in `result["warnings"]` and
`ValidationResult.warnings`. The codes are on
[Messages](messages.md#warning-codes).

```{eval-rst}
.. autoclass:: powderline.exceptions.StructuredWarning
   :members:
   :undoc-members:
```

## Recipe helpers

Move a core block (`payload.xrd_data`, `payload.fit_range` or
`payload.phases.<name>`) from one recipe to another. This is how a series of
runs is chained ([Run a series](../how-to/sequential-refinement.md)).

```{eval-rst}
.. autofunction:: powderline.recipes.block

.. autofunction:: powderline.recipes.with_block
```
