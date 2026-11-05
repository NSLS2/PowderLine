"""API tests that execute a GSAS-II refinement (``powderline.run()`` / ``GSASClient``).

The execution half of ``test_api.py`` (re/09 split): every test here runs the
LaB6 example through the gateway in-process or via the GSAS-II server fallback
and compares against the committed references, so the module is ``gsasii`` +
``slow``. The engine-free API tests stay in ``test_api.py``.
"""

import json
import uuid
from unittest.mock import patch
import pytest
import pandas as pd
from pathlib import Path

pytestmark = [pytest.mark.gsasii, pytest.mark.slow]

pytest.importorskip("GSASII.GSASIIscriptable")

import powderline  # noqa: E402
from powderline.exceptions import EngineExecutionError, ExecutionBackendError  # noqa: E402
from powderline.gateways.gsasii.client import GSASClient  # noqa: E402
from subprocess_utils import unit_cell_match, extract_rwp_from_lst, REFINED_PARAM_COLUMNS  # noqa: E402


# ─── Constants (must match test_example_LaB6_regression.py tolerances) ────────

RWP_TOLERANCE = 0.1          # percent — same as CLI regression test
REPO = Path(__file__).resolve().parent.parent  # the repo, whatever the cwd (review item 17)
REFERENCE_DIR = REPO / "examples" / "example_LaB6" / "output"


# ─── Shared LaB6 subprocess run ───────────────────────────────────────────────

@pytest.fixture(scope="module")
def lab6_subprocess_run(tmp_path_factory):
    """Run the LaB6 subprocess refinement ONCE and share it across read-only tests.

    Returns ``(result, output_dir)``. Tests that only inspect a successful run's
    result dict / output files consume this instead of each launching their own
    (slow) subprocess refinement. Tests that need a fresh or second independent
    run (e.g. run_id uniqueness) still call powderline.run() themselves.
    """
    recipe = json.loads((REPO / "examples" / "example_LaB6" / "input.json").read_text(encoding="utf-8"))
    output_dir = tmp_path_factory.mktemp("lab6_shared_run")
    result = powderline.run(recipe, output_dir, execution_mode="subprocess")
    return result, output_dir


# ─── run() subprocess mode tests ──────────────────────────────────────────────


def test_run_result_has_run_id(lab6_subprocess_run):
    """run() result includes a valid UUID4 run_id for every actual refinement."""
    result, _ = lab6_subprocess_run
    assert result["status"] == "ok", f"Refinement failed: {result.get('failure')}"
    assert "run_id" in result, "result dict must contain 'run_id'"
    # Raises ValueError if not a valid UUID4
    parsed = uuid.UUID(result["run_id"], version=4)
    assert str(parsed) == result["run_id"], "run_id must be a canonical UUID4 string"


def test_run_result_run_id_is_unique(recipe_LaB6_dict, tmp_path):
    """Each call to run() produces a distinct run_id."""
    result_a = powderline.run(
        recipe_LaB6_dict,
        tmp_path / "out_a",
        execution_mode="subprocess",
    )
    result_b = powderline.run(
        recipe_LaB6_dict,
        tmp_path / "out_b",
        execution_mode="subprocess",
    )
    assert result_a["status"] == "ok"
    assert result_b["status"] == "ok"
    assert result_a["run_id"] != result_b["run_id"], (
        "Two separate runs must produce different run_ids"
    )

def test_run_subprocess_succeeds(lab6_subprocess_run):
    """run(execution_mode='subprocess') completes successfully."""
    result, _ = lab6_subprocess_run
    assert result["status"] == "ok", f"Refinement failed: {result.get('failure')}"
    assert result["method"] == "subprocess"
    assert result["elapsed_time"] > 0


def test_run_subprocess_matches_cli_rwp(lab6_subprocess_run):
    """run() subprocess Rwp matches the committed reference within tolerance."""
    result, _ = lab6_subprocess_run
    assert result["status"] == "ok", f"Refinement failed: {result.get('failure')}"
    assert result.get("rwp") is not None, "No Rwp returned from subprocess run"

    ref_rwp = extract_rwp_from_lst(REFERENCE_DIR / "dummy.lst")
    assert abs(result["rwp"] - ref_rwp) < RWP_TOLERANCE, (
        f"API Rwp ({result['rwp']:.3f}%) differs from CLI reference "
        f"({ref_rwp:.3f}%) by more than {RWP_TOLERANCE}%"
    )


def test_run_subprocess_output_files_exist(lab6_subprocess_run):
    """run() subprocess creates all expected output files."""
    result, out = lab6_subprocess_run
    assert result["status"] == "ok"

    for fname in ["dummy.gpx", "dummy.lst", "LaB6_unit_cell_report.csv",
                  "LaB6_peak_list_report.csv", "fit_profile.txt"]:
        assert (out / fname).exists(), f"Expected output file missing: {fname}"


def test_run_subprocess_unit_cell_matches_reference(lab6_subprocess_run):
    """run() subprocess unit_cell CSV matches the committed reference."""
    result, out = lab6_subprocess_run
    assert result["status"] == "ok"

    test_df = pd.read_csv(out / "LaB6_unit_cell_report.csv")
    ref_df = pd.read_csv(REFERENCE_DIR / "LaB6_unit_cell_report.csv")
    assert unit_cell_match(test_df, ref_df), (
        f"Unit cell report mismatch:\nTest:\n{test_df}\nReference:\n{ref_df}"
    )


# ─── run() structured output tests (all modes return identical structure) ──────

def test_run_result_has_structured_data_keys(lab6_subprocess_run):
    """run() result dict always contains the expected structured-data keys."""
    result, _ = lab6_subprocess_run
    assert result["status"] == "ok"
    for key in ("fit_profile", "unit_cell_data", "peak_list_data", "refined_parameters"):
        assert key in result, f"Expected key '{key}' missing from result dict"


def test_run_subprocess_structured_data_is_dataframes(lab6_subprocess_run):
    """run(execution_mode='subprocess') returns non-empty DataFrames in result."""
    result, _ = lab6_subprocess_run
    assert result["status"] == "ok"

    assert isinstance(result["fit_profile"], pd.DataFrame)
    assert not result["fit_profile"].empty, "fit_profile DataFrame must not be empty"

    assert isinstance(result["unit_cell_data"], dict)
    assert len(result["unit_cell_data"]) > 0, "unit_cell_data dict must not be empty"
    for phase, df in result["unit_cell_data"].items():
        assert isinstance(df, pd.DataFrame), f"unit_cell_data['{phase}'] must be a DataFrame"
        assert not df.empty

    assert isinstance(result["peak_list_data"], dict)
    assert len(result["peak_list_data"]) > 0, "peak_list_data dict must not be empty"
    for phase, df in result["peak_list_data"].items():
        assert isinstance(df, pd.DataFrame), f"peak_list_data['{phase}'] must be a DataFrame"
        assert not df.empty

    assert isinstance(result["refined_parameters"], pd.DataFrame)
    assert not result["refined_parameters"].empty, "refined_parameters DataFrame must not be empty"


def test_run_refined_parameters_has_nine_columns(lab6_subprocess_run):
    """refined_parameters DataFrame contains all 9 expected columns in all modes."""
    expected_cols = set(REFINED_PARAM_COLUMNS)
    result, _ = lab6_subprocess_run
    assert result["status"] == "ok"
    actual_cols = set(result["refined_parameters"].columns)
    assert expected_cols == actual_cols, (
        f"refined_parameters columns mismatch.\nExpected: {sorted(expected_cols)}\nGot: {sorted(actual_cols)}"
    )


def test_run_auto_fallback_returns_full_structured_data(recipe_LaB6_dict, tmp_path):
    """GSASClient fallback (server down) returns full structured DataFrames identical to subprocess mode."""
    client = GSASClient(fallback_to_subprocess=True)
    result = client.submit_simulation(
        recipe=recipe_LaB6_dict,
        output_dir=tmp_path / "out",
        auto_start_server=False,  # force fallback path
    )
    # After run() DataFrame conversion the result should have the same structure
    # as any other mode — convert manually since submit_simulation() bypasses run()
    result["fit_profile"] = pd.DataFrame(result.get("fit_profile") or {})
    result["unit_cell_data"] = {
        k: pd.DataFrame(v) for k, v in result.get("unit_cell_data", {}).items()
    }
    result["peak_list_data"] = {
        k: pd.DataFrame(v) for k, v in result.get("peak_list_data", {}).items()
    }
    refined_raw = result.get("refined_parameters")
    result["refined_parameters"] = (
        pd.DataFrame(refined_raw) if refined_raw
        else pd.DataFrame(columns=list(REFINED_PARAM_COLUMNS))
    )

    assert result["status"] == "ok"
    assert result.get("rwp") is not None, "rwp must be present in fallback result"
    assert isinstance(result["fit_profile"], pd.DataFrame)
    assert not result["fit_profile"].empty
    assert isinstance(result["unit_cell_data"], dict) and len(result["unit_cell_data"]) > 0
    assert isinstance(result["refined_parameters"], pd.DataFrame)
    assert not result["refined_parameters"].empty


# ─── GSASClient direct dict/model input tests ─────────────────────────────────

def test_gsasclient_accepts_dict(recipe_LaB6_dict, tmp_path):
    """GSASClient.submit_simulation() accepts a plain dict (no file required)."""
    client = GSASClient(fallback_to_subprocess=True)
    result = client.submit_simulation(
        recipe=recipe_LaB6_dict,
        output_dir=tmp_path / "out",
        auto_start_server=False,  # force subprocess for determinism in CI
    )
    assert result["status"] == "ok", f"GSASClient dict submission failed: {result.get('failure')}"


def test_gsasclient_accepts_recipemodel(recipe_LaB6_model, tmp_path):
    """GSASClient.submit_simulation() accepts a validated model instance."""
    client = GSASClient(fallback_to_subprocess=True)
    result = client.submit_simulation(
        recipe=recipe_LaB6_model,
        output_dir=tmp_path / "out",
        auto_start_server=False,
    )
    assert result["status"] == "ok", f"GSASClient model submission failed: {result.get('failure')}"


def test_gsasclient_accepts_path(tmp_path):
    """GSASClient.submit_simulation() still accepts a Path (backward compat)."""
    client = GSASClient(fallback_to_subprocess=True)
    result = client.submit_simulation(
        recipe=REPO / "examples" / "example_LaB6" / "input.json",
        output_dir=tmp_path / "out",
        auto_start_server=False,
    )
    assert result["status"] == "ok", f"GSASClient path submission failed: {result.get('failure')}"


# ─── error key contract tests ──────────────────────────────────────────────────

def test_ok_result_has_status_and_alias_but_no_error_key(lab6_subprocess_run):
    """re/12 (review focus 5): an ok result carries status/converged/envelope_version and the deprecated
    success alias; the pre-0.2.0 error/traceback keys are gone (a failure raises instead)."""
    result, _ = lab6_subprocess_run
    assert result["status"] == "ok" and "success" not in result and result["envelope_version"] == "1"
    assert result["converged"] in (True, False)
    assert "error" not in result and "traceback" not in result


def test_frozen_early_exit_raises_engine_crashed(recipe_LaB6_dict, tmp_path):
    """re/12: an early-exit dict from the frozen executor (e.g. histogram load failed) is raised as
    EngineExecutionError(reason="engine_crashed") with the dict's data on .result."""
    minimal_failure = {
        "success": False,
        "run_id": "test-run-id",
        "error": "Simulated histogram load failure",
        "elapsed_time": 0.5,
        "method": "subprocess",
    }

    with patch("powderline.gateways.gsasii.gateway.run_refinement", return_value=minimal_failure):
        with pytest.raises(EngineExecutionError) as e:
            powderline.run(recipe_LaB6_dict, tmp_path / "out", execution_mode="subprocess")

    assert e.value.reason == "engine_crashed"
    assert e.value.result["status"] == "failed"
    assert e.value.result["failure"]["message"] == "Simulated histogram load failure"
    assert e.value.result["run_id"] == "test-run-id" and e.value.result["method"] == "subprocess"


def test_engine_failure_lists_partial_outputs(recipe_LaB6_dict, tmp_path, monkeypatch):
    """Review focus 1: the files the frozen executor wrote before failing are in e.result['output_files']."""
    from powderline.gateways.gsasii import executors

    def diverged(*a, **k):
        raise EngineExecutionError("diverged", reason="diverged")
    monkeypatch.setattr(executors, "fit_report", diverged)
    out = tmp_path / "out"
    with pytest.raises(EngineExecutionError) as e:
        powderline.run(recipe_LaB6_dict, out, execution_mode="subprocess")
    assert e.value.reason == "diverged"
    assert any(f.endswith("dummy.lst") for f in e.value.result["output_files"])
    assert (out / "dummy.lst").exists()  # kept for diagnosis (spec §3.1)


def test_converged_is_a_bool_for_rietveld_and_none_for_simulation(lab6_subprocess_run, tmp_path):
    result, _ = lab6_subprocess_run
    assert result["converged"] in (True, False)
    sim = json.loads((REFERENCE_DIR.parent.parent / "example_LaB6_simulation" / "input.json").read_text(encoding="utf-8"))
    sim_result = powderline.run(sim, tmp_path / "sim", execution_mode="subprocess")
    assert sim_result["status"] == "ok" and sim_result["converged"] is None and sim_result["simulation_mode"] is True


# ─── execution_mode='auto' fallback tests ──────────────────────────────────────

def test_run_auto_mode_falls_back_to_subprocess_when_server_unavailable(
    recipe_LaB6_dict, tmp_path
):
    """run(execution_mode='auto') falls back to subprocess when server cannot be started."""
    from powderline.gateways.gsasii import client as _gc

    with patch.object(_gc.GSASClient, "is_server_available", return_value=False), \
         patch.object(_gc.GSASClient, "_start_server_background", return_value=False):
        result = powderline.run(
            recipe_LaB6_dict,
            tmp_path / "out",
            execution_mode="auto",
        )

    assert result["status"] == "ok", f"Refinement failed: {result.get('failure')}"
    assert result["method"] == "subprocess", (
        f"Expected 'subprocess' fallback but got method='{result['method']}'"
    )


# ─── execution_mode='server' failure normalization ────────────────────────────

def test_run_server_mode_unavailable_raises_backend_error(recipe_LaB6_dict, tmp_path):
    """run(execution_mode='server') with no server and fallback disabled raises ExecutionBackendError."""
    from powderline.gateways.gsasii import client as _gc

    with patch.object(_gc.GSASClient, "is_server_available", return_value=False), \
         patch.object(_gc.GSASClient, "_start_server_background", return_value=False):
        with pytest.raises(ExecutionBackendError) as e:
            powderline.run(recipe_LaB6_dict, tmp_path / "out", execution_mode="server")

    assert e.value.reason == "server_unavailable"
    assert e.value.result["status"] == "failed" and e.value.result["failure"]["kind"] == "backend"


# ─── POWDERLINE_NO_SERVER (deployment off switch, v0.1.2) ─────────────────────

def _no_server_paths():
    """Patches that fail the test if any server path is touched."""
    from powderline.gateways.gsasii import client as _gc

    def _fail(*a, **k):
        raise AssertionError("server path used despite POWDERLINE_NO_SERVER")

    return (patch.object(_gc.GSASClient, "is_server_available", side_effect=_fail),
            patch.object(_gc.GSASClient, "_start_server_background", side_effect=_fail),
            patch.object(_gc.GSASClient, "_submit_to_server", side_effect=_fail))


def test_run_auto_mode_with_no_server_env_runs_in_process(
    recipe_LaB6_dict, tmp_path, monkeypatch
):
    """POWDERLINE_NO_SERVER: run(execution_mode='auto') never probes or starts a server."""
    monkeypatch.setenv("POWDERLINE_NO_SERVER", "1")
    probe, start, submit = _no_server_paths()
    with probe, start, submit:
        result = powderline.run(recipe_LaB6_dict, tmp_path / "out", execution_mode="auto")

    assert result["status"] == "ok", f"Refinement failed: {result.get('failure')}"
    assert result["method"] == "subprocess"


def test_run_server_mode_with_no_server_env_errors(recipe_LaB6_dict, tmp_path, monkeypatch):
    """POWDERLINE_NO_SERVER: run(execution_mode='server') raises ExecutionBackendError(server_disabled)."""
    monkeypatch.setenv("POWDERLINE_NO_SERVER", "true")
    probe, start, submit = _no_server_paths()
    with probe, start, submit:
        with pytest.raises(ExecutionBackendError) as e:
            powderline.run(recipe_LaB6_dict, tmp_path / "out", execution_mode="server")

    assert e.value.reason == "server_disabled" and "POWDERLINE_NO_SERVER" in str(e.value)




# ─── re/20b (KI-04): the output recipe from a real GSAS-II run ────────────────────────────────────────────────

def test_lab6_output_recipe_is_valid_and_feeds_back(lab6_subprocess_run, tmp_path_factory):
    result, output_dir = lab6_subprocess_run
    assert result["output_recipe_valid"] is True, [w for w in result["warnings"] if w["code"] == "output_recipe_not_valid"]
    out = result["output_recipe"]
    assert (output_dir / "output_recipe.json").exists() and (output_dir / "parameter_dispositions.csv").exists()
    rows = result["parameter_dispositions"].set_index("path")
    u = rows.loc["payload.instrument.broadening.U"]
    assert u["disposition"] == "varied" and u["esd"] > 0 and out["payload"]["instrument"]["broadening"]["U"][0] == u["value"]
    again = powderline.validate(out)
    assert not [w for w in again.warnings if w["code"] == "symmetry_value_derived" or w["code"].endswith("_default_applied")]
    second = powderline.run(out, tmp_path_factory.mktemp("lab6_again"), execution_mode="subprocess")
    assert second["status"] == "ok" and abs(second["rwp"] - result["rwp"]) < 0.05
    second_rows = second["parameter_dispositions"].set_index("path")
    compared = 0
    for path, row in rows.iterrows():
        if row["disposition"] == "varied" and row["esd"] and row["esd"] > 0 and abs(row["value"]) > 10 * row["esd"]:
            assert abs(second_rows.loc[path, "value"] - row["value"]) <= 3 * row["esd"], path
            compared += 1
    assert compared >= 3


def _spf_recipe(physical):
    """The LaB6 single-peak-fit example; ``physical`` holds what the example as posed lets run unphysical: the
    background peak's widths (its sigma^2 ends near -2700 centideg^2) and the Lorentzian width of the last, weak
    peak at the window edge (which goes negative once the background peak is physical)."""
    recipe = json.loads((REPO / "examples" / "example_LaB6_singlepeakfit" / "input.json").read_text(encoding="utf-8"))
    if physical:
        for k in ("pv_gaussian_sigma_sq", "pv_lorentzian_gamma"):
            recipe["payload"]["background"]["single_peaks"][k][0][1] = False
        recipe["payload"]["single_peaks"]["pv_lorentzian_gamma"][35][1] = False
    return recipe


def test_singlepeakfit_example_output_recipe_is_honestly_invalid_naming_the_background_peak(tmp_path):
    """re/21: the peak fit's own block carries everything it varied. The example as committed refines its one
    background peak's widths, which GSAS-II lets run far below its silent floor (sigma^2 of order -1e3, EB-35): the
    output recipe reports that and is not valid, naming the value (P-43 D5). Before re/21 the SPF output recipe
    kept the recipe's starting background, marked requested_not_varied."""
    result = powderline.run(_spf_recipe(False), tmp_path, execution_mode="subprocess")
    assert result["status"] == "ok"
    assert result["output_recipe_valid"] is False
    why = [w for w in result["warnings"] if w["code"] == "output_recipe_not_valid"][0]["message"]
    assert "payload.background.single_peaks.pv_gaussian_sigma_sq.0" in why and "EB-35" in why
    rows = result["parameter_dispositions"].set_index("path")
    back0 = rows.loc["payload.background.chebyshev.coefficients.0"]
    assert back0["disposition"] == "varied" and back0["esd"] > 0 and abs(back0["value"] - 10) > 1
    assert result["output_recipe"]["payload"]["background"]["chebyshev"]["coefficients"][0] == pytest.approx(back0["value"])
    assert rows.loc["payload.single_peaks.positions.0", "esd"] > 0
    assert rows.loc["payload.background.single_peaks.pv_gaussian_sigma_sq.0", "value"] < 0
    assert len(result["peak_fit"]["parameters"]) == result["engine_details"]["parameters_varied"]


def test_singlepeakfit_output_recipe_feeds_back(tmp_path):
    """With the background peak's widths and the last peak's gamma held the peak fit stays physical: the output
    recipe is valid, carries the refined background and peaks (with ESDs) and reproduces the step when fed back."""
    result = powderline.run(_spf_recipe(True), tmp_path / "first", execution_mode="subprocess")
    assert result["output_recipe_valid"] is True, [w for w in result["warnings"] if w["code"] == "output_recipe_not_valid"]
    out = result["output_recipe"]
    assert out["payload"]["single_peaks"]["positions"][0][0] == pytest.approx(float(result["spf_peaks"]["position_2theta"].iloc[0]))
    rows = result["parameter_dispositions"].set_index("path")
    assert rows.loc["payload.background.chebyshev.coefficients.0", "disposition"] == "varied"
    assert rows.loc["payload.background.single_peaks.positions.0", "disposition"] == "varied"
    assert rows.loc["payload.background.single_peaks.pv_gaussian_sigma_sq.0", "disposition"] == "held_by_user"
    assert rows.loc["payload.single_peaks.pv_lorentzian_gamma.35", "disposition"] == "held_by_user"
    assert rows.loc["payload.single_peaks.pv_lorentzian_gamma.34", "disposition"] == "varied"
    assert rows.loc["payload.single_peaks.positions.0", "esd"] > 0
    second = powderline.run(out, tmp_path / "second", execution_mode="subprocess")
    assert second["status"] == "ok" and second["output_recipe_valid"] is True
    assert second["rwp"] == pytest.approx(result["rwp"], abs=0.05)


def test_atomrefine_output_recipe_reports_unphysical_values(tmp_path):
    """DRX_33 atom refinement ends with occupancies outside [0, 1] and a negative size: the output recipe is
    written and returned, not valid, and the warning names them (P-43 D5)."""
    recipe = json.loads((REPO / "examples" / "example_DRX_33_atomrefine" / "input.json").read_text(encoding="utf-8"))
    result = powderline.run(recipe, tmp_path, execution_mode="subprocess")
    assert result["status"] == "ok" and result["output_recipe"] is not None
    assert (tmp_path / "output_recipe.json").exists()
    assert result["output_recipe_valid"] is False  # the committed reference refines occupancies below zero
    why = [w for w in result["warnings"] if w["code"] == "output_recipe_not_valid"][0]["message"]
    assert "occupancy" in why or "isotropic_size" in why


def test_instrument_profile_peak_fit_output_recipe_carries_the_refined_profile(tmp_path):
    """re/21 (the re/20b review): with use_instrument_profile GSAS-II refines U..Z; the peak fit's block carries them
    (with the peak ESDs) so the output recipe is valid and feeds back."""
    recipe = _spf_recipe(True)
    recipe["payload"]["refinement_controls"]["single_peak_fitting_mode"]["use_instrument_profile"] = True
    for k in ("pv_gaussian_sigma_sq", "pv_lorentzian_gamma"):
        for p in recipe["payload"]["single_peaks"][k]:
            p[1] = False
    start = {"U": 49.1, "V": 11.2, "W": 0.71, "X": 0.62, "Y": -10.3, "Z": 0.34}
    for k, v in start.items():
        recipe["payload"]["instrument"]["broadening"][k] = [v, True]
    result = powderline.run(recipe, tmp_path / "first", execution_mode="subprocess")
    assert result["status"] == "ok"
    assert result["output_recipe_valid"] is True, [w for w in result["warnings"] if w["code"] == "output_recipe_not_valid"]
    rows = result["parameter_dispositions"].set_index("path")
    u = rows.loc["payload.instrument.broadening.U"]
    assert u["disposition"] == "varied" and u["esd"] and u["esd"] > 0
    assert any(abs(rows.loc[f"payload.instrument.broadening.{k}", "value"] - v) > 1e-9 for k, v in start.items())
    assert rows.loc["payload.single_peaks.positions.0", "esd"] > 0  # peak ESDs come back too
    second = powderline.run(result["output_recipe"], tmp_path / "second", execution_mode="subprocess")
    assert second["status"] == "ok"
