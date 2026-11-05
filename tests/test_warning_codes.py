"""``WARNING_CODES`` is the vocabulary of structured warnings (P-37, S5).

Three things must agree: the registry, every ``code="..."`` literal emitted
under ``src/powderline``, and the "Warnings you may see" table in
``docs/engine-behavior.md`` (code, engine, level).
"""
import re
from pathlib import Path

import pytest

from powderline.exceptions import WARNING_CODES, WarningCode

pytestmark = pytest.mark.core

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src" / "powderline"
DOC = REPO / "docs" / "engine-behavior.md"
EMITTED = re.compile(r'code="([a-z0-9_]+)"')
DOC_ROW = re.compile(r"^\| `([a-z0-9_]+)` \| (\w+) \| (warning|info) \|", re.M)
OWNERS = ("core", "gsasii", "topas", "easydiffraction")


def _emitted() -> set:
    return {code for path in SRC.rglob("*.py") for code in EMITTED.findall(path.read_text(encoding="utf-8"))}


def test_every_emitted_code_is_registered_and_every_registered_code_is_emitted():
    assert _emitted() == set(WARNING_CODES)


def test_registry_entries_are_well_formed():
    for code, entry in WARNING_CODES.items():
        assert isinstance(entry, WarningCode) and entry.owner in OWNERS and entry.level in ("warning", "info"), code
        if entry.owner != "core":
            assert code.startswith(entry.owner + "_"), code
        else:
            assert not any(code.startswith(o + "_") for o in OWNERS[1:]), code


def test_docs_table_matches_the_registry():
    rows = DOC_ROW.findall(DOC.read_text(encoding="utf-8"))
    assert rows, "the warnings table was not found"
    assert {code: (owner, level) for code, owner, level in rows} == {k: tuple(v) for k, v in WARNING_CODES.items()}
