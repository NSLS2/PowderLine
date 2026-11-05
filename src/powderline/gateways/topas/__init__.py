"""TOPAS gateway for PowderLine (imports **zero** GSAS-II).

The ``topas.rietveld`` / ``topas.spf`` path (:mod:`.schema`,
:mod:`.native_writer`, :mod:`.native_run`, :mod:`.peak_list`,
:mod:`.runner`, :mod:`.gateway`) must run on Windows,
where GSAS-II does not install cleanly. ``powderline <recipe.json>`` serves
these recipes (the one CLI, P-06).

Citation notation used throughout this subpackage: ``findings §X`` / ``plan §Y``
/ ``D-numbers`` cite the internal TOPAS design record (empirical findings and
decision log kept with the maintainers' development notes); they label *why* a
formula or behavior is the way it is and appear verbatim in some emitted INP
headers, so they are stable identifiers - do not renumber them.
"""
