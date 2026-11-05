"""Shared writers for PowderLine's standardized report files.

This module provides engine-free writers for the standardized report files
emitted by all PowderLine engines: ``refined_parameters.csv``,
``<phase>_unit_cell_report.csv``, ``fit_profile.txt``, and
``<phase>_peak_list_report.csv``.

The module also owns the list of fixed file names PowderLine writes into an
output directory (``FIXED_OUTPUT_NAMES`` / ``FIXED_OUTPUT_PATTERNS``, including
``failure.json``) and ``clear_fixed_outputs``, which :func:`powderline.run`
calls before every run so a reused directory holds one run's results (re/30).

The writers own file naming, column order, header, delimiter, and quoting
(csv QUOTE_MINIMAL, like pandas). All files are written with UTF-8 encoding
and LF line endings (``encoding="utf-8", newline=""`` on open with csv
``lineterminator="\\n"``), ensuring deterministic output on all platforms.

**Number formatting stays with the caller**: engines format values differently,
so this module does not impose a format. A value that is a ``str`` is written
as-is, ``None`` is written as an empty field, and anything else is converted
via ``str(value)``.

Usage example::

    from powderline.reports import write_refined_parameters, REFINED_PARAMETERS_COLUMNS

    rows = [
        {
            "parameter_name": ":0:Scale",
            "descriptive_name": "scale",
            "phase_name": "",
            "phase_idx": None,
            "atom_name": "",
            "atom_idx": None,
            "value": "1.234567e+00",
            "esd": "2.345678e-03",
            "category": "scale",
        },
    ]
    path = write_refined_parameters(output_dir, rows)
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable, Mapping, Optional, Sequence, Union

#: The failed envelope on disk (re/30): written by :func:`powderline.run` beside the engine's own files when a
#: run fails; see :func:`powderline.api.run`.
FAILURE_FILE = "failure.json"

#: Every fixed file name PowderLine itself writes into an output directory (the engines' own files -- ``dummy.gpx``,
#: ``.lst``, ``.inp``, ``.xye`` -- are not PowderLine's and are never touched). ``powderline.run`` removes these
#: before every run (re/30): a directory used twice then holds one run's results, and a failed run's directory
#: holds the engine's files and ``failure.json`` only.
FIXED_OUTPUT_NAMES = ("refined_parameters.csv", "fit_profile.txt",
                      "single_peaks_report.txt", "single_peaks_report.csv",     # gsasii's and topas's SPF reports
                      "output_recipe.json", "parameter_dispositions.csv", FAILURE_FILE)
FIXED_OUTPUT_PATTERNS = ("*_unit_cell_report.csv", "*_peak_list_report.csv")


def clear_fixed_outputs(output_dir) -> list:
    """Remove PowderLine's own fixed-name outputs from ``output_dir`` (nothing else); return what was removed.

    A missing directory is left missing (nothing is created). Files, not directories, are removed.
    """
    out = Path(output_dir)
    if not out.is_dir():
        return []
    removed = []
    candidates = [out / name for name in FIXED_OUTPUT_NAMES]
    for pattern in FIXED_OUTPUT_PATTERNS:
        candidates.extend(sorted(out.glob(pattern)))
    for path in candidates:
        if path.is_file():
            path.unlink()
            removed.append(str(path))
    return removed


#: Column order for refined_parameters.csv (9 columns).
REFINED_PARAMETERS_COLUMNS = (
    "parameter_name",
    "descriptive_name",
    "phase_name",
    "phase_idx",
    "atom_name",
    "atom_idx",
    "value",
    "esd",
    "category",
)

#: Column order for parameter_dispositions.csv (re/20, KI-04): how each value of the output recipe came about.
DISPOSITION_COLUMNS = ("path", "value", "esd", "disposition", "at_limit")

#: Column order for <phase>_unit_cell_report.csv (3 columns).
UNIT_CELL_COLUMNS = ("parameter", "value", "esd")

#: The unit-cell report's **row vocabulary** (re/23, P-45): the six members and the volume, as the report names
#: them. This is the spreadsheet vocabulary -- a row is self-describing when the table is concatenated with others.
#: The same quantities appear in the output recipe and in parameter_dispositions under their *recipe* paths
#: (``payload.phases.<name>.unit_cell.a``); :data:`UNIT_CELL_MEMBER_OF` is the bridge between the two, and the
#: only place a report row name is turned back into a member.
UNIT_CELL_MEMBERS = ("a", "b", "c", "alpha", "beta", "gamma")
UNIT_CELL_ROW_OF = {m: f"cell_{m}" for m in UNIT_CELL_MEMBERS + ("volume",)}
UNIT_CELL_ROWS = tuple(UNIT_CELL_ROW_OF.values())
UNIT_CELL_MEMBER_OF = {row: m for m, row in UNIT_CELL_ROW_OF.items()}

#: Column order for fit_profile.txt (8 columns, tab-delimited).
FIT_PROFILE_COLUMNS = (
    "two_theta",
    "y_obs",
    "y_weights",
    "y_calc",
    "y_diff",
    "y_bkg",
    "q_values",
    "d_spacings",
)


def _write_table(
    path: Path,
    columns: Sequence[str],
    rows: Iterable[Union[Mapping[str, object], Sequence[object]]],
    delimiter: str,
) -> None:
    """Write a table to disk with the specified columns, rows, and delimiter.

    Args:
        path: Output file path.
        columns: Column names in order.
        rows: Iterable of mappings (column -> value) or sequences (in column order).
        delimiter: Field delimiter (',' or '\\t').

    Notes:
        - Values are written as-is if already strings, None becomes empty, else str(value).
        - UTF-8 encoding with LF line endings on all platforms.
        - CSV QUOTE_MINIMAL (only when necessary).
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, delimiter=delimiter, lineterminator="\n")
        writer.writerow(columns)

        for row in rows:
            if isinstance(row, Mapping):
                values = [row.get(col) for col in columns]
            else:
                values = list(row)
                if len(values) != len(columns):
                    raise ValueError(
                        f"{path.name}: row has {len(values)} values, expected "
                        f"{len(columns)} ({', '.join(columns)})"
                    )

            # Convert values: str as-is, None -> "", else str(value)
            formatted = [
                "" if v is None else (v if isinstance(v, str) else str(v))
                for v in values
            ]
            writer.writerow(formatted)


def write_refined_parameters(
    output_dir: Path,
    rows: Iterable[Union[Mapping[str, object], Sequence[object]]],
) -> Path:
    """Write refined_parameters.csv with the standardized 9-column schema.

    Args:
        output_dir: Directory to write the file (created if needed).
        rows: Iterable of mappings (column -> value) or sequences in
              REFINED_PARAMETERS_COLUMNS order.

    Returns:
        Path to the written file (output_dir / "refined_parameters.csv").
    """
    path = Path(output_dir) / "refined_parameters.csv"
    _write_table(path, REFINED_PARAMETERS_COLUMNS, rows, delimiter=",")
    return path


def unit_cell_rows(values: Mapping[str, float], esds: Mapping[str, Optional[float]], *, fixed: Iterable[str],
                   refined: Iterable[str], volume: Optional[float] = None,
                   volume_esd: Optional[float] = None) -> list[dict]:
    """The seven rows of a phase's unit-cell report, in :data:`UNIT_CELL_ROWS` order, with the one ESD rule.

    ``values`` holds the six members' refined (or stated) values in A / degrees; ``esds`` the engine's ESD for a
    member it refined (``None`` when it refined the member but reported none; a tied member carries its group's
    ESD scaled to it); ``fixed`` the members symmetry fixes; ``refined`` the members whose recipe flag is true (topas: the members
    TOPAS reported, which are the same set for any run that gets this far).
    The ESD rule (P-45): the engine's ESD for a refined member; ``0.0`` for a member fixed by symmetry or held by
    the user; ``None`` (an empty field) when the engine refined the member but reported no ESD. The volume is
    ``volume`` when the engine reports it, else gemmi's from the six values; its ESD is ``volume_esd`` when the
    engine propagates one (``0.0`` for a cell with nothing refined), else ``None``.
    """
    fixed, refined = set(fixed), set(refined)
    rows = []
    for m in UNIT_CELL_MEMBERS:
        v = float(values[m])
        esd = esds.get(m) if (m in refined and m not in fixed) else 0.0
        rows.append({"parameter": UNIT_CELL_ROW_OF[m], "value": v, "esd": None if esd is None else float(esd)})
    if volume is None:
        import gemmi  # a core dependency (powderline.symmetry)

        volume = gemmi.UnitCell(*(float(values[m]) for m in UNIT_CELL_MEMBERS)).volume
    if volume_esd is None and not (refined - fixed):
        volume_esd = 0.0                                 # nothing refined: the volume is a stated number
    rows.append({"parameter": UNIT_CELL_ROW_OF["volume"], "value": float(volume),
                 "esd": None if volume_esd is None else float(volume_esd)})
    return rows


def write_unit_cell_report(
    output_dir: Path,
    phase_name: str,
    rows: Iterable[Union[Mapping[str, object], Sequence[object]]],
) -> Path:
    """Write <phase>_unit_cell_report.csv with the 3-column schema.

    Every row's ``parameter`` must be one of :data:`UNIT_CELL_ROWS` (``cell_a`` ... ``cell_volume``): the report
    speaks one vocabulary for every engine, and a gateway that spells a row differently fails here, at run time,
    rather than shipping a table nobody else can read (re/23, P-45).

    Args:
        output_dir: Directory to write the file (created if needed).
        phase_name: Phase name (used in the filename).
        rows: Iterable of mappings (column -> value) or sequences in
              UNIT_CELL_COLUMNS order.

    Returns:
        Path to the written file (output_dir / "<phase>_unit_cell_report.csv").

    Raises:
        ValueError: a row whose ``parameter`` is not in the vocabulary.
    """
    rows = list(rows)
    for row in rows:
        name = row["parameter"] if isinstance(row, Mapping) else row[0]
        if str(name) not in UNIT_CELL_ROWS:
            raise ValueError(f"unit-cell report row {name!r} is not in the report vocabulary "
                             f"{', '.join(UNIT_CELL_ROWS)} (powderline.reports.UNIT_CELL_ROWS)")
    path = Path(output_dir) / f"{phase_name}_unit_cell_report.csv"
    _write_table(path, UNIT_CELL_COLUMNS, rows, delimiter=",")
    return path


def write_fit_profile(
    output_dir: Path,
    rows: Iterable[Union[Mapping[str, object], Sequence[object]]],
) -> Path:
    """Write fit_profile.txt with the 8-column tab-delimited schema.

    Args:
        output_dir: Directory to write the file (created if needed).
        rows: Iterable of mappings (column -> value) or sequences in
              FIT_PROFILE_COLUMNS order.

    Returns:
        Path to the written file (output_dir / "fit_profile.txt").
    """
    path = Path(output_dir) / "fit_profile.txt"
    _write_table(path, FIT_PROFILE_COLUMNS, rows, delimiter="\t")
    return path


def write_peak_list_report(
    output_dir: Path,
    phase_name: str,
    rows: Iterable[Union[Mapping[str, object], Sequence[object]]],
    columns: Sequence[str],
) -> Path:
    """Write <phase>_peak_list_report.csv with engine-specific columns.

    Args:
        output_dir: Directory to write the file (created if needed).
        phase_name: Phase name (used in the filename).
        rows: Iterable of mappings (column -> value) or sequences in
              the columns order.
        columns: Column names in order (varies per engine).

    Returns:
        Path to the written file (output_dir / "<phase>_peak_list_report.csv").
    """
    path = Path(output_dir) / f"{phase_name}_peak_list_report.csv"
    _write_table(path, columns, rows, delimiter=",")
    return path


def write_output_recipe(output_dir: Path, recipe: Mapping[str, object]) -> Path:
    """Write ``output_recipe.json`` (re/20, KI-04): the resolved recipe of the run, UTF-8, LF, 2-space indent."""
    import json

    path = Path(output_dir) / "output_recipe.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(recipe, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    return path


def write_parameter_dispositions(output_dir: Path, rows: Iterable[Mapping[str, object]]) -> Path:
    """Write ``parameter_dispositions.csv`` with :data:`DISPOSITION_COLUMNS`."""
    path = Path(output_dir) / "parameter_dispositions.csv"
    _write_table(path, DISPOSITION_COLUMNS, rows, delimiter=",")
    return path
