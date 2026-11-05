"""GSAS-II gateway — refinement execution and orchestration (run_refinement).

Moved verbatim from ``powderline/kicker.py`` (multi-engine refactor, re/01).
"""
from __future__ import annotations
import uuid
from typing import Any
from pathlib import Path
from GSASII import GSASIIscriptable as G2  # type: ignore
from powderline.gateways.gsasii.schema import GsasiiRietveldRecipe, GsasiiSpfRecipe, gsasii_iparm1
from powderline.gateways.gsasii.fit_report import fit_report
from powderline.gateways.gsasii.sites import check_sites
from powderline.exceptions import EngineExecutionError
from powderline.schema_core import fit_limits_on_data

from powderline.gateways.gsasii.helpers import (
    DEFAULT_HIST_SCALE_REFINE_FLAG,
    DEFAULT_HIST_SCALE_VAL,
    OUTPUT_NAMING,
)
from powderline.gateways.gsasii.project import (
    add_phases_from_dict,
    add_powder_histogram_from_arrays,
)
from powderline.gateways.gsasii.setters import (
    set_chebyshev_background,
    set_fit_range_hist,
    set_hist_scale,
    set_instrument_parameterization,
    set_phase_parameterization,
    set_refinement_cycles,
    set_single_peak_background,
    set_single_peaks,
)
from powderline.gateways.gsasii.extractors import (
    _extract_fit_profile,
    _extract_phase_reports,
    _extract_refined_parameters,
    _extract_spf_peak_report,
    extract_refined_params_from_project,
)



def _refine_with_message(proj) -> tuple[bool, str]:
    """Run the project refinement, returning (ok, GSAS-II failure message).

    ``G2Project.refine()`` calls ``G2strMain.Refine`` and DISCARDS its
    ``(OK, Rvals)`` return, so failure text like "Invalid metric tensor for
    phase #0" reaches only the console — callers see a silent no-Rwp failure.
    Mirror the non-sequential branch of ``refine()`` (index, constraint
    check, Refine, reload) to keep ``Rvals['msg']``. Any surprise from
    GSAS-II internals falls back to the plain ``proj.refine()`` so behavior
    is never worse than before.
    """
    try:
        from GSASII import GSASIIstrIO as G2stIO
        from GSASII import GSASIIstrMain as G2strMain

        seq_setting = proj.data['Controls']['data'].get('Seq Data', [])
        if not seq_setting:
            proj.index_ids()  # saves the project, as refine() does
            errmsg, _warnmsg = G2stIO.ReadCheckConstraints(proj.filename)
            if errmsg:
                return False, f"Constraint error: {errmsg}"
            ret = G2strMain.Refine(proj.filename, makeBack=False)
            proj.reload()
            ok, rvals = (ret if isinstance(ret, tuple) and len(ret) == 2
                         else (True, {}))
            msg = rvals.get('msg', '') if isinstance(rvals, dict) else ''
            msg = msg.replace('**** ERROR: Refinement failed ****', '').strip()
            return bool(ok), msg
    except (ImportError, AttributeError, KeyError, TypeError):
        pass  # GSAS-II internals changed: fall back to the plain call below

    proj.refine()
    return True, ''


def execute_rietveld_refinement(
    proj: Any,
    hist: Any,
    recipe: GsasiiRietveldRecipe,
    verbose: bool
) -> dict:
    """
    Execute standard GSAS-II Rietveld refinement.

    This replaces the previous "structural_only" strategy.

    Args:
        proj: GSAS-II project object
        hist: Histogram object
        recipe: Validated recipe model
        verbose: Print detailed progress

    Returns:
        Result dict with success, rwp, elapsed_time
    """
    controls = recipe.payload.refinement_controls

    if verbose:
        print(f"\n{'='*60}")
        print(f"Executing Rietveld Refinement")
        print(f"  Cycles: {controls.refinement_cycles}")
        print(f"{'='*60}\n")

    # Execute refinement (keeping GSAS-II's failure message, which
    # G2Project.refine() would otherwise discard)
    refine_ok, g2_msg = _refine_with_message(proj)

    # Extract Rwp
    rwp_final = hist.residuals.get("wR")

    if not refine_ok or rwp_final is None:
        if g2_msg:
            error = f"Rietveld refinement failed: {' '.join(g2_msg.split())}"
        else:
            error = ("Rietveld refinement produced no Rwp — proj.refine() "
                     "may have failed silently")
        return {
            'success': False,
            'rwp': None,
            'error': error,
        }

    if verbose:
        print(f"Rietveld refinement complete. Final Rwp: {rwp_final:.3f}%\n")

    return {
        'success': True,
        'rwp': rwp_final
    }


def execute_spf_refinement(
    proj: Any,
    hist: Any,
    recipe: GsasiiSpfRecipe,
    verbose: bool
) -> dict:
    """
    Execute single peak fitting refinement.

    This replaces the previous "peaks_only" strategy.

    Args:
        proj: GSAS-II project object
        hist: Histogram object
        recipe: Validated recipe model
        verbose: Print detailed progress

    Returns:
        Result dict with success, rwp, elapsed_time
    """
    controls = recipe.payload.refinement_controls
    spf_mode = "useIP" if controls.single_peak_fitting_mode.use_instrument_profile else "hold"

    if verbose:
        print(f"\n{'='*60}")
        print(f"Executing Single Peak Fitting")
        print(f"  Mode: {spf_mode} ({'use instrument profile' if spf_mode == 'useIP' else 'refine peak widths'})")
        print(f"  Cycles: {controls.refinement_cycles}")
        print(f"{'='*60}\n")

    # Execute single peak fitting (cycles already set in step 10)
    try:
        peak_result = hist.refine_peaks(mode=spf_mode)
    except TypeError as exc:  # DoPeakFit failed and returned None; refine_peaks then indexes it (EB-38)
        if "'NoneType' object is not subscriptable" not in str(exc):  # any other TypeError keeps its own traceback
            raise
        raise EngineExecutionError(
            "GSAS-II's peak fit failed: DoPeakFit returned no result (GSAS-II prints the reason only in its "
            "debug mode; GSAS-II quirk EB-38). Check the peak positions, widths and fit range.",
            reason="peak_fit_failed",
        ) from exc

    # Extract Rwp from peak_result
    rwp_final = peak_result[3].get("Rwp") if len(peak_result) > 3 else None

    if rwp_final is None:
        return {
            'success': False,
            'rwp': None,
            'error': "Single peak fitting produced no Rwp — hist.refine_peaks() may have failed silently",
        }

    if verbose:
        print(f"Single peak fitting complete. Final Rwp: {rwp_final:.3f}%\n")

    return {
        'success': True,
        'rwp': rwp_final,
        'engine_rvals': peak_result[3],  # DoPeakFit's own residuals, for engine_details (A23)
    }


# Schema executor registry
SCHEMA_EXECUTORS = {
    'gsasii.rietveld': execute_rietveld_refinement,
    'gsasii.spf': execute_spf_refinement,
}


########################################
# Kicker script for PowderLine
########################################

def run_refinement(recipe: GsasiiRietveldRecipe | GsasiiSpfRecipe, output_dir: Path, verbose: bool = False, method: str = 'server') -> dict:
    """
    Internal execution engine: run a GSAS-II refinement using already-loaded libraries.

    This function is the single execution entry point used by all paths:
    - the GSAS-II server (``gateways/gsasii/server.py``) calls it directly after receiving an HTTP request
      (``method='server'``).
    - ``GSASClient._submit_via_subprocess()`` calls it in-process as the
      subprocess fallback (``method='subprocess'``). Despite the method name,
      no OS subprocess is spawned; see :meth:`GSASClient._submit_via_subprocess`.

    For programmatic use, prefer ``powderline.run()`` which validates the recipe,
    dispatches to the appropriate backend, and normalises all structured data
    fields to pandas DataFrames.

    Args:
        recipe: Validated ``gsasii.rietveld`` / ``gsasii.spf`` recipe model (call
            ``powderline.validate()`` first if starting from a raw dict).
        output_dir: Directory where output files are written (``dummy.gpx``,
            ``dummy.lst``, CSV reports, ``fit_profile.txt``). Must exist or be
            creatable.
        verbose: If True, print detailed progress to stdout.
        method: Execution method identifier string stored in the return dict.
            Callers set this to ``'server'`` or ``'subprocess'`` so downstream
            consumers know how the run was executed. Default ``'server'``.

    Returns:
        dict with keys:

        - ``success`` (bool)
        - ``run_id`` (str) — UUID4 string
        - ``rwp`` (float | None)
        - ``elapsed_time`` (float) — wall-clock seconds
        - ``method`` (str) — value of the ``method`` argument
        - ``output_files`` (list[str]) — paths of all files written to
          ``output_dir`` (informational)
        - ``fit_profile`` (dict) — column-oriented dict (JSON-serializable);
          normalised to ``pd.DataFrame`` by ``run()``
        - ``unit_cell_data`` (dict) — ``{phase: list-of-records}``
        - ``peak_list_data`` (dict) — ``{phase: list-of-records}``
        - ``refined_parameters`` (list) — list-of-records (9-column schema)
        - ``spf_peaks`` (dict) — column-oriented dict; populated for
          ``gsasii.spf`` runs, empty dict otherwise
        - ``spf_convergence_diagnostics`` (dict) — column-oriented dict;
          populated when SPF peaks have convergence issues, empty dict otherwise
        - ``error`` (str) — present when ``success=False``
        - ``traceback`` (str) — present when an unhandled exception occurred

    Example::

        import powderline
        from powderline.gateways.gsasii.routing import run_refinement
        recipe = powderline.validate(recipe_dict).recipe  # a gsasii.rietveld recipe dict
        result = run_refinement(recipe, Path('output'), verbose=True)
        print(f"Rwp: {result['rwp']:.3f}%  [run_id={result['run_id']}]")
    """
    # Assign a unique ID for this refinement run immediately, before any work begins,
    # so every exit path (success, GSAS-II failure, unexpected exception) can include
    # it in the returned dict and server logs.
    run_id = str(uuid.uuid4())
    import time
    start_time = time.time()

    try:
        # 1. Get xrd_data from validated model (file-less: no sample_name)
        xrd_data = recipe.payload.xrd_data

        # 2. Construct name and initialize project using standard naming
        gpx_path = output_dir / OUTPUT_NAMING.gpx_filename
        proj = G2.G2Project(newgpx=str(gpx_path))

        # 3. Instrument parameters: GSAS-II's Iparm1 built from the instrument block (A99, A103)
        iparm1 = gsasii_iparm1(recipe.payload.instrument)

        # 4. Add histogram - phase1B update: xrd_data is now a dict with arrays, instrument_init is list of dicts
        try:
            hist = add_powder_histogram_from_arrays(
                proj=proj,
                tth_array=xrd_data.tth,
                intensity_array=xrd_data.Itth,
                intensity_weights_array=xrd_data.Itth_weights,
                histogram_name=OUTPUT_NAMING.histogram_name,
                instrument_prm_dict=iparm1,
                comments=None,
                phases=None, # Optionally could link to phases if order of operations
            )
        except EngineExecutionError:  # R30: PowderLine's own failure (divergence, site, peak fit) propagates
            raise
        except Exception as e:
            import traceback as _tb
            tb = _tb.format_exc()
            elapsed_time = time.time() - start_time
            return {
                'success': False,
                'rwp': None,
                'run_id': run_id,
                'error': f"Failed to load XRD data or instrument parameters: {str(e)}",
                'traceback': tb,
                'elapsed_time': elapsed_time,
                'method': method
            }

        # After adding histogram, set hist scale and refine flag to defaults
        set_hist_scale(proj, hist, hist_scale_val=DEFAULT_HIST_SCALE_VAL, hist_scale_refine_flag=DEFAULT_HIST_SCALE_REFINE_FLAG, print_info=verbose)

        # 5. Set fit range
        fit_range = fit_limits_on_data(recipe.payload.fit_range, recipe.payload.xrd_data)  # on data points (A149, R17)
        if fit_range != (None, None):
            set_fit_range_hist(hist, fit_range, print_info=verbose)

        # 6. Set background - Chebyshev and single peaks
        if recipe.payload.background is not None:
            background_dict = recipe.payload.background.model_dump(mode='json')
            if recipe.payload.background.chebyshev is not None:
                chebyshev_dict = background_dict.get('chebyshev')
                set_chebyshev_background(proj, hist, chebyshev_dict, print_info=verbose)
            if recipe.payload.background.single_peaks is not None:
                bkg_single_peaks_dict = background_dict.get('single_peaks')
                set_single_peak_background(proj, hist, bkg_single_peaks_dict, print_info=verbose)

        # 6b. Set single peaks (Peak List mode for non-background peaks)
        if getattr(recipe.payload, 'single_peaks', None) is not None:  # gsasii.spf only
            single_peaks_dict = recipe.payload.single_peaks.model_dump(mode='json')
            # Check if dict has any actual peak data before calling setter
            has_peak_data = False
            for key in ['positions', 'intensities', 'pv_gaussian_sigma_sq', 'pv_lorentzian_gamma']:
                if key in single_peaks_dict and single_peaks_dict[key] and len(single_peaks_dict[key]) > 0:
                    has_peak_data = True
                    break
            if has_peak_data:
                set_single_peaks(proj, hist, single_peaks_dict, print_info=verbose)

        # 7. Add phases (if present)
        if getattr(recipe.payload, 'phases', None) is not None and len(recipe.payload.phases) > 0:  # gsasii.rietveld only
            phases_dict = recipe.payload.model_dump(mode='json')['phases']
            add_phases_from_dict(proj, hist, phases_dict, print_info=verbose)
            check_sites(proj, recipe)  # GSAS-II's reading of each atom's site (A117; EB-40, EB-05)

            # 8. Parameterize phases
            holds = set_phase_parameterization(proj, hist, phases_dict, print_info=verbose)

            # 8b. Apply Hold constraints for per-parameter refine flags
            # (fixed members of partially-refined DOF groups).
            # The isinstance guard keeps mocked-setter unit tests inert.
            if isinstance(holds, list) and holds:
                proj.add_HoldConstr(holds)
                if verbose:
                    print(f"Applied {len(holds)} Hold constraint(s): {holds}")

        # 9. Set instrument parameterization
        instrument_param_dict = recipe.payload.instrument.model_dump(mode='json')  # single source (A99, A103)
        if instrument_param_dict is not None:
            instrument_param_changes = False
            for key, value in instrument_param_dict.items():
                if isinstance(value, dict):
                    if any(v is not None for v in value.values()):
                        instrument_param_changes = True
                        break
                elif value is not None:
                    instrument_param_changes = True
                    break
            if instrument_param_changes:
                set_instrument_parameterization(proj, hist, instrument_param_dict, print_info=verbose)

        # 10. Get refinement controls and set refinement cycles
        controls = recipe.payload.refinement_controls

        # 10a. Validate single_peak_fitting_mode requirements (only for gsasii.spf)
        if recipe.schema_name == 'gsasii.spf':
            if controls.single_peak_fitting_mode is None:
                raise ValueError(
                    f"Schema '{recipe.schema_name}' requires "
                    f"'single_peak_fitting_mode' to be configured in refinement_controls."
                )

        num_cycles = controls.refinement_cycles
        if num_cycles != proj.get_Controls('cycles'):
            set_refinement_cycles(proj, num_cycles, print_info=verbose)

        # 11. Execute refinement using schema-based dispatch
        executor = SCHEMA_EXECUTORS.get(recipe.schema_name)
        if executor is None:
            raise ValueError(f"Unknown schema_name: {recipe.schema_name}. Valid options: {list(SCHEMA_EXECUTORS.keys())}")

        try:
            result = executor(proj, hist, recipe, verbose)

            # Check if executor succeeded
            if not result.get('success', False):
                elapsed_time = time.time() - start_time
                return {
                    'success': False,
                    'rwp': None,
                    'run_id': run_id,
                    'error': result.get(
                        'error',
                        f"Refinement executor '{recipe.schema_name}' returned success=False without an error message",
                    ),
                    'traceback': result.get('traceback'),
                    'elapsed_time': elapsed_time,
                    'method': method
                }

        except EngineExecutionError:  # R30: PowderLine's own failure (divergence, site, peak fit) propagates
            raise
        except Exception as e:
            import traceback as _tb
            tb = _tb.format_exc()
            elapsed_time = time.time() - start_time
            return {
                'success': False,
                'rwp': None,
                'run_id': run_id,
                'error': f"Refinement failed: {str(e)}",
                'traceback': tb,
                'elapsed_time': elapsed_time,
                'method': method
            }

        # Save GPX file after successful refinement
        proj.save(str(gpx_path))

        # 12. Extract final Rwp from result
        rwp = result.get('rwp')

        # 12a. PowderLine's checks (divergence, abort, convergence) run before any result table is written, so a
        #      failed run leaves GSAS-II's own files only, as the other engines do (ledger row R38, re/30)
        statistics = fit_report(proj, hist, recipe, engine_rwp=rwp, engine_rvals=result.get('engine_rvals'))

        # --- Post-refinement data extraction ---
        # Each helper writes its own output files and returns JSON-serializable data.
        # run() normalises all dicts/lists to DataFrames for programmatic callers.

        fit_profile_data = _extract_fit_profile(hist, output_dir)

        spf_peaks_data, spf_diagnostics_data = _extract_spf_peak_report(
            proj, hist, recipe, output_dir, verbose
        )

        # Extract refined parameters (needed for unit cell ESDs in _extract_phase_reports)
        if verbose:
            print("\nExtracting refined parameters with ESDs...")

        param_dict = extract_refined_params_from_project(proj, verbose=verbose)

        # Only raise if GSAS-II populated a varyList (i.e. parameters were actually varied)
        # but we still got nothing back. An empty param_dict with an empty varyList is
        # expected and correct for simulation mode (refinement_cycles=1, all params locked)
        # and for gsasii.spf (no standard covariance matrix produced).
        cov_vary_list = (
            proj.data.get('Covariance', {}).get('data', {}).get('varyList', [])
        )
        if len(param_dict) == 0 and len(cov_vary_list) > 0:
            raise RuntimeError(
                "GSAS-II populated a varyList but refined parameter extraction returned "
                "empty results; covariance data may be corrupt. "
                "Ensure refinement completed successfully. "
                "Check the .lst file for GSAS-II error details."
            )

        # --- .lst fallback (disabled) ---
        unit_cell_data, peak_list_data = _extract_phase_reports(
            proj, hist, recipe, param_dict, output_dir
        )

        refined_parameters_data = _extract_refined_parameters(
            param_dict, output_dir, proj, verbose
        )

        elapsed_time = time.time() - start_time
        return {
            'success': True,
            'run_id': run_id,
            'rwp': rwp,
            'elapsed_time': elapsed_time,
            'method': method,
            'output_files': [str(f) for f in output_dir.glob('*')],
            'fit_profile': fit_profile_data,
            'unit_cell_data': unit_cell_data,
            'peak_list_data': peak_list_data,
            'refined_parameters': refined_parameters_data,
            'spf_peaks': spf_peaks_data,
            'spf_convergence_diagnostics': spf_diagnostics_data,
            # Standard fit statistics from core fitstats; 'rwp' becomes the standard Rwp and
            # GSAS-II's own values go to engine_details (A23, A45, A125); computed at 12a (R38)
            **statistics,
        }

    except EngineExecutionError:  # R30: PowderLine's own failure (divergence, site, peak fit) propagates
        raise
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        import logging
        logging.getLogger(__name__).error("run_refinement failed:\n%s", tb)
        elapsed_time = time.time() - start_time
        return {
            'success': False,
            'rwp': None,
            'run_id': run_id,
            'error': str(e),
            'traceback': tb,
            'elapsed_time': elapsed_time,
            'method': method
        }
