"""Recipe files and core blocks (engine-free): load a recipe asset from disk; move a core block between recipes.

``load_recipe_asset`` moved here from ``powderline.kicker`` (re/07, P-06) so
the public API can read a recipe without importing any engine. Interpreting
the recipe is the gateways' job (:func:`powderline.validate`).
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml


def load_recipe_asset(recipe_path: Path) -> dict:
    """Read a recipe file and return it as a dict, uninterpreted.

    ``.json`` is parsed as JSON; ``.yaml`` / ``.yml`` / ``.txt`` as YAML (an
    empty YAML document gives ``{}``). Files are read as UTF-8 (a leading BOM
    is accepted). The content is not validated: pass it to
    :func:`powderline.validate` or :func:`powderline.run`.

    Raises:
        ValueError: the suffix is none of the above (``Unsupported recipe format``);
            the text is not valid JSON / YAML; or the document is not a mapping.
            The message starts with the file path.
        OSError: the file cannot be read.
    """
    recipe_path = Path(recipe_path)
    ext = recipe_path.suffix.lower()
    if ext not in {".json", ".yaml", ".yml", ".txt"}:
        raise ValueError(f"Unsupported recipe format: {recipe_path}")
    text = recipe_path.read_text(encoding="utf-8-sig")
    if ext == ".json":
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{recipe_path}: not valid JSON ({exc})") from exc
    else:
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise ValueError(f"{recipe_path}: not valid YAML ({exc})") from exc
        if data is None:
            data = {}
    if not isinstance(data, dict):
        raise ValueError(
            f"{recipe_path}: a recipe must be a mapping with schema_name and payload, "
            f"got {type(data).__name__}")
    return data


#: The blocks every engine schema shares by construction (the core schema): the only parts of a recipe that may
#: move from one recipe to another, whatever their engines (P-43 D4). ``payload.phases.<name>`` is one of them.
CORE_BLOCKS = ("payload.xrd_data", "payload.fit_range")


def _is_core_block(path: str) -> bool:
    return path in CORE_BLOCKS or (path.startswith("payload.phases.") and path.count(".") == 2)


def _walk(recipe: dict, keys: list, create: bool = False) -> dict:
    node = recipe
    for key in keys:
        if create:
            node = node.setdefault(key, {})
        else:
            node = node[key]
    return node


def block(recipe: dict, path: str) -> dict:
    """A deep copy of the core block at ``path`` (``payload.xrd_data``, ``payload.fit_range``,
    ``payload.phases.<name>``) of a recipe dict -- the chaining currency between tools (re/20a, KI-04).

    Raises:
        ValueError: ``path`` is not a core block (engine blocks are never shared between engines).
        KeyError: the recipe has no such block.
    """
    import copy

    if not _is_core_block(path):
        raise ValueError(f"{path!r} is not a core block; only {', '.join(CORE_BLOCKS)} and payload.phases.<name> "
                         "move between recipes (an engine's own blocks are written in that engine's terms)")
    keys = path.split(".")
    return copy.deepcopy(_walk(recipe, keys[:-1])[keys[-1]])


def with_block(recipe: dict, path: str, value: dict) -> dict:
    """A deep copy of ``recipe`` with the core block at ``path`` replaced by a copy of ``value``.

    The result is not validated here: the target recipe's own schema is the gate
    (:func:`powderline.validate`). Raises ``ValueError`` for a path that is not a core block.
    """
    import copy

    if not _is_core_block(path):
        raise ValueError(f"{path!r} is not a core block; only {', '.join(CORE_BLOCKS)} and payload.phases.<name> "
                         "move between recipes (an engine's own blocks are written in that engine's terms)")
    out = copy.deepcopy(recipe)
    keys = path.split(".")
    _walk(out, keys[:-1], create=True)[keys[-1]] = copy.deepcopy(value)
    return out
