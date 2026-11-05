"""GSAS-II's ionic X-ray scattering types (P-47, re/28; non-frozen, imports no engine).

GSAS-II 5.7.9 keys its ionic form factors ``El±n`` (``La+3``, ``O-2``; ``atmdata.XrayFF``, 114 ions) and
reads the recipe spelling ``La3+`` as **hydrogen**, silently (``GSASIIElem.GetAtomInfo``; EB-94). The
recipe states ions in the CIF/IUCr spelling in the engine phase block's ``scattering_types``; this module
holds the table in that spelling (so validation stays engine-free) and the one translation the frozen
project builder applies when it writes the atom type (ledger row R35). ``tests/test_gsasii_scattering.py``
pins :data:`GSASII_IONS` to the installed engine's table; the pin moves with the engine (a deliberate change).
"""
from __future__ import annotations

from powderline.schema_core import scattering_type_parts

#: GSAS-II 5.7.9 ``atmdata.XrayFF`` ions, in the recipe spelling (generated from the installed engine). ``D1-`` is
#: reachable (gemmi knows ``D``); ``T1-`` is not (gemmi has no ``T``, so no recipe can state ``element: "T"``) -- it
#: is kept so the table is exactly the engine's.
GSASII_IONS = frozenset("""
Ac3+ Ag1+ Ag2+ Al3+ Au1+ Au3+ Ba2+ Be2+ Bi3+ Bi5+ Br1- Ca2+ Cd2+ Ce3+ Ce4+ Cl1- Co2+ Co3+ Cr2+ Cr3+ Cs1+ Cu1+
Cu2+ D1- Dy3+ Er3+ Eu2+ Eu3+ F1- Fe2+ Fe3+ Ga3+ Gd3+ Ge4+ H1- Hf4+ Hg1+ Hg2+ Ho3+ I1- In3+ Ir3+ Ir4+ K1+ La3+
Li1+ Lu3+ Mg2+ Mn2+ Mn3+ Mn4+ Mo3+ Mo5+ Mo6+ Na1+ Nb3+ Nb5+ Nd3+ Ni2+ Ni3+ Np3+ Np4+ Np6+ O1- O2- Os4+ Pb2+
Pb4+ Pd2+ Pd4+ Pm3+ Pr3+ Pr4+ Pt2+ Pt4+ Pu3+ Pu4+ Pu6+ Ra2+ Rb1+ Rh3+ Rh4+ Ru3+ Ru4+ Sb3+ Sb5+ Sc3+ Si4+
Sm3+ Sn2+ Sn4+ Sr2+ T1- Ta5+ Tb3+ Th4+ Ti2+ Ti3+ Ti4+ Tl1+ Tl3+ Tm3+ U3+ U4+ U6+ V2+ V3+ V5+ W6+ Y3+ Yb2+
Yb3+ Zn2+ Zr4+
""".split())

ENGINE_LABEL = "GSAS-II 5.7.9"


def gsasii_type(symbol: str) -> str:
    """The GSAS-II atom type for a recipe scattering type: ``"La3+" -> "La+3"``; a bare element unchanged."""
    if symbol in GSASII_IONS:
        element, charge = scattering_type_parts(symbol)
        return f"{element}{'+' if charge > 0 else '-'}{abs(charge)}"
    return symbol
