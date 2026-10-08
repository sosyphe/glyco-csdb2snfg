"""matplotlib 后端的 SNFG 节点符号绘制。"""

from csdb2snfg.snfg.geometry import ALL, node_fill_polys


def draw_shape(ax, comp, x, y, size, color):
    """
    绘制 SNFG 单糖节点
    ax: matplotlib Axes
    comp: glycan_dict 中的形状类型（FCircle, FSquare, DDiamond ...）
    x, y: 中心坐标
    size: 符号半径（圆的半径 / 正方形半边长）
    color: 填充颜色
    """
    xs, ys, entries = node_fill_polys(comp)
    XS = xs * size + x
    YS = ys * size + y

    for role, sel in entries:
        fill_color = color if role == 'color' else 'white'
        if sel is ALL:
            ax.fill(XS, YS, color=fill_color, edgecolor='black', zorder=2)
        else:
            ax.fill([XS[i] for i in sel], [YS[i] for i in sel],
                    color=fill_color, edgecolor='black', zorder=2)
