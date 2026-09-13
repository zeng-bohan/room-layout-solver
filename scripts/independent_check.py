#!/usr/bin/env python3
"""独立交叉校验：用与主实现零共享代码的方式复核 outputs/ 里的全部结果。

与 `layout_solver/` 故意不共享任何几何代码：点在多边形内改用射线法实现、
相交改用取样 + 叉积混判、门区从原始输入独立推导，用于捕获"实现与校验器
共用同一套错误假设"的系统性风险。

用法（仓库根目录）：
    python scripts/independent_check.py
读 examples/example*.json 与 outputs/example*.result.json，全部通过时
打印 ALL INDEPENDENT CHECKS PASSED 并以 0 退出，否则逐条列出失败项并以 1 退出。
"""

import json
import math
import os
import sys

TOL = 0.5  # mm，几何容差，与主实现的判定口径一致
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def pip(pt, poly):
    """射线法点在多边形内判定（even-odd）。"""
    x, y = pt
    inside = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            xt = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if xt > x:
                inside = not inside
    return inside


def seg_cross(p, p2, q, q2):
    """两线段是否存在真穿越（共线不算，允许贴墙共边）。"""

    def cr(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    d1, d2, d3, d4 = cr(q, q2, p), cr(q, q2, p2), cr(p, p2, q), cr(p, p2, q2)
    e = 1e-9
    if abs(d1) < e and abs(d2) < e and abs(d3) < e and abs(d4) < e:
        return False
    return ((d1 > e) != (d2 > e)) and ((d3 > e) != (d4 > e))


def corners(c, ang, length, width):
    """中心 + 旋转角（度，逆时针）→ 四角点，局部 +x 为 length 方向。"""
    a = math.radians(ang)
    ca, sa = math.cos(a), math.sin(a)
    return [
        (c[0] + dx * ca - dy * sa, c[1] + dx * sa + dy * ca)
        for dx, dy in (
            (-length / 2, -width / 2),
            (length / 2, -width / 2),
            (length / 2, width / 2),
            (-length / 2, width / 2),
        )
    ]


def sample_inset(pts, k=5):
    """四边形内部 k×k 双线性取样网格（避开边缘），用于探测内部越界。"""
    out = []
    for i in range(1, k):
        for j in range(1, k):
            u, v = i / k, j / k
            p = (
                pts[0][0] * (1 - u) * (1 - v)
                + pts[1][0] * u * (1 - v)
                + pts[2][0] * u * v
                + pts[3][0] * (1 - u) * v,
                pts[0][1] * (1 - u) * (1 - v)
                + pts[1][1] * u * (1 - v)
                + pts[2][1] * u * v
                + pts[3][1] * (1 - u) * v,
            )
            out.append(p)
    return out


def quads_overlap(A, B):
    """两个凸四边形是否重叠：顶点互含 OR 边真穿越（贴边/共线不算重叠）。"""

    def pt_in_quad(pt, Q):
        return pip(pt, Q) and not any(
            seg_cross(
                pt,
                (
                    (pt[0] + Q[i][0] + Q[(i + 1) % 4][0]) / 3,
                    (pt[1] + Q[i][1] + Q[(i + 1) % 4][1]) / 3,
                ),
                Q[i],
                Q[(i + 1) % 4],
            )
            for i in range(4)
        )

    inside = any(pt_in_quad(p, B) for p in A) or any(pt_in_quad(p, A) for p in B)
    cross = any(
        seg_cross(A[i], A[(i + 1) % 4], B[j], B[(j + 1) % 4]) for i in range(4) for j in range(4)
    )
    return inside or cross


def door_zone(data, poly):
    """从原始输入独立推导门禁入区：外开门取门线薄条，内开门取 N×N 门扇摆动方块。"""
    door = [tuple(p) for p in data["door"]]
    n = math.dist(door[0], door[1])
    um = ((door[1][0] - door[0][0]) / n, (door[1][1] - door[0][1]) / n)
    nm = (-um[1], um[0])
    mid = ((door[0][0] + door[1][0]) / 2, (door[0][1] + door[1][1]) / 2)
    if not pip((mid[0] + nm[0], mid[1] + nm[1]), poly):
        nm = (-nm[0], -nm[1])
    ang = math.degrees(math.atan2(um[1], um[0]))
    if data.get("isOpenInward"):
        return corners((mid[0] + nm[0] * n / 2, mid[1] + nm[1] * n / 2), ang, n, n)
    return corners((mid[0] + nm[0], mid[1] + nm[1]), ang, n, 2.0)


def load(example):
    with open(os.path.join(ROOT, "examples", f"example{example}.json"), encoding="utf-8") as f:
        data = json.load(f)
    with open(
        os.path.join(ROOT, "outputs", f"example{example}.result.json"), encoding="utf-8"
    ) as f:
        res = json.load(f)
    poly = [tuple(p) for p in data["boundary"]]
    if math.dist(poly[0], poly[-1]) < 1e-6:
        poly = poly[:-1]
    return data, res, poly


def check_containment(name, pts, poly, errors, ex):
    bad = [p for p in pts + sample_inset(pts) if not pip(p, poly)]
    if bad:
        errors.append(f"ex{ex} {name}: {len(bad)} sample points outside boundary")
    for e1, e2 in zip(poly, poly[1:] + poly[:1]):
        for i in range(4):
            if seg_cross(pts[i], pts[(i + 1) % 4], e1, e2):
                errors.append(f"ex{ex} {name}: edge crosses boundary edge")


def check_orientation(name, rotation, poly, errors, ex):
    for e1, e2 in zip(poly, poly[1:] + poly[:1]):
        wall = math.degrees(math.atan2(e2[1] - e1[1], e2[0] - e1[0])) % 180.0
        d = abs((rotation - wall) % 180.0)
        d = min(d, 180.0 - d)
        if d <= TOL:
            return
    errors.append(f"ex{ex} {name}: rotation {rotation} not parallel/perp to any wall")


def check_fridge_strip(name, spec, length, width, depth, poly, rects, errors, ex):
    """冰箱开门边（局部 +y 侧）外侧 depth 深的净空条必须留在房间内且无其他物品。"""
    c = tuple(spec["center"])
    ang = spec["rotation"]
    a = math.radians(ang)
    nx, ny = -math.sin(a), math.cos(a)
    edge_mid = (c[0] + nx * width / 2, c[1] + ny * width / 2)
    strip = corners(
        (edge_mid[0] + nx * depth / 2, edge_mid[1] + ny * depth / 2),
        ang,
        length - 2 * TOL,
        depth - TOL,
    )
    if any(not pip(p, poly) for p in strip + sample_inset(strip)):
        errors.append(f"ex{ex} {name}: door strip leaves the room")
    for other, other_pts in rects.items():
        if other != name and quads_overlap(strip, other_pts):
            errors.append(f"ex{ex} {other}: inside {name} door strip")


def check_example(ex):
    data, res, poly = load(ex)
    errors = []
    zone = door_zone(data, poly)

    rects = {}
    for name, spec in res["placements"].items():
        c = tuple(spec["center"])
        length, width = data["algoToPlace"][name]
        rects[name] = corners(c, spec["rotation"], length - 2 * TOL, width - 2 * TOL)

    for name, pts in rects.items():
        check_containment(name, pts, poly, errors, ex)
        if quads_overlap(pts, zone):
            errors.append(f"ex{ex} {name}: overlaps door zone/doorway")
        check_orientation(name, res["placements"][name]["rotation"], poly, errors, ex)

    names = list(rects)
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            if quads_overlap(rects[names[i]], rects[names[j]]):
                errors.append(f"ex{ex}: {names[i]} overlaps {names[j]}")

    clear = res.get("fridgeDoorClearanceMm") or 0.0
    depth = max(clear, 2.0)
    for name, spec in res["placements"].items():
        if "fridge" in name:
            length, width = data["algoToPlace"][name]
            check_fridge_strip(name, spec, length, width, depth, poly, rects, errors, ex)

    print(
        f"example{ex}: independent checks done "
        f"({len(rects)} items, inward={data.get('isOpenInward')}, clearance={clear})"
    )
    return errors


def main():
    errors = []
    for ex in (1, 2, 3, 4):
        errors.extend(check_example(ex))
    print()
    if errors:
        print("INDEPENDENT CHECK FAILURES:")
        for e in errors:
            print(" -", e)
        sys.exit(1)
    print("ALL INDEPENDENT CHECKS PASSED")


if __name__ == "__main__":
    main()
