"""Regenerate _code_hash.json after editing GSAS-II gateway modules.

Usage: pixi run update-code-hash
"""

import hashlib
import json
from pathlib import Path
import sys

SRC_DIR = Path(__file__).parent.parent / "src" / "powderline"
GATEWAY_DIR = SRC_DIR / "gateways" / "gsasii"
HASH_FILE = SRC_DIR / "_code_hash.json"

HASHED_MODULES = (
    "helpers.py",
    "project.py",
    "setters.py",
    "executors.py",
    "extractors.py",
    "constraints.py",
)


def main():
    current = json.loads(HASH_FILE.read_text(encoding="utf-8"))

    # Compute new hashes
    new_hashes = {}
    for module_name in HASHED_MODULES:
        module_path = GATEWAY_DIR / module_name
        if not module_path.exists():
            print(f"ERROR: Expected module not found: {module_path}", file=sys.stderr)
            sys.exit(1)
        new_hashes[module_name] = hashlib.md5(module_path.read_bytes()).hexdigest()

    # Compare against stored manifest
    old_manifest = current.get("gsasii_gateway_hashes", {})
    changed = []
    unchanged = []

    for module_name in HASHED_MODULES:
        old_hash = old_manifest.get(module_name)
        new_hash = new_hashes[module_name]
        if old_hash == new_hash:
            unchanged.append(f"{module_name}: {new_hash}")
        else:
            changed.append(f"{module_name}: {old_hash} -> {new_hash}")

    stale = sorted(set(current) - {"gsasii_gateway_hashes"}) + sorted(set(old_manifest) - set(HASHED_MODULES))
    if not changed and not stale:
        print("All hashes unchanged:")
        for line in unchanged:
            print(f"  {line}")
        return

    # Write updated manifest
    manifest = {"gsasii_gateway_hashes": new_hashes}
    HASH_FILE.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")

    print("Updated _code_hash.json:")
    for line in changed:
        print(f"  {line}")
    for key in stale:
        print(f"  {key}: removed (no longer in the manifest)")
    if unchanged:
        print("Unchanged:")
        for line in unchanged:
            print(f"  {line}")


if __name__ == "__main__":
    main()
