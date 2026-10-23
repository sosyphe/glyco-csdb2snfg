"""Legend row for the python-pptx backend."""

from pptx.enum.text import MSO_ANCHOR
from pptx.util import Emu, Pt

from csdb2snfg.export.pptx.primitives import draw_node
from csdb2snfg.export.pptx.text import add_text_box
from csdb2snfg.snfg.style import load_style

# Static per-character advance widths (1/1000 em) from the Adobe standard
# metrics: Helvetica.afm (Arial is metric-compatible) and Times-Roman.afm.
# Pure literal tables + arithmetic at runtime -> deterministic across
# machines; the root package's font discovery (glycan_pipeline converter.py)
# must not be used here (dependency direction + system-font nondeterminism).
_HELVETICA_W = {
    " ": 278,
    "!": 278,
    '"': 355,
    "#": 556,
    "$": 556,
    "%": 889,
    "&": 667,
    "'": 191,
    "(": 333,
    ")": 333,
    "*": 389,
    "+": 584,
    ",": 278,
    "-": 333,
    ".": 278,
    "/": 278,
    "0": 556,
    "1": 556,
    "2": 556,
    "3": 556,
    "4": 556,
    "5": 556,
    "6": 556,
    "7": 556,
    "8": 556,
    "9": 556,
    ":": 278,
    ";": 278,
    "<": 584,
    "=": 584,
    ">": 584,
    "?": 556,
    "@": 975,
    "A": 667,
    "B": 667,
    "C": 722,
    "D": 722,
    "E": 667,
    "F": 611,
    "G": 778,
    "H": 722,
    "I": 278,
    "J": 556,
    "K": 667,
    "L": 556,
    "M": 833,
    "N": 722,
    "O": 778,
    "P": 667,
    "Q": 778,
    "R": 722,
    "S": 667,
    "T": 611,
    "U": 722,
    "V": 667,
    "W": 944,
    "X": 667,
    "Y": 667,
    "Z": 611,
    "[": 278,
    "\\": 278,
    "]": 278,
    "^": 469,
    "_": 556,
    "`": 333,
    "a": 556,
    "b": 556,
    "c": 500,
    "d": 556,
    "e": 556,
    "f": 278,
    "g": 556,
    "h": 556,
    "i": 222,
    "j": 222,
    "k": 500,
    "l": 222,
    "m": 833,
    "n": 556,
    "o": 556,
    "p": 556,
    "q": 556,
    "r": 333,
    "s": 500,
    "t": 278,
    "u": 556,
    "v": 500,
    "w": 722,
    "x": 500,
    "y": 500,
    "z": 500,
    "{": 334,
    "|": 260,
    "}": 334,
    "~": 584,
}
_TIMES_W = {
    " ": 250,
    "!": 333,
    '"': 408,
    "#": 500,
    "$": 500,
    "%": 833,
    "&": 778,
    "'": 333,
    "(": 333,
    ")": 333,
    "*": 500,
    "+": 570,
    ",": 250,
    "-": 333,
    ".": 250,
    "/": 278,
    "0": 500,
    "1": 500,
    "2": 500,
    "3": 500,
    "4": 500,
    "5": 500,
    "6": 500,
    "7": 500,
    "8": 500,
    "9": 500,
    ":": 278,
    ";": 278,
    "<": 570,
    "=": 570,
    ">": 570,
    "?": 444,
    "@": 921,
    "A": 722,
    "B": 667,
    "C": 667,
    "D": 722,
    "E": 667,
    "F": 667,
    "G": 722,
    "H": 722,
    "I": 333,
    "J": 500,
    "K": 722,
    "L": 611,
    "M": 889,
    "N": 722,
    "O": 722,
    "P": 611,
    "Q": 722,
    "R": 667,
    "S": 556,
    "T": 611,
    "U": 722,
    "V": 722,
    "W": 889,
    "X": 722,
    "Y": 722,
    "Z": 611,
    "[": 333,
    "\\": 278,
    "]": 333,
    "^": 459,
    "_": 500,
    "`": 333,
    "a": 474,
    "b": 500,
    "c": 433,
    "d": 500,
    "e": 444,
    "f": 333,
    "g": 500,
    "h": 500,
    "i": 278,
    "j": 278,
    "k": 500,
    "l": 278,
    "m": 722,
    "n": 500,
    "o": 500,
    "p": 500,
    "q": 500,
    "r": 333,
    "s": 389,
    "t": 278,
    "u": 500,
    "v": 500,
    "w": 722,
    "x": 500,
    "y": 500,
    "z": 444,
    "{": 480,
    "|": 200,
    "}": 480,
    "~": 541,
}
_WIDTH_FALLBACK = 600  # conservative average for characters outside the tables
_SAFETY = 1.08  # PowerPoint may substitute the actual font; keep head room


def _est_text_width_emu(text, font_size_pt, family):
    """Estimated ink width of *text* in EMU (deterministic, conservative)."""
    table = _TIMES_W if "times" in str(family).lower() else _HELVETICA_W
    units = sum(table.get(c, _WIDTH_FALLBACK) for c in text)
    return int(units / 1000 * font_size_pt * 12700 * _SAFETY)


def add_legend(
    slide,
    used_monos,
    font_size,
    font_family,
    slide_bounds,
    content_bottom=None,
    node_size_emu=None,
    *,
    style=None,
    node_line_width_pt=None,
):
    """Add a legend row at the bottom of the slide showing used monosaccharides.

    Args:
        slide_bounds: (slide_left, slide_top, slide_width, slide_height) - full slide dimensions
        content_bottom: Y position (EMU) where main content ends. If None,
            legend placed at slide bottom - 1.5cm
        style: optional Style; the legend is a color key, not structure, so it
            always resolves with the full (non-dimmed) palette.
    """
    if not used_monos:
        return
    st = load_style(style)

    slide_left, slide_top, slide_width, slide_height = slide_bounds

    # Determine the legend position: content bottom + a generous gap (~1cm)
    LEGEND_MARGIN = 360000  # 1cm gap
    LEGEND_HEIGHT = 400000  # legend height ~1cm

    if content_bottom is not None:
        legend_y = content_bottom + LEGEND_MARGIN
        # Make sure it does not exceed the slide bottom
        max_legend_y = slide_top + slide_height - LEGEND_HEIGHT - LEGEND_MARGIN
        legend_y = min(legend_y, max_legend_y)
    else:
        legend_y = slide_top + slide_height - LEGEND_HEIGHT - LEGEND_MARGIN

    # Scale legend icon size to match main diagram node size (no min clamp to ensure consistency)
    MAX_LEGEND_EMU = int(Pt(36))
    if node_size_emu is not None:
        shape_size = Emu(min(node_size_emu, MAX_LEGEND_EMU))
    else:
        shape_size = Pt(15)

    legend_h = shape_size * 2

    # Sort monos for consistent ordering
    sorted_monos = sorted(used_monos)

    # Scale font size proportionally to icon size
    reference_emu = int(Pt(15))
    if node_size_emu is not None:
        scale = min(node_size_emu, MAX_LEGEND_EMU) / reference_emu
        legend_font_size = max(int(font_size * scale), 5)
    else:
        legend_font_size = max(font_size - 2, 5)

    # Scale spacing proportionally to icon size. Label ink was historically
    # never measured (text_w = 4*shape_size, word_wrap off, font scaled up to
    # 2.4x with the icon): long labels can overflow into the next slot.
    # Estimate widths from the static AFM tables and widen the step ONLY when
    # a label does not fit -> the default geometry stays bit-identical.
    text_w = shape_size * 4
    default_step = shape_size * 2 + text_w
    gap = int(shape_size * 0.6)
    need = max(_est_text_width_emu(m, legend_font_size, font_family) for m in sorted_monos)
    avail = default_step - shape_size * 1.4
    wide = need + gap > avail
    step = int(shape_size * 1.4 + need + gap) if wide else default_step
    box_w = max(text_w, need) if wide else text_w
    total_w = len(sorted_monos) * step
    start_x = max(slide_left, (slide_left + slide_width - total_w) // 2)

    x = start_x
    for mono in sorted_monos:
        comp, color_hex = st.resolve(mono)

        # Draw small shape - shape center at legend_y + shape_size (center of the row)
        draw_node(
            slide.shapes,
            x + shape_size,
            legend_y + shape_size,
            shape_size,
            comp,
            color_hex,
            line_hex=st.node_stroke_color,
            line_width_pt=(
                node_line_width_pt if node_line_width_pt is not None else st.node_stroke_width
            ),
        )

        # Draw text label - reduce icon-to-text gap by 30%
        add_text_box(
            slide.shapes,
            x + shape_size * 1.4,
            legend_y,
            box_w,
            legend_h,
            mono,
            Pt(legend_font_size),
            font_family,
            MSO_ANCHOR.MIDDLE,
            2,
        )

        x += step
