"""matplotlib 后端的 SNFG 符号图例。"""

from csdb2snfg.snfg.geometry import resolve_mono, shape_vcenter_offset

from csdb2snfg.export.image.shapes import draw_shape


def add_snfg_legend(ax, used_monos, mono_size=0.3, font_size=8, *,
                    main_scale=None, content_bottom_in=None,
                    content_center_in=None, gap_in=None):
    """在 figure 底部绘制 SNFG 符号图例。

    默认（main_scale=None）为旧行为：固定在 figure 底部 5% 处。
    传入 main_scale（主体 1 数据单位 = 多少英寸）与 content_bottom_in /
    content_center_in（主体内容 tight bbox 的底边 / 水平中心，英寸）后：
    - legend axes 物理尺寸 = 数据范围 × main_scale，box aspect == data
      aspect，aspect('equal') 不再二次收缩 → 符号与主体节点物理等大；
    - legend 顶边贴在 content_bottom - gap 之下、水平对齐内容中心
      → 任何糖链大小都不会与主体重叠。
    """
    if not used_monos:
        return None
    fig = ax.get_figure()
    n = len(used_monos)

    if main_scale is None:
        # ---- 兼容旧行为：固定在 figure 底部 5% ----
        legend_height = mono_size * 2
        legend_width = n * mono_size * 8

        legend_ax = fig.add_axes([(1 - legend_width / fig.get_figwidth()) / 2, 0.05,
                                  legend_width / fig.get_figwidth(), legend_height/fig.get_figheight()])
        legend_ax.axis('off')
        legend_ax.set_aspect('equal')

        for i, mono in enumerate(sorted(used_monos)):
            comp, color = resolve_mono(mono)
            x = i * mono_size * 4
            y = 0.5
            draw_shape(legend_ax, comp, x, y - shape_vcenter_offset(comp, mono_size),
                       mono_size, color)
            legend_ax.text(x+mono_size, y,
                           mono, fontsize=font_size, va='center', ha='left')
        return legend_ax

    # ---- 新路径：物理尺寸与主体严格等大、跟随内容底部定位 ----
    if gap_in is None:
        gap_in = max(0.12, 0.5 * mono_size * main_scale)  # ≈主体半个节点

    W, H = fig.get_figwidth(), fig.get_figheight()
    legend_ax = fig.add_axes([0.1, 0.05, 0.8, 0.1])  # 临时 rect，随后精调
    legend_ax.axis('off')
    legend_ax.margins(0)  # autoscale 不加 5% 边距

    for i, mono in enumerate(sorted(used_monos)):
        comp, color = resolve_mono(mono)
        x = i * mono_size * 4
        draw_shape(legend_ax, comp, x, 0.5 - shape_vcenter_offset(comp, mono_size),
                   mono_size, color)
        legend_ax.text(x + mono_size, 0.5, mono, fontsize=font_size,
                       va='center', ha='left')

    legend_ax.autoscale_view()
    dx0, dx1 = legend_ax.get_xlim()
    dy0, dy1 = legend_ax.get_ylim()
    Wd, Hd = dx1 - dx0, dy1 - dy0
    box_w, box_h = Wd * main_scale, Hd * main_scale  # 英寸
    # box aspect == data aspect → aspect('equal') 不再收缩 → 1 unit == main_scale 英寸
    legend_ax.set_aspect('equal')

    # 初放：中心对内容中心、顶边在 content_bottom - gap（text 右溢尚未计入）
    legend_ax.set_position([(content_center_in - box_w / 2) / W,
                            (content_bottom_in - gap_in - box_h) / H,
                            box_w / W, box_h / H])
    # 一次性修正：text 不参与 autoscale，用含 text 的 tight bbox 重新对中心、贴顶
    fig.canvas.draw()
    r = fig.canvas.get_renderer()
    lb = legend_ax.get_tightbbox(r)
    if lb is not None:
        dpi = fig.dpi
        dx = (content_center_in - (lb.x0 + lb.x1) / 2 / dpi) / W
        dy = ((content_bottom_in - gap_in) - lb.y1 / dpi) / H
        p = legend_ax.get_position()
        legend_ax.set_position([p.x0 + dx, p.y0 + dy, p.width, p.height])
    return legend_ax
