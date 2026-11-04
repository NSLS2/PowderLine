"""TOPAS INP writer for native ``topas.rietveld`` / ``topas.spf`` recipes (re/05; draft rev 3, A138-A148).

Pure: a validated model in, INP and ``.xye`` text out (no I/O, no TOPAS). Every
value comes from the validated model, never from recipe text (A39, A115,
A121).

Emission rules:

- **One TOPAS parameter per symmetry tie group (A94):** the group's first
  member carries the parameter; other members are equations from core's exact
  affine relations (``b = Get(a);``, ``y = -p1_a3_x + 1/2;``,
  ``u12 = p1_a3_u22/2;``); symmetry-fixed values are constants, ``= 1/3;``
  where no exact decimal exists (EB-08). Identical to constants on TOPAS 6 (C25).
- **Names are index-based** (``p1_a3_x``, ``inst_U``, ``bkpk2_xo``; D9), so
  phase and atom names can never compose into one another (EB-49).
- **Bounds (A138):** keyword parameters (cell, scale, sites, ``lam``, peaks)
  carry only the stated sides; TOPAS keeps its own default on the other side
  (C20). Macro parameters (peak type, LP, ``One_on_X``, ``Zero_Error``,
  ``Simple_Axial_Model``, CS/Strain) are declared as ``prm`` with explicit
  limits, stated or TOPAS.INC's own expression per side, and passed to the
  macro by name (``CV(c, v)`` takes ``v`` when ``c`` is blank), so their
  limits are exactly the stated or the default ones. The macro's ``del``
  (derivative step) is kept even when a bound is stated, where TOPAS.INC's
  3-argument ``If_Prm_Eqn_Rpt`` would drop it, and ZE's ``val_on_continue``
  (used only with ``continue_after_convergence``) is not written.
- **Numbers** are written with ``%.10g`` (``fmt``): recipe values beyond 10
  significant digits are rounded in the INP, like the ``.xye``.
- **Ions and texture:** an atom listed in the phase's ``scattering_types`` gets
  TOPAS's spelling in ``occ`` (``La3+`` -> ``occ La+3``, :mod:`.scattering`);
  ``preferred_orientation`` is TOPAS.INC's ``PO`` macro in the ``str``.
- **Scope (A148):** geometry corrections at the xdd level (every peak);
  Lorentz-polarisation and the instrument peak type in each ``str``; the
  instrument peak type also in each SPF peak.
- **Outputs:** a results CSV (TOPAS's R values, the independent-parameter
  count, every refined parameter and derived value with its ESD), the profile
  (X, Yobs, Ycalc; no ``Get(bkg)``, which is 0 on TOPAS 6, C17), and one
  ``phase_out`` reflection list per phase.
- **Background run (A152):** TOPAS 6 cannot output the background (C17, C34),
  so :func:`render_background` writes a second INP: the same data, window,
  corrections, emission and background, every parameter fixed at its refined
  value, no ``str`` phases or SPF peaks, ``iters 0``. Its Ycalc is the
  background with every convolution TOPAS applies.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Optional

from powderline.gateways.topas.scattering import topas_type
from powderline.gateways.topas.schema import (
    EIGHT_PI_SQ,
    KEYWORD_LIMITS,
    PEAK_TYPES,
    TopasRietveldRecipe,
    TopasSpfRecipe,
    topas_space_group,
)
from powderline.schema_core import BoundedRefinableParameter, fit_limits_on_data
from powderline.symmetry import analyze_site, cell_tie_groups, coupling_groups

P = BoundedRefinableParameter


def fmt(value: float) -> str:
    """Format a float for byte-stable INP output (``%.10g``, no exponent noise).

    Integral floats render without a trailing ``.0`` (matches the recipe's own
    ``a 4.15682`` / ``al 90`` style). ``-0.0`` normalises to ``0``.

    >>> fmt(90.0)
    '90'
    >>> fmt(4.15682)
    '4.15682'
    >>> fmt(-0.0)
    '0'
    """
    v = float(value)
    if v == 0.0:
        v = 0.0  # collapse -0.0
    return "%.10g" % v

RESULTS_SUFFIX = "_results.csv"
PROFILE_SUFFIX = "_profile.txt"
CHEBYSHEV_NAME = "bkg"  # TOPAS names the coefficients bkg_bkg0__, bkg_bkg1__, ...

_ANGLE_KEYWORD = {"alpha": "al", "beta": "be", "gamma": "ga"}

#: TOPAS.INC default limits of a refined macro parameter: (min, max, extra attributes); expressions in TOPAS syntax.
MACRO_DEFAULTS = {
    "tchz_uvwz": ("= Max(-1, Val-.1);", "= Min(2, Val+.1);", "del 1.0e-4"),
    "tchz_xy": ("= Max(0.0001, Val-.1);", "= Min(2, Val+.1);", "del 1.0e-4"),
    "pv_h": ("0.0001", "= 2 Val + .1;", "del 0.001"),
    "pv_lora": ("0.0001", "1", "del 0.001"),
    "pvii_h": ("0.0001", "1", ""),
    "pvii_ma": ("0.0001", "20", ""),
    "pvii_mbc": ("0.0001", "5", ""),
    "cs": ("0.3", "= Min(Val 2 + .3, 10000);", ""),
    "strain": ("0.0001", "5", ""),
    "one_on_x": ("0.0001", None, ""),
    "lp": ("0.0001", "90", ""),
    "lp_pp": ("0.0000001", "1.0", ""),
    "lp_mono": ("0.0000001", "90.0", ""),
    "simple_axial": ("0.0001", "50", ""),
    "zero_error": ("= Max(Val - 20 Yobs_dx_at(X1), -100 Yobs_dx_at(X1));",
                   "= Min(Val + 20 Yobs_dx_at(X2), 100 Yobs_dx_at(X2));", "del = .01 Yobs_dx_at(X1);"),
}

_PEAK_TYPE_KIND = {
    "TCHZ_Peak_Type": {"U": "tchz_uvwz", "V": "tchz_uvwz", "W": "tchz_uvwz", "Z": "tchz_uvwz",
                       "X": "tchz_xy", "Y": "tchz_xy"},
    "PV_Peak_Type": {"ha": "pv_h", "hb": "pv_h", "hc": "pv_h", "lora": "pv_lora", "lorb": "pv_h", "lorc": "pv_h"},
    "PVII_Peak_Type": {"ha": "pvii_h", "hb": "pvii_h", "hc": "pvii_h", "ma": "pvii_ma", "mb": "pvii_mbc",
                       "mc": "pvii_mbc"},
}


@dataclass
class ParamInfo:
    """One named TOPAS parameter and where it comes from."""

    path: str                    # recipe field path, e.g. "payload.phases.LaB6.atoms.La1.Uiso"
    category: str                # report category
    descriptive: str
    refined: bool
    phase: Optional[str] = None
    atom: Optional[str] = None
    scale: float = 1.0           # recipe value = TOPAS value / scale (beq: scale 8 pi^2)
    limits: tuple = (None, None)  # fixed limits after the run: stated bound, else TOPAS's fixed default
    limit_source: tuple = (None, None)  # per side: "stated", "TOPAS", "window" (SPF xo: the fit window's
    #                                     edge, reporting only, A154 N7 / P-04) or None (no fixed limit)


@dataclass
class NativeInput:
    """What the writer produced: INP and ``.xye`` text, and the map back to the recipe."""

    inp_text: str
    xye_text: str
    dropped_points: int
    params: dict = field(default_factory=dict)       # TOPAS name -> ParamInfo
    derived: dict = field(default_factory=dict)      # TOPAS name -> ParamInfo (LVol-IB, e0, SPF totals)
    phase_files: dict = field(default_factory=dict)  # phase name -> reflection-list file name
    results_file: str = ""
    profile_file: str = ""
    simulation: bool = False


def frac_text(value: Fraction) -> str:
    """A rational constant as TOPAS text: ``1/3``, ``-1/2``, ``0``."""
    if value.denominator == 1:
        return str(value.numerator)
    return f"{value.numerator}/{value.denominator}"


def affine_text(k: Fraction, rep: str, c: Fraction) -> str:
    """``k*rep + c`` in TOPAS syntax, e.g. ``-p1_a3_x + 1/2``, ``2*p1_a3_x``, ``p1_a3_u22/2``."""
    if k == 1:
        term = rep
    elif k == -1:
        term = f"-{rep}"
    elif k.denominator == 1:
        term = f"{k.numerator}*{rep}"
    elif k.numerator == 1:
        term = f"{rep}/{k.denominator}"
    elif k.numerator == -1:
        term = f"-{rep}/{k.denominator}"
    else:
        term = f"{frac_text(k)}*{rep}"
    if c == 0:
        return term
    return f"{term} {'+' if c > 0 else '-'} {frac_text(abs(c))}"


class _Writer:
    def __init__(self, model, base_name: str, background_values: Optional[dict] = None):
        self.model = model
        self.base = base_name
        self.data_base = base_name
        self.bkg_values = background_values  # TOPAS name -> refined value: the background run (A152)
        self.p = model.payload
        self.window: tuple = (None, None)  # (start_X, finish_X) once rendered
        self.out = NativeInput(inp_text="", xye_text="", dropped_points=0,
                               results_file=f"{base_name}{RESULTS_SUFFIX}",
                               profile_file=f"{base_name}{PROFILE_SUFFIX}",
                               simulation=self.p.refinement_controls.iters == 0)
        self.lines: list[str] = []

    # --- tokens ------------------------------------------------------------------

    def _register(self, name: str, info: ParamInfo) -> None:
        if name in self.out.params or name in self.out.derived:
            raise AssertionError(f"duplicate TOPAS parameter name {name!r}")  # D9: names are index-based
        self.out.params[name] = info

    def keyword_token(self, name: str, p: P, info: ParamInfo, scale: float = 1.0,
                      default: tuple = (None, None)) -> str:
        """``name value [min X] [max Y]`` (``!name`` when fixed); only the stated sides (A138)."""
        info.scale = scale
        info.refined = p.refine_flag
        lo = p.min * scale if p.min is not None else None
        hi = p.max * scale if p.max is not None else None
        info.limits = (lo if lo is not None else default[0], hi if hi is not None else default[1])
        info.limit_source = _sources((lo, hi), info.limits)
        self._register(name, info)
        if self.bkg_values is not None:
            return f"!{name} {fmt(self.bkg_values.get(name, p.value * scale))}"
        text = f"{name if p.refine_flag else '!' + name} {fmt(p.value * scale)}"
        if p.refine_flag:
            if lo is not None:
                text += f" min {fmt(lo)}"
            if hi is not None:
                text += f" max {fmt(hi)}"
        return text

    def prm_line(self, name: str, p: P, info: ParamInfo, kind: str, indent: str = "") -> str:
        """``prm name value min .. max ..`` for a macro parameter: stated or TOPAS.INC limits per side."""
        dmin, dmax, extra = MACRO_DEFAULTS[kind]
        info.refined = p.refine_flag
        fixed = {k: v for k, v in (("min", dmin), ("max", dmax))}
        info.limits = (p.min if p.min is not None else _number(dmin),
                       p.max if p.max is not None else _number(dmax))
        info.limit_source = _sources((p.min, p.max), info.limits)
        self._register(name, info)
        if self.bkg_values is not None:
            return f"{indent}prm !{name} {fmt(self.bkg_values.get(name, p.value))}"
        if not p.refine_flag:
            return f"{indent}prm !{name} {fmt(p.value)}"
        parts = [f"{indent}prm {name} {fmt(p.value)}"]
        for side, stated in (("min", p.min), ("max", p.max)):
            if stated is not None:
                parts.append(f"{side} {fmt(stated)}")
            elif fixed[side] is not None:
                expr = fixed[side]
                parts.append(f"{side} {expr}" if not expr.startswith("=") else f"{side} {expr}")
        if extra:
            parts.append(extra)
        return " ".join(parts)

    # --- top ---------------------------------------------------------------------

    def render(self) -> NativeInput:
        p = self.p
        c = p.refinement_controls
        schema = self.model.schema_name
        background_run = self.bkg_values is not None
        self.lines += [
            f"' Generated by PowderLine from a {schema} recipe (topas engine schema "
            f"{self.model.engine_schema_version}, TOPAS {self.model.engine_version})"
            + ("; background run: refined values fixed, no phases" if background_run else ""),
            f"iters {0 if background_run else c.iters}",
        ]
        if not self.out.simulation and not background_run:
            self.lines.append("do_errors")
        self.lines += [f"chi2_convergence_criteria {fmt(c.chi2_convergence_criteria)}", ""]
        if not background_run:
            self._instrument_prms()
        self.lines.append(f'xdd "{self.data_base}.xye" xye_format')
        self.lines.append(f"   x_calculation_step {fmt(c.x_calculation_step)}")
        start, finish = fit_limits_on_data(p.fit_range, p.xrd_data)  # on weighted data points (A149, A154, EB-59)
        self.window = (start, finish)
        self.lines += [f"   start_X {fmt(start)}", f"   finish_X {fmt(finish)}"]
        self._geometry_and_corrections()
        self._emission()
        self._background()
        if background_run:
            self._profile_output()
        else:
            if isinstance(self.model, TopasRietveldRecipe):
                for i, (name, phase) in enumerate(p.phases.items(), start=1):
                    self._phase(i, name, phase)
            else:
                for i, peak in enumerate(p.single_peaks, start=1):
                    self._single_peak(i, peak)
            self._outputs()
        self.out.inp_text = "\n".join(self.lines) + "\n"
        self.out.xye_text, self.out.dropped_points = render_xye(p.xrd_data)
        return self.out

    def _instrument_prms(self) -> None:
        """Global prms shared by every str / SPF peak: the peak type and Lorentz-polarisation (A148)."""
        b = self.p.instrument.broadening
        self.lines.append(f"' instrument peak type: {b.peak_type}")
        for name in PEAK_TYPES[b.peak_type]:
            info = ParamInfo(path=f"payload.instrument.broadening.parameters.{name}",
                             category="instrument_broadening", descriptive=f"instrument_{name}", refined=False)
            self.lines.append(self.prm_line(f"inst_{name}", b.parameters[name], info,
                                            _PEAK_TYPE_KIND[b.peak_type][name]))
        corr = self.p.instrument.corrections
        if corr is not None and corr.LP_Factor is not None:
            info = ParamInfo(path="payload.instrument.corrections.LP_Factor.monochromator_angle",
                             category="instrument_correction", descriptive="LP_Factor_monochromator_angle",
                             refined=False)
            self.lines.append(self.prm_line("lp_monochromator_angle", corr.LP_Factor.monochromator_angle, info, "lp"))
        if corr is not None and corr.LP_Factor_Synchrotron is not None:
            for field_, kind in (("pp", "lp_pp"), ("mono", "lp_mono")):
                info = ParamInfo(path=f"payload.instrument.corrections.LP_Factor_Synchrotron.{field_}",
                                 category="instrument_correction", descriptive=f"LP_Factor_Synchrotron_{field_}",
                                 refined=False)
                self.lines.append(self.prm_line(f"lps_{field_}", getattr(corr.LP_Factor_Synchrotron, field_),
                                                info, kind))
        self.lines.append("")

    def _peak_type_call(self) -> str:
        b = self.p.instrument.broadening
        args = ", ".join(f", inst_{n}" for n in PEAK_TYPES[b.peak_type])
        return f"{b.peak_type}({args})"

    def _lp_call(self) -> Optional[str]:
        corr = self.p.instrument.corrections
        if corr is None:
            return None
        if corr.LP_Factor is not None:
            return "LP_Factor(, lp_monochromator_angle)"
        if corr.LP_Factor_Synchrotron is not None:
            return "LP_Factor_Synchrotron(, lps_pp, , lps_mono)"
        return None

    def _geometry_and_corrections(self) -> None:
        g, corr = self.p.instrument.geometry, self.p.instrument.corrections
        if g is not None:
            radii = " ".join(f"{n} {fmt(getattr(g, n))}" for n in ("Rp", "Rs") if getattr(g, n) is not None)
            self.lines.append(f"   {radii}")
        if corr is None:
            return
        base = "payload.instrument.corrections"
        if corr.Zero_Error is not None:
            info = ParamInfo(path=f"{base}.Zero_Error.th2_offset", category="instrument_correction",
                             descriptive="Zero_Error_th2_offset", refined=False)
            self.lines.append(self.prm_line("ze_th2_offset", corr.Zero_Error.th2_offset, info, "zero_error", "   "))
            self.lines.append("   ZE(, ze_th2_offset)")
        if corr.Simple_Axial_Model is not None:
            info = ParamInfo(path=f"{base}.Simple_Axial_Model.axial_length_mm", category="instrument_correction",
                             descriptive="Simple_Axial_Model_axial_length_mm", refined=False)
            self.lines.append(self.prm_line("ax_axial_length_mm", corr.Simple_Axial_Model.axial_length_mm, info,
                                            "simple_axial", "   "))
            self.lines.append("   Simple_Axial_Model(, ax_axial_length_mm)")
        if corr.Full_Axial_Model is not None:
            f = corr.Full_Axial_Model
            self.lines.append("   axial_conv")
            for n in ("filament_length", "sample_length", "receiving_slit_length", "primary_soller_angle",
                      "secondary_soller_angle"):
                v = getattr(f, n)
                if v is None:
                    continue
                info = ParamInfo(path=f"{base}.Full_Axial_Model.{n}", category="instrument_correction",
                                 descriptive=f"Full_Axial_Model_{n}", refined=False)
                lo = KEYWORD_LIMITS["axial"][0]
                self.lines.append(f"      {n} {self.keyword_token(f'ax_{n}', v, info, default=(lo, None))}")
            self.lines.append(f"      axial_n_beta {f.axial_n_beta}")
        if corr.capillary is not None:
            cap = corr.capillary
            info = ParamInfo(path=f"{base}.capillary.diameter_mm", category="instrument_correction",
                             descriptive="capillary_diameter_mm", refined=False)
            self.lines.append(f"   capillary_diameter_mm {self.keyword_token('cap_diameter_mm', cap.diameter_mm, info)}")
            info = ParamInfo(path=f"{base}.capillary.u_cm_inv", category="instrument_correction",
                             descriptive="capillary_u_cm_inv", refined=False)
            self.lines.append(f"      capillary_u_cm_inv {self.keyword_token('cap_u_cm_inv', cap.u_cm_inv, info)}")
            self.lines.append(f"      capillary_{cap.beam}_beam")

    def _emission(self) -> None:
        r = self.p.instrument.radiation
        tokens = []
        for n in ("la", "lo", "lh", "lg"):
            v = getattr(r, n)
            if v is None:
                continue
            info = ParamInfo(path=f"payload.instrument.radiation.{n}", category="radiation", descriptive=n,
                             refined=False)
            tokens.append(f"{n} {self.keyword_token(f'lam_{n}', v, info, default=KEYWORD_LIMITS[n])}")
        self.lines.append(f"   lam ymin_on_ymax {fmt(r.ymin_on_ymax)} " + " ".join(tokens))

    def _background(self) -> None:
        bg = self.p.background
        if bg is None:
            return
        if bg.chebyshev is not None:
            ch = bg.chebyshev
            coefficients = ch.coefficients
            if self.bkg_values is not None:
                coefficients = [self.bkg_values.get(f"{CHEBYSHEV_NAME}_bkg{i}__", v) for i, v in enumerate(coefficients)]
            name = CHEBYSHEV_NAME if ch.refine_flag and self.bkg_values is None else f"!{CHEBYSHEV_NAME}"
            self.lines.append(f"   bkg {name} " + " ".join(fmt(v) for v in coefficients))
            for i in range(ch.num_coefficients):
                self._register(f"{CHEBYSHEV_NAME}_bkg{i}__", ParamInfo(
                    path=f"payload.background.chebyshev.coefficients.{i}", category="background",
                    descriptive=f"background_coefficient_{i}", refined=ch.refine_flag))
        if bg.One_on_X is not None:
            info = ParamInfo(path="payload.background.One_on_X", category="background", descriptive="One_on_X",
                             refined=False)
            self.lines.append(self.prm_line("oox", bg.One_on_X, info, "one_on_x", "   "))
            self.lines.append("   One_on_X(, oox)")
        for i, pk in enumerate(bg.peaks or [], start=1):
            base = f"payload.background.peaks.{i - 1}"
            self.lines.append("   xo_Is")
            tok = self._kw(f"bkpk{i}_xo", pk.xo, f"{base}.xo", "background_peak", f"background_peak_{i}_xo")
            itok = self._kw(f"bkpk{i}_I", pk.I, f"{base}.I", "background_peak", f"background_peak_{i}_I",
                            default=KEYWORD_LIMITS["I"])
            self.lines.append(f"      xo {tok} I {itok}")
            params = " ".join(
                f"{n} " + self._kw(f"bkpk{i}_{n}", v, f"{base}.parameters.{n}", "background_peak",
                                   f"background_peak_{i}_{n}", default=KEYWORD_LIMITS.get(n, (None, None)))
                for n, v in pk.parameters.items())
            self.lines.append(f"      peak_type {pk.peak_type} {params}")

    def _kw(self, name, p, path, category, descriptive, default=(None, None), phase=None, atom=None, scale=1.0):
        info = ParamInfo(path=path, category=category, descriptive=descriptive, refined=False, phase=phase, atom=atom)
        return self.keyword_token(name, p, info, scale=scale, default=default)

    # --- phases --------------------------------------------------------------------

    def _phase(self, i: int, name: str, phase) -> None:
        pfx = f"p{i}"
        base = f"payload.phases.{name}"
        self.lines += ["   str", f'      phase_name "{name}"',
                       f'      space_group "{topas_space_group(phase.space_group)}"']
        self.lines.append("      scale " + self._kw(f"{pfx}_scale", phase.scale, f"{base}.scale", "scale",
                                                     f"{name}_scale", default=KEYWORD_LIMITS["scale"], phase=name))
        self.lines.append("      " + self._cell(pfx, name, phase))
        self.lines.append(f"      prm {pfx}_volume = Get(cell_volume); : 0")
        self.out.derived[f"{pfx}_volume"] = ParamInfo(path=f"payload.phases.{name}.unit_cell", category="cell_volume",
                                                      descriptive=f"{name}_volume", refined=False, phase=name)
        types = phase.scattering_types or {}
        for j, (label, atom) in enumerate(phase.atoms.items(), start=1):
            self.lines.append("      " + self._site(pfx, j, name, label, phase.space_group, atom,
                                                     types.get(label, atom.element)))
        self._preferred_orientation(pfx, name, phase)
        self.lines.append(f"      {self._peak_type_call()}")
        self._sample_broadening(pfx, name, phase)
        lp = self._lp_call()
        if lp:
            self.lines.append(f"      {lp}")
        peaks = f"{self.base}_{pfx}_peaks.txt"
        self.out.phase_files[name] = peaks
        self.lines += [
            f'      phase_out "{peaks}" load out_record out_fmt out_eqn',
            "      {",
            '         " %.0f" = H;', '         " %.0f" = K;', '         " %.0f" = L;', '         " %.0f" = M;',
            '         " %.10g" = D_spacing;', '         " %.10g" = 2 Rad Th;', '         " %.10g" = I_no_scale_pks;',
            '         " %.10g" = I_after_scale_pks;', '         " %.10g" = Iobs_no_scale_pks;',
            '         " %.10g" = A01;', '         " %.10g" = B01;', '         " %.10g" = A11;',
            '         " %.10g\\n" = B11;',
            "      }",
        ]

    def _cell(self, pfx: str, name: str, phase) -> str:
        cell = phase.unit_cell
        ties = cell_tie_groups(phase.space_group)
        rep_of = {}
        for g in ties.groups:
            for m in g.members:
                rep_of[m] = g.members[0]
        parts = []
        for member in ("a", "b", "c", "alpha", "beta", "gamma"):
            kw = _ANGLE_KEYWORD.get(member, member)
            p = getattr(cell, member)
            default = KEYWORD_LIMITS["cell_angle" if member in _ANGLE_KEYWORD else "cell_length"]
            if member in ties.fixed:
                parts.append(f"{kw} {fmt(p.value)}")
            elif rep_of.get(member, member) == member:
                parts.append(f"{kw} " + self._kw(f"{pfx}_cell_{member}", p, f"payload.phases.{name}.unit_cell.{member}",
                                                 "cell", f"{name}_{member}", default=default, phase=name))
            else:
                parts.append(f"{kw} = Get({_ANGLE_KEYWORD.get(rep_of[member], rep_of[member])});")
        return "   ".join(parts)

    def _preferred_orientation(self, pfx: str, name: str, phase) -> None:
        """TOPAS.INC's ``PO(c, v, ang, hkl)`` March-Dollase macro: ``PO(p1_po_r, 0.8 min a max b, , 0 0 1)`` refined,
        ``PO(!p1_po_r, 0.6, , 0 0 1)`` fixed. ``ang`` only names the computed correction, so it is left empty. Only
        the stated bounds are written; on a ``null`` side TOPAS keeps its own limit: min 0.0001; max twice
        the current r plus 0.5, recomputed as r changes."""
        po = phase.preferred_orientation
        if po is None:
            return
        info = ParamInfo(path=f"payload.phases.{name}.preferred_orientation.ratio", category="preferred_orientation",
                         descriptive=f"{name}_po_ratio", refined=False, phase=name)
        label, _, value = self.keyword_token(f"{pfx}_po_r", po.ratio, info,
                                             default=KEYWORD_LIMITS["po_ratio"]).partition(" ")
        self.lines.append(f"      PO({label}, {value}, , {' '.join(str(int(i)) for i in po.hkl)})")

    def _site(self, pfx: str, j: int, name: str, label: str, sg: str, atom, scattering_type: str) -> str:
        xyz = (atom.x.value, atom.y.value, atom.z.value)
        ties = coupling_groups(sg, xyz)
        exact = analyze_site(sg, xyz).exact
        apfx = f"{pfx}_a{j}"
        base = f"payload.phases.{name}.atoms.{label}"
        rel = {}
        for g in ties.xyz.groups:
            for m in g.members:
                rel[m] = (g.members[0],) + g.relation(m)
        coords = []
        for axis, value in zip("xyz", exact):
            p = getattr(atom, axis)
            if axis in ties.xyz.fixed:
                coords.append(f"{axis} {_constant(value)}")
                continue
            rep, k, c = rel[axis]
            if rep == axis:
                coords.append(f"{axis} " + self._kw(f"{apfx}_{axis}", p, f"{base}.{axis}", "atom_coordinate",
                                                    f"{label}_{axis}", phase=name, atom=label))
            else:
                coords.append(f"{axis} = {affine_text(k, f'{apfx}_{rep}', c)};")
        occ = self._kw(f"{apfx}_occ", atom.occupancy, f"{base}.occupancy", "occupancy", f"{label}_occupancy",
                       default=KEYWORD_LIMITS["occ"], phase=name, atom=label)
        text = f"site {label} " + " ".join(coords) + f" occ {topas_type(scattering_type)} {occ}"
        if atom.ADP == "Uiso":
            text += " beq " + self._kw(f"{apfx}_beq", atom.Uiso, f"{base}.Uiso", "atom_adp", f"{label}_Uiso",
                                       default=KEYWORD_LIMITS["beq"], phase=name, atom=label, scale=EIGHT_PI_SQ)
        else:
            u = atom.Uaniso
            urel = {}
            for g in ties.uij.groups:
                for m in g.members:
                    urel[m] = (g.members[0],) + g.relation(m)
            for comp in ("U11", "U22", "U33", "U12", "U13", "U23"):
                kw = comp.lower()
                p = getattr(u, comp)
                if comp in ties.uij.fixed:
                    text += f" {kw} {fmt(p.value)}"
                    continue
                rep, k, c = urel[comp]
                if rep == comp:
                    text += f" {kw} " + self._kw(f"{apfx}_{kw}", p, f"{base}.Uaniso.{comp}", "atom_adp",
                                                 f"{label}_{comp}", phase=name, atom=label)
                else:
                    text += f" {kw} = {affine_text(k, f'{apfx}_{rep.lower()}', c)};"
        return text

    def _sample_broadening(self, pfx: str, name: str, phase) -> None:
        pb = phase.peak_broadening
        if pb is None:
            return
        base = f"payload.phases.{name}.peak_broadening"
        for part, comps, kind in (("size_broadening", ("CS_L", "CS_G"), "cs"),
                                  ("strain_broadening", ("Strain_L", "Strain_G"), "strain")):
            block = getattr(pb, part)
            if block is None:
                continue
            for comp in comps:
                v = getattr(block, comp)
                if v is None:
                    continue
                prm = f"{pfx}_{comp.lower()}"
                info = ParamInfo(path=f"{base}.{part}.{comp}", category=part, descriptive=f"{name}_{comp}",
                                 refined=False, phase=name)
                self.lines.append(self.prm_line(prm, v, info, kind, "      "))
                self.lines.append(f"      {comp}(, {prm})")
        self._derived_size_strain(pfx, name, pb)

    def _derived_size_strain(self, pfx: str, name: str, pb) -> None:
        """LVol-IB (k = 1) and e0 as TOPAS.INC computes them (EB-57; D7)."""
        s, e = pb.size_broadening, pb.strain_broadening
        if s is not None:
            csl = f"{pfx}_cs_l" if s.CS_L is not None else None
            csg = f"{pfx}_cs_g" if s.CS_G is not None else None
            if csl and csg:
                ib = f"Voigt_Integral_Breadth_GL(1/{csg}, 1/{csl})"
            elif csl:
                ib = f"(1.570796326795/{csl})"
            else:
                ib = f"(1.064467019431/{csg})"
            self._derived(f"{pfx}_lvol_ib", f"1 / {ib}", name, "LVol_IB", "nanometre")
        if e is not None:
            sg = f"{pfx}_strain_g" if e.Strain_G is not None else "0"
            sl = f"{pfx}_strain_l" if e.Strain_L is not None else "0"
            self._derived(f"{pfx}_e0", f"Voigt_FWHM_GL({sg}, {sl}) .25 Pi/360", name, "e0", "dimensionless")

    def _derived(self, prm: str, expr: str, phase: str, what: str, unit: str) -> None:
        self.lines.append(f"      prm {prm} = {expr}; : 0")
        self.out.derived[prm] = ParamInfo(path=f"payload.phases.{phase}", category="derived",
                                          descriptive=f"{phase}_{what}", refined=False, phase=phase)

    # --- single peaks ------------------------------------------------------------------

    def _single_peak(self, i: int, peak) -> None:
        pfx = f"spf{i}"
        base = f"payload.single_peaks.{i - 1}"
        self.lines.append("   xo_Is")
        xo = self._kw(f"{pfx}_xo", peak.xo, f"{base}.xo", "spf_peak", f"spf_peak_{i}_xo")
        self._window_as_limit(self.out.params[f"{pfx}_xo"])
        itok = self._kw(f"{pfx}_I", peak.I, f"{base}.I", "spf_peak", f"spf_peak_{i}_I", default=KEYWORD_LIMITS["I"])
        self.lines.append(f"      xo {xo} I {itok}")
        self.lines.append(f"      {self._peak_type_call()}")
        for kw in ("gauss_fwhm", "lor_fwhm"):
            v = getattr(peak, kw)
            if v is not None:
                self.lines.append(f"      {kw} " + self._kw(f"{pfx}_{kw}", v, f"{base}.{kw}", "spf_peak",
                                                           f"spf_peak_{i}_{kw}"))
        self._spf_totals(pfx, i, peak)

    def _window_as_limit(self, info: ParamInfo) -> None:
        """A peak position without a stated bound gets the fit window's edge as its limit, source ``"window"``
        (A154 N7, P-04): TOPAS does not hold ``xo`` inside ``start_X``..``finish_X``, so the runner's at-limit
        check reports a peak that ended on or beyond the window's edge. Reporting only: the INP is unchanged."""
        info.limits = tuple(w if lim is None else lim for lim, w in zip(info.limits, self.window))
        info.limit_source = tuple("window" if src is None and w is not None else src
                                  for src, w in zip(info.limit_source, self.window))

    def _spf_totals(self, pfx: str, i: int, peak) -> None:
        """The whole peak's FWHM and integral breadth at its position (TCHZ only: G and L parts are explicit; D13)."""
        if self.p.instrument.broadening.peak_type != "TCHZ_Peak_Type":
            return
        t = f"({pfx}_xo Deg_on_2)"
        g_inst = (f"Sqrt(Abs(inst_U Tan{t}^2 + inst_V Tan{t} + inst_W + inst_Z / Cos{t}^2))")
        l_inst = f"(inst_X Tan{t} + inst_Y / Cos{t})"
        g = f"Sqrt({g_inst}^2 + {pfx}_gauss_fwhm^2)" if peak.gauss_fwhm is not None else g_inst
        l = f"({l_inst} + {pfx}_lor_fwhm)" if peak.lor_fwhm is not None else l_inst
        self.lines.append(f"      prm {pfx}_fwhm = Voigt_FWHM_GL({g}, {l}); : 0")
        self.lines.append(f"      prm {pfx}_integral_breadth = Voigt_Integral_Breadth_GL({g}, {l}); : 0")
        for what in ("fwhm", "integral_breadth"):
            self.out.derived[f"{pfx}_{what}"] = ParamInfo(path=f"payload.single_peaks.{i - 1}", category="derived",
                                                          descriptive=f"spf_peak_{i}_{what}", refined=False)

    # --- outputs -------------------------------------------------------------------------

    def _profile_output(self) -> None:
        self.lines += [
            "",
            f'xdd_out "{self.out.profile_file}" load out_record out_fmt out_eqn',
            "{",
            '   " %.10g" = X;',
            '   " %.10g" = Yobs;',
            '   " %.10g\\n" = Ycalc;',
            "}",
        ]

    def _outputs(self) -> None:
        self._profile_output()
        self.lines += [
            "",
            f'out "{self.out.results_file}"',
            '   out_record out_fmt "parameter,value,esd\\n"',
        ]
        for stat in ("r_wp", "r_exp", "gof", "number_independent_parameters"):
            self.lines.append(f'   out_record out_eqn = Get({stat}); out_fmt "{stat},%.12g,\\n"')
        err = "" if self.out.simulation else ' out_fmt_err "%.12g\\n"'
        end = '\\n"' if self.out.simulation else '"'
        for name, info in list(self.out.params.items()) + list(self.out.derived.items()):
            if info.category not in ("derived", "cell_volume") and not info.refined:
                continue
            self.lines.append(f'   out_record out_eqn = {name}; out_fmt "{name},%.12g,{end}{err}')


def _constant(value: Optional[Fraction]) -> str:
    """A symmetry-fixed coordinate: an exact decimal as a number, a third etc. as an equation (EB-08)."""
    if value is None:
        raise AssertionError("fixed coordinate without an exact value")
    d = value.denominator
    while d % 2 == 0:
        d //= 2
    while d % 5 == 0:
        d //= 5
    if d == 1:
        return fmt(float(value))
    return f"= {frac_text(value)};"


def _sources(stated: tuple, limits: tuple) -> tuple:
    return tuple("stated" if s is not None else ("TOPAS" if lim is not None else None)
                 for s, lim in zip(stated, limits))


def _number(expr: Optional[str]) -> Optional[float]:
    """A fixed limit as a number; ``None`` for an expression in ``Val`` (a step limit) or no limit."""
    if expr is None:
        return None
    try:
        return float(expr)
    except ValueError:
        if "Val" in expr:
            text = expr.strip("= ;")
            for fn in ("Max", "Min"):  # Max(-1, Val-.1) -> -1, Min(Val 2 + .3, 10000) -> 10000: the fixed part
                if text.startswith(fn + "(") and text.endswith(")"):
                    for arg in _top_level_args(text[len(fn) + 1:-1]):
                        try:
                            return float(arg)
                        except ValueError:
                            continue
        return None


def _top_level_args(text: str) -> list[str]:
    """Split ``a, f(b, c)`` at the commas outside parentheses."""
    args, depth, start = [], 0, 0
    for i, ch in enumerate(text):
        depth += (ch == "(") - (ch == ")")
        if ch == "," and depth == 0:
            args.append(text[start:i].strip())
            start = i + 1
    return args + [text[start:].strip()]


def render_xye(xrd) -> tuple[str, int]:
    """``.xye`` text: 2theta, I, sigma = 1/sqrt(w); zero-weight points dropped (they carry no information)."""
    lines, dropped = [], 0
    for t, y, w in zip(xrd.tth, xrd.Itth, xrd.Itth_weights):
        if w == 0:
            dropped += 1
            continue
        lines.append(f"{fmt(t)} {fmt(y)} {fmt(1 / math.sqrt(w))}")
    return "\n".join(lines) + "\n", dropped


def render_native(model: TopasRietveldRecipe | TopasSpfRecipe, base_name: str) -> NativeInput:
    """Render a validated native recipe to TOPAS input (pure)."""
    return _Writer(model, base_name).render()


def background_base(base_name: str) -> str:
    """The background run's base name (A152): ``<base>_bkg`` (it reads ``<base>.xye``)."""
    return f"{base_name}_bkg"


def has_background(model) -> bool:
    """Whether the recipe models a background (else the background column is 0)."""
    bg = model.payload.background
    return bg is not None and (bg.chebyshev is not None or bg.One_on_X is not None or bool(bg.peaks))


def render_background(model: TopasRietveldRecipe | TopasSpfRecipe, base_name: str, values: dict) -> NativeInput:
    """The background run's INP (A152, pure): the main run's ``<base>.xye``, window, corrections, emission and
    background, every parameter fixed at ``values`` (TOPAS name -> refined value; the recipe value where absent),
    no ``str`` phases or SPF peaks, ``iters 0``; the profile goes to ``<base>_bkg_profile.txt``."""
    w = _Writer(model, background_base(base_name), background_values=values)
    w.data_base = base_name
    return w.render()
