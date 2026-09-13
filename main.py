#!/usr/bin/env python3
"""CLI entry point.

Usage:
    python main.py <input.json> [more.json ...] --out <output_dir>

For every input file this writes:
    <name>.result.json  - feasibility + centre/rotation of each item
    <name>.svg          - top-down drawing of the layout
and validates the result against every constraint from the task.
"""

import argparse
import json
import os
import sys

from layout_solver import Problem, Solver, render_svg, validate_result


def run_file(in_path, out_dir):
    name = os.path.splitext(os.path.basename(in_path))[0]
    with open(in_path, encoding="utf-8") as f:
        data = json.load(f)

    problem = Problem(data)
    result = Solver(problem).solve()

    os.makedirs(out_dir, exist_ok=True)
    result_path = os.path.join(out_dir, name + ".result.json")
    with open(result_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    svg_path = os.path.join(out_dir, name + ".svg")
    if result["feasible"]:
        rects = []
        for pname, spec in result["placements"].items():
            c = (spec["center"][0] - problem.offset[0], spec["center"][1] - problem.offset[1])
            length, w = problem.items[pname]
            rects.append((pname, (c, float(spec["rotation"]), length, w)))

        class _Pl:
            def __init__(self, name, rect):
                self.name = name
                self.rect = rect

        svg, _h = render_svg(problem, [_Pl(n, r) for n, r in rects])
        with open(svg_path, "w", encoding="utf-8") as f:
            f.write(svg)
    else:
        svg_path = None

    print("=" * 60)
    print(f"{in_path}  ->  {result_path}")
    ok, _infos = validate_result(data, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if svg_path:
        print(f"drawing: {svg_path}")
    return ok


def main():
    ap = argparse.ArgumentParser(description="place rectangular items inside a room boundary")
    ap.add_argument("inputs", nargs="+", help="input JSON file(s) or directories")
    ap.add_argument("--out", default="outputs", help="output directory (default: outputs)")
    args = ap.parse_args()

    files = []
    for path in args.inputs:
        if os.path.isdir(path):
            files.extend(
                sorted(
                    os.path.join(path, f)
                    for f in os.listdir(path)
                    if f.endswith(".json") and not f.endswith(".result.json")
                )
            )
        else:
            files.append(path)

    all_ok = True
    for path in files:
        try:
            all_ok &= run_file(path, args.out)
        except Exception as exc:  # keep going across batch inputs
            print(f"ERROR while solving {path}: {exc}", file=sys.stderr)
            all_ok = False
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
