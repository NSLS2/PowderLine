"""The core guard (tests/conftest.py, P-26) does what invariant §4.4 needs.

The activation rule is tested on its own (pure function). The two behaviour
tests run only when the guard is on -- i.e. in a run restricted to the
engine-free suites, such as ``pixi run test`` -- and prove that an engine
import and a real ``tc.exe`` call fail loudly there. In an unrestricted run
(``test-all``) they skip: the engines are legitimately importable.
"""

from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path

import pytest

from conftest import CORE_GUARD_BLOCKED, markexpr_excludes_engines

pytestmark = pytest.mark.core


@pytest.mark.parametrize("markexpr, expected", [
    ("core", True),
    ("topas_gen", True),
    ("core or topas_gen", True),
    ("core and not slow", True),
    ("(core or topas_gen) and not slow", True),
    ("", False),                      # unrestricted
    ("gsasii", False),
    ("easydiffraction", False),
    ("topas_exec", False),
    ("topas_gen or topas_exec", False),  # the test-topas task: tc.exe may run
    ("core or gsasii", False),
    ("not gsasii", False),            # still selects easydiffraction / topas_exec items
    ("not slow", False),
    ("slow", False),
    ("core or (", False),             # unparsable: pytest reports it; the guard stays off
])
def test_guard_activation_rule(markexpr, expected):
    assert markexpr_excludes_engines(markexpr) is expected


def test_guard_blocks_engine_imports(core_guard_active):
    if not core_guard_active:
        pytest.skip("core guard off: unrestricted run")
    for name in CORE_GUARD_BLOCKED:
        with pytest.raises(ModuleNotFoundError, match="core guard"):
            importlib.import_module(name)
    with pytest.raises(ModuleNotFoundError, match="core guard"):
        import GSASII.GSASIIscriptable  # noqa: F401
    with pytest.raises(ModuleNotFoundError, match="core guard"):
        import easydiffraction  # noqa: F401
    assert importlib.util.find_spec("GSASII") is not None  # a skipif(find_spec is None) keeps its meaning


def test_guard_refuses_real_tc_execution(core_guard_active, tmp_path):
    if not core_guard_active:
        pytest.skip("core guard off: unrestricted run")
    from powderline.gateways.topas import native_run

    with pytest.raises(RuntimeError, match="core guard"):
        native_run.run_tc(tmp_path / "tc.exe", tmp_path / "x.inp")
    tc_dir = tmp_path / "TOPAS6"
    tc_dir.mkdir()
    (tc_dir / "tc.exe").write_text("")
    # an injected runner is the tested path and still works
    calls = []
    native_run.run_tc(tc_dir / "tc.exe", tmp_path / "x.inp", runner=lambda cmd, **kw: calls.append(cmd))
    assert calls and Path(calls[0][0]) == tc_dir / "tc.exe"
