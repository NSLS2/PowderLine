# Recipe Helper Code and LLM Prompt

This page holds two **helpers** for building recipes from your own files: a
small Python module that reads a CIF, a GSAS-II `.instprm` file, and a
diffraction pattern into recipe-shaped dicts, and a prompt template you can
hand to an LLM coding assistant to drive that module.

> **These are guidance, not an authoritative recipe builder.** PowderLine does
> not ship a recipe builder (see [Building Recipes](building-recipes.md) for
> why). The code below is not part of the `powderline` package, is not covered
> by its tests, and makes choices — default values, which flags start on —
> that may not suit your data. Read it, adapt it, and check every recipe it
> produces. A recipe that passes validation can still describe the wrong model.

## The I/O helper module

Copy the code block below into a file named `io_helpers.py` next to your data
(or anywhere on your `PYTHONPATH`). It needs only `numpy` and `gemmi`, both of
which are installed with PowderLine, so it runs inside PowderLine's pixi
environment (`pixi shell` from your PowderLine clone) or any environment where
PowderLine is installed.

| Function | Reads / builds | Recipe section |
|---|---|---|
| `read_cif(path, phase_name=None)` | a CIF → `(structure, warnings)` | `phases.<name>.structure` |
| `phase_block(structure)` | the structure plus a parameterization with every flag `False` | `phases` |
| `merge_phases(*blocks)` | several phases, rejecting duplicate names | `phases` |
| `read_instprm(path)` | a GSAS-II `.instprm` file → flat dict | — |
| `instrument_block(flat, description, refine_profile=False)` | the instrument section | `instrument` |
| `read_pattern(path, x_unit="2theta", wavelength=None)` | a 2- or 3-column pattern → `(xrd_data, warnings)` | `xrd_data` |
| `assemble_recipe(...)` | the full `{schema_name, schema_version, payload}` | — |
| `save_recipe(recipe, path)` | JSON file for `pixi run kicker` | — |

A minimal Rietveld recipe:

```python
import io_helpers as io
import powderline

structure, cif_warnings = io.read_cif("LaB6.cif", phase_name="LaB6")
phases = io.phase_block(structure)  # every refine flag starts False
instrument = io.instrument_block(io.read_instprm("my_beamline.instprm"),
                                 "my beamline", refine_profile=True)
xrd_data, data_warnings = io.read_pattern("LaB6.xye")
for w in cif_warnings + data_warnings:
    print("WARNING:", w)

# Choose what to refine
p = phases["LaB6"]["parameterization"]
p["scale"][1] = True
p["unit_cell"]["a"][1] = True

recipe = io.assemble_recipe(
    xrd_data=xrd_data,
    instrument=instrument,
    phases=phases,
    background={"chebyshev": {"num_coefficients": 6,
                              "coefficients": [10, 5, 1, 0, 0, 0],
                              "refine_flag": True}},
    fit_range=[1.0, 15.0],
)
powderline.validate(recipe)
io.save_recipe(recipe, "recipe.json")  # then: pixi run kicker recipe.json
```

For a multi-phase recipe, read each CIF with its own `phase_name` and combine
the blocks with `io.merge_phases(...)`. For single-peak fitting, simulation
mode, and engine-specific limits, see the `assemble_recipe` docstring and
[Supported Features](capabilities.md).

```python
"""io_helpers.py -- example code for turning a CIF, a GSAS-II .instprm file, and a
diffraction pattern into a PowderLine recipe.

This module is NOT part of PowderLine and is not an authoritative recipe builder.
It is guidance: copy it, read it, and adapt it to your data. It was written
against recipe schema 0.26.0 (PowderLine 0.1.2); check the PowderLine docs if
your version differs.

Requirements: numpy and gemmi (both installed with PowderLine). PowderLine
itself is only needed for the final ``powderline.validate`` / ``powderline.run``.

Every builder function returns plain dicts in the recipe's shape and sets every
refine flag to False -- you decide what to refine. Readers return
``(result, warnings)``: print the warnings and check them. Problems that would
silently produce a wrong model (no space group, an unknown element, an atom
without coordinates) raise ``ValueError`` instead of being defaulted.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path

import gemmi
import numpy as np

SCHEMA_VERSION = "0.26.0"  # must equal PowderLine's EXPECTED_SCHEMA_VERSION exactly

DEFAULT_SIZE_UM = 10.0  # isotropic crystallite size, microns (GSAS-II convention)
DEFAULT_MICROSTRAIN = 0.0  # isotropic microstrain, (delta d / d) x 10^6
EIGHT_PI_SQ = 8.0 * math.pi**2  # B = 8 pi^2 U
U_KEYS = ("U11", "U22", "U33", "U12", "U13", "U23")


def _fixed(value):
    """A recipe leaf ``[value, refine_flag, min, max]``, held fixed."""
    return [value, False, None, None]


def _phase_key(name: str) -> str:
    """Recipe phase names: whitespace runs become underscores."""
    return re.sub(r"\s+", "_", name.strip())


# -- CIF -> phase ---------------------------------------------------------------


def _values(block, tag):
    """Values of a CIF tag (looped or single) as raw strings, or None if absent."""
    col = block.find_values(tag)
    return [col[i] for i in range(len(col))] if len(col) else None


def _number(raw):
    """CIF number with its s.u. stripped ("1.234(5)" -> 1.234); None for '?' / '.'."""
    if raw is None:
        return None
    value = gemmi.cif.as_number(raw)
    return None if math.isnan(value) else value


def _element(raw):
    """Element symbol from a type symbol or label, or None.

    Case-insensitive, two-letter symbols first: "O2-" -> "O", "La1" -> "La",
    "FE1" -> "Fe", "CL1" -> "Cl".
    """
    text = gemmi.cif.as_string(raw).strip()
    for size in (2, 1):
        symbol = text[:size].capitalize()
        if re.fullmatch(r"[A-Z][a-z]?", symbol) and gemmi.Element(symbol).name != "X":
            return symbol
    return None


def read_cif(path, phase_name=None):
    """Read the first CIF data block that has a cell and atom sites.

    Returns ``(structure, warnings)``, where ``structure`` is the recipe's
    ``phases.<name>.structure`` block::

        {"phase_name", "space_group", "unit_cell": {a, b, c, alpha, beta, gamma, volume},
         "atoms": {label: {element, x, y, z, occupancy, ADP, Uiso [, Uaniso]}}}

    Raises ``ValueError`` for a missing/unknown space group, an incomplete cell,
    missing coordinates, or an element that cannot be identified. Missing
    occupancies (-> 1.0) and missing Uiso/Biso (-> 0.0) are defaulted, with a
    warning. B values are converted to U (U = B / 8 pi^2). Ionic type symbols
    ("O2-") are reduced to the neutral element. ``Multiplicity`` is not written;
    PowderLine derives it from the space group.
    """
    raw = Path(path).read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")  # many real CIFs are latin-1 / cp1252
    doc = gemmi.cif.read_string(text)
    block = next(
        (b for b in doc if b.find_value("_cell_length_a") and len(b.find_values("_atom_site_fract_x"))),
        None,
    )
    if block is None:
        raise ValueError(f"{path}: no data block with both a unit cell and atom sites")
    warnings = []

    # Phase name
    name = phase_name
    if not name:
        for tag in ("_pd_phase_name", "_chemical_name_common", "_chemical_formula_sum"):
            value = block.find_value(tag)
            if value and gemmi.cif.as_string(value).strip() not in ("", "?", "."):
                name = gemmi.cif.as_string(value)
                break
    if not name:
        raise ValueError(f"{path}: CIF has no phase name; pass phase_name=...")
    name = _phase_key(name)

    # Space group: the symbol as written, checked with gemmi; else the IT number
    symbol = None
    for tag in ("_space_group_name_H-M_alt", "_symmetry_space_group_name_H-M"):
        value = block.find_value(tag)
        if value and gemmi.cif.as_string(value).strip() not in ("", "?", "."):
            symbol = gemmi.cif.as_string(value).strip()
            break
    if symbol:
        sg = gemmi.find_spacegroup_by_name(symbol)
        if sg is None:
            raise ValueError(f"{path}: space group symbol {symbol!r} not recognized")
    else:
        number = None
        for tag in ("_space_group_IT_number", "_symmetry_Int_Tables_number"):
            number = _number(block.find_value(tag)) or number
        if not number:
            raise ValueError(f"{path}: no space group symbol or number; refusing to guess")
        sg = gemmi.find_spacegroup_by_number(int(number))
        symbol = sg.hm
        warnings.append(f"space group taken from IT number {int(number)} as {symbol!r}; check the setting")
    if sg.ext in ("1", "2"):
        warnings.append(
            f"space group {symbol!r} has two origin choices: GSAS-II assumes origin choice 2 and "
            "the TOPAS engine needs it written out (e.g. 'F d -3 m:2'); check that the CIF "
            "coordinates use origin choice 2"
        )
    elif sg.ext in ("H", "R"):
        warnings.append(
            f"rhombohedral space group {symbol!r}: use hexagonal axes (gamma = 120); "
            "the TOPAS engine rejects rhombohedral axes"
        )

    # Unit cell
    cell = {k: _number(block.find_value(f"_cell_{t}"))
            for k, t in (("a", "length_a"), ("b", "length_b"), ("c", "length_c"),
                         ("alpha", "angle_alpha"), ("beta", "angle_beta"), ("gamma", "angle_gamma"))}
    if None in cell.values():
        raise ValueError(f"{path}: incomplete unit cell {cell}")
    cell["volume"] = gemmi.UnitCell(*cell.values()).volume

    # Atom sites
    labels = _values(block, "_atom_site_label")
    xyz = [_values(block, f"_atom_site_fract_{c}") for c in "xyz"]
    types = _values(block, "_atom_site_type_symbol")
    occs = _values(block, "_atom_site_occupancy")
    uisos = _values(block, "_atom_site_U_iso_or_equiv")
    bisos = _values(block, "_atom_site_B_iso_or_equiv")

    # Anisotropic Uij (or Bij, converted), keyed by label
    aniso = {}
    aniso_labels = _values(block, "_atom_site_aniso_label") or []
    for prefix, factor in (("U", 1.0), ("B", 1.0 / EIGHT_PI_SQ)):
        cols = {k: _values(block, f"_atom_site_aniso_{prefix}_{k[1:]}") for k in U_KEYS}
        if all(cols.values()):
            for i, lbl in enumerate(aniso_labels):
                values = {k: _number(cols[k][i]) for k in U_KEYS}
                aniso[gemmi.cif.as_string(lbl)] = {
                    k: None if value is None else value * factor for k, value in values.items()
                }
            break

    atoms = {}
    for i, raw_label in enumerate(labels):
        label = gemmi.cif.as_string(raw_label)
        coords = [_number(col[i]) for col in xyz]
        if None in coords:
            raise ValueError(f"{path}: atom {label!r} has missing coordinates")
        element = _element(types[i]) if types else None
        if element is None:
            element = _element(label)
            if element is not None:
                warnings.append(f"atom {label!r}: no usable type symbol, element {element!r} taken from the label")
        if element is None:
            raise ValueError(f"{path}: cannot determine the element of atom {label!r}")
        if types and gemmi.cif.as_string(types[i]).strip().lower() not in (element.lower(), ""):
            warnings.append(f"atom {label!r}: type {gemmi.cif.as_string(types[i])!r} used as neutral {element!r}")

        occ = _number(occs[i]) if occs else None
        if occ is None:
            occ = 1.0
            warnings.append(f"atom {label!r}: no occupancy, set to 1.0")
        uiso = _number(uisos[i]) if uisos else None
        if uiso is None and bisos:
            biso = _number(bisos[i])
            uiso = None if biso is None else biso / EIGHT_PI_SQ
        if uiso is None:
            uiso = 0.0
            warnings.append(f"atom {label!r}: no Uiso/Biso, set to 0.0")

        atom = {"element": element, "x": coords[0], "y": coords[1], "z": coords[2],
                "occupancy": occ, "ADP": "Uiso", "Uiso": uiso}
        if label in aniso and None not in aniso[label].values():
            atom["ADP"] = "Uaniso"
            atom["Uaniso"] = aniso[label]
        elif label in aniso:
            warnings.append(f"atom {label!r}: incomplete anisotropic ADPs, using Uiso instead")
        atoms[label] = atom

    structure = {"phase_name": name, "space_group": symbol, "unit_cell": cell, "atoms": atoms}
    return structure, warnings


def phase_block(structure):
    """Wrap a ``structure`` (from :func:`read_cif`) as ``{name: {structure, parameterization}}``.

    The parameterization repeats every refinable value as ``[value, False, None, None]``:
    phase scale, cell, per-atom x/y/z/occupancy/Uiso (or the six Uaniso terms),
    and explicit isotropic size/strain broadening. Size and strain are written out
    because leaving them unset lets each engine apply its own, different defaults.
    """
    name = structure["phase_name"]
    cell = {k: _fixed(structure["unit_cell"][k]) for k in ("a", "b", "c", "alpha", "beta", "gamma")}
    atoms = {}
    for label, atom in structure["atoms"].items():
        entry = {k: _fixed(atom[k]) for k in ("x", "y", "z", "occupancy")}
        entry["ADP"] = atom["ADP"]
        if atom["ADP"] == "Uaniso":
            entry["Uaniso"] = {k: _fixed(v) for k, v in atom["Uaniso"].items()}
        else:
            entry["Uiso"] = _fixed(atom["Uiso"])
        atoms[label] = entry
    parameterization = {
        "scale": _fixed(1.0),
        "unit_cell": cell,
        "atoms": atoms,
        "peak_broadening": {
            "size_broadening": {"model": "isotropic", "isotropic_size": _fixed(DEFAULT_SIZE_UM),
                                "LG_eta": _fixed(1.0)},
            "strain_broadening": {"model": "isotropic", "isotropic_strain": _fixed(DEFAULT_MICROSTRAIN),
                                  "LG_eta": _fixed(1.0)},
        },
    }
    return {name: {"structure": structure, "parameterization": parameterization}}


def merge_phases(*blocks):
    """Combine :func:`phase_block` outputs; raises on a duplicate phase name."""
    merged = {}
    for block in blocks:
        for name, phase in block.items():
            if name in merged:
                raise ValueError(f"duplicate phase name {name!r}; pass a distinct phase_name to read_cif")
            merged[name] = phase
    return merged


# -- .instprm -> instrument ------------------------------------------------------


def read_instprm(path):
    """Read a single-bank GSAS-II ``.instprm`` file into a flat dict.

    Each line holds one or more ``key:value`` pairs separated by ``;``, as in
    GSAS-II's own reader. For a multi-bank file, extract one bank first.
    """
    flat = {}
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        for pair in line.split(";"):
            if ":" not in pair:
                continue
            key, value = (s.strip() for s in pair.split(":", 1))
            try:
                flat[key] = float(value)
            except ValueError:
                flat[key] = value
    return flat


def instrument_block(flat, description, refine_profile=False):
    """Build ``payload.instrument`` from a flat ``.instprm`` dict.

    ``initialization`` holds every key as ``[value, value, False]`` (always emit
    the three-element form: the TOPAS and easydiffraction engines read the
    second element). ``parameterization`` holds the refinable terms; a ``None``
    value keeps the ``initialization`` value. ``refine_profile=True`` flags U, V,
    W, X and Y (not Z, which easydiffraction cannot refine). Zero shift and axial
    divergence are left unset (fixed); set e.g.
    ``corrections["zero_shift"] = [None, True, None, None]`` to refine one.

    Raises ``ValueError`` for a two-wavelength (Ka1/Ka2) file or a missing
    ``Type`` / ``Lam``: PowderLine supports single-wavelength data only.
    """
    if "Lam1" in flat or "Lam2" in flat:
        raise ValueError("two-wavelength (Lam1/Lam2) instrument files are not supported; use a single Lam")
    for key in ("Type", "Lam"):
        if key not in flat:
            raise ValueError(f".instprm has no {key!r} entry")
    init = {k: [v, v, False] for k, v in flat.items()}
    if "Bank" in init:
        init["Bank"] = [int(flat["Bank"]), int(flat["Bank"]), False]
    parameterization = {
        "wavelength": _fixed(flat["Lam"]),
        "broadening": {k: [None, refine_profile and k != "Z", None, None] for k in "UVWXYZ"},
        "corrections": {"zero_shift": None, "axial_divergence": None},
    }
    if "Polariz." in flat:
        parameterization["polarization"] = _fixed(flat["Polariz."])
    return {"description": description, "initialization": [init, {}], "parameterization": parameterization}


# -- pattern -> xrd_data ---------------------------------------------------------


def read_pattern(path, x_unit="2theta", wavelength=None):
    """Read a 2- or 3-column text pattern (.xy, .xye, .chi, .csv, .dat, .txt).

    Columns: x, intensity, and optionally the intensity's standard uncertainty
    (esd). Leading lines that are not at least two numbers (titles, column names,
    a point count) are skipped; ``#`` lines are ignored anywhere. Columns may be
    separated by whitespace, commas, or semicolons.

    ``x_unit`` is ``"2theta"`` (degrees), ``"q"`` (1/Angstrom) or ``"d"``
    (Angstrom); Q and d need ``wavelength`` (Angstrom) and are converted to 2theta.
    Points are sorted by 2theta; repeated 2theta values raise.

    Weights (1/sigma^2): 3 columns -> 1/esd^2 (an esd <= 0 raises); 2 columns ->
    1/max(I, 1), i.e. counting statistics with a floor for I <= 1 (warned).
    Intensities are never changed and no point is dropped.

    Returns ``(xrd_data, warnings)`` with ``xrd_data = {"tth", "Itth",
    "Itth_weights", "filename"}``.
    """
    rows, started = [], False
    for n, line in enumerate(Path(path).read_text(errors="replace").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        tokens = [t for t in re.split(r"[\s,;]+", line) if t]
        try:
            values = [float(t) for t in tokens]
        except ValueError:
            values = []
        if len(values) >= 2:
            rows.append(values[:3])
            started = True
        elif started:
            raise ValueError(f"{path}:{n}: cannot parse data line {line!r}")
    if not rows or len({len(r) for r in rows}) != 1:
        raise ValueError(f"{path}: expected rows of 2 or 3 numbers in every data line")
    data = np.array(rows, dtype=float)
    x, intensity = data[:, 0], data[:, 1]
    warnings = []

    if x_unit == "2theta":
        tth = x
        if tth.max() < 5.0:
            warnings.append(f"x runs {tth.min():.3g}..{tth.max():.3g}; check that it is 2theta, not Q or d")
    elif x_unit in ("q", "d"):
        if wavelength is None:
            raise ValueError(f"x_unit={x_unit!r} needs wavelength= (Angstrom)")
        sin_theta = x * wavelength / (4 * math.pi) if x_unit == "q" else wavelength / (2 * x)
        if np.any(np.abs(sin_theta) > 1):
            raise ValueError(f"some {x_unit} values are unreachable at wavelength {wavelength} A")
        tth = np.degrees(2 * np.arcsin(sin_theta))
    else:
        raise ValueError(f"x_unit must be '2theta', 'q' or 'd', not {x_unit!r}")

    if data.shape[1] == 3:
        esd = data[:, 2]
        invalid_esd = ~np.isfinite(esd) | (esd <= 0)
        if np.any(invalid_esd):
            raise ValueError(f"{path}: {np.count_nonzero(invalid_esd)} esd values are <= 0 or not finite")
        weights = 1.0 / esd**2
    else:
        weights = 1.0 / np.maximum(intensity, 1.0)
        n_low = int(np.count_nonzero(intensity <= 1.0))
        if n_low:
            warnings.append(
                f"{n_low} points have I <= 1 and get weight 1 (2-column data assumes counts; "
                "supply a third esd column for background-subtracted or rescaled data)"
            )

    order = np.argsort(tth, kind="stable")
    tth, intensity, weights = tth[order], intensity[order], weights[order]
    if np.any(np.diff(tth) <= 0):
        raise ValueError(f"{path}: repeated 2theta values")
    xrd_data = {"tth": tth.tolist(), "Itth": intensity.tolist(),
                "Itth_weights": weights.tolist(), "filename": Path(path).name}
    return xrd_data, warnings


# -- recipe ---------------------------------------------------------------------


def assemble_recipe(*, schema_name="GSASII_Rietveld", xrd_data, instrument, phases=None,
                    background=None, single_peaks=None, refinement_controls=None, fit_range=None):
    """Put the sections together as ``{schema_name, schema_version, payload}``.

    ``refinement_controls`` defaults to ``{"refinement_cycles": 5}``.
    ``refinement_cycles: 1`` is simulation mode: no refine flag may be true.
    ``GSASII_Rietveld`` needs ``phases``; ``GSASII_SPF`` needs ``single_peaks``,
    no ``phases``, and ``refinement_controls["single_peak_fitting_mode"]``.
    ``fit_range`` is ``[min_2theta, max_2theta]`` in degrees (either may be None).
    """
    payload = {"xrd_data": xrd_data, "instrument": instrument,
               "refinement_controls": refinement_controls or {"refinement_cycles": 5}}
    for key, value in (("phases", phases), ("background", background),
                       ("single_peaks", single_peaks), ("fit_range", fit_range)):
        if value is not None:
            payload[key] = value
    return {"schema_name": schema_name, "schema_version": SCHEMA_VERSION, "payload": payload}


def save_recipe(recipe, path):
    """Write the recipe as JSON (what ``pixi run kicker <file>`` reads)."""
    Path(path).write_text(json.dumps(recipe, indent=2))
    return Path(path)
```

## LLM prompt template

If you use an LLM coding assistant, the prompt below asks it to build and
validate a recipe with the module above. Save the module as `io_helpers.py`
first, fill in the bracketed values, and paste everything inside the block.
Review the script the assistant writes and the flags it sets — you are still
responsible for the refinement model.

````text
You are helping me build a PowderLine refinement recipe from my own data files
and validate it. PowderLine (https://nsls2.github.io/PowderLine/) reads a
single self-contained JSON recipe (schema 0.26.0) with the diffraction data,
instrument parameters, and crystal structure all embedded; it does not read
CIF, .instprm, or data files itself.

Use the helper module io_helpers.py (in my working directory) for all file
reading and recipe assembly. Read its docstrings first. Call its functions; do
not rewrite the parsing or invent recipe keys beyond the ones it produces and
the background block shown below. Treat
io_helpers.py as guidance, not as an authority: if it disagrees with
powderline.validate or the PowderLine docs, tell me.

My files:
- CIF (one per phase): [PATH TO .cif] (phase name: [NAME])
- Instrument parameters (GSAS-II .instprm): [PATH TO .instprm]
- Diffraction pattern: [PATH TO DATA FILE]
- The pattern's x-axis is: [2theta (degrees) | q (1/Angstrom) | d (Angstrom)]
- What I want to learn / refine: [e.g. lattice parameter and crystallite size]
- Engine I will run: [gsasii (default) | topas | easydiffraction]

What to do:
1. Write a Python script that imports io_helpers as io and powderline, and:
   - structure, cif_warnings = io.read_cif(cif_path, phase_name=...). Print
     every warning. If read_cif raises (no space group, unknown element, missing
     coordinates), stop and ask me; do not patch in a default.
   - phases = io.phase_block(structure); for several CIFs use
     io.merge_phases(io.phase_block(s1), io.phase_block(s2), ...) with a
     distinct phase_name for each.
   - instrument = io.instrument_block(io.read_instprm(path), "<description>",
     refine_profile=...).
   - xrd_data, data_warnings = io.read_pattern(path, x_unit=..., wavelength=...).
     Pass wavelength (the .instprm Lam) when x is q or d. Print every warning,
     especially "check that it is 2theta, not Q or d".
   - A Chebyshev background is written directly (its refine flag is a single
     boolean, not a 4-element list):
     background={"chebyshev": {"num_coefficients": 6,
                               "coefficients": [10, 5, 1, 0, 0, 0],
                               "refine_flag": True}}
   - recipe = io.assemble_recipe(...); io.save_recipe(recipe, "recipe.json").
2. Decide what to refine and set only those refine flags (the second element
   of a [value, refine_flag, min, max] leaf) to True; everything starts False,
   and absent or False means held fixed. Ask me if unsure. A sensible first
   Rietveld pass: the phase scale, a Chebyshev background (4-6 coefficients),
   the lattice parameters allowed by the symmetry, and the instrument profile
   (refine_profile=True). If my instrument parameters come from a separate
   calibrant fit, keep the profile fixed instead; sample size/strain (which
   start at 10 microns and 0, i.e. almost no broadening) can then be refined.
   Do not refine sample broadening on the calibrant itself. Leave atom
   coordinates, occupancies, and displacement parameters fixed unless I ask.
3. Set fit_range=[min_2theta, max_2theta] in degrees of 2theta (Q and d data
   have already been converted; xrd_data["tth"] holds the 2theta values). Do
   not truncate the data arrays yourself.
4. Call powderline.validate(recipe) (it returns the parsed recipe; don't print
   it, as it contains the whole pattern), then
   powderline.run(recipe, "output", engine="<my engine>", validate_only=True).
   Fix anything rejected. Do not run the refinement unless I ask; when I do,
   it is powderline.run(recipe, "output", engine=...). From the shell,
   pixi run kicker recipe.json runs GSAS-II only and pixi run topas-kicker
   recipe.json runs TOPAS; easydiffraction has no shell command.

Rules (schema 0.26.0):
- schema_version must be exactly "0.26.0".
- Every refinable value is a 4-element list [value, refine_flag, min, max];
  value null keeps the starting value. min/max are ignored by GSAS-II and
  TOPAS but used as bounds by easydiffraction; leave them null unless I ask.
- In GSAS-II, symmetry-linked parameters (cubic a=b=c, special-position
  coordinates, anisotropic displacement components) refine together if any one
  of them is flagged, and flags on symmetry-fixed parameters have no effect.
  TOPAS does not enforce this beyond grouping cell lengths: it refines a
  flagged symmetry-fixed angle or site-restricted coordinate/ADP on its own,
  with only a warning. Only flag parameters the symmetry allows to vary.
- Only single-wavelength, constant-wavelength X-ray data (Type PXC) on a 2theta
  axis is supported. Ka1/Ka2 doublets are not; io.instrument_block raises.
- Peak broadening: only the isotropic size (microns) and strain (microstrain,
  (delta d / d) x 10^6, so 1000 means 0.1%) models exist. Keep explicit values; unset values fall back to engine
  defaults that differ between engines.
- The background single-peaks block uses pv_gaussian_sigma (sigma); the
  GSASII_SPF single_peaks block uses pv_gaussian_sigma_sq (sigma squared).
  Misspelled or misplaced keys are silently ignored, not rejected, so
  double-check key names against the docs.
- Simulation mode is refinement_cycles = 1, with every refine flag False.
- GSASII_Rietveld needs phases; GSASII_SPF needs single_peaks, no phases, and
  refinement_controls.single_peak_fitting_mode = {"use_instrument_profile": ...}.
- Engine limits: easydiffraction cannot refine atom parameters, Z, polarization,
  axial divergence, or background peaks, and does not model size/strain or SPF;
  TOPAS does not translate zero shift, axial divergence, or polarization
  refinement. validate_only=True catches what that engine rejects outright,
  but not everything: features an engine ignores (e.g. size/strain in
  easydiffraction) pass with only a warning in the run output, and some
  recipe errors appear only at run time. Tell me about any such limits.

When you are done, report: phase name(s), space group(s) and atom counts; the
instrument Type and Lam; the number of points and the 2theta range; every
warning printed; which flags you set True and why; and the validation results.
````
