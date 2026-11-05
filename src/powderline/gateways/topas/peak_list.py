"""TOPAS reflection list -> PowderLine peak-list rows (re/07).

Moved verbatim from the deleted ``roundtrip.py`` so that the ``topas.*``
runner (:mod:`.native_run`) owns the peak-list parsing it uses. TOPAS code may
only be moved here, not changed (P-08: no TOPAS run available to re-verify).
"""

from __future__ import annotations

#: peak-list columns (GSAS-II names) TOPAS provides faithfully. F_calc² and
#: F_obs² are derived from confirmed structure-factor / intensity variables
#: (§D.11); GSAS-II-only columns (sigma_squared, gamma, I_corr, Prfo, Trans,
#: ExtP; peak widths) have no faithful TOPAS str equivalent and are omitted.
PEAK_LIST_COLUMNS = (
    "h", "k", "l", "multiplicity", "d_spacing", "2theta",
    "F_obs_squared", "F_calc_squared", "I_no_scale_pks", "I_after_scale_pks", "phase",
)


def _rows_of_floats(text: str, ncols: int) -> list[list[float]]:
    rows = []
    for raw in text.splitlines():
        parts = raw.split()
        if len(parts) < ncols:
            continue
        try:
            rows.append([float(p) for p in parts[:ncols]])
        except ValueError:
            continue  # skip a stray header/comment line
    return rows


def parse_peak_list(peaks_text: str, phase_name: str) -> list[dict]:
    """TOPAS peak table -> GSAS-II rows with derived F_obs² / F_calc².

    Columns: H K L M D_spacing 2theta I_no_scale_pks I_after_scale_pks
    Iobs_no_scale_pks A01 B01 A11 B11. Then, per reflection (§D.11):

    * ``F_calc² = A01² + B01² + A11² + B11²`` (the ``F2_Merged`` idiom)
    * ``F_obs²  = F_calc² · Iobs_no_scale_pks / I_no_scale_pks`` — the Rietveld
      observed/calculated intensity ratio applied to F_calc² (multiplicity, LP,
      etc. cancel); 0 when ``I_no_scale_pks`` is non-positive.
    """
    out = []
    for row in _rows_of_floats(peaks_text, 13):
        h, k, l, m, d, tt, i_ns, i_as, iobs, a01, b01, a11, b11 = row
        f_calc_sq = a01 * a01 + b01 * b01 + a11 * a11 + b11 * b11
        f_obs_sq = f_calc_sq * (iobs / i_ns) if i_ns > 0 else 0.0
        out.append({
            "h": h, "k": k, "l": l, "multiplicity": m, "d_spacing": d, "2theta": tt,
            "F_obs_squared": f_obs_sq, "F_calc_squared": f_calc_sq,
            "I_no_scale_pks": i_ns, "I_after_scale_pks": i_as, "phase": phase_name,
        })
    return out


