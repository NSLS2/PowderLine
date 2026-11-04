"""The committed easydiffraction example references against the native goldens (engine-free).

``examples/example_DRX_33/easydiffraction/input.json`` and
``examples/example_LaB6/easydiffraction/input.json`` are byte-for-byte copies of
native fixtures whose goldens live under
``tests/data/easydiffraction/native/golden/`` (``tests/test_easydiffraction_native.py``
runs the engine against them). The reference tables committed under
``examples/<case>/easydiffraction/output/`` come from a run of the same recipe, so
they must agree with the golden within the goldens' own cross-build tolerances;
this keeps the two from drifting apart without a second engine run.
"""
import csv
import json
from pathlib import Path

import numpy as np
import pytest

pytestmark = pytest.mark.core

REPO = Path(__file__).resolve().parent.parent
EXAMPLES = REPO / "examples"
NATIVE = REPO / "tests" / "data" / "easydiffraction" / "native"

#: The goldens' tolerances (tests/test_easydiffraction_native.py, GOLDEN_RTOL, GOLDEN_CELL_RTOL,
#: GOLDEN_ESD_FRACTION; that module needs the engine, so they are restated here).
GOLDEN_RTOL, GOLDEN_CELL_RTOL, GOLDEN_ESD_FRACTION = 1e-3, 1e-4, 1e-2

#: (example, fixture, start-dependent): a CrysFML refinement stops at start-dependent points (EB-90), so for
#: it only what does not depend on the stop is compared (refined names, the cell within 1e-4), as for its golden.
CASES = [("example_DRX_33", "drx33_two_phase_cryspy.json", False),
         ("example_LaB6", "lab6_crysfml_tch.json", True)]


def _rows(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _float(text):
    return float(text) if text not in ("", None) else None


@pytest.mark.parametrize("case, fixture, start_dependent", CASES, ids=[c[0] for c in CASES])
def test_example_reference_agrees_with_the_golden(case, fixture, start_dependent):
    leg = EXAMPLES / case / "easydiffraction"
    out = leg / "output"
    assert (leg / "input.json").read_bytes() == (NATIVE / fixture).read_bytes(), "the recipe is no longer the fixture"
    gold = json.loads((NATIVE / "golden" / fixture).read_text(encoding="utf-8"))["run"]

    refined = {r["parameter_name"]: (float(r["value"]), _float(r["esd"]))
               for r in _rows(out / "refined_parameters.csv")}
    assert list(refined) == list(gold["refined"])

    for phase, rows in gold["unit_cell"].items():
        got = _rows(out / f"{phase}_unit_cell_report.csv")
        assert [r["parameter"] for r in got] == [g["parameter"] for g in rows]
        for g, r in zip(rows, got):
            assert float(r["value"]) == pytest.approx(g["value"], rel=GOLDEN_CELL_RTOL), (phase, g["parameter"])

    recipe = json.loads((out / "output_recipe.json").read_text(encoding="utf-8"))
    assert recipe["metadata"]["powderline_provenance"]["engine_version"] == "0.21.1"
    if start_dependent:
        return

    for name, (value, esd) in gold["refined"].items():
        floor = GOLDEN_ESD_FRACTION * esd if esd is not None else 1e-12
        assert refined[name][0] == pytest.approx(value, rel=GOLDEN_RTOL, abs=floor), name
        assert (refined[name][1] is None) == (esd is None), name
        if esd is not None:
            assert refined[name][1] == pytest.approx(esd, rel=GOLDEN_RTOL), name

    # The uniform Rwp (core fitstats) recomputed from the committed fit profile over the stated window.
    from powderline.fitstats import compute_fit_statistics
    profile = np.loadtxt(out / "fit_profile.txt", skiprows=1, delimiter="\t")
    lo, hi = recipe["payload"]["fit_range"]
    mask = (profile[:, 0] >= lo) & (profile[:, 0] <= hi)
    stats = compute_fit_statistics(profile[:, 1], profile[:, 3], profile[:, 2], len(refined), mask=mask)
    assert stats.rwp == pytest.approx(gold["rwp"], rel=GOLDEN_RTOL)
