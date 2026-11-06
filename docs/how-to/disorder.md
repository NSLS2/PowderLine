# Model disorder near special positions

**Goal:** model positional disorder with a split site. You place an atom a
little off a special position, and its symmetry images form the split site:
a cation rattling off a 4a site, or an anion spread over several positions
around a mirror. PowderLine makes sure every engine reads the atom the same
way.

**You need:**
- A phase block that validates ([Refine a structure](refine-structure.md)).
- The displacement you expect, in ångströms.

## How PowderLine reads an atom near a special position

Each engine has its own tolerance for deciding whether an atom sits **on** a
special position or **off** it, and the engines do not agree. PowderLine
decides once, in core, the same way for every engine. Anything an engine
would do silently becomes either a reported value or an error.

The distance from the special position is measured as `d`: the largest
fractional-coordinate distance between the atom and one of its own symmetry
images. On a mirror or an inversion centre, `d` is twice the atom's offset
from the site. Fractional units make `d` independent of the cell, which is
itself refined. The distance in ångströms is roughly d × a: 2e-3 is 0.008 Å in a
4 Å cell, 0.02 Å in a 10 Å cell and 0.04 Å in a 20 Å cell.

| Stated position | GSAS-II 5.7.9 would… | easydiffraction / CrysPy would… | TOPAS 6 would… | PowderLine does |
|---|---|---|---|---|
| **Exactly on** it (`0.5`, `0.25`, `0`) | read it as special | read it as special | read it as special (only an exact value or an equation) | special position. A fixed coordinate cannot be refined: a refine flag on one is an error. |
| **Within 5e-6** (`0.333333` for 1/3, `0.5000001` for 1/2) | read it as special (its tolerance is 2e-5 + 1e-5·\|x\|) | read it as special and **move the coordinate** to its Wyckoff value | read it as a **general** position: `k` atoms almost on top of each other | depends on the value. A third, or a value derived from another stated value, is held exact and reported as `symmetry_value_derived` (level `info`); every engine gets the exact value, TOPAS the equation `= 1/3;`. A constant with an exact decimal form is an **error**: `0.5000001` gets "write x = 0.5". |
| **5e-6 to 2e-3** (`0.3333`, `0.33`, or an atom 0.001 off) | special up to about 2e-5, then general, with the multiplicity changing in between | special or general, depending on how the decimals rationalise | general | **error** naming the atom, the special position it is near and the fix: state the position exactly, or move the atom until `d` is at least 2e-3 |
| **2e-3 or more** | general | general | general | general position, used as stated. Nothing is moved. |

So every recipe PowderLine accepts is read the same way by all three
engines. [Validation](../concepts/validation.md#special-positions) states
PowderLine's rules for special positions in full.

The 2e-3 band is wider than any engine's own tolerance on purpose. An atom
whose own symmetry image is closer than 2e-3 is not a resolvable separate
site in powder data. Accepting it would leave the result depending on which
engine read it.

## Write a split site

This example moves Li off the 4a site `(0, 0, 0)` of the `F m -3 m` phase in
`examples/example_DRX_33/input.json`. The ordered atom is:

```json
"Li": {"element": "Li", "x": [0.0, false], "y": [0.0, false], "z": [0.0, false],
       "occupancy": [0.6, false], "Multiplicity": 4, "ADP": "Uiso", "Uiso": [0.0051, false]}
```

1. **Place the atom at least 2e-3 off** the special position, in fractional
   units. Work it out from the displacement you expect: 0.1 Å in a 10 Å cell
   is 0.01. Here Li moves to `x = 0.01`, a 24e site.

2. **Update `Multiplicity`, or leave it out.** It is optional. When stated,
   it must equal the multiplicity of the new site. Validation tells you:

   ```
   • payload -> phases -> DRX_33 -> atoms -> Li -> Multiplicity: Value error, stated Multiplicity 4, derived 24 ('F m -3 m', site (0.01, 0.0, 0.0))
   ```

3. **Divide the occupancy by `k`**, the number of symmetry images that now
   stand where the one atom stood. `k` is the new multiplicity divided by the
   special one: here 24 / 4 = 6, so 0.6 becomes 0.1.

   ```json
   "Li": {"element": "Li", "x": [0.01, false], "y": [0.0, false], "z": [0.0, false],
          "occupancy": [0.1, false], "Multiplicity": 24, "ADP": "Uiso", "Uiso": [0.0051, false]}
   ```

   :::{warning}
   PowderLine does not check this step. A split atom left at full occupancy
   puts `k` atoms on the site ({ref}`KI-17 <ki-17>`).
   :::

4. **For a mixed site, state each species as its own atom.** Atoms at the
   same coordinates are independent: each has its own values and flags, and
   PowderLine never ties them. One species can then move off the shared site
   while the other stays.

5. **Refine with care.** The coordinates, occupancy and displacement
   parameters of a split atom are strongly correlated. Check the ESDs and
   `parameter_dispositions.csv`, and see
   [Good refinement practice](../concepts/refinement-practice.md).

If the atom is too close, validation refuses it and says how far it is.
With Li at `x = 0.0005`:

```
• payload -> phases -> DRX_33 -> atoms -> Li: Value error, position (0.0005, 0, 0) is near the special position (0, 0, 0) (multiplicity 4) in 'F m -3 m' without being on it: a symmetry image of the atom is 0.001 (fractional) away from it. State the special-position coordinates to at least 6 decimals, or move the atom until its symmetry images are at least 0.002 away
```

## During a refinement

No engine moves a refined coordinate back onto a special position:

- GSAS-II never snaps.
- easydiffraction detects Wyckoff positions only when the structure is built
  ({ref}`EB-47 <eb-47>`).
- TOPAS compares exactly.

A disordered atom that refines towards its special position therefore stays
a general position with near-coincident images. If it ends inside the 2e-3
band, the run still returns its result, but the **output recipe is marked
not valid**: `output_recipe_valid: false`, with the `output_recipe_not_valid`
warning naming the coordinate. A chained next step stops there instead of
running on an ambiguous position ({ref}`KI-18 <ki-18>`).

When that happens, re-state the atom on the special position (an ordered
model), or restart it further off.

**Check:**
- `pixi run powderline my_sample/input.json --validate-only` reports no
  error for the split atom.
- After the run, the result says `output_recipe_valid: true`.

**Next:** [Run a series](sequential-refinement.md), which stops on an output
recipe that is not valid. [Validation](../concepts/validation.md) explains
the symmetry rules behind this page.
