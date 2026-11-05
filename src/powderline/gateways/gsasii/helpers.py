"""GSAS-II gateway — shared helpers, output naming and default constants.

Moved verbatim from ``powderline/kicker.py`` (multi-engine refactor, re/01).
"""
from __future__ import annotations
import numpy as np
from typing import Any
from GSASII import GSASIIpwd as G2pwd
from dataclasses import dataclass


# Standard naming (file-less, no sample_name)
@dataclass
class OutputNamingConfig:
    """Standard naming for file-less refinements."""
    gpx_filename: str = "dummy.gpx"
    histogram_name: str = "PWDR dummy"
    lst_filename: str = "dummy.lst"  # GSAS-II generates .lst with same basename as .gpx

OUTPUT_NAMING = OutputNamingConfig()

# TODO: In phase 2 move these defaults upstream for the recipe creation process.
# Further default parameters and values include refinement flags (False)
DEFAULT_HIST_SCALE_VAL = 1.0
DEFAULT_HIST_SCALE_REFINE_FLAG = False
# TODO: Phase 2 upstream recipe builder — will be used when setting default peak broadening parameters
DEFAULT_PHASE_CRYSTALLITE_SIZE = 10 # isotropic crystallite size in microns
# TODO: Phase 2 upstream recipe builder — will be used when setting default peak broadening parameters
DEFAULT_PHASE_MICROSTRAIN = 0.0 # isotropic microstrain
DEFAULT_SPF_SIGMA_MIN = 0.0001  # Minimum sigma_sq value for single peak fitting (centidegrees)
DEFAULT_SPF_GAMMA_MIN = 0.0001 # Minimum gamma value for single peak fitting (centidegrees)


def unpack_refinement_parameter(param: list | None, param_name: str = "parameter") -> tuple[Any, Any, Any, Any]:
    """
    Unpack a refinement parameter: [value, refine_flag] (gsasii 0.1.0; no bounds, so min and
    max are returned as None) or the older 4-element form [value, refine_flag, min, max].

    This utility reduces boilerplate for the common pattern of unpacking refinement
    parameters throughout the codebase. Use only in straightforward cases - complex
    conditional logic should inline the unpacking for clarity.

    Args:
        param: RefinementParameter list [value, refine_flag, min, max] or
            [value, refine_flag], or None
        param_name: Name of parameter for error messages (optional)

    Returns:
        Tuple of (value, refine_flag, min_val, max_val)
        If param is None, returns (None, None, None, None)

    Raises:
        ValueError: If param is neither list nor None

    Examples:
        >>> value, refine_flag, min_val, max_val = unpack_refinement_parameter([1.0, True, None, None])
        >>> value, refine_flag, min_val, max_val = unpack_refinement_parameter(None)
    """
    if param is None:
        return (None, None, None, None)
    elif isinstance(param, list):
        if len(param) == 2:  # gsasii 0.1.0 RefinableParameter (A39, A84)
            return (param[0], param[1], None, None)
        if len(param) != 4:
            raise ValueError(
                f"{param_name} must be a list of exactly 4 elements "
                f"[value, refine_flag, min, max] or 2 elements [value, refine_flag], "
                f"got {len(param)} elements"
            )
        return tuple(param)
    else:
        raise ValueError(
            f"{param_name} must be a list [value, refine_flag, min, max] or None, "
            f"got {type(param).__name__}"
        )


def require_phase(error_suffix: str):
    """
    Decorator to check phase existence in project before calling setter functions.

    Args:
        error_suffix: The error message suffix (e.g., "Cannot set scale.")

    The decorated function must accept 'proj' as first positional arg and 'phase_name'
    as a keyword or positional arg (position determined by inspection).

    Raises:
        ValueError: If phase_name is not found in proj.phases()
    """
    from functools import wraps
    import inspect

    def decorator(func):
        sig = inspect.signature(func)
        # Decoration-time misuse check: decorated functions must take these args.
        assert 'proj' in sig.parameters and 'phase_name' in sig.parameters

        @wraps(func)
        def wrapper(*args, **kwargs):
            # Find proj and phase_name from args/kwargs
            try:
                bound = sig.bind(*args, **kwargs)
            except TypeError:
                # Missing/extra arguments: call through so Python raises the
                # function's native signature error, as the undecorated
                # function would.
                return func(*args, **kwargs)
            bound.apply_defaults()

            proj = bound.arguments['proj']
            phase_name = bound.arguments['phase_name']

            # Perform the phase existence check unconditionally — the original
            # inline checks treated phase_name=None as a missing phase
            # (ValueError) and proj=None as an AttributeError; both semantics
            # are preserved by not special-casing None.
            if phase_name not in [p.name for p in proj.phases()]:
                raise ValueError(f"Phase '{phase_name}' not found in project. {error_suffix}")

            return func(*args, **kwargs)
        return wrapper
    return decorator


def calculate_peak_widths(sigma: float, gamma: float) -> tuple[float, float, float, float, float, float, bool, str | None]:
    """
    Calculate FWHM and integral breadth values for Gaussian, Lorentzian, and pseudo-Voigt peak shapes.

    Parameters:
        sigma: Squareroot of Gaussian width variance. No units assumed.
        gamma: Lorentzian width parameter (HWHM). No units assumed.

    Returns:
        Tuple of (fwhm_gaussian, fwhm_lorentzian, fwhm_pseudovoigt,
                  ib_gaussian, ib_lorentzian, ib_pseudovoigt, valid, warning_msg)
        valid: True if calculation succeeded (even with aphysical values), False for NaN/inf
        warning_msg: String describing any issues, or None if none

    NOTE: This functions differs from GSAS-II's internal getgamFW() which uses gamma as FWHM_L.
    Conventionally, gamma is HWHM_L. This function uses gamma as HWHM_L for consistency with scipy, TOPAS, and literature.
    """
    import warnings
    warning_msg = None

    # FWHM for Gaussian component
    fwhm_g = 2.0 * np.sqrt(2.0 * np.log(2.0)) * sigma  # ≈ 2.35482 * sigma

    # FWHM for Lorentzian component - NOTE: GSAS-II uses gamma = FWHM_L, not gamma = HWHM_L.
    fwhm_l = 2.0 * gamma

    # Pseudo-Voigt FWHM approximation (Thompson et al. 1987)
    fwhm_pv = (fwhm_g**5 + 2.69269*fwhm_g**4*fwhm_l + 2.42843*fwhm_g**3*fwhm_l**2 +
               4.47163*fwhm_g**2*fwhm_l**3 + 0.07842*fwhm_g*fwhm_l**4 + fwhm_l**5)**(1/5)

    try:
        gsas_fwhm = G2pwd.getgamFW(fwhm_l, sigma) # Call GSAS-II function - use FWHM_L (=gamma from SPF) and sigma
        if abs(fwhm_pv - gsas_fwhm) > 0.01 * abs(gsas_fwhm):  # >1% difference
            msg = f"Calculated FWHM ({fwhm_pv:.6f}) differs from GSAS-II ({gsas_fwhm:.6f})"
            warnings.warn(msg)
            warning_msg = msg if warning_msg is None else f"{warning_msg}; {msg}"
    except Exception as e:
        # GSAS-II function may fail with negative values
        msg = f"GSAS-II getgamFW() failed: {str(e)}"
        warnings.warn(msg)
        warning_msg = msg if warning_msg is None else f"{warning_msg}; {msg}"

    # Integral breadths
    # For Gaussian: IB = FWHM * sqrt(π / (4 * ln(2))) ≈ FWHM * 1.0645
    ib_g = fwhm_g * np.sqrt(np.pi / (4.0 * np.log(2.0)))

    # For Lorentzian: IB = π * HWHM = π * gamma = (π/2) * FWHM
    ib_l = np.pi * gamma  # or equivalently: fwhm_l * np.pi / 2.0

    # For pseudo-Voigt: approximate using convolution relationship
    # IB_pV ≈ η * IB_L + (1-η) * IB_G, where η is mixing parameter
    # Simplified approximation (may need refinement based on actual η calculation)
    try:
        eta = 1.36603 * (fwhm_l / fwhm_pv) - 0.47719 * (fwhm_l / fwhm_pv)**2 + 0.11116 * (fwhm_l / fwhm_pv)**3
        ib_pv = eta * ib_l + (1.0 - eta) * ib_g
    except (ZeroDivisionError, RuntimeWarning):
        ib_pv = np.nan
        warning_msg = "Failed to calculate pseudo-Voigt integral breadth" if warning_msg is None else f"{warning_msg}; eta calculation failed"

    return fwhm_g, fwhm_l, fwhm_pv, ib_g, ib_l, ib_pv, True, warning_msg


def has_active_refinement_parameter(atom_param: dict) -> bool:
    """
    Check if any refinement parameter has non-default values.

    Parameters:
    atom_param : dict
        Atom parameters dict with keys like 'x', 'y', 'z', 'occupancy', 'ADP', 'Uiso', 'Uaniso'

    Returns:
    bool
        True if any parameter should be set (not all [None, False, None, None])

    Notes:
    - Skips 'ADP' field (string, not refinement parameter)
    - Handles 'Uaniso' nested dict separately
    - Checks RefinementParameter lists for non-default values
    """
    for key, value in atom_param.items():
        if key == 'ADP':
            continue  # Skip ADP type string (not a refinement parameter)

        if key == 'Uaniso' and isinstance(value, dict):
            # Check nested Uaniso dict - any U value not [None, False, None, None]?
            if any(v is not None and v != [None, False, None, None] for v in value.values()):
                return True

        elif isinstance(value, list) and len(value) in (2, 4):
            # Check RefinementParameter list [value, refine_flag, min, max] or [value, refine_flag]
            if value != [None, False, None, None]:
                return True

    return False
