"""Tests for powderline.config_loader.ConfigLoader.

Covers the file-discovery paths (no config file → defaults, explicit missing
path → FileNotFoundError, valid YAML from a temporary file, tilde expansion,
empty YAML) and `get_simulation_defaults` (file value, fallback to the
built-ins). Runs in the default pixi environment and requires only pyyaml
(already a PowderLine dependency).
"""

from __future__ import annotations

from pathlib import Path

import pytest

import yaml

from powderline.config_loader import ConfigLoader

pytestmark = pytest.mark.core


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_yaml(path: Path, data: dict) -> Path:
    path.write_text(yaml.dump(data), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# No config file — default values
# ---------------------------------------------------------------------------

class TestConfigLoaderDefaults:
    """When no config file is found, ConfigLoader should return sane defaults."""

    def test_loads_without_error_when_no_config(self, tmp_path, monkeypatch):
        """ConfigLoader() with no file at default locations should not raise."""
        # Ensure neither default location exists in tmp_path
        monkeypatch.chdir(tmp_path)
        loader = ConfigLoader()
        assert isinstance(loader.config, dict)

    def test_defaults_include_simulation_defaults(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        loader = ConfigLoader()
        defaults = loader.get_simulation_defaults()
        assert "wavelength" in defaults["instrument_defaults"]
        assert "broadening" in defaults["instrument_defaults"]
        assert "size_broadening" in defaults["phase_defaults"]
        assert "strain_broadening" in defaults["phase_defaults"]
        assert "background" in defaults


# ---------------------------------------------------------------------------
# Explicit path
# ---------------------------------------------------------------------------

class TestConfigLoaderExplicitPath:

    def test_raises_file_not_found_for_nonexistent_path(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            ConfigLoader(config_path=tmp_path / "does_not_exist.yaml")

    def test_loads_from_explicit_valid_path(self, tmp_path):
        cfg_file = _write_yaml(tmp_path / "config.yaml", {
            "simulation_defaults": {"instrument_defaults": {"wavelength": 1.54056}},
        })
        loader = ConfigLoader(config_path=cfg_file)
        assert loader.get_simulation_defaults()["instrument_defaults"]["wavelength"] == pytest.approx(1.54056)

    def test_expands_tilde_in_path(self, tmp_path, monkeypatch):
        """Config paths with ~ are expanded before existence check."""
        # Point home to tmp_path so ~ resolves there. Path.expanduser() reads
        # HOME on POSIX and USERPROFILE on Windows, so set both to stay portable.
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("USERPROFILE", str(tmp_path))
        cfg_file = _write_yaml(tmp_path / "my_config.yaml", {
            "simulation_defaults": {"instrument_defaults": {"wavelength": 0.7}},
        })
        loader = ConfigLoader(config_path=Path("~") / "my_config.yaml")
        assert loader.get_simulation_defaults()["instrument_defaults"]["wavelength"] == pytest.approx(0.7)


# ---------------------------------------------------------------------------
# Config content
# ---------------------------------------------------------------------------

class TestConfigLoaderContent:

    def test_get_simulation_defaults_returns_file_values(self, tmp_path):
        """get_simulation_defaults returns the raw config block (layout
        normalization/merging happens in SimulationRecipeBuilder)."""
        cfg_file = _write_yaml(tmp_path / "config.yaml", {
            "simulation_defaults": {"instrument_defaults": {"wavelength": 0.1665}},
        })
        loader = ConfigLoader(config_path=cfg_file)
        defaults = loader.get_simulation_defaults()
        assert defaults["instrument_defaults"]["wavelength"] == pytest.approx(0.1665)

    def test_get_simulation_defaults_falls_back_to_defaults_if_absent(self, tmp_path):
        cfg_file = _write_yaml(tmp_path / "config.yaml", {
            "topas": {"version": "6"},  # another section, no simulation_defaults
        })
        loader = ConfigLoader(config_path=cfg_file)
        defaults = loader.get_simulation_defaults()
        # Falls back to the built-in defaults — must contain at least wavelength
        assert "wavelength" in defaults["instrument_defaults"]

    def test_empty_yaml_file_uses_defaults(self, tmp_path):
        cfg_file = tmp_path / "empty.yaml"
        cfg_file.write_text("", encoding="utf-8")
        loader = ConfigLoader(config_path=cfg_file)
        assert isinstance(loader.config, dict)
        assert "wavelength" in loader.get_simulation_defaults()["instrument_defaults"]


def test_malformed_config_raises_naming_the_file(tmp_path):
    cfg = tmp_path / ".powderline_config.yaml"
    cfg.write_text("simulation_defaults:\n  instrument_defaults: [unclosed\n", encoding="utf-8")
    with pytest.raises(ValueError, match=r"powderline_config\.yaml.*not valid YAML"):
        ConfigLoader(config_path=cfg)


def test_list_shaped_config_raises(tmp_path):
    cfg = tmp_path / ".powderline_config.yaml"
    cfg.write_text("- not\n- a mapping\n", encoding="utf-8")
    with pytest.raises(ValueError, match="mapping"):
        ConfigLoader(config_path=cfg)


def test_config_reads_utf8(tmp_path):
    cfg = tmp_path / ".powderline_config.yaml"
    cfg.write_text("simulation_defaults:\n  note: 'λ Å'\n", encoding="utf-8")
    assert ConfigLoader(config_path=cfg).config["simulation_defaults"]["note"] == "λ Å"
