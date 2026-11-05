"""Tests for powderline.gateways.topas.runner (tc.exe discovery + injected run)."""

from __future__ import annotations

from pathlib import Path

import pytest

from powderline.gateways.topas import runner

pytestmark = pytest.mark.topas_gen


def _make_tc(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    tc = directory / "tc.exe"
    tc.write_text("")  # dummy executable
    return tc


# --- discovery --------------------------------------------------------------


def test_discover_explicit_dir(tmp_path):
    tc = _make_tc(tmp_path / "TOPAS8")
    assert runner.discover_tc_exe(topas_dir=tmp_path / "TOPAS8") == tc


def test_discover_returns_none_when_absent(tmp_path, monkeypatch):
    # nothing declared -> None (P-35: no default directories are ever probed)
    monkeypatch.setattr(runner, "_read_topas_config", lambda: {})
    assert runner.discover_tc_exe() is None
    assert runner.discover_tc_exe(topas_dir=tmp_path / "nope") is None


def test_discover_from_config(tmp_path, monkeypatch):
    tc = _make_tc(tmp_path / "topas_home")
    monkeypatch.setattr(runner, "_read_topas_config", lambda: {"dir": str(tmp_path / "topas_home")})
    assert runner.discover_tc_exe() == tc


def test_explicit_dir_beats_config(tmp_path, monkeypatch):
    cfg_tc = _make_tc(tmp_path / "cfg")
    arg_tc = _make_tc(tmp_path / "arg")
    monkeypatch.setattr(runner, "_read_topas_config", lambda: {"dir": str(tmp_path / "cfg")})
    assert runner.discover_tc_exe(topas_dir=tmp_path / "arg") == arg_tc
    assert cfg_tc.exists()  # (sanity: config path is real but not chosen)


def test_discovery_consults_only_declared_locations(tmp_path, monkeypatch):
    """P-35: tc.exe runs only from --topas-dir / config topas.dir. No default-directory sweep, no
    C:/TOPAS<version> guess: a declared version alone finds nothing, so a recipe for TOPAS 6 can never
    silently run on a TOPAS 7 that happens to be installed."""
    assert not hasattr(runner, "_DEFAULT_TOPAS_DIRS")
    monkeypatch.setattr(runner, "_read_topas_config", lambda: {"version": "6"})
    assert runner.discover_tc_exe(topas_version="6") is None
    assert runner._candidate_dirs(None, {"version": "6"}) == []
    assert runner._candidate_dirs(None, {"dir": str(tmp_path)}) == [tmp_path]
    assert runner._candidate_dirs(tmp_path / "arg", {"dir": str(tmp_path)}) == [tmp_path / "arg"]


def test_read_topas_config_malformed_raises(tmp_path, monkeypatch):
    cfg = tmp_path / ".powderline_config.yaml"
    cfg.write_text("topas: {version: 6, dir: [oops\n", encoding="utf-8")
    monkeypatch.setattr(runner, "_CONFIG_PATHS", [str(cfg)])
    with pytest.raises(ValueError, match=r"powderline_config\.yaml.*not valid YAML"):
        runner._read_topas_config()


def test_read_topas_config_absent_is_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "_CONFIG_PATHS", [str(tmp_path / "nope.yaml")])
    assert runner._read_topas_config() == {}


def test_read_topas_config_utf8_dir(tmp_path, monkeypatch):
    cfg = tmp_path / ".powderline_config.yaml"
    cfg.write_text("topas:\n  version: '6'\n  dir: 'C:/Progrämme/TOPAS6'\n", encoding="utf-8")
    monkeypatch.setattr(runner, "_CONFIG_PATHS", [str(cfg)])
    assert runner._read_topas_config() == {"version": "6", "dir": "C:/Progrämme/TOPAS6"}
