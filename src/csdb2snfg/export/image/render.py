"""matplotlib 后端主渲染：编排器 + 形状/括号/图形辅助函数。"""

import matplotlib.pyplot as plt

from csdb2snfg.snfg.layout import prepare_layout, parse_edge_label, is_open_node
from csdb2snfg.snfg.geometry import (
    LABEL_PERP_RATIO,
    bracket_geometry,
    bracket_pad,
    bracket_bounds,
    edge_label_slots,
    resolve_mono,
    shape_vcenter_offset,
)

from csdb2snfg.export.image.shapes import draw_shape
from csdb2snfg.export.image.legend import add_snfg_legend


# ─── 括号绘制 ────────────────────────────────────────────────


def draw_repeat_brackets(ax, repeat_groups, mono_size, font_size):
    """Draw brackets and subscript count labels for compact repeat groups."""
    for rg in repeat_groups:
        x_min, y_min, x_max, y_max = rg['bbox']
        count = rg['count']
        geom = bracket_geometry(x_min, y_min, x_max, y_max, mono_size)

        # 左括号 [
        ax.plot([geom.left_x + geom.cap, geom.left_x, geom.left_x, geom.left_x + geom.cap],
                [geom.y_top, geom.y_top, geom.y_bot, geom.y_bot],
                color='black', lw=0.8, zorder=3)
        # 右括号 ]
        ax.plot([geom.right_x - geom.cap, geom.right_x, geom.right_x, geom.right_x - geom.cap],
                [geom.y_top, geom.y_top, geom.y_bot, geom.y_bot],
                color='black', lw=0.8, zorder=3)
        # 下标文字：用普通字符而非 Unicode 下标码位，字体族/字号与连线
        # label 完全一致（Unicode 下标在缺字形字体会回退、且天生偏小），
        # 靠括号底部的位置体现下标效果
        ax.text(geom.right_x + geom.cap * 0.5, geom.y_bot,
                str(count), fontsize=font_size - 1,
                va='top', ha='left', zorder=4)


# ─── Figure 量测与尺寸调整 ───────────────────────────────────


def main_scale_inches(fig, ax):
    """aspect-equal 收缩生效后，主体 1 数据单位 = 多少英寸。须先 fig.canvas.draw()。"""
    p0 = ax.transData.transform((0, 0))
    p1 = ax.transData.transform((1, 0))
    return abs(p1[0] - p0[0]) / fig.dpi


def content_bbox_inches(fig, ax, renderer):
    """主体实际内容（含括号下标/连线标签等所有可见 artist）的英寸 bbox。

    不用 ax.get_tightbbox()：其是否包含 axes patch 随 matplotlib 版本而异，
    手动并集最确定。axis('off') 已把 patch/spines 置为不可见，会被跳过。
    """
    from matplotlib.transforms import Bbox
    dpi = fig.dpi
    boxes = []
    for ch in ax.get_children():
        if not ch.get_visible():
            continue
        try:
            bb = (ch.get_tightbbox(renderer)
                  if hasattr(ch, 'get_tightbbox') else None)
            if bb is None:
                bb = ch.get_window_extent(renderer)
        except Exception:
            bb = ch.get_window_extent(renderer)
        if bb is not None and bb.width >= 0 and bb.height >= 0:
            boxes.append(bb)
    u = Bbox.union(boxes) if boxes else ax.get_window_extent(renderer)
    return u.x0 / dpi, u.y0 / dpi, u.x1 / dpi, u.y1 / dpi  # x0,y0,x1,y1 英寸


def grow_figure_for_legend(fig, legend_ax, margin_in=0.0):
    """legend 底边低于画布时增高 figure：所有 axes 英寸几何整体上移 delta，
    fraction 按新高度重算 → s_main、内容-legend 间距均不变。"""
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    lb = legend_ax.get_tightbbox(renderer)
    if lb is None:
        return
    bottom_in = lb.y0 / fig.dpi
    if bottom_in >= margin_in:
        return
    H = fig.get_figheight()
    delta = margin_in - bottom_in
    H_new = H + delta
    # 先按 H_new 算新 fraction，再改画布尺寸（forward=False 不动子 axes）
    rects = []
    for a in fig.axes:
        p = a.get_position(original=True)      # aspect 调整前的显式 rect
        y0_in = p.y0 * H + delta               # 整体上移 delta
        h_in = p.height * H                    # 英寸高度不变 → s_main 不变
        rects.append((a, [p.x0, y0_in / H_new, p.width, h_in / H_new]))
    fig.set_size_inches(fig.get_figwidth(), H_new, forward=False)
    for a, r in rects:
        a.set_position(r)


# ─── 主编排器 ────────────────────────────────────────────────


def draw_snfg(tree, dx=1, dy=1, mono_size=0.3, ratio=1,
              font_size=12, font_family="sans-serif", save_svg=None,
              add_legend=True, compact_repeat=True):

    _, pos, edges, labels, repeat_groups = prepare_layout(
        tree, dx=dx, dy=dy, ratio=ratio, compact_repeat=compact_repeat)
    xs = [x for x, y in pos.values()]
    ys = [y for x, y in pos.values()]
    width = max(xs) - min(xs) + 2
    height = max(ys) - min(ys) + 2

    plt.rcParams['font.family'] = font_family
    # 根据节点数量动态调整图形大小
    node_count = len(pos)
    min_width = max(4, min(12, node_count * 1.5))
    min_height = max(3, min(6, node_count * 0.8))
    fig, ax = plt.subplots(
        figsize=(max(min_width, width * 1.2), max(min_height, height * 1.2)),
    )

    # 括号间距参数
    PAD = bracket_pad(mono_size)

    # 构建括号边界信息（用于跨括号边的标签避让）
    bounds = bracket_bounds(repeat_groups, pad=PAD)

    # ---------- 绘制边 ----------
    for p, c, lk in edges:
        x1, y1 = pos[p]
        x2, y2 = pos[c]

        ax.plot([x1, x2], [y1, y2],
                color='black', lw=1, zorder=1)

        if lk:
            left, right = parse_edge_label(lk)
            x_l, y_l, x_r, y_r = edge_label_slots(
                p, c, (x1, y1), (x2, y2),
                perp=mono_size * LABEL_PERP_RATIO,
                along_mode='sign',
                bounds=bounds,
                avoid_margin=0.2,
            )

            if left:
                ax.text(x_l, y_l, left,
                        fontsize=font_size - 1,
                        rotation=0,
                        rotation_mode='anchor',
                        ha='center', va='center',
                        zorder=4)
            if right:
                ax.text(x_r, y_r, right,
                        fontsize=font_size - 1,
                        rotation=0,
                        rotation_mode='anchor',
                        ha='center', va='center',
                        zorder=4)

    # ---------- 绘制节点 ----------
    used_monos = set()
    for i, (x, y) in pos.items():
        if is_open_node(i):
            pass
        else :
            mono = labels[i]
            used_monos.add(mono)
            comp, color_hex = resolve_mono(mono)
            # 按 bbox 中心补偿：三角形等非上下对称形状否则顶端与连线齐平，
            # 与圆形混排时视觉不居中
            draw_shape(ax, comp, x, y - shape_vcenter_offset(comp, mono_size),
                       mono_size, color_hex)

    # ---------- 绘制重复单元括号 ----------
    if repeat_groups:
        draw_repeat_brackets(ax, repeat_groups, mono_size, font_size)

    ax.set_aspect('equal')
    ax.axis('off')

    # ---------- 绘制图例（内容感知定位 + 与主体等大的符号） ----------
    if add_legend and used_monos:
        fig.canvas.draw()                 # 解析 aspect-equal 收缩
        renderer = fig.canvas.get_renderer()
        s_main = main_scale_inches(fig, ax)
        cx0, cy0, cx1, cy1 = content_bbox_inches(fig, ax, renderer)
        legend_ax = add_snfg_legend(
            ax, used_monos, mono_size, font_size,
            main_scale=s_main,
            content_bottom_in=cy0,
            content_center_in=(cx0 + cx1) / 2,
        )
        if legend_ax is not None:
            grow_figure_for_legend(fig, legend_ax)

    if save_svg:
        fig.savefig(save_svg, bbox_inches='tight')
        plt.close(fig)
        return None, None

    return fig, ax
