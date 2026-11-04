"""GSAS-II gateway — standard fit statistics, engine details and engine warnings after a run (A23, A41, A45, A125).

Read after the refinement from what GSAS-II stored:

- the profile arrays (``hist.data['data'][1]``: 2theta, yobs, weights, ycalc)
  and the fit window (``Limits``; excluded regions are masked), for core
  :mod:`powderline.fitstats` (standard keys ``rwp``, ``r_exp``, ``gof``,
  ``chi2_red``);
- ``P``, the varied-parameter count GSAS-II used: Rietveld
  ``Covariance['data']['Rvals']['Nvars']`` (it includes parameters GSAS-II then
  dropped as singular, EB-33), Peak List fit ``len(Peak List['sigDict'])``;
- GSAS-II's own values (``Rwp``; ``GOF``, which for a Rietveld refinement is
  sqrt(reduced chi^2) and for a peak fit the reduced chi^2 itself, EB-52;
  ``chisq``; ``Nobs``)
  under ``engine_details``, with ``parameters_requested`` (the recipe's
  independently refined parameters) next to ``parameters_varied`` (P);
- GSAS-II's refinement message (``Rvals['msg']``: parameters dropped as
  singular, SVD problems, limits), which ``G2strMain.Refine`` only prints
  (EB-32), as a structured warning; and a warning when GSAS-II varied fewer
  parameters than the recipe requested (A128);
- whether a Rietveld refinement converged (``Rvals['converged']``: the last
  cycle's chi^2 change below GSAS-II's tolerance), as ``engine_details['converged']``
  and the informative warning ``gsasii_fit_not_converged`` when it did not
  (values kept, as for easydiffraction, A166, A172; EB-85). A peak fit has no such
  flag (``DoPeakFit`` drops scipy's), so ``converged`` is ``None`` there.

A calculated pattern that is not finite inside the fit window means the
refinement diverged; GSAS-II does not report that as a failure (its wR shows
100 %, EB-52), so it is raised here as an ``EngineExecutionError`` (A130). A
simulation (``refinement_cycles == 1``) gets the same statistics as a
refinement, and every result says which it was (``simulation_mode``, A129).
A statistic that is undefined (no degrees of freedom) is ``None``.

A Rietveld refinement GSAS-II *aborted* (``Rvals['Aborted']``: no damped step
lowered chi-squared in a cycle; the last accepted values stay but the stored
pattern and wR are the rejected step's, finite and worthless) is the other face
of the same failure and is also raised as ``diverged`` (EB-99, re/29);
simulations are exempt.

For a peak fit (``gsasii.spf``) the result also carries ``peak_fit``: every
parameter ``DoPeakFit`` varied, by its own name, with the refined value and ESD
(re/21, KI-04). ``DoPeakFit`` fills no covariance block (the frozen extractor
therefore reports no refined-parameter rows for a peak fit); its names and ESDs
are ``Peak List['sigDict']`` and it writes the refined values in place --
``Back;n`` into ``Background[0][3 + n]``, ``BkPkpos|int|sig|gam;i`` into
``Background[1]['peaksList'][i]``, the instrument terms (``U`` .. ``Z``,
``SH/L``) into ``Instrument Parameters[0][name][1]`` and ``pos|int|sig|gam<i>``
into ``Peak List['peaks'][i]`` -- all in GSAS-II's own units, which are the
recipe's. The gateway's name-to-path map (``paths.py``) reads this block.

Runtime layer (called with GSAS-II objects); imports no GSAS-II module itself.
"""

from __future__ import annotations

import re

import numpy as np

from powderline.exceptions import EngineExecutionError, StructuredWarning
from powderline.fitstats import compute_fit_statistics
from powderline.schema_core import parameters_requested  # noqa: F401  (moved to core, re/05 D12; re-exported)


def _dropped(msg: str) -> int | None:
    match = re.search(r"(\d+)\s+Parameter\(s\) dropped", msg or "")
    return int(match.group(1)) if match else None


def _finite_or_none(v) -> float | None:
    """A plain float (the result crosses JSON in server mode), or ``None`` if undefined (NaN) or absent."""
    return None if v is None or not np.isfinite(v) else float(v)


def fit_report(proj, hist, recipe, engine_rwp, engine_rvals=None) -> dict:
    """``rwp``, ``r_exp``, ``gof``, ``chi2_red``, ``simulation_mode``, ``engine_details`` and ``warnings``.

    ``engine_rwp`` is the Rwp GSAS-II reported for the run (the executor's
    value); ``engine_rvals`` the peak fit's own residuals (``DoPeakFit``'s
    ``Rvals``; single peak fitting only). Raises ``EngineExecutionError`` when
    the refinement diverged (a non-finite calculated pattern in the fit window).
    """
    x, yobs, weights, ycalc = (hist.data["data"][1][i] for i in range(4))
    lo, hi = hist.data["Limits"][1]
    xs = np.ma.getdata(x)
    mask = (xs >= lo) & (xs <= hi) & ~np.ma.getmaskarray(x)
    yc = np.ma.getdata(ycalc)
    diverged = int(np.count_nonzero(~np.isfinite(yc[mask])))
    simulation = recipe.payload.refinement_controls.refinement_cycles == 1
    aborted = bool((proj.data.get("Covariance", {}).get("data", {}).get("Rvals", {}) or {}).get("Aborted"))
    if not diverged and not simulation and aborted:
        # GSAS-II's Hessian least squares returns 'Ouch#4' when no damped step lowers chi-squared in a cycle
        # (GSASIImath.HessianLSQ; e.g. a March-Dollase coefficient started at exactly 1.0 in a cubic phase, where the
        # averaged correction is stationary) and RefineCore records it as ``Rvals['Aborted']``. The project then
        # keeps the last *accepted* parameter vector (the start, in a first-cycle abort) while the stored pattern
        # and wR are the *rejected* trial step's -- finite but worthless, wR printed at the 100 % cap -- so no
        # statistic belongs to the parameters. GSAS-II's GUI keeps such a result behind "Minimizer halted because
        # chi**2 increased"; PowderLine is deliberately stricter and fails it (re/29, EB-99; EB-52's other face,
        # which the non-finite check above does not see).
        raise EngineExecutionError(
            "GSAS-II aborted the refinement: no step lowered chi-squared before its damping reached its limit (a "
            "parameter the data cannot move, or a model far from the data). GSAS-II keeps the last accepted "
            "parameter values but stores the rejected step's calculated pattern (finite but worthless; wR printed "
            "at its 100 % cap, EB-52), so no statistic would belong to the parameters and no result is reported. "
            "Start closer to the solution or refine fewer parameters; the GSAS-II files in the output directory "
            "show the attempt.",
            reason="diverged")
    if diverged:
        raise EngineExecutionError(
            f"GSAS-II's refinement diverged: the calculated pattern is not finite at {diverged} of "
            f"{int(np.count_nonzero(mask))} points in the fit window, so no result is reported (GSAS-II itself "
            "does not flag this; its wR shows 100 %, EB-52). Refine fewer or less correlated parameters, or start "
            "closer to the solution; the GSAS-II files in the output directory show the diverged parameters.",
            reason="diverged")
    spf = recipe.schema_name == "gsasii.spf"
    if spf:
        rvals = {k: v for k, v in (engine_rvals or {}).items() if k in ("GOF",)}
        n_params = len(hist.data.get("Peak List", {}).get("sigDict") or {})
    else:
        rvals = proj.data.get("Covariance", {}).get("data", {}).get("Rvals", {}) or {}
        n_params = int(rvals.get("Nvars", 0))
    stats = compute_fit_statistics(np.ma.getdata(yobs), yc, np.ma.getdata(weights), n_params, mask=mask)
    message = " ".join(str(rvals.get("msg", "")).split())
    num = _finite_or_none
    requested = parameters_requested(recipe)
    details = {
        "engine": "GSAS-II",
        "engine_version": _engine_version(),
        "rwp": num(engine_rwp),
        "gof": num(rvals.get("GOF")),
        "chi2": num(rvals.get("chisq")),
        "n_obs": None if rvals.get("Nobs") is None else int(rvals["Nobs"]),
        "n_points": stats.n_points,
        "parameters_requested": requested,
        "parameters_varied": n_params,
        "message": message or None,
        "converged": None if spf or rvals.get("converged") is None else bool(rvals["converged"]),
    }
    warnings = []
    if message:
        dropped = _dropped(message)
        warnings.append(StructuredWarning(
            code="gsasii_refinement_message",
            message=(f"GSAS-II reported: {message}"
                     + (f" ({dropped} parameter(s) dropped as singular are still counted in "
                        "parameters_varied, GSAS-II's own count, EB-33)" if dropped else "")),
            field_path=None))
    if details["converged"] is False and not simulation:
        warnings.append(StructuredWarning(
            code="gsasii_fit_not_converged",
            message=(f"GSAS-II stopped after {recipe.payload.refinement_controls.refinement_cycles} cycle(s) without "
                     "converging (its last chi^2 change was above its tolerance); the values are reported as they "
                     "stand. Likely causes: too few cycles (refinement_cycles) or poorly conditioned parameters "
                     "(strong correlations); check the ESDs and GSAS-II's message"),
            field_path="payload.refinement_controls.refinement_cycles"))
    if n_params < requested:
        warnings.append(StructuredWarning(
            code="gsasii_parameters_not_varied",
            message=(f"GSAS-II varied {n_params} parameter(s), but the recipe refines {requested} (one per "
                     "symmetry tie group); GSAS-II left the others fixed or dropped them"
                     + (" as singular without reporting which (single peak fitting, EB-53)" if spf else "")
                     + "; compare refined_parameters with the recipe's refine flags"),
            field_path=None))
    return {"rwp": num(stats.rwp), "r_exp": num(stats.rexp), "gof": num(stats.gof), "chi2_red": num(stats.chi2_red),
            "simulation_mode": simulation,
            "engine_details": details, "warnings": warnings,
            "peak_fit": {"parameters": peak_fit_parameters(hist)} if spf else None}


def _engine_version():
    """The GSAS-II runtime version that ran (A191), as the gateway's version check reads it; ``None`` if unreadable.

    Read here, in the process that ran GSAS-II, so a server run reports the server's engine."""
    try:
        from powderline.gateways.gsasii.gateway import installed_engine_version
        return installed_engine_version()
    except Exception:  # noqa: BLE001 - reporting only; never fail a finished refinement over it
        return None


#: value slots of a GSAS-II constant-wavelength peak row ``[pos, flag, int, flag, sig, flag, gam, flag]``
#: (``getHeaderInfo``; TOF / pink-beam rows carry ``alp`` and ``bet`` before ``sig`` -- gsasii 0.1.0 is PXC only)
_PEAK_SLOT = {"pos": 0, "int": 2, "sig": 4, "gam": 6}


def peak_fit_parameters(hist) -> list[dict]:
    """``[{"name", "value", "esd"}]`` for every parameter GSAS-II's peak fit varied (``Peak List['sigDict']``).

    The refined values are read from where ``DoPeakFit`` wrote them in the project (see the module docstring),
    in GSAS-II's units. A name whose value cannot be located in the project is reported with ``value: None``,
    so that the path map names it instead of dropping it. An ESD of exactly 0 is ``None``: ``DoPeakFit`` starts
    from ``sig = [0]*len(varyList)`` and leaves the zeros when its least squares ends on a singular matrix it
    cannot repair (it prints "Refinement failed - singular matrix" and nothing else; the values are the last
    cycle's), so 0 means undetermined, not exact (re/21 review).
    """
    data = hist.data
    peak_list = data.get("Peak List") or {}
    background = data.get("Background") or [[], {}]
    inst = (data.get("Instrument Parameters") or [{}])[0]
    peaks = peak_list.get("peaks") or []
    rows = []
    for name, esd in (peak_list.get("sigDict") or {}).items():
        value = None
        base, _, index = str(name).partition(";")
        peak = re.fullmatch(r"(pos|int|sig|gam)(\d+)", str(name))
        if base == "Back" and index.isdigit() and 3 + int(index) < len(background[0]):
            value = background[0][3 + int(index)]
        elif base.startswith("BkPk") and base[4:] in _PEAK_SLOT and index.isdigit() and len(background) > 1:
            rows_bk = (background[1] or {}).get("peaksList") or []
            if int(index) < len(rows_bk):
                value = rows_bk[int(index)][_PEAK_SLOT[base[4:]]]
        elif name in inst and isinstance(inst[name], (list, tuple)) and len(inst[name]) > 1:
            value = inst[name][1]
        elif peak and int(peak.group(2)) < len(peaks):
            value = peaks[int(peak.group(2))][_PEAK_SLOT[peak.group(1)]]
        esd = _finite_or_none(esd)
        rows.append({"name": str(name), "value": _finite_or_none(value), "esd": None if esd == 0 else esd})
    return rows
