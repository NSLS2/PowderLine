"""Print the steps for checking a candidate engine version (docs/engine-versions.md).

Dry: runs no pixi command, edits nothing. It reads the gateway's current
ENGINE_VERSION_SPEC (an engine-free import) and the pin in pixi.toml, says
whether the candidate is already admitted, and prints the throwaway-env
instructions and the pytest command for that engine's suite.

Usage:
    pixi run python scripts/check_engine_version_candidate.py --engine gsasii --version 5.8.0 --rev <commit>
    pixi run python scripts/check_engine_version_candidate.py --engine easydiffraction --version 0.22.0
    pixi run python scripts/check_engine_version_candidate.py --engine topas --version 7
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from packaging.specifiers import SpecifierSet
from packaging.version import InvalidVersion, Version

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

ENGINES = {
    "gsasii": {
        "env": "gsasii",
        "task": "test-gsasii",
        "spec_file": "src/powderline/gateways/gsasii/gateway.py",
        "spec_name": "ENGINE_VERSION_SPEC",
        "pin": "pixi.toml [feature.gsasii.dependencies] GSAS-II = { git = ..., rev = <commit> }",
        "pin_pattern": r'GSAS-II = \{ git = "([^"]+)", rev = "([0-9a-f]+)" \}',
    },
    "easydiffraction": {
        "env": "easydiffraction",
        "task": "test-easydiffraction",
        "spec_file": "src/powderline/gateways/easydiffraction/gateway.py",
        "spec_name": "ENGINE_VERSION_SPEC",
        "pin": 'pixi.toml [feature.easydiffraction.pypi-dependencies] easydiffraction = "==x.y.z"',
        "pin_pattern": r'^easydiffraction = "(==[^"]+)"',
    },
    "topas": {
        "env": None,
        "task": "test-topas",
        "spec_file": "src/powderline/gateways/topas/schema.py",
        "spec_name": "SUPPORTED_ENGINE_VERSION_SPEC",
        "pin": "none: TOPAS is not installable; the recipe's engine_version and the installed version "
               "declared in .powderline_config.yaml (or --topas-version)",
        "pin_pattern": None,
    },
}


def current_spec(engine: str) -> str:
    info = ENGINES[engine]
    if engine == "topas":
        from powderline.gateways.topas import schema as module
    else:
        import importlib

        module = importlib.import_module(f"powderline.gateways.{engine}.gateway")
    return getattr(module, info["spec_name"])


def current_pin(engine: str) -> str | None:
    pattern = ENGINES[engine]["pin_pattern"]
    if pattern is None:
        return None
    text = (ROOT / "pixi.toml").read_text(encoding="utf-8")
    m = re.search(pattern, text, re.M)
    return m.group(0) if m else "(pin not found in pixi.toml -- check the manifest)"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--engine", required=True, choices=sorted(ENGINES))
    parser.add_argument("--version", required=True, help="candidate runtime version (e.g. 5.8.0, 0.22.0, 7)")
    parser.add_argument("--rev", help="GSAS-II only: the source commit of the candidate (pixi-build rev)")
    args = parser.parse_args(argv)

    info = ENGINES[args.engine]
    spec = SpecifierSet(current_spec(args.engine))
    try:
        candidate = Version(args.version)
    except InvalidVersion:
        parser.error(f"{args.version!r} is not a PEP 440 version")
    admitted = candidate in spec
    if args.engine == "gsasii" and not args.rev:
        parser.error("--rev <commit> is required for gsasii: the pin is the pixi-build source revision")

    report_name = f"engine-version-{args.engine}-{args.version}.md"
    scratch = f"scratch/{args.engine}-{args.version}"
    lines = [
        f"Engine: {args.engine}",
        f"Current spec: {info['spec_file']} {info['spec_name']} = \"{spec}\"",
        f"Current pin:  {current_pin(args.engine) or info['pin']}",
        f"Candidate:    {candidate}" + (f" (rev {args.rev})" if args.rev else ""),
        f"Already admitted by the spec: {'yes -- nothing to widen; still run step 2 if the pin moves' if admitted else 'no'}",
        "",
        "Procedure (docs/engine-versions.md; nothing below is executed by this script):",
        "",
        f"1. Throwaway worktree:  git worktree add ../pl-candidate -b {scratch}",
    ]
    if args.engine == "gsasii":
        lines += [
            f"   - pixi.toml: set rev = \"{args.rev}\" on the GSAS-II git dependency",
            f"   - {info['spec_file']}: {info['spec_name']} = \"{spec},=={candidate}\"  (or the widened range you intend)",
            "   - pixi lock && pixi install -e gsasii && pixi reinstall powderline",
            "   - note: gateway.py is not code-hashed; the frozen modules are (tests/test_code_hash.py)",
        ]
    elif args.engine == "easydiffraction":
        lines += [
            f"   - pixi.toml: easydiffraction = \"=={candidate}\"",
            f"   - {info['spec_file']}: {info['spec_name']} = \"=={candidate}\"  (test_gateways asserts pin inside spec)",
            "   - pixi lock && pixi install -e easydiffraction && pixi reinstall powderline",
            "   - regenerate the table: pixi run -e easydiffraction python scripts/generate_easydiffraction_space_groups.py",
            "   - re-verify the settings (about 1.5 h, at most 4 workers):",
            "       pixi run -e easydiffraction python scripts/verify_easydiffraction_settings.py --workers 4",
            "   - re-run the maintainers' engine-issue reproductions for easydiffraction (an upstream fix may retire a workaround)",
        ]
    else:
        lines += [
            f"   - {info['spec_file']}: add \"{candidate}\" to SUPPORTED_ENGINE_VERSIONS (the published "
            f"{info['spec_name']} is derived from it; several versions need a decision on its form)",
            f"   - .powderline_config.yaml on the TOPAS machine: topas.dir / topas.version = {candidate}",
            "   - the generation goldens (tests/data/topas/native/golden/<version>/, by the fixture's engine_version)",
            "     are TOPAS 6 output: a TOPAS 7 run needs a TOPAS 7 installation; TOPAS 7 support is a separate addition",
        ]
    env_flag = f"-e {info['env']} " if info["env"] else ""
    lines += [
        "",
        f"2. Run the suite incl. slow:  pixi run {env_flag}{info['task']}",
        f"   (equivalently: pixi run {env_flag}pytest -m \"{'topas_gen or topas_exec' if args.engine == 'topas' else args.engine}\")",
        "",
        "3. Record pass/fail and the numeric deltas of every regression case in a compatibility report:",
        f"   {report_name}",
        "",
        "4. Pass: one PR widening the spec + moving the pin + updating the support matrix; references unchanged.",
        "   Fail: record the behaviour change; decide schema bump vs stay pinned. The pin does not move before that.",
    ]
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
