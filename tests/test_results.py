"""The run-result envelope and its exception mapping (re/12 spec §3–§5)."""
import os
import pickle
from concurrent.futures import ProcessPoolExecutor

import pytest

import powderline
from powderline import results
from powderline.exceptions import (EngineExecutionError, EngineNotAvailableError, EngineVersionError,
                                   ExecutionBackendError, GatewayNotInstalledError)

pytestmark = pytest.mark.core


def test_reason_sets_are_disjoint_and_match_the_spec():
    assert results.ENGINE_REASONS == {"diverged", "unusable_site", "peak_fit_failed", "engine_crashed",
                                      "output_missing", "output_malformed"}
    assert results.BACKEND_REASONS == {"server_unavailable", "server_disabled",
                                       "communication_failed", "timeout", "backend_error"}
    assert not (results.ENGINE_REASONS & results.BACKEND_REASONS)
    assert results.STATUSES == ("ok", "generated", "failed") and results.ENVELOPE_VERSION == "1"


def test_failure_envelope_shape():
    env = results.failure_envelope("engine", "diverged", "boom", run_id="r1", elapsed=1.5, method="subprocess",
                                   warnings=[{"code": "c", "message": "m", "field_path": None}],
                                   output_files=["/o/dummy.lst"], traceback="tb", engine_details={"engine": "GSAS-II"})
    assert env["status"] == "failed" and env["envelope_version"] == "1"
    assert env["failure"] == {"kind": "engine", "reason": "diverged", "message": "boom", "traceback": "tb",
                              "engine_details": {"engine": "GSAS-II"}}
    assert env["run_id"] == "r1" and env["method"] == "subprocess" and env["output_files"] == ["/o/dummy.lst"]
    assert env["warnings"][0]["code"] == "c"
    assert "success" not in env and "error" not in env


@pytest.mark.parametrize("kind, reason", [("engine", "timeout"), ("backend", "diverged"), ("x", "diverged")])
def test_failure_envelope_rejects_unknown_kind_or_reason(kind, reason):
    with pytest.raises(ValueError):
        results.failure_envelope(kind, reason, "m")


def test_raise_if_failed_maps_kind_to_class_and_passes_ok_through():
    ok = {"status": "ok"}
    assert results.raise_if_failed(ok) is ok
    env = results.failure_envelope("backend", "timeout", "took too long", output_files=["a"])
    with pytest.raises(ExecutionBackendError) as e:
        results.raise_if_failed(env)
    assert e.value.reason == "timeout" and e.value.result is env and "took too long" in str(e.value)
    with pytest.raises(EngineExecutionError) as e2:
        results.raise_if_failed(results.failure_envelope("engine", "unusable_site", "site"))
    assert e2.value.reason == "unusable_site"


def test_with_status_fields_adds_status_alias_version_and_drops_error_keys():
    r = {"rwp": 6.5, "error": None, "traceback": None}
    out = results.with_status_fields(r, status="ok", converged=False)
    assert out is r
    assert r["status"] == "ok" and r["converged"] is False and r["envelope_version"] == "1" and "success" not in r
    assert "error" not in r and "traceback" not in r


def test_generated_envelope():
    env = results.generated_envelope(run_id="g", elapsed=0.1, method="topas_generate_only", warnings=[],
                                     output_files=["x.inp", "x.xye"], simulation_mode=False, engine_details={})
    assert env["status"] == "generated" and "success" not in env and env["converged"] is None
    assert env["rwp"] is None and env["output_files"] == ["x.inp", "x.xye"]
    assert env["fit_profile"].empty and env["refined_parameters"].empty


def test_legacy_failure_adapts_a_frozen_dict():
    old = {"success": False, "run_id": "r", "error": "Refinement failed: x", "traceback": "tb",
           "elapsed_time": 2.0, "method": "subprocess"}
    env = results.legacy_failure(old)
    assert env["status"] == "failed" and env["failure"]["reason"] == "engine_crashed"
    assert env["failure"]["message"] == "Refinement failed: x" and env["failure"]["traceback"] == "tb"
    assert env["run_id"] == "r" and env["elapsed_time"] == 2.0


def _boom():
    raise EngineExecutionError("diverged in a worker", reason="diverged", result={"status": "failed", "run_id": "w"})


@pytest.mark.parametrize("exc", [
    EngineExecutionError("m", reason="diverged", result={"status": "failed"}),
    ExecutionBackendError("m", reason="timeout", result={"status": "failed"}),
    EngineNotAvailableError(gateway="g", dependency="d", env="e", install_command="i"),
    EngineVersionError(gateway="g", engine="x", installed="1", supported="==2"),
    GatewayNotInstalledError("m", gateway="g"),
])
def test_exceptions_pickle_round_trip(exc):
    back = pickle.loads(pickle.dumps(exc))
    assert type(back) is type(exc) and str(back) == str(exc)
    for attr in ("reason", "result", "gateway", "dependency", "env", "install_command", "engine", "installed",
                 "supported"):
        if hasattr(exc, attr):
            assert getattr(back, attr) == getattr(exc, attr)


@pytest.mark.skipif(os.name == "nt", reason="spawn start method must import this test module by name in the "
                                             "child; the pickle round-trip test above covers the mechanism")
def test_exception_crosses_a_process_pool():
    with ProcessPoolExecutor(max_workers=1) as pool:
        with pytest.raises(EngineExecutionError) as e:
            pool.submit(_boom).result()
    assert e.value.reason == "diverged" and e.value.result["run_id"] == "w"


def test_execution_backend_error_is_public():
    assert "ExecutionBackendError" in powderline.__all__ and powderline.ExecutionBackendError is ExecutionBackendError


def test_converged_of_is_none_for_a_simulation_whatever_the_engine_says():
    assert results.converged_of({"simulation_mode": True, "engine_details": {"converged": False}}) is None
    assert results.converged_of({"simulation_mode": False, "engine_details": {"converged": False}}) is False
    assert results.converged_of({"simulation_mode": False, "engine_details": {}}) is None
    assert results.converged_of({"engine_details": {"converged": True}}) is True


# --- re/19 (P-42 D2): the deprecated success alias is gone from every envelope ----------------------------

def test_envelopes_carry_no_success_alias():
    ok = results.with_status_fields({"engine_details": {"converged": True}, "simulation_mode": False},
                                    status="ok", converged=True)
    gen = results.generated_envelope(elapsed=0.0, method="generate", warnings=[], output_files=[],
                                     simulation_mode=False, engine_details={})
    failed = results.failure_envelope("backend", "backend_error", "x")
    for env in (ok, gen, failed):
        assert "success" not in env, env.get("status")


def test_with_status_fields_strips_a_success_key_the_engine_set():
    env = results.with_status_fields({"success": True}, status="ok", converged=None)
    assert "success" not in env and env["status"] == "ok"
