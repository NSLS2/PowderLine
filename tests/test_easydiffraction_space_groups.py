"""The committed easydiffraction space-group table matches the installed library (re/06, EB-42).

``space_group_table.py`` lets the schema validate without easydiffraction; this
test regenerates it from the library (``scripts/generate_easydiffraction_space_groups.py``)
and compares. It runs only where the installed easydiffraction is the version
the table was generated from.
"""

from __future__ import annotations

import importlib.util
import re
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
TABLE = ROOT / "src" / "powderline" / "gateways" / "easydiffraction" / "space_group_table.py"


def _table_version() -> str:
    return re.search(r"from easydiffraction\n(\S+):", TABLE.read_text(encoding="utf-8")).group(1)


def _installed() -> str | None:
    try:
        return version("easydiffraction")
    except PackageNotFoundError:
        return None


pytestmark = [
    pytest.mark.easydiffraction,
    pytest.mark.skipif(_installed() != _table_version(),
                       reason=f"table generated from easydiffraction {_table_version()}, installed: {_installed()}"),
]


def _generator():
    spec = importlib.util.spec_from_file_location("gen", ROOT / "scripts" / "generate_easydiffraction_space_groups.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_committed_table_is_current():
    gen = _generator()
    assert TABLE.read_text(encoding="utf-8") == gen.render(gen.build())


@pytest.mark.parametrize("xhm, expected", [
    ("P m -3 m", ("P m -3 m", "1", True)),
    ("C 1 2/m 1", ("C 2/m", "b1", True)),
    ("P 1 1 21/b", ("P 21/c", "c3", False)),
    ("R -3 m:H", ("R -3 m", "h", True)),
    ("R -3 m:R", ("R -3 m", "r", False)),
    ("F d -3 m:1", ("F d -3 m", "1", False)),
    ("F d -3 m:2", ("F d -3 m", "2", True)),
])
def test_structure_accepts_the_mapped_setting(xhm, expected):
    from easydiffraction import StructureFactory

    from powderline.gateways.easydiffraction.space_group_table import SPACE_GROUPS

    assert SPACE_GROUPS[xhm] == expected
    name, code, is_default = expected
    s = StructureFactory.from_scratch(name="t")
    s.space_group.name_h_m = name
    assert (s.space_group.coord_system_code.value == code) is is_default
    s.space_group.coord_system_code = code
    assert (s.space_group.name_h_m.value, s.space_group.coord_system_code.value) == (name, code)


#: A fixed sample re-verified by computation against the committed support sets (EB-80): defaults,
#: origin choices, rhombohedral axes, non-default monoclinic and orthorhombic settings, CrysPy crashes,
#: P 31 (CrysPy computes the other hand; A170), and origin-1 settings whose special positions CrysPy computes
#: wrongly (A174).
SUPPORT_SAMPLE = ("P m -3 m", "F d -3 m:1", "F d -3 m:2", "R -3 m:H", "R -3 m:R", "C 1 2/m 1", "P 1 1 2",
                  "P n n n:1", "P n n n:2", "P b n m", "A 1 2 1", "P 31", "P 6/m", "F d -3 c:2", "F d d d:1",
                  "P n -3 m:1")


def test_support_sets_reverified_on_a_sample():
    gen = importlib.util.spec_from_file_location("ver", ROOT / "scripts" / "verify_easydiffraction_settings.py")
    module = importlib.util.module_from_spec(gen)
    gen.loader.exec_module(module)
    from powderline.gateways.easydiffraction import space_group_support as support
    from powderline.gateways.easydiffraction.space_group_table import SPACE_GROUPS

    for xhm, cryspy_ok, crysfml_ok, note in module._verify_chunk([(x, SPACE_GROUPS[x]) for x in SUPPORT_SAMPLE]):
        assert (cryspy_ok, crysfml_ok) == (xhm in support.CRYSPY_SETTINGS, xhm in support.CRYSFML_SETTINGS), (xhm, note)
