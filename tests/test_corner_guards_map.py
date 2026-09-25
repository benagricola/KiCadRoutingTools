"""Corner guards in the Rust obstacle map (docs/corner-move-check-design.md).

A guard is a circle (gx, gy, r) in grid units on one layer. move_clips_corner
says whether a one-step move's segment passes nearer a guard's centre than its
radius plus the move's own margin (the caller's radius already carries the
rule's tie, so a move exactly at it stays legal): checked here
against a brute-force distance over random guards and moves. Guards are
refcounted like blocked cells, and copies of the map carry them.
"""
import math
import os
import random
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'rust_router'))
from grid_router import GridObstacleMap  # noqa: E402

TIE = 1e-9              # float noise, grid units; the caller's radii carry the rule's own tie
DIRS = [(1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)]


def seg_point(ax, ay, bx, by, px, py):
    dx, dy = bx - ax, by - ay
    l2 = dx * dx + dy * dy
    t = 0.0 if l2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / l2))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def brute(guards, gx1, gy1, gx2, gy2, layer, extra):
    return any(g[3] == layer and seg_point(gx1, gy1, gx2, gy2, g[0], g[1]) < g[2] + extra - TIE for g in guards)


def rows(guards):
    return np.array(guards, dtype=np.float64).reshape(-1, 4)


def test_the_move_check_is_the_exact_distance():
    rng = random.Random(7)
    guards = [(rng.uniform(0, 20), rng.uniform(0, 20), rng.uniform(0.5, 4.0), rng.choice((0, 1)))
              for _ in range(60)]
    m = GridObstacleMap(2)
    m.add_corner_guards_batch(rows(guards))
    hits = 0
    for _ in range(20000):
        gx, gy = rng.randint(-3, 23), rng.randint(-3, 23)
        dx, dy = rng.choice(DIRS)
        layer = rng.choice((0, 1))
        extra = rng.choice((0.0, 0.0, 0.5))
        want = brute(guards, gx, gy, gx + dx, gy + dy, layer, extra)
        got = m.move_clips_corner(gx, gy, gx + dx, gy + dy, layer, extra)
        assert got == want, (gx, gy, dx, dy, layer, extra)
        hits += want
    assert hits > 500


def test_a_move_exactly_at_the_radius_is_legal():
    m = GridObstacleMap(1)
    m.add_corner_guards_batch(rows([(5.0, 5.0, 3.0, 0)]))
    assert not m.move_clips_corner(2, 4, 2, 5, 0, 0.0)      # the segment x = 2 is 3.0 from the centre
    assert m.move_clips_corner(3, 4, 3, 5, 0, 0.0)


def test_guards_are_refcounted_and_copied():
    g = rows([(5.0, 5.0, 2.0, 0), (9.5, 4.25, 1.5, 0)])
    m = GridObstacleMap(1)
    m.add_corner_guards_batch(g)
    m.add_corner_guards_batch(g[:1])
    assert m.corner_guard_count() == 3
    c = m.clone_fresh()
    assert c.move_clips_corner(5, 3, 6, 4, 0, 0.0) and m.clone().move_clips_corner(5, 3, 6, 4, 0, 0.0)
    m.remove_corner_guards_batch(g)
    assert m.corner_guard_count() == 1
    assert m.move_clips_corner(5, 3, 6, 4, 0, 0.0)          # the second copy of the first guard
    m.remove_corner_guards_batch(g[:1])
    assert m.corner_guard_count() == 0
    assert not m.move_clips_corner(5, 3, 6, 4, 0, 0.0)
    assert c.corner_guard_count() == 3                      # the copy kept its own


if __name__ == '__main__':
    test_the_move_check_is_the_exact_distance()
    test_a_move_exactly_at_the_radius_is_legal()
    test_guards_are_refcounted_and_copied()
    print("PASS")
