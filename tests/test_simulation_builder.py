"""Tests for the SimulationRecipeBuilder (structure dict -> gsasii.rietveld simulation recipe).

Covers the emitted ``gsasii.rietveld`` 0.1.0 shape (A93 phase block, A103
instrument blocks, A105 canonical space group, A96/A119 everything stated,
A120/A121 exact symmetry values; validates as written with no warnings,
A115), config handling (instrument_defaults/phase_defaults flow-through,
partial-config deep merge, strict validation of unknown keys and invalid
values), simulation-mode invariants (all refine flags locked), structural
fallbacks (Uiso/occupancy defaults + warnings, occupancy passthrough), the
reduction of the conventional cell to symmetry-unique sites and the
origin-choice handling for two-origin groups. GSASClient behavior lives in
test_gsas_client_visibility.py. Unit tests need no GSAS-II; the end-to-end
test (build recipe → run simulation → check output files) is
``test_simulation_builder_gsasii.py`` (re/09 split).
"""

import pytest

import powderline
from powderline.gateways.gsasii.simulation_builder import (

    SimulationRecipeBuilder,
    space_group_setting,
    unique_sites,
)
from powderline.gateways.gsasii.schema import GsasiiRietveldRecipe
from powderline.symmetry import orbit

pytestmark = pytest.mark.core


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _collect_refine_flags(obj, path=""):
    """Recursively collect all [value, refine_flag] list refine_flags.

    Returns a list of (dotted_path, refine_flag) tuples for every list that
    looks like a refinable parameter (len >= 2, second element is bool).
    """
    results = []
    if isinstance(obj, list) and len(obj) >= 2 and isinstance(obj[1], bool):
        results.append((path, obj[1]))
    elif isinstance(obj, dict):
        for k, v in obj.items():
            results.extend(_collect_refine_flags(v, f"{path}.{k}" if path else k))
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            results.extend(_collect_refine_flags(item, f"{path}[{i}]"))
    return results


def _validate(recipe):
    """The recipe through the public validate(): the gateway's model and its structured warnings."""
    result = powderline.validate(recipe)
    assert isinstance(result.recipe, GsasiiRietveldRecipe)
    return result


def _diamond_origin_1():
    """A diamond conventional cell as spglib standardizes it: F d -3 m in origin choice 1 (C at 0,0,0)."""
    positions = [(0, 0, 0), (0, .5, .5), (.5, 0, .5), (.5, .5, 0),
                 (.25, .25, .25), (.25, .75, .75), (.75, .25, .75), (.75, .75, .25)]
    return {
        'material_id': 'mp-66', 'cif': '', 'formula': 'C', 'space_group': 'Fd-3m',
        'unit_cell': {'a': 3.567, 'b': 3.567, 'c': 3.567, 'alpha': 90.0, 'beta': 90.0, 'gamma': 90.0,
                      'volume': 3.567 ** 3},
        'sites': [{'element': 'C', 'x': x, 'y': y, 'z': z, 'occupancy': 1.0, 'label': f'C{i + 1}'}
                  for i, (x, y, z) in enumerate(positions)],
        'is_ordered': True, 'metadata': {},
    }


# ─── The emitted shape (gsasii 0.1.0) ────────────────────────────────────────

def test_builder_recipe_passes_schema_validation(lab6_structure_data):
    """Builder output validates as written (A115) with no structured warning: every default is stated.

    This is the primary regression guard — it would have caught every known
    breakage introduced between schema 0.21 and 0.26, and now the 0.1.0 rules.
    """
    recipe = SimulationRecipeBuilder().build_recipe_from_structure(lab6_structure_data)
    result = _validate(recipe)
    assert result.recipe.schema_name == "gsasii.rietveld"
    assert result.warnings == []


def test_builder_recipe_top_level_fields(lab6_structure_data):
    """Top level: schema_name and the two 0.1.0 versions, payload, metadata; no 0.26.0 keys."""
    recipe = SimulationRecipeBuilder().build_recipe_from_structure(lab6_structure_data)

    assert recipe["schema_name"] == "gsasii.rietveld"
    assert recipe["core_schema_version"] == "0.1.0"
    assert recipe["engine_schema_version"] == "0.1.0"
    assert "payload" in recipe
    assert recipe["metadata"]["materials_project"] == {
        "material_id": "mp-2680", "formula": "LaB6", "space_group_as_stated": "Pm-3m"}

    for removed in ("schema_version", "sample_name", "recipe_description", "comment"):
        assert removed not in recipe


def test_builder_payload_blocks(lab6_structure_data):
    """The payload is the 0.1.0 layout: instrument blocks (A103), background, one phase block (A93), controls."""
    recipe = SimulationRecipeBuilder().build_recipe_from_structure(lab6_structure_data)
    payload = recipe["payload"]
    assert set(payload) == {"xrd_data", "instrument", "fit_range", "background", "phases", "refinement_controls"}
    assert "refinement_cycles" not in recipe
    assert payload["refinement_controls"] == {"refinement_cycles": 1}

    inst = payload["instrument"]
    assert set(inst) == {"description", "radiation", "geometry", "corrections", "broadening"}
    assert inst["radiation"] == {"type": "PXC", "wavelength": [0.4133, False]}
    assert inst["geometry"] == {"bank": 1, "azimuth": 0.0}
    assert inst["corrections"] == {"zero_shift": [0.0, False], "polarization": [0.99, False],
                                   "axial_divergence": [0.002, False]}  # SH/L at GSAS-II's floor (P-05)
    assert set(inst["broadening"]) == set("UVWXYZ") and inst["broadening"]["U"] == [1.0, False]
    assert "initialization" not in inst and "parameterization" not in inst

    assert payload["background"] == {"chebyshev": {"num_coefficients": 3, "coefficients": [10.0, 0.0, 0.0],
                                                   "refine_flag": False}}

    phase = payload["phases"]["LaB6"]
    assert set(phase) == {"space_group", "unit_cell", "atoms", "scale", "peak_broadening"}
    assert "structure" not in phase and "parameterization" not in phase
    assert phase["space_group"] == "P m -3 m"  # canonical gemmi name (A105), from MP's 'Pm-3m'
    assert phase["unit_cell"]["a"] == [4.15682, False] and phase["unit_cell"]["gamma"] == [90.0, False]
    assert "volume" not in phase["unit_cell"]
    assert phase["scale"] == [1.0, False]  # stated (A96)


def test_builder_atoms_are_unique_sites_with_stated_values(lab6_structure_data):
    """The 7-atom conventional cell becomes 2 sites (1a La, 6f B); occupancy and Uiso stated; no Multiplicity."""
    recipe = SimulationRecipeBuilder().build_recipe_from_structure(lab6_structure_data)
    atoms = recipe["payload"]["phases"]["LaB6"]["atoms"]
    assert list(atoms) == ["La1", "B1"]
    assert atoms["La1"] == {"element": "La", "x": [0.0, False], "y": [0.0, False], "z": [0.0, False],
                            "occupancy": [1.0, False], "ADP": "Uiso", "Uiso": [0.01, False]}
    assert atoms["B1"] == {"element": "B", "x": [0.5, False], "y": [0.5, False], "z": [0.2021, False],
                           "occupancy": [1.0, False], "ADP": "Uiso", "Uiso": [0.01, False]}


def test_builder_peak_broadening_field_names(lab6_structure_data):
    """size_broadening / strain_broadening carry model, isotropic_size / isotropic_strain and LG_eta, all stated."""
    recipe = SimulationRecipeBuilder().build_recipe_from_structure(lab6_structure_data)
    pb = recipe["payload"]["phases"]["LaB6"]["peak_broadening"]
    assert pb == {
        "size_broadening": {"model": "isotropic", "isotropic_size": [10.0, False], "LG_eta": [1.0, False]},
        "strain_broadening": {"model": "isotropic", "isotropic_strain": [0.0, False], "LG_eta": [1.0, False]},
    }


def test_builder_all_refine_flags_false(lab6_structure_data):
    """All refine flags must be False in simulation mode.

    Simulation (refinement_cycles=1) is a pure forward calculation; the gsasii
    schema rejects any refine flag in it (A88), so this is also what makes the
    recipe validate.
    """
    recipe = SimulationRecipeBuilder().build_recipe_from_structure(lab6_structure_data)

    flags = _collect_refine_flags(recipe["payload"])
    assert len(flags) >= 25, "No refinable parameters found — helper or recipe structure may be wrong"

    true_flags = [(path, flag) for path, flag in flags if flag is True]
    assert not true_flags, (
        f"Found {len(true_flags)} refine_flag(s) set to True in simulation recipe "
        f"(all must be False):\n" +
        "\n".join(f"  {p}" for p, _ in true_flags)
    )


# ─── Configuration flow-through ─────────────────────────────────────────────

def test_builder_custom_wavelength(lab6_structure_data):
    """Custom wavelength in defaults must land in instrument.radiation.wavelength (and the description)."""
    builder = SimulationRecipeBuilder(simulation_defaults={"instrument_defaults": {"wavelength": 0.7}})
    recipe = builder.build_recipe_from_structure(lab6_structure_data)

    inst = recipe["payload"]["instrument"]
    assert inst["radiation"]["wavelength"] == [0.7, False]
    assert "0.7000" in inst["description"]
    _validate(recipe)


def test_builder_phase_defaults_flow_into_recipe(lab6_structure_data):
    """Configured phase_defaults (scale, models, LG_eta, size/strain) must land
    in the phase block, and instrument_defaults.polarization in corrections."""
    defaults = {
        "instrument_defaults": {"polarization": 0.95, "axial_divergence": 0.01},
        "phase_defaults": {
            "scale": 2.0,
            "Uiso": 0.02,
            "size_broadening": {"isotropic_size": 0.5, "LG_eta": 0.3},
            "strain_broadening": {"isotropic_strain": 1500.0, "LG_eta": 0.7},
        },
    }
    recipe = SimulationRecipeBuilder(simulation_defaults=defaults).build_recipe_from_structure(lab6_structure_data)

    phase = recipe["payload"]["phases"]["LaB6"]
    assert phase["scale"] == [2.0, False]
    pb = phase["peak_broadening"]
    assert pb["size_broadening"] == {"model": "isotropic", "isotropic_size": [0.5, False], "LG_eta": [0.3, False]}
    assert pb["strain_broadening"] == {"model": "isotropic", "isotropic_strain": [1500.0, False],
                                       "LG_eta": [0.7, False]}

    corrections = recipe["payload"]["instrument"]["corrections"]
    assert corrections["polarization"] == [0.95, False]
    assert corrections["axial_divergence"] == [0.01, False]

    # Uiso fallback (MP provides none) comes from phase_defaults
    assert all(atom["Uiso"] == [0.02, False] for atom in phase["atoms"].values())

    assert _validate(recipe).warnings == []


def test_builder_partial_config_merges_with_hardcoded_defaults(lab6_structure_data):
    """A partial simulation_defaults dict must be deep-merged over the
    hardcoded defaults, not replace them."""
    builder = SimulationRecipeBuilder(
        simulation_defaults={"instrument_defaults": {"wavelength": 0.1665}})

    assert builder.defaults["instrument_defaults"]["wavelength"] == 0.1665
    # Untouched siblings and sections survive the merge
    assert builder.defaults["instrument_defaults"]["polarization"] == 0.99
    assert builder.defaults["instrument_defaults"]["axial_divergence"] == 0.002
    assert builder.defaults["phase_defaults"]["size_broadening"]["isotropic_size"] == 10.0
    assert "data_range" in builder.defaults

    _validate(builder.build_recipe_from_structure(lab6_structure_data))


def test_builder_sh_l_below_the_floor_is_the_schemas_error(lab6_structure_data):
    """The builder states what it is given; a config SH/L below 0.002 is refused by the schema (A91), not fixed."""
    from pydantic import ValidationError

    builder = SimulationRecipeBuilder(simulation_defaults={"instrument_defaults": {"axial_divergence": 0.001}})
    recipe = builder.build_recipe_from_structure(lab6_structure_data)
    with pytest.raises(ValidationError, match="axial_divergence"):
        powderline.validate(recipe)


def test_builder_rejects_unknown_top_level_key():
    """Unknown top-level keys — including the retired flat layout — must be
    rejected with an error naming the key and the allowed alternatives."""
    with pytest.raises(ValueError, match=r"simulation_defaults\.sample") as excinfo:
        SimulationRecipeBuilder(simulation_defaults={
            "sample": {"crystallite_size": 5.0},
        })
    msg = str(excinfo.value)
    assert "instrument_defaults" in msg  # allowed keys are listed
    assert ".powderline_config.yaml.example" in msg


def test_builder_rejects_unknown_nested_key():
    """Typos inside a section must be rejected with the full key path."""
    with pytest.raises(ValueError,
                       match=r"instrument_defaults\.wavelenght"):
        SimulationRecipeBuilder(simulation_defaults={
            "instrument_defaults": {"wavelenght": 0.7},  # typo
        })


def test_builder_rejects_null_value_from_empty_yaml_key():
    """An empty YAML key parses as None; it must be rejected with the key
    path and a hint, not silently override a built-in default."""
    with pytest.raises(ValueError,
                       match=r"instrument_defaults\.polarization") as excinfo:
        SimulationRecipeBuilder(simulation_defaults={
            "instrument_defaults": {"polarization": None},
        })
    assert "empty YAML key" in str(excinfo.value)


def test_builder_rejects_non_numeric_value():
    with pytest.raises(ValueError,
                       match=r"phase_defaults\.size_broadening\.isotropic_size"):
        SimulationRecipeBuilder(simulation_defaults={
            "phase_defaults": {"size_broadening": {"isotropic_size": "big"}},
        })


def test_builder_rejects_bad_chebyshev_coefficients():
    with pytest.raises(ValueError,
                       match=r"background\.chebyshev_coefficients"):
        SimulationRecipeBuilder(simulation_defaults={
            "background": {"chebyshev_coefficients": [10.0, None]},
        })


# ─── Structural fallbacks and the unique-site reduction ─────────────────────

def test_builder_warns_on_missing_structural_values(lab6_structure_data, capsys):
    """Missing Uiso (always, for MP data) and missing occupancy must trigger
    a warning naming the affected input atoms; provided values must not.

    Both 'missing' shapes are covered: key absent entirely and key present
    with an explicit None — each must receive the default value (never pass
    None through into the recipe). The warning names the input atoms (B3,
    B5), before the reduction to unique sites merges them into B1's orbit."""
    data = lab6_structure_data
    data["sites"][3]["occupancy"] = None  # B3: present-but-None counts as missing
    del data["sites"][5]["occupancy"]     # B5: key absent entirely

    recipe = SimulationRecipeBuilder().build_recipe_from_structure(data)
    out = capsys.readouterr().out

    assert "no Uiso in structure source" in out
    assert "La1" in out and "B1" in out
    assert "no occupancy in structure source" in out
    # Only B3 (explicit None) and B5 (key absent) are missing occupancy —
    # the warning must not list La1 or B1 for it
    occ_line = next(line for line in out.splitlines() if "no occupancy" in line)
    assert "B3" in occ_line and "B5" in occ_line and "La1" not in occ_line and "B1" not in occ_line

    atoms = recipe["payload"]["phases"][data["formula"]]["atoms"]
    assert list(atoms) == ["La1", "B1"]  # the defaulted B3/B5 are the same site as B1 again
    assert atoms["La1"]["occupancy"] == [1.0, False]  # provided by fixture
    assert atoms["B1"]["occupancy"] == [1.0, False]
    _validate(recipe)


def test_builder_occupancy_passthrough(lab6_structure_data):
    """Partial occupancies from MP sites must be carried into recipe atoms; a
    co-occupied site is two atoms (distinct labels) at the same coordinates."""
    data = lab6_structure_data
    data["sites"][0:1] = [
        {'element': 'La', 'x': 0.0, 'y': 0.0, 'z': 0.0, 'occupancy': 0.5, 'label': 'La1'},
        {'element': 'Ce', 'x': 0.0, 'y': 0.0, 'z': 0.0, 'occupancy': 0.5, 'label': 'Ce1'},
    ]
    data["is_ordered"] = False

    recipe = SimulationRecipeBuilder().build_recipe_from_structure(data)

    atoms = recipe["payload"]["phases"][data["formula"]]["atoms"]
    assert list(atoms) == ["La1", "Ce1", "B1"]
    assert atoms["La1"]["occupancy"] == [0.5, False]
    assert atoms["Ce1"]["occupancy"] == [0.5, False]
    assert atoms["B1"]["occupancy"] == [1.0, False]
    assert atoms["La1"]["x"] == atoms["Ce1"]["x"]

    # Recipe with fractional occupancies must still validate
    _validate(recipe)


def test_builder_valid_config_does_not_mutate_input(lab6_structure_data):
    """The builder must not modify the caller's simulation_defaults dict
    (it may be a live reference into ConfigLoader.config)."""
    import copy
    defaults = {
        "instrument_defaults": {"wavelength": 0.1665},
        "phase_defaults": {"size_broadening": {"isotropic_size": 2.0}},
    }
    snapshot = copy.deepcopy(defaults)
    builder = SimulationRecipeBuilder(simulation_defaults=defaults)
    builder.build_recipe_from_structure(lab6_structure_data)
    assert defaults == snapshot


def test_unique_sites_snaps_to_exact_special_positions():
    """A representative on a special position is written with the exact constants (A121)."""
    sites = [{'element': 'C', 'x': x, 'y': y, 'z': z, 'occupancy': 1.0, 'label': f'C{i + 1}'}
             for i, (x, y, z) in enumerate([(0, 0, .25), (0, 0, .75), (0.33333333, 0.66666667, .25),
                                            (0.66666667, 0.33333333, .75)])]
    kept = unique_sites("P 63/m m c", sites)
    assert [(s['label'], s['x'], s['y'], s['z']) for s in kept] == [("C1", 0.0, 0.0, 0.25), ("C3", 1 / 3, 2 / 3, 0.25)]


def test_unique_sites_refuses_an_incomplete_cell():
    """Only one of the six boron atoms listed: the orbit count check stops instead of guessing."""
    sites = [{'element': 'La', 'x': 0.0, 'y': 0.0, 'z': 0.0, 'occupancy': 1.0, 'label': 'La1'},
             {'element': 'B', 'x': 0.5, 'y': 0.5, 'z': 0.2021, 'occupancy': 1.0, 'label': 'B1'}]
    with pytest.raises(ValueError, match=r"B1 \(B at 0.5, 0.5, 0.2021\): 1 atom\(s\) listed, multiplicity 6"):
        unique_sites("P m -3 m", sites)


def test_unique_sites_near_special_position_is_the_core_error():
    """A coordinate near but not on a special position is the core A73 refusal, naming the site."""
    sites = [{'element': 'C', 'x': 0.3333, 'y': 0.6667, 'z': 0.25, 'occupancy': 1.0, 'label': 'C1'},
             {'element': 'C', 'x': 0.6667, 'y': 0.3333, 'z': 0.75, 'occupancy': 1.0, 'label': 'C2'}]
    with pytest.raises(ValueError, match="site 'C1'.*without being on it"):
        unique_sites("P 63/m m c", sites)


# ─── Space-group settings ───────────────────────────────────────────────────

@pytest.mark.parametrize("stated, canonical", [
    ("Pm-3m", "P m -3 m"), ("P6_3/mmc".replace("_", ""), "P 63/m m c"), ("C2/m", "C 1 2/m 1"),
    ("R-3m", "R -3 m:H"), ("I4/mmm", "I 4/m m m"),
])
def test_space_group_setting_single_setting_groups(stated, canonical):
    """spglib's standard setting is gemmi's default reading: canonical name, no coordinate change."""
    assert space_group_setting(stated) == (canonical, None)


def test_space_group_setting_two_origin_group_moves_to_origin_2():
    name, op = space_group_setting("Fd-3m")
    assert name == "F d -3 m:2"
    assert op.triplet() == "x-1/8,y-1/8,z-1/8"
    # origin-1 8a (0,0,0 and 3/4,1/4,3/4 + F) lands on origin-2 8a (1/8,1/8,1/8 and 7/8,3/8,3/8 + F)
    images = orbit("F d -3 m:2", (0.125, 0.125, 0.125))
    for point in [(0, 0, 0), (0.75, 0.25, 0.75), (0.25, 0.25, 0.25)]:
        moved = tuple(round(v % 1.0, 6) for v in op.apply_to_xyz(list(point)))
        assert any(all(abs(a - b) < 1e-9 for a, b in zip(moved, img)) for img in images), (point, moved)


def test_space_group_setting_unknown_symbol():
    with pytest.raises(ValueError, match="not a symbol gemmi reads"):
        space_group_setting("Xyz")


def test_builder_two_origin_group_written_in_origin_2(capsys):
    """Diamond as spglib standardizes it (origin 1, C at 0,0,0) becomes F d -3 m:2 with C on 8a (1/8,1/8,1/8)."""
    recipe = SimulationRecipeBuilder().build_recipe_from_structure(_diamond_origin_1())
    out = capsys.readouterr().out
    assert "origin choice 1" in out and "x-1/8,y-1/8,z-1/8" in out

    phase = recipe["payload"]["phases"]["C"]
    assert phase["space_group"] == "F d -3 m:2"
    assert list(phase["atoms"]) == ["C1"]  # the first input atom (0,0,0) -> 7/8,7/8,7/8, an 8a position
    assert (phase["atoms"]["C1"]["x"], phase["atoms"]["C1"]["y"], phase["atoms"]["C1"]["z"]) == \
        ([0.875, False], [0.875, False], [0.875, False])
    assert len(orbit("F d -3 m:2", (0.875, 0.875, 0.875))) == 8  # the eight input atoms, one site
    assert any(all(abs(a - b) < 1e-9 for a, b in zip(img, (0.125, 0.125, 0.125)))
               for img in orbit("F d -3 m:2", (0.875, 0.875, 0.875)))
    assert _validate(recipe).warnings == []
