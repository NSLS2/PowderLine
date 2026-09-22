"""Pydantic models for validating GSAS-II refinement recipe JSON files.

Schema 0.25 introduced a two-tier structure: schema_name + payload pattern.
This enables distinct validation rules for Rietveld vs single peak fitting workflows.

Schema 0.26 changes recipe *semantics* without changing recipe shape:
per-parameter refine flags are now honored for unit-cell parameters, atomic
coordinates, and anisotropic displacement components (previously collapsed
into GSAS-II's lumped whole-cell / per-atom flags). A parameter refines iff it
is present with refine_flag=true; absent or false means fixed. Symmetry-linked
parameters (e.g. cubic a=b=c) refine together if any member is requested.
See docs/SCHEMA_HISTORY.md.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal
from typing_extensions import Self
from pathlib import Path
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator, field_serializer
from pydantic.functional_serializers import PlainSerializer
import numpy as np

# Expected schema version for recipe validation
EXPECTED_SCHEMA_VERSION = "0.26.0"

# Accepted schema names (must match exactly)
ACCEPTED_SCHEMA_NAMES: list[str] = ["GSASII_Rietveld", "GSASII_SPF"]

# Type alias for refinement parameter format: [value, refine_flag, min, max]
# Using tuple to preserve types at each position
#: Format for a single refinement parameter, ``[value, refine_flag, min, max]``.
#: Modeled as a fixed 4-tuple (rather than a list) so each position keeps its
#: own type; serialized back to a JSON list via the attached ``PlainSerializer``.
RefinementParameter = Annotated[
    tuple[float | None, bool | None, float | None, float | None],
    PlainSerializer(lambda x: list(x), return_type=list, when_used='json')
]


class RefinementParameterModel(BaseModel):
    """Model for the standard [value, refine_flag, min, max] parameter format."""

    model_config = ConfigDict(extra='forbid')

    value: float | None = Field(description="Parameter value")
    refine_flag: bool | None = Field(description="Whether to refine this parameter")
    min_val: float | None = Field(default=None, description="Minimum value constraint (not implemented in GSAS-II)")
    max_val: float | None = Field(default=None, description="Maximum value constraint (not implemented in GSAS-II)")

    @classmethod
    def from_list(cls, param_list: list) -> 'RefinementParameterModel':
        """Create from [value, refine_flag, min, max] list format."""
        if len(param_list) != 4:
            raise ValueError(f"Parameter list must have exactly 4 elements, got {len(param_list)}")
        return cls(
            value=param_list[0],
            refine_flag=param_list[1],
            min_val=param_list[2],
            max_val=param_list[3]
        )


class InstrumentBroadening(BaseModel):
    """Instrument broadening parameters (Thompson-Cox-Hastings pseudo-Voigt)."""

    model_config = ConfigDict(extra='allow')

    U: RefinementParameter | None = None
    V: RefinementParameter | None = None
    W: RefinementParameter | None = None
    X: RefinementParameter | None = None
    Y: RefinementParameter | None = None
    Z: RefinementParameter | None = None


class InstrumentCorrections(BaseModel):
    """Instrument correction parameters."""

    model_config = ConfigDict(extra='allow')

    zero_shift: RefinementParameter | None = None
    axial_divergence: RefinementParameter | None = None


class InstrumentParameterization(BaseModel):
    """Instrument parameter settings for refinement."""

    model_config = ConfigDict(extra='allow')

    wavelength: RefinementParameter | None = None
    polarization: RefinementParameter | None = None
    broadening: InstrumentBroadening | None = None
    corrections: InstrumentCorrections | None = None


class InstrumentModel(BaseModel):
    """Instrument configuration."""

    model_config = ConfigDict(extra='allow')

    description: str = Field(description="Instrument description or beamline name")
    initialization: list[dict[str, Any]] = Field(description="GSAS-II instrument parameters [Iparm1, Iparm2]")
    parameterization: InstrumentParameterization | None = None

    @field_validator('initialization')
    @classmethod
    def validate_initialization_structure(cls, v):
        """Ensure initialization is a list of two dicts."""
        if not isinstance(v, list) or len(v) != 2:
            raise ValueError(f"initialization must be a list of exactly 2 dicts [Iparm1, Iparm2], got {type(v)} with length {len(v) if isinstance(v, list) else 'N/A'}")
        if not isinstance(v[0], dict) or not isinstance(v[1], dict):
            raise ValueError(f"Both elements in initialization must be dicts")
        return v


class ChebyshevBackground(BaseModel):
    """Chebyshev polynomial background."""

    model_config = ConfigDict(extra='allow')

    num_coefficients: int = Field(gt=0, description="Number of Chebyshev coefficients")
    coefficients: list[float] = Field(description="Coefficient values")
    refine_flag: bool = Field(description="Whether to refine background")

    @field_validator('coefficients')
    @classmethod
    def validate_coefficients_length(cls, v, info):
        """Ensure number of coefficients matches num_coefficients."""
        num_coef = info.data.get('num_coefficients')
        if num_coef is not None and len(v) != num_coef:
            raise ValueError(f"Number of coefficients ({len(v)}) must match num_coefficients ({num_coef})")
        return v


class SinglePeaksBackground(BaseModel):
    """Single peak background parameters (for background.single_peaks).

    Width convention: uses Gaussian sigma (σ), **not** sigma squared (σ²).
    This is the natural convention for describing peak widths and matches
    scipy/TOPAS usage. Contrast with ``SinglePeaks`` (peak-list peaks)
    which uses σ² to match GSAS-II's internal Peak List storage format.
    See also: ``SinglePeaks.pv_gaussian_sigma_sq``.
    """

    model_config = ConfigDict(extra='allow')

    positions: list[RefinementParameter] | None = None
    intensities: list[RefinementParameter] | None = None
    pv_gaussian_sigma: list[RefinementParameter] | None = None
    pv_lorentzian_gamma: list[RefinementParameter] | None = None

    @model_validator(mode='after')
    def validate_peak_lists_same_length(self):
        """Ensure all peak parameter lists have the same length."""
        lists = [
            self.positions, self.intensities,
            self.pv_gaussian_sigma, self.pv_lorentzian_gamma
        ]
        non_none_lists = [lst for lst in lists if lst is not None]

        if len(non_none_lists) > 0:
            lengths = [len(lst) for lst in non_none_lists]
            if len(set(lengths)) > 1:
                raise ValueError(
                    f"All peak parameter lists must have the same length. "
                    f"Got lengths: positions={len(self.positions) if self.positions else 0}, "
                    f"intensities={len(self.intensities) if self.intensities else 0}, "
                    f"pv_gaussian_sigma={len(self.pv_gaussian_sigma) if self.pv_gaussian_sigma else 0}, "
                    f"pv_lorentzian_gamma={len(self.pv_lorentzian_gamma) if self.pv_lorentzian_gamma else 0}"
                )
        return self


class SinglePeaks(BaseModel):
    """Single peak fitting parameters (for top-level single_peaks).

    These peaks are fitted in the Peak List, allowing individual peak refinement
    independent of phase structure.
    """

    model_config = ConfigDict(extra='allow')

    positions: list[RefinementParameter] | None = None
    intensities: list[RefinementParameter] | None = None
    pv_gaussian_sigma_sq: list[RefinementParameter] | None = Field(
        default=None,
        description="Gaussian width variance (σ²). GSAS-II stores Peak List peaks as variance internally."
    )
    pv_lorentzian_gamma: list[RefinementParameter] | None = None

    @model_validator(mode='after')
    def validate_peak_lists_same_length(self):
        """Ensure all peak parameter lists have the same length."""
        lists = [
            self.positions, self.intensities,
            self.pv_gaussian_sigma_sq, self.pv_lorentzian_gamma
        ]
        non_none_lists = [lst for lst in lists if lst is not None]

        if len(non_none_lists) > 0:
            lengths = [len(lst) for lst in non_none_lists]
            if len(set(lengths)) > 1:
                raise ValueError(
                    f"All peak parameter lists must have the same length. "
                    f"Got lengths: positions={len(self.positions) if self.positions else 0}, "
                    f"intensities={len(self.intensities) if self.intensities else 0}, "
                    f"pv_gaussian_sigma_sq={len(self.pv_gaussian_sigma_sq) if self.pv_gaussian_sigma_sq else 0}, "
                    f"pv_lorentzian_gamma={len(self.pv_lorentzian_gamma) if self.pv_lorentzian_gamma else 0}"
                )
        return self


class BackgroundModel(BaseModel):
    """Background model configuration."""

    model_config = ConfigDict(extra='allow')

    chebyshev: ChebyshevBackground | None = None
    single_peaks: SinglePeaksBackground | None = None


class SinglePeakFittingMode(BaseModel):
    """Single peak fitting mode configuration.

    **Schema 0.25 Addition:** Required for GSASII_SPF schema.
    """

    model_config = ConfigDict(extra='allow')

    use_instrument_profile: bool = Field(
        description="If True, use 'useIP' mode (constrain peak widths to instrument profile). "
                    "If False, use 'hold' mode (refine individual peak widths independently)."
    )


class RefinementControls(BaseModel):
    """Controls for refinement execution.

    **Schema 0.25 Simplification:**
    Removed multi-strategy refinement system from 0.24. PowderLine now executes
    a single refinement pass (proj.refine() for Rietveld, hist.refine_peaks() for SPF).

    Future algorithm selection (e.g., Powell vs Levenberg-Marquardt) may be
    controlled via refinement_algorithm field.
    """

    model_config = ConfigDict(extra='allow')

    refinement_cycles: int = Field(
        default=5,
        ge=1,
        description="Number of refinement cycles to execute"
    )
    refinement_algorithm: str | None = Field(
        default=None,
        description="Optional future field for algorithm selection (e.g., 'levenberg_marquardt', 'powell')"
    )
    single_peak_fitting_mode: SinglePeakFittingMode | None = Field(
        default=None,
        description="Single peak fitting mode configuration (required for GSASII_SPF schema)"
    )


class UnitCellParameters(BaseModel):
    """Unit cell parameters (a, b, c, alpha, beta, gamma).

    **Schema 0.26 semantics:** each parameter refines iff it is present with
    refine_flag=true; absent or false means fixed (held). Parameters that are
    symmetry-linked for the phase's Laue class (e.g. cubic a=b=c, or the
    coupled monoclinic a/c/beta) refine together if any member is requested;
    flags on symmetry-fixed parameters (e.g. cubic angles) have no effect.
    Listing only the parameters you wish to refine is equivalent to listing
    all six with explicit flags.
    """

    model_config = ConfigDict(extra='allow')

    a: RefinementParameter | None = None
    b: RefinementParameter | None = None
    c: RefinementParameter | None = None
    alpha: RefinementParameter | None = None
    beta: RefinementParameter | None = None
    gamma: RefinementParameter | None = None

    @field_validator('a', 'b', 'c')
    @classmethod
    def validate_cell_lengths(cls, v):
        """Ensure unit cell lengths are positive."""
        if v is not None:
            value = v[0]  # RefinementParameter is tuple: (value, refine_flag, min, max)
            if value is not None and value <= 0:
                raise ValueError(
                    f"Unit cell lengths (a, b, c) must be positive, got {value}. "
                    "Check your CIF file or structure definition."
                )
        return v

    @field_validator('alpha', 'beta', 'gamma')
    @classmethod
    def validate_cell_angles(cls, v):
        """Ensure unit cell angles are between 0 and 180 degrees."""
        if v is not None:
            value = v[0]  # RefinementParameter is tuple: (value, refine_flag, min, max)
            if value is not None and not (0 < value < 180):
                raise ValueError(
                    f"Unit cell angles (alpha, beta, gamma) must be between 0 and 180 degrees, got {value}. "
                    "Check your CIF file or structure definition."
                )
        return v


class AtomParameters(BaseModel):
    """Atomic position and displacement parameters.

    **Schema 0.26 semantics:** each coordinate (x/y/z) and each anisotropic
    Uaniso component refines iff present with refine_flag=true; absent or
    false means fixed (held). Site-symmetry-linked components refine together
    if any member is requested; symmetry-fixed components ignore their flags.
    """

    model_config = ConfigDict(extra='allow')

    x: RefinementParameter | None = None
    y: RefinementParameter | None = None
    z: RefinementParameter | None = None
    occupancy: RefinementParameter | None = None
    ADP: str = Field(description="Displacement parameter type: 'Uiso' or 'Uaniso' (required in schema 0.22)")
    Uiso: RefinementParameter | None = None
    Uaniso: dict[str, RefinementParameter | None] | None = Field(
        default=None,
        description="Anisotropic displacement parameters in Angstrom^2 with keys U11, U22, U33, U12, U13, U23"
    )


class SizeBroadening(BaseModel):
    """Crystallite size broadening parameters.

    **Schema 0.25 Change:** Renamed `size` to `isotropic_size` to prepare for
    future uniaxial/ellipsoidal size broadening support. Added `model` field
    to specify broadening geometry (isotropic, uniaxial, ellipsoidal).

    **Models:**
    - `isotropic`: Single size parameter (currently implemented)
    - `uniaxial`: Equatorial and axial sizes with hkl direction (future)
    - `ellipsoidal`: Full S11-S23 tensor (future)
    """

    model_config = ConfigDict(extra='allow')

    model: Literal["isotropic", "uniaxial", "ellipsoidal"] = Field(
        default="isotropic",
        description="Size broadening model: 'isotropic' (implemented), 'uniaxial' (future), 'ellipsoidal' (future)"
    )

    # Isotropic parameters (currently implemented)
    isotropic_size: RefinementParameter | None = Field(
        default=None,
        description="Isotropic crystallite size in microns (GSAS-II convention)"
    )

    # Uniaxial parameters (future implementation)
    uniaxial_equatorial: RefinementParameter | None = Field(
        default=None,
        description="Equatorial crystallite size for uniaxial model (future)"
    )
    uniaxial_axial: RefinementParameter | None = Field(
        default=None,
        description="Axial crystallite size along hkl direction for uniaxial model (future)"
    )
    hkl_direction: list[int] | None = Field(
        default=None,
        description="[h, k, l] direction for uniaxial broadening (future)"
    )

    # Ellipsoidal parameters (future implementation)
    S11: RefinementParameter | None = Field(default=None, description="Ellipsoidal S11 parameter (future)")
    S22: RefinementParameter | None = Field(default=None, description="Ellipsoidal S22 parameter (future)")
    S33: RefinementParameter | None = Field(default=None, description="Ellipsoidal S33 parameter (future)")
    S12: RefinementParameter | None = Field(default=None, description="Ellipsoidal S12 parameter (future)")
    S13: RefinementParameter | None = Field(default=None, description="Ellipsoidal S13 parameter (future)")
    S23: RefinementParameter | None = Field(default=None, description="Ellipsoidal S23 parameter (future)")

    # Common parameter for all models
    LG_eta: RefinementParameter | None = Field(
        default=None,
        description="Lorentzian/Gaussian mixing parameter (1=Lorentzian, 0=Gaussian)"
    )

    @model_validator(mode='after')
    def validate_model_implementation(self) -> Self:
        """Validate that only implemented models are used."""
        if self.model == 'uniaxial':
            raise NotImplementedError(
                "Uniaxial size broadening model is not yet implemented. "
                "Support planned for future release. Use 'isotropic' model instead."
            )
        elif self.model == 'ellipsoidal':
            raise NotImplementedError(
                "Ellipsoidal size broadening model is not yet implemented. "
                "Support planned for future release. Use 'isotropic' model instead."
            )
        return self


class StrainBroadening(BaseModel):
    """Microstrain broadening parameters.

    **Schema 0.25 Change:** Renamed `strain` to `isotropic_strain` to prepare for
    future uniaxial/generalized strain broadening support. Added `model` field
    to specify strain model (isotropic, uniaxial, generalized).

    **Models:**
    - `isotropic`: Single strain parameter (currently implemented)
    - `uniaxial`: Equatorial and axial strains with hkl direction (future)
    - `generalized`: Stephens model - symmetry-dependent parameters based on Laue class (future)

    **Note:** The `generalized` Stephens model requires complex parameterization
    that depends on the crystal symmetry (Laue class). Implementation deferred to Phase 2.
    """

    model_config = ConfigDict(extra='allow')

    model: Literal["isotropic", "uniaxial", "generalized"] = Field(
        default="isotropic",
        description="Strain broadening model: 'isotropic' (implemented), 'uniaxial' (future), 'generalized'/Stephens (future)"
    )

    # Isotropic parameters (currently implemented)
    isotropic_strain: RefinementParameter | None = Field(
        default=None,
        description="Isotropic microstrain as delta-d/d x 10^-6 (GSAS-II convention)"
    )

    # Uniaxial parameters (future implementation)
    uniaxial_equatorial: RefinementParameter | None = Field(
        default=None,
        description="Equatorial microstrain for uniaxial model (future)"
    )
    uniaxial_axial: RefinementParameter | None = Field(
        default=None,
        description="Axial microstrain along hkl direction for uniaxial model (future)"
    )
    hkl_direction: list[int] | None = Field(
        default=None,
        description="[h, k, l] direction for uniaxial strain (future)"
    )

    # Generalized/Stephens parameters (future implementation)
    # Note: Actual parameters depend on Laue class - will be added when implemented
    stephens_parameters: dict[str, RefinementParameter] | None = Field(
        default=None,
        description="Symmetry-dependent Stephens model parameters (future)"
    )

    # Common parameter for all models
    LG_eta: RefinementParameter | None = Field(
        default=None,
        description="Lorentzian/Gaussian mixing parameter (1=Lorentzian, 0=Gaussian)"
    )

    @model_validator(mode='after')
    def validate_model_implementation(self) -> Self:
        """Validate that only implemented models are used."""
        if self.model == 'uniaxial':
            raise NotImplementedError(
                "Uniaxial strain broadening model is not yet implemented. "
                "Support planned for future release. Use 'isotropic' model instead."
            )
        elif self.model == 'generalized':
            raise NotImplementedError(
                "Generalized (Stephens) strain broadening model is not yet implemented. "
                "This model requires complex symmetry-dependent parameterization. "
                "Support planned for Phase 2. Use 'isotropic' model instead."
            )
        return self


class PeakBroadening(BaseModel):
    """Phase-specific peak broadening from size and strain.

    **Schema 0.25 Change:** Model field moved to individual size_broadening and
    strain_broadening classes to allow independent model selection.
    """

    model_config = ConfigDict(extra='allow')

    size_broadening: SizeBroadening | None = None
    strain_broadening: StrainBroadening | None = None


class PhaseParameterization(BaseModel):
    """Phase-specific refinement parameters."""

    model_config = ConfigDict(extra='allow')

    scale: RefinementParameter | None = None
    unit_cell: UnitCellParameters | None = None
    atoms: dict[str, AtomParameters] | None = None
    peak_broadening: PeakBroadening | None = None


class AtomStructure(BaseModel):
    """Atomic structure definition."""

    model_config = ConfigDict(extra='allow')

    element: str = Field(description="Element symbol")
    x: float = Field(description="Fractional x coordinate")
    y: float = Field(description="Fractional y coordinate")
    z: float = Field(description="Fractional z coordinate")
    occupancy: float = Field(default=1.0, description="Site occupancy")
    Multiplicity: int | None = Field(default=None, description="Site multiplicity")
    ADP: str = Field(description="Atomic displacement parameter type from CIF: 'Uiso' or 'Uaniso' (required in schema 0.22)")
    Uiso: float | None = Field(default=None, description="Isotropic displacement parameter in Angstrom^2 (can be None if using Uaniso)")
    Uaniso: dict[str, float | None] | None = Field(
        default=None,
        description="Anisotropic displacement parameters in Angstrom^2 with keys U11, U22, U33, U12, U13, U23"
    )


class UnitCellStructure(BaseModel):
    """Unit cell structure (actual values, not refinement parameters)."""

    model_config = ConfigDict(extra='allow')

    a: float = Field(description="Unit cell a parameter (Angstroms)")
    b: float = Field(description="Unit cell b parameter (Angstroms)")
    c: float = Field(description="Unit cell c parameter (Angstroms)")
    alpha: float = Field(description="Unit cell alpha angle (degrees)")
    beta: float = Field(description="Unit cell beta angle (degrees)")
    gamma: float = Field(description="Unit cell gamma angle (degrees)")
    volume: float | None = Field(default=None, description="Unit cell volume (calculated)")


class PhaseStructure(BaseModel):
    """Phase structure definition."""

    model_config = ConfigDict(extra='allow')

    phase_name: str = Field(description="Phase name identifier")
    space_group: str = Field(description="Space group symbol (Hermann-Mauguin notation)")
    unit_cell: UnitCellStructure = Field(description="Unit cell parameters")
    atoms: dict[str, AtomStructure] = Field(description="Atomic positions keyed by atom label")


class PhaseModel(BaseModel):
    """Complete phase definition."""

    model_config = ConfigDict(extra='allow')

    structure: PhaseStructure = Field(description="Phase structure definition")
    parameterization: PhaseParameterization | None = None


class XRDDataModel(BaseModel):
    """XRD data arrays."""

    model_config = ConfigDict(extra='allow')

    tth: list[float] = Field(description="Two-theta values (degrees)")
    Itth: list[float] = Field(description="Intensity values")
    Itth_weights: list[float] = Field(description="Intensity weights (1/sigma^2)")
    filename: str | None = Field(default=None, description="Original filename for reference")

    @model_validator(mode='after')
    def validate_all_arrays_same_length(self):
        """Ensure tth, Itth, and Itth_weights have the same length."""
        lengths = [len(self.tth), len(self.Itth), len(self.Itth_weights)]
        if len(set(lengths)) > 1:
            raise ValueError(
                f"XRD data arrays must have the same length. "
                f"Got tth={len(self.tth)}, Itth={len(self.Itth)}, Itth_weights={len(self.Itth_weights)}"
            )
        return self

    @model_validator(mode='after')
    def validate_arrays_wellformed(self):
        """Reject ill-formed XRD data. PowderLine never repairs data — it rejects it.

        Transforming raw data (unit conversion, weight derivation, handling
        background-subtracted negatives) is the job of the reader/parser that builds
        this block, not PowderLine. Here we only enforce that what arrives is usable:

        * arrays must be non-empty;
        * every tth / Itth / Itth_weights value must be finite (no NaN or inf) —
          this catches, e.g., a weight computed as 1/esd**2 with esd == 0 (inf);
        * tth must be strictly increasing (a powder pattern is monotonic in 2-theta);
        * weights must be >= 0 (a 0 weight legitimately excludes a point; a negative
          weight is nonsensical) and at least one weight must be > 0 (all-zero =
          nothing to fit).

        A negative *intensity* is explicitly allowed: background-subtracted data
        legitimately dips below zero, so Itth is checked for finiteness only, not sign.
        """
        if len(self.tth) == 0:
            raise ValueError(
                "XRD data arrays must be non-empty (tth/Itth/Itth_weights have length 0)."
            )

        tth = np.asarray(self.tth, dtype=float)
        Itth = np.asarray(self.Itth, dtype=float)
        weights = np.asarray(self.Itth_weights, dtype=float)

        # All values finite (rejects NaN and +/-inf across all three arrays).
        for name, arr in (("tth", tth), ("Itth", Itth), ("Itth_weights", weights)):
            bad = np.where(~np.isfinite(arr))[0]
            if bad.size:
                i = int(bad[0])
                raise ValueError(
                    f"XRD data '{name}' contains non-finite values (NaN/inf); first at "
                    f"index {i} (value {float(arr[i])!r}). Fix the data upstream — "
                    "PowderLine does not repair xrd_data."
                )

        # tth must be strictly increasing.
        bad = np.where(np.diff(tth) <= 0)[0]
        if bad.size:
            i = int(bad[0])
            raise ValueError(
                f"XRD 'tth' must be strictly increasing; tth[{i + 1}]={float(tth[i + 1])!r} "
                f"<= tth[{i}]={float(tth[i])!r}. Sort/deduplicate the pattern upstream."
            )

        # Weights: non-negative, with at least one strictly positive.
        bad = np.where(weights < 0)[0]
        if bad.size:
            i = int(bad[0])
            raise ValueError(
                f"XRD 'Itth_weights' must be >= 0; first negative at index {i} "
                f"(value {float(weights[i])!r}). A 0 weight excludes a point; "
                "negative weights are invalid."
            )
        if not np.any(weights > 0):
            raise ValueError(
                "XRD 'Itth_weights' are all zero — nothing to fit. At least one "
                "weight must be > 0."
            )

        return self


class PayloadModel(BaseModel):
    """Refinement data payload containing all refinement parameters.

    **Payload structure:** The payload contains recipe-specific refinement data,
    separated from top-level metadata (schema_name, schema_version). This allows
    distinct validation rules for different refinement types (Rietveld vs SPF)
    while maintaining a consistent outer structure.

    **Type Preservation:** Refinement parameters use `[value, refine_flag, min, max]`
    format where `refine_flag` must remain boolean. Always export with
    `model_dump(mode='json')` to preserve types.

    Validation rules:
    - GSASII_Rietveld: Requires `phases` and `instrument`
    - GSASII_SPF: Requires `single_peaks`, forbids `phases`
    """

    model_config = ConfigDict(extra='allow')  # Allow extra fields for schema evolution

    # Core data fields
    xrd_data: XRDDataModel = Field(description="XRD data arrays")
    instrument: InstrumentModel | None = Field(default=None, description="Instrument configuration (required for Rietveld)")
    phases: dict[str, PhaseModel] | None = Field(default=None, description="Phase definitions (required for Rietveld, forbidden for SPF)")

    # Optional refinement components
    asset_path: str | None = Field(default=None, description="Base path for asset files")
    fit_range: list[float | None] | None = Field(default=None, description="Fit range [min, max]")
    background: BackgroundModel | None = Field(default=None, description="Background model")
    single_peaks: SinglePeaks | None = Field(default=None, description="Single peaks for Peak List fitting (required for SPF)")
    refinement_controls: RefinementControls = Field(description="Controls for refinement execution (required)")

    @field_validator('fit_range')
    @classmethod
    def validate_fit_range(cls, v):
        """Ensure fit_range is a list of length 2 if provided."""
        if v is not None and len(v) != 2:
            raise ValueError(f"fit_range must be a list of exactly 2 elements [min, max], got {len(v)}")
        return v


class RecipeModel(BaseModel):
    """Top-level refinement recipe model for schema 0.26.

    **Architecture**: Two-tier structure (since schema 0.25) with schema
    metadata and payload:

    .. code-block:: javascript

        {
            "schema_name": "GSASII_Rietveld",
            "schema_version": "0.26.0",
            "payload": {
                "xrd_data": {...},
                "phases": {...},
                ...
            }
        }

    **Schema Types**:

    - ``GSASII_Rietveld``: Full Rietveld refinement (requires phases + instrument)
    - ``GSASII_SPF``: Single peak fitting only (requires single_peaks, forbids phases)

    **Validation Rules**:

    - GSASII_Rietveld: ``payload.phases`` must be present, ``payload.instrument`` required
    - GSASII_SPF: ``payload.single_peaks`` must be present, ``payload.phases`` must be None

    **Breaking Changes from 0.24**:

    - Removed multi-strategy refinement system (strategy, spf_first, iterative_cycles, etc.)
    - Removed sample_name, recipe_description, software_package from payload
    - Added schema_name for explicit workflow type declaration
    - Payload structure replaces flat top-level fields

    **Migration from 0.24 to 0.25**:

    .. code-block:: javascript

        // Old (0.24):
        {
            "schema_version": "0.24",
            "sample_name": "LaB6",
            "xrd_data": {...},
            "phases": {...},
            "refinement_controls": {
                "strategy": "structural_only",
                "refinement_cycles": 5
            }
        }

        // New (0.25):
        {
            "schema_name": "GSASII_Rietveld",
            "schema_version": "0.26.0",
            "payload": {
                "xrd_data": {...},
                "phases": {...},
                "refinement_controls": {
                    "refinement_cycles": 5
                }
            }
        }
    """

    model_config = ConfigDict(extra='allow')

    schema_name: Literal["GSASII_Rietveld", "GSASII_SPF"] = Field(
        description="Schema type: 'GSASII_Rietveld' for Rietveld refinement, 'GSASII_SPF' for single peak fitting"
    )
    schema_version: str = Field(
        description="Schema version number (required)"
    )
    payload: PayloadModel = Field(
        description="Refinement data payload"
    )

    @field_validator('schema_name')
    @classmethod
    def validate_schema_name(cls, v):
        """Validate that schema_name is in the accepted list."""
        if v not in ACCEPTED_SCHEMA_NAMES:
            raise ValueError(
                f"Invalid schema_name '{v}'. Must be one of: {ACCEPTED_SCHEMA_NAMES}"
            )
        return v

    @field_validator('schema_version')
    @classmethod
    def validate_schema_version(cls, v):
        """Validate that the schema version is currently supported."""
        if v != EXPECTED_SCHEMA_VERSION:
            raise ValueError(
                f"Schema version mismatch: recipe uses '{v}', but code expects '{EXPECTED_SCHEMA_VERSION}'. "
                f"See docs/SCHEMA_HISTORY.md for migration guidance."
            )
        return v

    @model_validator(mode='after')
    def validate_payload_by_schema_name(self):
        """Validate payload contents match schema_name requirements.

        - GSASII_Rietveld: Requires phases, instrument, instrument.initialization, refinement_controls
        - GSASII_SPF: Requires single_peaks, instrument.initialization, refinement_controls; forbids phases
        """
        schema_name = self.schema_name
        payload = self.payload

        if schema_name == "GSASII_Rietveld":
            # Rietveld refinement requires phases and instrument
            if payload.phases is None or len(payload.phases) == 0:
                raise ValueError(
                    "GSASII_Rietveld schema requires 'payload.phases' to be defined with at least one phase"
                )
            if payload.instrument is None:
                raise ValueError(
                    "GSASII_Rietveld schema requires 'payload.instrument' to be defined"
                )

            # Validate instrument.initialization exists (required for adding XRD data to GSAS-II)
            if payload.instrument.initialization is None:
                raise ValueError(
                    "GSASII_Rietveld schema requires 'payload.instrument.initialization' "
                    "to be defined for adding XRD data to GSAS-II project."
                )

            # Validate unique phase names
            phase_names = list(payload.phases.keys())
            duplicates = [name for name in phase_names if phase_names.count(name) > 1]
            if duplicates:
                raise ValueError(
                    f"Duplicate phase names found: {set(duplicates)}. "
                    "Each phase must have a unique name."
                )

        elif schema_name == "GSASII_SPF":
            # Single peak fitting requires single_peaks and forbids phases
            if payload.single_peaks is None:
                raise ValueError(
                    "GSASII_SPF schema requires 'payload.single_peaks' to be defined"
                )
            if payload.phases is not None:
                raise ValueError(
                    "GSASII_SPF schema forbids 'payload.phases' (must be None). "
                    "Single peak fitting does not use structural phases."
                )

            # Validate instrument.initialization exists (required for adding XRD data to GSAS-II)
            if payload.instrument is None or payload.instrument.initialization is None:
                raise ValueError(
                    "GSASII_SPF schema requires 'payload.instrument.initialization' "
                    "to be defined for adding XRD data to GSAS-II project."
                )

            # Validate that single_peak_fitting_mode is configured in refinement_controls
            if (payload.refinement_controls is None or
                    payload.refinement_controls.single_peak_fitting_mode is None):
                raise ValueError(
                    "GSASII_SPF schema requires "
                    "'payload.refinement_controls.single_peak_fitting_mode' to be defined. "
                    "Set 'use_instrument_profile' to true (use instrument broadening) "
                    "or false (refine peak widths independently)."
                )

        return self
