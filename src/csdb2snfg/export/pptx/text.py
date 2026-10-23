"""Font mapping and the shared textbox primitive (edge labels/subscripts/legend)."""

from pptx.dml.color import RGBColor
from pptx.enum.text import MSO_ANCHOR
from pptx.util import Emu, Pt

from csdb2snfg.export.pptx.primitives import hex_to_rgb

# Predefined textbox size (400,000 EMU is about 1.1cm, enough to hold digits)
LABEL_BOX_W = Emu(400000)
LABEL_BOX_H = Emu(250000)


def resolve_font_family(font_family):
    """Map generic font family names to concrete font names."""
    mapping = {
        "serif": "Times New Roman",
        "sans-serif": "Arial",
        "monospace": "Courier New",
    }
    return mapping.get(font_family.lower(), font_family)


def add_text_box(
    shapes,
    left,
    top,
    width,
    height,
    text,
    font_size_pt,
    font_family,
    anchor,
    alignment,
    *,
    text_hex=None,
):
    """Add a textbox at (left, top) and style it.

    The property assignment order is fixed as margins -> wrap -> anchor ->
    text -> size -> color -> name -> alignment: python-pptx's XML element
    order is sensitive to it; changing the order shifts bytes. Only the VALUE
    of the color may be parameterized (text_hex); its position in the
    sequence must never move.
    """
    tb = shapes.add_textbox(left, top, width, height)
    tf = tb.text_frame

    # Key setting: zero inner margins for physical centering
    tf.margin_top = tf.margin_bottom = tf.margin_left = tf.margin_right = 0
    tf.word_wrap = False
    tf.vertical_anchor = anchor

    p = tf.paragraphs[0]
    p.text = text
    p.font.size = font_size_pt
    p.font.color.rgb = RGBColor(0, 0, 0) if text_hex is None else RGBColor(*hex_to_rgb(text_hex))
    p.font.name = font_family
    p.alignment = alignment
    return tb


def add_centered_label(shapes, tx, ty, text, font_size, font_family, *, text_hex=None):
    """Make the textbox's center point land exactly on (tx, ty)."""
    if not text.strip():
        return

    # Compute the top-left corner so the center aligns
    left = int(tx - LABEL_BOX_W / 2)
    top = int(ty - LABEL_BOX_H / 2)

    add_text_box(
        shapes,
        left,
        top,
        LABEL_BOX_W,
        LABEL_BOX_H,
        text,
        Pt(max(font_size - 1, 6)),
        font_family,
        MSO_ANCHOR.MIDDLE,
        2,  # 2 = horizontally centered in box (Center)
        text_hex=text_hex,
    )
