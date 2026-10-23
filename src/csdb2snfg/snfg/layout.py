"""Repeat expansion and backend-agnostic tree layout for glycan ASTs.

Pure functions over the dict/list AST produced by csdb2snfg.csdb.parser;
no matplotlib/pptx dependency. Extracted verbatim from the former flat
renderer module.
"""

import copy
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from csdb2snfg.snfg.symbols import MODIFIERS

# Open-end node ids: layout_tree is the sole minter of these keys (the
# producer owns the protocol vocabulary)
OPEN_HEAD = "OPEN_HEAD"
OPEN_TAIL = "OPEN_TAIL"

# PEP 484 aliases for the layout output contract. Node identity is either the
# id() of a dict inside the expanded structure, or an OPEN_* string sentinel
# (per fuzzy variant: 'OPEN_HEAD#k' / 'OPEN_TAIL#k').
NodeId = Union[int, str]
Positions = Dict[NodeId, Tuple[float, float]]
EdgeList = List[Tuple[NodeId, NodeId, str]]
LabelMap = Dict[NodeId, str]


def is_open_node(node_id: NodeId) -> bool:
    """Decide whether a node id is an open-edge endpoint (not a real residue).

    Includes the per-variant fuzzy open-point sentinels 'OPEN_HEAD#k'/'OPEN_TAIL#k'
    (prefix match). Real residue ids are id(obj) integers; any string id is
    treated as an open point.
    """
    return isinstance(node_id, str) and node_id.startswith((OPEN_HEAD, OPEN_TAIL))


# ------------------------------
# Repeat expansion
# ------------------------------
def _expand_repeat_item(item: Any) -> List[Any]:
    """Expand one chain item of a repeat-bearing chain into output nodes.

    Numeric repeats expand to ``Count`` copies of their (recursively
    expanded) unit; repeats nested inside a unit or a branch expand
    recursively as well. Counts that are not parseable as int (e.g. ``'n'``
    or ``'?'``) expand the unit ONCE and wrap it in a ``RepeatGroup`` marker
    (the compact-mode shape), so renderers still draw the ``[unit]n``
    bracket instead of silently losing the repeat information.
    """
    if not (isinstance(item, dict) and "Repeat" in item):
        if isinstance(item, dict) and "Branch" in item:
            item = copy.deepcopy(item)
            item["Branch"] = expand_repeat(item["Branch"])
            return [item]
        # String node or plain dict
        return [item]

    repeat_data = item["Repeat"]
    unit = repeat_data.get("Unit", [])
    # If unit is a single dict or str, normalize it into a list
    if isinstance(unit, (dict, str)):
        unit = [unit]

    # Expand the unit once (recursing into nested Repeats/Branches)
    expanded_unit: List[Any] = []
    for u in unit:
        if isinstance(u, dict):
            expanded_unit.extend(_expand_repeat_item(copy.deepcopy(u)))
        else:
            # String nodes are appended as-is
            expanded_unit.append(u)

    try:
        count = int(repeat_data.get("Count", 1))
    except (ValueError, TypeError):
        # Symbolic count: keep one expanded copy inside a bracket marker
        return [
            {
                "RepeatGroup": {
                    "Unit": expanded_unit,
                    "Count": str(repeat_data.get("Count", "1")),
                }
            }
        ]

    # Expand the repeat unit count times (independent copies)
    out: List[Any] = []
    for _ in range(count):
        out.extend(copy.deepcopy(expanded_unit))
    return out


def expand_repeat(nodes: List[Any]) -> List[Any]:
    """Fully expand ``Repeat`` entries into ``Count`` copies of their unit.

    Operates on the dict/list form produced by ``Node.to_dict()``. Repeats
    nested inside branches or inside other repeats' units are expanded
    recursively, and branch/unit dicts are deep-copied so the caller's
    structure is never mutated. Counts that are not parseable as int
    (e.g. ``'?'``) keep a single unit copy wrapped in a ``RepeatGroup``
    marker (see ``_expand_repeat_item``).
    """
    new_nodes = []
    for item in nodes:
        new_nodes.extend(_expand_repeat_item(item))
    return new_nodes


# ------------------------------
# Compact repeat expansion
# ------------------------------
def expand_repeat_compact(nodes: List[Any]) -> List[Any]:
    """Compact mode: wrap repeats in RepeatGroup markers instead of expanding."""
    new_nodes = []
    for item in nodes:
        if isinstance(item, dict) and "Repeat" in item:
            repeat_data = item["Repeat"]
            unit = repeat_data.get("Unit", [])
            count = str(repeat_data.get("Count", "1"))
            if isinstance(unit, (dict, str)):
                unit = [unit]
            # Recurse into Repeats and Branches inside the unit
            expanded_unit = expand_repeat_compact(unit)
            new_nodes.append({"RepeatGroup": {"Unit": expanded_unit, "Count": count}})
        else:
            if isinstance(item, dict) and "Branch" in item:
                item = copy.deepcopy(item)
                item["Branch"] = expand_repeat_compact(item["Branch"])
                new_nodes.append(item)
            else:
                new_nodes.append(item)
    return new_nodes


def _unit_advance_steps(unit_nodes: List[Any]) -> int:
    """Chain-advance steps a laid-out RepeatGroup unit consumes.

    Mirrors the Case C advance loop: one step per row residue, recursing
    into nested ``RepeatGroup`` markers (a nested unit's own row residues
    advance the enclosing chain too). A unit with no row residues at all
    but a fuzzy block counts as one step, mirroring the pure-fuzzy
    fallback of the advance loop.
    """
    steps = 0
    for it in unit_nodes:
        if isinstance(it, dict):
            if "Residue" in it:
                steps += 1
            elif "RepeatGroup" in it:
                steps += _unit_advance_steps(it["RepeatGroup"].get("Unit", []))
    if steps == 0 and any(
        isinstance(it, dict) and (it.get("XOR") or it.get("OR")) for it in unit_nodes
    ):
        steps = 1
    return steps


def _first_unit_row_residue_id(unit_nodes: List[Any], positions: Positions) -> Optional[NodeId]:
    """Id of the leftmost row residue of a (possibly nested) unit.

    First ``Residue`` in unit list order, descending into nested
    ``RepeatGroup`` markers; ``None`` when the unit has no positioned row
    residue (pure fuzzy block). Used for the left-neighbour hand-off when a
    unit starts with a nested repeat.
    """
    for it in unit_nodes:
        if isinstance(it, dict):
            if "Residue" in it and id(it) in positions:
                return id(it)
            if "RepeatGroup" in it:
                found = _first_unit_row_residue_id(it["RepeatGroup"].get("Unit", []), positions)
                if found is not None:
                    return found
    return None


# ------------------------------
# Tree layout
# ------------------------------
def layout_tree(
    nodes: List[Any],
    dx: float = 1.5,
    dy: float = 1.5,
    depth: int = 0,
    x: float = 0,
    y: float = 0,
    ratio: float = 1,
    positions: Optional[Positions] = None,
    edges: Optional[EdgeList] = None,
    labels: Optional[LabelMap] = None,
    parent_id: Optional[NodeId] = None,
    repeat_groups: Optional[List[dict]] = None,
    _top_level: bool = True,
    _main_chain_ids: Optional[Set[NodeId]] = None,
    unknown_marker: Optional[str] = None,
    radius_ratio: float = 0.3,
) -> Tuple[None, Positions, EdgeList, LabelMap, List[dict]]:
    """Assign 2D coordinates to a dict/list glycan structure (pure layout).

    Walks ``nodes`` in REVERSE (CSDB lists the reducing end first, so the
    layout advances leftward from ``(x, y)``), handling residues, modifier
    groups, ``Branch`` containers, fuzzy OR/XOR blocks, and compact-mode
    ``RepeatGroup`` markers.

    Node identity: ``positions``/``labels`` are keyed by ``id()`` of the
    node dicts inside ``nodes``. Callers must keep that same (expanded)
    structure alive for any id-based lookup — see ``prepare_layout_ext``.
    Open-edge endpoints use the string sentinels ``OPEN_HEAD``/``OPEN_TAIL``
    (``OPEN_*#k`` per fuzzy variant); detect them with ``is_open_node``.

    The ``positions``/``edges``/``labels``/``repeat_groups`` containers are
    mutated in place when passed in (recursive calls share them) and
    created fresh when left ``None``.

    Args:
        nodes: dict/list structure from ``Node.to_dict()`` after repeat
            expansion (``expand_repeat`` or ``expand_repeat_compact``).
        dx, dy: signed per-step advance along the horizontal/vertical axis.
        depth: recursion depth; even depths lay out horizontally, odd
            depths vertically.
        x, y: coordinate of this level's first (rightmost) node.
        ratio: branch scaling factor applied per depth level.
        parent_id: node id the first edge of this level connects from.
        repeat_groups: accumulator for annotation dicts — fuzzy entries
            carry ``{'bbox','mode','node_ids','variant_ids'}``, compact
            repeats carry ``{'bbox','count','node_ids'}``.
        _top_level: internal — ``False`` inside branch/fuzzy/repeat-unit
            recursion; only the top-level call appends open edges.
        _main_chain_ids: internal — shared set of depth-0 residue ids, so
            open-edge endpoints are chosen on the main axis and deep
            branches cannot steal them.

    Returns:
        ``(None, positions, edges, labels, repeat_groups)`` — the first
        element is always ``None`` (historical placeholder). ``edges``
        entries are ``(from_id, to_id, label)`` with labels in the
        ``make_edge_label`` "site-configuration" protocol.
    """
    if positions is None:
        positions = {}
    if edges is None:
        edges = []
    if labels is None:
        labels = {}
    if repeat_groups is None:
        repeat_groups = []
    if _main_chain_ids is None:
        _main_chain_ids = set()

    current_x = x
    current_y = y
    branch_counter = 0
    last_node_id = parent_id
    first_node_id = None
    pending_fanout = (
        None  # multi-connection anchors on the upstream side of a fuzzy block (one per variant)
    )

    for item in reversed(nodes):
        # Case A: current item is a Residue node
        if "Residue" in item:
            node_id = id(item)
            labels[node_id] = item.get("Residue", "Unknown")
            # Establish the main-axis chain connection
            if labels[node_id] in MODIFIERS and last_node_id is not None:
                px, py = positions[last_node_id]
                if depth % 2 == 0:
                    positions[node_id] = (px - dx * 0.5, py)
                else:
                    positions[node_id] = (px, py - dy * 0.5)
                continue
            # ===== Case B: regular sugar Residue =====
            positions[node_id] = (current_x, current_y)
            if depth == 0:
                _main_chain_ids.add(node_id)
            if depth == 0 and first_node_id is None:
                first_node_id = node_id
            if last_node_id is not None:
                linkage = item.get("Linkage", "(?-?)")
                # Without unknown_marker, '?' (explicit unknown position)
                # renders like 'none': both slots blank (default path). With
                # a marker, '?' survives into the slots and gets drawn.
                unk = ("none", "?") if unknown_marker is None else ("none",)
                try:
                    ilink = linkage[1:-1].split("-")
                    if len(ilink) != 2 or ilink[0].lower() in unk or ilink[1].lower() in unk:
                        ilink = ["", ""]
                except Exception:
                    # Non-string or malformed linkage: fall back to empty slots
                    ilink = ["", ""]
                anomeric = item.get("Anomeric")
                if anomeric is None or anomeric.lower() == "none":
                    anomeric = ""
                if not anomeric and unknown_marker and item.get("AnomericUnknown"):
                    anomeric = unknown_marker
                # Labels are unified as "site-configuration":
                # the left slot (site, acceptor side) sits near the parent node,
                # the right slot (anomeric configuration, donor side) near the
                # child node. Slot geometry is consistent between horizontal
                # edges and vertical branch edges (left=parent side,
                # right=child side in both export backends), so both depths use
                # the same order.
                edge_label = make_edge_label(ilink[1], anomeric)
                if pending_fanout:
                    # Right neighbor is a fuzzy block: this residue's connection
                    # becomes one edge per variant
                    for fid in pending_fanout:
                        edges.append((fid, node_id, edge_label))
                    pending_fanout = None
                else:
                    edges.append((last_node_id, node_id, edge_label))
            # Advance the current chain's pointer and coordinates
            last_node_id = node_id
            if depth % 2 == 0:
                current_x -= dx
            else:
                current_y -= dy
        # Case B: current item is a branch container
        elif "Branch" in item and item["Branch"]:
            if last_node_id is None:
                # Degenerate input: a branch with no residue to attach to (e.g.
                # CSDB is just "[X]"). The old behavior silently skipped it ->
                # empty positions -> draw_snfg crashed; here we degrade to
                # laying it out as a top-level main chain so there is at least
                # something renderable.
                layout_tree(
                    item["Branch"],
                    dx,
                    dy,
                    depth,
                    current_x,
                    current_y,
                    ratio,
                    positions,
                    edges,
                    labels,
                    None,
                    repeat_groups,
                    _top_level=False,
                    _main_chain_ids=_main_chain_ids,
                    unknown_marker=unknown_marker,
                    radius_ratio=radius_ratio,
                )
            else:
                side_sign = -1 if branch_counter % 2 == 0 else 1
                rdx = side_sign * dx * (ratio ** (depth + 1))
                rdy = side_sign * dy * (ratio ** (depth + 1))
                if depth % 2 == 0:
                    bx, by = positions[last_node_id][0], positions[last_node_id][1] - rdy
                elif depth % 2 == 1:
                    bx, by = positions[last_node_id][0] - rdx, positions[last_node_id][1]
                # Recurse into the branch, passing the current last_node_id as parent_id
                layout_tree(
                    item["Branch"],
                    rdx,
                    rdy,
                    depth + 1,
                    bx,
                    by,
                    ratio,
                    positions,
                    edges,
                    labels,
                    last_node_id,
                    repeat_groups,
                    _top_level=False,
                    _main_chain_ids=_main_chain_ids,
                    unknown_marker=unknown_marker,
                    radius_ratio=radius_ratio,
                )
                branch_counter += 1

        # Case D: Fuzzy block (<<XOR>> / <OR> alternative variants, CSDB
        # structural ambiguity). Variants are arranged along the axis
        # perpendicular to the chain direction (horizontal chain -> vertical
        # stacking, variant 0 on the + side; shown as top/right in both
        # rendering backends). Rendering backends draw a gray bounding box +
        # OR/XOR label from the {'bbox','mode','node_ids'} entries recorded in
        # repeat_groups (style reference: tests/testdata/glycan.svg).
        elif isinstance(item, dict) and (item.get("XOR") or item.get("OR")):
            mode = "XOR" if item.get("XOR") else "OR"
            options = [o for o in item[mode] if o]
            if not options:
                continue
            horiz = depth % 2 == 0  # chain direction: horizontal at even depth
            adv = -dx if horiz else -dy  # per-step advance (signed)
            n = len(options)
            row_gap = (abs(dy) if horiz else abs(dx)) or 1.0
            ids_before = set(positions.keys())
            anchors = []

            def _extreme(ids, horiz=horiz, adv=adv, positions=positions):
                """Node id of the most downstream variant node (extreme
                along the chain advance direction)."""
                axis = 0 if horiz else 1
                return (
                    max(ids, key=lambda nid: positions[nid][axis])
                    if adv > 0
                    else min(ids, key=lambda nid: positions[nid][axis])
                )

            # Two-pass stacking: first measure each variant's thickness along
            # the chain-perpendicular axis (scratch layout, parent_id=None to
            # avoid the MODIFIER KeyError on last_node_id), then stack by actual
            # thickness + row_gap spacing, still centered on the chain axis.
            # Tall variants with branches no longer overlap their neighbors.
            # Point variants (thickness 0) degrade exactly to the old formula
            # ((n-1)/2-k)*row_gap. Cost: one extra measurement layout per fuzzy
            # level (real data nests at depth <= 2).
            axis = 1 if horiz else 0
            extents = []
            for opt in options:
                _, spos, _se, _sl, _sg = layout_tree(
                    opt,
                    dx,
                    dy,
                    depth,
                    0.0,
                    0.0,
                    ratio,
                    None,
                    None,
                    None,
                    None,
                    None,
                    _top_level=False,
                    _main_chain_ids=set(),
                    unknown_marker=unknown_marker,
                    radius_ratio=radius_ratio,
                )
                pts = [v[axis] for kk, v in spos.items() if not is_open_node(kk)]
                extents.append((min(pts), max(pts)) if pts else (0.0, 0.0))
            heights = [hi - lo for lo, hi in extents]
            total = sum(heights) + (n - 1) * row_gap
            offs = []
            prev_lo = None
            for k in range(n):
                if prev_lo is None:
                    off = total / 2.0 - extents[k][1]  # top variant's upper edge = +total/2
                else:
                    off = prev_lo - row_gap - extents[k][1]
                offs.append(off)
                prev_lo = extents[k][0] + off

            variant_ids = []
            for k, opt in enumerate(options):
                off = offs[k]
                if horiz:
                    vx, vy = current_x, current_y + off
                else:
                    vx, vy = current_x + off, current_y
                ids_k = set(positions.keys())
                layout_tree(
                    opt,
                    dx,
                    dy,
                    depth,
                    vx,
                    vy,
                    ratio,
                    positions,
                    edges,
                    labels,
                    last_node_id,
                    repeat_groups,
                    _top_level=False,
                    _main_chain_ids=_main_chain_ids,
                    unknown_marker=unknown_marker,
                    radius_ratio=radius_ratio,
                )
                new_k = [i for i in positions if i not in ids_k and not is_open_node(i)]
                variant_ids.append(new_k)
                if new_k:
                    # Most-downstream anchor of this variant; if the variant
                    # itself ends in a nested fuzzy block the most-downstream
                    # set is a row of tied nodes -> all of them become fan-out
                    # anchors (the left neighbor forms one edge per nested variant)
                    ext_id = _extreme(new_k)
                    ax0 = 0 if horiz else 1
                    ext_v = positions[ext_id][ax0]
                    anchors.extend(i for i in new_k if positions[i][ax0] == ext_v)

            new_ids = [i for i in positions if i not in ids_before and not is_open_node(i)]
            if new_ids:
                xs = [positions[i][0] for i in new_ids]
                ys = [positions[i][1] for i in new_ids]
                repeat_groups.append(
                    {
                        "bbox": (min(xs), min(ys), max(xs), max(ys)),
                        # discriminator key: fuzzy entries carry mode,
                        # repeats carry count
                        "mode": mode,
                        "node_ids": new_ids,
                        # per-variant node ids (order = option order): used
                        # for per-variant open-edge fan-out
                        "variant_ids": variant_ids,
                    }
                )
            if anchors:
                pending_fanout = anchors  # the upstream neighbor residue forms one edge per variant
                last_node_id = anchors[0]
                ext = positions[_extreme(new_ids)][0 if horiz else 1]
                if horiz:
                    current_x = ext + adv
                else:
                    current_y = ext + adv

        # Case C: current item is a RepeatGroup (compact-mode repeat unit)
        elif "RepeatGroup" in item:
            rg = item["RepeatGroup"]
            unit_nodes = rg.get("Unit", [])

            # Record the position set before layout, used to compute the bounding box
            ids_before = set(positions.keys())
            n_groups_before = len(repeat_groups)

            # Recursively lay out the nodes inside the unit (same level as the main chain)
            layout_tree(
                unit_nodes,
                dx,
                dy,
                depth,
                current_x,
                current_y,
                ratio,
                positions,
                edges,
                labels,
                last_node_id,
                repeat_groups,
                _top_level=False,
                _main_chain_ids=_main_chain_ids,
                unknown_marker=unknown_marker,
                radius_ratio=radius_ratio,
            )

            # Find all newly added node positions inside the unit (excluding OPEN_HEAD/OPEN_TAIL)
            new_ids = [k for k in positions.keys() if k not in ids_before and not is_open_node(k)]

            extra_shift = 0.0
            if new_ids:
                # Fuzzy variant nodes laid out inside the unit stay out of the
                # bracket box: their gray box is wider than the unit row, and
                # including it pushed the bracket verticals onto neighbour
                # residues / variant symbols (testdata30). The inner fuzzy
                # groups appended by the recursive call above carry their ids;
                # the box floats free above the bracket instead. Plain
                # branches stay enclosed, backbone x span keeps the verticals
                # in the circle-free corridor beside the unit.
                fuzzy_ids = set()
                for g in repeat_groups[n_groups_before:]:
                    if "mode" in g:
                        fuzzy_ids.update(g["node_ids"])
                # The drawn bracket verticals sit EXACTLY on the midpoints of
                # the bonds entering/leaving the unit (draw-time rule,
                # geometry.bracket_vertical_xs), so each bond's two label chars
                # straddle its vertical. When the unit wraps a fuzzy block the
                # gray box must stay ENCLOSED by the bracket: if a box edge
                # reaches past the crossing bond's midpoint, LENGTHEN that bond
                # (shift the unit -- and, for the entering bond, everything
                # after it -- left by extra_shift) until the lengthened bond's
                # midpoint clears the box edge; the circle term likewise keeps
                # half the lengthened bond clear of radius + clearance.
                # Canonical layout-unit constants mirror the draw-time
                # geometry in THIS backend's units: radius = radius_ratio*|dx|
                # (image mono_size/dx; pptx effective capped radius over its
                # dx), box pad = FUZZY_PAD_X_RATIO*r, K = box gap + radius +
                # circle clearance.
                if fuzzy_ids and depth % 2 == 0:
                    # Backend-self-aware canonical constants: radius in this
                    # layout's own units (radius_ratio = radius/bond, bond =
                    # |dx|); image defaults reproduce the historical 0.3.
                    _r = radius_ratio * (dx if dx > 0 else -dx)
                    _k = _r * (0.35 + 1.0 + 0.25)
                    fxs = [positions[k][0] for k in fuzzy_ids if k in positions]
                    if fxs:
                        pad_x0 = min(fxs) - 1.1 * _r
                        pad_x1 = max(fxs) + 1.1 * _r
                        mid_x1 = None
                        mid_x0 = None
                        for e in edges:
                            a, b = e[0], e[1]
                            a_in, b_in = a in fuzzy_ids, b in fuzzy_ids
                            if a_in == b_in:
                                continue
                            out_id, in_id = (a, b) if b_in else (b, a)
                            if out_id not in positions or in_id not in positions:
                                continue
                            ox = positions[out_id][0]
                            mid = (ox + positions[in_id][0]) / 2
                            if ox > max(fxs) and (mid_x1 is None or mid > mid_x1):
                                mid_x1 = mid
                            elif ox < min(fxs) and (mid_x0 is None or mid < mid_x0):
                                mid_x0 = mid
                        members = set(new_ids)
                        anchor_x = max(positions[k][0] for k in new_ids if k in positions)
                        rights = [
                            x
                            for i, (x, _y) in positions.items()
                            if i not in members and x > anchor_x
                        ]
                        # Leaving bond (right): between the unit's last
                        # backbone residue and its row neighbour. Its midpoint
                        # must end up clear of the gray box's right edge
                        # (bracket enclosure) and half the bond clear of the
                        # neighbour circle (vertical circle-clearance).
                        bxs = [
                            positions[k][0]
                            for k in new_ids
                            if k in positions
                            and positions[k][1] == current_y
                            and k not in fuzzy_ids
                        ]
                        if rights and bxs:
                            x_ulast = max(bxs)
                            rights2 = [
                                x
                                for i, (x, _y) in positions.items()
                                if i not in members and _y == current_y and x > x_ulast
                            ]
                            if rights2:
                                a_right2 = min(rights2)
                                mid0_r = (x_ulast + a_right2) / 2
                                # midpoint ends up BRACKET_BOX_GAP_RATIO*_r
                                # clear of the box edge, so the drawn vertical
                                # keeps its gap while sitting on the midpoint
                                e_r3 = 2.0 * (pad_x1 + 0.35 * _r - mid0_r)
                                e_r4 = 2.5 * _r - (a_right2 - x_ulast)
                                rights = rights2
                                anchor_x = x_ulast
                                extra_shift = max(extra_shift, e_r3, e_r4)
                        if rights:
                            a_right = min(rights)
                            vx_r = max(fxs)
                            e_r1 = pad_x1 + _k - a_right
                            e_r2 = vx_r - a_right + 2 * _k
                            extra_shift = max(0.0, e_r1, e_r2, extra_shift)
                            if extra_shift > 0:
                                for k in new_ids:
                                    px, py = positions[k]
                                    positions[k] = (px - extra_shift, py)
                                for g in repeat_groups[n_groups_before:]:
                                    bx0, by0, bx1, by1 = g["bbox"]
                                    g["bbox"] = (bx0 - extra_shift, by0, bx1 - extra_shift, by1)
                        # leaving bond (left): downstream residues only.
                        # Three possible left box edges (pad, inner fan-bond
                        # midpoint, future left-neighbour bond midpoint) each
                        # give a clearance bound on the downstream advance.
                        b0 = min(positions[k][0] for k in new_ids if k in positions)
                        vx_l = min(fxs) - extra_shift
                        e_l1 = b0 - dx + _k - pad_x0 + extra_shift
                        e_l2 = b0 - dx + _k - mid_x0 + extra_shift if mid_x0 is not None else 0.0
                        e_l3 = b0 - dx + 2 * _k - vx_l
                        # Entering bond (left): its midpoint (unit first
                        # residue vs the left neighbour, placed later at
                        # current_x) must end up clear of the gray box's left
                        # edge, and the bond itself at least 2.5*_r long so the
                        # midpoint vertical clears both circles.
                        e_l4 = 2.0 * (b0 - dx / 2 - (pad_x0 - extra_shift) + 0.35 * _r)
                        e_l5 = 2.5 * _r - dx
                        extra_shift += max(0.0, e_l1, e_l2, e_l3, e_l4, e_l5)
                backbone_ids = [
                    k for k in new_ids if positions[k][1] == current_y and k not in fuzzy_ids
                ]
                box_ids = [k for k in new_ids if k not in fuzzy_ids]
                # Degenerate unit (pure fuzzy block, no backbone residue):
                # fall back to the variant nodes so the bbox stays defined
                rg_xs = [positions[k][0] for k in backbone_ids or box_ids or new_ids]
                rg_ys = [positions[k][1] for k in box_ids or new_ids]
                repeat_groups.append(
                    {
                        "bbox": (min(rg_xs), min(rg_ys), max(rg_xs), max(rg_ys)),
                        "count": rg["Count"],
                        "node_ids": list(new_ids),
                        "backbone_ids": backbone_ids,
                    }
                )

            # Advance the pointer: the first forward Residue in the unit is the
            # leftmost residue. During the reverse traversal, what follows a
            # RepeatGroup is its left neighbor, which must connect to the unit's
            # leftmost residue (not the rightmost one).
            # Coordinate advance still happens once per unit residue.
            first_unit_res_id = None
            for rg_item in unit_nodes:
                if isinstance(rg_item, dict) and "Residue" in rg_item:
                    rg_item_id = id(rg_item)
                    if rg_item_id in positions:
                        if first_unit_res_id is None:
                            first_unit_res_id = rg_item_id
                        if depth % 2 == 0:
                            current_x -= dx
                        else:
                            current_y -= dy
                elif isinstance(rg_item, dict) and "RepeatGroup" in rg_item:
                    # Nested repeat marker (a repeat inside a repeat unit):
                    # its unit row advances the enclosing chain exactly like
                    # the nested Case C recursion did while laying it out,
                    # and its leftmost residue takes the left-neighbour
                    # hand-off when the unit starts with the nested repeat.
                    nested_unit = rg_item["RepeatGroup"].get("Unit", [])
                    for _ in range(_unit_advance_steps(nested_unit)):
                        if depth % 2 == 0:
                            current_x -= dx
                        else:
                            current_y -= dy
                    if first_unit_res_id is None:
                        first_unit_res_id = _first_unit_row_residue_id(nested_unit, positions)
            if first_unit_res_id is not None:
                last_node_id = first_unit_res_id
            elif new_ids:
                # Unit has no top-level residue (e.g. a pure fuzzy block
                # `/<<A|B>>/n=2/`): the residue-driven advance loop above never
                # runs -> advance the chain pointer by one step, and hand each
                # variant's most-downstream node to the left neighbor as fan-out
                # anchors (otherwise pending_fanout stays trapped inside the
                # unit recursion and gets lost, and the left neighbor would
                # wrongly connect to the residue before the unit).
                ax0 = 0 if depth % 2 == 0 else 1
                xmax = max(positions[i][ax0] for i in new_ids)
                anchors_u = [i for i in new_ids if positions[i][ax0] == xmax]
                pending_fanout = anchors_u
                last_node_id = anchors_u[0]
                if depth % 2 == 0:
                    current_x -= dx
                else:
                    current_y -= dy
            if extra_shift and depth % 2 == 0:
                # lengthened entering bond: downstream residues continue from
                # the shifted unit position
                current_x -= extra_shift

    # --- Add open edges (top-level calls only) ---
    if depth == 0 and _top_level:
        _add_open_edges(nodes, positions, edges, repeat_groups, _main_chain_ids, dx, unknown_marker)

    return None, positions, edges, labels, repeat_groups


# ------------------------------
# Open-edge epilogue helpers (top-level layout_tree only)
# ------------------------------
def _find_node(target_id: int, obj: Any) -> Optional[dict]:
    """Recursively search for a node dict (walks dicts and lists)."""
    if isinstance(obj, dict):
        if id(obj) == target_id:
            return obj
        for v in obj.values():
            r = _find_node(target_id, v)
            if r:
                return r
    elif isinstance(obj, list):
        for item in obj:
            r = _find_node(target_id, item)
            if r:
                return r
    return None


def _head_label_parts(
    node: Optional[dict], unknown_marker: Optional[str] = None
) -> Tuple[str, str]:
    """(to-site, anomeric configuration) of the rightmost residue
    -> the two open-edge label parts. With unknown_marker, an explicit '?'
    position / unknown anomeric is shown as the marker instead of blank."""
    r_anomeric = ""
    r_to = ""
    if node:
        a = node.get("Anomeric")
        if a and str(a).lower() != "none":
            r_anomeric = str(a)
        if not r_anomeric and unknown_marker and node.get("AnomericUnknown"):
            r_anomeric = unknown_marker
        linkage = node.get("Linkage")
        if linkage:
            try:
                parts = str(linkage).strip("()").split("-")
                unk = ("none", "?") if unknown_marker is None else ("none",)
                if len(parts) == 2 and parts[1].lower() not in unk:
                    r_to = parts[1]
            except Exception:
                r_to = ""
    return r_to, r_anomeric


def _ns_of(node: Optional[dict]) -> str:
    """Non-stoichiometric prefix of a node dict as a string ('' when absent)."""
    if node:
        ns = node.get("NonStoichiometric")
        if ns is not None and str(ns).lower() != "none":
            return str(ns)
    return ""


def _add_open_edges(
    nodes: List[Any],
    positions: Positions,
    edges: EdgeList,
    repeat_groups: List[dict],
    main_chain_ids: Set[NodeId],
    dx: float,
    unknown_marker: Optional[str] = None,
) -> None:
    """Attach OPEN_HEAD/OPEN_TAIL stub edges to a finished top-level layout.

    Verbatim extraction of layout_tree's epilogue; the depth==0/_top_level
    guard stays at the call site. Mutates ``positions``/``edges`` in place:
    open-point sentinels get coordinates one ``dx`` step outside the
    chain endpoints, and one labelled stub edge is appended per endpoint
    (per fuzzy variant when a fuzzy block terminates the chain).

    When a fuzzy block terminates the chain (chain endpoint lands
    inside some variant): each variant carries its own horizontal
    open stub (as if each were its own main chain), with open-point
    sentinels OPEN_HEAD#k / OPEN_TAIL#k (is_open_node prefix match).
    Non-fuzzy termination takes the legacy single-stub path.
    """
    # Find the actual rightmost and leftmost nodes (by x coordinate),
    # selecting only among main-axis (depth==0) residues so that deep
    # branches (horizontal layout at depth>=2) cannot steal the endpoints.
    real_ids = [k for k in positions if not is_open_node(k)]
    if real_ids:
        _chain = [k for k in real_ids if k in main_chain_ids]
        _anchor = _chain if _chain else real_ids
        right_id = max(_anchor, key=lambda k: positions[k][0])
        left_id = min(_anchor, key=lambda k: positions[k][0])
        rx, ry = positions[right_id]
        lx, ly = positions[left_id]

        variant_owner = {}
        for g in repeat_groups:
            if "mode" not in g:
                continue
            for vlist in g.get("variant_ids", []):
                for v in vlist:
                    variant_owner[v] = g

        # OPEN_HEAD: right-side open edge
        # Label convention: the left slot (linkage site) is drawn at the
        # open end (outside the bracket), the right slot (anomeric
        # configuration) at the residue end.
        # The rightmost node's Linkage "(1-6)" describes its connection
        # toward the right open end; the to-site (e.g. 6) belongs to the
        # open edge and must not be dropped.
        head_id = OPEN_HEAD
        g_r = variant_owner.get(right_id)
        if g_r is not None:
            for k, vlist in enumerate(g_r.get("variant_ids", [])):
                if not vlist:
                    continue
                r_id = max(vlist, key=lambda i: positions[i][0])
                sx, sy = positions[r_id]
                sid = f"{OPEN_HEAD}#{k}"
                positions[sid] = (sx + dx, sy)
                r_to, r_anomeric = _head_label_parts(_find_node(r_id, nodes), unknown_marker)
                if r_to:
                    edges.append((sid, r_id, f"{r_to}-{r_anomeric}"))
                else:
                    edges.append((sid, r_id, f"{r_anomeric}-"))
        else:
            positions[head_id] = (rx + dx, ry)
            r_to, r_anomeric = _head_label_parts(_find_node(right_id, nodes), unknown_marker)
            if r_to:
                edges.append((head_id, right_id, f"{r_to}-{r_anomeric}"))
            else:
                edges.append((head_id, right_id, f"{r_anomeric}-"))

        # OPEN_TAIL: left-side open edge (mirrored per variant when fuzzy-terminated)
        tail_id = OPEN_TAIL
        g_l = variant_owner.get(left_id)
        if g_l is not None:
            for k, vlist in enumerate(g_l.get("variant_ids", [])):
                if not vlist:
                    continue
                l_id = min(vlist, key=lambda i: positions[i][0])
                sx, sy = positions[l_id]
                sid = f"{OPEN_TAIL}#{k}"
                positions[sid] = (sx - dx, sy)
                edges.append((l_id, sid, f"{_ns_of(_find_node(l_id, nodes))}-"))
        else:
            positions[tail_id] = (lx - dx, ly)
            edges.append((left_id, tail_id, f"{_ns_of(_find_node(left_id, nodes))}-"))


# ------------------------------
# Edge label protocol ("site-configuration" string)
# ------------------------------
def make_edge_label(site: Any, anomeric: Any) -> str:
    """Mint the edge-label protocol string.

    Left slot = linkage site (acceptor side), right slot = anomeric
    configuration (donor side).
    """
    return f"{site}-{anomeric}"


def parse_edge_label(label_key: str) -> Tuple[str, str]:
    """Parse the edge-label protocol string -> (left, right).

    '4-1' -> ('4', '1'); '4-' -> ('4', ''); without '-' -> (label_key, '').
    """
    parts = label_key.split("-")
    return (parts[0] if parts else ""), (parts[1] if len(parts) > 1 else "")


# ------------------------------
# Parse -> expand -> layout pipeline
# ------------------------------
def prepare_layout_ext(
    tree: Any,
    dx: float = 1.5,
    dy: float = 1.5,
    ratio: float = 1,
    compact_repeat: bool = True,
    unknown_marker: Optional[str] = None,
    radius_ratio: float = 0.3,
) -> Tuple[None, Positions, EdgeList, LabelMap, List[dict], List[Any]]:
    """AST (or to_dict result) -> layout_tree's 5-tuple PLUS the expanded structure.

    Pipeline orchestration shared by both export backends: compact_repeat
    selects the repeat expansion mode. The 6th element is the expanded
    dict/list structure that layout_tree keyed `positions` by id() --
    expand_repeat* deep-copies Branch/Repeat contents, so the ORIGINAL AST
    dicts do not share ids with the layout output. Anything needing to look
    up residue fields (Anomeric/Ring/Absolute) by layout node id (e.g.
    highlight matching) must walk this expanded structure, never the caller's
    tree. Do not re-expand: ids would drift again.
    """
    nodes = tree.to_dict() if hasattr(tree, "to_dict") else tree
    if compact_repeat:
        expanded = expand_repeat_compact(nodes)
    else:
        expanded = expand_repeat(nodes)
    _, positions, edges, labels, repeat_groups = layout_tree(
        expanded, dx, dy, ratio=ratio, unknown_marker=unknown_marker, radius_ratio=radius_ratio
    )
    return None, positions, edges, labels, repeat_groups, expanded


def prepare_layout(
    tree: Any,
    dx: float = 1.5,
    dy: float = 1.5,
    ratio: float = 1,
    compact_repeat: bool = True,
    unknown_marker: Optional[str] = None,
    radius_ratio: float = 0.3,
) -> Tuple[None, Positions, EdgeList, LabelMap, List[dict]]:
    """AST (or to_dict result) -> layout_tree's original 5-tuple.

    Legacy wrapper around prepare_layout_ext; consumers that do not need the
    expanded structure keep unpacking five values.
    """
    return prepare_layout_ext(tree, dx, dy, ratio, compact_repeat, unknown_marker, radius_ratio)[
        :-1
    ]
