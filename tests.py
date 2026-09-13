"""Smoke tests: run `python tests.py` (no test framework needed).

Covers the constraint set with small synthetic rooms:
  1. roomy square room          -> feasible, every item wall-flush
  2. room too small for fridge  -> infeasible
  3. inward door swing blocks a
     one-item-wide corridor     -> infeasible
  4. fridge door edge must stay touch-free (a shelf behind it is rejected)
"""

import json
import os
import sys

from layout_solver import Problem, Solver, validate_result

OUT = "outputs/tests"
os.makedirs(OUT, exist_ok=True)


def square_room(size, door, inward, items):
    boundary = [[0, 0], [size, 0], [size, size], [0, size]]
    return {
        "boundary": boundary,
        "door": door,
        "isOpenInward": inward,
        "algoToPlace": items,
    }


def run(name, data, expect_feasible, expect_flush=None):
    problem = Problem(data)
    result = Solver(problem).solve()
    ok, _ = validate_result(data, result, report=lambda m: print("   " + m))
    assert result["feasible"] == expect_feasible, "{}: expected feasible={} got {}".format(
        name,
        expect_feasible,
        result["feasible"],
    )
    assert ok, f"{name}: validation failed"
    if expect_flush is not None:
        assert result.get("allItemsWallFlush") is expect_flush, (
            f"{name}: expected allItemsWallFlush={expect_flush}"
        )
    with open(os.path.join(OUT, name + ".result.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print("PASS {} (feasible={})".format(name, result["feasible"]))


# 1. roomy room, everything fits against the walls
run(
    "roomy",
    square_room(
        6000,
        [[6000, 2000], [6000, 3000]],
        False,
        {
            "fridge": [1220, 1330],
            "shelf-1": [1000, 400],
            "shelf-2": [1000, 400],
            "overShelf-1": [600, 400],
        },
    ),
    expect_feasible=True,
    expect_flush=True,
)

# 2. fridge simply does not fit (1200 < 1220 in every orientation)
run(
    "too-small",
    square_room(1200, [[1200, 400], [1200, 800]], False, {"fridge": [1220, 1330]}),
    expect_feasible=False,
)

# 3. inward door: a 900 mm swing square fills the doorway wall. The leftover
#    strips (395 mm above/below the zone, 350 mm to its right) are all narrower
#    than the 400 mm shelf depth, so nothing can be placed - yet total free
#    area (1.3 m^2) exceeds the shelves' area, so only the door rule explains
#    the infeasibility.
run(
    "door-swing-blocks",
    {
        "boundary": [[0, 0], [1250, 0], [1250, 1690], [0, 1690]],
        "door": [[0, 395], [0, 1295]],
        "isOpenInward": True,
        "algoToPlace": {"shelf-1": [1000, 400], "shelf-2": [1000, 400]},
    },
    expect_feasible=False,
)

# 4. the fridge door edge strip: the room leaves only 300 mm right of the
#    610 mm clearance strip - too narrow for the shelf - so neither 1220 nor
#    610 mm is possible; the solver must fall back to the bare
#    "nothing touches the door edge" rule (2 mm) and report 0.
run(
    "fridge-door-edge",
    {
        "boundary": [[0, 0], [2130, 0], [2130, 1330], [0, 1330]],
        "door": [[2130, 400], [2130, 1000]],
        "isOpenInward": False,
        "algoToPlace": {"fridge": [1220, 1330], "shelf-1": [1000, 400]},
    },
    expect_feasible=True,
)
data = {
    "boundary": [[0, 0], [2130, 0], [2130, 1330], [0, 1330]],
    "door": [[2130, 400], [2130, 1000]],
    "isOpenInward": False,
    "algoToPlace": {"fridge": [1220, 1330], "shelf-1": [1000, 400]},
}
res = Solver(Problem(data)).solve()
assert res["fridgeDoorClearanceMm"] == 0.0, (
    "fridge-door-edge: expected fallback clearance 0, got {}".format(res["fridgeDoorClearanceMm"])
)
print("PASS fridge-door-edge clearance fallback (0 mm)")

print("ALL TESTS PASSED")
sys.exit(0)
