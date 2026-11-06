"""Build ``gsasii.rietveld`` simulation recipes from crystal structures.

This module converts crystal structure data (a plain dict: ``space_group``, ``unit_cell``,
``sites`` (every atom of the conventional cell), ``formula``, optional ``material_id``; any source, e.g. a Materials Project fetch, or other
sources) into PowderLine recipes configured for simulation mode
(``refinement_cycles`` 1, every refine flag false). It ships with the GSAS-II
gateway (master plan A43): the simulation runs through GSAS-II, so every
default follows GSAS-II's conventions and units (NOT TOPAS or
easydiffraction, whose instrument terms differ):

- wavelength: Angstroms
- U, V, W: centidegrees^2; X, Y, Z and zero shift: centidegrees; SH/L dimensionless
- isotropic_size: microns
- isotropic_strain: delta-d/d x 10^-6
- LG_eta: Lorentzian/Gaussian mixing (1 = Lorentzian, 0 = Gaussian)
- Uiso: Angstrom^2

The emitted recipe is a gsasii 0.1.0 recipe as the schema reads it (A115):
one phase block per phase (A93), the instrument blocks (A103), the canonical
space-group name (A105), occupancy and scale stated (A96), every default
stated rather than left to the schema (A119), and exact symmetry values
(A120/A121). Symmetry work uses core ``powderline.symmetry`` (gemmi); no
GSAS-II import.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import gemmi
import numpy as np

from powderline._status import WARN
from powderline.exceptions import SymmetryError
from powderline.symmetry import SPECIAL_POSITION_TOL, analyze_site, orbit


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively merge ``override`` into ``base`` (returns a new dict)."""
    merged = dict(base)
    for key, value in override.items():
        if (key in merged and isinstance(merged[key], dict)
                and isinstance(value, dict)):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


# Markers for leaf types in _DEFAULTS_SCHEMA
_NUM = 'number'
_STR = 'string'
_NUM_LIST = 'number list'

# The complete allowed shape of a user-supplied simulation_defaults dict.
# Must mirror _get_hardcoded_defaults and .powderline_config.yaml.example.
_DEFAULTS_SCHEMA: Dict[str, Any] = {
    'instrument_defaults': {
        'wavelength': _NUM,
        'polarization': _NUM,
        'zero_shift': _NUM,
        'axial_divergence': _NUM,
        'broadening': {'U': _NUM, 'V': _NUM, 'W': _NUM,
                       'X': _NUM, 'Y': _NUM, 'Z': _NUM},
    },
    'phase_defaults': {
        'scale': _NUM,
        'Uiso': _NUM,
        'occupancy': _NUM,
        'size_broadening': {'model': _STR, 'isotropic_size': _NUM,
                            'LG_eta': _NUM},
        'strain_broadening': {'model': _STR, 'isotropic_strain': _NUM,
                              'LG_eta': _NUM},
    },
    'data_range': {'min_2theta': _NUM, 'max_2theta': _NUM, 'step': _NUM},
    'background': {'chebyshev_coefficients': _NUM_LIST},
}

_SEE_EXAMPLE = "See .powderline_config.yaml.example for the supported layout."

#: Two positions closer than this (fractional, mod 1) are the same site. Materials
#: Project conventional cells are spglib-idealized, so images agree to ~1e-10.
_SAME_SITE_TOL = 1e-4


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _validate_user_defaults(user: Any,
                            schema: Dict[str, Any] = _DEFAULTS_SCHEMA,
                            path: str = 'simulation_defaults') -> None:
    """Strictly validate a user-supplied simulation_defaults dict.

    Unknown keys at any level and invalid values are rejected with a
    ValueError naming the offending key path, so config mistakes (typos,
    the old flat layout, empty YAML keys that parse as null) fail here with
    a clear message instead of surfacing deep inside GSAS-II.
    """
    if not isinstance(user, dict):
        raise ValueError(
            f"Invalid config: '{path}' must be a mapping of settings, "
            f"got {user!r}. {_SEE_EXAMPLE}"
        )
    for key, value in user.items():
        key_path = f"{path}.{key}"
        if key not in schema:
            raise ValueError(
                f"Invalid config: unknown key '{key_path}'. Allowed keys "
                f"here: {', '.join(schema)}. {_SEE_EXAMPLE}"
            )
        expected = schema[key]
        if isinstance(expected, dict):
            _validate_user_defaults(value, expected, key_path)
        elif expected == _NUM:
            if not _is_number(value):
                hint = (" (an empty YAML key parses as null — set a value "
                        "or remove the key)") if value is None else ""
                raise ValueError(
                    f"Invalid config: '{key_path}' must be a number, "
                    f"got {value!r}{hint}. {_SEE_EXAMPLE}"
                )
        elif expected == _STR:
            if not isinstance(value, str):
                raise ValueError(
                    f"Invalid config: '{key_path}' must be a string, "
                    f"got {value!r}. {_SEE_EXAMPLE}"
                )
        elif expected == _NUM_LIST:
            if (not isinstance(value, list) or not value
                    or not all(_is_number(v) for v in value)):
                raise ValueError(
                    f"Invalid config: '{key_path}' must be a non-empty "
                    f"list of numbers, got {value!r}. {_SEE_EXAMPLE}"
                )


# --- symmetry: the space-group setting and the unique sites ------------------


def space_group_setting(symbol: str) -> tuple[str, Optional[gemmi.Op]]:
    """The canonical gsasii name for a structure source's symbol, and the coordinate change it needs.

    Materials Project (pymatgen ``get_conventional_standard_structure``) writes
    spglib's standard setting: unique axis b / cell choice 1 for monoclinic
    groups, hexagonal axes for rhombohedral groups and **origin choice 1** for
    the 24 groups with two origins (verified on a diamond cell: C at 0,0,0).
    gemmi's lenient lookup picks the same defaults, so the name is its
    ``xhm()`` — except for two-origin groups, which gsasii 0.1.0 refuses in
    origin choice 1 (GSAS-II cannot use it, A105): there the coordinates are
    moved to origin choice 2 with gemmi's change-of-basis operators
    (``basisop`` maps the reference setting onto a setting, so origin 1 ->
    origin 2 is ``basisop_2 . basisop_1^-1``: ``x - 1/8`` for F d -3 m, whose
    origin 2 is 1/8 1/8 1/8 from origin 1) and the returned operation must be
    applied to every site. :func:`unique_sites` then checks the orbits, so a
    wrong setting cannot pass silently.

    Raises:
        ValueError: gemmi does not read the symbol.
    """
    sg = gemmi.find_spacegroup_by_name(symbol.strip())
    if sg is None:
        raise ValueError(f"space group {symbol!r} is not a symbol gemmi reads")
    if sg.ext == '1':
        origin2 = gemmi.find_spacegroup_by_name(f"{sg.hm}:2")
        return origin2.xhm(), origin2.basisop.combine(sg.basisop.inverse())
    return sg.xhm(), None


def _wrap(xyz) -> tuple[float, float, float]:
    out = []
    for v in xyz:
        v = float(v) % 1.0
        if 1.0 - v < _SAME_SITE_TOL:  # 0.99999999 is 0
            v = 0.0
        out.append(v)
    return tuple(out)


def _same_position(a, b) -> bool:
    d = np.abs(np.asarray(a, dtype=float) - np.asarray(b, dtype=float))
    return bool(np.all(np.minimum(d, 1.0 - d) < _SAME_SITE_TOL))


def unique_sites(space_group: str, sites: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Reduce a conventional cell's atom list to one representative per orbit.

    ``sites`` holds every atom of the conventional cell (what
    a structure fetch returns; a co-occupied site is several
    entries with the same coordinates). GSAS-II expands each stated atom by
    the space group itself, so passing the whole cell would count a site
    ``multiplicity`` times over (6x for the boron of LaB6; v0.1.1's
    mp-simulate did). One representative per (element, occupancy, orbit) is
    kept, in input order, with the label of its first member; its coordinates
    are the exact special-position constants where it sits on one (A121).

    The reduction is checked both ways: every input atom must lie on the orbit
    of its representative, and each representative's multiplicity must equal
    the number of input atoms it stands for. A mismatch means the structure
    source and the space-group setting disagree (or the list is not a full
    conventional cell) and is a ``ValueError``, never a silently wrong pattern.

    Raises:
        ValueError: a site near but not on a special position (core A73
            rule, with the schema's message), or an orbit count mismatch.
    """
    kept: List[Dict[str, Any]] = []
    orbits: List[list] = []
    counts: List[int] = []
    for site in sites:
        xyz = _wrap((site['x'], site['y'], site['z']))
        key = (site['element'], site['occupancy'])
        for i, rep in enumerate(kept):
            if (rep['element'], rep['occupancy']) == key and any(_same_position(xyz, img) for img in orbits[i]):
                counts[i] += 1
                break
        else:
            try:
                analysis = analyze_site(space_group, xyz)
            except SymmetryError as exc:
                raise ValueError(f"site {site['label']!r}: {exc}") from exc
            exact = tuple(float(e) if e is not None and abs(float(e) - v) <= SPECIAL_POSITION_TOL else v
                          for e, v in zip(analysis.exact, xyz))
            rep = dict(site, x=exact[0], y=exact[1], z=exact[2])
            kept.append(rep)
            orbits.append(orbit(space_group, exact))
            counts.append(1)
    problems = [f"{rep['label']} ({rep['element']} at {rep['x']}, {rep['y']}, {rep['z']}): {n} atom(s) listed, "
                f"multiplicity {len(images)} in {space_group!r}"
                for rep, images, n in zip(kept, orbits, counts) if n != len(images)]
    if problems:
        raise ValueError(
            "the structure's atom list does not match its space group (is it the full conventional cell in the "
            "stated setting?): " + "; ".join(problems))
    return kept


class SimulationRecipeBuilder:
    """Builder for ``gsasii.rietveld`` simulation recipes (GSAS-II conventions)."""

    def __init__(self, simulation_defaults: Optional[Dict[str, Any]] = None):
        """Initialize recipe builder.

        Args:
            simulation_defaults: Dictionary with default simulation parameters
                               (instrument_defaults, phase_defaults, data_range,
                               background). Partial dicts are allowed — missing
                               keys fall back to the hardcoded defaults.
                               Validation is strict: unknown keys (including
                               the retired flat layout) and invalid values
                               raise ValueError naming the offending key.

        Raises:
            ValueError: If simulation_defaults contains unknown keys or
                invalid values.
        """
        user_defaults = simulation_defaults or {}
        _validate_user_defaults(user_defaults)
        self.defaults = _deep_merge(self._get_hardcoded_defaults(), user_defaults)

    def _get_hardcoded_defaults(self) -> Dict[str, Any]:
        """Fallback defaults if no config provided (GSAS-II units)."""
        return {
            'instrument_defaults': {
                'wavelength': 0.4133,      # Angstroms (30 keV)
                'polarization': 0.99,      # GSAS-II 'Polariz.'
                'zero_shift': 0.0,         # degrees 2theta ('Zero')
                'axial_divergence': 0.002, # GSAS-II 'SH/L': its own floor (A91; P-05)
                # TCH pseudo-Voigt instrumental broadening (GSAS-II U,V,W,X,Y,Z)
                'broadening': {'U': 1.0, 'V': -0.5, 'W': 0.1,
                               'X': 0.0, 'Y': 0.0, 'Z': 0.0},
            },
            'phase_defaults': {
                'scale': 1.0,
                # Structural fallbacks — applied ONLY when the structure source
                # does not provide a value (a warning is emitted per phase)
                'Uiso': 0.01,       # Angstrom^2
                'occupancy': 1.0,
                'size_broadening': {
                    'model': 'isotropic',
                    'isotropic_size': 10.0,  # microns (~no size broadening)
                    'LG_eta': 1.0,           # 1 = Lorentzian, 0 = Gaussian
                },
                'strain_broadening': {
                    'model': 'isotropic',
                    'isotropic_strain': 0.0,  # delta-d/d x 10^-6
                    'LG_eta': 1.0,
                },
            },
            'data_range': {'min_2theta': 1.0, 'max_2theta': 80.0, 'step': 0.05},
            'background': {'chebyshev_coefficients': [10.0, 0.0, 0.0]},
        }

    def _generate_dummy_xrd_data(self) -> Dict[str, Any]:
        """Generate dummy XRD data arrays for simulation.

        GSAS-II requires observed data arrays even in simulation mode.
        We generate a uniform grid with dummy intensities.

        Raises:
            ValueError: If data_range parameters are invalid
        """
        data_range = self.defaults['data_range']

        # Validate data range parameters
        min_2theta = data_range['min_2theta']
        max_2theta = data_range['max_2theta']
        step = data_range['step']

        if min_2theta >= max_2theta:
            raise ValueError(f"min_2theta ({min_2theta}) must be < max_2theta ({max_2theta})")

        if step <= 0:
            raise ValueError(f"step ({step}) must be > 0")

        # Check for excessive number of points (>50k could cause memory issues)
        num_steps = int(round((max_2theta - min_2theta) / step))
        if num_steps + 1 > 50000:
            raise ValueError(
                f"Data range would generate {num_steps + 1} points (>50k limit). "
                f"Increase step size (currently {step}°) or reduce 2θ range."
            )

        # min_2theta .. max_2theta inclusive, so the recipe's fit_range [min, max]
        # is exactly the data's window (the core fit-window rule, A149, refuses
        # a limit outside the data; np.arange would stop one step short of max)
        tth = np.linspace(min_2theta, min_2theta + num_steps * step, num_steps + 1).tolist()

        # Dummy intensities (will be ignored, y_calc is what matters)
        Itth = [1.0] * len(tth)

        # Uniform weights
        Itth_weights = [1.0] * len(tth)

        return {
            'tth': tth,
            'Itth': Itth,
            'Itth_weights': Itth_weights,
            'filename': 'simulation_dummy_data'
        }

    def _build_instrument(self) -> Dict[str, Any]:
        """The gsasii 0.1.0 instrument block (A103), every term stated and fixed."""
        inst = self.defaults['instrument_defaults']
        wavelength = inst['wavelength']
        broadening = inst['broadening']
        energy_kev = 12.398 / wavelength
        return {
            'description': f'Simulated synchrotron (λ={wavelength:.4f} Å, ~{energy_kev:.0f} keV)',
            'radiation': {'type': 'PXC', 'wavelength': [wavelength, False]},
            'geometry': {'bank': 1, 'azimuth': 0.0},
            'corrections': {
                'zero_shift': [inst['zero_shift'], False],
                'polarization': [inst['polarization'], False],
                'axial_divergence': [inst['axial_divergence'], False],
            },
            'broadening': {key: [broadening[key], False] for key in ('U', 'V', 'W', 'X', 'Y', 'Z')},
        }

    def _build_phase_from_structure(self, structure_data: Dict[str, Any], phase_name: str) -> Dict[str, Any]:
        """Build the gsasii phase block (A93) from structure data.

        Reads the structure dict directly (no CIF parsing). Structural fallbacks (Uiso, occupancy) are applied ONLY to
        sites that do not provide a value, with a warning naming the affected
        atoms (every atom of the input list, before the reduction to unique
        sites). The space group is written in its canonical setting
        (:func:`space_group_setting`) and the atom list reduced to one
        representative per orbit (:func:`unique_sites`).
        """
        if not structure_data.get('unit_cell') or not structure_data.get('space_group') or not structure_data.get('sites'):
            raise ValueError(
                "Structure data missing required fields. "
                "Ensure unit_cell, space_group, and sites are present."
            )

        phase_defaults = self.defaults['phase_defaults']
        default_uiso = phase_defaults['Uiso']
        default_occupancy = phase_defaults['occupancy']

        space_group, to_origin_2 = space_group_setting(structure_data['space_group'])
        if to_origin_2 is not None:
            print(f"{WARN}  Phase '{phase_name}': space group {structure_data['space_group']!r} stated in "
                  f"origin choice 1 (spglib's standard setting), which GSAS-II cannot use; the coordinates are "
                  f"moved to origin choice 2 ({to_origin_2.triplet()}) and the phase written as {space_group!r}.")

        sites = []
        missing_uiso = []
        missing_occupancy = []
        for site in structure_data['sites']:
            label = site['label']
            # A key that is absent OR explicitly None both count as missing
            uiso = site.get('Uiso')
            occupancy = site.get('occupancy')
            if uiso is None:
                missing_uiso.append(label)
                uiso = default_uiso
            if occupancy is None:
                missing_occupancy.append(label)
                occupancy = default_occupancy
            xyz = (site['x'], site['y'], site['z'])
            if to_origin_2 is not None:
                xyz = to_origin_2.apply_to_xyz(list(xyz))
            sites.append({'element': site['element'], 'label': label, 'occupancy': float(occupancy),
                          'Uiso': float(uiso), 'x': xyz[0], 'y': xyz[1], 'z': xyz[2]})

        if missing_uiso:
            print(f"{WARN}  Phase '{phase_name}': no Uiso in structure source for "
                  f"{len(missing_uiso)} atom(s) ({', '.join(missing_uiso)}); "
                  f"default {default_uiso} Å² applied.")
        if missing_occupancy:
            print(f"{WARN}  Phase '{phase_name}': no occupancy in structure source "
                  f"for {len(missing_occupancy)} atom(s) "
                  f"({', '.join(missing_occupancy)}); "
                  f"default {default_occupancy} applied.")

        atoms = {}
        for site in unique_sites(space_group, sites):
            atoms[site['label']] = {
                'element': site['element'],
                'x': [site['x'], False],
                'y': [site['y'], False],
                'z': [site['z'], False],
                'occupancy': [site['occupancy'], False],
                'ADP': 'Uiso',
                'Uiso': [site['Uiso'], False],
            }

        cell = structure_data['unit_cell']
        size_defaults = phase_defaults['size_broadening']
        strain_defaults = phase_defaults['strain_broadening']
        return {
            'space_group': space_group,
            'unit_cell': {key: [float(cell[key]), False] for key in ('a', 'b', 'c', 'alpha', 'beta', 'gamma')},
            'atoms': atoms,
            'scale': [phase_defaults['scale'], False],  # Locked
            'peak_broadening': {
                'size_broadening': {
                    'model': size_defaults['model'],
                    'isotropic_size': [size_defaults['isotropic_size'], False],
                    'LG_eta': [size_defaults['LG_eta'], False],
                },
                'strain_broadening': {
                    'model': strain_defaults['model'],
                    'isotropic_strain': [strain_defaults['isotropic_strain'], False],
                    'LG_eta': [strain_defaults['LG_eta'], False],
                },
            },
        }

    def build_recipe_from_structure(
        self,
        structure_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Build a complete ``gsasii.rietveld`` simulation recipe from a structure dict.

        Args:
            structure_data: Structure data (see the module docstring for the keys)

        Returns:
            Complete PowderLine recipe dictionary (``gsasii.rietveld``, core
            and engine schema 0.1.0) that validates as written (A115).

        Note:
            Sample identity (name, description) is managed externally by the
            caller (e.g. via directory names or a database).
        """
        formula = structure_data['formula']
        phase_name = formula

        return {
            'schema_name': 'gsasii.rietveld',
            'core_schema_version': '0.1.0',
            'engine_schema_version': '0.1.0',
            'payload': {
                # Dummy XRD data (required for GSAS-II, but not used in simulation)
                'xrd_data': self._generate_dummy_xrd_data(),

                # Instrument configuration (every term stated and fixed)
                'instrument': self._build_instrument(),

                # Fit range covers full generated data range
                'fit_range': [
                    self.defaults['data_range']['min_2theta'],
                    self.defaults['data_range']['max_2theta']
                ],

                # Background (flat, locked for simulation)
                'background': {
                    'chebyshev': {
                        'num_coefficients': len(self.defaults['background']['chebyshev_coefficients']),
                        'coefficients': self.defaults['background']['chebyshev_coefficients'],
                        'refine_flag': False  # CRITICAL: locked for simulation
                    },
                },

                # Phase definition (one block: structure, scale, broadening)
                'phases': {
                    phase_name: self._build_phase_from_structure(structure_data, phase_name),
                },

                # Simulation mode: 1 cycle, no refinement
                'refinement_controls': {
                    'refinement_cycles': 1
                },
            },
            'metadata': {
                'materials_project': {
                    'material_id': structure_data.get('material_id'),
                    'formula': formula,
                    'space_group_as_stated': structure_data['space_group'],
                },
            },
        }
