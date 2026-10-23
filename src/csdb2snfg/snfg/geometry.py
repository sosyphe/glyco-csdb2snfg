"""Backend-agnostic drawing geometry over layout_tree's abstract space.

numpy-only (via symbols.get_shape_coords); no matplotlib / python-pptx dependency.
Dependency chain: symbols <- layout <- geometry <- export.{image,pptx}.

Coordinate convention: shared functions are defined in the abstract layout
space (y-up) or any Cartesian space isomorphic to it; device quantities
(perp/margin/pad) are passed in the units of the caller's space.
"""

from collections import namedtuple
from math import inf
from typing import TYPE_CHECKING, Any, List, Optional, Tuple

from csdb2snfg.snfg.layout import OPEN_HEAD, OPEN_TAIL, NodeId, Positions, is_open_node
from csdb2snfg.snfg.symbols import get_shape_coords, glycan_color, glycan_dict

if TYPE_CHECKING:
    import numpy as np

DEFAULT_COMP = "FCircle"
DEFAULT_COLOR_NAME = "White"
DEFAULT_COLOR_HEX = "#FFFFFF"

# Visual constants unified across both backends
LABEL_PERP_RATIO = 0.55  # perpendicular offset of edge labels, relative to node size
BRACKET_CAP_RATIO = 0.4  # repeat-unit bracket cap length = BRACKET_CAP_RATIO * PAD
BRACKET_ADJACENT_OFFSET_RATIO = (
    0.8  # total gap between adjacent ][ bracket verticals, relative to size
)
BRACKET_MARKER_GAP_RATIO = 0.06  # gap between a ']' bar and its count marker, relative to size


def resolve_mono(mono: str) -> Tuple[str, str]:
    """mono -> (comp, color_hex); unified glycan_dict/glycan_color lookup with default fallback."""
    comp, color_name = glycan_dict.get(mono, (DEFAULT_COMP, DEFAULT_COLOR_NAME))
    return comp, glycan_color.get(color_name, DEFAULT_COLOR_HEX)


# ------------------------------
# Half-fill vertex index decision table
# ------------------------------
# Indexes in sel point at the vertices of get_shape_coords(comp, size=1.0)
# (y-up local coordinates).
# Vertex order: FSquare/CSquare = [bottom-left, bottom-right, top-right, top-left].
ALL = object()  # sentinel: whole outline filled with a single color

_FILL_POLY_TABLE = {
    "DDiamond": [("color", [3, 0, 1]), ("white", [3, 2, 1])],
    "DDiamondInv": [("white", [3, 0, 1]), ("color", [3, 2, 1])],
    "CSquare": [("color", [1, 2, 3]), ("white", [0, 1, 3])],
    "DTriangle": [("color", [0, 2, 1])],
}


def node_fill_polys(comp: str) -> Tuple["np.ndarray", "np.ndarray", List[Tuple[str, Any]]]:
    """-> (xs, ys, entries): unit local coordinates + fill polygon entry table.

    entries = [(role, sel)], role in {'color', 'white'}, sel = vertex index list
    or ALL. CSquare is always a diagonally split square (top-right colored +
    bottom-left white).
    Backends handle device mapping:
      image: XS = xs*size + x
      pptx : (int(x_emu + xs[i]*size_emu), int(y_emu - ys[i]*size_emu))
    """
    xs, ys = get_shape_coords(comp, size=1.0)
    if comp in _FILL_POLY_TABLE:
        entries = _FILL_POLY_TABLE[comp]
    else:
        entries = [("color", ALL)]
    return xs, ys, entries


def shape_vcenter_offset(comp: str, size: float) -> float:
    """Vertical offset of the shape bbox center relative to the drawing anchor.

    Symmetric shapes (circle/square/diamond, ...) give 0; asymmetric shapes such
    as triangles (y in [-0.5s, s]) and stars give non-zero values -- when mixed
    on the same row without compensation, shape bboxes align at their top edge
    ("top alignment") and look vertically off-center. Legend drawing compensates
    with y - offset.
    """
    _, ys = get_shape_coords(comp, size)
    return (ys.max() + ys.min()) / 2


# ------------------------------
# Repeat-unit bracket geometry
# ------------------------------
BracketGeom = namedtuple(
    "BracketGeom", ["left_x", "right_x", "y_center", "v_extent", "y_top", "y_bot", "cap", "pad"]
)


def bracket_pad(size: float) -> float:
    """Spacing between bracket and nodes: PAD = size * 1.65."""
    return size * 1.65


def bracket_geometry(
    x_min: float,
    y_min: float,
    x_max: float,
    y_max: float,
    size: float,
    *,
    pad: Optional[float] = None,
    nest_level: int = 0,
) -> BracketGeom:
    """Bracket geometry (expressions bit-identical to the original matplotlib implementation).

    y-up space: y_top > y_bot. When the pptx backend consumes this in EMU y-down
    space it takes top=geom.y_bot, bottom=geom.y_top (the smaller value is on top).

    ``nest_level`` (0 = flat, the historical default) grows the vertical extent
    by one ``pad`` per repeat group this bracket encloses, so an enclosing
    bracket reads taller than the ones inside it (see ``repeat_nest_levels``).
    """
    if pad is None:
        pad = bracket_pad(size)
    left_x = x_min - pad
    right_x = x_max + pad
    v_extent = max((y_max - y_min) / 2 + pad, size * 2) + nest_level * pad
    y_center = (y_min + y_max) / 2
    y_top = y_center + v_extent
    y_bot = y_center - v_extent
    cap = pad * BRACKET_CAP_RATIO
    return BracketGeom(left_x, right_x, y_center, v_extent, y_top, y_bot, cap, pad)


def repeat_nest_levels(repeat_groups: List[dict]) -> List[int]:
    """Bracket growth level per ``repeat_groups`` entry (0 = encloses nothing).

    Only count groups (entries carrying ``count``) nest; fuzzy entries
    (``mode``) get 0. A group's level is the number of other count groups its
    bbox ENCLOSES: x-span contained in its own (inclusive on both ends, strict
    on at least one) with an overlapping y-band — so an enclosing bracket
    grows taller than the brackets inside it and nested pairs read as
    concentric. Containment is x-driven, so the result is immune to the pptx
    backend's y-flip; triple nesting generalizes (level 2). Flat structures
    yield all zeros, keeping historical geometry.
    """
    counts = [g for g in repeat_groups if "count" in g and "bbox" in g]
    levels = []
    for g in repeat_groups:
        if "count" not in g or "bbox" not in g:
            levels.append(0)
            continue
        x0, y0, x1, y1 = g["bbox"]
        lvl = 0
        for o in counts:
            if o is g:
                continue
            ox0, oy0, ox1, oy1 = o["bbox"]
            if x0 <= ox0 and ox1 <= x1 and (x0 < ox0 or ox1 < x1) and oy0 <= y1 and y0 <= oy1:
                lvl += 1
        levels.append(lvl)
    return levels


def bracket_vertical_xs(rg: dict, edges, positions: Positions):
    """-> (x_entry, x_exit): midpoints of the bonds entering/leaving a repeat unit.

    The drawn bracket verticals sit EXACTLY on these midpoints: the two
    edge-label chars of a horizontal bond (site digit / anomeric config, at
    residue centre +/- 0.4*bond) then straddle the vertical one per side, and
    the vertical never cuts a residue circle (half a bond clears radius +
    clearance at every default bond length). Entry bond = row bond between the
    unit's first backbone residue and its left neighbour (OPEN_HEAD stub
    included); exit bond likewise to the right neighbour. Only row-parallel
    crossing bonds qualify (branch/fan bonds leave the row in y). None on a
    side with no such bond (nested/degenerate units) -- callers fall back to
    the historical bbox +/- pad placement for that side.
    """
    ids = rg.get("backbone_ids") or rg.get("node_ids", [])
    xs = [positions[i][0] for i in ids if i in positions]
    if not xs:
        return (None, None)
    row_y = next(positions[i][1] for i in ids if i in positions)
    members = set(rg.get("node_ids", []))
    x_first, x_last = min(xs), max(xs)
    entry = None
    exit_ = None
    for e in edges:
        a, b = e[0], e[1]
        if (a in members) == (b in members):
            continue
        if a not in positions or b not in positions:
            continue
        (xa, ya), (xb, yb) = positions[a], positions[b]
        if ya != row_y or yb != row_y:
            continue  # branch / fan bond leaving the row
        mid = (xa + xb) / 2
        if mid < x_first and (entry is None or mid > entry):
            entry = mid
        elif mid > x_last and (exit_ is None or mid < exit_):
            exit_ = mid
    return (entry, exit_)


def adjacent_bracket_vertical_xs(
    repeat_groups: List[dict],
    edges,
    positions: Positions,
    size: float,
) -> List[Tuple[Optional[float], Optional[float]]]:
    """-> [(entry_x, exit_x), ...] aligned with ``repeat_groups``.

    When repeat units on the same row share a bracket side (``][``, ``[[`` or
    ``]]``) their vertical lines would coincide.  This helper nudges the
    coincident verticals apart just enough to keep each side readable, while
    keeping the connecting-bond labels inside their own half-bracket.  Each
    nudged vertical is clamped back into its circle-free corridor via
    ``bracket_clamp_limits``.

    Non-adjacent groups, groups on different rows, and isolated repeats keep
    the original ``bracket_vertical_xs`` values, so the default render path
    stays byte-identical for those cases.
    """
    raw = [bracket_vertical_xs(rg, edges, positions) for rg in repeat_groups]
    if len(repeat_groups) < 2 or edges is None:
        return raw

    def _row_y(rg: dict) -> Optional[float]:
        ids = rg.get("backbone_ids") or rg.get("node_ids", [])
        for nid in ids:
            if nid in positions:
                return positions[nid][1]
        return None

    def _min_x(rg: dict) -> float:
        xs = [positions[nid][0] for nid in rg.get("node_ids", []) if nid in positions]
        return min(xs) if xs else float("inf")

    indexed = sorted(enumerate(repeat_groups), key=lambda iv: (_min_x(iv[1]), iv[0]))
    limits = [bracket_clamp_limits(rg, positions, size) for rg in repeat_groups]
    levels = repeat_nest_levels(repeat_groups)
    result = list(raw)
    eps = size * 0.01
    # Edge labels on a normal (close) bond sit at 0.4 and 0.6 of the bond, i.e.
    # 0.1*bond_len away from the midpoint.  Nudge the bracket verticals only
    # enough to keep each label inside its own half-bracket with a small margin.
    label_offset_ratio = 0.5 - 0.4  # = 0.1
    label_margin_ratio = 0.08
    max_half_gap = size * BRACKET_ADJACENT_OFFSET_RATIO / 2.0

    def _clamp_entry(x: float, lim: Optional[Tuple[float, float, float, float]]) -> float:
        if lim is None:
            return x
        lo_l, hi_l, _lo_r, _hi_r = lim
        return float(min(max(x, lo_l), hi_l))

    def _clamp_exit(x: float, lim: Optional[Tuple[float, float, float, float]]) -> float:
        if lim is None:
            return x
        _lo_l, _hi_l, lo_r, hi_r = lim
        return float(min(max(x, lo_r), hi_r))

    def _half_gap(bond_len: float) -> float:
        return min(
            max_half_gap,
            max(size * 0.02, bond_len * (label_offset_ratio - label_margin_ratio)),
        )

    def _bond_len_between(members_a: set, members_b: set, mid: float, row_y: float) -> Optional[float]:
        for e in edges:
            a, b = e[0], e[1]
            if not ((a in members_a and b in members_b) or (a in members_b and b in members_a)):
                continue
            if a not in positions or b not in positions:
                continue
            (xa, ya), (xb, yb) = positions[a], positions[b]
            if ya != row_y or yb != row_y:
                continue
            if abs((xa + xb) / 2 - mid) <= eps:
                return abs(xa - xb)
        return None

    def _bond_len_at_side(members: set, mid: float, row_y: float) -> Optional[float]:
        for e in edges:
            a, b = e[0], e[1]
            if (a in members) == (b in members):
                continue
            if a not in positions or b not in positions:
                continue
            (xa, ya), (xb, yb) = positions[a], positions[b]
            if ya != row_y or yb != row_y:
                continue
            if abs((xa + xb) / 2 - mid) <= eps:
                return abs(xa - xb)
        return None

    def _outer_index(ia: int, ib: int) -> int:
        if levels[ia] != levels[ib]:
            return ia if levels[ia] > levels[ib] else ib
        ax0, _ay0, ax1, _ay1 = repeat_groups[ia]["bbox"]
        bx0, _by0, bx1, _by1 = repeat_groups[ib]["bbox"]
        return ia if (ax1 - ax0) >= (bx1 - bx0) else ib

    for k in range(len(indexed) - 1):
        i_a, rg_a = indexed[k]
        i_b, rg_b = indexed[k + 1]
        row_a = _row_y(rg_a)
        row_b = _row_y(rg_b)
        if row_a is None or row_b is None or row_a != row_b:
            continue
        ent_a, ex_a = raw[i_a]
        ent_b, ex_b = raw[i_b]

        # Detect the three "coincident side" patterns.
        if ent_a is not None and ent_b is not None and abs(ent_a - ent_b) <= eps:
            pattern = "[["
            mid = ent_a
        elif ex_a is not None and ex_b is not None and abs(ex_a - ex_b) <= eps:
            pattern = "]]"
            mid = ex_a
        elif ex_a is not None and ent_b is not None and abs(ex_a - ent_b) <= eps:
            pattern = "]["
            mid = ex_a
        else:
            continue

        members_a = set(rg_a.get("node_ids", []))
        members_b = set(rg_b.get("node_ids", []))
        if pattern == "][":
            bond_len = _bond_len_between(members_a, members_b, mid, row_a) or size * 2
            hg = _half_gap(bond_len)
            ex_a_new = _clamp_exit(mid - hg, limits[i_a])
            en_b_new = _clamp_entry(mid + hg, limits[i_b])
            result[i_a] = (result[i_a][0], ex_a_new)
            result[i_b] = (en_b_new, result[i_b][1])
        elif pattern == "[[":
            bond_len = _bond_len_at_side(members_a | members_b, mid, row_a) or size * 2
            hg = _half_gap(bond_len)
            i_outer = _outer_index(i_a, i_b)
            i_inner = i_b if i_outer == i_a else i_a
            en_outer = _clamp_entry(mid - hg, limits[i_outer])
            en_inner = _clamp_entry(mid + hg, limits[i_inner])
            result[i_outer] = (en_outer, result[i_outer][1])
            result[i_inner] = (en_inner, result[i_inner][1])
        elif pattern == "]]":
            bond_len = _bond_len_at_side(members_a | members_b, mid, row_a) or size * 2
            hg = _half_gap(bond_len)
            i_outer = _outer_index(i_a, i_b)
            i_inner = i_b if i_outer == i_a else i_a
            ex_inner = _clamp_exit(mid - hg, limits[i_inner])
            ex_outer = _clamp_exit(mid + hg, limits[i_outer])
            result[i_inner] = (result[i_inner][0], ex_inner)
            result[i_outer] = (result[i_outer][0], ex_outer)
    return result


def bracket_bounds(
    repeat_groups: List[dict],
    *,
    pad: float,
    cap: Optional[float] = None,
    positions: Optional[Positions] = None,
    size: Optional[float] = None,
    fuzzy_pairs=None,
    box_gap: Optional[float] = None,
    edges=None,
) -> List[dict]:
    """-> [{'left', 'right', 'node_ids'[, 'cap']}], for cross-bracket label avoidance.

    positions=None: use rg['bbox'] (legacy abstract-space path);
    positions given: recompute the x range from rg['node_ids'] in that space
    (legacy pptx EMU path), skip empty groups; write 'cap' into the entry when
    cap is not None. size: node radius in the same space, for the bracket
    circle-clearance clamp (defaults to pad / 1.65, the bracket_pad inverse).
    fuzzy_pairs (+ box_gap): fuzzy_box_geoms output; for a repeat unit that
    CONTAINS fuzzy boxes the drawn verticals sit just outside the boxes, so
    the avoidance bounds mirror that placement instead of bbox+pad.
    """
    out = []
    adjusted = None
    if positions is not None and edges is not None and size is not None:
        adjusted = adjacent_bracket_vertical_xs(repeat_groups, edges, positions, size)
    for rg_i, rg in enumerate(repeat_groups):
        if positions is None:
            bx_min, _by_min, bx_max, _by_max = rg["bbox"]
            left = bx_min - pad
            right = bx_max + pad
        else:
            group_ids = rg.get("node_ids", [])
            group_x = [positions[nid][0] for nid in group_ids if nid in positions]
            if not group_x:
                continue
            left = min(group_x) - pad
            right = max(group_x) + pad
            # Match the drawn brackets: keep verticals out of residue circles
            sz = size if size is not None else pad / 1.65
            limits = bracket_clamp_limits(rg, positions, sz)
            if limits:
                left, right = clamp_bracket_xs(left, right, limits)
            # The drawn verticals sit on the entry/exit bond midpoints; the
            # avoidance bounds must mirror exactly that placement.
            if edges is not None:
                mid_l, mid_r = (
                    adjusted[rg_i]
                    if adjusted is not None
                    else bracket_vertical_xs(rg, edges, positions)
                )
                if mid_l is not None:
                    left = mid_l
                if mid_r is not None:
                    right = mid_r
        if fuzzy_pairs and box_gap is not None:
            members = set(rg.get("node_ids", []))
            inner = [
                geom
                for geom, grp in fuzzy_pairs
                if set(grp.get("node_ids", ())) <= members and set(grp.get("node_ids", ()))
            ]
            if inner:
                # Mirror the drawn verticals: bond midpoints (the layout
                # lengthens the crossing bonds so the midpoints clear the
                # boxes); box-adjacent + circle-cleared only as fallback for
                # sides without a row crossing bond.
                mid_l, mid_r = (None, None)
                if edges is not None and positions is not None:
                    mid_l, mid_r = (
                        adjusted[rg_i]
                        if adjusted is not None
                        else bracket_vertical_xs(rg, edges, positions)
                    )
                if mid_l is None or mid_r is None:
                    box_l = min(b.x0 for b in inner) - box_gap
                    box_r = max(b.x1 for b in inner) + box_gap
                    if positions is not None and size is not None:
                        box_l, box_r = circle_clear_verticals(box_l, box_r, positions, size)
                    if mid_l is None:
                        left = box_l
                    if mid_r is None:
                        right = box_r
        entry = {
            "left": left,
            "right": right,
            "node_ids": set(rg.get("node_ids", [])),
        }
        if cap is not None:
            entry["cap"] = cap
        out.append(entry)
    return out


def bracket_clamp_limits(
    rg: dict,
    positions: Positions,
    size: float,
    *,
    gap: Optional[float] = None,
) -> Optional[Tuple[float, float, float, float]]:
    """-> (left_lo, left_hi, right_lo, right_hi) corridors for rg's verticals.

    A repeat unit's bbox x range can be pushed sideways by off-row nodes
    (horizontal fuzzy variants, testdata30), so after pad the bracket verticals
    would land on residue circles (the neighbour's, or the unit's own first).
    The verticals belong in the free corridors between circles: left between
    the previous residue's right edge and the unit's first residue's left edge,
    right between the unit's last residue's right edge and the next residue's
    left edge. Values already inside a corridor stay put, so repeats without
    off-row widening keep their historical geometry bit-for-bit.

    positions: node id -> (x, y) in the caller's space; the chain row is taken
    from the unit's backbone_ids (fallback node_ids). Neighbours are same-row
    nodes outside the group; OPEN_HEAD/OPEN_TAIL count as corridor ends too.
    gap: extra clearance beyond the circle edge; default 0.2 * size.
    None when the group has no positioned backbone node (nothing to clamp).
    """
    ids = rg.get("backbone_ids") or rg.get("node_ids", [])
    xs = [positions[i][0] for i in ids if i in positions]
    if not xs:
        return None
    row_y = next(positions[i][1] for i in ids if i in positions)
    members = set(rg.get("node_ids", []))
    outsiders = [x for i, (x, y) in positions.items() if i not in members and y == row_y]
    g = size * 0.2 if gap is None else gap
    x_first, x_last = min(xs), max(xs)
    lefts = [x for x in outsiders if x < x_first]
    rights = [x for x in outsiders if x > x_last]
    lo_l = -inf if not lefts else max(lefts) + size + g
    hi_r = inf if not rights else min(rights) - size - g
    return (lo_l, x_first - size - g, x_last + size + g, hi_r)


def clamp_bracket_xs(
    left_x: float,
    right_x: float,
    limits: Tuple[float, float, float, float],
) -> Tuple[float, float]:
    """Clamp bracket verticals into bracket_clamp_limits corridors."""
    lo_l, hi_l, lo_r, hi_r = limits
    return (min(max(left_x, lo_l), hi_l), max(min(right_x, hi_r), lo_r))


def bracket_y_under_fuzzy(
    geom: "BracketGeom", fuzzy_geoms, size: float, *, margin: float, row_y: Optional[float] = None
):
    """-> (y_top, y_bot) shortened so the caps miss fuzzy boxes in the columns.

    A fuzzy gray box hanging beside the chain row can reach into the bracket's
    vertical span (testdata30: the box bottom sits below the historical cap
    height). Where a box x-overlaps the bracket, pull the cap just outside the
    box edge; never closer to the chain row than size * 1.1 so the cap still
    clears the residue circles.

    row_y: y of the repeat unit's chain row in the caller's space (take it from
    the unit's backbone_ids; the pptx backend's flipped y-up space yields
    negative values). Defaults to geom.y_center. The circle-clearance floor is
    relative to that row -- an absolute +-size*1.1 clamp would assume the row
    sits at y=0 and teleport caps of off-main-chain or flipped-space brackets
    across the drawing. Caps only ever shrink: the result never exceeds
    geom.y_top / geom.y_bot.
    """
    if row_y is None:
        row_y = geom.y_center
    orig_top, orig_bot = geom.y_top, geom.y_bot
    y_top, y_bot = orig_top, orig_bot
    y_mid = (geom.y_top + geom.y_bot) / 2
    for fg in fuzzy_geoms:
        if fg.x1 < geom.left_x or fg.x0 > geom.right_x:
            continue
        if fg.y0 < y_top and fg.y1 >= y_mid:  # box above the chain row
            y_top = min(y_top, fg.y0 - margin)
        if fg.y1 > y_bot and fg.y0 <= y_mid:  # box below the chain row
            y_bot = max(y_bot, fg.y1 + margin)
    y_top = min(orig_top, max(y_top, row_y + size * 1.1))
    y_bot = max(orig_bot, min(y_bot, row_y - size * 1.1))
    return y_top, y_bot


BRACKET_BOX_GAP_RATIO = 0.35  # bracket verticals sit this many *size outside inner fuzzy boxes


def circle_clear_verticals(
    left_x: float, right_x: float, positions: Positions, size: float, *, gap_ratio: float = 0.25
):
    """Push bracket verticals out of any residue circle they would cut through.

    Box-hugging verticals (inner fuzzy units) can land on a circle when the
    gray box overlaps the unit's own backbone span (testdata30: the box's
    left edge sits over the first backbone residue). Push each vertical to
    the near side's circle edge + clearance; verticals already clear of every
    circle stay put (so box-hugging is preserved elsewhere).
    """
    g = size * gap_ratio
    for i, (x, _y) in positions.items():
        if is_open_node(i):
            continue
        if abs(left_x - x) < size + g:
            left_x = min(left_x, x - size - g)
        if abs(right_x - x) < size + g:
            right_x = max(right_x, x + size + g)
    return left_x, right_x


def fuzzy_boxes_inside_repeat(rg: dict, pairs: List[Tuple["FuzzyBoxGeom", dict]]):
    """-> (inner_geoms, outer_geoms) from fuzzy_box_geoms' (geom, group) pairs.

    A fuzzy group is INSIDE the repeat unit when all of its variant nodes are
    unit members (rg['node_ids'] covers them; the layout guarantees this for
    units like '/<<A|B>>/n=2/'). Inner boxes must be ENCLOSED by the bracket
    (their extent merges into the bracket bbox via bbox_union_boxes) -- cap
    shortening (bracket_y_under_fuzzy) only applies to OUTER boxes hanging
    beside the unit into the bracket columns (the testdata30 shape).
    """
    members = set(rg.get("node_ids", []))
    inner = []
    outer = []
    for geom, grp in pairs:
        ids = set(grp.get("node_ids", ()))
        if ids and ids <= members:
            inner.append(geom)
        else:
            outer.append(geom)
    return inner, outer


def bbox_union_boxes(
    bbox: Tuple[float, float, float, float], box_geoms
) -> Tuple[float, float, float, float]:
    """Union of a repeat-unit bbox (x_min, y_min, x_max, y_max) with the
    extents of fuzzy boxes that live inside the unit, so bracket_geometry's
    pad lands outside the gray boxes instead of cutting through them."""
    x_min, y_min, x_max, y_max = bbox
    for fg in box_geoms:
        x_min = min(x_min, fg.x0)
        x_max = max(x_max, fg.x1)
        y_min = min(y_min, fg.y0)
        y_max = max(y_max, fg.y1)
    return (x_min, y_min, x_max, y_max)


# ------------------------------
# Open edges and edge label slots
# ------------------------------
def open_edge_flags(parent_id: NodeId, child_id: NodeId) -> Tuple[bool, bool, bool]:
    """-> (is_open_tail, is_open_head, is_open_edge)."""
    is_open_tail = child_id == OPEN_TAIL or parent_id == OPEN_TAIL
    is_open_head = child_id == OPEN_HEAD or parent_id == OPEN_HEAD
    return is_open_tail, is_open_head, (is_open_tail or is_open_head)


def _slots_horizontal(
    x1: float,
    y1: float,
    x2: float,
    dx_line: float,
    *,
    is_open_edge: bool,
    along_mode: str,
    open_ratio: float,
    close_ratio: float,
    perp: float,
    y_up: bool,
) -> Tuple[float, float, float, float]:
    """Horizontal-edge branch of edge_label_slots (dy_line == 0).

    Verbatim extraction; the expressions are byte-load-bearing (both
    backends hash-compare against them) — never re-associate or simplify.
    """
    # Horizontal line: labels above (y_up) / above means decreasing y
    # (y-down), distributed along the X axis
    if along_mode == "sign":
        if is_open_edge:
            sx = open_ratio if dx_line > 0 else -open_ratio
            x_l = x2 - sx  # child node side
            x_r = x1 + sx  # parent node side
        else:
            sx = close_ratio if dx_line > 0 else (-close_ratio if dx_line < 0 else 0)
            x_l = x1 + sx  # parent node side
            x_r = x2 - sx  # child node side
    else:
        if is_open_edge:
            x_l = x2 - dx_line * open_ratio  # child node side
            x_r = x1 + dx_line * open_ratio  # parent node side
        else:
            x_l = x1 + dx_line / 2 - dx_line / 10
            x_r = x2 - dx_line / 2 + dx_line / 10
    if y_up:
        y_l = y1 + perp
        y_r = y1 + perp
    else:
        y_l = y1 - perp
        y_r = y1 - perp
    return x_l, y_l, x_r, y_r


def _slots_vertical(
    x2: float,
    y1: float,
    y2: float,
    dy_line: float,
    *,
    is_open_edge: bool,
    along_mode: str,
    open_ratio: float,
    close_ratio: float,
    perp: float,
) -> Tuple[float, float, float, float]:
    """Purely-vertical-edge branch of edge_label_slots (dx_line == 0).

    Verbatim extraction (legacy expressions, bit-for-bit unchanged) —
    never re-associate or simplify.
    """
    # Purely vertical line: labels on the right, distributed along the Y
    # axis (legacy expressions, bit-for-bit unchanged)
    x_l = x2 + perp
    x_r = x2 + perp
    if along_mode == "sign":
        if is_open_edge:
            sy = open_ratio if dy_line > 0 else -open_ratio
            y_l = y2 - sy  # child node side
            y_r = y1 + sy  # parent node side
        else:
            sy = close_ratio if dy_line > 0 else (-close_ratio if dy_line < 0 else 0)
            y_l = y1 + sy  # parent node side
            y_r = y2 - sy  # child node side
    else:
        if is_open_edge:
            y_l = y2 - dy_line / 2 - dy_line / 10  # child node side
            y_r = y1 + dy_line / 2 + dy_line / 10  # parent node side
        else:
            y_l = y1 + dy_line * close_ratio
            y_r = y2 - dy_line * close_ratio
    return x_l, y_l, x_r, y_r


def _slots_diagonal(
    x1: float,
    y1: float,
    dx_line: float,
    dy_line: float,
    *,
    is_open_edge: bool,
    along_mode: str,
    open_ratio: float,
    close_ratio: float,
    perp: float,
    ny_hint: Optional[float],
) -> Tuple[float, float, float, float]:
    """Diagonal-edge branch of edge_label_slots (fuzzy fan edges etc.).

    Slots are parameterized along their own segment P(t) and offset along
    the fan-outside normal. Verbatim extraction — the expressions are
    byte-load-bearing; never re-associate or simplify.
    """
    # Diagonal line (fuzzy fan edges, ...): slots parameterized along their
    # own segment + offset perpendicular to it.
    # P(t) = p1 + t*(p2-p1); normal n = (uy,-ux) normalized to nx >= 0
    # (uniform +x side: image y-up and EMU y-down land on the same visual
    # side, so no y_up branch is needed).
    # Each diagonal edge's labels sit on its own segment -> line<->label is
    # 1:1, fan edges de-duplicate naturally.
    # t order: left (site) near the parent end, right (configuration) near
    # the child end, same order for open/close (open uses open_ratio, see
    # the clamp note below).
    L = (dx_line * dx_line + dy_line * dy_line) ** 0.5
    ux, uy = dx_line / L, dy_line / L
    if abs(uy) > abs(ux):
        # Near-vertical diagonal (branch / fuzzy branch fan, mouth facing up
        # or down): take the fan outside -- text of a down-right line sits
        # upper-right of the line, a down-left line upper-left (mirrored the
        # same way for upward lines).
        # n = sign(ux*uy)*(uy,-ux); y-mirror-consistent with the
        # near-horizontal branch.
        s = 1.0 if ux * uy > 0 else -1.0
        nx, ny = s * uy, -s * ux
    elif ny_hint is not None:
        # Near-horizontal fuzzy fan edge: the backend reports, per fuzzy
        # group, the direction the variant end deviates from the chain axis
        # (ny_hint=sign(y_variant - y_neighbor_residue)) -> labels take the
        # fan outside (above an up-right line, below a down-right line).
        # Edges of the left/right fan mouths share direction but have
        # opposite outsides; undecidable without group info.
        nx, ny = uy, -ux
        if ny * ny_hint < 0:
            nx, ny = -nx, -ny
    else:
        # Near-horizontal diagonal (no group info fallback): uniform +x side
        nx, ny = uy, -ux
        if nx < 0:
            nx, ny = -nx, -ny
    a = open_ratio if is_open_edge else close_ratio
    if along_mode == "sign":
        # Absolute units -> fraction; short-edge clamp: close <=0.5 prevents
        # slot crossing, open <=0.4 keeps the slots at least 0.2*L apart
        # (legacy horizontal open edges at L=1 have |t_l-t_r|=0.2). 'frac'
        # proportions are naturally <=0.6, no clamp.
        a = min(a / L, 0.4 if is_open_edge else 0.5)
    # Diagonal open edges do not swap slot order (the legacy horizontal/
    # vertical open formulas under their own endpoint orientation are
    # already equivalent to chemical order): site (left) near the parent
    # end, configuration (right) near the child end -- for OPEN_HEAD edges
    # the parent end is the open point (the to-site belongs to the open
    # edge), for OPEN_TAIL edges the parent end is the residue (the ns site
    # sits on the residue).
    t_l, t_r = a, 1.0 - a
    x_l = x1 + t_l * dx_line + nx * perp
    y_l = y1 + t_l * dy_line + ny * perp
    x_r = x1 + t_r * dx_line + nx * perp
    y_r = y1 + t_r * dy_line + ny * perp
    return x_l, y_l, x_r, y_r


def edge_label_slots(
    parent_id: NodeId,
    child_id: NodeId,
    p1: Tuple[float, float],
    p2: Tuple[float, float],
    *,
    perp: float,
    y_up: bool = True,
    along_mode: str = "sign",
    open_ratio: float = 0.6,
    close_ratio: float = 0.4,
    bounds: tuple = (),
    avoid_margin: float = 0.0,
    avoid_floor: bool = False,
    ny_hint: Optional[float] = None,
) -> Tuple[float, float, float, float]:
    """Two label slots of one edge (x_l, y_l, x_r, y_r).

    left = linkage site (acceptor side, near parent), right = anomeric
    configuration (donor side, near child); p1 = parent end, p2 = child end, in
    any Cartesian space; perp = perpendicular distance (units of caller space).
    With y_up=False, horizontal-edge labels take y1-perp (EMU y-down convention).
    Edges fall into three classes:
      horizontal: labels above (y_up) / on the decreasing-y side (y-down),
        distributed along the X axis;
      purely vertical: labels on the right (x+perp), distributed along the Y
        axis (legacy expressions);
      diagonal (fuzzy fan edges, ...): both slots parameterized along their own
        segment P(t)=p1+t*(p2-p1), offset by perp along the normal; the normal
        side is the outside of the fan: near-horizontal lines uniformly take the
        +x side; near-vertical lines take sign(ux*uy)*(uy,-ux) (down-right line
        -> upper right, down-left line -> upper left) -> each line's labels
        follow their own segment, so fan edges sharing an endpoint no longer
        stack their labels.
    along_mode:
      'sign': along-line offset = +/-ratio absolute units (three-state, incl.
              dx==0 -> 0); the diagonal branch converts to a fraction
              a=min(ratio/L, 0.5) (short-edge clamp prevents crossing);
      'frac': along-line offset = ratio x edge vector component (affine
              invariant); regular horizontal / open vertical keep the legacy
              expressions dx/2-dx/10 etc. (sub-ulp difference vs ratio*dx, may
              differ by 1 EMU after int() truncation).
    Open-edge slot order: horizontal/vertical branches swap the two slots (left
    near the child end, legacy convention); the diagonal branch keeps open/close
    in the same order (left near the parent end) -- parent/child orientation is
    the chemical orientation (OPEN_HEAD parent end = open point, OPEN_TAIL
    parent end = residue).
    'frac' open-edge ratio=0.6>0.5 is by existing design; the diagonal branch
    does not clamp it.
    ny_hint: for near-horizontal fuzzy fan edges the backend passes the
    direction in which the variant end deviates from the chain axis
    (sign(y_variant - y_neighbor_residue), caller space, +/-1) to select the
    fan-outside normal; when None, near-horizontal diagonals fall back to the
    +x side. Near-vertical lines do not need it (the sign(ux*uy) rule is
    self-sufficient).
    bounds+avoid_margin: OPEN_TAIL cross-bracket push-out (push x_l when the
    parent is inside and the child outside); with avoid_floor=True the pushed
    result takes int() (legacy pptx behavior).
    """
    x1, y1 = p1
    x2, y2 = p2
    dx_line = x2 - x1
    dy_line = y2 - y1
    _t, _h, is_open_edge = open_edge_flags(parent_id, child_id)
    is_open_tail = _t

    # Orientation dispatch; each branch is a verbatim extraction (see the
    # _slots_* helpers — expressions are byte-load-bearing).
    if dy_line == 0:
        x_l, y_l, x_r, y_r = _slots_horizontal(
            x1,
            y1,
            x2,
            dx_line,
            is_open_edge=is_open_edge,
            along_mode=along_mode,
            open_ratio=open_ratio,
            close_ratio=close_ratio,
            perp=perp,
            y_up=y_up,
        )
    elif dx_line == 0:
        x_l, y_l, x_r, y_r = _slots_vertical(
            x2,
            y1,
            y2,
            dy_line,
            is_open_edge=is_open_edge,
            along_mode=along_mode,
            open_ratio=open_ratio,
            close_ratio=close_ratio,
            perp=perp,
        )
    else:
        x_l, y_l, x_r, y_r = _slots_diagonal(
            x1,
            y1,
            dx_line,
            dy_line,
            is_open_edge=is_open_edge,
            along_mode=along_mode,
            open_ratio=open_ratio,
            close_ratio=close_ratio,
            perp=perp,
            ny_hint=ny_hint,
        )

    # Label avoidance for bracket-crossing edges: only OPEN_TAIL open edges need
    # push-out -- the natural position of the left open edge's linkage-site digit
    # falls inside the bracket and must be pushed to the open end outside it.
    # Real-real bracket-crossing edges and OPEN_HEAD edges are already chemically
    # correct with default-side placement (site digit near the acceptor side,
    # anomeric configuration near the donor side, open end naturally outside the
    # bracket), so no pushing is done for them.
    if is_open_tail:
        for bb in bounds:
            p_in = parent_id in bb["node_ids"]
            c_in = child_id in bb["node_ids"]
            if p_in and not c_in:
                # EXIT: residue inside, open end outside -> push x_l out of the bracket
                if x2 < bb["left"]:
                    x_l = bb["left"] - avoid_margin
                elif x2 > bb["right"]:
                    x_l = bb["right"] + avoid_margin
                if avoid_floor:
                    x_l = int(x_l)

    return x_l, y_l, x_r, y_r


# ------------------------------
# Fuzzy gray-box geometry
# ------------------------------
FUZZY_PAD_X_RATIO = 1.1  # horizontal gap between box and variant nodes (was hardcoded per backend)
FUZZY_PAD_Y_RATIO = (
    1.7  # vertical gap between box and variant nodes; linkage labels must stay inside
)
FUZZY_BAND_RATIO = 0.55  # top title-band height = LABEL_PERP_RATIO*size.
# Edge label slots reach at most y_max + 0.55*size + half ink height
# (horizontal/open stubs sit at perp=0.55*size, diagonal normal
# component <= perp), so the title band constructively contains no
# edge label -> XOR/OR labels (anchored 0.2*size below the box top)
# never overlap any linkage annotation.
FUZZY_LABEL_INSET = 0.2  # XOR/OR anchor inset from the box top edge (same in both backends)

FuzzyBoxGeom = namedtuple("FuzzyBoxGeom", ["x0", "y0", "x1", "y1", "label_x", "label_y"])


def fuzzy_bond_midpoints(group: dict, edges, positions: Positions):
    """-> (x0_ext, x1_ext): horizontal bond midpoints beside a fuzzy group.

    The gray box swallows the inner half of every bond entering/leaving the
    block (and the linkage labels sitting on that half): the extension target
    is the midpoint between the variant node and its neighbour across the
    group boundary. Only midpoints OUTSIDE the variant x span widen the box
    (diagonal fan bonds whose midpoints stay over the block change nothing).
    None on a side with no crossing bond. Both spaces (layout abstract /
    flipped EMU) give the same relative geometry.
    """
    members = set(group.get("node_ids", ()))
    xs_in = [positions[i][0] for i in members if i in positions]
    if not xs_in or not edges:
        return (None, None)
    x_min, x_max = min(xs_in), max(xs_in)
    lo = None
    hi = None
    for e in edges:
        a, b = e[0], e[1]
        a_in, b_in = a in members, b in members
        if a_in == b_in or a not in positions or b not in positions:
            continue
        mid = (positions[a][0] + positions[b][0]) / 2
        if mid > x_max and (hi is None or mid > hi):
            hi = mid
        elif mid < x_min and (lo is None or mid < lo):
            lo = mid
    return (lo, hi)


def fuzzy_box_geometry(
    x_min: float,
    y_min: float,
    x_max: float,
    y_max: float,
    size: float,
    *,
    band: Optional[float] = None,
    extend_x: Optional[Tuple[Optional[float], Optional[float]]] = None,
    pad_y: Optional[float] = None,
) -> FuzzyBoxGeom:
    """Geometry of one fuzzy gray box (y-up space; the pptx backend flips y
    when consuming, like bracket_geometry).

    bbox = bounding box of variant node centers. Top pad = FUZZY_PAD_Y_RATIO*size
    + band (title band), the other three sides keep their pad. label = (box
    horizontal center, y1-inset), i.e. an anchor with ha='center'/va='top'
    semantics -- XOR/OR is fixed at the top-center inside the box, ink extends
    downward from the anchor into the title band, and the position does not move
    with label crowding.

    extend_x: optional (x0_ext, x1_ext) absolute bond-midpoint targets (see
    fuzzy_bond_midpoints); the box only ever WIDENS to swallow them.
    pad_y: override the vertical pad (both sides) in caller units. Backends
    whose label ink is large relative to their native node size (pptx: fixed
    pt font over a capped radius) pass the fan-label reach + half ink height so
    the box still swallows the variant linkage labels; None keeps
    FUZZY_PAD_Y_RATIO*size bit-for-bit.
    """
    if band is None:
        band = size * FUZZY_BAND_RATIO
    if pad_y is None:
        pad_y = size * FUZZY_PAD_Y_RATIO
    x0 = x_min - size * FUZZY_PAD_X_RATIO
    x1 = x_max + size * FUZZY_PAD_X_RATIO
    if extend_x is not None:
        if extend_x[0] is not None and extend_x[0] < x0:
            x0 = extend_x[0]
        if extend_x[1] is not None and extend_x[1] > x1:
            x1 = extend_x[1]
    y0 = y_min - pad_y
    y1 = y_max + pad_y + band
    return FuzzyBoxGeom(x0, y0, x1, y1, (x0 + x1) / 2, y1 - size * FUZZY_LABEL_INSET)


def fuzzy_box_geoms(
    fuzzy_groups: List[dict],
    size: float,
    *,
    positions: Optional[Positions] = None,
    band: Optional[float] = None,
    edges=None,
    pad_y: Optional[float] = None,
) -> List[Tuple[FuzzyBoxGeom, dict]]:
    """-> [(geom, group)] in draw order (reversed: outer box first, nested
    inner boxes last so their borders stay visible).

    fuzzy_groups: layout order (inner groups appended first when nested).
    positions=None: use g['bbox'] (image abstract space, y-up);
    positions given: recompute bbox from g['node_ids'] -- pptx EMU y-down path;
    the caller negates y first to flip into y-up before passing in, and flips
    back after getting the geom (top=-y1).
    edges (+ positions): widen each box to the bond midpoints crossing its
    boundary (fuzzy_bond_midpoints) so the box swallows the inner half of the
    entering/leaving bonds and their labels. Callers that draw or collide
    against boxes must pass the same edges/positions to stay consistent.
    Geometry is otherwise fully static: box and corner-label positions depend
    only on the bbox and size.
    """
    entries = []
    for g in fuzzy_groups:
        if positions is None:
            bbox = g["bbox"]
        else:
            pts = [positions[nid] for nid in g.get("node_ids", ()) if nid in positions]
            if not pts:
                continue
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            bbox = (min(xs), min(ys), max(xs), max(ys))
        extend_x = None
        if edges is not None and positions is not None:
            lo, hi = fuzzy_bond_midpoints(g, edges, positions)
            if lo is not None or hi is not None:
                extend_x = (lo, hi)
        entries.append(
            (fuzzy_box_geometry(*bbox, size, band=band, extend_x=extend_x, pad_y=pad_y), g)
        )

    return [(geom, g) for geom, g in reversed(entries)]


# ------------------------------
# Reducing-end marker geometry (end= parameter)
# ------------------------------
# Horizontal gap between the OPEN_HEAD stub tip and a text-kind marker's left
# anchor (squiggle-kind markers center ON the stub point instead, so the
# existing stub edge runs into the curve like a GlycoWorkbench center-to-center
# linkage line).
END_GAP_RATIO = 0.25

#: kind: 'squiggle' (freeEnd/redEnd) | 'text'; (cx, cy): marker center
#: (squiggle) or left/vertical-center anchor (text); rx/ry: squiggle box half
#: extents; text: 'O' for redEnd, the label string for text kind, None for
#: freeEnd; head_key: the OPEN_HEAD* position key the marker belongs to.
EndSpec = namedtuple("EndSpec", ["kind", "cx", "cy", "rx", "ry", "text", "head_key"])

#: Exact-match graphic end names (any other non-empty string is a text label)
GRAPHIC_ENDS = ("freeEnd", "redEnd")


def end_marker_specs(
    positions: Positions,
    size: float,
    end: Optional[str],
    *,
    gap_ratio: float = END_GAP_RATIO,
) -> List[EndSpec]:
    """-> [EndSpec] for the reducing (right) end of the drawing.

    Space-agnostic: works in the abstract y-up layout space (image) and in
    EMU y-down space (pptx) alike -- only end_squiggle_points needs to know
    the orientation. One marker per OPEN_HEAD* stub, so fuzzy-terminated
    chains get one marker per variant (OPEN_HEAD#k).

    end values: 'freeEnd' -> squiggle; 'redEnd' -> squiggle + centered 'O';
    any other non-empty string -> text label anchored right of the stub tip;
    None/'' -> no specs. Names match EXACTLY ('FreeEnd' renders as text).
    """
    if end is None or end == "":
        return []
    if not isinstance(end, str):
        raise TypeError(f"end must be a string or None, got {type(end).__name__}")
    squiggle = end in GRAPHIC_ENDS
    specs = []
    for key in positions:
        if not (isinstance(key, str) and key.startswith(OPEN_HEAD)):
            continue
        hx, hy = positions[key]
        if squiggle:
            specs.append(
                EndSpec("squiggle", hx, hy, size, size, "O" if end == "redEnd" else None, key)
            )
        else:
            specs.append(EndSpec("text", hx + gap_ratio * size, hy, size, size, end, key))
    return specs


def end_squiggle_points(spec: EndSpec, *, y_up: bool) -> Tuple[Tuple[float, float], ...]:
    """The four cubic Bezier points of the GlycoWorkbench 'end' shape.

    Faithful port of AbstractResidueRenderer.createEnd for the default RL
    orientation (angle=0): a subtle vertical S-curve from the box top-center
    to the box bottom-center with control points (cx-0.5rx, cy-0.5ry) and
    (cx+0.5rx, cy+0.5ry) (y-down, as in Java AWT / EMU). y_up=True mirrors
    every y about cy for the matplotlib space; the rendered shape is the same.
    """
    cx, cy, rx, ry = spec.cx, spec.cy, spec.rx, spec.ry
    if y_up:
        p0 = (cx, cy + ry)
        p1 = (cx - 0.5 * rx, cy + 0.5 * ry)
        p2 = (cx + 0.5 * rx, cy - 0.5 * ry)
        p3 = (cx, cy - ry)
    else:
        p0 = (cx, cy - ry)
        p1 = (cx - 0.5 * rx, cy - 0.5 * ry)
        p2 = (cx + 0.5 * rx, cy + 0.5 * ry)
        p3 = (cx, cy + ry)
    return p0, p1, p2, p3


def sample_cubic_bezier(
    p0: Tuple[float, float],
    p1: Tuple[float, float],
    p2: Tuple[float, float],
    p3: Tuple[float, float],
    n: int = 32,
) -> List[Tuple[float, float]]:
    """Deterministic uniform-t sampling of a cubic Bezier -> n+1 points.

    Endpoints are exact (t=0 and t=1 included). Used by the pptx backend,
    whose freeform builder only takes line segments; the image backend draws
    the exact curve via matplotlib Path CURVE4 instead.
    """
    pts = []
    for i in range(n + 1):
        t = i / n
        u = 1.0 - t
        x = u * u * u * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t * t * t * p3[0]
        y = u * u * u * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t * t * t * p3[1]
        pts.append((x, y))
    return pts
