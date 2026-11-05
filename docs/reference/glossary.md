# Glossary

In the statistics below, the sums run over the $N$ data points inside the fit
window with a positive weight $w_i$. $P$ is the number of parameters the
engine varied.

ADP, `Uiso`, `Uaniso`
: Atomic displacement parameter: how far an atom vibrates or is displaced
  about its site. `Uiso` is one isotropic value; `Uaniso` is the six values
  `U11 U22 U33 U12 U13 U23`. Both are in Å². An atom's `ADP` field says which
  one it states.

Bound
: The `min` or `max` of a `[value, refine_flag, min, max]` parameter, or
  `null` for an open side. What a bound means depends on the engine; see
  [Bounds](recipe-format.md#bounds).

Calibrant
: A standard reference material, such as LaB6, Si or CeO2, measured with the
  same wavelength and geometry as your sample. Refining it gives the
  instrument's peak shape and the corrections that apply.

Canonical space-group name
: The one spelling gemmi gives each space-group setting, such as
  `"P m -3 m"` or `"F d -3 m:2"`. Recipes must use it exactly.

Chebyshev background
: A smooth background written as a sum of Chebyshev polynomials over the fit
  window. It is the background model every engine shares.

Core block
: A part of the payload that is the same in every engine: `xrd_data`,
  `fit_range`, the Chebyshev background and a phase's `space_group`,
  `unit_cell` and `atoms`.

Disposition
: How a value of the output recipe came about: `default_applied`,
  `held_by_symmetry`, `held_by_user`, `requested_not_varied` or `varied`.

Engine
: The refinement program that does the calculation: GSAS-II, TOPAS or
  easydiffraction.

Envelope
: The fixed shape of a run's result, shared by successful, generated and
  failed runs. Its version is `envelope_version`.

ESD, s.u.
: Estimated standard deviation, the uncertainty of a refined value. The IUCr
  calls the same quantity the standard uncertainty (s.u.). PowderLine's
  columns are named `esd`, as in the engines.

Execution mode
: Where a GSAS-II recipe runs: `auto` (the default: try the GSAS-II server,
  else run in-process), `server` or `subprocess` (in-process).

Fit window
: The 2θ range that is fitted, set by `fit_range`. Every engine fits exactly
  the points inside it with a positive weight.

Gateway
: The adapter between PowderLine and one engine. It knows the engine's recipe
  schema, how to run the engine and how to read its output.

Generate-only
: A TOPAS run where no `tc.exe` is found. PowderLine writes the TOPAS input
  files and returns `status: "generated"`.

GoF
: Goodness of fit, $R_\mathrm{wp} / R_\mathrm{exp}$. Close to 1 when the
  model fits the data to within its weights.

GSAS-II server
: A local process, one per user, that keeps GSAS-II loaded so that repeated
  runs skip its start-up time.

Metadata
: The optional free-form `metadata` block of a recipe. PowderLine never reads
  it and carries it into the output recipe.

Multiplicity
: The number of equivalent positions of an atom's site in the unit cell. It
  follows from the space group and the site.

Output recipe
: The recipe a run returns: your recipe with the refined values written
  back. It is ready to be the input of the next run.

Payload
: The `payload` block of a recipe: the refinement itself, written in the
  engine's terms.

Provenance
: The record of where a result came from. PowderLine writes it into the
  output recipe as `metadata.powderline_provenance`: the parent run ID, the
  engine and its version, and the PowderLine version.

Recipe
: A complete refinement as structured data: a dictionary in Python,
  serialised as JSON when it is stored or sent.

Refine flag
: The second entry of a parameter: `true` to refine the value, `false` to
  hold it.

Rexp
: Expected R factor, the best Rwp the weights allow:
  $R_\mathrm{exp} = 100 \sqrt{(N - P) / \sum w_i y_{\mathrm{obs},i}^2}$, in
  percent.

Run ID
: A UUID that identifies one run (`result["run_id"]`). It becomes the
  `parent_run_id` of the output recipe.

Rwp
: Weighted-profile R factor:
  $R_\mathrm{wp} = 100 \sqrt{\sum w_i (y_{\mathrm{obs},i} - y_{\mathrm{calc},i})^2 / \sum w_i y_{\mathrm{obs},i}^2}$,
  in percent.

Schema
: The exact definition of what a recipe may contain. A recipe is checked
  against the core schema and one engine schema, each with its own version.

Setting, origin choice
: Different ways to describe the same space group: origin choice 1 or 2
  (`:1`, `:2`), hexagonal or rhombohedral axes (`:H`, `:R`), and the unique
  axis and cell choice of a monoclinic group. The canonical name states the
  setting.

Simulation
: A run that refines nothing and only calculates the pattern from the stated
  values.

Single-peak fitting (SPF)
: Fitting individual peaks, each with its own position, intensity and widths,
  without a crystal structure. The `gsasii.spf` and `topas.spf` workflows.

Special position
: A site that lies on a symmetry element, so some of its coordinates are
  fixed or tied to each other, such as `(x, x, x)` or `(1/2, 0, 0)`.

Structured warning
: A warning as data: `{code, message, field_path[, level]}`. The codes are on
  [Messages](messages.md#warning-codes).

Tie group
: Parameters that symmetry makes one parameter, such as the cubic `a`, `b`
  and `c`. Every member is stated, with the same refine flag.

Validation
: Checking a recipe against its schemas and its crystallographic symmetry
  before anything runs. It needs no engine.

Workflow
: What a recipe does with its engine: Rietveld refinement (`rietveld`) or
  single-peak fitting (`spf`). The second part of `schema_name`.

χ²_red
: Reduced chi-squared,
  $\chi^2_\mathrm{red} = \sum w_i (y_{\mathrm{obs},i} - y_{\mathrm{calc},i})^2 / (N - P)$.
  It equals GoF².
