"""Simulate the LaB6 temperature series this example refines (GSAS-II, ``gsasii.rietveld`` one-cycle runs).

Truth: the SRM 660a lattice parameter of Akdoğan & Payzant, J. Appl. Cryst. 58 (2025) 1635,
``a(T) = 4.15678 + 2.4645e-5 (T - 298 K) + 1.0325e-8 (T - 298 K)^2`` A, and an isotropic displacement
growing with absolute temperature (``Uiso(T) = Uiso(298 K) * T / 298 K``, the high-temperature harmonic
limit). Instrument profile, background and scale are the committed ``example_LaB6`` refinement's values, so
the series looks like that data set (28-ID-1, lambda 0.1665 A) heated in place. Each pattern is GSAS-II's
calculated profile on the measured 2-theta grid with Poisson counting noise (fixed seeds).

Writes ``data/lab6_<T>C.json`` (an ``xrd_data`` block each), ``data/truth.json`` (the programmed values) and
``input.json`` (the first step's refinement recipe). Run in the gsasii environment:

    pixi run -e gsasii python examples/example_LaB6_temperature_series/make_series.py
"""
from __future__ import annotations

import argparse
import copy
import json
import tempfile
from pathlib import Path

import numpy as np

import powderline

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE.parent / "example_LaB6" / "input.json"
TEMPERATURES_C = [25, 120, 215, 310, 405, 500]
SEED = 20261020

# Akdoğan & Payzant (2025): SRM 660a, 298-998 K
A0, XI, PSI, T0_K = 4.15678, 2.4645e-5, 1.0325e-8, 298.0
UISO_298 = {"La": 0.00858, "B": 0.009}
# the committed example_LaB6 refinement (examples/example_LaB6/output/refined_parameters.csv)
INSTRUMENT = {"U": 49.11908, "V": 11.18459, "W": 0.7063716, "X": 0.6193714, "Y": -10.26013, "Z": 0.3421716}
BACKGROUND = [30.02431, 1.362780, 1.178665, -1.426545, 0.5206805, 0.3164668]
SCALE = 0.03773081


def kelvin(t_c: float) -> float:
    return t_c + 273.15


def a_true(t_c: float) -> float:
    dt = kelvin(t_c) - T0_K
    return A0 + XI * dt + PSI * dt * dt


def uiso_true(atom: str, t_c: float) -> float:
    return UISO_298[atom] * kelvin(t_c) / T0_K


def _held(recipe: dict) -> dict:
    """Every refine flag False (a pure calculation)."""
    def walk(node):
        if isinstance(node, dict):
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            if len(node) == 2 and isinstance(node[1], bool) and isinstance(node[0], (int, float)):
                node[1] = False
            else:
                for v in node:
                    walk(v)
    r = copy.deepcopy(recipe)
    walk(r["payload"])
    r["payload"]["background"]["chebyshev"]["refine_flag"] = False
    return r


def simulation_recipe(template: dict, t_c: float) -> dict:
    r = _held(template)
    p = r["payload"]
    for k, v in INSTRUMENT.items():
        p["instrument"]["broadening"][k] = [v, False]
    p["background"]["chebyshev"]["coefficients"] = list(BACKGROUND)
    phase = p["phases"]["LaB6"]
    a = round(a_true(t_c), 6)
    for k in ("a", "b", "c"):
        phase["unit_cell"][k] = [a, False]
    for atom in ("La", "B"):
        phase["atoms"][atom]["Uiso"] = [round(uiso_true(atom, t_c), 6), False]
    phase["scale"] = [SCALE, False]
    tth = [x for x in template["payload"]["xrd_data"]["tth"] if 0.9 <= x <= 15.1]
    p["fit_range"] = [tth[0], tth[-1]]               # the whole kept grid, wider than the refinement window [1, 15]
    p["refinement_controls"] = {"refinement_cycles": 1}
    p["xrd_data"] = {"tth": tth, "Itth": [1.0] * len(tth), "Itth_weights": [1.0] * len(tth),
                     "filename": f"placeholder_{int(t_c):03d}C"}
    r["metadata"] = {"simulation": {"temperature_C": t_c, "a_true": a}}
    return r


def refinement_recipe(template: dict, data: dict) -> dict:
    """The first step's recipe: starts from the room-temperature SRM value, refines the cell (one tie group),
    the scale, the background and both Uiso; the instrument profile is known and held."""
    r = _held(template)
    p = r["payload"]
    for k, v in INSTRUMENT.items():
        p["instrument"]["broadening"][k] = [v, False]
    p["background"]["chebyshev"] = {"num_coefficients": 6, "coefficients": [30, 0, 0, 0, 0, 0], "refine_flag": True}
    phase = p["phases"]["LaB6"]
    for k in ("a", "b", "c"):
        phase["unit_cell"][k] = [4.15682, True]
    for atom in ("La", "B"):
        phase["atoms"][atom]["Uiso"] = [UISO_298[atom], True]
    phase["scale"] = [0.03, True]
    p["fit_range"] = [1, 15]
    p["refinement_controls"] = {"refinement_cycles": 5}
    p["xrd_data"] = data
    r["metadata"] = {"series": {"what": "simulated LaB6 heated in place; see DESCRIPTION.md and data/truth.json",
                                "first_temperature_C": TEMPERATURES_C[0]}}
    return r


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--work", type=Path, default=None, help="where the simulation runs write (default: a temp dir)")
    args = ap.parse_args(argv)
    work = args.work or Path(tempfile.mkdtemp(prefix="lab6_series_"))
    template = json.loads(TEMPLATE.read_text(encoding="utf-8-sig"))
    truth = {"source": "Akdoğan & Payzant, J. Appl. Cryst. 58 (2025) 1635: a(T) = A0 + XI dT + PSI dT^2, dT = T[K] - 298",
             "A0": A0, "XI": XI, "PSI": PSI, "Uiso_298K": UISO_298, "Uiso_model": "Uiso(T) = Uiso(298 K) * T[K] / 298",
             "instrument": INSTRUMENT, "background": BACKGROUND, "scale": SCALE, "seed": SEED,
             "noise": "Poisson counts on GSAS-II's calculated profile; weights 1/max(counts, 1)", "steps": []}
    for i, t_c in enumerate(TEMPERATURES_C):
        recipe = simulation_recipe(template, t_c)
        result = powderline.run(recipe, work / f"sim_{int(t_c):03d}C", execution_mode="subprocess")
        prof = result["fit_profile"]
        y = np.asarray(prof["y_calc"], dtype=float)
        tth = np.asarray(prof["two_theta"], dtype=float)
        assert np.all(np.isfinite(y)) and y.min() > 0, "the simulation must give a positive pattern everywhere"
        rng = np.random.default_rng(SEED + i)
        counts = rng.poisson(y).astype(float)
        weights = 1.0 / np.maximum(counts, 1.0)
        data = {"tth": [round(float(v), 7) for v in tth], "Itth": [float(v) for v in counts],
                "Itth_weights": [round(float(w), 9) for w in weights], "filename": f"simulated_LaB6_{int(t_c):03d}C"}
        (HERE / "data" / f"lab6_{int(t_c):03d}C.json").write_text(json.dumps(data, separators=(",", ":")) + "\n", encoding="utf-8")
        truth["steps"].append({"temperature_C": t_c, "a": round(a_true(t_c), 6),
                               "Uiso": {k: round(uiso_true(k, t_c), 6) for k in UISO_298},
                               "points": int(len(tth)), "max_counts": float(counts.max())})
        print(f"{t_c:4d} C  a {a_true(t_c):.6f}  Uiso La {uiso_true('La', t_c):.5f}  points {len(tth)}  "
              f"max counts {counts.max():.0f}  Rwp(placeholder) {result['rwp']:.1f}")
        if i == 0:
            (HERE / "input.json").write_text(json.dumps(refinement_recipe(template, data), indent=2) + "\n", encoding="utf-8")
    (HERE / "data" / "truth.json").write_text(json.dumps(truth, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {len(TEMPERATURES_C)} patterns, data/truth.json and input.json; runs in {work}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
