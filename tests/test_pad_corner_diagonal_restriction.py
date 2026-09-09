#!/usr/bin/env python3
"""A pad's corner ring closes DIAGONAL travel, not the cell.

A cell in the corner region of a pad clears it by the margin measured centre to
centre. An axis-aligned step through that cell keeps exactly the margin - the
cell centre IS the track centre. Only a diagonal step is a hazard, because its
midpoint leaves the line the cell centres sit on and can come closer.

Blocking the cell outright, which is what the corner buffer used to do, closes
the straight path too. On a fine-pitch escape that is decisive: a 0.4 mm pitch
row with 0.2 mm pads leaves 0.30 mm from the escape axis to the neighbour's
edge against a demand of track/2 + clearance = 0.30 - legal by DRC, and walled
off by any buffer at all.

Run:  python3 tests/test_pad_corner_diagonal_restriction.py
"""

import os
import sys

import numpy as np

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_TESTS_DIR)
for _p in (_ROOT, os.path.join(_ROOT, 'py_router'), os.path.join(_ROOT, 'rust_router')):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from grid_router import GridObstacleMap

FAILURES = []


def check(cond, label):
    print(f"  {'PASS' if cond else 'FAIL'}  {label}")
    if not cond:
        FAILURES.append(label)


def test_the_two_planes_are_independent():
    m = GridObstacleMap(2)
    m.add_diag_blocked_cell(5, 5, 0)
    check(not m.is_blocked(5, 5, 0), "1: a diagonal-restricted cell is not blocked")
    check(m.is_diag_blocked(5, 5, 0), "1b: it is diagonal-restricted")
    m.add_blocked_cell(7, 7, 0)
    check(m.is_blocked(7, 7, 0) and not m.is_diag_blocked(7, 7, 0),
          "1c: an ordinary blocked cell is not diagonal-restricted")


def test_straight_through_diagonal_around():
    m = GridObstacleMap(2)
    m.add_diag_blocked_cell(5, 5, 0)
    check(not m.segment_blocked(4, 5, 5, 5, 0, 0.0), "2: a straight step in is allowed")
    check(not m.segment_blocked(5, 5, 6, 5, 0, 0.0), "2b: and a straight step out")
    check(m.segment_blocked(4, 4, 5, 5, 0, 0.0), "2c: a diagonal step in is refused")
    check(m.segment_blocked(5, 5, 6, 6, 0, 0.0), "2d: and a diagonal step out")


def test_a_lane_one_cell_wide_stays_walkable():
    """The escape case: a corridor of restricted cells is still a corridor."""
    m = GridObstacleMap(1)
    for y in range(10):
        m.add_diag_blocked_cell(5, y, 0)
    ok = all(not m.segment_blocked(5, y, 5, y + 1, 0, 0.0) for y in range(9))
    check(ok, "3: a one-cell lane of restricted cells walks end to end")
    check(m.segment_blocked(5, 4, 6, 5, 0, 0.0), "3b: but nothing leaves it diagonally")


def test_batch_matches_single():
    m1, m2 = GridObstacleMap(2), GridObstacleMap(2)
    pts = [(1, 2), (3, 4), (5, 6)]
    for x, y in pts:
        m1.add_diag_blocked_cell(x, y, 1)
    arr = np.array([[x, y, 1] for x, y in pts], dtype=np.int32)
    m2.add_diag_blocked_cells_batch(arr)
    same = all(m1.is_diag_blocked(x, y, 1) == m2.is_diag_blocked(x, y, 1) for x, y in pts)
    check(same, "4: the batch entry point agrees with the single one")
    check(not m2.is_diag_blocked(1, 2, 0), "4b: and respects the layer")


def test_the_ring_is_what_the_pad_pass_marks():
    """End to end through the obstacle builder: a pad's corner ring lands in the
    diagonal plane, and the cells within the margin land in the blocked one."""
    import obstacle_map as OM
    from routing_config import GridCoord
    import routing_utils as RU
    margin, step = 0.30, 0.1
    hard = RU.pad_blocked_cells_array(0, 0, 0.10, 0.335, margin, step, 0.0, 0.0)
    both = RU.pad_blocked_cells_array(0, 0, 0.10, 0.335, margin, step, 0.0, None)
    ring = OM._rows_not_in(both, hard)
    check(len(ring) > 0, "5: the corner ring is a non-empty set of cells")
    hs = {(int(a), int(b)) for a, b in hard}
    check(all((int(a), int(b)) not in hs for a, b in ring),
          "5b: and disjoint from the cells blocked outright")


def test_cache_add_then_remove_leaves_the_diagonal_plane_empty():
    """The per-net cache adds a net's rings and removes them to route that net.
    If the remove misses any of them the restriction leaks onto every net routed
    afterwards, silently and forever."""
    import numpy as np
    from obstacle_cache import (NetObstacleData, add_net_obstacles_from_cache,
                                remove_net_obstacles_from_cache)
    m = GridObstacleMap(2)
    cells = np.array([[1, 1, 0], [2, 2, 0], [3, 3, 1]], dtype=np.int32)
    data = NetObstacleData(diag_cells=cells)
    add_net_obstacles_from_cache(m, data)
    check(all(m.is_diag_blocked(int(a), int(b), int(l)) for a, b, l in cells),
          "6: the cache add marks every ring cell")
    remove_net_obstacles_from_cache(m, data)
    check(not any(m.is_diag_blocked(int(a), int(b), int(l)) for a, b, l in cells),
          "6b: and the remove leaves none of them behind")


def test_two_nets_sharing_a_ring_cell():
    """Overlapping rings: the first net to leave must not open the cell."""
    import numpy as np
    from obstacle_cache import (NetObstacleData, add_net_obstacles_from_cache,
                                remove_net_obstacles_from_cache)
    m = GridObstacleMap(1)
    shared = np.array([[4, 4, 0]], dtype=np.int32)
    a = NetObstacleData(diag_cells=shared)
    b = NetObstacleData(diag_cells=shared.copy())
    add_net_obstacles_from_cache(m, a)
    add_net_obstacles_from_cache(m, b)
    remove_net_obstacles_from_cache(m, a)
    check(m.is_diag_blocked(4, 4, 0), "7: the second net still holds the shared cell")
    remove_net_obstacles_from_cache(m, b)
    check(not m.is_diag_blocked(4, 4, 0), "7b: and it opens when both have gone")


if __name__ == '__main__':
    for fn in (test_the_two_planes_are_independent,
               test_straight_through_diagonal_around,
               test_a_lane_one_cell_wide_stays_walkable,
               test_batch_matches_single,
               test_the_ring_is_what_the_pad_pass_marks,
               test_cache_add_then_remove_leaves_the_diagonal_plane_empty,
               test_two_nets_sharing_a_ring_cell):
        print(fn.__name__)
        fn()
    print()
    if FAILURES:
        print("FAILED: %d" % len(FAILURES))
        for f in FAILURES:
            print("  -", f)
        sys.exit(1)
    print("all checks passed")
