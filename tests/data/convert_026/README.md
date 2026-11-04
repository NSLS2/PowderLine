# The converter's 0.26.0 fixtures

Byte-identical copies of every `examples/*/input.json` as committed before the
examples were migrated to the `gsasii.*` schemas (`2eed3f3`), i.e. the ten 0.26.0 recipes
(`GSASII_Rietveld` / `GSASII_SPF`) that `scripts/convert_recipe_026.py` — the
0.26.0 → `gsasii.*` migration tool — is tested on
(`tests/test_convert_recipe_026.py`: one sweep over all of them, plus the
per-rule tests). `tests/test_gsasii_native_run.py` and `tests/test_api.py`
read the LaB6 ones through the converter too, so a converted recipe still
carries the background peak the committed example lost (EB-33). Same
blobs as the history (no repository growth).

The 0.26.0 path itself (schema, executors, translation layers) was deleted in
0.2.0; nothing here is run as a 0.26.0 recipe, and nothing but the converter
and its tests may depend on this directory.
