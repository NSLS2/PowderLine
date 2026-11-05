"""easydiffraction's ionic X-ray scattering types (P-47, re/28; engine-free).

easydiffraction 0.21.1 accepts any CIF ``type_symbol`` and hands it to the calculator. **CrysPy** has form
factors for the 111 ions below (``cryspy DATABASE['Scattering amplitude']``); for any other ion it falls back
to the neutral atom with a ``log.warning`` only -- ``Logger.Reaction.RAISE`` does not stop it (EB-95).
**CrysFML** "resolves scattering by element" and strips every charge (``calculators/crysfml.py``, EB-96).
The recipe states ions in the engine phase block's ``scattering_types``; the schema refuses what the chosen
calculator would silently neutralise. ``tests/test_easydiffraction_scattering.py`` pins :data:`CRYSPY_IONS`
to the installed engine's table.
"""
from __future__ import annotations

#: CrysPy's ``DATABASE['Scattering amplitude']`` ions (easydiffraction 0.21.1), recipe spelling (generated).
CRYSPY_IONS = frozenset("""
Ac3+ Ag1+ Ag2+ Al3+ Au1+ Au3+ Ba2+ Be2+ Bi3+ Bi5+ Br1- Ca2+ Cd2+ Ce3+ Ce4+ Cl1- Co2+ Co3+ Cr2+ Cr3+ Cs1+ Cu1+
Cu2+ Dy3+ Er3+ Eu2+ Eu3+ F1- Fe2+ Fe3+ Ga3+ Gd3+ Ge4+ H1- Hf4+ Hg1+ Hg2+ Ho3+ I1- In3+ Ir3+ Ir4+ K1+ La3+ Li1+
Lu3+ Mg2+ Mn2+ Mn3+ Mn4+ Mo3+ Mo5+ Mo6+ Na1+ Nb3+ Nb5+ Nd3+ Ni2+ Ni3+ Np3+ Np4+ Np6+ O1- Os4+ Pb2+ Pb4+ Pd2+
Pd4+ Pm3+ Pr3+ Pr4+ Pt2+ Pt4+ Pu3+ Pu4+ Pu6+ Ra2+ Rb1+ Rh3+ Rh4+ Ru3+ Ru4+ Sb3+ Sb5+ Sc3+ Si4+ Sm3+ Sn2+ Sn4+
Sr2+ Ta5+ Tb3+ Th4+ Ti2+ Ti3+ Ti4+ Tl1+ Tl3+ Tm3+ U3+ U4+ U6+ V2+ V3+ V5+ W6+ Y3+ Yb2+ Yb3+ Zn2+ Zr4+
""".split())

ENGINE_LABEL = "easydiffraction 0.21.1 (CrysPy)"
