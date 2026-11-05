#!/usr/bin/env python3
"""Generate the docs' field tables and support matrix from the schemas themselves (re/10 §1.2; P-27).

The user docs must not drift from the code, so the field-by-field tables on
``docs/fields.md`` and the matrix on ``docs/support-matrix.md`` are not
hand-written: this script derives them from each schema's pydantic JSON
Schema (``model_json_schema()``, including the ``json_schema_extra={"unit":
...}`` metadata every quantity carries, A19) and from
``powderline.support_matrix()`` (A40, A65), and writes MyST fragments that the
pages pull in with ``{include}``:

* ``docs/_generated/fields_core.md`` -- the core-owned fields (recipe frame,
  ``xrd_data``, ``fit_range``, the Chebyshev background, the phase block);
* ``docs/_generated/fields_<engine>_<workflow>.md`` -- one per schema name:
  the engine-owned fields, with the core blocks collapsed to one row each;
* ``docs/_generated/support_matrix.md`` -- one row per installed gateway.

Engine-free: imports the schema layer only, so it runs in the default
environment::

    PYTHONPATH=src python scripts/gen_schema_field_tables.py            # rewrite the fragments
    PYTHONPATH=src python scripts/gen_schema_field_tables.py --check    # exit 1 if they are stale

Run it after changing a schema module and commit the fragments with the
change. Nothing else reads the fragments; the docs build never imports an
engine.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

OUT_DIR = ROOT / "docs" / "_generated"

#: Core ``$defs`` names (``CoreJsonSchema`` strips the parameter type from the title).
CORE_DEFS = {"XRDData", "FitRange", "ChebyshevBackground", "UnitCell", "Atom", "UanisoTensor"}
#: Core-owned phase fields (A93): every engine schema carries them unchanged.
CORE_PHASE_FIELDS = ("space_group", "unit_cell", "atoms")
#: Core-owned payload blocks, collapsed to one row in the engine tables.
CORE_BLOCKS = {"XRDData": "xrd_data (core block)", "FitRange": "fit_range (core block)",
               "ChebyshevBackground": "Chebyshev background (core block)"}
PARAM_TYPES = {"RefinableParameter": "`[value, flag]`", "BoundedRefinableParameter": "`[value, flag, min, max]`"}
KEY_PLACEHOLDER = {"phases": "<phase>", "atoms": "<label>"}


def _recipe_models() -> dict[str, type]:
    from powderline.gateways.easydiffraction import schema as e
    from powderline.gateways.gsasii import schema as g
    from powderline.gateways.topas import schema as t

    return {
        "gsasii.rietveld": g.GsasiiRietveldRecipe, "gsasii.spf": g.GsasiiSpfRecipe,
        "topas.rietveld": t.TopasRietveldRecipe, "topas.spf": t.TopasSpfRecipe,
        "easydiffraction.rietveld": e.EasydiffractionRietveldRecipe,
    }


# --- JSON Schema walking ---------------------------------------------------------------------


def _deref(node: dict, defs: dict) -> tuple[dict, str | None]:
    """Follow a ``$ref`` (also inside a one-element ``allOf``); return (schema, def name)."""
    if "$ref" in node:
        name = node["$ref"].rsplit("/", 1)[-1]
        return defs[name], name
    if "allOf" in node and len(node["allOf"]) == 1 and "$ref" in node["allOf"][0]:
        name = node["allOf"][0]["$ref"].rsplit("/", 1)[-1]
        return defs[name], name
    return node, None


def _variants(node: dict) -> list[dict] | None:
    """The non-null alternatives of an ``anyOf``/``oneOf`` node, or ``None``."""
    for key in ("oneOf", "anyOf"):
        if key in node:
            return [v for v in node[key] if v.get("type") != "null"]
    return None


def _clean(text: str) -> str:
    """First paragraph of a docstring-derived description, as Markdown (rst double backticks -> single)."""
    return text.split("\n\n", 1)[0].replace("\n", " ").replace("``", "`").strip()


def _type_text(node: dict, name: str | None, *, core_param_text: bool) -> str:
    if name in PARAM_TYPES:
        if core_param_text:
            return "parameter (`[value, flag]`; `[value, flag, min, max]` in engines with bounds)"
        return PARAM_TYPES[name]
    if name == "FitRange":
        return "`[min, max]` (either end `null`)"
    if "const" in node:
        return f"`{node['const']!r}`".replace("'", '"')
    if "enum" in node:
        return " \\| ".join(f'`"{v}"`' if isinstance(v, str) else f"`{v}`" for v in node["enum"])
    t = node.get("type")
    if t == "array":
        items = node.get("items", {})
        if "$ref" in items:
            inner = items["$ref"].rsplit("/", 1)[-1]
            return f"list of {PARAM_TYPES.get(inner, inner)}"
        if "prefixItems" in node:
            return f"list of {node.get('minItems', '?')}"
        return f"list of {items.get('type', 'value')}"
    if t == "object" and isinstance(node.get("additionalProperties"), dict):
        return "object keyed by name"
    if t == "object":
        return "block"
    return str(t or name or "object")


def _rows(node: dict, defs: dict, path: str, required: bool, *, collapse_core: bool, core_param_text: bool,
          owner: str, out: list[dict]) -> None:
    """Flatten ``node`` (a property schema) into table rows under ``path``."""
    schema, name = _deref(node, defs)
    unit = node.get("unit") or schema.get("unit") or ""
    desc = node.get("description") or ("" if name in PARAM_TYPES else schema.get("description")) or ""
    desc = _clean(desc)
    default = node.get("default", schema.get("default"))
    note = ""
    if default is not None and not required:
        note = f"default `{default}`"

    variants = _variants(node) if name is None else None
    if variants and len(variants) > 1 and all("$ref" in v for v in variants):
        # a discriminated union (e.g. the easydiffraction peak profile): one block per variant
        disc = (node.get("discriminator") or {}).get("propertyName")
        for v in variants:
            vschema, vname = _deref(v, defs)
            label = vname
            if disc and disc in vschema.get("properties", {}):
                label = vschema["properties"][disc].get("const") or label
            out.append({"path": path, "type": f"one of the `{disc}` variants" if disc else "one of",
                        "unit": "", "required": required, "desc": f"variant `{label}`:", "owner": owner})
            _object_rows(vschema, defs, path, collapse_core=collapse_core, core_param_text=core_param_text,
                         owner=owner, out=out)
        return
    if variants and len(variants) == 1:
        schema, name = _deref(variants[0], defs)
        if not required and not note:
            note = "optional"

    if collapse_core and name in CORE_BLOCKS:
        out.append({"path": path, "type": CORE_BLOCKS[name], "unit": unit, "required": required,
                    "desc": "; ".join(x for x in (desc, note) if x), "owner": "core"})
        return
    row_owner = "core" if name in CORE_DEFS else owner
    type_text = _type_text({**schema, **{k: v for k, v in node.items() if k != "$ref"}}, name,
                           core_param_text=core_param_text)
    out.append({"path": path, "type": type_text, "unit": unit, "required": required,
                "desc": "; ".join(x for x in (desc, note) if x), "owner": row_owner})
    if name in PARAM_TYPES or name == "FitRange":
        return
    if schema.get("type") == "object" and "properties" in schema:
        _object_rows(schema, defs, path, collapse_core=collapse_core, core_param_text=core_param_text,
                     owner=row_owner, out=out)
    elif schema.get("type") == "object" and isinstance(schema.get("additionalProperties"), dict):
        key = KEY_PLACEHOLDER.get(path.rsplit(".", 1)[-1], "<name>")
        _rows(schema["additionalProperties"], defs, f"{path}.{key}", True, collapse_core=collapse_core,
              core_param_text=core_param_text, owner=row_owner, out=out)
    elif schema.get("type") == "array" and "$ref" in schema.get("items", {}):
        inner = schema["items"]["$ref"].rsplit("/", 1)[-1]
        if inner not in PARAM_TYPES:
            _rows(schema["items"], defs, f"{path}[]", True, collapse_core=collapse_core,
                  core_param_text=core_param_text, owner=row_owner, out=out)


def _object_rows(schema: dict, defs: dict, prefix: str, *, collapse_core: bool, core_param_text: bool,
                 owner: str, out: list[dict]) -> None:
    req = set(schema.get("required", ()))
    for fname, fnode in schema.get("properties", {}).items():
        if collapse_core and fname in CORE_PHASE_FIELDS and prefix.endswith("<phase>"):
            _, ref = _deref(fnode, defs)
            label = {"space_group": "canonical space-group name (core)", "unit_cell": "unit cell (core block)",
                     "atoms": "atoms (core block)"}[fname]
            out.append({"path": f"{prefix}.{fname}", "type": label, "unit": "", "required": fname in req,
                        "desc": "see the core fields", "owner": "core"})
            continue
        fowner = "core" if (prefix.endswith("<phase>") and fname in CORE_PHASE_FIELDS) else owner
        _rows(fnode, defs, f"{prefix}.{fname}" if prefix else fname, fname in req,
              collapse_core=collapse_core, core_param_text=core_param_text, owner=fowner, out=out)


# --- tables ----------------------------------------------------------------------------------


def _table(rows: list[dict], *, owner_column: bool) -> str:
    head = "| Field | Type | Unit | Required | Notes |"
    sep = "|---|---|---|---|---|"
    if owner_column:
        head = "| Field | Owner | Type | Unit | Required | Notes |"
        sep = "|---|---|---|---|---|---|"
    lines = [head, sep]
    for r in rows:
        cells = [f"`{r['path']}`"] + ([r["owner"]] if owner_column else []) + [
            r["type"], f"`{r['unit']}`" if r["unit"] else "", "yes" if r["required"] else "no",
            r["desc"].replace("|", "\\|")]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def core_table() -> str:
    from powderline import schema_core as c

    out: list[dict] = []
    frame = c.CoreRecipe.model_json_schema()
    for fname, fnode in frame["properties"].items():
        if fname == "payload":
            continue
        _rows(fnode, frame.get("$defs", {}), fname, fname in set(frame["required"]), collapse_core=False,
              core_param_text=True, owner="core", out=out)
    blocks = [("payload.xrd_data", c.XRDData), ("payload.fit_range", c.FitRange),
              ("payload.background.chebyshev", c.ChebyshevBackground),
              ("payload.phases.<phase>", c.Phase[c.RefinableParameter])]
    for prefix, model in blocks:
        s = model.model_json_schema()
        defs = s.get("$defs", {})
        if "prefixItems" in s or s.get("type") == "array":
            out.append({"path": prefix, "type": _type_text(s, s.get("title"), core_param_text=True), "unit":
                        s.get("unit", ""), "required": False, "desc": s.get("description", ""), "owner": "core"})
            continue
        out.append({"path": prefix, "type": "block", "unit": "", "required": prefix != "payload.fit_range",
                    "desc": _clean(s.get("description") or ""), "owner": "core"})
        _object_rows(s, defs, prefix, collapse_core=False, core_param_text=True, owner="core", out=out)
    text = ("<!-- generated by scripts/gen_schema_field_tables.py from powderline.schema_core; do not edit -->\n\n"
            f"Core schema version `{c.CORE_SCHEMA_VERSION}` (accepted: `{c.SUPPORTED_CORE_SCHEMAS}`). "
            "Where an engine places the Chebyshev background, and whether `fit_range` and `background` may be left "
            "out, is stated in that engine's table.\n\n")
    return text + _table(out, owner_column=False)


def engine_table(schema_name: str, model: type) -> str:
    s = model.model_json_schema()
    defs = s.get("$defs", {})
    out: list[dict] = []
    for fname in ("engine_version",):  # top-level additions beyond the core frame
        if fname in s["properties"]:
            _rows(s["properties"][fname], defs, fname, fname in set(s["required"]), collapse_core=True,
                  core_param_text=False, owner="engine", out=out)
    payload, _ = _deref(s["properties"]["payload"], defs)
    _object_rows(payload, defs, "payload", collapse_core=True, core_param_text=False, owner="engine", out=out)
    engine = schema_name.split(".")[0]
    mod = sys.modules[model.__module__]
    decl = mod.DECLARATIONS
    extra = ""
    if "supported_engine_versions" in decl:
        extra = f"; TOPAS versions a recipe may state: `{decl['supported_engine_versions']}`"
    text = (f"<!-- generated by scripts/gen_schema_field_tables.py from {model.__module__}; do not edit -->\n\n"
            f"`{schema_name}`: engine schema `{decl['engine_schema_version']}` (accepted: "
            f"`{decl['supported_engine_schemas']}`), requires core `{decl['requires_core_schema']}`{extra}. "
            f"Parameter shape: {PARAM_TYPES['BoundedRefinableParameter' if engine != 'gsasii' else 'RefinableParameter']}. "
            "Rows marked *core* are the core blocks of the core table above, placed where this engine puts them.\n\n")
    return text + _table(out, owner_column=True)


def support_matrix_table() -> str:
    import powderline

    rows = powderline.support_matrix()
    lines = ["<!-- generated by scripts/gen_schema_field_tables.py from powderline.support_matrix(); do not edit -->",
             "",
             "| Gateway | PowderLine | Core schema (current / accepted) | Engine schema (current / accepted) | "
             "Requires core | Engine version | Workflows |",
             "|---|---|---|---|---|---|---|"]
    for r in rows:
        if r["declared"]:
            engine_schema = f"{r['engine_schema_version']} / `{r['supported_engine_schemas']}`"
            requires = f"`{r['requires_core_schema']}`"
        else:
            engine_schema = requires = "**undeclared**"
        lines.append(f"| `{r['gateway']}` | {r['powderline_version']} | {r['core_schema_version']} / "
                     f"`{r['supported_core_schemas']}` | {engine_schema} | {requires} | "
                     f"`{r['engine_version_spec']}` | {', '.join(f'`{w}`' for w in r['workflows'])} |")
    lines.append("")
    lines.append(f"Generated from `powderline.support_matrix()` of PowderLine {powderline.__version__}; "
                 f"{sum(r['declared'] for r in rows)} of {len(rows)} gateways declare their versions.")
    return "\n".join(lines) + "\n"


def fragments() -> dict[str, str]:
    files = {"fields_core.md": core_table(), "support_matrix.md": support_matrix_table()}
    for name, model in _recipe_models().items():
        files[f"fields_{name.replace('.', '_')}.md"] = engine_table(name, model)
    return files


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="exit 1 if a committed fragment differs from the schemas")
    ap.add_argument("--out-dir", type=Path, default=OUT_DIR)
    args = ap.parse_args(argv)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    stale = []
    for name, text in fragments().items():
        path = args.out_dir / name
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != text:
                stale.append(path)
        else:
            path.write_text(text, encoding="utf-8")
            print(f"wrote {path}")
    if stale:
        print("stale (regenerate with scripts/gen_schema_field_tables.py): " + ", ".join(map(str, stale)),
              file=sys.stderr)
        return 1
    if args.check:
        # say what was compared, so a clean run is distinguishable from a run that did nothing (a smoke test or a CI
        # log sees only this line)
        import powderline
        from powderline.schema_core import CORE_SCHEMA_VERSION
        engines = ", ".join(f"{r['gateway']} {r['engine_schema_version']}" for r in powderline.support_matrix())
        try:
            shown = args.out_dir.resolve().relative_to(Path.cwd().resolve())
        except ValueError:
            shown = args.out_dir
        print(f"fields-check: {len(fragments())} files under {shown} match the schema declarations "
              f"(core {CORE_SCHEMA_VERSION}; {engines})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
