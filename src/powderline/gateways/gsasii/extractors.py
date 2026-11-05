"""GSAS-II gateway — post-refinement extraction and reporting.

Moved verbatim from ``powderline/kicker.py`` (multi-engine refactor, re/01).
"""
from __future__ import annotations
import json
import numpy as np
import pandas as pd
from typing import Any, Dict, List, Optional
from pathlib import Path
from GSASII import GSASIIlattice as G2lat
from GSASII import GSASIImapvars as G2mv
from GSASII import GSASIIpwd as G2pwd
from powderline.gateways.gsasii.schema import GsasiiRietveldRecipe, GsasiiSpfRecipe

from powderline.gateways.gsasii.report_rows import pandas_csv_rows
from powderline.reports import (
    write_fit_profile,
    write_peak_list_report,
    write_refined_parameters,
    write_unit_cell_report,
)
from powderline.gateways.gsasii.helpers import (
    DEFAULT_SPF_GAMMA_MIN,
    DEFAULT_SPF_SIGMA_MIN,
    calculate_peak_widths,
)



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
        list[float | None]: The 7 ESDs, in order
        ``[esd_a, esd_b, esd_c, esd_alpha, esd_beta, esd_gamma, esd_volume]``.

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
            # R34 (re/24, P-45): no covariance means nothing was refined (a simulation); every cell value is
            # a stated number, so its ESD is 0.0 under the one unit-cell report ESD rule -- not "unknown".
            return [0.0] * 7

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
        dict: Mapping of parameter names to ``{"value": float, "esd": float}``.
        Returns an empty dict if no covariance data is available.

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

    if include_category and Path(output_file).name == "refined_parameters.csv":  # the core writer's file (A83)
        write_refined_parameters(Path(output_file).parent, pandas_csv_rows(df))
    else:
        df.to_csv(output_file, index=False, lineterminator="\n")
    return df


########################################
# Post-refinement extraction helpers
########################################

def _extract_fit_profile(hist: Any, output_dir: Path) -> dict:
    """Extract fit profile arrays from histogram and save fit_profile.txt.

    Args:
        hist: GSAS-II histogram object after refinement.
        output_dir: Directory to write ``fit_profile.txt``.

    Returns:
        dict: Column-oriented data (JSON-serializable) with keys ``two_theta``,
        ``y_obs``, ``y_weights``, ``y_calc``, ``y_diff``, ``y_bkg``, ``q_values``,
        ``d_spacings``.
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
    write_fit_profile(output_dir, pandas_csv_rows(fit_profile_df, "%.8f"))  # core writer (A83)
    return {col: fit_profile_df[col].tolist() for col in fit_profile_df.columns}


def _extract_spf_peak_report(
    proj: Any, hist: Any, recipe: GsasiiRietveldRecipe | GsasiiSpfRecipe, output_dir: Path, verbose: bool
) -> tuple[dict, dict]:
    """Extract single peak fitting results and save report files.

    Called only for ``gsasii.spf`` runs where ``recipe.payload.single_peaks``
    is set. Returns two column-oriented dicts (JSON-serializable) that are
    normalised to DataFrames by ``run()``.

    Also writes:
    - ``single_peaks_report.txt`` — per-peak widths and convergence status
    - ``peak_convergence_diagnostics.txt`` — only when peaks have issues

    Args:
        proj: GSAS-II project object after refinement.
        hist: GSAS-II histogram object.
        recipe: Validated ``gsasii.spf`` recipe model.
        output_dir: Directory to write report files.
        verbose: If True, print convergence warnings to stdout.

    Returns:
        ``(spf_peaks_data, spf_diagnostics_data)`` where each is a
        column-oriented dict, or ``({}, {})`` when single peaks are not used.
    """
    if getattr(recipe.payload, 'single_peaks', None) is None:  # gsasii.spf only
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
    proj: Any, hist: Any, recipe: GsasiiRietveldRecipe | GsasiiSpfRecipe, param_dict: dict, output_dir: Path
) -> tuple[dict, dict]:
    """Extract unit cell and peak list reports for all phases.

    Writes ``{phase}_unit_cell_report.csv`` and ``{phase}_peak_list_report.csv``
    for each phase.

    Args:
        proj: GSAS-II project object after refinement.
        hist: GSAS-II histogram object.
        recipe: Validated ``gsasii.rietveld`` / ``gsasii.spf`` recipe model (used to check if phases exist).
        param_dict: Refined parameter dict from
            ``extract_refined_params_from_project()`` (needed for cell ESDs).
        output_dir: Directory to write CSV files.

    Returns:
        ``(unit_cell_data, peak_list_data)`` — each is a
        ``{phase_name: list-of-records}`` dict (JSON-serializable).
    """
    unit_cell_data: dict = {}
    peak_list_data: dict = {}

    if getattr(recipe.payload, 'phases', None) is None or len(recipe.payload.phases) == 0:  # gsasii.rietveld only
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
        write_unit_cell_report(output_dir, phase_name, pandas_csv_rows(unit_cell_df, "%.8f"))  # core writer (A83)
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
        write_peak_list_report(output_dir, phase_name, pandas_csv_rows(peak_list_df, "%.8f"),
                               columns=headers)  # core writer (A83)
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
