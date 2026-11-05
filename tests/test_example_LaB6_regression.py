"""Regression tests for example_LaB6 (and sibling examples) to ensure code changes
don't affect refinement results.

Refinements run via ``pixi run [-e gsasii] kicker --no-server`` (subprocess,
``subprocess_utils.kicker_command``) on the native ``gsasii.*`` example
recipes and outputs are compared to committed references
under ``examples/<name>/output/`` (regenerated on the native path at re/07)
using helpers in ``subprocess_utils``. Two Rwp assertions per refinement:
GSAS-II's own wR from ``dummy.lst`` (the freeze tripwire, independent of
PowderLine's statistics code) and PowderLine's uniform ``rwp`` from the CLI's
"Final Rwp" line (core ``fitstats`` over the stated window, A23/A125); on the
native path they agree because GSAS-II fits exactly the stated window (A149). The bulk of these tests share an identical shape and are
grouped into ``@pytest.mark.parametrize`` tests (one body per group), resolving the
per-example fixtures via ``request.getfixturevalue``.
"""

import json
import re
from pathlib import Path
import pandas as pd
import pytest

pytestmark = [pytest.mark.gsasii, pytest.mark.slow]

from subprocess_utils import (
    kicker_command,
    run_subprocess_utf8,
    refined_params_match,
    unit_cell_match,
    extract_rwp_from_lst,
    REFINED_PARAM_COLUMNS,
)

REPO = Path(__file__).resolve().parent.parent  # the repo, whatever the cwd (review item 17)


def extract_rwp_from_stdout(stdout_text: str) -> float | None:
    """
    Extract PowderLine's uniform Rwp from the CLI's stdout.

    Looks for pattern: "Refinement complete. Final Rwp: 45.257%" — the result
    dict's ``rwp`` (core fitstats, A23), printed for every run including a
    simulation (A129). Returns None if the line is absent.
    """
    pattern = r'Final Rwp: ([\d.]+)%'
    match = re.search(pattern, stdout_text)
    if not match:
        return None
    return float(match.group(1))


# ============================================================================
# --validate-only smoke tests (uniform: returncode 0, success banner, marker)
# ============================================================================

# (id, input_fixture, expected_marker) — the marker is the per-example string the
# original test asserted was present in stdout.
_VALIDATE_ONLY_CASES = [
    ("LaB6", "example_LaB6_input", "Schema name: gsasii.rietveld"),
    ("DRX_33", "example_DRX_33_input", "DRX_33"),
    ("LaB6_simulation", "example_LaB6_simulation_input", "Schema name: gsasii.rietveld"),
    ("DRX_33_simulation", "example_DRX_33_simulation_input", "DRX_33"),
    ("DRX_33_atomrefine", "example_DRX_33_atomrefine_input", "DRX_33"),
    ("DRX_33_anisoADP", "example_DRX_33_anisoADP_input", "DRX_33"),
    ("DRX_33_strainonly", "example_DRX_33_strainonly_input", "DRX_33"),
]


@pytest.mark.parametrize(
    "input_fixture, expected_marker",
    [case[1:] for case in _VALIDATE_ONLY_CASES],
    ids=[case[0] for case in _VALIDATE_ONLY_CASES],
)
def test_validate_only_example(request, input_fixture, expected_marker):
    """--validate-only succeeds and reports the expected schema/example marker."""
    recipe_input = request.getfixturevalue(input_fixture)
    cmd = kicker_command(
        str(recipe_input),
        "--validate-only",
        repo_root=REPO
    )

    result = run_subprocess_utf8(cmd, capture_output=True, text=True, cwd=REPO)

    assert result.returncode == 0, f"Validation failed:\n{result.stderr}"
    assert "Recipe validation successful" in result.stdout
    assert expected_marker in result.stdout


def test_cli_reports_recipe_validation_errors(example_LaB6_input, tmp_path):
    """A pydantic-invalid recipe exits 1 through the CLI ValidationError branch,
    rendering each error as a "loc -> path: msg" bullet (kicker.py main)."""
    recipe = json.loads(example_LaB6_input.read_text())
    # Type-corrupt one payload field: every required field stays present, so the
    # template check passes and pydantic raises ValidationError inside run().
    recipe["payload"]["refinement_controls"]["refinement_cycles"] = "five"
    bad_recipe = tmp_path / "invalid_cycles.json"
    bad_recipe.write_text(json.dumps(recipe))

    cmd = kicker_command(str(bad_recipe), "--validate-only", repo_root=REPO)
    result = run_subprocess_utf8(cmd, capture_output=True, text=True, cwd=REPO)

    assert result.returncode == 1
    assert "Recipe validation failed" in result.stdout
    assert "Validation errors:" in result.stdout
    assert "payload -> refinement_controls -> refinement_cycles" in result.stdout


# ============================================================================
# Standard Rietveld regressions (run; expected files incl. dummy.lst; rwp via
# .lst; unit_cell via unit_cell_match; peak-list row count; refined_params via
# refined_params_match). Single-phase examples are the multi-phase body with one
# phase, so a single parametrized body covers both.
# ============================================================================

# PowderLine's uniform rwp of each committed reference (core fitstats; A23, A125),
# recorded when the references were regenerated on the native path (re/07,
# devkit tasks/re07-equivalence.md). Same 0.1 pp tolerance as the .lst wR check.
UNIFORM_RWP_REFERENCE = {
    "LaB6": 6.5345,
    "DRX_33": 10.8288,
    "DRX_33_atomrefine": 15.0592,
    "DRX_33_anisoADP": 15.5296,
    "DRX_33_strainonly": 8.4573,  # 8.457289680786326 (re07-equivalence.md §1/§3); added after the G2 review (S5)
    "LaB6_singlepeakfit": 1.8159,
    # simulations: the uniform statistic of the simulated pattern against the
    # example's placeholder observation (A129; it means nothing physically,
    # GSAS-II's own 100 % is under engine_details) — a determinism guard
    "LaB6_simulation": 1787.0085,
    "DRX_33_simulation": 6819.9237,
}
UNIFORM_RWP_TOLERANCE = 0.1  # percentage points

# (id, input, lst, unit_cell_ref, peak_ref, refined_params_ref, phases)
# unit_cell_ref/peak_ref resolve to a single Path (single-phase) or a
# {phase: Path} dict (multi-phase); ``phases`` names the per-phase report files.
_STANDARD_RIETVELD_CASES = [
    ("LaB6",
     "example_LaB6_input", "example_LaB6_reference_lst",
     "example_LaB6_reference_unit_cell_csv", "example_LaB6_reference_peak_csv",
     "example_LaB6_reference_refined_params_csv", ["LaB6"]),
    ("DRX_33",
     "example_DRX_33_input", "example_DRX_33_reference_lst",
     "example_DRX_33_reference_unit_cell_csvs", "example_DRX_33_reference_peak_csvs",
     "example_DRX_33_reference_refined_params_csv", ["DRX_33", "Li4MgWO6_SG12"]),
    ("DRX_33_atomrefine",
     "example_DRX_33_atomrefine_input", "example_DRX_33_atomrefine_reference_lst",
     "example_DRX_33_atomrefine_reference_unit_cell_csvs",
     "example_DRX_33_atomrefine_reference_peak_csvs",
     "example_DRX_33_atomrefine_reference_refined_params_csv", ["DRX_33", "Li4MgWO6_SG12"]),
    ("DRX_33_anisoADP",
     "example_DRX_33_anisoADP_input", "example_DRX_33_anisoADP_reference_lst",
     "example_DRX_33_anisoADP_reference_unit_cell_csvs",
     "example_DRX_33_anisoADP_reference_peak_csvs",
     "example_DRX_33_anisoADP_reference_refined_params_csv", ["DRX_33", "Li4MgWO6_SG12"]),
    ("DRX_33_strainonly",
     "example_DRX_33_strainonly_input", "example_DRX_33_strainonly_reference_lst",
     "example_DRX_33_strainonly_reference_unit_cell_csvs",
     "example_DRX_33_strainonly_reference_peak_csvs",
     "example_DRX_33_strainonly_reference_refined_params_csv", ["DRX_33", "Li4MgWO6_SG12"]),
]


@pytest.mark.parametrize(
    "case_id, input_fixture, lst_fixture, unit_cell_fixture, peak_fixture, refined_params_fixture, phases",
    _STANDARD_RIETVELD_CASES,
    ids=[case[0] for case in _STANDARD_RIETVELD_CASES],
)
def test_example_regression(request, tmp_output_dir, case_id, input_fixture, lst_fixture,
                            unit_cell_fixture, peak_fixture, refined_params_fixture, phases):
    """
    Run a standard Rietveld example and compare outputs to reference files.

    Exact matching on structure (files present, labels, peak counts); numeric
    value/esd columns compared within cross-build tolerance. Rwp twice:
    GSAS-II's own wR from dummy.lst (freeze tripwire) and the uniform rwp the
    CLI prints (core fitstats), each against its reference.
    """
    recipe_input = request.getfixturevalue(input_fixture)
    ref_lst = request.getfixturevalue(lst_fixture)
    unit_cell_ref = request.getfixturevalue(unit_cell_fixture)
    peak_ref = request.getfixturevalue(peak_fixture)
    ref_refined_params_csv = request.getfixturevalue(refined_params_fixture)

    # Normalise single-phase (Path) and multi-phase (dict) references to a
    # {phase_name: reference_path} mapping so the body is phase-count agnostic.
    unit_cell_map = unit_cell_ref if isinstance(unit_cell_ref, dict) else {phases[0]: unit_cell_ref}
    peak_map = peak_ref if isinstance(peak_ref, dict) else {phases[0]: peak_ref}

    cmd = kicker_command(
        str(recipe_input),
        "--output", str(tmp_output_dir),
        repo_root=REPO
    )

    result = run_subprocess_utf8(cmd, capture_output=True, text=True, cwd=REPO)

    # Check that refinement completed successfully
    assert result.returncode == 0, f"Refinement failed with error:\n{result.stderr}"

    # Verify all expected output files were created (fixed dummy.gpx/lst naming)
    expected_files = (
        ["dummy.gpx", "dummy.lst"]
        + [f"{p}_unit_cell_report.csv" for p in phases]
        + [f"{p}_peak_list_report.csv" for p in phases]
        + ["fit_profile.txt"]
    )
    for filename in expected_files:
        output_file = tmp_output_dir / filename
        assert output_file.exists(), f"Expected output file not created: {filename}"

    # 1. GSAS-II's own wR from the .lst file (the freeze tripwire: independent of
    #    PowderLine's statistics code), against the reference .lst
    test_rwp = extract_rwp_from_lst(tmp_output_dir / "dummy.lst")
    ref_rwp = extract_rwp_from_lst(ref_lst)
    assert abs(test_rwp - ref_rwp) < 0.1, (
        f"Rwp mismatch: test={test_rwp}%, reference={ref_rwp}%\n"
        f"Difference: {abs(test_rwp - ref_rwp):.2f}%\n"
        f"This indicates refinement results have changed significantly."
    )

    # 2. PowderLine's uniform rwp (A23) printed by the CLI, against the value
    #    recorded for the reference; on the native path it equals GSAS-II's wR
    #    to printed precision because the fit window is exactly the stated one
    uniform_rwp = extract_rwp_from_stdout(result.stdout)
    assert uniform_rwp is not None, f"No 'Final Rwp' line in stdout:\n{result.stdout}"
    assert abs(uniform_rwp - UNIFORM_RWP_REFERENCE[case_id]) < UNIFORM_RWP_TOLERANCE, (
        f"Uniform Rwp mismatch: test={uniform_rwp}%, reference={UNIFORM_RWP_REFERENCE[case_id]}%"
    )
    assert abs(uniform_rwp - test_rwp) < 0.01, (
        f"Uniform Rwp ({uniform_rwp}%) and GSAS-II's wR ({test_rwp}%) disagree: the fit windows differ (A149)"
    )

    # Compare unit cell CSV(s) per phase
    for phase_name, ref_csv_path in unit_cell_map.items():
        test_unit_cell = pd.read_csv(tmp_output_dir / f"{phase_name}_unit_cell_report.csv")
        ref_unit_cell = pd.read_csv(ref_csv_path)
        assert unit_cell_match(test_unit_cell, ref_unit_cell), (
            f"Unit cell report mismatch for phase {phase_name}:\n"
            f"Test:\n{test_unit_cell}\n"
            f"Reference:\n{ref_unit_cell}"
        )

    # Compare peak list CSV(s) per phase - check row count
    for phase_name, ref_csv_path in peak_map.items():
        test_peaks = pd.read_csv(tmp_output_dir / f"{phase_name}_peak_list_report.csv")
        ref_peaks = pd.read_csv(ref_csv_path)
        assert len(test_peaks) == len(ref_peaks), (
            f"Peak list row count mismatch for phase {phase_name}: "
            f"test={len(test_peaks)}, reference={len(ref_peaks)}"
        )

    # Compare refined_parameters CSV
    test_refined_params = pd.read_csv(tmp_output_dir / "refined_parameters.csv")
    ref_refined_params = pd.read_csv(ref_refined_params_csv)
    assert refined_params_match(test_refined_params, ref_refined_params), (
        f"Refined parameters mismatch:\n"
        f"Test shape: {test_refined_params.shape}, Reference shape: {ref_refined_params.shape}\n"
        f"Test columns: {list(test_refined_params.columns)}\n"
        f"Reference columns: {list(ref_refined_params.columns)}"
    )


# ============================================================================
# Simulation regressions (simulation mode: deterministic; no refined_parameters.csv;
# the uniform rwp against the placeholder data is checked as a determinism guard,
# A129). Same single/multi-phase normalisation as above.
# ============================================================================

# (id, input, unit_cell_ref, peak_ref, phases)
_SIMULATION_REGRESSION_CASES = [
    ("LaB6_simulation", "example_LaB6_simulation_input",
     "example_LaB6_simulation_reference_unit_cell_csv",
     "example_LaB6_simulation_reference_peak_csv", ["LaB6"]),
    ("DRX_33_simulation", "example_DRX_33_simulation_input",
     "example_DRX_33_simulation_reference_unit_cell_csvs",
     "example_DRX_33_simulation_reference_peak_csvs", ["DRX_33", "Li4MgWO6_SG12"]),
]


@pytest.mark.parametrize(
    "case_id, input_fixture, unit_cell_fixture, peak_fixture, phases",
    _SIMULATION_REGRESSION_CASES,
    ids=[case[0] for case in _SIMULATION_REGRESSION_CASES],
)
def test_example_simulation_regression(request, tmp_output_dir, case_id, input_fixture,
                                       unit_cell_fixture, peak_fixture, phases):
    """
    Run a simulation-mode example and verify output reproducibility.

    Simulation mode locks all parameters, so the cell is computed (not refined);
    tolerance guards float drift. There is no refined_parameters.csv. The CLI
    still prints the uniform rwp (every result carries the standard statistics
    and simulation_mode, A129); it is compared with the recorded value.
    """
    recipe_input = request.getfixturevalue(input_fixture)
    unit_cell_ref = request.getfixturevalue(unit_cell_fixture)
    peak_ref = request.getfixturevalue(peak_fixture)

    unit_cell_map = unit_cell_ref if isinstance(unit_cell_ref, dict) else {phases[0]: unit_cell_ref}
    peak_map = peak_ref if isinstance(peak_ref, dict) else {phases[0]: peak_ref}

    cmd = kicker_command(
        str(recipe_input),
        "--output", str(tmp_output_dir),
        repo_root=REPO
    )

    result = run_subprocess_utf8(cmd, capture_output=True, text=True, cwd=REPO)

    # Check that simulation completed successfully
    assert result.returncode == 0, f"Simulation failed with error:\n{result.stderr}"

    # Verify all expected output files were created
    expected_files = (
        ["dummy.gpx", "dummy.lst"]
        + [f"{p}_unit_cell_report.csv" for p in phases]
        + [f"{p}_peak_list_report.csv" for p in phases]
        + ["fit_profile.txt"]
    )
    for filename in expected_files:
        output_file = tmp_output_dir / filename
        assert output_file.exists(), f"Expected output file not created: {filename}"
    assert not (tmp_output_dir / "refined_parameters.csv").exists(), "a simulation refines nothing"

    # The uniform rwp of the simulated pattern against the placeholder data (A129):
    # meaningless as a fit quality, exact as a determinism guard
    uniform_rwp = extract_rwp_from_stdout(result.stdout)
    assert uniform_rwp is not None, f"No 'Final Rwp' line in stdout:\n{result.stdout}"
    assert uniform_rwp == pytest.approx(UNIFORM_RWP_REFERENCE[case_id], rel=1e-4)

    # Cell is computed (not refined) in simulation; tolerance guards float drift
    for phase_name, ref_csv_path in unit_cell_map.items():
        test_unit_cell = pd.read_csv(tmp_output_dir / f"{phase_name}_unit_cell_report.csv")
        ref_unit_cell = pd.read_csv(ref_csv_path)
        assert unit_cell_match(test_unit_cell, ref_unit_cell), (
            f"Unit cell mismatch for phase {phase_name} - simulation should be deterministic:\n"
            f"Test:\n{test_unit_cell}\n"
            f"Reference:\n{ref_unit_cell}"
        )

    # Exact match for peak count (should be identical)
    for phase_name, ref_csv_path in peak_map.items():
        test_peaks = pd.read_csv(tmp_output_dir / f"{phase_name}_peak_list_report.csv")
        ref_peaks = pd.read_csv(ref_csv_path)
        assert len(test_peaks) == len(ref_peaks), (
            f"Peak list row count mismatch for phase {phase_name}: "
            f"test={len(test_peaks)}, reference={len(ref_peaks)}"
        )


# ============================================================================
# Simulation determinism (run twice; fit_profile.txt must be byte-identical)
# ============================================================================

# (id, input, obj_label) — obj_label is the pandas assert_frame_equal ``obj``.
_DETERMINISM_CASES = [
    ("LaB6", "example_LaB6_simulation_input",
     "LaB6_simulation fit profiles should be deterministic"),
    ("DRX_33", "example_DRX_33_simulation_input",
     "DRX_33_simulation fit profiles should be deterministic"),
]


@pytest.mark.parametrize(
    "input_fixture, obj_label",
    [case[1:] for case in _DETERMINISM_CASES],
    ids=[case[0] for case in _DETERMINISM_CASES],
)
def test_simulation_determinism(request, tmp_path, input_fixture, obj_label):
    """
    Simulation mode is deterministic - running twice produces identical y_calc.

    Prevents regression where simulation parameters were accidentally set to
    refine, causing y_calc to vary between runs instead of being identical.
    """
    recipe_input = request.getfixturevalue(input_fixture)

    output_dir1 = tmp_path / "run1"
    output_dir2 = tmp_path / "run2"
    output_dir1.mkdir()
    output_dir2.mkdir()

    for output_dir in [output_dir1, output_dir2]:
        cmd = kicker_command(
            str(recipe_input),
            "--output", str(output_dir),
            repo_root=REPO,
        )
        result = run_subprocess_utf8(cmd, capture_output=True, text=True, cwd=REPO)
        assert result.returncode == 0, f"Simulation failed:\n{result.stderr}"

    # Compare fit_profile.txt outputs (contains y_calc)
    fit1 = pd.read_csv(output_dir1 / "fit_profile.txt", sep="\t")
    fit2 = pd.read_csv(output_dir2 / "fit_profile.txt", sep="\t")

    # y_calc should be EXACTLY identical between runs
    pd.testing.assert_frame_equal(fit1, fit2, check_exact=True, obj=obj_label)


# ============================================================================
# NEGATIVE VALIDATION TESTS - Verify validation catches constraint violations
# ============================================================================

def _violate_scale(recipe_dict):
    """Set the LaB6 scale refine_flag to True (gsasii.rietveld phase block, A93)."""
    recipe_dict['payload']['phases']['LaB6']['scale'][1] = True


def _violate_chebyshev(recipe_dict):
    """Set the Chebyshev background refine_flag to True."""
    recipe_dict['payload']['background']['chebyshev']['refine_flag'] = True


def _violate_instrument(recipe_dict):
    """Set the instrument wavelength refine_flag to True (gsasii instrument block, A103)."""
    recipe_dict['payload']['instrument']['radiation']['wavelength'] = [0.1665, True]


# (id, mutate, bad_filename, sim_fail_required, lower_markers)
# ``sim_fail_required`` gates the assertion on the gsasii schema's simulation
# message ("refinement_cycles is 1 (a simulation), so nothing may be refined",
# A88; only scale/chebyshev asserted the 0.26.0 equivalent). Each entry of
# ``lower_markers`` is a list of acceptable alternatives; at least one must
# appear in ``combined_output.lower()`` (chebyshev accepts "chebyshev" or
# "background").
_SIM_VALIDATION_CASES = [
    ("scale", _violate_scale, "bad_simulation.json", True, [["scale"]]),
    ("chebyshev", _violate_chebyshev, "bad_simulation_chebyshev.json", True,
     [["chebyshev", "background"]]),
    ("instrument", _violate_instrument, "bad_simulation_instrument.json", False,
     [["wavelength"]]),
]


@pytest.mark.parametrize(
    "mutate, bad_filename, sim_fail_required, lower_markers",
    [case[1:] for case in _SIM_VALIDATION_CASES],
    ids=[case[0] for case in _SIM_VALIDATION_CASES],
)
def test_simulation_validation_catches_refine_violation(
    example_LaB6_simulation_input, tmp_path, mutate, bad_filename, sim_fail_required, lower_markers
):
    """
    CRITICAL: validation catches a refine_flag=true violation in simulation mode.

    These negative tests ensure the validation system prevents the most common
    mistake: accidentally trying to refine a parameter in simulation mode.
    """
    # Load the valid simulation recipe and introduce a single violation
    recipe_dict = json.loads(example_LaB6_simulation_input.read_text())
    mutate(recipe_dict)

    # Write to temporary file
    bad_recipe_path = tmp_path / bad_filename
    bad_recipe_path.write_text(json.dumps(recipe_dict, indent=2))

    # Run validation on the bad recipe
    cmd = kicker_command(
        str(bad_recipe_path),
        "--validate-only",
        repo_root=REPO
    )

    result = run_subprocess_utf8(cmd, capture_output=True, text=True, cwd=REPO)

    # CRITICAL: Should exit with error code 1 (validation failed)
    assert result.returncode == 1, (
        f"Validation should have FAILED for a simulation-mode refine violation.\n"
        f"Exit code: {result.returncode} (expected 1)\n"
        f"Stdout: {result.stdout}\n"
        f"Stderr: {result.stderr}"
    )

    combined_output = result.stdout + result.stderr

    if sim_fail_required:
        assert "a simulation), so nothing may be refined" in combined_output, (
            f"Error message should indicate simulation validation failure.\n"
            f"Output:\n{combined_output}"
        )

    for alternatives in lower_markers:
        assert any(a in combined_output.lower() for a in alternatives), (
            f"Error message should identify one of {alternatives} as the problem.\n"
            f"Output:\n{combined_output}"
        )


# ============================================================================
# refined_parameters.csv structure tests (kept standalone - assert richer,
# example-specific column/context semantics rather than the uniform shape)
# ============================================================================

def test_refined_parameters_csv_structure(tmp_output_dir, example_LaB6_input):
    """
    Test that refined_parameters.csv has correct structure with phase/atom columns.

    Validates:
    - CSV contains all 9 expected columns
    - Phase parameters have phase_name and phase_idx populated
    - Instrument parameters have all four context columns as None
    - Column order is correct
    """
    # Run refinement on LaB6 (single phase, simple structure)
    cmd = kicker_command(
        str(example_LaB6_input),
        "--output", str(tmp_output_dir),
        repo_root=REPO
    )

    result = run_subprocess_utf8(cmd, capture_output=True, text=True, cwd=REPO)
    assert result.returncode == 0, f"Refinement failed: {result.stderr}"

    # Load refined_parameters.csv
    csv_path = tmp_output_dir / "refined_parameters.csv"
    assert csv_path.exists(), "refined_parameters.csv not created"

    df = pd.read_csv(csv_path)

    # Verify all expected columns exist
    expected_columns = REFINED_PARAM_COLUMNS
    assert list(df.columns) == expected_columns, (
        f"Column mismatch. Expected: {expected_columns}, Got: {list(df.columns)}"
    )

    # Verify phase parameters have correct context
    # LaB6 should have phase_name="LaB6" and phase_idx=0
    phase_params = df[df['parameter_name'].str.startswith('0::')]
    if len(phase_params) > 0:
        assert all(phase_params['phase_name'] == 'LaB6'), "Phase parameters should have phase_name='LaB6'"
        assert all(phase_params['phase_idx'] == 0), "Phase parameters should have phase_idx=0"

    # Verify HAP parameters (phase-histogram) have phase context but no atom context
    hap_params = df[df['parameter_name'].str.match(r'^\d+:\d+:')]
    if len(hap_params) > 0:
        assert all(hap_params['phase_name'] == 'LaB6'), "HAP parameters should have phase_name='LaB6'"
        assert all(hap_params['phase_idx'] == 0), "HAP parameters should have phase_idx=0"
        assert all(pd.isna(hap_params['atom_name'])), "HAP parameters should have atom_name=None"
        assert all(pd.isna(hap_params['atom_idx'])), "HAP parameters should have atom_idx=None"

    # Verify instrument parameters have no phase/atom context
    instrument_params = df[df['parameter_name'].str.startswith(':')]
    if len(instrument_params) > 0:
        assert all(pd.isna(instrument_params['phase_name'])), "Instrument parameters should have phase_name=None"
        assert all(pd.isna(instrument_params['phase_idx'])), "Instrument parameters should have phase_idx=None"
        assert all(pd.isna(instrument_params['atom_name'])), "Instrument parameters should have atom_name=None"
        assert all(pd.isna(instrument_params['atom_idx'])), "Instrument parameters should have atom_idx=None"


def test_refined_parameters_csv_multiphase(tmp_output_dir, example_DRX_33_atomrefine_input):
    """
    Test refined_parameters.csv with multi-phase atom refinement.

    Validates:
    - Atom parameters have correct phase_name, phase_idx, atom_name, atom_idx
    - Both phases have correct mappings (DRX_33 and Li4MgWO6_SG12)
    - Atom names match expected labels (Li, Mg, Mn1, O1, W for phase 0)
    """
    # Run refinement on DRX_33_atomrefine (2 phases, 5 and 7 atoms respectively)
    cmd = kicker_command(
        str(example_DRX_33_atomrefine_input),
        "--output", str(tmp_output_dir),
        repo_root=REPO
    )

    result = run_subprocess_utf8(cmd, capture_output=True, text=True, cwd=REPO)
    assert result.returncode == 0, f"Refinement failed: {result.stderr}"

    # Load refined_parameters.csv
    csv_path = tmp_output_dir / "refined_parameters.csv"
    assert csv_path.exists(), "refined_parameters.csv not created"

    df = pd.read_csv(csv_path)

    # Verify phase 0 (DRX_33) parameters
    phase0_params = df[df['phase_idx'] == 0]
    assert len(phase0_params) > 0, "Should have phase 0 parameters"
    assert all(phase0_params['phase_name'] == 'DRX_33'), "Phase 0 should be named 'DRX_33'"

    # Verify atom parameters for phase 0
    # DRX_33 atoms: Li, Mg, Mn1, O1, W (indices 0-4)
    phase0_atom_params = df[(df['phase_idx'] == 0) & (df['atom_idx'].notna())]
    if len(phase0_atom_params) > 0:
        expected_atoms = {'Li', 'Mg', 'Mn1', 'O1', 'W'}
        actual_atoms = set(phase0_atom_params['atom_name'].unique())
        # Subset check: actual atoms should be a subset of expected
        assert actual_atoms.issubset(expected_atoms), (
            f"Phase 0 atom names mismatch. Expected subset of {expected_atoms}, got {actual_atoms}"
        )

    # Verify phase 1 (Li4MgWO6_SG12) parameters
    phase1_params = df[df['phase_idx'] == 1]
    assert len(phase1_params) > 0, "Should have phase 1 parameters"
    assert all(phase1_params['phase_name'] == 'Li4MgWO6_SG12'), "Phase 1 should be named 'Li4MgWO6_SG12'"

    # Verify atom parameters for phase 1
    # Li4MgWO6_SG12 atoms: Li1, Li2, Li3, Mg, O1, O2, W (indices 0-6)
    phase1_atom_params = df[(df['phase_idx'] == 1) & (df['atom_idx'].notna())]
    if len(phase1_atom_params) > 0:
        expected_atoms = {'Li1', 'Li2', 'Li3', 'Mg', 'O1', 'O2', 'W'}
        actual_atoms = set(phase1_atom_params['atom_name'].unique())
        # Subset check: actual atoms should be a subset of expected
        assert actual_atoms.issubset(expected_atoms), (
            f"Phase 1 atom names mismatch. Expected subset of {expected_atoms}, got {actual_atoms}"
        )

    # Verify specific parameter example: 0::Afrac:0 should be DRX_33, Li, occupancy
    afrac_phase0 = df[df['parameter_name'] == '0::Afrac:0']
    if len(afrac_phase0) > 0:
        row = afrac_phase0.iloc[0]
        assert row['phase_name'] == 'DRX_33', "0::Afrac:0 should be phase DRX_33"
        assert row['phase_idx'] == 0, "0::Afrac:0 should have phase_idx=0"
        assert row['atom_name'] == 'Li', "0::Afrac:0 should be atom Li"
        assert row['atom_idx'] == 0, "0::Afrac:0 should have atom_idx=0"


# ============================================================================
# Single-peak fitting (SPF) regression - standalone (shape differs: no
# dummy.lst, Rwp via stdout, SPF-specific report files)
# ============================================================================

def test_example_LaB6_singlepeakfit_regression(example_LaB6_singlepeakfit_input, tmp_output_dir,
                                               example_LaB6_singlepeakfit_reference_single_peaks_txt):
    """
    Run example_LaB6_singlepeakfit (gsasii.spf) and compare outputs to reference files.

    This test validates the peaks_only strategy which fits peaks without a
    crystal structure model (36 peaks on the LaB6 standard pattern).

    Note: SPF mode outputs: dummy.gpx, fit_profile.txt, single_peaks_report.txt
    and, only when a peak has convergence issues, peak_convergence_diagnostics.txt
    (the re/07 reference run had none). Rwp is extracted from stdout (the
    uniform rwp; for a peak fit it equals GSAS-II's own, ledger R17).
    """
    # Run kicker on example_LaB6_singlepeakfit with temporary output directory
    cmd = kicker_command(
        str(example_LaB6_singlepeakfit_input),
        "--output", str(tmp_output_dir),
        repo_root=REPO
    )

    result = run_subprocess_utf8(cmd, capture_output=True, text=True, cwd=REPO)

    # Check that refinement completed successfully
    assert result.returncode == 0, f"Refinement failed with error:\n{result.stderr}"

    # Verify all expected output files were created
    # SPF mode generates core + SPF-specific files.
    # peak_convergence_diagnostics.txt is written ONLY when peaks have
    # convergence issues (see kicker SPF output docs), which for this cleanly
    # converging LaB6 data is build-dependent — checked conditionally below.
    expected_files = [
        "dummy.gpx",
        "fit_profile.txt",
        "single_peaks_report.txt",
    ]

    for filename in expected_files:
        output_file = tmp_output_dir / filename
        assert output_file.exists(), f"Expected output file not created: {filename}"

    # SPF mode fits peaks without a structural model and must NOT produce the
    # structural-refinement listing file.
    assert not (tmp_output_dir / "dummy.lst").exists(), (
        "gsasii.spf should not generate dummy.lst file"
    )

    # Parse final Rwp from stdout (SPF doesn't generate .lst or trajectory CSV)
    test_rwp = extract_rwp_from_stdout(result.stdout)
    assert test_rwp is not None, f"No 'Final Rwp' line in stdout:\n{result.stdout}"
    ref_rwp = UNIFORM_RWP_REFERENCE["LaB6_singlepeakfit"]  # GSAS-II v5.7.9, native path (re/07)
    assert abs(test_rwp - ref_rwp) < UNIFORM_RWP_TOLERANCE, (
        f"Rwp mismatch: test={test_rwp}%, reference={ref_rwp}%\n"
        f"Difference: {abs(test_rwp - ref_rwp):.2f}%\n"
        f"This indicates refinement results have changed significantly."
    )

    # Compare single peaks report - check row count (should be 36 peaks)
    test_peaks_report = tmp_output_dir / "single_peaks_report.txt"
    ref_peaks_report = example_LaB6_singlepeakfit_reference_single_peaks_txt

    # Read files and count data rows (skip header and comment lines)
    test_lines = [line for line in test_peaks_report.read_text().splitlines()
                  if line.strip() and not line.startswith('#')]
    ref_lines = [line for line in ref_peaks_report.read_text().splitlines()
                 if line.strip() and not line.startswith('#')]

    # Subtract 1 for column header row to get actual data row count
    test_peak_count = len(test_lines) - 1
    ref_peak_count = len(ref_lines) - 1

    assert test_peak_count == ref_peak_count, (
        f"Single peaks report row count mismatch: test={test_peak_count}, reference={ref_peak_count}"
    )

    # Convergence diagnostics are only written when peaks have issues; the
    # re/07 reference run converged all 36 peaks without it, but another build
    # may flag a marginal peak. If present, check structure.
    test_convergence = tmp_output_dir / "peak_convergence_diagnostics.txt"
    if test_convergence.exists():
        convergence_content = test_convergence.read_text()
        assert "aphysical" in convergence_content.lower() or "warning" in convergence_content.lower() or "sigma" in convergence_content.lower(), (
            "Convergence diagnostics should report peak sigma/warning columns"
        )
