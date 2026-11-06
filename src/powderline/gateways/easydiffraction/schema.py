"""easydiffraction engine schema ``easydiffraction.rietveld`` (engine schema 0.1.0, easydiffraction 0.21.1).

Built on the core schema (:mod:`powderline.schema_core`): a recipe is a
:class:`~powderline.schema_core.CoreRecipe`, a phase a
``Phase[BoundedRefinableParameter]`` with ``scale`` flat in the same block
(A93). Every refinable is ``[value, refine_flag, min, max]`` (A20); a ``null``
bound keeps easydiffraction's physical limit on that side, a stated one
replaces it (A157 B4). Names and units are easydiffraction's own (A4):
``setup_wavelength``, ``calib_twotheta_offset``, ``broad_gauss_u`` (deg^2),
...; the blocks follow gsasii's A103 layout where they fit. Invalid recipes
raise pydantic's ``ValidationError`` with every problem at its location (A70).

Engine-free: imports nothing of easydiffraction, so ``validate()`` runs in the
core-only environment. The runtime layer consumes the validated model (A39).
Design: devkit ``tasks/re06-easydiffraction-schema-draft.md``; engine behaviour:
``engine-behavior-register.md`` (EB-42..EB-47, EB-70..).

The instrument blocks expose every correction easydiffraction models for
constant-wavelength X-ray powder data (A160), including ones PowderLine does
not support for its own data yet (the Kα doublet): a left-out optional block is
not modelled (the engine's neutral value). The calculator is chosen in
``refinement_controls`` (A162): CrysPy and CrysFML differ in what they
compute, so the choice is part of the recipe.

easydiffraction rules checked here:

- the space group must be a setting easydiffraction has (EB-42) and one the
  chosen calculator computes correctly, for a general position and every special
  site (EB-80, A174: established by computation; CrysFML misreads most
  non-default settings, CrysPy computes special positions wrongly in nine
  origin-choice-1 settings);
- a value outside easydiffraction's physical limits is refused by the engine
  even when fixed, so it is an error (cell lengths 0..30 A, angles 0..180 deg,
  occupancy 0..1, Uiso and U11/U22/U33 0..10 A^2, wavelength, scale and
  absorption mu_r >= 0; EB-71; A111, A157 B4);
- wavelength > 0 (A126); scale >= 0 (A161: a phase may contribute nothing);
- a data point handed to the engine has a weight <= 1e8 (sigma >= 1e-4):
  easydiffraction replaces a smaller sigma with 1.0 silently (A159), and an
  intensity >= 0: easydiffraction refuses a negative one (EB-91, A177);
- the peak type must be one the calculator computes; ``cutoff_fwhm`` is a
  CrysPy setting (CrysFML ignores it) (A162, A127 principle);
- ``Uaniso`` needs the cryspy calculator: easydiffraction hands CrysFML only
  B = 8 pi^2 Ueq, so the tensor would have no effect (EB-23, A127 principle);
- the stated profile makes no peak width negative within ``WIDTH_MARGIN`` of the
  fit window, widened by the stated position corrections (Gaussian FWHM^2 or
  Lorentzian FWHM): easydiffraction would compute a wrong pattern without a
  message, also from a reflection just outside the window (EB-87, A171, A178);
- the Kα2 wavelength and its intensity ratio are stated together;
- ``scattering_types`` (CIF spelling, ions CrysPy has a form factor for, EB-95)
  and ``preferred_orientation`` (March-Dollase with the required
  ``march_random_fract``; stated bounds inside the engine's own limits) need
  the cryspy calculator: CrysFML computes neutral atoms only (EB-96) and
  ignores preferred orientation (EB-97) (P-47, P-48);
- simulation = no refine flag set (lmfit is not run).
"""

from __future__ import annotations

from typing import Annotated, Any, ClassVar, Literal, Mapping, Optional, Union

import numpy as np
from pydantic import Field, field_validator, model_serializer, model_validator
from pydantic_core import InitErrorDetails

from powderline.compat import schema_declarations
from powderline.gateways.easydiffraction.space_group_support import CRYSFML_SETTINGS, CRYSPY_SETTINGS
from powderline.gateways.easydiffraction.space_group_table import SPACE_GROUPS
from powderline.gateways.easydiffraction.scattering import CRYSPY_IONS, ENGINE_LABEL as SCATTERING_ENGINE_LABEL
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
    Phase,
    XRDData,
    absent_not_null,
    absent_not_null_schema,
    custom_error,
    fit_limits_on_data,
    fit_range_problems,
    name_keyed,
    omit_absent,
    MarchDollase,
    raise_problems,
    scattering_type_problems,
    recipe_validator,
    refined_flags,
    unique_phase_names,
    unit_schema,
)

P = BoundedRefinableParameter

# --- versions (A65) -------------------------------------------------------------

ENGINE_SCHEMA_VERSION = "0.1.0"
SUPPORTED_ENGINE_SCHEMAS = "==0.1.0"
REQUIRES_CORE_SCHEMA = "==0.1.0"

#: The gateway's schema declarations (``capabilities()`` keys, A65). No engine
#: version in the recipe: the library is pinned and read at run time (A157 B2).
DECLARATIONS = schema_declarations(
    engine_schema_version=ENGINE_SCHEMA_VERSION,
    supported_engine_schemas=SUPPORTED_ENGINE_SCHEMAS,
    requires_core_schema=REQUIRES_CORE_SCHEMA,
)

SCHEMA_NAMES = ("easydiffraction.rietveld",)

# --- units (easydiffraction's own, A4) ---------------------------------------------

UNIT_DEGREE2 = "degree^2"
UNIT_DIMENSIONLESS = "dimensionless"

#: Largest data weight easydiffraction keeps: it replaces sigma < 1e-4 by 1.0 (EB-73, A159).
MAX_WEIGHT = 1e8

#: How far outside the fit window (deg 2theta) peak widths must be >= 0 (A178): easydiffraction computes
#: reflections beyond the window whose tails reach it (EB-70), and a negative width there distorts or drops
#: them silently (EB-87). The stated position corrections widen it further (they move reflections).
WIDTH_MARGIN = 1.0
#: Spacing of the 2theta grid on which the widths are checked, besides the points handed to the engine.
WIDTH_GRID_STEP = 0.01

#: easydiffraction's physical limits (min, max) on values (EB-71; ``None`` = none). The
#: engine refuses a value outside them at input, fixed or refined, and gives an
#: unbounded side of a refined parameter its physical limit.
PHYSICAL_LIMITS = {
    "cell_length": (0.0, 30.0),
    "cell_angle": (0.0, 180.0),
    "occupancy": (0.0, 1.0),
    "adp": (0.0, 10.0),
    "nonnegative": (0.0, None),
}


def negative_widths(u: float, v: float, w: float, x: float, y: float, tth) -> dict[str, tuple[float, float]]:
    """2theta range (first, last point of ``tth``) where a peak width is negative, per width.

    The Gaussian FWHM^2 is U tan^2 theta + V tan theta + W, the Lorentzian FWHM X tan theta + Y / cos theta
    (both calculators, EB-76). Where either is negative easydiffraction computes a wrong pattern without a
    message: CrysFML drops those peaks, CrysPy distorts them (EB-87, A171).
    """
    tth = np.asarray(tth, dtype=float)
    theta = np.radians(tth / 2)
    tan, cos = np.tan(theta), np.cos(theta)
    out = {}
    for kind, width in (("Gaussian FWHM^2 (U tan^2 + V tan + W)", u * tan ** 2 + v * tan + w),
                        ("Lorentzian FWHM (X tan + Y / cos)", x * tan + y / cos)):
        bad = tth[width < 0]
        if bad.size:
            out[kind] = (float(bad.min()), float(bad.max()))
    return out


def profile_negative_widths(values, tth) -> dict[str, tuple[float, float]]:
    """:func:`negative_widths` for an object carrying ``broad_gauss_u`` ... ``broad_lorentz_y`` values."""
    return negative_widths(*(float(values(name)) for name in (
        "broad_gauss_u", "broad_gauss_v", "broad_gauss_w", "broad_lorentz_x", "broad_lorentz_y")), tth)


def width_check_points(tth, shifts=()) -> tuple[np.ndarray, float]:
    """2theta values where the peak widths must be >= 0, and the margin used (A178).

    The points handed to the engine (``tth``) and a ``WIDTH_GRID_STEP`` grid over the window widened by
    ``WIDTH_MARGIN`` plus the size of the position corrections ``shifts`` (zero, displacement, transparency,
    deg), kept inside (0, 179] deg.
    """
    tth = np.asarray(tth, dtype=float)
    pad = WIDTH_MARGIN + sum(abs(float(v)) for v in shifts)
    lo, hi = max(tth.min() - pad, 1e-3), min(tth.max() + pad, 179.0)
    return np.union1d(tth, np.linspace(lo, hi, int(np.ceil((hi - lo) / WIDTH_GRID_STEP)) + 1)), pad


def physical_problems(p: Optional[P], limits: tuple, loc: tuple, what: str) -> list[InitErrorDetails]:
    """A value outside easydiffraction's physical limits: the engine refuses it at input (EB-71)."""
    if p is None:
        return []
    lo, hi = limits
    if (lo is None or p.value >= lo) and (hi is None or p.value <= hi):
        return []
    span = f"[{lo:g}, {hi:g}]" if hi is not None else f">= {lo:g}"
    return [custom_error("easydiffraction_physical_limit",
                   "{what} {value} is outside easydiffraction's physical limit {span}: the engine refuses it (EB-71)",
                   loc, p.model_dump(), what=what, value=p.value, span=span)]


#: Settings each calculator computes correctly, by computation (EB-80; ``scripts/verify_easydiffraction_settings.py``).
CALCULATOR_SETTINGS = {"cryspy": CRYSPY_SETTINGS, "crysfml": CRYSFML_SETTINGS}


def calculator_setting_problem(name: str, calculator: str) -> Optional[str]:
    """Why ``calculator`` cannot use the setting ``name`` (EB-80), naming one it can; ``None`` when it can."""
    if name in CALCULATOR_SETTINGS[calculator] or name not in SPACE_GROUPS:
        return None
    number = SPACE_GROUPS[name][0]
    usable = [x for x, entry in SPACE_GROUPS.items() if entry[0] == number and x in CALCULATOR_SETTINGS[calculator]]
    usable.sort(key=lambda x: not SPACE_GROUPS[x][2])  # easydiffraction's default setting first
    other = [c for c in CALCULATOR_SETTINGS if c != calculator and name in CALCULATOR_SETTINGS[c]]
    hint = (f"transform the structure to {usable[0]!r}" if usable else "no setting of this space group is computed "
            "correctly by it")
    alt = f", or use the {other[0]} calculator" if other else ""
    return (f"the {calculator} calculator does not compute the setting {name!r} correctly (easydiffraction "
            f"misreads it, fails, or computes its special positions wrongly; EB-80, EB-77): {hint}{alt}")


def easydiffraction_space_group(name: str) -> tuple[str, str]:
    """easydiffraction's ``(name_h_m, coord_system_code)`` for a canonical name; ``ValueError`` if it has none."""
    entry = SPACE_GROUPS.get(name)
    if entry is None:
        raise ValueError(f"easydiffraction has no space-group setting equal to {name!r} (EB-42); transform the "
                         "structure to a setting easydiffraction has (e.g. the standard one)")
    return entry[0], entry[1]


# --- instrument (A103 layout, A160) ------------------------------------------------


class Radiation(CoreModel):
    """Incident radiation: one wavelength, optionally a Kα2 line (both stated or neither)."""

    setup_wavelength: P = Field(json_schema_extra=unit_schema(UNIT_ANGSTROM), description="Wavelength (Kα1), > 0")
    setup_wavelength_2: Optional[CoreFloat] = Field(
        default=None, gt=0, json_schema_extra=absent_not_null_schema(UNIT_ANGSTROM),
        description="Second wavelength (Kα2), > 0, with setup_wavelength_2_to_1_ratio; left out: one wavelength")
    setup_wavelength_2_to_1_ratio: Optional[CoreFloat] = Field(
        default=None, gt=0, le=1, json_schema_extra=absent_not_null_schema(UNIT_DIMENSIONLESS),
        description="Kα2/Kα1 intensity ratio, 0 < ratio <= 1, with setup_wavelength_2")

    _not_null = field_validator("setup_wavelength_2", "setup_wavelength_2_to_1_ratio", mode="before")(absent_not_null)

    @model_serializer(mode="wrap")
    def _omit_absent(self, handler):
        return omit_absent(handler(self), self, ("setup_wavelength_2", "setup_wavelength_2_to_1_ratio"))

    @model_validator(mode="after")
    def _easydiffraction_radiation(self) -> "Radiation":
        problems = []
        if self.setup_wavelength.value <= 0:  # A126
            problems.append(custom_error("easydiffraction_positive", "setup_wavelength must be > 0, got {value}",
                                   ("setup_wavelength",), self.setup_wavelength.model_dump(),
                                   value=self.setup_wavelength.value))
        if (self.setup_wavelength_2 is None) != (self.setup_wavelength_2_to_1_ratio is None):
            missing = "setup_wavelength_2_to_1_ratio" if self.setup_wavelength_2 is not None else "setup_wavelength_2"
            problems.append(custom_error("easydiffraction_doublet",
                                   "a Kα2 line needs both setup_wavelength_2 and setup_wavelength_2_to_1_ratio; "
                                   "state {missing} too, or leave both out", (missing,), None, missing=missing))
        raise_problems(type(self).__name__, problems)
        return self


class Polarization(CoreModel):
    """Lorentz-polarization: factor 1 - p + p cos^2(2theta_m) cos^2(2theta) (EB-75). Fixed values."""

    setup_polarization_coefficient: CoreFloat = Field(
        ge=0, le=1, json_schema_extra=unit_schema(UNIT_DIMENSIONLESS), description="p, 0..1")
    setup_monochromator_twotheta: CoreFloat = Field(
        ge=0, lt=180, json_schema_extra=unit_schema(UNIT_DEGREE), description="Monochromator 2theta_m, 0 <= 2theta_m < 180")


class Corrections(CoreModel):
    """Peak-position corrections (degrees 2theta). Displacement and transparency left out: not modeled."""

    calib_twotheta_offset: P = Field(json_schema_extra=unit_schema(UNIT_DEG_2THETA), description="Zero offset")
    calib_sample_displacement: Optional[P] = Field(
        default=None, json_schema_extra=absent_not_null_schema(UNIT_DEG_2THETA),
        description="Specimen displacement term (shift x cos 2theta)")
    calib_sample_transparency: Optional[P] = Field(
        default=None, json_schema_extra=absent_not_null_schema(UNIT_DEG_2THETA),
        description="Transparency term (shift x sin 2theta)")

    _not_null = field_validator("calib_sample_displacement", "calib_sample_transparency", mode="before")(absent_not_null)

    @model_serializer(mode="wrap")
    def _omit_absent(self, handler):
        return omit_absent(handler(self), self, ("calib_sample_displacement", "calib_sample_transparency"))


class Absorption(CoreModel):
    """Cylindrical-sample absorption (Hewat), both calculators."""

    type: Literal["cylinder-hewat"] = Field(description="easydiffraction absorption type")
    mu_r: P = Field(json_schema_extra=unit_schema(UNIT_DIMENSIONLESS), description="mu R, >= 0")

    @model_validator(mode="after")
    def _easydiffraction_mu_r(self) -> "Absorption":
        raise_problems(type(self).__name__, physical_problems(self.mu_r, PHYSICAL_LIMITS["nonnegative"], ("mu_r",), "mu_r"))
        return self


class _Broadening(CoreModel):
    """Caglioti Gaussian (FWHM^2 = U tan^2 theta + V tan theta + W) and Lorentzian (X tan theta + Y / cos theta)."""

    broad_gauss_u: P = Field(json_schema_extra=unit_schema(UNIT_DEGREE2))
    broad_gauss_v: P = Field(json_schema_extra=unit_schema(UNIT_DEGREE2))
    broad_gauss_w: P = Field(json_schema_extra=unit_schema(UNIT_DEGREE2))
    broad_lorentz_x: P = Field(json_schema_extra=unit_schema(UNIT_DEGREE))
    broad_lorentz_y: P = Field(json_schema_extra=unit_schema(UNIT_DEGREE))


class PseudoVoigtParameters(_Broadening):
    """``cwl-pseudo-voigt``: the Thompson-Cox-Hastings pseudo-Voigt, no asymmetry (EB-76)."""


class BerarBaldinozziParameters(_Broadening):
    """``cwl-pseudo-voigt-berar-baldinozzi-asymmetry``: pseudo-Voigt with empirical asymmetry (CrysPy)."""

    asym_beba_a0: P = Field(json_schema_extra=unit_schema(UNIT_DIMENSIONLESS))
    asym_beba_b0: P = Field(json_schema_extra=unit_schema(UNIT_DIMENSIONLESS))
    asym_beba_a1: P = Field(json_schema_extra=unit_schema(UNIT_DIMENSIONLESS))
    asym_beba_b1: P = Field(json_schema_extra=unit_schema(UNIT_DIMENSIONLESS))


class FcjParameters(_Broadening):
    """``cwl-thompson-cox-hastings``: pseudo-Voigt with FCJ axial-divergence asymmetry (CrysFML)."""

    asym_fcj_1: P = Field(json_schema_extra=unit_schema(UNIT_DIMENSIONLESS), description="FCJ S/L")
    asym_fcj_2: P = Field(json_schema_extra=unit_schema(UNIT_DIMENSIONLESS), description="FCJ H/L")


class _PeakProfile(CoreModel):
    cutoff_fwhm: Optional[CoreFloat] = Field(
        default=None, gt=0, json_schema_extra=absent_not_null_schema(UNIT_DIMENSIONLESS),
        description="CrysPy only: peaks computed within this many FWHM; left out: no cutoff (full tails)")

    _not_null = field_validator("cutoff_fwhm", mode="before")(absent_not_null)

    @model_serializer(mode="wrap")
    def _omit_absent(self, handler):
        return omit_absent(handler(self), self, ("cutoff_fwhm",))


class PseudoVoigt(_PeakProfile):
    peak_type: Literal["cwl-pseudo-voigt"]
    parameters: PseudoVoigtParameters


class PseudoVoigtBerarBaldinozzi(_PeakProfile):
    peak_type: Literal["cwl-pseudo-voigt-berar-baldinozzi-asymmetry"]
    parameters: BerarBaldinozziParameters


class ThompsonCoxHastings(_PeakProfile):
    peak_type: Literal["cwl-thompson-cox-hastings"]
    parameters: FcjParameters


PeakProfile = Annotated[Union[PseudoVoigt, PseudoVoigtBerarBaldinozzi, ThompsonCoxHastings],
                        Field(discriminator="peak_type")]

#: Peak types each calculator computes (EB-76).
CALCULATOR_PEAK_TYPES = {
    "cryspy": ("cwl-pseudo-voigt", "cwl-pseudo-voigt-berar-baldinozzi-asymmetry"),
    "crysfml": ("cwl-pseudo-voigt", "cwl-thompson-cox-hastings"),
}


class Instrument(CoreModel):
    """The instrument block."""

    description: Optional[str] = Field(default=None, json_schema_extra=absent_not_null_schema(),
                                       description="Free text")
    radiation: Radiation
    polarization: Optional[Polarization] = Field(default=None, json_schema_extra=absent_not_null_schema(),
                                                 description="Left out: no polarization correction (p = 0)")
    corrections: Corrections
    absorption: Optional[Absorption] = Field(default=None, json_schema_extra=absent_not_null_schema(),
                                             description="Left out: no absorption correction")
    broadening: PeakProfile

    _not_null = field_validator("description", "polarization", "absorption", mode="before")(absent_not_null)

    @model_serializer(mode="wrap")
    def _omit_absent(self, handler):
        return omit_absent(handler(self), self, ("description", "polarization", "absorption"))


# --- background ----------------------------------------------------------------------


class Background(CoreModel):
    """Chebyshev background over the fit window's first and last points (A149)."""

    chebyshev: ChebyshevBackground


# --- phase ------------------------------------------------------------------------------


class EasydiffractionMarchDollase(MarchDollase[BoundedRefinableParameter]):
    """easydiffraction's March-Dollase row: core's axis and ``ratio`` (``march_r`` > 0) plus the fraction of
    randomly oriented crystallites, ``march_random_fract`` in [0, 1] -- stated, never defaulted (P-48)."""

    march_random_fract: BoundedRefinableParameter = Field(
        description="Fraction of the sample with no preferred orientation, 0..1 (easydiffraction 'march_random_fract')")

    @field_validator("march_random_fract")
    @classmethod
    def _fraction(cls, v):
        if not 0.0 <= v.value <= 1.0:
            raise ValueError(f"march_random_fract must be within [0, 1], got {v.value}")
        return v

    @model_validator(mode="after")
    def _bounds_inside_the_engine_limits(self) -> "EasydiffractionMarchDollase":
        """A stated bound the engine would refuse (``march_r`` > 0, ``march_random_fract`` in [0, 1], its own
        ``RangeValidator``s): refused here, like a value (EB-71); ``null`` stays open."""
        template = "{what} {value} is outside easydiffraction's physical limit {span}: the engine refuses it (EB-71)"
        problems = []
        if self.ratio.min is not None and self.ratio.min <= 0:
            problems.append(custom_error("easydiffraction_physical_limit", template, ("ratio",), self.ratio.model_dump(),
                                         what="ratio min", value=self.ratio.min, span="> 0"))
        for side, outside in (("min", lambda v: v < 0.0), ("max", lambda v: v > 1.0)):
            bound = getattr(self.march_random_fract, side)
            if bound is not None and outside(bound):
                problems.append(custom_error("easydiffraction_physical_limit", template, ("march_random_fract",),
                                             self.march_random_fract.model_dump(), what=f"march_random_fract {side}",
                                             value=bound, span="[0, 1]"))
        if problems:
            raise_problems(type(self).__name__, problems)
        return self


class EasydiffractionPhase(Phase[BoundedRefinableParameter]):
    """An easydiffraction phase: core's space group, cell and atoms, plus ``scale``.

    easydiffraction rules: a setting easydiffraction has (EB-42); values inside
    its physical limits (EB-71); ``scale >= 0`` (A161).
    """

    scale: P = Field(json_schema_extra=unit_schema(UNIT_ARBITRARY), description="Phase scale factor, >= 0")
    scattering_types: Optional[dict[str, str]] = Field(
        default=None, json_schema_extra=absent_not_null_schema(),
        description="Ionic X-ray scattering types by atom label, CIF spelling ('La3+', 'O1-'); an atom left out "
                    "scatters as the neutral element; cryspy calculator only, and only ions CrysPy has")
    preferred_orientation: Optional[EasydiffractionMarchDollase] = Field(
        default=None, json_schema_extra=absent_not_null_schema(),
        description="March-Dollase preferred orientation (one axis, march_r > 0, march_random_fract 0..1); cryspy "
                    "calculator only -- CrysFML ignores it; left out: none")

    _easydiffraction_not_null = field_validator("scattering_types", "preferred_orientation", mode="before")(absent_not_null)

    @model_serializer(mode="wrap")
    def _easydiffraction_omit_absent(self, handler):
        return omit_absent(handler(self), self, ("scattering_types", "preferred_orientation"))

    @field_validator("space_group")
    @classmethod
    def _easydiffraction_setting(cls, v: str) -> str:
        easydiffraction_space_group(v)
        return v

    @model_validator(mode="after")
    def _easydiffraction_scattering_types(self) -> "EasydiffractionPhase":
        if self.scattering_types:
            raise_problems(type(self).__name__,
                           scattering_type_problems(self.scattering_types, self.atoms, CRYSPY_IONS, SCATTERING_ENGINE_LABEL))
        return self

    @model_validator(mode="after")
    def _easydiffraction_limits(self) -> "EasydiffractionPhase":
        problems = physical_problems(self.scale, PHYSICAL_LIMITS["nonnegative"], ("scale",), "scale")
        for name in ("a", "b", "c"):
            problems += physical_problems(getattr(self.unit_cell, name), PHYSICAL_LIMITS["cell_length"],
                                          ("unit_cell", name), name)
        for name in ("alpha", "beta", "gamma"):
            problems += physical_problems(getattr(self.unit_cell, name), PHYSICAL_LIMITS["cell_angle"],
                                          ("unit_cell", name), name)
        for label, atom in self.atoms.items():
            problems += physical_problems(atom.occupancy, PHYSICAL_LIMITS["occupancy"],
                                          ("atoms", label, "occupancy"), "occupancy")
            if atom.Uiso is not None:
                problems += physical_problems(atom.Uiso, PHYSICAL_LIMITS["adp"], ("atoms", label, "Uiso"), "Uiso")
            if atom.Uaniso is not None:
                for key in ("U11", "U22", "U33"):
                    problems += physical_problems(getattr(atom.Uaniso, key), PHYSICAL_LIMITS["adp"],
                                                  ("atoms", label, "Uaniso", key), key)
        raise_problems(type(self).__name__, problems)
        return self


# --- payload and recipe -------------------------------------------------------------


class RefinementControls(CoreModel):
    """How the pattern is calculated and fitted, all stated. lmfit runs only if a flag is set."""

    calculator: Literal["cryspy", "crysfml"] = Field(
        description="easydiffraction calculator; they compute different intensities and offer different "
                    "peak types (EB-76..EB-79)")
    minimizer: Literal["lmfit (leastsq)"] = Field(description="Minimizer (lmfit's Levenberg-Marquardt only)")
    max_iterations: CoreInt = Field(ge=1, description="easydiffraction max_iterations = lmfit max_nfev: the maximum number of function evaluations (not iterations)")
    chi_square_change_tolerance: CoreFloat = Field(gt=0, description="Relative chi-square change that stops the fit "
                                                                      "(lmfit ftol)")
    parameter_change_tolerance: CoreFloat = Field(gt=0, description="Relative parameter change that stops the fit "
                                                                    "(lmfit xtol)")
    gradient_tolerance: CoreFloat = Field(ge=0, description="Gradient orthogonality that stops the fit (lmfit gtol)")


class RietveldPayload(CoreModel):
    """``easydiffraction.rietveld`` payload."""

    xrd_data: XRDData
    fit_range: Optional[FitRange] = Field(default=None, json_schema_extra=absent_not_null_schema(),
                                          description="Left out: the data's weighted points, end to end")
    instrument: Instrument
    background: Optional[Background] = Field(default=None, json_schema_extra=absent_not_null_schema(),
                                             description="Left out: no background")
    phases: dict[CoreName, EasydiffractionPhase] = Field(min_length=1, json_schema_extra=name_keyed)
    refinement_controls: RefinementControls

    _not_null = field_validator("fit_range", "background", mode="before")(absent_not_null)

    @model_serializer(mode="wrap")
    def _omit_absent(self, handler):
        return omit_absent(handler(self), self, ("fit_range", "background"))

    _phase_names = field_validator("phases")(unique_phase_names)

    def window_mask(self) -> np.ndarray:
        """The points handed to easydiffraction: weighted, within the limits on data points (A149, A154, A158)."""
        lo, hi = fit_limits_on_data(self.fit_range, self.xrd_data)
        tth = np.asarray(self.xrd_data.tth, dtype=float)
        w = np.asarray(self.xrd_data.Itth_weights, dtype=float)
        return (tth >= lo) & (tth <= hi) & (w > 0)

    def simulation_mode(self) -> bool:
        """No refine flag set: the pattern is calculated, lmfit is not run."""
        return not refined_flags(self)

    @model_validator(mode="after")
    def _easydiffraction_payload(self) -> "RietveldPayload":
        problems = fit_range_problems(self.fit_range, self.xrd_data)
        mask = None if problems else self.window_mask()  # the window check passed, so the mask cannot fail
        if mask is not None:
            heavy = np.flatnonzero(mask & (np.asarray(self.xrd_data.Itth_weights, dtype=float) > MAX_WEIGHT))
            for i in heavy[:20]:
                problems.append(custom_error(
                    "easydiffraction_weight",
                    "weight {value} (sigma {sigma}) is above {limit}: easydiffraction would replace sigma "
                    "< 1e-4 by 1.0 without saying so (EB-73); rescale the intensities and weights",
                    ("xrd_data", "Itth_weights", int(i)), self.xrd_data.Itth_weights[i],
                    value=self.xrd_data.Itth_weights[i], sigma=f"{self.xrd_data.Itth_weights[i] ** -0.5:.3g}",
                    limit=f"{MAX_WEIGHT:g}"))  # pydantic's templates take no format specs
            itth = np.asarray(self.xrd_data.Itth, dtype=float)
            for i in np.flatnonzero(mask & (itth < 0))[:20]:
                problems.append(custom_error(
                    "easydiffraction_negative_intensity",
                    "intensity {value} at {tth} deg 2theta is negative: easydiffraction refuses negative measured "
                    "intensities (EB-91); shift the data so that every point in the fit window is >= 0, or give "
                    "the point weight 0 (it is then not handed to the engine)",
                    ("xrd_data", "Itth", int(i)), self.xrd_data.Itth[i], value=self.xrd_data.Itth[i],
                    tth=f"{self.xrd_data.tth[i]:g}"))
        calculator = self.refinement_controls.calculator
        for name, phase in self.phases.items():
            why = calculator_setting_problem(phase.space_group, calculator)
            if why is not None:
                problems.append(custom_error("easydiffraction_setting", "{why}", ("phases", name, "space_group"),
                                       phase.space_group, why=why))
            if calculator == "crysfml" and phase.preferred_orientation is not None:
                problems.append(custom_error(
                    "easydiffraction_po_crysfml",
                    "the crysfml calculator ignores preferred orientation: easydiffraction emits the March-Dollase "
                    "texture for CrysPy only (EB-97), so this block would have no effect; use the cryspy calculator, "
                    "or leave preferred_orientation out",
                    ("phases", name, "preferred_orientation"), phase.preferred_orientation.model_dump()))
            if calculator == "crysfml" and phase.scattering_types:
                problems.append(custom_error(
                    "easydiffraction_ions_crysfml",
                    "the crysfml calculator computes neutral atoms only: easydiffraction strips the charge from every "
                    "type symbol it hands to CrysFML (EB-96), so these scattering types would have no effect; use the "
                    "cryspy calculator, or leave scattering_types out",
                    ("phases", name, "scattering_types"), phase.scattering_types))
            if calculator == "crysfml":
                for label, atom in phase.atoms.items():
                    if atom.Uaniso is not None:
                        problems.append(custom_error(
                            "easydiffraction_uaniso_crysfml",
                            "the crysfml calculator does not use anisotropic ADPs: easydiffraction hands CrysFML "
                            "B = 8 pi^2 Ueq (the trace / 3) and the tensor has no effect (EB-23); state Uiso, or "
                            "use the cryspy calculator",
                            ("phases", name, "atoms", label, "Uaniso"), atom.Uaniso.model_dump()))
        profile = self.instrument.broadening
        if profile.peak_type not in CALCULATOR_PEAK_TYPES[calculator]:
            problems.append(custom_error(
                "easydiffraction_peak_type",
                "peak_type '{peak_type}' is not computed by the {calculator} calculator; it computes {allowed}",
                ("instrument", "broadening", "peak_type"), profile.peak_type, peak_type=profile.peak_type,
                calculator=calculator, allowed=", ".join(CALCULATOR_PEAK_TYPES[calculator])))
        if profile.cutoff_fwhm is not None and calculator != "cryspy":
            problems.append(custom_error(
                "easydiffraction_cutoff",
                "cutoff_fwhm is a CrysPy setting; {calculator} ignores it (fixed 30-FWHM window, EB-76): leave it out",
                ("instrument", "broadening", "cutoff_fwhm"), profile.cutoff_fwhm, calculator=calculator))
        if mask is not None:
            pars = profile.parameters
            corrections = self.instrument.corrections
            shifts = [q.value for q in (corrections.calib_twotheta_offset, corrections.calib_sample_displacement,
                                        corrections.calib_sample_transparency) if q is not None]
            points, pad = width_check_points(np.asarray(self.xrd_data.tth, dtype=float)[mask], shifts)
            for kind, (lo, hi) in profile_negative_widths(lambda n: getattr(pars, n).value, points).items():
                problems.append(custom_error(
                    "easydiffraction_negative_width",
                    "the {width} is negative from {lo} to {hi} deg 2theta, within {pad} deg of the fit window "
                    "(reflections there are computed and reach it): easydiffraction then computes a wrong "
                    "pattern without a message (CrysFML drops those peaks, CrysPy distorts them; EB-87)",
                    ("instrument", "broadening", "parameters"), pars.model_dump(),
                    width=kind, lo=f"{lo:g}", hi=f"{hi:g}", pad=f"{pad:g}"))
        raise_problems(type(self).__name__, problems)
        return self


class EasydiffractionRietveldRecipe(EngineRecipe):
    """An ``easydiffraction.rietveld`` recipe."""

    gateway_name: ClassVar[str] = "easydiffraction"
    schema_declarations: ClassVar[Mapping[str, Any]] = DECLARATIONS

    schema_name: Literal["easydiffraction.rietveld"]
    payload: RietveldPayload


validate_recipe = recipe_validator({"easydiffraction.rietveld": EasydiffractionRietveldRecipe},
                                   engine="easydiffraction", title="EasydiffractionRecipe")
