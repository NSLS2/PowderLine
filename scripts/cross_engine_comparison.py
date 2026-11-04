#!/usr/bin/env python3
"""Cross-engine comparison of the reference cases (master plan A173; re/10 §1 item 5).

For each reference case (LaB6, DRX_33) the script collects, per engine and
profile model, the refined cell with its ESD, the difference from a stated
reference in ppm and in σ, the uniform fit statistics (``rwp`` / ``r_exp`` /
``gof``, A125: the same statistic over the same window points), the number of
parameters varied and a note on the model, and writes

* ``docs/_generated/cross_engine_comparison.md`` — the tables the user page
  ``docs/cross-engine-comparison.md`` includes (MyST ``{include}``), with a
  "versions and date" footer;
* ``docs/_generated/cross_engine_comparison.json`` — the same numbers, plus the
  record of every GSAS-II run (date, versions) that ``--no-run`` reuses.

Where each row comes from
-------------------------
* **GSAS-II** — a run of the committed example recipe (``examples/<case>/
  input.json``; a 0.26.0 recipe is converted in memory with
  ``scripts/convert_recipe_026.py``, the LaB6 background peak dropped (P-01)
  and, for LaB6, the cell freed so every engine refines it, EB-88). With
  ``--no-run`` the rows are read back from the committed JSON (their own run
  date and versions are kept).
* **TOPAS 6** — never run here (P-08): the rows are rebuilt from the committed
  TOPAS 6 goldens (``tests/data/topas/native/golden/``) with the gateway's own
  result builder, so the statistics are the uniform ones.
* **easydiffraction** — read from the committed goldens
  (``tests/data/easydiffraction/native/golden/``), which record the versions
  they were made with. ``--rerun-easydiffraction`` runs the fixtures again (the
  easydiffraction environment) and records how far the rerun is from the golden.

Usage (from the repo root)::

    python scripts/cross_engine_comparison.py            # runs GSAS-II (default env)
    python scripts/cross_engine_comparison.py --no-run   # committed goldens + JSON record only
    python scripts/cross_engine_comparison.py --out-dir /tmp/x --no-run

Exit status 1 when an input is missing (a golden, the example, or the JSON
record in ``--no-run`` mode).
"""

from __future__ import annotations

import argparse
import datetime as _dt
import importlib.util
import json
import math
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

TOPAS_GOLDEN = ROOT / "tests" / "data" / "topas" / "native" / "golden"
TOPAS_NATIVE = ROOT / "tests" / "data" / "topas" / "native"
ED_NATIVE = ROOT / "tests" / "data" / "easydiffraction" / "native"
ED_GOLDEN = ED_NATIVE / "golden"
DEFAULT_OUT_DIR = ROOT / "docs" / "_generated"
STEM = "cross_engine_comparison"

#: NIST SRM 660c certificate (issued 29 October 2015): a = 0.415 682 6 nm ± 0.000 008 nm,
#: expanded uncertainty k = 2, at 22.5 °C. Standard uncertainty = 0.000 04 Å.
NIST_660C = {"value": 4.156826, "esd": 0.00004, "label": "NIST SRM 660c",
             "note": "certificate 2015-10-29: 0.4156826(8) nm, k = 2, 22.5 °C"}

#: The reference cases: the GSAS-II example and, per other engine, the committed fixture(s).
CASES = {
    "LaB6": {
        "example": "example_LaB6",
        "free_cell": True,  # EB-88: the example fixes the cell; every engine refines it here
        "topas": ["lab6_rietveld"],
        "easydiffraction": ["lab6_crysfml_tch", "lab6_cryspy_pv"],
        "nist": NIST_660C,
    },
    "DRX_33": {
        "example": "example_DRX_33",
        "free_cell": False,
        "topas": ["drx33_rietveld"],
        "easydiffraction": ["drx33_two_phase_cryspy"],
        "nist": None,
    },
}

#: Model notes per fixture (what the fixture README / register say the model is).
MODEL_NOTES = {
    "lab6_rietveld": "TCHZ; no axial-asymmetry model; Chebyshev + one pv background peak; "
                     "CS_L 10000 nm fixed; **cell fixed** (fixture)",
    "drx33_rietveld": "TCHZ instrument fixed; Chebyshev; Strain_L/Strain_G per phase; no size term",
    "lab6_crysfml_tch": "Thompson-Cox-Hastings + FCJ axial asymmetry (S/L = H/L = 0.001, fixed); "
                        "no background peak; no sample broadening (start-dependent)",
    "lab6_cryspy_pv": "pseudo-Voigt, no asymmetry; no background peak; no sample broadening",
    "drx33_two_phase_cryspy": "pseudo-Voigt, no asymmetry; U-V-W-X-Y refined instead of per-phase size/strain",
}
CELL_PARAMS = ("a", "b", "c", "alpha", "beta", "gamma")
PARAM_LABEL = {"alpha": "α", "beta": "β", "gamma": "γ"}


class MissingInput(RuntimeError):
    """A committed input (golden, example, JSON record) is absent."""


# --- helpers -------------------------------------------------------------------------------


def _fmt_esd(value: float, esd: float | None, unit_digits: int = 6) -> str:
    """``4.157216(21)``; a value without an ESD is printed to ``unit_digits`` decimals."""
    if esd is None or not math.isfinite(esd) or esd <= 0:
        return f"{value:.{unit_digits}f}"
    exp = math.floor(math.log10(esd))
    digits = max(0, 1 - exp)  # two significant digits of the ESD
    scaled = round(esd * 10 ** digits)
    if scaled >= 100:  # rounding carried (e.g. 0.0999 -> 100)
        digits -= 1
        scaled = round(esd * 10 ** digits)
    return f"{value:.{digits}f}({scaled})"


def _ppm(value: float, ref: float) -> float:
    return (value - ref) / ref * 1e6


def _sigma(value: float, esd: float | None, ref: float, ref_esd: float | None) -> float | None:
    s2 = sum(e * e for e in (esd, ref_esd) if e is not None and math.isfinite(e) and e > 0)
    if s2 <= 0:
        return None
    return (value - ref) / math.sqrt(s2)


def _records_to_cell(records: list[dict]) -> dict[str, tuple[float, float | None]]:
    """``[{parameter, value, esd}]`` -> ``{member: (value, esd)}`` for a..gamma.

    Every engine's unit-cell report uses the core row vocabulary (``cell_a`` ...,
    ``powderline.reports.UNIT_CELL_ROWS``); the bridge back to the members is
    ``UNIT_CELL_MEMBER_OF``.
    """
    from powderline.reports import UNIT_CELL_MEMBER_OF

    out = {}
    for rec in records:
        name = UNIT_CELL_MEMBER_OF.get(str(rec["parameter"]), str(rec["parameter"]))
        if name in CELL_PARAMS:
            esd = rec.get("esd")
            out[name] = (float(rec["value"]), None if esd is None else float(esd))
    return out


def _refined_cell(recipe: dict) -> dict[str, list[str]]:
    """Per phase, the cell parameters the recipe flags for refinement (every native schema: ``[value, flag]``)."""
    return {name: [p for p in CELL_PARAMS if ph["unit_cell"][p][1]] for name, ph in recipe["payload"]["phases"].items()}


def _row(engine: str, version: str, source: str, model: str, result: dict, cells: dict,
         refined_cell: dict[str, list[str]], extra: dict | None = None) -> dict:
    d = result["engine_details"]
    return {
        "engine": engine, "engine_version": version, "source": source, "model": model,
        "rwp": result["rwp"], "r_exp": result["r_exp"], "gof": result["gof"],
        "n_points": d.get("n_points"), "parameters_varied": d.get("parameters_varied"),
        "parameters_requested": d.get("parameters_requested"),
        "warnings": sorted({w["code"] if isinstance(w, dict) else str(w) for w in result.get("warnings", [])}),
        "cell": {phase: {p: list(v) for p, v in c.items()} for phase, c in cells.items()},
        "refined_cell": refined_cell,
        **(extra or {}),
    }


def _shown_params(cell: dict, *refined_sets: list[str]) -> list[str]:
    """The cell parameters worth a table row: refined by the row or the reference, tied duplicates dropped
    (a cubic ``b = c = a`` with the same value and ESD is one row)."""
    wanted = [p for p in CELL_PARAMS if any(p in s for s in refined_sets)]
    out: list[str] = []
    for p in wanted:
        if p in ("b", "c") and "a" in out and cell.get(p) == cell.get("a"):
            continue
        out.append(p)
    return out


# --- GSAS-II -------------------------------------------------------------------------------


def _load_converter():
    spec = importlib.util.spec_from_file_location("convert_recipe_026", ROOT / "scripts" / "convert_recipe_026.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def gsasii_recipe(case: str) -> tuple[dict, list[str]]:
    """The native ``gsasii.rietveld`` recipe of a case (converted in memory when still 0.26.0)."""
    path = ROOT / "examples" / CASES[case]["example"] / "input.json"
    if not path.exists():
        raise MissingInput(f"GSAS-II example missing: {path}")
    recipe = json.loads(path.read_text(encoding="utf-8"))
    report: list[str] = []
    if recipe.get("schema_name", "").startswith("GSASII_"):
        peaks = recipe["payload"].get("background", {}).pop("single_peaks", None)
        if peaks:
            report.append("payload.background.single_peaks: dropped before conversion")
        recipe, conv_report = _load_converter().convert(recipe)
        report.extend(conv_report)
    if CASES[case]["free_cell"]:
        for name, phase in recipe["payload"]["phases"].items():
            for p in ("a", "b", "c"):
                phase["unit_cell"][p][1] = True
            report.append(f"payload.phases.{name}.unit_cell: a, b, c freed (EB-88: every engine refines the cell)")
    return recipe, report


def run_gsasii(case: str, work: Path) -> dict:
    import powderline
    from powderline.gateways.gsasii.gateway import installed_engine_version

    recipe, report = gsasii_recipe(case)
    out = work / "gsasii" / case
    out.mkdir(parents=True, exist_ok=True)
    result = powderline.run(recipe, out, execution_mode="subprocess")   # a failed run raises (re/12)
    if result["status"] != "ok":
        raise RuntimeError(f"GSAS-II run of {case} produced no fit: status {result['status']}")
    cells = {phase: _records_to_cell(df.to_dict("records")) for phase, df in result["unit_cell_data"].items()}
    shl = recipe["payload"]["instrument"]["corrections"]["axial_divergence"][0]
    notes = [f"FCJ axial asymmetry (SH/L {shl})", "no background peak"]
    phases = recipe["payload"]["phases"]
    if any("peak_broadening" in ph for ph in phases.values()):
        notes.append("isotropic size + microstrain refined per phase")
    else:
        notes.append("size 10 µm / strain 0 defaults, not refined")
    d = result["engine_details"]
    if d.get("converged") is False:
        notes.append(f"not converged in {recipe['payload']['refinement_controls']['refinement_cycles']} cycles")
    return _row("GSAS-II", installed_engine_version(), "run", "; ".join(notes), result, cells, _refined_cell(recipe),
                {"run_date": _dt.date.today().isoformat(), "converged": d.get("converged"),
                 "engine_rwp": d.get("rwp"), "recipe_report": report,
                 "python": platform.python_version(), "powderline": powderline.__version__})


# --- TOPAS (goldens only) --------------------------------------------------------------------


def topas_golden_row(fixture: str) -> dict:
    from powderline.gateways.topas import native_run, native_writer, schema

    recipe_path = TOPAS_NATIVE / f"{fixture}.json"
    base = f"{fixture}__snapped"
    files = sorted(TOPAS_GOLDEN.glob(f"{base}*"))
    if not recipe_path.exists() or not any(f.name == f"{base}_results.csv" for f in files):
        raise MissingInput(f"TOPAS golden missing: {TOPAS_GOLDEN / (base + '_results.csv')}")
    recipe = json.loads(recipe_path.read_text(encoding="utf-8"))
    model = schema.validate_recipe(recipe)
    native = native_writer.render_native(model, base)
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        for f in files:
            if not f.name.endswith(".inp"):
                shutil.copy(f, out / f.name)
        result = native_run.build_result(model, native, out, [], elapsed=0.0)
    cells = {phase: _records_to_cell(df.to_dict("records")) for phase, df in result["unit_cell_data"].items()}
    return _row("TOPAS", f"{model.engine_version} (golden)", f"golden `{fixture}`",
                MODEL_NOTES.get(fixture, ""), result, cells, _refined_cell(recipe),
                {"golden_files": [f.name for f in files]})


# --- easydiffraction (goldens; optional rerun) -----------------------------------------------


def ed_golden_row(fixture: str) -> dict:
    path = ED_GOLDEN / f"{fixture}.json"
    if not path.exists():
        raise MissingInput(f"easydiffraction golden missing: {path}")
    golden = json.loads(path.read_text(encoding="utf-8"))
    run = golden["run"]
    cells = {phase: _records_to_cell(rows) for phase, rows in run["unit_cell"].items()}
    recipe = json.loads((ED_NATIVE / f"{fixture}.json").read_text(encoding="utf-8"))
    d = run["engine_details"]
    model = f"{d['calculator']} (`{d['peak_type']}`): {MODEL_NOTES.get(fixture, '')}"
    return _row("easydiffraction", golden["versions"]["easydiffraction"], f"golden `{fixture}`", model,
                run, cells, _refined_cell(recipe), {"versions": golden["versions"]})


def ed_rerun(fixture: str, work: Path) -> dict:
    """Run the fixture again and report the largest cell deviation from its golden (A179: rtol 1e-4)."""
    import powderline

    recipe = json.loads((ED_NATIVE / f"{fixture}.json").read_text(encoding="utf-8"))
    out = work / "easydiffraction" / fixture
    out.mkdir(parents=True, exist_ok=True)
    result = powderline.run(recipe, out)
    golden = json.loads((ED_GOLDEN / f"{fixture}.json").read_text(encoding="utf-8"))["run"]
    worst = 0.0
    for phase, rows in golden["unit_cell"].items():
        got = _records_to_cell(result["unit_cell_data"][phase].to_dict("records"))
        for p, (gv, _) in _records_to_cell(rows).items():
            worst = max(worst, abs(got[p][0] - gv) / gv)
    return {"fixture": fixture, "rwp": result["rwp"], "golden_rwp": golden["rwp"],
            "rwp_rel": abs(result["rwp"] - golden["rwp"]) / golden["rwp"],
            "cell_worst_rel": worst, "within_a179": worst <= 1e-4, "run_date": _dt.date.today().isoformat()}


# --- assembly --------------------------------------------------------------------------------


def collect(no_run: bool, record: dict | None, work: Path, rerun_ed: bool) -> dict:
    cases = {}
    for case, spec in CASES.items():
        rows = []
        if no_run:
            prev = ((record or {}).get("cases", {}).get(case, {}).get("rows", []))
            gsas = [r for r in prev if r["engine"] == "GSAS-II" and r["source"] == "run"]
            if not gsas:
                raise MissingInput(f"--no-run: no recorded GSAS-II run for {case} in the JSON record "
                                   "(run the script without --no-run first)")
            rows.extend(gsas)
        else:
            rows.append(run_gsasii(case, work))
        rows.extend(topas_golden_row(f) for f in spec["topas"])
        rows.extend(ed_golden_row(f) for f in spec["easydiffraction"])
        ref_row = next(r for r in rows if r["engine"] == "GSAS-II")
        cases[case] = {"rows": rows, "reference": {"engine": "GSAS-II", "source": ref_row["source"],
                                                   "run_date": ref_row.get("run_date")},
                       "nist": spec["nist"]}
    reruns = []
    if rerun_ed:
        for spec in CASES.values():
            reruns.extend(ed_rerun(f, work) for f in spec["easydiffraction"])
    return {"cases": cases, "easydiffraction_reruns": reruns or (record or {}).get("easydiffraction_reruns", [])}


def _git_head() -> str | None:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True,
                              text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _stat(v) -> str:
    return "—" if v is None else f"{v:.3f}"


def render_markdown(data: dict, generated: dict) -> str:
    lines = []
    for case, block in data["cases"].items():
        rows = block["rows"]
        ref_row = next(r for r in rows if r["engine"] == "GSAS-II")
        lines += [f"### {case}", ""]
        lines += [f"Fit window and points: {rows[0]['n_points']} points (every engine scores the same points)."
                  if len({r['n_points'] for r in rows}) == 1 else
                  "Points per engine: " + ", ".join(f"{r['engine']} {r['n_points']}" for r in rows), ""]
        lines += ["| Engine (version) | Source | Model | Varied | Rwp % | Rexp % | GoF | Warnings |",
                  "|---|---|---|---:|---:|---:|---:|---|"]
        for r in rows:
            lines.append(f"| {r['engine']} {r['engine_version']} | {r['source']} | {r['model']} | "
                         f"{r['parameters_varied']} | {_stat(r['rwp'])} | {_stat(r['r_exp'])} | {_stat(r['gof'])} | "
                         f"{', '.join(f'`{w}`' for w in r['warnings']) or '—'} |")
        lines.append("")
        nist = block.get("nist")
        head = "| Engine | Phase | Parameter | Value (ESD) | Δ vs GSAS-II (ppm) | Δ/σ |"
        sep = "|---|---|---|---:|---:|---:|"
        if nist:
            head += f" Δ vs {nist['label']} (ppm) | Δ/σ |"
            sep += "---:|---:|"
        lines += [head, sep]
        for r in rows:
            for phase, cell in r["cell"].items():
                ref_cell = ref_row["cell"].get(phase, {})
                refined = r["refined_cell"].get(phase, [])
                for p in _shown_params(cell, refined, ref_row["refined_cell"].get(phase, [])):
                    v, e = cell[p]
                    unit = "°" if p in ("alpha", "beta", "gamma") else " Å"
                    fixed = p not in refined
                    val = _fmt_esd(v, None if fixed else e) + unit + (" (fixed)" if fixed else "")
                    line = f"| {r['engine']} | {phase} | {PARAM_LABEL.get(p, p)} | {val} |"
                    if r is ref_row:
                        line += " reference | — |"
                    elif fixed:
                        line += " not refined | — |"
                    elif p in ref_cell:
                        rv, re_ = ref_cell[p]
                        s = _sigma(v, e, rv, re_)
                        line += f" {_ppm(v, rv):+.0f} | {'—' if s is None else f'{s:+.1f}'} |"
                    else:
                        line += " — | — |"
                    if nist:
                        if p == "a" and not fixed:
                            s = _sigma(v, e, nist["value"], nist["esd"])
                            line += f" {_ppm(v, nist['value']):+.0f} | {'—' if s is None else f'{s:+.1f}'} |"
                        else:
                            line += " — | — |"
                    lines.append(line)
        lines.append("")
        if nist:
            lines += [f"Reference for the NIST columns: {nist['label']}, a = {nist['value']} Å "
                      f"({nist['note']}; standard uncertainty {nist['esd']} Å used for σ).", ""]
    reruns = data.get("easydiffraction_reruns") or []
    if reruns:
        lines += ["### easydiffraction goldens reproduced", "",
                  "| Fixture | Rwp % (rerun / golden) | Worst cell deviation (rel.) | Within 1e-4 | Run date |",
                  "|---|---:|---:|---|---|"]
        for x in reruns:
            lines.append(f"| `{x['fixture']}` | {x['rwp']:.3f} / {x['golden_rwp']:.3f} | {x['cell_worst_rel']:.1e} | "
                         f"{'yes' if x['within_a179'] else 'no'} | {x['run_date']} |")
        lines.append("")
    # versions and date footer
    lines += ["### Versions and dates", ""]
    gs = [r for b in data["cases"].values() for r in b["rows"] if r["engine"] == "GSAS-II"]
    tp = [r for b in data["cases"].values() for r in b["rows"] if r["engine"] == "TOPAS"]
    ed = [r for b in data["cases"].values() for r in b["rows"] if r["engine"] == "easydiffraction"]
    if gs:
        lines.append(f"- GSAS-II {gs[0]['engine_version']}: run {', '.join(sorted({r['run_date'] for r in gs}))} "
                     f"(PowderLine {gs[0].get('powderline')}, Python {gs[0].get('python')}); "
                     "`execution_mode='subprocess'`.")
    if tp:
        lines.append(f"- TOPAS: TOPAS-64 Version {tp[0]['engine_version'].split()[0]} goldens "
                     "(`tests/data/topas/native/golden/`, TOPAS machine runs of 2026-10-09); **not executed "
                     "for this page**: the rows are the gateway's result built from the committed files.")
    if ed:
        v = ed[0].get("versions", {})
        lines.append("- easydiffraction goldens (`tests/data/easydiffraction/native/golden/`, runs of 2026-10-09): "
                     + ", ".join(f"{k} {v[k]}" for k in ("easydiffraction", "cryspy", "crysfml", "lmfit", "numpy",
                                                           "scipy") if k in v) + ".")
    lines.append(f"- Table generated {generated['date']} by `scripts/cross_engine_comparison.py`"
                 + (f" at commit `{generated['commit']}`" if generated.get("commit") else "")
                 + (" in `--no-run` mode (GSAS-II rows from the committed JSON record)." if generated["no_run"]
                    else "."))
    lines.append("")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-run", action="store_true",
                    help="use committed goldens and the JSON record only (no engine is imported or run)")
    ap.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR, help="where the .md and .json go")
    ap.add_argument("--record", type=Path, default=None,
                    help="JSON record to read GSAS-II rows from in --no-run mode (default: <out-dir>/%s.json or the "
                         "committed docs/_generated one)" % STEM)
    ap.add_argument("--work-dir", type=Path, default=None, help="engine output directory (default: a temp dir)")
    ap.add_argument("--rerun-easydiffraction", action="store_true",
                    help="also rerun the easydiffraction fixtures (needs the easydiffraction environment)")
    args = ap.parse_args(argv)

    record = None
    candidates = [args.record] if args.record else [args.out_dir / f"{STEM}.json", DEFAULT_OUT_DIR / f"{STEM}.json"]
    work = args.work_dir or Path(tempfile.mkdtemp(prefix="cross_engine_"))
    try:
        for candidate in candidates:
            if candidate.exists():
                record = json.loads(candidate.read_text(encoding="utf-8"))
                break
        else:
            if args.no_run:
                raise MissingInput(f"--no-run: JSON record not found ({', '.join(map(str, candidates))})")
        data = collect(args.no_run, record, work, args.rerun_easydiffraction)
    except MissingInput as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    generated = {"date": _dt.date.today().isoformat(), "commit": _git_head(), "no_run": args.no_run}
    data["generated"] = generated
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / f"{STEM}.json").write_text(json.dumps(data, indent=1, default=str) + "\n", encoding="utf-8")
    (args.out_dir / f"{STEM}.md").write_text(render_markdown(data, generated), encoding="utf-8")
    print(f"wrote {args.out_dir / (STEM + '.md')} and .json"
          + ("" if args.no_run else f"; engine outputs in {work}"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
