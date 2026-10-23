"""Motif highlighting: match a CSDB substructure against a laid-out glycan tree.

Ported semantics follow glycowork's GlycoDraw highlight (glycowork/motif/
draw.py): every element of the drawing gets a 'show'/'hide' state; hidden
elements are rendered with the dimmed palette while geometry stays identical.
Differences from glycowork:

- the motif is a CSDB substructure string (this package's own notation), not
  IUPAC-condensed;
- matching is a dependency-free backtracking tree matcher instead of networkx
  VF2 subgraph isomorphism. Glycan layouts here are small trees (<= ~100
  nodes, small degree), so a rooted-subtree matcher with wildcard predicates
  is microseconds and keeps the package free of new runtime dependencies;

Wildcard rules (v1):
- '?' inside linkage parentheses matches any site: (1-?), (?-4), (?-?);
- '?' in the anomeric position ('?DGlc') matches any anomeric configuration;
- 'X' in the absolute-configuration position matches any configuration;
- sugar NAMES come from the closed parser sugar_list -- name wildcards are
  not supported;
- motifs containing fuzzy (<<|>>/<|>) or repeat (/…/n=…/) blocks are rejected
  with ValueError.
"""

import logging
import re
from collections import namedtuple
from typing import Any, Dict, FrozenSet, Iterator, List, Optional, Tuple

from csdb2snfg.csdb.parser import parse_csdb_linear
from csdb2snfg.snfg.layout import EdgeList, LabelMap, is_open_node, parse_edge_label
from csdb2snfg.snfg.symbols import MODIFIERS

logger = logging.getLogger(__name__)

#: matched_nodes: set of layout node ids (union over ALL occurrences)
#: matched_edge_idx: set of indices into the layout `edges` list that are
#:     INTERNAL to some occurrence (full color); all other edges dim
#: occurrences: number of distinct match occurrences found
HighlightPlan = namedtuple("HighlightPlan", ["matched_nodes", "matched_edge_idx", "occurrences"])

_ANOM_ALIASES = {"α": "a", "β": "b"}
_ANOM_WILDCARDS = {"", "x", "?", "none"}
_ABS_WILDCARDS = {"", "x", "?", "none"}


class MotifNode:
    """One residue of the parsed motif tree.

    children: list of (site, anomeric, MotifNode) -- the linkage the child
    residue declares toward this (parent) residue, mirroring layout_tree's
    edge-label convention.
    """

    __slots__ = ("residue", "children")

    def __init__(self, residue):
        self.residue = residue
        self.children = []


def normalize_motif(motif: str) -> str:
    """Make '?' wildcards parser-legal.

    - '?' inside linkage parens -> '' : (1-?) -> (1-), (?-4) -> (-4),
      (?-?) -> (-);
    - remaining '?' (anomeric position) -> 'x' (RES_RE already accepts x).
    """

    def _strip_paren_wildcards(m):
        """re.sub callback: drop '?' wildcards inside one linkage paren group."""
        return "(" + m.group(1).replace("?", "") + ")"

    out = re.sub(r"\(([^()]*)\)", _strip_paren_wildcards, motif)
    return out.replace("?", "x")


def _reject_fuzzy_repeat(items: List[Any], motif: str) -> None:
    """Raise ValueError on any fuzzy/repeat block nested in ``items`` (motif v1 limit)."""
    for item in items:
        if not isinstance(item, dict):
            continue
        if item.get("XOR") or item.get("OR"):
            raise ValueError(
                f"highlight motif {motif!r} contains a fuzzy (<<|>>/<|>) "
                f"block, which is not supported in motifs (v1)"
            )
        if "Repeat" in item or "RepeatGroup" in item:
            raise ValueError(
                f"highlight motif {motif!r} contains a repeat (/…/n=…/) "
                f"block, which is not supported in motifs (v1)"
            )
        if "Branch" in item and item["Branch"]:
            _reject_fuzzy_repeat(item["Branch"], motif)


def _motif_link(item: dict) -> Tuple[str, str]:
    """(site, anomeric) the residue declares toward its parent, layout-style.

    Mirrors layout_tree: site = the 'to' half of the residue's own Linkage
    "(by-to)"; anomeric = the residue's Anomeric ('' when absent).
    """
    site = ""
    linkage = item.get("Linkage")
    if linkage:
        parts = str(linkage).strip("()").split("-")
        if len(parts) == 2 and parts[1].lower() != "none":
            site = parts[1]
    anomeric = item.get("Anomeric")
    if anomeric is None or str(anomeric).lower() == "none":
        anomeric = ""
    return site, str(anomeric)


def _build_motif(items: List[Any], attach_to: Optional[MotifNode]) -> Optional[MotifNode]:
    """Build the motif tree by walking chain items RIGHT-TO-LEFT like layout_tree.

    attach_to=None for the top chain (its first residue in reversed order is
    the motif root); for a Branch, attach_to is the parent MotifNode the
    branch's first residue connects to. Modifier residues (Me/Ac) have no
    edges in the layout and cannot participate in matching (v1) -- skipped.
    """
    root = None
    cur = attach_to
    for item in reversed(items):
        if not isinstance(item, dict):
            continue
        if "Residue" in item:
            if item["Residue"] in MODIFIERS:
                continue
            node = MotifNode(item)
            if root is None:
                root = node
            if cur is not None:
                site, anomeric = _motif_link(item)
                cur.children.append((site, anomeric, node))
            cur = node
        elif "Branch" in item and item["Branch"]:
            if cur is not None:
                _build_motif(item["Branch"], cur)
    return root


def parse_motif(motif: str) -> MotifNode:
    """Parse a CSDB substructure motif string into a MotifNode tree.

    Raises ValueError when the motif parses to nothing or contains
    fuzzy/repeat blocks.
    """
    normalized = normalize_motif(motif)
    tree = parse_csdb_linear(normalized)
    if tree is None:
        raise ValueError(f"highlight motif {motif!r} parses to nothing")
    items = tree.to_dict()
    if not isinstance(items, list):
        items = [items]
    _reject_fuzzy_repeat(items, motif)
    root = _build_motif(items, None)
    if root is None:
        raise ValueError(f"highlight motif {motif!r} contains no matchable residue")
    return root


def collect_residues(expanded: Any) -> Dict[int, dict]:
    """-> {id(residue_dict): residue_dict} for the EXPANDED layout structure.

    The layout keys positions by id() of dicts inside this structure (deep
    copies made by expand_repeat*), so residue fields (Anomeric/Ring/
    Absolute) can only be looked up through it. See prepare_layout_ext.
    """
    out = {}

    def _walk(obj):
        """Recursively collect every residue dict of ``obj`` into ``out``."""
        if isinstance(obj, dict):
            if "Residue" in obj:
                out[id(obj)] = obj
            for v in obj.values():
                _walk(v)
        elif isinstance(obj, list):
            for it in obj:
                _walk(it)

    _walk(expanded)
    return out


def _norm_anom(value: Any) -> str:
    """Normalize an anomeric value to a lowercase single letter (α/β -> a/b, None -> '')."""
    if value is None:
        return ""
    s = str(value).strip().lower()
    return _ANOM_ALIASES.get(s, s)


def _res_match(
    motif_res: dict, target_id: int, labels: LabelMap, residues: Dict[int, dict]
) -> bool:
    """Residue predicate: name equality + wildcard-aware field checks."""
    if labels.get(target_id) != motif_res.get("Residue"):
        return False
    target = residues.get(target_id, {})

    m_anom = _norm_anom(motif_res.get("Anomeric"))
    if m_anom not in _ANOM_WILDCARDS:
        if _norm_anom(target.get("Anomeric")) != m_anom:
            return False

    m_abs = motif_res.get("Absolute")
    m_abs = "" if m_abs is None else str(m_abs).strip().lower()
    if m_abs not in _ABS_WILDCARDS:
        t_abs = target.get("Absolute")
        t_abs = "" if t_abs is None else str(t_abs).strip().lower()
        if t_abs != m_abs:
            return False

    m_ring = motif_res.get("Ring")
    if m_ring not in (None, ""):
        t_ring = target.get("Ring")
        if t_ring is None or str(t_ring) != str(m_ring):
            return False

    return True


def _edge_match(motif_edge: Tuple[str, str], target_edge: Tuple[str, str]) -> bool:
    """(site, anomeric) predicate with wildcard support on both halves."""
    m_site, m_anom = motif_edge
    t_site, t_anom = target_edge
    m_site = "" if m_site is None else str(m_site).strip()
    if m_site not in ("", "?"):
        if str(t_site).strip() != m_site:
            return False
    m_anom = _norm_anom(m_anom)
    if m_anom not in _ANOM_WILDCARDS:
        if _norm_anom(t_anom) != m_anom:
            return False
    return True


def _match_all(
    mnode: MotifNode,
    tid: int,
    used_edges: FrozenSet[int],
    mapping: Dict[int, int],
    children_of: Dict[int, list],
    labels: LabelMap,
    residues: Dict[int, dict],
) -> Iterator[Tuple[Dict[int, int], FrozenSet[int]]]:
    """Yield (mapping, used_edge_set) for every way to root the motif at tid.

    Subgraph (not induced) semantics: every motif child must bind a DISTINCT
    target child edge; extra target children are allowed -- same as
    GlycoWorkbench/glycowork motif matching.
    """
    if not _res_match(mnode.residue, tid, labels, residues):
        return
    mapping = dict(mapping)
    mapping[id(mnode)] = tid
    if not mnode.children:
        yield mapping, frozenset(used_edges)
        return
    yield from _bind_children(
        mnode.children, 0, tid, used_edges, mapping, children_of, labels, residues
    )


def _bind_children(
    mchildren: List[Tuple[str, str, MotifNode]],
    k: int,
    tid: int,
    used_edges: FrozenSet[int],
    mapping: Dict[int, int],
    children_of: Dict[int, list],
    labels: LabelMap,
    residues: Dict[int, dict],
) -> Iterator[Tuple[Dict[int, int], FrozenSet[int]]]:
    """Backtracking generator binding ``mchildren[k:]`` to distinct target edges.

    Yields ``(mapping, used_edges)`` for every assignment in which each
    remaining motif child occupies a distinct, unused target child edge of
    ``tid`` (subgraph semantics: extra target children are allowed).
    """
    if k == len(mchildren):
        yield mapping, used_edges
        return
    site, anom, cnode = mchildren[k]
    for idx, cid, t_site, t_anom in children_of.get(tid, ()):
        if idx in used_edges:
            continue
        if not _edge_match((site, anom), (t_site, t_anom)):
            continue
        for m2, used2 in _match_all(
            cnode, cid, used_edges | {idx}, mapping, children_of, labels, residues
        ):
            yield from _bind_children(
                mchildren, k + 1, tid, used2, m2, children_of, labels, residues
            )


def compute_highlight(
    expanded: Any, edges: EdgeList, labels: LabelMap, motif: str
) -> Optional[HighlightPlan]:
    """-> HighlightPlan | None.

    Matches the CSDB substructure `motif` against the laid-out structure
    (expanded/edges/labels from prepare_layout_ext) and returns the union of
    ALL occurrences. Zero occurrences -> logger.warning + None (the backends
    then render without highlight, per requirement).
    """
    motif_root = parse_motif(motif)
    residues = collect_residues(expanded)

    children_of = {}
    for idx, (parent_id, child_id, label_str) in enumerate(edges):
        if is_open_node(parent_id) or is_open_node(child_id):
            continue
        site, anomeric = parse_edge_label(label_str or "")
        children_of.setdefault(parent_id, []).append((idx, child_id, site, anomeric))

    matched_nodes = set()
    matched_edges = set()
    seen = set()
    occurrences = 0
    for cand in [nid for nid in labels if not is_open_node(nid)]:
        for mapping, used in _match_all(
            motif_root, cand, frozenset(), {}, children_of, labels, residues
        ):
            key = (frozenset(mapping.values()), frozenset(used))
            if key in seen:
                continue
            seen.add(key)
            occurrences += 1
            matched_nodes.update(mapping.values())
            matched_edges.update(used)

    if not occurrences:
        logger.warning(
            "highlight motif %r matched nothing in the structure; rendering without highlight",
            motif,
        )
        return None
    return HighlightPlan(matched_nodes, matched_edges, occurrences)
