"""Native ``topas.*`` fixtures against TOPAS 6 runs (re/05 goldens; A143, A149, A152).

``tests/data/topas/native/golden/<engine_version>/`` holds what TOPAS wrote for
each fixture in ``tests/data/topas/native/`` (TOPAS-64 Version 6 under ``6/``;
the directory is the fixture's ``engine_version``; base name
``<fixture>__snapped``): the INP the writer produced, TOPAS's results CSV,
profile and reflection lists, and the background run (INP and profile).
Without TOPAS these tests check that the writer still emits exactly those INPs
and that the result built from TOPAS's files is right.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np
import pytest

from powderline.gateways.topas import native_run, native_writer, schema

pytestmark = pytest.mark.topas_gen

NATIVE = Path(__file__).parent / "data" / "topas" / "native"
GOLDENS = NATIVE / "golden"
FIXTURES = ("drx33_rietveld", "lab6_cell_rietveld", "lab6_corrections", "lab6_pv_full_axial", "lab6_rietveld",
            "lab6_spf", "ties_simulation")
#: Warnings each TOPAS 6 run gives (beyond the recipe's own validation warnings).
RUN_WARNINGS = {
    "drx33_rietveld": set(),
    "lab6_cell_rietveld": {"topas_parameter_at_limit"},
    "lab6_corrections": set(),
    "lab6_pv_full_axial": {"topas_parameter_at_limit"},
    "lab6_rietveld": {"topas_parameter_at_limit"},
    "lab6_spf": set(),
    "ties_simulation": set(),
}


def _recipe(fixture):
    return json.loads((NATIVE / f"{fixture}.json").read_text(encoding="utf-8"))


def _model(fixture):
    return schema.validate_recipe(_recipe(fixture))


def golden_dir(fixture):
    """The fixture's goldens: ``golden/<engine_version>/`` (what that TOPAS version wrote)."""
    return GOLDENS / _recipe(fixture)["engine_version"]


def _base(fixture):
    return f"{fixture}__snapped"


def _values(fixture):
    """TOPAS's refined values, read with the native runner's strict reader (A154 S1; re/07 B)."""
    _, values = native_run._read_results(golden_dir(fixture) / f"{_base(fixture)}_results.csv")
    return values


@pytest.fixture(scope="module", params=FIXTURES)
def golden_result(request, tmp_path_factory):
    fixture = request.param
    out = tmp_path_factory.mktemp(fixture)
    for f in golden_dir(fixture).glob(f"{_base(fixture)}*"):
        if not f.name.endswith(".inp"):
            shutil.copy(f, out / f.name)
    model = _model(fixture)
    native = native_writer.render_native(model, _base(fixture))
    return fixture, model, native_run.build_result(model, native, out, [], elapsed=0.0)


@pytest.mark.parametrize("fixture", FIXTURES)
def test_writer_emits_the_inp_topas_ran(fixture):
    model = _model(fixture)
    assert native_writer.render_native(model, _base(fixture)).inp_text == \
        (golden_dir(fixture) / f"{_base(fixture)}.inp").read_text(encoding="utf-8")


@pytest.mark.parametrize("fixture", FIXTURES)
def test_background_run_inp_is_the_one_topas_ran(fixture):
    """A152: the background INP from the golden refined values is the one TOPAS 6 ran (pack 5)."""
    values = {name: v for name, (v, _) in _values(fixture).items()}
    assert native_writer.render_background(_model(fixture), _base(fixture), values).inp_text == \
        (golden_dir(fixture) / f"{_base(fixture)}_bkg.inp").read_text(encoding="utf-8")


def test_core_rwp_equals_topas_rwp(golden_result):
    """A149: with the fit limits on data points TOPAS fits exactly the window core scores."""
    fixture, model, r = golden_result
    d = r["engine_details"]
    assert r["rwp"] == pytest.approx(d["rwp"], rel=1e-6)
    assert d["n_points"] == 3767
    assert d["parameters_varied"] == d["parameters_requested"]


def test_background_column_is_topas_background_run(golden_result):
    """A152: y_bkg is the background run's Ycalc; TOPAS's Ycalc never falls below it."""
    fixture, model, r = golden_result
    bkg = np.loadtxt(golden_dir(fixture) / f"{_base(fixture)}_bkg_profile.txt")
    profile = r["fit_profile"]
    np.testing.assert_array_equal(profile["two_theta"].to_numpy(), bkg[:, 0])
    np.testing.assert_array_equal(profile["y_bkg"].to_numpy(), bkg[:, 2])
    assert (profile["y_calc"] - profile["y_bkg"] > -1e-6).all()


def test_run_warnings(golden_result):
    fixture, model, r = golden_result
    assert {w["code"] for w in r["warnings"]} == RUN_WARNINGS[fixture]


def test_refined_values_are_topas_values(golden_result):
    """Every refined parameter row carries TOPAS's value (recipe units: beq / 8 pi^2)."""
    fixture, model, r = golden_result
    values = _values(fixture)
    native = native_writer.render_native(model, _base(fixture))
    rows = r["refined_parameters"].set_index("parameter_name")
    for name, info in native.params.items():
        if info.refined:
            assert rows.loc[name, "value"] == pytest.approx(values[name][0] / info.scale, rel=1e-12)


def test_drx33_cells(golden_result):
    fixture, model, r = golden_result
    if fixture != "drx33_rietveld":
        pytest.skip("DRX_33 only")
    cells = {name: df.set_index("parameter")["value"] for name, df in r["unit_cell_data"].items()}
    values = _values(fixture)
    (cubic, c1), (mono, c2) = cells.items()
    assert c1["cell_a"] == c1["cell_b"] == c1["cell_c"] == pytest.approx(values["p1_cell_a"][0], rel=1e-12)
    for axis in ("a", "b", "c"):
        assert c2[f"cell_{axis}"] == pytest.approx(values[f"p2_cell_{axis}"][0], rel=1e-12)
    assert c2["cell_beta"] == pytest.approx(values["p2_cell_beta"][0], rel=1e-12)
    assert c1["cell_volume"] == pytest.approx(values["p1_volume"][0], rel=1e-12)


# --- A130 / A154: any non-finite number TOPAS writes is a divergence (re/05 PR review S1) ---------------

def _golden_copy(tmp_path, fixture="lab6_rietveld"):
    for f in golden_dir(fixture).glob(f"{_base(fixture)}*"):
        if not f.name.endswith(".inp"):
            shutil.copy(f, tmp_path / f.name)
    model = _model(fixture)
    return model, native_writer.render_native(model, _base(fixture))


def _replace_token(path, line_no, column, token):
    lines = path.read_text(encoding="utf-8").splitlines()
    sep = "," if path.suffix == ".csv" else None
    parts = lines[line_no].split(sep)
    parts[column] = token
    lines[line_no] = ("," if sep else " ").join(parts)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _row(path, name):
    return next(i for i, ln in enumerate(path.read_text(encoding="utf-8").splitlines()) if ln.startswith(name + ","))


@pytest.mark.parametrize("token", ["nan", "-inf", "1.#QNAN", "-1.#IND", "1.#INF", "-nan(ind)"])
@pytest.mark.parametrize("where", ["value", "statistic", "profile", "peaks"])
def test_non_finite_topas_output_is_a_divergence(tmp_path, token, where):
    """Python and MSVC spellings alike, in the results CSV, the profile and a reflection list."""
    model, native = _golden_copy(tmp_path)
    base = _base("lab6_rietveld")
    if where in ("value", "statistic"):
        f = tmp_path / f"{base}_results.csv"
        _replace_token(f, _row(f, "p1_scale" if where == "value" else "r_wp"), 1, token)
    elif where == "profile":
        _replace_token(tmp_path / f"{base}_profile.txt", 100, 2, token)
    else:
        _replace_token(tmp_path / f"{base}_p1_peaks.txt", 0, 7, token)
    with pytest.raises(native_run.EngineExecutionError, match="diverged"):
        native_run.build_result(model, native, tmp_path, [], elapsed=0.0)


def test_non_finite_esd_is_not_a_divergence(tmp_path):
    """TOPAS cannot give the ESD of a degenerate parameter: the ESD is empty, the run stands."""
    model, native = _golden_copy(tmp_path)
    f = tmp_path / f"{_base('lab6_rietveld')}_results.csv"
    _replace_token(f, _row(f, "p1_scale"), 2, "1.#QNAN")
    rows = native_run.build_result(model, native, tmp_path, [], elapsed=0.0)["refined_parameters"]
    assert np.isnan(rows.set_index("parameter_name").loc["p1_scale", "esd"])


def test_unreadable_topas_number_is_an_engine_error(tmp_path):
    model, native = _golden_copy(tmp_path)
    _replace_token(tmp_path / f"{_base('lab6_rietveld')}_profile.txt", 5, 2, "1.23.4")
    with pytest.raises(native_run.EngineExecutionError, match="not a number"):
        native_run.build_result(model, native, tmp_path, [], elapsed=0.0)


def test_limit_hit_message_in_recipe_units(tmp_path):
    """A refined Uiso stopped at TOPAS's beq maximum 20 is reported as Uiso 20/8 pi^2 (re/05 PR review N2)."""
    recipe = json.loads((NATIVE / "lab6_rietveld.json").read_text(encoding="utf-8"))
    recipe["payload"]["phases"]["LaB6"]["atoms"]["La"]["Uiso"][1] = True
    model = schema.validate_recipe(recipe)
    for f in golden_dir("lab6_rietveld").glob(f"{_base('lab6_rietveld')}*"):
        if not f.name.endswith(".inp"):
            shutil.copy(f, tmp_path / f.name)
    with open(tmp_path / f"{_base('lab6_rietveld')}_results.csv", "a", encoding="utf-8") as fh:
        fh.write("p1_a1_beq,20,0.1\n")
    r = native_run.build_result(model, native_writer.render_native(model, _base("lab6_rietveld")), tmp_path, [],
                                elapsed=0.0)
    (hit,) = [w for w in r["warnings"] if w["field_path"] == "payload.phases.LaB6.atoms.La.Uiso"]
    assert "max limit 0.253303 (TOPAS's default limit, TOPAS value 20)" in hit["message"]


def test_cs_ceiling_is_a_recorded_limit():
    """TOPAS.INC's CS maximum Min(Val 2 + .3, 10000) has the fixed part 10000 (re/05 PR review N7)."""
    native = native_writer.render_native(_model("lab6_corrections"), "x")
    assert native.params["p1_cs_l"].limits == (0.3, 10000.0)
    assert native.params["inst_U"].limits == (-1.0, 2.0)
    assert native.params["ze_th2_offset"].limits == (None, None)  # data-step expressions: no fixed part


# --- re/20a (KI-04, P-43): the output recipe from the writer's parameter paths -----------------------------

def test_output_recipe_is_valid_and_carries_topas_values(golden_result):
    fixture, model, r = golden_result
    assert r["output_recipe_valid"] is True, [w["message"] for w in r["warnings"] if w["code"] == "output_recipe_not_valid"]
    out = r["output_recipe"]
    assert out["schema_name"] == model.schema_name and out["metadata"]["powderline_provenance"]["parent_run_id"] == r["run_id"]
    values = _values(fixture)
    native = native_writer.render_native(model, _base(fixture))
    rows = r["parameter_dispositions"].set_index("path")
    for name, info in native.params.items():
        if info.refined and name in values:
            node = out
            for key in info.path.split("."):
                node = node[int(key) if key.isdigit() else key]
            written = node if "chebyshev.coefficients" in info.path else node[0]
            assert written == pytest.approx(values[name][0] / info.scale, rel=1e-12), info.path
            assert rows.loc[info.path, "disposition"] in ("varied", "requested_not_varied"), info.path
    again = schema.validate_recipe(out)
    from powderline.schema_core import collect_warnings
    assert not [w for w in collect_warnings(again) if w["code"] == "symmetry_value_derived"]
    assert again.model_dump(mode="json") == out


def test_inp_from_the_output_recipe_is_the_inp_topas_ran(golden_result):
    """Feeding the output recipe back writes the same INP for every parameter TOPAS did not move; the moved
    ones carry TOPAS's final values (the idempotence of the writer on a resolved recipe)."""
    fixture, model, r = golden_result
    again = schema.validate_recipe(r["output_recipe"])
    text = native_writer.render_native(again, _base(fixture)).inp_text
    assert text.count("\n") == native_writer.render_native(model, _base(fixture)).inp_text.count("\n")
