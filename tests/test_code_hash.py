"""Test that the frozen GSAS-II gateway modules change only with a recorded hash update.

WHY THIS EXISTS:
    The GSAS-II setup/execution code (src/powderline/gateways/gsasii/
    helpers, project, setters, executors, extractors, constraints) is frozen
    for the multi-engine refactor (master plan invariant 1, A39): it moves
    verbatim, and every edit goes through the signed edits ledger. The hash
    manifest is the tripwire. The GSAS-II server also caches these modules in
    memory, so a change on disk needs a server restart (pixi run gsas-server
    restart).

WHEN THIS TEST FAILS:
    A hashed module was modified but _code_hash.json was not updated. Fix it:

    1. Record the edit (ledger row) if the module is frozen, or bump the
       engine_schema_version where the output behaviour changed.
    2. Run: pixi run update-code-hash
    3. Commit _code_hash.json alongside your changes.

    See docs/DEVELOPMENT.md 'Schema Version Discipline' for full details.
"""

import hashlib
import json
from pathlib import Path
import pytest

pytestmark = pytest.mark.core


SRC_DIR = Path(__file__).parent.parent / "src" / "powderline"
GATEWAY_DIR = SRC_DIR / "gateways" / "gsasii"
HASH_FILE = SRC_DIR / "_code_hash.json"

# Expected modules in the manifest (independent tripwire)
EXPECTED_MODULES = (
    "helpers.py",
    "project.py",
    "setters.py",
    "executors.py",
    "extractors.py",
    "constraints.py",
)


def test_gateway_manifest_covers_expected_modules():
    """Verify the manifest covers exactly the expected GSAS-II gateway modules."""
    assert HASH_FILE.exists(), f"_code_hash.json not found at {HASH_FILE}"

    stored = json.loads(HASH_FILE.read_text(encoding="utf-8"))
    manifest = stored.get("gsasii_gateway_hashes", {})

    assert set(manifest.keys()) == set(EXPECTED_MODULES), (
        f"\nManifest modules mismatch!\n"
        f"  Expected: {set(EXPECTED_MODULES)}\n"
        f"  Got:      {set(manifest.keys())}\n"
    )


@pytest.mark.parametrize("module_name", EXPECTED_MODULES)
def test_gateway_hashes_match(module_name):
    """Verify each GSAS-II gateway module hash matches the stored hash.

    If this test fails, it means a gateway module was modified without updating
    the code hash. To fix:

    1. Record the edit (ledger row), or bump the engine_schema_version where the
       output behaviour changed.
    2. Run: pixi run update-code-hash
    3. Commit the updated _code_hash.json along with your changes.
    """
    module_path = GATEWAY_DIR / module_name
    assert module_path.exists(), f"{module_name} not found at {module_path}"
    assert HASH_FILE.exists(), f"_code_hash.json not found at {HASH_FILE}"

    current_hash = hashlib.md5(module_path.read_bytes()).hexdigest()
    stored = json.loads(HASH_FILE.read_text(encoding="utf-8"))
    manifest = stored.get("gsasii_gateway_hashes", {})

    assert module_name in manifest, f"{module_name} not in manifest"
    stored_hash = manifest[module_name]

    assert current_hash == stored_hash, (
        f"\n{module_name} has changed but _code_hash.json was not updated!\n"
        f"  Stored hash:  {stored_hash}\n"
        f"  Current hash: {current_hash}\n\n"
        f"Record the edit in the frozen-edits ledger (or bump engine_schema_version).\n"
        f"Then run: pixi run update-code-hash\n"
        f"See docs/DEVELOPMENT.md 'Schema Version Discipline' for details."
    )
