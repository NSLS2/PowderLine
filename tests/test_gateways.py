"""Tests for the three built-in gateways: schema layer, version checking, import-block guarantee.

Coverage:
- ENGINE_VERSION_SPEC consistency across all gateways
- validate() for each gateway (LaB6 recipe)
- Version-check behavior (gsasii, topas, easydiffraction)
- Dispatcher routing (registry.get → gateway.run)
- Import-block guarantee: capabilities/validate work with engines unavailable
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

from packaging.specifiers import SpecifierSet
from pydantic import ValidationError

import powderline
from powderline import registry
from powderline.exceptions import EngineNotAvailableError, EngineVersionError
from powderline.gateways.gsasii import gateway as gsasii_gateway
from powderline.gateways.gsasii import schema as gsasii_schema
from powderline.gateways.topas import gateway as topas_gateway
from powderline.gateways.topas import schema as topas_schema
from powderline.gateways.easydiffraction import gateway as easydiff_gateway
from powderline.gateways.easydiffraction import schema as easydiff_schema
from powderline.schema_core import CoreRecipe
from subprocess_utils import run_subprocess_utf8

pytestmark = pytest.mark.core

REPO = Path(__file__).resolve().parent.parent
EXAMPLES = REPO / "examples"
LAB6 = EXAMPLES / "example_LaB6" / "input.json"  # gsasii.rietveld
TOPAS_LAB6 = REPO / "tests" / "data" / "topas" / "native" / "lab6_rietveld.json"  # topas.rietveld
EASY_LAB6 = REPO / "tests" / "data" / "easydiffraction" / "native" / "lab6_crysfml_tch.json"  # easydiffraction.rietveld


def _load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _lab6_recipe():
    """Load the LaB6 example recipe (gsasii.rietveld) as a dict."""
    return _load(LAB6)


#: Each gateway with its native LaB6 recipe and the model it validates to.
NATIVE_CASES = [
    pytest.param(gsasii_gateway, LAB6, gsasii_schema.GsasiiRietveldRecipe, id="gsasii"),
    pytest.param(topas_gateway, TOPAS_LAB6, topas_schema.TopasRietveldRecipe, id="topas"),
    pytest.param(easydiff_gateway, EASY_LAB6, easydiff_schema.EasydiffractionRietveldRecipe, id="easydiffraction"),
]


@pytest.fixture
def isolated_registry():
    """Snapshot the registry caches; restore them even if the test fails."""
    saved = (registry._explicit.copy(), registry._instances.copy(), registry._entry_points)
    yield registry
    registry._explicit.clear()
    registry._explicit.update(saved[0])
    registry._instances.clear()
    registry._instances.update(saved[1])
    registry._entry_points = saved[2]


# --- ENGINE_VERSION_SPEC consistency ---


@pytest.mark.parametrize(
    "gateway_module,expected_spec",
    [
        (gsasii_gateway, "==5.7.9"),
        (topas_gateway, "==6"),  # the native declaration (A143, A144); the 0.26.0 path's >=7,<8 went with it (A146)
        (easydiff_gateway, "==0.21.1"),
    ],
)
def test_engine_version_spec_parses_and_matches_capabilities(gateway_module, expected_spec):
    """Each gateway's ENGINE_VERSION_SPEC parses and equals capabilities()['engine_version_spec']."""
    spec_str = gateway_module.ENGINE_VERSION_SPEC
    SpecifierSet(spec_str)  # must parse
    assert spec_str == expected_spec
    caps = gateway_module.capabilities()
    assert caps["engine_version_spec"] == expected_spec


@pytest.mark.parametrize(
    "gateway_module",
    [gsasii_gateway, topas_gateway, easydiff_gateway],
)
def test_get_gateway_returns_gateway_with_correct_name(gateway_module):
    """Each gateway module's get_gateway() returns a Gateway whose name == NAME."""
    gw = gateway_module.get_gateway()
    assert gw.name == gateway_module.NAME
    assert isinstance(gw, registry.Gateway)


# --- validate() ---


@pytest.mark.parametrize("gateway_module,path,model_type", NATIVE_CASES)
def test_validate_lab6_recipe_dict_returns_the_native_model(gateway_module, path, model_type):
    """Validating each engine's LaB6 recipe dict returns that engine's model (a CoreRecipe)."""
    result = gateway_module.validate(_load(path))
    assert isinstance(result, model_type)
    assert isinstance(result, CoreRecipe)


@pytest.mark.parametrize("gateway_module,path,model_type", NATIVE_CASES)
def test_validate_recipe_model_is_idempotent(gateway_module, path, model_type):
    """Passing a validated model to validate() returns it unchanged (A50)."""
    model = gateway_module.validate(_load(path))
    assert gateway_module.validate(model) is model


@pytest.mark.parametrize(
    "gateway_module,invalid_recipe",
    [
        (gsasii_gateway, {"schema_name": "gsasii.rietveld"}),
        (topas_gateway, {"schema_name": "topas.rietveld"}),
        (easydiff_gateway, {"schema_name": "easydiffraction.rietveld"}),
        (gsasii_gateway, {}),
        (topas_gateway, {}),
        (easydiff_gateway, {}),
    ],
)
def test_validate_invalid_recipe_raises(gateway_module, invalid_recipe):
    """An invalid recipe raises pydantic's ValidationError."""
    with pytest.raises(ValidationError):
        gateway_module.validate(invalid_recipe)


@pytest.mark.parametrize("gateway_module", [gsasii_gateway, topas_gateway, easydiff_gateway],
                         ids=["gsasii", "topas", "easydiffraction"])
def test_validate_foreign_schema_name_is_reported_at_schema_name(gateway_module):
    """A gateway given another engine's (or an unknown) schema_name reports it at schema_name (A133)."""
    with pytest.raises(ValidationError) as exc:
        gateway_module.validate({"schema_name": "other.workflow", "payload": {}})
    assert [tuple(e["loc"]) for e in exc.value.errors()] == [("schema_name",)]


# --- pixi pins mirror the gateway specifiers (A41; re/08) ---


def _pixi_manifest() -> dict:
    try:
        import tomllib
    except ModuleNotFoundError:  # Python 3.10
        import tomli as tomllib
    return tomllib.loads((REPO / "pixi.toml").read_text(encoding="utf-8"))


def test_pixi_easydiffraction_pin_is_within_gateway_spec():
    """pixi.toml pins easydiffraction to one version, and that version satisfies ENGINE_VERSION_SPEC.

    The gateway specifier is the contract; the manifest must not drift from it (A41).
    """
    pin = _pixi_manifest()["feature"]["easydiffraction"]["pypi-dependencies"]["easydiffraction"]
    pin_set = SpecifierSet(pin)
    pinned = [spec for spec in pin_set if spec.operator == "=="]
    assert len(pinned) == 1, f"easydiffraction must be pinned exactly in pixi.toml, got {pin!r}"
    assert pinned[0].version in SpecifierSet(easydiff_gateway.ENGINE_VERSION_SPEC)


def test_pixi_env_names_match_gateway_constants():
    """The env a gateway names in EngineNotAvailableError exists in pixi.toml, and GSAS-II lives only there."""
    manifest = _pixi_manifest()
    envs = manifest["environments"]
    for gateway in (gsasii_gateway, easydiff_gateway):
        assert gateway.ENV in envs, f"{gateway.NAME}: pixi env {gateway.ENV!r} not in pixi.toml"
        assert gateway.INSTALL_COMMAND == f"pixi install --frozen -e {gateway.ENV}"
    assert "GSAS-II" not in manifest["dependencies"], "the default env must stay engine-free (A31)"
    assert "GSAS-II" in manifest["feature"][gsasii_gateway.ENV]["dependencies"]


# The runtime counterpart (GSASII.__version__ in ENGINE_VERSION_SPEC) is
# test_gateways_installed_engines.test_gsasii_installed_engine_version_satisfies_spec,
# run in the gsasii env.

# --- gsasii version checking ---


def test_gsasii_version_check_raises_when_version_out_of_range(tmp_path, monkeypatch):
    """When the installed version is out of range, run() raises EngineVersionError."""
    monkeypatch.setattr(gsasii_gateway, "installed_engine_version", lambda: "5.8.0")
    # Mock the in-process executor so nothing actually runs
    fake_run = Mock()
    monkeypatch.setattr(gsasii_gateway, "run_refinement", fake_run)

    with pytest.raises(EngineVersionError):
        gsasii_gateway.run(_lab6_recipe(), str(tmp_path), validate_only=False, execution_mode="subprocess")
    assert not fake_run.called, "run_refinement should not be called when version check fails"


def test_gsasii_version_check_bypassed_with_allow_unsupported(tmp_path, monkeypatch):
    """With allow_unsupported_engine_version=True, the version check is bypassed and the run proceeds."""
    monkeypatch.setattr(gsasii_gateway, "installed_engine_version", lambda: "5.8.0")
    fake_run = Mock(return_value={"success": True, "method": "subprocess"})
    monkeypatch.setattr(gsasii_gateway, "run_refinement", fake_run)

    result = gsasii_gateway.run(
        _lab6_recipe(),
        str(tmp_path),
        validate_only=False,
        verbose=True,
        execution_mode="subprocess",
        allow_unsupported_engine_version=True,
    )
    assert fake_run.called
    recipe_arg, output_arg = fake_run.call_args[0]
    assert isinstance(recipe_arg, gsasii_schema.GsasiiRietveldRecipe)  # the gateway validated the dict first
    assert Path(output_arg) == tmp_path
    call_kwargs = fake_run.call_args[1]
    assert call_kwargs["verbose"] is True
    assert call_kwargs["method"] == "subprocess"
    # the gateway's own result normalisation applied
    assert result["status"] == "ok" and "error" not in result  # re/12 envelope
    assert result["refined_parameters"].empty


def test_gsasii_validate_only_skips_version_check(tmp_path, monkeypatch):
    """With validate_only=True, the version check is skipped."""
    called = []

    def failing_version_check():
        called.append(True)
        raise AssertionError("version check should not be called for validate_only=True")

    monkeypatch.setattr(gsasii_gateway, "installed_engine_version", failing_version_check)
    fake_run = Mock(return_value={})
    monkeypatch.setattr(gsasii_gateway, "run_refinement", fake_run)

    result = gsasii_gateway.run(_lab6_recipe(), str(tmp_path), validate_only=True)
    assert not called, "installed_engine_version should not be called for validate_only=True"
    assert not fake_run.called
    assert result["method"] == "validate_only" and result["schema_name"] == "gsasii.rietveld"


# --- topas version checking (the A145 rule itself is tested in test_topas_native) ---


def test_topas_run_forwards_the_recipe_and_options_to_run_native(tmp_path, monkeypatch):
    """gateway.run(topas recipe) validates, then hands the model, topas_dir and topas_version to run_native."""
    from powderline.gateways.topas import native_run

    fake_run = Mock(return_value={})
    monkeypatch.setattr(native_run, "run_native", fake_run)

    topas_gateway.run(_load(TOPAS_LAB6), str(tmp_path), topas_dir="/t", topas_version="6", validate_only=False)
    assert fake_run.called
    (model, output_arg), kwargs = fake_run.call_args
    assert isinstance(model, topas_schema.TopasRietveldRecipe)
    assert Path(output_arg) == tmp_path
    assert kwargs["topas_dir"] == "/t" and kwargs["topas_version"] == "6"
    assert callable(kwargs["engine_version_check"])  # A145, applied by run_native when tc.exe is found


def test_topas_validate_only_skips_version_check(tmp_path, monkeypatch):
    """With validate_only=True no version is needed, even a mismatching declared one."""
    from powderline.gateways.topas import native_run

    fake_run = Mock()
    monkeypatch.setattr(native_run, "run_native", fake_run)

    result = topas_gateway.run(_load(TOPAS_LAB6), str(tmp_path), topas_version=7, validate_only=True)
    assert result["method"] == "validate_only"
    assert not fake_run.called


# --- easydiffraction version checking ---


def test_easydiff_version_out_of_range_raises(tmp_path, monkeypatch):
    """When installed_engine_version() returns '0.20.1' (the previous pin), run() raises EngineVersionError."""
    monkeypatch.setattr(easydiff_gateway, "installed_engine_version", lambda: "0.20.1")
    from powderline.gateways.easydiffraction import native_run

    fake_run = Mock()
    monkeypatch.setattr(native_run, "run_native", fake_run)

    with pytest.raises(EngineVersionError):
        easydiff_gateway.run(_load(EASY_LAB6), str(tmp_path), validate_only=False)
    assert not fake_run.called


def test_easydiff_version_in_range_calls_engine(tmp_path, monkeypatch):
    """When installed_engine_version() returns '0.21.1', run() calls run_native with the validated model."""
    monkeypatch.setattr(easydiff_gateway, "installed_engine_version", lambda: "0.21.1")
    from powderline.gateways.easydiffraction import native_run

    fake_run = Mock(return_value={})
    monkeypatch.setattr(native_run, "run_native", fake_run)

    easydiff_gateway.run(_load(EASY_LAB6), str(tmp_path), validate_only=False)
    assert fake_run.called
    model, output_arg = fake_run.call_args[0]
    assert isinstance(model, easydiff_schema.EasydiffractionRietveldRecipe)
    assert Path(output_arg) == tmp_path


def _easydiffraction_distribution_installed() -> bool:
    """What the gateway itself checks (installed_engine_version): the distribution, not an import."""
    import importlib.metadata
    try:
        importlib.metadata.version("easydiffraction")
    except importlib.metadata.PackageNotFoundError:
        return False
    return True


easydiffraction_absent_only = pytest.mark.skipif(
    _easydiffraction_distribution_installed(),
    reason="easydiffraction is installed in this env; the not-installed path is exercised in the default env",
)


@easydiffraction_absent_only
def test_easydiff_not_installed_raises_engine_not_available_error(tmp_path):
    """When easydiffraction is not installed, run() raises EngineNotAvailableError."""
    with pytest.raises(EngineNotAvailableError) as exc_info:
        easydiff_gateway.run(_load(EASY_LAB6), str(tmp_path), validate_only=False)
    assert isinstance(exc_info.value, ImportError)
    assert "pixi install --frozen -e easydiffraction" in str(exc_info.value)


@easydiffraction_absent_only
def test_easydiff_not_installed_validate_only_does_not_raise(tmp_path):
    """When easydiffraction is not installed, validate_only=True returns the summary without the engine."""
    result = easydiff_gateway.run(_load(EASY_LAB6), str(tmp_path), validate_only=True)
    assert result["method"] == "validate_only" and result["schema_name"] == "easydiffraction.rietveld"


# --- Dispatcher routing (powderline.run dispatches on schema_name, P-06) ---


def _recording_gateways(names, workflows=()):
    """Register fake gateways under ``names`` that record run() kwargs; return the record."""
    calls = {}

    def make_fake_gateway(name):
        def fake_run(recipe, output_dir, **kwargs):
            calls[name] = kwargs
            return {}

        return registry.Gateway(
            name=name,
            capabilities=lambda: {"name": name, "workflows": list(workflows), "engine_version_spec": ">=1"},
            validate=lambda recipe, **opts: recipe,
            run=fake_run,
        )

    for name in names:
        registry.register_gateway(name, lambda n=name: make_fake_gateway(n))
    return calls


def test_dispatcher_routes_by_schema_name_through_registry_get(tmp_path, isolated_registry):
    """powderline.run(recipe) routes to registry.get(<engine of schema_name>).run(...) with the options unchanged."""
    calls = _recording_gateways(["gsasii", "topas", "easydiffraction"])

    powderline.run({"schema_name": "gsasii.rietveld"}, str(tmp_path), verbose=True, validate_only=False,
                   execution_mode="subprocess")
    assert calls == {"gsasii": {"verbose": True, "validate_only": False, "execution_mode": "subprocess"}}

    calls.clear()
    powderline.run({"schema_name": "topas.spf"}, str(tmp_path), verbose=False, validate_only=True,
                   topas_dir="/fake", topas_version=7)
    assert calls == {"topas": {"verbose": False, "validate_only": True, "topas_dir": "/fake", "topas_version": 7}}

    calls.clear()
    powderline.run({"schema_name": "easydiffraction.rietveld"}, str(tmp_path), verbose=True)
    assert calls == {"easydiffraction": {"verbose": True, "validate_only": False}}


def test_run_has_no_engine_keyword(tmp_path):
    """The engine is named by schema_name alone (P-06): run(engine=...) is an option no gateway takes (A59)."""
    with pytest.raises(TypeError, match="engine"):
        powderline.run(_lab6_recipe(), str(tmp_path), validate_only=True, engine="gsasii")


def test_run_schema_name_without_engine_prefix_is_a_validation_error(tmp_path, isolated_registry):
    """A schema_name that is not <engine>.<workflow> is reported at schema_name before any gateway is asked (A133)."""
    calls = _recording_gateways(["gsasii"])
    with pytest.raises(ValidationError, match="does not name an engine"):
        powderline.run({"schema_name": "Rietveld"}, str(tmp_path))
    assert calls == {}


def test_dispatcher_refuses_allow_unsupported_engine_version(tmp_path, isolated_registry):
    """The gateways' test-only version-check bypass is not a public run() option (A53)."""
    calls = _recording_gateways(["gsasii"])
    with pytest.raises(TypeError, match="allow_unsupported_engine_version"):
        powderline.run({"schema_name": "gsasii.rietveld"}, str(tmp_path), allow_unsupported_engine_version=True)
    assert calls == {}


def test_dispatcher_unknown_option_is_the_gateways_type_error(tmp_path):
    """An option the gateway does not take is a TypeError naming it (A59), from the gateway's signature."""
    with pytest.raises(TypeError, match="topas_dir"):
        powderline.run(_lab6_recipe(), str(tmp_path), validate_only=True, topas_dir="/nowhere")


# --- Import-block guarantee ---


def test_import_block_schema_layer_and_validate():
    """Schema-layer imports (registry, gateways, capabilities, validate) work with engines blocked."""
    recipe_path = str(LAB6)
    easydiff_recipe_path = str(EASY_LAB6)
    topas_native_path = str(TOPAS_LAB6)
    script = f"""
import sys, importlib.abc, json
from pathlib import Path

# Block GSASII and easydiffraction imports
class _Block(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path, target=None):
        if name in ("GSASII", "easydiffraction") or name.startswith(("GSASII.", "easydiffraction.")):
            raise ImportError(f"{{name}} blocked for import-block test")
        return None

sys.meta_path.insert(0, _Block())

# Import the engine-free core + schema-layer modules
import powderline
import powderline.registry
import powderline.exceptions
import powderline.fitstats
import powderline.reports
import powderline.symmetry
import powderline.schema_core
import powderline.compat
import powderline.gateways.gsasii
import powderline.gateways.gsasii.gateway
import powderline.gateways.gsasii.schema
import powderline.gateways.topas.gateway
import powderline.gateways.topas.schema
import powderline.gateways.topas.native_writer
import powderline.gateways.topas.native_run
import powderline.gateways.easydiffraction.gateway
from powderline import registry

# The core phase block and its symmetry rules run engine-free (re/03b)
from powderline.schema_core import Phase, RefinableParameter
from powderline.symmetry import canonical_space_group, cell_tie_groups, coupling_groups
canonical_space_group("F d -3 m:2")
assert [g.members for g in cell_tie_groups("R -3 m:R").groups] == [("a", "b", "c"), ("alpha", "beta", "gamma")]
assert coupling_groups("P -4 21 m", (0.1, 0.6, 0.3)).xyz.groups[0].relations_text() == "y = x + 1/2"
p = lambda v, f=False: [v, f]
phase = Phase[RefinableParameter].model_validate({{
    "space_group": "P 63/m m c",
    "unit_cell": {{"a": p(3.0, True), "b": p(3.0, True), "c": p(5.0), "alpha": p(90.0), "beta": p(90.0),
                  "gamma": p(120.0)}},
    "atoms": {{"C": {{"element": "C", "x": p(1 / 6, True), "y": p(1 / 3, True), "z": p(0.25),
                     "occupancy": p(1.0), "ADP": "Uiso", "Uiso": p(0.01)}}}},
}})
assert phase.site("C").multiplicity == 6 and phase.atoms["C"].x.value == 1 / 6

# The native gsasii schema validates engine-free (re/04, A39)
native = {{
    "schema_name": "gsasii.rietveld", "core_schema_version": "0.1.0", "engine_schema_version": "0.1.0",
    "payload": {{
        "xrd_data": {{"tth": [1.0, 2.0], "Itth": [1.0, 2.0], "Itth_weights": [1.0, 1.0]}},
        "instrument": {{"radiation": {{"type": "PXC", "wavelength": p(0.1665)}},
                        "geometry": {{"bank": 1, "azimuth": 0.0}},
                        "corrections": {{"zero_shift": p(0.0), "polarization": p(0.99),
                                         "axial_divergence": p(0.002)}},
                        "broadening": {{k: p(1.0) for k in "UVWXYZ"}}}},
        "phases": {{"C": {{**phase.model_dump(mode="json"), "scale": p(1.0)}}}},
        "refinement_controls": {{"refinement_cycles": 5}},
    }},
}}
assert type(registry.get("gsasii").validate(native)).__name__ == "GsasiiRietveldRecipe"

# The native topas schema validates and the native writer renders engine-free (re/05)
from powderline.gateways.topas.native_writer import render_native
topas_native = registry.get("topas").validate(json.loads(Path(r'{topas_native_path}').read_text(encoding="utf-8")))
assert type(topas_native).__name__ == "TopasRietveldRecipe"
assert "TCHZ_Peak_Type" in render_native(topas_native, "lab6").inp_text

recipes = {{
    "gsasii": (json.loads(Path(r'{recipe_path}').read_text(encoding="utf-8")), "GsasiiRietveldRecipe"),
    "topas": (json.loads(Path(r'{topas_native_path}').read_text(encoding="utf-8")), "TopasRietveldRecipe"),
    "easydiffraction": (json.loads(Path(r'{easydiff_recipe_path}').read_text(encoding="utf-8")),
                        "EasydiffractionRietveldRecipe"),
}}

# The schema-only consumer path, through the registry (entry points)
for name, (recipe, model_name) in recipes.items():
    gw = registry.get(name)
    caps = gw.capabilities()
    assert caps["name"] == name and "engine_version_spec" in caps
    assert list(caps["workflows"]) == [w for w in caps["workflows"] if w.startswith(name + ".")], caps["workflows"]
    assert type(gw.validate(recipe)).__name__ == model_name

# The support matrix loads every gateway factory (A65)
assert {{row["gateway"] for row in powderline.support_matrix()}} >= set(recipes)

# Assert GSASII and easydiffraction are NOT in sys.modules
assert "GSASII" not in sys.modules, "GSASII was imported despite the block"
assert "easydiffraction" not in sys.modules, "easydiffraction was imported despite the block"

print("OK")
"""
    proc = run_subprocess_utf8([sys.executable, "-c", script], capture_output=True, text=True)
    assert proc.returncode == 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    assert "OK" in proc.stdout


def test_native_package_imports_are_legacy_free():
    """Importing the topas/easydiffraction packages, gateways and native runners loads only the native modules (re/07 B/H).

    The module set each package may load at import time is stated here; a new
    translation layer or an engine import at package import would show up as
    an unexpected name.
    """
    script = """
import sys
import powderline.gateways.topas
import powderline.gateways.topas.gateway
import powderline.gateways.topas.native_run
import powderline.gateways.easydiffraction
import powderline.gateways.easydiffraction.gateway
import powderline.gateways.easydiffraction.native_run
allowed = {
    "powderline.gateways.topas": {"schema", "native_writer", "native_run", "peak_list", "runner", "gateway",
                                  "scattering"},
    "powderline.gateways.easydiffraction": {"schema", "native_builder", "native_run", "space_group_support",
                                            "space_group_table", "gateway", "scattering"},
}
for pkg, names in allowed.items():
    loaded = {m[len(pkg) + 1:] for m in sys.modules if m.startswith(pkg + ".")}
    assert loaded <= names, f"{pkg} loaded unexpected modules: {sorted(loaded - names)}"
for engine in ("GSASII", "easydiffraction", "cryspy"):
    assert engine not in sys.modules, engine
print("OK")
"""
    proc = run_subprocess_utf8([sys.executable, "-c", script], capture_output=True, text=True)
    assert proc.returncode == 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    assert "OK" in proc.stdout


def test_import_block_run_raises_engine_not_available_error(tmp_path):
    """With GSASII blocked, gsasii gateway run() raises EngineNotAvailableError."""
    recipe_path = str(LAB6)
    output_path = str(tmp_path)
    script = f"""
import sys, importlib.abc, json
from pathlib import Path

# Block GSASII import
class _Block(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path, target=None):
        if name == "GSASII" or name.startswith("GSASII."):
            raise ImportError("GSASII blocked for import-block test")
        return None

sys.meta_path.insert(0, _Block())

from powderline.gateways.gsasii import gateway as gsasii_gw
from powderline.exceptions import EngineNotAvailableError

recipe = json.loads(Path(r'{recipe_path}').read_text(encoding="utf-8"))

try:
    gsasii_gw.run(recipe, r'{output_path}', validate_only=False)
    print("ERROR: should have raised EngineNotAvailableError")
    sys.exit(1)
except EngineNotAvailableError as e:
    assert isinstance(e, ImportError)
    print("OK")
"""
    proc = run_subprocess_utf8([sys.executable, "-c", script], capture_output=True, text=True)
    assert proc.returncode == 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    assert "OK" in proc.stdout


# --- Uniform validate() contract (A59) ---


@pytest.mark.parametrize("gateway_module", [gsasii_gateway, topas_gateway, easydiff_gateway],
                         ids=["gsasii", "topas", "easydiffraction"])
def test_validate_signature_is_uniform(gateway_module):
    import inspect

    params = inspect.signature(gateway_module.validate).parameters
    assert list(params) == ["recipe", "verbose"]
    assert params["verbose"].kind is inspect.Parameter.KEYWORD_ONLY
    assert params["verbose"].default is False


@pytest.mark.parametrize("gateway_module,path,model_type", NATIVE_CASES)
def test_validate_accepts_verbose_through_the_registry(gateway_module, path, model_type):
    assert isinstance(registry.get(gateway_module.NAME).validate(_load(path), verbose=True), model_type)



def test_gsasii_frames_build_the_output_recipe_from_the_result_tables(tmp_path):
    """re/20b (KI-04): the GSAS-II gateway maps the result tables onto recipe paths and writes the output recipe
    beside the reports; a GSAS-II name the map does not know is never dropped silently."""
    import json
    import pandas as pd
    from powderline.gateways.gsasii import gateway as g, paths
    root = Path(__file__).resolve().parents[1] / "examples" / "example_LaB6"
    model = gsasii_schema.validate_recipe(json.loads((root / "input.json").read_text(encoding="utf-8-sig")))
    tables = {"refined_parameters": pd.read_csv(root / "output" / "refined_parameters.csv").to_dict("records"),
              "unit_cell_data": {"LaB6": pd.read_csv(root / "output" / "LaB6_unit_cell_report.csv").to_dict("records")},
              "peak_list_data": {}, "fit_profile": None, "spf_peaks": None, "spf_convergence_diagnostics": None,
              "warnings": [], "output_files": [], "run_id": "r-1", "engine_details": {"converged": True},
              "simulation_mode": False}
    res = g._frames(dict(tables), model, tmp_path)
    assert res["output_recipe_valid"] is True and res["output_recipe"]["metadata"]["powderline_provenance"]["parent_run_id"] == "r-1"
    assert res["output_recipe"]["payload"]["instrument"]["broadening"]["U"][0] == pytest.approx(49.11908, rel=1e-6)
    assert (tmp_path / "output_recipe.json").exists() and str(tmp_path / "parameter_dispositions.csv") in res["output_files"]
    bad = dict(tables, refined_parameters=tables["refined_parameters"] + [
        {"parameter_name": ":0:Mystery", "value": 1.0, "esd": None, "phase_name": "", "atom_name": ""}])
    res = g._frames(bad, model, None)
    assert res["output_recipe_valid"] is False and "Mystery" in res["warnings"][-1]["message"]
