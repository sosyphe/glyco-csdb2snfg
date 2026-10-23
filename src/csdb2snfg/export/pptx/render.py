"""python-pptx backend main orchestration: template/placeholder management + generate_snfg_pptx."""

import logging
import os
from io import BytesIO
from typing import List, Optional, Tuple, Union

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE_TYPE
from pptx.slide import SlideLayout
from pptx.util import Pt

from csdb2snfg.csdb.parser import parse_csdb_linear
from csdb2snfg.export.pptx.legend import add_legend
from csdb2snfg.export.pptx.overlays import (
    draw_connectors,
    draw_edge_labels,
    draw_end_markers,
    draw_fuzzy_boxes,
    draw_fuzzy_mode_labels,
    draw_repeat_brackets,
    fuzzy_box_pairs,
)
from csdb2snfg.export.pptx.primitives import draw_node
from csdb2snfg.export.pptx.text import resolve_font_family
from csdb2snfg.export.pptx.transform import (
    compute_node_size,
    min_node_distance,
    transform_positions,
)
from csdb2snfg.snfg.geometry import (
    BRACKET_BOX_GAP_RATIO,
    adjacent_bracket_vertical_xs,
    bbox_union_boxes,
    bracket_geometry,
    bracket_vertical_xs,
    circle_clear_verticals,
    end_marker_specs,
    fuzzy_box_geoms,
    fuzzy_boxes_inside_repeat,
    repeat_nest_levels,
)
from csdb2snfg.snfg.layout import is_open_node, prepare_layout_ext
from csdb2snfg.snfg.style import Style, load_style

logger = logging.getLogger(__name__)


# ─── Template / placeholder / layout strategy ─────────────────

DEFAULT_SLIDE_W = 9144000  # 25.4cm
DEFAULT_SLIDE_H = 6858000  # 19.1cm

# Functional data, not UI copy: Chinese-localized Microsoft Office installs
# name built-in slide layouts and placeholders in Chinese. These substrings
# are matched against user-template shape/layout names, so the literal values
# must stay in Chinese; changing them breaks detection on zh-CN Office.
ZH_CONTENT_KEYWORD = "内容"  # "content"; substring of zh-CN content layout/placeholder names
ZH_CONTENT_PLACEHOLDER = "内容占位符"  # "Content Placeholder"
ZH_BLANK_LAYOUT = "空白"  # "Blank"


def _find_placeholder(prs) -> Tuple[int, int, int, int]:
    """Find the SNFG drawing area on a slide layout.

    Strategy:
    1. Look for a shape named 'SNFG_Placeholder'
    2. Fall back to a zh-CN content placeholder (ZH_CONTENT_KEYWORD match)
    3. Fall back to 80% centered area of the slide
    """
    for layout in prs.slide_layouts:
        for shape in layout.shapes:
            if shape.name == "SNFG_Placeholder":
                return shape.left, shape.top, shape.width, shape.height
            # Match common zh-CN content placeholder names
            if ZH_CONTENT_KEYWORD in shape.name and shape.shape_type == MSO_SHAPE_TYPE.PLACEHOLDER:
                return shape.left, shape.top, shape.width, shape.height
    # Fallback: 80% of slide centered
    slide_w = prs.slide_width
    slide_h = prs.slide_height
    w = int(slide_w * 0.8)
    h = int(slide_h * 0.8)
    left = (slide_w - w) // 2
    top = (slide_h - h) // 2
    return left, top, w, h


def get_content_layout(prs) -> SlideLayout:
    """Get the best slide layout for SNFG diagrams.

    Prefer a zh-CN 'Title and Content'-style layout, then a 'Blank' one.
    Layout names are matched via the ZH_* constants (zh-CN Office installs
    name built-in layouts in Chinese; English templates fall through to the
    final first-layout fallback).
    """
    for layout in prs.slide_layouts:
        # The second condition is logically redundant (ZH_CONTENT_KEYWORD is a
        # substring of ZH_CONTENT_PLACEHOLDER); kept for parity with the
        # original matching behavior.
        if ZH_CONTENT_KEYWORD in layout.name or ZH_CONTENT_PLACEHOLDER in layout.name:
            return layout
    # Fallback to blank
    for layout in prs.slide_layouts:
        if ZH_BLANK_LAYOUT in layout.name:
            return layout
    # Last fallback: first layout
    return prs.slide_layouts[0]


def delete_placeholder_shapes(slide, prs) -> None:
    """Delete default placeholder shapes from a new slide so they don't overlap SNFG."""
    shapes_to_delete = []
    bottom_threshold = int(prs.slide_height * 0.85)
    for shape in slide.shapes:
        if shape.is_placeholder:
            # Keep only footer/date placeholders at the very bottom
            if hasattr(shape, "top") and shape.top > bottom_threshold:
                continue
            shapes_to_delete.append(shape)

    for shape in shapes_to_delete:
        sp = shape._element
        sp.getparent().remove(sp)


def get_effective_bounds(
    template_path: Optional[str],
    ph_bounds: Tuple[int, int, int, int],
    slide_w: int,
    slide_h: int,
) -> Tuple[int, int, int, int]:
    """Compute the actual drawing area: with a template keep the placeholder's
    relative proportions; otherwise use the centered 80% region of the slide."""
    ph_left, ph_top, ph_width, ph_height = ph_bounds
    if template_path and os.path.exists(template_path):
        # Keep the placeholder's relative position
        rel_left = ph_left / DEFAULT_SLIDE_W
        rel_top = ph_top / DEFAULT_SLIDE_H
        rel_w = ph_width / DEFAULT_SLIDE_W
        rel_h = ph_height / DEFAULT_SLIDE_H
        return (
            int(slide_w * rel_left),
            int(slide_h * rel_top),
            int(slide_w * rel_w),
            int(slide_h * rel_h),
        )
    else:
        # Without a template use the centered 80% region
        w = int(slide_w * 0.8)
        h = int(slide_h * 0.8)
        return ((slide_w - w) // 2, (slide_h - h) // 2, w, h)


def _add_error_slide(prs, layout: SlideLayout, errors: List[str], resolved_font: str) -> None:
    """Add errors slide if any failures."""
    slide = prs.slides.add_slide(layout)
    delete_placeholder_shapes(slide, prs)
    sw = prs.slide_width or 9144000  # default 10 inches in EMU
    sh = prs.slide_height or 6858000  # default 7.5 inches in EMU
    tb = slide.shapes.add_textbox(int(sw * 0.1), int(sh * 0.1), int(sw * 0.8), int(sh * 0.8))
    tf = tb.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.text = "Export Errors"
    p.font.size = Pt(18)
    p.font.color.rgb = RGBColor(204, 0, 0)
    p.font.bold = True
    p.font.name = resolved_font

    for err in errors:
        p = tf.add_paragraph()
        p.text = err
        p.font.size = Pt(10)
        p.font.name = resolved_font
        p.space_before = Pt(6)


def _decoration_margin_emu(
    pos,
    repeat_groups: List[dict],
    scale: float,
    size_emu: int,
    edges=None,
) -> Tuple[int, int]:
    """-> (horizontal, vertical) EMU by which decorations overhang the node bbox.

    Repeat brackets (pad 1.65*size + caps) and fuzzy gray boxes (pad +
    title band) are drawn outside the node-centre bounding box, but the
    needed_* sizing historically counted node centres only, leaving flat
    wide structures with brackets close to the slide edge. Overhang is
    estimated in layout space from the unclamped bracket_geometry (the
    fuzzy clamp only ever shortens caps, so this is an upper bound) and
    scaled to EMU. Edge label boxes (LABEL_BOX_W/2 = 200000 EMU) are
    deliberately not counted: PADDING_EMU (360000) per side already covers
    them, and including them would inflate nearly every deck's needed size.
    """
    if not repeat_groups or not pos or scale <= 0:
        return (0, 0)
    size_l = size_emu / scale
    xs = [x for x, _ in pos.values()]
    ys = [y for _, y in pos.values()]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    left = right = top = bottom = 0.0
    fuzzy = [g for g in repeat_groups if "mode" in g]
    fpairs = fuzzy_box_geoms(fuzzy, size_l, positions=pos, edges=edges) if fuzzy else []
    nest_levels = repeat_nest_levels(repeat_groups)
    adjusted = None
    if edges is not None:
        adjusted = adjacent_bracket_vertical_xs(repeat_groups, edges, pos, size_l)
    for g_i, g in enumerate(repeat_groups):
        if "mode" in g:
            continue
        geom = bracket_geometry(*g["bbox"], size_l, nest_level=nest_levels[g_i])
        cand_l, cand_r = geom.left_x, geom.right_x
        # The drawn verticals sit on the entry/exit bond midpoints (enclosure
        # clamped to inner gray boxes); on lengthened bonds they overhang the
        # historical bbox+pad estimate, so the sizing decision must see them.
        # Adjacent units are nudged apart, so the margin must include that.
        if edges is not None:
            mid_l, mid_r = (
                adjusted[g_i] if adjusted is not None else bracket_vertical_xs(g, edges, pos)
            )
            if mid_l is not None:
                cand_l = mid_l
            if mid_r is not None:
                cand_r = mid_r
        inner, _outer = fuzzy_boxes_inside_repeat(g, fpairs)
        if inner:
            gap = size_l * BRACKET_BOX_GAP_RATIO
            cand_l, cand_r = circle_clear_verticals(
                min(b.x0 for b in inner) - gap, max(b.x1 for b in inner) + gap, pos, size_l
            )
            cand_l = min(cand_l, geom.left_x)
            cand_r = max(cand_r, geom.right_x)
        left = max(left, min_x - cand_l)
        right = max(right, cand_r - max_x)
        bottom = max(bottom, min_y - geom.y_bot)
        top = max(top, geom.y_top - max_y)
    for geom, _g in fpairs:
        left = max(left, min_x - geom.x0)
        right = max(right, geom.x1 - max_x)
        bottom = max(bottom, min_y - geom.y0)
        top = max(top, geom.y1 - max_y)
    return (int(max(left, right) * scale), int(max(top, bottom) * scale))


def _plan_slide_items(
    csdb_list: List[str],
    *,
    ratio: float,
    compact_repeat: bool,
    highlight_motif: Optional[str],
    default_bounds: Tuple[int, int, int, int],
    node_size: Optional[float] = None,
    unknown_marker: Optional[str] = None,
) -> Tuple[List[Optional[tuple]], List[str]]:
    """Pass 1 of generate_snfg_pptx: parse + lay out every entry (verbatim).

    Returns ``(items, errors)``. ``items`` holds one 9-tuple per entry, in
    input order — ``(csdb, pos, edges, labels, needed_w, needed_h, scale,
    repeat_groups, plan)`` — or ``None`` for entries whose layout raised;
    ``errors`` collects one human-readable line per empty/failed entry
    (they feed the closing error slide).
    """
    errors = []

    items = []
    for idx, csdb in enumerate(csdb_list):
        csdb = csdb.strip()
        if not csdb:
            errors.append(f"[{idx + 1}] EMPTY CSDB")
            continue
        try:
            tree = parse_csdb_linear(csdb)
            # Layout's fuzzy clearance/bond-lengthening constants must use THIS
            # backend's effective radius/bond ratio. It is only knowable after
            # a transform (compute_node_size caps at MAX_NODE_SIZE_EMU), so
            # fuzzy entries re-layout once with the measured ratio (fixed
            # point, <=2 extra passes); fuzzy-free entries keep a single pass
            # bit-identical. dx here is prepare_layout_ext's default 1.5.
            rb = 0.3
            for _pass in range(3):
                _, pos, edges, labels, repeat_groups, expanded = prepare_layout_ext(
                    tree,
                    ratio=ratio,
                    compact_repeat=compact_repeat,
                    unknown_marker=unknown_marker,
                    radius_ratio=rb,
                )
                if not any("mode" in g for g in repeat_groups):
                    break
                pos_emu_p, _bounds_p, scale_p, _tf_p = transform_positions(pos, default_bounds)
                size_p = (
                    int(node_size * scale_p)
                    if node_size is not None
                    else compute_node_size(pos_emu_p, labels)
                )
                rb_new = size_p / scale_p / 1.5
                if rb_new == rb:
                    break
                rb = rb_new
            plan = None
            if highlight_motif:
                from csdb2snfg.snfg.highlight import compute_highlight

                plan = compute_highlight(expanded, edges, labels, highlight_motif)
            positions_emu, (needed_w, needed_h), scale, _tf = transform_positions(
                pos, default_bounds
            )
            # Fold decoration overhang (brackets / fuzzy boxes) into the
            # needed size so the slide-sizing decision sees them; only
            # re-ask transform_positions when there is an overhang, keeping
            # decoration-free entries bit-identical.
            if repeat_groups:
                size_emu = (
                    int(node_size * scale)
                    if node_size is not None
                    else compute_node_size(positions_emu, labels)
                )
                deco = _decoration_margin_emu(pos, repeat_groups, scale, size_emu, edges)
                if deco != (0, 0):
                    _, (needed_w, needed_h), _, _ = transform_positions(
                        pos, default_bounds, deco_margin_emu=deco
                    )
            items.append((csdb, pos, edges, labels, needed_w, needed_h, scale, repeat_groups, plan))
        except Exception as e:
            errors.append(f"[{idx + 1}] {csdb}\n  ERROR: {e}")
            items.append(None)
    return items, errors


def _draw_slide(
    prs,
    layout: SlideLayout,
    item: tuple,
    *,
    template_path: Optional[str],
    ph_bounds: Tuple[int, int, int, int],
    st: Style,
    eff_node_stroke: Optional[float],
    eff_link_width: Optional[float],
    font_size: float,
    resolved_font: str,
    node_size: Optional[float],
    show_linkage: bool,
    end: Optional[str],
) -> None:
    """Pass-2 body of generate_snfg_pptx: draw one planned structure (verbatim).

    ``item`` is one 9-tuple produced by _plan_slide_items. Shape insertion
    order IS the PPT z-order (fuzzy boxes -> connectors -> end markers ->
    nodes -> brackets -> legend -> edge labels -> XOR/OR labels); do not
    reorder statements here — the default render path is byte-compared
    across commits (slideN.xml sha256 guards).
    """
    (csdb, pos, edges, labels, needed_w, needed_h, scale, repeat_groups, plan) = item

    # Compute the actual drawing area from the current slide size
    actual_bounds = get_effective_bounds(
        template_path, ph_bounds, prs.slide_width, prs.slide_height
    )
    positions_emu, _, _, _ = transform_positions(pos, actual_bounds, fixed_scale=scale)

    # Add new slide
    slide = prs.slides.add_slide(layout)

    # Remove placeholder shapes that would overlap
    delete_placeholder_shapes(slide, prs)

    if node_size is None:
        size_emu = compute_node_size(positions_emu, labels)
    else:
        size_emu = int(node_size * scale)
        min_dist = min_node_distance(positions_emu, labels)
        if min_dist is not None and size_emu > min_dist * 0.5:
            logger.warning(
                "node_size=%d EMU exceeds half the minimum inter-node "
                "distance (%d EMU); nodes may overlap",
                size_emu,
                int(min_dist),
            )

    # Split fuzzy entries (mode) from repeat entries (count); label
    # avoidance applies only to repeat brackets -- variant linkage labels
    # inside a fuzzy box must stay inside the box
    fuzzy_groups = [g for g in repeat_groups if "mode" in g]
    repeat_plain = [g for g in repeat_groups if "mode" not in g]

    # Fuzzy gray boxes are drawn first (PPT z-order = insertion order ->
    # below connectors and nodes); reversed inside: outer box inserted
    # first (bottom), nested inner boxes later -> inner borders visible.
    # XOR/OR textboxes are deferred until after edge labels (top z-order,
    # matching the image backend)
    # Highlight: decorations always dim while a plan is active; per-edge
    # color lists keep matched internals at full color (glycowork semantics)
    dimmed = plan is not None
    edge_colors = label_colors = None
    if dimmed:
        edge_colors = [
            None if idx in plan.matched_edge_idx else st.dim_link_color for idx in range(len(edges))
        ]
        label_colors = [
            None if idx in plan.matched_edge_idx else st.dim_link_label_color
            for idx in range(len(edges))
        ]

    fuzzy_label_specs = []
    if fuzzy_groups:
        fuzzy_label_specs = draw_fuzzy_boxes(
            slide.shapes,
            fuzzy_groups,
            positions_emu,
            size_emu,
            fill_hex=st.dim_fuzzy_box_color if dimmed else st.fuzzy_box_color,
            line_hex=(st.dim_fuzzy_box_line_color if dimmed else st.fuzzy_box_line_color),
            line_width_pt=st.fuzzy_box_line_width,
            edges=edges,
        )

    # Draw edges first (behind shapes)
    draw_connectors(
        slide.shapes,
        edges,
        positions_emu,
        line_hex=st.link_color,
        line_width_pt=eff_link_width,
        edge_colors=edge_colors,
    )

    # Reducing-end markers (after connectors, before nodes: z-order
    # mirrors the image backend where the squiggle sits above lines)
    if end:
        end_specs = end_marker_specs(positions_emu, size_emu, end)
        if end_specs:
            draw_end_markers(
                slide.shapes,
                end_specs,
                stroke_hex=(st.node_stroke_color.lstrip("#") if st.node_stroke_color else "000000"),
                stroke_width_pt=(eff_node_stroke if eff_node_stroke is not None else 1),
                font_size=font_size,
                font_family=resolved_font,
            )

    # Draw nodes (on top of connectors)
    used_monos = set()
    for node_id, (x_emu, y_emu) in positions_emu.items():
        if is_open_node(node_id):
            continue
        mono = labels[node_id]
        used_monos.add(mono)
        if dimmed and node_id not in plan.matched_nodes:
            comp, color_hex = st.resolve_dim(mono)
            node_line_hex = st.dim_node_stroke_color
        else:
            comp, color_hex = st.resolve(mono)
            node_line_hex = st.node_stroke_color
        draw_node(
            slide.shapes,
            x_emu,
            y_emu,
            size_emu,
            comp,
            color_hex,
            line_hex=node_line_hex,
            line_width_pt=eff_node_stroke,
        )

    # Draw repeat brackets (on top of nodes)
    if repeat_plain:
        draw_repeat_brackets(
            slide.shapes,
            repeat_plain,
            positions_emu,
            size_emu,
            font_size,
            resolved_font,
            bar_fill_hex=(st.dim_bracket_color if dimmed else st.bracket_color),
            count_text_hex=(st.dim_link_label_color if dimmed else None),
            bracket_width_pt=st.bracket_width,
            fuzzy_groups=fuzzy_groups,
            edges=edges,
        )

    # Draw legend (shapes) before labels so labels stay on top
    if used_monos:
        ys = [
            y_emu for node_id, (x_emu, y_emu) in positions_emu.items() if not is_open_node(node_id)
        ]
        content_bottom = max(ys) + size_emu if ys else None
        # Repeat brackets / fuzzy boxes can hang below the node row (tall
        # inner-fuzzy units); the legend row must clear them or it overlaps
        # the bracket caps (bracket_encloses_inner_fuzzy).
        if content_bottom is not None and repeat_groups and scale > 0:
            size_l = size_emu / scale
            # bracket_geometry consumes abstract units; fuzzy_box_pairs EMU --
            # keep each overhang in its own space, convert once at the end.
            min_y_abs = min(y for _x, y in pos.values())
            over_emu = 0.0
            # abstract-space pairs (native pad) for the bracket bbox union;
            # EMU pairs (pad_y refined) for the drawn box bottom
            fpairs_abs = (
                fuzzy_box_geoms(fuzzy_groups, size_l, positions=pos, edges=edges)
                if fuzzy_groups
                else []
            )
            nest_levels = repeat_nest_levels(repeat_groups)
            for g_i, g in enumerate(repeat_groups):
                if "mode" in g:
                    continue
                bbox = g["bbox"]
                inner, _outer = fuzzy_boxes_inside_repeat(g, fpairs_abs)
                if inner:
                    bbox = bbox_union_boxes(bbox, inner)
                geom = bracket_geometry(*bbox, size_l, nest_level=nest_levels[g_i])
                over_emu = max(over_emu, (min_y_abs - geom.y_bot) * scale)
            for geom, _g in fpairs_abs:
                over_emu = max(over_emu, (min_y_abs - geom.y0) * scale)
            if fuzzy_groups:
                # EMU y-down: drawn box bottom = -geom.y0; compare against the
                # deepest node row (max y), which content_bottom already covers
                for geom, _g in fuzzy_box_pairs(fuzzy_groups, positions_emu, size_emu, edges=edges):
                    over_emu = max(over_emu, -geom.y0 - max(ys))
            content_bottom += int(over_emu)
        slide_bounds = (0, 0, prs.slide_width, prs.slide_height)
        add_legend(
            slide,
            used_monos,
            font_size,
            resolved_font,
            slide_bounds,
            content_bottom=content_bottom,
            node_size_emu=size_emu,
            style=st,
            node_line_width_pt=eff_node_stroke,
        )

    # Draw labels last (on top of shapes and connectors)
    if show_linkage:
        draw_edge_labels(
            slide.shapes,
            edges,
            positions_emu,
            font_size,
            resolved_font,
            node_size=size_emu,
            repeat_groups=repeat_plain,
            size_emu=size_emu,
            fuzzy_groups=fuzzy_groups,
            text_hex=st.link_label_color,
            edge_label_colors=label_colors,
        )

    # XOR/OR labels inserted last (top z-order): same semantics as the
    # image backend's "drawn later + zorder=4"
    if fuzzy_label_specs:
        draw_fuzzy_mode_labels(
            slide.shapes,
            fuzzy_label_specs,
            font_size,
            resolved_font,
            text_hex=(st.dim_link_label_color if dimmed else None),
        )


def generate_snfg_pptx(
    csdb_list: List[str],
    template_path: Optional[str] = None,
    ratio: float = 1,
    font_size: float = 8,
    font_family: str = "sans-serif",
    compact_repeat: bool = True,
    split_fuzzy: bool = False,
    *,
    style: Union[None, str, dict, Style] = None,
    node_size: Optional[float] = None,
    node_stroke_width: Optional[float] = None,
    link_width: Optional[float] = None,
    show_linkage: bool = True,
    highlight_motif: Optional[str] = None,
    end: Optional[str] = None,
    show_unknown: bool = False,
) -> BytesIO:
    """Generate a PPTX file with one SNFG diagram per slide.

    Args:
        csdb_list: List of CSDB notation strings
        template_path: Path to .pptx/.potx template file, or None for blank
        ratio: Branch scaling ratio
        font_size: Font size for labels
        font_family: Font family name for labels and legend text
        compact_repeat: Show repeat units as [unit]ₙ instead of expanding
        split_fuzzy: expand <<A|B>>/<A|B> fuzzy blocks -- each input string
            emits [merged original, variant1, variant2, ...] as one slide each
            (see csdb.fuzzy.expand_fuzzy)
        style: None | preset name ('default'/'glycoworkbench') | dict | path
            to a JSON style file | Style instance. None keeps the historical
            built-in appearance byte-for-byte. One style applies to every
            slide.
        node_size: node radius in abstract layout units (same unit space as
            the image backend's mono_size). None keeps the automatic sizing
            (compute_node_size); an explicit value bypasses the size cap and
            logs a warning when nodes risk overlapping.
        node_stroke_width: node outline width in points; overrides the style
            value; None keeps style/backend default (0.25pt).
        link_width: connector line width in points; overrides the style value;
            None keeps style/backend default (Pt(1)).
        show_linkage: when False, edge linkage labels are not drawn. XOR/OR
            mode labels and repeat-count subscripts stay (structural
            annotations).
        highlight_motif: CSDB substructure string; matched elements keep the
            full palette, everything else is dimmed (glycowork-style). One
            motif applies to every slide; a structure without a match logs a
            warning and renders undimmed.
        end: reducing-end (right side) marker on every slide: 'freeEnd'
            (squiggle), 'redEnd' (squiggle + centered 'O') or any other
            non-empty string drawn as a text label (e.g. 'PA', '2AB').
            None/'' emits zero extra shapes.

    Returns:
        BytesIO containing the PPTX file
    """
    st = load_style(style)
    eff_node_stroke = node_stroke_width if node_stroke_width is not None else st.node_stroke_width
    eff_link_width = link_width if link_width is not None else st.link_width
    if split_fuzzy:
        from csdb2snfg.csdb.fuzzy import expand_fuzzy

        csdb_list = expand_fuzzy(csdb_list)
    if template_path and os.path.exists(template_path):
        prs = Presentation(template_path)
    else:
        prs = Presentation()

    # Detect placeholder from first slide layout
    ph_bounds = _find_placeholder(prs)
    ph_left, ph_top, ph_width, ph_height = ph_bounds

    layout = get_content_layout(prs)

    resolved_font = resolve_font_family(font_family)

    # Pass 1: compute positions and required size for every structure
    default_bounds = get_effective_bounds(
        template_path, ph_bounds, DEFAULT_SLIDE_W, DEFAULT_SLIDE_H
    )
    items, errors = _plan_slide_items(
        csdb_list,
        ratio=ratio,
        compact_repeat=compact_repeat,
        highlight_motif=highlight_motif,
        default_bounds=default_bounds,
        node_size=node_size,
        unknown_marker="?" if show_unknown else None,
    )

    # Set the slide size: max of all structures' needs, but at least the default
    max_needed_w = max((it[4] for it in items if it), default=DEFAULT_SLIDE_W)
    max_needed_h = max((it[5] for it in items if it), default=DEFAULT_SLIDE_H)
    if max_needed_w > DEFAULT_SLIDE_W or max_needed_h > DEFAULT_SLIDE_H:
        prs.slide_width = int(max_needed_w + 500000)
        prs.slide_height = int(max(max_needed_h + 500000, DEFAULT_SLIDE_H))

    # Pass 2: draw every structure, re-centering if the slide grew
    for item in items:
        if item is None:
            continue
        _draw_slide(
            prs,
            layout,
            item,
            template_path=template_path,
            ph_bounds=ph_bounds,
            st=st,
            eff_node_stroke=eff_node_stroke,
            eff_link_width=eff_link_width,
            font_size=font_size,
            resolved_font=resolved_font,
            node_size=node_size,
            show_linkage=show_linkage,
            end=end,
        )

    # Add errors slide if any failures
    if errors:
        _add_error_slide(prs, layout, errors, resolved_font)

    buf = BytesIO()
    prs.save(buf)
    buf.seek(0)
    return buf
