"""PPTX export for SNFG diagrams using python-pptx vector shapes."""

import os
from io import BytesIO

from pptx import Presentation
from pptx.util import Emu, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE_TYPE, MSO_CONNECTOR

from csdb2snfg.parser import parse_csdb_linear
from csdb2snfg.renderer import (
    glycan_color,
    glycan_dict,
    expand_repeat,
    layout_tree,
    get_shape_coords,
    MODIFIERS,
)



def _resolve_font_family(font_family):
    """Map generic font family names to concrete font names."""
    mapping = {
        'serif': 'Times New Roman',
        'sans-serif': 'Arial',
        'monospace': 'Courier New',
    }
    return mapping.get(font_family.lower(), font_family)


def _hex_to_rgb(hex_color):
    """Convert #RRGGBB or #RRGGBBAA hex string to (R, G, B) tuple."""
    h = hex_color.lstrip('#')
    if len(h) == 8:
        h = h[:6]  # strip alpha
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))


def _set_shape_fill_color(shape, hex_color):
    """Set solid fill color on a pptx shape."""
    fill = shape.fill
    fill.solid()
    fill.fore_color.rgb = RGBColor(*_hex_to_rgb(hex_color))


def _set_shape_line_color(shape, hex_color='000000', width_pt=0.25):
    """Set line color and width on a pptx shape."""
    line = shape.line
    line.color.rgb = RGBColor(*_hex_to_rgb(f'#{hex_color}'))
    line.width = Pt(width_pt)


def _remove_shape_style(shape):
    """Remove <p:style> element to eliminate theme-based shadow effects."""
    sp = shape._element
    style_el = sp.find('p:style', {'p': 'http://schemas.openxmlformats.org/presentationml/2006/main'})
    if style_el is not None:
        sp.remove(style_el)


def find_placeholder(prs):
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


def _transform_positions(positions, ph_bounds, fixed_scale=None, cap_offset_y=False):
    """Map layout_tree abstract coords to PPT EMU coords within placeholder.

    Y axis is flipped (matplotlib up -> PPT down).

    Args:
        fixed_scale: If provided, use this scale instead of calculating (for re-centering).
        cap_offset_y: If True, limit offset_y to 0 (don't push content down further).

    Returns:
        tuple: (positions_emu dict, needed_bounds tuple, scale float)
        needed_bounds = (needed_width, needed_height) in EMU, may exceed ph_bounds
    """
    ph_left, ph_top, ph_width, ph_height = ph_bounds
    PADDING_EMU = 360000  # 1cm fixed padding

    xs = [x for x, y in positions.values()]
    ys = [y for x, y in positions.values()]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)

    data_w = max_x - min_x if max_x != min_x else 1
    data_h = max_y - min_y if max_y != min_y else 1

    avail_w = ph_width - 2 * PADDING_EMU
    avail_h = ph_height - 2 * PADDING_EMU

    if fixed_scale is not None:
        scale = fixed_scale
    else:
        MAX_SCALE = 450000
        MIN_SCALE = 360000
        base_scale = min(avail_w / data_w, avail_h / data_h)
        scale = max(min(base_scale, MAX_SCALE), MIN_SCALE)

    drawn_w = data_w * scale
    drawn_h = data_h * scale

    EXTRA_MARGIN = 900000
    needed_w = int(drawn_w + 2 * PADDING_EMU + EXTRA_MARGIN)
    needed_h = int(drawn_h + 2 * PADDING_EMU + EXTRA_MARGIN)

    # 居中时包含图例空间，使节点+图例整体居中
    offset_x = (avail_w - drawn_w) / 2
    offset_y = (avail_h - drawn_h - EXTRA_MARGIN) / 2
    if cap_offset_y:
        offset_y = min(offset_y, 0)

    result = {}
    for node_id, (x, y) in positions.items():
        emu_x = ph_left + PADDING_EMU + (x - min_x) * scale + offset_x
        emu_y = ph_top + PADDING_EMU + (max_y - y) * scale + offset_y
        result[node_id] = (emu_x, emu_y)

    return result, (needed_w, needed_h), scale


def _compute_node_size(positions_emu, labels=None):
    """Compute node radius based on minimum inter-node distance, excluding modifiers.

    Max shape size is capped at 1cm (diameter) = 180,000 EMU (radius).
    Min shape size is 0.25cm (diameter) = 90,000 EMU (radius) as fallback.
    """
    MAX_NODE_SIZE_EMU = 180000  # 0.5cm radius = 1cm diameter max
    MIN_NODE_SIZE_EMU = 90000   # 0.25cm radius = 0.5cm diameter min
    real_ids = [k for k in positions_emu if k not in ('OPEN_HEAD', 'OPEN_TAIL')]
    if labels is not None:
        real_ids = [k for k in real_ids if labels.get(k) not in MODIFIERS]
    if len(real_ids) < 2:
        return int(min(200000, MAX_NODE_SIZE_EMU))  # default, capped

    min_dist = float('inf')
    for i in range(len(real_ids)):
        for j in range(i + 1, len(real_ids)):
            x1, y1 = positions_emu[real_ids[i]]
            x2, y2 = positions_emu[real_ids[j]]
            dist = ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5
            # 跳过完全重叠的节点（layout_tree 的 bug）
            if dist > 0 and dist < min_dist:
                min_dist = dist

    # 如果所有节点都重叠，使用最小尺寸
    if min_dist == float('inf'):
        return MIN_NODE_SIZE_EMU

    return int(min(min_dist * 0.36, MAX_NODE_SIZE_EMU))


def _add_freeform_shape(shapes, vertices, fill_color_hex, remove_style=True):
    """Create a freeform shape from a list of (x, y) EMU vertices."""
    freeform = shapes.build_freeform(vertices[0][0], vertices[0][1])
    freeform.add_line_segments(vertices[1:], close=True)
    shape = freeform.convert_to_shape()
    _set_shape_fill_color(shape, fill_color_hex)
    _set_shape_line_color(shape)
    if remove_style:
        _remove_shape_style(shape)
    return shape


def _draw_snfg_node(shapes, x_emu, y_emu, size_emu, comp, color_hex):
    """Draw a single SNFG node (possibly composed of multiple shapes for divided types)."""
    xs, ys = get_shape_coords(comp, size=1.0)

    # PPT y-axis goes down, matplotlib y-axis goes up.
    # Flip y for shapes so they render with correct orientation in PPT.
    def ppt_coords():
        return [(int(x_emu + vx * size_emu), int(y_emu - vy * size_emu)) for vx, vy in zip(xs, ys)]

    def to_vertices():
        return ppt_coords()

    if comp == 'DDiamond':
        # Diamond: vertices [top, right, bottom, left]
        # Colored half: left->top->right, White half: left->bottom->right
        v_all = ppt_coords()
        _add_freeform_shape(shapes, [v_all[3], v_all[0], v_all[1]], color_hex)
        _add_freeform_shape(shapes, [v_all[3], v_all[2], v_all[1]], '#FFFFFF')
    elif comp == 'CSquare':
        # Square: vertices [top-left, top-right, bottom-right, bottom-left]
        # Colored half: center -> top-right -> bottom-right, White: center -> bottom-left -> top-left
        v_all = ppt_coords()
        center = (int(x_emu), int(y_emu))
        _add_freeform_shape(shapes, [center, v_all[1], v_all[2]], color_hex)
        _add_freeform_shape(shapes, [center, v_all[3], v_all[0]], '#FFFFFF')
    elif comp == 'DTriangle':
        # Triangle: vertices [top, bottom-left, bottom-right]
        # Colored half: top->bottom-right->bottom-left (right half)
        v_all = ppt_coords()
        _add_freeform_shape(shapes, [v_all[0], v_all[2], v_all[1]], color_hex)
    elif comp == 'FTriangle':
        # Flip y so triangle points up in PPT (y-down coordinate system)
        xs_flipped, ys_flipped = xs, [-y for y in ys]
        v_flip = [(int(x_emu + vx * size_emu), int(y_emu + vy * size_emu)) for vx, vy in zip(xs_flipped, ys_flipped)]
        _add_freeform_shape(shapes, v_flip, color_hex)
    else:
        vertices = to_vertices()
        _add_freeform_shape(shapes, vertices, color_hex)


def _draw_edges_and_labels(shapes, edges, positions_emu, labels, font_size, font_family="sans-serif", draw_connectors_only=False, node_size=None):
    """
    绘制连接线和糖链键位标签。
    使用中心对齐逻辑复刻 Matplotlib 的布局效果。
    """
    if draw_connectors_only:
        for parent_id, child_id, label_str in edges:
            if parent_id not in positions_emu or child_id not in positions_emu:
                continue
            x1, y1 = positions_emu[parent_id]
            x2, y2 = positions_emu[child_id]
            connector = shapes.add_connector(
                MSO_CONNECTOR.STRAIGHT,
                int(x1), int(y1), int(x2), int(y2)
            )
            line = connector.line
            line.color.rgb = RGBColor(0, 0, 0)
            line.width = Pt(1)
            _remove_shape_style(connector)
        return

    # --- 标签绘制逻辑 (复刻 Matplotlib) ---
    
    # 预定义文本框尺寸 (40万 EMU 约等于 1.1cm，足够容纳数字)
    box_w = Emu(400000)
    box_h = Emu(250000)
    
    # 映射 Matplotlib 中的 0.1 常数偏移
    # 在 PPT 中，y 轴减小是向上偏移（远离线条）
    offset_const = int(node_size * 0.4) if node_size else Emu(40000)

    for parent_id, child_id, label_str in edges:
        if parent_id not in positions_emu or child_id not in positions_emu:
            continue
        
        x1, y1 = positions_emu[parent_id]
        x2, y2 = positions_emu[child_id]

        if not label_str:
            continue

        # 解析连接符号，例如 "4-1" -> left="4", right="1"
        parts = label_str.split('-')
        left_text = parts[0] if len(parts) > 0 else ''
        right_text = parts[1] if len(parts) > 1 else ''

        dx_line = x2 - x1
        dy_line = y2 - y1

        # 完全复刻你提供的逻辑判断
        if dy_line == 0:
            # 水平线：标签在上方，沿 X 轴分布
            x_l = x1 + dx_line / 2 - dx_line / 10
            x_r = x2 - dx_line / 2 + dx_line / 10
            y_l = y1 - offset_const  # PPT 中 y 减小为向上
            y_r = y1 - offset_const
        else:
            # 非水平线（垂直或倾斜）：标签在右侧，沿 Y 轴分布
            x_l = x2 + offset_const
            x_r = x2 + offset_const
            y_l = y1 + dy_line / 2 + dy_line / 10
            y_r = y2 - dy_line / 2 - dy_line / 10

        # 内部辅助函数：确保文本框的“中心点”对准 (tx, ty)
        def add_centered_label(tx, ty, text):
            if not text.strip():
                return
            
            # 计算左上角坐标，使中心对齐
            left = int(tx - box_w / 2)
            top = int(ty - box_h / 2)
            
            tb = shapes.add_textbox(left, top, box_w, box_h)
            tf = tb.text_frame
            
            # 关键设置：消除内边距以实现物理居中
            tf.margin_top = tf.margin_bottom = tf.margin_left = tf.margin_right = 0
            tf.word_wrap = False
            tf.vertical_anchor = MSO_ANCHOR.MIDDLE  # 框内垂直居中
            
            p = tf.paragraphs[0]
            p.text = text
            p.font.size = Pt(max(font_size - 1, 6))
            p.font.color.rgb = RGBColor(0, 0, 0)
            p.font.name = font_family
            p.alignment = 2  # 框内水平居中 (Center)

        # 绘制左右（或父子）标签
        if left_text:
            add_centered_label(x_l, y_l, left_text)
        if right_text:
            add_centered_label(x_r, y_r, right_text)

def _add_legend(slide, used_monos, font_size, font_family, slide_bounds, content_bottom=None, node_size_emu=None):
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
    mono_w = shape_size * 2.5
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
        comp, color_name = glycan_dict.get(mono, ('FCircle', 'White'))
        color_hex = glycan_color.get(color_name, '#FFFFFF')

        # Draw small shape - shape center at legend_y + shape_size (center of the row)
        _draw_snfg_node(slide.shapes, x + shape_size, legend_y + shape_size, shape_size, comp, color_hex)

        # Draw text label - reduce icon-to-text gap by 30%
        tb = slide.shapes.add_textbox(x + shape_size * 1.4, legend_y, text_w, legend_h)
        tf = tb.text_frame
        tf.margin_top = tf.margin_bottom = tf.margin_left = tf.margin_right = 0
        tf.word_wrap = False
        tf.vertical_anchor = MSO_ANCHOR.MIDDLE
        p = tf.paragraphs[0]
        p.text = mono
        p.font.size = Pt(legend_font_size)
        p.font.color.rgb = RGBColor(0, 0, 0)
        p.font.name = font_family
        p.alignment = 2  # 框内水平居中 (Center)

        x += shape_size * 2 + text_w


def _get_content_layout(prs):
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


def _delete_placeholder_shapes(slide, prs):
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


def generate_snfg_pptx(csdb_list, template_path=None, ratio=1, font_size=8, font_family="sans-serif"):
    """Generate a PPTX file with one SNFG diagram per slide.

    Args:
        csdb_list: List of CSDB notation strings
        template_path: Path to .pptx/.potx template file, or None for blank
        ratio: Branch scaling ratio
        font_size: Font size for labels
        font_family: Font family name for labels and legend text

    Returns:
        BytesIO containing the PPTX file
    """
    if template_path and os.path.exists(template_path):
        prs = Presentation(template_path)
    else:
        prs = Presentation()

    # Detect placeholder from first slide layout
    ph_left, ph_top, ph_width, ph_height = find_placeholder(prs)

    layout = _get_content_layout(prs)

    resolved_font = _resolve_font_family(font_family)

    errors = []

    DEFAULT_SLIDE_W = 9144000  # 25.4cm
    DEFAULT_SLIDE_H = 6858000  # 19.1cm

    # 计算���际绘图区域：如果使用模板，保持占位符比例；否则使用幻灯片的 80% 中心区域
    def get_effective_bounds(slide_w, slide_h):
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

    # 第一遍：计算每个结构的位置和所需尺寸
    items = []
    default_bounds = get_effective_bounds(DEFAULT_SLIDE_W, DEFAULT_SLIDE_H)
    for idx, csdb in enumerate(csdb_list):
        csdb = csdb.strip()
        if not csdb:
            errors.append(f"[{idx + 1}] EMPTY CSDB")
            continue
        try:
            tree = parse_csdb_linear(csdb)
            _, pos, edges, labels = layout_tree(
                expand_repeat(tree.to_dict()), ratio=ratio
            )
            positions_emu, (needed_w, needed_h), scale = _transform_positions(pos, default_bounds)
            items.append((csdb, pos, edges, labels, needed_w, needed_h, scale))
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
        csdb, pos, edges, labels, needed_w, needed_h, scale = item

        # 使用当前幻灯片尺寸计算实际绘图区域
        actual_bounds = get_effective_bounds(prs.slide_width, prs.slide_height)
        positions_emu, _, _ = _transform_positions(pos, actual_bounds, fixed_scale=scale)

        # Add new slide
        slide = prs.slides.add_slide(layout)

        # Remove placeholder shapes that would overlap
        _delete_placeholder_shapes(slide, prs)

        size_emu = _compute_node_size(positions_emu, labels)

        # Draw edges first (behind shapes)
        _draw_edges_and_labels(slide.shapes, edges, positions_emu, labels, font_size, resolved_font, draw_connectors_only=True, node_size=size_emu)

        # Draw nodes (on top of connectors)
        used_monos = set()
        for node_id, (x_emu, y_emu) in positions_emu.items():
            if node_id in ("OPEN_HEAD", "OPEN_TAIL"):
                continue
            mono = labels[node_id]
            used_monos.add(mono)
            comp, color_name = glycan_dict.get(mono, ('FCircle', 'White'))
            color_hex = glycan_color.get(color_name, '#FFFFFF')
            _draw_snfg_node(slide.shapes, x_emu, y_emu, size_emu, comp, color_hex)

        # Draw legend (shapes) before labels so labels stay on top
        if used_monos:
            ys = [y_emu for node_id, (x_emu, y_emu) in positions_emu.items()
                  if node_id not in ("OPEN_HEAD", "OPEN_TAIL")]
            content_bottom = max(ys) + size_emu if ys else None
            slide_bounds = (0, 0, prs.slide_width, prs.slide_height)
            _add_legend(slide, used_monos, font_size, resolved_font, slide_bounds,
                        content_bottom=content_bottom, node_size_emu=size_emu)

        # Draw labels last (on top of shapes and connectors)
        _draw_edges_and_labels(slide.shapes, edges, positions_emu, labels, font_size, resolved_font, draw_connectors_only=False, node_size=size_emu)

    # Add errors slide if any failures
    if errors:
        slide = prs.slides.add_slide(layout)
        _delete_placeholder_shapes(slide, prs)
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

    buf = BytesIO()
    prs.save(buf)
    buf.seek(0)
    return buf
