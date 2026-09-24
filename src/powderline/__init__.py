"""PowderLine: Automated powder diffraction analysis using GSAS-II."""

__version__ = "0.1.1"

# The GSAS-II-backed public API is imported eagerly when GSAS-II is available,
# preserving the original behaviour exactly (including `powderline.kicker` being
# registered as a submodule attribute). When GSAS-II is absent -- on Windows, or
# on a TOPAS-only dev box -- these imports are skipped so that the GSAS-II-free
# TOPAS path (`powderline.topas`) still imports cleanly. `powderline.schema` is
# GSAS-II-free and always loaded, so `RecipeModel` is available either way.

# `run` is the GSAS-II-free engine dispatcher (engine="gsasii"|"topas"); it loads
# the GSAS-II backend lazily only for engine="gsasii", so it imports here without
# requiring GSAS-II. The remaining GSAS-II-backed helpers are imported eagerly
# when GSAS-II is available and skipped otherwise (the TOPAS path stays usable).
from powderline.engine import run

try:  # GSAS-II-backed helpers + client (require the GSAS-II package)
    from powderline.kicker import (
        validate,
        load_recipe_asset,
        validate_simulation_mode_parameters,
    )
    from powderline.gsas_client import GSASClient
except ImportError:  # pragma: no cover - exercised only where GSAS-II is absent
    pass

from powderline.schema import RecipeModel

__all__ = [
    "run",
    "validate",
    "load_recipe_asset",
    "validate_simulation_mode_parameters",
    "RecipeModel",
    "GSASClient",
]
