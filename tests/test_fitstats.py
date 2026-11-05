"""Unit tests for powderline.fitstats (uniform Rwp / Rexp / GoF / reduced χ²).

Pure tests: no engine. Synthetic cases are hand-computed; the LaB6 case
characterizes (does not assert equality with) GSAS-II's own reported values.
"""
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from powderline.fitstats import FitStatistics, compute_fit_statistics

pytestmark = pytest.mark.core

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def test_hand_computed_case():
    # yobs=[10,20,30,40], ycalc=[11,19,30,42], w=[1,0.5,0.25,0.1], P=1
    #   Σw·yobs²       = 100 + 200 + 225 + 160 = 685
    #   Σw·(yobs−ycalc)² = 1 + 0.5 + 0 + 0.4   = 1.9
    #   N = 4, N−P = 3
    s = compute_fit_statistics([10, 20, 30, 40], [11, 19, 30, 42], [1, 0.5, 0.25, 0.1], 1)
    assert s.rwp == pytest.approx(100 * math.sqrt(1.9 / 685))
    assert s.rexp == pytest.approx(100 * math.sqrt(3 / 685))
    assert s.chi2_red == pytest.approx(1.9 / 3)
    assert s.gof == pytest.approx(math.sqrt(1.9 / 3))
    assert s.gof == pytest.approx(s.rwp / s.rexp)
    assert (s.n_points, s.n_params) == (4, 1)


def test_perfect_fit_is_zero():
    s = compute_fit_statistics([1.0, 2.0, 3.0], [1.0, 2.0, 3.0], [1, 1, 1], 0)
    assert s.rwp == 0.0 and s.gof == 0.0 and s.chi2_red == 0.0
    assert s.rexp == pytest.approx(100 * math.sqrt(3 / 14))


def test_mask_and_zero_weights_are_excluded_from_n_and_sums():
    base = compute_fit_statistics([10, 20], [11, 19], [1, 0.5], 1)
    padded = compute_fit_statistics(
        [10, 20, 999, 5], [11, 19, 0, 7], [1, 0.5, 1, 0], 1,
        mask=[True, True, False, True],  # point 2 out of range; point 3 has w=0
    )
    assert padded == base
    assert padded.n_points == 2


def test_undefined_values_are_nan():
    s = compute_fit_statistics([1.0, 2.0], [1.5, 2.5], [1, 1], 2)  # N − P = 0
    assert s.rwp == pytest.approx(100 * math.sqrt(0.5 / 5))
    assert math.isnan(s.rexp) and math.isnan(s.gof) and math.isnan(s.chi2_red)
    z = compute_fit_statistics([0.0, 0.0], [1.0, 1.0], [1, 1], 0)  # Σw·yobs² = 0
    assert math.isnan(z.rwp) and math.isnan(z.rexp)
    assert z.chi2_red == pytest.approx(1.0)


@pytest.mark.parametrize("kwargs, match", [
    (dict(yobs=[1, 2], ycalc=[1], weights=[1, 1], n_params=0), "equal length"),
    (dict(yobs=[1, 2], ycalc=[1, 2], weights=[1, -1], n_params=0), ">= 0"),
    (dict(yobs=[1, 2], ycalc=[1, 2], weights=[1, 1], n_params=-1), "non-negative integer"),
    (dict(yobs=[1, 2], ycalc=[1, 2], weights=[1, 1], n_params=1.5), "non-negative integer"),
    (dict(yobs=[1, np.nan], ycalc=[1, 2], weights=[1, 1], n_params=0), "finite"),
    (dict(yobs=[1, 2, 3], ycalc=[1, 2, 3], weights=[1, np.nan, 1], n_params=0), "finite"),
    (dict(yobs=[1, 2], ycalc=[1, 2], weights=[1, np.inf], n_params=0), "finite"),
    (dict(yobs=[1, 2], ycalc=[1, 2], weights=[1, 1], n_params=0, mask=[True]), "mask"),
])
def test_invalid_input_raises(kwargs, match):
    with pytest.raises(ValueError, match=match):
        compute_fit_statistics(**kwargs)


def test_non_finite_outside_fit_range_is_ignored():
    s = compute_fit_statistics([1.0, np.nan], [1.0, 0.0], [1, 1], 0, mask=[True, False])
    assert s.n_points == 1


def test_result_is_frozen():
    s = compute_fit_statistics([1.0], [1.0], [1.0], 0)
    assert isinstance(s, FitStatistics)
    with pytest.raises(AttributeError):
        s.rwp = 1.0


def test_lab6_characterization_vs_gsasii():
    """Characterize (not assert equality with) GSAS-II on the committed LaB6 fit.

    Inputs: ``examples/example_LaB6/output/fit_profile.txt`` (4096 points, values
    rounded to 8 decimals; the native-path reference of re/07), fit range
    [1, 15]° 2θ from the recipe, P = 13 from ``dummy.lst`` ("No. of parameters: 13";
    the recipe lost its four background-peak terms, P-01).

    GSAS-II (``dummy.lst``): wR = 6.53 %, wRmin = 12.48 %, GOF = 0.52,
    chi**2 = 1033.08, 3767 observations.
    PowderLine fitstats:     Rwp = 6.5345 %, Rexp = 12.456 %, GoF = 0.5246,
    N = 3767.

    How and why they differ (A23):
    - Rwp and GoF agree to the reported precision.
    - N agrees since re/05 (A149): the native path gives GSAS-II the first and
      last weighted points inside [1, 15] as its limits, so its slice is the
      inclusive mask used here (v0.1.1 counted one point more, EB-54).
    - Rexp vs GSAS-II ``wRmin``: GSAS-II's ``wRmin`` = sqrt(N / Σw·yobs²), i.e.
      it does **not** subtract P; fitstats uses the standard sqrt((N − P) /
      Σw·yobs²). sqrt(3767/3754) accounts for the 12.48 vs 12.456 gap.
    - GSAS-II's ``chi**2`` is the un-reduced Σw·(yobs − ycalc)²; χ²_red here is
      that sum divided by (N − P).
    """
    recipe = json.loads((EXAMPLES / "example_LaB6" / "input.json").read_text(encoding="utf-8"))
    lo, hi = recipe["payload"]["fit_range"]
    prof = pd.read_csv(EXAMPLES / "example_LaB6" / "output" / "fit_profile.txt", sep="\t")
    tth = prof["two_theta"].to_numpy()
    s = compute_fit_statistics(prof["y_obs"], prof["y_calc"], prof["y_weights"], 13,
                               mask=(tth >= lo) & (tth <= hi))
    assert s.n_points == 3767
    assert s.rwp == pytest.approx(6.5345, abs=0.0005)
    assert s.gof == pytest.approx(0.5246, abs=0.0005)
    assert s.rexp == pytest.approx(12.456, abs=0.0005)
    assert s.chi2_red * (3767 - 13) == pytest.approx(1033.08, abs=0.01)  # GSAS-II's un-reduced chi**2
    # GSAS-II's wRmin omits P: reproduce it from the same sums to prove the claim.
    gsas_wrmin = s.rexp * math.sqrt(3767 / (3767 - 13))
    assert gsas_wrmin == pytest.approx(12.48, abs=0.005)
