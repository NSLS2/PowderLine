Getting Started
===============

Installation
------------

PowderLine uses `pixi <https://pixi.sh>`_ for reproducible conda environments.
The **default environment is core-only**: it validates recipes for every
engine and runs none. Each engine has its own environment::

    pixi install                      # core only (validation, the CLI)
    pixi install -e gsasii            # + GSAS-II (conda package built by pixi-build)
    pixi install -e easydiffraction   # + easydiffraction (Python >= 3.12)
    pixi install -e all               # every engine
    pixi install -e dev               # all engines + docs/test tooling (contributors)

TOPAS has no Python package: ``topas.*`` recipes validate and write their input
files in any environment; running them needs a Windows machine with TOPAS 6
(``tc.exe``).

Basic usage
-----------

One command serves every engine; the recipe's ``schema_name`` names the engine
that runs it (``gsasii.rietveld``, ``gsasii.spf``, ``topas.rietveld``,
``topas.spf``, ``easydiffraction.rietveld``)::

    pixi run -e gsasii kicker examples/example_LaB6/input.json             # GSAS-II
    pixi run -e easydiffraction kicker examples/example_LaB6/easydiffraction/input.json
    pixi run kicker examples/example_LaB6/topas/input.json --topas-dir C:/TOPAS6 --topas-version 6   # TOPAS (tc.exe on Windows)

Validate a recipe without running anything — no engine needed, so the default
environment suffices::

    pixi run kicker --validate-only examples/example_LaB6/input.json

Enable verbose output::

    pixi run -e gsasii kicker --verbose examples/example_LaB6/input.json

After ``pixi reinstall powderline`` the same program is available as the
installed command ``powderline <recipe.json> ...``. Flags: ``--output DIR``
(default ``output/`` next to the recipe), ``--validate-only``, ``--verbose``;
for ``gsasii.*`` recipes ``--use-server`` / ``--no-server`` / ``--server-timeout
SECONDS`` (how long to wait for the server's answer; default no limit); for ``topas.*``
recipes ``--topas-dir DIR`` / ``--topas-version V`` / ``--topas-timeout
SECONDS`` (each tc.exe run is stopped after this long; default 3600, 0 = no
limit). A flag given for a recipe
of another engine exits with an error. Exit status is 0 on success, 1
otherwise.

Running tests
-------------

Execute the engine-free test suite (core and TOPAS input generation; any
environment)::

    pixi run test

The per-engine suites are ``pixi run -e gsasii test-gsasii`` and
``pixi run -e easydiffraction test-easydiffraction``; ``pixi run test-all``
runs everything in the ``dev`` environment.

Or a selection, in one engine's environment::

    pixi run -e gsasii pytest tests/test_example_LaB6_regression.py -q

Recipe structure
----------------

A recipe is a JSON file with a fixed frame — ``schema_name``,
``core_schema_version``, ``engine_schema_version``, optional ``metadata``, and
``payload`` — whose payload is written in the named engine's own terms. Data
are embedded (no external files). A minimal ``gsasii.rietveld`` recipe (three
data points are shown; a real pattern has thousands, and ``fit_range`` must lie
inside them):

.. code-block:: json

    {
      "schema_name": "gsasii.rietveld",
      "core_schema_version": "0.1.0",
      "engine_schema_version": "0.1.0",
      "payload": {
        "xrd_data": {
          "tth": [1.0, 1.0036, 1.0071],
          "Itth": [30.6, 30.9, 30.2],
          "Itth_weights": [0.0327, 0.0324, 0.0331]
        },
        "fit_range": [1.0, 1.0071],
        "instrument": {
          "description": "28-ID-2",
          "radiation": {"type": "PXC", "wavelength": [0.1665, false]},
          "geometry": {"bank": 1, "azimuth": 0.0},
          "corrections": {
            "zero_shift": [0.0, false],
            "polarization": [0.99, false],
            "axial_divergence": [0.002, false]
          },
          "broadening": {
            "U": [1.163, true], "V": [-0.126, true], "W": [0.063, true],
            "X": [0.0, false], "Y": [0.0, false], "Z": [0.0, false]
          }
        },
        "background": {
          "chebyshev": {"num_coefficients": 6, "coefficients": [30, 0.6, 0.7, -0.4, -0.8, 0.9], "refine_flag": true}
        },
        "phases": {
          "LaB6": {
            "space_group": "P m -3 m",
            "unit_cell": {
              "a": [4.15682, false], "b": [4.15682, false], "c": [4.15682, false],
              "alpha": [90.0, false], "beta": [90.0, false], "gamma": [90.0, false]
            },
            "atoms": {
              "La": {"element": "La", "x": [0.0, false], "y": [0.0, false], "z": [0.0, false],
                     "occupancy": [1.0, false], "ADP": "Uiso", "Uiso": [0.0086, false]},
              "B":  {"element": "B",  "x": [0.2021, false], "y": [0.5, false], "z": [0.5, false],
                     "occupancy": [1.0, false], "ADP": "Uiso", "Uiso": [0.0092, false]}
            },
            "scale": [1.0, true]
          }
        },
        "refinement_controls": {"refinement_cycles": 5}
      }
    }

Every refinable quantity is a list: ``[value, refine_flag]`` in ``gsasii.*``
(no bounds), ``[value, refine_flag, min, max]`` in ``topas.*`` and
``easydiffraction.*``. The structural block (``space_group``, ``unit_cell``,
``atoms``) is the same in every engine and is checked against the symmetry at
validation; the instrument, background and controls are the engine's own, with
its units (GSAS-II's ``U, V, W`` in centidegree², TOPAS's and easydiffraction's
in degree², for instance). Unknown keys are errors.

See :doc:`schemas` for the five schemas and their minimum inputs,
:doc:`fields` for every field with its unit, :doc:`input-guidance` for how to
fill the data, structure and instrument blocks, and ``examples/`` for complete
working recipes (``examples/<case>/input.json`` for GSAS-II,
``examples/<case>/topas/`` and ``examples/<case>/easydiffraction/`` for the
other engines).

Output files
------------

.. note::

   **ESD and standard uncertainty.** PowderLine labels uncertainties ``esd``
   (estimated standard deviation) to match the terminology of the refinement
   engines it drives. The quantity reported is what is now called the
   *standard uncertainty* (s.u.): the IUCr recommends "standard uncertainty"
   in place of "estimated standard deviation" (Schwarzenbach et al., `Acta
   Cryst. A 51, 565-569 (1995) <https://doi.org/10.1107/S0108767395002340>`_), in
   line with `NIST Technical Note 1297
   <https://www.nist.gov/pml/nist-technical-note-1297>`_ (Taylor & Kuyatt,
   1994).

Every engine writes the same standardized reports, with fixed filenames, into
the output directory:

- ``refined_parameters.csv`` — all refined parameters with ESDs (9 columns):

  - ``parameter_name``: the engine's identifier (GSAS-II's ``::0:Scale``, a
    TOPAS parameter name, an easydiffraction path)
  - ``descriptive_name``: human-readable description
  - ``phase_name``, ``phase_idx``: phase associations (empty for non-phase parameters)
  - ``atom_name``, ``atom_idx``: atom associations (empty for non-atom parameters)
  - ``value``: refined value
  - ``esd``: estimated standard deviation
  - ``category``: parameter classification (instrument, background, cell, atom_position, …)

- ``<phase>_unit_cell_report.csv`` — unit cell parameters with ESDs (``parameter``,
  ``value``, ``esd``; a, b, c, alpha, beta, gamma, volume)
- ``<phase>_peak_list_report.csv`` — reflection list per phase (not written with
  easydiffraction's CrysFML calculator, which reports none)
- ``fit_profile.txt`` — ``two_theta, y_obs, y_weights, y_calc, y_diff, y_bkg, q_values, d_spacings``

- ``output_recipe.json`` and ``parameter_dispositions.csv`` — the recipe with the
  refined values written back, and each parameter's disposition (refinement runs)

Before every run ``powderline.run()`` removes its own fixed-name files from the
output directory (never the engine's), so a reused directory holds one run's
results. A failed run raises and writes none of them; the directory then holds
the engine's own files and ``failure.json`` (the failed envelope: reason,
message, traceback, the engine's last console lines).

**Native artifacts, always kept alongside:**

- gsasii: ``dummy.gpx`` (the GSAS-II project, reopenable in the GUI) and
  ``dummy.lst`` (GSAS-II's refinement log with its own Rwp and parameter tables)
- topas: ``<base>.inp`` and ``<base>.xye`` (what TOPAS was given) and what TOPAS
  wrote (``<base>_results.csv``, ``<base>_profile.txt``, per-phase peak lists,
  the background-only run ``<base>_bkg.inp`` / ``<base>_bkg_profile.txt``)
- easydiffraction: none beyond the reports

**Single peak fitting (``gsasii.spf``, ``topas.spf``) additional files:**

- ``single_peaks_report.txt`` (gsasii) / ``single_peaks_report.csv`` (topas) —
  per-peak position, intensity, widths
- ``peak_convergence_diagnostics.txt`` (gsasii) — only when a peak did not converge

**Note:** a simulation (nothing refined) writes no ``refined_parameters.csv``
for ``gsasii.*`` (there is nothing to list), while ``topas.*`` and
``easydiffraction.*`` write one with no rows; unit cell reports are generated
in every case, and in a simulation every ``esd`` is ``0.0`` (nothing was
refined, so every value is exact as stated).

Programmatic API
----------------

``powderline.run()`` is the main Python entry point. It validates the recipe,
hands it to the gateway its ``schema_name`` names, and returns results with the
tables as pandas DataFrames.

.. code-block:: python

   from pathlib import Path
   import powderline

   recipe = powderline.load_recipe_asset(Path("examples/example_LaB6/input.json"))
   output_dir = Path("/tmp/powderline_out")

   result = powderline.run(recipe, output_dir)        # needs the gsasii environment for this recipe

**Result keys (every engine):**

- ``result['status']`` (``"ok"``, or ``"generated"`` for a TOPAS run without a declared ``tc.exe``) and
  ``result['converged']`` (``True`` / ``False`` / ``None``); a failed run **raises**
  ``EngineExecutionError`` (the engine ran and failed) or ``ExecutionBackendError`` (it did not run),
  each with ``.reason`` and ``.result``
- ``result['rwp']``, ``result['r_exp']``, ``result['gof']``, ``result['chi2_red']`` — PowderLine's
  uniform statistics over the fit window (percent / dimensionless; ``None`` where undefined)
- ``result['simulation_mode']`` (bool)
- ``result['engine_details']`` (dict) — the engine's own statistics, ``parameters_requested``
  vs ``parameters_varied``, ``n_points``, and per engine ``converged`` / ``calculator`` / ``engine_version``
- ``result['warnings']`` (list of ``{code, message, field_path[, level]}``)
- ``result['elapsed_time']`` (float), ``result['method']`` (which execution path ran), ``result['run_id']``
- ``result['fit_profile']`` (DataFrame)
- ``result['unit_cell_data']`` (dict[str, DataFrame]) — per phase, keyed by phase name
- ``result['peak_list_data']`` (dict[str, DataFrame]) — per phase, keyed by phase name
- ``result['refined_parameters']`` (DataFrame) — the 9-column table
- ``result['spf_peaks']``, ``result['spf_convergence_diagnostics']`` (DataFrame) — single peak fitting; empty otherwise
- ``result['output_files']`` (list[str])

**Validate without running** (engine-free; works in the default environment):

.. code-block:: python

   checked = powderline.validate(recipe)        # -> ValidationResult
   checked.recipe                               # the gateway's validated model (e.g. GsasiiRietveldRecipe)
   checked.warnings                             # structured warnings, e.g. a default applied

   # or the run()-style summary dict (status, schema_name, core/engine schema
   # versions, phases, simulation_mode, warnings, the engine's controls):
   summary = powderline.run(recipe, output_dir, validate_only=True)

An invalid recipe raises pydantic's ``ValidationError`` listing every problem
with its field path.

**Engine options** are keyword arguments of ``run()``, forwarded to the gateway;
an option another engine does not take is a ``TypeError``:

.. code-block:: python

   result = powderline.run(recipe, output_dir, execution_mode='auto')         # gsasii: try the server, fall back to in-process (default)
   result = powderline.run(recipe, output_dir, execution_mode='server')       # gsasii: require the server
   result = powderline.run(recipe, output_dir, execution_mode='subprocess')   # gsasii: in-process only
   result = powderline.run(topas_recipe, output_dir, topas_version="6")       # topas: the installed TOPAS version (required to run)
   result = powderline.run(topas_recipe, output_dir, topas_dir=Path(r"C:\TOPAS6"), topas_version="6")

The GSAS-II server and client live at ``powderline.gateways.gsasii.server`` /
``powderline.gateways.gsasii.client`` (``GSASClient``); ``run()`` uses the
client internally for ``execution_mode='auto'`` / ``'server'``.

**Errors:** ``powderline.PowderLineError`` is the base of every PowderLine
error; ``GatewayNotInstalledError`` (no gateway of that name),
``EngineNotAvailableError`` (the gateway exists but its engine is not in this
environment — the message names the environment and the install command),
``EngineVersionError`` (installed engine outside the supported version),
``EngineExecutionError`` (the engine ran and failed, including a diverged
refinement).

Next steps
----------

- :doc:`schemas`, :doc:`fields`, :doc:`input-guidance` — the recipe contract
- :doc:`engine-behavior` — what each engine does with your recipe
- :doc:`DEVELOPMENT` — architecture and development workflow
- :doc:`TROUBLESHOOTING` — if you encounter issues
- :doc:`api` — the public API reference
