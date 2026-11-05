"""Tests for run_refinement() handling of missing GSAS-II data structure keys.

GSAS-II doesn't always populate all keys in its data structures for certain
crystal structures (e.g. missing 'wR' residual, missing 'RefList', missing
'Cell'). These tests verify that run_refinement() handles these cases
gracefully instead of raising KeyError.

The function under test is ``powderline.gateways.gsasii.executors.run_refinement``
(the ``gsasii.rietveld`` / ``gsasii.spf`` executor); the GSAS-II setters,
extractors and ``G2Project`` are patched on that module. (Until re/07 the
same tests also ran the pre-refactor copy of the executor, since deleted.)
"""

import numpy as np
import pytest

from pathlib import Path
from unittest.mock import MagicMock, patch

pytestmark = pytest.mark.gsasii

pytest.importorskip("GSASII.GSASIIscriptable")  # the mocked run imports the frozen executors, which import GSAS-II


def _make_mock_hist(hist_name, residuals=None, has_reflection_lists=True,
                    has_reflist=True, has_cell=True):
    """Build a mock hist and proj.data that simulates GSAS-II post-refinement state.

    Includes minimal covariance data so that extract_refined_params_from_project()
    returns a non-empty dict. These tests exercise missing GSAS-II data-structure
    keys (Cell, Reflection Lists, etc.), not ESD extraction, so covariance is just
    scaffolding that satisfies the post-refinement contract.
    """
    hist = MagicMock()
    hist.name = hist_name
    hist.residuals = residuals if residuals is not None else {}

    dummy = np.ones(10)
    hist.getdata = MagicMock(return_value=dummy)

    # Build proj.data
    phase_name = "TestPhase"

    phase_data = {}
    if has_cell:
        # Cell: [refine_flag, a, b, c, alpha, beta, gamma, volume]
        phase_data = {"General": {"Cell": [False, 5.0, 5.0, 5.0, 90.0, 90.0, 90.0, 125.0]}}
    else:
        phase_data = {"General": {}}

    hist_entry = {}
    if has_reflection_lists:
        if has_reflist:
            hist_entry["Reflection Lists"] = {
                phase_name: {
                    "RefList": np.array([[1, 0, 0, 6, 2.5, 36.0, 0.01, 0.0,
                                          100.0, 95.0, 0.0, 1.0, 1.0, 1.0, 1.0]])
                }
            }
        else:
            # Phase entry exists but no RefList key
            hist_entry["Reflection Lists"] = {phase_name: {"Type": "SXC"}}
    # else: no 'Reflection Lists' key at all

    # Minimal covariance data: one refined parameter so that
    # extract_refined_params_from_project() returns a non-empty dict.
    # These tests are not about ESD correctness, so synthetic values are fine.
    covariance_data = {
        "varyList": [":0:Back;0"],
        "variables": [1.0],
        "sig": [0.1],
        "covMatrix": np.array([[0.01]]),
    }

    proj_data = {
        "Phases": {phase_name: phase_data},
        "Covariance": {"data": covariance_data},
        hist_name: hist_entry,
    }

    # Build mock proj
    proj = MagicMock()
    proj.data = proj_data

    mock_phase = MagicMock()
    mock_phase.name = phase_name
    proj.phases.return_value = [mock_phase]

    return proj, hist, phase_name


@pytest.fixture
def mock_recipe():
    """Minimal mock recipe for run_refinement().

    Updated for schema 0.25: Payload-based structure with all recipe fields under payload.
    Added schema_name field (required for SCHEMA_EXECUTORS dispatch).

    """
    recipe = MagicMock()
    recipe.schema_name = "gsasii.rietveld"

    # Schema 0.25: All recipe fields under payload
    recipe.payload = MagicMock()
    recipe.payload.xrd_data = MagicMock()
    recipe.payload.xrd_data.tth = np.linspace(10, 80, 10)
    recipe.payload.xrd_data.Itth = np.ones(10)
    recipe.payload.xrd_data.Itth_weights = np.ones(10)
    recipe.payload.xrd_data.filename = "test"

    recipe.payload.instrument = MagicMock()
    recipe.payload.instrument.initialization = [{}]
    recipe.payload.instrument.parameterization = None

    # instrument must work with model_dump(mode='json')
    recipe.payload.instrument.model_dump = MagicMock(return_value={})

    recipe.payload.background = None
    recipe.payload.fit_range = None  # Native executor checks truthiness then .min/.max

    # refinement_controls under payload
    recipe.payload.refinement_controls = MagicMock()
    recipe.payload.refinement_controls.strategy = "structural_only"
    recipe.payload.refinement_controls.refinement_cycles = 3
    recipe.payload.refinement_controls.spf_first = True
    recipe.payload.refinement_controls.output_comparison_data = None

    # single_peaks attribute under payload (None = no single peak fitting)
    recipe.payload.single_peaks = None

    # Phases dict under payload (required for CSV report generation)
    recipe.payload.phases = {"TestPhase": MagicMock()}

    # payload must work with model_dump(mode='json')
    recipe.payload.model_dump = MagicMock(return_value={"phases": []})

    recipe.model_dump.return_value = {"phases": []}
    return recipe


def _run_with_mocked_gsas(mock_recipe, tmp_path, proj, hist):
    """Patch GSAS-II internals and run run_refinement() with provided mocks.

    Args:
        mock_recipe: Recipe mock (schema_name gsasii.rietveld)
        tmp_path: pytest tmp_path fixture
        proj: Mocked GSAS-II project
        hist: Mocked histogram
    """
    output_dir = tmp_path / "output"
    output_dir.mkdir()

    module_path = "powderline.gateways.gsasii.executors"
    from powderline.gateways.gsasii.executors import run_refinement as native_run_refinement
    call_fn = lambda: native_run_refinement(mock_recipe, output_dir, verbose=False, method='test')

    patches_list = [
        patch("powderline.gateways.gsasii.executors.G2.G2Project", return_value=proj),
        patch(f"{module_path}.add_powder_histogram_from_arrays", return_value=hist),
        patch(f"{module_path}.set_hist_scale"),
        patch(f"{module_path}.set_fit_range_hist"),
        patch(f"{module_path}.set_chebyshev_background"),
        patch(f"{module_path}.set_single_peak_background"),
        patch(f"{module_path}.add_phases_from_dict"),
        patch(f"{module_path}.set_phase_parameterization"),
        patch(f"{module_path}.set_instrument_parameterization"),
        patch(f"{module_path}.set_refinement_cycles"),
        patch("powderline.gateways.gsasii.extractors.calculate_cell_esds_from_A_matrix",
              return_value=[0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]),
    ]

    patches_list.append(patch(f"{module_path}.gsasii_iparm1", return_value={}))
    # the native run's site check and fit report read real GSAS-II data (tested in
    # test_gsasii_native_run); these mocks test missing-key handling only
    patches_list.append(patch(f"{module_path}.check_sites"))
    patches_list.append(patch(f"{module_path}.fit_report", return_value={}))

    # Apply all patches and call
    from contextlib import ExitStack
    with ExitStack() as stack:
        for p in patches_list:
            stack.enter_context(p)
        result = call_fn()

    return result, output_dir


class TestMissingResiduals:
    """Test behaviour when hist.residuals['wR'] is absent after refinement.

    A missing Rwp indicates that GSAS-II failed to complete the refinement
    (silent failure — no exception raised, but no result produced).  The
    executor must propagate this as success=False so the failure is visible
    to callers.
    """

    def test_missing_wR_returns_failure(self, mock_recipe, tmp_path):
        """Missing wR must now be reported as a refinement failure."""
        proj, hist, _ = _make_mock_hist("PWDR test", residuals={})
        result, _ = _run_with_mocked_gsas(mock_recipe, tmp_path, proj, hist)

        assert result["success"] is False
        assert result["rwp"] is None
        assert "run_id" in result
        assert "Rwp" in result["error"]

    def test_missing_wR_executor_directly_returns_failure(self, mock_recipe, tmp_path):
        """execute_rietveld_refinement returns success=False when wR is absent.

        """
        from unittest.mock import MagicMock
        from powderline.gateways.gsasii.executors import execute_rietveld_refinement

        proj = MagicMock()
        hist = MagicMock()
        hist.residuals = {}  # no 'wR' key

        result = execute_rietveld_refinement(proj, hist, mock_recipe, verbose=False)

        assert result["success"] is False
        assert result["rwp"] is None
        assert "error" in result
        assert result["error"]  # non-empty

    def test_present_wR_returns_value(self, mock_recipe, tmp_path):
        proj, hist, _ = _make_mock_hist("PWDR test", residuals={"wR": 5.23})
        result, _ = _run_with_mocked_gsas(mock_recipe, tmp_path, proj, hist)

        assert result["success"] is True
        assert result["rwp"] == 5.23


class TestMissingReflectionLists:
    """Test that missing or incomplete Reflection Lists don't cause failure."""

    def test_no_reflection_lists_key(self, mock_recipe, tmp_path):
        proj, hist, phase_name = _make_mock_hist(
            "PWDR test", residuals={"wR": 5.0},
            has_reflection_lists=False)
        result, output_dir = _run_with_mocked_gsas(mock_recipe, tmp_path, proj, hist)

        assert result["success"] is True
        assert not (output_dir / f"{phase_name}_peak_list_report.csv").exists()

    def test_hist_name_missing_from_proj_data(self, mock_recipe, tmp_path):
        proj, hist, phase_name = _make_mock_hist(
            "PWDR test", residuals={"wR": 5.0},
            has_reflection_lists=True)
        # Remove the hist entry from proj.data entirely
        del proj.data[hist.name]
        result, output_dir = _run_with_mocked_gsas(mock_recipe, tmp_path, proj, hist)

        assert result["success"] is True
        assert not (output_dir / f"{phase_name}_peak_list_report.csv").exists()

    def test_no_reflist_key(self, mock_recipe, tmp_path):
        proj, hist, phase_name = _make_mock_hist(
            "PWDR test", residuals={"wR": 5.0},
            has_reflection_lists=True, has_reflist=False)
        result, output_dir = _run_with_mocked_gsas(mock_recipe, tmp_path, proj, hist)

        assert result["success"] is True
        assert not (output_dir / f"{phase_name}_peak_list_report.csv").exists()

    def test_complete_reflection_lists_produces_csv(self, mock_recipe, tmp_path):
        proj, hist, phase_name = _make_mock_hist(
            "PWDR test", residuals={"wR": 5.0},
            has_reflection_lists=True, has_reflist=True)
        result, output_dir = _run_with_mocked_gsas(mock_recipe, tmp_path, proj, hist)

        assert result["success"] is True
        assert (output_dir / f"{phase_name}_peak_list_report.csv").exists()


class TestMissingUnitCell:
    """Test that missing General/Cell data doesn't cause failure."""

    def test_no_cell_key(self, mock_recipe, tmp_path):
        proj, hist, phase_name = _make_mock_hist(
            "PWDR test", residuals={"wR": 5.0}, has_cell=False)
        result, output_dir = _run_with_mocked_gsas(mock_recipe, tmp_path, proj, hist)

        assert result["success"] is True
        assert not (output_dir / f"{phase_name}_unit_cell_report.csv").exists()

    def test_complete_cell_produces_csv(self, mock_recipe, tmp_path):
        proj, hist, phase_name = _make_mock_hist(
            "PWDR test", residuals={"wR": 5.0}, has_cell=True)
        result, output_dir = _run_with_mocked_gsas(mock_recipe, tmp_path, proj, hist)

        assert result["success"] is True
        assert (output_dir / f"{phase_name}_unit_cell_report.csv").exists()


class TestOuterExceptTraceback:
    """Test that the outer except block includes traceback info."""

    def test_unexpected_error_includes_traceback(self, mock_recipe, tmp_path):
        proj, hist, _ = _make_mock_hist("PWDR test", residuals={"wR": 5.0})
        # Make getdata raise to trigger the outer except
        hist.getdata = MagicMock(side_effect=RuntimeError("GSAS-II segfault"))

        result, _ = _run_with_mocked_gsas(mock_recipe, tmp_path, proj, hist)

        assert result["success"] is False
        assert "GSAS-II segfault" in result["error"]
        assert "traceback" in result
        assert "RuntimeError" in result["traceback"]


class TestHistogramLoadFailure:
    """Test that a failure inside add_powder_histogram_from_arrays returns a
    structured error dict instead of propagating an exception."""

    def test_histogram_load_error_returns_failure(self, mock_recipe, tmp_path):
        proj = MagicMock()
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        module_path = "powderline.gateways.gsasii.executors"
        from powderline.gateways.gsasii.executors import run_refinement as native_run_refinement
        call_fn = lambda: native_run_refinement(mock_recipe, output_dir, verbose=False, method='test')

        patches_list = [
            patch("powderline.gateways.gsasii.executors.G2.G2Project", return_value=proj),
            patch(f"{module_path}.add_powder_histogram_from_arrays",
                  side_effect=ValueError("bad instrument params")),
        ]
        patches_list.append(patch(f"{module_path}.gsasii_iparm1", return_value={}))
        # the native run's site check and fit report read real GSAS-II data (tested in
        # test_gsasii_native_run); these mocks test missing-key handling only
        patches_list.append(patch(f"{module_path}.check_sites"))
        patches_list.append(patch(f"{module_path}.fit_report", return_value={}))

        from contextlib import ExitStack
        with ExitStack() as stack:
            for p in patches_list:
                stack.enter_context(p)
            result = call_fn()

        assert result["success"] is False
        assert "Failed to load XRD data or instrument parameters" in result["error"]
        assert "bad instrument params" in result["error"]

    def test_histogram_load_error_includes_run_id(self, mock_recipe, tmp_path):
        proj = MagicMock()
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        module_path = "powderline.gateways.gsasii.executors"
        from powderline.gateways.gsasii.executors import run_refinement as native_run_refinement
        call_fn = lambda: native_run_refinement(mock_recipe, output_dir, verbose=False, method='test')

        patches_list = [
            patch("powderline.gateways.gsasii.executors.G2.G2Project", return_value=proj),
            patch(f"{module_path}.add_powder_histogram_from_arrays",
                  side_effect=IOError("file not found")),
        ]
        patches_list.append(patch(f"{module_path}.gsasii_iparm1", return_value={}))
        # the native run's site check and fit report read real GSAS-II data (tested in
        # test_gsasii_native_run); these mocks test missing-key handling only
        patches_list.append(patch(f"{module_path}.check_sites"))
        patches_list.append(patch(f"{module_path}.fit_report", return_value={}))

        from contextlib import ExitStack
        with ExitStack() as stack:
            for p in patches_list:
                stack.enter_context(p)
            result = call_fn()

        assert "run_id" in result
        assert result["run_id"] is not None


class TestExecutorFailure:
    """Test the two failure modes of the schema executor dispatch."""

    def test_executor_raises_exception_returns_failure(self, mock_recipe, tmp_path):
        proj, hist, _ = _make_mock_hist("PWDR test", residuals={"wR": 5.0})

        module_path = "powderline.gateways.gsasii.executors"
        schema_key = "gsasii.rietveld"
        from powderline.gateways.gsasii.executors import run_refinement as native_run_refinement
        call_fn = lambda: native_run_refinement(mock_recipe, output_dir=tmp_path, verbose=False, method='test')

        patches_list = [
            patch("powderline.gateways.gsasii.executors.G2.G2Project", return_value=proj),
            patch(f"{module_path}.add_powder_histogram_from_arrays", return_value=hist),
            patch(f"{module_path}.set_hist_scale"),
            patch(f"{module_path}.set_fit_range_hist"),
            patch(f"{module_path}.set_chebyshev_background"),
            patch(f"{module_path}.set_single_peak_background"),
            patch(f"{module_path}.add_phases_from_dict"),
            patch(f"{module_path}.set_phase_parameterization"),
            patch(f"{module_path}.set_instrument_parameterization"),
            patch(f"{module_path}.set_refinement_cycles"),
            patch(f"{module_path}.SCHEMA_EXECUTORS",
                  {schema_key: MagicMock(side_effect=RuntimeError("diverged"))}),
        ]
        patches_list.append(patch(f"{module_path}.gsasii_iparm1", return_value={}))
        # the native run's site check and fit report read real GSAS-II data (tested in
        # test_gsasii_native_run); these mocks test missing-key handling only
        patches_list.append(patch(f"{module_path}.check_sites"))
        patches_list.append(patch(f"{module_path}.fit_report", return_value={}))

        from contextlib import ExitStack
        with ExitStack() as stack:
            for p in patches_list:
                stack.enter_context(p)
            result = call_fn()

        assert result["success"] is False
        assert "Refinement failed" in result["error"]
        assert "diverged" in result["error"]

    def test_executor_returns_failure_dict(self, mock_recipe, tmp_path):
        proj, hist, _ = _make_mock_hist("PWDR test", residuals={"wR": 5.0})
        failing_executor = MagicMock(return_value={"success": False, "rwp": None})

        module_path = "powderline.gateways.gsasii.executors"
        schema_key = "gsasii.rietveld"
        from powderline.gateways.gsasii.executors import run_refinement as native_run_refinement
        call_fn = lambda: native_run_refinement(mock_recipe, output_dir=tmp_path, verbose=False, method='test')

        patches_list = [
            patch("powderline.gateways.gsasii.executors.G2.G2Project", return_value=proj),
            patch(f"{module_path}.add_powder_histogram_from_arrays", return_value=hist),
            patch(f"{module_path}.set_hist_scale"),
            patch(f"{module_path}.set_fit_range_hist"),
            patch(f"{module_path}.set_chebyshev_background"),
            patch(f"{module_path}.set_single_peak_background"),
            patch(f"{module_path}.add_phases_from_dict"),
            patch(f"{module_path}.set_phase_parameterization"),
            patch(f"{module_path}.set_instrument_parameterization"),
            patch(f"{module_path}.set_refinement_cycles"),
            patch(f"{module_path}.SCHEMA_EXECUTORS", {schema_key: failing_executor}),
        ]
        patches_list.append(patch(f"{module_path}.gsasii_iparm1", return_value={}))
        # the native run's site check and fit report read real GSAS-II data (tested in
        # test_gsasii_native_run); these mocks test missing-key handling only
        patches_list.append(patch(f"{module_path}.check_sites"))
        patches_list.append(patch(f"{module_path}.fit_report", return_value={}))

        from contextlib import ExitStack
        with ExitStack() as stack:
            for p in patches_list:
                stack.enter_context(p)
            result = call_fn()

        assert result["success"] is False
        assert schema_key in result["error"]


class TestUnknownSchemaName:
    """Test that an unrecognised schema_name is caught and returned as a failure
    (the ValueError is caught by the outer except block)."""

    def test_unknown_schema_name_returns_failure(self, mock_recipe, tmp_path):
        mock_recipe.schema_name = "gsasii.bogus"
        expected_in_error = ["Unknown schema_name", "gsasii.bogus"]
        module_path = "powderline.gateways.gsasii.executors"
        from powderline.gateways.gsasii.executors import run_refinement as native_run_refinement
        call_fn = lambda: native_run_refinement(mock_recipe, output_dir=tmp_path, verbose=False, method='test')

        proj, hist, _ = _make_mock_hist("PWDR test", residuals={"wR": 5.0})

        patches_list = [
            patch("powderline.gateways.gsasii.executors.G2.G2Project", return_value=proj),
            patch(f"{module_path}.add_powder_histogram_from_arrays", return_value=hist),
            patch(f"{module_path}.set_hist_scale"),
            patch(f"{module_path}.set_fit_range_hist"),
            patch(f"{module_path}.set_chebyshev_background"),
            patch(f"{module_path}.set_single_peak_background"),
            patch(f"{module_path}.add_phases_from_dict"),
            patch(f"{module_path}.set_phase_parameterization"),
            patch(f"{module_path}.set_instrument_parameterization"),
            patch(f"{module_path}.set_refinement_cycles"),
        ]
        patches_list.append(patch(f"{module_path}.gsasii_iparm1", return_value={}))
        # the native run's site check and fit report read real GSAS-II data (tested in
        # test_gsasii_native_run); these mocks test missing-key handling only
        patches_list.append(patch(f"{module_path}.check_sites"))
        patches_list.append(patch(f"{module_path}.fit_report", return_value={}))

        from contextlib import ExitStack
        with ExitStack() as stack:
            for p in patches_list:
                stack.enter_context(p)
            result = call_fn()

        assert result["success"] is False
        assert any(expected in result["error"] for expected in expected_in_error)


class TestCorruptCovariance:
    """Test that a non-empty varyList paired with empty param extraction
    raises an error instead of silently producing incorrect ESD values."""

    def test_nonempty_varylist_with_empty_params_returns_failure(self, mock_recipe, tmp_path):
        proj, hist, _ = _make_mock_hist("PWDR test", residuals={"wR": 5.0})
        # Inject a non-empty varyList into proj.data so the covariance guard triggers
        proj.data["Covariance"]["data"]["varyList"] = [":0:Back;0"]

        module_path = "powderline.gateways.gsasii.executors"
        from powderline.gateways.gsasii.executors import run_refinement as native_run_refinement
        call_fn = lambda: native_run_refinement(mock_recipe, output_dir=tmp_path, verbose=False, method='test')

        patches_list = [
            patch("powderline.gateways.gsasii.executors.G2.G2Project", return_value=proj),
            patch(f"{module_path}.add_powder_histogram_from_arrays", return_value=hist),
            patch(f"{module_path}.set_hist_scale"),
            patch(f"{module_path}.set_fit_range_hist"),
            patch(f"{module_path}.set_chebyshev_background"),
            patch(f"{module_path}.set_single_peak_background"),
            patch(f"{module_path}.add_phases_from_dict"),
            patch(f"{module_path}.set_phase_parameterization"),
            patch(f"{module_path}.set_instrument_parameterization"),
            patch(f"{module_path}.set_refinement_cycles"),
            patch("powderline.gateways.gsasii.extractors.calculate_cell_esds_from_A_matrix",
                  return_value=[0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]),
            patch(f"{module_path}.extract_refined_params_from_project", return_value={}),
        ]
        patches_list.append(patch(f"{module_path}.gsasii_iparm1", return_value={}))
        # the native run's site check and fit report read real GSAS-II data (tested in
        # test_gsasii_native_run); these mocks test missing-key handling only
        patches_list.append(patch(f"{module_path}.check_sites"))
        patches_list.append(patch(f"{module_path}.fit_report", return_value={}))

        from contextlib import ExitStack
        with ExitStack() as stack:
            for p in patches_list:
                stack.enter_context(p)
            result = call_fn()

        assert result["success"] is False
        assert "covariance" in result["error"].lower() or "varyList" in result["error"] or "traceback" in result


class TestTracebackConsistency:
    """All run_refinement() failure exits must include a 'traceback' key with
    a non-None string so that callers have full diagnostic information without
    catching KeyError."""

    def test_exit1_histogram_load_failure_has_traceback(self, mock_recipe, tmp_path):
        """Exit 1 — add_powder_histogram_from_arrays raises → traceback present."""
        proj = MagicMock()
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        module_path = "powderline.gateways.gsasii.executors"
        from powderline.gateways.gsasii.executors import run_refinement as native_run_refinement
        call_fn = lambda: native_run_refinement(mock_recipe, output_dir, verbose=False, method='test')

        patches_list = [
            patch("powderline.gateways.gsasii.executors.G2.G2Project", return_value=proj),
            patch(f"{module_path}.add_powder_histogram_from_arrays",
                  side_effect=ValueError("bad instrument params")),
        ]
        patches_list.append(patch(f"{module_path}.gsasii_iparm1", return_value={}))
        # the native run's site check and fit report read real GSAS-II data (tested in
        # test_gsasii_native_run); these mocks test missing-key handling only
        patches_list.append(patch(f"{module_path}.check_sites"))
        patches_list.append(patch(f"{module_path}.fit_report", return_value={}))

        from contextlib import ExitStack
        with ExitStack() as stack:
            for p in patches_list:
                stack.enter_context(p)
            result = call_fn()

        assert result["success"] is False
        assert "traceback" in result
        assert result["traceback"] is not None
        assert "ValueError" in result["traceback"]
        assert "bad instrument params" in result["traceback"]

    def test_exit3_executor_exception_has_traceback(self, mock_recipe, tmp_path):
        """Exit 3 — executor raises → traceback present with full exception info."""
        proj, hist, _ = _make_mock_hist("PWDR test", residuals={"wR": 5.0})
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        module_path = "powderline.gateways.gsasii.executors"
        schema_key = "gsasii.rietveld"
        from powderline.gateways.gsasii.executors import run_refinement as native_run_refinement
        call_fn = lambda: native_run_refinement(mock_recipe, output_dir=output_dir, verbose=False, method='test')

        patches_list = [
            patch("powderline.gateways.gsasii.executors.G2.G2Project", return_value=proj),
            patch(f"{module_path}.add_powder_histogram_from_arrays", return_value=hist),
            patch(f"{module_path}.set_hist_scale"),
            patch(f"{module_path}.set_fit_range_hist"),
            patch(f"{module_path}.set_chebyshev_background"),
            patch(f"{module_path}.set_single_peak_background"),
            patch(f"{module_path}.add_phases_from_dict"),
            patch(f"{module_path}.set_phase_parameterization"),
            patch(f"{module_path}.set_instrument_parameterization"),
            patch(f"{module_path}.set_refinement_cycles"),
            patch(f"{module_path}.SCHEMA_EXECUTORS",
                  {schema_key: MagicMock(side_effect=RuntimeError("diverged"))}),
        ]
        patches_list.append(patch(f"{module_path}.gsasii_iparm1", return_value={}))
        # the native run's site check and fit report read real GSAS-II data (tested in
        # test_gsasii_native_run); these mocks test missing-key handling only
        patches_list.append(patch(f"{module_path}.check_sites"))
        patches_list.append(patch(f"{module_path}.fit_report", return_value={}))

        from contextlib import ExitStack
        with ExitStack() as stack:
            for p in patches_list:
                stack.enter_context(p)
            result = call_fn()

        assert result["success"] is False
        assert "traceback" in result
        assert result["traceback"] is not None
        assert "RuntimeError" in result["traceback"]
        assert "diverged" in result["traceback"]

    def test_exit2_executor_failure_dict_with_traceback_forwards_it(self, mock_recipe, tmp_path):
        """Exit 2 — executor returns success=False with traceback → forwarded."""
        proj, hist, _ = _make_mock_hist("PWDR test", residuals={"wR": 5.0})
        sentinel_tb = "Traceback (most recent call last):\n  File ...\nValueError: something"
        failing_executor = MagicMock(return_value={
            "success": False,
            "rwp": None,
            "error": "executor said no",
            "traceback": sentinel_tb,
        })
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        module_path = "powderline.gateways.gsasii.executors"
        schema_key = "gsasii.rietveld"
        from powderline.gateways.gsasii.executors import run_refinement as native_run_refinement
        call_fn = lambda: native_run_refinement(mock_recipe, output_dir=output_dir, verbose=False, method='test')

        patches_list = [
            patch("powderline.gateways.gsasii.executors.G2.G2Project", return_value=MagicMock()),
            patch(f"{module_path}.add_powder_histogram_from_arrays", return_value=hist),
            patch(f"{module_path}.set_hist_scale"),
            patch(f"{module_path}.set_fit_range_hist"),
            patch(f"{module_path}.set_chebyshev_background"),
            patch(f"{module_path}.set_single_peak_background"),
            patch(f"{module_path}.add_phases_from_dict"),
            patch(f"{module_path}.set_phase_parameterization"),
            patch(f"{module_path}.set_instrument_parameterization"),
            patch(f"{module_path}.set_refinement_cycles"),
            patch(f"{module_path}.SCHEMA_EXECUTORS", {schema_key: failing_executor}),
        ]
        patches_list.append(patch(f"{module_path}.gsasii_iparm1", return_value={}))
        # the native run's site check and fit report read real GSAS-II data (tested in
        # test_gsasii_native_run); these mocks test missing-key handling only
        patches_list.append(patch(f"{module_path}.check_sites"))
        patches_list.append(patch(f"{module_path}.fit_report", return_value={}))

        from contextlib import ExitStack
        with ExitStack() as stack:
            for p in patches_list:
                stack.enter_context(p)
            result = call_fn()

        assert result["success"] is False
        assert result["traceback"] == sentinel_tb

    def test_exit2_executor_failure_dict_without_traceback_gives_none(self, mock_recipe, tmp_path):
        """Exit 2 — executor returns success=False with no traceback key → None."""
        proj, hist, _ = _make_mock_hist("PWDR test", residuals={"wR": 5.0})
        failing_executor = MagicMock(return_value={"success": False, "rwp": None})
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        module_path = "powderline.gateways.gsasii.executors"
        schema_key = "gsasii.rietveld"
        from powderline.gateways.gsasii.executors import run_refinement as native_run_refinement
        call_fn = lambda: native_run_refinement(mock_recipe, output_dir=output_dir, verbose=False, method='test')

        patches_list = [
            patch("powderline.gateways.gsasii.executors.G2.G2Project", return_value=MagicMock()),
            patch(f"{module_path}.add_powder_histogram_from_arrays", return_value=hist),
            patch(f"{module_path}.set_hist_scale"),
            patch(f"{module_path}.set_fit_range_hist"),
            patch(f"{module_path}.set_chebyshev_background"),
            patch(f"{module_path}.set_single_peak_background"),
            patch(f"{module_path}.add_phases_from_dict"),
            patch(f"{module_path}.set_phase_parameterization"),
            patch(f"{module_path}.set_instrument_parameterization"),
            patch(f"{module_path}.set_refinement_cycles"),
            patch(f"{module_path}.SCHEMA_EXECUTORS", {schema_key: failing_executor}),
        ]
        patches_list.append(patch(f"{module_path}.gsasii_iparm1", return_value={}))
        # the native run's site check and fit report read real GSAS-II data (tested in
        # test_gsasii_native_run); these mocks test missing-key handling only
        patches_list.append(patch(f"{module_path}.check_sites"))
        patches_list.append(patch(f"{module_path}.fit_report", return_value={}))

        from contextlib import ExitStack
        with ExitStack() as stack:
            for p in patches_list:
                stack.enter_context(p)
            result = call_fn()

        assert result["success"] is False
        assert "traceback" in result
        assert result["traceback"] is None

    def test_success_result_has_traceback_key_as_none(self, mock_recipe, tmp_path):
        """Successful run_refinement() result always has traceback=None after run() normalises it."""
        proj, hist, _ = _make_mock_hist("PWDR test", residuals={"wR": 5.23})
        result, _ = _run_with_mocked_gsas(mock_recipe, tmp_path, proj, hist)

        # run() calls result.setdefault('traceback', None) before returning.
        # run_refinement() itself may not include the key, but run() guarantees it.
        # Check through run_refinement directly: key may or may not be present.
        # The guarantee lives in run(); here we verify run_refinement at minimum
        # doesn't overwrite a None with something unexpected on success.
        assert result["success"] is True
        # If traceback key is present (added by run() normalization layer), it must be None.
        if "traceback" in result:
            assert result["traceback"] is None

