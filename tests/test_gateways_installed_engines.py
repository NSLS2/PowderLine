"""The installed engines satisfy their gateway's ENGINE_VERSION_SPEC (A41, A44).

The two runtime counterparts of the manifest-pin tests in ``test_gateways.py``
(re/09 split): each needs its engine importable, so each carries its own suite
marker and skips where the engine is absent. ``pixi run -e gsasii test-gsasii``
and ``pixi run -e easydiffraction test-easydiffraction`` run them.
"""

from __future__ import annotations

import importlib.util

import pytest
from packaging.specifiers import SpecifierSet

from powderline.gateways.easydiffraction import gateway as easydiff_gateway
from powderline.gateways.gsasii import gateway as gsasii_gateway


@pytest.mark.gsasii
@pytest.mark.skipif(
    importlib.util.find_spec("GSASII") is None, reason="GSAS-II not installed"
)
def test_gsasii_installed_engine_version_satisfies_spec():
    """When GSAS-II is installed, installed_engine_version() satisfies ENGINE_VERSION_SPEC."""
    version = gsasii_gateway.installed_engine_version()
    spec = SpecifierSet(gsasii_gateway.ENGINE_VERSION_SPEC)
    assert version in spec, f"installed {version} not in {spec}"


@pytest.mark.easydiffraction
@pytest.mark.skipif(
    importlib.util.find_spec("easydiffraction") is None,
    reason="easydiffraction not installed",
)
def test_easydiff_installed_version_satisfies_spec():
    """When easydiffraction is installed, its version satisfies ENGINE_VERSION_SPEC.

    easydiffraction (0.20.1, 0.21.1) has no ``__version__``; its own runtime version source
    is ``utils.package_version`` (distribution metadata), which must agree.
    """
    from easydiffraction.utils.utils import package_version

    version = easydiff_gateway.installed_engine_version()
    assert version == package_version("easydiffraction")
    spec = SpecifierSet(easydiff_gateway.ENGINE_VERSION_SPEC)
    assert version in spec
