"""Unit tests for powderline.exceptions (hierarchy, messages, warning shape).

Pure tests: no engine, no network.
"""
import pytest

from pydantic import BaseModel, ValidationError

from powderline.exceptions import (

    EngineExecutionError,
    EngineNotAvailableError,
    EngineVersionError,
    GatewayNotInstalledError,
    PowderLineError,
    StructuredWarning,
    SymmetryError,
)

pytestmark = pytest.mark.core


@pytest.mark.parametrize("cls", [
    GatewayNotInstalledError, EngineNotAvailableError,
    EngineVersionError, EngineExecutionError, SymmetryError,
])
def test_all_derive_from_powderline_error(cls):
    assert issubclass(cls, PowderLineError)


def test_engine_not_available_is_an_import_error():
    # A52: callers that caught the underlying ImportError keep working.
    err = EngineNotAvailableError(gateway="easydiffraction", dependency="easydiffraction",
                                  env="easydiffraction", install_command="pixi install -e easydiffraction")
    with pytest.raises(ImportError):
        raise err


def test_engine_not_available_message_names_gateway_env_and_command():
    err = EngineNotAvailableError(gateway="easydiffraction", dependency="easydiffraction",
                                  env="easydiffraction", install_command="pixi install -e easydiffraction")
    msg = str(err)
    assert "'easydiffraction' gateway" in msg
    assert "'easydiffraction' pixi environment" in msg
    assert "pixi install -e easydiffraction" in msg
    assert "pixi run -e easydiffraction" in msg
    assert (err.gateway, err.env) == ("easydiffraction", "easydiffraction")


def test_engine_version_error_message():
    err = EngineVersionError(gateway="gsasii", engine="GSAS-II", installed="5.8.0",
                             supported="==5.7.9")
    assert str(err) == ("the 'gsasii' gateway supports GSAS-II ==5.7.9, but 5.8.0 is "
                        "installed; install a supported version")
    assert (err.installed, err.supported) == ("5.8.0", "==5.7.9")


def test_gateway_not_installed_keeps_name():
    err = GatewayNotInstalledError("no gateway 'foo'", gateway="foo")
    assert err.gateway == "foo"
    assert str(err) == "no gateway 'foo'"


def test_symmetry_error_raised_in_a_validator_is_reported_by_pydantic():
    # A61/A70: a SymmetryError raised inside a validator joins pydantic's
    # aggregated ValidationError with its field location.
    from pydantic import field_validator

    from powderline.exceptions import SymmetryError

    class _S(BaseModel):
        sg: str
        n: int

        @field_validator("sg")
        @classmethod
        def _sg(cls, v):
            raise SymmetryError(f"bad group {v!r}")

    with pytest.raises(ValidationError) as info:
        _S.model_validate({"sg": "Q", "n": "x"})
    locs = {e["loc"]: e["msg"] for e in info.value.errors()}
    assert set(locs) == {("sg",), ("n",)}
    assert "bad group 'Q'" in locs[("sg",)]


def test_structured_warning_shape():
    assert StructuredWarning.__required_keys__ == {"code", "message", "field_path"}
    assert StructuredWarning.__optional_keys__ == {"level"}  # P-34: absent means "warning"
    w: StructuredWarning = {"code": "W001", "message": "m", "field_path": None}
    assert w["field_path"] is None and w.get("level", "warning") == "warning"


def test_engine_execution_error_defaults():
    e = EngineExecutionError("m")
    assert e.reason == "engine_crashed" and e.result == {}
    from powderline.exceptions import ExecutionBackendError, PowderLineError
    b = ExecutionBackendError("n")
    assert b.reason == "backend_error" and b.result == {} and isinstance(b, PowderLineError)
    assert not isinstance(b, ImportError)
