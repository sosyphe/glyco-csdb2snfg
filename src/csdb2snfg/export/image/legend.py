"""SNFG symbol legend for the matplotlib backend."""

from matplotlib.font_manager import FontProperties

from csdb2snfg.export.image.shapes import draw_shape
from csdb2snfg.snfg.geometry import shape_vcenter_offset
from csdb2snfg.snfg.style import load_style

_LABEL_CLEAR_RATIO = 0.2  # gap kept between a label and the next symbol, in mono_size units


def _measure_label_widths_px(fig, monos, font_size):
    """-> max measured label width in px (Agg/FreeType metrics, deterministic).

    The legend slots are geometric (data units scaled by main_scale) while the
    labels are sized in points; without measuring, long names (LDmanHep,
    Neu5Ac, ...) overflow their slot and overlap the next symbol.
    """
    renderer = fig.canvas.get_renderer()
    prop = FontProperties(size=font_size)
    return max(renderer.get_text_width_height_descent(m, prop, False)[0] for m in monos)


def add_snfg_legend(
    ax,
    used_monos,
    mono_size=0.3,
    font_size=8,
    *,
    main_scale=None,
    content_bottom_in=None,
    content_center_in=None,
    gap_in=None,
    style=None,
    node_stroke_width=None,
):
    """Draw the SNFG symbol legend at the bottom of the figure.

    The default (main_scale=None) is the legacy behavior: fixed at 5% from the
    figure bottom. When main_scale (inches per data unit of the main axes) and
    content_bottom_in / content_center_in (bottom edge / horizontal center of
    the main content's tight bbox, in inches) are given:
    - the legend axes' physical size = data extent x main_scale, box aspect ==
      data aspect, so aspect('equal') no longer shrinks it again -> symbols are
      physically the same size as the main nodes;
    - the legend's top edge sits below content_bottom - gap, horizontally
      aligned with the content center -> it never overlaps the main figure at
      any glycan size.
    """
    if not used_monos:
        return None
    # The legend is a color key, not part of the structure: it always uses the
    # full (non-dimmed) palette.
    st = load_style(style)
    edgecolor = st.node_stroke_color if st.node_stroke_color is not None else "black"
    linewidth = node_stroke_width if node_stroke_width is not None else st.node_stroke_width
    fig = ax.get_figure()
    n = len(used_monos)

    if main_scale is None:
        # ---- Legacy-compatible behavior: fixed at 5% from the figure bottom ----
        # No in-repo caller uses this path (draw_snfg always passes main_scale);
        # it is kept for API compatibility. Two-pass: draw at the historical
        # pitch, measure the labels, and redraw wider only if one overflows --
        # short-label output stays bit-identical, long labels no longer overlap.
        monos_sorted = sorted(used_monos)
        legend_height = mono_size * 2
        legend_width = n * mono_size * 8

        legend_ax = fig.add_axes(
            [
                (1 - legend_width / fig.get_figwidth()) / 2,
                0.05,
                legend_width / fig.get_figwidth(),
                legend_height / fig.get_figheight(),
            ]
        )
        legend_ax.axis("off")
        legend_ax.set_aspect("equal")

        def _draw_entries(wide_pitch=None):
            texts = []
            for i, mono in enumerate(monos_sorted):
                comp, color = st.resolve(mono)
                # legacy expression preserved verbatim for the default pitch
                x = i * wide_pitch if wide_pitch is not None else i * mono_size * 4
                y = 0.5
                draw_shape(
                    legend_ax,
                    comp,
                    x,
                    y - shape_vcenter_offset(comp, mono_size),
                    mono_size,
                    color,
                    edgecolor=edgecolor,
                    linewidth=linewidth,
                    clip_on=False,
                )
                texts.append(
                    legend_ax.text(
                        x + mono_size, y, mono, fontsize=font_size, va="center", ha="left"
                    )
                )
            return texts

        texts = _draw_entries()
        legend_ax.autoscale_view()
        fig.canvas.draw()
        r = fig.canvas.get_renderer()
        inv = legend_ax.transData.inverted()
        widths_data = []
        for t in texts:
            bb = t.get_window_extent(r)
            widths_data.append(inv.transform((bb.x1, 0))[0] - inv.transform((bb.x0, 0))[0])
        clear = _LABEL_CLEAR_RATIO * mono_size
        if widths_data and max(widths_data) + clear > 2 * mono_size:
            pitch = 2 * mono_size + max(widths_data) + clear
            legend_ax.cla()
            legend_ax.axis("off")
            legend_ax.set_aspect("equal")
            _draw_entries(wide_pitch=pitch)
            legend_ax.autoscale_view()
        return legend_ax

    # ---- New path: physical size strictly equal to the main figure,
    #      positioned below the content ----
    if gap_in is None:
        gap_in = max(0.12, 0.5 * mono_size * main_scale)  # ~half a main-figure node

    W, H = fig.get_figwidth(), fig.get_figheight()
    legend_ax = fig.add_axes([0.1, 0.05, 0.8, 0.1])  # temporary rect, fine-tuned below
    legend_ax.axis("off")
    legend_ax.margins(0)  # autoscale without the 5% margin

    # Slots are geometric (1 data unit == main_scale inches) but labels are
    # sized in points: measure them and widen the pitch for ALL entries only
    # when the widest label does not fit beside its symbol. Short-label
    # legends keep the historical expression (and bytes) untouched.
    monos_sorted = sorted(used_monos)
    px_per_unit = main_scale * fig.dpi
    max_w_data = _measure_label_widths_px(fig, monos_sorted, font_size) / px_per_unit
    clear = _LABEL_CLEAR_RATIO * mono_size
    wide = max_w_data + clear > 2 * mono_size
    pitch = 2 * mono_size + max_w_data + clear

    for i, mono in enumerate(monos_sorted):
        comp, color = st.resolve(mono)
        x = i * pitch if wide else i * mono_size * 4
        draw_shape(
            legend_ax,
            comp,
            x,
            0.5 - shape_vcenter_offset(comp, mono_size),
            mono_size,
            color,
            edgecolor=edgecolor,
            linewidth=linewidth,
            clip_on=False,
        )
        legend_ax.text(x + mono_size, 0.5, mono, fontsize=font_size, va="center", ha="left")

    legend_ax.autoscale_view()
    dx0, dx1 = legend_ax.get_xlim()
    dy0, dy1 = legend_ax.get_ylim()
    Wd, Hd = dx1 - dx0, dy1 - dy0
    box_w, box_h = Wd * main_scale, Hd * main_scale  # inches
    # box aspect == data aspect -> aspect('equal') no longer shrinks -> 1 unit == main_scale inches
    legend_ax.set_aspect("equal")

    # Initial placement: centered on the content center, top edge at
    # content_bottom - gap (text right-overflow not yet accounted for)
    legend_ax.set_position(
        [
            (content_center_in - box_w / 2) / W,
            (content_bottom_in - gap_in - box_h) / H,
            box_w / W,
            box_h / H,
        ]
    )
    # One-shot correction: text does not participate in autoscale, so re-center
    # and re-align the top using the tight bbox that includes text
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
