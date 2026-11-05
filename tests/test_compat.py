"""Direct tests for powderline.compat schema-version compatibility functions.

Engine-free, no GSAS-II import (re/03).
"""
import pytest

from powderline import registry
from powderline.compat import (

    check_engine_schema_version,
    declarations,
    required_core_schemas,
    support_matrix,
)
from powderline.schema_core import CORE_SCHEMA_VERSION

pytestmark = pytest.mark.core


# --- declarations -----------------------------------------------------------


def test_declarations_none_when_no_keys():
    caps = {"name": "test", "workflows": ["rietveld"]}
    assert declarations(caps) is None


def test_declarations_dict_when_all_three_present():
    caps = {
        "name": "test",
        "engine_schema_version": "0.1.0",
        "supported_engine_schemas": "==0.1.0",
        "requires_core_schema": "==0.1.0",
    }
    decl = declarations(caps)
    assert decl is not None
    assert decl["engine_schema_version"] == "0.1.0"
    assert decl["supported_engine_schemas"] == "==0.1.0"
    assert decl["requires_core_schema"] == "==0.1.0"


def test_declarations_raises_when_only_some_present():
    caps = {
        "name": "test",
        "engine_schema_version": "0.1.0",
        "supported_engine_schemas": "==0.1.0",
        # missing requires_core_schema
    }
    with pytest.raises(ValueError, match="declares.*but not"):
        declarations(caps)


# --- required_core_schemas --------------------------------------------------


def test_required_core_schemas_plain_string_returned_as_is():
    result = required_core_schemas("==0.1.0", "0.1.0")
    assert result == "==0.1.0"


def test_required_core_schemas_mapping_picks_first_matching_key():
    # 0.2.5 matches both keys; the first one in declaration order wins, even
    # though the second has the higher lower bound.
    requires = {
        ">=0.1.0": "==0.1.0",
        ">=0.2.0": "==0.2.0",
    }
    assert required_core_schemas(requires, "0.2.5") == "==0.1.0"
    assert required_core_schemas(dict(reversed(list(requires.items()))), "0.2.5") == "==0.2.0"


def test_required_core_schemas_mapping_skips_non_matching_keys():
    requires = {
        ">=0.2.0": "==0.2.0",
        ">=0.1.0": "==0.1.0",
    }
    assert required_core_schemas(requires, "0.1.5") == "==0.1.0"


def test_required_core_schemas_rejects_non_mapping():
    with pytest.raises(ValueError, match="specifier string or a mapping"):
        required_core_schemas(["==0.1.0"], "0.1.0")


def test_required_core_schemas_no_matching_key_raises():
    requires = {
        ">=0.2.0": "==0.2.0",
    }
    with pytest.raises(ValueError, match="no entry for engine schema"):
        required_core_schemas(requires, "0.1.0")


# --- check_engine_schema_version --------------------------------------------


def test_check_engine_schema_version_accepted_pair_passes():
    caps = {
        "engine_schema_version": "0.1.0",
        "supported_engine_schemas": "==0.1.0",
        "requires_core_schema": "==0.1.0",
    }
    # Should not raise
    check_engine_schema_version("0.1.0", "0.1.0", gateway="test", capabilities=caps)


def test_check_engine_schema_version_engine_version_outside_supported_raises():
    caps = {
        "engine_schema_version": "0.1.0",
        "supported_engine_schemas": "==0.1.0",
        "requires_core_schema": "==0.1.0",
    }
    with pytest.raises(ValueError) as exc_info:
        check_engine_schema_version("0.1.0", "0.2.0", gateway="test", capabilities=caps)
    err_msg = str(exc_info.value)
    assert "test" in err_msg
    assert "==0.1.0" in err_msg


def test_check_engine_schema_version_core_version_not_in_requires_raises():
    caps = {
        "engine_schema_version": "0.1.0",
        "supported_engine_schemas": "==0.1.0",
        "requires_core_schema": "==0.2.0",  # requires different core version
    }
    with pytest.raises(ValueError, match="requires core"):
        check_engine_schema_version("0.1.0", "0.1.0", gateway="test", capabilities=caps)


def test_check_engine_schema_version_unsupported_core_version_raises():
    caps = {
        "engine_schema_version": "0.1.0",
        "supported_engine_schemas": "==0.1.0",
        "requires_core_schema": "==0.1.0",
    }
    with pytest.raises(ValueError, match="not supported by PowderLine"):
        check_engine_schema_version("0.2.0", "0.1.0", gateway="test", capabilities=caps)


def test_check_engine_schema_version_gateway_with_no_declarations_raises():
    caps = {"name": "test"}  # no declarations
    with pytest.raises(ValueError, match="declares no supported engine schema versions"):
        check_engine_schema_version("0.1.0", "0.1.0", gateway="test", capabilities=caps)


def test_check_engine_schema_version_invalid_specifier_in_supported_engine_schemas_raises():
    caps = {
        "engine_schema_version": "0.1.0",
        "supported_engine_schemas": "not-a-valid-specifier",
        "requires_core_schema": "==0.1.0",
    }
    with pytest.raises(ValueError, match="not a valid PEP 440 specifier"):
        check_engine_schema_version("0.1.0", "0.1.0", gateway="test", capabilities=caps)


def test_check_engine_schema_version_invalid_specifier_in_requires_core_schema_raises():
    caps = {
        "engine_schema_version": "0.1.0",
        "supported_engine_schemas": "==0.1.0",
        "requires_core_schema": "not-a-valid-specifier",
    }
    with pytest.raises(ValueError, match="not a valid PEP 440 specifier"):
        check_engine_schema_version("0.1.0", "0.1.0", gateway="test", capabilities=caps)


# --- support_matrix ---------------------------------------------------------


@pytest.fixture
def fake_gateway_declared():
    """Register a fake gateway with declarations, unregister on teardown."""
    name = "test_declared"

    def factory():
        return registry.Gateway(
            name=name,
            capabilities=lambda: {
                "name": name,
                "workflows": ["rietveld"],
                "engine_schema_version": "0.1.5",
                "supported_engine_schemas": ">=0.1.0",
                "requires_core_schema": "==0.1.0",
            },
            validate=lambda r, *, verbose=False: r,
            run=lambda *a, **k: {},
        )

    registry.register_gateway(name, factory)
    yield name
    registry.unregister_gateway(name)


@pytest.fixture
def fake_gateway_undeclared():
    """Register a fake gateway without declarations, unregister on teardown."""
    name = "test_undeclared"

    def factory():
        return registry.Gateway(
            name=name,
            capabilities=lambda: {
                "name": name,
                "workflows": ["spf"],
            },
            validate=lambda r, *, verbose=False: r,
            run=lambda *a, **k: {},
        )

    registry.register_gateway(name, factory)
    yield name
    registry.unregister_gateway(name)


def test_support_matrix_declared_gateway_has_values(fake_gateway_declared):
    matrix = support_matrix()
    rows = [r for r in matrix if r["gateway"] == fake_gateway_declared]
    assert len(rows) == 1
    row = rows[0]
    assert row["declared"] is True
    assert row["engine_schema_version"] == "0.1.5"
    assert row["supported_engine_schemas"] == ">=0.1.0"
    assert row["requires_core_schema"] == "==0.1.0"


def test_support_matrix_undeclared_gateway_has_none_values(fake_gateway_undeclared):
    matrix = support_matrix()
    rows = [r for r in matrix if r["gateway"] == fake_gateway_undeclared]
    assert len(rows) == 1
    row = rows[0]
    assert row["declared"] is False
    assert row["engine_schema_version"] is None
    assert row["supported_engine_schemas"] is None
    assert row["requires_core_schema"] is None


def test_support_matrix_every_row_has_core_schema_version():
    matrix = support_matrix()
    for row in matrix:
        assert row["core_schema_version"] == CORE_SCHEMA_VERSION


def test_support_matrix_is_powderline_support_matrix():
    # Check that powderline.support_matrix is the same as compat.support_matrix
    import powderline
    assert powderline.support_matrix is support_matrix


def test_support_matrix_has_in_repo_gateways():
    matrix = support_matrix()
    gateway_names = {r["gateway"] for r in matrix}
    # The three in-repo gateways (undeclared until re/04-06)
    assert "gsasii" in gateway_names
    assert "topas" in gateway_names
    assert "easydiffraction" in gateway_names
