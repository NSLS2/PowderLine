"""re/27 (KI-13): ``powderline --doctor`` — what this environment can do (engine-free)."""
import pytest

from powderline import doctor, kicker, registry

pytestmark = pytest.mark.core


def test_report_lists_every_registered_gateway_with_its_requirement():
    rep = doctor.report()
    names = {g["name"] for g in rep["gateways"]}
    assert {"gsasii", "topas", "easydiffraction"} <= names
    by = {g["name"]: g for g in rep["gateways"]}
    assert by["gsasii"]["engine_version_spec"] == "==5.7.9" and "gsasii.spf" in by["gsasii"]["workflows"]
    assert by["topas"]["engine_status"].startswith(("declared only", "no installed version declared"))
    for g in rep["gateways"]:
        assert g["engine_status"] != "unknown"
        if g["engine_installed"] is not None and "satisfies" in g["engine_status"]:
            assert g["problem"] is None
    assert rep["powderline"] and rep["python"] and "server" in rep
    text = doctor.format_report(rep)
    assert "gateways (" in text and ("no problems found" in text or "PROBLEMS" in text)


def test_no_registry_is_a_problem_naming_the_repair(monkeypatch):
    monkeypatch.setattr(registry, "available", lambda: [])
    rep = doctor.report()
    assert rep["gateways"] == [] and len(rep["problems"]) == 1
    assert "KI-13" in rep["problems"][0] and "pixi reinstall powderline" in rep["problems"][0]
    assert doctor.main() == 1


def test_an_engine_outside_its_requirement_is_a_problem(monkeypatch):
    from powderline.gateways.gsasii import gateway as gsasii_gateway
    monkeypatch.setattr(gsasii_gateway, "installed_engine_version", lambda: "5.8.0")
    rep = doctor.report()
    g = next(x for x in rep["gateways"] if x["name"] == "gsasii")
    assert g["engine_installed"] == "5.8.0" and "OUTSIDE ==5.7.9" in g["engine_status"]
    assert any("5.8.0" in p and "==5.7.9" in p for p in rep["problems"])


def test_an_engine_not_installed_is_reported_not_a_problem(monkeypatch):
    from powderline.exceptions import EngineNotAvailableError
    from powderline.gateways.gsasii import gateway as gsasii_gateway

    def missing():
        raise EngineNotAvailableError(gateway="gsasii", dependency="GSAS-II", env="gsasii", install_command="pixi install -e gsasii")
    monkeypatch.setattr(gsasii_gateway, "installed_engine_version", missing)
    rep = doctor.report()
    g = next(x for x in rep["gateways"] if x["name"] == "gsasii")
    assert g["engine_status"] == "not installed in this environment" and g["problem"] is None
    assert not any("gsasii" in p for p in rep["problems"])


def test_cli_doctor_flag_needs_no_recipe(capsys):
    code = kicker.main(["--doctor"])
    out = capsys.readouterr().out
    assert "PowderLine" in out and "gateways" in out
    assert code == (1 if doctor.report()["problems"] else 0)


def test_cli_without_a_recipe_or_doctor_is_a_usage_error(capsys):
    with pytest.raises(SystemExit) as info:
        kicker.main([])
    assert info.value.code == 2
    assert "a recipe file is required (or --doctor)" in capsys.readouterr().err
