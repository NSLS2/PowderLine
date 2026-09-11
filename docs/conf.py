# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

import sys
from pathlib import Path

# Add src directory to Python path for autodoc
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information

project = 'PowderLine'
copyright = '2026, NSLS-II / Brookhaven National Laboratory'
author = 'Dan Olds and Adam Corrao'
# Single-source the version from the package (pyproject reads the same
# attribute via [tool.hatch.version]).
from powderline import __version__ as release  # noqa: E402

# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

extensions = [
    'sphinx.ext.autodoc',      # Auto-generate docs from docstrings
    'sphinx.ext.napoleon',     # Support Google/NumPy docstring styles
    'sphinx.ext.viewcode',     # Add links to source code
    'sphinx.ext.intersphinx',  # Link to other project docs (e.g., Python, NumPy)
    'myst_parser',             # Support Markdown files
]

# GSAS-II is a heavy conda dependency absent from the doc-build
# environment; mock it so autodoc can import powderline.kicker
# (kicker.py imports `from GSASII import ...` unguarded at module top).
autodoc_mock_imports = ["GSASII"]

# Napoleon settings for Google/NumPy style docstrings
napoleon_google_docstring = True
napoleon_numpy_docstring = True
napoleon_include_init_with_doc = False
napoleon_include_private_with_doc = False
napoleon_include_special_with_doc = True
napoleon_use_admonition_for_examples = False
napoleon_use_admonition_for_notes = False
napoleon_use_admonition_for_references = False
napoleon_use_ivar = False
napoleon_use_param = True
napoleon_use_rtype = True

# Intersphinx mapping to link to external docs
intersphinx_mapping = {
    'python': ('https://docs.python.org/3', None),
    'numpy': ('https://numpy.org/doc/stable/', None),
    'pandas': ('https://pandas.pydata.org/pandas-docs/stable/', None),
    'pydantic': ('https://docs.pydantic.dev/latest/', None),
}

templates_path = ['_templates']
exclude_patterns = ['_build', 'Thumbs.db', '.DS_Store', 'dev']  # dev/ = in-repo development dossiers, not user-facing docs

# Treat missing cross-reference targets as warnings (not silently ignored)
nitpicky = True

# cases without a link target
nitpick_ignore = [
    # pandas' public docs index `pandas.DataFrame`, but runtime type hints
    # resolve to its internal module path; the pandas intersphinx inventory
    # has no entry for the latter.
    ('py:class', 'pandas.core.frame.DataFrame'),
    # pydantic's `Field(gt=..., ge=...)` constraints are implemented via
    # `annotated_types.Gt`/`Ge` metadata; the package has no published Sphinx
    # inventory to link against.
    ('py:class', 'annotated_types.Gt'),
    ('py:class', 'annotated_types.Ge'),
    # `RefinementParameter`'s auto-generated "alias of Annotated[...]" line
    # (see its `#:` doc-comment in schema.py) spells out its real
    # `PlainSerializer(func=<lambda>, ...)` metadata; Sphinx's stringifier
    # renders the lambda's qualname fragment as its own bogus xref target.
    ('py:class', 'lambda'),
]


def _resolve_type_alias_as_data(app, env, node, contnode):
    """Fall back to a ``py:obj``-style lookup for unresolved ``py:class`` refs.

    Type-hint rendering always emits a ``:py:class:`` xref for any bare
    identifier (see ``sphinx.domains.python._annotations.parse_reftarget``),
    even when the identifier is actually a module-level type alias documented
    as ``py:data`` (e.g. ``RefinementParameter = Annotated[...]``). The
    Python domain's ``class`` role only searches ``class``/``exception``
    objtypes, so such a ref can never resolve as-is -- regardless of how the
    alias itself is documented. Retry it as an ``obj`` lookup, which every
    objtype (data, type, attribute, ...) satisfies.
    """
    if node.get('refdomain') != 'py' or node.get('reftype') not in {'class', 'obj'}:
        return None
    py_domain = env.get_domain('py')
    return py_domain.resolve_xref(
        env, node['refdoc'], app.builder, 'obj', node['reftarget'], node, contnode
    )


def setup(app):
    app.connect('missing-reference', _resolve_type_alias_as_data)

# MyST parser settings for Markdown support
myst_enable_extensions = [
    "deflist",      # Definition lists
    "colon_fence",  # ::: fences
    "dollarmath",   # $$...$$ math blocks (e.g. Rwp formula in DEVELOPMENT.md)
]
# Auto-generate GitHub-style heading anchors (up to H4) so in-page TOC links
# like `[Root Causes Summary](#1-root-causes-summary)` in cross-platform-guide.md
# resolve instead of raising 'myst.xref_missing'.
myst_heading_anchors = 4
source_suffix = {
    '.rst': 'restructuredtext',
    '.md': 'markdown',
}

# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

html_theme = 'sphinx_rtd_theme'  # Read the Docs *theme*; docs are hosted on GitHub Pages
html_static_path = ['_static']

# Canonical URL for the GitHub Pages site (used for sitemap/canonical links).
html_baseurl = 'https://nsls2.github.io/PowderLine/'

# -- Options for autodoc -----------------------------------------------------

autodoc_default_options = {
    'members': True,
    'member-order': 'bysource',
    'special-members': '__init__',
    'undoc-members': True,
    # model_config is pydantic's internal ConfigDict boilerplate (identical on
    # every model, not part of the recipe schema) -- excluding it avoids ~24
    # unresolvable `py:class reference target not found: ConfigDict` warnings
    # (pydantic doesn't publish ConfigDict in its intersphinx inventory).
    'exclude-members': '__weakref__,model_config',
}

# Type hints configuration
autodoc_typehints = 'signature'
autodoc_type_aliases = {
    'RefinementParameter': 'powderline.schema.RefinementParameter',
}
