API Reference
=============

The public API is the names in ``powderline.__all__``. ``import powderline``
imports no engine: ``validate`` runs each gateway's engine-free schema layer,
and ``run`` imports an engine lazily through the gateway the recipe's
``schema_name`` names. The recipe contract itself (every field, with its unit)
is documented on :doc:`fields` (tables generated from the schema modules
``powderline.schema_core`` and ``powderline.gateways.<engine>.schema``), and
the result dict on :doc:`schemas`.

Public API (``powderline``)
---------------------------

.. py:module:: powderline

.. autofunction:: powderline.run

.. autofunction:: powderline.validate

.. autoclass:: powderline.ValidationResult
   :members:

.. autofunction:: powderline.load_recipe_asset

.. autofunction:: powderline.support_matrix

Exceptions
~~~~~~~~~~

.. autoexception:: powderline.PowderLineError

.. autoexception:: powderline.GatewayNotInstalledError

.. autoexception:: powderline.EngineNotAvailableError

.. autoexception:: powderline.EngineVersionError

.. autoexception:: powderline.EngineExecutionError

.. autoexception:: powderline.ExecutionBackendError

The run-result envelope the exceptions carry (``.result``) and every gateway produces:

``powderline.results.ENVELOPE_VERSION`` (``"1"``), ``STATUSES`` (``ok``, ``generated``, ``failed``),
``ENGINE_REASONS`` and ``BACKEND_REASONS`` (the reason codes, tabulated in :doc:`schemas`):

.. automodule:: powderline.results
   :members: failure_envelope, generated_envelope, with_status_fields, raise_if_failed

The structured-warning shape shared by validation results and run results:

.. autoclass:: powderline.exceptions.StructuredWarning
   :members:
   :undoc-members:

Command line
------------

.. py:module:: powderline.kicker

``powderline <recipe.json> [--output DIR] [--validate-only] [--verbose]
[--use-server | --no-server] [--topas-dir DIR] [--topas-version V]
[--topas-timeout SECONDS]`` (the pixi
task ``kicker`` runs the same ``main``), and ``powderline --doctor`` (the pixi
task ``doctor``): what this environment can do — the gateways the registry
finds, each engine's installed version against its requirement, the GSAS-II
server's state — exiting 1 on a stale install or an engine outside its
requirement (:mod:`powderline.doctor`). The engine is the one the recipe's
``schema_name`` names; an engine flag given for a recipe of another engine is
an error; exit status 0 on success, 1 otherwise. The module imports no engine.

.. py:module:: powderline.doctor

``powderline --doctor``'s report (re/27, KI-13): ``report()`` returns the
structured dict (``powderline``, ``python``, ``platform``, ``gateways`` — one
entry per registered gateway with ``workflows``, ``engine_version_spec``,
``engine_installed``, ``engine_status``, ``problem`` — ``server`` and
``problems``), ``format_report()`` renders it, ``main()`` prints it and
returns 1 when ``problems`` is non-empty. Engine-free at import; the gateway
modules are imported lazily when the report runs.

.. autofunction:: powderline.kicker.main

.. autofunction:: powderline.kicker.is_template_file

Gateway registry
----------------

Gateways are discovered from the ``powderline.gateways`` entry-point group;
these are the hooks an out-of-tree engine uses.

.. autoclass:: powderline.registry.Gateway

.. autofunction:: powderline.registry.available

.. autofunction:: powderline.registry.get

.. autofunction:: powderline.registry.register_gateway

.. autofunction:: powderline.registry.check_engine_version

Gateway ``run`` functions (the gateway contract)
------------------------------------------------

**Run recipes with** :func:`powderline.run` **(or the** ``powderline`` **CLI),
not with these.** Each gateway's ``run`` is what ``powderline.run`` forwards to
after validating the recipe and choosing the gateway; they are documented
for gateway authors, for tests, and because their keyword options are
exactly the engine options ``powderline.run`` accepts for that engine.
Calling one directly skips the orchestration ``powderline.run`` provides
on every engine: PowderLine's own fixed-name outputs are not cleared from
the output directory first, and a failed run writes no ``failure.json``.

.. autofunction:: powderline.gateways.gsasii.gateway.run

.. autofunction:: powderline.gateways.topas.gateway.run

.. autofunction:: powderline.gateways.easydiffraction.gateway.run

GSAS-II gateway helpers
-----------------------

Output generation
~~~~~~~~~~~~~~~~~

Functions of the frozen extraction path
(``powderline.gateways.gsasii.extractors``).

.. autofunction:: powderline.gateways.gsasii.extractors.export_refined_parameters_csv

.. autofunction:: powderline.gateways.gsasii.extractors.calculate_cell_esds_from_A_matrix

.. autofunction:: powderline.gateways.gsasii.extractors.extract_refined_params_from_project

.. note::

   These helpers document the GSAS-II engine's extraction path. ESDs (estimated
   standard deviations) are read from GSAS-II's covariance matrix
   (``proj.data['Covariance']``). Unit cell ESDs require conversion from the reciprocal
   metric tensor (A-matrix) to direct lattice parameters via ``calculate_cell_esds_from_A_matrix()``.

Post-refinement extraction helpers (private)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The four private ``_extract_*`` helpers encapsulate the post-refinement data
extraction and file-writing logic. They are not part of the public API but are
documented here for maintainers.

.. autofunction:: powderline.gateways.gsasii.extractors._extract_fit_profile

.. autofunction:: powderline.gateways.gsasii.extractors._extract_spf_peak_report

.. autofunction:: powderline.gateways.gsasii.extractors._extract_phase_reports

.. autofunction:: powderline.gateways.gsasii.extractors._extract_refined_parameters

Background functions
~~~~~~~~~~~~~~~~~~~~

.. autofunction:: powderline.gateways.gsasii.setters.set_chebyshev_background

.. autofunction:: powderline.gateways.gsasii.setters.set_single_peak_background

Fit range
~~~~~~~~~

.. autofunction:: powderline.gateways.gsasii.setters.set_fit_range_hist


Types
-----

Refinement parameter format
~~~~~~~~~~~~~~~~~~~~~~~~~~~

A refinable parameter is a list, never an object. In the ``gsasii.*`` schemas
(no bounds)::

    [value, refine_flag]

in the ``topas.*`` and ``easydiffraction.*`` schemas::

    [value, refine_flag, min, max]

Where:

- ``value`` (number): the starting value, never ``null``
- ``refine_flag`` (JSON boolean): ``true`` to refine, ``false`` to hold fixed
- ``min`` / ``max`` (number or ``null``): bounds, each side optional; what a
  bound means is the engine's (see :doc:`engine-behavior`)

Example::

    "wavelength": [0.45236, false]              // gsasii: fixed at 0.45236 Å
    "scale": [1.0, true, null, null]            // topas / easydiffraction: refined, no bounds
    "a": [4.157, true, 4.1, 4.2]                // bounded

Phase vs histogram parameters
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- **Phase parameters**: belong to a crystal structure (space group, unit cell,
  atoms, scale, sample broadening): the ``phases.<name>`` block
- **Histogram parameters**: belong to the measurement (instrument profile and
  corrections, background): the ``instrument`` and ``background`` blocks

In multi-phase refinements, phase parameters are phase-specific while histogram
parameters are shared across all phases (the phase ``scale`` factors are per
phase). Multi-phase refinement is supported by every Rietveld schema.
