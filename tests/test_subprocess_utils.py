"""subprocess_utils: command construction is cwd-independent (review item 17)."""
import json
from pathlib import Path

import pytest

import subprocess_utils

pytestmark = pytest.mark.core


def test_kicker_command_without_repo_root_is_unchanged(monkeypatch):
    monkeypatch.setenv(subprocess_utils.PIXI_ENV_OVERRIDE_VAR, "gsasii")
    assert subprocess_utils.kicker_command("x.json") == ["pixi", "run", "-e", "gsasii", "kicker", "--no-server", "x.json"]


def test_kicker_command_with_repo_root_pins_the_manifest(monkeypatch, tmp_path):
    monkeypatch.setenv(subprocess_utils.PIXI_ENV_OVERRIDE_VAR, "gsasii")
    cmd = subprocess_utils.kicker_command("x.json", repo_root=tmp_path)
    assert cmd[:4] == ["pixi", "run", "--manifest-path", str(tmp_path / "pixi.toml")]
    assert cmd[4:] == ["-e", "gsasii", "kicker", "--no-server", "x.json"]


def test_conftest_example_paths_are_absolute():
    import conftest
    assert conftest.EXAMPLES.is_absolute() and (conftest.EXAMPLES / "example_LaB6" / "input.json").is_file()


def test_no_cwd_relative_example_paths_in_tests():
    """Every test module resolves examples/ from its own location, never from the cwd (review item 17)."""
    tests_dir = Path(__file__).resolve().parent
    offenders = [f"{p.name}:{n}" for p in sorted(tests_dir.glob("*.py"))
                 for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
                 if 'Path("' + 'examples/' in line]  # built so this scanner does not match itself
    assert offenders == []


def test_conftest_reads_text_with_an_explicit_encoding():
    """Review item 28: no platform-default text reads in the shared fixtures."""
    conftest = (Path(__file__).resolve().parent / "conftest.py").read_text(encoding="utf-8")
    offenders = [n for n, line in enumerate(conftest.splitlines(), 1)
                 if ".read_text()" in line or "open(" in line and "encoding" not in line and "os.open" not in line]
    assert offenders == []


def test_output_recipe_mismatches_skips_provenance_and_holds_tolerance():
    """The output-recipe comparison: provenance ignored, numbers within tolerance, everything else exact."""
    ref = {"metadata": {"powderline_provenance": {"created": "a", "parent_run_id": "1"}, "UID": "x"},
           "payload": {"phases": {"P": {"unit_cell": {"a": [4.15692, True]},
                                        "peak_broadening": {"size_broadening": {"isotropic_size": [1.0, True]}}}}}}
    test = json.loads(json.dumps(ref))
    test["metadata"]["powderline_provenance"] = {"created": "b"}
    test["payload"]["phases"]["P"]["unit_cell"]["a"][0] = 4.15692 * (1 + 5e-4)
    test["payload"]["phases"]["P"]["peak_broadening"]["size_broadening"]["isotropic_size"][0] = 1.005  # loose class
    assert subprocess_utils.output_recipe_mismatches(test, ref) == []
    test["payload"]["phases"]["P"]["unit_cell"]["a"][0] = 4.15692 * (1 + 5e-3)
    test["payload"]["phases"]["P"]["unit_cell"]["a"][1] = False
    test["metadata"]["UID"] = "y"
    found = subprocess_utils.output_recipe_mismatches(test, ref)
    assert [m.split(":")[0] for m in found] == ["metadata.UID", "payload.phases.P.unit_cell.a.0",
                                                 "payload.phases.P.unit_cell.a.1"]


def test_dispositions_match_is_exact_on_labels_and_tolerant_on_values():
    import pandas as pd
    ref = pd.DataFrame({"path": ["payload.a", "payload.phases.P.peak_broadening.s"], "value": [1.0, 2.0],
                        "esd": [0.1, float("nan")], "disposition": ["varied", "varied"], "at_limit": [False, False]})
    test = ref.copy()
    test.loc[1, "value"] = 2.01  # 0.5 %: inside the size/strain class's loose tolerance
    assert subprocess_utils.dispositions_match(test, ref)
    test.loc[0, "value"] = 1.01
    assert not subprocess_utils.dispositions_match(test, ref)
    test = ref.copy()
    test.loc[0, "disposition"] = "held_by_user"
    assert not subprocess_utils.dispositions_match(test, ref)
