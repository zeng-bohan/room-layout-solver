"""Independent validity checker for solver output.

Given the original input JSON and the result JSON, re-derives every
constraint from scratch (fresh polygon tests, SAT overlap, door zones,
fridge clearance) and reports pass/fail per rule.
"""

import math

from . import geometry as geo
from .solver import MIN_DOOR_CLEARANCE, ang_eq


def check(data, result, report=print):
    problems = ProblemView(data)
    placements = result.get("placements", {})
    errors = []
    infos = []

    if not result.get("feasible"):
        report("result declares INFEASIBLE - nothing to check")
        return True, infos

    rects = {}
    for name, spec in placements.items():
        cx, cy = spec["center"]
        # back to local frame; inset slightly so wall-flush items (which touch
        # the boundary exactly, which is legal) still pass the point tests
        c = (cx - problems.offset[0], cy - problems.offset[1])
        length, w = problems.items[name]
        rects[name] = (c, float(spec["rotation"]), length - 1.0, w - 1.0)

    # 1. inside the boundary
    for name, r in rects.items():
        corners = geo.rect_corners(*r)
        mid_ok = all(
            geo.point_in_polygon(
                geo.mul(geo.add(corners[i], corners[(i + 1) % 4]), 0.5), problems.poly
            )
            for i in range(4)
        )
        corners_ok = all(geo.point_in_polygon(p, problems.poly) for p in corners)
        crossing = any(
            geo.segments_properly_cross(corners[i], corners[(i + 1) % 4], e1, e2)
            for e1, e2 in geo.polygon_edges(problems.poly)
            for i in range(4)
        )
        if not (corners_ok and mid_ok) or crossing:
            errors.append(f"{name} is not fully inside the boundary")

    # 2. pairwise overlap
    names = list(rects)
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            if geo.rect_overlap(rects[names[i]], rects[names[j]]):
                errors.append(f"{names[i]} overlaps {names[j]}")

    # 3. door rules
    for name, r in rects.items():
        if problems.door_zone and geo.rect_overlap(r, problems.door_zone):
            errors.append(f"{name} blocks the inward-door swing zone")
        if geo.rect_overlap(r, problems.doorway_strip):
            errors.append(f"{name} blocks the doorway")

    # 4. orientation must be parallel/perpendicular to some boundary edge
    for name, r in rects.items():
        if not any(ang_eq(r[1], w[4]) or ang_eq(r[1], w[4] + 90.0) for w in problems.walls):
            errors.append(f"{name} rotation {r[1]:.2f} not parallel/perpendicular to any wall")

    # 5. fridge door edge: nothing may touch it; clearance strip must be clear
    for name, r in rects.items():
        if "fridge" not in name.lower():
            continue
        clear = result.get("fridgeDoorClearanceMm")
        depth = max(float(clear or 0.0), MIN_DOOR_CLEARANCE)
        c, a, length, w = r
        rad = math.radians(a)
        nx, ny = -math.sin(rad), math.cos(rad)
        edge_mid = (c[0] + nx * w / 2.0, c[1] + ny * w / 2.0)
        center = (edge_mid[0] + nx * depth / 2.0, edge_mid[1] + ny * depth / 2.0)
        strip = (center, a, length, depth)
        if not geo.rect_inside_polygon(strip[0], strip[1], strip[2], strip[3], problems.poly):
            errors.append(f"{name} door edge faces a wall / leaves the room")
        for other, orect in rects.items():
            if other != name and geo.rect_overlap(strip, orect):
                errors.append(f"{other} sits inside {name}'s door clearance strip")
        infos.append(f"{name} door clearance strip: {length:.0f} mm x {depth:.0f} mm kept clear")

    # 6. informational: wall-flush ratio
    flush = 0
    for r in rects.values():
        contact = sum(geo.segment_rect_overlap_len(w[0], w[1], r, 1.0) for w in problems.walls)
        if contact > 1.0:
            flush += 1
    infos.append(f"wall-flush items: {flush} / {len(rects)}")

    for e in errors:
        report("FAIL: " + e)
    for i in infos:
        report("info: " + i)
    report("VALIDATION " + ("FAILED" if errors else "PASSED"))
    return not errors, infos


class ProblemView:
    """Re-derives the normalised problem without reusing solver logic."""

    def __init__(self, data):
        raw = [tuple(map(float, p)) for p in data["boundary"]]
        if geo.norm(geo.sub(raw[0], raw[-1])) < 1e-6:
            raw = raw[:-1]
        self.offset = (min(p[0] for p in raw), min(p[1] for p in raw))
        self.poly = [(x - self.offset[0], y - self.offset[1]) for x, y in raw]
        self.items = {n: (float(d[0]), float(d[1])) for n, d in data["algoToPlace"].items()}

        door = [tuple(map(float, p)) for p in data["door"]]
        door = [
            (door[0][0] - self.offset[0], door[0][1] - self.offset[1]),
            (door[1][0] - self.offset[0], door[1][1] - self.offset[1]),
        ]

        self.walls = []
        for a, b in geo.polygon_edges(self.poly):
            if geo.norm(geo.sub(b, a)) < 1e-9:
                continue
            u = geo.unit(geo.sub(b, a))
            n0 = geo.perp(u)
            mid = geo.mul(geo.add(a, b), 0.5)
            n = (
                n0
                if geo.point_in_polygon(geo.add(mid, geo.mul(n0, 1.0)), self.poly)
                else geo.mul(n0, -1.0)
            )
            self.walls.append((a, b, u, n, (math.degrees(math.atan2(u[1], u[0]))) % 180.0))

        # nearest wall to the door
        def d_seg(p, a, b):
            ab = geo.sub(b, a)
            t = max(0.0, min(1.0, geo.dot(geo.sub(p, a), ab) / geo.dot(ab, ab)))
            return geo.norm(geo.sub(p, geo.add(a, geo.mul(ab, t))))

        wa, wb, wu, wn, wangle = min(
            self.walls, key=lambda w: min(d_seg(door[0], w[0], w[1]), d_seg(door[1], w[0], w[1]))
        )
        n = geo.norm(geo.sub(door[1], door[0]))
        mid = geo.mul(geo.add(door[0], door[1]), 0.5)
        self.doorway_strip = (mid, wangle, n, MIN_DOOR_CLEARANCE)
        self.door_zone = None
        if data.get("isOpenInward", False):
            self.door_zone = (geo.add(mid, geo.mul(wn, n / 2.0)), wangle, n, n)
