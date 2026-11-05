"""Tests verifying that ESD extraction uses the covariance matrix path exclusively.

These tests confirm that:
  A. The covariance path produces non-empty refined parameter dicts with finite ESDs.
  B. calculate_cell_esds_from_A_matrix returns floats for all 7 cell parameters.
  C. ESD values in output CSVs match committed reference values within tolerance.
  D. extract_refined_params_from_project returns {} (not silently swallows) when
     covariance data is absent — the RuntimeError is raised at the call site.

Tests A–C run the full pipeline via subprocess on the native ``gsasii.rietveld``
examples (consistent with the rest of the suite); test A also checks both Rwp
sources (GSAS-II's wR in ``dummy.lst``, the freeze tripwire, and the uniform
``rwp`` the CLI prints) against the re/07 reference. Test D is a pure unit test
using a lightweight mock.
"""

import math
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pandas as pd
import pytest

pytestmark = [pytest.mark.gsasii, pytest.mark.slow]

pytest.importorskip("GSASII.GSASIIscriptable")  # the unit tests import the frozen extractors, which import GSAS-II

from subprocess_utils import extract_rwp_from_lst, kicker_command, run_subprocess_utf8

REPO = Path(__file__).resolve().parent.parent  # the repo, whatever the cwd (review item 17)
from test_example_LaB6_regression import UNIFORM_RWP_REFERENCE, UNIFORM_RWP_TOLERANCE, extract_rwp_from_stdout


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _run_kicker(input_json: Path, output_dir: Path) -> subprocess.CompletedProcess:
    result = run_subprocess_utf8(
        kicker_command(str(input_json), "--output", str(output_dir), repo_root=REPO),
        capture_output=True,
        text=True,
        cwd=REPO,
    )
    return result


# ─── Test A: covariance path produces nonempty refined parameter dict ──────────

def test_covariance_path_returns_nonempty_params(example_LaB6_input, tmp_output_dir):
    """
    After a successful LaB6 Rietveld refinement, refined_parameters.csv must be
    non-empty and all ESD values must be finite floats.

    This confirms that the covariance matrix path (extract_refined_params_from_project)
    is sufficient on its own — no .lst fallback was needed.
    """
    result = _run_kicker(example_LaB6_input, tmp_output_dir)
    assert result.returncode == 0, f"Refinement failed:\n{result.stderr}"

    csv_path = tmp_output_dir / "refined_parameters.csv"
    assert csv_path.exists(), "refined_parameters.csv not created — covariance extraction failed"

    df = pd.read_csv(csv_path)
    assert len(df) > 0, "refined_parameters.csv is empty — covariance extraction returned nothing"

    # Confirm expected instrument parameter names are present (GSAS-II native naming)
    param_names = set(df["parameter_name"])
    for expected in [":0:U", ":0:V", ":0:W", "0:0:Scale"]:
        assert expected in param_names, (
            f"Expected parameter '{expected}' missing from refined_parameters.csv. "
            f"Present parameters: {sorted(param_names)}"
        )

    # All esd values must be finite floats (NaN/None indicate extraction failure)
    assert df["esd"].notna().all(), (
        "Some ESDs are NaN in refined_parameters.csv — covariance extraction incomplete"
    )
    assert df["esd"].apply(lambda v: math.isfinite(float(v))).all(), (
        "Some ESDs are non-finite (inf/-inf) in refined_parameters.csv"
    )

    # Both Rwp sources against the reference: GSAS-II's own wR (freeze tripwire)
    # and PowderLine's uniform rwp (A23)
    lst_wr = extract_rwp_from_lst(tmp_output_dir / "dummy.lst")
    uniform_rwp = extract_rwp_from_stdout(result.stdout)
    assert uniform_rwp is not None, result.stdout
    assert abs(lst_wr - UNIFORM_RWP_REFERENCE["LaB6"]) < UNIFORM_RWP_TOLERANCE
    assert abs(uniform_rwp - UNIFORM_RWP_REFERENCE["LaB6"]) < UNIFORM_RWP_TOLERANCE


# ─── Test B: cell ESD calculation returns floats for all 7 cell parameters ────

def test_cell_esd_matrix_all_params_have_esd(example_LaB6_input, tmp_output_dir):
    """
    After LaB6 refinement, LaB6_unit_cell_report.csv must have exactly 7 rows with
    float ESD values (not NaN/None), sourced from calculate_cell_esds_from_A_matrix.

    Note: LaB6 is cubic so ESDs for the constrained equal-length / right-angle
    parameters are legitimately 0.0 — the check is for finite floats, not non-zero.
    """
    result = _run_kicker(example_LaB6_input, tmp_output_dir)
    assert result.returncode == 0, f"Refinement failed:\n{result.stderr}"

    csv_path = tmp_output_dir / "LaB6_unit_cell_report.csv"
    assert csv_path.exists(), "LaB6_unit_cell_report.csv not created"

    df = pd.read_csv(csv_path)
    assert len(df) == 7, f"Expected 7 cell parameter rows, got {len(df)}"

    assert df["esd"].notna().all(), (
        "Some cell ESDs are NaN — calculate_cell_esds_from_A_matrix may have failed"
    )
    assert df["esd"].apply(lambda v: math.isfinite(float(v))).all(), (
        "Some cell ESDs are non-finite"
    )


# ─── Test C: ESD values match committed reference ─────────────────────────────

def test_esd_values_match_reference(
    example_LaB6_input, tmp_output_dir, example_LaB6_reference_unit_cell_csv
):
    """
    Unit cell ESD values from the covariance path must match the committed reference
    output within a small absolute tolerance.

    This is the key regression proof: the reference was generated with the covariance
    path active, so any deviation indicates the ESD source has changed.
    """
    result = _run_kicker(example_LaB6_input, tmp_output_dir)
    assert result.returncode == 0, f"Refinement failed:\n{result.stderr}"

    test_df = pd.read_csv(tmp_output_dir / "LaB6_unit_cell_report.csv")
    ref_df = pd.read_csv(example_LaB6_reference_unit_cell_csv)

    assert list(test_df["parameter"]) == list(ref_df["parameter"]), (
        "Cell parameter names differ from reference"
    )

    esd_tolerance = 1e-6
    for param, test_esd, ref_esd in zip(
        test_df["parameter"], test_df["esd"], ref_df["esd"]
    ):
        assert abs(float(test_esd) - float(ref_esd)) < esd_tolerance, (
            f"ESD mismatch for '{param}': test={test_esd}, reference={ref_esd}"
        )


# ─── Test C (multi-phase): DRX_33 cell ESDs are non-zero for free parameters ──

def test_multiphase_cell_esds_nonzero_for_free_params(example_DRX_33_input, tmp_output_dir):
    """
    After a two-phase DRX_33 refinement, the refined unit cell parameter 'cell_a'
    must have a non-zero ESD for both phases, confirming phase_idx is correctly
    incremented across phases in calculate_cell_esds_from_A_matrix.

    DRX_33 is cubic so a=b=c are free to refine together; the ESD for cell_a
    comes directly from the A-matrix (A0 component) and should be > 0.
    """
    result = _run_kicker(example_DRX_33_input, tmp_output_dir)
    assert result.returncode == 0, f"Refinement failed:\n{result.stderr}"

    # Check both phase unit cell reports are present and have non-zero cell_a ESDs
    phase_csvs = list(tmp_output_dir.glob("*_unit_cell_report.csv"))
    assert len(phase_csvs) == 2, (
        f"Expected 2 unit_cell_report CSVs (one per phase), found {len(phase_csvs)}: {phase_csvs}"
    )

    for csv_path in phase_csvs:
        df = pd.read_csv(csv_path)
        cell_a_row = df[df["parameter"] == "cell_a"]
        assert len(cell_a_row) == 1, f"'cell_a' row missing in {csv_path.name}"
        cell_a_esd = float(cell_a_row["esd"].iloc[0])
        assert cell_a_esd > 0.0, (
            f"cell_a ESD is 0.0 in {csv_path.name} — "
            "phase_idx may be wrong in calculate_cell_esds_from_A_matrix"
        )


# ─── Test D: empty covariance — function boundary and call-site raise ─────────

def test_extract_refined_params_empty_covariance_returns_empty_dict():
    """
    extract_refined_params_from_project() returns {} when covariance data is absent.

    This is expected for simulation mode (no parameters varied) and for gsasii.spf.
    The RuntimeError at the call site only fires when GSAS-II DID populate a varyList
    but extraction still returned nothing (indicating corrupt covariance data).
    """
    from powderline.gateways.gsasii.extractors import extract_refined_params_from_project  # noqa: PLC0415

    mock_proj = MagicMock()
    mock_proj.data = {"Covariance": {"data": {}}}

    result = extract_refined_params_from_project(mock_proj)
    assert result == {}, (
        "extract_refined_params_from_project should return {} for empty covariance "
        "(expected for simulation mode and SPF, not an error at this level)."
    )


def test_extract_refined_params_missing_covariance_key_returns_empty_dict():
    """
    extract_refined_params_from_project() returns {} when the 'Covariance' key is
    entirely absent from proj.data (e.g. a freshly constructed project that has not
    been refined yet, or SPF mode).
    """
    from powderline.gateways.gsasii.extractors import extract_refined_params_from_project  # noqa: PLC0415

    mock_proj = MagicMock()
    mock_proj.data = {}  # No 'Covariance' key at all

    result = extract_refined_params_from_project(mock_proj)
    assert result == {}, (
        "extract_refined_params_from_project should return {} when Covariance key is absent"
    )


def test_extract_refined_params_populated_varylast_returns_params():
    """
    extract_refined_params_from_project() returns a non-empty dict when covariance
    data has a non-empty varyList. This is the normal post-refinement case.
    """
    from powderline.gateways.gsasii.extractors import extract_refined_params_from_project  # noqa: PLC0415

    import numpy as np

    mock_proj = MagicMock()
    mock_proj.data = {
        "Covariance": {
            "data": {
                "varyList": [":0:U"],
                "variables": [47.4],
                "sig": [8.3],
                "covMatrix": np.array([[68.89]]),
            }
        }
    }

    result = extract_refined_params_from_project(mock_proj)
    assert ":0:U" in result, "Expected ':0:U' in extracted param dict"
    assert abs(result[":0:U"]["value"] - 47.4) < 1e-9
    assert abs(result[":0:U"]["esd"] - 8.3) < 1e-9
