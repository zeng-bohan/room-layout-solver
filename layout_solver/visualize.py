"""Minimal SVG renderer for a layout result (standard library only)."""

from . import geometry as geo
from .solver import ANGLE_TOL


def snap_angle(angle):
    a = angle % 360.0
    for axis in (0.0, 90.0, 180.0, 270.0):
        d = abs(a - axis)
        if min(d, 360.0 - d) <= ANGLE_TOL:
            return axis
    return round(a, 2)

TYPE_COLORS = {
    "fridge": "#f4a261",
    "iceMaker": "#8ecae6",
    "shelf": "#90be6d",
    "overShelf": "#c8b6ff",
    "zone": "#ffb3b3",
}


def render_svg(problem, placements, width=900.0):
    poly = problem.poly
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    minx, maxx = min(xs), max(xs)
    miny, maxy = min(ys), max(ys)
    pad = 0.06 * max(maxx - minx, maxy - miny)
    w = maxx - minx + 2 * pad
    h = maxy - miny + 2 * pad
    scale = width / w
    height = h * scale

    def T(pt):
        """Local coords -> SVG coords (y flipped)."""
        return ((pt[0] - minx + pad) * scale, (maxy - pt[1] + pad) * scale)

    def poly_points(points):
        return " ".join("%.2f,%.2f" % T(p) for p in points)

    parts = []
    parts.append('<svg xmlns="http://www.w3.org/2000/svg" '
                 'viewBox="0 0 %.0f %.0f" font-family="Helvetica,Arial,sans-serif">'
                 % (width, height))
    parts.append('<rect width="100%" height="100%" fill="white"/>')
    parts.append('<polygon points="%s" fill="#f6f6f6" stroke="#333" stroke-width="2"/>'
                 % poly_points(poly))

    # door zone (inward swing) and doorway line
    if problem.door_zone is not None:
        c, a, zw, zh = problem.door_zone
        parts.append(_rect_svg(c, a, zw, zh, T, fill=TYPE_COLORS["zone"],
                               stroke="#e63946", dash="6,4", opacity=0.55))
    d1, d2 = T(problem.door[0]), T(problem.door[1])
    parts.append('<line x1="%.2f" y1="%.2f" x2="%.2f" y2="%.2f" '
                 'stroke="#e63946" stroke-width="5" stroke-linecap="round"/>'
                 % (d1[0], d1[1], d2[0], d2[1]))

    for pl in placements:
        c, a, rw, rh = pl.rect
        t = problem.item_type(pl.name)
        parts.append(_rect_svg(c, a, rw, rh, T, fill=TYPE_COLORS.get(t, "#ddd"),
                               stroke="#264653", opacity=0.95))
        lx, ly = T(c)
        fs = max(11.0, rw * scale * 0.12)
        parts.append('<text x="%.2f" y="%.2f" font-size="%.0f" text-anchor="middle" '
                     'dominant-baseline="middle" fill="#1d3557">%s</text>'
                     % (lx, ly, fs, _esc(pl.name)))
        parts.append('<text x="%.2f" y="%.2f" font-size="%.0f" text-anchor="middle" '
                     'fill="#45586b">%.0f&#176;</text>'
                     % (lx, ly + fs * 1.1, fs * 0.85, snap_angle(a)))
    parts.append('</svg>')
    return "\n".join(parts), height


def _rect_svg(center, angle, w, h, T, fill, stroke, dash=None, opacity=1.0):
    corners = geo.rect_corners(center, angle, w, h)
    pts = " ".join("%.2f,%.2f" % T(p) for p in corners)
    dash_attr = ' stroke-dasharray="%s"' % dash if dash else ""
    return ('<polygon points="%s" fill="%s" fill-opacity="%.2f" stroke="%s" '
            'stroke-width="1.5"%s/>'
            % (pts, fill, opacity, stroke, dash_attr))


def _esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
