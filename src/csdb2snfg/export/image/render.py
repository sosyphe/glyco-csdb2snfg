"""matplotlib backend main renderer: orchestrator + shape/bracket/figure helpers."""

from typing import TYPE_CHECKING, Any, List, Optional, Set, Tuple, Union

import matplotlib.pyplot as plt

from csdb2snfg.export.image.legend import add_snfg_legend
from csdb2snfg.export.image.shapes import draw_shape
from csdb2snfg.snfg.geometry import (
    BRACKET_BOX_GAP_RATIO,
    BRACKET_MARKER_GAP_RATIO,
    LABEL_PERP_RATIO,
    adjacent_bracket_vertical_xs,
    bbox_union_boxes,
    bracket_bounds,
    bracket_clamp_limits,
    bracket_geometry,
    bracket_pad,
    bracket_vertical_xs,
    bracket_y_under_fuzzy,
    circle_clear_verticals,
    clamp_bracket_xs,
    edge_label_slots,
    end_marker_specs,
    end_squiggle_points,
    fuzzy_box_geoms,
    fuzzy_boxes_inside_repeat,
    repeat_nest_levels,
    shape_vcenter_offset,
)
from csdb2snfg.snfg.layout import (
    EdgeList,
    LabelMap,
    Positions,
    is_open_node,
    parse_edge_label,
    prepare_layout_ext,
)
from csdb2snfg.snfg.style import Style, load_style

if TYPE_CHECKING:
    from csdb2snfg.snfg.highlight import HighlightPlan

# ─── Bracket drawing ─────────────────────────────────────────


def split_groups(repeat_groups: List[dict]) -> Tuple[List[dict], List[dict]]:
    """Split into (repeat entries, fuzzy entries): fuzzy entries carry 'mode' (XOR/OR)."""
    fuzzy = [g for g in repeat_groups if "mode" in g]
    plain = [g for g in repeat_groups if "mode" not in g]
    return plain, fuzzy


def draw_fuzzy_boxes(
    ax,
    fuzzy_groups,
    mono_size,
    font_size,
    *,
    fill_color=None,
    line_color=None,
    line_width=None,
    mode_label_color=None,
    positions=None,
    edges=None,
):
    """Gray boxes wrapping fuzzy variants + OR/XOR label at the top-center inside each box.

    Style reference tests/testdata/glycan.svg: #dddddd fill, black outline
    (zorder=0 -> below edges/nodes). The label is fixed at the top-center
    inside the box (ha='center'/va='top', see geometry.fuzzy_box_geometry):
    the top pad additionally contains a title band of
    FUZZY_BAND_RATIO*mono_size; the linkage-label band of horizontal/open
    stubs (y_max + 0.55*mono) lies below it, so the corner-label position
    does not move with label crowding.
    fuzzy_groups: layout order (inner first, outer last), reversed inside ->
    outer boxes drawn first, nested inner box borders stay visible.
    Color/width kwargs: None keeps the historical literals (#dddddd fill,
    black outline, lw 0.8, default text color).
    """
    face = fill_color if fill_color is not None else "#dddddd"
    edge = line_color if line_color is not None else "black"
    lw = line_width if line_width is not None else 0.8
    text_kw = {} if mode_label_color is None else {"color": mode_label_color}
    for geom, fg in fuzzy_box_geoms(fuzzy_groups, mono_size, positions=positions, edges=edges):
        rect = plt.Rectangle(
            (geom.x0, geom.y0),
            geom.x1 - geom.x0,
            geom.y1 - geom.y0,
            facecolor=face,
            edgecolor=edge,
            lw=lw,
            zorder=0,
        )
        ax.add_patch(rect)
        ax.text(
            geom.label_x,
            geom.label_y,
            fg["mode"],
            fontsize=font_size - 2,
            rotation=0,
            ha="center",
            va="top",
            zorder=4,
            **text_kw,
        )


def draw_repeat_brackets(
    ax,
    repeat_groups,
    mono_size,
    font_size,
    *,
    color=None,
    line_width=None,
    count_color=None,
    positions=None,
    fuzzy_groups=None,
    edges=None,
):
    """Draw brackets and subscript count labels for compact repeat groups.

    Color/width kwargs: None keeps the historical literals (black, lw 0.8,
    default text color). positions: layout positions in the same space as
    rg['bbox']; given, the bracket verticals are clamped into the circle-free
    corridors beside the unit (see geometry.bracket_clamp_limits) so units
    widened by off-row nodes (fuzzy variants) never get a vertical drawn
    through a residue circle. fuzzy_groups: fuzzy entries of the same layout;
    caps are shortened under/over any gray box hanging into the bracket
    columns (geometry.bracket_y_under_fuzzy).
    """
    col = color if color is not None else "black"
    lw = line_width if line_width is not None else 0.8
    count_kw = {} if count_color is None else {"color": count_color}
    fpairs = (
        fuzzy_box_geoms(fuzzy_groups, mono_size, positions=positions, edges=edges)
        if fuzzy_groups
        else []
    )
    nest_levels = repeat_nest_levels(repeat_groups)
    vert_xs = None
    if positions is not None and edges is not None:
        vert_xs = adjacent_bracket_vertical_xs(repeat_groups, edges, positions, mono_size)
    for rg_i, rg in enumerate(repeat_groups):
        x_min, y_min, x_max, y_max = rg["bbox"]
        count = rg["count"]
        inner_boxes, outer_boxes = fuzzy_boxes_inside_repeat(rg, fpairs) if fpairs else ([], [])
        if inner_boxes:
            # A fuzzy block inside the unit ('/<<A|B>>/n=2/'): the bracket
            # must ENCLOSE the gray boxes, so merge their extents into the
            # bbox before the pad is applied.
            x_min, y_min, x_max, y_max = bbox_union_boxes((x_min, y_min, x_max, y_max), inner_boxes)
        geom = bracket_geometry(x_min, y_min, x_max, y_max, mono_size, nest_level=nest_levels[rg_i])
        if positions is not None:
            # Verticals sit EXACTLY on the entry/exit bond midpoints: the two
            # edge-label chars of each bond (residue centre +/- 0.4*bond)
            # straddle them one per side, and half a bond clears every residue
            # circle at default bond lengths.  Adjacent units on the same row
            # share a midpoint, so nudge their verticals apart to keep ][
            # brackets visually separated.
            mid_l, mid_r = (None, None)
            if edges is not None:
                mid_l, mid_r = (
                    vert_xs[rg_i]
                    if vert_xs is not None
                    else bracket_vertical_xs(rg, edges, positions)
                )
            if inner_boxes:
                # The bracket must still ENCLOSE inner gray boxes: should a
                # box edge reach past its midpoint vertical, hug the box just
                # outside instead (layout lengthens the crossing bonds on
                # main-chain rows, so this fallback stays inactive there).
                # Sides without a row crossing bond (nested/degenerate units)
                # take the historical box-hug placement verbatim. Only the
                # box-hug value needs circle clearing (legacy semantics):
                # midpoints clear every circle at sane bond lengths, and a
                # blanket clear would chain-push verticals into off-row
                # nodes sharing the column (entry_0056).
                gap = mono_size * BRACKET_BOX_GAP_RATIO
                box_l = min(b.x0 for b in inner_boxes) - gap
                box_r = max(b.x1 for b in inner_boxes) + gap
                box_l, box_r = circle_clear_verticals(box_l, box_r, positions, mono_size)
                mid_l = box_l if mid_l is None else min(mid_l, box_l)
                mid_r = box_r if mid_r is None else max(mid_r, box_r)
            if mid_l is None or mid_r is None:
                # No inner box and no row crossing bond on that side:
                # historical corridor-clamped bbox placement.
                limits = bracket_clamp_limits(rg, positions, mono_size)
                if limits:
                    clamped = clamp_bracket_xs(geom.left_x, geom.right_x, limits)
                    if mid_l is None:
                        mid_l = clamped[0]
                    if mid_r is None:
                        mid_r = clamped[1]
            geom = geom._replace(left_x=mid_l, right_x=mid_r)
        if fpairs:
            # The cap floor is relative to the unit's own chain row: repeats on
            # branches sit at y != 0 and an absolute clamp would stretch the
            # bracket across the main chain (geometry.bracket_y_under_fuzzy).
            # Only OUTER boxes (hanging beside the unit into the bracket
            # columns) shorten the caps; inner boxes are enclosed instead.
            row_y = None
            if positions is not None:
                ids = rg.get("backbone_ids") or rg.get("node_ids", [])
                row_y = next((positions[i][1] for i in ids if i in positions), None)
            y_top, y_bot = bracket_y_under_fuzzy(
                geom, outer_boxes, mono_size, margin=mono_size * 0.1, row_y=row_y
            )
            geom = geom._replace(y_top=y_top, y_bot=y_bot)

        # Left bracket [
        ax.plot(
            [geom.left_x + geom.cap, geom.left_x, geom.left_x, geom.left_x + geom.cap],
            [geom.y_top, geom.y_top, geom.y_bot, geom.y_bot],
            color=col,
            lw=lw,
            zorder=3,
        )
        # Right bracket ]
        ax.plot(
            [geom.right_x - geom.cap, geom.right_x, geom.right_x, geom.right_x - geom.cap],
            [geom.y_top, geom.y_top, geom.y_bot, geom.y_bot],
            color=col,
            lw=lw,
            zorder=3,
        )
        # Subscript text: plain characters instead of Unicode subscript code
        # points; font family/size exactly match the edge labels (Unicode
        # subscripts fall back on fonts missing the glyphs and are inherently
        # smaller); the position at the bracket bottom conveys the subscript.
        ax.text(
            geom.right_x + BRACKET_MARKER_GAP_RATIO * mono_size,
            geom.y_bot,
            str(count),
            fontsize=font_size - 1,
            va="top",
            ha="left",
            zorder=4,
            **count_kw,
        )


# ─── Reducing-end markers ────────────────────────────────────


def draw_end_markers(ax, specs, *, stroke_color="black", stroke_width=None, font_size=12):
    """Draw end= markers at the right (reducing) end: squiggle and/or text.

    Squiggle: exact cubic Bezier (matplotlib Path CURVE4) ported from
    GlycoWorkbench's createEnd; open curve, no fill. 'redEnd' adds a centered
    'O'; text-kind specs draw a left-anchored label right of the stub tip.
    Markers stay full-color even while a highlight plan is active (explicit
    user annotation).
    """
    from matplotlib.patches import PathPatch
    from matplotlib.path import Path

    lw = stroke_width if stroke_width is not None else 1
    for spec in specs:
        if spec.kind == "squiggle":
            p0, p1, p2, p3 = end_squiggle_points(spec, y_up=True)
            path = Path([p0, p1, p2, p3], [Path.MOVETO, Path.CURVE4, Path.CURVE4, Path.CURVE4])
            ax.add_patch(
                PathPatch(
                    path,
                    facecolor="none",
                    edgecolor=stroke_color,
                    lw=lw,
                    capstyle="round",
                    joinstyle="round",
                    zorder=2,
                    label="snfg-end-marker",
                )
            )
            if spec.text:
                ax.text(
                    spec.cx,
                    spec.cy,
                    spec.text,
                    fontsize=font_size,
                    ha="center",
                    va="center",
                    zorder=4,
                )
        else:
            ax.text(
                spec.cx, spec.cy, spec.text, fontsize=font_size, ha="left", va="center", zorder=4
            )


# ─── Figure measurement and resizing ─────────────────────────


def main_scale_inches(fig, ax):
    """Inches per data unit of the main axes after aspect-equal shrink. Call
    fig.canvas.draw() first."""
    p0 = ax.transData.transform((0, 0))
    p1 = ax.transData.transform((1, 0))
    return abs(p1[0] - p0[0]) / fig.dpi


def content_bbox_inches(fig, ax, renderer):
    """Inch bbox of the actual main content (all visible artists incl.
    bracket subscripts/edge labels).

    Deliberately not ax.get_tightbbox(): whether it includes the axes patch
    varies across matplotlib versions; a manual union is the most
    deterministic. axis('off') already made patch/spines invisible, so they
    are skipped.
    """
    from matplotlib.transforms import Bbox

    dpi = fig.dpi
    boxes = []
    for ch in ax.get_children():
        if not ch.get_visible():
            continue
        try:
            bb = ch.get_tightbbox(renderer) if hasattr(ch, "get_tightbbox") else None
            if bb is None:
                bb = ch.get_window_extent(renderer)
        except Exception:
            bb = ch.get_window_extent(renderer)
        if bb is not None and bb.width >= 0 and bb.height >= 0:
            boxes.append(bb)
    u = Bbox.union(boxes) if boxes else ax.get_window_extent(renderer)
    return u.x0 / dpi, u.y0 / dpi, u.x1 / dpi, u.y1 / dpi  # x0,y0,x1,y1 in inches


def grow_figure_for_legend(fig, legend_ax, margin_in=0.0):
    """Grow the figure when the legend bottom dips below the canvas: all axes shift
    up by delta in inch geometry, fractions recomputed against the new height ->
    s_main and the content-legend gap both stay unchanged."""
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    lb = legend_ax.get_tightbbox(renderer)
    if lb is None:
        return
    bottom_in = lb.y0 / fig.dpi
    if bottom_in >= margin_in:
        return
    H = fig.get_figheight()
    delta = margin_in - bottom_in
    H_new = H + delta
    # Compute new fractions against H_new first, then resize the canvas
    # (forward=False leaves child axes untouched)
    rects = []
    for a in fig.axes:
        p = a.get_position(original=True)  # explicit rect before aspect adjustment
        y0_in = p.y0 * H + delta  # shift everything up by delta
        h_in = p.height * H  # inch height unchanged -> s_main unchanged
        rects.append((a, [p.x0, y0_in / H_new, p.width, h_in / H_new]))
    fig.set_size_inches(fig.get_figwidth(), H_new, forward=False)
    for a, r in rects:
        a.set_position(r)


# ─── Main orchestrator ───────────────────────────────────────


def _draw_edges_and_labels(
    ax: "plt.Axes",
    pos: Positions,
    edges: EdgeList,
    *,
    mono_size: float,
    font_size: float,
    show_linkage: bool,
    plan: Optional["HighlightPlan"],
    st: Style,
    bounds: List[dict],
    fuzzy_groups: List[dict],
    eff_link_width: Optional[float],
) -> None:
    """Draw all chain edges plus their linkage labels (verbatim extraction).

    Artist creation order (zorder=1 lines, then per-edge zorder=4 label
    texts) is part of the byte-stable default output — do not reorder or
    batch. The nested ``_draw_label`` closure deduplicates true fuzzy-fan
    duplicates only (identical full edge label + shared endpoint node +
    within ``label_dedup_eps``); same-glyph labels of different bonds must
    both draw.
    """
    # Fuzzy fan edges converge at the shared endpoint: they carry the *same*
    # full edge label (site/configuration taken from the shared residue) and
    # their slots sit extremely close -> drawn once, avoiding visual ghosting.
    # Dedup must stay restricted to that case: neighbouring bonds with an
    # incidentally equal glyph (e.g. a fuzzy fan '2-α' next to a main-chain
    # '6-α') are distinct information and must both be drawn.
    drawn_labels = []
    label_dedup_eps = mono_size * 1.5  # identical labels at the fan convergence
    # end (the same residue's site/configuration carried by multiple fan edges)
    # are drawn only once within this radius

    # Fuzzy variant node set: fan edges (one end inside the group, one outside)
    # need group info to pick the label's outside direction
    fuzzy_ids = set()
    for g in fuzzy_groups:
        fuzzy_ids.update(g.get("node_ids", ()))
    link_color = st.link_color if st.link_color is not None else "black"
    link_lw = eff_link_width if eff_link_width is not None else 1
    label_kw = {} if st.link_label_color is None else {"color": st.link_label_color}

    def _draw_label(x, y, text, lk, endpoint, color=None):
        """Draw an edge-label text unless it is a true fuzzy-fan duplicate.

        ``endpoint`` is the node this slot belongs to: the parent for the
        left/site slot, the child for the right/anomeric slot. Suppression
        requires ALL of: same slot text, identical full edge label ``lk``,
        the SAME ``endpoint``, and slots within ``label_dedup_eps`` -- i.e.
        exactly the duplicated slot that fan edges converging at a shared
        residue carry (fan-out from one parent, or pending_fanout into one
        child). Labels belonging to different bonds never merge, however
        close they sit (anti-ghosting convention shared with the pptx
        backend)."""
        for dx_, dy_, tt, ll, ee in drawn_labels:
            if (
                tt == text
                and ll == lk
                and ee == endpoint
                and (dx_ - x) ** 2 + (dy_ - y) ** 2 < label_dedup_eps**2
            ):
                return
        drawn_labels.append((x, y, text, lk, endpoint))
        kw = dict(label_kw)
        if color is not None:
            kw["color"] = color
        ax.text(
            x,
            y,
            text,
            fontsize=font_size - 1,
            rotation=0,
            rotation_mode="anchor",
            ha="center",
            va="center",
            zorder=4,
            **kw,
        )

    for e_idx, (p, c, lk) in enumerate(edges):
        x1, y1 = pos[p]
        x2, y2 = pos[c]

        # Highlight: edges internal to some motif occurrence keep the full
        # link color; every other edge dims (glycowork semantics)
        if plan is not None and e_idx not in plan.matched_edge_idx:
            edge_color = st.dim_link_color
            edge_label_color = st.dim_link_label_color
        else:
            edge_color = link_color
            edge_label_color = None

        ax.plot([x1, x2], [y1, y2], color=edge_color, lw=link_lw, zorder=1)

        if lk and show_linkage:
            left, right = parse_edge_label(lk)
            # Fan edge: direction the variant end deviates from the chain axis
            # -> label goes to the fan outside
            ny_hint = None
            if fuzzy_ids and (p in fuzzy_ids) != (c in fuzzy_ids):
                dy_off = (y1 - y2) if p in fuzzy_ids else (y2 - y1)
                ny_hint = 1.0 if dy_off > 0 else -1.0
            x_l, y_l, x_r, y_r = edge_label_slots(
                p,
                c,
                (x1, y1),
                (x2, y2),
                perp=mono_size * LABEL_PERP_RATIO,
                along_mode="sign",
                bounds=bounds,
                avoid_margin=0.2,
                ny_hint=ny_hint,
            )

            if left:
                _draw_label(x_l, y_l, left, lk, p, edge_label_color)
            if right:
                _draw_label(x_r, y_r, right, lk, c, edge_label_color)


def _draw_nodes(
    ax: "plt.Axes",
    pos: Positions,
    labels: LabelMap,
    *,
    mono_size: float,
    plan: Optional["HighlightPlan"],
    st: Style,
    node_edgecolor: str,
    eff_node_stroke: Optional[float],
) -> Set[str]:
    """Draw every residue symbol (verbatim extraction); return the used monos.

    Iterates ``pos`` in insertion order; the returned ``used_monos`` set
    feeds the legend with its historical iteration order. ``node_edgecolor``
    stays a caller-owned local (the end markers reuse it).
    """
    used_monos = set()
    for i, (x, y) in pos.items():
        if is_open_node(i):
            pass
        else:
            mono = labels[i]
            used_monos.add(mono)
            # Highlight: non-matched residues get the dimmed palette + dim
            # outline; geometry is untouched (glycowork semantics)
            if plan is not None and i not in plan.matched_nodes:
                comp, color_hex = st.resolve_dim(mono)
                edge_color = st.dim_node_stroke_color
            else:
                comp, color_hex = st.resolve(mono)
                edge_color = node_edgecolor
            # Compensate by bbox center: otherwise asymmetric shapes like
            # triangles have their apex flush with the edge line and look
            # off-center when mixed with circles
            draw_shape(
                ax,
                comp,
                x,
                y - shape_vcenter_offset(comp, mono_size),
                mono_size,
                color_hex,
                edgecolor=edge_color,
                linewidth=eff_node_stroke,
            )
    return used_monos


def draw_snfg(
    tree: Any,
    dx: float = 1,
    dy: float = 1,
    mono_size: float = 0.3,
    ratio: float = 1,
    font_size: float = 12,
    font_family: str = "sans-serif",
    save_svg: Optional[str] = None,
    add_legend: bool = True,
    compact_repeat: bool = True,
    *,
    style: Union[None, str, dict, Style] = None,
    node_stroke_width: Optional[float] = None,
    link_width: Optional[float] = None,
    show_linkage: bool = True,
    highlight_motif: Optional[str] = None,
    end: Optional[str] = None,
    show_unknown: bool = False,
) -> "Tuple[plt.Figure, plt.Axes]":
    """Render a parsed CSDB tree as an SNFG diagram (matplotlib backend).

    Args (keyword-only additions):
        style: None | preset name ('default'/'glycoworkbench') | dict | path
            to a JSON style file | csdb2snfg.snfg.style.Style instance.
            None keeps the historical built-in appearance byte-for-byte.
        node_stroke_width: node outline width in points; overrides the style
            value; None keeps style/backend default.
        link_width: edge line width in points; overrides the style value;
            None keeps style/backend default.
        show_linkage: when False, edge linkage labels (site + anomeric slots)
            are not drawn. XOR/OR mode labels and repeat-count subscripts are
            structural annotations and stay.
        highlight_motif: CSDB substructure string; matched elements keep the
            full palette, everything else is dimmed (glycowork-style). '?'
            wildcards supported; no match -> warning + normal render.
        end: reducing-end (right side) marker: 'freeEnd' (squiggle), 'redEnd'
            (squiggle + centered 'O') or any other non-empty string drawn as
            a text label (e.g. 'PA', '2AB'). None/'' draws nothing.
        show_unknown: when True, explicit '?' markers in the CSDB source
            (unknown linkage position '(1-?)' / unknown anomeric '?DGalp')
            are rendered as '?' in the corresponding edge-label slots.
            Default False keeps the historical blank slots byte-for-byte.
            The markers live in edge labels, so show_linkage=False hides them.
    """
    st = load_style(style)
    eff_node_stroke = node_stroke_width if node_stroke_width is not None else st.node_stroke_width
    eff_link_width = link_width if link_width is not None else st.link_width

    _, pos, edges, labels, repeat_groups, expanded = prepare_layout_ext(
        tree,
        dx=dx,
        dy=dy,
        ratio=ratio,
        compact_repeat=compact_repeat,
        unknown_marker="?" if show_unknown else None,
        # Layout's fuzzy clearance constants must use THIS backend's own
        # radius/bond ratio (mono_size over dx) so the bond-lengthening it
        # performs matches the drawn geometry; the 0.3 default reproduces the
        # historical constants at the default mono_size/dx.
        radius_ratio=mono_size / (dx if dx > 0 else -dx),
    )

    plan = None
    if highlight_motif:
        from csdb2snfg.snfg.highlight import compute_highlight

        plan = compute_highlight(expanded, edges, labels, highlight_motif)
    xs = [x for x, y in pos.values()]
    ys = [y for x, y in pos.values()]
    width = max(xs) - min(xs) + 2
    height = max(ys) - min(ys) + 2

    plt.rcParams["font.family"] = font_family
    # Adjust the figure size dynamically based on the node count
    node_count = len(pos)
    min_width = max(4, min(12, node_count * 1.5))
    min_height = max(3, min(6, node_count * 0.8))
    fig, ax = plt.subplots(
        figsize=(max(min_width, width * 1.2), max(min_height, height * 1.2)),
    )

    # Bracket padding parameter
    PAD = bracket_pad(mono_size)

    # Split fuzzy entries (mode) from repeat entries (count); label avoidance
    # applies only to repeat brackets -- variant linkage labels inside a fuzzy
    # box must stay inside the box
    repeat_plain, fuzzy_groups = split_groups(repeat_groups)

    # Build bracket bounds info (for label avoidance on bracket-crossing edges)
    # fuzzy_pairs mirror the drawn boxes (bond-midpoint extensions included)
    # so units wrapping a fuzzy block avoid labels at the real verticals
    bounds = bracket_bounds(
        repeat_plain,
        pad=PAD,
        positions=pos,
        size=mono_size,
        edges=edges,
        fuzzy_pairs=(
            fuzzy_box_geoms(fuzzy_groups, mono_size, positions=pos, edges=edges)
            if fuzzy_groups
            else []
        ),
        box_gap=mono_size * BRACKET_BOX_GAP_RATIO,
    )

    # ---------- Draw edges ----------
    _draw_edges_and_labels(
        ax,
        pos,
        edges,
        mono_size=mono_size,
        font_size=font_size,
        show_linkage=show_linkage,
        plan=plan,
        st=st,
        bounds=bounds,
        fuzzy_groups=fuzzy_groups,
        eff_link_width=eff_link_width,
    )

    # ---------- Draw nodes ----------
    node_edgecolor = st.node_stroke_color if st.node_stroke_color is not None else "black"
    used_monos = _draw_nodes(
        ax,
        pos,
        labels,
        mono_size=mono_size,
        plan=plan,
        st=st,
        node_edgecolor=node_edgecolor,
        eff_node_stroke=eff_node_stroke,
    )

    # ---------- Draw reducing-end markers (end= parameter) ----------
    if end:
        draw_end_markers(
            ax,
            end_marker_specs(pos, mono_size, end),
            stroke_color=node_edgecolor,
            stroke_width=eff_node_stroke,
            font_size=font_size,
        )

    # ---------- Draw fuzzy gray boxes and repeat brackets ----------
    # Decorations always dim while a highlight is active (glycowork renders
    # floating bits/repeat brackets as 'hide' whenever a motif is set)
    dimmed = plan is not None
    if fuzzy_groups:
        # Draw in reversed inner order: outer groups first, nested (inner)
        # fuzzy last -> inner box borders are not covered by outer box fills
        draw_fuzzy_boxes(
            ax,
            fuzzy_groups,
            mono_size,
            font_size,
            fill_color=st.dim_fuzzy_box_color if dimmed else st.fuzzy_box_color,
            line_color=st.dim_fuzzy_box_line_color if dimmed else st.fuzzy_box_line_color,
            line_width=st.fuzzy_box_line_width,
            mode_label_color=st.dim_link_label_color if dimmed else None,
            positions=pos,
            edges=edges,
        )
    if repeat_plain:
        draw_repeat_brackets(
            ax,
            repeat_plain,
            mono_size,
            font_size,
            color=st.dim_bracket_color if dimmed else st.bracket_color,
            line_width=st.bracket_width,
            count_color=st.dim_link_label_color if dimmed else None,
            positions=pos,
            fuzzy_groups=fuzzy_groups,
            edges=edges,
        )

    ax.set_aspect("equal")
    ax.axis("off")

    # ---- Draw legend (content-aware placement + symbols sized like the main figure) ----
    if add_legend and used_monos:
        fig.canvas.draw()  # resolve the aspect-equal shrink
        renderer = fig.canvas.get_renderer()
        s_main = main_scale_inches(fig, ax)
        cx0, cy0, cx1, cy1 = content_bbox_inches(fig, ax, renderer)
        legend_ax = add_snfg_legend(
            ax,
            used_monos,
            mono_size,
            font_size,
            main_scale=s_main,
            content_bottom_in=cy0,
            content_center_in=(cx0 + cx1) / 2,
            style=st,
            node_stroke_width=eff_node_stroke,
        )
        if legend_ax is not None:
            grow_figure_for_legend(fig, legend_ax)

    if save_svg:
        fig.savefig(save_svg, bbox_inches="tight")
        plt.close(fig)
        return None, None

    return fig, ax
