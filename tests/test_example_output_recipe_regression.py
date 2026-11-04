"""The output recipe and parameter dispositions committed with the example references (KI-04, KI-15).

Every committed ``examples/<case>/output/output_recipe.json`` (and a per-engine
``examples/<case>/<engine>/output/output_recipe.json``) is a regression reference
like the tables beside it. Two checks:

- engine-free: each committed output recipe validates exactly when KI-15 says it
  should (four references end on unphysical values by design; their invalidity is
  itself the reference);
- GSAS-II: a fresh ``kicker --no-server`` run of each older gsasii example that
  carries the two files reproduces ``output_recipe.json`` (the run-specific
  ``metadata.powderline_provenance`` block excluded) and ``parameter_dispositions.csv``
  within the regression tolerances of ``refined_params_match``
  (docs/regression-tolerance.md), and the CLI reports the recipe's validity as KI-15
  says.
"""

import json
from pathlib import Path

import pandas as pd
import pytest

from subprocess_utils import (
    dispositions_match,
    kicker_command,
    output_recipe_mismatches,
    run_subprocess_utf8,
)

REPO = Path(__file__).resolve().parent.parent
EXAMPLES = REPO / "examples"

#: KI-15: the references whose output recipe is invalid as written (by design).
KI15_INVALID = {"example_DRX_33", "example_DRX_33_anisoADP", "example_DRX_33_atomrefine",
                "example_LaB6_singlepeakfit"}

#: Per-engine references whose output recipe is invalid as written: not KI-15 (which names the GSAS-II
#: references), recorded here as found when the reference was made. The ionic LaB6 easydiffraction leg is
#: tests/data/easydiffraction/native/lab6_cryspy_pv.json with La3+; like that fixture's golden it refines
#: broad_lorentz_x negative, so the Lorentzian FWHM is negative at the top of the window (EB-87,
#: easydiffraction_negative_width) and the output recipe is refused.
INVALID_PER_ENGINE = {"example_LaB6_ionic/easydiffraction"}

#: The older gsasii references that carry output_recipe.json + parameter_dispositions.csv
#: (maintainer decision on the 0.2.0 handover question Q3; equivalence record in the devkit,
#: tasks/cleanup-step3-q3-equivalence.md). The three DRX_33 refinements reproduce their older
#: reference files only within the regression tolerances on this build (phase-angle sign flips
#: 180/-180, last-digit drift); their two files were added from this build without touching the
#: older ones (maintainer, option a).
OUTPUT_RECIPE_CASES = [
    "example_DRX_33",
    "example_DRX_33_anisoADP",
    "example_DRX_33_atomrefine",
    "example_DRX_33_simulation",
    "example_DRX_33_strainonly",
    "example_LaB6",
    "example_LaB6_simulation",
    "example_LaB6_singlepeakfit",
]

_COMMITTED_OUTPUT_RECIPES = sorted(
    p for pattern in ("*/output/output_recipe.json", "*/*/output/output_recipe.json")
    for p in EXAMPLES.glob(pattern))


@pytest.mark.core
def test_older_cases_carry_both_files():
    for case in OUTPUT_RECIPE_CASES:
        for name in ("output_recipe.json", "parameter_dispositions.csv"):
            assert (EXAMPLES / case / "output" / name).is_file(), f"{case}/output/{name}"


@pytest.mark.core
@pytest.mark.parametrize("path", _COMMITTED_OUTPUT_RECIPES,
                         ids=[p.parent.relative_to(EXAMPLES).as_posix() for p in _COMMITTED_OUTPUT_RECIPES])
def test_committed_output_recipe_validity_agrees_with_ki15(path):
    """A committed output recipe validates unless it is a KI-15 reference (or a per-engine leg in
    ``INVALID_PER_ENGINE``); those do not."""
    import pydantic
    import powderline

    recipe = json.loads(path.read_text(encoding="utf-8"))
    assert "powderline_provenance" in recipe["metadata"]
    leg = path.parent.parent.relative_to(EXAMPLES).as_posix()  # "<case>" or "<case>/<engine>"
    if leg in KI15_INVALID or leg in INVALID_PER_ENGINE:
        with pytest.raises(pydantic.ValidationError):
            powderline.validate(recipe)
    else:
        powderline.validate(recipe)


@pytest.mark.gsasii
@pytest.mark.slow
@pytest.mark.parametrize("case", OUTPUT_RECIPE_CASES)
def test_example_output_recipe_regression(case, tmp_output_dir):
    """A fresh run reproduces the committed output recipe and dispositions; validity as KI-15 says."""
    ref_dir = EXAMPLES / case / "output"
    cmd = kicker_command(str(EXAMPLES / case / "input.json"), "--output", str(tmp_output_dir), repo_root=REPO)
    result = run_subprocess_utf8(cmd, capture_output=True, text=True, cwd=REPO)
    assert result.returncode == 0, f"Refinement failed with error:\n{result.stderr}"

    test_recipe = json.loads((tmp_output_dir / "output_recipe.json").read_text(encoding="utf-8"))
    ref_recipe = json.loads((ref_dir / "output_recipe.json").read_text(encoding="utf-8"))
    mismatches = output_recipe_mismatches(test_recipe, ref_recipe)
    assert mismatches == [], "output_recipe.json differs from the reference:\n" + "\n".join(mismatches[:20])

    test_disp = pd.read_csv(tmp_output_dir / "parameter_dispositions.csv")
    ref_disp = pd.read_csv(ref_dir / "parameter_dispositions.csv")
    assert dispositions_match(test_disp, ref_disp), (
        f"parameter_dispositions.csv differs from the reference:\nTest:\n{test_disp}\nReference:\n{ref_disp}")

    reported_invalid = "not valid as written" in result.stdout
    assert reported_invalid == (case in KI15_INVALID), (
        f"output_recipe_valid disagrees with KI-15 for {case}:\n{result.stdout}")
