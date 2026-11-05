"""PowderLine: automated powder diffraction refinement from a JSON recipe, on interchangeable engines.

The public API (v0.2.0, P-06) is the names in ``__all__``:

- :func:`run` -- run a recipe with the engine its ``schema_name`` names;
- :func:`validate` -- validate a recipe engine-free, returning a :class:`ValidationResult`;
- :func:`load_recipe_asset` -- read a recipe file (JSON / YAML) into a dict;
- :func:`support_matrix` -- the schema versions every installed gateway declares;
- the exceptions (:class:`PowderLineError` and its gateway subclasses; a failed run raises
  :class:`EngineExecutionError` or :class:`ExecutionBackendError`, each with ``.reason`` and ``.result``).

``import powderline`` imports no engine: GSAS-II, TOPAS and easydiffraction
are imported by their gateways, lazily, when a recipe runs. Engine-specific
helpers live under ``powderline.gateways.<engine>`` (e.g.
``powderline.gateways.gsasii.client.GSASClient``).
"""

__version__ = "0.2.0"

from powderline.api import run, validate, ValidationResult
from powderline.recipes import load_recipe_asset
from powderline.compat import support_matrix
from powderline.exceptions import (
    PowderLineError,
    GatewayNotInstalledError,
    EngineNotAvailableError,
    EngineVersionError,
    EngineExecutionError,
    ExecutionBackendError,
)

__all__ = [
    "run",
    "validate",
    "ValidationResult",
    "load_recipe_asset",
    "support_matrix",
    "PowderLineError",
    "GatewayNotInstalledError",
    "EngineNotAvailableError",
    "EngineVersionError",
    "EngineExecutionError",
    "ExecutionBackendError",
]
