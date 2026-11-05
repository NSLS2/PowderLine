"""``powderline --doctor``: what this environment can do (KI-13, re/27).

Engine-free at import. The report lists the PowderLine version, the Python and platform, every gateway the
registry finds (the entry-point metadata written at install time -- the thing that goes stale, KI-13), each
gateway's workflows and engine version requirement, the engine installed (or not) and whether it satisfies
the requirement, and the GSAS-II server's state directory and whether a server is running. A **problem** is
something that will make a run fail in this environment through no fault of the recipe: no gateway at all
(stale install), or an installed engine outside its gateway's version requirement. An engine that is simply
not installed is reported, not counted: the ``default`` environment validates everything and runs nothing by
design.
"""
from __future__ import annotations

import importlib
import platform
import sys
from typing import Any, Optional

from powderline import __version__, registry
from powderline.exceptions import EngineNotAvailableError


def _gateway_report(name: str) -> dict:
    gw = registry.get(name)
    caps = gw.capabilities() or {}
    entry: dict[str, Any] = {"name": name, "workflows": list(caps.get("workflows") or []),
                             "engine_version_spec": caps.get("engine_version_spec"),
                             "env": caps.get("env"), "install_command": caps.get("install_command"),
                             "engine_installed": None, "engine_status": "unknown", "problem": None}
    module_name = f"powderline.gateways.{name}.gateway"
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        if exc.name and module_name.startswith(exc.name):
            module = None                                    # not an in-repo gateway: capabilities only
        else:
            raise                                            # an in-repo gateway whose own import failed
    probe = getattr(module, "installed_engine_version", None) if module else None
    declared = getattr(module, "configured_engine_version", None) if module else None
    spec = entry["engine_version_spec"]
    if probe is not None:
        try:
            installed = str(probe())
        except EngineNotAvailableError:
            entry["engine_status"] = "not installed in this environment"
            return entry
        except Exception as exc:  # the probe itself failed: say so, do not guess
            entry["engine_status"] = f"version probe failed: {exc}"
            entry["problem"] = f"{name}: the engine version could not be read ({exc})"
            return entry
        entry["engine_installed"] = installed
        entry["engine_status"] = _spec_status(name, installed, spec, entry)
    elif declared is not None:                              # topas: the installed version is declared, not read
        try:
            version = declared()
        except Exception as exc:                            # a malformed .powderline_config.yaml
            entry["engine_status"] = f"configuration unreadable: {exc}"
            entry["problem"] = f"{name}: the TOPAS configuration could not be read ({exc})"
            return entry
        entry["engine_installed"] = None if version is None else str(version)
        entry["engine_status"] = ("declared (not read from tc.exe)" if version is not None
                                  else "no installed version declared (topas_version / .powderline_config.yaml)")
    else:
        entry["engine_status"] = "no version probe (a gateway outside PowderLine)"
    return entry


def _spec_status(name: str, installed: str, spec: Optional[str], entry: dict) -> str:
    if not spec:
        return "installed"
    try:
        from packaging.specifiers import SpecifierSet
        from packaging.version import Version

        ok = Version(installed) in SpecifierSet(spec)
    except Exception:                                       # an unparsable version: report, do not judge
        return f"installed; requirement {spec} not checked (version not parsable)"
    if ok:
        return f"installed, satisfies {spec}"
    entry["problem"] = f"{name}: installed engine {installed} is outside the gateway's requirement {spec}"
    return f"installed, OUTSIDE {spec}"


def _server_report() -> dict:
    try:
        from powderline.gateways.gsasii import server
    except Exception as exc:                                # the gsasii gateway package is absent or broken
        return {"state_dir": None, "running": None, "note": f"server module not importable: {exc}"}
    try:
        state = str(server.state_dir())
    except Exception as exc:                                # no private state directory available
        return {"state_dir": None, "running": None, "note": str(exc)}
    try:
        running = bool(server.is_server_running())
    except Exception as exc:
        return {"state_dir": state, "running": None, "note": str(exc)}
    return {"state_dir": state, "running": running, "note": None}


def report() -> dict:
    """The structured report; ``problems`` is the list that makes the exit status non-zero."""
    gateways = []
    problems: list[str] = []
    names = registry.available()
    if not names:
        problems.append("no PowderLine gateway is registered: the install metadata is stale or missing "
                        "(KI-13); re-install this environment's package: pixi reinstall powderline, or "
                        "python -m pip install --no-deps --no-build-isolation --no-index -e .")
    for name in names:
        try:
            entry = _gateway_report(name)
        except Exception as exc:                            # a gateway that fails to load is a problem by itself
            entry = {"name": name, "workflows": [], "engine_version_spec": None, "env": None,
                     "install_command": None, "engine_installed": None,
                     "engine_status": f"gateway failed to load: {exc}", "problem": f"{name}: {exc}"}
        gateways.append(entry)
        if entry.get("problem"):
            problems.append(entry["problem"])
    return {"powderline": __version__, "python": sys.version.split()[0], "executable": sys.executable,
            "platform": platform.platform(), "gateways": gateways, "server": _server_report(),
            "problems": problems}


def format_report(rep: dict) -> str:
    lines = [f"PowderLine {rep['powderline']}  (Python {rep['python']}, {rep['platform']})",
             f"  python: {rep['executable']}"]
    if rep["gateways"]:
        lines.append(f"  gateways ({len(rep['gateways'])}, from the powderline.gateways entry points):")
        for g in rep["gateways"]:
            spec = f" requires {g['engine_version_spec']}" if g.get("engine_version_spec") else ""
            lines.append(f"    {g['name']:16s} workflows {', '.join(g['workflows']) or '-'}{spec}")
            lines.append(f"    {'':16s} engine: {g['engine_status']}"
                         + (f" [{g['engine_installed']}]" if g.get("engine_installed") else ""))
            if g.get("env") and "not installed" in g["engine_status"]:
                lines.append(f"    {'':16s} env: {g['env']}" + (f"  ({g['install_command']})" if g.get("install_command") else ""))
    else:
        lines.append("  gateways: none found")
    s = rep["server"]
    if s.get("state_dir"):
        lines.append(f"  GSAS-II server: {'running' if s['running'] else 'not running'}  (state dir {s['state_dir']})")
    elif s.get("note"):
        lines.append(f"  GSAS-II server: {s['note']}")
    if rep["problems"]:
        lines.append(f"  PROBLEMS ({len(rep['problems'])}):")
        lines.extend(f"    - {p}" for p in rep["problems"])
    else:
        lines.append("  no problems found")
    return "\n".join(lines)


def main() -> int:
    rep = report()
    print(format_report(rep))
    return 1 if rep["problems"] else 0
