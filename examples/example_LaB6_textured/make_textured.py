"""Simulate the textured LaB6 pattern this example refines (GSAS-II, one-cycle ``gsasii.rietveld`` run).

LaB6 powders do not texture; this is a **mathematical demonstration** of PowderLine's March-Dollase preferred
orientation (P-48, re/29) on the one well-conditioned phase in the examples. Truth: the ``example_LaB6`` structure
with March-Dollase r = 0.6 along [001] (platy), the *original* ``example_LaB6`` instrument profile (U 18.72,
V 0.600, W 1.147, X 0.281, Y 0.001, Z 0 centideg -- a profile every engine can represent, EB-93), the committed
refinement's background and scale, Poisson counting noise (fixed seed) on the measured 28-ID-1 grid.

Writes ``data/lab6_textured.json`` (the ``xrd_data`` block), ``data/truth.json`` and ``input.json`` (the
refinement recipe: r starts at 0.8, on the platy side -- see the note in ``refinement_recipe``). Run in the gsasii environment:

    pixi run -e gsasii python examples/example_LaB6_textured/make_textured.py
"""
from __future__ import annotations

import copy
import json
import sys
import tempfile
from pathlib import Path

import numpy as np

import powderline

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE.parent / "example_LaB6" / "input.json"
SEED = 20261021
R_TRUE, AXIS = 0.6, [0, 0, 1]
PROFILE = {"U": 18.71740850558368, "V": 0.6003411256329596, "W": 1.1470130081855334, "X": 0.28143034323339766, "Y": 0.001, "Z": 0.0}
BACKGROUND = [30.02431, 1.362780, 1.178665, -1.426545, 0.5206805, 0.3164668]
SCALE = 0.03773081


def _held(recipe: dict) -> dict:
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


def simulation_recipe(template: dict) -> dict:
    r = _held(template)
    p = r["payload"]
    for k, v in PROFILE.items():
        p["instrument"]["broadening"][k] = [v, False]
    p["background"]["chebyshev"]["coefficients"] = list(BACKGROUND)
    phase = p["phases"]["LaB6"]
    phase["scale"] = [SCALE, False]
    phase["preferred_orientation"] = {"model": "march_dollase", "hkl": list(AXIS), "ratio": [R_TRUE, False]}
    tth = [x for x in template["payload"]["xrd_data"]["tth"] if 0.9 <= x <= 15.1]
    p["fit_range"] = [tth[0], tth[-1]]
    p["refinement_controls"] = {"refinement_cycles": 1}
    p["xrd_data"] = {"tth": tth, "Itth": [1.0] * len(tth), "Itth_weights": [1.0] * len(tth), "filename": "placeholder"}
    r["metadata"] = {"simulation": {"march_dollase_r": R_TRUE, "axis": AXIS}}
    return r


def refinement_recipe(template: dict, data: dict) -> dict:
    """The refinement: r from 0.8 (platy side, see below), scale and background free; the cell, the atoms and the profile
    (the simulation's own) held -- the question the example asks is "is r recovered?"."""
    r = _held(template)
    p = r["payload"]
    for k, v in PROFILE.items():
        p["instrument"]["broadening"][k] = [v, False]
    p["background"]["chebyshev"] = {"num_coefficients": 6, "coefficients": [30, 0, 0, 0, 0, 0], "refine_flag": True}
    phase = p["phases"]["LaB6"]
    phase["scale"] = [0.03, True]
    # start on the platy side, not at exactly 1.0: in a cubic phase the averaged correction is stationary at r = 1 and
    # GSAS-II aborts (reported as `diverged`); from 1.2 it settles on the needle-side minimum r = 1.73 (EB-99)
    phase["preferred_orientation"] = {"model": "march_dollase", "hkl": list(AXIS), "ratio": [0.8, True]}
    p["fit_range"] = [1, 15]
    p["refinement_controls"] = {"refinement_cycles": 5}
    p["xrd_data"] = data
    r["metadata"] = {"textured": {"what": "simulated LaB6 with March-Dollase r = 0.6 along [001]; a mathematical demonstration (LaB6 does not texture); see DESCRIPTION.md and data/truth.json"}}
    return r


def main() -> int:
    work = Path(tempfile.mkdtemp(prefix="lab6_textured_"))
    template = json.loads(TEMPLATE.read_text(encoding="utf-8-sig"))
    result = powderline.run(simulation_recipe(template), work / "sim", execution_mode="subprocess")
    prof = result["fit_profile"]
    y = np.asarray(prof["y_calc"], dtype=float); tth = np.asarray(prof["two_theta"], dtype=float)
    assert np.all(np.isfinite(y)) and y.min() > 0
    counts = np.random.default_rng(SEED).poisson(y).astype(float)
    data = {"tth": [round(float(v), 7) for v in tth], "Itth": [float(v) for v in counts],
            "Itth_weights": [round(float(1 / max(c, 1.0)), 9) for c in counts], "filename": "simulated_LaB6_textured_r0.6_001"}
    (HERE / "data" / "lab6_textured.json").write_text(json.dumps(data, separators=(",", ":")) + "\n", encoding="utf-8")
    (HERE / "data" / "truth.json").write_text(json.dumps({
        "march_dollase_r": R_TRUE, "axis": AXIS, "convention": "IUCr / GSAS-II: 1 random, < 1 platy, > 1 needle",
        "profile": PROFILE, "background": BACKGROUND, "scale": SCALE, "seed": SEED, "points": int(len(tth)),
        "max_counts": float(counts.max()),
        "noise": "Poisson counts on GSAS-II's calculated profile; weights 1/max(counts, 1)"}, indent=2) + "\n", encoding="utf-8")
    (HERE / "input.json").write_text(json.dumps(refinement_recipe(template, data), indent=2) + "\n", encoding="utf-8")
    print(f"textured LaB6: r={R_TRUE} along {AXIS}, {len(tth)} points, max counts {counts.max():.0f}; runs in {work}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
