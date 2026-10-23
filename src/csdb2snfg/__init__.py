"""csdb2snfg - Convert CSDB linear notation to SNFG glycan diagrams."""

# Keep in sync with [project].version in pyproject.toml (a dynamic
# importlib.metadata lookup was rejected: it would run a dist-info scan at
# import time and defeat the PEP 562 lazy-import design below).
__version__ = "0.3.0"

__all__ = [
    "__version__",
    "parse_csdb_linear",
    "print_ast",
    "split_fuzzy_options",
    "split_fuzzy_variants",
    "expand_fuzzy",
    "expand_fuzzy_tracked",
    "draw_snfg",
    "layout_tree",
    "expand_repeat",
    "expand_repeat_compact",
    "generate_snfg_pptx",
    "glycan_color",
    "glycan_dict",
    "MODIFIERS",
    "Node",
    "ChainNode",
    "BranchNode",
    "FuzzyNode",
    "RepeatNode",
    "LinkageNode",
    "ResidueNode",
    "Style",
    "PRESETS",
    "load_style",
]

# Lazy re-export (PEP 562): importing csdb2snfg does not pull in heavy
# dependencies like matplotlib / python-pptx / numpy; the corresponding module
# is imported on first attribute access and cached in globals().
_LAZY_ATTRS = {
    "parse_csdb_linear": "csdb2snfg.csdb.parser",
    "print_ast": "csdb2snfg.csdb.parser",
    "split_fuzzy_options": "csdb2snfg.csdb.fuzzy",
    "split_fuzzy_variants": "csdb2snfg.csdb.fuzzy",
    "expand_fuzzy": "csdb2snfg.csdb.fuzzy",
    "expand_fuzzy_tracked": "csdb2snfg.csdb.fuzzy",
    "Node": "csdb2snfg.csdb.parser",
    "ChainNode": "csdb2snfg.csdb.parser",
    "BranchNode": "csdb2snfg.csdb.parser",
    "FuzzyNode": "csdb2snfg.csdb.parser",
    "RepeatNode": "csdb2snfg.csdb.parser",
    "LinkageNode": "csdb2snfg.csdb.parser",
    "ResidueNode": "csdb2snfg.csdb.parser",
    "glycan_color": "csdb2snfg.snfg.symbols",
    "glycan_dict": "csdb2snfg.snfg.symbols",
    "MODIFIERS": "csdb2snfg.snfg.symbols",
    "layout_tree": "csdb2snfg.snfg.layout",
    "expand_repeat": "csdb2snfg.snfg.layout",
    "expand_repeat_compact": "csdb2snfg.snfg.layout",
    "draw_snfg": "csdb2snfg.export.image",
    "generate_snfg_pptx": "csdb2snfg.export.pptx",
    "Style": "csdb2snfg.snfg.style",
    "PRESETS": "csdb2snfg.snfg.style",
    "load_style": "csdb2snfg.snfg.style",
}


def __getattr__(name):
    """PEP 562 lazy attribute access: import the owning module on first use."""
    try:
        module_name = _LAZY_ATTRS[name]
    except KeyError:
        raise AttributeError(f"module 'csdb2snfg' has no attribute {name!r}") from None
    import importlib

    value = getattr(importlib.import_module(module_name), name)
    globals()[name] = value  # cache; subsequent accesses cost nothing
    return value


def __dir__():
    """Expose only the public API in dir()/completion (lazy attrs included)."""
    return sorted(__all__)
