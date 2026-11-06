"""Every recipe shipped under examples/ validates engine-free, and the minimal recipe on
docs/engines/gsasii.md is a valid recipe (review items 30 and 10; the five per-engine recipes had no test)."""
import json
import re
from pathlib import Path

import pytest

import powderline

pytestmark = pytest.mark.core

REPO = Path(__file__).resolve().parent.parent
RECIPES = sorted(p for p in (REPO / "examples").glob("*/**/input.json") if "example_template" not in p.parts)


@pytest.mark.parametrize("recipe_path", RECIPES, ids=lambda p: str(p.relative_to(REPO / "examples")))
def test_shipped_recipe_validates_engine_free(recipe_path, tmp_path):
    recipe = powderline.load_recipe_asset(recipe_path)
    summary = powderline.run(recipe, tmp_path / "out", validate_only=True)
    assert summary["method"] == "validate_only"
    assert summary["schema_name"] == recipe["schema_name"]
    assert not (tmp_path / "out").exists()  # validate-only writes nothing (P-14)


def test_the_twenty_one_shipped_recipes_are_all_covered():
    """Guard against a new example dir without a recipe, or a recipe this test cannot see.

    11 gsasii examples (incl. the temperature series' first step, re/22, the ionic LaB6, re/28, and the textured
    LaB6, re/29) + 10 per-engine recipes (LaB6 and DRX_33 topas/easydiffraction, singlepeakfit topas, the
    temperature series', the ionic and the textured LaB6's easydiffraction and topas legs); the template's recipes
    are blanks and are excluded.
    """
    assert len(RECIPES) == 21, [str(p.relative_to(REPO)) for p in RECIPES]


def _getting_started_recipe() -> dict:
    text = (REPO / "docs" / "engines" / "gsasii.md").read_text(encoding="utf-8")
    block = re.search(r"A minimal `gsasii\.rietveld` recipe.*?```json\n(.*?)\n```", text, re.S)
    assert block, "docs/engines/gsasii.md: the minimal recipe code block was not found"
    return json.loads(block.group(1))


def test_getting_started_minimal_recipe_validates(tmp_path):
    recipe = _getting_started_recipe()
    summary = powderline.run(recipe, tmp_path / "out", validate_only=True)
    assert summary["schema_name"] == "gsasii.rietveld" and summary["phases"] == 1
