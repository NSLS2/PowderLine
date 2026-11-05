"""GSAS-II gateway — GSAS-II project construction (histograms, phases).

Moved verbatim from ``powderline/kicker.py`` (multi-engine refactor, re/01).
"""
from __future__ import annotations
import sys
import random as ran
import numpy as np
from typing import Any, Dict, List, Optional, Sequence, Union
from GSASII import GSASIIlattice as G2lat
from GSASII import GSASIIobj as G2obj
from GSASII import GSASIIspc as G2spc
from GSASII import GSASIIElem as G2elem
from powderline.gateways.gsasii.schema import gsasii_space_group
from powderline.gateways.gsasii.scattering import gsasii_type  # R35 (re/28, P-47)


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
    sg = gsasii_space_group(cif_data["space_group"])  # canonical name -> GSAS-II symbol (A105, EB-41)
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
        unit_cell_constants = [unit_cell[k][0] for k in ("a", "b", "c", "alpha", "beta", "gamma")]  # [value, refine_flag]
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
        x = float(atom["x"][0])  # [value, refine_flag]
        y = float(atom["y"][0])
        z = float(atom["z"][0])
        occ = float(atom["occupancy"][0])

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
        # R35 (re/28, P-47): the stated ionic type, in GSAS-II's own spelling (``La3+`` -> ``La+3``); neutral otherwise
        atom_record[1] = gsasii_type((cif_data.get("scattering_types") or {}).get(label, atom.get("element", label.rstrip('0123456789') or "X")))
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
                atom_record[11] = float(uaniso_dict["U11"][0])
                atom_record[12] = float(uaniso_dict["U22"][0])
                atom_record[13] = float(uaniso_dict["U33"][0])
                atom_record[14] = float(uaniso_dict["U12"][0])
                atom_record[15] = float(uaniso_dict["U13"][0])
                atom_record[16] = float(uaniso_dict["U23"][0])

                # Set atom_record[10] to Uiso if provided, else calculate from diagonal elements
                if atom.get("Uiso") is not None:
                    atom_record[10] = float(atom["Uiso"][0])
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
                atom_record[10] = float(uiso[0])
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
        structure_info = phase_info  # the phase block (gsasii 0.1.0, A93); the name is the dict key (A100)

        # Prevent duplicate phase names - TODO: handle upstream in schema validation / recipe maker
        if phase_name in [p.name for p in proj.phases()]:
            raise ValueError(f"Phase '{phase_name}' already exists in project.")

        try:
            add_phase_from_cif_dict(proj=proj, cif_data=structure_info, phase_name=phase_name, histograms=[hist])
        except Exception as e:
            raise RuntimeError(f"Failed to add phase '{phase_name}': {e}") from e
    if print_info:
        print("\nPhases in proj: ", *[ph.name for ph in proj.phases()], sep='\n\t')
