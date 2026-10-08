"""SNFG intermediate model layer: symbol tables, colors, geometry and tree layout.

Backend-agnostic (no matplotlib/pptx dependency); shared by csdb2snfg.export.*.
"""

from csdb2snfg.snfg.symbols import (
    glycan_color,
    glycan_dict,
    MODIFIERS,
    get_shape_coords,
)
from csdb2snfg.snfg.layout import (
    expand_repeat,
    expand_repeat_compact,
    layout_tree,
    prepare_layout,
    OPEN_HEAD,
    OPEN_TAIL,
    is_open_node,
    make_edge_label,
    parse_edge_label,
)
from csdb2snfg.snfg.geometry import (
    resolve_mono,
    node_fill_polys,
    shape_vcenter_offset,
    bracket_pad,
    bracket_geometry,
    bracket_bounds,
    open_edge_flags,
    edge_label_slots,
)

__all__ = [
    "glycan_color",
    "glycan_dict",
    "MODIFIERS",
    "get_shape_coords",
    "expand_repeat",
    "expand_repeat_compact",
    "layout_tree",
    "prepare_layout",
    "OPEN_HEAD",
    "OPEN_TAIL",
    "is_open_node",
    "make_edge_label",
    "parse_edge_label",
    "resolve_mono",
    "node_fill_polys",
    "shape_vcenter_offset",
    "bracket_pad",
    "bracket_geometry",
    "bracket_bounds",
    "open_edge_flags",
    "edge_label_slots",
]
