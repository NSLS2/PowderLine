"""
Example: validating a recipe and running it through its engine.

Demonstrates the main import patterns for consuming projects:
  1. Engine-free validation via powderline.validate()
  2. Programmatic refinement via powderline.run() (recommended entry point);
     the engine is the one the recipe's schema_name names
  3. Server-based GSAS-II refinement via GSASClient (preferred for repeated/batch runs)

REQUIREMENTS:
  - An environment with GSAS-II: PowderLine's ``gsasii`` environment
    (``pixi run -e gsasii python docs/integration/example_full.py``) or one
    built from docs/integration/pixi_full.toml
  - PowderLine editable-installed (pixi install handles this automatically)

POWDERLINE_REPO defaults to the clone this file sits in; edit it if you copied
the script elsewhere.
"""

import tempfile
from pathlib import Path

# ---------------------------------------------------------------------------
# Edit these paths for your setup
# ---------------------------------------------------------------------------

# Absolute path to your local PowderLine clone
POWDERLINE_REPO = Path(__file__).resolve().parents[2]

# Directory where output files (dummy.gpx, dummy.lst, *.csv, fit_profile.txt) will be written
OUTPUT_DIR = Path(tempfile.mkdtemp(prefix="powderline_example_"))

# Recipe to use -- any gsasii.* input.json from the PowderLine examples directory works here
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
# 1. Validation -- engine-free: GSAS-II is NOT imported at this point.
# ---------------------------------------------------------------------------

import powderline
from pydantic import ValidationError

recipe = powderline.load_recipe_asset(RECIPE_PATH)

try:
    checked = powderline.validate(recipe)
    model = checked.recipe
    print("Recipe validated successfully.")
    print(f"  Schema:   {model.schema_name}  (core {model.core_schema_version}, engine {model.engine_schema_version})")
    print(f"  Phases:   {list(model.payload.phases.keys())}")
    print(f"  Cycles:   {model.payload.refinement_controls.refinement_cycles}")
    for w in checked.warnings:
        print(f"  warning:  {w['code']} ({w['field_path']})")
except ValidationError as exc:
    print("Recipe validation failed:")
    for error in exc.errors():
        print(f"  {' -> '.join(str(loc) for loc in error['loc'])}: {error['msg']}")
    raise SystemExit(1)

# ---------------------------------------------------------------------------
# 2. Programmatic refinement (powderline.run)
#    Dispatches to the gateway the schema_name names (gsasii here), which
#    tries the GSAS-II server, auto-starts it if needed, and falls back to an
#    in-process run; returns all outputs as pandas DataFrames.
#    GSAS-II is imported here -- expect ~10 s on first call.
# ---------------------------------------------------------------------------

print(f"\nRunning refinement via powderline.run() (output -> {OUTPUT_DIR})")
try:
    result = powderline.run(recipe, OUTPUT_DIR)
except powderline.EngineNotAvailableError as exc:
    # the gateway is installed but its engine is not in this environment
    raise SystemExit(f"  {exc}")
except powderline.EngineExecutionError as exc:
    # the engine ran and failed: the reason code and the files kept for diagnosis (the engine's own
    # files and failure.json, which holds this envelope; no result table exists for a failed run)
    raise SystemExit(f"  Refinement failed ({exc.reason}): {exc}\n  kept: {exc.result['output_files']}")
except powderline.ExecutionBackendError as exc:
    raise SystemExit(f"  Could not run the engine ({exc.reason}): {exc}")

if result["status"] == "ok":
    print(f"  Refinement complete.  Rwp = {result['rwp']:.3f} %  (uniform statistic; "
          f"GSAS-II's own: {result['engine_details'].get('rwp'):.3f} %)")
    print(f"  Parameters requested/varied: {result['engine_details']['parameters_requested']}/"
          f"{result['engine_details']['parameters_varied']}")
    print(f"  Output files: {[Path(p).name for p in result['output_files']]}")
    for w in result["warnings"]:
        print(f"  warning:  {w['code']}")
# (a failed run never reaches here: it raised above)

# ---------------------------------------------------------------------------
# 3. Server-based refinement (GSASClient)
#    Best for: repeated or batch GSAS-II refinements where the engine's startup
#    cost matters. GSASClient keeps GSAS-II loaded in a background process.
#    The client auto-starts the server if it is not already running.
# ---------------------------------------------------------------------------

from powderline.gateways.gsasii.client import GSASClient

server_output_dir = OUTPUT_DIR / "server_run"
server_output_dir.mkdir(parents=True, exist_ok=True)

print(f"\nRunning server-based refinement (output -> {server_output_dir})")
client = GSASClient(fallback_to_subprocess=True)
server_result = client.submit_simulation(
    recipe=RECIPE_PATH,          # also accepts a dict or a validated gsasii model
    output_dir=server_output_dir,
    verbose=False,
    auto_start_server=True,
)

# GSASClient returns the envelope itself (ok or failed) and never raises for an application outcome:
if server_result["status"] == "ok":
    print(f"  Refinement complete.  method={server_result['method']}")
    print(f"  Output files: {[Path(p).name for p in server_result['output_files']]}")
else:
    failure = server_result["failure"]
    print(f"  Refinement failed ({failure['kind']}/{failure['reason']}): {failure['message']}")
