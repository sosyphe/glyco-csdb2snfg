"""python-pptx 后端的视觉标注层：连接线 + 重复单元括号。"""

from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR
from pptx.util import Emu, Pt

from csdb2snfg.snfg.layout import parse_edge_label
from csdb2snfg.snfg.geometry import (
    LABEL_PERP_RATIO,
    bracket_bounds,
    bracket_geometry,
    edge_label_slots,
)

from csdb2snfg.export.pptx.primitives import (
    remove_shape_style,
    set_shape_fill_color,
    set_shape_line_color,
)
from csdb2snfg.export.pptx.text import LABEL_BOX_W, LABEL_BOX_H, add_text_box, add_centered_label


# ─── 连接线 ──────────────────────────────────────────────────


def draw_connectors(shapes, edges, positions_emu):
    """只画直线 connector（z 序底层）。"""
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
        remove_shape_style(connector)


def draw_edge_labels(shapes, edges, positions_emu, font_size,
                     font_family="sans-serif", node_size=None,
                     repeat_groups=None, size_emu=None):
    """
    绘制糖链键位标签（z 序顶层）。
    使用中心对齐逻辑复刻 Matplotlib 的布局效果。
    """
    # 标签紧贴连线的垂直偏移（与 image 后端同一比例）
    offset_const = int(node_size * LABEL_PERP_RATIO) if node_size else Emu(20000)

    # 构建括号边界信息（EMU 坐标，用于跨括号边的标签避让）
    bounds = ()
    if repeat_groups and size_emu:
        bounds = bracket_bounds(repeat_groups, pad=int(size_emu * 1.5),
                                positions=positions_emu)

    avoid_margin = int(size_emu * 0.3) if size_emu else 50000

    for parent_id, child_id, label_str in edges:
        if parent_id not in positions_emu or child_id not in positions_emu:
            continue

        x1, y1 = positions_emu[parent_id]
        x2, y2 = positions_emu[child_id]

        if not label_str:
            continue

        # 解析连接符号，例如 "4-1" -> left="4", right="1"
        left_text, right_text = parse_edge_label(label_str)

        x_l, y_l, x_r, y_r = edge_label_slots(
            parent_id, child_id, (x1, y1), (x2, y2),
            perp=offset_const,
            y_up=False,
            along_mode='frac',
            bounds=bounds,
            avoid_margin=avoid_margin,
            avoid_floor=True,
        )

        # 绘制左右（或父子）标签
        if left_text:
            add_centered_label(shapes, x_l, y_l, left_text, font_size, font_family)
        if right_text:
            add_centered_label(shapes, x_r, y_r, right_text, font_size, font_family)


# ─── 重复单元括号 ────────────────────────────────────────────

LINE_THICKNESS = Emu(6350)  # 0.5pt 粗细


def _add_bar(shapes, left, top, width, height):
    bar = shapes.add_shape(MSO_SHAPE.RECTANGLE, left, top, width, height)
    set_shape_fill_color(bar, '#000000')
    set_shape_line_color(bar, '000000', 0.25)
    remove_shape_style(bar)
    return bar


def draw_repeat_brackets(shapes, repeat_groups, positions_emu, size_emu,
                         font_size, font_family="Arial"):
    """Draw brackets and subscript count labels for compact repeat groups in PPTX."""
    for rg in repeat_groups:
        count = rg['count']

        # 从 node_ids 计算每组的 EMU 边界框
        group_ids = rg.get('node_ids', [])
        group_positions = [positions_emu[nid]
                           for nid in group_ids
                           if nid in positions_emu]
        if not group_positions:
            continue

        group_xs = [x for x, y in group_positions]
        group_ys = [y for x, y in group_positions]

        # 括号几何与 image 后端共享；EMU y-down，数值小者为上
        geom = bracket_geometry(min(group_xs), min(group_ys),
                                max(group_xs), max(group_ys), size_emu)
        left_x = geom.left_x
        right_x = geom.right_x
        y_top = geom.y_bot  # PPT 中 y 小 = 上
        y_bot = geom.y_top  # PPT 中 y 大 = 下
        cap = int(geom.cap)  # 括号横线长度

        # 左括号 [ (三条线段：上横、左竖、下横)
        _add_bar(shapes, left_x, y_top, cap, LINE_THICKNESS)          # 上横线
        _add_bar(shapes, left_x, y_top, LINE_THICKNESS, y_bot - y_top)  # 左竖线
        _add_bar(shapes, left_x, y_bot, cap, LINE_THICKNESS)           # 下横线

        # 右括号 ]
        _add_bar(shapes, right_x - cap, y_top, cap, LINE_THICKNESS)    # 上横线
        _add_bar(shapes, right_x, y_top, LINE_THICKNESS, y_bot - y_top)  # 右竖线
        _add_bar(shapes, right_x - cap, y_bot, cap, LINE_THICKNESS)    # 下横线

        # 下标文字：普通字符，字体族/字号与连线 label 一致（与 image 后端同步）
        add_text_box(shapes, right_x + cap // 2, y_bot, LABEL_BOX_W, LABEL_BOX_H,
                     str(count), Pt(max(font_size - 1, 6)), font_family,
                     MSO_ANCHOR.TOP, 1)  # 1 = Left
