"""String-level utilities for CSDB fuzzy groups (<<XOR>>/<OR>):
nesting-aware option split + variant expansion.

split_fuzzy_variants/expand_fuzzy are pure string operations (itertools only)
and never go through the AST -- expansion results keep byte fidelity with the
original string (surrounding contexts such as brackets `[<<A|B>>]` and repeat
wrappers `/<<A|B>>/n=2/` are naturally preserved; only the `<<...>>`/`<...>`
spans themselves are replaced).

This module does not import the parser (the parser imports split_fuzzy_options
the other way around), so there is no cycle.
"""

from itertools import product
from typing import List, Tuple


def split_fuzzy_options(inner: str) -> List[str]:
    """Split a fuzzy group's inner text into options at '|' characters with depth==0.

    Depth counting: '<' +1, '>' -1, so '|' inside nested <<...>>/<...> groups is
    never cut by mistake. No stripping -- parse_csdb_linear strips by itself,
    and the expansion path needs byte fidelity.

    >>> split_fuzzy_options("βDGalp(1-4)|<<αDManp(1-2)|αLRhap(1-2)>>βDGalp(1-4)")
    ['βDGalp(1-4)', '<<αDManp(1-2)|αLRhap(1-2)>>βDGalp(1-4)']
    """
    options: List[str] = []
    depth = 0
    start = 0
    for i, c in enumerate(inner):
        if c == "<":
            depth += 1
        elif c == ">":
            depth -= 1
        elif c == "|" and depth == 0:
            options.append(inner[start:i])
            start = i + 1
    options.append(inner[start:])
    return options


def _scan_segments(csdb: str) -> Tuple[List[List[str]], bool]:
    """Cut csdb into a list of segments; each segment is a list of choosable
    alternatives (list[str]).

    Literal segments have a single element; fuzzy-group segments contain the
    (recursive) expansion texts of all their options.
    An unclosed '<' passes through literally (consistent with the parser's
    tolerance). Returns (segments, has_fuzzy).
    """
    segments: List[List[str]] = []
    literal: List[str] = []
    has_fuzzy = False
    i = 0
    n = len(csdb)
    while i < n:
        c = csdb[i]
        if c == "<":
            xor = i + 1 < n and csdb[i + 1] == "<"
            open_len = 2 if xor else 1
            depth = open_len
            j = i + open_len
            while j < n and depth > 0:
                if csdb[j] == "<":
                    depth += 1
                elif csdb[j] == ">":
                    depth -= 1
                j += 1
            if depth != 0:
                # Unclosed '<': pass through literally
                literal.append(c)
                i += 1
                continue
            # j stops after the matching closer (for xor it has passed both '>')
            inner = csdb[i + open_len : j - open_len]
            alts: List[str] = []
            for opt in split_fuzzy_options(inner):
                alts.extend(split_fuzzy_variants(opt))  # nested fuzzy expands recursively
            if literal:
                segments.append(["".join(literal)])
                literal = []
            segments.append(alts)
            has_fuzzy = True
            i = j
        else:
            literal.append(c)
            i += 1
    if literal:
        segments.append(["".join(literal)])
    return segments, has_fuzzy


def split_fuzzy_variants(csdb: str) -> List[str]:
    """Expand every fuzzy group in csdb as a Cartesian product -> plain variant
    string list (source order, deduplicated).

    No fuzzy group -> returns [csdb] (the original string object itself, zero byte drift).
    Variant order = order in which the options appear in the source string; the
    leftmost group varies slowest (product order).
    Degenerate cases: `<<A|A>>` deduplicates to 1 entry; `<<A|>>` replaces the
    empty option with an empty string; an unclosed '<' is treated as literal text.

    >>> split_fuzzy_variants("βDGlcp(1-4)/<<αDGalp(1-4)|αDGalpA(1-4)>>/n=2/")
    ['βDGlcp(1-4)/αDGalp(1-4)/n=2/', 'βDGlcp(1-4)/αDGalpA(1-4)/n=2/']
    """
    segments, has_fuzzy = _scan_segments(csdb)
    if not has_fuzzy:
        return [csdb]
    seen = set()
    out: List[str] = []
    for combo in product(*segments):
        s = "".join(combo)
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out


def expand_fuzzy_tracked(csdb_list) -> List[Tuple[int, str]]:
    """Like expand_fuzzy, but keep provenance: return [(source_index, text)].

    source_index is the 0-based index of the input line that produced each
    output string (the line itself or one of its generated variants).

    Idempotent: a generated variant that already appears as an input line is
    skipped, so re-expanding an already-expanded list ([merged, v1, v2]) is a
    no-op. Input lines themselves are never dropped or deduplicated (a
    duplicated fuzzy line still expands in place), preserving per-line
    grouping semantics.
    """
    items = list(csdb_list)
    present = set(items)
    out: List[Tuple[int, str]] = []
    for i, csdb in enumerate(items):
        out.append((i, csdb))
        for v in split_fuzzy_variants(csdb):
            if v != csdb and v not in present:
                out.append((i, v))
    return out


def expand_fuzzy(csdb_list) -> List[str]:
    """Emit [merged original, variant1, variant2, ...] per element and flatten.

    Elements without fuzzy groups pass through unchanged (single element).

    Idempotent against already-expanded input: generated variants that already
    appear as input lines are skipped, so a round trip that re-sends
    [merged, v1, v2] does not duplicate the variants. Variant dedup runs only
    against the input lines -- input lines themselves are never deduplicated,
    preserving per-line grouping semantics.
    """
    return [s for _, s in expand_fuzzy_tracked(csdb_list)]
