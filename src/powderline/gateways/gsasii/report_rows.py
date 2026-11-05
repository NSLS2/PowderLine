"""GSAS-II gateway — table rows formatted exactly as ``DataFrame.to_csv`` wrote them (A83).

The gsasii extractors build pandas DataFrames; their report files are written
by core :mod:`powderline.reports` writers (one writer for every engine). Core's
writers leave number formatting to the caller, so this formats each cell as
pandas did (``na_rep=''``, ``float_format`` on float columns only), and the
files stay byte-identical to the ones v0.1.1 wrote.
"""

from __future__ import annotations

import pandas as pd


def pandas_csv_rows(df: pd.DataFrame, float_format: str | None = None) -> list[list[str]]:
    """``df``'s rows as ``to_csv(index=False, float_format=...)`` formats them."""
    columns = []
    for name in df.columns:
        col = df[name]
        if col.dtype.kind == "f":
            fmt = (lambda v, f=float_format: f % v) if float_format else str
            # numpy scalars, not Python floats: a float32 0.1 is written "0.1", as pandas does
            columns.append(["" if pd.isna(v) else fmt(v) for v in col.to_numpy()])
        else:
            columns.append(["" if _missing(v) else str(v) for v in col.astype(object)])
    return [list(row) for row in zip(*columns)] if columns else []


def _missing(v) -> bool:
    """What ``to_csv`` writes as ``na_rep``: None, NaN of any float type, ``pd.NA``, ``NaT``."""
    try:
        return bool(pd.isna(v))
    except (TypeError, ValueError):  # a list or array in an object column: not a scalar missing value
        return False
