# Scope and limitations

What PowderLine does not do. None of these is approximated silently: a recipe
that asks for one is refused at validation, or the schema has no field for it.

## Data

| Not supported | What PowderLine accepts |
|---|---|
| Neutron data | X-ray data only. |
| Time-of-flight and energy-dispersive data | Constant-wavelength data. |
| Data on a Q or d-spacing axis | 2θ in degrees. Convert Q or d to 2θ in the reader that builds `xrd_data`. |
| Kα doublets and laboratory X-ray data | GSAS-II recipes are single-wavelength (`type: "PXC"`). TOPAS recipes state one emission line. easydiffraction has a Kα2 line, which reaches the engine but has not been verified against laboratory data. |
| Several patterns in one refinement (multi-histogram) | One pattern per recipe. |
| Repairing data | PowderLine accepts or refuses data, and never changes it. Sorting, unit conversion, weights from counts and masking belong to your reader. |

## Models

| Not supported | Notes |
|---|---|
| Pawley and Le Bail fitting | Every phase is a structure. For a fit without a structure, use single-peak fitting (`gsasii.spf`, `topas.spf`). |
| Magnetic structures | X-ray data only. |
| Anisotropic size and strain models (uniaxial, ellipsoidal, Stephens) | GSAS-II and TOPAS take isotropic size and strain. easydiffraction has no sample broadening: its profile is the instrument's. |
| Preferred orientation other than March–Dollase | No spherical harmonics, no second axis. |
| Fundamental-parameters profiles (TOPAS `fp`) | Out of scope. |
| Extinction and surface roughness | In no engine schema. |
| Sample absorption and sample displacement in GSAS-II recipes | GSAS-II's sample parameters are not exposed. TOPAS has a `capillary` absorption correction; easydiffraction has `absorption` and displacement slots. |
| Bragg–Brentano and other specimen corrections in TOPAS recipes (`Specimen_Displacement`, `Absorption`, goniometer radii beyond the axial models) | Not in the TOPAS schema. |

## Refinement features

| Not supported | Notes |
|---|---|
| Bounds in GSAS-II recipes | GSAS-II applies limits only after a fit ([Bounds](recipe-format.md#gsas-ii-no-bounds)). |
| User-defined constraints between atoms (shared occupancies, ADPs tied across sites) | Only the space-group symmetry ties parameters. |
| Restraints and rigid bodies | In no engine schema. |
| Refinement strategies inside one recipe (sequential or iterative steps) | One refinement per recipe. Chain runs yourself through the output recipe ([Run a series](../how-to/sequential-refinement.md)). |
| A choice of minimizer | Each engine uses its own least squares. easydiffraction's `minimizer` must be stated, and accepts only `"lmfit (leastsq)"`. |
| Relaxed checks | There is no mode that switches validation rules off, for example the occupancy range. |

## Engines and versions

| Not supported | Notes |
|---|---|
| Engines other than GSAS-II, TOPAS and easydiffraction | Each engine needs its own gateway ([Adding an engine](../development/adding-an-engine.md)). |
| Translating a recipe between engines | A recipe is written in one engine's terms. Only the [core blocks](recipe-format.md#core-blocks-and-engine-blocks) move between engines. |
| Single-peak fitting with easydiffraction | `gsasii.spf` and `topas.spf` only. |
| TOPAS 7 and other TOPAS versions | `topas.*` recipes are verified against TOPAS 6 and declare it only. |
| Running TOPAS outside Windows | `tc.exe` runs on Windows. Elsewhere a TOPAS recipe validates and its input files are written, without a run. |
| Other GSAS-II or easydiffraction versions | Each environment pins the version the gateway requires ([Versions](versions.md#engine-versions)). |
| `Uaniso`, `scattering_types` and `preferred_orientation` with easydiffraction's CrysFML calculator | CrysPy only. CrysFML also reports no reflection list. |

## Tools around the recipe

| Not supported | Notes |
|---|---|
| Reading CIF files | The structure arrives as a phase block that you or your tooling write. |
| Building recipes | PowderLine checks recipes strictly and leaves building them to the tool that knows where the data came from. |
| Reading raw data files | Your reader fills `xrd_data` with the arrays. |
| Fetching structures from a database (Materials Project or others) | Not part of PowderLine. |

Why PowderLine reads no CIF and builds no recipe is explained on
[Recipes](../concepts/recipes.md#where-recipes-come-from).
