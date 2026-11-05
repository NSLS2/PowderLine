# Add an engine or a capability

**Goal:** add a refinement engine behind a new gateway, or teach an existing
gateway a new recipe field.

**You need:** a development setup ([Contributing](contributing.md)), the
engine installed somewhere you can run it, and the layout in
[Architecture](architecture.md).

## The gateway contract

A gateway is a package that `powderline.registry` finds through the
`powderline.gateways` entry-point group. Its factory returns a frozen
`registry.Gateway`:

```python
from powderline.registry import Gateway

def get_gateway() -> Gateway:
    return Gateway(name="myengine", capabilities=capabilities, validate=validate, run=run)
```

| Member | Contract |
|---|---|
| `name` | The registry name, which is also the `schema_name` prefix (`myengine.rietveld`) |
| `capabilities()` | A dict with at least `name`, `workflows` (the schema names), `engine_version_spec` (a PEP 440 specifier) and the schema `DECLARATIONS` |
| `validate(recipe, *, verbose=False)` | Schema layer only. Takes a dict or a validated model and returns the validated model. Exactly these keywords |
| `run(recipe, output_dir, *, verbose=False, validate_only=False, allow_unsupported_engine_version=False, **own_options)` | Runtime layer. Validates, checks the engine version, imports the engine lazily, runs it, and returns the standardized result dict |

The schema layer must import no engine. `powderline.validate()` runs it in
the default environment, where no engine is installed.

An in-repo gateway lives in `src/powderline/gateways/<engine>/`. An
out-of-tree gateway is a separate distribution that declares the same entry
point. For tests and development, `registry.register_gateway(name, factory)`
registers a gateway in code without an entry point.

## Add an engine

1. **Write the schema module** (`schema.py`, engine-free).
   - Subclass core's phase block in the engine's parameter shape:
     `class MyPhase(Phase[BoundedRefinableParameter])`, or
     `Phase[RefinableParameter]` if the engine has no usable bounds. Add the
     engine's phase fields with their own validator names and `'after'`
     validators only.
   - Model the instrument, background and controls in the **engine's own
     terms and units**. Every quantity carries
     `json_schema_extra={"unit": ...}`, which the field tables read. Keep
     `extra='forbid'`. A block that may be left out is left out, never
     `null`.
   - Add no default that silently replaces an engine behaviour. Either the
     value is required, or the default is documented and reported with a
     structured warning.
   - Write the recipe models as subclasses of `schema_core.EngineRecipe`,
     with `schema_name` narrowed to a `Literal` and two class variables:
     `gateway_name` and `schema_declarations = DECLARATIONS`.
   - Declare the versions exactly:

     ```python
     DECLARATIONS = compat.schema_declarations(
         engine_schema_version="0.1.0",
         supported_engine_schemas="==0.1.0",
         requires_core_schema="==0.1.0",
     )
     ```

     `EngineRecipe` runs the check. A declaration is widened explicitly
     later, never written as a range ([Policies](policies.md#versioning)).
   - Export `SCHEMA_NAMES` and
     `validate_recipe = schema_core.recipe_validator({<schema_name>: <model>, ...}, engine="<engine>", title="<Engine>Recipe")`.
     It accepts a dict or a validated model and reports an unknown
     `schema_name` at `schema_name`.
2. **Write every engine rule as a validator.** Refuse what the engine cannot
   express, and what it would silently alter (a floor, a limit, a snapped
   value), naming the value to write. Use core's building blocks rather than
   copies:
   - `absent_not_null` and `omit_absent` for blocks that may be left out;
   - `unique_phase_names`, `fit_window`, `fit_limits_on_data`,
     `fit_range_problems`, `outside_window_problems` and
     `refined_flag_problems` for the payload rules;
   - `refined_flags`, `custom_error` and `raise_problems` to report every
     problem at once.
3. **Register every warning code** the engine emits in
   `powderline.exceptions.WARNING_CODES` (owner, level), and add its row to
   the warnings table in `docs/reference/messages.md`.
   `tests/test_warning_codes.py` holds the registry, the code and the table in
   agreement.
4. **Write the gateway module** (`gateway.py`) with `get_gateway()`,
   `capabilities()`, `validate()`, `run()` and `ENGINE_VERSION_SPEC`. If the
   engine is a pixi dependency, add `ENV` and `INSTALL_COMMAND`. In `run()`:
   - With `validate_only=True`, return `registry.validate_only_summary(...)`
     and skip the engine version check.
   - Otherwise call `registry.check_engine_version(...)`. Raise
     `EngineNotAvailableError` with `env` and `install_command` when the
     engine is missing.
   - Define `installed_engine_version()` in the module that defines `run`.
     `powderline.run()` calls it to check that the engine is importable
     before it touches the output directory.
   - Import the engine lazily, inside `run()`.
5. **Return the standard result.** Use the same keys and types as the other
   gateways (see [Outputs](../reference/outputs.md)).
   - Compute the statistics with `powderline.fitstats` over the window's
     weighted points, with P read from the engine after the run. Put the
     engine's own values under `engine_details`, with `parameters_requested`
     and `parameters_varied`.
   - Hand `powderline.roundtrip` the refined values by recipe path
     (`{path: (value, esd)}` in recipe units), plus the flagged paths the
     engine did not vary and those that ended at a limit.
     `roundtrip.build_output` and `roundtrip.attach` build the output recipe,
     the dispositions and their files.
   - Write the report files with `powderline.reports`. Keep the engine's
     native files.
6. **Never return a failed result.** Raise `EngineExecutionError` when the
   engine ran and failed, or `ExecutionBackendError` when it did not run,
   with a `reason` from `powderline.results.REASONS`. A non-finite
   calculated pattern is a failure (`diverged`). `results.raise_if_failed`
   raises on a failed envelope you received.
7. **Declare the entry point** in `pyproject.toml`, then run
   `pixi reinstall powderline --all`:

   ```toml
   [project.entry-points."powderline.gateways"]
   myengine = "powderline.gateways.myengine.gateway:get_gateway"
   ```

8. **Add a pixi feature and environment** for the engine's dependencies, so
   the default environment stays engine-free. Pin the engine exactly and keep
   the pin inside `ENGINE_VERSION_SPEC`. Put the engine's test task in its
   feature.

**Check:** `pixi run powderline <recipe.json> --validate-only` works in the
default environment, `pixi run powderline --doctor` lists the gateway, and a
run in the engine's environment returns `status` `ok`.

## Tests to write

Follow the pattern of the existing gateways. Mark each test with exactly one
suite marker; tests that need the engine get the engine's marker, so
`pixi run test` stays green without it.

- **Schema tests** (`tests/test_<engine>_schema.py`): every rule and every
  refusal, with the error path.
- **Phase canary:** add the engine's phase model to `ENGINE_PHASES` in
  `tests/test_phase_canary.py`. It runs core's must-fail recipes through it.
- **Import block:** prove that the schema layer and `import powderline` load
  no engine module.
- **Space groups:** compare every setting the engine accepts with gemmi
  (orbits or operators).
- **Fixtures and goldens:** hand-derived native recipes with a README of the
  derivations, and the engine's output recorded with its version, under
  `tests/data/<engine>/native/`.
- **Result contract:** the same keys and types as the other engines.
- **Pins:** `tests/test_gateways.py` checks that the pixi pin lies inside
  `ENGINE_VERSION_SPEC`.

The goldens are the references. A change in what the engine is asked to do
(the input file, the project, the input dictionary) is proved against them.

## Docs to update

- Add the recipe models to `_recipe_models()` in
  `scripts/gen_schema_field_tables.py` and regenerate the field tables. Add a
  section for the new tables to [Fields](../reference/fields.md). The support
  matrix regenerates itself.
- Write the engine page under `docs/engines/` and add a column to the
  feature table on [Engines](../engines/index.md).
- Add a catalogue entry in `docs/catalog/engine_behaviour.yaml` for every
  engine behaviour a user can meet, with PowderLine's policy. Regenerate with
  `scripts/gen_catalog.py`. Anything the engine does silently is written up
  before the gateway ships.
- Add the engine schema's entry to [Versions](../reference/versions.md) and a
  CHANGELOG bullet.

## Add a capability to an existing engine

The same discipline, smaller.

1. **Find the ground truth.** Read and run the engine to see what it does with
   the quantity. If the engine's behaviour is unknown, ask the maintainers
   rather than infer it.
2. **Add the field** to the engine's `schema.py`, with its unit, validators
   and refusals. A structural quantity shared by every engine goes into
   `schema_core` as a building block, and each engine's phase model adds it
   in its own parameter shape. March–Dollase preferred orientation is built
   this way (`schema_core.MarchDollase`).
3. **Consume it in the runtime layer** from the validated model. For gsasii,
   put the read in a non-frozen module. A read inside a frozen module is a
   behaviour change and needs the maintainers' consent
   ([Policies](policies.md#frozen-gsas-ii-code)). Map the refined parameter
   back to its recipe path (gsasii `paths.py`) so it reaches the output
   recipe.
4. **Prove it.** Add a fixture and a golden that show the value reaches the
   engine and does what the recipe says. Prefer a formula check on a
   simulated pattern as the gate, and an example as the demonstration.
5. **Add an example** if it is a real case: `examples/<case>/` with its
   `DESCRIPTION.md` and, for gsasii, the committed output.
6. **Record it.** Regenerate the field tables, add catalogue entries for
   anything the engine does silently, and update
   [Versions](../reference/versions.md) and the CHANGELOG.

If the new field changes what an existing recipe means, it is a deliberate
change: a schema version bump, a CHANGELOG entry, and a note for users
([Policies](policies.md#deliberate-behaviour-changes)).
