"""Low-level python-pptx primitives: color conversion, fill/stroke/style
removal, freeform, node drawing."""

from pptx.dml.color import RGBColor
from pptx.oxml.ns import qn
from pptx.util import Pt

from csdb2snfg.snfg.geometry import ALL, node_fill_polys, shape_vcenter_offset


def hex_to_rgb(hex_color):
    """Convert #RRGGBB or #RRGGBBAA hex string to (R, G, B) tuple."""
    h = hex_color.lstrip("#")
    if len(h) == 8:
        h = h[:6]  # strip alpha
    return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))


def set_shape_fill_color(shape, hex_color):
    """Set solid fill color on a pptx shape.

    8-digit hex (#RRGGBBAA) preserves transparency: written into DrawingML
    <a:alpha>, consistent with matplotlib svg/png translucent fills
    (hex_to_rgb only takes the RGB components).
    """
    fill = shape.fill
    fill.solid()
    fill.fore_color.rgb = RGBColor(*hex_to_rgb(hex_color))
    h = hex_color.lstrip("#")
    if len(h) == 8:
        alpha_pct = int(round(int(h[6:8], 16) / 255 * 100000))
        srgb = shape._element.spPr.find(qn("a:solidFill")).find(qn("a:srgbClr"))
        srgb.append(srgb.makeelement(qn("a:alpha"), {"val": str(alpha_pct)}))


def set_shape_line_color(shape, hex_color="000000", width_pt=0.25):
    """Set line color and width on a pptx shape."""
    line = shape.line
    line.color.rgb = RGBColor(*hex_to_rgb(f"#{hex_color}"))
    line.width = Pt(width_pt)


def remove_shape_style(shape):
    """Remove <p:style> element to eliminate theme-based shadow effects."""
    sp = shape._element
    style_el = sp.find(
        "p:style", {"p": "http://schemas.openxmlformats.org/presentationml/2006/main"}
    )
    if style_el is not None:
        sp.remove(style_el)


def add_freeform_shape(
    shapes, vertices, fill_color_hex, remove_style=True, *, line_hex=None, line_width_pt=None
):
    """Create a freeform shape from a list of (x, y) EMU vertices.

    line_hex/line_width_pt: None keeps the historical outline defaults
    ('000000', 0.25pt).
    """
    freeform = shapes.build_freeform(vertices[0][0], vertices[0][1])
    freeform.add_line_segments(vertices[1:], close=True)
    shape = freeform.convert_to_shape()
    set_shape_fill_color(shape, fill_color_hex)
    if line_hex is None and line_width_pt is None:
        set_shape_line_color(shape)
    else:
        set_shape_line_color(
            shape,
            line_hex.lstrip("#") if line_hex is not None else "000000",
            line_width_pt if line_width_pt is not None else 0.25,
        )
    if remove_style:
        remove_shape_style(shape)
    return shape


# ─── Node drawing ────────────────────────────────────────────


def draw_node(
    shapes, x_emu, y_emu, size_emu, comp, color_hex, *, line_hex=None, line_width_pt=None
):
    """Draw a single SNFG node (possibly composed of multiple shapes for divided types).

    line_hex/line_width_pt: node outline overrides; None keeps the historical
    defaults ('000000', 0.25pt).
    """
    xs, ys, entries = node_fill_polys(comp)
    # Compensate by bbox center: otherwise asymmetric shapes like triangles
    # have their apex flush with the edge line and look off-center when mixed
    # with circles (same compensation as the image backend)
    y_c = y_emu + shape_vcenter_offset(comp, size_emu)

    # PPT y-axis goes down, matplotlib y-axis goes up.
    # Flip y for shapes so they render with correct orientation in PPT.
    for role, sel in entries:
        fill_hex = color_hex if role == "color" else "#FFFFFF"
        if sel is ALL:
            vertices = [
                (int(x_emu + vx * size_emu), int(y_c - vy * size_emu)) for vx, vy in zip(xs, ys)
            ]
        else:
            vertices = [(int(x_emu + xs[i] * size_emu), int(y_c - ys[i] * size_emu)) for i in sel]
        add_freeform_shape(
            shapes, vertices, fill_hex, line_hex=line_hex, line_width_pt=line_width_pt
        )
