.. PowderLine documentation master file

PowderLine Documentation
========================

PowderLine automates powder X-ray diffraction refinement from a declarative
JSON "recipe". It is the application layer over interchangeable refinement
engines — GSAS-II, Bruker TOPAS 6, or the open-source easydiffraction. A recipe
names one engine and one workflow and is written in that engine's own
conventions; PowderLine runs it and returns standardized, machine-readable
result tables with uniform fit statistics, which makes it a natural fit for
interactive, scripted, high-throughput, and autonomous workflows.

New to PowderLine? Start with the :doc:`quickstart` — the shortest path from a
fresh clone to a finished refinement, on Linux or Windows.

.. toctree::
   :maxdepth: 2
   :caption: User Guide:

   quickstart
   getting-started
   schemas
   fields
   input-guidance
   engine-behavior
   integration-guide
   cross-engine-comparison
   TROUBLESHOOTING
   migration-0.1-to-0.2
   support-matrix
   SCHEMA_HISTORY
   policies
   changelog
   api

.. toctree::
   :maxdepth: 1
   :caption: Developer:

   DEVELOPMENT
   known_issues
   regression-tolerance
   engine-versions
   cross-platform-guide

Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
