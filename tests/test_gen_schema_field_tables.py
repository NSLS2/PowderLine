"""The field-table generator's ``--check`` says what it compared on success and names the stale file on failure."""
import importlib.util
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.core

REPO = Path(__file__).resolve().parents[1]


def _script():
    spec = importlib.util.spec_from_file_location("gen_schema_field_tables", REPO / "scripts" / "gen_schema_field_tables.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_check_reports_what_matched_on_the_committed_tables(capsys):
    assert _script().main(["--check"]) == 0
    out = capsys.readouterr().out.strip().splitlines()
    assert len(out) == 1 and out[0].startswith("fields-check: 7 files under ") and "core 0.1.0" in out[0]
    assert all(f"{e} 0.1.0" in out[0] for e in ("gsasii", "topas", "easydiffraction"))


def test_check_names_the_stale_file(tmp_path, capsys):
    mod = _script()
    assert mod.main(["--out-dir", str(tmp_path)]) == 0                       # a fresh set, all written
    (tmp_path / "fields_core.md").write_text("edited\n", encoding="utf-8")
    assert mod.main(["--check", "--out-dir", str(tmp_path)]) == 1
    captured = capsys.readouterr()
    assert "fields_core.md" in captured.err and "fields-check:" not in captured.out
