"""Pytest configuration and fixtures for PowderLine tests."""

import importlib.abc
import importlib.machinery
import json
import os
import subprocess
import sys
import pytest
from pathlib import Path
import tempfile
import shutil

#: The shipped examples, independent of the working directory (review item 17).
EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


# ─── Suite markers (re/09, A13.6) ─────────────────────────────────────────────

#: The engine-class markers declared in pyproject.toml. Every test carries
#: exactly one of them (module-level ``pytestmark`` as a rule; per-test marks
#: only in a module that mixes classes), plus the optional ``slow``.
SUITE_MARKERS = ("core", "gsasii", "topas_gen", "topas_exec", "easydiffraction")


def pytest_collection_modifyitems(config, items):
    """Refuse a collection in which any test has zero or several suite markers.

    The suite tasks (``pixi run test`` / ``test-gsasii`` / ...) select on these
    markers, so an unmarked test would run in no suite and a doubly marked one
    in two (and under the core guard). ``--strict-markers`` catches misspelt
    names; this catches missing or duplicated ones.
    """
    bad = []
    for item in items:
        found = sorted({m.name for m in item.iter_markers() if m.name in SUITE_MARKERS})
        if len(found) != 1:
            bad.append(f"{item.nodeid}: {found or 'no suite marker'}")
    if bad:
        shown = "\n  ".join(bad[:20])
        more = f"\n  ... and {len(bad) - 20} more" if len(bad) > 20 else ""
        raise pytest.UsageError(
            f"{len(bad)} test(s) without exactly one suite marker {SUITE_MARKERS}:\n  {shown}{more}"
        )


# ─── The core guard (re/09, P-26; master plan invariant §4.4) ─────────────────
#
# A pytest run restricted to the engine-free suites (`-m core`, `-m topas_gen`,
# `-m "core or topas_gen"`, ... -- any -m expression that can select no
# gsasii/easydiffraction/topas_exec item) must pass in an env that HAS the
# engines without ever importing one: that is the enforceable form of the
# no-plugin guarantee. The guard is installed in pytest_configure, before
# collection, so a module-level engine import in a mis-marked test fails too;
# a module that imports its engine through pytest.importorskip is skipped, as
# it would be in the real core env.
#
# POWDERLINE_CORE_GUARD=1 forces the guard on (e.g. for a `-k` or path
# selection), =0 forces it off.

CORE_GUARD_ENV = "POWDERLINE_CORE_GUARD"

#: Top-level packages no core/topas_gen test may import: the engines and their
#: calculators (P-21); a test that needs one is `gsasii` or `easydiffraction`.
CORE_GUARD_BLOCKED = ("GSASII", "easydiffraction", "cryspy", "pycrysfml", "crysfml")

ENGINE_MARKERS = tuple(m for m in SUITE_MARKERS if m not in ("core", "topas_gen"))


def markexpr_excludes_engines(markexpr: str) -> bool:
    """True if the ``-m`` expression can select no engine-marked item.

    Evaluated the way pytest does: for each engine marker, an item carrying it
    (alone or with ``slow``) must be deselected. An empty or unparsable
    expression selects everything, so the guard stays off.
    """
    if not markexpr or not markexpr.strip():
        return False
    try:
        from _pytest.mark.expression import Expression

        expr = Expression.compile(markexpr)
    except Exception:
        return False
    for name in ENGINE_MARKERS:
        for marks in ({name}, {name, "slow"}):
            if expr.evaluate(lambda n, marks=marks: n in marks):
                return False
    return True


class _CoreGuardFinder(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    """Claims every blocked package and refuses to create it.

    ``find_spec`` returns a spec (so ``importlib.util.find_spec`` still reports
    the engine as present and a ``skipif(find_spec(...) is None)`` keeps its
    meaning); the import itself raises ``ModuleNotFoundError`` naming the guard.
    """

    def find_spec(self, name, path, target=None):
        if name.partition(".")[0] in CORE_GUARD_BLOCKED:
            return importlib.machinery.ModuleSpec(name, self)
        return None

    def create_module(self, spec):
        raise ModuleNotFoundError(
            f"import of {spec.name!r} blocked by the PowderLine core guard (P-26): this pytest run is "
            f"restricted to the engine-free suites, so the test that imported it is marked wrong, or core "
            f"code gained an engine import. Unset the restriction or set {CORE_GUARD_ENV}=0 to run it.",
            name=spec.name,
        )

    def exec_module(self, module):  # pragma: no cover - create_module always raises
        raise ModuleNotFoundError(module.__name__, name=module.__name__)


def _install_core_guard():
    already = sorted(m for m in sys.modules if m.partition(".")[0] in CORE_GUARD_BLOCKED)
    if already:
        raise pytest.UsageError(f"core guard: engine modules already imported before the guard: {already}")
    sys.meta_path.insert(0, _CoreGuardFinder())

    # tc.exe must never run from an engine-free suite: where the native TOPAS
    # runner would call its default (un-injected) subprocess.run, it gets a
    # runner that raises instead. Discovery still works (a run without tc.exe
    # is the generate-only path, tested in topas_gen); tests inject fake runners.
    from powderline.gateways.topas import native_run

    def _refusing_runner(command, **kwargs):
        raise RuntimeError(
            f"executing {command[0]!r} blocked by the PowderLine core guard (P-26): running tc.exe is a "
            "topas_exec test, not core/topas_gen."
        )

    real_run_tc = native_run.run_tc

    def guarded_run_tc(tc, inp, runner=subprocess.run, **kwargs):
        return real_run_tc(tc, inp, runner=_refusing_runner if runner is subprocess.run else runner, **kwargs)

    native_run.run_tc = guarded_run_tc


def pytest_configure(config):
    forced = os.environ.get(CORE_GUARD_ENV)
    if forced in ("0", "1"):
        active = forced == "1"
    else:
        active = markexpr_excludes_engines(config.getoption("markexpr") or "")
    config._powderline_core_guard = active
    if active:
        _install_core_guard()


def pytest_report_header(config):
    if getattr(config, "_powderline_core_guard", False):
        return f"PowderLine core guard: ON (blocked imports: {', '.join(CORE_GUARD_BLOCKED)}; tc.exe execution refused)"
    return "PowderLine core guard: off (unrestricted run)"


@pytest.fixture(scope="session")
def core_guard_active(request) -> bool:
    """Whether this run installed the core guard (see pytest_configure)."""
    return bool(getattr(request.config, "_powderline_core_guard", False))
@pytest.fixture(autouse=True)
def _private_server_state(request, tmp_path_factory, monkeypatch):
    """Keep every test away from the developer's real GSAS-II server state.

    A probe there would create the per-user state directory and could submit
    jobs to the developer's own running server. Each test gets a private
    directory instead (in-process only; subprocesses are unaffected). The
    state-path logic itself is tested in test_gsas_server_unit.py, which
    isolates every case explicitly.
    """
    if request.module.__name__.endswith("test_gsas_server_unit"):
        return
    from powderline.gateways.gsasii import server as gsas_server

    root = tmp_path_factory.mktemp("server_state")
    root.chmod(0o700)
    monkeypatch.setattr(gsas_server, "_state_dir_path", lambda: root / "powderline")


@pytest.fixture
def example_LaB6_dir():
    """Path to example_LaB6 directory."""
    return EXAMPLES / "example_LaB6"


@pytest.fixture
def example_LaB6_input(example_LaB6_dir):
    """Path to example_LaB6 input.json file."""
    return example_LaB6_dir / "input.json"


@pytest.fixture
def example_LaB6_reference_lst(example_LaB6_dir):
    """Path to example_LaB6 reference .lst output file."""
    return example_LaB6_dir / "output" / "dummy.lst"  # Fixed filename in schema 0.25


@pytest.fixture
def example_LaB6_reference_unit_cell_csv(example_LaB6_dir):
    """Path to example_LaB6 reference unit cell CSV file."""
    return example_LaB6_dir / "output" / "LaB6_unit_cell_report.csv"


@pytest.fixture
def example_LaB6_reference_peak_csv(example_LaB6_dir):
    """Path to example_LaB6 reference peak list CSV file."""
    return example_LaB6_dir / "output" / "LaB6_peak_list_report.csv"


@pytest.fixture
def example_LaB6_reference_refined_params_csv(example_LaB6_dir):
    """Path to example_LaB6 reference refined_parameters.csv file."""
    return example_LaB6_dir / "output" / "refined_parameters.csv"


# LaB6 Simulation Example Fixtures
@pytest.fixture
def example_LaB6_simulation_dir():
    """Path to example_LaB6_simulation directory."""
    return EXAMPLES / "example_LaB6_simulation"


@pytest.fixture
def example_LaB6_simulation_input(example_LaB6_simulation_dir):
    """Path to example_LaB6_simulation input.json file."""
    return example_LaB6_simulation_dir / "input.json"


@pytest.fixture
def example_LaB6_simulation_reference_unit_cell_csv(example_LaB6_simulation_dir):
    """Path to example_LaB6_simulation reference unit cell CSV file."""
    return example_LaB6_simulation_dir / "output" / "LaB6_unit_cell_report.csv"


@pytest.fixture
def example_LaB6_simulation_reference_peak_csv(example_LaB6_simulation_dir):
    """Path to example_LaB6_simulation reference peak list CSV file."""
    return example_LaB6_simulation_dir / "output" / "LaB6_peak_list_report.csv"


# ─── API test fixtures ────────────────────────────────────────────────────────

@pytest.fixture
def recipe_LaB6_dict():
    """example_LaB6 recipe loaded as a plain dict (no model validation)."""
    return json.loads((EXAMPLES / "example_LaB6" / "input.json").read_text(encoding="utf-8"))


@pytest.fixture
def recipe_LaB6_model(recipe_LaB6_dict):
    """example_LaB6 recipe as its validated model (GsasiiRietveldRecipe)."""
    import powderline
    return powderline.validate(recipe_LaB6_dict).recipe


# ─── Shared tmp_output_dir ────────────────────────────────────────────────────

@pytest.fixture
def tmp_output_dir(tmp_path):
    """Create a temporary output directory that auto-cleans."""
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    yield output_dir
    # Cleanup handled by tmp_path fixture


# DRX_33 Multi-Phase Example Fixtures
@pytest.fixture
def example_DRX_33_dir():
    """Path to example_DRX_33 directory."""
    return EXAMPLES / "example_DRX_33"


@pytest.fixture
def example_DRX_33_input(example_DRX_33_dir):
    """Path to example_DRX_33 input.json file."""
    return example_DRX_33_dir / "input.json"


@pytest.fixture
def example_DRX_33_reference_lst(example_DRX_33_dir):
    """Path to example_DRX_33 reference .lst output file."""
    return example_DRX_33_dir / "output" / "dummy.lst"


@pytest.fixture
def example_DRX_33_reference_unit_cell_csvs(example_DRX_33_dir):
    """Paths to example_DRX_33 reference unit cell CSV files (both phases)."""
    return {
        "DRX_33": example_DRX_33_dir / "output" / "DRX_33_unit_cell_report.csv",
        "Li4MgWO6_SG12": example_DRX_33_dir / "output" / "Li4MgWO6_SG12_unit_cell_report.csv"
    }


@pytest.fixture
def example_DRX_33_reference_peak_csvs(example_DRX_33_dir):
    """Paths to example_DRX_33 reference peak list CSV files (both phases)."""
    return {
        "DRX_33": example_DRX_33_dir / "output" / "DRX_33_peak_list_report.csv",
        "Li4MgWO6_SG12": example_DRX_33_dir / "output" / "Li4MgWO6_SG12_peak_list_report.csv"
    }


@pytest.fixture
def example_DRX_33_reference_refined_params_csv(example_DRX_33_dir):
    """Path to example_DRX_33 reference refined_parameters.csv file."""
    return example_DRX_33_dir / "output" / "refined_parameters.csv"


# ─── MP Pipeline fixtures ─────────────────────────────────────────────────────

@pytest.fixture
def lab6_structure_data():
    """Synthetic structure data for LaB6 in the builder's input format (the shape RandomXRD's Materials Project fetch produced).

    Uses LaB6 lattice parameters from examples/example_LaB6/input.json.
    """
    return {
        'material_id': 'mp-2680',
        'cif': '',  # Not used by SimulationRecipeBuilder
        'formula': 'LaB6',
        # Condensed spglib-style symbol (as Materials Project emits); the
        # simulation builder writes the canonical gemmi name (A105)
        'space_group': 'Pm-3m',
        'unit_cell': {
            'a': 4.15682,
            'b': 4.15682,
            'c': 4.15682,
            'alpha': 90.0,
            'beta': 90.0,
            'gamma': 90.0,
            'volume': 71.82632674659455,
        },
        # Every atom of the conventional cell, as a Materials Project structure lists
        # them (1 La on 1a, the 6 B of site 6f); the builder reduces them to one
        # representative per orbit
        'sites': [
            {'element': 'La', 'x': 0.0, 'y': 0.0, 'z': 0.0,
             'occupancy': 1.0, 'label': 'La1'},
            {'element': 'B', 'x': 0.5, 'y': 0.5, 'z': 0.2021,
             'occupancy': 1.0, 'label': 'B1'},
            {'element': 'B', 'x': 0.5, 'y': 0.5, 'z': 0.7979,
             'occupancy': 1.0, 'label': 'B2'},
            {'element': 'B', 'x': 0.2021, 'y': 0.5, 'z': 0.5,
             'occupancy': 1.0, 'label': 'B3'},
            {'element': 'B', 'x': 0.7979, 'y': 0.5, 'z': 0.5,
             'occupancy': 1.0, 'label': 'B4'},
            {'element': 'B', 'x': 0.5, 'y': 0.2021, 'z': 0.5,
             'occupancy': 1.0, 'label': 'B5'},
            {'element': 'B', 'x': 0.5, 'y': 0.7979, 'z': 0.5,
             'occupancy': 1.0, 'label': 'B6'},
        ],
        'is_ordered': True,
        'metadata': {
            'material_id': 'mp-2680',
            'formula': 'LaB6',
            'space_group': 'Pm-3m',
            'space_group_number': 221,
            'crystal_system': 'cubic',
            'nelements': 2,
            'num_atoms': 7.0,
            'energy_above_hull': 0.0,
            'theoretical': False,
        },
    }


# DRX_33 Simulation Example Fixtures
@pytest.fixture
def example_DRX_33_simulation_dir():
    """Path to example_DRX_33_simulation directory."""
    return EXAMPLES / "example_DRX_33_simulation"


@pytest.fixture
def example_DRX_33_simulation_input(example_DRX_33_simulation_dir):
    """Path to example_DRX_33_simulation input.json file."""
    return example_DRX_33_simulation_dir / "input.json"


@pytest.fixture
def example_DRX_33_simulation_reference_unit_cell_csvs(example_DRX_33_simulation_dir):
    """Paths to example_DRX_33_simulation reference unit cell CSV files (both phases)."""
    return {
        "DRX_33": example_DRX_33_simulation_dir / "output" / "DRX_33_unit_cell_report.csv",
        "Li4MgWO6_SG12": example_DRX_33_simulation_dir / "output" / "Li4MgWO6_SG12_unit_cell_report.csv"
    }


@pytest.fixture
def example_DRX_33_simulation_reference_peak_csvs(example_DRX_33_simulation_dir):
    """Paths to example_DRX_33_simulation reference peak list CSV files (both phases)."""
    return {
        "DRX_33": example_DRX_33_simulation_dir / "output" / "DRX_33_peak_list_report.csv",
        "Li4MgWO6_SG12": example_DRX_33_simulation_dir / "output" / "Li4MgWO6_SG12_peak_list_report.csv"
    }


# LaB6 single-peak-fit example fixtures
@pytest.fixture
def example_LaB6_singlepeakfit_dir():
    """Path to example_LaB6_singlepeakfit directory."""
    return EXAMPLES / "example_LaB6_singlepeakfit"


@pytest.fixture
def example_LaB6_singlepeakfit_input(example_LaB6_singlepeakfit_dir):
    """Path to example_LaB6_singlepeakfit input.json file."""
    return example_LaB6_singlepeakfit_dir / "input.json"


@pytest.fixture
def example_LaB6_singlepeakfit_reference_single_peaks_txt(example_LaB6_singlepeakfit_dir):
    """Path to example_LaB6_singlepeakfit reference single_peaks_report.txt file."""
    return example_LaB6_singlepeakfit_dir / "output" / "single_peaks_report.txt"

# ============================================================================
# example_DRX_33_atomrefine fixtures
# ============================================================================

@pytest.fixture
def example_DRX_33_atomrefine_dir():
    """Path to example_DRX_33_atomrefine directory."""
    return EXAMPLES / "example_DRX_33_atomrefine"


@pytest.fixture
def example_DRX_33_atomrefine_input(example_DRX_33_atomrefine_dir):
    """Path to example_DRX_33_atomrefine input.json file."""
    return example_DRX_33_atomrefine_dir / "input.json"


@pytest.fixture
def example_DRX_33_atomrefine_reference_lst(example_DRX_33_atomrefine_dir):
    """Path to example_DRX_33_atomrefine reference .lst output file."""
    return example_DRX_33_atomrefine_dir / "output" / "dummy.lst"


@pytest.fixture
def example_DRX_33_atomrefine_reference_unit_cell_csvs(example_DRX_33_atomrefine_dir):
    """Paths to example_DRX_33_atomrefine reference unit cell CSV files (both phases)."""
    return {
        "DRX_33": example_DRX_33_atomrefine_dir / "output" / "DRX_33_unit_cell_report.csv",
        "Li4MgWO6_SG12": example_DRX_33_atomrefine_dir / "output" / "Li4MgWO6_SG12_unit_cell_report.csv"
    }


@pytest.fixture
def example_DRX_33_atomrefine_reference_peak_csvs(example_DRX_33_atomrefine_dir):
    """Paths to example_DRX_33_atomrefine reference peak list CSV files (both phases)."""
    return {
        "DRX_33": example_DRX_33_atomrefine_dir / "output" / "DRX_33_peak_list_report.csv",
        "Li4MgWO6_SG12": example_DRX_33_atomrefine_dir / "output" / "Li4MgWO6_SG12_peak_list_report.csv"
    }


@pytest.fixture
def example_DRX_33_atomrefine_reference_refined_params_csv(example_DRX_33_atomrefine_dir):
    """Path to example_DRX_33_atomrefine reference refined_parameters.csv file."""
    return example_DRX_33_atomrefine_dir / "output" / "refined_parameters.csv"


# ============================================================================
# example_DRX_33_anisoADP fixtures
# ============================================================================

@pytest.fixture
def example_DRX_33_anisoADP_dir():
    """Path to example_DRX_33_anisoADP directory."""
    return EXAMPLES / "example_DRX_33_anisoADP"


@pytest.fixture
def example_DRX_33_anisoADP_input(example_DRX_33_anisoADP_dir):
    """Path to example_DRX_33_anisoADP input.json file."""
    return example_DRX_33_anisoADP_dir / "input.json"


@pytest.fixture
def example_DRX_33_anisoADP_reference_lst(example_DRX_33_anisoADP_dir):
    """Path to example_DRX_33_anisoADP reference .lst output file."""
    return example_DRX_33_anisoADP_dir / "output" / "dummy.lst"


@pytest.fixture
def example_DRX_33_anisoADP_reference_unit_cell_csvs(example_DRX_33_anisoADP_dir):
    """Paths to example_DRX_33_anisoADP reference unit cell CSV files (both phases)."""
    return {
        "DRX_33": example_DRX_33_anisoADP_dir / "output" / "DRX_33_unit_cell_report.csv",
        "Li4MgWO6_SG12": example_DRX_33_anisoADP_dir / "output" / "Li4MgWO6_SG12_unit_cell_report.csv"
    }


@pytest.fixture
def example_DRX_33_anisoADP_reference_peak_csvs(example_DRX_33_anisoADP_dir):
    """Paths to example_DRX_33_anisoADP reference peak list CSV files (both phases)."""
    return {
        "DRX_33": example_DRX_33_anisoADP_dir / "output" / "DRX_33_peak_list_report.csv",
        "Li4MgWO6_SG12": example_DRX_33_anisoADP_dir / "output" / "Li4MgWO6_SG12_peak_list_report.csv"
    }


@pytest.fixture
def example_DRX_33_anisoADP_reference_refined_params_csv(example_DRX_33_anisoADP_dir):
    """Path to example_DRX_33_anisoADP reference refined_parameters.csv file."""
    return example_DRX_33_anisoADP_dir / "output" / "refined_parameters.csv"


# ============================================================================
# example_DRX_33_strainonly fixtures
# ============================================================================

@pytest.fixture
def example_DRX_33_strainonly_dir():
    """Path to example_DRX_33_strainonly directory."""
    return EXAMPLES / "example_DRX_33_strainonly"


@pytest.fixture
def example_DRX_33_strainonly_input(example_DRX_33_strainonly_dir):
    """Path to example_DRX_33_strainonly input.json file."""
    return example_DRX_33_strainonly_dir / "input.json"


@pytest.fixture
def example_DRX_33_strainonly_reference_lst(example_DRX_33_strainonly_dir):
    """Path to example_DRX_33_strainonly reference .lst output file."""
    return example_DRX_33_strainonly_dir / "output" / "dummy.lst"


@pytest.fixture
def example_DRX_33_strainonly_reference_unit_cell_csvs(example_DRX_33_strainonly_dir):
    """Paths to example_DRX_33_strainonly reference unit cell CSV files (both phases)."""
    return {
        "DRX_33": example_DRX_33_strainonly_dir / "output" / "DRX_33_unit_cell_report.csv",
        "Li4MgWO6_SG12": example_DRX_33_strainonly_dir / "output" / "Li4MgWO6_SG12_unit_cell_report.csv"
    }


@pytest.fixture
def example_DRX_33_strainonly_reference_peak_csvs(example_DRX_33_strainonly_dir):
    """Paths to example_DRX_33_strainonly reference peak list CSV files (both phases)."""
    return {
        "DRX_33": example_DRX_33_strainonly_dir / "output" / "DRX_33_peak_list_report.csv",
        "Li4MgWO6_SG12": example_DRX_33_strainonly_dir / "output" / "Li4MgWO6_SG12_peak_list_report.csv"
    }


@pytest.fixture
def example_DRX_33_strainonly_reference_refined_params_csv(example_DRX_33_strainonly_dir):
    """Path to example_DRX_33_strainonly reference refined_parameters.csv file."""
    return example_DRX_33_strainonly_dir / "output" / "refined_parameters.csv"
