"""2D geometry primitives used by the layout solver.

All lengths are in millimetres unless noted otherwise. A rectangle is
represented by (center, angle_deg, w, h): w extends along the local x axis
when angle is 0, h along the local y axis. Rectangles are only ever built
axis-parallel to one of the boundary wall directions, but collision code is
written for arbitrary oriented boxes (OBB via SAT) so slanted rooms work too.
"""

import math

EPS = 1e-9
# Distance (mm) we are allowed to "lose" when testing containment, so that
# wall-flush placements (zero distance to the boundary) still validate.
CONTAINMENT_SLACK = 0.5


# ---------------------------------------------------------------- points ---

def sub(a, b):
    return (a[0] - b[0], a[1] - b[1])


def add(a, b):
    return (a[0] + b[0], a[1] + b[1])


def mul(a, k):
    return (a[0] * k, a[1] * k)


def dot(a, b):
    return a[0] * b[0] + a[1] * b[1]


def perp(a):
    return (-a[1], a[0])


def norm(a):
    return math.hypot(a[0], a[1])


def unit(a):
    n = norm(a)
    if n < EPS:
        return (0.0, 0.0)
    return (a[0] / n, a[1] / n)


# -------------------------------------------------------------- polygons ---

def polygon_signed_area(poly):
    s = 0.0
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        s += x1 * y2 - x2 * y1
    return s / 2.0


def point_in_polygon(pt, poly):
    """Even-odd ray casting. Boundary behaviour unspecified by design;
    callers shrink rectangles slightly before containment tests."""
    x, y = pt
    inside = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            x_at = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if x_at > x:
                inside = not inside
    return inside


def cross3(o, a, b):
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def segments_properly_cross(p1, p2, p3, p4):
    """True only for a genuine X-shaped crossing.

    Collinear overlaps and endpoint touches return False: wall-flush
    rectangle edges lie exactly on boundary edges and must not be treated
    as intersections. Genuine crossings mean the rectangle pokes outside.
    """
    d1 = cross3(p3, p4, p1)
    d2 = cross3(p3, p4, p2)
    d3 = cross3(p1, p2, p3)
    d4 = cross3(p1, p2, p4)
    if abs(d1) < EPS and abs(d2) < EPS and abs(d3) < EPS and abs(d4) < EPS:
        return False
    if ((d1 > EPS and d2 < -EPS) or (d1 < -EPS and d2 > EPS)) and \
       ((d3 > EPS and d4 < -EPS) or (d3 < -EPS and d4 > EPS)):
        return True
    return False


def polygon_edges(poly):
    n = len(poly)
    for i in range(n):
        yield poly[i], poly[(i + 1) % n]


# ------------------------------------------------------------ rectangles ---

def rect_corners(center, angle_deg, w, h):
    a = math.radians(angle_deg)
    ca, sa = math.cos(a), math.sin(a)
    cx, cy = center
    hw, hh = w / 2.0, h / 2.0
    return [
        (cx + dx * ca - dy * sa, cy + dx * sa + dy * ca)
        for dx, dy in ((-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh))
    ]


def rect_axes(angle_deg):
    a = math.radians(angle_deg)
    return (math.cos(a), math.sin(a)), (-math.sin(a), math.cos(a))


def shrink_rect(center, angle_deg, w, h, amount=CONTAINMENT_SLACK):
    """Inset each edge by `amount` (for strict containment tests)."""
    return center, angle_deg, max(w - 2 * amount, 1e-3), max(h - 2 * amount, 1e-3)


def rect_overlap(r1, r2, eps=1e-6):
    """Strict interior overlap of two OBBs (touching edges are OK)."""
    (c1, a1, w1, h1), (c2, a2, w2, h2) = r1, r2
    p1 = rect_corners(c1, a1, w1, h1)
    p2 = rect_corners(c2, a2, w2, h2)
    axes = [rect_axes(a1)[0], rect_axes(a1)[1], rect_axes(a2)[0], rect_axes(a2)[1]]
    for ax in axes:
        min1 = min(dot(p, ax) for p in p1)
        max1 = max(dot(p, ax) for p in p1)
        min2 = min(dot(p, ax) for p in p2)
        max2 = max(dot(p, ax) for p in p2)
        if min(max1, max2) - max(min1, min2) <= eps:
            return False
    return True


def rect_inside_polygon(center, angle_deg, w, h, poly):
    """True if the (slightly shrunk) rectangle lies strictly inside `poly`."""
    sc, sa, sw, sh = shrink_rect(center, angle_deg, w, h)
    corners = rect_corners(sc, sa, sw, sh)
    if not all(point_in_polygon(p, poly) for p in corners):
        return False
    for e1, e2 in polygon_edges(poly):
        for j in range(4):
            if segments_properly_cross(corners[j], corners[(j + 1) % 4], e1, e2):
                return False
    return True


def segment_rect_overlap_len(seg_a, seg_b, rect, tol=1.0):
    """Length of the part of `rect`'s border lying within `tol` of the wall
    segment `seg_a`-`seg_b` projected onto that segment (contact metric)."""
    u = unit(sub(seg_b, seg_a))
    n = perp(u)
    corners = rect_corners(*rect)
    best = 0.0
    for j in range(4):
        p1, p2 = corners[j], corners[(j + 1) % 4]
        # both edge endpoints near the wall line and within the wall span
        off1 = abs(dot(sub(p1, seg_a), n))
        off2 = abs(dot(sub(p2, seg_a), n))
        if off1 <= tol and off2 <= tol:
            t1 = dot(sub(p1, seg_a), u)
            t2 = dot(sub(p2, seg_a), u)
            lo, hi = sorted((t1, t2))
            wall_len = norm(sub(seg_b, seg_a))
            lo_c = max(lo, 0.0)
            hi_c = min(hi, wall_len)
            if hi_c - lo_c > best:
                best = hi_c - lo_c
    return best


def rects_edge_contact_len(rect_a, rect_b, tol=1.0):
    """Longest shared-border length between two touching rectangles."""
    ca, aa, wa, ha = rect_a
    cb, ab, wb, hb = rect_b
    best = 0.0
    ca_pts = rect_corners(ca, aa, wa, ha)
    cb_pts = rect_corners(cb, ab, wb, hb)
    for j in range(4):
        p1, p2 = ca_pts[j], ca_pts[(j + 1) % 4]
        mid = mul(add(p1, p2), 0.5)
        if point_near_rect_border(mid, cb_pts, tol):
            length = norm(sub(p2, p1))
            best = max(best, length)
    for j in range(4):
        p1, p2 = cb_pts[j], cb_pts[(j + 1) % 4]
        mid = mul(add(p1, p2), 0.5)
        if point_near_rect_border(mid, ca_pts, tol):
            length = norm(sub(p2, p1))
            best = max(best, length)
    return best


def point_near_rect_border(pt, corners, tol):
    for j in range(4):
        p1, p2 = corners[j], corners[(j + 1) % 4]
        if point_near_segment(pt, p1, p2, tol):
            return True
    return False


def point_near_segment(pt, a, b, tol):
    ab = sub(b, a)
    l2 = dot(ab, ab)
    if l2 < EPS:
        return norm(sub(pt, a)) <= tol
    t = dot(sub(pt, a), ab) / l2
    t = max(0.0, min(1.0, t))
    closest = add(a, mul(ab, t))
    return norm(sub(pt, closest)) <= tol
