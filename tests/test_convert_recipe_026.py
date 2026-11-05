"""The 0.26.0 -> gsasii 0.1.0 converter (``scripts/convert_recipe_026.py``; re/04 subplan §3, A95, A101, A124).

One test per rule, a synthetic ADP switch in both directions (no committed
example has one), and every 0.26.0 example converted: the result validates,
or the conversion stops for a stated reason. The 0.26.0 inputs are the
converter's fixtures in ``tests/data/convert_026/`` (the pre-conversion
examples, byte-identical; the committed examples are native ``gsasii.*``
recipes since re/07; P-16, P-23).
"""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest

from powderline.gateways.gsasii.schema import gsasii_iparm1, gsasii_space_group, validate_recipe

pytestmark = pytest.mark.core

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("convert_recipe_026", ROOT / "scripts" / "convert_recipe_026.py")
conv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(conv)

LEGACY = ROOT / "tests" / "data" / "convert_026"  # the converter's 0.26.0 fixtures (re/07, P-23)
EXAMPLES = sorted(LEGACY.glob("*/input.json"))


def _load(name: str) -> dict:
    return json.loads((LEGACY / name / "input.json").read_text(encoding="utf-8"))


def _lab6() -> dict:
    """The LaB6 example with its background peak raised to GSAS-II's floor (the committed one is below it)."""
    r = _load("example_LaB6")
    r["payload"]["background"]["single_peaks"]["pv_lorentzian_gamma"][0][0] = 0.1
    return r


def _phase(r: dict) -> dict:
    return r["payload"]["phases"]["LaB6"]


def _convert(r: dict):
    new, report = conv.convert(r)
    return new, "\n".join(report)


# --- top level, instrument, background ----------------------------------------


def test_top_level_and_metadata():
    new, report = _convert(_lab6())
    assert (new["schema_name"], new["core_schema_version"], new["engine_schema_version"]) == \
        ("gsasii.rietveld", "0.1.0", "0.1.0")
    assert "schema_version" not in new
    assert new["metadata"] == {"xrd_data": {"UID": _lab6()["payload"]["xrd_data"]["UID"]}}
    assert set(new["payload"]["xrd_data"]) <= {"tth", "Itth", "Itth_weights", "filename"}
    assert "payload.xrd_data.UID: moved to metadata.xrd_data.UID" in report


def test_instrument_from_iparm1_and_parameterization():
    r = _lab6()
    new, report = _convert(r)
    inst = new["payload"]["instrument"]
    iparm1 = r["payload"]["instrument"]["initialization"][0]
    assert inst["radiation"] == {"type": "PXC", "wavelength": [0.1665, False]}
    assert inst["geometry"] == {"bank": 1, "azimuth": 0.0}
    assert inst["broadening"]["U"] == [iparm1["U"][1], True]  # null value: Iparm1; flag from the parameterization
    assert inst["corrections"]["zero_shift"] == [0.0, False]  # parameterization null: Iparm1 value and flag
    assert inst["corrections"]["axial_divergence"] == [0.002, False]  # A91
    assert "SH/L 0.0005 -> 0.002" in report
    model = validate_recipe(new)
    built = gsasii_iparm1(model.payload.instrument)
    assert {k: v for k, v in built.items() if k != "SH/L"} == {k: v for k, v in iparm1.items() if k != "SH/L"}


@pytest.mark.parametrize("key", ["Lam1", "Lam2"])
def test_instrument_doublet_stops(key):
    r = _lab6()
    r["payload"]["instrument"]["initialization"][0][key] = [0.1, 0.1, False]
    with pytest.raises(conv.ConversionError, match="not supported"):
        conv.convert(r)


def test_instrument_type_other_than_pxc_stops():
    r = _lab6()
    r["payload"]["instrument"]["initialization"][0]["Type"] = ["PNC", "PNC", False]
    with pytest.raises(conv.ConversionError, match="'PXC' only"):
        conv.convert(r)


def test_iparm2_dropped_with_report():
    r = _lab6()
    r["payload"]["instrument"]["initialization"][1] = {"something": [1, 1, False]}
    assert "Iparm2 dropped" in _convert(r)[1]


def test_background_peaks_renamed_and_null_peaks_dropped():
    r = _lab6()
    peaks = r["payload"]["background"]["single_peaks"]
    for k in peaks:
        peaks[k].append([None, False, None, None])
    new, report = _convert(r)
    bp = new["payload"]["background"]["single_peaks"]
    assert set(bp) == {"positions", "intensities", "pv_gaussian_sigma_sq", "pv_lorentzian_gamma"}
    assert bp["pv_gaussian_sigma_sq"] == [[1000, True]] and bp["pv_lorentzian_gamma"] == [[0.1, True]]
    assert "1 peak(s) with a null entry dropped" in report and "renamed pv_gaussian_sigma_sq" in report


def test_background_left_out_reported():
    r = _lab6()
    r["payload"]["background"] = None
    new, report = _convert(r)
    assert "background" not in new["payload"]
    assert "constant 1.0" in report
    assert validate_recipe(new).payload.background.chebyshev.coefficients == [0.0]


def test_background_peak_below_engine_floor_stops():
    with pytest.raises(conv.ConversionError) as exc:
        conv.convert(_load("example_LaB6"))
    assert exc.value.problems == [
        "payload.background.single_peaks.pv_lorentzian_gamma.0: pv_lorentzian_gamma[0] = 1e-05 is below 0.1, the "
        "smallest value GSAS-II computes with; it would silently use 0.1 (GSAS-II quirk EB-35)"]


def test_unused_peak_list_dropped_from_rietveld():
    r = _lab6()
    r["payload"]["single_peaks"] = {"positions": [[2.0, True, None, None]], "intensities": [[1.0, True, None, None]],
                                    "pv_gaussian_sigma_sq": [[1.0, True, None, None]],
                                    "pv_lorentzian_gamma": [[1.0, True, None, None]]}
    new, report = _convert(r)
    assert "single_peaks" not in new["payload"] and "Peak List peaks take no part" in report


def test_controls_fit_range_asset_path_and_bounds():
    r = _lab6()
    r["payload"]["refinement_controls"]["refinement_algorithm"] = "lm"
    r["payload"]["asset_path"] = "data/"
    r["payload"]["fit_range"] = [None, None]
    _phase(r)["parameterization"]["scale"] = [1, True, 0.0, 10.0]
    new, report = _convert(r)
    assert new["payload"]["refinement_controls"] == {"refinement_cycles": 5}
    assert "fit_range" not in new["payload"]
    assert "refinement_algorithm: dropped ('lm'" in report and "asset_path: dropped" in report
    assert "payload.phases.LaB6.parameterization.scale: bounds [0.0, 10.0] dropped" in report
    assert new["payload"]["phases"]["LaB6"]["scale"] == [1, True]


# --- phases -------------------------------------------------------------------


@pytest.mark.parametrize("old, canonical", [
    ("P m -3 m", "P m -3 m"), ("C2/m", "C 1 2/m 1"), ("P21/c", "P 1 21/c 1"), ("R -3 m", "R -3 m:H"),
    ("R -3 m R", "R -3 m:R"), ("R -3 m:R", "R -3 m:R"), ("R -3 m:H", "R -3 m:H"), ("R 3 2:R", "R 3 2:R"),
    ("F d -3 m", "F d -3 m:2"), ("F d -3 m:2", "F d -3 m:2"), ("Fd-3m", "F d -3 m:2"),
])
def test_space_group_as_gsasii_read_it(old, canonical):
    assert conv.canonical_space_group(old) == canonical


@pytest.mark.parametrize("old", ["F d -3 m:1", "P 4/n:1", "P n -3 n:1"])
def test_space_group_origin_choice_1_stops(old):
    """v0.1.1 ran origin-1 coordinates as origin 2 (EB-03): neither structure is known, so stop (A132)."""
    with pytest.raises(ValueError, match="origin choice 1"):
        conv.canonical_space_group(old)


def test_values_merge_and_cell_flags_expand():
    r = _lab6()
    cell = _phase(r)["parameterization"]["unit_cell"]
    cell["a"] = [4.157, True, None, None]
    cell["b"] = [4.157, False, None, None]
    cell["c"] = [4.157, False, None, None]
    cell["alpha"] = [None, True, None, None]
    new, report = _convert(r)
    uc = new["payload"]["phases"]["LaB6"]["unit_cell"]
    assert uc["a"] == uc["b"] == uc["c"] == [4.157, True]
    assert uc["alpha"] == [90.0, False]
    assert "4.15682 -> 4.157" in report and "unit_cell.b: refine flag false -> true" in report
    assert "unit_cell.alpha: refine flag true -> false (fixed by symmetry" in report


def test_cell_override_breaking_symmetry_stops():
    r = _lab6()
    _phase(r)["parameterization"]["unit_cell"]["a"] = [4.157, True, None, None]
    with pytest.raises(conv.ConversionError, match="unit_cell"):
        conv.convert(r)  # a = 4.157 but b = c = 4.15682: core rejects the cubic cell (A123)


def test_monoclinic_gsasii_cell_group_expands():
    r = _load("example_DRX_33")
    ph = r["payload"]["phases"]["Li4MgWO6_SG12"]
    ph["parameterization"]["unit_cell"] = {k: [None, k == "a", None, None]
                                           for k in ("a", "b", "c", "alpha", "beta", "gamma")}
    new, report = _convert(r)
    uc = new["payload"]["phases"]["Li4MgWO6_SG12"]["unit_cell"]
    assert [uc[k][1] for k in ("a", "b", "c", "alpha", "beta", "gamma")] == [True, False, True, False, True, False]
    assert "Li4MgWO6_SG12.unit_cell.beta: refine flag false -> true" in report


def test_atom_flags_and_fixed_constant_rewritten():
    r = _lab6()
    atoms = _phase(r)["parameterization"]["atoms"]
    atoms["B"]["x"] = [None, True, None, None]  # B at (0.5, 0.5, z): x fixed
    atoms["B"]["z"] = [None, True, None, None]
    _phase(r)["structure"]["atoms"]["B"]["y"] = 0.4999999
    new, report = _convert(r)
    b = new["payload"]["phases"]["LaB6"]["atoms"]["B"]
    assert b["x"] == [0.5, False] and b["y"] == [0.5, False] and b["z"] == [0.2021, True]
    assert "atoms.B.x: refine flag true -> false (fixed by symmetry" in report
    assert "atoms.B.y: 0.4999999 -> 0.5" in report


def test_ambiguous_position_stops():
    r = _lab6()
    _phase(r)["structure"]["atoms"]["B"]["y"] = 0.4995
    with pytest.raises(conv.ConversionError, match="atoms.B"):
        conv.convert(r)


def test_multiplicity_kept_or_dropped():
    new, report = _convert(_lab6())
    assert new["payload"]["phases"]["LaB6"]["atoms"]["B"]["Multiplicity"] == 6
    new, report = _convert(_load("example_DRX_33"))
    assert "Multiplicity" not in new["payload"]["phases"]["Li4MgWO6_SG12"]["atoms"]["O1"]
    assert "atoms.O1.Multiplicity: stated 1, derived 8: dropped (the site symmetry fixes it)" in report


def test_silent_defaults_written():
    r = _lab6()
    b = _phase(r)["structure"]["atoms"]["B"]
    del b["occupancy"]
    b["Uiso"] = None
    _phase(r)["parameterization"]["scale"] = [None, True, None, None]
    new, report = _convert(r)
    atom = new["payload"]["phases"]["LaB6"]["atoms"]["B"]
    assert atom["occupancy"] == [1.0, False] and atom["Uiso"] == [0.0, False]
    assert new["payload"]["phases"]["LaB6"]["scale"] == [1.0, True]
    assert "atoms.B.occupancy: absent: 1.0" in report and "atoms.B.Uiso: absent: 0.0" in report


def test_adp_switch_uiso_flag_on_anisotropic_atom():
    """Structure Uaniso, parameterization ADP Uiso with a flag and no value: GSAS-II kept Uaniso and refined it."""
    r = _lab6()
    la = _phase(r)["structure"]["atoms"]["La"]
    la.update(ADP="Uaniso", Uiso=None, Uaniso={"U11": 0.01, "U22": 0.01, "U33": 0.01, "U12": 0.0, "U13": 0.0,
                                               "U23": 0.0})
    _phase(r)["parameterization"]["atoms"]["La"]["Uiso"] = [None, True, None, None]
    new, report = _convert(r)
    atom = new["payload"]["phases"]["LaB6"]["atoms"]["La"]
    assert atom["ADP"] == "Uaniso" and "Uiso" not in atom
    assert [atom["Uaniso"][k][1] for k in ("U11", "U22", "U33", "U12", "U13", "U23")] == \
        [True, True, True, False, False, False]  # m-3m site: U11 = U22 = U33 free, off-diagonal fixed
    assert "atoms.La.ADP: Uaniso (the structure's)" in report


def test_adp_switch_uij_flags_on_isotropic_atom():
    """Structure Uiso, parameterization ADP Uaniso with flags and no values: GSAS-II kept Uiso and refined it."""
    r = _lab6()
    p = _phase(r)["parameterization"]["atoms"]["B"]
    p.pop("Uiso")
    p.update(ADP="Uaniso", Uaniso={k: [None, k == "U11", None, None] for k in ("U11", "U22", "U33", "U12", "U13",
                                                                           "U23")})
    new, report = _convert(r)
    atom = new["payload"]["phases"]["LaB6"]["atoms"]["B"]
    assert atom["ADP"] == "Uiso" and atom["Uiso"] == [0.009, True]
    assert "atoms.B.ADP: Uiso (the structure's)" in report


def test_adp_switch_with_values_takes_the_parameterization():
    r = _lab6()
    p = _phase(r)["parameterization"]["atoms"]["La"]
    p.pop("Uiso")
    p.update(ADP="Uaniso", Uaniso={k: [0.01 if k in ("U11", "U22", "U33") else 0.0, False, None, None]
                                   for k in ("U11", "U22", "U33", "U12", "U13", "U23")})
    new, _ = _convert(r)
    atom = new["payload"]["phases"]["LaB6"]["atoms"]["La"]
    assert atom["ADP"] == "Uaniso" and atom["Uaniso"]["U11"] == [0.01, False]


def test_size_strain_left_out_or_kept():
    new, report = _convert(_lab6())
    assert "peak_broadening" not in new["payload"]["phases"]["LaB6"]
    assert "size_broadening: left out" in report and "strain_broadening: left out" in report
    r = _lab6()
    _phase(r)["parameterization"]["peak_broadening"]["size_broadening"]["isotropic_size"] = [1.0, True, None, None]
    new, report = _convert(r)
    assert new["payload"]["phases"]["LaB6"]["peak_broadening"] == {
        "size_broadening": {"model": "isotropic", "isotropic_size": [1.0, True], "LG_eta": [1.0, False]}}
    assert "size_broadening.LG_eta: no value" in report


def test_names_and_phase_name_mismatch_stop():
    r = _lab6()
    r["payload"]["phases"]["La B6"] = r["payload"]["phases"].pop("LaB6")
    with pytest.raises(conv.ConversionError) as exc:
        conv.convert(r)
    assert any("phase_name" in p for p in exc.value.problems)
    assert any(p.startswith("payload.phases.La B6") for p in exc.value.problems)


def test_unknown_keys_and_orphan_atoms_reported():
    """0.26.0 accepted any extra key (extra='allow') and v0.1.1 ignored it: dropped, and reported (A132)."""
    r = _lab6()
    r["payload"]["phases"]["LaB6"]["parameterization"]["preferred_orientation"] = {"ratio": [1.2, True, None, None]}
    r["payload"]["phases"]["LaB6"]["parameterization"]["atoms"]["Zz"] = {"x": [0.1, True, None, None], "ADP": "Uiso"}
    r["payload"]["phases"]["LaB6"]["parameterization"]["peak_broadening"]["size_broadening"]["S11"] = 0.5
    r["payload"]["notes"] = "lab book p. 12"
    _, report = _convert(r)
    assert "payload.phases.LaB6.parameterization.preferred_orientation: dropped: not a 0.26.0 field" in report
    assert "payload.phases.LaB6.parameterization.atoms.Zz: dropped: the structure has no atom of that label" in report
    assert "size_broadening.S11: dropped (0.5): the isotropic model v0.1.1 ran did not use it" in report
    assert "payload.notes: dropped: not a 0.26.0 field" in report


def test_unknown_correction_key_stops():
    """v0.1.1 raised for a correction it did not know, so there is nothing to reproduce."""
    r = _lab6()
    r["payload"]["instrument"]["parameterization"]["corrections"]["sample_displacement"] = [0.1, True, None, None]
    with pytest.raises(conv.ConversionError, match="not a 0.26.0 correction; v0.1.1 raised"):
        conv.convert(r)


def test_old_uij_name_read_as_uaniso():
    """v0.1.1's reader took the structure's Uaniso from the old key Uij too (project.py)."""
    r = _lab6()
    atom = _phase(r)["structure"]["atoms"]["La"]
    atom.pop("Uiso", None)
    atom.update(ADP="Uaniso", Uij={k: (0.01 if k in ("U11", "U22", "U33") else 0.0)
                                   for k in ("U11", "U22", "U33", "U12", "U13", "U23")})
    _phase(r)["parameterization"]["atoms"]["La"]["ADP"] = "Uaniso"
    _phase(r)["parameterization"]["atoms"]["La"].pop("Uiso", None)
    new, report = _convert(r)
    assert new["payload"]["phases"]["LaB6"]["atoms"]["La"]["Uaniso"]["U11"] == [0.01, False]
    assert "atoms.La.Uij: read as Uaniso" in report


def test_partial_uaniso_override_stops():
    """v0.1.1 raised unless all six Uij were given in the parameterization."""
    r = _lab6()
    p = _phase(r)["parameterization"]["atoms"]["La"]
    p.pop("Uiso")
    p.update(ADP="Uaniso", Uaniso={k: [0.01 if k == "U11" else None, False, None, None]
                                   for k in ("U11", "U22", "U33", "U12", "U13", "U23")})
    with pytest.raises(conv.ConversionError, match="gives U11 only; v0.1.1 raised"):
        conv.convert(r)


# --- every committed example ---------------------------------------------------

STOPS = {
    "example_LaB6": "pv_lorentzian_gamma[0] = 1e-05 is below 0.1",
    "example_LaB6_simulation": "pv_lorentzian_gamma[0] = 1e-05 is below 0.1",
    "example_template": "missing GSAS-II keys",
}


@pytest.mark.parametrize("path", EXAMPLES, ids=[p.parent.name for p in EXAMPLES])
def test_committed_example(path):
    recipe = json.loads(path.read_text(encoding="utf-8"))
    name = path.parent.name
    if name in STOPS:
        with pytest.raises(conv.ConversionError, match=STOPS[name].replace("[", r"\[").replace("]", r"\]")):
            conv.convert(recipe)
        return
    new, report = conv.convert(recipe)
    model = validate_recipe(new)
    assert validate_recipe(json.loads(json.dumps(new))).model_dump() == model.model_dump()
    if name.startswith("example_DRX_33"):
        assert "Multiplicity: stated 1, derived 8: dropped (the site symmetry fixes it)" in "\n".join(report)
    if name == "example_LaB6_singlepeakfit":
        assert "SH/L 0.0 -> 0.002" in "\n".join(report)


def test_cli_writes_utf8_lf(tmp_path):
    src = tmp_path / "in.json"
    src.write_text(json.dumps(_lab6()), encoding="utf-8")
    out = tmp_path / "out.json"
    assert conv.main([str(src), "-o", str(out)]) == 0
    data = out.read_bytes()
    assert b"\r\n" not in data and data.endswith(b"\n")
    validate_recipe(json.loads(data.decode("utf-8")))
    assert conv.main([str(LEGACY / "example_template" / "input.json")]) == 1


def test_a_gsasii_spelled_ion_becomes_neutral_element_plus_scattering_types():
    """re/28 (P-47): v0.1.1 passed GSAS-II's own ion spelling through unchecked; the converter maps it onto the
    0.1.0 shape (neutral element, the ion in the recipe spelling under scattering_types) and notes it."""
    r = copy.deepcopy(_lab6())
    phase = next(iter(r["payload"]["phases"].values()))
    phase["structure"]["atoms"]["La"]["element"] = "La+3"
    new, report = _convert(r)
    atoms = next(iter(new["payload"]["phases"].values()))["atoms"]
    assert atoms["La"]["element"] == "La"
    assert next(iter(new["payload"]["phases"].values()))["scattering_types"] == {"La": "La3+"}
    assert "'La+3' -> neutral 'La' + scattering_types['La'] = 'La3+'" in report
    validate_recipe(new)
