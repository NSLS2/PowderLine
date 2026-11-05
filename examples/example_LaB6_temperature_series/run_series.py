"""Refine the simulated LaB6 temperature series sequentially: each step starts from the previous
step's **output recipe** with only the ``xrd_data`` block swapped (``powderline.recipes.with_block``, the core
block chaining of KI-04 / P-43 D4), and the chain stops at the first step whose output recipe is not valid.

Writes, under ``--output`` (default ``output/`` beside this file): ``series_report.csv`` (one row per step:
temperature, programmed and refined cell with ESD, programmed and refined Uiso, Rwp, Rexp, GoF, parameters varied,
``output_recipe_valid``), ``steps/<T>C_unit_cell_report.csv`` and ``steps/<T>C_refined_parameters.csv`` (the
per-step references), ``final_output_recipe.json`` (the last step's output recipe, the next step's input; not valid if the chain stopped) and
``thermal_expansion_fit.json`` (a quadratic fit of the refined a(T) against the programmed polynomial). The
full per-step engine output goes to ``--work`` (default: a temp dir).

    pixi run -e gsasii python examples/example_LaB6_temperature_series/run_series.py
    pixi run -e easydiffraction python examples/example_LaB6_temperature_series/run_series.py \
        --recipe examples/example_LaB6_temperature_series/easydiffraction/input.json --output <dir>

The first-step recipe decides the engine (``--recipe``; default ``input.json``, GSAS-II); the loop is the same for
every engine because only the core ``xrd_data`` block moves. The same loop, in six lines, is what an automation
would run (see docs/integration-guide.md).
"""
from __future__ import annotations

import argparse
import csv
import json
import shutil
import tempfile
from pathlib import Path

import numpy as np

import powderline
from powderline import recipes

HERE = Path(__file__).resolve().parent
PHASE = "LaB6"


def steps() -> list[dict]:
    return json.loads((HERE / "data" / "truth.json").read_text(encoding="utf-8"))["steps"]


def data_for(step: dict) -> dict:
    return json.loads((HERE / "data" / f"lab6_{int(step['temperature_C']):03d}C.json").read_text(encoding="utf-8"))


def _num(v):
    """A float, or None for a missing / NaN value (an engine that reports no ESD)."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f != f else f


def run_series(output: Path, work: Path, recipe_path: Path | None = None, verbose: bool = False,
               **engine_options) -> list[dict]:
    """Run the chain from ``recipe_path`` (default this example's ``input.json``); returns the report rows (also
    written). Stops when an output recipe is not valid. ``engine_options`` go to ``powderline.run`` (gsasii:
    ``execution_mode``)."""
    output.mkdir(parents=True, exist_ok=True)
    (output / "steps").mkdir(exist_ok=True)
    recipe = powderline.load_recipe_asset(recipe_path or HERE / "input.json")
    if recipe.get("schema_name", "").startswith("gsasii."):
        engine_options.setdefault("execution_mode", "subprocess")   # in-process unless the caller asks for the server
    rows = []
    for i, step in enumerate(steps()):
        t_c = step["temperature_C"]
        if i:  # the chaining step: the previous output recipe, this temperature's data
            recipe = recipes.with_block(recipe, "payload.xrd_data", data_for(step))
        step_dir = work / f"step_{i}_{int(t_c):03d}C"
        result = powderline.run(recipe, step_dir, verbose=verbose, **engine_options)
        cell = result["unit_cell_data"][PHASE].set_index("parameter")
        a_row = "cell_a"                                          # the report vocabulary (powderline.reports.UNIT_CELL_ROWS)
        disp = result["parameter_dispositions"].set_index("path")
        uiso = {atom: disp.loc[f"payload.phases.{PHASE}.atoms.{atom}.Uiso"] for atom in ("La", "B")}
        rows.append({
            "step": i, "temperature_C": t_c,
            "a_true": step["a"], "a_refined": float(cell.loc[a_row, "value"]), "a_esd": _num(cell.loc[a_row, "esd"]),
            "Uiso_La_true": step["Uiso"]["La"], "Uiso_La_refined": float(uiso["La"]["value"]), "Uiso_La_esd": _num(uiso["La"]["esd"]),
            "Uiso_B_true": step["Uiso"]["B"], "Uiso_B_refined": float(uiso["B"]["value"]), "Uiso_B_esd": _num(uiso["B"]["esd"]),
            "rwp": result["rwp"], "r_exp": result["r_exp"], "gof": result["gof"],
            "parameters_varied": result["engine_details"]["parameters_varied"],
            "converged": result["converged"], "output_recipe_valid": result["output_recipe_valid"],
        })
        for name in (f"{PHASE}_unit_cell_report.csv", "refined_parameters.csv"):
            if (step_dir / name).exists():
                shutil.copyfile(step_dir / name, output / "steps" / f"{int(t_c):03d}C_{name}")
        esd = rows[-1]["a_esd"]
        print(f"step {i} {t_c:4d} C  a {rows[-1]['a_refined']:.6f} ({esd if esd is None else f'{esd:.6f}'})  true {step['a']:.6f}  "
              f"Uiso La {rows[-1]['Uiso_La_refined']:.5f} true {step['Uiso']['La']:.5f}  Rwp {result['rwp']:.3f} GoF {result['gof']:.2f}  "
              f"valid {result['output_recipe_valid']}")
        recipe = result["output_recipe"]                 # the next step's input (written as final_output_recipe.json)
        if not result["output_recipe_valid"]:
            print("  the output recipe is not valid; the chain stops here:",
                  [w["message"] for w in result["warnings"] if w["code"] == "output_recipe_not_valid"])
            break
    with (output / "series_report.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")  # LF on every platform
        w.writeheader()
        w.writerows(rows)
    (output / "final_output_recipe.json").write_text(json.dumps(recipe, indent=2) + "\n", encoding="utf-8")
    (output / "thermal_expansion_fit.json").write_text(json.dumps(expansion_fit(rows), indent=2) + "\n", encoding="utf-8")
    return rows


def expansion_fit(rows: list[dict]) -> dict:
    """Quadratic a(T) through the refined cells (weighted by 1/ESD^2), against the programmed polynomial;
    a line through three or fewer points, nothing through fewer than two (a chain that stopped early)."""
    truth = json.loads((HERE / "data" / "truth.json").read_text(encoding="utf-8"))
    if len(rows) < 2:
        return {"fit": None, "coefficients": None, "programmed": [truth["A0"], truth["XI"], truth["PSI"]],
                "max_abs_deviation_A": (float(abs(rows[0]["a_refined"] - rows[0]["a_true"])) if rows else None),
                "max_deviation_in_esd": None, "note": f"{len(rows)} step(s) completed: no fit"}
    dt = np.array([r["temperature_C"] + 273.15 - 298.0 for r in rows])
    a = np.array([r["a_refined"] for r in rows])
    esds = [r["a_esd"] for r in rows]
    weighted = all(e is not None and e > 0 for e in esds)
    w = 1.0 / np.array(esds) if weighted else None          # unweighted when an engine reported no ESD
    degree = 2 if len(rows) > 3 else 1
    coef = np.polyfit(dt, a, degree, w=w)[::-1].tolist()
    programmed = [truth["A0"], truth["XI"], truth["PSI"]]
    return {"fit": ("a(T) = c0 + c1 dT + c2 dT^2" if degree == 2 else "a(T) = c0 + c1 dT") + ", dT = T[K] - 298, "
                   + ("weighted 1/esd^2" if weighted else "unweighted"),
            "coefficients": coef, "programmed": programmed,
            "max_abs_deviation_A": float(max(abs(r["a_refined"] - r["a_true"]) for r in rows)),
            "max_deviation_in_esd": (float(max(abs(r["a_refined"] - r["a_true"]) / r["a_esd"] for r in rows))
                                     if weighted else None)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--recipe", type=Path, default=HERE / "input.json",
                    help="the first step's recipe; its schema_name picks the engine (default: input.json, gsasii)")
    ap.add_argument("--output", type=Path, default=HERE / "output")
    ap.add_argument("--work", type=Path, default=None, help="where each step's full engine output goes (default: a temp dir)")
    ap.add_argument("--use-server", action="store_true", help="gsasii: run through the GSAS-II server (default: in-process)")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args(argv)
    work = args.work or Path(tempfile.mkdtemp(prefix="lab6_series_run_"))
    recipe = powderline.load_recipe_asset(args.recipe)
    options = {}
    if recipe.get("schema_name", "").startswith("gsasii."):
        options["execution_mode"] = "auto" if args.use_server else "subprocess"
    rows = run_series(args.output, work, recipe_path=args.recipe, verbose=args.verbose, **options)
    fit = expansion_fit(rows)
    in_esd = fit["max_deviation_in_esd"]
    print(f"{len(rows)} steps; max |a_refined - a_true| = {fit['max_abs_deviation_A']:.2e} A"
          + (f" ({in_esd:.1f} ESD)" if in_esd is not None else " (no ESDs reported)") + f"; full outputs in {work}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
