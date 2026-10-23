"""SNFG intermediate model layer: symbol tables, colors, geometry and tree layout.

Backend-agnostic (no matplotlib/pptx dependency); shared by csdb2snfg.export.*.
"""

from csdb2snfg.snfg.geometry import (
    GRAPHIC_ENDS,
    EndSpec,
    bracket_bounds,
    bracket_geometry,
    bracket_pad,
    edge_label_slots,
    end_marker_specs,
    end_squiggle_points,
    node_fill_polys,
    open_edge_flags,
    resolve_mono,
    sample_cubic_bezier,
    shape_vcenter_offset,
)
from csdb2snfg.snfg.highlight import (
    HighlightPlan,
    compute_highlight,
    normalize_motif,
    parse_motif,
)
from csdb2snfg.snfg.layout import (
    OPEN_HEAD,
    OPEN_TAIL,
    expand_repeat,
    expand_repeat_compact,
    is_open_node,
    layout_tree,
    make_edge_label,
    parse_edge_label,
    prepare_layout,
    prepare_layout_ext,
)
from csdb2snfg.snfg.style import (
    DEFAULT_DIM_PALETTE,
    PRESETS,
    Style,
    load_style,
)
from csdb2snfg.snfg.symbols import (
    MODIFIERS,
    get_shape_coords,
    glycan_color,
    glycan_dict,
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
    "prepare_layout_ext",
    "HighlightPlan",
    "compute_highlight",
    "normalize_motif",
    "parse_motif",
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
    "EndSpec",
    "end_marker_specs",
    "end_squiggle_points",
    "sample_cubic_bezier",
    "GRAPHIC_ENDS",
    "Style",
    "PRESETS",
    "load_style",
    "DEFAULT_DIM_PALETTE",
]
