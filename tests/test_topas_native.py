"""Tests for native TOPAS path (re/05): writer, runner, gateway.

Tests the TOPAS-native input generation, execution handling, and gateway
integration without requiring a TOPAS installation (runner is injected).
"""

from __future__ import annotations

import json
import math
import os
import re
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

from powderline.exceptions import EngineExecutionError, EngineVersionError, ExecutionBackendError
from powderline.gateways.topas import gateway, native_run, native_writer, peak_list, schema
from subprocess_utils import run_subprocess_utf8
from test_topas_schema import P, _rietveld, _spf

pytestmark = pytest.mark.topas_gen


# ============================================================================
# A. Writer tests (render_native on validated models)
# ============================================================================


def test_writer_lab6_rietveld_structure():
    """LaB6 INP contains space group, cell, site keywords, peak type, corrections."""
    model = schema.validate_recipe(_rietveld())
    native = native_writer.render_native(model, "test")
    inp = native.inp_text

    # Space group and cell
    assert 'space_group "pm-3m"' in inp
    assert "a p1_cell_a 4.1569" in inp
    assert "b = Get(a);" in inp
    assert "c = Get(a);" in inp
    assert "al 90" in inp
    assert "be 90" in inp
    assert "ga 90" in inp

    # Site B1 with refined x and ties
    assert "site B1" in inp
    assert "x p1_a2_x 0.1993 min 0.15 max 0.25" in inp
    assert "y 0.5" in inp
    assert "z 0.5" in inp

    # beq = 8*pi^2*Uiso
    beq_b1 = 8 * math.pi ** 2 * 0.006
    beq_pattern = rf"beq p1_a2_beq {beq_b1:.6g}"
    assert re.search(beq_pattern.replace(".", r"\.").replace("+", r"\+"), inp), f"Expected beq {beq_b1}"

    # Peak type
    assert "TCHZ_Peak_Type(, inst_U, , inst_V, , inst_W, , inst_Z, , inst_X, , inst_Y)" in inp

    # LP_Factor after str (look for the str phase keyword on its own line)
    str_lines = [i for i, line in enumerate(inp.split('\n')) if line.strip() == 'str']
    lp_lines = [i for i, line in enumerate(inp.split('\n')) if 'LP_Factor(, lp_monochromator_angle)' in line]
    assert len(str_lines) > 0 and len(lp_lines) > 0
    assert str_lines[0] < lp_lines[0]

    # Geometry corrections before first str (xdd level)
    assert "ZE(, ze_th2_offset)" in inp
    assert "Simple_Axial_Model(, ax_axial_length_mm)" in inp
    ze_lines = [i for i, line in enumerate(inp.split('\n')) if 'ZE(, ze_th2_offset)' in line]
    axial_lines = [i for i, line in enumerate(inp.split('\n')) if 'Simple_Axial_Model(, ax_axial_length_mm)' in line]
    assert ze_lines[0] < str_lines[0]
    assert axial_lines[0] < str_lines[0]

    # Rs 1000, no Rp
    assert "Rs 1000" in inp
    assert "Rp" not in inp

    # do_errors present, no Get(bkg)
    assert "do_errors" in inp
    assert "Get(bkg)" not in inp


def test_writer_macro_prm_limits():
    """Macro parameters get TOPAS.INC default expressions or stated bounds."""
    model = schema.validate_recipe(_rietveld())
    native = native_writer.render_native(model, "test")
    inp = native.inp_text

    # Refined inst_U with no stated bounds: TOPAS.INC defaults
    assert re.search(r"prm inst_U .* min = Max\(-1, Val-\.1\);", inp)
    assert re.search(r"prm inst_U .* max = Min\(2, Val\+\.1\);", inp)
    assert re.search(r"prm inst_U .* del 1\.0e-4", inp)

    # Fixed macro parameter: prm !name value, no limits
    recipe = _rietveld()
    recipe["payload"]["instrument"]["corrections"]["Zero_Error"]["th2_offset"][1] = False
    model = schema.validate_recipe(recipe)
    native = native_writer.render_native(model, "test")
    assert re.search(r"prm !ze_th2_offset 0(?:\.\d+)?(?:\s|$)", native.inp_text)
    assert "min" not in [line for line in native.inp_text.splitlines() if "ze_th2_offset" in line][0]

    # Macro parameter with only min stated: min <stated> AND default max expression
    recipe = _rietveld()
    recipe["payload"]["instrument"]["broadening"]["parameters"]["U"] = P(0.0001, True, -0.5, None)
    model = schema.validate_recipe(recipe)
    native = native_writer.render_native(model, "test")
    inst_u_line = [line for line in native.inp_text.splitlines() if "prm inst_U" in line and "!inst_U" not in line][0]
    assert "min -0.5" in inst_u_line or "min = -0.5" in inst_u_line
    assert "max = Min(2, Val+.1)" in inst_u_line


def test_writer_keyword_parameter_one_sided():
    """Keyword parameter with only one stated side emits only that side."""
    recipe = _rietveld()
    recipe["payload"]["phases"]["LaB6"]["scale"] = P(1.5e-6, True, 1e-7, None)
    model = schema.validate_recipe(recipe)
    native = native_writer.render_native(model, "test")

    scale_line = [line for line in native.inp_text.splitlines() if "scale p1_scale" in line][0]
    assert "min 1e-07" in scale_line or "min 1.0e-7" in scale_line
    assert "max" not in scale_line


def test_writer_affine_ties_and_thirds():
    """Ties with affine relations: thirds as equations, affine forms."""
    recipe = _rietveld()
    # P 63/m m c: a=b, gamma=120
    # Atom A at (1/3, 2/3, 1/4) Uaniso
    # Atom B at 6h site (x, 2x, 1/4) with Uaniso U11, U22, U33, U12=U22/2, U13=U23=0
    # For 6h: U22=U11, U12=U11/2
    recipe["payload"]["phases"]["LaB6"]["space_group"] = "P 63/m m c"
    recipe["payload"]["phases"]["LaB6"]["unit_cell"] = {
        "a": P(5.0, True), "b": P(5.0, True), "c": P(10.0, True),
        "alpha": P(90), "beta": P(90), "gamma": P(120)
    }
    recipe["payload"]["phases"]["LaB6"]["atoms"] = {
        "A": {
            "element": "La", "x": P(0.3333333333333333), "y": P(0.6666666666666666), "z": P(0.25),
            "occupancy": P(1), "ADP": "Uaniso",
            "Uaniso": {
                "U11": P(0.005, True), "U22": P(0.005, True), "U33": P(0.003, True),
                "U12": P(0.0025, True), "U13": P(0), "U23": P(0)
            }
        },
        "B": {
            "element": "B", "x": P(0.17, True), "y": P(0.34, True), "z": P(0.25),  # y refine flag must match x
            "occupancy": P(1), "ADP": "Uaniso",
            "Uaniso": {
                "U11": P(0.006, True), "U22": P(0.006), "U33": P(0.004, True),
                "U12": P(0.003), "U13": P(0), "U23": P(0)
            }
        }
    }
    model = schema.validate_recipe(recipe)
    native = native_writer.render_native(model, "test")
    inp = native.inp_text

    # Thirds as equations
    assert "x = 1/3;" in inp
    assert "y = 2/3;" in inp

    # Affine tie: y = 2*x for atom B
    assert "y = 2*p1_a2_x;" in inp

    # U12 = U22/2 and U22 = U11, U12 = U11/2
    assert "u12 = p1_a2_u22/2;" in inp  # 6h: U12 = U22/2
    assert "u12 = p1_a1_u11/2;" in inp  # 2c: U12 = U11/2
    assert "u22 = p1_a1_u11;" in inp

    # U13 = 0
    assert "u13 0" in inp


def test_affine_text_and_frac_text_unit_cases():
    """affine_text and frac_text formatting."""
    from fractions import Fraction

    assert native_writer.affine_text(Fraction(-1), "r", Fraction(1, 2)) == "-r + 1/2"
    assert native_writer.affine_text(Fraction(2), "r", Fraction(0)) == "2*r"
    assert native_writer.affine_text(Fraction(1, 2), "r", Fraction(0)) == "r/2"
    assert native_writer.affine_text(Fraction(-1, 2), "r", Fraction(0)) == "-r/2"
    assert native_writer.affine_text(Fraction(1), "r", Fraction(-1, 3)) == "r - 1/3"


def test_writer_unique_names_multi_phase():
    """Names are unique across phases."""
    recipe = _rietveld()
    # Add a second phase (copy LaB6 with a different label set)
    phase2 = json.loads(json.dumps(recipe["payload"]["phases"]["LaB6"]))
    recipe["payload"]["phases"]["CeO2"] = phase2
    model = schema.validate_recipe(recipe)
    native = native_writer.render_native(model, "test")

    # All parameter names are unique
    all_names = list(native.params.keys())
    assert len(all_names) == len(set(all_names)), f"Duplicate names: {all_names}"

    # Phase-2 names start with p2_
    p2_names = [n for n in all_names if n.startswith("p2_")]
    assert len(p2_names) > 0, "Expected some p2_ names for the second phase"


def test_writer_simulation_no_do_errors():
    """Simulation (iters 0): no do_errors, no out_fmt_err."""
    recipe = _rietveld()
    recipe["payload"]["refinement_controls"]["iters"] = 0
    # Turn off all refine flags
    for phase in recipe["payload"]["phases"].values():
        for param in ["scale", "unit_cell"]:
            if param == "unit_cell":
                for axis in ["a", "b", "c", "alpha", "beta", "gamma"]:
                    phase[param][axis][1] = False
            else:
                phase[param][1] = False
        for atom in phase["atoms"].values():
            for p in ["x", "y", "z", "occupancy", "Uiso"]:
                if p in atom and isinstance(atom[p], list):
                    atom[p][1] = False
        if "peak_broadening" in phase and phase["peak_broadening"]:
            if "size_broadening" in phase["peak_broadening"] and phase["peak_broadening"]["size_broadening"]:
                for k in ["CS_L", "CS_G"]:
                    if k in phase["peak_broadening"]["size_broadening"] and phase["peak_broadening"]["size_broadening"][k]:
                        phase["peak_broadening"]["size_broadening"][k][1] = False
    recipe["payload"]["background"]["chebyshev"]["refine_flag"] = False
    recipe["payload"]["background"]["One_on_X"][1] = False
    recipe["payload"]["background"]["peaks"][0]["xo"][1] = False
    recipe["payload"]["background"]["peaks"][0]["I"][1] = False
    recipe["payload"]["background"]["peaks"][0]["parameters"]["pv_fwhm"][1] = False
    recipe["payload"]["background"]["peaks"][0]["parameters"]["pv_lor"][1] = False
    for corr_param in ["Zero_Error", "Simple_Axial_Model"]:
        if corr_param in recipe["payload"]["instrument"]["corrections"]:
            for k, v in recipe["payload"]["instrument"]["corrections"][corr_param].items():
                if isinstance(v, list):
                    recipe["payload"]["instrument"]["corrections"][corr_param][k][1] = False
    for k in recipe["payload"]["instrument"]["broadening"]["parameters"]:
        recipe["payload"]["instrument"]["broadening"]["parameters"][k][1] = False

    model = schema.validate_recipe(recipe)
    native = native_writer.render_native(model, "test")

    assert "do_errors" not in native.inp_text
    assert "out_fmt_err" not in native.inp_text


def test_writer_spf_structure():
    """SPF: one xo_Is per peak, gauss_fwhm, no LP_Factor in SPF, spf_fwhm derived."""
    recipe = _spf()
    model = schema.validate_recipe(recipe)
    native = native_writer.render_native(model, "test")
    inp = native.inp_text

    # Two xo_Is blocks (one per peak)
    assert inp.count("xo_Is") == 2

    # Each has the peak type call
    assert "TCHZ_Peak_Type(, inst_U, , inst_V, , inst_W, , inst_Z, , inst_X, , inst_Y)" in inp

    # gauss_fwhm for peak 1
    assert "gauss_fwhm spf1_gauss_fwhm 0.01" in inp

    # No LP_Factor anywhere (A148: LP only in str)
    assert "LP_Factor" not in inp

    # spf1_fwhm = Voigt_FWHM_GL(... present (TCHZ case)
    assert "prm spf1_fwhm = Voigt_FWHM_GL(" in inp


def test_writer_render_xye_drops_zero_weight():
    """render_xye drops zero-weight points and writes sigma = 1/sqrt(w)."""
    from powderline.schema_core import XRDData

    xrd = XRDData(
        tth=[1.0, 2.0, 3.0, 4.0],
        Itth=[100.0, 200.0, 300.0, 400.0],
        Itth_weights=[0.01, 0.0, 0.02, 0.01]
    )
    xye_text, dropped = native_writer.render_xye(xrd)

    assert dropped == 1
    lines = xye_text.strip().split("\n")
    assert len(lines) == 3

    # sigma = 1/sqrt(w): for w=0.01, sigma=10; for w=0.02, sigma=7.071...
    assert "1 100 10" in lines[0] or "1.0 100.0 10.0" in lines[0]
    assert "3" in lines[1] and "300" in lines[1]
    assert "4" in lines[2] and "400" in lines[2]


# ============================================================================
# B. Runner tests (fake runner, no TOPAS)
# ============================================================================


def _fake_topas_runner(results_csv_content, profile_content, peaks_content=None, bkg_profile_content=None):
    """Return a fake runner that writes the specified output files.

    The background run (``<base>_bkg.inp``, A152) writes only its profile:
    ``bkg_profile_content``, else the main profile.
    """
    def runner(cmd, cwd, capture_output=True, **kwargs):
        # cmd is [tc, inp_path]
        inp_path = Path(cmd[1])
        base = inp_path.stem
        out_dir = inp_path.parent
        if base.endswith("_bkg"):
            (out_dir / f"{base}_profile.txt").write_text(
                bkg_profile_content if bkg_profile_content is not None else profile_content,
                encoding="utf-8", newline="\n")
            return MagicMock(returncode=0)

        # Write the files TOPAS would write
        (out_dir / f"{base}_results.csv").write_text(results_csv_content, encoding="utf-8", newline="\n")
        (out_dir / f"{base}_profile.txt").write_text(profile_content, encoding="utf-8", newline="\n")

        if peaks_content:
            for phase_name, content in peaks_content.items():
                # Find the correct filename from the INP
                (out_dir / f"{base}_p1_peaks.txt").write_text(content, encoding="utf-8", newline="\n")

        result = MagicMock()
        result.returncode = 0
        return result
    return runner


def _make_results_csv(params, stats=None):
    """Build a TOPAS results.csv."""
    if stats is None:
        stats = {"r_wp": 8.5, "r_exp": 5.2, "gof": 1.634, "number_independent_parameters": 22}

    lines = ["parameter,value,esd"]
    for k, v in stats.items():
        lines.append(f"{k},{v},")
    for name, (val, esd) in params.items():
        lines.append(f"{name},{val},{esd if esd is not None else ''}")
    return "\n".join(lines) + "\n"


def _make_profile(tth_vals, yobs_vals, ycalc_vals):
    """Build a TOPAS profile.txt (3 columns)."""
    lines = []
    for t, yo, yc in zip(tth_vals, yobs_vals, ycalc_vals):
        lines.append(f"{t} {yo} {yc}")
    return "\n".join(lines) + "\n"


def _make_peak_list():
    """Build a TOPAS peaks.txt (13 columns)."""
    lines = []
    for i in range(5):
        h, k, l = i, 0, 0
        d = 4.0 / (i + 1)
        tth = 2 * math.degrees(math.asin(0.1665 / (2 * d)))
        I_no_scale = 100.0 * (5 - i)
        I_after_scale = I_no_scale * 1e-6
        Iobs = I_after_scale * 1.1
        line = f"{h} {k} {l} 1 {d} {tth} {I_no_scale} {I_after_scale} {Iobs} 0 0 0 0"
        lines.append(line)
    return "\n".join(lines) + "\n"


def test_runner_successful_run(tmp_path, monkeypatch):
    """Successful run: result success True, rwp/gof computed, reports exist."""
    recipe = _rietveld()
    model = schema.validate_recipe(recipe)

    # Build the fake output
    refined_params = {
        "p1_cell_a": (4.1580, 0.0002),
        "p1_a2_x": (0.1995, 0.0003),
        "p1_a1_beq": (8 * math.pi ** 2 * 0.0051, 8 * math.pi ** 2 * 0.0001),
        "p1_a2_beq": (8 * math.pi ** 2 * 0.0061, 8 * math.pi ** 2 * 0.0001),
        "p1_scale": (1.52e-6, 1e-8),
        "p1_cs_l": (305.0, 5.0),
        "ze_th2_offset": (0.002, 0.001),
        "ax_axial_length_mm": (1.05, 0.02),
        "inst_U": (0.00012, 0.00001),
        "inst_V": (-0.00019, 0.00002),
        "inst_W": (0.00031, 0.00001),
        "inst_Z": (0.0001, 0.00005),
        "inst_X": (0.0021, 0.0001),
        "inst_Y": (0.00012, 0.00001),
        "bkg_bkg0__": (10.5, 0.5),
        "bkg_bkg1__": (5.2, 0.3),
        "bkg_bkg2__": (1.1, 0.2),
        "oox": (102.0, 2.0),
        "bkpk1_xo": (3.21, 0.01),
        "bkpk1_I": (51.0, 1.0),
        "bkpk1_pv_fwhm": (0.81, 0.02),
        "bkpk1_pv_lor": (0.51, 0.01),
        "p1_volume": (71.85, 0.01),
    }

    results_csv = _make_results_csv(refined_params)

    # Build profile that matches the data range
    tth = model.payload.xrd_data.tth
    lo, hi = model.payload.window()
    mask = [(t >= lo and t <= hi) for t in tth]
    profile_tth = [t for t, m in zip(tth, mask) if m]
    yobs_vals = [100.0 + 50 * math.sin(t) for t in profile_tth]
    ycalc_vals = [100.0 + 48 * math.sin(t) for t in profile_tth]
    profile = _make_profile(profile_tth, yobs_vals, ycalc_vals)

    peaks = _make_peak_list()

    runner = _fake_topas_runner(results_csv, profile, {"LaB6": peaks})

    # Mock discover_tc_exe to return a fake path
    fake_tc = tmp_path / "TOPAS6" / "tc.exe"
    monkeypatch.setattr("powderline.gateways.topas.native_run.discover_tc_exe", lambda *a, **kw: fake_tc)

    result = native_run.run_native(model, tmp_path, runner=runner)

    assert result["status"] == "ok"
    assert result["method"] == "topas"
    assert result["simulation_mode"] is False
    assert isinstance(result["rwp"], float)
    assert isinstance(result["r_exp"], float)
    assert isinstance(result["gof"], float)
    assert isinstance(result["chi2_red"], float)

    # Check rwp computation
    w = np.array(model.payload.xrd_data.Itth_weights)
    yo = np.array(model.payload.xrd_data.Itth)
    yc_full = np.full_like(yo, np.nan)
    tth_arr = np.array(model.payload.xrd_data.tth)
    for t, yc in zip(profile_tth, ycalc_vals):
        idx = np.searchsorted(tth_arr, t)
        if idx < len(tth_arr) and abs(tth_arr[idx] - t) < 1e-6:
            yc_full[idx] = yc

    mask_arr = np.array(mask) & (w > 0) & np.isfinite(yc_full)
    wm = w[mask_arr]
    yom = yo[mask_arr]
    ycm = yc_full[mask_arr]
    expected_rwp = 100 * math.sqrt(np.sum(wm * (yom - ycm) ** 2) / np.sum(wm * yom ** 2))
    assert result["rwp"] == pytest.approx(expected_rwp, rel=1e-9)

    # Engine details
    assert result["engine_details"]["engine"] == "TOPAS"
    assert result["engine_details"]["engine_version"] == "6"
    assert result["engine_details"]["rwp"] == 8.5
    assert result["engine_details"]["parameters_requested"] == 22
    assert result["engine_details"]["parameters_varied"] == 22

    # Report files exist
    assert (tmp_path / "refined_parameters.csv").exists()
    assert (tmp_path / "fit_profile.txt").exists()
    assert (tmp_path / "LaB6_unit_cell_report.csv").exists()
    assert (tmp_path / "LaB6_peak_list_report.csv").exists()

    # Uiso conversion: refined_parameters has value = beq/(8 pi^2)
    refined_df = result["refined_parameters"]
    uiso_rows = refined_df[refined_df["parameter_name"].str.contains("beq")]
    for _, row in uiso_rows.iterrows():
        if "a1" in row["parameter_name"]:
            expected_uiso = refined_params["p1_a1_beq"][0] / (8 * math.pi ** 2)
            assert abs(row["value"] - expected_uiso) < 1e-6

    # Unit cell report: b = c = a's refined value
    cell_data = result["unit_cell_data"]["LaB6"]
    a_row = cell_data[cell_data["parameter"] == "cell_a"].iloc[0]
    b_row = cell_data[cell_data["parameter"] == "cell_b"].iloc[0]
    c_row = cell_data[cell_data["parameter"] == "cell_c"].iloc[0]
    assert abs(a_row["value"] - 4.1580) < 1e-6
    assert abs(b_row["value"] - 4.1580) < 1e-6
    assert abs(c_row["value"] - 4.1580) < 1e-6
    assert abs(a_row["esd"] - 0.0002) < 1e-6

    # alpha = 90 with esd 0
    alpha_row = cell_data[cell_data["parameter"] == "cell_alpha"].iloc[0]
    assert abs(alpha_row["value"] - 90.0) < 1e-6
    assert alpha_row["esd"] == 0.0

    # Volume from p1_volume
    vol_row = cell_data[cell_data["parameter"] == "cell_volume"].iloc[0]
    assert abs(vol_row["value"] - 71.85) < 1e-6


def test_runner_exit_code_ignored(tmp_path, monkeypatch):
    """Exit code 3221226324 is ignored; run still succeeds."""
    recipe = _rietveld()
    model = schema.validate_recipe(recipe)

    refined_params = {"p1_cell_a": (4.1580, 0.0002), "p1_volume": (71.85, 0.01)}
    results_csv = _make_results_csv(refined_params, {"r_wp": 8.5, "r_exp": 5.2, "gof": 1.6, "number_independent_parameters": 1})

    tth = model.payload.xrd_data.tth
    lo, hi = model.payload.window()
    profile_tth = [t for t in tth if lo <= t <= hi]
    profile = _make_profile(profile_tth, [100.0] * len(profile_tth), [100.0] * len(profile_tth))
    peaks = _make_peak_list()

    def bad_runner(cmd, cwd, capture_output=True, **kwargs):
        inp_path = Path(cmd[1])
        base = inp_path.stem
        out_dir = inp_path.parent
        (out_dir / f"{base}_results.csv").write_text(results_csv, encoding="utf-8", newline="\n")
        (out_dir / f"{base}_profile.txt").write_text(profile, encoding="utf-8", newline="\n")
        (out_dir / f"{base}_p1_peaks.txt").write_text(peaks, encoding="utf-8", newline="\n")
        result = MagicMock()
        result.returncode = 3221226324
        return result

    fake_tc = tmp_path / "TOPAS6" / "tc.exe"
    monkeypatch.setattr("powderline.gateways.topas.native_run.discover_tc_exe", lambda *a, **kw: fake_tc)

    result = native_run.run_native(model, tmp_path, runner=bad_runner)
    assert result["status"] == "ok"


def test_runner_missing_output_error(tmp_path, monkeypatch):
    """Missing output -> EngineExecutionError."""
    recipe = _rietveld()
    model = schema.validate_recipe(recipe)

    def no_output_runner(cmd, cwd, capture_output=True, **kwargs):
        # Write nothing
        result = MagicMock()
        result.returncode = 0
        return result

    fake_tc = tmp_path / "TOPAS6" / "tc.exe"
    monkeypatch.setattr("powderline.gateways.topas.native_run.discover_tc_exe", lambda *a, **kw: fake_tc)

    with pytest.raises(EngineExecutionError, match="stopped without writing") as info:
        native_run.run_native(model, tmp_path, runner=no_output_runner)
    # A195: the failure carries a real envelope -- the files kept for diagnosis and the engine details
    env = info.value.result
    assert env["status"] == "failed" and env["failure"]["reason"] == "output_missing"
    assert sorted(Path(f).suffix for f in env["output_files"]) == [".inp", ".xye"]
    details = env["failure"]["engine_details"]
    assert details["tc_path"] == str(fake_tc) and details["engine_version"] == "6" and details["exit_code"] == 0
    assert env["failure"]["console_tail"] is None and "console window" in str(info.value)


def test_runner_missing_output_keeps_what_tc_printed(tmp_path, monkeypatch):
    """A195: when tc.exe prints something, its tail goes into the failure record and the message says so."""
    model = schema.validate_recipe(_rietveld())

    def chatty_runner(cmd, cwd, capture_output=True, **kwargs):
        return subprocess.CompletedProcess(cmd, 1, stdout=b"TOPAS-64 Version 6\nAtom La+9 not found\n", stderr=b"")

    fake_tc = tmp_path / "TOPAS6" / "tc.exe"
    monkeypatch.setattr("powderline.gateways.topas.native_run.discover_tc_exe", lambda *a, **kw: fake_tc)
    with pytest.raises(EngineExecutionError) as info:
        native_run.run_native(model, tmp_path, runner=chatty_runner)
    assert "Atom La+9 not found" in info.value.result["failure"]["console_tail"]
    assert "console_tail" in str(info.value) and info.value.result["failure"]["engine_details"]["exit_code"] == 1


def test_runner_timeout_is_a_backend_timeout_with_the_input_kept(tmp_path, monkeypatch):
    """A195: tc.exe past its limit -> ExecutionBackendError('timeout'); the INP and data are listed; the limit
    reaches the runner."""
    model = schema.validate_recipe(_rietveld())
    seen = {}

    def hung_runner(cmd, cwd, capture_output=True, **kwargs):
        seen.update(kwargs)
        raise subprocess.TimeoutExpired(cmd, kwargs["timeout"])

    fake_tc = tmp_path / "TOPAS6" / "tc.exe"
    monkeypatch.setattr("powderline.gateways.topas.native_run.discover_tc_exe", lambda *a, **kw: fake_tc)
    with pytest.raises(ExecutionBackendError, match="did not finish") as info:
        native_run.run_native(model, tmp_path, runner=hung_runner, timeout=12.5)
    assert seen == {"timeout": 12.5} and info.value.reason == "timeout"
    assert sorted(Path(f).suffix for f in info.value.result["output_files"]) == [".inp", ".xye"]


def test_runner_without_a_limit_passes_no_timeout(tmp_path, monkeypatch):
    """timeout=None (0 in the option or config) means no limit: the runner gets no timeout keyword."""
    model = schema.validate_recipe(_rietveld())
    seen = []

    def runner(cmd, cwd, capture_output=True, **kwargs):
        seen.append(kwargs)
        return subprocess.CompletedProcess(cmd, 0, stdout=b"", stderr=b"")

    fake_tc = tmp_path / "TOPAS6" / "tc.exe"
    monkeypatch.setattr("powderline.gateways.topas.native_run.discover_tc_exe", lambda *a, **kw: fake_tc)
    with pytest.raises(EngineExecutionError):
        native_run.run_native(model, tmp_path, runner=runner, timeout=None)
    assert seen == [{}]


@pytest.mark.parametrize("option, config, expected", [
    (None, None, 3600.0), (None, 120, 120.0), (30, 120, 30.0), (0, 120, None), (None, 0, None), ("45", None, 45.0)])
def test_configured_timeout(monkeypatch, option, config, expected):
    from powderline.gateways.topas import runner as topas_runner
    monkeypatch.setattr(topas_runner, "_read_topas_config", lambda: {} if config is None else {"timeout": config})
    assert topas_runner.configured_timeout(option) == expected


@pytest.mark.parametrize("bad", [-1, "soon", float("nan"), float("inf")])
def test_configured_timeout_refuses_a_bad_value(monkeypatch, bad):
    from powderline.gateways.topas import runner as topas_runner
    monkeypatch.setattr(topas_runner, "_read_topas_config", lambda: {})
    with pytest.raises(ValueError, match="TOPAS timeout"):
        topas_runner.configured_timeout(bad)


@pytest.mark.parametrize("age", [-7200, 7200])
def test_runner_stale_output_error(tmp_path, monkeypatch, age):
    """Files left by an earlier run never pass for this run's, whatever their timestamps (A154):
    they are removed before TOPAS runs (a share's clock may be ahead of or behind the PC's)."""
    recipe = _rietveld()
    model = schema.validate_recipe(recipe)

    # Pre-create old files
    native = native_run.write_input(model, tmp_path, "test")
    base = "test"
    old_time = os.path.getmtime(tmp_path / f"{base}.inp") + age
    for f in [f"{base}_results.csv", f"{base}_profile.txt", f"{base}_p1_peaks.txt"]:
        (tmp_path / f).write_text("old", encoding="utf-8")
        os.utime(tmp_path / f, (old_time, old_time))

    def no_write_runner(cmd, cwd, capture_output=True, **kwargs):
        # Runner writes nothing (files remain stale)
        result = MagicMock()
        result.returncode = 0
        return result

    fake_tc = tmp_path / "TOPAS6" / "tc.exe"
    monkeypatch.setattr("powderline.gateways.topas.native_run.discover_tc_exe", lambda *a, **kw: fake_tc)

    with pytest.raises(EngineExecutionError, match="stopped without writing"):
        native_run.run_native(model, tmp_path, base_name=base, runner=no_write_runner)


def test_runner_non_finite_ycalc_error(tmp_path, monkeypatch):
    """Non-finite Ycalc in profile -> EngineExecutionError."""
    recipe = _rietveld()
    model = schema.validate_recipe(recipe)

    refined_params = {"p1_cell_a": (4.1580, 0.0002), "p1_volume": (71.85, 0.01)}
    results_csv = _make_results_csv(refined_params, {"r_wp": 8.5, "r_exp": 5.2, "gof": 1.6, "number_independent_parameters": 1})

    tth = model.payload.xrd_data.tth
    lo, hi = model.payload.window()
    profile_tth = [t for t in tth if lo <= t <= hi][:10]
    profile = _make_profile(profile_tth, [100.0] * len(profile_tth), [float("nan")] * len(profile_tth))
    peaks = _make_peak_list()

    runner = _fake_topas_runner(results_csv, profile, {"LaB6": peaks})

    fake_tc = tmp_path / "TOPAS6" / "tc.exe"
    monkeypatch.setattr("powderline.gateways.topas.native_run.discover_tc_exe", lambda *a, **kw: fake_tc)

    with pytest.raises(EngineExecutionError, match="diverged"):
        native_run.run_native(model, tmp_path, runner=runner)


def test_runner_not_varied_warning(tmp_path, monkeypatch):
    """Parameters not varied -> warning topas_parameters_not_varied."""
    recipe = _rietveld()
    model = schema.validate_recipe(recipe)

    refined_params = {"p1_cell_a": (4.1580, 0.0002), "p1_volume": (71.85, 0.01)}
    # number_independent_parameters = 10, but recipe requests 22
    results_csv = _make_results_csv(refined_params, {"r_wp": 8.5, "r_exp": 5.2, "gof": 1.6, "number_independent_parameters": 10})

    tth = model.payload.xrd_data.tth
    lo, hi = model.payload.window()
    profile_tth = [t for t in tth if lo <= t <= hi]
    profile = _make_profile(profile_tth, [100.0] * len(profile_tth), [100.0] * len(profile_tth))
    peaks = _make_peak_list()

    runner = _fake_topas_runner(results_csv, profile, {"LaB6": peaks})

    fake_tc = tmp_path / "TOPAS6" / "tc.exe"
    monkeypatch.setattr("powderline.gateways.topas.native_run.discover_tc_exe", lambda *a, **kw: fake_tc)

    result = native_run.run_native(model, tmp_path, runner=runner)
    warnings = [w for w in result["warnings"] if w["code"] == "topas_parameters_not_varied"]
    assert len(warnings) == 1
    assert "22" in warnings[0]["message"]
    assert "10" in warnings[0]["message"]


def test_runner_limit_hit_warning(tmp_path, monkeypatch):
    """Parameter at limit -> warning topas_parameter_at_limit."""
    recipe = _rietveld()
    model = schema.validate_recipe(recipe)

    # ax_axial_length_mm has default max 50; set final value to exactly 50
    refined_params = {
        "p1_cell_a": (4.1580, 0.0002),
        "ax_axial_length_mm": (50.0, 0.01),
        "p1_volume": (71.85, 0.01)
    }
    results_csv = _make_results_csv(refined_params, {"r_wp": 8.5, "r_exp": 5.2, "gof": 1.6, "number_independent_parameters": 2})

    tth = model.payload.xrd_data.tth
    lo, hi = model.payload.window()
    profile_tth = [t for t in tth if lo <= t <= hi]
    profile = _make_profile(profile_tth, [100.0] * len(profile_tth), [100.0] * len(profile_tth))
    peaks = _make_peak_list()

    runner = _fake_topas_runner(results_csv, profile, {"LaB6": peaks})

    fake_tc = tmp_path / "TOPAS6" / "tc.exe"
    monkeypatch.setattr("powderline.gateways.topas.native_run.discover_tc_exe", lambda *a, **kw: fake_tc)

    result = native_run.run_native(model, tmp_path, runner=runner)
    limit_warnings = [w for w in result["warnings"] if w["code"] == "topas_parameter_at_limit"]
    assert len(limit_warnings) == 1
    assert "Simple_Axial_Model.axial_length_mm" in limit_warnings[0]["field_path"]
    assert "TOPAS's default limit" in limit_warnings[0]["message"]


def test_runner_phase_contributes_nothing_warning(tmp_path, monkeypatch):
    """All I_after_scale_pks zero -> warning topas_phase_contributes_nothing."""
    recipe = _rietveld()
    model = schema.validate_recipe(recipe)

    refined_params = {"p1_cell_a": (4.1580, 0.0002), "p1_scale": (0.0, 0.0), "p1_volume": (71.85, 0.01)}
    results_csv = _make_results_csv(refined_params, {"r_wp": 8.5, "r_exp": 5.2, "gof": 1.6, "number_independent_parameters": 1})

    tth = model.payload.xrd_data.tth
    lo, hi = model.payload.window()
    profile_tth = [t for t in tth if lo <= t <= hi]
    profile = _make_profile(profile_tth, [100.0] * len(profile_tth), [100.0] * len(profile_tth))

    # All I_after_scale zero
    peaks_lines = []
    for i in range(5):
        peaks_lines.append(f"{i} 0 0 1 4.0 10.0 100.0 0.0 0.0 0 0 0 0")
    peaks = "\n".join(peaks_lines) + "\n"

    runner = _fake_topas_runner(results_csv, profile, {"LaB6": peaks})

    fake_tc = tmp_path / "TOPAS6" / "tc.exe"
    monkeypatch.setattr("powderline.gateways.topas.native_run.discover_tc_exe", lambda *a, **kw: fake_tc)

    result = native_run.run_native(model, tmp_path, runner=runner)
    contrib_warnings = [w for w in result["warnings"] if w["code"] == "topas_phase_contributes_nothing"]
    assert len(contrib_warnings) == 1
    assert "LaB6" in contrib_warnings[0]["message"]
    assert contrib_warnings[0]["level"] == "info"  # informative: nothing to act on


def _bkg_case(tmp_path, monkeypatch, recipe=None, bkg_profile=None, write_bkg=True):
    model = schema.validate_recipe(recipe or _rietveld())
    refined = {"p1_cell_a": (4.1580, 0.0002), "bkg_bkg0__": (10.5, 0.1), "p1_volume": (71.85, 0.01)}
    results_csv = _make_results_csv(refined, {"r_wp": 8.5, "r_exp": 5.2, "gof": 1.6,
                                              "number_independent_parameters": 2})
    lo, hi = model.payload.window()
    xs = [t for t in model.payload.xrd_data.tth if lo <= t <= hi]
    profile = _make_profile(xs, [100.0] * len(xs), [100.0] * len(xs))
    calls = []
    inner = _fake_topas_runner(results_csv, profile, {"LaB6": _make_peak_list()},
                               bkg_profile_content=bkg_profile or _make_profile(xs, [100.0] * len(xs),
                                                                                [40.0 + i for i in range(len(xs))]))

    def runner(cmd, cwd, capture_output=True, **kwargs):
        calls.append(Path(cmd[1]).name)
        if Path(cmd[1]).stem.endswith("_bkg") and not write_bkg:
            return MagicMock(returncode=0)
        return inner(cmd, cwd, capture_output)

    monkeypatch.setattr("powderline.gateways.topas.native_run.discover_tc_exe",
                        lambda *a, **kw: tmp_path / "TOPAS6" / "tc.exe")
    return native_run.run_native(model, tmp_path, base_name="run", runner=runner), calls, xs


def test_runner_background_column_from_the_background_run(tmp_path, monkeypatch):
    """A152: a second TOPAS run (background alone, refined values fixed) gives y_bkg."""
    result, calls, xs = _bkg_case(tmp_path, monkeypatch)
    assert calls == ["run.inp", "run_bkg.inp"]
    bkg_inp = (tmp_path / "run_bkg.inp").read_text()
    assert "iters 0" in bkg_inp and "   bkg !bkg 10.5 " in bkg_inp and "str" not in bkg_inp.split()
    assert result["fit_profile"]["y_bkg"].tolist() == [40.0 + i for i in range(len(xs))]
    assert not [w for w in result["warnings"] if w["code"] == "topas_background_not_calculated"]


def test_runner_background_run_missing_leaves_the_column_empty(tmp_path, monkeypatch):
    """No background profile (or a stale one from an earlier run): y_bkg empty + a warning; the fit stands."""
    (tmp_path / "run_bkg_profile.txt").write_text("1 2 3\n", encoding="utf-8")  # stale: removed before the run
    result, calls, _ = _bkg_case(tmp_path, monkeypatch, write_bkg=False)
    assert result["status"] == "ok" and calls == ["run.inp", "run_bkg.inp"]
    assert result["fit_profile"]["y_bkg"].isna().all()
    hits = [w for w in result["warnings"] if w["code"] == "topas_background_not_calculated"]
    assert [w["field_path"] for w in hits] == ["payload.background"]


def test_runner_no_background_modelled_is_zero_and_no_second_run(tmp_path, monkeypatch):
    recipe = _rietveld()
    recipe["payload"].pop("background")
    result, calls, _ = _bkg_case(tmp_path, monkeypatch, recipe=recipe)
    assert calls == ["run.inp"]
    assert (result["fit_profile"]["y_bkg"] == 0).all()


def test_runner_no_tc_exe_generate_only(tmp_path, monkeypatch):
    """No tc.exe -> status "generated", method topas_generate_only, files exist (re/12 D6)."""
    recipe = _rietveld()
    model = schema.validate_recipe(recipe)

    monkeypatch.setattr("powderline.gateways.topas.native_run.discover_tc_exe", lambda *a, **kw: None)

    # Create fake output dir named "output" so default_base_name returns parent name
    out_dir = tmp_path / "output"
    out_dir.mkdir()
    result = native_run.run_native(model, out_dir)

    # re/12 D6: generate-only is a normal outcome, not a failure
    assert result["status"] == "generated" and "success" not in result
    assert result["rwp"] is None and result["converged"] is None
    assert [w["code"] for w in result["warnings"] if w["code"] == "topas_generate_only"] == ["topas_generate_only"]
    note = next(w for w in result["warnings"] if w["code"] == "topas_generate_only")
    assert note["level"] == "info" and "--topas-dir" in note["message"]
    assert result["method"] == "topas_generate_only"
    # default_base_name(output_dir) returns parent.name when output_dir.name == "output"
    base = tmp_path.name
    assert (out_dir / f"{base}.inp").exists()
    assert (out_dir / f"{base}.xye").exists()


def test_runner_validation_warnings_appear_in_result(tmp_path, monkeypatch):
    """topas_adp_converted warnings from validation appear in result."""
    recipe = _rietveld()
    model = schema.validate_recipe(recipe)

    refined_params = {"p1_cell_a": (4.1580, 0.0002), "p1_volume": (71.85, 0.01)}
    results_csv = _make_results_csv(refined_params, {"r_wp": 8.5, "r_exp": 5.2, "gof": 1.6, "number_independent_parameters": 1})

    tth = model.payload.xrd_data.tth
    lo, hi = model.payload.window()
    profile_tth = [t for t in tth if lo <= t <= hi]
    profile = _make_profile(profile_tth, [100.0] * len(profile_tth), [100.0] * len(profile_tth))
    peaks = _make_peak_list()

    runner = _fake_topas_runner(results_csv, profile, {"LaB6": peaks})

    fake_tc = tmp_path / "TOPAS6" / "tc.exe"
    monkeypatch.setattr("powderline.gateways.topas.native_run.discover_tc_exe", lambda *a, **kw: fake_tc)

    result = native_run.run_native(model, tmp_path, runner=runner)

    adp_warnings = [w for w in result["warnings"] if w["code"] == "topas_adp_converted"]
    assert len(adp_warnings) == 2  # La1 and B1


# ============================================================================
# C. Gateway tests
# ============================================================================


def test_gateway_validate_native_dict():
    """gateway.validate on a native dict returns TopasRietveldRecipe."""
    result = gateway.validate(_rietveld())
    assert isinstance(result, schema.TopasRietveldRecipe)


def test_gateway_capabilities():
    """capabilities() includes topas.rietveld, topas.spf, supported_engine_versions==6."""
    caps = gateway.capabilities()
    assert "topas.rietveld" in caps["workflows"]
    assert "topas.spf" in caps["workflows"]
    assert caps["supported_engine_versions"] == "==6"


def test_gateway_check_native_engine_version_no_declared(monkeypatch):
    """No declared version -> EngineVersionError."""
    monkeypatch.setattr("powderline.gateways.topas.runner._read_topas_config", lambda: {})
    model = schema.validate_recipe(_rietveld())

    with pytest.raises(EngineVersionError, match="not declared"):
        gateway.check_native_engine_version(model)


def test_gateway_check_native_engine_version_wrong(monkeypatch):
    """Declared version 7 -> EngineVersionError."""
    monkeypatch.setattr("powderline.gateways.topas.runner._read_topas_config", lambda: {"version": "7"})
    model = schema.validate_recipe(_rietveld())

    with pytest.raises(EngineVersionError):
        gateway.check_native_engine_version(model, topas_version="7")


def test_gateway_check_native_engine_version_matches():
    """Declared version 6 -> passes."""
    model = schema.validate_recipe(_rietveld())
    gateway.check_native_engine_version(model, topas_version="6")

    # Also "6.0" should work
    gateway.check_native_engine_version(model, topas_version="6.0")


def test_gateway_check_native_engine_version_allow_unsupported():
    """allow_unsupported=True skips the check."""
    model = schema.validate_recipe(_rietveld())
    gateway.check_native_engine_version(model, topas_version="7", allow_unsupported=True)


def test_gateway_run_validate_only(tmp_path):
    """gateway.run(native_dict, tmp, validate_only=True) returns method validate_only."""
    from powderline.registry import VALIDATE_ONLY_KEYS
    result = gateway.run(_rietveld(), tmp_path, validate_only=True)

    assert result["method"] == "validate_only"
    assert result["simulation_mode"] is False
    assert "warnings" in result
    # the uniform summary (P-28): the TOPAS items under "engine", core_schema_version present
    assert tuple(result) == VALIDATE_ONLY_KEYS
    assert result["core_schema_version"] == "0.1.0"
    assert result["engine"] == {"iters": _rietveld()["payload"]["refinement_controls"]["iters"], "engine_version": "6"}
    assert "iters" not in result and "engine_version" not in result
    from powderline.schema_core import parameters_requested
    spf = gateway.run(_spf(), tmp_path, validate_only=True)
    assert spf["phases"] == 0  # a peak-fit workflow
    assert spf["parameters_requested"] == parameters_requested(schema.validate_recipe(_spf())) >= 6  # 2 peaks + zero


def test_runner_stated_limit_hit_named_stated(tmp_path, monkeypatch):
    """A refined value ending at its stated bound is reported as the stated limit (A147 Q-L4)."""
    model = schema.validate_recipe(_rietveld())  # B1 x refined with stated bounds [0.15, 0.25]
    refined_params = {"p1_cell_a": (4.1580, 0.0002), "p1_a2_x": (0.25, 0.001), "p1_volume": (71.85, 0.01)}
    results_csv = _make_results_csv(refined_params, {"r_wp": 8.5, "r_exp": 5.2, "gof": 1.6,
                                                     "number_independent_parameters": 2})
    lo, hi = model.payload.window()
    profile_tth = [t for t in model.payload.xrd_data.tth if lo <= t <= hi]
    profile = _make_profile(profile_tth, [100.0] * len(profile_tth), [100.0] * len(profile_tth))
    runner = _fake_topas_runner(results_csv, profile, {"LaB6": _make_peak_list()})
    monkeypatch.setattr("powderline.gateways.topas.native_run.discover_tc_exe",
                        lambda *a, **kw: tmp_path / "TOPAS6" / "tc.exe")
    result = native_run.run_native(model, tmp_path, runner=runner)
    hits = [w for w in result["warnings"] if w["code"] == "topas_parameter_at_limit"]
    assert [w["field_path"] for w in hits] == ["payload.phases.LaB6.atoms.B1.x"]
    assert "the recipe's stated bound" in hits[0]["message"]


def test_writer_exports_cell_volume():
    """The cell volume is written out although it is not refined (pack 2: the volume was missing)."""
    native = native_writer.render_native(schema.validate_recipe(_rietveld()), "test")
    assert "prm p1_volume = Get(cell_volume); : 0" in native.inp_text
    assert 'out_record out_eqn = p1_volume; out_fmt "p1_volume,%.12g,' in native.inp_text


def test_runner_profile_x_rounded_above_the_recipe_value(tmp_path, monkeypatch):
    """TOPAS prints X to 10 significant digits; a value rounded up still matches its own point (pack 2)."""
    model = schema.validate_recipe(_rietveld())
    results_csv = _make_results_csv({"p1_cell_a": (4.1580, 0.0002), "p1_volume": (71.85, 0.01)},
                                    {"r_wp": 8.5, "r_exp": 5.2, "gof": 1.6, "number_independent_parameters": 1})
    lo, hi = model.payload.window()
    tth = np.asarray(model.payload.xrd_data.tth, dtype=float)
    w = np.asarray(model.payload.xrd_data.Itth_weights, dtype=float)
    inside = tth[(tth >= lo) & (tth <= hi)]
    printed = inside * (1 + 3e-10)  # every X above its recipe value
    yobs = [100.0] * len(printed)
    ycalc = [100.0 + i % 7 for i in range(len(printed))]
    runner = _fake_topas_runner(results_csv, _make_profile(printed, yobs, ycalc),
                                {"LaB6": _make_peak_list()})
    monkeypatch.setattr("powderline.gateways.topas.native_run.discover_tc_exe",
                        lambda *a, **kw: tmp_path / "TOPAS6" / "tc.exe")
    result = native_run.run_native(model, tmp_path, runner=runner)

    yo = np.asarray(model.payload.xrd_data.Itth, dtype=float)
    m = (tth >= lo) & (tth <= hi)
    expected = 100 * math.sqrt(np.sum(w[m] * (yo[m] - np.array(ycalc)) ** 2) / np.sum(w[m] * yo[m] ** 2))
    assert result["rwp"] == pytest.approx(expected, rel=1e-12)
    assert result["fit_profile"]["y_weights"].tolist() == w[m].tolist()


def test_writer_fit_limits_on_data_points():
    """start_X/finish_X are the first/last data points inside fit_range, written as in the .xye (A149, EB-59)."""
    recipe = json.loads((Path(__file__).parent / "data" / "topas" / "native" / "lab6_rietveld.json").read_text())
    native = native_writer.render_native(schema.validate_recipe(recipe), "test")
    assert "   start_X 1.000355998\n   finish_X 14.99760389\n" in native.inp_text
    xs = [line.split()[0] for line in native.xye_text.splitlines()]
    assert "1.000355998" in xs and "14.99760389" in xs


def test_render_background_run():
    """A152: same data/window/corrections/background, refined values fixed, no phases or SPF peaks, iters 0."""
    recipe = json.loads((Path(__file__).parent / "data" / "topas" / "native" / "lab6_corrections.json").read_text())
    model = schema.validate_recipe(recipe)
    main = native_writer.render_native(model, "run")
    values = {"bkg_bkg0__": -746.49, "oox": 0.000161, "bkpk1_h1": 211.48, "ze_th2_offset": 0.0025,
              "p1_scale": 1.8e-8}
    bkg = native_writer.render_background(model, "run", values)
    text = bkg.inp_text
    assert 'xdd "run.xye" xye_format' in text and bkg.profile_file == "run_bkg_profile.txt"
    assert "iters 0" in text and "do_errors" not in text
    assert "str" not in text.split() and "phase_name" not in text and '\nout "' not in text
    assert "   bkg !bkg -746.49 " in text  # refined value fixed; the rest as stated
    assert "prm !oox 0.000161" in text and "prm !ze_th2_offset 0.0025" in text
    assert "h1 !bkpk1_h1 211.48" in text and "ZE(, ze_th2_offset)" in text and "Simple_Axial_Model(" in text
    for line in ("   start_X 1.000355998", "   finish_X 14.99760389", "   Rs 217.5", "      capillary_parallel_beam"):
        assert line in main.inp_text.splitlines() and line in text.splitlines()
    assert native_writer.has_background(model)


def test_render_background_spf_has_no_peaks():
    recipe = json.loads((Path(__file__).parent / "data" / "topas" / "native" / "lab6_spf.json").read_text())
    text = native_writer.render_background(schema.validate_recipe(recipe), "s", {}).inp_text
    assert "xo_Is" not in text and "spf1_" not in text and "bkg !bkg" in text


def test_writer_open_ends_are_the_weighted_data_limits():
    """A154: without fit_range the INP still states start_X/finish_X, the first/last weighted points (zero-weight
    edge points are not in the .xye), so TOPAS's Chebyshev basis spans the same points as GSAS-II's."""
    recipe = _rietveld()
    recipe["payload"].pop("fit_range", None)
    w = recipe["payload"]["xrd_data"]["Itth_weights"]
    for i in (0, 1, len(w) - 1):
        w[i] = 0.0
    tth = recipe["payload"]["xrd_data"]["tth"]
    model = schema.validate_recipe(recipe)
    native = native_writer.render_native(model, "x")
    assert f"   start_X {fmt(tth[2])}\n   finish_X {fmt(tth[-2])}\n" in native.inp_text
    assert native.dropped_points == 3


# ============================================================================
# I. Peak-list parsing (peak_list.py; moved from test_topas_roundtrip, re/07 H)
# ============================================================================


def test_parse_peak_list_derives_f_obs_and_f_calc():
    # 13 cols: H K L M d 2theta I_no I_after Iobs A01 B01 A11 B11
    # F_calc^2 = A01^2+B01^2+A11^2+B11^2; F_obs^2 = F_calc^2 * Iobs/I_no
    text = " 1 0 0 6 4.15682 2.29512 0.0010494 0.0010494 0.0010491 37.405 0 0 0\n"
    (row,) = peak_list.parse_peak_list(text, "LaB6")
    assert row["F_calc_squared"] == pytest.approx(37.405**2, rel=1e-6)
    # F_calc^2 ~ GSAS-II F_calc_squared(100) = 1395.2 (different engine, ~0.3%)
    assert row["F_calc_squared"] == pytest.approx(1395.2, rel=0.01)
    assert row["F_obs_squared"] == pytest.approx(37.405**2 * (0.0010491 / 0.0010494), rel=1e-6)
    assert row["phase"] == "LaB6"


def test_f_obs_zero_when_i_no_scale_nonpositive():
    text = " 1 0 0 6 4.1 2.3 0 0.001 0.5 10 0 0 0\n"  # I_no_scale_pks = 0
    (row,) = peak_list.parse_peak_list(text, "P")
    assert row["F_obs_squared"] == 0.0
    assert row["F_calc_squared"] == pytest.approx(100.0)


def test_parse_peak_list_skips_garbage_rows():
    # a stray header/short line is skipped, not fatal
    assert len(peak_list.parse_peak_list("oops\n1 0 0 6 4.1 2.3 1 1 1 5 0 0 0\n", "P")) == 1


def test_parse_peak_list_golden_row():
    """The first LaB6 reflection TOPAS 6 wrote (golden ``_p1_peaks.txt``): F_calc^2 and F_obs^2 as derived."""
    golden = Path(__file__).parent / "data" / "topas" / "native" / "golden" / "lab6_rietveld__snapped_p1_peaks.txt"
    row = peak_list.parse_peak_list(golden.read_text(encoding="utf-8"), "LaB6")[0]
    assert (row["h"], row["k"], row["l"], row["multiplicity"]) == (1, 0, 0, 6)
    assert row["d_spacing"] == pytest.approx(4.15682)
    assert row["F_calc_squared"] == pytest.approx(37.40517764**2, rel=1e-9)
    assert row["F_obs_squared"] == pytest.approx(37.40517764**2 * 0.02053270198 / 0.02213020061, rel=1e-9)


# ============================================================================
# J. Package guards (moved from test_topas_writer, re/07 H): zero GSAS-II
# ============================================================================


def test_topas_package_has_no_gsasii_imports():
    import powderline.gateways.topas as topas_pkg

    pkg_dir = Path(topas_pkg.__file__).parent
    offenders = []
    for src in pkg_dir.glob("*.py"):
        text = src.read_text()
        if re.search(r"\bimport\s+GSASII|\bfrom\s+GSASII", text):
            offenders.append(src.name)
    assert not offenders, f"GSAS-II imports found in TOPAS package: {offenders}"


def test_topas_import_does_not_load_gsasii():
    # The TOPAS path must work with GSAS-II *unavailable* (the Windows scenario).
    # Run in a fresh subprocess that blocks the GSASII import so this holds even
    # when GSAS-II is installed in the dev env (Linux regression dependency).
    import textwrap

    script = textwrap.dedent(
        """
        import sys, importlib.abc, importlib.machinery

        class _Block(importlib.abc.MetaPathFinder):
            def find_spec(self, name, path, target=None):
                if name == "GSASII" or name.startswith("GSASII."):
                    raise ImportError("GSASII blocked for the TOPAS-path guard test")
                return None

        sys.meta_path.insert(0, _Block())
        import powderline               # imports no engine
        import powderline.gateways.topas
        import powderline.gateways.topas.native_writer
        import powderline.gateways.topas.native_run
        import powderline.gateways.topas.gateway
        assert "GSASII" not in sys.modules, "TOPAS path pulled GSAS-II into sys.modules"
        print("OK")
        """
    )
    proc = run_subprocess_utf8([sys.executable, "-c", script], capture_output=True, text=True)
    assert proc.returncode == 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    assert "OK" in proc.stdout


# ============================================================================
# K. Cross-engine result contract (moved from test_topas_engine, re/07 H)
# ============================================================================

#: run() dict keys and types locked by tests/test_api.py for GSAS-II; every engine returns them.
_GSASII_CONTRACT = {
    "run_id": str,
    "rwp": (float, type(None)),
    "elapsed_time": float,
    "method": str,
    "output_files": list,
    "fit_profile": pd.DataFrame,
    "unit_cell_data": dict,
    "peak_list_data": dict,
    "refined_parameters": pd.DataFrame,
    "spf_peaks": pd.DataFrame,
    "spf_convergence_diagnostics": pd.DataFrame,
    # re/12: the envelope fields; the pre-0.2.0 error/traceback keys are gone (a failure raises)
    "status": str,
    "converged": (bool, type(None)),
    "envelope_version": str,
    # re/20a (KI-04): the output recipe (None only where a gateway cannot build it yet) and the dispositions
    "output_recipe": (dict, type(None)),
    "output_recipe_valid": bool,
    "parameter_dispositions": pd.DataFrame,
}


def test_native_result_matches_gsasii_key_and_type_contract(tmp_path, monkeypatch):
    """A native TOPAS success dict carries every GSAS-II key with the matching type."""
    model = schema.validate_recipe(_rietveld())
    refined_params = {"p1_cell_a": (4.1580, 0.0002), "p1_a2_x": (0.1995, 0.0003), "p1_volume": (71.85, 0.01)}
    tth = model.payload.xrd_data.tth
    lo, hi = model.payload.window()
    profile_tth = [t for t in tth if lo <= t <= hi]
    profile = _make_profile(profile_tth, [100.0 + 50 * math.sin(t) for t in profile_tth],
                            [100.0 + 48 * math.sin(t) for t in profile_tth])
    runner = _fake_topas_runner(_make_results_csv(refined_params), profile, {"LaB6": _make_peak_list()})
    monkeypatch.setattr("powderline.gateways.topas.native_run.discover_tc_exe",
                        lambda *a, **kw: tmp_path / "TOPAS6" / "tc.exe")

    result = native_run.run_native(model, tmp_path, runner=runner)

    assert result["status"] == "ok"
    for key, expected_type in _GSASII_CONTRACT.items():
        assert key in result, f"missing GSAS-II contract key {key!r}"
        assert isinstance(result[key], expected_type), (
            f"{key!r} is {type(result[key]).__name__}, expected "
            f"{getattr(expected_type, '__name__', expected_type)}"
        )
    # dict-of-DataFrame values carry DataFrames (GSAS-II per-phase contract)
    for phase_frame in result["unit_cell_data"].values():
        assert isinstance(phase_frame, pd.DataFrame)
    for phase_frame in result["peak_list_data"].values():
        assert isinstance(phase_frame, pd.DataFrame)
    # the 9 refined_parameters columns of the GSAS-II path
    assert set(result["refined_parameters"].columns) == {
        "parameter_name", "descriptive_name", "phase_name", "phase_idx",
        "atom_name", "atom_idx", "value", "esd", "category",
    }
    # empty SPF frames match GSAS-II's column-less pd.DataFrame() for a Rietveld recipe
    assert result["spf_peaks"].empty and list(result["spf_peaks"].columns) == []
    assert list(result["spf_convergence_diagnostics"].columns) == []


# ============================================================================
# P-04 (A154 N7, N10) — reporting-only additions after the G2 review of re/07 (S1)
# ============================================================================


def _spf_run(tmp_path, monkeypatch, xo_values, **kwargs):
    """Run the SPF fixture against a crafted results file; return (model, result)."""
    model = schema.validate_recipe(_spf())
    refined = {"spf1_xo": (xo_values[0], 0.001), "spf1_I": (10.0, 0.1), "spf1_gauss_fwhm": (0.01, 0.001),
               "spf2_xo": (xo_values[1], 0.001), "spf2_I": (5.0, 0.1), "ze_th2_offset": (0.0, 0.001)}
    results_csv = _make_results_csv(refined, {"r_wp": 8.5, "r_exp": 5.2, "gof": 1.6,
                                              "number_independent_parameters": len(refined)})
    lo, hi = model.payload.window()
    profile_tth = [t for t in model.payload.xrd_data.tth if lo <= t <= hi]
    profile = _make_profile(profile_tth, [100.0] * len(profile_tth), [100.0] * len(profile_tth))
    monkeypatch.setattr("powderline.gateways.topas.native_run.discover_tc_exe",
                        lambda *a, **kw: tmp_path / "TOPAS6" / "tc.exe")
    return model, native_run.run_native(model, tmp_path, runner=_fake_topas_runner(results_csv, profile), **kwargs)


def test_writer_spf_xo_gets_the_window_as_reporting_limit():
    """A154 N7 (P-04): an SPF peak position without a stated bound records (start_X, finish_X) as its limits with
    source "window"; the INP token is unchanged (no min/max emitted)."""
    from powderline.schema_core import fit_limits_on_data
    model = schema.validate_recipe(_spf())
    native = native_writer.render_native(model, "test")
    start, finish = fit_limits_on_data(model.payload.fit_range, model.payload.xrd_data)  # = start_X, finish_X
    for name in ("spf1_xo", "spf2_xo"):
        assert native.params[name].limits == (start, finish)
        assert native.params[name].limit_source == ("window", "window")
    xo_lines = [ln for ln in native.inp_text.splitlines() if "xo spf1_xo" in ln or "xo spf2_xo" in ln]
    assert len(xo_lines) == 2 and all("min" not in ln and "max" not in ln for ln in xo_lines), xo_lines
    assert f"start_X {native_writer.fmt(start)}" in native.inp_text  # the source of the recorded limits
    # a stated bound keeps its own source; the other side is the window's
    recipe = _spf()
    recipe["payload"]["single_peaks"][0]["xo"] = P(5.0, True, 4.0, None)
    native = native_writer.render_native(schema.validate_recipe(recipe), "test")
    assert native.params["spf1_xo"].limits == (4.0, finish)
    assert native.params["spf1_xo"].limit_source == ("stated", "window")
    assert native.params["spf1_I"].limit_source[1] is None  # only xo gets the window


@pytest.mark.parametrize("edge", ["min", "max"])
def test_runner_spf_xo_on_window_edge_is_a_limit_hit_with_window_source(tmp_path, monkeypatch, edge):
    """A154 N7 (P-04): a peak position ending on start_X / finish_X is reported as topas_parameter_at_limit naming
    the window edge, and the peak enters spf_convergence_diagnostics as at_limit."""
    start, finish = schema.validate_recipe(_spf()).payload.window()
    at_edge = start if edge == "min" else finish
    _, result = _spf_run(tmp_path, monkeypatch, (at_edge, 7.0))
    hits = [w for w in result["warnings"] if w["code"] == "topas_parameter_at_limit"]
    assert len(hits) == 1
    assert hits[0]["field_path"] == "payload.single_peaks.0.xo"
    assert f"fit window's {edge} edge" in hits[0]["message"]
    assert ("start_X" if edge == "min" else "finish_X") in hits[0]["message"]
    diag = result["spf_convergence_diagnostics"]
    assert list(diag["peak_index"]) == [0] and list(diag["status"]) == ["at_limit"]
    assert "fit window" in diag["notes"].iloc[0]


def test_runner_spf_xo_beyond_window_edge_is_a_limit_hit(tmp_path, monkeypatch):
    """A154 N7: unlike a TOPAS limit, the window edge can be crossed; a peak that left the window is flagged too,
    and one that stayed inside is not."""
    start, finish = schema.validate_recipe(_spf()).payload.window()
    _, result = _spf_run(tmp_path, monkeypatch, (start - 0.5, finish + 0.25))
    hits = sorted(w["field_path"] for w in result["warnings"] if w["code"] == "topas_parameter_at_limit")
    assert hits == ["payload.single_peaks.0.xo", "payload.single_peaks.1.xo"]
    _, result = _spf_run(tmp_path, monkeypatch, (5.0, 7.0))
    assert not [w for w in result["warnings"] if w["code"] == "topas_parameter_at_limit"]
    assert result["spf_convergence_diagnostics"].empty


def test_safe_base_name():
    """A154 N10 (P-04): ASCII base names pass through; anything else becomes 'topas' with a structured warning."""
    assert native_run.safe_base_name("example_LaB6") == ("example_LaB6", None)
    base, warning = native_run.safe_base_name("Ünïcødé")
    assert base == "topas"
    assert warning["code"] == "topas_base_name_sanitized" and warning["field_path"] is None
    assert "Ünïcødé" in warning["message"] and "topas.*" in warning["message"]


def test_runner_non_ascii_base_name_is_sanitized(tmp_path, monkeypatch):
    """A154 N10 (P-04): a non-ASCII base name (here derived from examples/<name>/output) writes topas.* files,
    the result carries topas_base_name_sanitized once, and the INP equals the one rendered for base 'topas'."""
    model = schema.validate_recipe(_rietveld())
    out = tmp_path / "Ünïcødé" / "output"
    out.mkdir(parents=True)
    assert native_run.default_base_name(out) == "Ünïcødé"

    # generate-only (no tc.exe)
    monkeypatch.setattr("powderline.gateways.topas.native_run.discover_tc_exe", lambda *a, **kw: None)
    result = native_run.run_native(model, out)
    assert result["method"] == "topas_generate_only"
    assert (out / "topas.inp").is_file() and (out / "topas.xye").is_file()
    assert not [p for p in out.iterdir() if not p.name.isascii()]
    assert [w["code"] for w in result["warnings"]].count("topas_base_name_sanitized") == 1
    assert (out / "topas.inp").read_text(encoding="utf-8") == native_writer.render_native(model, "topas").inp_text

    # a full (fake) run reads its results back from the topas_* files
    refined = {"p1_cell_a": (4.1580, 0.0002), "p1_volume": (71.85, 0.01)}
    results_csv = _make_results_csv(refined, {"r_wp": 8.5, "r_exp": 5.2, "gof": 1.6, "number_independent_parameters": 1})
    lo, hi = model.payload.window()
    profile_tth = [t for t in model.payload.xrd_data.tth if lo <= t <= hi]
    profile = _make_profile(profile_tth, [100.0] * len(profile_tth), [100.0] * len(profile_tth))
    monkeypatch.setattr("powderline.gateways.topas.native_run.discover_tc_exe",
                        lambda *a, **kw: tmp_path / "TOPAS6" / "tc.exe")
    result = native_run.run_native(model, out, base_name="Ünïcødé",
                                   runner=_fake_topas_runner(results_csv, profile, {"LaB6": _make_peak_list()}))
    assert result["status"] == "ok"
    assert (out / "topas_results.csv").is_file()
    assert [w["code"] for w in result["warnings"]].count("topas_base_name_sanitized") == 1
    # an ASCII name is untouched and raises no warning
    result = native_run.run_native(model, tmp_path / "plain", base_name="example_LaB6",
                                   runner=_fake_topas_runner(results_csv, profile, {"LaB6": _make_peak_list()}))
    assert (tmp_path / "plain" / "example_LaB6.inp").is_file()
    assert "topas_base_name_sanitized" not in [w["code"] for w in result["warnings"]]


def test_run_native_records_the_executable_that_ran(tmp_path, monkeypatch):
    """P-35: a real run states which tc.exe ran (engine_details.tc_path), so the provenance is explicit."""
    import json as _json
    from powderline.gateways.topas.schema import validate_recipe as _validate
    model = _validate(_json.loads((Path(__file__).parent / "data" / "topas" / "native" / "lab6_rietveld.json")
                                  .read_text(encoding="utf-8")))
    tth = model.payload.xrd_data.tth
    lo, hi = model.payload.window()
    profile_tth = [t for t in tth if lo <= t <= hi]
    profile = _make_profile(profile_tth, [100.0] * len(profile_tth), [99.0] * len(profile_tth))
    runner = _fake_topas_runner(_make_results_csv({}), profile, {"LaB6": _make_peak_list()})
    fake_tc = tmp_path / "declared" / "tc.exe"
    monkeypatch.setattr("powderline.gateways.topas.native_run.discover_tc_exe", lambda *a, **kw: fake_tc)
    result = native_run.run_native(model, tmp_path, runner=runner)
    assert result["status"] == "ok"
    assert result["engine_details"]["tc_path"] == str(fake_tc)


# --- re/12: reasons on every TOPAS failure; engine errors wrapped --------------------------------------

def test_missing_results_file_is_output_missing(tmp_path, monkeypatch):
    model = schema.validate_recipe(_rietveld())
    fake_tc = tmp_path / "declared" / "tc.exe"
    monkeypatch.setattr("powderline.gateways.topas.native_run.discover_tc_exe", lambda *a, **kw: fake_tc)
    with pytest.raises(EngineExecutionError) as e:
        native_run.run_native(model, tmp_path, runner=lambda *a, **k: None)  # writes nothing
    assert e.value.reason == "output_missing"


def test_ragged_profile_row_is_output_malformed(tmp_path):
    p = tmp_path / "x_profile.txt"
    p.write_text("1.0 100.0 99.0\n1.1 100.0\n", encoding="utf-8")
    with pytest.raises(EngineExecutionError) as e:
        native_run._read_profile(p)
    assert e.value.reason == "output_malformed" and "x_profile.txt" in str(e.value)


def test_non_numeric_token_is_output_malformed():
    with pytest.raises(EngineExecutionError) as e:
        native_run._topas_float("abc", "f.txt")
    assert e.value.reason == "output_malformed"


def test_tc_launch_failure_is_engine_crashed(tmp_path, monkeypatch):
    model = schema.validate_recipe(_rietveld())
    fake_tc = tmp_path / "declared" / "tc.exe"
    monkeypatch.setattr("powderline.gateways.topas.native_run.discover_tc_exe", lambda *a, **kw: fake_tc)

    def cannot_start(*a, **k):
        raise PermissionError("tc.exe is not executable")
    with pytest.raises(EngineExecutionError) as e:
        native_run.run_native(model, tmp_path, runner=cannot_start)
    assert e.value.reason == "engine_crashed" and "not executable" in str(e.value)


def test_divergence_reason_is_diverged():
    with pytest.raises(EngineExecutionError) as e:
        raise native_run._diverged("the pattern")
    assert e.value.reason == "diverged"


# --- fmt: byte-stable number formatting (moved here from the deleted conversions module, re/17) ---

from powderline.gateways.topas.native_writer import fmt  # noqa: E402


@pytest.mark.parametrize(
    "value,expected",
    [
        (90.0, "90"),
        (4.15682, "4.15682"),
        (-0.0, "0"),
        (0.0, "0"),
        (0.001, "0.001"),
        (1.0, "1"),
        (109.96, "109.96"),
    ],
)
def test_fmt(value, expected):
    assert fmt(value) == expected


def test_fmt_is_deterministic_and_roundtrips():
    for v in (0.677449, 4.1813, 1e-05, 18.71740850558368):
        assert fmt(v) == fmt(v)
        assert float(fmt(v)) == pytest.approx(v, rel=1e-9)


def test_generated_result_carries_the_resolved_input(tmp_path, monkeypatch):
    """re/20a: without tc.exe the output recipe is the resolved input; flagged parameters were not varied."""
    recipe = _rietveld()
    model = schema.validate_recipe(recipe)
    monkeypatch.setattr("powderline.gateways.topas.native_run.discover_tc_exe", lambda *a, **kw: None)
    out_dir = tmp_path / "output"
    out_dir.mkdir()
    result = native_run.run_native(model, out_dir)
    assert result["status"] == "generated" and result["output_recipe_valid"] is True
    assert result["output_recipe"]["payload"]["xrd_data"] == model.model_dump(mode="json")["payload"]["xrd_data"]
    rows = result["parameter_dispositions"]
    assert set(rows[rows["disposition"] == "varied"]["path"]) == set()
    from powderline.roundtrip import parameter_paths
    flagged = {pp.path for pp in parameter_paths(model) if pp.refine_flag and pp.tie not in ("member", "fixed")}
    assert set(rows[rows["disposition"] == "requested_not_varied"]["path"]) == flagged
    assert (out_dir / "output_recipe.json").exists() and str(out_dir / "output_recipe.json") in result["output_files"]
    # the INP written from the output recipe is byte-identical to the one written from the input
    again = schema.validate_recipe(result["output_recipe"])
    from powderline.gateways.topas import native_writer
    assert native_writer.render_native(again, "x").inp_text == native_writer.render_native(model, "x").inp_text
