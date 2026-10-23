"""Export backends: matplotlib image rendering and python-pptx vector export.

Lazy re-export: importing csdb2snfg.export itself pulls in neither backend's dependencies.
"""

__all__ = [
    "draw_snfg",
    "generate_snfg_pptx",
]

_LAZY_ATTRS = {
    "draw_snfg": "csdb2snfg.export.image",
    "generate_snfg_pptx": "csdb2snfg.export.pptx",
}


def __getattr__(name):
    """PEP 562 lazy attribute access: import the owning backend on first use."""
    try:
        module_name = _LAZY_ATTRS[name]
    except KeyError:
        raise AttributeError(f"module 'csdb2snfg.export' has no attribute {name!r}") from None
    import importlib

    value = getattr(importlib.import_module(module_name), name)
    globals()[name] = value
    return value


def __dir__():
    """Expose only the public re-exports in dir()/completion."""
    return sorted(__all__)
