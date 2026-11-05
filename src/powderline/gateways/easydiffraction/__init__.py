"""easydiffraction gateway for PowderLine (imports **zero** GSAS-II).

The ``easydiffraction.rietveld`` path (:mod:`.schema`, :mod:`.native_builder`,
:mod:`.native_run`, :mod:`.space_group_support`, :mod:`.gateway`) targets
easydiffraction (https://github.com/easyscience/diffraction-lib) and needs the
optional ``easydiffraction`` pixi environment (Python >=3.12 + easydiffraction).
Importing this package imports no engine; ``powderline <recipe.json>`` serves
these recipes (the one CLI, P-06).
"""
