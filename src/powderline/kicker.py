"""PowderLine command line: run or validate a recipe with the engine its ``schema_name`` names.

::

    powderline <recipe.json> [--output DIR] [--validate-only] [--verbose]
                             [--use-server | --no-server] [--server-timeout SECONDS]
                             [--topas-dir DIR] [--topas-version V] [--topas-timeout SECONDS]
    powderline --doctor      (what this environment can do: gateways, engines, server; re/27)

(``pixi run powderline ...``, the pixi task ``pixi run kicker ...`` and ``python src/powderline/kicker.py ...`` run the same
``main``; re/08 binds the task names.) The CLI loads the recipe
(:func:`powderline.load_recipe_asset`), refuses template files, maps the
engine flags onto the gateway's run options and calls :func:`powderline.run`;
the engine is the one named by the recipe's ``schema_name``, so the same
command serves ``gsasii.*``, ``topas.*`` and ``easydiffraction.*`` recipes.
An engine flag given for a recipe of another engine is an error. Exit status 0 for an ``ok`` or
``generated`` outcome, 1 otherwise (a failed run is raised by the gateway and reported by reason).

Engine-free: this module imports no engine; GSAS-II is imported by the gsasii
gateway when a gsasii recipe runs.

"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from powderline import api
from powderline._status import CHECK, CROSS, INFO, WARN, emoji
from powderline.api import run
from powderline.exceptions import EngineExecutionError, ExecutionBackendError, PowderLineError
from powderline.recipes import load_recipe_asset

#: CLI flag (argparse dest) -> the gateway it belongs to; any other recipe rejects it.
_FLAG_GATEWAYS = {
    "use_server": "gsasii",
    "no_server": "gsasii",
    "server_timeout": "gsasii",
    "topas_dir": "topas",
    "topas_version": "topas",
    "topas_timeout": "topas",
}
_FLAG_NAMES = {"use_server": "--use-server", "no_server": "--no-server", "server_timeout": "--server-timeout",
               "topas_dir": "--topas-dir", "topas_version": "--topas-version", "topas_timeout": "--topas-timeout"}


def is_template_file(recipe_dict: dict, input_path: Path) -> tuple[bool, str | None]:
    """Detect a recipe file that is a template and must not be run directly (CLI-only guard).

    Two-level detection:

    1. the path contains "template" (case-insensitive);
    2. the payload is missing, or lacks the fields the workflow needs: a
       ``*.rietveld`` recipe needs ``xrd_data``, ``instrument``, ``phases`` and
       ``refinement_controls``; a ``*.spf`` one ``single_peaks`` instead of
       ``phases``; any other schema name is a template only when all of
       ``xrd_data``, ``instrument`` and ``refinement_controls`` are absent.

    Returns:
        ``(is_template, reason)``; ``(False, None)`` for a runnable recipe.

    Examples:
        >>> is_template_file({}, Path("example_template/input.json"))
        (True, "filename or path contains 'template'")
        >>> is_template_file({"schema_name": "gsasii.rietveld", "payload": {"xrd_data": {...}, ...}}, Path("in.json"))
        (False, None)
    """
    if "template" in str(input_path).lower():
        return True, "filename or path contains 'template'"

    payload = recipe_dict.get('payload', {}) if isinstance(recipe_dict, dict) else {}
    if not payload:
        return True, "missing payload"

    schema_name = recipe_dict.get('schema_name')
    workflow = None
    if isinstance(schema_name, str):
        if schema_name.endswith('.rietveld'):
            workflow = ('rietveld', ['xrd_data', 'instrument', 'phases', 'refinement_controls'])
        elif schema_name.endswith('.spf'):
            workflow = ('single-peak-fitting', ['xrd_data', 'instrument', 'single_peaks', 'refinement_controls'])
    if workflow is not None:
        label, required_fields = workflow
        missing = [field for field in required_fields if field not in payload or payload[field] is None]
        if missing:
            return True, f"{schema_name} ({label}) schema missing required fields: {missing}"
    else:
        core_fields = ['xrd_data', 'instrument', 'refinement_controls']
        missing_core = [field for field in core_fields if field not in payload]
        if len(missing_core) == len(core_fields):
            return True, "missing all required fields in payload (xrd_data, instrument, refinement_controls)"

    return False, None


def engine_options_from_args(args: argparse.Namespace, gateway_name: str) -> dict:
    """Map the engine flags onto the gateway's ``run`` options; refuse a flag for another engine.

    ``--no-server`` / ``--use-server`` → gsasii ``execution_mode`` (``'subprocess'``
    / ``'server'``; neither → the gateway's default, ``'auto'``);
    ``--server-timeout`` → gsasii ``server_timeout``;
    ``--topas-dir`` / ``--topas-version`` / ``--topas-timeout`` → topas ``topas_dir`` /
    ``topas_version`` / ``topas_timeout``.

    Raises:
        ValueError: a flag that belongs to a gateway other than ``gateway_name``;
            ``--use-server`` while ``POWDERLINE_NO_SERVER`` disables the server.
    """
    given = {dest: getattr(args, dest, None) for dest in _FLAG_GATEWAYS}
    for dest, value in given.items():
        if value is not None and value is not False and _FLAG_GATEWAYS[dest] != gateway_name:  # 0 is given
            raise ValueError(
                f"{_FLAG_NAMES[dest]} applies to {_FLAG_GATEWAYS[dest]!r} recipes only; this recipe's "
                f"schema_name names the {gateway_name!r} engine")
    options: dict[str, Any] = {}
    if given["no_server"]:
        options["execution_mode"] = "subprocess"
    elif given["use_server"]:
        # POWDERLINE_NO_SERVER (v0.1.2): an explicit server request is refused up front, before any
        # engine is touched. The server module is engine-free (stdlib + pydantic); imported here, not
        # at module top, so the CLI module itself imports no gateway module.
        from powderline.gateways.gsasii.server import NO_SERVER_MESSAGE, server_disabled
        if server_disabled():
            raise ValueError(f"--use-server: {NO_SERVER_MESSAGE}")
        options["execution_mode"] = "server"
    if given["server_timeout"] is not None:
        options["server_timeout"] = given["server_timeout"]
    if given["topas_dir"] is not None:
        options["topas_dir"] = given["topas_dir"]
    if given["topas_version"] is not None:
        options["topas_version"] = given["topas_version"]
    if given["topas_timeout"] is not None:
        options["topas_timeout"] = given["topas_timeout"]
    return options


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="powderline",
        description="Run (or validate) a PowderLine recipe with the engine its schema_name names",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Engine flags (accepted only for a recipe of that engine):
  gsasii.*  default:      try the GSAS-II server, auto-start it, fall back to in-process
            --use-server: server only (fail if it cannot be started)
            --no-server:  in-process only (skip the server)
            POWDERLINE_NO_SERVER=1 (env): never use a server; the default mode runs in-process
            --server-timeout SECONDS: stop waiting for the server's answer after this long
            (default: no limit, as in-process; the job itself keeps running on the server)
  topas.*   --topas-dir DIR / --topas-version V: the TOPAS installation to run
            (a run needs a declared version: --topas-version or .powderline_config.yaml)
            --topas-timeout SECONDS: stop tc.exe after this long (default 3600; 0 = no limit)

Examples:
  powderline examples/example_LaB6/input.json                     # engine from schema_name
  powderline examples/example_LaB6/input.json --no-server --verbose
  powderline recipe.json --validate-only                          # no engine needed
  powderline topas_recipe.json --topas-version 6 --output out/
  powderline --doctor                                              # what this environment can do
        """
    )
    parser.add_argument("input_json", type=Path, nargs="?", help="Path to the recipe file (.json / .yaml)")
    parser.add_argument("--doctor", action="store_true",
                        help="report what this environment can do (gateways, engines and versions, the GSAS-II "
                             "server) and exit non-zero on a problem; no recipe needed")
    parser.add_argument("--output", type=Path, default=None,
                        help="Output directory (default: <recipe dir>/output)")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose output")
    parser.add_argument("--validate-only", action="store_true",
                        help="Validate the recipe and report its summary; run nothing")
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument('--use-server', action='store_true',
                            help='gsasii: server mode only (auto-start enabled, fail if still unavailable)')
    mode_group.add_argument('--no-server', action='store_true',
                            help='gsasii: in-process mode only (skip the server entirely)')
    parser.add_argument("--server-timeout", type=float, default=None, metavar="SECONDS",
                        help="gsasii: stop waiting for the server's answer after this many seconds "
                             "(default: no limit; 0 = no limit)")
    parser.add_argument("--topas-dir", type=Path, default=None, help="topas: directory containing tc.exe")
    parser.add_argument("--topas-version", default=None, help="topas: the installed TOPAS version to run")
    parser.add_argument("--topas-timeout", type=float, default=None, metavar="SECONDS",
                        help="topas: stop tc.exe after this many seconds (default 3600, or topas.timeout; 0 = no limit)")
    return parser


#: Labels of the engine-specific ``validate_only`` items (``engine`` sub-dict, P-28); other keys are title-cased.
_ENGINE_ITEM_LABELS = {'refinement_cycles': 'Refinement cycles', 'iters': 'Iterations',
                       'engine_version': 'Engine version', 'calculator': 'Calculator'}


def _print_validate_only(result: dict, input_path: Path, verbose: bool = False) -> None:
    """Print the uniform ``validate_only`` summary (``powderline.registry.validate_only_summary``, P-28)."""
    print(f"{CHECK} Recipe validation successful: {input_path}")
    print(f"   Schema name: {result['schema_name']}")
    print(f"   Core schema version: {result['core_schema_version']}")
    print(f"   Engine schema version: {result['engine_schema_version']}")
    print(f"   Phases: {result['phases']}")
    print(f"   Parameters requested: {result['parameters_requested']}")
    for key, value in result['engine'].items():
        print(f"   {_ENGINE_ITEM_LABELS.get(key, key.replace('_', ' ').capitalize())}: {value}")
    if result['simulation_mode']:
        print("   Mode: Simulation (all parameters locked)")
    _print_warnings(result['warnings'], verbose=verbose)


def _print_warnings(warnings, verbose: bool = False) -> None:
    """Print the structured warnings: ``warning``-level entries always, ``info``-level ones only with
    ``verbose`` (otherwise their count and a hint; P-34)."""
    if not warnings:
        return
    actionable = [w for w in warnings if w.get('level', 'warning') != 'info']
    informative = [w for w in warnings if w.get('level', 'warning') == 'info']

    def _line(w) -> str:
        where = f" ({w['field_path']})" if w.get('field_path') else ""
        return f"   - {w['code']}: {w['message']}{where}"

    if actionable:
        print(f"{WARN} {len(actionable)} warning(s):")
        for w in actionable:
            print(_line(w))
    if informative:
        if verbose:
            print(f"{INFO} {len(informative)} informative note(s):")
            for w in informative:
                print(_line(w))
        else:
            print(f"{INFO} {len(informative)} informative note(s) (values held at their symmetry-derived "
                  f"form, etc.); run with --verbose to list them")


def main(argv: list[str] | None = None) -> int:
    """Entry point of the ``powderline`` command; returns the exit status."""
    # Ensure emoji/Unicode output works on Windows consoles that default to a
    # legacy code page (e.g. cp1252), which cannot encode the status emoji below.
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            try:
                _reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass

    parser = build_parser()
    args = parser.parse_args(argv)
    if args.doctor:
        from powderline import doctor
        return doctor.main()
    if args.input_json is None:
        parser.error("a recipe file is required (or --doctor)")
    output_dir = args.output if args.output else args.input_json.parent / "output"

    try:
        recipe_dict = load_recipe_asset(args.input_json)
    except (OSError, ValueError) as e:
        print(f"\n{CROSS} Cannot read recipe {args.input_json}: {e}\n")
        return 1

    if args.verbose:
        print(f"This is the recipe:\n\n{recipe_dict}\n\n")

    is_template, template_reason = is_template_file(recipe_dict, args.input_json)
    if is_template:
        print(f"\n{CROSS} Error: This appears to be a template file ({template_reason}).")
        print(f"\nTemplate files are not meant to be run directly.")
        print(f"To create a working example:")
        print(f"  1. Copy the template directory:")
        print(f"     cp -r examples/example_template")
        print(f"  2. Edit examples/example_template/input.json with your refinement parameters")
        print(f"  3. See examples/example_template/DESCRIPTION.md for guidance")
        print(f"\nOr run an existing example:")
        print(f"     pixi run -e gsasii powderline examples/example_LaB6/input.json --output my_lab6\n")
        return 1

    try:
        gateway_name = api.gateway_name_for(api.schema_name_of(recipe_dict))
        engine_options = engine_options_from_args(args, gateway_name)
        if not args.validate_only:
            output_dir.mkdir(parents=True, exist_ok=True)
        if args.verbose:
            print(f"{CHECK} Template check passed. Engine: {gateway_name}. Starting refinement...\n")

        result = run(
            recipe_dict,
            output_dir,
            verbose=args.verbose,
            validate_only=args.validate_only,
            **engine_options,
        )

    except ValidationError as e:
        print(f"\n{CROSS} Recipe validation failed: {args.input_json}\n")
        print("Validation errors:")
        for error in e.errors():
            location = " -> ".join(str(loc) for loc in error['loc'])
            print(f"  • {location}: {error['msg']}")
        print(f"\nPlease fix the errors above and try again.")
        print(f"See examples/example_LaB6/input.json for a working example.\n")
        return 1

    except EngineExecutionError as e:  # the engine ran and failed (re/12)
        print(f"\n{CROSS} Refinement failed ({e.reason}): {e}")
        tail = ((e.result or {}).get("failure") or {}).get("console_tail")
        if tail:
            lines = tail.strip().splitlines()
            print("   The engine's last console lines:")
            for line in lines[-12:]:
                print(f"     | {line}")
        files = (e.result or {}).get('output_files') or []
        if files:
            print("   Files kept for diagnosis (the engine's own files and failure.json):")
            for f in files:
                print(f"     {f}")
        hint = f"{output_dir}/*.lst" if gateway_name == "gsasii" else str(output_dir)
        print(f"\nCheck the engine's log for details: {hint}\n")
        return 1

    except ExecutionBackendError as e:  # the engine did not run (re/12)
        print(f"\n{CROSS} Could not run the engine ({e.reason}): {e}\n")
        return 1

    except (ValueError, PowderLineError) as e:
        print(f"\n{CROSS} {e}\n")
        return 1

    except Exception as e:
        print(f"\n{CROSS} Unexpected error during refinement:")
        print(f"   {str(e)}")
        if args.verbose:
            import traceback
            print()
            print(traceback.format_exc())
        else:
            print(f"\nAdd --verbose to the same command for the full traceback.\n")
        return 1

    if args.validate_only:
        _print_validate_only(result, args.input_json, verbose=args.verbose)
        return 0

    if result.get('status') == 'generated':  # the engine's input was written, the engine did not run (re/12 D6)
        print(f"\n{INFO} Generated the engine input only ({result.get('method')}, {result.get('elapsed_time', 0):.1f}s):")
        for f in result.get('output_files', []):
            print(f"   {f}")
        _print_output_recipe(result)
        _print_warnings(result.get('warnings'), verbose=True)  # the topas_generate_only note says how to run it
        return 0

    method = result.get('method', 'unknown')
    mode_emoji = emoji("🚀" if method == 'server' else "🐢")
    print(f"\n{INFO} Executed using {method} mode {mode_emoji} ({result.get('elapsed_time', 0):.1f}s)")
    if args.verbose and 'run_id' in result:
        print(f"{INFO} Run ID: {result['run_id']}")

    _print_warnings(result.get('warnings'), verbose=args.verbose)
    if result.get('rwp') is not None:
        print(f"{CHECK} Refinement complete. Final Rwp: {result['rwp']:.3f}%")
    else:
        print(f"{CHECK} Refinement complete.")
    if result.get('converged') is False:
        print(f"{WARN} The refinement did not converge within the cycle limit; the values are reported as they "
              "stand (see the *_fit_not_converged warning).")
    _print_output_recipe(result, verbose=args.verbose)
    print()
    return 0


def _print_output_recipe(result: dict, verbose: bool = False) -> None:
    """Where the output recipe went (re/20a, KI-04) and, with ``verbose``, how its values came about."""
    path = next((f for f in result.get('output_files') or [] if f.endswith('output_recipe.json')), None)
    if result.get('output_recipe') is None:
        return  # the gateway said why in its warnings
    state = "" if result.get('output_recipe_valid') else " (not valid as written: see the output_recipe_not_valid warning)"
    print(f"{INFO} Output recipe: {path or 'in the result'}{state}")
    if verbose and result.get('parameter_dispositions') is not None and len(result['parameter_dispositions']):
        counts = result['parameter_dispositions']['disposition'].value_counts().to_dict()
        print("   Dispositions: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())))


if __name__ == "__main__":
    sys.exit(main())
