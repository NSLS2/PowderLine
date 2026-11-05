"""The simulation recipe builder, end to end through GSAS-II (re/09 split from test_simulation_builder).

Build the recipe from the synthetic structure, validate it,
run the simulation in-process and check the outputs. Needs GSAS-II: ``gsasii`` + ``slow``.
"""

import pytest

pytestmark = [pytest.mark.gsasii, pytest.mark.slow]

pytest.importorskip("GSASII.GSASIIscriptable")

import powderline  # noqa: E402
from powderline.gateways.gsasii.simulation_builder import SimulationRecipeBuilder  # noqa: E402
from test_simulation_builder import _validate  # noqa: E402


def test_builder_pipeline_end_to_end(lab6_structure_data, tmp_output_dir):
    """Full stack: build recipe → validate → run simulation → check outputs.

    Uses subprocess execution mode to bypass the server requirement.
    Requires GSAS-II to be installed (part of the standard pixi environment).
    """
    recipe = SimulationRecipeBuilder().build_recipe_from_structure(lab6_structure_data)
    model = _validate(recipe).recipe

    result = powderline.run(model, output_dir=tmp_output_dir, execution_mode="subprocess")

    assert result["status"] == "ok", result.get("failure")
    assert result["simulation_mode"] is True  # A129
    assert result["engine_details"]["parameters_varied"] == 0
    assert (tmp_output_dir / "fit_profile.txt").exists(), (
        "fit_profile.txt not found — simulation did not complete successfully"
    )
    assert (tmp_output_dir / "LaB6_peak_list_report.csv").exists()
