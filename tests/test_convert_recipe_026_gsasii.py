"""The 0.26.0 converter's space-group mapping, checked against GSAS-II's own reader (A132).

The two GSAS-II-reading tests of ``test_convert_recipe_026.py`` (re/09 split):
they compare the general-position orbit GSAS-II generates for the old symbol
with the one for the converted setting, so they need ``GSASII.GSASIIspc``. The
converter's fixtures and helpers are imported from the engine-free module.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

pytestmark = pytest.mark.gsasii

G2spc = pytest.importorskip("GSASII.GSASIIspc")

from powderline.gateways.gsasii.schema import gsasii_space_group  # noqa: E402
from test_convert_recipe_026 import EXAMPLES, conv  # noqa: E402


def test_space_group_every_spelling_gsasii_read_converts_to_the_same_setting():
    """Every gemmi spelling v0.1.1's GSAS-II read (incl. its StandardizeSpcName fallback) converts to that
    setting, or stops (origin choice 1, or a setting gsasii 0.1.0 refuses); never another setting (A132)."""
    import gemmi
    xyz = (0.1234, 0.2345, 0.3456)

    def read(symbol):
        err, sgdata = G2spc.SpcGroup(symbol)
        if err and symbol:
            normalized = G2spc.StandardizeSpcName(symbol)
            if normalized and normalized != symbol:
                err, sgdata = G2spc.SpcGroup(normalized)
        return None if err else sorted(tuple(np.round(np.mod(r[0], 1.0), 5) % 1.0) for r in G2spc.GenAtom(xyz, sgdata))

    spellings = {s for sg in gemmi.spacegroup_table()
                 for s in (sg.hm, sg.xhm(), sg.short_name(), sg.hm.replace(" ", ""), sg.xhm().replace(" ", ""))}
    differ = []
    for old in sorted(spellings | {"R -3 m R", "R 3 m R", "R -3 c R"}):
        before = read(old)
        if before is None:
            continue
        try:
            after = read(gsasii_space_group(conv.canonical_space_group(old)))
        except ValueError:
            continue
        if after != before:
            differ.append(old)
    assert differ == []


def test_space_group_as_gsasii_read_it_matches_gsasii():
    """GSAS-II's reading of each old symbol is the converted setting (general-position orbit)."""
    xyz = (0.1234, 0.2718, 0.3141)
    symbols = {"P m -3 m", "R -3 m", "R -3 m R", "F d -3 m", "C 2/m", "P 21/c"}
    for f in EXAMPLES:
        for ph in (json.loads(f.read_text(encoding="utf-8"))["payload"].get("phases") or {}).values():
            symbols.add(ph["structure"]["space_group"])

    def orbit(sgdata):
        return [np.array(r[0]) % 1.0 for r in G2spc.GenAtom(xyz, sgdata)]

    def same(a, b):
        return len(a) == len(b) and all(any(np.allclose(((p - q + 0.5) % 1) - 0.5, 0, atol=1e-6) for q in b)
                                        for p in a)
    for old in sorted(symbols):
        err_old, sg_old = G2spc.SpcGroup(old)
        if err_old:
            err_old, sg_old = G2spc.SpcGroup(G2spc.StandardizeSpcName(old))  # the v0.1.1 reader's fallback
        err_new, sg_new = G2spc.SpcGroup(gsasii_space_group(conv.canonical_space_group(old)))
        assert not err_old and not err_new, old
        assert same(orbit(sg_old), orbit(sg_new)), old
