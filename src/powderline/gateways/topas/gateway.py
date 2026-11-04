"""Engine-free factory for the TOPAS gateway (entry point ``powderline.gateways:topas``).

- **Schema layer** — ``validate`` / ``capabilities``: a ``topas.rietveld`` /
  ``topas.spf`` recipe validates against the native schemas (:mod:`.schema`,
  re/05); any other ``schema_name`` is a validation error at ``schema_name``.
- **Runtime layer** — ``run``: :func:`.native_run.run_native`.

TOPAS has no Python engine dependency, so ``EngineNotAvailableError`` never
applies: without ``tc.exe`` a run is generate-only. TOPAS also has no
queryable runtime version (``tc.exe`` carries no version metadata and prints
its banner only to its console window; devkit ``re05-topas6-compat.md`` C29),
so version checks use the **declared** version (``topas_version`` argument,
else ``.powderline_config.yaml`` ``topas.version``): a run that will execute
TOPAS needs a declared version, equal to the recipe's ``engine_version`` and
within ``supported_engine_versions`` (A144, A145); a missing declaration is an
error.
"""

from __future__ import annotations

from packaging.version import Version

from powderline.exceptions import EngineVersionError
from powderline.gateways.topas import schema
from powderline.registry import Gateway, check_engine_version

NAME = "topas"
#: The TOPAS versions the native recipes are written for (A143, A144): the
#: same declaration the schema makes (``supported_engine_versions``).
ENGINE_VERSION_SPEC = schema.SUPPORTED_ENGINE_VERSIONS
#: Workflows served (the native schemas).
WORKFLOWS = tuple(schema.SCHEMA_NAMES)


def capabilities() -> dict:
    return {"name": NAME, "workflows": WORKFLOWS, "engine_version_spec": ENGINE_VERSION_SPEC,
            **schema.DECLARATIONS}


def validate(recipe, *, verbose: bool = False):
    """Validate a recipe (dict or model); return the validated model (A50, A59).

    A ``topas.*`` recipe gives its native model (``TopasRietveldRecipe`` /
    ``TopasSpfRecipe``). ``verbose`` is part of the uniform gateway contract;
    this gateway prints nothing extra.
    """
    return schema.validate_recipe(recipe)


def configured_engine_version(topas_version=None):
    """The configured TOPAS version, or ``None`` when none is configured."""
    if topas_version is not None:
        return topas_version
    from powderline.gateways.topas.runner import _read_topas_config

    return _read_topas_config().get("version")


def check_native_engine_version(model, topas_version=None, *, allow_unsupported: bool = False) -> None:
    """A145: the declared installed TOPAS version must exist and equal the recipe's ``engine_version``."""
    if allow_unsupported:
        return
    declared = configured_engine_version(topas_version)
    supported = schema.SUPPORTED_ENGINE_VERSIONS
    if declared is None:
        raise EngineVersionError(
            gateway=NAME, engine="TOPAS", installed="undeclared", supported=supported,
            message=(f"the TOPAS version to run is not declared: PowderLine cannot read it from tc.exe, so set "
                     f"topas_version (run argument) or topas.version in .powderline_config.yaml; this recipe is "
                     f"written for TOPAS {model.engine_version}"))
    check_engine_version(gateway=NAME, engine="TOPAS", installed=declared, spec=supported)
    if Version(str(declared)) != Version(model.engine_version):
        raise EngineVersionError(
            gateway=NAME, engine="TOPAS", installed=str(declared), supported=f"=={model.engine_version}",
            message=(f"the recipe is written for TOPAS {model.engine_version} (engine_version), but TOPAS "
                     f"{declared} is declared as installed"))


def run(recipe, output_dir, *, verbose: bool = False, validate_only: bool = False,
        topas_dir=None, topas_version=None, topas_timeout=None,
        allow_unsupported_engine_version: bool = False) -> dict:
    """Run a recipe; see :func:`.native_run.run_native` for the result dict.

    ``topas_dir`` / ``topas_version``: the TOPAS installation and its version
    (else ``topas.dir`` / ``topas.version`` in ``.powderline_config.yaml``).
    ``topas_timeout``: the limit on each tc.exe run in seconds (else
    ``topas.timeout``, else 3600; 0 = no limit); past it the run fails with
    ``ExecutionBackendError`` ``timeout``.

    ``allow_unsupported_engine_version`` is the test-only bypass of the engine
    version check (A53); the check is skipped for ``validate_only`` and when
    no ``tc.exe`` is found (generate-only).
    """
    from powderline.gateways.topas import native_run

    from powderline.gateways.topas.runner import configured_timeout

    model = schema.validate_recipe(recipe)  # the model validated from the user's recipe (A115)
    if validate_only:
        return native_run.run_native_validate(model)
    timeout = configured_timeout(topas_timeout)  # a bad value is refused before anything is written
    return native_run.run_native(
        model, output_dir, topas_dir=topas_dir, topas_version=topas_version, timeout=timeout,
        engine_version_check=lambda _tc: check_native_engine_version(
            model, topas_version, allow_unsupported=allow_unsupported_engine_version))


def get_gateway() -> Gateway:
    return Gateway(name=NAME, capabilities=capabilities, validate=validate, run=run)
