"""Engine-free factory for the easydiffraction gateway (entry point
``powderline.gateways:easydiffraction``).

- **Schema layer** — ``validate`` / ``capabilities``: an
  ``easydiffraction.rietveld`` recipe validates against the native schema
  (:mod:`.schema`, re/06); any other ``schema_name`` is a validation error at
  ``schema_name``. No easydiffraction import.
- **Runtime layer** — ``run``: :func:`.native_run.run_native`. On a real run
  it first reads the installed easydiffraction version: missing ⇒
  ``EngineNotAvailableError``; outside ``ENGINE_VERSION_SPEC`` ⇒
  ``EngineVersionError``.
"""

from __future__ import annotations

from powderline.exceptions import EngineNotAvailableError
from powderline.gateways.easydiffraction import schema
from powderline.registry import Gateway, check_engine_version

NAME = "easydiffraction"
#: Supported easydiffraction versions (A41/A44); mirrors the pixi pin.
ENGINE_VERSION_SPEC = "==0.21.1"
#: Workflows served (the native schema; no SPF, A13.3).
WORKFLOWS = tuple(schema.SCHEMA_NAMES)
#: pixi environment providing easydiffraction + how to install it (re/08, A42).
ENV = "easydiffraction"
INSTALL_COMMAND = "pixi install -e easydiffraction"


def capabilities() -> dict:
    return {"name": NAME, "workflows": WORKFLOWS, "engine_version_spec": ENGINE_VERSION_SPEC, **schema.DECLARATIONS}


def validate(recipe, *, verbose: bool = False):
    """Validate a recipe (dict or model); return the validated model (A50, A59).

    An ``easydiffraction.rietveld`` recipe gives its native model
    (``EasydiffractionRietveldRecipe``). ``verbose`` is part of the uniform
    gateway contract; this gateway prints nothing extra.
    """
    return schema.validate_recipe(recipe)


def installed_engine_version() -> str:
    """The installed easydiffraction version (distribution == runtime there)."""
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("easydiffraction")
    except PackageNotFoundError as exc:
        raise EngineNotAvailableError(gateway=NAME, dependency="easydiffraction", env=ENV,
                                      install_command=INSTALL_COMMAND) from exc


def run(recipe, output_dir, *, verbose: bool = False, validate_only: bool = False,
        allow_unsupported_engine_version: bool = False) -> dict:
    """Run a recipe; see :func:`.native_run.run_native` for the result dict.

    ``allow_unsupported_engine_version`` is the test-only bypass of the engine
    version check; the check is skipped for ``validate_only``.
    """
    from powderline.gateways.easydiffraction import native_run

    model = schema.validate_recipe(recipe)  # the model validated from the user's recipe (A115)
    if validate_only:
        return native_run.run_native_validate(model)
    check_engine_version(gateway=NAME, engine="easydiffraction", installed=installed_engine_version(),
                         spec=ENGINE_VERSION_SPEC, allow_unsupported=allow_unsupported_engine_version)
    return native_run.run_native(model, output_dir)


def get_gateway() -> Gateway:
    return Gateway(name=NAME, capabilities=capabilities, validate=validate, run=run)
