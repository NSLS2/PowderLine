"""TOPAS's ionic X-ray scattering types (engine-free).

TOPAS reads an atom's scattering type from the ``occ`` keyword of its ``site`` (``occ La+3 1``) and spells an
ion ``El±n`` (``La+3``, ``O-2``). Its table is the TOPAS 6 ``ATMSCAT.CPP`` shipped with the program, measured
on 2026-11-04 (sha256 ``f8f01a90bbcb2d0db446817c6bc64da9040b45b9aa2981faaa64fd442b35f4c0``): 113 ions, exactly
GSAS-II 5.7.9's table without ``T1-`` (unreachable anyway: gemmi has no ``T``, so no recipe can state
``element: "T"``). TOPAS rejects the CIF spelling ``La3+``, a sign-only ``Na+`` and an unknown symbol, and then
writes no results (``output_missing``); it never falls back to the neutral atom. The recipe states ions in the
CIF/IUCr spelling in the phase block's ``scattering_types``; this module holds the table in that spelling (so
validation stays engine-free) and the translation the INP writer applies to ``occ``.

``ATMSCAT.CPP`` is a text file the user can edit: a TOPAS installation with an edited table can differ from
this set. The set moves with the supported TOPAS version (a deliberate change).
"""
from __future__ import annotations

from powderline.schema_core import scattering_type_parts

#: The TOPAS 6 ``ATMSCAT.CPP`` ions, in the recipe spelling: GSAS-II 5.7.9's set minus ``T1-`` (113 ions).
TOPAS_IONS = frozenset("""
Ac3+ Ag1+ Ag2+ Al3+ Au1+ Au3+ Ba2+ Be2+ Bi3+ Bi5+ Br1- Ca2+ Cd2+ Ce3+ Ce4+ Cl1- Co2+ Co3+ Cr2+ Cr3+ Cs1+ Cu1+
Cu2+ D1- Dy3+ Er3+ Eu2+ Eu3+ F1- Fe2+ Fe3+ Ga3+ Gd3+ Ge4+ H1- Hf4+ Hg1+ Hg2+ Ho3+ I1- In3+ Ir3+ Ir4+ K1+ La3+
Li1+ Lu3+ Mg2+ Mn2+ Mn3+ Mn4+ Mo3+ Mo5+ Mo6+ Na1+ Nb3+ Nb5+ Nd3+ Ni2+ Ni3+ Np3+ Np4+ Np6+ O1- O2- Os4+ Pb2+
Pb4+ Pd2+ Pd4+ Pm3+ Pr3+ Pr4+ Pt2+ Pt4+ Pu3+ Pu4+ Pu6+ Ra2+ Rb1+ Rh3+ Rh4+ Ru3+ Ru4+ Sb3+ Sb5+ Sc3+ Si4+
Sm3+ Sn2+ Sn4+ Sr2+ Ta5+ Tb3+ Th4+ Ti2+ Ti3+ Ti4+ Tl1+ Tl3+ Tm3+ U3+ U4+ U6+ V2+ V3+ V5+ W6+ Y3+ Yb2+
Yb3+ Zn2+ Zr4+
""".split())

ENGINE_LABEL = "TOPAS 6"


def topas_type(symbol: str) -> str:
    """The TOPAS ``occ`` type for a recipe scattering type: ``"La3+" -> "La+3"``; a bare element unchanged."""
    if symbol in TOPAS_IONS:
        element, charge = scattering_type_parts(symbol)
        return f"{element}{'+' if charge > 0 else '-'}{abs(charge)}"
    return symbol
