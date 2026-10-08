"""python-pptx 后端主编排：模板/占位符管理 + generate_snfg_pptx。"""

import os
from io import BytesIO

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE_TYPE
from pptx.util import Pt

from csdb2snfg.csdb.parser import parse_csdb_linear
from csdb2snfg.snfg.layout import prepare_layout, is_open_node
from csdb2snfg.snfg.geometry import resolve_mono

from csdb2snfg.export.pptx.transform import transform_positions, compute_node_size
from csdb2snfg.export.pptx.primitives import draw_node
from csdb2snfg.export.pptx.text import resolve_font_family
from csdb2snfg.export.pptx.overlays import draw_connectors, draw_edge_labels, draw_repeat_brackets
from csdb2snfg.export.pptx.legend import add_legend


# ─── 模板/占位符/版式策略 ───────────────────────────────────

DEFAULT_SLIDE_W = 9144000  # 25.4cm
DEFAULT_SLIDE_H = 6858000  # 19.1cm


def _find_placeholder(prs):
    """Find the SNFG drawing area on a slide layout.

    Strategy:
    1. Look for a shape named 'SNFG_Placeholder'
    2. Fall back to '内容占位符' (content placeholder)
    3. Fall back to 80% centered area of the slide
    """
    for layout in prs.slide_layouts:
        for shape in layout.shapes:
            if shape.name == 'SNFG_Placeholder':
                return shape.left, shape.top, shape.width, shape.height
            # Match common Chinese content placeholder names
            if '内容' in shape.name and shape.shape_type == MSO_SHAPE_TYPE.PLACEHOLDER:
                return shape.left, shape.top, shape.width, shape.height
    # Fallback: 80% of slide centered
    slide_w = prs.slide_width
    slide_h = prs.slide_height
    w = int(slide_w * 0.8)
    h = int(slide_h * 0.8)
    left = (slide_w - w) // 2
    top = (slide_h - h) // 2
    return left, top, w, h


def get_content_layout(prs):
    """Get the best slide layout for SNFG diagrams.

    Prefer '标题和内容' or '空白' layout.
    """
    for layout in prs.slide_layouts:
        if '内容' in layout.name or '内容占位符' in layout.name:
            return layout
    # Fallback to blank
    for layout in prs.slide_layouts:
        if '空白' in layout.name:
            return layout
    # Last fallback: first layout
    return prs.slide_layouts[0]


def delete_placeholder_shapes(slide, prs):
    """Delete default placeholder shapes from a new slide so they don't overlap SNFG."""
    shapes_to_delete = []
    bottom_threshold = int(prs.slide_height * 0.85)
    for shape in slide.shapes:
        if shape.is_placeholder:
            # Keep only footer/date placeholders at the very bottom
            if hasattr(shape, 'top') and shape.top > bottom_threshold:
                continue
            shapes_to_delete.append(shape)

    for shape in shapes_to_delete:
        sp = shape._element
        sp.getparent().remove(sp)


def get_effective_bounds(template_path, ph_bounds, slide_w, slide_h):
    """计算实际绘图区域：如果使用模板，保持占位符比例；否则使用幻灯片的 80% 中心区域。"""
    ph_left, ph_top, ph_width, ph_height = ph_bounds
    if template_path and os.path.exists(template_path):
        # 保持占位符相对位置
        rel_left = ph_left / DEFAULT_SLIDE_W
        rel_top = ph_top / DEFAULT_SLIDE_H
        rel_w = ph_width / DEFAULT_SLIDE_W
        rel_h = ph_height / DEFAULT_SLIDE_H
        return (int(slide_w * rel_left), int(slide_h * rel_top),
                int(slide_w * rel_w), int(slide_h * rel_h))
    else:
        # 无模板时使用 80% 中心区域
        w = int(slide_w * 0.8)
        h = int(slide_h * 0.8)
        return ((slide_w - w) // 2, (slide_h - h) // 2, w, h)


def _add_error_slide(prs, layout, errors, resolved_font):
    """Add errors slide if any failures."""
    slide = prs.slides.add_slide(layout)
    delete_placeholder_shapes(slide, prs)
    sw = prs.slide_width or 9144000  # default 10 inches in EMU
    sh = prs.slide_height or 6858000  # default 7.5 inches in EMU
    tb = slide.shapes.add_textbox(
        int(sw * 0.1),
        int(sh * 0.1),
        int(sw * 0.8),
        int(sh * 0.8)
    )
    tf = tb.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.text = "Export Errors"
    p.font.size = Pt(18)
    p.font.color.rgb = RGBColor(204, 0, 0)
    p.font.bold = True
    p.font.name = resolved_font

    for err in errors:
        p = tf.add_paragraph()
        p.text = err
        p.font.size = Pt(10)
        p.font.name = resolved_font
        p.space_before = Pt(6)


def generate_snfg_pptx(csdb_list, template_path=None, ratio=1, font_size=8,
                        font_family="sans-serif", compact_repeat=True):
    """Generate a PPTX file with one SNFG diagram per slide.

    Args:
        csdb_list: List of CSDB notation strings
        template_path: Path to .pptx/.potx template file, or None for blank
        ratio: Branch scaling ratio
        font_size: Font size for labels
        font_family: Font family name for labels and legend text
        compact_repeat: Show repeat units as [unit]ₙ instead of expanding

    Returns:
        BytesIO containing the PPTX file
    """
    if template_path and os.path.exists(template_path):
        prs = Presentation(template_path)
    else:
        prs = Presentation()

    # Detect placeholder from first slide layout
    ph_bounds = _find_placeholder(prs)
    ph_left, ph_top, ph_width, ph_height = ph_bounds

    layout = get_content_layout(prs)

    resolved_font = resolve_font_family(font_family)

    errors = []

    # 第一遍：计算每个结构的位置和所需尺寸
    items = []
    default_bounds = get_effective_bounds(template_path, ph_bounds,
                                          DEFAULT_SLIDE_W, DEFAULT_SLIDE_H)
    for idx, csdb in enumerate(csdb_list):
        csdb = csdb.strip()
        if not csdb:
            errors.append(f"[{idx + 1}] EMPTY CSDB")
            continue
        try:
            tree = parse_csdb_linear(csdb)
            _, pos, edges, labels, repeat_groups = prepare_layout(tree, ratio=ratio,
                                                                  compact_repeat=compact_repeat)
            positions_emu, (needed_w, needed_h), scale, _tf = transform_positions(pos, default_bounds)
            items.append((csdb, pos, edges, labels, needed_w, needed_h, scale, repeat_groups))
        except Exception as e:
            errors.append(f"[{idx + 1}] {csdb}\n  ERROR: {e}")
            items.append(None)

    # 设置幻灯片尺寸：取所有结构所需的最大值，但至少为默认尺寸
    max_needed_w = max((it[4] for it in items if it), default=DEFAULT_SLIDE_W)
    max_needed_h = max((it[5] for it in items if it), default=DEFAULT_SLIDE_H)
    if max_needed_w > DEFAULT_SLIDE_W or max_needed_h > DEFAULT_SLIDE_H:
        prs.slide_width = int(max_needed_w + 500000)
        prs.slide_height = int(max(max_needed_h + 500000, DEFAULT_SLIDE_H))

    # 第二遍：绘制每个结构，如果幻灯片扩大了则重新居中
    for item in items:
        if item is None:
            continue
        csdb, pos, edges, labels, needed_w, needed_h, scale, repeat_groups = item

        # 使用当前幻灯片尺寸计算实际绘图区域
        actual_bounds = get_effective_bounds(template_path, ph_bounds,
                                             prs.slide_width, prs.slide_height)
        positions_emu, _, _, _ = transform_positions(pos, actual_bounds, fixed_scale=scale)

        # Add new slide
        slide = prs.slides.add_slide(layout)

        # Remove placeholder shapes that would overlap
        delete_placeholder_shapes(slide, prs)

        size_emu = compute_node_size(positions_emu, labels)

        # Draw edges first (behind shapes)
        draw_connectors(slide.shapes, edges, positions_emu)

        # Draw nodes (on top of connectors)
        used_monos = set()
        for node_id, (x_emu, y_emu) in positions_emu.items():
            if is_open_node(node_id):
                continue
            mono = labels[node_id]
            used_monos.add(mono)
            comp, color_hex = resolve_mono(mono)
            draw_node(slide.shapes, x_emu, y_emu, size_emu, comp, color_hex)

        # Draw repeat brackets (on top of nodes)
        if repeat_groups:
            draw_repeat_brackets(slide.shapes, repeat_groups, positions_emu,
                                 size_emu, font_size, resolved_font)

        # Draw legend (shapes) before labels so labels stay on top
        if used_monos:
            ys = [y_emu for node_id, (x_emu, y_emu) in positions_emu.items()
                  if not is_open_node(node_id)]
            content_bottom = max(ys) + size_emu if ys else None
            slide_bounds = (0, 0, prs.slide_width, prs.slide_height)
            add_legend(slide, used_monos, font_size, resolved_font, slide_bounds,
                       content_bottom=content_bottom, node_size_emu=size_emu)

        # Draw labels last (on top of shapes and connectors)
        draw_edge_labels(slide.shapes, edges, positions_emu, font_size,
                         resolved_font, node_size=size_emu,
                         repeat_groups=repeat_groups, size_emu=size_emu)

    # Add errors slide if any failures
    if errors:
        _add_error_slide(prs, layout, errors, resolved_font)

    buf = BytesIO()
    prs.save(buf)
    buf.seek(0)
    return buf
