"""GSAS-II gateway — route a validated recipe to its executor (re/04, A39).

A ``gsasii.rietveld`` / ``gsasii.spf`` model runs through
``executors.run_refinement``, which consumes the model directly. The gateway's
``run`` (``execution_mode='subprocess'``), the GSAS-II server and the client's
in-process fallback all call this function. GSAS-II is imported when it runs,
not here.
"""

from __future__ import annotations

from pathlib import Path

from powderline.gateways.gsasii.schema import validate_recipe


def run_refinement(recipe, output_dir: Path, verbose: bool = False, method: str = 'server') -> dict:
    """Run a validated recipe in this process; see ``executors.run_refinement`` for the result dict."""
    from powderline.gateways.gsasii.executors import run_refinement as run
    return run(recipe, output_dir, verbose=verbose, method=method)


def model_from_request(recipe_dict: dict):
    """The validated model for a recipe dict received by the server or the in-process fallback.

    Raises pydantic's ``ValidationError`` (an unknown ``schema_name`` is
    reported at ``schema_name``).
    """
    return validate_recipe(recipe_dict)
