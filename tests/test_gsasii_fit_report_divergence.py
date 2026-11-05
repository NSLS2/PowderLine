"""re/29 (EB-99): a Rietveld refinement GSAS-II *aborted* (``Rvals['Aborted']``: its damping reached its limit; the
starting values stay, the finite pattern is worthless, wR prints 100 %) is a ``diverged`` failure -- EB-52's other face,
which the non-finite check does not see. A poor but honest fit (wR at the cap, no abort) and a simulation (one cycle,
nothing refined) are not failures (engine-free)."""
from types import SimpleNamespace

import numpy as np
import pytest

from powderline.exceptions import EngineExecutionError
from powderline.gateways.gsasii.fit_report import fit_report

pytestmark = pytest.mark.core


def _hist(n=50, ycalc=1e9):
    x = np.linspace(1.0, 15.0, n); yobs = np.full(n, 100.0); w = np.full(n, 0.01)
    return SimpleNamespace(data={"data": [None, [x, yobs, w, np.full(n, ycalc)]], "Limits": [None, [1.0, 15.0]], "Peak List": {}})


def _recipe(cycles):
    return SimpleNamespace(schema_name="gsasii.rietveld",
                           payload=SimpleNamespace(refinement_controls=SimpleNamespace(refinement_cycles=cycles)))


def _proj(**rvals):
    base = {"Rwp": 100.0, "GOF": 7e19, "Nvars": 1, "converged": False}
    return SimpleNamespace(data={"Covariance": {"data": {"varyList": ["0:0:MD"], "sig": [1.0], "Rvals": {**base, **rvals}}}})


def test_an_aborted_refinement_is_a_divergence():
    with pytest.raises(EngineExecutionError) as info:
        fit_report(_proj(Aborted=True, lamMax=10.0), _hist(), _recipe(5), engine_rwp=100.0)
    assert info.value.reason == "diverged" and "aborted" in str(info.value) and "100 %" in str(info.value)


def test_a_poor_fit_at_the_cap_without_an_abort_is_reported():
    out = fit_report(_proj(), _hist(ycalc=300.0), _recipe(5), engine_rwp=100.0)
    assert out["engine_details"]["converged"] is False and out["rwp"] > 100


def test_a_simulation_is_never_aborted():
    out = fit_report(_proj(Aborted=True), _hist(), _recipe(1), engine_rwp=100.0)
    assert out["simulation_mode"] is True
