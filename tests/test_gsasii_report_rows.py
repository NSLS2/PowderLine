"""``gateways.gsasii.report_rows.pandas_csv_rows`` + core writers == ``DataFrame.to_csv`` byte for byte (A83).

The gsasii extractors write their report files through core ``reports``
writers; the rows are formatted as pandas did, so the files stay identical.
Edge cases from the re/04 PR review: NaN/inf, NaN of other float types and
NaT in object columns, nullable integers and strings, booleans, float32,
quoting.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from powderline.gateways.gsasii.report_rows import pandas_csv_rows
from powderline.reports import _write_table

pytestmark = pytest.mark.core


def _frame() -> pd.DataFrame:
    return pd.DataFrame({
        "f": [1.5, np.nan, np.inf, -np.inf, 1e20],
        "obj": ["a,b", 'q"x', None, np.nan, 2.5],
        "i64": pd.array([1, None, 3, 4, 5], dtype="Int64"),
        "b": [True, False, True, False, True],
        "f32": np.array([0.1, 0.2, np.nan, 1.0, 2.0], dtype=np.float32),
        "obj_missing": pd.Series([np.float32("nan"), pd.NaT, pd.NA, 2, "x"], dtype=object),
        "s": pd.array(["x", None, "z", "w", "v"], dtype="string"),
    })


@pytest.mark.parametrize("float_format", [None, "%.8f"])
def test_rows_match_to_csv(tmp_path, float_format):
    df = _frame()
    path = tmp_path / "t.csv"
    _write_table(path, list(df.columns), pandas_csv_rows(df, float_format), ",")
    assert path.read_bytes() == df.to_csv(index=False, lineterminator="\n", float_format=float_format).encode("utf-8")
