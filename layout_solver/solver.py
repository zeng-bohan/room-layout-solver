"""Wall-preference layout solver.

Strategy
--------
1. Normalise the boundary into a local frame; extract walls, the doorway and
   (for inward-opening doors) the N x N door swing zone.
2. Derive the set of allowed item rotations from the boundary edge
   directions: each wall direction theta contributes {theta, theta+90}.
3. Backtracking search over items ordered by constraint tightness
   (fridge first, then by area). For every item we generate candidates:
     - wall-flush placements (slid along each wall, both orientations)
     - placements butted against an already placed item (builds compact rows)
     - a coarse free-grid fallback (only used when nothing else fits)
   Candidates are scored: wall contact first, then butt contact, then
   compactness (bounding-box growth), so wall-lined layouts win.
4. The fridge needs a clear strip in front of its door edge. We try to
   satisfy the full door-swing depth first, then half, then the bare
   "nothing may touch the door edge" rule, and report which level held.
"""

import math
import time

from . import geometry as geo

ANGLE_TOL = 0.5          # degrees; angles closer than this are "the same"
WALL_SLIDE_STEP = 50.0   # mm between wall-flush candidate positions
BUTT_SLIDE_STEP = 50.0   # mm between butt-joint candidate positions
GRID_STEP = 250.0        # mm between free-grid fallback candidates
CONTACT_TOL = 1.0        # mm; proximity treated as "flush"
MIN_DOOR_CLEARANCE = 2.0 # mm strip that keeps the fridge door edge touch-free


def _ang_norm360(a):
    return a % 360.0


def ang_eq(a, b, tol=ANGLE_TOL):
    d = abs((a - b) % 180.0)
    return min(d, 180.0 - d) <= tol


class Wall:
    __slots__ = ("a", "b", "u", "n", "angle", "length")

    def __init__(self, a, b, u, n, angle, length):
        self.a = a
        self.b = b
        self.u = u          # unit vector along the wall
        self.n = n          # unit inward normal
        self.angle = angle  # degrees, mod 180
        self.length = length


class Problem:
    """Parsed and normalised input (local coordinates, min corner at origin)."""

    def __init__(self, data):
        raw = [tuple(map(float, p)) for p in data["boundary"]]
        if geo.norm(geo.sub(raw[0], raw[-1])) < 1e-6:
            raw = raw[:-1]
        self.offset = (min(p[0] for p in raw), min(p[1] for p in raw))
        self.poly = [(x - self.offset[0], y - self.offset[1]) for x, y in raw]

        door = [tuple(map(float, p)) for p in data["door"]]
        self.door = [
            (door[0][0] - self.offset[0], door[0][1] - self.offset[1]),
            (door[1][0] - self.offset[0], door[1][1] - self.offset[1]),
        ]
        self.is_inward = bool(data.get("isOpenInward", False))

        self.items = {}
        for name, dims in data["algoToPlace"].items():
            self.items[name] = (float(dims[0]), float(dims[1]))

        self.walls = self._extract_walls()
        self.allowed_angles = self._allowed_angles()
        self.door_wall = self._find_door_wall()
        self.door_width = geo.norm(geo.sub(self.door[1], self.door[0]))
        self.door_zone, self.doorway_strip = self._build_door_zones()
        self.poly_area = abs(geo.polygon_signed_area(self.poly))
        self.has_fridge = any(self.item_type(n) == "fridge" for n in self.items)

    # ------------------------------------------------------------------ setup

    def _extract_walls(self):
        walls = []
        for a, b in geo.polygon_edges(self.poly):
            length = geo.norm(geo.sub(b, a))
            if length < 1e-9:
                continue
            u = geo.unit(geo.sub(b, a))
            n0 = geo.perp(u)
            mid = geo.mul(geo.add(a, b), 0.5)
            probe = geo.add(mid, geo.mul(n0, 1.0))
            n = n0 if geo.point_in_polygon(probe, self.poly) else geo.mul(n0, -1.0)
            angle = (math.degrees(math.atan2(u[1], u[0]))) % 180.0
            walls.append(Wall(a, b, u, n, angle, length))
        return walls

    def _allowed_angles(self):
        """Cluster wall directions; snap near-axis angles to exactly 0/90."""
        raw = sorted({round(w.angle, 6) for w in self.walls})
        clusters = []
        for a in raw:
            if clusters and ang_eq(a, clusters[-1][-1]):
                clusters[-1].append(a)
            else:
                clusters.append([a])
        if len(clusters) > 1 and ang_eq(clusters[0][0] + 180.0, clusters[-1][-1]):
            clusters[0] = clusters.pop() + clusters[0]
        bases = []
        for cl in clusters:
            mean = sum(cl) / len(cl)
            if min(abs(mean), abs(mean - 180.0)) <= ANGLE_TOL:
                mean = 0.0
            elif abs(mean - 90.0) <= ANGLE_TOL:
                mean = 90.0
            bases.append(round(mean % 180.0, 6))
        return sorted(set(bases))

    def _find_door_wall(self):
        best, best_d = None, float("inf")
        for w in self.walls:
            d = max(self._pt_seg_dist(self.door[0], w),
                    self._pt_seg_dist(self.door[1], w))
            if d < best_d:
                best, best_d = w, d
        if best is None or best_d > 2.0:
            raise ValueError("door segment does not lie on the boundary")
        return best

    @staticmethod
    def _pt_seg_dist(p, w):
        ab = geo.sub(w.b, w.a)
        t = max(0.0, min(1.0, geo.dot(geo.sub(p, w.a), ab) / geo.dot(ab, ab)))
        return geo.norm(geo.sub(p, geo.add(w.a, geo.mul(ab, t))))

    def _build_door_zones(self):
        w = self.door_wall
        mid = geo.mul(geo.add(self.door[0], self.door[1]), 0.5)
        n = self.door_width
        if self.is_inward:
            # inward door reserves an N x N square just inside the doorway
            center = geo.add(mid, geo.mul(w.n, n / 2.0))
            return (center, w.angle, n, n), (mid, w.angle, n, MIN_DOOR_CLEARANCE)
        center = geo.add(mid, geo.mul(w.n, MIN_DOOR_CLEARANCE / 2.0))
        return None, (center, w.angle, n, MIN_DOOR_CLEARANCE)

    # ---------------------------------------------------------------- helpers

    def item_type(self, name):
        low = name.lower()
        if "fridge" in low:
            return "fridge"
        if "icemaker" in low:
            return "iceMaker"
        if "overshelf" in low:
            return "overShelf"
        return "shelf"

    def rotations_for(self, name):
        """Candidate angles (degrees, mod 360) for one item.

        Non-fridge items only need footprints unique mod 180.  For fridges the
        door edge sits on one `length` side (local +y), so flipped variants
        are physically different and all four are kept.
        """
        rots = set()
        for a in self.allowed_angles:
            rots.add(_ang_norm360(a))
            rots.add(_ang_norm360(a + 90.0))
        if self.item_type(name) == "fridge":
            rots = {_ang_norm360(r) for r in rots}
            extra = {_ang_norm360(r + 180.0) for r in rots}
            rots |= extra
        else:
            rots = {r for r in rots if r < 180.0 - ANGLE_TOL}
        return sorted(rots)

    @staticmethod
    def _extent(angle, l, w, axis_angle):
        """Extent of an l x w rect rotated by `angle`, projected on `axis_angle`."""
        d = math.radians(angle - axis_angle)
        return l * abs(math.cos(d)) + w * abs(math.sin(d))


class _Placed:
    __slots__ = ("name", "rect", "strip")

    def __init__(self, name, rect, strip=None):
        self.name = name
        self.rect = rect
        self.strip = strip  # fridge door clearance strip, if any


class Solver:
    def __init__(self, problem, node_cap=150_000, time_cap=20.0):
        self.p = problem
        self.node_cap = node_cap
        self.time_cap = time_cap
        self._fridge_clearance = 0.0
        self._wall_only = False

    # -------------------------------------------------------------------- api

    def solve(self):
        p = self.p
        names = sorted(p.items,
                       key=lambda n: (p.item_type(n) != "fridge",
                                      -p.items[n][0] * p.items[n][1], n))
        if p.has_fridge:
            fl = p.items[next(n for n in names if p.item_type(n) == "fridge")][0]
            levels = [fl, fl / 2.0, 0.0]
        else:
            levels = [0.0]

        # phase A: every item must sit flush against a wall (the stated
        # preference); phase B: relax to butted-to-item and free placements
        for wall_only in (True, False):
            for level in levels:
                self._wall_only = wall_only
                self._fridge_clearance = level
                self._deadline = time.time() + self.time_cap
                self._solution = None
                if self._search(names):
                    return self._build_result(names, True, wall_only)
        return self._build_result(names, False, False)

    def _build_result(self, names, feasible, wall_only=False):
        p = self.p
        out = {"feasible": feasible, "placements": {}}
        if not feasible:
            out["fridgeDoorClearanceMm"] = None
            return out
        out["allItemsWallFlush"] = wall_only
        out["fridgeDoorClearanceMm"] = self._fridge_clearance if p.has_fridge else None
        for pl in self._solution:
            cx, cy = pl.rect[0]
            ox, oy = p.offset
            out["placements"][pl.name] = {
                "center": [round(cx + ox, 4), round(cy + oy, 4)],
                "rotation": self._snap_angle(pl.rect[1]),
            }
        return out

    @staticmethod
    def _snap_angle(angle):
        # mod-360 comparison: 90 vs 270 differ for the fridge door side
        a = _ang_norm360(angle)
        for axis in (0.0, 90.0, 180.0, 270.0):
            d = abs(a - axis)
            if min(d, 360.0 - d) <= ANGLE_TOL:
                return axis
        return round(a, 2)

    # ----------------------------------------------------------------- search

    def _search(self, names):
        p = self.p
        placed = []
        areas = [p.items[n][0] * p.items[n][1] for n in names]
        suffix = [0.0] * (len(names) + 1)
        for i in range(len(names) - 1, -1, -1):
            suffix[i] = suffix[i + 1] + areas[i]
        door_zone_area = p.door_zone[2] * p.door_zone[3] if p.door_zone else 0.0
        self._nodes = 0

        def rec(idx, used_area):
            self._nodes += 1
            if self._nodes > self.node_cap or time.time() > self._deadline:
                return False
            if idx == len(names):
                self._solution = list(placed)
                return True
            if suffix[idx] > (p.poly_area - door_zone_area - used_area) + 1.0:
                return False
            for rect, strip in self._candidates(names[idx], placed):
                if not self._fits(rect, strip, placed):
                    continue
                entry = _Placed(names[idx], rect, strip)
                placed.append(entry)
                if rec(idx + 1, used_area + areas[idx]):
                    return True
                placed.pop()
            return False

        return rec(0, 0.0)

    def _fits(self, rect, strip, placed):
        p = self.p
        if not geo.rect_inside_polygon(rect[0], rect[1], rect[2], rect[3], p.poly):
            return False
        for pl in placed:
            if geo.rect_overlap(rect, pl.rect):
                return False
            if pl.strip is not None and geo.rect_overlap(rect, pl.strip):
                return False
        for zone in (p.door_zone, p.doorway_strip):
            if zone is not None and geo.rect_overlap(rect, zone):
                return False
        if strip is not None:
            if not geo.rect_inside_polygon(strip[0], strip[1], strip[2], strip[3], p.poly):
                return False
            for pl in placed:
                if geo.rect_overlap(strip, pl.rect):
                    return False
        return True

    # ------------------------------------------------------------- candidates

    def _fridge_strip(self, name, rect):
        """Clear strip in front of the fridge door edge (local +y side)."""
        if self.p.item_type(name) != "fridge":
            return None
        c, a, l, w = rect
        depth = max(self._fridge_clearance, MIN_DOOR_CLEARANCE)
        rad = math.radians(a)
        nx, ny = -math.sin(rad), math.cos(rad)  # local +y axis in world
        edge_mid = (c[0] + nx * w / 2.0, c[1] + ny * w / 2.0)
        center = (edge_mid[0] + nx * depth / 2.0, edge_mid[1] + ny * depth / 2.0)
        return (center, a, l, depth)

    def _candidates(self, name, placed):
        p = self.p
        l, w = p.items[name]
        rots = p.rotations_for(name)
        seen = set()
        out = []

        def add(center, angle):
            key = (round(center[0] / 25.0), round(center[1] / 25.0),
                   round(angle / 45.0))
            if key not in seen:
                seen.add(key)
                out.append(((center, angle, l, w), self._fridge_strip(name, (center, angle, l, w))))

        # 1) wall-flush placements
        for wall in p.walls:
            for theta in rots:
                if not (ang_eq(theta, wall.angle) or ang_eq(theta, wall.angle + 90.0)):
                    continue
                eu = p._extent(theta, l, w, wall.angle)
                en = p._extent(theta, l, w, wall.angle + 90.0)
                if eu > wall.length + 1e-6:
                    continue
                ts = []
                t = 0.0
                while t < wall.length - eu - 1e-9:
                    ts.append(t)
                    t += WALL_SLIDE_STEP
                ts.append(max(wall.length - eu, 0.0))
                for t in ts:
                    base = geo.add(wall.a, geo.mul(wall.u, t + eu / 2.0))
                    add(geo.add(base, geo.mul(wall.n, en / 2.0)), theta)

        # 2) butted against an already placed item (phase B only)
        if not self._wall_only:
            for pl in placed:
                pc, pa, pw, ph = pl.rect
                corners = geo.rect_corners(pc, pa, pw, ph)
                for side in range(4):
                    s1, s2 = corners[side], corners[(side + 1) % 4]
                    su = geo.unit(geo.sub(s2, s1))
                    outward = (su[1], -su[0])  # right-hand normal: outward for CCW
                    side_mid = geo.mul(geo.add(s1, s2), 0.5)
                    side_len = geo.norm(geo.sub(s2, s1))
                    out_ang = math.degrees(math.atan2(outward[1], outward[0]))
                    u_ang = math.degrees(math.atan2(su[1], su[0]))
                    for theta in rots:
                        if not (ang_eq(theta, pa) or ang_eq(theta, pa + 90.0)):
                            continue
                        e_n = p._extent(theta, l, w, out_ang)
                        e_u = p._extent(theta, l, w, u_ang)
                        base = geo.add(side_mid, geo.mul(outward, e_n / 2.0))
                        t = -e_u / 2.0
                        stop = side_len - e_u / 2.0 + 1e-9
                        while t <= stop:
                            add(geo.add(base, geo.mul(su, t)), theta)
                            t += BUTT_SLIDE_STEP

        # 3) free-grid fallback (phase B only; scored last)
        if not self._wall_only:
            xs = [pt[0] for pt in p.poly]
            ys = [pt[1] for pt in p.poly]
            gx = math.floor(min(xs))
            while gx <= max(xs):
                gy = math.floor(min(ys))
                while gy <= max(ys):
                    for theta in rots:
                        add((float(gx), float(gy)), theta)
                    gy += GRID_STEP
                gx += GRID_STEP

        return self._score_all(out, placed)

    def _score_all(self, cands, placed):
        p = self.p
        scored = []
        for rect, strip in cands:
            wall_contact = sum(
                geo.segment_rect_overlap_len(wa.a, wa.b, rect, CONTACT_TOL)
                for wa in p.walls)
            butt = sum(geo.rects_edge_contact_len(rect, pl.rect, CONTACT_TOL)
                       for pl in placed)
            growth = self._bbox_growth(rect, placed)
            scored.append(((round(wall_contact + 0.3 * butt, 3),
                            -round(growth, 1)), rect, strip))
        scored.sort(key=lambda s: (s[0], s[1][1]), reverse=True)
        return [(r, s) for _sc, r, s in scored]

    @staticmethod
    def _bbox_growth(rect, placed):
        if not placed:
            return 0.0
        all_pts = []
        for pl in placed:
            all_pts.extend(geo.rect_corners(*pl.rect))
        all_pts.extend(geo.rect_corners(*rect))
        xs = [p[0] for p in all_pts]
        ys = [p[1] for p in all_pts]
        return (max(xs) - min(xs)) * (max(ys) - min(ys))
