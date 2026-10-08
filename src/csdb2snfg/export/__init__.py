"""Export backends: matplotlib image rendering and python-pptx vector export.

惰性 re-export：import csdb2snfg.export 本身不拉起任一后端依赖。
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
    try:
        module_name = _LAZY_ATTRS[name]
    except KeyError:
        raise AttributeError(
            f"module 'csdb2snfg.export' has no attribute {name!r}") from None
    import importlib
    value = getattr(importlib.import_module(module_name), name)
    globals()[name] = value
    return value


def __dir__():
    return sorted(__all__)
