"""Tests for the gateway registry: entry-point discovery, explicit registration, version checks.

Key invariants (A17/A7/A54):
- Discovery is lazy: available() lists entry points without loading them; get() loads on first use.
- register_gateway() takes precedence over an entry point of the same name.
- A factory returning a non-Gateway raises TypeError.
- check_engine_version enforces PEP 440 specs; allow_unsupported=True bypasses.
- Entry points are only present after re-installing the editable package (pixi reinstall powderline).
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

from packaging.specifiers import SpecifierSet

from powderline import registry
from powderline.exceptions import EngineVersionError, GatewayNotInstalledError
from subprocess_utils import run_subprocess_utf8

pytestmark = pytest.mark.core

REPO = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _reset_registry_caches(monkeypatch):
    """Snapshot and restore the module-level registry caches before/after each test."""
    original_explicit = registry._explicit.copy()
    original_instances = registry._instances.copy()
    original_entry_points = registry._entry_points

    yield

    # Restore the original state
    registry._explicit.clear()
    registry._explicit.update(original_explicit)
    registry._instances.clear()
    registry._instances.update(original_instances)
    # Reset entry points to force re-discovery
    monkeypatch.setattr(registry, "_entry_points", original_entry_points)


def _fake_gateway(name="fake"):
    """Build a minimal Gateway for testing."""
    return registry.Gateway(
        name=name,
        capabilities=lambda: {"name": name, "workflows": [], "engine_version_spec": ">=1"},
        validate=lambda recipe, **opts: recipe,
        run=lambda recipe, output_dir, **opts: {},
    )


def _fake_entry_point(name, gateway):
    """Build a fake entry point that tracks load() calls."""
    ep = Mock()
    ep.name = name
    ep.load_called = False
    original_gateway = gateway

    def load():
        ep.load_called = True
        return lambda: original_gateway

    ep.load = load
    return ep


# --- register_gateway escape hatch ---


def test_register_gateway_makes_get_return_it():
    factory = lambda: _fake_gateway("test_gw")
    registry.register_gateway("test_gw", factory)
    assert registry.get("test_gw").name == "test_gw"


def test_register_gateway_is_cached(monkeypatch):
    call_count = 0

    def factory():
        nonlocal call_count
        call_count += 1
        return _fake_gateway("cached")

    registry.register_gateway("cached", factory)
    registry.get("cached")
    registry.get("cached")
    assert call_count == 1, "factory should be called exactly once (cached)"


def test_explicit_registration_takes_precedence_over_entry_point(monkeypatch):
    """An explicit registration shadows an entry point of the same name."""
    gw_from_ep = _fake_gateway("from_ep")
    gw_explicit = _fake_gateway("from_explicit")
    ep = _fake_entry_point("shadowed", gw_from_ep)
    monkeypatch.setattr(registry, "_entry_points", {"shadowed": ep})

    registry.register_gateway("shadowed", lambda: gw_explicit)
    assert registry.get("shadowed").name == "from_explicit"
    assert not ep.load_called, "entry point should not be loaded when shadowed"


def test_unregister_gateway_removes_explicit():
    registry.register_gateway("to_remove", lambda: _fake_gateway("to_remove"))
    registry.get("to_remove")  # cache it
    registry.unregister_gateway("to_remove")
    with pytest.raises(GatewayNotInstalledError, match="to_remove"):
        registry.get("to_remove")


def test_available_lists_explicit_and_entry_point_names_sorted(monkeypatch):
    registry.register_gateway("explicit_a", lambda: _fake_gateway("explicit_a"))
    registry.register_gateway("explicit_z", lambda: _fake_gateway("explicit_z"))
    ep1 = _fake_entry_point("ep_b", _fake_gateway("ep_b"))
    ep2 = _fake_entry_point("ep_y", _fake_gateway("ep_y"))
    monkeypatch.setattr(registry, "_entry_points", {"ep_b": ep1, "ep_y": ep2})

    names = registry.available()
    assert names == ["ep_b", "ep_y", "explicit_a", "explicit_z"]
    assert not ep1.load_called, "available() should not load entry points"
    assert not ep2.load_called, "available() should not load entry points"


# --- Lazy loading ---


def test_available_does_not_load_entry_points(monkeypatch):
    ep = _fake_entry_point("lazy_test", _fake_gateway("lazy_test"))
    monkeypatch.setattr(registry, "_entry_points", {"lazy_test": ep})
    registry.available()
    assert not ep.load_called, "available() should not call ep.load()"


def test_get_loads_entry_point_exactly_once(monkeypatch):
    load_count = 0
    gw = _fake_gateway("lazy_gw")

    def load():
        nonlocal load_count
        load_count += 1
        return lambda: gw

    ep = Mock()
    ep.name = "lazy_gw"
    ep.load = load
    monkeypatch.setattr(registry, "_entry_points", {"lazy_gw": ep})

    registry.get("lazy_gw")
    registry.get("lazy_gw")
    assert load_count == 1, "entry point load() should be called exactly once"


# --- get() of unregistered name ---


def test_get_unregistered_name_raises_gateway_not_installed_error(monkeypatch):
    monkeypatch.setattr(registry, "_entry_points", {"known": Mock()})
    with pytest.raises(GatewayNotInstalledError) as exc_info:
        registry.get("unknown")
    assert exc_info.value.gateway == "unknown"
    msg = str(exc_info.value)
    assert "unknown" in msg
    assert "pip install" in msg or "register_gateway" in msg


def test_zero_entry_points_message_mentions_stale_metadata(monkeypatch):
    """When no entry points are found at all, message says re-install."""
    monkeypatch.setattr(registry, "_entry_points", {})
    with pytest.raises(GatewayNotInstalledError) as exc_info:
        registry.get("anything")
    msg = str(exc_info.value)
    assert "no 'powderline.gateways' entry points were found" in msg
    assert "pixi reinstall powderline" in msg


# --- factory returning non-Gateway ---


def test_factory_returning_non_gateway_raises_type_error(monkeypatch):
    registry.register_gateway("bad", lambda: "not a Gateway")
    with pytest.raises(TypeError, match="expected powderline.registry.Gateway"):
        registry.get("bad")


# --- check_engine_version ---


def test_check_engine_version_in_range_passes():
    registry.check_engine_version(
        gateway="test", engine="TestEngine", installed="1.2.3", spec=">=1,<2"
    )


def test_check_engine_version_out_of_range_raises():
    with pytest.raises(EngineVersionError) as exc_info:
        registry.check_engine_version(
            gateway="test", engine="TestEngine", installed="0.9.0", spec=">=1,<2"
        )
    assert exc_info.value.installed == "0.9.0"
    assert exc_info.value.supported == ">=1,<2"


def test_check_engine_version_invalid_version_raises():
    with pytest.raises(EngineVersionError):
        registry.check_engine_version(
            gateway="test", engine="TestEngine", installed="not-a-version", spec=">=1,<2"
        )


def test_check_engine_version_allow_unsupported_bypasses():
    registry.check_engine_version(
        gateway="test",
        engine="TestEngine",
        installed="0.9.0",
        spec=">=1,<2",
        allow_unsupported=True,
    )


# The two '>=7,<8' strings below are arbitrary specifier inputs exercising the
# bare-integer version form, NOT the TOPAS gateway's spec: that is
# gateways.topas.gateway.ENGINE_VERSION_SPEC ("==6", A143, P-24).
def test_check_engine_version_topas_bare_int():
    """TOPAS-style bare int '7' against '>=7,<8' passes."""
    registry.check_engine_version(
        gateway="topas", engine="TOPAS", installed="7", spec=">=7,<8"
    )


def test_check_engine_version_topas_bare_int_out_of_range():
    """TOPAS-style bare int '6' against '>=7,<8' fails."""
    with pytest.raises(EngineVersionError):
        registry.check_engine_version(
            gateway="topas", engine="TOPAS", installed="6", spec=">=7,<8"
        )


# --- REAL entry points (requires re-install) ---


def test_real_entry_points_available(monkeypatch):
    """With caches reset, available() includes the three built-in gateways."""
    # Reset to force discovery
    monkeypatch.setattr(registry, "_entry_points", None)
    monkeypatch.setattr(registry, "_instances", {})
    names = registry.available()
    # Expected to fail until `pixi reinstall powderline` is run
    assert {"gsasii", "topas", "easydiffraction"} <= set(names)


def test_real_entry_points_get_returns_gateway(monkeypatch):
    """With caches reset, get(name) returns a Gateway for each built-in."""
    monkeypatch.setattr(registry, "_entry_points", None)
    monkeypatch.setattr(registry, "_instances", {})
    for name in ["gsasii", "topas", "easydiffraction"]:
        gw = registry.get(name)
        assert gw.name == name
        assert isinstance(gw, registry.Gateway)


# --- PYTHONPATH=src mode ---


def test_pythonpath_src_mode_sees_entry_points():
    """Subprocess with PYTHONPATH=src sees the three built-in entry points."""
    import os

    script = """
import sys
import os
from importlib.metadata import entry_points

sys.path.insert(0, os.environ.get("PYTHONPATH", ""))
eps = entry_points(group="powderline.gateways")
names = sorted(ep.name for ep in eps)
print(",".join(names))
"""
    env = {"PYTHONPATH": str(REPO / "src")}
    proc = run_subprocess_utf8(
        [sys.executable, "-c", script], capture_output=True, text=True, env={**os.environ, **env}
    )
    assert proc.returncode == 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    names = proc.stdout.strip().split(",")
    # Expected to fail until re-install
    assert set(names) >= {"easydiffraction", "gsasii", "topas"}
