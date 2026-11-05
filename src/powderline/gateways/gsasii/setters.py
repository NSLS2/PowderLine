"""GSAS-II gateway — refinement-parameter setters.

Moved verbatim from ``powderline/kicker.py`` (multi-engine refactor, re/01).
"""
from __future__ import annotations
import numpy as np
from typing import Any
from GSASII import GSASIIlattice as G2lat
from powderline.gateways.gsasii.constraints import atom_refinement_plan, cell_refinement_plan

from powderline.gateways.gsasii.helpers import (
    has_active_refinement_parameter,
    require_phase,
    unpack_refinement_parameter,
)



# By default (G2obj.SetSampleDefault() called when adding histogram) histogram scale set to refine
def set_hist_scale(proj: Any, hist: Any, hist_scale_val: float = 1.0, hist_scale_refine_flag: bool = False, print_info: bool = False) -> None:
    """Set histogram scale and refine flag."""
    proj.data[hist.name]['Sample Parameters']['Scale'] = [hist_scale_val, hist_scale_refine_flag]
    if print_info:
        print(f"Set histogram scale to {hist_scale_val} with refine flag {hist_scale_refine_flag} for histogram {hist.name}")


def set_fit_range_hist(hist: Any, fit_range: tuple[float | None, float | None], print_info: bool = False) -> None:
    """Set fit range for histogram in GSAS-II project."""
    min_val, max_val = fit_range
    old_limits = hist.data['Limits'][1].copy() # this is a view on the object, need to save old limits before changing
    if min_val is not None:
        hist.data['Limits'][1][0] = min_val
    if max_val is not None:
        hist.data['Limits'][1][1] = max_val
    if print_info:
        print('Updated fit limits in hist from ', old_limits, 'to', hist.data['Limits'][1])


def set_chebyshev_background(proj: Any, hist: Any, chebyshev_dict: dict, print_info: bool = False) -> None:
    """
    Set the Chebyshev background for a given histogram.

    Chebyshev polynomials provide smooth curved backgrounds. Coefficients start
    at 0th order (constant term) and increase: [c0, c1, c2, ...] represents
    c0 + c1*T1(x) + c2*T2(x) + ... where Tn are Chebyshev polynomials.

    The function manipulates proj.data[hist.name]['Background'][0] which has structure:
    [background_type, refine_flag, num_coefficients, c0, c1, c2, ...]

    Parameters:
        proj: GSAS-II project object containing the histogram
        hist: Histogram object to set the background for
        chebyshev_dict: Dictionary containing Chebyshev background parameters:
            - num_coefficients (int): Number of Chebyshev coefficients
            - coefficients (list[float]): Coefficient values [c0, c1, c2, ...]
            - refine_flag (bool): Whether to refine background during fitting
        print_info: If True, print background configuration to stdout

    Returns:
        None

    Raises:
        ValueError: If number of coefficients doesn't match list length or
                   required background entries are missing

    Examples:
        >>> chebyshev_dict = {
        ...     'num_coefficients': 3,
        ...     'coefficients': [100.0, -50.0, 10.0],
        ...     'refine_flag': True
        ... }
        >>> set_chebyshev_background(proj, hist, chebyshev_dict)
    """
    # First parse the chebyshev_dict
    num_coefficients = chebyshev_dict.get('num_coefficients')
    coefficients = chebyshev_dict.get('coefficients')
    refine_flag = chebyshev_dict.get('refine_flag')

    # Defaults are not provided because those will be provided upstream
    # None will be caught in validation and trigger a default assignment.
    # The code below is an example of how to handle defaults here if needed.

    # This should be enforced with the pydantic schema when loading the recipe
    if coefficients is None:
        coefficients = [0.0] * num_coefficients

    if num_coefficients != len(coefficients):
        raise ValueError(
            "Number of coefficients does not match the length of the coefficients list."
        )

    chebyshev_bkg = proj.data[hist.name]['Background'][0]

    # Check for default entries (type, refine flag, num coefficients)
    if len(chebyshev_bkg) < 3:
        raise ValueError("Chebyshev background list missing required entries. type, refine flag, num coefficients should be present by default.")

    # Set number of coefficients
    chebyshev_bkg[2] = num_coefficients

    # Pad or truncate the coefficients list in chebyshev_bkg to match num_coefficients
    # This would be done in an earlier validation step!
    needed_len = num_coefficients + 3
    if len(chebyshev_bkg) < needed_len:
        chebyshev_bkg.extend([0.0] * (needed_len - len(chebyshev_bkg)))
    elif len(chebyshev_bkg) > needed_len:
        del chebyshev_bkg[needed_len:]  # in-place truncate

    # Set coefficients
    for i, coeff in enumerate(coefficients):
        chebyshev_bkg[i + 3] = coeff

    # Set refine flag
    chebyshev_bkg[1] = refine_flag

    if print_info:
        print(f"Chebyshev background set with {chebyshev_bkg[2]} coeffiencients, refine_flag={chebyshev_bkg[1]}")
        print(f"Coefficients: {chebyshev_bkg[3:3+chebyshev_bkg[2]]}")


# function to set single peak background
# this should be a rather exposed function
# e.g., take lists of positions, intensities, sigmas, gammas, refine flags, etc.
# This function should expect inputs from the background_dict['single_peaks'] structure

def set_single_peak_background(proj: Any, hist: Any, bkg_single_peaks_dict: dict, print_info: bool = False) -> None:
    """
    Set single peak background for histogram using pseudo-Voigt profiles.

    Single peaks are useful for modeling known impurity peaks or other non-background
    features that shouldn't be included in the main phase refinement. Each peak is
    described by a pseudo-Voigt profile (weighted sum of Gaussian and Lorentzian).

    Peak profile: I(2θ) = intensity * [η*L(2θ) + (1-η)*G(2θ)]
    where:
    - G(2θ) is Gaussian with width sigma
    - L(2θ) is Lorentzian with width gamma
    - η (eta) is mixing parameter (0=pure Gaussian, 1=pure Lorentzian)

    Args:
        proj: GSAS-II project object
        hist: Histogram object to set single peaks for
        bkg_single_peaks_dict: Dictionary with keys:
            - positions: List of [[2θ, refine], ...] for peak positions
            - intensities: List of [[I, refine], ...] for peak heights
            - pv_gaussian_sigma_sq: List of [[σ², refine], ...] Gaussian variances, centideg²
            - pv_lorentzian_gamma: List of [[γ, refine], ...] for Lorentzian widths
            All lists must have same length (number of peaks)
        print_info: If True, print peak configuration to stdout

    Returns:
        None

    Raises:
        ValueError: If parameter lists have inconsistent lengths

    Examples:
        >>> # Two single peaks at 2θ=35.5° and 42.0°
        >>> single_peaks = {
        ...     'positions': [[35.5, False], [42.0, False]],
        ...     'intensities': [[50.0, True], [30.0, True]],
        ...     'pv_gaussian_sigma_sq': [[0.1, False], [0.1, False]],
        ...     'pv_lorentzian_gamma': [[0.15, False], [0.15, False]]
        ... }
        >>> set_single_peak_background(proj, hist, single_peaks)
    """
    """
    Set the single peak background for a given histogram.

    Parameters:
    proj: object
        The GSAS-II project containing the histogram.
    hist : object
        The histogram to set the background for.
    bkg_single_peaks_dict : dict
        Dictionary containing single peak background parameters:
        - positions : list of [float, bool]: [position value, refine flag] for each peak.
            These are two-theta values. Q / d can be passed upstream and converted in validation.
        - intensities: list of [float, bool]: [intensity value, refine flag] for each peak.
        - pv_gaussian_sigma_sq: list of [float, bool]: [Gaussian variance (centideg²), refine flag]
            for each peak.
        - pv_lorentzian_gamma: list of [float, bool]: [Lorentzian gamma value, refine flag] for each peak.
    print_info : bool
        Whether to print information about the set background.
    Returns:
    None
    """
    # Parse the bkg_single_peaks_dict
    positions = bkg_single_peaks_dict.get('positions', [])
    intensities = bkg_single_peaks_dict.get('intensities', [])
    gaussian_sigmas = bkg_single_peaks_dict.get('pv_gaussian_sigma_sq', [])
    lorentzian_gammas = bkg_single_peaks_dict.get('pv_lorentzian_gamma', [])

    # Default intensity, sigma, gamma values to use if value input is None
    # TODO: Phase 2 upstream recipe builder — these defaults will be set before calling this function
    # default_intensity = 1.0
    # default_sigma = 0.1
    # default_gamma = 0.1
    # default_refine_flag = False

    # Validate that all input lists have the same length
    if not (len(positions) == len(intensities) == len(gaussian_sigmas) == len(lorentzian_gammas)):
        raise ValueError("All input lists must have the same length.")

    num_peaks = len(positions) # only used for looping

    # Construct the single peak background list
    single_peak_bkg = []

    for i in range(num_peaks):
        pos, pos_refine, pos_min, pos_max = unpack_refinement_parameter(positions[i], "positions")
        inten, inten_refine, inten_min, inten_max = unpack_refinement_parameter(intensities[i], "intensities")
        g_sigma, g_refine, g_sigma_min, g_sigma_max = unpack_refinement_parameter(gaussian_sigmas[i], "pv_gaussian_sigma_sq")
        l_gamma, l_refine, l_gamma_min, l_gamma_max = unpack_refinement_parameter(lorentzian_gammas[i], "pv_lorentzian_gamma")

        # TODO: move default behavior upstream
        # # Use default values if None provided
        # if inten is None:
        #     inten = default_intensity
        # if g_sigma is None:
        #     g_sigma = default_sigma
        # if l_gamma is None:
        #     l_gamma = default_gamma

        # # Use default refine flags if None provided
        # if pos_refine is None:
        #     pos_refine = default_refine_flag
        # if inten_refine is None:
        #     inten_refine = default_refine_flag
        # if g_refine is None:
        #     g_refine = default_refine_flag
        # if l_refine is None:
        #     l_refine = default_refine_flag

        # Min / max not currently available in GSAS-II single peak background definition
        # They can be stored upstream for reference, but not used downstream currently.
        # [placeholder for code to handle min/max if needed in future]

        # Append peak parameters to the single peak background list
        # Each peak is a list:
        # [pos, pos_refine, inten, inten_refine, g_sigma, g_refine, l_gamma, l_refine]
        if None in [pos, pos_refine,
                                inten, inten_refine,
                                g_sigma, g_refine,
                                l_gamma, l_refine]:
            continue

        # We only append if there are no Nones - this is a temp fix before phase2
        # TODO: update this behavior in the future when this list will only be passed with valid contents
        single_peak_bkg.append([pos, pos_refine,
                                inten, inten_refine,
                                g_sigma, g_refine,
                                l_gamma, l_refine])

    # Append the single peak background to the histogram's background list
    if proj.data[hist.name]['Background'][1]['peaksList'] is None:
        proj.data[hist.name]['Background'][1]['peaksList'] = []

    # Since single_peak_bkg is a list of peaks, we need to append each peak individually
    for peak in single_peak_bkg:
        proj.data[hist.name]['Background'][1]['peaksList'].append(peak)

    # Update the number of peaks
    proj.data[hist.name]['Background'][1]['nPeaks'] = len(proj.data[hist.name]['Background'][1]['peaksList'])

    # if print_info, then print details about the set background using the proj data, not the inputs
    if print_info:
        print(f"Single peak background set with {proj.data[hist.name]['Background'][1]['nPeaks']} peaks:")
        for peak in proj.data[hist.name]['Background'][1]['peaksList']:
            print(f"  Position: {peak[0]} (refine: {peak[1]}), Intensity: {peak[2]} (refine: {peak[3]}), "
                  f"Gaussian Sigma: {peak[4]} (refine: {peak[5]}), Lorentzian Gamma: {peak[6]} (refine: {peak[7]})")


def set_single_peaks(proj: Any, hist: Any, single_peaks_dict: dict, print_info: bool = False) -> None:
    """
    Set single peaks in the Peak List (non-background peaks) with direct control over position, intensity,
    and pseudo-Voigt width parameters (sigma_sq, gamma).

    **Schema 0.24:** Values should be sigma² (variance), not sigma - no conversion is performed.
    Peak fitting mode is controlled by refinement strategy execution functions via
    refinement_controls.single_peak_fitting_mode and passed to hist.refine_peaks().

    sigma_sq and gamma must be positive non-zero values.
    GSAS-II does not use negative values for FWHM calc and instead enforces a minimum (0.001 in centidegrees for sigma and gamma).
    In our approach, we raise an error for negative or zero values to avoid confusion.
    GSAS-II will output negative values if refined to such, but uses the near-zero value in PV calculation.

    Parameters:
        proj: GSAS-II project object
        hist: Histogram object
        single_peaks_dict: Dictionary containing peak parameters (positions, intensities, pv_gaussian_sigma_sq, pv_lorentzian_gamma)
        print_info: If True, print details about set peaks
    """
    # Extract parameters from dict
    positions = single_peaks_dict.get('positions')
    intensities = single_peaks_dict.get('intensities')
    pv_gaussian_sigma_sq = single_peaks_dict.get('pv_gaussian_sigma_sq')
    pv_lorentzian_gamma = single_peaks_dict.get('pv_lorentzian_gamma')

    # Validate that all required lists are present
    required_keys = ['positions', 'intensities', 'pv_gaussian_sigma_sq', 'pv_lorentzian_gamma']
    for key in required_keys:
        if single_peaks_dict.get(key) is None:
            raise ValueError(f"Missing required key '{key}' in single_peaks_dict")

    # Validate all lists are non-empty
    if not positions or len(positions) == 0:
        raise ValueError("positions list cannot be empty")
    if not intensities or len(intensities) == 0:
        raise ValueError("intensities list cannot be empty")
    if not pv_gaussian_sigma_sq or len(pv_gaussian_sigma_sq) == 0:
        raise ValueError("pv_gaussian_sigma_sq list cannot be empty")
    if not pv_lorentzian_gamma or len(pv_lorentzian_gamma) == 0:
        raise ValueError("pv_lorentzian_gamma list cannot be empty")

    # Validate all lists have the same length
    list_lengths = [
        len(positions),
        len(intensities),
        len(pv_gaussian_sigma_sq),
        len(pv_lorentzian_gamma)
    ]
    if len(set(list_lengths)) > 1:
        raise ValueError(
            f"All peak parameter lists must have the same length. "
            f"Got: positions={len(positions)}, intensities={len(intensities)}, "
            f"pv_gaussian_sigma_sq={len(pv_gaussian_sigma_sq)}, pv_lorentzian_gamma={len(pv_lorentzian_gamma)}"
        )

    num_peaks = len(positions)

    # Check if Peak List exists, initialize if not
    if 'Peak List' not in proj.data[hist.name]:
        import warnings
        warnings.warn(f"Peak List not found for histogram {hist.name}. Initializing with default structure.")
        proj.data[hist.name]['Peak List'] = {
            'peaks': [],
            'sigDict': {},
            'xtraPeaks': [],
            'xtraMode': False
        }

    # Build peak list
    peaks_list = []
    for i in range(num_peaks):
        # Extract values and refine flags from RefinementParameter format [value, refine_flag, min, max]
        pos_val, pos_refine = positions[i][0], positions[i][1]
        int_val, int_refine = intensities[i][0], intensities[i][1]
        sigma_sq_val, sigma_sq_refine = pv_gaussian_sigma_sq[i][0], pv_gaussian_sigma_sq[i][1]
        gamma_val, gamma_refine = pv_lorentzian_gamma[i][0], pv_lorentzian_gamma[i][1]

        # Input validation - check for invalid values
        if np.isnan(sigma_sq_val) or np.isinf(sigma_sq_val):
            raise ValueError(f"Peak {i}: sigma² value is NaN or inf ({sigma_sq_val}), which is always invalid")
        if np.isnan(gamma_val) or np.isinf(gamma_val):
            raise ValueError(f"Peak {i}: gamma value is NaN or inf ({gamma_val}), which is always invalid")

        # Check for negative or zero values, raise Error (while GSAS-II allows negative values, we will not in our approach)
        if sigma_sq_val <= 0:
            raise ValueError(f"Peak {i}: sigma² <= 0 ({sigma_sq_val}), which is invalid for peak fitting")
        if gamma_val <= 0:
            raise ValueError(f"Peak {i}: gamma <= 0 ({gamma_val}), which is invalid for peak fitting")

        # Convert boolean refine flags to integers (0 or 1)
        pos_flag = 1 if pos_refine else 0
        int_flag = 1 if int_refine else 0
        # Refine flag for sig² (variance) - input is already sigma² from GUI/calculations
        sig_sq_flag = 1 if sigma_sq_refine else 0
        gamma_flag = 1 if gamma_refine else 0

        # Build peak as: [pos, pos_flag, intensity, int_flag, sig², sig²_flag, gamma, gam_flag]
        peak = [pos_val, pos_flag, int_val, int_flag, sigma_sq_val, sig_sq_flag, gamma_val, gamma_flag]
        peaks_list.append(peak)

    # Set peaks in Peak List
    proj.data[hist.name]['Peak List']['peaks'] = peaks_list

    # Print info if requested
    if print_info:
        print(f"Single peaks (Peak List) set with {num_peaks} peaks:")
        for i, peak in enumerate(peaks_list):
            pos, pos_flag, intensity, int_flag, sig_sq, sig_sq_flag, gamma, gam_flag = peak
            print(f"  Peak {i+1}: Position={pos:.4f} (refine: {bool(pos_flag)}), "
                  f"Intensity={intensity:.4f} (refine: {bool(int_flag)}), "
                  f"Sigma²={sig_sq:.6f}, (refine: {bool(sig_sq_flag)}), "
                  f"Gamma={gamma:.6f} (refine: {bool(gam_flag)})")


##################################################################
# Functions for phase parameterization

@require_phase("Cannot set scale.")
def set_phase_scale(proj: Any, hist: Any, phase_name: str, scale_param: list, print_info: bool = False) -> None:
    """
    Set the phase scale factor in the GSAS-II project.

    Parameters:
    proj : GSAS-II project object
        The GSAS-II project containing the phase.
    hist : GSAS-II histogram object
        The histogram associated with the phase.
    phase_name : str
        The name of the phase to set the scale for.
    scale_param : list
        List containing [value, refine_flag, min, max] for the scale factor.

    Returns:
    None
    """
    value, refine_flag, min_val, max_val = unpack_refinement_parameter(scale_param, "scale_param")

    # Set the scale factor value - defaults will be handled upstream in future in validation
    if value is not None:
        proj.data['Phases'][phase_name]['Histograms'][hist.name]['Scale'][0] = value

    # Set refinement flag
    if refine_flag is not None:
        proj.data['Phases'][phase_name]['Histograms'][hist.name]['Scale'][1] = refine_flag
    # Set min and max if provided - CURRENTLY NOT IMPLEMENETED. Unclear if allowed in GSAS-II.
    # if min_val is not None:
    #     phase.set_parameter_min('Scale', min_val)
    # if max_val is not None:
    #     phase.set_parameter_max('Scale', max_val)

    if print_info:
        print(f"Set scale for phase '{phase_name}' to {value} with refine_flag={refine_flag}")

@require_phase("Cannot set unit cell parameters.")
def set_phase_unit_cell(proj: Any, phase_name: str, unit_cell_dict: dict, print_info: bool = False) -> list[str]:
    """
    Set the unit cell parameters in the GSAS-II project for a given phase.

    Per-parameter refine semantics: each cell parameter refines iff it is present with
    refine_flag=true; absent or false means fixed. Because GSAS-II has a single
    whole-cell refine flag, per-parameter control is achieved by setting that
    flag when any symmetry degree-of-freedom (DOF) group is requested and
    returning "Hold" constraint variable names (e.g. '0::A2') for the DOF
    groups that were not requested. Symmetry-linked parameters (e.g. cubic
    a=b=c, or the coupled monoclinic {a, c, beta}) refine together if any
    member is requested — see powderline.gateways.gsasii.constraints.

    Parameters:
    proj : GSAS-II project object
        The GSAS-II project containing the phase.
    phase_name : str
        The name of the phase to set the unit cell for.
    unit_cell_dict : dict
        Dictionary containing unit cell parameters and their parameterization.
    print_info : bool
        Whether to print information about the set unit cell.

    Returns:
    list[str]
        GSAS-II variable names to Hold (empty when the whole cell refines or
        is entirely fixed). The caller applies them via proj.add_HoldConstr.
    """

    # Note: cell values are set verbatim; validating them against the phase's
    # crystal system is intentionally NOT done here (PowderLine is the engine,
    # not the arbiter of recipe correctness — see docs/development/known-issues.md, KI-01).

    # Note2: hist not required since unit cell is phase-specific, not histogram-specific.
    # The delineation of phase and histogram parameters is confusing in GSAS-II documentation.
    # This makes sticking with a project based approach more straightforward.

    phase_names = [p.name for p in proj.phases()]
    cell_changed = False
    cell_params = ['a', 'b', 'c', 'alpha', 'beta', 'gamma'] # must match schema, and match order in GSAS-II

    for i, param in enumerate(cell_params):
        if unit_cell_dict.get(param) is not None:
            value, refine_flag, min_val, max_val = unpack_refinement_parameter(unit_cell_dict[param], param)

            # Set the unit cell parameter value - a=1, b=2, c=3, alpha=4, beta=5, gamma=6
            if value is not None:
                proj.data['Phases'][phase_name]['General']['Cell'][i+1] = value
                cell_changed = True

            # Set min and max if provided - CURRENTLY NOT IMPLEMENTED (deferred;
            # GSAS-II's own min/max semantics differ from simple bounds).

    # Calculate and set volume from unit cell parameters only if cell was changed
    if cell_changed:
        cell = proj.data['Phases'][phase_name]['General']['Cell'][1:7] # get list of a, b, c, alpha, beta, gamma
        proj.data['Phases'][phase_name]['General']['Cell'][7] = G2lat.calc_V(G2lat.cell2A(cell)) # index 7 is volume

    # Translate per-parameter refine flags into the whole-cell flag + holds
    SGData = proj.data['Phases'][phase_name]['General']['SGData']
    phase_idx = phase_names.index(phase_name)
    cell_plan = cell_refinement_plan(SGData, unit_cell_dict, phase_idx)
    proj.data['Phases'][phase_name]['General']['Cell'][0] = cell_plan.refine_cell

    if print_info:
        curr_cell = proj.data['Phases'][phase_name]['General']['Cell']
        if cell_changed:
            cell_prms_dict = {"a": curr_cell[1],
                            "b": curr_cell[2],
                            "c": curr_cell[3],
                            "alpha": curr_cell[4],
                            "beta": curr_cell[5],
                            "gamma": curr_cell[6],
                            "volume": curr_cell[7]}

            print(f"Set unit cell parameters for phase '{phase_name}' to {[(key, value) for key, value in cell_prms_dict.items()]} with refine_flag={curr_cell[0]}")
        else:
            print(f"No unit cell parameters were changed for phase '{phase_name}'. Refine_flag={curr_cell[0]}")
        if cell_plan.holds:
            print(f"Holding fixed unit cell DOFs for phase '{phase_name}': {cell_plan.holds}")

    return cell_plan.holds


@require_phase("Cannot set size broadening parameters.")
def set_phase_size_broadening(proj: Any, hist: Any, phase_name: str, size_broadening_dict: dict, print_info: bool = False) -> None:
    """
    Set size broadening parameters in the GSAS-II project for a given phase.

    Supports model branching for isotropic, uniaxial, and ellipsoidal models.
    Currently only isotropic model is implemented - others raise NotImplementedError.

    Parameters:
    proj : GSAS-II project object
        The GSAS-II project containing the phase.
    hist : GSAS-II histogram object
        The histogram associated with the phase.
    phase_name : str
        The name of the phase to set the size broadening for.
    size_broadening_dict : dict
        Dictionary containing size broadening parameters with 'model' key.

    Raises:
        NotImplementedError: For uniaxial or ellipsoidal models
        ValueError: For unknown model types or invalid parameters

    Returns:
    None
    """
    # Extract model type (default to isotropic for backward compatibility)
    model = size_broadening_dict.get('model', 'isotropic')

    # Validate model type
    valid_models = ['isotropic', 'uniaxial', 'ellipsoidal']
    if model not in valid_models:
        raise ValueError(
            f"Unknown size broadening model '{model}'. "
            f"Valid options: {valid_models}"
        )

    # Set model type in GSAS-II data structure
    proj.data['Phases'][phase_name]['Histograms'][hist.name]['Size'][0] = model

    # Branch on model type
    if model == 'isotropic':
        _set_isotropic_size_broadening(proj, hist, phase_name, size_broadening_dict, print_info)
    elif model == 'uniaxial':
        raise NotImplementedError(
            "Uniaxial size broadening model is not yet implemented. "
            "Support planned for future release. Use 'isotropic' model instead."
        )
    elif model == 'ellipsoidal':
        raise NotImplementedError(
            "Ellipsoidal size broadening model is not yet implemented. "
            "Support planned for future release. Use 'isotropic' model instead."
        )


def _set_isotropic_size_broadening(proj: Any, hist: Any, phase_name: str, size_broadening_dict: dict, print_info: bool = False) -> None:
    """
    Set isotropic size broadening parameters (internal helper).

    Refactored from original set_phase_size_broadening function.
    """

    # Example structure of proj.data['Phases'][phase_name]['Histograms'][hist.name]['Size']:
    # ['isotropic', # [0]: str for broadening type. 'isotropic', 'uniaxial', or 'ellipsoidal'
    # [1.0, 1.0, 1.0], # [1][0]: iso size or equatorial size, [1][1]: axial size (if uniaxial used, else ignored), [1][2]: LG_mix (eta parameter, 1 = Lorentzian, 0 = Gaussian)
    # [False, False, False], # boolean refinement flags. [2][0]: isotropic or uniaxial equatorial refine, [2][1]: uniaxial axial refine, [2][2]: LG_mix refine
    # [0, 0, 1], # hkl direction for uniaxial broadening. [3][0]: h, [3][1]: k, [3][2]: l
    # [1.0, 1.0, 1.0, 0.0, 0.0, 0.0], # ellipsoidal sizes. S11, S22, S33, S12, S13, S23 for [4][0:6]
    # [False, False, False, False, False, False]]  # ellipsoidal size refine flags. S11, S22, S33, S12, S13, S23 for [5][0:6]
    ############################
    # Set isotropic size parameters
    ############################
    value, refine_flag, min_val, max_val = unpack_refinement_parameter(
        size_broadening_dict.get('isotropic_size'), "isotropic_size"
    )

    # Set the size parameter value
    if value is not None:
        proj.data['Phases'][phase_name]['Histograms'][hist.name]['Size'][1][0] = value

    # Set refinement flag
    if refine_flag is not None:
        proj.data['Phases'][phase_name]['Histograms'][hist.name]['Size'][2][0] = refine_flag

    # Set min and max if provided - CURRENTLY NOT IMPLEMENTED. Unclear if allowed in GSAS-II.

    if print_info:
        print(f"Set size broadening size parameters for phase '{phase_name}' to {value} with refine_flag={refine_flag}")

    ############################
    # Set size LG_eta parameter
    ############################
    try:
        value, refine_flag, min_val, max_val = unpack_refinement_parameter(
            size_broadening_dict.get('LG_eta'), "LG_eta"
        )
    except (ValueError, TypeError) as e:
        # Preserve original error message format
        raise ValueError(f"Size broadening 'LG_eta' parameter must be a list or None.\nType for phase {phase_name} is {type(size_broadening_dict['LG_eta'])}.") from e

    # Set the LG_eta parameter value
    if value is not None:
        proj.data['Phases'][phase_name]['Histograms'][hist.name]['Size'][1][2] = value

    # Set refinement flag
    if refine_flag is not None:
        proj.data['Phases'][phase_name]['Histograms'][hist.name]['Size'][2][2] = refine_flag

    # Set min and max if provided - CURRENTLY NOT IMPLEMENTED. Unclear if allowed in GSAS-II.

    if print_info:
        print(f"Set size broadening LG_eta parameters for phase '{phase_name}' to {value} with refine_flag={refine_flag}")


# Setting strain broadening should be done in the same way as size broadening
# The dictionary structure is very similar. We just need to map to the correct keys in the proj.data structure.

@require_phase("Cannot set strain broadening parameters.")
def set_phase_strain_broadening(proj: Any, hist: Any, phase_name: str, strain_broadening_dict: dict, print_info: bool = False) -> None:
    """
    Set strain broadening parameters in the GSAS-II project for a given phase.

    Supports model branching for isotropic, uniaxial, and generalized (Stephens) models.
    Currently only isotropic model is implemented - others raise NotImplementedError.

    Parameters:
    proj : GSAS-II project object
        The GSAS-II project containing the phase.
    hist : GSAS-II histogram object
        The histogram associated with the phase.
    phase_name : str
        The name of the phase to set the strain broadening for.
    strain_broadening_dict : dict
        Dictionary containing strain broadening parameters with 'model' key.

    Raises:
        NotImplementedError: For uniaxial or generalized models
        ValueError: For unknown model types or invalid parameters

    Returns:
    None
    """
    # Extract model type (default to isotropic for backward compatibility)
    model = strain_broadening_dict.get('model', 'isotropic')

    # Validate model type
    valid_models = ['isotropic', 'uniaxial', 'generalized']
    if model not in valid_models:
        raise ValueError(
            f"Unknown strain broadening model '{model}'. "
            f"Valid options: {valid_models}"
        )

    # Set model type in GSAS-II data structure
    proj.data['Phases'][phase_name]['Histograms'][hist.name]['Mustrain'][0] = model

    # Branch on model type
    if model == 'isotropic':
        _set_isotropic_strain_broadening(proj, hist, phase_name, strain_broadening_dict, print_info)
    elif model == 'uniaxial':
        raise NotImplementedError(
            "Uniaxial strain broadening model is not yet implemented. "
            "Support planned for future release. Use 'isotropic' model instead."
        )
    elif model == 'generalized':
        raise NotImplementedError(
            "Generalized (Stephens) strain broadening model is not yet implemented. "
            "This model requires complex symmetry-dependent parameterization. "
            "Support planned for Phase 2. Use 'isotropic' model instead."
        )


def _set_isotropic_strain_broadening(proj: Any, hist: Any, phase_name: str, strain_broadening_dict: dict, print_info: bool = False) -> None:
    """
    Set isotropic strain broadening parameters (internal helper).

    Refactored from original set_phase_strain_broadening function.
    """
    ############################
    # Set isotropic strain parameters
    ############################
    value, refine_flag, min_val, max_val = unpack_refinement_parameter(
        strain_broadening_dict.get('isotropic_strain'), "isotropic_strain"
    )

    # Set the strain parameter value
    if value is not None:
        proj.data['Phases'][phase_name]['Histograms'][hist.name]['Mustrain'][1][0] = value

    # Set refinement flag
    if refine_flag is not None:
        proj.data['Phases'][phase_name]['Histograms'][hist.name]['Mustrain'][2][0] = refine_flag

    # Set min and max if provided - CURRENTLY NOT IMPLEMENTED. Unclear if allowed in GSAS-II.

    if print_info:
        print(f"Set strain broadening strain parameters for phase '{phase_name}' to {value} with refine_flag={refine_flag}")

    ############################
    # Set strain LG_eta parameter
    ############################
    try:
        value, refine_flag, min_val, max_val = unpack_refinement_parameter(
            strain_broadening_dict.get('LG_eta'), "LG_eta"
        )
    except (ValueError, TypeError) as e:
        # Preserve original error message format
        raise ValueError(f"Strain broadening dict key 'LG_eta' must hold a value that is a list or None.\nType for phase {phase_name} is {type(strain_broadening_dict['LG_eta'])}.") from e

    # Set the LG_eta parameter value
    if value is not None:
        proj.data['Phases'][phase_name]['Histograms'][hist.name]['Mustrain'][1][2] = value

    # Set refinement flag
    if refine_flag is not None:
        proj.data['Phases'][phase_name]['Histograms'][hist.name]['Mustrain'][2][2] = refine_flag

    # Set min and max if provided - CURRENTLY NOT IMPLEMENTED. Unclear if allowed in GSAS-II.

    if print_info:
        print(f"Set strain broadening LG_eta parameters for phase '{phase_name}' to {value} with refine_flag={refine_flag}")


# Function to set atom parameters for a phase
@require_phase("Cannot set atom parameters.")
def set_phase_atom_parameters(proj: Any, phase_name: str, atom_parameters_dict: dict, print_info: bool = False) -> list[str]:
    """
    Set atom parameters for a phase in the GSAS-II project.

    This function parses atom-specific refinement parameters (coordinates, occupancy, displacement)
    and constructs GSAS-II's refine_flags string ('F', 'X', 'U' combinations).

    Per-parameter refine semantics: each coordinate (x/y/z) and each anisotropic Uij
    component refines iff present with refine_flag=true; absent or false means
    fixed. GSAS-II's 'X'/'U' flags are per-atom, so per-component control is
    achieved by returning "Hold" constraint variable names (e.g. '0::dAy:3',
    '0::AU22:4') for the site-symmetry DOF groups that were not requested —
    see powderline.gateways.gsasii.constraints.
    Symmetry-linked components (e.g. x=y on an (x,x,z) site) refine together
    if any member is requested.

    Parameters:
    proj : GSAS-II project object
        The GSAS-II project containing the phase.
    phase_name : str
        The name of the phase to set the atom parameters for.
    atom_parameters_dict : dict
        Dictionary containing atom parameters and their parameterization.
        E.g., payload['phases'][phase_name]['parameterization']['atoms']

        Expected structure:
        {
            'atom_label': {
                'x': [value, refine_flag, min, max],
                'y': [value, refine_flag, min, max],
                'z': [value, refine_flag, min, max],
                'occupancy': [value, refine_flag, min, max],
                'ADP': 'Uiso' or 'Uaniso',
                'Uiso': [value, refine_flag, min, max],  # if ADP='Uiso'
                'Uaniso': {  # if ADP='Uaniso'
                    'U11': [value, refine_flag, min, max],
                    'U22': [value, refine_flag, min, max],
                    ...
                }
            }
        }
    print_info : bool, optional
        If True, print detailed information about the atom parameters being set. Default is False.

    Returns:
    list[str]
        GSAS-II variable names to Hold (empty when every requested DOF group
        refines in full). The caller applies them via proj.add_HoldConstr.

    Notes:
    proj.data['Phases'][phase_name]['Atoms'] is a list of lists, where each sublist represents an atom and its parameters.
    Sublist structure in atom_param_index_mapping below.

    Example: proj.data['Phases'][phase_name]['Atoms'][0] from LaB6 example returns:
    ['La', 'La', '', 0.0, 0.0, 0.0, 1.0, 'm3m', 1, 'I', 0.00858, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 844046454091148456]

    GSAS-II refine_flags string format (index 2):
    - 'F': refine occupancy
    - 'X': refine all coordinates (x, y, z together)
    - 'U': refine displacement parameters (isotropic or anisotropic)
    - Combinations: 'FXU', 'XU', 'F', etc.
    """

    # Dictionary of atom parameter names to their indices in the atom list
    atom_param_index_mapping = {
        'label': 0, # atom label
        'element': 1, # element symbol
        'refine_flags': 2, # string of refine flags e.g., 'F', 'X', 'U' or any combination such as 'FXU'. F for occupancy, X for xyz coords, U for displacement parameters
        'x': 3, # fractional coordinate x value
        'y': 4, # fractional coordinate y value
        'z': 5, # fractional coordinate z value
        'occupancy': 6, # float, referred to as frac in GSAS-II syntax
        'site_symmetry': 7, # string representation of site symmetry
        'multiplicity': 8, # multiplicity of the site, integer
        'Utype': 9, # 'I' for isotropic, 'A' for anisotropic
        'Uiso': 10, # value if isotropic
        'U11': 11, # value if anisotropic
        'U22': 12, # value if anisotropic
        'U33': 13, # value if anisotropic
        'U12': 14, # value if anisotropic
        'U13': 15, # value if anisotropic
        'U23': 16 # value if anisotropic
        # Note: index 17 is a random unique ID for the atom, not a parameter to set
    }

    phase_names = [p.name for p in proj.phases()]
    phase_idx = phase_names.index(phase_name)
    SGData = proj.data['Phases'][phase_name]['General']['SGData']
    atom_labels_present = [x[0] for x in proj.data['Phases'][phase_name]['Atoms']]
    holds: list[str] = []

    for atom_label, atom_params in atom_parameters_dict.items():
        if atom_label not in atom_labels_present:
            print(f"Atom '{atom_label}' not found in phase '{phase_name}'. Skipping.")
            continue

        # Get the atom record
        atom_index = atom_labels_present.index(atom_label)
        atom_record = proj.data['Phases'][phase_name]['Atoms'][atom_index]

        # Get ADP type for this atom (required in schema 0.22)
        adp_type = atom_params.get('ADP')

        # Process coordinate parameters (x, y, z) — values only; refine flags
        # are translated by atom_refinement_plan below
        for coord in ['x', 'y', 'z']:
            if coord in atom_params and atom_params[coord] is not None:
                param_value = atom_params[coord]
                if param_value != [None, False, None, None]:
                    value, refine_flag, min_val, max_val = unpack_refinement_parameter(param_value, coord)

                    # Update coordinate value if provided
                    if value is not None:
                        atom_record[atom_param_index_mapping[coord]] = value

        # Process occupancy
        if 'occupancy' in atom_params and atom_params['occupancy'] is not None:
            param_value = atom_params['occupancy']
            if param_value != [None, False, None, None]:
                value, refine_flag, min_val, max_val = unpack_refinement_parameter(param_value, 'occupancy')

                # Update occupancy value if provided
                if value is not None:
                    atom_record[6] = value

        # Process displacement parameters based on ADP type
        if adp_type == 'Uiso':
            # Isotropic displacement parameters
            if 'Uiso' in atom_params and atom_params['Uiso'] is not None:
                param_value = atom_params['Uiso']
                if param_value != [None, False, None, None]:
                    value, refine_flag, min_val, max_val = unpack_refinement_parameter(param_value, 'Uiso')

                    # Update Uiso value if provided
                    if value is not None:
                        atom_record[9] = 'I'  # Set to isotropic
                        atom_record[10] = value

        elif adp_type == 'Uaniso':
            # Anisotropic displacement parameters
            if 'Uaniso' in atom_params and atom_params['Uaniso'] is not None:
                uaniso_dict = atom_params['Uaniso']

                # Track if any anisotropic values are being updated
                aniso_values_provided = []

                # Process each anisotropic parameter
                for u_key in ['U11', 'U22', 'U33', 'U12', 'U13', 'U23']:
                    if u_key in uaniso_dict and uaniso_dict[u_key] is not None:
                        param_value = uaniso_dict[u_key]
                        if param_value != [None, False, None, None]:
                            value, refine_flag, min_val, max_val = unpack_refinement_parameter(param_value, u_key)

                            # Update anisotropic value if provided
                            if value is not None:
                                atom_record[9] = 'A'  # Set to anisotropic
                                atom_record[atom_param_index_mapping[u_key]] = value
                                aniso_values_provided.append(u_key)

                # Validate that if any anisotropic values are provided, all 6 must be provided
                if aniso_values_provided:
                    required_keys = ['U11', 'U22', 'U33', 'U12', 'U13', 'U23']
                    missing_keys = [k for k in required_keys if k not in aniso_values_provided]
                    if missing_keys:
                        raise ValueError(
                            f"Atom '{atom_label}' in phase '{phase_name}': "
                            f"When updating anisotropic displacement parameters, all 6 values (U11-U23) must be provided. "
                            f"Missing: {missing_keys}"
                        )

        # Translate per-parameter refine flags into GSAS-II's per-atom flag
        # string plus holds for the unrefined site-symmetry DOF groups.
        # xyz/SGData let the plan recompute a stale/blank site symmetry the
        # same way GSAS-II itself does (GetPhaseData's KeyError patch).
        atom_plan = atom_refinement_plan(
            atom_params,
            atom_record[7],
            phase_idx,
            atom_index,
            xyz=atom_record[3:6],
            SGData=SGData,
        )
        atom_record[2] = atom_plan.refine_flags
        holds.extend(atom_plan.holds)

        # Verbose logging
        if print_info and atom_plan.refine_flags:
            adp_display = adp_type if adp_type else "inherited"
            print(f"  Set refine flags for atom '{atom_label}' ({adp_display}): '{atom_plan.refine_flags}'")
            if atom_plan.holds:
                print(f"  Holding fixed DOFs for atom '{atom_label}': {atom_plan.holds}")

    return holds


# Main function to set phase parameterization from phases dictionary

@require_phase("Cannot set preferred orientation.")
def set_phase_preferred_orientation(proj: Any, hist: Any, phase_name: str, po_dict: dict, print_info: bool = False) -> None:
    """R36 (re/29, P-48): write the recipe's March-Dollase block into the HAP ``'Pref.Ori.'`` entry.

    The entry GSAS-II created for the phase (``GSASIImath.SetDefaultDData``: ``['MD', 1.0, False, [0, 0, 1], 0,
    {}, [], 0.1]``) is kept and three slots are overwritten: ``[0]`` the type ``'MD'``, ``[1]`` the coefficient,
    ``[2]`` its refine flag, ``[3]`` the axis. Nothing else in the HAP dict changes.
    """
    value, refine_flag, min_val, max_val = unpack_refinement_parameter(po_dict.get('ratio'), "ratio")
    entry = proj.data['Phases'][phase_name]['Histograms'][hist.name]['Pref.Ori.']
    entry[0] = 'MD'
    if value is not None:
        entry[1] = float(value)
    if refine_flag is not None:
        entry[2] = bool(refine_flag)
    hkl = po_dict.get('hkl')
    if hkl is not None:
        entry[3] = [int(h) for h in hkl]
    if print_info:
        print(f"Set March-Dollase preferred orientation for phase '{phase_name}': r={value} refine={refine_flag} axis={entry[3]}")


def set_phase_parameterization(proj: Any, hist: Any, phases_dict: dict, print_info: bool = False) -> list[str]:
    """
    Set phase parameterization in the GSAS-II project from a phases dictionary.

    Parameters:
    proj : GSAS-II project object
        The GSAS-II project containing the phases.
    hist : GSAS-II histogram object
        The histogram associated with the phases.
    phases_dict : dict
        Dictionary containing phase parameterization information. E.g., payload['phases']
    print_info : bool, optional
        If True, print information about the parameterization being set. Default is False.

    Returns:
    list[str]
        Accumulated GSAS-II "Hold" variable names from the unit-cell and atom
        setters (per-parameter refine flags). The caller applies
        them once via proj.add_HoldConstr.
    """
    holds: list[str] = []

    for phase_name, phase_info in phases_dict.items():

        # In schema 0.21, phase_name is the dict key itself
        # (structure.phase_name should match, but we use the key for consistency)

        # Check that phase exists in project - this would indicate an error in phase addition earlier
        if phase_name not in [p.name for p in proj.phases()]:
            print(f"Phase '{phase_name}' not found in project. Skipping parameterization.")
            continue

        # Now that we have the phase name, we can add phase-specific parameterization here
        # This will call on a few helper functions to set scale, unit cell, peak broadening, atom parameters, etc.
        # Each of these helper functions will take the proj, phase name (rather than phase object), and relevant parameterization dict

        # The phase block itself holds values and refine flags (gsasii 0.1.0, A93)
        param_dict = phase_info

        # Keys in param dict are 'scale', 'unit_cell', 'peak_broadening', and 'atoms' for now
        # It is not as simple as looping over keys since some have nested dicts and others hold values or lists

        # Set scale factor if provided
        scale_param = param_dict.get('scale', None)
        if scale_param is not None:
            if any(value is not None for value in scale_param):
                set_phase_scale(proj, hist, phase_name, scale_param, print_info=False)

        # Set unit cell parameters if provided. The key values can be None,
        # so here we cannot just check for unit_cell_dict not being None.
        # We need to check if any of hte keys in unit_cell_dict are not None.
        unit_cell_dict = param_dict.get('unit_cell', None)

        if unit_cell_dict is not None:
            if any(value is not None for value in unit_cell_dict.values()):
                holds.extend(set_phase_unit_cell(proj, phase_name, unit_cell_dict, print_info=False))

        # Set peak broadening if provided. Keys are "size_broadening" and "strain_broadening"
        # and each holds a dict with relevant parameters (size or strain) and the LG_eta
        # ("or {}" because model_dump emits an explicit None when the section is absent)
        peak_broadening_dict = param_dict.get('peak_broadening') or {}
        size_broadening_dict = peak_broadening_dict.get('size_broadening', None)
        strain_broadening_dict = peak_broadening_dict.get('strain_broadening', None)

        if size_broadening_dict is not None:
            if any(value is not None for value in size_broadening_dict.values()):
                set_phase_size_broadening(proj, hist, phase_name, size_broadening_dict, print_info=False)

        if strain_broadening_dict is not None:
            if any(value is not None for value in strain_broadening_dict.values()):
                set_phase_strain_broadening(proj, hist, phase_name, strain_broadening_dict, print_info=False)

        # R37 (re/29, P-48): March-Dollase preferred orientation, when the phase block states it
        po_dict = param_dict.get('preferred_orientation')
        if po_dict:
            set_phase_preferred_orientation(proj, hist, phase_name, po_dict, print_info=False)

        atoms_parameters_dict = param_dict.get('atoms', {})
        if atoms_parameters_dict and any(has_active_refinement_parameter(ap) for ap in atoms_parameters_dict.values()):
            holds.extend(set_phase_atom_parameters(proj, phase_name, atoms_parameters_dict, print_info=False))

        if print_info:
            print(f"Completed parameterization for phase '{phase_name}'.")

    if print_info:
        print("All phase parameterization complete. Phases in proj: ", *[p.name for p in proj.phases()], sep='\n\t')
        if holds:
            print("Hold constraints to apply (per-parameter refine flags): ", *holds, sep='\n\t')

    return holds

# Function for setting instrument parameterization
def set_instrument_parameterization(proj: Any, hist: Any, instrument_param_dict: dict, print_info: bool = False) -> None:
    """
    Set instrument parameterization in the GSAS-II project from an instrument parameterization dictionary.

    Parameters:
    proj : GSAS-II project object
        The GSAS-II project containing the histogram.
    hist : GSAS-II histogram object
        The histogram associated with the instrument.
    instrument_param_dict : dict
        Dictionary containing instrument parameterization information. E.g., payload['instrument']
    print_info : bool, optional
        If True, print information about the parameterization being set. Default is False.

    Returns:
    None
    """

    # Note: GSAS-II's instrument parameters hold values in a list.
    # The indices for each parameter (e.g., 'Lam' for wavelength) are as follows:
    # [0] default/starting value from iprms, [1] = value, [2] = refinement flag

    # Wavelength
    wavelength_param = instrument_param_dict.get('radiation', {}).get('wavelength', None)
    if wavelength_param is not None:
        value, refine_flag, min_val, max_val = unpack_refinement_parameter(wavelength_param, "wavelength")
        wavelength_changed = False # track if wavelength value changed

        # Set wavelength value
        curr_wavelength = proj.data[hist.name]['Instrument Parameters'][0]['Lam'][1]

        if value is not None and value != curr_wavelength:
            proj.data[hist.name]['Instrument Parameters'][0]['Lam'][1] = value
            wavelength_changed = True

        # Set refinement flag
        if refine_flag is not None:
            proj.data[hist.name]['Instrument Parameters'][0]['Lam'][2] = refine_flag

        if print_info:
            if wavelength_changed:
                print(f"Set instrument wavelength to {value} with refine_flag={refine_flag}")
            else:
                print(f"No change to instrument wavelength. Refine_flag={refine_flag}")

    # Additional instrument parameters (polarization, broadening, corrections) would be set similarly
    # Implementing those follows the same pattern as above

    # Polarization
    polarization_param = instrument_param_dict.get('corrections', {}).get('polarization', None)
    if polarization_param is not None:
        value, refine_flag, min_val, max_val = unpack_refinement_parameter(polarization_param, "polarization")
        polarization_changed = False # track if polarization value changed

        curr_polarization = proj.data[hist.name]['Instrument Parameters'][0]['Polariz.'][1]

        # Set polarization value
        if value is not None and value != curr_polarization:
            proj.data[hist.name]['Instrument Parameters'][0]['Polariz.'][1] = value
            polarization_changed = True

        # Set refinement flag
        if refine_flag is not None:
            proj.data[hist.name]['Instrument Parameters'][0]['Polariz.'][2] = refine_flag

        if print_info:
            if polarization_changed:
                print(f"Set instrument polarization to {value} with refine_flag={refine_flag}")
            else:
                print(f"No change to instrument polarization. Refine_flag={refine_flag}")

    # Broadening parameters (U, V, W, X, Y, Z)
    broadening_dict = instrument_param_dict.get('broadening', {})
    for param_key in broadening_dict.keys():
        broadening_param = broadening_dict.get(param_key, None)
        if broadening_param is not None:
            value, refine_flag, min_val, max_val = unpack_refinement_parameter(broadening_param, f"broadening.{param_key}")

            broadening_changed = False

            # Set broadening parameter value
            if value is not None:
                proj.data[hist.name]['Instrument Parameters'][0][param_key][1] = value
                broadening_changed = True

            # Set refinement flag
            if refine_flag is not None:
                proj.data[hist.name]['Instrument Parameters'][0][param_key][2] = refine_flag

            if print_info:
                if broadening_changed:
                    # Print changed parameter
                    print(f"Set instrument broadening parameter '{param_key}' to {value} with refine_flag={refine_flag}")

                # Always print refinement flag even if value not changed
                else:
                    print(f"No change to instrument broadening parameter '{param_key}'. Refine_flag={refine_flag}")


    # Corrections parameters (zero_shift, axial_divergence, sample_height_displacement)
    corrections_dict = instrument_param_dict.get('corrections', {})
    for param_key in corrections_dict.keys():
        correction_param = corrections_dict.get(param_key, None)
        if correction_param is not None: # only loop over provided params

            if param_key == 'zero_shift':
                gsas_key = 'Zero'
            elif param_key == 'axial_divergence':
                gsas_key = 'SH/L'
            elif param_key == 'polarization':
                continue  # set above ('Polariz.'); it sits in corrections (A103)
            #elif param_key == 'sample_height_displacement': # irrelevant to area detector data, future work for Bragg-Brentano geometry
            #    gsas_key = 'SampHt'
            else:
                raise ValueError(f"Unknown instrument correction parameter key '{param_key}'.")

            value, refine_flag, min_val, max_val = unpack_refinement_parameter(correction_param, param_key)
            correction_changed = False

            # Set correction parameter value
            if value is not None:
                proj.data[hist.name]['Instrument Parameters'][0][gsas_key][1] = value
                correction_changed = True

            # Set refinement flag
            if refine_flag is not None:
                proj.data[hist.name]['Instrument Parameters'][0][gsas_key][2] = refine_flag

            if print_info:
                if correction_changed:
                    # Print changed parameter
                    print(f"Set instrument correction parameter '{param_key}' to {value} with refine_flag={refine_flag}")

                # Always print refinement flag even if value not changed
                else:
                    print(f"No change to instrument correction parameter '{param_key}'. Refine_flag={refine_flag}")

    # Print instrument parameters set and flags if requested
    if print_info:
        # Check if 1st and 2nd indices are different for any instrument parameteters
        # If they are all the same, then no parameters were changed
        params_changed = False
        for param in proj.data[hist.name]['Instrument Parameters'][0].values():
            if param[0] != param[1]:
                params_changed = True
                break
        if not params_changed:
            print("No instrument parameters were changed from their default values.")

        # print refine flags for all instrument parameters
        print("Instrument parameter refinement flags:")
        for param_key, param in proj.data[hist.name]['Instrument Parameters'][0].items():
            print(f"  {param_key}: refine_flag={param[2]}")


def set_refinement_cycles(proj: Any, num_cycles: int, print_info: bool = False) -> None:
    """
    Set the number of refinement cycles in the GSAS-II project.

    Parameters:
    proj : GSAS-II project object
        The GSAS-II project to set the refinement cycles for.
    num_cycles : int
        The number of refinement cycles to set.
    print_info : bool, optional
        If True, print information about the refinement cycles being set. Default is False.

    Returns:
    None
    """

    proj.set_Controls('cycles', num_cycles)
    if print_info:
        print(f"Set number of refinement cycles to {num_cycles}")
