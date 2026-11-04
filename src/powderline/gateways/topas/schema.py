"""TOPAS engine schemas ``topas.rietveld`` and ``topas.spf`` (engine schema 0.1.0, TOPAS 6).

Built on the core schema (:mod:`powderline.schema_core`): a recipe is a
:class:`~powderline.schema_core.CoreRecipe` plus ``engine_version``, a phase a
``Phase[BoundedRefinableParameter]`` with the TOPAS fields flat in the same
block (A93). Every refinable is ``[value, refine_flag, min, max]`` (A20).
Recipes state TOPAS's own keywords, macro parameters and units (A142): the
numbers in the recipe are the numbers in the INP. Nothing has a default: a
block that is left out is not modelled. Invalid recipes raise pydantic's
``ValidationError`` with every problem at its location (A70).

Engine-free: imports nothing of TOPAS (it has no Python package), so
``validate()`` runs anywhere. The runtime layer consumes the validated model
(A39). Design: devkit ``tasks/re05-topas-schema-draft.md`` rev 3 (signed,
A147); engine behaviour: ``tasks/re05-topas6-compat.md`` (C1-C30).

Engine version: the recipe states the TOPAS major version it is written for
(``engine_version``, A144); 0.1.0 supports TOPAS 6 only (A143).

TOPAS rules checked here:

- the space group must be a setting TOPAS 6 reads as itself (541 of 564; C16);
- a refined parameter's start value lies within TOPAS's fixed default limits on
  every side the recipe leaves ``null``, since TOPAS moves it silently
  otherwise (A138; C20);
- widths are positive (a negative FWHM stops TOPAS, C24); wavelength and
  crystallite size are positive (A126); ``la``, ``lh``, ``lg`` and the capillary
  diameter are positive (a line with no area or width, or a capillary of no
  diameter, does not exist: A111(a)). Fixed instrument peak-type terms are not
  checked (a fixed TCHZ X < 0 can make the Lorentzian width negative; whether
  TOPAS stops there is unverified; documented, A155);
- peak positions lie inside the fit window (A126);
- ``geometry`` holds exactly the radii the axial model reads (C26);
- mutually exclusive corrections; ``LP_Factor_Synchrotron`` never refines
  both ``pp`` and ``mono`` (TOPAS.INC: ~100 % correlated; A147 Q-L1);
- a simulation (``iters == 0``) refines nothing.
"""

from __future__ import annotations

import math
from typing import Annotated, Any, ClassVar, Literal, Mapping, Optional, Union

import gemmi
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version
from pydantic import Field, StrictStr, field_validator, model_serializer, model_validator
from pydantic_core import InitErrorDetails

from powderline.compat import schema_declarations
from powderline.exceptions import StructuredWarning
from powderline.schema_core import (
    UNIT_ANGSTROM,
    UNIT_ARBITRARY,
    UNIT_DEG_2THETA,
    UNIT_DEGREE,
    BoundedRefinableParameter,
    ChebyshevBackground,
    CoreFloat,
    CoreInt,
    CoreModel,
    CoreName,
    EngineRecipe,
    FitRange,
    MarchDollase,
    Phase,
    XRDData,
    absent_not_null,
    absent_not_null_schema,
    custom_error,
    fit_range_problems,
    fit_window,
    name_keyed,
    omit_absent,
    outside_window_problems,
    raise_problems,
    recipe_validator,
    refined_flag_problems,
    unique_phase_names,
    unit_schema,
)

P = BoundedRefinableParameter

# --- versions (A65, A143, A144) -----------------------------------------------

ENGINE_SCHEMA_VERSION = "0.1.0"
SUPPORTED_ENGINE_SCHEMAS = "==0.1.0"
REQUIRES_CORE_SCHEMA = "==0.1.0"
#: TOPAS major versions a ``topas.*`` 0.1.0 recipe may state (A143, A144); widened explicitly, never by range.
SUPPORTED_ENGINE_VERSIONS = "==6"

#: The gateway's schema declarations (``capabilities()`` keys, A65) plus the TOPAS versions (A144).
DECLARATIONS = schema_declarations(
    engine_schema_version=ENGINE_SCHEMA_VERSION,
    supported_engine_schemas=SUPPORTED_ENGINE_SCHEMAS,
    requires_core_schema=REQUIRES_CORE_SCHEMA,
    supported_engine_versions=SUPPORTED_ENGINE_VERSIONS,
)

SCHEMA_NAMES = ("topas.rietveld", "topas.spf")

# --- units (TOPAS native, A4, A142) -------------------------------------------

UNIT_MILLIANGSTROM = "milliangstrom"
UNIT_NANOMETRE = "nanometre"
UNIT_MILLIMETRE = "millimetre"
UNIT_INV_CM = "1/cm"
UNIT_DIMENSIONLESS = "dimensionless"

#: beq = 8 pi^2 Uiso (EB-24; confirmed on TOPAS 6, C19).
EIGHT_PI_SQ = 8 * math.pi ** 2


# --- TOPAS's fixed default limits (A138; TR Table 3.1, TOPAS.INC; EB-58) ------

def _limit_text(limit: float, side: str) -> str:
    """A limit as the message prints it: 6 significant digits when that value is itself allowed, else exact."""
    text = f"{limit:.6g}"
    outside = float(text) < limit if side == "min" else float(text) > limit
    return repr(float(limit)) if outside else text


def limit_problems(p: Optional[P], lo: Optional[float], hi: Optional[float], loc: tuple,
                   what: str) -> list[InitErrorDetails]:
    """A refined start outside TOPAS's fixed default limit, on a side the recipe leaves ``null`` (A138 rule 1).

    TOPAS's limits act only on refined parameters, and a stated bound replaces
    TOPAS's on that side. TOPAS moves a start outside the limit silently (a
    ``beq`` start of 25 ended at exactly 20 on TOPAS 6, C20), so it is an error.
    """
    if p is None or not p.refine_flag:
        return []
    problems = []
    if lo is not None and p.min is None and p.value < lo:
        problems.append(custom_error(
            "topas_default_limit",
            "{what} is refined from {value}, below TOPAS's default minimum {limit}: TOPAS would move it to the "
            "limit without saying so; start at or above {limit}, or state min to replace TOPAS's limit",
            loc, p.model_dump(), what=what, value=p.value, limit=_limit_text(lo, "min")))
    if hi is not None and p.max is None and p.value > hi:
        problems.append(custom_error(
            "topas_default_limit",
            "{what} is refined from {value}, above TOPAS's default maximum {limit}: TOPAS would move it to the "
            "limit without saying so; start at or below {limit}, or state max to replace TOPAS's limit",
            loc, p.model_dump(), what=what, value=p.value, limit=_limit_text(hi, "max")))
    return problems


def _positive(p: Optional[P], loc: tuple, what: str, *, allow_zero: bool = False) -> list[InitErrorDetails]:
    if p is None:
        return []
    bad = p.value < 0 if allow_zero else p.value <= 0
    if not bad:
        return []
    need = ">= 0" if allow_zero else "> 0"
    return [custom_error("topas_positive", "{what} must be {need}, got {value}", loc, p.model_dump(),
                   what=what, need=need, value=p.value)]


#: Fixed default limits (min, max) of TOPAS keywords on refined values (TR Table 3.1 p. 76; ``None`` = none).
KEYWORD_LIMITS = {
    "la": (1e-5, None), "lo": (0.01, 100.0), "lh": (0.001, 5.0), "lg": (0.001, 5.0),
    "cell_length": (1.5, None), "cell_angle": (1.5, None), "scale": (1e-11, None), "occ": (0.0, None),
    "beq": (-10.0, 20.0), "I": (1e-11, None), "pv_fwhm": (1e-6, None), "h1": (1e-6, None),
    "h2": (1e-6, None), "spv_h1": (1e-6, None), "spv_h2": (1e-6, None), "pv_lor": (0.0, 1.0),
    "spv_l1": (0.0, 1.0), "spv_l2": (0.0, 1.0), "m1": (0.75, 30.0), "m2": (0.75, 30.0),
    "axial": (1e-4, None),
}

# --- space group (A105; C16, EB-11, EB-43) ------------------------------------

#: Canonical names TOPAS 6 cannot express (no symbol in its table), or reads as another setting
#: (it drops the origin shift of the last three). Evidence: TOPAS 6's own operator files for every
#: other setting equal gemmi's (devkit ``probes/re05_topas_sg_mapping.py``, ``re05-topas6-compat.md`` C16).
TOPAS_UNREADABLE_SETTINGS = frozenset({
    "P 21212(a)", "C 2 2 21a)", "C 2 2 2a", "F 2 2 2a", "I 2 2 2a", "P 42 21 2a", "I 2 3a",
    "B 1 2 1", "C 1 1 2", "B 1 21 1", "C 1 1 21", "F 1 2 1", "F 1 m 1", "F 1 d 1", "F 1 2/m 1",
    "A b a m", "F 4 2 2", "C -4 2 m", "C -4 2 b", "F 4/m m m",
    "C 1 21 1", "I 1 21 1", "C 4 2 21",
})


def topas_symbol(name: str) -> str:
    """TOPAS's symbol for a canonical gemmi name, by rule (no setting check; see :func:`topas_space_group`).

    Lowercase, no spaces; ``:1`` dropped (a bare two-origin symbol is origin
    choice 1 in TOPAS, EB-11), ``:2`` kept; ``:H`` dropped (a bare R symbol is
    hexagonal axes), ``:R`` becomes a trailing ``r`` (rhombohedral axes, EB-43).
    """
    sym = name.replace(" ", "").lower()
    if sym.endswith(":1") or sym.endswith(":h"):
        return sym[:-2]
    if sym.endswith(":r"):
        return sym[:-2] + "r"
    return sym


def topas_space_group(name: str) -> str:
    """TOPAS's symbol for a canonical space-group name; ``ValueError`` for a setting TOPAS cannot express."""
    sg = gemmi.find_spacegroup_by_name(name)
    if sg is None or sg.xhm() != name:
        raise ValueError(f"{name!r} is not a canonical space-group name")
    if name in TOPAS_UNREADABLE_SETTINGS:
        raise ValueError(
            f"TOPAS cannot express the setting {name!r} (it has no symbol for it, or reads it as another "
            "setting); transform the structure to a standard setting (TOPAS quirk EB-43)")
    return topas_symbol(name)


# --- instrument (A140, A141, A143) --------------------------------------------


class Radiation(CoreModel):
    """One emission line (TOPAS ``lam``): ``la``, ``lo``, ``lh`` and optionally ``lg`` with ``lh``."""

    ymin_on_ymax: CoreFloat = Field(gt=0, description="TOPAS 'ymin_on_ymax': x-axis extent of the emission line")
    la: P = Field(json_schema_extra=unit_schema(UNIT_DIMENSIONLESS), description="TOPAS 'la': area of the line, > 0")
    lo: P = Field(json_schema_extra=unit_schema(UNIT_ANGSTROM), description="TOPAS 'lo': wavelength, > 0")
    lh: P = Field(json_schema_extra=unit_schema(UNIT_MILLIANGSTROM),
                  description="TOPAS 'lh': Lorentzian half-width of the line, > 0 (synchrotron: very narrow, "
                              "e.g. 0.0001)")
    lg: Optional[P] = Field(default=None, json_schema_extra=absent_not_null_schema(UNIT_MILLIANGSTROM),
                            description="TOPAS 'lg': Gaussian half-width, > 0; only together with lh (lg alone "
                                        "crashes TOPAS 6)")

    _not_null = field_validator("lg", mode="before")(absent_not_null)

    @model_serializer(mode="wrap")
    def _omit_absent(self, handler):
        return omit_absent(handler(self), self, ("lg",))

    @model_validator(mode="after")
    def _topas_radiation(self) -> "Radiation":
        problems = []
        for name in ("la", "lo", "lh", "lg"):
            p = getattr(self, name)
            problems += _positive(p, (name,), name)
            problems += limit_problems(p, *KEYWORD_LIMITS[name], (name,), name)
        raise_problems(type(self).__name__, problems)
        return self


class Geometry(CoreModel):
    """Goniometer radii (TOPAS ``Rp``, ``Rs``), plain values; only those the axial model reads."""

    Rp: Optional[CoreFloat] = Field(default=None, gt=0, json_schema_extra=absent_not_null_schema(UNIT_MILLIMETRE),
                                    description="Primary radius; required with Full_Axial_Model only")
    Rs: Optional[CoreFloat] = Field(default=None, gt=0, json_schema_extra=absent_not_null_schema(UNIT_MILLIMETRE),
                                    description="Secondary radius; required with either axial model")

    _not_null = field_validator("Rp", "Rs", mode="before")(absent_not_null)

    @model_serializer(mode="wrap")
    def _omit_absent(self, handler):
        return omit_absent(handler(self), self, ("Rp", "Rs"))


class ZeroError(CoreModel):
    """TOPAS ``ZE`` / ``Zero_Error``: ``th2_offset``."""

    th2_offset: P = Field(json_schema_extra=unit_schema(UNIT_DEG_2THETA), description="Zero error")


class LPFactor(CoreModel):
    """TOPAS ``LP_Factor``: Lorentz-polarisation with a monochromator angle."""

    monochromator_angle: P = Field(json_schema_extra=unit_schema(UNIT_DEGREE),
                                   description="Monochromator 2theta: 90 synchrotron/neutron, 0 no monochromator")


class LPFactorSynchrotron(CoreModel):
    """TOPAS ``LP_Factor_Synchrotron`` (Madsen): in-plane polarisation and monochromator angle."""

    pp: P = Field(json_schema_extra=unit_schema(UNIT_DIMENSIONLESS),
                  description="Polarisation in the plane: 0 ideal synchrotron ... 1 laboratory tube")
    mono: P = Field(json_schema_extra=unit_schema(UNIT_DEGREE), description="Monochromator 2theta")

    @model_validator(mode="after")
    def _topas_lp_sync(self) -> "LPFactorSynchrotron":
        problems = limit_problems(self.pp, 1e-7, 1.0, ("pp",), "pp")
        problems += limit_problems(self.mono, 1e-7, 90.0, ("mono",), "mono")
        if self.pp.refine_flag and self.mono.refine_flag:
            problems.append(custom_error(
                "topas_lp_sync_correlated",
                "pp and mono are ~100 % correlated (TOPAS.INC: do not attempt to refine both together); "
                "refine at most one of them", ("mono",), self.mono.model_dump()))
        raise_problems(type(self).__name__, problems)
        return self


class SimpleAxialModel(CoreModel):
    """TOPAS ``Simple_Axial_Model``: one axial length; reads ``Rs``."""

    axial_length_mm: P = Field(json_schema_extra=unit_schema(UNIT_MILLIMETRE), description="Axial divergence length")


class FullAxialModel(CoreModel):
    """TOPAS ``Full_Axial_Model`` (``axial_conv``); reads ``Rp`` and ``Rs``. Soller angles left out: no Soller slit."""

    filament_length: P = Field(json_schema_extra=unit_schema(UNIT_MILLIMETRE))
    sample_length: P = Field(json_schema_extra=unit_schema(UNIT_MILLIMETRE))
    receiving_slit_length: P = Field(json_schema_extra=unit_schema(UNIT_MILLIMETRE))
    primary_soller_angle: Optional[P] = Field(default=None, json_schema_extra=absent_not_null_schema(UNIT_DEGREE))
    secondary_soller_angle: Optional[P] = Field(default=None, json_schema_extra=absent_not_null_schema(UNIT_DEGREE))
    axial_n_beta: CoreInt = Field(gt=0, description="TOPAS 'axial_n_beta': rays per point source")

    _not_null = field_validator("primary_soller_angle", "secondary_soller_angle", mode="before")(absent_not_null)

    @model_serializer(mode="wrap")
    def _omit_absent(self, handler):
        return omit_absent(handler(self), self, ("primary_soller_angle", "secondary_soller_angle"))

    @model_validator(mode="after")
    def _topas_axial(self) -> "FullAxialModel":
        problems = []
        for name in ("filament_length", "sample_length", "receiving_slit_length",
                     "primary_soller_angle", "secondary_soller_angle"):
            problems += limit_problems(getattr(self, name), *KEYWORD_LIMITS["axial"], (name,), name)
        raise_problems(type(self).__name__, problems)
        return self


class Capillary(CoreModel):
    """TOPAS capillary absorption (TOPAS 6 keywords; the focusing-beam keywords are TOPAS 7 only)."""

    diameter_mm: P = Field(json_schema_extra=unit_schema(UNIT_MILLIMETRE), description="TOPAS 'capillary_diameter_mm'")
    u_cm_inv: P = Field(json_schema_extra=unit_schema(UNIT_INV_CM),
                        description="TOPAS 'capillary_u_cm_inv': linear absorption coefficient")
    beam: Literal["parallel", "divergent"] = Field(
        description="TOPAS 'capillary_parallel_beam' or 'capillary_divergent_beam' (the capillary is assumed "
                    "fully illuminated)")


class Corrections(CoreModel):
    """Instrument corrections, keyed by TOPAS macro; a correction left out is not applied."""

    Zero_Error: Optional[ZeroError] = Field(default=None, json_schema_extra=absent_not_null_schema())
    LP_Factor: Optional[LPFactor] = Field(default=None, json_schema_extra=absent_not_null_schema())
    LP_Factor_Synchrotron: Optional[LPFactorSynchrotron] = Field(default=None,
                                                                 json_schema_extra=absent_not_null_schema())
    Simple_Axial_Model: Optional[SimpleAxialModel] = Field(default=None, json_schema_extra=absent_not_null_schema())
    Full_Axial_Model: Optional[FullAxialModel] = Field(default=None, json_schema_extra=absent_not_null_schema())
    capillary: Optional[Capillary] = Field(default=None, json_schema_extra=absent_not_null_schema())

    _not_null = field_validator("Zero_Error", "LP_Factor", "LP_Factor_Synchrotron", "Simple_Axial_Model",
                                "Full_Axial_Model", "capillary", mode="before")(absent_not_null)

    @model_serializer(mode="wrap")
    def _omit_absent(self, handler):
        return omit_absent(handler(self), self, tuple(type(self).model_fields))

    @model_validator(mode="after")
    def _topas_corrections(self) -> "Corrections":
        problems = []
        for a, b in (("LP_Factor", "LP_Factor_Synchrotron"), ("Simple_Axial_Model", "Full_Axial_Model")):
            if getattr(self, a) is not None and getattr(self, b) is not None:
                problems.append(custom_error("topas_exclusive", "{a} and {b} model the same effect; state one of them",
                                       (b,), getattr(self, b).model_dump(), a=a, b=b))
        if self.LP_Factor is not None:
            problems += limit_problems(self.LP_Factor.monochromator_angle, 1e-4, 90.0,
                                       ("LP_Factor", "monochromator_angle"), "monochromator_angle")
        if self.Simple_Axial_Model is not None:
            problems += limit_problems(self.Simple_Axial_Model.axial_length_mm, 1e-4, 50.0,
                                       ("Simple_Axial_Model", "axial_length_mm"), "axial_length_mm")
        if self.capillary is not None:
            problems += _positive(self.capillary.diameter_mm, ("capillary", "diameter_mm"), "diameter_mm")
        raise_problems(type(self).__name__, problems)
        return self


#: Instrument peak types (TOPAS.INC macros, A141) and their parameters, in macro argument order.
PEAK_TYPES = {
    "TCHZ_Peak_Type": ("U", "V", "W", "Z", "X", "Y"),
    "PV_Peak_Type": ("ha", "hb", "hc", "lora", "lorb", "lorc"),
    "PVII_Peak_Type": ("ha", "hb", "hc", "ma", "mb", "mc"),
}

#: TOPAS.INC limits on a refined peak-type parameter (fixed parts).
PEAK_TYPE_LIMITS = {
    "TCHZ_Peak_Type": {"U": (-1.0, 2.0), "V": (-1.0, 2.0), "W": (-1.0, 2.0), "Z": (-1.0, 2.0),
                       "X": (1e-4, 2.0), "Y": (1e-4, 2.0)},
    "PV_Peak_Type": {"ha": (1e-4, None), "hb": (1e-4, None), "hc": (1e-4, None), "lora": (1e-4, 1.0),
                     "lorb": (1e-4, None), "lorc": (1e-4, None)},
    "PVII_Peak_Type": {"ha": (1e-4, 1.0), "hb": (1e-4, 1.0), "hc": (1e-4, 1.0), "ma": (1e-4, 20.0),
                       "mb": (1e-4, 5.0), "mc": (1e-4, 5.0)},
}


def _named_parameters(params: dict, expected: tuple[str, ...], loc: tuple, owner: str) -> list[InitErrorDetails]:
    problems = []
    for name in expected:
        if name not in params:
            problems.append(custom_error("missing_parameter", "{owner} needs parameter '{name}' (expected: {names})",
                                   loc, sorted(params), owner=owner, name=name, names=", ".join(expected)))
    for name in params:
        if name not in expected:
            problems.append(custom_error("unexpected_parameter", "{owner} has no parameter '{name}' (expected: {names})",
                                   loc + (name,), params[name].model_dump(), owner=owner, name=name,
                                   names=", ".join(expected)))
    return problems


class InstrumentBroadening(CoreModel):
    """Instrument peak type (TOPAS.INC macro) and its parameters.

    ``TCHZ_Peak_Type``: U, V, W, Z (degree^2 2theta), X, Y (degree 2theta);
    Gamma_G = |U tan^2 + V tan + W + Z/cos^2|^0.5 (TOPAS takes the absolute
    value, EB-55), Gamma_L = X tan + Y/cos. These letters are not GSAS-II's.
    ``PV_Peak_Type``: fwhm = ha + hb tan + hc/cos (degree 2theta), eta = lora +
    lorb tan + lorc/cos. ``PVII_Peak_Type``: half-widths h1 = h2 = ha + hb/cos +
    hc tan (degree 2theta), m = 0.6 + ma + mb/cos + mc tan (EB-56).
    """

    peak_type: Literal["TCHZ_Peak_Type", "PV_Peak_Type", "PVII_Peak_Type"]
    parameters: dict[str, P]

    @model_validator(mode="after")
    def _topas_peak_type(self) -> "InstrumentBroadening":
        expected = PEAK_TYPES[self.peak_type]
        problems = _named_parameters(self.parameters, expected, ("parameters",), self.peak_type)
        for name, (lo, hi) in PEAK_TYPE_LIMITS[self.peak_type].items():
            problems += limit_problems(self.parameters.get(name), lo, hi, ("parameters", name), name)
        raise_problems(type(self).__name__, problems)
        return self


class Instrument(CoreModel):
    """The instrument: emission line, radii, corrections, peak type."""

    description: Optional[str] = Field(default=None, json_schema_extra=absent_not_null_schema(),
                                       description="Free text, e.g. the beamline")
    radiation: Radiation
    geometry: Optional[Geometry] = Field(default=None, json_schema_extra=absent_not_null_schema(),
                                         description="Required with an axial model, else left out")
    corrections: Optional[Corrections] = Field(default=None, json_schema_extra=absent_not_null_schema(),
                                               description="Left out: no corrections")
    broadening: InstrumentBroadening

    _not_null = field_validator("description", "geometry", "corrections", mode="before")(absent_not_null)

    @model_serializer(mode="wrap")
    def _omit_absent(self, handler):
        return omit_absent(handler(self), self, ("description", "geometry", "corrections"))

    @model_validator(mode="after")
    def _topas_geometry(self) -> "Instrument":
        c = self.corrections
        need_rs = c is not None and (c.Simple_Axial_Model is not None or c.Full_Axial_Model is not None)
        need_rp = c is not None and c.Full_Axial_Model is not None
        g = self.geometry
        problems = []
        for name, needed, reader in (("Rs", need_rs, "Simple_Axial_Model or Full_Axial_Model"),
                                     ("Rp", need_rp, "Full_Axial_Model")):
            value = None if g is None else getattr(g, name)
            if needed and value is None:
                problems.append(custom_error("topas_radius_needed", "{reader} reads the radius {name}; state "
                                       "geometry.{name}", ("geometry", name), None, reader=reader, name=name))
            elif not needed and value is not None:
                problems.append(custom_error("topas_radius_unused", "geometry.{name} is read only by {reader}, which "
                                       "this recipe does not use; leave it out", ("geometry", name), value,
                                       reader=reader, name=name))
        raise_problems(type(self).__name__, problems)
        return self


# --- background (A142; C17, C18) ------------------------------------------------

#: Parameters of a background peak's own peak type (TR p. 39).
BACKGROUND_PEAK_TYPES = {
    "pv": ("pv_fwhm", "pv_lor"),
    "spv": ("spv_h1", "spv_h2", "spv_l1", "spv_l2"),
    "spvii": ("h1", "h2", "m1", "m2"),
}
_WIDTHS = ("pv_fwhm", "spv_h1", "spv_h2", "h1", "h2")


class BackgroundPeak(CoreModel):
    """A background peak: one TOPAS ``xo_Is`` phase with its own peak type (no instrument profile)."""

    xo: P = Field(json_schema_extra=unit_schema(UNIT_DEG_2THETA), description="Position, inside the fit window")
    I: P = Field(json_schema_extra=unit_schema(UNIT_ARBITRARY), description="Intensity")  # noqa: E741  TOPAS's name
    peak_type: Literal["pv", "spv", "spvii"]
    parameters: dict[str, P] = Field(description="pv: pv_fwhm, pv_lor; spv: spv_h1, spv_h2, spv_l1, spv_l2; "
                                                 "spvii: h1, h2, m1, m2 (widths in degree 2theta)")

    @model_validator(mode="after")
    def _topas_background_peak(self) -> "BackgroundPeak":
        problems = _named_parameters(self.parameters, BACKGROUND_PEAK_TYPES[self.peak_type], ("parameters",),
                                     f"peak type {self.peak_type!r}")
        problems += limit_problems(self.I, *KEYWORD_LIMITS["I"], ("I",), "I")
        for name, p in self.parameters.items():
            if name in _WIDTHS:
                problems += _positive(p, ("parameters", name), name)
            if name in KEYWORD_LIMITS:
                problems += limit_problems(p, *KEYWORD_LIMITS[name], ("parameters", name), name)
        raise_problems(type(self).__name__, problems)
        return self


class Background(CoreModel):
    """Background: Chebyshev (TOPAS ``bkg``), ``One_on_X``, background peaks; at least one, each optional.

    TOPAS's Chebyshev polynomials T_n(t) map the fit window (first to last
    calculated point within ``start_X..finish_X``) onto t = -1..1 (C18).
    """

    chebyshev: Optional[ChebyshevBackground] = Field(default=None, json_schema_extra=absent_not_null_schema())
    One_on_X: Optional[P] = Field(default=None, json_schema_extra=absent_not_null_schema(UNIT_ARBITRARY),
                                  description="TOPAS One_on_X: fit_obj = value / X")
    peaks: Optional[list[BackgroundPeak]] = Field(default=None, min_length=1,
                                                  json_schema_extra=absent_not_null_schema())

    _not_null = field_validator("chebyshev", "One_on_X", "peaks", mode="before")(absent_not_null)

    @model_serializer(mode="wrap")
    def _omit_absent(self, handler):
        return omit_absent(handler(self), self, ("chebyshev", "One_on_X", "peaks"))

    @model_validator(mode="after")
    def _topas_background(self) -> "Background":
        if self.chebyshev is None and self.One_on_X is None and self.peaks is None:
            raise ValueError("background states nothing; leave the block out for no background")
        raise_problems(type(self).__name__, limit_problems(self.One_on_X, 1e-4, None, ("One_on_X",), "One_on_X"))
        return self


# --- phase (A93, A142) ------------------------------------------------------------


class SizeBroadening(CoreModel):
    """Isotropic crystallite-size broadening: TOPAS ``CS_L`` / ``CS_G`` (nm; at least one).

    Not a crystallite size: TOPAS reports LVol-IB and LVol-FWHM from these (TR p. 160, EB-57).
    """

    model: Literal["isotropic"]
    CS_L: Optional[P] = Field(default=None, json_schema_extra=absent_not_null_schema(UNIT_NANOMETRE))
    CS_G: Optional[P] = Field(default=None, json_schema_extra=absent_not_null_schema(UNIT_NANOMETRE))

    _not_null = field_validator("CS_L", "CS_G", mode="before")(absent_not_null)

    @model_serializer(mode="wrap")
    def _omit_absent(self, handler):
        return omit_absent(handler(self), self, ("CS_L", "CS_G"))

    @model_validator(mode="after")
    def _topas_size(self) -> "SizeBroadening":
        if self.CS_L is None and self.CS_G is None:
            raise ValueError("size_broadening needs CS_L, CS_G or both")
        problems = []
        for name in ("CS_L", "CS_G"):
            p = getattr(self, name)
            problems += _positive(p, (name,), name)
            problems += limit_problems(p, 0.3, 10000.0, (name,), name)
        raise_problems(type(self).__name__, problems)
        return self


class StrainBroadening(CoreModel):
    """Isotropic microstrain broadening: TOPAS ``Strain_L`` / ``Strain_G`` (degree 2theta; at least one).

    Not a strain: TOPAS reports e0 from these (TR p. 160, EB-57).
    """

    model: Literal["isotropic"]
    Strain_L: Optional[P] = Field(default=None, json_schema_extra=absent_not_null_schema(UNIT_DEG_2THETA))
    Strain_G: Optional[P] = Field(default=None, json_schema_extra=absent_not_null_schema(UNIT_DEG_2THETA))

    _not_null = field_validator("Strain_L", "Strain_G", mode="before")(absent_not_null)

    @model_serializer(mode="wrap")
    def _omit_absent(self, handler):
        return omit_absent(handler(self), self, ("Strain_L", "Strain_G"))

    @model_validator(mode="after")
    def _topas_strain(self) -> "StrainBroadening":
        if self.Strain_L is None and self.Strain_G is None:
            raise ValueError("strain_broadening needs Strain_L, Strain_G or both")
        problems = []
        for name in ("Strain_L", "Strain_G"):
            p = getattr(self, name)
            problems += _positive(p, (name,), name, allow_zero=True)
            problems += limit_problems(p, 1e-4, 5.0, (name,), name)
        raise_problems(type(self).__name__, problems)
        return self


class PeakBroadening(CoreModel):
    """Sample broadening (the gsasii shape, A142); a part left out is not modelled (TOPAS adds none)."""

    size_broadening: Optional[SizeBroadening] = Field(default=None, json_schema_extra=absent_not_null_schema())
    strain_broadening: Optional[StrainBroadening] = Field(default=None, json_schema_extra=absent_not_null_schema())

    _not_null = field_validator("size_broadening", "strain_broadening", mode="before")(absent_not_null)

    @model_serializer(mode="wrap")
    def _omit_absent(self, handler):
        return omit_absent(handler(self), self, ("size_broadening", "strain_broadening"))

    @model_validator(mode="after")
    def _topas_broadening(self) -> "PeakBroadening":
        if self.size_broadening is None and self.strain_broadening is None:
            raise ValueError("peak_broadening states nothing; leave the block out for no sample broadening")
        return self


class TopasPhase(Phase[BoundedRefinableParameter]):
    """A topas phase: core's space group, cell and atoms, plus ``scale`` and ``peak_broadening``.

    TOPAS rules: a setting TOPAS reads as itself (EB-43); refined cell, ``Uiso``
    (as beq) and ``scale`` starts within TOPAS's fixed default limits where no
    bound is stated (A138).
    """

    scale: P = Field(json_schema_extra=unit_schema(UNIT_ARBITRARY), description="Phase scale factor (TOPAS magnitude), > 0")
    peak_broadening: Optional[PeakBroadening] = Field(default=None, json_schema_extra=absent_not_null_schema(),
                                                      description="Left out: no sample broadening")
    scattering_types: Optional[dict[str, str]] = Field(
        default=None, json_schema_extra=absent_not_null_schema(),
        description="Ionic scattering types: not yet available for TOPAS (a validation error until the TOPAS "
                    "path has been verified on a TOPAS machine)")
    preferred_orientation: Optional[MarchDollase[BoundedRefinableParameter]] = Field(
        default=None, json_schema_extra=absent_not_null_schema(),
        description="March-Dollase preferred orientation: not yet available for TOPAS (a validation error until "
                    "the PO(...) macro path has been verified on a TOPAS machine)")

    _topas_not_null = field_validator("peak_broadening", "scattering_types", "preferred_orientation",
                                      mode="before")(absent_not_null)

    @model_serializer(mode="wrap")
    def _topas_omit_absent(self, handler):
        data = handler(self)
        if self.peak_broadening is None:
            data.pop("peak_broadening", None)
        if self.scattering_types is None:
            data.pop("scattering_types", None)
        if self.preferred_orientation is None:
            data.pop("preferred_orientation", None)
        return data

    @model_validator(mode="after")
    def _topas_no_ions(self) -> "TopasPhase":
        if self.scattering_types is not None:
            raise_problems(type(self).__name__, [custom_error(
                "topas_ions_unavailable",
                "ionic scattering types are not yet available for TOPAS: TOPAS spells them 'Fe+3' in occ and "
                "reports an unknown ion only on its console, and that path has not yet been verified on a TOPAS "
                "machine; use the neutral elements, or a gsasii / easydiffraction (cryspy) recipe",
                ("scattering_types",), self.scattering_types)])
        if self.preferred_orientation is not None:
            raise_problems(type(self).__name__, [custom_error(
                "topas_po_unavailable",
                "preferred orientation is not yet available for TOPAS: the PO(...) March-Dollase macro, its bounds "
                "and the read-back of the refined r have not yet been verified on a TOPAS machine; leave "
                "preferred_orientation out, or use a gsasii / easydiffraction (cryspy) recipe",
                ("preferred_orientation",), self.preferred_orientation.model_dump())])
        return self

    @field_validator("space_group")
    @classmethod
    def _topas_setting(cls, v: str) -> str:
        topas_space_group(v)
        return v

    @model_validator(mode="after")
    def _topas_limits(self) -> "TopasPhase":
        problems = _positive(self.scale, ("scale",), "scale")
        problems += limit_problems(self.scale, *KEYWORD_LIMITS["scale"], ("scale",), "scale")
        for name in ("a", "b", "c"):
            problems += limit_problems(getattr(self.unit_cell, name), *KEYWORD_LIMITS["cell_length"],
                                       ("unit_cell", name), name)
        for name in ("alpha", "beta", "gamma"):
            problems += limit_problems(getattr(self.unit_cell, name), *KEYWORD_LIMITS["cell_angle"],
                                       ("unit_cell", name), name)
        lo, hi = KEYWORD_LIMITS["beq"]
        for label, atom in self.atoms.items():
            if atom.Uiso is not None:
                problems += limit_problems(atom.Uiso, lo / EIGHT_PI_SQ, hi / EIGHT_PI_SQ, ("atoms", label, "Uiso"),
                                           f"Uiso (TOPAS beq = 8 pi^2 Uiso, limits {lo:g}..{hi:g})")
        raise_problems(type(self).__name__, problems)
        return self


# --- single peak fitting (A13.3) ---------------------------------------------------


class SinglePeak(CoreModel):
    """One single peak: a TOPAS ``xo_Is`` with the instrument peak type convolved with its own sample widths."""

    xo: P = Field(json_schema_extra=unit_schema(UNIT_DEG_2THETA), description="Position, inside the fit window")
    I: P = Field(json_schema_extra=unit_schema(UNIT_ARBITRARY), description="Intensity")  # noqa: E741  TOPAS's name
    gauss_fwhm: Optional[P] = Field(default=None, json_schema_extra=absent_not_null_schema(UNIT_DEG_2THETA),
                                    description="Sample Gaussian FWHM, >= 0; left out: not convolved")
    lor_fwhm: Optional[P] = Field(default=None, json_schema_extra=absent_not_null_schema(UNIT_DEG_2THETA),
                                  description="Sample Lorentzian FWHM, >= 0; left out: not convolved")

    _not_null = field_validator("gauss_fwhm", "lor_fwhm", mode="before")(absent_not_null)

    @model_serializer(mode="wrap")
    def _omit_absent(self, handler):
        return omit_absent(handler(self), self, ("gauss_fwhm", "lor_fwhm"))

    @model_validator(mode="after")
    def _topas_single_peak(self) -> "SinglePeak":
        problems = limit_problems(self.I, *KEYWORD_LIMITS["I"], ("I",), "I")
        for name in ("gauss_fwhm", "lor_fwhm"):  # a negative FWHM stops TOPAS (C24)
            problems += _positive(getattr(self, name), (name,), name, allow_zero=True)
        raise_problems(type(self).__name__, problems)
        return self


# --- payloads and recipes -----------------------------------------------------------


class RefinementControls(CoreModel):
    """Refinement controls, all stated (no defaults). ``iters == 0`` is a simulation (nothing refined)."""

    iters: CoreInt = Field(ge=0, description="TOPAS 'iters': maximum iterations; 0 = calculate only")
    chi2_convergence_criteria: CoreFloat = Field(gt=0, description="TOPAS 'chi2_convergence_criteria'")
    x_calculation_step: CoreFloat = Field(gt=0, json_schema_extra=unit_schema(UNIT_DEG_2THETA),
                                          description="TOPAS 'x_calculation_step' (required for .xye data)")


class _Payload(CoreModel):
    """Fields both topas workflows share."""

    xrd_data: XRDData
    fit_range: Optional[FitRange] = Field(default=None, json_schema_extra=absent_not_null_schema(),
                                          description="Left out: the data's full 2theta range")
    instrument: Instrument
    background: Optional[Background] = Field(default=None, json_schema_extra=absent_not_null_schema(),
                                             description="Left out: no background")
    refinement_controls: RefinementControls

    _not_null = field_validator("fit_range", "background", mode="before")(absent_not_null)

    @model_serializer(mode="wrap")
    def _omit_absent(self, handler):
        return omit_absent(handler(self), self, ("fit_range", "background"))

    def window(self) -> tuple[float, float]:
        """The fit window: ``fit_range``, open ends at the data limits."""
        return fit_window(self.fit_range, self.xrd_data)

    @model_validator(mode="after")
    def _payload_rules(self) -> "_Payload":
        problems = fit_range_problems(self.fit_range, self.xrd_data)
        if self.background is not None and self.background.peaks is not None:
            problems += self._outside_window([p.xo for p in self.background.peaks],
                                             lambda i: ("background", "peaks", i, "xo"), "background peak")
        problems += self._zero_error_envelope()
        problems += self._workflow_problems()
        if self.refinement_controls.iters == 0:  # simulation: nothing refined
            problems += refined_flag_problems(self, "iters is 0 (a simulation), so nothing may be refined; "
                                                    "set this refine flag to false")
        raise_problems(type(self).__name__, problems)
        return self

    def _outside_window(self, positions: list[P], loc, what: str) -> list[InitErrorDetails]:
        return outside_window_problems(positions, self.window(), loc, what)

    def _zero_error_envelope(self) -> list[InitErrorDetails]:
        """TOPAS.INC ``ZE``: a refined zero error stays within 100 data steps of 0 (fixed envelope, A138)."""
        c = self.instrument.corrections
        if c is None or c.Zero_Error is None:
            return []
        tth = self.xrd_data.tth
        lo_step, hi_step = tth[1] - tth[0], tth[-1] - tth[-2]
        return limit_problems(c.Zero_Error.th2_offset, -100 * lo_step, 100 * hi_step,
                              ("instrument", "corrections", "Zero_Error", "th2_offset"),
                              "th2_offset (TOPAS ZE: within 100 data steps)")

    def _workflow_problems(self) -> list[InitErrorDetails]:
        return []


class RietveldPayload(_Payload):
    """``topas.rietveld`` payload."""

    phases: dict[CoreName, TopasPhase] = Field(min_length=1, json_schema_extra=name_keyed)

    _phase_names = field_validator("phases")(unique_phase_names)

    def warnings(self) -> list[StructuredWarning]:
        """Uiso emitted as TOPAS beq (A67, D8): one warning per atom, paths relative to the payload."""
        found = []
        for name, phase in self.phases.items():
            for label, atom in phase.atoms.items():
                if atom.Uiso is None:
                    continue
                found.append(StructuredWarning(
                    code="topas_adp_converted",
                    message=(f"Uiso {atom.Uiso.value:g} A^2 is written to TOPAS as beq = 8 pi^2 Uiso = "
                             f"{EIGHT_PI_SQ * atom.Uiso.value:.6g} A^2 (bounds likewise); results report Uiso"),
                    field_path=f"phases.{name}.atoms.{label}.Uiso",
                ))
        return found


class SpfPayload(_Payload):
    """``topas.spf`` payload: single peak fitting, no phases (A13.3)."""

    single_peaks: list[SinglePeak] = Field(min_length=1)

    def _workflow_problems(self) -> list[InitErrorDetails]:
        return self._outside_window([p.xo for p in self.single_peaks], lambda i: ("single_peaks", i, "xo"),
                                    "single peak")


def check_engine_version(engine_version: str) -> None:
    """``ValueError`` unless ``engine_version`` is in :data:`SUPPORTED_ENGINE_VERSIONS` (A144)."""
    try:
        version = Version(engine_version)
        supported = SpecifierSet(SUPPORTED_ENGINE_VERSIONS)
    except (InvalidVersion, InvalidSpecifier) as exc:
        raise ValueError(f"engine_version {engine_version!r} is not a version: {exc}") from exc
    if version not in supported:
        raise ValueError(f"engine_version {engine_version!r}: topas engine schema {ENGINE_SCHEMA_VERSION} supports "
                         f"TOPAS {SUPPORTED_ENGINE_VERSIONS}")


class _TopasRecipe(EngineRecipe):
    gateway_name: ClassVar[str] = "topas"
    schema_declarations: ClassVar[Mapping[str, Any]] = DECLARATIONS

    engine_version: StrictStr = Field(description="TOPAS major version the recipe is written for, e.g. '6'")

    @field_validator("engine_version")
    @classmethod
    def _engine_version(cls, v: str) -> str:
        check_engine_version(v)
        return v


class TopasRietveldRecipe(_TopasRecipe):
    """A ``topas.rietveld`` recipe."""

    schema_name: Literal["topas.rietveld"]
    payload: RietveldPayload


class TopasSpfRecipe(_TopasRecipe):
    """A ``topas.spf`` recipe."""

    schema_name: Literal["topas.spf"]
    payload: SpfPayload


TopasRecipe = Annotated[Union[TopasRietveldRecipe, TopasSpfRecipe], Field(discriminator="schema_name")]
validate_recipe = recipe_validator({"topas.rietveld": TopasRietveldRecipe, "topas.spf": TopasSpfRecipe},
                                   engine="topas", title="TopasRecipe")
