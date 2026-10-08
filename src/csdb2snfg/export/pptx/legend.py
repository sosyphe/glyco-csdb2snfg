"""python-pptx 后端的图例行。"""

from pptx.enum.text import MSO_ANCHOR
from pptx.util import Emu, Pt

from csdb2snfg.snfg.geometry import resolve_mono

from csdb2snfg.export.pptx.primitives import draw_node
from csdb2snfg.export.pptx.text import add_text_box


def add_legend(slide, used_monos, font_size, font_family, slide_bounds,
               content_bottom=None, node_size_emu=None):
    """Add a legend row at the bottom of the slide showing used monosaccharides.

    Args:
        slide_bounds: (slide_left, slide_top, slide_width, slide_height) - full slide dimensions
        content_bottom: Y position (EMU) where main content ends. If None, legend placed at slide bottom - 1.5cm
    """
    if not used_monos:
        return

    slide_left, slide_top, slide_width, slide_height = slide_bounds

    # 确定图例位置：内容底部 + 较大间距（约1cm）
    LEGEND_MARGIN = 360000  # 1cm 间距
    LEGEND_HEIGHT = 400000  # 图例高度约 1cm

    if content_bottom is not None:
        legend_y = content_bottom + LEGEND_MARGIN
        # 确保不超出幻灯片底部
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

    # Scale spacing proportionally to icon size
    text_w = shape_size * 4
    total_w = len(sorted_monos) * (shape_size * 2 + text_w)
    start_x = max(slide_left, (slide_left + slide_width - total_w) // 2)

    # Scale font size proportionally to icon size
    reference_emu = int(Pt(15))
    if node_size_emu is not None:
        scale = min(node_size_emu, MAX_LEGEND_EMU) / reference_emu
        legend_font_size = max(int(font_size * scale), 5)
    else:
        legend_font_size = max(font_size - 2, 5)

    x = start_x
    for mono in sorted_monos:
        comp, color_hex = resolve_mono(mono)

        # Draw small shape - shape center at legend_y + shape_size (center of the row)
        draw_node(slide.shapes, x + shape_size, legend_y + shape_size, shape_size, comp, color_hex)

        # Draw text label - reduce icon-to-text gap by 30%
        add_text_box(slide.shapes, x + shape_size * 1.4, legend_y, text_w, legend_h,
                     mono, Pt(legend_font_size), font_family, MSO_ANCHOR.MIDDLE, 2)

        x += shape_size * 2 + text_w
