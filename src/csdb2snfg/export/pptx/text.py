"""字体映射与通用文本框（边标签/下标/图例共用）。"""

from pptx.dml.color import RGBColor
from pptx.enum.text import MSO_ANCHOR
from pptx.util import Emu, Pt

# 预定义文本框尺寸 (40万 EMU 约等于 1.1cm，足够容纳数字)
LABEL_BOX_W = Emu(400000)
LABEL_BOX_H = Emu(250000)


def resolve_font_family(font_family):
    """Map generic font family names to concrete font names."""
    mapping = {
        'serif': 'Times New Roman',
        'sans-serif': 'Arial',
        'monospace': 'Courier New',
    }
    return mapping.get(font_family.lower(), font_family)


def add_text_box(shapes, left, top, width, height, text, font_size_pt,
                 font_family, anchor, alignment):
    """在 (left, top) 添加文本框并排版。

    属性设置顺序固定为 margins→wrap→anchor→text→size→color→name→
    alignment：python-pptx 的 XML 元素序对此敏感，改动会漂字节。
    """
    tb = shapes.add_textbox(left, top, width, height)
    tf = tb.text_frame

    # 关键设置：消除内边距以实现物理居中
    tf.margin_top = tf.margin_bottom = tf.margin_left = tf.margin_right = 0
    tf.word_wrap = False
    tf.vertical_anchor = anchor

    p = tf.paragraphs[0]
    p.text = text
    p.font.size = font_size_pt
    p.font.color.rgb = RGBColor(0, 0, 0)
    p.font.name = font_family
    p.alignment = alignment
    return tb


def add_centered_label(shapes, tx, ty, text, font_size, font_family):
    """确保文本框的"中心点"对准 (tx, ty)。"""
    if not text.strip():
        return

    # 计算左上角坐标，使中心对齐
    left = int(tx - LABEL_BOX_W / 2)
    top = int(ty - LABEL_BOX_H / 2)

    add_text_box(shapes, left, top, LABEL_BOX_W, LABEL_BOX_H, text,
                 Pt(max(font_size - 1, 6)), font_family,
                 MSO_ANCHOR.MIDDLE, 2)  # 2 = 框内水平居中 (Center)
