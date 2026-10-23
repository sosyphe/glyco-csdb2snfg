"""CSDB linear notation parser producing an AST for glycan structures."""

import logging
import re
from typing import List, Optional, Tuple

from csdb2snfg.csdb.fuzzy import split_fuzzy_options

logger = logging.getLogger(__name__)

# =========================
# AST Nodes
# =========================


class Node:
    """Base class for CSDB AST nodes.

    Subclass contract:
    - ``children()`` returns the list of direct child nodes (empty for
      leaves); it never returns ``None``.
    - ``to_dict()`` returns the JSON-serializable form consumed by
      ``snfg.layout`` (dict/list/scalar), or ``None`` when the node has no
      serializable payload (e.g. an empty LinkageNode).
    """

    def children(self):
        return []

    def to_dict(self):
        raise NotImplementedError


class ChainNode(Node):
    """A linear (unbranched) sequence of nodes; the top-level parse result."""

    def __init__(self, nodes: List[Node]):
        self.nodes = nodes

    def children(self):
        return self.nodes

    def to_dict(self):
        return [n.to_dict() for n in self.nodes]


class BranchNode(Node):
    """A ``[...]`` branch; wraps the branch contents as a single ChainNode child."""

    def __init__(self, chain: ChainNode):
        self.chain = chain

    def children(self):
        return [self.chain]

    def to_dict(self):
        return {"Branch": self.chain.to_dict()}


class FuzzyNode(Node):
    """An ambiguous group: ``<A|B>`` (OR, ``xor=False``) or ``<<A|B>>`` (XOR)."""

    def __init__(self, options: List[Node], xor=False):
        self.options = options
        self.xor = xor

    def children(self):
        return self.options

    def to_dict(self):
        return {"XOR" if self.xor else "OR": [o.to_dict() for o in self.options]}


class RepeatNode(Node):
    """A ``/unit/n=count/`` repeating block.

    ``count`` is the raw text between ``/n=`` and the closing ``/`` (a
    string, ``'?'`` for open counts, or ``None`` for the bare ``/n=`` form).
    """

    def __init__(self, unit: Node, count):
        self.unit = unit
        self.count = count

    def children(self):
        return [self.unit]

    def to_dict(self):
        return {"Repeat": {"Unit": self.unit.to_dict(), "Count": self.count}}


class LinkageNode(Node):
    """Linkage positions attached to a residue, e.g. ``(1-4)``.

    ``by``/``to`` are ints or ``None`` when the corresponding position is
    unspecified; ``by_unknown``/``to_unknown`` mark an explicit ``?`` in the
    source (``(1-?)``, ``(?-4)``), which to_dict renders back as ``?``.
    """

    def __init__(self, by=None, to=None, by_unknown=False, to_unknown=False):
        self.by = by
        self.to = to
        self.by_unknown = by_unknown
        self.to_unknown = to_unknown

    def to_dict(self):
        if not (self.by or self.to or self.by_unknown or self.to_unknown):
            return None
        by = "?" if self.by_unknown else self.by
        to = "?" if self.to_unknown else self.to
        return f"({by}-{to})"


class ResidueNode(Node):
    """A single monosaccharide residue.

    Fields: ``name`` (base sugar + modifier, e.g. ``GlcNAc``), ``anomeric``
    (one of α/β/a/b/l/x), ``absolute`` (D/L/R/X/S), ``ring`` (``'p'`` or
    ``'f'``), ``linkage`` (LinkageNode or ``None``), ``non_stoichiometric``
    (int from a ``-6)``/``%40``-style prefix, or ``None``), ``raw`` (the
    exact source text the residue was parsed from), ``anomeric_unknown`` /
    ``absolute_unknown`` (an explicit ``?`` occupied that slot in the
    source, e.g. ``?DGalp`` / ``x?DGlcp`` / ``??Glcp``; a ``?`` suppresses
    the literal configuration value, so ``anomeric`` stays ``None``).
    """

    def __init__(
        self,
        name,
        anomeric=None,
        absolute=None,
        ring=None,
        linkage=None,
        non_stoichiometric=None,
        raw=None,
        anomeric_unknown=False,
        absolute_unknown=False,
    ):
        self.name = name
        self.anomeric = anomeric
        self.absolute = absolute
        self.ring = ring
        self.linkage = linkage
        self.non_stoichiometric = non_stoichiometric
        self.raw = raw
        self.anomeric_unknown = anomeric_unknown
        self.absolute_unknown = absolute_unknown

    def children(self):
        return [self.linkage] if self.linkage else []

    def to_dict(self):
        d = {
            "Residue": self.name,
            "Anomeric": self.anomeric,
            "Absolute": self.absolute,
            "Ring": self.ring,
            "Linkage": self.linkage.to_dict() if self.linkage else None,
            "NonStoichiometric": self.non_stoichiometric,
            "Raw": self.raw,
        }
        # Conditional keys: clean strings keep the historical JSON verbatim
        if self.anomeric_unknown:
            d["AnomericUnknown"] = True
        if self.absolute_unknown:
            d["AbsoluteUnknown"] = True
        return d


# =========================
# Residue Parser
# =========================
sugar_list = [
    # Modifying groups and special prefixes
    "Me","Ac","Gc","P","S","T",
    # Complex long abbreviations (matched first)
    "LDmanHep","DDmanHep","6dAltNAc","6dTalNAc","8eAci","8eLeg","4eLeg",
    "MurNAc","MurNGc","Neu5Ac","Neu5Gc","RhaNAc","GalNAc","GlcNAc","ManNAc",
    "AllNAc","AltNAc","GulNAc","IdoNAc","TalNAc","QuiNAc","FucNAc",
    # Abbreviations carrying a modifier
    "AllA","AllN","AltA","AltN","GalA","GalN","GlcA","GlcN","GulA",
    "GulN","IdoA","IdoN","ManA","ManN","TalA","TalN",
    # 6-deoxy series
    "6dAlt","6dGul","6dTal",
    # Base three-character abbreviations
    "Abe","Aci","All","Alt","Api","Ara","Bac","Col","Dha","Dig","Fru",
    "Fuc","Gal","Glc","Gul","Ido","Kdn","Kdo","Leg","Lyx","Man","Mur",
    "Neu","Oli","Par","Pse","Psi","Qui","Rha","Rib","Sia","Sor","Tag","Tal","Tyv","Xyl",
]  # fmt: skip

sugar_list.sort(key=len, reverse=True)
sugar_pattern = "|".join(map(re.escape, sugar_list))
RES_RE = re.compile(
    rf"""
    (?P<ns>-\d+\)|%\d+)?                       # optional non-stoichiometric number
    (?P<anomeric>[αβablx]?)                    # α/β anomeric configuration
    (?P<anom_q>\?)?                            # '?' at the anomeric slot ('?DGalp', 'x?DGlcp')
    (?P<absolute>[DLRXS]?)                     # D/L/R/X/S absolute configuration
    (?P<abs_q>\?)?                             # '?' at the absolute slot (second ? of '??Glcp')
    (?P<name>{sugar_pattern})                  # base sugar name (e.g. Gal, Rha, Glc)
    (?P<ring>[pf])?                            # ring form (p pyranose / f furanose)
    (?P<modifier>[ANS])?                       # key modifiers: A(acid), N(amine), S(sulfate)
    (?:\((?P<by>\?|\d*)-(?P<to>\?|\d*)?\)? )?   # linkage positions (1-4); '?' = unknown
    #                                          ('\?' must precede \d*: the empty \d* match
    #                                          would win the alternation and skip '?')
    """,
    re.VERBOSE,
)

# A run of nothing but anomeric-configuration characters (e.g. a stray 'β'
# split off its residue by an intervening '/n=K/' repeat marker). Such a run
# is carried across the intervening construct onto the next residue instead
# of being dropped with a warning.
ANOM_RUN = re.compile(r"[αβablx]+")


def parse_residue(token: str) -> List[ResidueNode]:
    """Parse the leading run of residues in ``token`` via RES_RE.

    One "token" may hold several consecutive residues (e.g.
    ``βDGalp(1-4)αLRhap``); matching stops at the first position RES_RE
    does not recognize. Returns the parsed ResidueNode list — empty when
    the head matches no known residue. Trailing unmatched text is left for
    the caller to dispatch or drop.
    """
    nodes = []
    pos = 0
    while pos < len(token):
        m = RES_RE.match(token, pos)
        if not m:
            break
        ns = m.group("ns")
        if ns:
            ns = int(ns.strip("-)%")) if ns.startswith("-") else int(ns.strip("%"))
        anomeric = m.group("anomeric") or None
        # An explicit '?' suppresses the literal configuration: 'x?DGlcp'
        # keeps anomeric=None (the historical output dropped the whole 'x?'
        # fragment, so the default render path stays byte-identical) and is
        # recorded as anomeric_unknown for show_unknown consumers.
        anomeric_unknown = m.group("anom_q") is not None
        if anomeric_unknown:
            anomeric = None
        absolute = m.group("absolute") or None
        absolute_unknown = m.group("abs_q") is not None
        name = m.group("name")
        mod = m.group("modifier") or ""
        fullname = f"{name}{mod}"
        ring = m.group("ring") or None
        by = m.group("by")
        to = m.group("to")
        by_unknown = by == "?"
        to_unknown = to == "?"
        linkage = (
            LinkageNode(
                by=None if by_unknown else (int(by) if by else None),
                to=None if to_unknown else (int(to) if to else None),
                by_unknown=by_unknown,
                to_unknown=to_unknown,
            )
            if by or to
            else None
        )
        raw = token[m.start() : m.end()]
        nodes.append(
            ResidueNode(
                fullname,
                anomeric,
                absolute,
                ring,
                linkage,
                ns,
                raw,
                anomeric_unknown=anomeric_unknown,
                absolute_unknown=absolute_unknown,
            )
        )
        pos = m.end()
    return nodes


# =========================
# Stack-based Parser with Repeat
# =========================
# The _apply_* handlers below are verbatim extractions of one dispatch case
# each; the dispatch order itself lives in parse_csdb_linear.


def _has_unclosed_opener(text: str) -> bool:
    """Return True if ``text`` holds a '[' or '<' with no matching closer.

    Used by ``_apply_repeat`` to detect a repeat unit whose left boundary fell
    through to the string start and still runs across a still-open branch /
    fuzzy opener — i.e. the ``/n=?/`` marker is missing its leading ``/``.
    """
    square = angle = 0
    for ch in text:
        if ch == "[":
            square += 1
        elif ch == "]":
            square = max(0, square - 1)
        elif ch == "<":
            angle += 1
        elif ch == ">":
            angle = max(0, angle - 1)
    return square > 0 or angle > 0


def _apply_repeat(
    code: str,
    i: int,
    stack: List[List[Node]],
    spans: List[Tuple[int, int]],
    pending_anom: Optional[str] = None,
) -> Tuple[int, Optional[str]]:
    """Apply the ``/n=`` repeat construct at offset ``i``.

    The repeat unit is the text between the nearest ``/`` left of the marker
    (or the string start) and ``i``. It is re-parsed recursively, keeping a
    non-stoichiometric prefix carried by the nodes it replaces, and those
    nodes in ``stack[-1]`` are swapped for a single RepeatNode.

    ``spans`` accumulates the ``(unit_start, end_offset)`` text ranges of the
    repeats applied so far in this frame. When searching for the unit start,
    ``/`` characters inside an already-consumed span are skipped, so an outer
    repeat's unit can enclose an inner ``/unit/n=K/`` block (nested repeats):
    without the skip the inner marker's closing ``/`` would always win the
    nearest-``/`` search and nesting could never be represented. Dropped
    repeats register no span — their slashes stay eligible boundaries.

    Returns ``(new offset, pending_anom)``: a bare anomeric run left over at
    the tail of the unit re-parse (e.g. the 'β' of '…β/n=4/DManp…') migrates
    into the caller's ``pending_anom`` so it reaches the residue after the
    marker; the caller's own pending value survives otherwise.
    """
    # Matches /n=?/ as well
    m = re.match(r"/n=([^/]+)/?", code[i:])
    count = m.group(1) if m else None

    # Detect malformed repeat count — a valid count is digits, '?', or a
    # simple variable letter (e.g. 'n', 'N').  When the closing '/' is
    # missing, [^/]+ absorbs residue text (e.g. '2αDGalp(1-6)'); warn so
    # the user sees the problem instead of getting a silently wrong AST.
    if count and not re.match(r"^[0-9a-zA-Z?]+$", count):
        logger.warning(
            "malformed repeat count %r — expected digits or '?' "
            "(possibly missing closing '/'): %r",
            count,
            code,
        )

    # Find the repeat unit start: nearest '/' to the left, or the beginning
    unit_start = code.rfind("/", 0, i)
    while unit_start != -1 and any(a <= unit_start < b for a, b in spans):
        unit_start = code.rfind("/", 0, unit_start)
    if unit_start == -1:
        # No '/' found outside inner spans — the repeat unit extends to the
        # beginning of the string.  Include position 0 when it is a residue
        # character (e.g. anomeric β); skip it when it is a branch opener
        # '[' or fuzzy opener '<' (those are handled by the dispatch loop and
        # are not part of the repeat unit text).
        unit_start = 0
        if code and code[0] in "[<":
            unit_str = code[1:i]
        else:
            unit_str = code[:i]
    else:
        unit_str = code[unit_start + 1 : i]

    # A repeat unit must be a self-contained, '/'-delimited fragment at the
    # marker's own nesting level. A unit at string start is allowed (unit_str
    # trimmed from position 0/the enclosing '['), but if the backward search
    # fell through and the text still holds an opener whose closer lies after
    # the marker, then '/n=?/' is missing its leading '/' ('[…UU/n=2/…]' should
    # be '[…U/U/n=2/…]'). That is a hard format error, not a silent drop.
    if _has_unclosed_opener(unit_str):
        raise ValueError(
            f"incomplete repeat unit at offset {i}: '/n=?/' must be preceded "
            "by a '/'-delimited unit ('/unit/n=?/'), but the unit runs across "
            "an unclosed '[' or '<'"
        )

    # Pre-count the nodes about to be removed (to save NonStoichiometric)
    pre_nodes, _, _ = _parse_frame(unit_str, None, None, [])
    n_remove = len(pre_nodes) if pre_nodes else 1

    # CSDB notation rule: the whole structure (or side chain / repeat unit)
    # cannot start with a repeating part.  '/n=K/...' at position 0 has no
    # unit at all — the user should extract one copy out (e.g. 'AB/AB/n=9/'
    # instead of '/AB/n=10/').
    if unit_start == 0 and not unit_str:
        logger.warning(
            "repeat at start of string with no preceding unit — "
            "CSDB rule: extract one copy out (e.g. 'AB/AB/n=9/' "
            "instead of '/AB/n=10/'): %r",
            code,
        )

    # Save NonStoichiometric (e.g. a -6) prefix) from the nodes being removed
    removed = stack[-1][-n_remove:] if n_remove <= len(stack[-1]) else []
    saved_ns = None
    for rn in removed:
        if hasattr(rn, "non_stoichiometric") and rn.non_stoichiometric is not None:
            saved_ns = rn.non_stoichiometric
            break

    # Re-parse the repeat unit (pass saved_ns to keep -6)-style prefixes);
    # a bare anomeric run left at the unit tail migrates to the caller.
    unit_nodes, _, unit_pending_anom = _parse_frame(unit_str, saved_ns, None, [])
    unit_node = ChainNode(unit_nodes) if unit_nodes else None

    if unit_node is None:
        # The unit holds no recognizable residue (e.g. an unsupported
        # abbreviation as in '/xXEtg(1-2)/n=?/'): its characters were
        # already dropped with warnings and never pushed nodes, so
        # there is nothing to replace. Skip the repeat instead of
        # building RepeatNode(None), which would crash to_dict().
        logger.warning(
            "dropped repeat with unparseable unit %r at offset %d "
            "(no recognizable residue inside): %r",
            unit_str,
            unit_start,
            code,
        )
    else:
        # Replace the repeat unit's nodes in stack[-1]
        stack[-1] = stack[-1][:-n_remove] + [RepeatNode(unit_node, count)]
        # Record the consumed span (unit-opening '/' through the marker end)
        # so enclosing repeats can skip over these boundaries.
        spans.append((unit_start, i + (m.end() if m else 3)))

    # Advance the pointer; hand the unit tail's bare anomeric (if any) to the
    # caller so it reaches the residue parsed after the marker.
    new_i = i + (m.end() if m else 3)
    if unit_pending_anom is not None:
        pending_anom = unit_pending_anom
    return new_i, pending_anom


def _apply_fuzzy(code: str, i: int, n: int, stack: List[List[Node]]) -> int:
    """Apply the ``<`` fuzzy construct at offset ``i``; return the new offset.

    Scans the balanced ``<...>`` (OR) or ``<<...>>`` (XOR) group, splits the
    inner text into nesting-aware options, parses each one recursively and
    appends a FuzzyNode to ``stack[-1]``. Options that parse to nothing are
    dropped with a warning; if none survives, the whole group is dropped.
    """
    xor = False
    if i + 1 < n and code[i + 1] == "<":
        xor = True
        i += 1
    depth = 1
    j = i + 1
    while j < n and depth > 0:
        if code[j] == "<":
            depth += 1
        elif code[j] == ">":
            depth -= 1
        j += 1
    # Unclosed '<' / '<<' — the scan loop exited at EOF with depth > 0
    if depth > 0:
        opener = "<<" if xor else "<"
        closer = ">>" if xor else ">"
        logger.warning(
            "unclosed '%s' at offset %d — expected '%s' but reached end of "
            "input: %r",
            opener,
            i - (1 if xor else 0),
            closer,
            code,
        )
    inner = code[i + 1 : j - 1]
    # Nesting-aware split (the inner '|' of <<A|<<B|C>>D>> must not be
    # cut); parse_csdb_linear strips whitespace itself, so no
    # preprocessing is needed here
    raw_options = split_fuzzy_options(inner)
    options = [parse_csdb_linear(x) for x in raw_options]
    kept = [o for o in options if o is not None]
    if len(kept) < len(options):
        # An option holds no recognizable residue (e.g. an unsupported
        # substituent abbreviation): drop it with a warning instead of
        # crashing in FuzzyNode.to_dict(). If nothing survives, the
        # whole fuzzy group is dropped.
        dropped = [r for r, o in zip(raw_options, options) if o is None]
        logger.warning(
            "dropped unparseable fuzzy option(s) %r at offset %d "
            "(no recognizable residue inside): %r",
            dropped,
            i,
            code,
        )
    if kept:
        stack[-1].append(FuzzyNode(kept, xor))
    return j + (1 if xor else 0)


def _apply_residues(
    code: str,
    i: int,
    n: int,
    stack: List[List[Node]],
    pending_ns: Optional[int],
    pending_anom: Optional[str] = None,
) -> Tuple[int, Optional[int], Optional[str]]:
    """Consume the residue run at offset ``i``.

    Returns ``(new offset, pending_ns, pending_anom)``.

    Handles the non-stoichiometric hand-off: a prefix carried by the first
    residue of an otherwise empty chain migrates into ``pending_ns``, and a
    pending prefix is applied to the next residue while at stack depth 1.
    ``pending_anom`` carries a bare anomeric-configuration run (e.g. a 'β'
    split off its residue by an intervening ``/n=K/`` marker) onto the next
    residue parsed; it is cleared whether or not it could be applied, and
    never overrides an explicit (or explicit-'?') configuration.
    When nothing matches, skips forward to the next construct the outer
    dispatch would handle and emits one coalesced warning for the dropped
    run (a ``\\d+%`` suffix gets a suffix-specific message; a pure anomeric
    run is carried instead of warned about).
    """
    residues = parse_residue(code[i:])
    if residues:
        # Mirror the pending_ns convention: the carried anomeric applies to
        # the next residue at stack depth 1 and stays pending inside deeper
        # levels (e.g. across a '[...]' branch) until then.
        if pending_anom is not None and len(stack) == 1:
            if residues[0].anomeric is None and not residues[0].anomeric_unknown:
                residues[0].anomeric = pending_anom
            pending_anom = None
        if (
            residues[0].non_stoichiometric is not None
            and pending_ns is None
            and len(stack[-1]) == 0
        ):
            pending_ns = residues[0].non_stoichiometric
            residues[0].non_stoichiometric = None
        if pending_ns is not None and len(stack) == 1:
            residues[0].non_stoichiometric = pending_ns
            pending_ns = None
        stack[-1].extend(residues)
        i += sum(len(r.raw) for r in residues)
    else:
        # Unrecognized fragment: skip forward until the next construct
        # the outer dispatch would handle, coalescing the run into a
        # single warning. The break conditions mirror the outer
        # dispatch condition-for-condition, so parse behavior is
        # unchanged -- the same characters get skipped, in the same
        # order -- but the user now learns what was dropped (e.g. a
        # residue whose name is not in sugar_list like '?DGro', or a
        # non-stoichiometric suffix like '40%' which only has
        # prefix-form support). Ambiguity markers on known residues
        # ('?DGlc', '(1-?)') are parsed, not dropped.
        start = i
        while i < n:
            ch = code[i]
            if re.match(r"-?(\d+)\)", code[i:]) or code[i : i + 3] == "/n=" or ch in "[]<>/":
                break
            if parse_residue(code[i:]):
                break
            i += 1
        skipped = code[start:i]
        if ANOM_RUN.fullmatch(skipped):
            # A bare anomeric run (e.g. the 'β' of '…β/n=4/DManp…'): carry it
            # onto the next residue instead of dropping it with a warning.
            pending_anom = skipped
        elif re.fullmatch(r"\d+%", skipped):
            logger.warning(
                "dropped non-stoichiometric suffix %r at offset %d "
                "(only the prefix form like '%%40aDXylp' is "
                "supported): %r",
                skipped,
                start,
                code,
            )
        else:
            logger.warning(
                "dropped unrecognized text %r at offset %d (unknown "
                "or ambiguous residue/character): %r",
                skipped,
                start,
                code,
            )
    return i, pending_ns, pending_anom


def _parse_frame(
    code: str,
    pending_ns: Optional[int],
    pending_anom: Optional[str],
    spans: List[Tuple[int, int]],
) -> Tuple[List[Node], Optional[int], Optional[str]]:
    """Run one dispatch-loop frame over stripped ``code``.

    Returns ``(parsed nodes, pending_ns, pending_anom)``. ``[...]`` branches
    push/pop ``stack``; repeats, fuzzy groups and residue runs delegate to
    the ``_apply_*`` handlers. ``spans`` and the ``pending_*`` values thread
    the repeat-nesting and bare-anomeric carry-over state described on
    ``parse_csdb_linear``/``_apply_repeat``/``_apply_residues``.
    """
    i = 0
    n = len(code)
    stack = [[]]

    while i < n:
        c = code[i]
        m = re.match(r"-?(\d+)\)", code[i:])
        if m:
            pending_ns = int(m.group(1))
            i += m.end()
            continue

        # Repeat detection
        if code[i : i + 3] == "/n=":
            i, pending_anom = _apply_repeat(code, i, stack, spans, pending_anom)
            continue

        # Branch
        elif c == "[":
            stack.append([])
            i += 1
        elif c == "]":
            if len(stack) < 2:
                # Unbalanced ']' (e.g. inside a repeat unit whose text was
                # cut mid-branch): dropping it keeps the documented
                # "unrecognized fragments never raise" contract.
                logger.warning(
                    "dropped unbalanced ']' at offset %d (no open branch): %r",
                    i,
                    code,
                )
                i += 1
                continue
            nodes = stack.pop()
            branch = BranchNode(ChainNode(nodes))
            stack[-1].append(branch)
            i += 1

        # Fuzzy
        elif c == "<":
            i = _apply_fuzzy(code, i, n, stack)

        # Chain separator
        elif c == "/":
            i += 1

        # Stray / extra '>': a fuzzy group written '<...>>' closes the '<...>'
        # scan at its first '>', leaving this orphan (or a bare '>' with no
        # opener). Raising keeps the dispatch loop from hanging and reports the
        # position. (XOR '<<...>>' is consumed whole by _apply_fuzzy's +1.)
        elif c == ">":
            raise ValueError(
                f"unmatched '>' at offset {i}: fuzzy delimiter not balanced "
                "(a '<...>' opener cannot close with '>>'; use '<...>' or '<<...>>')"
            )

        # Residue / Alias
        else:
            i, pending_ns, pending_anom = _apply_residues(
                code, i, n, stack, pending_ns, pending_anom
            )
    # Unclosed '[' — branch contents would be silently discarded
    if len(stack) > 1:
        logger.warning(
            "unclosed '[' — %d branch level(s) still open at end of input, "
            "contents discarded: %r",
            len(stack) - 1,
            code,
        )
    return stack[0], pending_ns, pending_anom


# Regex matching a truncated linkage: an opening '(' followed by digits and '-'
# but no closing ')'.  E.g. "βDGlcp(1-" matches "(1-" at the tail.
_TRUNC_LINKAGE_RE = re.compile(r"\(\d+-[^)]*$")


def _iter_all_residues(nodes):
    """Yield every ResidueNode in an AST node list (recursive into branches,
    fuzzy options, and repeat units)."""
    for node in nodes:
        if isinstance(node, ResidueNode):
            yield node
        elif isinstance(node, BranchNode):
            yield from _iter_all_residues(node.chain.children())
        elif isinstance(node, FuzzyNode):
            for opt in node.options:
                yield from _iter_all_residues(opt.children())
        elif isinstance(node, RepeatNode):
            yield from _iter_all_residues(node.unit.children())
        elif isinstance(node, ChainNode):
            yield from _iter_all_residues(node.children())


def _check_truncated_linkages(nodes: list, code: str) -> None:
    """Warn if any residue has a truncated linkage (e.g. ``βDGlcp(1-``).

    A residue with ``linkage.to is None`` is legitimate at the reducing end
    (no linkage at all, e.g. the trailing ``βDGlcp`` of ``…(1-4)βDGlcp``,
    or a partial linkage like ``(1-`` indicating an unspecified target).
    We only flag residues whose *raw* text ends with an unclosed parenthesis
    like ``(1-`` — a clear sign of input truncation — and only when they
    are **not** the last top-level chain node (the reducing end).
    """
    # Skip the last top-level node: the reducing-end residue legitimately
    # has an incomplete linkage (e.g. SIMPLE_CSDB = "βDGlcp(1-4)αDGlcp(1-").
    for node in _iter_all_residues(nodes[:-1]):
        if (
            node.linkage is not None
            and node.linkage.to is None
            and not node.linkage.to_unknown
            and node.raw
            and _TRUNC_LINKAGE_RE.search(node.raw)
        ):
            logger.warning(
                "truncated linkage in '%s' — missing target position: %r",
                node.raw,
                code,
            )


def parse_csdb_linear(code: str, _pending_ns: Optional[int] = None) -> Optional[Node]:
    """Parse a CSDB linear-notation string into an AST.

    Supported grammar: residues (anomeric/absolute/ring/modifier/linkage
    parts), ``[...]`` branches, ``<A|B>`` / ``<<A|B>>`` fuzzy OR/XOR
    groups, ``/unit/n=count/`` repeats (nestable: an outer unit may enclose
    an inner ``/n=`` block), non-stoichiometric prefixes (``-6)`` or
    ``%40``), and ``/`` chain separators. A bare anomeric run split off its
    residue by an intervening construct (e.g. the ``β`` of
    ``…β/n=4/DManp…``) is carried onto the next residue instead of dropped.

    Returns a ChainNode wrapping the parsed nodes, or ``None`` when nothing
    recognizable was parsed. The result is always a ChainNode (never a bare
    Branch/Repeat/residue node) because downstream consumers iterate the
    ``to_dict()`` list. Unrecognized fragments never raise: they are
    dropped with a ``logger.warning`` naming the offending text and offset.

    Args:
        code: CSDB linear string; surrounding whitespace is stripped.
        _pending_ns: internal — carries a saved non-stoichiometric prefix
            across the recursive re-parse of a repeat unit, so that e.g.
            the ``-6)`` of ``/-6)[X(1-3)]Y/n=3/`` stays on the unit's
            first residue. External callers should leave it ``None``.
    """
    stripped = code.strip()
    nodes, _, _ = _parse_frame(stripped, _pending_ns, None, [])
    if not nodes:
        logger.warning(
            "no recognizable glycan structure parsed from: %r", stripped
        )
        return None
    # Post-parse structural validation (warnings only, no AST mutation)
    _check_truncated_linkages(nodes, stripped)
    # Always return a ChainNode: downstream consumers (expand_repeat/
    # layout_tree, ...) iterate the to_dict() list; returning a bare node for a
    # single residue/Branch/Repeat would make iteration land on the dict's keys
    return ChainNode(nodes)


# =========================
# AST Printer
# =========================
def print_ast(node: Node, indent: int = 0) -> None:
    """Print an indented human-readable view of the AST to stdout (debug aid)."""
    prefix = "  " * indent
    if isinstance(node, ChainNode):
        print(f"{prefix}ChainNode")
        for c in node.children():
            print_ast(c, indent + 1)
    elif isinstance(node, BranchNode):
        print(f"{prefix}BranchNode")
        print_ast(node.chain, indent + 1)
    elif isinstance(node, FuzzyNode):
        print(f"{prefix}FuzzyNode({'XOR' if node.xor else 'OR'})")
        for o in node.options:
            print_ast(o, indent + 1)
    elif isinstance(node, RepeatNode):
        print(f"{prefix}RepeatNode(count={node.count})")
        print(f"{prefix}  Unit:")
        print_ast(node.unit, indent + 2)
    elif isinstance(node, ResidueNode):
        print(f"{prefix}ResidueNode({node.raw})")
