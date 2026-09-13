"""Minimal SVG renderer for a layout result (standard library only)."""

from . import geometry as geo


def _fmt_angle(angle):
    return f"{round(angle, 2):g}"


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
        return " ".join("{:.2f},{:.2f}".format(*T(p)) for p in points)

    parts = []
    parts.append(
        '<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {width:.0f} {height:.0f}" font-family="Helvetica,Arial,sans-serif">'
    )
    parts.append('<rect width="100%" height="100%" fill="white"/>')
    parts.append(
        f'<polygon points="{poly_points(poly)}" fill="#f6f6f6" stroke="#333" stroke-width="2"/>'
    )

    # door zone (inward swing) and doorway line
    if problem.door_zone is not None:
        c, a, zw, zh = problem.door_zone
        parts.append(
            _rect_svg(
                c,
                a,
                zw,
                zh,
                T,
                fill=TYPE_COLORS["zone"],
                stroke="#e63946",
                dash="6,4",
                opacity=0.55,
            )
        )
    d1, d2 = T(problem.door[0]), T(problem.door[1])
    parts.append(
        f'<line x1="{d1[0]:.2f}" y1="{d1[1]:.2f}" x2="{d2[0]:.2f}" y2="{d2[1]:.2f}" '
        'stroke="#e63946" stroke-width="5" stroke-linecap="round"/>'
    )

    for pl in placements:
        c, a, rw, rh = pl.rect
        t = problem.item_type(pl.name)
        parts.append(
            _rect_svg(
                c, a, rw, rh, T, fill=TYPE_COLORS.get(t, "#ddd"), stroke="#264653", opacity=0.95
            )
        )
        lx, ly = T(c)
        fs = max(11.0, rw * scale * 0.12)
        parts.append(
            f'<text x="{lx:.2f}" y="{ly:.2f}" font-size="{fs:.0f}" text-anchor="middle" '
            f'dominant-baseline="middle" fill="#1d3557">{_esc(pl.name)}</text>'
        )
        parts.append(
            f'<text x="{lx:.2f}" y="{ly + fs * 1.1:.2f}" font-size="{fs * 0.85:.0f}" '
            f'text-anchor="middle" fill="#45586b">{_fmt_angle(problem.snap_angle(a))}&#176;</text>'
        )
    parts.append("</svg>")
    return "\n".join(parts), height


def _rect_svg(center, angle, w, h, T, fill, stroke, dash=None, opacity=1.0):
    corners = geo.rect_corners(center, angle, w, h)
    pts = " ".join("{:.2f},{:.2f}".format(*T(p)) for p in corners)
    dash_attr = f' stroke-dasharray="{dash}"' if dash else ""
    return (
        f'<polygon points="{pts}" fill="{fill}" fill-opacity="{opacity:.2f}" stroke="{stroke}" '
        f'stroke-width="1.5"{dash_attr}/>'
    )


def _esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
