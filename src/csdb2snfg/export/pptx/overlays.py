"""Visual annotation layer of the python-pptx backend: connectors + repeat brackets."""

from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, MSO_AUTO_SIZE, PP_ALIGN
from pptx.util import Emu, Pt

from csdb2snfg.export.pptx.legend import _est_text_width_emu
from csdb2snfg.export.pptx.primitives import (
    hex_to_rgb,
    remove_shape_style,
    set_shape_fill_color,
    set_shape_line_color,
)
from csdb2snfg.export.pptx.text import LABEL_BOX_H, LABEL_BOX_W, add_centered_label, add_text_box
from csdb2snfg.snfg.geometry import (
    BRACKET_BOX_GAP_RATIO,
    BRACKET_MARKER_GAP_RATIO,
    FUZZY_BAND_RATIO,
    FUZZY_PAD_Y_RATIO,
    LABEL_PERP_RATIO,
    adjacent_bracket_vertical_xs,
    bbox_union_boxes,
    bracket_bounds,
    bracket_clamp_limits,
    bracket_geometry,
    bracket_vertical_xs,
    bracket_y_under_fuzzy,
    circle_clear_verticals,
    clamp_bracket_xs,
    edge_label_slots,
    end_squiggle_points,
    fuzzy_box_geoms,
    fuzzy_boxes_inside_repeat,
    repeat_nest_levels,
    sample_cubic_bezier,
)
from csdb2snfg.snfg.layout import parse_edge_label

# ─── Connectors ──────────────────────────────────────────────


def draw_connectors(
    shapes, edges, positions_emu, *, line_hex=None, line_width_pt=None, edge_colors=None
):
    """Draw straight-line connectors only (bottom z-order).

    line_hex/line_width_pt: None keeps the historical literals (black, Pt(1)).
    edge_colors: optional per-edge list (same indexing as `edges`) of hex
    colors or None; a non-None entry overrides line_hex for that edge.
    """
    for idx, (parent_id, child_id, _label_str) in enumerate(edges):
        if parent_id not in positions_emu or child_id not in positions_emu:
            continue
        x1, y1 = positions_emu[parent_id]
        x2, y2 = positions_emu[child_id]
        connector = shapes.add_connector(MSO_CONNECTOR.STRAIGHT, int(x1), int(y1), int(x2), int(y2))
        hex_ = None
        if edge_colors is not None and idx < len(edge_colors):
            hex_ = edge_colors[idx]
        if hex_ is None:
            hex_ = line_hex
        line = connector.line
        line.color.rgb = RGBColor(0, 0, 0) if hex_ is None else RGBColor(*hex_to_rgb(hex_))
        line.width = Pt(1) if line_width_pt is None else Pt(line_width_pt)
        remove_shape_style(connector)


def draw_edge_labels(
    shapes,
    edges,
    positions_emu,
    font_size,
    font_family="sans-serif",
    node_size=None,
    repeat_groups=None,
    size_emu=None,
    fuzzy_groups=None,
    *,
    text_hex=None,
    edge_label_colors=None,
):
    """
    Draw glycan linkage labels (top z-order).
    Reproduces the Matplotlib layout using center-alignment logic.
    fuzzy_groups: fuzzy gray-box entries (with node_ids), used to place fan-edge
    labels on the outside.
    text_hex: label color override; None keeps the historical black.
    edge_label_colors: optional per-edge list (same indexing as `edges`) of hex
    colors or None; a non-None entry overrides text_hex for both slots of that
    edge.
    """
    # Perpendicular offset keeping labels tight against their edge (same ratio as the image backend)
    offset_const = int(node_size * LABEL_PERP_RATIO) if node_size else Emu(20000)

    # Build bracket bounds info (EMU coordinates, for label avoidance on bracket-crossing edges)
    bounds = ()
    if repeat_groups and size_emu:
        bounds = bracket_bounds(
            repeat_groups,
            pad=int(size_emu * 1.5),
            positions=positions_emu,
            size=size_emu,
            edges=edges,
            # mirror the drawn boxes (pad/band included) so units wrapping a
            # fuzzy block avoid labels at the real verticals
            fuzzy_pairs=(
                fuzzy_box_pairs(
                    fuzzy_groups,
                    positions_emu,
                    size_emu,
                    edges=edges,
                    band=max(int(size_emu * FUZZY_BAND_RATIO), FUZZY_BAND_MIN_EMU),
                )
                if fuzzy_groups
                else []
            ),
            box_gap=int(size_emu * BRACKET_BOX_GAP_RATIO),
        )

    avoid_margin = int(size_emu * 0.3) if size_emu else 50000

    # Fuzzy variant node set: fan edges (one end inside the group, one outside)
    # need group info to pick the label's outside direction
    fuzzy_ids = set()
    for g in fuzzy_groups or ():
        fuzzy_ids.update(g.get("node_ids", ()))

    # Fuzzy fan edges converge at the shared endpoint: they carry the *same*
    # full edge label and their slots sit extremely close -> drawn once,
    # avoiding textbox ghosting. Dedup must stay restricted to that case:
    # neighbouring bonds with an incidentally equal glyph (e.g. a fuzzy fan
    # '2-α' next to a main-chain '6-α') are distinct information and must
    # both be drawn (same convention as the image backend)
    drawn_labels = []
    label_dedup_eps = int(node_size * 1.5) if node_size else 180000

    def _add_label(x, y, text, lk, endpoint, hex_=None):
        """Add a centered edge-label textbox unless it is a true fuzzy-fan
        duplicate.

        ``endpoint`` is the node this slot belongs to: the parent for the
        left/site slot, the child for the right/anomeric slot. Suppression
        requires ALL of: same slot text, identical full edge label ``lk``,
        the SAME ``endpoint``, and slots within ``label_dedup_eps`` -- the
        duplicated slot that fan edges converging at a shared residue carry
        (anti-ghosting convention shared with the image backend). Labels
        belonging to different bonds never merge."""
        for lx, ly, lt, ll, ee in drawn_labels:
            if (
                lt == text
                and ll == lk
                and ee == endpoint
                and (lx - x) ** 2 + (ly - y) ** 2 < label_dedup_eps**2
            ):
                return
        drawn_labels.append((x, y, text, lk, endpoint))
        add_centered_label(shapes, x, y, text, font_size, font_family, text_hex=hex_)

    for idx, (parent_id, child_id, label_str) in enumerate(edges):
        if parent_id not in positions_emu or child_id not in positions_emu:
            continue

        x1, y1 = positions_emu[parent_id]
        x2, y2 = positions_emu[child_id]

        if not label_str:
            continue

        # Parse the linkage symbol, e.g. "4-1" -> left="4", right="1"
        left_text, right_text = parse_edge_label(label_str)

        # Fan edge: direction the variant end deviates from the chain axis
        # (the same-sign rule is self-consistent in EMU y-down space)
        ny_hint = None
        if fuzzy_ids and (parent_id in fuzzy_ids) != (child_id in fuzzy_ids):
            dy_off = (y1 - y2) if parent_id in fuzzy_ids else (y2 - y1)
            ny_hint = 1.0 if dy_off > 0 else -1.0

        x_l, y_l, x_r, y_r = edge_label_slots(
            parent_id,
            child_id,
            (x1, y1),
            (x2, y2),
            perp=offset_const,
            y_up=False,
            along_mode="frac",
            bounds=bounds,
            avoid_margin=avoid_margin,
            avoid_floor=True,
            ny_hint=ny_hint,
        )

        # Draw the left/right (i.e. parent/child) labels
        slot_hex = text_hex
        if edge_label_colors is not None and idx < len(edge_label_colors):
            slot_hex = edge_label_colors[idx] or text_hex
        if left_text:
            _add_label(x_l, y_l, left_text, label_str, parent_id, slot_hex)
        if right_text:
            _add_label(x_r, y_r, right_text, label_str, child_id, slot_hex)


# ─── Fuzzy gray boxes (CSDB <<XOR>>/<OR> structural ambiguity) ─────────────


# PPTX title-band EMU floor: in compact drawings with ratio<1 compute_node_size
# can shrink to ~65k EMU; a 0.55*size title band minus the 0.2*size inset and
# the ink height would leave negative clearance -> floor it (derivation in the
# geometry.FUZZY_BAND_RATIO comment and tests/test_csdb2snfg_pptx.py)
FUZZY_BAND_MIN_EMU = 110000


def fuzzy_box_pairs(fuzzy_groups, positions_emu, size_emu, *, edges=None, band=None):
    """-> [(FuzzyBoxGeom, group)] in draw order, with per-group vertical pad.

    The box must swallow the fan bonds' anomeric labels (right slots) ink-deep:
    the native 1.7*size pad is sized off the capped node radius and can fall
    short of the slot reach (testdata30: alpha centers land below the box
    bottom). The site digits (left slots, outer bond half) stay outside by
    design, as in the image backend. Every consumer (drawn rects, bracket
    enclosure/caps, label-avoidance bounds) must use THIS so the geometries
    agree.
    """
    flipped = {nid: (x, -y) for nid, (x, y) in positions_emu.items()}
    offset_const = int(size_emu * LABEL_PERP_RATIO)
    pairs = []
    for fg in fuzzy_groups:
        members = set(fg.get("node_ids", ()))
        var_ys = [flipped[n][1] for n in members if n in flipped]
        pad_y = None
        if var_ys and edges:
            top = min(var_ys)
            reach = None
            for e in edges:
                p, c = e[0], e[1]
                if (p in members) == (c in members):
                    continue
                if p not in flipped or c not in flipped:
                    continue
                (x1, y1), (x2, y2) = flipped[p], flipped[c]
                dy_off = (y1 - y2) if p in members else (y2 - y1)
                ny_hint = 1.0 if dy_off > 0 else -1.0
                _xl, _yl, _xr, y_r = edge_label_slots(
                    p,
                    c,
                    (x1, y1),
                    (x2, y2),
                    perp=offset_const,
                    y_up=False,
                    along_mode="frac",
                    ny_hint=ny_hint,
                )
                # flipped y-up: deeper on screen = smaller y; the pad must
                # reach from the topmost variant down to the deepest slot
                if reach is None or top - y_r > reach:
                    reach = top - y_r
            if reach is not None:
                pad_y = max(size_emu * FUZZY_PAD_Y_RATIO, reach + LABEL_BOX_H // 4)
        pairs.append((fg, pad_y))
    # fuzzy_box_geoms reverses its input (outer box first = bottom z-order);
    # per-group calls keep the per-group pad, so reverse the concatenation.
    ordered = []
    for fg, pad_y in pairs:
        ordered.extend(
            fuzzy_box_geoms([fg], size_emu, positions=flipped, band=band, edges=edges, pad_y=pad_y)
        )
    ordered.reverse()
    return ordered


def draw_fuzzy_boxes(
    shapes,
    fuzzy_groups,
    positions_emu,
    size_emu,
    *,
    fill_hex=None,
    line_hex=None,
    line_width_pt=None,
    edges=None,
):
    """Draw only the fuzzy gray-box rectangles (bottom z-order); return XOR/OR label specs.

    Must be called before connectors/nodes (PPT z-order = insertion order, box
    at the bottom); XOR/OR textboxes are inserted by draw_fuzzy_mode_labels
    after the edge labels (top z-order, matching the image backend's
    "drawn later + zorder=4").
    The top pad contains the title band; the corner label is fixed at the
    top-center inside the box (geometry.fuzzy_box_geometry) and does not move
    with label crowding.
    fuzzy_groups: layout order (inner first, outer last), reversed inside ->
    outer box inserted first (bottom), nested inner box borders visible.
    The bbox is recomputed from node_ids in EMU coordinates (same approach as
    draw_repeat_brackets); EMU y-down -> negate y to flip into y-up for the
    shared geometry, flip back after getting the geom.
    -> [(left, top, mode)], consumed by draw_fuzzy_mode_labels.
    """
    band = max(int(size_emu * FUZZY_BAND_RATIO), FUZZY_BAND_MIN_EMU)
    fill = fill_hex if fill_hex is not None else "#DDDDDD"
    line = line_hex.lstrip("#") if line_hex is not None else "000000"
    width_pt = line_width_pt if line_width_pt is not None else 0.75
    specs = []
    for geom, fg in fuzzy_box_pairs(fuzzy_groups, positions_emu, size_emu, edges=edges, band=band):
        left = int(geom.x0)
        top = int(-geom.y1)  # flip y-up back to EMU y-down, larger value = top
        width = int(geom.x1 - geom.x0)
        height = int(geom.y1 - geom.y0)
        box = shapes.add_shape(MSO_SHAPE.RECTANGLE, left, top, width, height)
        set_shape_fill_color(box, fill)
        set_shape_line_color(box, line, width_pt)
        remove_shape_style(box)
        # Label textbox: horizontal center pinned to the box's horizontal
        # center (CENTER alignment -> ink center = anchor)
        specs.append(
            (int(geom.label_x - LABEL_BOX_W / 2), int(-geom.label_y), fg.get("mode", "OR"))
        )
    return specs


def draw_fuzzy_mode_labels(shapes, specs, font_size, font_family="Arial", *, text_hex=None):
    """XOR/OR labels (top z-order): call after the edge labels.

    Textboxes are anchored TOP + CENTER, reproducing the ink semantics of the
    image backend's ha='center'/va='top' (the old MIDDLE+Center implementation
    pushed the ink into the box's linkage-label band): ink extends downward
    from the anchor at the top-center inside the box, landing in the title band.
    text_hex: None keeps the historical black.
    """
    for left, top, mode in specs:
        add_text_box(
            shapes,
            left,
            top,
            LABEL_BOX_W,
            LABEL_BOX_H,
            mode,
            Pt(max(font_size - 1, 6)),
            font_family,
            MSO_ANCHOR.TOP,
            2,  # 2 = horizontally centered in box (Center)
            text_hex=text_hex,
        )


# ─── Reducing-end markers (end= parameter) ───────────────────


def draw_end_markers(
    shapes, specs, *, stroke_hex="000000", stroke_width_pt=1, font_size=8, font_family="Arial"
):
    """Draw end= markers in EMU y-down space.

    Squiggle: the GlycoWorkbench createEnd cubic Bezier sampled into 32
    deterministic segments and emitted as an OPEN freeform custGeom with
    noFill (verified against python-pptx 1.0.2 build_freeform +
    fill.background()). 'redEnd' adds a centered 'O' textbox; text-kind specs
    draw a left-anchored label right of the stub tip. Markers stay full-color
    even while a highlight plan is active (explicit user annotation).
    """
    for spec in specs:
        if spec.kind == "squiggle":
            pts = sample_cubic_bezier(*end_squiggle_points(spec, y_up=False))
            fb = shapes.build_freeform(int(pts[0][0]), int(pts[0][1]))
            fb.add_line_segments([(int(x), int(y)) for x, y in pts[1:]], close=False)
            sh = fb.convert_to_shape()
            sh.fill.background()
            set_shape_line_color(sh, stroke_hex, stroke_width_pt)
            remove_shape_style(sh)
            if spec.text:
                add_text_box(
                    shapes,
                    int(spec.cx - LABEL_BOX_W / 2),
                    int(spec.cy - LABEL_BOX_H / 2),
                    LABEL_BOX_W,
                    LABEL_BOX_H,
                    spec.text,
                    Pt(font_size),
                    font_family,
                    MSO_ANCHOR.MIDDLE,
                    2,
                )  # 2 = Center
        else:
            add_text_box(
                shapes,
                int(spec.cx),
                int(spec.cy - LABEL_BOX_H / 2),
                LABEL_BOX_W,
                LABEL_BOX_H,
                spec.text,
                Pt(font_size),
                font_family,
                MSO_ANCHOR.MIDDLE,
                1,
            )  # 1 = Left


# ─── Repeat-unit brackets ────────────────────────────────────

BRACKET_FONT_FAMILY = "Times New Roman"
BRACKET_LINE_WIDTH_PT = 0.75


def _add_bracket_shape(
    shapes,
    left,
    top,
    width,
    height,
    is_right,
    *,
    line_hex=None,
    line_width_pt=None,
):
    """Add a thin vector bracket autoshape and an invisible parseable bracket character.

    The shape itself is a ``leftBracket``/``rightBracket`` preset, so the stroke
    stays thin even when the shape is stretched to enclose a tall repeat unit.
    The shape text holds a single invisible ``'['`` / ``']'`` character so a
    text-bracket parser can recover the bracket pair; the visible count label
    is drawn separately at the lower-right of the right bracket.
    """
    shape_type = MSO_SHAPE.RIGHT_BRACKET if is_right else MSO_SHAPE.LEFT_BRACKET
    shape = shapes.add_shape(shape_type, int(left), int(top), int(width), int(height))
    set_shape_line_color(
        shape,
        line_hex.lstrip("#") if line_hex is not None else "000000",
        line_width_pt if line_width_pt is not None else BRACKET_LINE_WIDTH_PT,
    )
    shape.fill.background()
    remove_shape_style(shape)

    tf = shape.text_frame
    tf.word_wrap = False
    tf.auto_size = MSO_AUTO_SIZE.NONE
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.LEFT

    # Parseable bracket character: invisible but present so the read-side parser
    # can recover the bracket pair and repeat count.
    bracket_run = p.add_run()
    bracket_run.text = "]" if is_right else "["
    bracket_run.font.size = Pt(8)
    bracket_run.font.name = BRACKET_FONT_FAMILY
    bracket_run.font.fill.background()

    return shape


def _add_count_subscript_textbox(
    shapes,
    left,
    top,
    count,
    font_pt,
    *,
    text_hex=None,
):
    """Add a small subscript count label positioned at the lower-right of a bracket."""
    text = str(count)
    width = _est_text_width_emu(text, font_pt, BRACKET_FONT_FAMILY) + int(font_pt * 12700 * 0.3)
    height = int(font_pt * 12700 * 1.4)
    tb = shapes.add_textbox(int(left), int(top), int(width), int(height))
    tf = tb.text_frame
    tf.word_wrap = False
    tf.auto_size = MSO_AUTO_SIZE.NONE
    tf.vertical_anchor = MSO_ANCHOR.BOTTOM
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.LEFT

    run = p.add_run()
    run.text = text
    run.font.size = Pt(font_pt)
    run.font.name = BRACKET_FONT_FAMILY
    if text_hex is not None:
        run.font.color.rgb = RGBColor(*hex_to_rgb(text_hex))
    rPr = run._r.get_or_add_rPr()
    rPr.set("baseline", "-25000")
    return tb


def draw_repeat_brackets(
    shapes,
    repeat_groups,
    positions_emu,
    size_emu,
    font_size,
    font_family="Arial",
    *,
    bar_fill_hex=None,
    count_text_hex=None,
    bracket_width_pt=None,
    fuzzy_groups=None,
    edges=None,
):
    """Draw brackets and subscript count labels for compact repeat groups in PPTX.

    Brackets are rendered as thin ``leftBracket``/``rightBracket`` autoshapes
    that scale to the computed bracket geometry. Each shape carries an invisible
    ``'['`` / ``']'`` character so the read-side parser can recover repeat
    units; the visible count subscript is drawn in a separate textbox at the
    lower-right of the right bracket.

    bar_fill_hex: line color for the bracket strokes; None keeps native black.
    count_text_hex: text color for the visible subscript count; None keeps
        native black.
    bracket_width_pt: stroke width for the bracket lines; None keeps the native
        thin width (0.75 pt).
    fuzzy_groups: fuzzy entries of the same layout; caps are shortened under/
    over any gray box hanging into the bracket columns (same rule as image).
    """
    fpairs = []
    if fuzzy_groups:
        # Same pad/band as the drawn rects, so enclosure and cap shortening
        # see exactly the boxes on the slide.
        fpairs = fuzzy_box_pairs(
            fuzzy_groups,
            positions_emu,
            size_emu,
            edges=edges,
            band=max(int(size_emu * FUZZY_BAND_RATIO), FUZZY_BAND_MIN_EMU),
        )
    nest_levels = repeat_nest_levels(repeat_groups)
    vert_xs = None
    if edges is not None:
        vert_xs = adjacent_bracket_vertical_xs(repeat_groups, edges, positions_emu, size_emu)
    for rg_i, rg in enumerate(repeat_groups):
        count = rg["count"]

        # Compute each group's EMU bounding box from node_ids
        group_ids = rg.get("node_ids", [])
        group_positions = [positions_emu[nid] for nid in group_ids if nid in positions_emu]
        if not group_positions:
            continue

        group_xs = [x for x, y in group_positions]
        group_ys = [-y for x, y in group_positions]  # y-up for the shared geometry

        inner_boxes, outer_boxes = fuzzy_boxes_inside_repeat(rg, fpairs) if fpairs else ([], [])
        bbox = (min(group_xs), min(group_ys), max(group_xs), max(group_ys))
        if inner_boxes:
            # A fuzzy block inside the unit: the bracket must ENCLOSE the gray
            # boxes, so merge their extents into the bbox before the pad.
            bbox = bbox_union_boxes(bbox, inner_boxes)

        # Bracket geometry shared with the image backend, computed y-up here
        geom = bracket_geometry(*bbox, size_emu, nest_level=nest_levels[rg_i])
        # Verticals sit EXACTLY on the entry/exit bond midpoints (same rule as
        # the image backend): the bond's two label chars straddle them one per
        # side. Sides without a row crossing bond fall back to the historical
        # corridor-clamped bbox placement.
        mid_l, mid_r = (None, None)
        if edges is not None:
            # Adjacent units on the same row share a bond midpoint; nudge the
            # two verticals apart so the ][ brackets do not coincide.
            mid_l, mid_r = (
                vert_xs[rg_i]
                if vert_xs is not None
                else bracket_vertical_xs(rg, edges, positions_emu)
            )
        if inner_boxes:
            # The bracket must still ENCLOSE inner gray boxes: should a box
            # edge reach past its midpoint vertical, hug the box just outside
            # instead (layout lengthens the crossing bonds on main-chain rows,
            # so this fallback stays inactive there). Sides without a row
            # crossing bond take the historical box-hug placement verbatim.
            gap = int(size_emu * BRACKET_BOX_GAP_RATIO)
            box_l = min(b.x0 for b in inner_boxes) - gap
            box_r = max(b.x1 for b in inner_boxes) + gap
            # Only the box-hug value needs circle clearing (legacy semantics):
            # a blanket clear would chain-push verticals into off-row nodes
            # sharing the column (entry_0056).
            box_l, box_r = circle_clear_verticals(box_l, box_r, positions_emu, size_emu)
            mid_l = box_l if mid_l is None else min(mid_l, box_l)
            mid_r = box_r if mid_r is None else max(mid_r, box_r)
        if mid_l is None or mid_r is None:
            # No inner box and no row crossing bond on that side: historical
            # corridor-clamped bbox placement.
            limits = bracket_clamp_limits(rg, positions_emu, size_emu)
            if limits:
                clamped = clamp_bracket_xs(geom.left_x, geom.right_x, limits)
                if mid_l is None:
                    mid_l = clamped[0]
                if mid_r is None:
                    mid_r = clamped[1]
        geom = geom._replace(left_x=mid_l, right_x=mid_r)
        if fpairs:
            # Flipped y-up space: every row y is negative here, so the cap floor
            # must be relative to the unit's own row -- an absolute clamp would
            # push top caps off the slide (geometry.bracket_y_under_fuzzy).
            # Only OUTER boxes shorten the caps; inner boxes are enclosed.
            ids = rg.get("backbone_ids") or rg.get("node_ids", [])
            row_y = next((-positions_emu[i][1] for i in ids if i in positions_emu), None)
            y_top_u, y_bot_u = bracket_y_under_fuzzy(
                geom, outer_boxes, size_emu, margin=size_emu * 0.1, row_y=row_y
            )
            geom = geom._replace(y_top=y_top_u, y_bot=y_bot_u)
        left_x = geom.left_x
        right_x = geom.right_x
        y_top = -geom.y_top  # in PPT smaller y = top
        y_bot = -geom.y_bot  # in PPT larger y = bottom
        cap = int(geom.cap)  # bracket cap length
        bracket_height = int(y_bot - y_top)

        # Left bracket '['
        _add_bracket_shape(
            shapes,
            left_x,
            y_top,
            cap,
            bracket_height,
            is_right=False,
            line_hex=bar_fill_hex,
            line_width_pt=bracket_width_pt,
        )

        # Right bracket ']'
        _add_bracket_shape(
            shapes,
            right_x - cap,
            y_top,
            cap,
            bracket_height,
            is_right=True,
            line_hex=bar_fill_hex,
            line_width_pt=bracket_width_pt,
        )

        # Visible subscript count at the lower-right of the right bracket,
        # hugging just BELOW the bracket bottom so it never runs into an
        # adjacent repeat's tall bracket vertical. The sub-baseline
        # (rPr baseline=-25000) lowers the glyph by 25% of its size, so the
        # box top is raised by that same amount to keep the visible glyph
        # tight against the bracket bottom instead of floating lower.
        count_font_pt = max(6, min(14, int(bracket_height / 12700 / 3)))
        count_tb = add_text_box(
            shapes,
            int(right_x + size_emu * BRACKET_MARKER_GAP_RATIO),
            int(y_bot - count_font_pt * 12700 * 0.25),
            _est_text_width_emu(str(count), count_font_pt, BRACKET_FONT_FAMILY)
            + int(count_font_pt * 12700 * 0.3),
            int(count_font_pt * 12700 * 1.4),
            str(count),
            Pt(count_font_pt),
            BRACKET_FONT_FAMILY,
            MSO_ANCHOR.TOP,
            PP_ALIGN.LEFT,
            text_hex=count_text_hex,
        )
        count_run = count_tb.text_frame.paragraphs[0].runs[0]
        count_run._r.get_or_add_rPr().set("baseline", "-25000")
