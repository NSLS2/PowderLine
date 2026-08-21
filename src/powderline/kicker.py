"""PowderLine: Automated powder X-ray diffraction Rietveld refinements using GSAS-II.

File-less architecture (since schema 0.25):
- All data (XRD patterns, structures, instrument parameters) embedded in JSON
- No external file dependencies (CIF, CHI, INSTPRM)
- File handling occurs upstream of PowderLine

This module orchestrates the complete refinement workflow: JSON parsing, GSAS-II
project initialization, parameter setting, refinement execution, and output generation.
"""
from __future__ import annotations
import sys
import uuid
import yaml
import json
import argparse
import random as ran
import numpy as np
import pandas as pd
from typing import Any, Dict, List, Literal, Optional, Sequence, Union
from pathlib import Path
from pydantic import ValidationError
from GSASII import GSASIIscriptable as G2  # type: ignore
from GSASII import GSASIIlattice as G2lat
from GSASII import GSASIImapvars as G2mv
from GSASII import GSASIIobj as G2obj
from GSASII import GSASIIspc as G2spc
from GSASII import GSASIIElem as G2elem
from GSASII import GSASIIpwd as G2pwd
from powderline.schema import RecipeModel, RefinementControls
from powderline.constraints import atom_refinement_plan, cell_refinement_plan
from powderline._status import CHECK, CROSS, INFO, WARN, emoji
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
    Unpack refinement parameter from [value, refine_flag, min, max] format.

    This utility reduces boilerplate for the common pattern of unpacking refinement
    parameters throughout the codebase. Use only in straightforward cases - complex
    conditional logic should inline the unpacking for clarity.

    Args:
        param: RefinementParameter list [value, refine_flag, min, max] or None
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
        if len(param) != 4:
            raise ValueError(
                f"{param_name} must be a list of exactly 4 elements "
                f"[value, refine_flag, min, max], got {len(param)} elements"
            )
        return tuple(param)
    else:
        raise ValueError(
            f"{param_name} must be a list [value, refine_flag, min, max] or None, "
            f"got {type(param).__name__}"
        )


def load_recipe_asset(recipe_path: Path) -> dict:
    """Load a recipe asset from .json, .yaml/.yml, or .txt (YAML)."""
    ext = recipe_path.suffix.lower()
    text = recipe_path.read_text()
    if ext == ".json":
        return json.loads(text)
    if ext in {".yaml", ".yml", ".txt"}:
        return yaml.safe_load(text) or {}
    raise ValueError(f"Unsupported recipe format: {recipe_path}")


def is_template_file(recipe_dict: dict, input_path: Path) -> tuple[bool, str | None]:
    """
    Detect if the recipe file is a template that shouldn't be run directly.

    Uses two-level detection strategy:
    1. Path contains "template" (case-insensitive)
    2. Missing required fields based on schema_name (for GSASII_Rietveld or GSASII_SPF)

    Args:
        recipe_dict: Recipe dictionary loaded from JSON
        input_path: Path to the JSON file

    Returns:
        (is_template, reason): is_template is True if this appears to be a template,
                              reason explains why it was detected as a template.
                              If not a template, returns (False, None).

    Examples:
        >>> is_template_file({}, Path("example_template/input.json"))
        (True, "filename or path contains 'template'")

        >>> is_template_file({"schema_name": "GSASII_Rietveld", "payload": {"xrd_data": {...}}}, Path("example_LaB6/input.json"))
        (False, None)
    """
    # Check 1: Path contains "template"
    if "template" in str(input_path).lower():
        return True, "filename or path contains 'template'"

    # Check 2: Missing payload or schema-specific required fields
    payload = recipe_dict.get('payload', {})
    if not payload:
        return True, "missing payload"

    # Check for schema-specific required fields
    schema_name = recipe_dict.get('schema_name')
    if schema_name == 'GSASII_Rietveld':
        required_fields = ['xrd_data', 'instrument', 'phases', 'refinement_controls']
        missing = [field for field in required_fields if field not in payload or payload[field] is None]
        if missing:
            return True, f"GSASII_Rietveld schema missing required fields: {missing}"
    elif schema_name == 'GSASII_SPF':
        required_fields = ['xrd_data', 'instrument', 'single_peaks', 'refinement_controls']
        missing = [field for field in required_fields if field not in payload or payload[field] is None]
        if missing:
            return True, f"GSASII_SPF schema missing required fields: {missing}"
    else:
        # Fallback: check for common core fields if schema unknown
        core_fields = ['xrd_data', 'instrument', 'refinement_controls']
        missing_core = [field for field in core_fields if field not in payload]
        if len(missing_core) == len(core_fields):
            return True, "missing all required fields in payload (xrd_data, instrument, refinement_controls)"

    return False, None


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


def validate_simulation_mode_parameters(recipe: RecipeModel, verbose: bool = False) -> tuple[bool, List[str]]:
    """
    Validate that simulation mode examples have all refinement parameters locked.

    Simulation mode (refinement_cycles=1 with all parameters fixed) must have deterministic
    output. This function checks for any `refine_flag: true` in structural or background
    parameters that would violate determinism.

    Args:
        recipe: Validated RecipeModel instance (uses payload structure)
        verbose: If True, print detailed parameter checks

    Returns:
        (is_valid, warnings): is_valid is True if all parameters are properly locked,
                             warnings is a list of issues found (empty if valid).

    Examples:
        >>> is_valid, warnings = validate_simulation_mode_parameters(recipe)
        >>> if not is_valid:
        ...     for warning in warnings:
        ...         print(f"WARNING: {warning}")
    """
    is_valid = True
    warnings: List[str] = []

    # Get refinement controls (in payload)
    controls = recipe.payload.refinement_controls

    # Only check simulation mode (refinement_cycles == 1)
    if controls.refinement_cycles != 1:
        return True, []  # Not simulation mode, skip validation

    if verbose:
        print("Validating simulation mode constraints...")

    # Check background parameters
    if recipe.payload.background is not None:
        if recipe.payload.background.chebyshev is not None:
            if recipe.payload.background.chebyshev.refine_flag:
                msg = "CRITICAL: Chebyshev background has refine_flag=true in simulation mode (refinement_cycles=1). " \
                      "This violates determinism - all parameters must be locked. Set refine_flag=false."
                warnings.append(msg)
                is_valid = False
                if verbose:
                    print(f"  {CROSS} {msg}")

        if recipe.payload.background.single_peaks is not None:
            # Check single peak parameters
            param_lists = [
                (recipe.payload.background.single_peaks.positions, "single_peaks.positions"),
                (recipe.payload.background.single_peaks.intensities, "single_peaks.intensities"),
                (recipe.payload.background.single_peaks.pv_gaussian_sigma, "single_peaks.pv_gaussian_sigma"),
                (recipe.payload.background.single_peaks.pv_lorentzian_gamma, "single_peaks.pv_lorentzian_gamma"),
            ]
            for param_list, param_name in param_lists:
                if param_list is not None:
                    for i, param in enumerate(param_list):
                        if param[1]:  # refine_flag is second element
                            msg = f"WARNING: {param_name}[{i}] has refine_flag=true in simulation mode. " \
                                  "Set refine_flag=false for deterministic output."
                            warnings.append(msg)
                            is_valid = False
                            if verbose:
                                print(f"  {WARN}  {msg}")

    # Check instrument parameterization
    if recipe.payload.instrument.parameterization is not None:
        param_dict = recipe.payload.instrument.parameterization.model_dump(mode='json')

        # Check wavelength
        if param_dict.get('wavelength') and param_dict['wavelength'][1]:
            msg = "WARNING: instrument.parameterization.wavelength has refine_flag=true in simulation mode"
            warnings.append(msg)
            is_valid = False
            if verbose:
                print(f"  {WARN}  {msg}")

        # Check broadening parameters
        if param_dict.get('broadening'):
            for param_key, param_value in param_dict['broadening'].items():
                if param_value and param_value[1]:  # refine_flag
                    msg = f"WARNING: instrument.parameterization.broadening.{param_key} has refine_flag=true in simulation mode"
                    warnings.append(msg)
                    is_valid = False
                    if verbose:
                        print(f"  {WARN}  {msg}")

        # Check corrections
        if param_dict.get('corrections'):
            for param_key, param_value in param_dict['corrections'].items():
                if param_value and param_value[1]:  # refine_flag
                    msg = f"WARNING: instrument.parameterization.corrections.{param_key} has refine_flag=true in simulation mode"
                    warnings.append(msg)
                    is_valid = False
                    if verbose:
                        print(f"  {WARN}  {msg}")

    # Check phase-level parameters (only if phases exist)
    if recipe.payload.phases is not None:
        phases_dict = recipe.payload.model_dump(mode='json')['phases']
        for phase_name, phase_info in phases_dict.items():
            param_dict = phase_info.get('parameterization', {})

            # Check scale
            if param_dict.get('scale') and param_dict['scale'][1]:
                msg = f"WARNING: phases.{phase_name}.parameterization.scale has refine_flag=true in simulation mode"
                warnings.append(msg)
                is_valid = False
                if verbose:
                    print(f"  {WARN}  {msg}")

            # Check unit cell
            unit_cell = param_dict.get('unit_cell', {})
            if unit_cell:
                for cell_param, param_value in unit_cell.items():
                    if param_value and param_value[1]:  # refine_flag
                        msg = f"WARNING: phases.{phase_name}.parameterization.unit_cell.{cell_param} has refine_flag=true in simulation mode"
                        warnings.append(msg)
                        is_valid = False
                        if verbose:
                            print(f"  {WARN}  {msg}")

            # Check peak broadening
            peak_broadening = param_dict.get('peak_broadening', {})
            if peak_broadening:
                # Check size broadening
                if peak_broadening.get('size_broadening'):
                    for param_key, param_value in peak_broadening['size_broadening'].items():
                        if param_key == 'model':  # Skip model field (string literal, not [value, refine_flag])
                            continue
                        if param_value and param_value[1]:  # refine_flag
                            msg = f"WARNING: phases.{phase_name}.parameterization.peak_broadening.size_broadening.{param_key} has refine_flag=true"
                            warnings.append(msg)
                            is_valid = False
                            if verbose:
                                print(f"  {WARN}  {msg}")

                # Check strain broadening
                if peak_broadening.get('strain_broadening'):
                    for param_key, param_value in peak_broadening['strain_broadening'].items():
                        if param_key == 'model':  # Skip model field (string literal, not [value, refine_flag])
                            continue
                        if param_value and param_value[1]:  # refine_flag
                            msg = f"WARNING: phases.{phase_name}.parameterization.peak_broadening.strain_broadening.{param_key} has refine_flag=true"
                            warnings.append(msg)
                            is_valid = False
                            if verbose:
                                print(f"  {WARN}  {msg}")

            # Check atom parameters (using same logic as has_active_refinement_parameter for consistency)
            atoms = param_dict.get('atoms', {})
            if atoms:
                for atom_label, atom_params in atoms.items():
                    for param_key, param_value in atom_params.items():
                        # Skip ADP field (it's a string, not a RefinementParameter)
                        if param_key == 'ADP':
                            continue

                        # Handle Uaniso nested dict
                        if param_key == 'Uaniso' and isinstance(param_value, dict):
                            for uaniso_key, uaniso_value in param_value.items():
                                if isinstance(uaniso_value, list) and len(uaniso_value) >= 2 and uaniso_value[1]:
                                    msg = f"WARNING: phases.{phase_name}.parameterization.atoms.{atom_label}.Uaniso.{uaniso_key} has refine_flag=true in simulation mode"
                                    warnings.append(msg)
                                    is_valid = False
                                    if verbose:
                                        print(f"  {WARN}  {msg}")

                        # Check regular RefinementParameter lists (use elif to avoid checking lists after Uaniso)
                        elif isinstance(param_value, list) and len(param_value) >= 2 and param_value[1]:
                            msg = f"WARNING: phases.{phase_name}.parameterization.atoms.{atom_label}.{param_key} has refine_flag=true in simulation mode"
                            warnings.append(msg)
                            is_valid = False
                            if verbose:
                                print(f"  {WARN}  {msg}")

    if verbose:
        if is_valid:
            print(f"{CHECK} All parameters properly locked for simulation mode determinism")

    return is_valid, warnings

# Functions to add histogram with instrument parameters from recipe.xrd_data (dict with arrays) and recipe.instrument.initialization (list of dicts)

InstParmValue = Union[float, int, str, Sequence[Any]]
InstParmDict = Dict[str, InstParmValue]
G2InstParmDict = Dict[str, List[Any]]  # values like [val, val, 0]

def _to_gsasii_instparm_dict(flat: InstParmDict) -> G2InstParmDict:
    """
    Convert a "flat" instrument parameter dictionary (values as scalars/strings)
    into the GSAS-II scripting format where each value is a 3-item list:

        key: [value, value, refinement_flag]

    Examples (GSAS-II format):
        "Type": ["PXC", "PXC", False]
        "U": [2.0, 2.0, False]

    If the value already looks like a GSAS-II 3-item list/tuple, it is passed through.

    Notes
    -----
    GSAS-II's scriptable examples show this 3-item-list structure for direct
    instrument parameter specification.
    """
    out: G2InstParmDict = {}

    for k, v in flat.items():
        # Already in GSAS-II form?
        if isinstance(v, (list, tuple)) and len(v) == 3:
            out[k] = list(v)
            continue

        # Otherwise convert scalar/string -> [v, v, False]
        out[k] = [v, v, False]

    # Ensure a few expected keys exist where possible
    if "Bank" in out:
        # normalize Bank to int-ish in the first two slots when possible
        try:
            b = int(float(out["Bank"][0]))
            out["Bank"] = [b, b, out["Bank"][2]]
        except Exception:
            pass

    return out


def add_powder_histogram_from_arrays(
    proj,
    tth_array: Union[np.ndarray, Sequence[float]],
    intensity_array: Union[np.ndarray, Sequence[float]],
    intensity_weights_array: Union[np.ndarray, Sequence[float]],
    histogram_name: str,
    instrument_prm_dict: Dict[str, Any],
    *,
    comments: Optional[List[str]] = None,
    phases: Union[None, str, Sequence[Any]] = None,
):
    """
    Create a GSAS-II powder histogram inside an in-memory GSASIIscriptable project,
    using arrays rather than reading a powder data file from disk.

    Parameters
    ----------
    proj
        A `GSASIIscriptable.G2Project` instance (e.g. created with `G2Project(newgpx='dummy')`).

    tth_array, intensity_array, intensity_weights_array
        1D arrays (same length) for 2θ (degrees), Iobs, and weights.
        Weights are used directly in the histogram.
        Default weighting (set in phase 2, the recipe creator) is 1 / sigma**2 where sigma is the uncertainty in the intensity (default is SQRT(Iobs)).

    histogram_name
        Name to use for the histogram. If it does not start with "PWDR ",
        the prefix is added. If the name collides with an existing histogram,
        it is made unique using `G2obj.MakeUniqueLabel`.
        TODO: catch non-unique names in phase2 (recipe creator)

    instrument_prm_dict
        Instrument parameters. This can be either:
          * a "flat" dict with scalars/strings (your current format), or
          * a GSAS-II scripting-format dict where each value is a 3-item list
            like `[val, val, False]`.

        This function will convert flat dicts into the GSAS-II scripting format.

        The histogram will store instrument parameters as `[Iparm1, Iparm2]`,
        where Iparm2 is an empty dict (typical for CW lab/synchrotron usage).

    comments
        Optional list of strings for the histogram "Comments" entry. Default is [].

    phases
        Optional linking behavior, mirroring `add_powder_histogram`:
          * None: do not link phases
          * 'all': link all phases in the project
          * sequence: link the listed phases (objects/names/rIds/etc)

        (Linking is not needed for your current test requirement, but it’s here
        so the histogram is inserted in the same place in the project tree and
        can be linked the same way.)

    Returns
    -------
    hist
        A `G2PwdrData` histogram wrapper object from `proj.histogram(histname)`.

    Implementation notes
    --------------------
    This function intentionally mirrors the internal GSAS-II construction performed
    in `GSASIIscriptable.load_pwd_from_reader` for the output histogram dictionary:
    keys, `data` packing, defaults for background and peaks, and ID handling.

    Because this builds the same dict structure GSAS-II uses, the project is GUI-compatible
    if later saved, and downstream GSAS-II operations (background fitting/refinement/etc.)
    see the histogram in the expected format.
    """
    # ---- Validate/normalize arrays
    x = np.asarray(tth_array, dtype=float).ravel()
    y = np.asarray(intensity_array, dtype=float).ravel()
    w = np.asarray(intensity_weights_array, dtype=float).ravel()

    # GSAS-II powderdata commonly holds 6 arrays (obs, weights, calc, bkg, diff)
    ycalc = np.zeros_like(y)
    ybkg = np.zeros_like(y)
    ydiff = np.zeros_like(y)

    powderdata = [x, y, w, ycalc, ybkg, ydiff]

    # ---- Instrument parameters: convert flat dict -> GSAS-II list-of-3 form if needed
    Iparm1 = _to_gsasii_instparm_dict(instrument_prm_dict)
    Iparm2: Dict[str, Any] = {}

    # Sanity: Type must be present and be list-like for GSAS-II-style indexing
    if "Type" not in Iparm1 or not isinstance(Iparm1["Type"], list) or len(Iparm1["Type"]) < 1:
        raise ValueError(
            "instrument_prm_dict must define 'Type' (e.g. 'PXC'), "
            "and after conversion it must be list-like (e.g. ['PXC','PXC', False])."
        )

    # TODO: in phase 2 (recipe creator), the full histname including 'PWDR' will be validated upstream.
    # ---- Histogram naming: match GSAS-II convention
    HistName = histogram_name.strip()
    if not HistName.startswith("PWDR "):
        HistName = "PWDR " + HistName

    # TODO: in phase 2 (recipe creator), a check for existing histogram names will be done.
    # Make unique vs existing histogram names
    existing = [h.name for h in proj.histograms()]  # GSASIIscriptable method
    HistName = G2obj.MakeUniqueLabel(HistName, existing)

    # ---- Mirror load_pwd_from_reader value packing and defaults
    Ymin = float(np.min(y))
    Ymax = float(np.max(y))

    # TODO: in phase 2 (recipe creator), the random ID generation will be done upstream using a schema check.

    valuesdict = {
        "wtFactor": 1.0,
        "Dummy": False,
        "ranId": ran.randint(0, sys.maxsize),
        "Offset": [0.0, 0.0],
        "delOffset": 0.02 * Ymax,
        "refOffset": -0.1 * Ymax,
        "refDelt": 0.1 * Ymax,
        "Yminmax": [Ymin, Ymax],
    }

    Tmin = float(np.min(x))
    Tmax = float(np.max(x))
    Tmin1 = Tmin

    # Keep the small special-case from load_pwd_from_reader for NT data
    try:
        if "NT" in Iparm1["Type"][0] and G2lat.Pos2dsp(Iparm1, Tmin) < 0.4:
            Tmin1 = float(G2lat.Dsp2pos(Iparm1, 0.4))
    except Exception:
        # If Pos2dsp fails (unlikely for PXC), ignore
        pass

    # TODO: in phase 2 (recipe creator), the default background will be set upstream using a schema check.
    default_background = [
        ["chebyschev-1", False, 3, 1.0, 0.0, 0.0],
        {"nDebye": 0, "debyeTerms": [], "nPeaks": 0, "peaksList": [], "background PWDR": ["", 1.0, False]},
    ]

    sample = G2obj.SetDefaultSample()
    sample["ranId"] = valuesdict["ranId"]  # matches load_pwd_from_reader behavior
    # If Azimuth supplied in inst parms, copy into sample (nice-to-have consistency)
    try:
        if "Azimuth" in Iparm1 and isinstance(Iparm1["Azimuth"], list):
            sample["Azimuth"] = float(Iparm1["Azimuth"][0])
    except Exception:
        pass

    output_dict = {
        "Reflection Lists": {},
        "Limits": [(Tmin, Tmax), [Tmin1, Tmax]],
        "data": [valuesdict, powderdata, HistName],
        "Index Peak List": [[], []],
        "Comments": comments if comments is not None else [],
        "Unit Cells List": [],
        "Sample Parameters": sample,
        "Peak List": {"peaks": [], "sigDict": {}},
        "Background": default_background,
        "Instrument Parameters": [Iparm1, Iparm2],
    }

    # Tree ordering list matches load_pwd_from_reader
    section_names = [
        "Comments",
        "Limits",
        "Background",
        "Instrument Parameters",
        "Sample Parameters",
        "Peak List",
        "Index Peak List",
        "Unit Cells List",
        "Reflection Lists",
    ]
    new_names = [HistName] + section_names

    # ---- Insert into project in the same way add_powder_histogram does
    if HistName in proj.data:
        # keep behavior: redefine with a warning-like action
        try:
            import GSASIIfiles as G2fil
            G2fil.G2Print("Warning - redefining histogram", HistName)
        except Exception:
            pass

    # proj.names is a list of "tree entries"; match add_powder_histogram insertion point
    if proj.names and proj.names[-1][0] == "Phases":
        proj.names.insert(-1, new_names)
    else:
        proj.names.append(new_names)

    proj.data[HistName] = output_dict
    proj.update_ids()

    # Optional phase linking (mirrors add_powder_histogram flow)
    if phases == "all":
        phases = proj.phases()
    if phases:
        for ph in phases:
            ph_obj = proj.phase(ph)
            proj.link_histogram_phase(HistName, ph_obj)

    return proj.histogram(HistName)


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
            - positions: List of [[2θ, refine, min, max], ...] for peak positions
            - intensities: List of [[I, refine, min, max], ...] for peak heights
            - pv_gaussian_sigma: List of [[σ, refine, min, max], ...] for Gaussian widths
            - pv_lorentzian_gamma: List of [[γ, refine, min, max], ...] for Lorentzian widths
            All lists must have same length (number of peaks)
        print_info: If True, print peak configuration to stdout

    Returns:
        None

    Raises:
        ValueError: If parameter lists have inconsistent lengths

    Examples:
        >>> # Two single peaks at 2θ=35.5° and 42.0°
        >>> single_peaks = {
        ...     'positions': [[35.5, False, None, None], [42.0, False, None, None]],
        ...     'intensities': [[50.0, True, None, None], [30.0, True, None, None]],
        ...     'pv_gaussian_sigma': [[0.1, False, None, None], [0.1, False, None, None]],
        ...     'pv_lorentzian_gamma': [[0.05, False, None, None], [0.05, False, None, None]]
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
        - positions : list of [float, bool, float, float]. Indices 2 and 3 can be None.
            List of [position value, refine flag, min, max] for each peak.
            These are two-theta values. Q / d can be passed upstream and converted in validation.
        - intensities: list of [float, bool, float, float]. Indices 2 and 3 can be None.
            List of [intensity value, refine flag, min, max] for each peak.
        - pv_gaussian_sigma: list of [float, bool, float, float]. Indices 2 and 3 can be None.
            List of [gaussian sigma value, refine flag, min, max] for each peak.
        - pv_lorentzian_gamma: list of [float, bool, float, float]. Indices 2 and 3 can be None.
            List of [lorentzian gamma value, refine flag, min, max] for each peak.
    print_info : bool
        Whether to print information about the set background.
    Returns:
    None
    """
    # Parse the bkg_single_peaks_dict
    positions = bkg_single_peaks_dict.get('positions', [])
    intensities = bkg_single_peaks_dict.get('intensities', [])
    gaussian_sigmas = bkg_single_peaks_dict.get('pv_gaussian_sigma', [])
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
        pos, pos_refine, pos_min, pos_max = positions[i]
        inten, inten_refine, inten_min, inten_max = intensities[i]
        g_sigma, g_refine, g_sigma_min, g_sigma_max = gaussian_sigmas[i]
        l_gamma, l_refine, l_gamma_min, l_gamma_max = lorentzian_gammas[i]

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

def add_phase_from_cif_dict(proj: Any, cif_data: Dict[str, Any], phase_name: str, histograms: Union[Sequence, str] = 'all') -> Any:
    """
    Add a phase to a GSAS-II project from an embedded structure dictionary.

    This function creates a phase from an in-memory structure data dictionary
    (file-less payload format) without reading from files. It creates a new phase entry
    in the project, sets up the phase's general data (space group, unit_cell) and
    atoms, and links the phase to specified histograms.

    Parameters
    ----------
    proj : GSASIIscriptable.G2Project
        The GSAS-II project object to which the phase will be added.
    cif_data : dict
        The structure dictionary containing phase structural information.
        From the payload this dict is stowed in payload['phases'][phase]['structure']
        (e.g., payload['phases']['LaB6']['structure']).
    phase_name : str
        Name for the new phase. Top level key for a phase in payload['phases'],
        or within payload['phases'][phase]['structure']['phase_name'] from payload.
    histograms : list or 'all', optional
        Which histograms to associate with this phase. Can be:
         - 'all' (default): link to all powder histograms in the project.
         - a list of histogram identifiers (names, objects, or indices).
         - None or empty list for no links.

    Returns
    -------
    phase_obj : GSASIIscriptable.G2Phase
        The newly created phase object (GSAS-II scriptable phase wrapper).

    Raises
    ------
    ValueError
        If the space group in cif_data is invalid or cannot be interpreted.

    Notes
    -----
    The function generates a new phase dictionary using GSASIIobj.SetNewPhase with
    the provided space group and unit_cell parameters. Atomic coordinates and
    occupancies from cif_data are inserted into the phase's atom list. Anisotropic
    displacement parameters, if present, are fully supported.

    By default, the phase will be linked to all existing powder histograms in the
    project. You can specify a subset of histograms by name, index, or object, or
    pass an empty list/None to link none.
    """
    pname = phase_name if phase_name else cif_data.get("name", "New Phase")
    # Ensure phase name is unique in project
    # TODO: handle phase name collisions more gracefully upstream in validation
    existing_names = [p.name for p in proj.phases()]
    pname = G2obj.MakeUniqueLabel(pname, existing_names)

    # Interpret space group symbol into SGData
    sg = cif_data.get("space_group", "P 1")
    err, SGData = G2spc.SpcGroup(sg)

    # Attempt normalization if initial interpretation failed
    normalized_sg = sg
    if err and sg:
        normalized_sg = G2spc.StandardizeSpcName(sg)
        if normalized_sg and normalized_sg != sg:
            err, SGData = G2spc.SpcGroup(normalized_sg)

    # Handle space group interpretation errors
    if err:
        error_msg = G2spc.SGErrors(err)
        raise ValueError(
            f"Space group '{sg}' could not be interpreted.\n"
            f"Error: {error_msg}\n"
            f"Attempted normalization: '{normalized_sg}'\n"
            f"\nCommon issues:\n"
            f"  • Missing spaces in Hermann-Mauguin notation (e.g., use 'R 3 m' not 'R3m')\n"
            f"  • Ambiguous rhombohedral symbols (R-3m normalizes to R-3c rhombohedral)\n"
            f"  • Check structure dict space_group entry matches the crystal structure\n"
        )

    # Create a new phase data structure (similar to reading from file):
    phase_data = G2obj.SetNewPhase(Name=pname, SGData=SGData)
    phase_data['General']['Name'] = pname

    # Document any space group normalization that occurred (silently - verbose mode not available here)
    # if normalized_sg != sg:
    #     print(f"ℹ️  Space group normalization: '{sg}' → '{normalized_sg}'")

    # Set unit cell parameters if available
    unit_cell = cif_data.get("unit_cell", {})
    if unit_cell:
        unit_cell_constants = [unit_cell.get("a"), unit_cell.get("b"), unit_cell.get("c"), unit_cell.get("alpha"), unit_cell.get("beta"), unit_cell.get("gamma")]
        if len(unit_cell_constants) == 6 and None not in unit_cell_constants:
            phase_data['General']['Cell'][1:7] = unit_cell_constants  # insert a,b,c,alpha,beta,gamma
            try:
                # Recalculate volume for consistency
                phase_data['General']['Cell'][7] = G2lat.calc_V(G2lat.cell2A(tuple(unit_cell_constants)))
            except Exception as e:
                raise RuntimeError(
                    f"Unit cell volume calculation failed for phase '{pname}'. "
                    f"Cell parameters: {unit_cell_constants}. "
                    f"Original error: {e}"
                ) from e

    # Add atoms from cif_data into phase_data['Atoms']
    # TODO: review handling of site_sym, multiplicity, and ADPS.
    # The current approach expects minimal info in cif_data, but we are now populating this with the complete info needed.
    # For example, cif_data['atoms'] stows info as shown below, where label is the key for each atom entry.:
        # atoms[label] = {
        #     "element": element,
        #     "Multiplicity": mult,
        #     "x": x, "y": y, "z": z,
        #     "occupancy": occ,
        #     "ADP": ADP,
        #     "Uiso": Uiso_val
        # }
        # # Add Uij if anisotropic and data available
        # if ADP == "Uani" and label in aniso_data:
        #     atoms[label]["Uij"] = aniso_data[label]
    # TODO: in phase 2, assembly of atom_record using GSAS-II helpers will done upstream using "parse_cif_to_dict" function.
    # This code will need to be update accordingly and use "get" with defaults for missing values. E.g., don't interpret site sym or mult.

    for label, atom in cif_data.get("atoms", {}).items():
        x = float(atom.get("x", 0.0))
        y = float(atom.get("y", 0.0))
        z = float(atom.get("z", 0.0))
        occ = float(atom.get("occupancy", 1.0))

        # Get ADP type for this atom (required in schema 0.22)
        adp_type = atom.get("ADP", None)
        if adp_type is None:
            raise ValueError(
                f"Atom '{label}' in phase '{pname}' is missing required 'ADP' field. "
                f"Schema 0.22 requires explicit ADP specification ('Uiso' or 'Uaniso') for all atoms."
            )

        # Prepare atom record list (based on GSAS-II internal format):
        atom_record = ["", "", "", 0.0, 0.0, 0.0, 1.0, "", 0.0, "I", 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        atom_record[0] = label
        atom_record[1] = atom.get("element", label.rstrip('0123456789') or "X")
        atom_record[2] = ""  # refinement flags placeholder (left blank)
        atom_record[3] = x
        atom_record[4] = y
        atom_record[5] = z
        atom_record[6] = occ
        # Determine site symmetry and multiplicity for this atom in the given SG
        site_sym, mult = "", 1
        try:
            site_sym, mult = G2spc.SytSym([x, y, z], SGData)[0:2]
        except Exception:
            pass
        atom_record[7] = site_sym if site_sym is not None else ""
        atom_record[8] = mult if mult is not None else 1

        # Set displacement parameters (isotropic or anisotropic)
        if adp_type == "Uaniso":
            # Anisotropic displacement parameters
            atom_record[9] = "A"

            # Get Uaniso dict (supports both "Uij" old name and "Uaniso" new name)
            uaniso_dict = atom.get("Uaniso") or atom.get("Uij")

            if uaniso_dict:
                # Validate all 6 anisotropic values are present
                required_keys = ["U11", "U22", "U33", "U12", "U13", "U23"]
                missing_keys = [k for k in required_keys if k not in uaniso_dict or uaniso_dict[k] is None]
                if missing_keys:
                    raise ValueError(
                        f"Atom '{label}' marked as anisotropic (ADP='Uaniso') but missing required U values: {missing_keys}. "
                        f"All 6 anisotropic parameters (U11, U22, U33, U12, U13, U23) must be provided."
                    )

                # Populate U11, U22, U33, U12, U13, U23 (indices 11-16)
                atom_record[11] = float(uaniso_dict["U11"])
                atom_record[12] = float(uaniso_dict["U22"])
                atom_record[13] = float(uaniso_dict["U33"])
                atom_record[14] = float(uaniso_dict["U12"])
                atom_record[15] = float(uaniso_dict["U13"])
                atom_record[16] = float(uaniso_dict["U23"])

                # Set atom_record[10] to Uiso if provided, else calculate from diagonal elements
                if atom.get("Uiso") is not None:
                    atom_record[10] = float(atom["Uiso"])
                else:
                    # Calculate equivalent isotropic value from diagonal elements
                    atom_record[10] = (atom_record[11] + atom_record[12] + atom_record[13]) / 3.0
            else:
                raise ValueError(
                    f"Atom '{label}' marked as anisotropic (ADP='Uaniso') but no Uaniso dict found. "
                    f"Provide 'Uaniso' dict with U11, U22, U33, U12, U13, U23 values."
                )
        else:
            # Isotropic displacement parameters
            atom_record[9] = "I"
            uiso = atom.get("Uiso")
            if uiso is not None:
                atom_record[10] = float(uiso)
            else:
                atom_record[10] = 0.0
            atom_record[11:17] = [0.0]*6  # six anisotropic Uij (zeros since not used here)

        # Append a random unique ID for the atom
        atom_record.append(ran.randint(0, sys.maxsize))
        phase_data['Atoms'].append(atom_record)

    # Insert the new phase into project data structure
    if 'Phases' not in proj.data:
        proj.data['Phases'] = {'data': None}
    assert pname not in proj.data['Phases'], "Phase name collision despite uniqueness check"
    proj.data['Phases'][pname] = phase_data
    # Update the project tree name list for phases
    for entry in proj.names:
        if entry[0] == 'Phases':
            entry.append(pname); break
    else:
        proj.names.append(['Phases', pname])

    # Initialize phase general data (e.g. set default atom form factors):
    try:
        G2elem.SetupGeneral(phase_data, None)
    except ValueError as err:
        raise ValueError(f"Error in phase initialization: {err}")

    # Link phase to specified histograms
    hist_list = []
    if histograms == 'all':
        hist_list = [h.name for h in proj.histograms()]
    elif histograms:
        for h in histograms:
            if hasattr(h, 'name'):
                hist_list.append(h.name)
            elif isinstance(h, str):
                hist_list.append(h)
            elif isinstance(h, int):
                try:
                    hist_list.append(proj.histogram(h).name)
                except Exception:
                    continue
    for hist_name in hist_list:
        try:
            proj.link_histogram_phase(hist_name, pname)
        except Exception as e:
            print(f"Warning: could not link phase to histogram '{hist_name}': {e}")

    # Refresh internal IDs and return the new phase object
    proj.index_ids()
    proj.update_ids()
    return proj.phase(pname)

# Add all phases from phases dict (file-less approach)
def add_phases_from_dict(proj: Any, hist: Any, phases_dict: dict, print_info: bool = False) -> None:
    """
    Add phases to the GSAS-II project from a phases dictionary.

    Parameters:
    proj : GSAS-II project object
        The GSAS-II project to add phases to.
    hist : GSAS-II histogram object
        The histogram to associate with the phases.
    phases_dict : dict
        Dictionary containing phase information. (e.g., payload['phases'])
    print_info : bool
        Whether to print information about the added phases.

    Returns:
    None
    """

    for phase_name, phase_info in phases_dict.items():
        structure_info = phase_info.get('structure', {})

        # Validation check (TODO: move this upstream in phase2)
        if phase_name != structure_info.get('phase_name'):
            raise NameError(f"Phase name mismatch for '{phase_name}'. Structure info name is '{structure_info.get('phase_name')}'.")

        # Prevent duplicate phase names - TODO: handle upstream in schema validation / recipe maker
        if phase_name in [p.name for p in proj.phases()]:
            raise ValueError(f"Phase '{phase_name}' already exists in project.")

        try:
            add_phase_from_cif_dict(proj=proj, cif_data=structure_info, phase_name=phase_name, histograms=[hist])
        except Exception as e:
            raise RuntimeError(f"Failed to add phase '{phase_name}': {e}") from e
    if print_info:
        print("\nPhases in proj: ", *[ph.name for ph in proj.phases()], sep='\n\t')


##################################################################
# Functions for phase parameterization

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
    if phase_name not in [p.name for p in proj.phases()]:
        raise ValueError(f"Phase '{phase_name}' not found in project. Cannot set scale.")

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

def set_phase_unit_cell(proj: Any, phase_name: str, unit_cell_dict: dict, print_info: bool = False) -> list[str]:
    """
    Set the unit cell parameters in the GSAS-II project for a given phase.

    Schema 0.26 semantics: each cell parameter refines iff it is present with
    refine_flag=true; absent or false means fixed. Because GSAS-II has a single
    whole-cell refine flag, per-parameter control is achieved by setting that
    flag when any symmetry degree-of-freedom (DOF) group is requested and
    returning "Hold" constraint variable names (e.g. '0::A2') for the DOF
    groups that were not requested. Symmetry-linked parameters (e.g. cubic
    a=b=c, or the coupled monoclinic {a, c, beta}) refine together if any
    member is requested — see powderline.constraints.

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
    # not the arbiter of recipe correctness — see docs/known_issues.md, KI-01).

    # Note2: hist not required since unit cell is phase-specific, not histogram-specific.
    # The delineation of phase and histogram parameters is confusing in GSAS-II documentation.
    # This makes sticking with a project based approach more straightforward.

    phase_names = [p.name for p in proj.phases()]
    if phase_name not in phase_names:
        raise ValueError(f"Phase '{phase_name}' not found in project. Cannot set unit cell parameters.")

    cell_changed = False
    cell_params = ['a', 'b', 'c', 'alpha', 'beta', 'gamma'] # must match schema, and match order in GSAS-II

    for i, param in enumerate(cell_params):
        if unit_cell_dict.get(param) is not None:
            value, refine_flag, min_val, max_val = unit_cell_dict[param]

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

    if phase_name not in [p.name for p in proj.phases()]:
        raise ValueError(f"Phase '{phase_name}' not found in project. Cannot set size broadening parameters.")

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

    if phase_name not in [p.name for p in proj.phases()]:
        raise ValueError(f"Phase '{phase_name}' not found in project. Cannot set strain broadening parameters.")

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

        elif isinstance(value, list) and len(value) == 4:
            # Check RefinementParameter list [value, refine_flag, min, max]
            if value != [None, False, None, None]:
                return True

    return False


# Function to set atom parameters for a phase
def set_phase_atom_parameters(proj: Any, phase_name: str, atom_parameters_dict: dict, print_info: bool = False) -> list[str]:
    """
    Set atom parameters for a phase in the GSAS-II project.

    This function parses atom-specific refinement parameters (coordinates, occupancy, displacement)
    and constructs GSAS-II's refine_flags string ('F', 'X', 'U' combinations).

    Schema 0.26 semantics: each coordinate (x/y/z) and each anisotropic Uij
    component refines iff present with refine_flag=true; absent or false means
    fixed. GSAS-II's 'X'/'U' flags are per-atom, so per-component control is
    achieved by returning "Hold" constraint variable names (e.g. '0::dAy:3',
    '0::AU22:4') for the site-symmetry DOF groups that were not requested —
    see powderline.constraints.
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
    if phase_name not in phase_names:
        raise ValueError(f"Phase '{phase_name}' not found in project. Cannot set atom parameters.")

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
                    value, refine_flag, min_val, max_val = param_value

                    # Update coordinate value if provided
                    if value is not None:
                        atom_record[atom_param_index_mapping[coord]] = value

        # Process occupancy
        if 'occupancy' in atom_params and atom_params['occupancy'] is not None:
            param_value = atom_params['occupancy']
            if param_value != [None, False, None, None]:
                value, refine_flag, min_val, max_val = param_value

                # Update occupancy value if provided
                if value is not None:
                    atom_record[6] = value

        # Process displacement parameters based on ADP type
        if adp_type == 'Uiso':
            # Isotropic displacement parameters
            if 'Uiso' in atom_params and atom_params['Uiso'] is not None:
                param_value = atom_params['Uiso']
                if param_value != [None, False, None, None]:
                    value, refine_flag, min_val, max_val = param_value

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
                            value, refine_flag, min_val, max_val = param_value

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
        setters (schema 0.26 per-parameter refine flags). The caller applies
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

        # First, get parameterization dict from phase_info (already phase-specific)
        param_dict = phase_info.get('parameterization', {})

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
    wavelength_param = instrument_param_dict.get('wavelength', None)
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
    polarization_param = instrument_param_dict.get('polarization', None)
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
            #elif param_key == 'sample_height_displacement': # irrelevant to area detector data, future work for Bragg-Brentano geometry
            #    gsas_key = 'SampHt'
            else:
                raise ValueError(f"Unknown instrument correction parameter key '{param_key}'.")

            value, refine_flag, min_val, max_val = correction_param
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


def calculate_cell_esds_from_A_matrix(phase_idx: int, proj: Any, phase_name: str) -> List[Optional[float]]:
    """
    Calculate unit cell parameter ESDs using GSAS-II's reciprocal metric tensor conversion.

    GSAS-II refines reciprocal metric tensor components (A-matrix: A11, A22, A33, A12, A13, A23)
    and this function converts those ESDs to direct lattice parameter ESDs (a, b, c, α, β, γ).

    Args:
        phase_idx: Phase index (0-based) for parameter naming (e.g., "0::A0")
        proj: GSAS-II project object after refinement
        phase_name: Name of the phase

    Returns:
        List of 7 ESDs: [esd_a, esd_b, esd_c, esd_alpha, esd_beta, esd_gamma, esd_volume]

    Raises:
        RuntimeError: If covariance data is unavailable or the ESD calculation fails.

    Note:
        The A-matrix parameters (A0-A5) in GSAS-II correspond to:
        A0=A11, A1=A22, A2=A33, A3=A12, A4=A13, A5=A23 (reciprocal metric tensor)
        NOT direct cell parameters a, b, c, α, β, γ.
    """
    try:
        # Get covariance data
        cov_data = proj.data.get('Covariance', {}).get('data', {})
        if not cov_data:
            return [None] * 7

        # Get space group data for this phase
        SGData = proj.data['Phases'][phase_name]['General'].get('SGData')
        if not SGData:
            return [None] * 7

        # Get current cell parameters and convert to A-matrix
        cell = proj.data['Phases'][phase_name]['General']['Cell'][1:7]  # a, b, c, alpha, beta, gamma
        A = G2lat.cell2A(cell)  # Convert to reciprocal metric tensor

        # Call GSAS-II's getCellEsd function
        # pfx format: "phase_idx::" (e.g., "0::" for first phase)
        pfx = f"{phase_idx}::"
        cell_esds = G2lat.getCellEsd(pfx, SGData, A, cov_data)

        # getCellEsd returns [esd_a, esd_b, esd_c, esd_alpha, esd_beta, esd_gamma, esd_volume]
        return cell_esds

    except Exception as e:
        raise RuntimeError(
            f"Cell ESD calculation from covariance matrix failed for phase '{phase_name}'. "
            f"Ensure refinement completed successfully and covariance data is present. "
            f"Original error: {e}"
        ) from e


def extract_refined_params_from_project(proj: Any, verbose: bool = False) -> Dict[str, Dict[str, Any]]:
    """
    Extract all refined parameters with their values and ESDs from proj.data.

    Uses the covariance data stored in proj.data['Covariance']['data'] after refinement.
    This includes both independent and dependent parameters (via ComputeDepESD).

    Args:
        proj: GSAS-II project object after refinement
        verbose: If True, print progress messages.

    Returns:
        Dictionary mapping parameter names to {"value": float, "esd": float}
        Returns empty dict if no covariance data available.

    Raises:
        RuntimeError: If ComputeDepESD fails (dependent parameter ESDs cannot be calculated).

    Example:
        >>> params = extract_refined_params_from_project(proj)
        >>> params[":0:U"]
        {"value": 47.406, "esd": 8.314}
    """
    cov_data = proj.data.get('Covariance', {}).get('data', {})

    if not cov_data:
        return {}

    vary_list = cov_data.get('varyList', [])
    variables = cov_data.get('variables', [])
    sig = cov_data.get('sig', [])

    # Check if any are empty (works for both lists and numpy arrays)
    if len(vary_list) == 0 or len(variables) == 0 or len(sig) == 0:
        return {}

    # Create parameter dictionary with values and ESDs for independent parameters
    param_dict = {}
    for param_name, value, esd in zip(vary_list, variables, sig):
        param_dict[param_name] = {
            "value": float(value),
            "esd": float(esd)
        }

    # Add dependent parameter ESDs using GSAS-II's ComputeDepESD
    cov_matrix = cov_data.get('covMatrix')
    # Check if cov_matrix exists and is not empty (works for None, empty array, etc.)
    if cov_matrix is not None and hasattr(cov_matrix, '__len__') and len(cov_matrix) > 0:
        try:
            dep_sig_dict = G2mv.ComputeDepESD(cov_matrix, vary_list)
            # dep_sig_dict only contains ESDs; values are already in param_dict from
            # the independent-parameter loop above — just update the esd entries.
            for param_name, esd in dep_sig_dict.items():
                if param_name in param_dict:
                    param_dict[param_name]["esd"] = float(esd)
                # If param not in param_dict, it's a dependent param we haven't seen.
                # For now, skip it as we don't have its value easily accessible.
        except Exception as e:
            raise RuntimeError(
                f"ComputeDepESD failed; dependent parameter ESDs cannot be calculated. "
                f"Original error: {e}"
            ) from e
    elif verbose:
        print("  Note: covariance matrix is absent; dependent parameter ESDs skipped.")

    return param_dict


def extract_refined_params_from_lst(lst_file: Path) -> Dict[str, Dict[str, Any]]:
    """
    PRESERVED (disabled at call site) — see commented block in run_refinement() for context.

    Extract all refined parameters with values and ESDs from .lst file.

    NOTE: This function is incomplete and its call site has been intentionally disabled.
    The covariance matrix path (extract_refined_params_from_project) is the only supported
    extraction method. This function does not cover atom parameters and uses a custom naming
    scheme (e.g. "cell:a") that differs from the GSAS-II-native names in proj.data.

    # TODO: Remove this function once a test is written confirming that covariance matrix
    # ESD output (extract_refined_params_from_project) matches what .lst parsing previously
    # produced for the parameters it did cover (instrument, background, unit cell).
    # Do not delete until that regression test exists and passes.

    Parses the GSAS-II .lst file to extract parameter names, values, and ESDs.
    This is used as a fallback or complement to proj.data extraction.

    Args:
        lst_file: Path to the .lst file

    Returns:
        Dictionary mapping parameter names to {"value": float, "esd": float|None}
        Parameters without ESDs (fixed parameters) have esd=None.

    Note:
        Currently extracts instrument parameters, background, and unit cell.
        Additional parameter types (atoms, etc.) can be added as needed.
    """
    if not lst_file.exists():
        return {}

    param_dict = {}
    content = lst_file.read_text()
    lines = content.split('\n')

    i = 0
    while i < len(lines):
        line = lines[i]

        # Instrument parameters section
        if 'Instrument Parameters:' in line:
            # Look for the "names :" line
            i += 1
            while i < len(lines) and not lines[i].strip().startswith('names :'):
                i += 1

            if i < len(lines):
                names_line = lines[i]
                # Next line should be "value :"
                i += 1
                if i < len(lines) and lines[i].strip().startswith('value :'):
                    values_line = lines[i]
                    # Next line should be "sig :" (ESDs)
                    i += 1
                    sig_line = ""
                    if i < len(lines) and lines[i].strip().startswith('sig   :'):
                        sig_line = lines[i]

                    # Parse the three lines
                    names = names_line.split(':')[1].strip().split()
                    values = values_line.split(':')[1].strip().split()
                    sigs = sig_line.split(':')[1].strip().split() if sig_line else []

                    for j, name in enumerate(names):
                        if j < len(values):
                            try:
                                value = float(values[j])
                                esd = float(sigs[j]) if j < len(sigs) and sigs[j] else None
                                # Use GSAS-II naming convention for instrument params
                                param_name = f":0:{name}"
                                param_dict[param_name] = {"value": value, "esd": esd}
                            except (ValueError, IndexError):
                                pass

        # Background coefficients section
        elif 'Background function:' in line and 'chebyschev' in line:
            # Next line should be "value :"
            i += 1
            if i < len(lines) and lines[i].strip().startswith('value :'):
                values_line = lines[i]
                # Next line should be "sig :"
                i += 1
                sig_line = ""
                if i < len(lines) and lines[i].strip().startswith('sig   :'):
                    sig_line = lines[i]

                values = values_line.split(':')[1].strip().split()
                sigs = sig_line.split(':')[1].strip().split() if sig_line else []

                for j, value_str in enumerate(values):
                    try:
                        value = float(value_str)
                        esd = float(sigs[j]) if j < len(sigs) and sigs[j] else None
                        param_name = f":0:Back;{j}"
                        param_dict[param_name] = {"value": value, "esd": esd}
                    except (ValueError, IndexError):
                        pass

        # Unit cell parameters section
        elif 'New unit cell:' in line:
            # Look for values line
            i += 1
            while i < len(lines) and not lines[i].strip().startswith('values:'):
                i += 1

            if i < len(lines):
                values_line = lines[i]
                # Next line should be "esds  :"
                i += 1
                esds_line = ""
                if i < len(lines) and lines[i].strip().startswith('esds  :'):
                    esds_line = lines[i]

                # Parse - note that unit cell params are phase-specific
                # For now, store with generic name (can be enhanced later to include phase name)
                values = values_line.split(':')[1].strip().split()
                esds = esds_line.split(':')[1].strip().split() if esds_line else []

                cell_param_names = ['a', 'b', 'c', 'alpha', 'beta', 'gamma', 'volume']
                for j, name in enumerate(cell_param_names):
                    if j < len(values):
                        try:
                            value = float(values[j])
                            esd = float(esds[j]) if j < len(esds) and esds[j] else None
                            # Store with generic cell param naming
                            param_name = f"cell:{name}"
                            param_dict[param_name] = {"value": value, "esd": esd}
                        except (ValueError, IndexError):
                            pass

        i += 1

    return param_dict


def get_descriptive_param_name(param_name: str) -> str:
    """
    Convert GSAS-II internal parameter names to human-readable descriptions.

    Args:
        param_name: GSAS-II parameter name (e.g., ":0:U", "0::A0", ":0:Back;3")

    Returns:
        Human-readable description of the parameter

    Examples:
        >>> get_descriptive_param_name(":0:U")
        "instrument_broadening_U"
        >>> get_descriptive_param_name("0::A0")
        "phase_0_A11_reciprocal_metric_tensor"
        >>> get_descriptive_param_name(":0:Scale")
        "phase_scale_factor"
        >>> get_descriptive_param_name(":0:Back;3")
        "background_coefficient_3"
    """
    # Handle phase-specific reciprocal metric tensor (A-matrix)
    # Check for A0-A5 specifically (not AUiso, Afrac, etc.)
    if '::A' in param_name:
        parts = param_name.split('::')
        if len(parts) == 2:
            phase_idx = parts[0]
            a_param = parts[1]  # e.g., "A0", "A1", etc.

            # Only handle A0-A5 (reciprocal metric tensor)
            if a_param in ['A0', 'A1', 'A2', 'A3', 'A4', 'A5']:
                # A0-A5 map to A11, A22, A33, A12, A13, A23
                a_mapping = {
                    'A0': 'A11', 'A1': 'A22', 'A2': 'A33',
                    'A3': 'A12', 'A4': 'A13', 'A5': 'A23'
                }
                tensor_component = a_mapping[a_param]
                return f"phase_{phase_idx}_reciprocal_metric_tensor_{tensor_component}"

    # Handle other phase parameters (e.g., "0::Afrac:0", "0::Ax:0")
    if '::' in param_name:
        parts = param_name.split('::')
        phase_idx = parts[0]
        param_type = parts[1]

        if ':' in param_type:
            # Format: "0::Afrac:0" or "0::Ax:0"
            sub_parts = param_type.split(':')
            param_base = sub_parts[0]
            atom_idx = sub_parts[1]

            if param_base == 'Afrac':
                return f"phase_{phase_idx}_atom_{atom_idx}_occupancy"
            elif param_base == 'AUiso':
                return f"phase_{phase_idx}_atom_{atom_idx}_isotropic_displacement"
            elif param_base == 'Ax':
                return f"phase_{phase_idx}_atom_{atom_idx}_x_coordinate"
            elif param_base == 'Ay':
                return f"phase_{phase_idx}_atom_{atom_idx}_y_coordinate"
            elif param_base == 'Az':
                return f"phase_{phase_idx}_atom_{atom_idx}_z_coordinate"
            elif param_base.startswith('AU'):
                # Anisotropic displacement parameters (AU11, AU22, etc.)
                return f"phase_{phase_idx}_atom_{atom_idx}_anisotropic_displacement_{param_base}"
            else:
                return f"phase_{phase_idx}_atom_{atom_idx}_{param_base}"
        else:
            return f"phase_{phase_idx}_{param_type}"

    # Handle histogram parameters (format: ":hist_idx:param")
    if param_name.startswith(':') and param_name.count(':') >= 2:
        parts = param_name.split(':')
        # parts[0] is empty, parts[1] is hist_idx, parts[2] is param
        hist_idx = parts[1]
        param = parts[2] if len(parts) > 2 else ""

        # Instrument broadening parameters
        if param == 'U':
            return "instrument_broadening_U"
        elif param == 'V':
            return "instrument_broadening_V"
        elif param == 'W':
            return "instrument_broadening_W"
        elif param == 'X':
            return "instrument_broadening_X"
        elif param == 'Y':
            return "instrument_broadening_Y"
        elif param == 'Z':
            return "instrument_broadening_Z"

        # Instrument parameters
        elif param == 'Lam':
            return "wavelength"
        elif param == 'Zero':
            return "zero_point_correction"
        elif param == 'SH/L':
            return "axial_divergence"
        elif param == 'Polariz':
            return "polarization_correction"

        # Scale factor
        elif param == 'Scale':
            return "phase_scale_factor"

        # Background coefficients
        elif param.startswith('Back;'):
            coeff_idx = param.split(';')[1]
            return f"background_coefficient_{coeff_idx}"

        # Background peaks
        elif param.startswith('BkPk'):
            # Format: "BkPkpos;0", "BkPkint;0", "BkPksig;0", "BkPkgam;0"
            # Extract type (pos/int/sig/gam) and index
            if ';' in param:
                # Remove 'BkPk' prefix and split
                without_prefix = param[4:]  # Remove "BkPk"
                parts = without_prefix.split(';')
                pk_type = parts[0]  # pos, int, sig, gam
                pk_idx = parts[1] if len(parts) > 1 else "0"

                type_mapping = {
                    'pos': 'position',
                    'int': 'intensity',
                    'sig': 'sigma',
                    'gam': 'gamma'
                }
                return f"background_peak_{pk_idx}_{type_mapping.get(pk_type, pk_type)}"
            else:
                return f"background_peak_{param}"

        else:
            return f"histogram_{hist_idx}_{param}"

    # Handle phase-histogram parameters (format: "phase_idx:hist_idx:param")
    # This includes Scale and other HAP (Histogram-Atom-Phase) parameters
    if ':' in param_name and not param_name.startswith(':'):
        parts = param_name.split(':')
        if len(parts) >= 3:
            phase_idx = parts[0]
            hist_idx = parts[1]
            param = parts[2]

            if param == 'Scale':
                return f"phase_{phase_idx}_scale_factor"
            elif param.startswith('Mustrain'):
                return f"phase_{phase_idx}_mustrain_{param.split(';')[1]}"
            elif param.startswith('Size'):
                return f"phase_{phase_idx}_crystallite_size_{param.split(';')[1]}"
            else:
                return f"phase_{phase_idx}_histogram_{hist_idx}_{param}"

    # Handle cell parameters from .lst parsing
    if param_name.startswith('cell:'):
        cell_param = param_name.split(':')[1]
        param_mapping = {
            'a': 'lattice_parameter_a',
            'b': 'lattice_parameter_b',
            'c': 'lattice_parameter_c',
            'alpha': 'lattice_angle_alpha',
            'beta': 'lattice_angle_beta',
            'gamma': 'lattice_angle_gamma',
            'volume': 'unit_cell_volume'
        }
        return param_mapping.get(cell_param, f"cell_{cell_param}")

    # Fallback
    return param_name


def parse_parameter_associations(param_name: str) -> dict:
    """
    Parse GSAS-II parameter name to extract phase and atom associations.

    Args:
        param_name: GSAS-II parameter name (e.g., "0::Afrac:2", ":0:U", "1:0:Scale")

    Returns:
        Dictionary with keys 'phase_idx' and 'atom_idx' (both int or None)

    Examples:
        >>> parse_parameter_associations("0::Afrac:2")
        {"phase_idx": 0, "atom_idx": 2}
        >>> parse_parameter_associations("1::A0")
        {"phase_idx": 1, "atom_idx": None}
        >>> parse_parameter_associations("0:0:Scale")
        {"phase_idx": 0, "atom_idx": None}
        >>> parse_parameter_associations(":0:U")
        {"phase_idx": None, "atom_idx": None}
    """
    phase_idx = None
    atom_idx = None

    # Pattern 1: Phase-atom parameters (format: "phase_idx::param:atom_idx")
    # Examples: "0::Afrac:2", "1::AUiso:0", "0::Ax:3"
    if '::' in param_name:
        parts = param_name.split('::')
        try:
            phase_idx = int(parts[0])
        except (ValueError, IndexError):
            pass

        # Check if there's an atom index
        if len(parts) > 1 and ':' in parts[1]:
            sub_parts = parts[1].split(':')
            if len(sub_parts) > 1:
                try:
                    atom_idx = int(sub_parts[1])
                except (ValueError, IndexError):
                    pass

    # Pattern 2: Phase-histogram parameters (format: "phase_idx:hist_idx:param")
    # Examples: "0:0:Scale", "1:0:Mustrain;i", "0:0:Size;mx"
    elif ':' in param_name and not param_name.startswith(':'):
        parts = param_name.split(':')
        if len(parts) >= 2:
            try:
                phase_idx = int(parts[0])
            except (ValueError, IndexError):
                pass

    # Pattern 3: Histogram-only parameters (format: ":hist_idx:param")
    # Examples: ":0:U", ":0:Back;3", ":0:BkPkpos;1"
    # These have no phase or atom association (already None)

    return {"phase_idx": phase_idx, "atom_idx": atom_idx}


def build_phase_name_mapping(proj: Any) -> Dict[int, str]:
    """
    Build mapping from phase index to phase name.

    Args:
        proj: GSAS-II project object

    Returns:
        Dictionary mapping phase index (int) to phase name (str)

    Example:
        >>> mapping = build_phase_name_mapping(proj)
        >>> mapping
        {0: "LaB6", 1: "DRX_33"}
    """
    phase_mapping = {}
    try:
        phase_names = [p.name for p in proj.phases() if p is not None]
        for phase_idx, phase_name in enumerate(phase_names):
            phase_mapping[phase_idx] = phase_name
    except Exception as e:
        print(f"  Warning: Failed to build phase name mapping: {e}")
    return phase_mapping


def build_atom_name_mapping(proj: Any) -> Dict[int, Dict[int, str]]:
    """
    Build mapping from (phase_idx, atom_idx) to atom label.

    Args:
        proj: GSAS-II project object

    Returns:
        Nested dictionary: {phase_idx: {atom_idx: atom_label}}

    Example:
        >>> mapping = build_atom_name_mapping(proj)
        >>> mapping
        {0: {0: "La", 1: "B"}, 1: {0: "Li", 1: "Mg", 2: "Mn1"}}
    """
    atom_mapping = {}
    try:
        phase_names = [p.name for p in proj.phases() if p is not None]
        for phase_idx, phase_name in enumerate(phase_names):
            atom_mapping[phase_idx] = {}
            try:
                atoms_list = proj.data['Phases'][phase_name]['Atoms']
                for atom_idx, atom_record in enumerate(atoms_list):
                    # atom_record[0] is the atom label
                    atom_label = atom_record[0]
                    atom_mapping[phase_idx][atom_idx] = atom_label
            except (KeyError, IndexError, TypeError) as e:
                print(f"  Warning: Failed to extract atoms for phase '{phase_name}': {e}")
    except Exception as e:
        print(f"  Warning: Failed to build atom name mapping: {e}")
    return atom_mapping


def export_refined_parameters_csv(
    param_dict: Dict[str, Dict[str, Any]],
    output_file: Path,
    proj: Any = None,
    include_category: bool = True
) -> Optional[pd.DataFrame]:
    """
    Export refined parameters to CSV file and return the DataFrame.

    Args:
        param_dict: Dictionary from extract_refined_params_* functions
        output_file: Path to output CSV file
        proj: GSAS-II project object (optional, needed for phase/atom names)
        include_category: If True, add 'category' and 'descriptive_name' columns (default: True)

    Returns:
        DataFrame with the exported parameters, or None if param_dict is empty.

    Output CSV / DataFrame columns:
        - parameter_name: GSAS-II internal parameter name
        - descriptive_name: Human-readable parameter description (if include_category=True)
        - phase_name: Name of associated phase (None if not phase-specific)
        - phase_idx: Index of associated phase (None if not phase-specific)
        - atom_name: Label of associated atom (None if not atom-specific)
        - atom_idx: Index of associated atom (None if not atom-specific)
        - value: Refined value
        - esd: Estimated standard deviation (None for fixed parameters)
        - category: Parameter category (instrument, background, cell, etc.) if include_category=True
    """
    if len(param_dict) == 0:
        return None

    # Build phase and atom mappings if proj is available
    phase_mapping = {}
    atom_mapping = {}
    if proj is not None:
        phase_mapping = build_phase_name_mapping(proj)
        atom_mapping = build_atom_name_mapping(proj)

    rows = []
    for param_name, param_data in param_dict.items():
        # Parse parameter associations
        associations = parse_parameter_associations(param_name)
        phase_idx = associations["phase_idx"]
        atom_idx = associations["atom_idx"]

        # Lookup names from mappings
        phase_name = phase_mapping.get(phase_idx) if phase_idx is not None else None
        atom_name = atom_mapping.get(phase_idx, {}).get(atom_idx) if phase_idx is not None and atom_idx is not None else None

        row = {
            "parameter_name": param_name,
            "value": param_data["value"],
            "esd": param_data.get("esd"),
            "phase_name": phase_name,
            "phase_idx": phase_idx,
            "atom_name": atom_name,
            "atom_idx": atom_idx
        }

        if include_category:
            # Add descriptive name
            row["descriptive_name"] = get_descriptive_param_name(param_name)

            # Determine category from parameter name
            if '::A' in param_name and len(param_name.split('::')[1]) <= 2:
                # Reciprocal metric tensor (A0-A5)
                category = 'reciprocal_metric_tensor'
            elif '::' in param_name:
                # Other phase parameters (atoms, etc.)
                param_type = param_name.split('::')[1]
                if 'frac' in param_type:
                    category = 'atom_occupancy'
                elif 'Uiso' in param_type:
                    category = 'atom_displacement_isotropic'
                elif param_type.startswith('AU') and len(param_type) > 2:
                    category = 'atom_displacement_anisotropic'
                elif param_type.startswith('A') and param_type[1] in ['x', 'y', 'z']:
                    category = 'atom_position'
                else:
                    category = 'phase_other'
            elif param_name.startswith('cell:'):
                category = 'unit_cell'
            elif ':' in param_name:
                parts = param_name.split(':')
                if len(parts) >= 3:
                    param_part = parts[2]
                    if param_part.startswith('Back;'):
                        category = 'background'
                    elif param_part.startswith('BkPk'):
                        category = 'background_peak'
                    elif param_part == 'Scale':
                        category = 'scale'
                    elif param_part in ['U', 'V', 'W', 'X', 'Y', 'Z']:
                        category = 'instrument_broadening'
                    elif param_part in ['Lam', 'Zero', 'SH/L', 'Polariz']:
                        category = 'instrument'
                    else:
                        category = 'other'
                else:
                    category = 'other'
            else:
                category = 'other'

            row["category"] = category

        rows.append(row)

    # Sort by category, then parameter name
    if include_category:
        rows.sort(key=lambda x: (x["category"], x["parameter_name"]))
    else:
        rows.sort(key=lambda x: x["parameter_name"])

    # Reorder columns: parameter_name, descriptive_name, phase_name, phase_idx, atom_name, atom_idx, value, esd, category
    if include_category:
        df = pd.DataFrame(rows, columns=["parameter_name", "descriptive_name", "phase_name", "phase_idx", "atom_name", "atom_idx", "value", "esd", "category"])
    else:
        df = pd.DataFrame(rows, columns=["parameter_name", "phase_name", "phase_idx", "atom_name", "atom_idx", "value", "esd"])

    # Convert index columns to nullable integer type (Int64) to avoid scientific notation formatting
    df['phase_idx'] = df['phase_idx'].astype('Int64')
    df['atom_idx'] = df['atom_idx'].astype('Int64')

    # Format float columns independently: values need 6 decimal places, ESDs need 8
    df['value'] = df['value'].apply(lambda x: f"{x:.6e}" if pd.notna(x) else "")
    df['esd'] = df['esd'].apply(lambda x: f"{x:.8e}" if pd.notna(x) else "")

    df.to_csv(output_file, index=False, lineterminator="\n")
    return df


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


def _refine_with_message(proj) -> tuple[bool, str]:
    """Run the project refinement, returning (ok, GSAS-II failure message).

    ``G2Project.refine()`` calls ``G2strMain.Refine`` and DISCARDS its
    ``(OK, Rvals)`` return, so failure text like "Invalid metric tensor for
    phase #0" reaches only the console — callers see a silent no-Rwp failure.
    Mirror the non-sequential branch of ``refine()`` (index, constraint
    check, Refine, reload) to keep ``Rvals['msg']``. Any surprise from
    GSAS-II internals falls back to the plain ``proj.refine()`` so behavior
    is never worse than before.
    """
    try:
        from GSASII import GSASIIstrIO as G2stIO
        from GSASII import GSASIIstrMain as G2strMain

        seq_setting = proj.data['Controls']['data'].get('Seq Data', [])
        if not seq_setting:
            proj.index_ids()  # saves the project, as refine() does
            errmsg, _warnmsg = G2stIO.ReadCheckConstraints(proj.filename)
            if errmsg:
                return False, f"Constraint error: {errmsg}"
            ret = G2strMain.Refine(proj.filename, makeBack=False)
            proj.reload()
            ok, rvals = (ret if isinstance(ret, tuple) and len(ret) == 2
                         else (True, {}))
            msg = rvals.get('msg', '') if isinstance(rvals, dict) else ''
            msg = msg.replace('**** ERROR: Refinement failed ****', '').strip()
            return bool(ok), msg
    except Exception:
        pass  # GSAS-II internals changed: fall back to the plain call below

    proj.refine()
    return True, ''


def execute_rietveld_refinement(
    proj: Any,
    hist: Any,
    recipe: RecipeModel,
    verbose: bool
) -> dict:
    """
    Execute standard GSAS-II Rietveld refinement.

    This replaces the previous "structural_only" strategy.

    Args:
        proj: GSAS-II project object
        hist: Histogram object
        recipe: Validated recipe model
        verbose: Print detailed progress

    Returns:
        Result dict with success, rwp, elapsed_time
    """
    controls = recipe.payload.refinement_controls

    if verbose:
        print(f"\n{'='*60}")
        print(f"Executing Rietveld Refinement")
        print(f"  Cycles: {controls.refinement_cycles}")
        print(f"{'='*60}\n")

    # Execute refinement (keeping GSAS-II's failure message, which
    # G2Project.refine() would otherwise discard)
    refine_ok, g2_msg = _refine_with_message(proj)

    # Extract Rwp
    rwp_final = hist.residuals.get("wR")

    if not refine_ok or rwp_final is None:
        if g2_msg:
            error = f"Rietveld refinement failed: {' '.join(g2_msg.split())}"
        else:
            error = ("Rietveld refinement produced no Rwp — proj.refine() "
                     "may have failed silently")
        return {
            'success': False,
            'rwp': None,
            'error': error,
        }

    if verbose:
        print(f"Rietveld refinement complete. Final Rwp: {rwp_final:.3f}%\n")

    return {
        'success': True,
        'rwp': rwp_final
    }


def execute_spf_refinement(
    proj: Any,
    hist: Any,
    recipe: RecipeModel,
    verbose: bool
) -> dict:
    """
    Execute single peak fitting refinement.

    This replaces the previous "peaks_only" strategy.

    Args:
        proj: GSAS-II project object
        hist: Histogram object
        recipe: Validated recipe model
        verbose: Print detailed progress

    Returns:
        Result dict with success, rwp, elapsed_time
    """
    controls = recipe.payload.refinement_controls
    spf_mode = "useIP" if controls.single_peak_fitting_mode.use_instrument_profile else "hold"

    if verbose:
        print(f"\n{'='*60}")
        print(f"Executing Single Peak Fitting")
        print(f"  Mode: {spf_mode} ({'use instrument profile' if spf_mode == 'useIP' else 'refine peak widths'})")
        print(f"  Cycles: {controls.refinement_cycles}")
        print(f"{'='*60}\n")

    # Execute single peak fitting (cycles already set in step 10)
    peak_result = hist.refine_peaks(mode=spf_mode)

    # Extract Rwp from peak_result
    rwp_final = peak_result[3].get("Rwp") if len(peak_result) > 3 else None

    if rwp_final is None:
        return {
            'success': False,
            'rwp': None,
            'error': "Single peak fitting produced no Rwp — hist.refine_peaks() may have failed silently",
        }

    if verbose:
        print(f"Single peak fitting complete. Final Rwp: {rwp_final:.3f}%\n")

    return {
        'success': True,
        'rwp': rwp_final
    }


# Schema executor registry
SCHEMA_EXECUTORS = {
    'GSASII_Rietveld': execute_rietveld_refinement,
    'GSASII_SPF': execute_spf_refinement
}


########################################
# Post-refinement extraction helpers
########################################

def _extract_fit_profile(hist: Any, output_dir: Path) -> dict:
    """Extract fit profile arrays from histogram and save fit_profile.txt.

    Args:
        hist: GSAS-II histogram object after refinement.
        output_dir: Directory to write ``fit_profile.txt``.

    Returns:
        Column-oriented dict (JSON-serializable) with keys: two_theta,
        y_obs, y_weights, y_calc, y_diff, y_bkg, q_values, d_spacings.
    """
    two_theta = hist.getdata(datatype="X")
    q_values = hist.getdata(datatype="Q")
    d_spacings = hist.getdata(datatype="d")
    y_obs = hist.getdata(datatype="Yobs")
    y_weights = hist.getdata(datatype="Yweight")
    y_calc = hist.getdata(datatype="Ycalc")
    y_bkg = hist.getdata(datatype="Background")
    y_diff = hist.getdata(datatype="Residual")

    fit_profile_df = pd.DataFrame({
        "two_theta": two_theta,
        "y_obs": y_obs,
        "y_weights": y_weights,
        "y_calc": y_calc,
        "y_diff": y_diff,
        "y_bkg": y_bkg,
        "q_values": q_values,
        "d_spacings": d_spacings,
    })
    fit_profile_df.to_csv(
        output_dir / "fit_profile.txt", sep="\t", float_format="%.8f",
        header=True, index=False, lineterminator="\n"
    )
    return {col: fit_profile_df[col].tolist() for col in fit_profile_df.columns}


def _extract_spf_peak_report(
    proj: Any, hist: Any, recipe: RecipeModel, output_dir: Path, verbose: bool
) -> tuple[dict, dict]:
    """Extract single peak fitting results and save report files.

    Called only for ``GSASII_SPF`` runs where ``recipe.payload.single_peaks``
    is set. Returns two column-oriented dicts (JSON-serializable) that are
    normalised to DataFrames by ``run()``.

    Also writes:
    - ``single_peaks_report.txt`` — per-peak widths and convergence status
    - ``peak_convergence_diagnostics.txt`` — only when peaks have issues

    Args:
        proj: GSAS-II project object after refinement.
        hist: GSAS-II histogram object.
        recipe: Validated RecipeModel.
        output_dir: Directory to write report files.
        verbose: If True, print convergence warnings to stdout.

    Returns:
        ``(spf_peaks_data, spf_diagnostics_data)`` where each is a
        column-oriented dict, or ``({}, {})`` when single peaks are not used.
    """
    if recipe.payload.single_peaks is None:
        return {}, {}

    peak_list = proj.data.get(hist.name, {}).get('Peak List', {}).get('peaks', [])
    if not peak_list:
        return {}, {}

    peak_data = []
    convergence_diagnostics = []
    converged_count = 0
    aphysical_count = 0

    for i, peak in enumerate(peak_list):
        pos, pos_flag, intensity, int_flag, sig_sq, sig_sq_flag, gamma, gam_flag = peak

        # Determine convergence status
        status = "converged"
        if np.isnan(sig_sq) or np.isnan(gamma):
            status = "NaN_failed"
        elif sig_sq <= 0 and gamma < 0:
            status = "negative_sigma_sq_and_gamma_warning"
            aphysical_count += 1
        elif sig_sq <= 0:
            status = "zero_or_negative_sigma_sq_warning"
            aphysical_count += 1
        elif gamma < 0:
            status = "negative_gamma_warning"
            aphysical_count += 1
        else:
            converged_count += 1

        # Copy GSAS-II behavior for PV calc — use a small positive default for
        # aphysical (zero/negative) sigma_sq or gamma values
        sigma = np.sqrt(sig_sq) if sig_sq > 0 else DEFAULT_SPF_SIGMA_MIN
        # NOTE: GSAS-II gamma = FWHM_L (not HWHM), so we use gamma directly
        gamma_calc = gamma if gamma > 0 else DEFAULT_SPF_GAMMA_MIN

        # Calculate widths in degrees (GSAS-II stores in centidegrees)
        fwhm_g, fwhm_l, fwhm_pv, ib_g, ib_l, ib_pv, valid, warning_msg = calculate_peak_widths(
            sigma / 100, gamma_calc * 0.5 / 100
        )

        # Get GSAS-II verification (may fail for aphysical values)
        try:
            # GSAS-II uses gamma directly as FWHM_L (differs from scipy, TOPAS, literature)
            fwhm_gsas = G2pwd.getgamFW(gamma_calc / 100, sigma / 100)
        except Exception:
            fwhm_gsas = np.nan

        converged_bool = status == "converged"
        peak_data.append([
            pos, intensity, sigma, sig_sq, gamma_calc,
            fwhm_g, fwhm_l, fwhm_pv, ib_g, ib_l, ib_pv,
            fwhm_gsas, converged_bool, status
        ])

        if status != "converged":
            convergence_diagnostics.append({
                'peak_index': i,
                'position_2theta': pos,
                'final_sigma_sq': sig_sq,
                'final_gamma': gamma,
                'status': status,
                'notes': warning_msg if warning_msg else ""
            })

    # Build DataFrames
    spf_cols = [
        "position_2theta", "intensity", "sigma", "sigma_squared", "gamma",
        "fwhm_gaussian", "fwhm_lorentzian", "fwhm_pseudovoigt",
        "integral_breadth_gaussian", "integral_breadth_lorentzian",
        "integral_breadth_pseudovoigt", "fwhm_gsas_verification",
        "converged", "convergence_detail"
    ]
    spf_peaks_df = pd.DataFrame(peak_data, columns=spf_cols)
    diag_df = pd.DataFrame(convergence_diagnostics) if convergence_diagnostics else pd.DataFrame(
        columns=['peak_index', 'position_2theta', 'final_sigma_sq', 'final_gamma', 'status', 'notes']
    )

    # Write single_peaks_report.txt (custom mixed-type formatting)
    header_comment = (
        f"{converged_count} of {len(peak_list)} peaks converged; "
        f"{aphysical_count} peaks have aphysical values (warnings)"
    )
    header_cols = "\t".join(spf_cols)
    peak_array = np.array(peak_data, dtype=object)
    with open(output_dir / "single_peaks_report.txt", 'w', newline="\n") as f:
        f.write(f"# {header_comment}\n")
        f.write(f"{header_cols}\n")
        for row in peak_array:
            formatted_row = []
            for j, val in enumerate(row):
                col_name = spf_cols[j]
                if col_name == "converged":
                    formatted_row.append(str(val).lower())
                elif col_name == "convergence_detail":
                    formatted_row.append(str(val))
                else:
                    formatted_row.append("nan" if np.isnan(val) else f"{val:.8f}")
            f.write("\t".join(formatted_row) + "\n")

    # Write diagnostics file if there are issues
    if convergence_diagnostics:
        diag_df.to_csv(
            output_dir / "peak_convergence_diagnostics.txt", sep="\t",
            float_format="%.8f", header=True, index=False, lineterminator="\n"
        )
        if verbose:
            print(
                f"\nWarning: {len(convergence_diagnostics)} of {len(peak_list)} "
                f"peaks have convergence issues"
            )
            print(f"  See {output_dir / 'peak_convergence_diagnostics.txt'} for details\n")

    return (
        {col: spf_peaks_df[col].tolist() for col in spf_peaks_df.columns},
        {col: diag_df[col].tolist() for col in diag_df.columns},
    )


def _extract_phase_reports(
    proj: Any, hist: Any, recipe: RecipeModel, param_dict: dict, output_dir: Path
) -> tuple[dict, dict]:
    """Extract unit cell and peak list reports for all phases.

    Writes ``{phase}_unit_cell_report.csv`` and ``{phase}_peak_list_report.csv``
    for each phase.

    Args:
        proj: GSAS-II project object after refinement.
        hist: GSAS-II histogram object.
        recipe: Validated RecipeModel (used to check if phases exist).
        param_dict: Refined parameter dict from
            ``extract_refined_params_from_project()`` (needed for cell ESDs).
        output_dir: Directory to write CSV files.

    Returns:
        ``(unit_cell_data, peak_list_data)`` — each is a
        ``{phase_name: list-of-records}`` dict (JSON-serializable).
    """
    unit_cell_data: dict = {}
    peak_list_data: dict = {}

    if recipe.payload.phases is None or len(recipe.payload.phases) == 0:
        return unit_cell_data, peak_list_data

    phase_names = [p.name for p in proj.phases() if p is not None]

    for phase_idx, phase_name in enumerate(phase_names):
        try:
            unit_cell = proj.data['Phases'][phase_name]['General']['Cell'][1:8]
        except (KeyError, IndexError):
            continue

        cell_params = ["cell_a", "cell_b", "cell_c", "cell_alpha", "cell_beta", "cell_gamma", "cell_volume"]
        esds = calculate_cell_esds_from_A_matrix(phase_idx, proj, phase_name)

        # NOTE: .lst fallback for cell ESDs is disabled — preserved for Phase 2 reference.
        # calculate_cell_esds_from_A_matrix raises RuntimeError on failure rather than
        # returning [None]*7, so the fallback block below is unreachable.
        # if all(esd is None for esd in esds):
        #     cell_param_keys = ['a', 'b', 'c', 'alpha', 'beta', 'gamma', 'volume']
        #     esds = [param_dict.get(f"cell:{k}", {}).get("esd") for k in cell_param_keys]

        unit_cell_df = pd.DataFrame({
            "parameter": cell_params,
            "value": unit_cell,
            "esd": esds,
        })
        unit_cell_df.to_csv(
            output_dir / f"{phase_name}_unit_cell_report.csv",
            float_format="%.8f", index=False, lineterminator="\n"
        )
        unit_cell_data[phase_name] = json.loads(unit_cell_df.to_json(orient='records'))

    # Peak list for each phase
    reflection_lists = proj.data.get(hist.name, {}).get('Reflection Lists', {})
    for phase_name in phase_names:
        if phase_name not in reflection_lists:
            continue
        phase_ref = reflection_lists[phase_name]
        if 'RefList' not in phase_ref:
            continue
        reflection_list = phase_ref['RefList']
        headers = [
            "h", "k", "l", "multiplicity", "d_spacing", "2theta",
            "sigma_squared", "gamma", "F_obs_squared", "F_calc_squared",
            "phase", "I_corr", "Prfo", "Trans", "ExtP"
        ]
        peak_list_df = pd.DataFrame(reflection_list, columns=headers)
        peak_list_df.to_csv(
            output_dir / f"{phase_name}_peak_list_report.csv",
            float_format="%.8f", index=False, lineterminator="\n"
        )
        peak_list_data[phase_name] = json.loads(peak_list_df.to_json(orient='records'))

    return unit_cell_data, peak_list_data


def _extract_refined_parameters(
    param_dict: dict, output_dir: Path, proj: Any, verbose: bool
) -> list:
    """Export refined parameters to CSV and return as list-of-records.

    Args:
        param_dict: From ``extract_refined_params_from_project()``.
        output_dir: Directory to write ``refined_parameters.csv``.
        proj: GSAS-II project object (for phase/atom name mappings).
        verbose: If True, print export status to stdout.

    Returns:
        List of dicts (records) with the 9-column schema. Returns ``[]``
        when ``param_dict`` is empty (simulation mode, SPF, etc.).
    """
    if not param_dict:
        if verbose:
            print("  No refined parameters found to export")
        return []

    try:
        refined_params_csv = output_dir / "refined_parameters.csv"
        refined_params_df = export_refined_parameters_csv(
            param_dict, refined_params_csv, proj=proj
        )
        if refined_params_df is not None:
            if verbose:
                print(f"  Exported {len(param_dict)} refined parameters to {refined_params_csv.name}")
            return refined_params_df.to_dict('records')
    except Exception as e:
        if verbose:
            print(f"  Warning: Failed to export refined parameters CSV: {e}")
    return []


########################################
# Public programmatic API
########################################

def validate(recipe: RecipeModel | dict, verbose: bool = False) -> RecipeModel:
    """Validate a PowderLine recipe without running a refinement.

    Performs full Pydantic schema validation and simulation-mode consistency
    checks. Raises ``pydantic.ValidationError`` immediately on any schema
    violation so callers receive structured, actionable error information.

    This function is useful when batch-creating recipes and you want to
    confirm each one is valid before committing to a refinement run.

    Note: The ``is_template_file()`` guard is **not** applied here. That
    check is CLI-only (guards against accidentally running bare template
    files from disk). When calling ``validate()`` programmatically the
    caller is responsible for ensuring the recipe contains real data.

    Args:
        recipe: A fully-populated ``RecipeModel`` instance or equivalent
            dict. XRD data must already be present in
            ``recipe.payload.xrd_data``.
        verbose: If True, print simulation-mode warnings to stdout.

    Returns:
        Validated ``RecipeModel`` instance.

    Raises:
        pydantic.ValidationError: If the recipe fails schema validation.
        ValueError: If simulation-mode constraints are violated (all
            ``refine_flag`` fields must be ``false`` when
            ``refinement_cycles == 1``).

    Example::

        import json
        import powderline

        recipe_dict = json.load(open("my_recipe.json"))
        recipe_model = powderline.validate(recipe_dict)
        print(f"Schema: {recipe_model.schema_name}, phases: {len(recipe_model.payload.phases or [])}")
    """
    from pydantic import ValidationError  # already imported at module level, re-stated for clarity

    if not isinstance(recipe, RecipeModel):
        recipe = RecipeModel.model_validate(recipe)  # raises ValidationError on failure

    is_sim_valid, sim_warnings = validate_simulation_mode_parameters(recipe, verbose=verbose)
    if not is_sim_valid:
        raise ValueError(
            "Simulation mode validation failed. All refine_flag fields must be false "
            f"when refinement_cycles == 1.\nConstraints violated:\n"
            + "\n".join(f"  - {w}" for w in sim_warnings)
        )

    return recipe


def run(
    recipe: RecipeModel | dict,
    output_dir: Path,
    *,
    verbose: bool = False,
    validate_only: bool = False,
    execution_mode: Literal['auto', 'server', 'subprocess'] = 'auto',
) -> dict:
    """Execute a PowderLine refinement from an in-memory recipe.

    This is the primary public API for programmatic use. It encapsulates
    the full pipeline: schema validation, simulation-mode checks, output
    directory creation, and refinement execution with automatic backend
    selection.

    Note: The ``is_template_file()`` guard is **not** applied here.
    That check is CLI-only (guards against accidentally running bare
    template JSON files from disk). When calling ``run()``
    programmatically the caller is responsible for ensuring the recipe
    contains real data in ``payload.xrd_data``.

    Args:
        recipe: A fully-populated ``RecipeModel`` instance or equivalent
            dict. XRD data must already be injected into
            ``recipe.payload.xrd_data`` before calling.
        output_dir: Directory where output files will be written
            (``dummy.gpx``, ``dummy.lst``, CSV reports,
            ``fit_profile.txt``). Created if it does not exist.
        verbose: If True, print detailed progress to stdout.
        validate_only: If True, validate the recipe and return a summary
            dict without running a refinement. No output files are
            written in this mode.
        execution_mode: Controls the backend used to execute the
            refinement. One of:

            ``'auto'`` *(default)*
                Try the persistent GSAS-II server first (auto-starting
                it if needed); fall back to subprocess if unavailable.
            ``'server'``
                Use the server only. Fails with an error result if the
                server cannot be started.
            ``'subprocess'``
                Skip the server entirely; always run in a fresh
                subprocess. Suitable for batch/HPC workflows where each
                refinement is isolated.

    Returns:
        **Normal refinement** (``validate_only=False``):

        - ``success`` (bool)
        - ``run_id`` (str) — UUID4 string uniquely identifying this run
        - ``rwp`` (float | None) — final weighted-profile R factor
        - ``elapsed_time`` (float) — wall-clock seconds
        - ``method`` (str) — ``'server'`` or ``'subprocess'``
        - ``fit_profile`` (pd.DataFrame) — columns: two_theta, y_obs,
          y_weights, y_calc, y_diff, y_bkg, q_values, d_spacings
        - ``unit_cell_data`` (dict) — ``{phase_name: pd.DataFrame}``
          with columns: parameter, value, esd
        - ``peak_list_data`` (dict) — ``{phase_name: pd.DataFrame}``
          with columns: h, k, l, multiplicity, d_spacing, 2theta, …
        - ``refined_parameters`` (pd.DataFrame) — 9 columns:
          parameter_name, descriptive_name, phase_name, phase_idx,
          atom_name, atom_idx, value, esd, category
          (empty DataFrame with all 9 columns when nothing was refined)
        - ``spf_peaks`` (pd.DataFrame) — SPF peak report with columns:
          position_2theta, intensity, sigma, sigma_squared, gamma,
          fwhm_gaussian, fwhm_lorentzian, fwhm_pseudovoigt,
          integral_breadth_gaussian, integral_breadth_lorentzian,
          integral_breadth_pseudovoigt, fwhm_gsas_verification,
          converged, convergence_detail
          (empty DataFrame for non-SPF runs)
        - ``spf_convergence_diagnostics`` (pd.DataFrame) — per-peak
          diagnostic info for peaks with convergence issues; columns:
          peak_index, position_2theta, final_sigma_sq, final_gamma,
          status, notes (empty DataFrame when all peaks converged or
          for non-SPF runs)
        - ``output_files`` (list[str]) — paths written to ``output_dir``
          (informational; secondary to the DataFrame fields above)
        - ``error`` (str | None) — error message when ``success=False``

        **Validate-only** (``validate_only=True``) — a slim summary dict,
        no refinement executed, no output files written, no ``run_id``:

        - ``success`` (bool)
        - ``rwp`` (None)
        - ``elapsed_time`` (0.0)
        - ``method`` (``'validate_only'``)
        - ``schema_name`` (str)
        - ``schema_version`` (str)
        - ``phases`` (int) — number of phases in payload
        - ``refinement_cycles`` (int)
        - ``simulation_mode`` (bool)

    Raises:
        pydantic.ValidationError: If the recipe fails schema validation.
        ValueError: If simulation-mode constraints are violated.
        OSError: If ``output_dir`` cannot be created (e.g. permission denied).

    Example::

        import json
        from pathlib import Path
        import powderline

        recipe_dict = json.load(open("my_recipe.json"))
        result = powderline.run(recipe_dict, Path("output/"))
        if not result["success"]:
            raise RuntimeError(f"Refinement failed: {result['error']}")
        print(f"Rwp = {result['rwp']:.3f}%  [{result['method']} mode]")
        # Access structured results directly as DataFrames:
        unit_cell_df = result["unit_cell_data"].get("LaB6", pd.DataFrame())
    """
    # 0. Validate execution_mode early to catch typos
    _VALID_EXECUTION_MODES = ('auto', 'server', 'subprocess')
    if execution_mode not in _VALID_EXECUTION_MODES:
        raise ValueError(
            f"Invalid execution_mode={execution_mode!r}. "
            f"Must be one of: {', '.join(_VALID_EXECUTION_MODES)}"
        )

    # 1. Validate (raises ValidationError / ValueError on failure)
    recipe = validate(recipe, verbose=verbose)

    # 2. Validate_only short-circuit
    if validate_only:
        controls = recipe.payload.refinement_controls
        return {
            'success': True,
            'rwp': None,
            'elapsed_time': 0.0,
            'method': 'validate_only',
            'schema_name': recipe.schema_name,
            'schema_version': recipe.schema_version,
            'phases': len(recipe.payload.phases) if recipe.payload.phases else 0,
            'refinement_cycles': controls.refinement_cycles,
            'simulation_mode': controls.refinement_cycles == 1,
        }

    # 3. Ensure output directory exists
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # 4. Dispatch by execution_mode
    if execution_mode == 'subprocess':
        result = run_refinement(recipe, output_dir, verbose=verbose, method='subprocess')
    else:
        from powderline.gsas_client import GSASClient
        fallback = execution_mode != 'server'
        client = GSASClient(fallback_to_subprocess=fallback)
        result = client.submit_simulation(
            recipe=recipe,
            output_dir=output_dir,
            verbose=verbose,
            auto_start_server=True,
        )

    # Normalise structured data fields to DataFrames for a consistent API.
    # run_refinement() and the server return JSON-serializable primitives;
    # converting here ensures callers always receive DataFrames regardless
    # of execution_mode, without touching the HTTP serialization boundary.
    fit_profile_raw = result.get('fit_profile')
    result['fit_profile'] = (
        pd.DataFrame(fit_profile_raw) if fit_profile_raw else pd.DataFrame()
    )
    # `or {}` (not a .get default): early-failure results serialize these
    # tables as an explicit null, which .get(key, {}) passes through as None.
    result['unit_cell_data'] = {
        phase: pd.DataFrame(records)
        for phase, records in (result.get('unit_cell_data') or {}).items()
    }
    result['peak_list_data'] = {
        phase: pd.DataFrame(records)
        for phase, records in (result.get('peak_list_data') or {}).items()
    }
    refined_params_raw = result.get('refined_parameters')
    result['refined_parameters'] = (
        pd.DataFrame(refined_params_raw)
        if refined_params_raw
        else pd.DataFrame(columns=[
            'parameter_name', 'descriptive_name', 'phase_name', 'phase_idx',
            'atom_name', 'atom_idx', 'value', 'esd', 'category'
        ])
    )
    spf_peaks_raw = result.get('spf_peaks')
    result['spf_peaks'] = (
        pd.DataFrame(spf_peaks_raw) if spf_peaks_raw else pd.DataFrame()
    )
    spf_diag_raw = result.get('spf_convergence_diagnostics')
    result['spf_convergence_diagnostics'] = (
        pd.DataFrame(spf_diag_raw) if spf_diag_raw else pd.DataFrame()
    )

    # Ensure 'error' key is always present (None on success) so callers can
    # safely use result['error'] without KeyError regardless of success state.
    # Similarly normalise 'traceback' so callers never hit a KeyError.
    result.setdefault('error', None)
    result.setdefault('traceback', None)

    return result


########################################
# Kicker script for PowderLine
########################################

def run_refinement(recipe: RecipeModel, output_dir: Path, verbose: bool = False, method: str = 'server') -> dict:
    """
    Internal execution engine: run a GSAS-II refinement using already-loaded libraries.

    This function is the single execution entry point used by all paths:
    - ``gsas_server.py`` calls it directly after receiving an HTTP request
      (``method='server'``).
    - ``GSASClient._submit_via_subprocess()`` calls it in-process as the
      subprocess fallback (``method='subprocess'``). Despite the method name,
      no OS subprocess is spawned; see :meth:`GSASClient._submit_via_subprocess`.

    For programmatic use, prefer ``powderline.run()`` which validates the recipe,
    dispatches to the appropriate backend, and normalises all structured data
    fields to pandas DataFrames.

    Args:
        recipe: Validated RecipeModel instance (call ``powderline.validate()``
            first if starting from a raw dict).
        output_dir: Directory where output files are written (``dummy.gpx``,
            ``dummy.lst``, CSV reports, ``fit_profile.txt``). Must exist or be
            creatable.
        verbose: If True, print detailed progress to stdout.
        method: Execution method identifier string stored in the return dict.
            Callers set this to ``'server'`` or ``'subprocess'`` so downstream
            consumers know how the run was executed. Default ``'server'``.

    Returns:
        dict with keys:

        - ``success`` (bool)
        - ``run_id`` (str) — UUID4 string
        - ``rwp`` (float | None)
        - ``elapsed_time`` (float) — wall-clock seconds
        - ``method`` (str) — value of the ``method`` argument
        - ``output_files`` (list[str]) — paths of all files written to
          ``output_dir`` (informational)
        - ``fit_profile`` (dict) — column-oriented dict (JSON-serializable);
          normalised to ``pd.DataFrame`` by ``run()``
        - ``unit_cell_data`` (dict) — ``{phase: list-of-records}``
        - ``peak_list_data`` (dict) — ``{phase: list-of-records}``
        - ``refined_parameters`` (list) — list-of-records (9-column schema)
        - ``spf_peaks`` (dict) — column-oriented dict; populated for
          ``GSASII_SPF`` runs, empty dict otherwise
        - ``spf_convergence_diagnostics`` (dict) — column-oriented dict;
          populated when SPF peaks have convergence issues, empty dict otherwise
        - ``error`` (str) — present when ``success=False``
        - ``traceback`` (str) — present when an unhandled exception occurred

    Example::

        from powderline.kicker import run_refinement
        from powderline.schema import RecipeModel
        recipe = RecipeModel.model_validate(recipe_dict)
        result = run_refinement(recipe, Path('output'), verbose=True)
        print(f"Rwp: {result['rwp']:.3f}%  [run_id={result['run_id']}]")
    """
    # Assign a unique ID for this refinement run immediately, before any work begins,
    # so every exit path (success, GSAS-II failure, unexpected exception) can include
    # it in the returned dict and server logs.
    run_id = str(uuid.uuid4())
    import time
    start_time = time.time()

    try:
        # 1. Get xrd_data from validated model (file-less: no sample_name)
        xrd_data = recipe.payload.xrd_data

        # 2. Construct name and initialize project using standard naming
        gpx_path = output_dir / OUTPUT_NAMING.gpx_filename
        proj = G2.G2Project(newgpx=str(gpx_path))

        # 3. Instrument initialization - now a list of dicts [Iparm1, Iparm2]
        instrument_init = recipe.payload.instrument.initialization

        # 4. Add histogram - phase1B update: xrd_data is now a dict with arrays, instrument_init is list of dicts
        try:
            hist = add_powder_histogram_from_arrays(
                proj=proj,
                tth_array=xrd_data.tth,
                intensity_array=xrd_data.Itth,
                intensity_weights_array=xrd_data.Itth_weights,
                histogram_name=OUTPUT_NAMING.histogram_name,
                instrument_prm_dict=instrument_init[0],  # Use Iparm1 (first dict)
                comments=None,
                phases=None, # Optionally could link to phases if order of operations
            )
        except Exception as e:
            import traceback as _tb
            tb = _tb.format_exc()
            elapsed_time = time.time() - start_time
            return {
                'success': False,
                'rwp': None,
                'run_id': run_id,
                'error': f"Failed to load XRD data or instrument parameters: {str(e)}",
                'traceback': tb,
                'elapsed_time': elapsed_time,
                'method': method
            }

        # After adding histogram, set hist scale and refine flag to defaults
        set_hist_scale(proj, hist, hist_scale_val=DEFAULT_HIST_SCALE_VAL, hist_scale_refine_flag=DEFAULT_HIST_SCALE_REFINE_FLAG, print_info=verbose)

        # 5. Set fit range
        fit_range = recipe.payload.fit_range if recipe.payload.fit_range else (None, None)
        if fit_range != (None, None):
            set_fit_range_hist(hist, fit_range, print_info=verbose)

        # 6. Set background - Chebyshev and single peaks
        if recipe.payload.background is not None:
            background_dict = recipe.payload.background.model_dump(mode='json')
            if recipe.payload.background.chebyshev is not None:
                chebyshev_dict = background_dict.get('chebyshev')
                set_chebyshev_background(proj, hist, chebyshev_dict, print_info=verbose)
            if recipe.payload.background.single_peaks is not None:
                bkg_single_peaks_dict = background_dict.get('single_peaks')
                set_single_peak_background(proj, hist, bkg_single_peaks_dict, print_info=verbose)

        # 6b. Set single peaks (Peak List mode for non-background peaks)
        if recipe.payload.single_peaks is not None:
            single_peaks_dict = recipe.payload.single_peaks.model_dump(mode='json')
            # Check if dict has any actual peak data before calling setter
            has_peak_data = False
            for key in ['positions', 'intensities', 'pv_gaussian_sigma_sq', 'pv_lorentzian_gamma']:
                if key in single_peaks_dict and single_peaks_dict[key] and len(single_peaks_dict[key]) > 0:
                    has_peak_data = True
                    break
            if has_peak_data:
                set_single_peaks(proj, hist, single_peaks_dict, print_info=verbose)

        # 7. Add phases (if present)
        if recipe.payload.phases is not None and len(recipe.payload.phases) > 0:
            phases_dict = recipe.payload.model_dump(mode='json')['phases']
            add_phases_from_dict(proj, hist, phases_dict, print_info=verbose)

            # 8. Parameterize phases
            holds = set_phase_parameterization(proj, hist, phases_dict, print_info=verbose)

            # 8b. Apply Hold constraints for per-parameter refine flags
            # (schema 0.26: fixed members of partially-refined DOF groups).
            # The isinstance guard keeps mocked-setter unit tests inert.
            if isinstance(holds, list) and holds:
                proj.add_HoldConstr(holds)
                if verbose:
                    print(f"Applied {len(holds)} Hold constraint(s): {holds}")

        # 9. Set instrument parameterization
        instrument_param_dict = recipe.payload.instrument.parameterization.model_dump(mode='json') if recipe.payload.instrument.parameterization else None
        if instrument_param_dict is not None:
            instrument_param_changes = False
            for key, value in instrument_param_dict.items():
                if isinstance(value, dict):
                    if any(v is not None for v in value.values()):
                        instrument_param_changes = True
                        break
                elif value is not None:
                    instrument_param_changes = True
                    break
            if instrument_param_changes:
                set_instrument_parameterization(proj, hist, instrument_param_dict, print_info=verbose)

        # 10. Get refinement controls and set refinement cycles
        controls = recipe.payload.refinement_controls

        # 10a. Validate single_peak_fitting_mode requirements (only for GSASII_SPF)
        if recipe.schema_name == 'GSASII_SPF':
            if controls.single_peak_fitting_mode is None:
                raise ValueError(
                    f"Schema '{recipe.schema_name}' requires "
                    f"'single_peak_fitting_mode' to be configured in refinement_controls."
                )

        num_cycles = controls.refinement_cycles
        if num_cycles != proj.get_Controls('cycles'):
            set_refinement_cycles(proj, num_cycles, print_info=verbose)

        # 11. Execute refinement using schema-based dispatch
        executor = SCHEMA_EXECUTORS.get(recipe.schema_name)
        if executor is None:
            raise ValueError(f"Unknown schema_name: {recipe.schema_name}. Valid options: {list(SCHEMA_EXECUTORS.keys())}")

        try:
            result = executor(proj, hist, recipe, verbose)

            # Check if executor succeeded
            if not result.get('success', False):
                elapsed_time = time.time() - start_time
                return {
                    'success': False,
                    'rwp': None,
                    'run_id': run_id,
                    'error': result.get(
                        'error',
                        f"Refinement executor '{recipe.schema_name}' returned success=False without an error message",
                    ),
                    'traceback': result.get('traceback'),
                    'elapsed_time': elapsed_time,
                    'method': method
                }

        except Exception as e:
            import traceback as _tb
            tb = _tb.format_exc()
            elapsed_time = time.time() - start_time
            return {
                'success': False,
                'rwp': None,
                'run_id': run_id,
                'error': f"Refinement failed: {str(e)}",
                'traceback': tb,
                'elapsed_time': elapsed_time,
                'method': method
            }

        # Save GPX file after successful refinement
        proj.save(str(gpx_path))

        # 12. Extract final Rwp from result
        rwp = result.get('rwp')

        # --- Post-refinement data extraction ---
        # Each helper writes its own output files and returns JSON-serializable data.
        # run() normalises all dicts/lists to DataFrames for programmatic callers.

        fit_profile_data = _extract_fit_profile(hist, output_dir)

        spf_peaks_data, spf_diagnostics_data = _extract_spf_peak_report(
            proj, hist, recipe, output_dir, verbose
        )

        # Extract refined parameters (needed for unit cell ESDs in _extract_phase_reports)
        if verbose:
            print("\nExtracting refined parameters with ESDs...")

        # NOTE: .lst fallback (extract_refined_params_from_lst) is preserved for Phase 2
        # reference but its call site is intentionally disabled: .lst parsing is incomplete
        # (no atom/HAP params; different naming scheme) and obscured covariance failures.
        param_dict = extract_refined_params_from_project(proj, verbose=verbose)

        # Only raise if GSAS-II populated a varyList (i.e. parameters were actually varied)
        # but we still got nothing back. An empty param_dict with an empty varyList is
        # expected and correct for simulation mode (refinement_cycles=1, all params locked)
        # and for GSASII_SPF (no standard covariance matrix produced).
        cov_vary_list = (
            proj.data.get('Covariance', {}).get('data', {}).get('varyList', [])
        )
        if len(param_dict) == 0 and len(cov_vary_list) > 0:
            raise RuntimeError(
                "GSAS-II populated a varyList but refined parameter extraction returned "
                "empty results; covariance data may be corrupt. "
                "Ensure refinement completed successfully. "
                "Check the .lst file for GSAS-II error details."
            )

        # --- .lst fallback (disabled) ---
        # NOTE: preserved for Phase 2 reference — .lst parsing is incomplete
        # (no atom/HAP params; different naming scheme); covariance extraction is the
        # only supported path.
        # if len(param_dict) == 0:
        #     lst_file = output_dir / OUTPUT_NAMING.lst_filename
        #     if lst_file.exists():
        #         if verbose:
        #             print("  Covariance data not available, parsing .lst file...")
        #         param_dict = extract_refined_params_from_lst(lst_file)

        unit_cell_data, peak_list_data = _extract_phase_reports(
            proj, hist, recipe, param_dict, output_dir
        )

        refined_parameters_data = _extract_refined_parameters(
            param_dict, output_dir, proj, verbose
        )

        elapsed_time = time.time() - start_time
        return {
            'success': True,
            'run_id': run_id,
            'rwp': rwp,
            'elapsed_time': elapsed_time,
            'method': method,
            'output_files': [str(f) for f in output_dir.glob('*')],
            'fit_profile': fit_profile_data,
            'unit_cell_data': unit_cell_data,
            'peak_list_data': peak_list_data,
            'refined_parameters': refined_parameters_data,
            'spf_peaks': spf_peaks_data,
            'spf_convergence_diagnostics': spf_diagnostics_data,
        }

    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        import logging
        logging.getLogger(__name__).error("run_refinement failed:\n%s", tb)
        elapsed_time = time.time() - start_time
        return {
            'success': False,
            'rwp': None,
            'run_id': run_id,
            'error': str(e),
            'traceback': tb,
            'elapsed_time': elapsed_time,
            'method': method
        }


if __name__ == "__main__":
    # Ensure emoji/Unicode output works on Windows consoles that default to a
    # legacy code page (e.g. cp1252), which cannot encode the status emoji below.
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            try:
                _reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass

    # Parse command line arguments
    parser = argparse.ArgumentParser(
        description="Run GSAS-II refinement from JSON recipe",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Execution modes:
  Default (no flags):  Try server → auto-start if needed → fall back to subprocess
  --use-server:        Use server only (fail if unavailable, auto-start enabled)
  --no-server:         Use subprocess only (skip server entirely)

Examples:
  pixi run kicker recipe.json                    # Smart mode (auto-detect)
  pixi run kicker recipe.json --use-server       # Server only (with auto-start)
  pixi run kicker recipe.json --no-server        # Subprocess only
  pixi run kicker recipe.json --verbose          # Show detailed output
        """
    )

    parser.add_argument("input_json", type=Path, help="Path to input JSON recipe file")
    parser.add_argument("--output", type=Path, default=None, help="Output directory (default: input_json_parent/output)")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose output")
    parser.add_argument("--validate-only", action="store_true", help="Validate recipe without running refinement")

    # Execution mode flags
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        '--use-server',
        action='store_true',
        help='Force server mode (auto-start enabled, fail if still unavailable)'
    )
    mode_group.add_argument(
        '--no-server',
        action='store_true',
        help='Force subprocess mode (skip server entirely)'
    )

    args = parser.parse_args()

    # Set output directory
    output_dir = args.output if args.output else args.input_json.parent / "output"
    output_dir.mkdir(parents=True, exist_ok=True)

    # Load recipe
    recipe_dict = load_recipe_asset(args.input_json)

    if args.verbose:
        print(f"This is the recipe:\n\n{recipe_dict}\n\n")

    # Check if this is a template file
    is_template, template_reason = is_template_file(recipe_dict, args.input_json)
    if is_template:
        print(f"\n{CROSS} Error: This appears to be a template file ({template_reason}).")
        print(f"\nTemplate files are not meant to be run directly.")
        print(f"To create a working example:")
        print(f"  1. Copy the template directory:")
        print(f"     cp -r examples/example_template")
        print(f"  2. Edit examples/example_template/input.json with your refinement parameters")
        print(f"  3. See examples/example_template/DESCRIPTION.md for guidance")
        print(f"\nOr run an existing example:")
        print(f"     pixi run kicker examples/example_LaB6/input.json\n")
        sys.exit(1)

    # Validate recipe, check constraints, and execute via run()
    try:
        # Map CLI flags to execution_mode
        if args.no_server:
            execution_mode = 'subprocess'
        elif args.use_server:
            execution_mode = 'server'
        else:
            execution_mode = 'auto'

        if args.verbose:
            print(f"{CHECK} Template check passed. Starting refinement...\n")

        result = run(
            recipe=recipe_dict,
            output_dir=output_dir,
            verbose=args.verbose,
            validate_only=args.validate_only,
            execution_mode=execution_mode,
        )

    except ValidationError as e:
        print(f"\n{CROSS} Recipe validation failed: {args.input_json}\n")
        print("Validation errors:")
        for error in e.errors():
            location = " -> ".join(str(loc) for loc in error['loc'])
            print(f"  • {location}: {error['msg']}")
        print(f"\nPlease fix the errors above and try again.")
        print(f"See examples/example_LaB6/input.json for a working example.\n")
        sys.exit(1)

    except ValueError as e:
        print(f"\n{CROSS} {e}\n")
        sys.exit(1)

    except Exception as e:
        print(f"\n{CROSS} Unexpected error during refinement:")
        print(f"   {str(e)}")
        print(f"\nTry running with --verbose for more details:")
        print(f"  pixi run kicker {args.input_json} --verbose\n")
        sys.exit(1)

    # Handle validate_only result
    if args.validate_only:
        print(f"{CHECK} Recipe validation successful: {args.input_json}")
        print(f"   Schema name: {result.get('schema_name')}")
        print(f"   Schema version: {result.get('schema_version')}")
        print(f"   Phases: {result.get('phases', 0)}")
        print(f"   Refinement cycles: {result.get('refinement_cycles')}")
        if result.get('simulation_mode'):
            print(f"   Mode: Simulation (all parameters locked)")
        sys.exit(0)

    # Show execution mode and timing
    mode_emoji = emoji("🚀" if result.get('method') == 'server' else "🐢")
    print(f"\n{INFO} Executed using {result.get('method', 'unknown')} mode {mode_emoji} ({result.get('elapsed_time', 0):.1f}s)")
    if args.verbose and 'run_id' in result:
        print(f"{INFO} Run ID: {result['run_id']}")

    # Check for success
    if not result.get('success'):
        print(f"\n{CROSS} Refinement failed:")
        print(f"   {result.get('error', 'Unknown error')}")
        print(f"\nCheck .lst file for detailed error messages: {output_dir}/*.lst\n")
        sys.exit(1)

    # Report final Rwp
    if result.get('rwp') is not None:
        print(f"{CHECK} Refinement complete. Final Rwp: {result['rwp']:.3f}%\n")
    else:
        print(f"{CHECK} Refinement complete.\n")
