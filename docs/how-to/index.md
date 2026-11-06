# How-to guides

Each guide gets one task done. It starts with the goal and what you need,
then gives numbered steps and a check.

- [Calibrate the instrument with a standard](calibrate-instrument.md): refine a standard once and reuse its peak shape and corrections for your samples.
- [Refine a structure](refine-structure.md): refine the cell, atom positions, occupancies, displacement parameters, ions, texture and several phases.
- [Model disorder near special positions](disorder.md): write a split site that every engine reads the same way.
- [Fit single peaks](single-peak-fitting.md): fit individual peaks without a crystal structure, in GSAS-II or TOPAS.
- [Simulate a pattern](simulate.md): calculate a pattern from a model without fitting anything.
- [Run a series](sequential-refinement.md): refine against many patterns in sequence, each step starting from the last.
- [Use PowderLine from Python and in pipelines](python-pipelines.md): validate and run recipes from your own code, and handle failures.
- [Run at a beamline](beamline-operation.md): the GSAS-II server, batches of recipes and unattended runs on shared workstations.
- [Run TOPAS recipes](run-topas.md): run TOPAS 6 on Windows, or write its input anywhere.
- [Troubleshoot](troubleshooting.md): what an error message means and how to fix it.

```{toctree}
:hidden:
:maxdepth: 1

calibrate-instrument
refine-structure
disorder
single-peak-fitting
simulate
sequential-refinement
python-pipelines
beamline-operation
run-topas
troubleshooting
```
