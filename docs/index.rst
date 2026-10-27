.. PowderLine documentation master file

PowderLine Documentation
========================

PowderLine automates powder X-ray diffraction refinement from a declarative
JSON "recipe". It is the application layer over interchangeable refinement
engines — GSAS-II by default, or Bruker TOPAS v7 or the open-source
easydiffraction — returning standardized, machine-readable result tables. The
same recipe runs on any engine, which makes PowderLine a natural fit for
interactive, scripted, high-throughput, and autonomous workflows.

New to PowderLine? Start with the :doc:`quickstart` — the shortest path from a
fresh clone to a finished refinement, on Linux or Windows.

.. toctree::
   :maxdepth: 2
   :caption: User Guide:

   quickstart
   getting-started
   building-recipes
   capabilities
   integration-guide
   mp-simulation
   TROUBLESHOOTING
   SCHEMA_HISTORY
   api
   citing

.. toctree::
   :maxdepth: 1
   :caption: Developer:

   DEVELOPMENT
   known_issues
   regression-tolerance
   cross-platform-guide

Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
