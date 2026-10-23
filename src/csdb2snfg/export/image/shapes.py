"""SNFG node symbol drawing for the matplotlib backend."""

from csdb2snfg.snfg.geometry import ALL, node_fill_polys


def draw_shape(ax, comp, x, y, size, color, *, edgecolor="black", linewidth=None, clip_on=True):
    """
    Draw one SNFG monosaccharide node.
    ax: matplotlib Axes
    comp: shape type from glycan_dict (FCircle, FSquare, DDiamond ...)
    x, y: center coordinates
    size: symbol radius (circle radius / square half-side)
    color: fill color
    edgecolor: outline color ('black' keeps the historical literal)
    linewidth: outline width in points; None keeps the matplotlib rc default
    clip_on: clip the patches to the axes bbox (matplotlib default). Legend
        axes are sized exactly to the symbol extents, so they pass False --
        otherwise the outer half of the stroke is cut at the axes border
        (circles lose their round top/bottom).
    """
    xs, ys, entries = node_fill_polys(comp)
    XS = xs * size + x
    YS = ys * size + y

    lw_kw = {} if linewidth is None else {"linewidth": linewidth}
    for role, sel in entries:
        fill_color = color if role == "color" else "white"
        if sel is ALL:
            ax.fill(
                XS, YS, color=fill_color, edgecolor=edgecolor, zorder=2, clip_on=clip_on, **lw_kw
            )
        else:
            ax.fill(
                [XS[i] for i in sel],
                [YS[i] for i in sel],
                color=fill_color,
                edgecolor=edgecolor,
                zorder=2,
                clip_on=clip_on,
                **lw_kw,
            )
