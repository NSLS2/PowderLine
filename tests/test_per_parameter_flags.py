"""Integration tests: per-parameter refine flags honored end-to-end (gsasii.rietveld).

A recipe that requests a subset of a lumped GSAS-II parameter class must
refine exactly that subset — verified against the actual post-refinement
varyList and the held values in the saved project.

These tests run real GSAS-II refinements on small synthetic patterns; the fit
quality is irrelevant (the data are featureless), only the constraint
machinery is under test. The recipes are native ``gsasii.rietveld`` 0.1.0
(re/07 H; until then the same probes ran on the 0.26.0 path): a cell flag is
stated per GSAS-II cell group (A95: tetragonal ``a`` and ``b`` refine together),
every value is stated with its flag.
"""
import numpy as np
import pytest

pytestmark = [pytest.mark.gsasii, pytest.mark.slow]

G2 = pytest.importorskip("GSASII.GSASIIscriptable")
from powderline.gateways.gsasii.routing import run_refinement  # noqa: E402
from powderline.gateways.gsasii.schema import validate_recipe  # noqa: E402


def P(value, flag=False):
    return [value, flag]


def make_recipe(space_group, cell, atoms, cell_flags=None):
    """Minimal valid gsasii.rietveld recipe around a synthetic pattern.

    ``cell`` = (a, b, c, alpha, beta, gamma); ``cell_flags`` names the cell
    parameters to refine; ``atoms`` is the native atoms block.
    """
    tth = np.arange(5.0, 90.0, 0.05)
    y = 100.0 + 10.0 * np.sin(tth / 5.0)
    w = 1.0 / np.sqrt(np.maximum(y, 1.0))
    names = ("a", "b", "c", "alpha", "beta", "gamma")
    flags = set(cell_flags or ())
    return {
        "schema_name": "gsasii.rietveld",
        "core_schema_version": "0.1.0",
        "engine_schema_version": "0.1.0",
        "payload": {
            "xrd_data": {"tth": tth.tolist(), "Itth": y.tolist(), "Itth_weights": w.tolist()},
            "instrument": {
                "description": "synthetic CW instrument",
                "radiation": {"type": "PXC", "wavelength": P(1.5406)},
                "geometry": {"bank": 1, "azimuth": 0.0},
                "corrections": {"zero_shift": P(0.0), "polarization": P(0.7), "axial_divergence": P(0.002)},
                "broadening": {"U": P(2.0), "V": P(-2.0), "W": P(5.0), "X": P(0.0), "Y": P(0.0), "Z": P(0.0)},
            },
            "phases": {
                "P": {
                    "space_group": space_group,
                    "unit_cell": {name: P(value, name in flags) for name, value in zip(names, cell)},
                    "atoms": atoms,
                    "scale": P(1.0),
                }
            },
            "refinement_controls": {"refinement_cycles": 2},
        },
    }


def uiso_atom(element, x, y, z, refine=()):
    """A Uiso atom; ``refine`` names the coordinates flagged for refinement."""
    return {"element": element, "x": P(x, "x" in refine), "y": P(y, "y" in refine), "z": P(z, "z" in refine),
            "occupancy": P(1.0), "ADP": "Uiso", "Uiso": P(0.01)}


def run(recipe_dict, tmp_path):
    model = validate_recipe(recipe_dict)
    result = run_refinement(model, tmp_path, verbose=False, method="subprocess")
    assert result["success"], f"refinement failed: {result.get('error')}"  # the frozen executor's own dict (run_refinement directly)
    gpx = G2.G2Project(str(tmp_path / "dummy.gpx"))
    vary = list(gpx.data["Covariance"]["data"].get("varyList", []))
    return result, gpx, vary


def test_tetragonal_refine_a_hold_c(tmp_path):
    """Recipe-level probe2: a (with its tied b) true, c false -> A0 varies, A2 held, c unchanged."""
    atoms = {"Ba": uiso_atom("Ba", 0.0, 0.0, 0.0)}
    recipe = make_recipe("P 4/m m m", (3.90, 3.90, 4.50, 90, 90, 90), atoms, cell_flags=("a", "b"))
    result, gpx, vary = run(recipe, tmp_path)

    assert "0::A0" in vary
    assert "0::A2" not in vary
    final_cell = gpx.data["Phases"]["P"]["General"]["Cell"]
    assert final_cell[3] == pytest.approx(4.50, abs=1e-9)   # c held exactly
    assert final_cell[1] != pytest.approx(3.90, abs=1e-12)  # a actually refined


def test_tetragonal_refine_c_hold_a(tmp_path):
    """Holding the equivalence-independent A0 cascades to A1; only c refines."""
    atoms = {"Ba": uiso_atom("Ba", 0.0, 0.0, 0.0)}
    recipe = make_recipe("P 4/m m m", (3.90, 3.90, 4.50, 90, 90, 90), atoms, cell_flags=("c",))
    result, gpx, vary = run(recipe, tmp_path)

    assert "0::A2" in vary
    assert "0::A0" not in vary
    final_cell = gpx.data["Phases"]["P"]["General"]["Cell"]
    assert final_cell[1] == pytest.approx(3.90, abs=1e-9)   # a held exactly


def test_p1_refine_x_only(tmp_path):
    """Recipe-level probe3: x=true, y/z=false -> only dAx varies; y,z unchanged."""
    atoms = {
        "Na": uiso_atom("Na", 0.111, 0.222, 0.333, refine=("x",)),
        "Cl": uiso_atom("Cl", 0.611, 0.522, 0.733),
    }
    recipe = make_recipe("P 1", (5.0, 6.0, 7.0, 88.0, 92.0, 95.0), atoms)
    result, gpx, vary = run(recipe, tmp_path)

    assert "0::dAx:0" in vary
    assert "0::dAy:0" not in vary
    assert "0::dAz:0" not in vary
    na = gpx.data["Phases"]["P"]["Atoms"][0]
    assert na[4] == pytest.approx(0.222, abs=1e-12)  # y held
    assert na[5] == pytest.approx(0.333, abs=1e-12)  # z held


def test_p1_refine_single_uij_component(tmp_path):
    """Recipe-level probe5: U11=true, others=false -> only AU11 varies."""
    atoms = {
        "W": {"element": "W", "x": P(0.2), "y": P(0.3), "z": P(0.4), "occupancy": P(1.0), "ADP": "Uaniso",
              "Uaniso": {"U11": P(0.011, True), "U22": P(0.012), "U33": P(0.013),
                         "U12": P(0.001), "U13": P(0.002), "U23": P(0.003)}},
    }
    recipe = make_recipe("P 1", (5.0, 6.0, 7.0, 88.0, 92.0, 95.0), atoms)
    result, gpx, vary = run(recipe, tmp_path)

    au_varied = [v for v in vary if "::AU" in v]
    assert au_varied == ["0::AU11:0"]
    w = gpx.data["Phases"]["P"]["Atoms"][0]
    # indices 12..16 = U22, U33, U12, U13, U23 — all held at input values
    assert w[12] == pytest.approx(0.012, abs=1e-12)
    assert w[13] == pytest.approx(0.013, abs=1e-12)
    assert w[14] == pytest.approx(0.001, abs=1e-12)
    assert w[15] == pytest.approx(0.002, abs=1e-12)
    assert w[16] == pytest.approx(0.003, abs=1e-12)


def test_uniform_flags_unchanged_behavior(tmp_path):
    """All symmetry-linked flags true -> whole cell refines, no holds."""
    atoms = {"Ba": uiso_atom("Ba", 0.0, 0.0, 0.0)}
    recipe = make_recipe("P 4/m m m", (3.90, 3.90, 4.50, 90, 90, 90), atoms, cell_flags=("a", "b", "c"))
    result, gpx, vary = run(recipe, tmp_path)

    assert "0::A0" in vary and "0::A2" in vary
    assert gpx.data["Constraints"]["data"]["Phase"] == []  # no holds emitted
