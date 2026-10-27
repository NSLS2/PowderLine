Getting Started
===============

Installation
------------

PowderLine uses `pixi <https://pixi.sh>`_ for reproducible conda environments::

    # Install dependencies (first time)
    pixi install

    # Activate environment
    pixi shell

Basic Usage
-----------

Run a refinement from a JSON recipe::

    pixi run kicker examples/example_LaB6/input.json

Validate a recipe without running refinement::

    pixi run kicker --validate-only examples/example_LaB6/input.json

Enable verbose output::

    pixi run kicker --verbose examples/example_LaB6/input.json

Running a recipe through TOPAS v7 instead of GSAS-II
----------------------------------------------------

The same JSON recipe can be driven through TOPAS v7 (Bruker), not just GSAS-II.
The TOPAS path imports **zero** GSAS-II, so it runs with no GSAS-II installed at
all. Translate a ``GSASII_Rietveld`` or ``GSASII_SPF``
recipe into a TOPAS v7 ``.inp`` + ``.xye`` pair::

    pixi run topas-kicker examples/example_LaB6/input.json

This writes ``<name>.inp`` and ``<name>.xye`` under
``examples/<name>/output/topas/``; if ``tc.exe`` is discoverable it also runs the
refinement and parses the results into the same standardized reports the GSAS-II
path produces. Use ``--output DIR`` to choose a directory, ``--validate-only`` to
check translatability without writing files, and ``--topas-dir`` /
``--topas-version`` to locate ``tc.exe``.

From Python, select the engine with a single flag::

    import powderline
    result = powderline.run(recipe, output_dir, engine="topas")   # vs engine="gsasii"

A third engine, open-source `easydiffraction
<https://easydiffraction.org>`_, is available as
``engine="easydiffraction"`` after installing the optional pixi environment
(``pixi install -e easydiff``; easydiffraction needs Python ≥3.12, the default
environment is untouched). It consumes the same recipes and returns the same
result dictionary — see the integration guide's easydiffraction section for
its v1 capability list.

``engine="topas"`` returns the same result dictionary as the GSAS-II engine
(plus ``rwp``/``r_exp``/``gof``). The bundled ``GSASII_Rietveld`` / ``GSASII_SPF``
example recipes translate to TOPAS, and the committed golden set has been
validated against a real ``tc.exe`` run on Windows (``example_template`` is a
fill-in-the-blanks skeleton and is rejected with a clear error by design).
Refined **lattice parameters agree with GSAS-II to
sub-percent** across the example set; correlated profile terms (instrument
U..Z, size vs. strain) are not individually comparable between engines, but
cell, scale, and occupancy are reliable.

Running Tests
-------------

Execute the test suite::

    pixi run test

Or with pytest directly::

    pixi run pytest -v

Recipe Structure
----------------

A PowderLine recipe is a JSON file describing refinement parameters (Schema 0.26.0).
All examples use schema 0.26.0 file-less payloads with embedded data.

.. code-block:: json

    {
      "schema_name": "GSASII_Rietveld",
      "schema_version": "0.26.0",
      "payload": {
        "xrd_data": {
          "tth": [10.0, 10.5, 11.0],
          "Itth": [1234.5, 1230.2, 1228.9],
          "Itth_weights": [1.0, 1.0, 1.0]
        },
        "instrument": {
          "description": "28-ID-2",
          "initialization": [
            {
              "Type": ["PXC", "PXC", false],
              "Bank": [1, 1, false],
              "Lam": [0.45236, 0.45236, false],
              "Zero": [0.0, 0.0, false],
              "Polariz.": [0.99, 0.99, false],
              "U": [2.0, 2.0, false],
              "V": [-2.0, -2.0, false],
              "W": [5.0, 5.0, false],
              "X": [0.0, 0.0, false],
              "Y": [0.0, 0.0, false],
              "Z": [0.0, 0.0, false],
              "SH/L": [0.002, 0.002, false]
            },
            {}
          ],
          "parameterization": {
            "wavelength": [0.45236, false, null, null],
            "broadening": {
              "U": [null, true, null, null],
              "V": [null, true, null, null],
              "W": [null, true, null, null]
            },
            "corrections": {
              "zero_shift": null,
              "axial_divergence": null
            }
          }
        },
        "phases": {
          "MyPhase": {
            "structure": {
              "phase_name": "MyPhase",
              "space_group": "P m -3 m",
              "unit_cell": {
                "a": 4.157,
                "b": 4.157,
                "c": 4.157,
                "alpha": 90.0,
                "beta": 90.0,
                "gamma": 90.0,
                "volume": 71.83
              },
              "atoms": {
                "La": {
                  "element": "La",
                  "x": 0.0,
                  "y": 0.0,
                  "z": 0.0,
                  "occupancy": 1.0,
                  "ADP": "Uiso",
                  "Uiso": 0.008,
                  "Multiplicity": 1
                }
              }
            },
            "parameterization": {
              "scale": [1.0, true, null, null]
            }
          }
        },
        "refinement_controls": {
          "refinement_cycles": 5
        }
      }
    }

``initialization`` holds the GSAS-II instrument parameters (the contents of a
``.instprm`` file) as ``[value, value, refine_flag]`` lists; ``parameterization``
lists what to refine, with ``null`` values meaning "start from the
``initialization`` value". See ``examples/`` for complete working recipes, and
:doc:`building-recipes` for every section, how to validate a recipe, and how to
build one from your own CIF, instrument, and data files.

Output Files
------------

After refinement, PowderLine generates standardized outputs with fixed filenames (Schema 0.26.0):

.. note::

   **ESD and standard uncertainty.** PowderLine labels uncertainties ``esd``
   (estimated standard deviation) to match the terminology of the refinement
   engines it drives. The quantity reported is what is now called the
   *standard uncertainty* (s.u.): the IUCr recommends "standard uncertainty"
   in place of "estimated standard deviation" (Schwarzenbach et al., `Acta
   Cryst. A51, 565 (1995) <https://doi.org/10.1107/S0108767395002340>`_), in
   line with `NIST Technical Note 1297
   <https://www.nist.gov/pml/nist-technical-note-1297>`_ (Taylor & Kuyatt,
   1994).

**GSAS-II files:**

- ``dummy.gpx`` - GSAS-II project file (reopenable in GUI)
- ``dummy.lst`` - Human-readable refinement log with Rwp and parameter tables

**Refinement results:**

- ``refined_parameters.csv`` - All refined parameters with ESDs (9 columns):

  - ``parameter_name``: GSAS-II internal identifier
  - ``descriptive_name``: Human-readable description
  - ``phase_name``, ``phase_idx``: Phase associations (null for non-phase parameters)
  - ``atom_name``, ``atom_idx``: Atom associations (null for non-atom parameters)
  - ``value``: Refined parameter value
  - ``esd``: Estimated standard deviation from covariance matrix
  - ``category``: Parameter classification (instrument, background, cell, atom_position, etc.)

- ``<phase>_unit_cell_report.csv`` - Unit cell parameters with ESDs (3 columns per phase):

  - ``parameter``: a, b, c, alpha, beta, gamma, volume
  - ``value``: Refined unit cell parameter
  - ``esd``: Estimated standard deviation

- ``<phase>_peak_list_report.csv`` - Reflection list (hkl, d-spacing, 2θ, intensities per phase)
- ``fit_profile.txt`` - Observed/calculated/background/difference intensities

**Single peak fitting (SPF) mode additional files:**

- ``single_peaks_report.txt`` - Peak fit results (position, width, intensity)
- ``peak_convergence_diagnostics.txt`` - Convergence warnings

**Note:** Simulation mode (``refinement_cycles=1`` with all ``refine_flag=false``) does not generate ``refined_parameters.csv`` since no parameters are refined.

Programmatic API
----------------

``powderline.run()`` is the main Python entry point. It validates the recipe,
dispatches to the GSAS-II server (or falls back to in-process execution), and
returns results as pandas DataFrames.

.. code-block:: python

   import json
   from pathlib import Path
   import powderline

   recipe_path = Path("examples/example_LaB6/input.json")
   recipe = json.loads(recipe_path.read_text())
   output_dir = Path("/tmp/powderline_out")
   output_dir.mkdir(exist_ok=True)

   result = powderline.run(recipe, output_dir)

**Normal refinement — result keys:**

- ``result['success']`` (bool): True if refinement converged
- ``result['rwp']`` (float): Weighted profile R-factor
- ``result['elapsed_time']`` (float): Wall-clock seconds
- ``result['fit_profile']`` (DataFrame): Observed/calculated/background/difference intensity columns
- ``result['unit_cell_data']`` (dict[str, DataFrame]): Per-phase unit cell parameters and ESDs, keyed by phase name
- ``result['peak_list_data']`` (dict[str, DataFrame]): Per-phase hkl reflection lists, keyed by phase name
- ``result['refined_parameters']`` (DataFrame): 9-column parameter table with ESDs
- ``result['spf_peaks']`` (DataFrame): SPF peak positions, widths, intensities; empty for Rietveld
- ``result['spf_convergence_diagnostics']`` (DataFrame): SPF convergence warnings; empty for Rietveld
- ``result['output_files']`` (list[str]): Paths of all written output files

**Validate-only mode (no refinement executed):**

.. code-block:: python

   result = powderline.run(recipe, output_dir, validate_only=True)
   # result keys: success, rwp (None), elapsed_time, method ('validate_only'),
   #              schema_name, schema_version, phases, refinement_cycles, simulation_mode

**SPF DataFrame example:**

.. code-block:: python

   result = powderline.run(spf_recipe, output_dir)
   df = result['spf_peaks']
   # Columns: position_2theta, intensity, sigma, sigma_squared, gamma,
   #          fwhm_gaussian, fwhm_lorentzian, fwhm_pseudovoigt,
   #          integral_breadth_gaussian, integral_breadth_lorentzian,
   #          integral_breadth_pseudovoigt, fwhm_gsas_verification,
   #          converged, convergence_detail

**Execution mode control:**

.. code-block:: python

   result = powderline.run(recipe, output_dir, execution_mode='auto')         # default: try server, fall back to subprocess
   result = powderline.run(recipe, output_dir, execution_mode='server')       # require the HTTP server
   result = powderline.run(recipe, output_dir, execution_mode='subprocess')   # in-process execution

Next Steps
----------

- Read :doc:`DEVELOPMENT` for comprehensive project understanding
- Explore examples in ``examples/`` directory
- Consult :doc:`TROUBLESHOOTING` if you encounter issues
- See :doc:`api` for detailed function documentation
