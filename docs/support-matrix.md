# Schema and engine support matrix

<!-- Model: compatibility is declared, never inferred from version
     arithmetic; declarations are capabilities() keys (support_matrix() in
     powderline.compat); engine versions are pinned and checked at run time;
     TOPAS declares its version in the recipe and the installed version is
     declared by the user; easydiffraction recipes carry no engine version;
     gemmi is pinned exactly. The table below is generated:
     scripts/gen_schema_field_tables.py. -->

## How compatibility is decided

PowderLine never works out from version numbers whether a recipe is
acceptable. Every acceptance is **declared** in code, and this page is
generated from those declarations:

- **Core** (`powderline.schema_core`) declares `CORE_SCHEMA_VERSION`, the
  version new recipes are written against, and `SUPPORTED_CORE_SCHEMAS`, a
  [PEP 440](https://peps.python.org/pep-0440/#version-specifiers) specifier
  of the core-schema versions this release accepts.
- **Each gateway** declares, as keys of its `capabilities()`:
  `engine_schema_version` (what new recipes for that engine are written
  against), `supported_engine_schemas` (the engine-schema versions it
  accepts) and `requires_core_schema` (the core versions that engine schema
  needs — a single specifier, or a mapping when different engine-schema
  versions need different core versions).
- A gateway that declares none of these is listed as **undeclared** and its
  recipes are rejected; a gateway that declares only some of them is a
  configuration error, raised by name.

`validate()` checks a recipe's `core_schema_version` against core's
declaration, its `engine_schema_version` against the gateway's, and the pair
against `requires_core_schema`, in that order; the error names the versions
and the PowderLine release that produced it. Widening a declaration is a
deliberate act with a compatibility run behind it, never a range.


**Engine versions** are declared and checked differently per engine:

| Engine | How the version is fixed | Checked |
|---|---|---|
| GSAS-II | pinned by pixi; the gateway declares `engine_version_spec` | at run time against the installed package |
| easydiffraction | pinned by pixi (`==0.21.1`); recipes carry no engine version | at run time against the installed package |
| TOPAS | cannot be pinned: a `topas.*` recipe states `engine_version` (`"6"`; 0.1.0 supports TOPAS 6 only, `supported_engine_versions == "==6"`) | at run time against the version **the user declares** (`topas_version` argument or `.powderline_config.yaml` `topas.version`), since `tc.exe` carries no version PowderLine could read |

gemmi, which provides the canonical space-group names core validates against,
is pinned exactly (`==0.7.5`); widening it means re-running the symmetry
tests and regenerating `tests/data/canonical_space_groups.txt`.

## The matrix

The table is **generated from the declarations** by
`scripts/gen_schema_field_tables.py` (the same script that writes the
[field tables](fields.md)), into `docs/_generated/support_matrix.md`, so it
cannot drift from the code. Regenerate it after changing a declaration, in
any environment where the gateways are installed (the call imports no
engine):

```bash
PYTHONPATH=src python scripts/gen_schema_field_tables.py
```

The raw rows are `powderline.support_matrix()` (one dict per gateway with
the keys `gateway`, `powderline_version`, `core_schema_version`,
`supported_core_schemas`, `engine_schema_version`, `supported_engine_schemas`,
`requires_core_schema`, `engine_version_spec`, `workflows`, `declared`):

```bash
python -c "import powderline, json; print(json.dumps(powderline.support_matrix(), indent=1))"
```

```{include} _generated/support_matrix.md
```

The PowderLine version in the table is the package's `__version__` at
generation time; it reads `0.2.0` once the release step bumps the version.
The TOPAS `engine_version_spec` is the native declaration (`==6`, TOPAS 6
only): the `topas.*` 0.1.0 recipes state `engine_version: "6"`.

**Verification status (0.2.0).** The `topas.*` gateway's INP and XYE writer is
verified byte-for-byte against goldens produced on a TOPAS 6 machine; a run
without `tc.exe` writes the files and returns `status: generated`. The TOPAS
halves of ionic scattering types and March–Dollase preferred orientation are
checked against output TOPAS 6 wrote (La3+/La within 0.07 % of GSAS-II; the
`PO` correction within 1.4e-7 of the March–Dollase formula). **TOPAS execution
is verified on TOPAS 6** on 0.2.0's code: `pixi run test-topas` with `tc.exe`
declared reruns every golden fixture and the ionic and textured examples, and
passed on Windows (KI-16). GSAS-II and easydiffraction execution are verified
by their suites on linux-64 and win-64.

## Reading the matrix

- A recipe with `core_schema_version: "0.1.0"` and
  `engine_schema_version: "0.1.0"` validates on every gateway listed.
- A recipe stating any other version pair is rejected with a message naming
  the accepted specifiers — even `0.1.1`, until a release declares it.
- Which engine schema is *meant* is read from `schema_name`
  (`<engine>.<workflow>`), never from the versions.
- The schema changelog, [SCHEMA_HISTORY](SCHEMA_HISTORY.md), records every
  declaration change; the package changelog, [CHANGELOG](changelog.md),
  records the release that made it.
