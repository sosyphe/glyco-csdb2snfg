"""csdb2snfg - Convert CSDB linear notation to SNFG glycan diagrams."""

__version__ = "0.2.0"

__all__ = [
    "__version__",
    "parse_csdb_linear",
    "print_ast",
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
]

# 惰性 re-export（PEP 562）：import csdb2snfg 不拉起 matplotlib / python-pptx /
# numpy 等重依赖，首次属性访问时才导入对应模块并缓存到 globals()。
_LAZY_ATTRS = {
    "parse_csdb_linear": "csdb2snfg.csdb.parser",
    "print_ast": "csdb2snfg.csdb.parser",
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
}


def __getattr__(name):
    try:
        module_name = _LAZY_ATTRS[name]
    except KeyError:
        raise AttributeError(
            f"module 'csdb2snfg' has no attribute {name!r}") from None
    import importlib
    value = getattr(importlib.import_module(module_name), name)
    globals()[name] = value  # 缓存，二次访问零开销
    return value


def __dir__():
    return sorted(__all__)
