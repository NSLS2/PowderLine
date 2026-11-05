"""
Example: validating PowderLine recipes without any refinement engine.

Demonstrates ``powderline.validate()``: it dispatches on the recipe's
``schema_name`` to the gateway's engine-free schema layer, so it runs in the
core-only default environment for every schema (``gsasii.*``, ``topas.*``,
``easydiffraction.*``) and imports no engine.

Typical use cases:
  - Recipe builder / editor tools that construct input.json files
  - Pre-flight validation before submitting a refinement job
  - CI checks that recipe files conform to the schemas

REQUIREMENTS:
  - Environment built from docs/integration/pixi_schema_only.toml (or
    PowderLine's own default environment: ``pixi run python docs/integration/example_schema_only.py``)
  - PowderLine editable-installed (pixi install handles this automatically)

POWDERLINE_REPO defaults to the clone this file sits in; edit it if you copied
the script elsewhere.
"""

import json
from pathlib import Path

from pydantic import ValidationError

# ---------------------------------------------------------------------------
# Edit this path if you copied the script out of the PowderLine clone
# ---------------------------------------------------------------------------

# Absolute path to your local PowderLine clone (used only to locate example files)
POWDERLINE_REPO = Path(__file__).resolve().parents[2]

RECIPE_PATH = POWDERLINE_REPO / "examples" / "example_LaB6" / "input.json"

# ---------------------------------------------------------------------------
# Fail-fast: verify paths before doing any imports or real work.
# ---------------------------------------------------------------------------

if not POWDERLINE_REPO.is_dir():
    raise SystemExit(
        f"POWDERLINE_REPO does not exist: {POWDERLINE_REPO}\n"
        f"Edit the POWDERLINE_REPO constant at the top of this script."
    )
if not RECIPE_PATH.is_file():
    raise SystemExit(
        f"Recipe file not found: {RECIPE_PATH}\n"
        f"Check that POWDERLINE_REPO points to a valid PowderLine clone "
        f"containing examples/example_LaB6/input.json."
    )

# ---------------------------------------------------------------------------
# Schema validation -- ``import powderline`` imports no engine.
# ---------------------------------------------------------------------------

import powderline
from powderline import ValidationResult


def validate_recipe(path: Path) -> ValidationResult | None:
    """Load and validate a PowderLine recipe. Returns the ValidationResult or None on failure."""
    try:
        recipe_dict = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Failed to read {path}: {exc}")
        return None

    try:
        return powderline.validate(recipe_dict)
    except ValidationError as exc:
        print(f"Validation errors in {path}:")
        for error in exc.errors():
            location = " -> ".join(str(loc) for loc in error["loc"])
            print(f"  [{error['type']}] {location}: {error['msg']}")
        return None
    except powderline.GatewayNotInstalledError as exc:
        # the schema_name's engine prefix names no installed gateway
        print(f"No gateway for {path}: {exc}")
        return None


# ---------------------------------------------------------------------------
# Example: validate a single recipe and inspect the result
# ---------------------------------------------------------------------------

checked = validate_recipe(RECIPE_PATH)

if checked is not None:
    model = checked.recipe  # the gateway's validated model (here GsasiiRietveldRecipe)
    print(f"Valid recipe: {RECIPE_PATH.name}")
    print(f"  Schema:   {model.schema_name}  core {model.core_schema_version}, engine {model.engine_schema_version}")
    print(f"  Phases:   {list(model.payload.phases.keys())}")
    print(f"  Cycles:   {model.payload.refinement_controls.refinement_cycles}")

    # Every payload field is a typed pydantic model
    wl = model.payload.instrument.radiation.wavelength
    print(f"  Wavelength: {wl.value} Å  (refine={wl.refine_flag})")

    # Structured warnings: what the recipe left out and PowderLine applied a documented default for
    for w in checked.warnings:
        print(f"  warning {w['code']} at {w['field_path']}")

# ---------------------------------------------------------------------------
# Example: batch-validate every committed recipe, for every engine
# ---------------------------------------------------------------------------

examples_dir = POWDERLINE_REPO / "examples"
recipe_files = sorted(p for p in examples_dir.glob("*/**/input.json") if "template" not in str(p))

print(f"\nBatch validating {len(recipe_files)} example recipes:")
passed, failed = 0, 0
for recipe_path in recipe_files:
    result = validate_recipe(recipe_path)
    status = "OK" if result is not None else "FAIL"
    name = recipe_path.relative_to(examples_dir).parent
    schema = result.recipe.schema_name if result is not None else "-"
    print(f"  [{status}] {name}  ({schema})")
    if result is not None:
        passed += 1
    else:
        failed += 1

print(f"\n{passed} passed, {failed} failed.")
