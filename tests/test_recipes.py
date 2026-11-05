"""load_recipe_asset: encodings, document shape, error messages (review items 28, 11)."""
import json
import pytest

from powderline.recipes import load_recipe_asset

pytestmark = pytest.mark.core

RECIPE = {"schema_name": "gsasii.rietveld", "payload": {"note": "λ = 0.1665 Å"}}


def test_json_utf8_non_ascii_round_trips(tmp_path):
    p = tmp_path / "r.json"
    p.write_text(json.dumps(RECIPE, ensure_ascii=False), encoding="utf-8")
    assert load_recipe_asset(p) == RECIPE


def test_json_with_utf8_bom_loads(tmp_path):
    p = tmp_path / "r.json"
    p.write_bytes(b"\xef\xbb\xbf" + json.dumps(RECIPE, ensure_ascii=False).encode("utf-8"))
    assert load_recipe_asset(p) == RECIPE


def test_yaml_mapping_loads_and_txt_is_yaml(tmp_path):
    p = tmp_path / "r.txt"
    p.write_text("schema_name: gsasii.rietveld\npayload: {}\n", encoding="utf-8")
    assert load_recipe_asset(p) == {"schema_name": "gsasii.rietveld", "payload": {}}


def test_empty_yaml_is_empty_dict(tmp_path):
    p = tmp_path / "r.yaml"
    p.write_text("", encoding="utf-8")
    assert load_recipe_asset(p) == {}


def test_yaml_list_top_level_is_a_value_error_naming_the_file(tmp_path):
    p = tmp_path / "r.yaml"
    p.write_text("- a\n- b\n", encoding="utf-8")
    with pytest.raises(ValueError, match=r"r\.yaml.*mapping"):
        load_recipe_asset(p)


def test_malformed_json_is_a_value_error_naming_the_file(tmp_path):
    p = tmp_path / "r.json"
    p.write_text('{"schema_name": "gsasii.rietveld",}', encoding="utf-8")
    with pytest.raises(ValueError, match=r"r\.json.*not valid JSON"):
        load_recipe_asset(p)


def test_malformed_yaml_is_a_value_error_naming_the_file(tmp_path):
    p = tmp_path / "r.yaml"
    p.write_text("schema_name: [unclosed\n", encoding="utf-8")
    with pytest.raises(ValueError, match=r"r\.yaml.*not valid YAML"):
        load_recipe_asset(p)


def test_unsupported_suffix(tmp_path):
    p = tmp_path / "r.toml"
    p.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="Unsupported recipe format"):
        load_recipe_asset(p)


def test_client_normalize_recipe_uses_the_loader(tmp_path):
    from powderline.gateways.gsasii.client import GSASClient
    p = tmp_path / "r.json"
    p.write_text(json.dumps(RECIPE, ensure_ascii=False), encoding="utf-8")
    assert GSASClient._normalize_recipe(p) == RECIPE
    bad = tmp_path / "bad.json"
    bad.write_text("{", encoding="utf-8")
    with pytest.raises(ValueError, match="not valid JSON"):
        GSASClient._normalize_recipe(bad)


# --- re/20a (KI-04, P-43 D4): core blocks are the chaining currency ------------------------------------------

def _two_recipes():
    import json
    from pathlib import Path
    root = Path(__file__).resolve().parents[1] / "examples"
    a = json.loads((root / "example_LaB6" / "input.json").read_text(encoding="utf-8-sig"))
    b = json.loads((root / "example_LaB6" / "topas" / "input.json").read_text(encoding="utf-8-sig"))
    return a, b


def test_block_and_with_block_move_core_blocks_between_engines():
    from powderline import validate
    from powderline.recipes import block, with_block
    gsasii, topas = _two_recipes()
    data = block(gsasii, "payload.xrd_data")
    assert data is not gsasii["payload"]["xrd_data"] and data == gsasii["payload"]["xrd_data"]
    grafted = with_block(topas, "payload.xrd_data", data)
    assert grafted["payload"]["xrd_data"] == data and topas["payload"]["xrd_data"] is not data  # a copy, not an alias
    validate(grafted)  # the target recipe's own validation is the gate


def test_with_block_refuses_engine_blocks():
    from powderline.recipes import with_block
    gsasii, topas = _two_recipes()
    with pytest.raises(ValueError, match="not a core block"):
        with_block(topas, "payload.instrument", gsasii["payload"]["instrument"])
    with pytest.raises(ValueError, match="not a core block"):
        with_block(topas, "payload.refinement_controls", {})


def test_phase_block_is_a_core_block():
    from powderline.recipes import block, with_block
    gsasii, topas = _two_recipes()
    phase = block(gsasii, "payload.phases.LaB6")
    out = with_block(topas, "payload.phases.LaB6_copy", phase)
    assert out["payload"]["phases"]["LaB6_copy"]["space_group"] == phase["space_group"]
