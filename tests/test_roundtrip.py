"""The output recipe (KI-04, P-43): every parameter leaf, tie propagation, the multiplicity invariant,
dispositions, validity, provenance. Engine-free: real gateway schemas, no engine run."""
import copy
import json
from pathlib import Path

import pytest

from powderline import roundtrip
from powderline.api import validate
from powderline.schema_core import collect_warnings

pytestmark = pytest.mark.core

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def _load(rel):
    return json.loads((EXAMPLES / rel).read_text(encoding="utf-8-sig"))


def _hex_recipe():
    """A gsasii.rietveld recipe with one hexagonal phase: 'C' on the (x, 2x, 1/4) site of P 63/m m c."""
    r = _load("example_LaB6/input.json")
    p = lambda v, f=False: [v, f]  # noqa: E731
    r["payload"]["phases"] = {"Gr": {
        "space_group": "P 63/m m c", "scale": p(0.01, True),
        "unit_cell": {"a": p(2.46, True), "b": p(2.46, True), "c": p(6.71, True),
                      "alpha": p(90.0), "beta": p(90.0), "gamma": p(120.0)},
        "atoms": {"C": {"element": "C", "x": p(1 / 6, True), "y": p(1 / 3, True), "z": p(0.25),
                        "occupancy": p(1.0), "ADP": "Uiso", "Uiso": p(0.005, True)}},
    }}
    return r


def _paths(model):
    return {pp.path: pp for pp in roundtrip.parameter_paths(model)}


def test_parameter_paths_lists_every_leaf():
    model = validate(_load("example_LaB6/input.json")).recipe
    paths = _paths(model)
    assert "payload.phases.LaB6.unit_cell.a" in paths and "payload.instrument.broadening.U" in paths
    cheb = [p for p in paths if p.startswith("payload.background.chebyshev.coefficients.")]
    assert len(cheb) == model.payload.background.chebyshev.num_coefficients
    assert paths["payload.background.chebyshev.coefficients.0"].refine_flag == model.payload.background.chebyshev.refine_flag
    assert paths["payload.phases.LaB6.atoms.B.x"].tie == "fixed"  # La on 1a: every coordinate fixed


def test_tie_classification_cell_and_site():
    paths = _paths(validate(_hex_recipe()).recipe)
    cell = "payload.phases.Gr.unit_cell."
    assert paths[cell + "a"].tie == "representative" and paths[cell + "b"].tie == "member"
    assert paths[cell + "b"].relation[:2] == (1, 0) and paths[cell + "b"].relation[2] == cell + "a"
    assert paths[cell + "c"].tie == "free" and paths[cell + "gamma"].tie == "fixed"
    site = "payload.phases.Gr.atoms.C."
    assert paths[site + "x"].tie == "representative" and paths[site + "y"].tie == "member"
    assert paths[site + "y"].relation[:2] == (2, 0) and paths[site + "z"].tie == "fixed"


def test_build_output_sets_values_and_propagates_the_cell():
    r = _load("example_LaB6/input.json")
    for k in ("a", "b", "c"):
        r["payload"]["phases"]["LaB6"]["unit_cell"][k][1] = True  # refine the cubic cell (one tie group)
    model = validate(r).recipe
    out = roundtrip.build_output(model, {"payload.phases.LaB6.unit_cell.a": (4.2, 1e-4)}, parent_run_id="r1")
    cell = out.recipe["payload"]["phases"]["LaB6"]["unit_cell"]
    assert cell["a"][0] == cell["b"][0] == cell["c"][0] == 4.2 and cell["a"][1] is True
    assert out.valid, out.problems
    rows = {r["path"]: r for r in out.dispositions}
    assert rows["payload.phases.LaB6.unit_cell.a"]["disposition"] == "varied"
    assert rows["payload.phases.LaB6.unit_cell.a"]["esd"] == 1e-4
    assert rows["payload.phases.LaB6.unit_cell.b"]["disposition"] == "held_by_symmetry"
    assert rows["payload.phases.LaB6.unit_cell.alpha"]["disposition"] == "held_by_symmetry"


def test_half_updated_coordinate_tie_is_propagated():
    """Validation would accept x moved alone as a general position of double multiplicity (probe 2026-10-19);
    the output must carry y = 2x and keep the multiplicity."""
    model = validate(_hex_recipe()).recipe
    out = roundtrip.build_output(model, {"payload.phases.Gr.atoms.C.x": (0.17, 1e-3)})
    atom = out.recipe["payload"]["phases"]["Gr"]["atoms"]["C"]
    assert atom["x"][0] == 0.17 and atom["y"][0] == pytest.approx(0.34) and atom["z"][0] == 0.25
    assert out.valid, out.problems
    assert validate(out.recipe).recipe.payload.phases["Gr"].site("C").multiplicity == model.payload.phases["Gr"].site("C").multiplicity


def test_disagreeing_tie_member_is_invalid():
    model = validate(_hex_recipe()).recipe
    out = roundtrip.build_output(model, {"payload.phases.Gr.atoms.C.x": (0.17, None), "payload.phases.Gr.atoms.C.y": (0.30, None)})
    assert not out.valid and any("C" in p and "y" in p for p in out.problems)


def test_unphysical_value_is_written_but_invalid():
    model = validate(_load("example_LaB6/input.json")).recipe
    out = roundtrip.build_output(model, {"payload.phases.LaB6.atoms.B.occupancy": (1.3, 0.1)})
    assert out.recipe["payload"]["phases"]["LaB6"]["atoms"]["B"]["occupancy"][0] == 1.3
    assert not out.valid and any("occupancy" in p for p in out.problems)


def test_dispositions_precedence_and_at_limit():
    r = _load("example_LaB6/input.json")
    r["payload"]["phases"]["LaB6"]["peak_broadening"] = {}  # defaults applied
    model = validate(r).recipe
    scale = "payload.phases.LaB6.scale"
    out = roundtrip.build_output(model, {scale: (0.5, 0.01)}, not_varied={"payload.instrument.broadening.U"},
                                 at_limit={scale})
    rows = {x["path"]: x for x in out.dispositions}
    assert rows["payload.phases.LaB6.peak_broadening.size_broadening.isotropic_size"]["disposition"] == "default_applied"
    assert rows[scale]["disposition"] == "varied" and rows[scale]["at_limit"] is True
    assert rows["payload.instrument.broadening.U"]["disposition"] == "requested_not_varied"
    assert rows["payload.instrument.radiation.wavelength"]["disposition"] == "held_by_user"
    assert set(r["disposition"] for r in out.dispositions) <= set(roundtrip.DISPOSITIONS)


def test_provenance_block_and_untouched_metadata():
    r = _load("example_LaB6/input.json")
    r["metadata"] = {"sample": "LaB6 NIST"}
    out = roundtrip.build_output(validate(r).recipe, {}, parent_run_id="run-7")
    prov = out.recipe["metadata"]["powderline_provenance"]
    assert prov["parent_run_id"] == "run-7" and prov["schema_name"] == "gsasii.rietveld" and "created" in prov
    assert prov["engine"] == "gsasii" and prov["engine_version"] is None      # A191: no run, no engine version
    ran = roundtrip.build_output(validate(r).recipe, {}, parent_run_id="run-8", engine_version="5.7.9")
    assert ran.recipe["metadata"]["powderline_provenance"]["engine_version"] == "5.7.9"
    assert out.recipe["metadata"]["sample"] == "LaB6 NIST"
    assert out.recipe["payload"]["xrd_data"] == r["payload"]["xrd_data"]


@pytest.mark.parametrize("rel", sorted(p.relative_to(EXAMPLES).as_posix() for p in EXAMPLES.glob("*/**/input.json")
                                       if "example_template" not in p.parts))
def test_output_recipe_revalidates_silently(rel):
    out = roundtrip.build_output(validate(_load(rel)).recipe, {})
    assert out.valid, out.problems
    again = validate(out.recipe)
    assert not [w for w in again.warnings if w["code"] == "symmetry_value_derived" or w["code"].endswith("_default_applied")]
    assert again.recipe.model_dump(mode="json") == out.recipe


def test_attach_writes_files_and_flags_invalid(tmp_path):
    model = validate(_load("example_LaB6/input.json")).recipe
    good = roundtrip.attach({"warnings": [], "output_files": []}, roundtrip.build_output(model, {}), tmp_path)
    assert good["output_recipe_valid"] is True and good["output_recipe"]["schema_name"] == "gsasii.rietveld"
    assert (tmp_path / "output_recipe.json").exists() and (tmp_path / "parameter_dispositions.csv").exists()
    assert str(tmp_path / "output_recipe.json") in good["output_files"]
    assert list(good["parameter_dispositions"].columns) == list(roundtrip.DISPOSITION_COLUMNS)
    bad = roundtrip.attach({"warnings": []}, roundtrip.build_output(model, {"payload.phases.LaB6.atoms.B.occupancy": (1.3, None)}))
    assert bad["output_recipe_valid"] is False and bad["warnings"][-1]["code"] == "output_recipe_not_valid"



def test_engine_value_for_a_held_parameter_is_a_problem():
    """A gateway must only report what the user let the engine vary; a changed held value is not hidden."""
    model = validate(_load("example_LaB6/input.json")).recipe  # the cell is held (flags false)
    out = roundtrip.build_output(model, {"payload.phases.LaB6.unit_cell.a": (4.2, None)})
    assert not out.valid and any("held" in p and "unit_cell.a" in p for p in out.problems)


# --- re/20a review: exact tie arithmetic, member-only reports, readable problems ---------------------------

def _recipe_with_phase(space_group, atoms, cell):
    r = _load("example_LaB6/input.json")
    p = lambda v, f=False: [v, f]  # noqa: E731
    r["payload"]["phases"] = {"Ph": {"space_group": space_group, "scale": p(0.01, True),
                                     "unit_cell": {k: p(v, k in ("a", "b", "c")) for k, v in cell.items()}, "atoms": atoms}}
    return r


def test_uij_tie_with_k_not_one_is_exact():
    """P 63/m m c 2c site (1/3, 2/3, 1/4): U22 = U11, U12 = U11/2, U13 = U23 = 0 — refined U11 drives the rest exactly."""
    p = lambda v, f=False: [v, f]  # noqa: E731
    atoms = {"C": {"element": "C", "x": p(1 / 3), "y": p(2 / 3), "z": p(0.25), "occupancy": p(1.0), "ADP": "Uaniso",
                   "Uaniso": {"U11": p(0.01, True), "U22": p(0.01, True), "U33": p(0.02, True),
                              "U12": p(0.005, True), "U13": p(0.0), "U23": p(0.0)}}}
    cell = {"a": 2.46, "b": 2.46, "c": 6.71, "alpha": 90.0, "beta": 90.0, "gamma": 120.0}
    model = validate(_recipe_with_phase("P 63/m m c", atoms, cell)).recipe
    out = roundtrip.build_output(model, {"payload.phases.Ph.atoms.C.Uaniso.U11": (0.0123, 1e-4),
                                         "payload.phases.Ph.atoms.C.Uaniso.U33": (0.0211, 1e-4)})
    u = out.recipe["payload"]["phases"]["Ph"]["atoms"]["C"]["Uaniso"]
    assert out.valid, out.problems
    assert u["U22"][0] == 0.0123 and u["U12"][0] == 0.0123 / 2 and u["U13"][0] == 0.0 and u["U33"][0] == 0.0211
    rows = {r["path"]: r for r in out.dispositions}
    assert rows["payload.phases.Ph.atoms.C.Uaniso.U12"]["disposition"] == "held_by_symmetry"


def test_affine_offset_tie_is_propagated_exactly():
    """P -4 21 m: a (x, x+1/2, z) site — refining x moves y by the same amount, offset kept exact."""
    p = lambda v, f=False: [v, f]  # noqa: E731
    atoms = {"S": {"element": "S", "x": p(0.1, True), "y": p(0.6, True), "z": p(0.3, True), "occupancy": p(1.0),
                   "ADP": "Uiso", "Uiso": p(0.01)}}
    cell = {"a": 5.0, "b": 5.0, "c": 7.0, "alpha": 90.0, "beta": 90.0, "gamma": 90.0}
    model = validate(_recipe_with_phase("P -4 21 m", atoms, cell)).recipe
    out = roundtrip.build_output(model, {"payload.phases.Ph.atoms.S.x": (0.1234, 1e-3), "payload.phases.Ph.atoms.S.z": (0.31, 1e-3)})
    atom = out.recipe["payload"]["phases"]["Ph"]["atoms"]["S"]
    assert out.valid, out.problems
    assert atom["x"][0] == 0.1234 and atom["y"][0] == 0.6234 and atom["z"][0] == 0.31


def test_member_only_report_derives_the_representative_and_keeps_its_esd():
    """An engine may free a non-representative member (easydiffraction does): the representative is derived and
    carries the ESD scaled by the relation; the member row is held_by_symmetry."""
    model = validate(_hex_recipe()).recipe
    out = roundtrip.build_output(model, {"payload.phases.Gr.atoms.C.y": (0.34, 2e-3)}, at_limit={"payload.phases.Gr.atoms.C.y"})
    atom = out.recipe["payload"]["phases"]["Gr"]["atoms"]["C"]
    assert out.valid, out.problems
    assert atom["x"][0] == pytest.approx(0.17) and atom["y"][0] == pytest.approx(0.34)
    rows = {r["path"]: r for r in out.dispositions}
    rep, member = rows["payload.phases.Gr.atoms.C.x"], rows["payload.phases.Gr.atoms.C.y"]
    assert rep["disposition"] == "varied" and rep["esd"] == pytest.approx(1e-3) and rep["at_limit"] is True
    assert member["disposition"] == "held_by_symmetry"


def test_problems_list_each_validation_error_with_its_message():
    model = validate(_load("example_LaB6/input.json")).recipe
    out = roundtrip.build_output(model, {"payload.phases.LaB6.atoms.B.occupancy": (1.3, None),
                                         "payload.phases.LaB6.atoms.La.occupancy": (-0.2, None)})
    assert not out.valid
    located = [p for p in out.problems if ": " in p and ("occupancy" in p)]
    assert len(located) >= 2, out.problems
    assert all(len(p.split(": ", 1)[1]) > 10 for p in located), out.problems  # the message, not just the location


def test_held_parameter_check_tolerates_formatting_noise():
    model = validate(_load("example_LaB6/input.json")).recipe
    a = model.payload.phases["LaB6"].unit_cell.a.value
    out = roundtrip.build_output(model, {"payload.phases.LaB6.unit_cell.a": (a * (1 + 1e-12), None)})
    assert out.valid, out.problems
