"""A pad's corner guards (docs/corner-move-check-design.md), per pad shape,
against the pad's exact copper:

- no over-block: every point inside a guard is nearer the pad than the margin;
- no miss: a one-step grid move between two cells whose centres are at least
  the margin from the pad, and whose segment comes nearer than the margin,
  passes inside a guard.
"""
import math
import os
import random
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'py_router'))
from kicad_parser import Pad  # noqa: E402
from routing_utils import pad_corner_guards  # noqa: E402

STEP = 0.1
MARGIN = 0.3
DIRS = [(1, 0), (0, 1), (1, 1), (1, -1)]


def _pad(shape, sx, sy, x=50.037, y=40.061, rratio=0.0, rot=0.0, polygons=None):
    return Pad('U1', '1', x, y, 0.0, 0.0, sx, sy, shape, ['F.Cu'], 1, 'A',
               roundrect_rratio=rratio, rect_rotation=rot, polygons=polygons)


def _corner_radius(p):
    if p.shape in ('circle', 'oval'):
        return min(p.size_x, p.size_y) / 2
    if p.shape == 'roundrect':
        return p.roundrect_rratio * min(p.size_x, p.size_y)
    return 0.0


def _seg_pt(ax, ay, bx, by, px, py):
    dx, dy = bx - ax, by - ay
    l2 = dx * dx + dy * dy
    t = 0.0 if l2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / l2))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def _inside(poly, x, y):
    n, c = len(poly), False
    for i in range(n):
        (x1, y1), (x2, y2) = poly[i], poly[(i + 1) % n]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            c = not c
    return c


def _inner(p):
    """(polygon, radius): the pad is the points within `radius` of `polygon`
    (a custom pad: its outline and 0; a rounded rect: its inner rect, which may
    be a segment or a point, and the corner radius)."""
    if p.polygons:
        return p.polygons[0], 0.0
    cr = _corner_radius(p)
    ex, ey = max(p.size_x / 2 - cr, 0.0), max(p.size_y / 2 - cr, 0.0)
    a = math.radians(p.rect_rotation)
    c, s = math.cos(a), math.sin(a)
    pts = [(p.global_x + lx * c - ly * s, p.global_y + lx * s + ly * c)
           for lx, ly in ((-ex, -ey), (ex, -ey), (ex, ey), (-ex, ey))]
    return pts, cr


def _cross(ax, ay, bx, by, cx, cy, dx, dy):
    def o(px, py, qx, qy, rx, ry):
        return (qx - px) * (ry - py) - (qy - py) * (rx - px)
    d1, d2 = o(cx, cy, dx, dy, ax, ay), o(cx, cy, dx, dy, bx, by)
    d3, d4 = o(ax, ay, bx, by, cx, cy), o(ax, ay, bx, by, dx, dy)
    return ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0))


def _seg_seg(a, b, c, d):
    if _cross(*a, *b, *c, *d):
        return 0.0
    return min(_seg_pt(*c, *d, *a), _seg_pt(*c, *d, *b), _seg_pt(*a, *b, *c), _seg_pt(*a, *b, *d))


def seg_dist(p, a, b):
    """Exact distance from the segment a-b to the pad's copper."""
    poly, r = _inner(p)
    if len({tuple(q) for q in poly}) >= 3 and (_inside(poly, *a) or _inside(poly, *b)):
        return 0.0
    n = len(poly)
    d = min(_seg_seg(a, b, poly[k], poly[(k + 1) % n]) for k in range(n))
    return max(d - r, 0.0)


def dist(p, x, y):
    return seg_dist(p, (x, y), (x, y))


PADS = {
    'rect': _pad('rect', 0.665, 0.2),
    'roundrect': _pad('roundrect', 0.9, 0.5, rratio=0.25),
    'circle': _pad('circle', 0.6, 0.6),
    'oval': _pad('oval', 1.2, 0.5),
    'rotated rect': _pad('rect', 0.8, 0.3, rot=30.0),
    'custom polygon': _pad('custom', 1.0, 1.0, polygons=[[(49.6, 39.7), (50.5, 39.7), (50.5, 40.0),
                                                          (50.1, 40.0), (50.1, 40.4), (49.6, 40.4)]]),
}


def _guards_mm(p):
    return [(gx * STEP, gy * STEP, r * STEP) for gx, gy, r in pad_corner_guards(p, STEP, MARGIN)]


def test_nothing_inside_a_guard_is_legal():
    rng = random.Random(3)
    for name, p in PADS.items():
        guards = _guards_mm(p)
        assert guards, name
        for gx, gy, r in guards:
            for _ in range(400):
                a, rr = rng.uniform(0, 2 * math.pi), r * math.sqrt(rng.random())
                x, y = gx + rr * math.cos(a), gy + rr * math.sin(a)
                assert dist(p, x, y) < MARGIN, (name, x, y)


def _moved(p, dx, dy):
    q = Pad(p.component_ref, p.pad_number, p.global_x + dx, p.global_y + dy, 0.0, 0.0, p.size_x, p.size_y,
            p.shape, p.layers, p.net_id, p.net_name, roundrect_rratio=p.roundrect_rratio,
            rect_rotation=p.rect_rotation,
            polygons=[[(x + dx, y + dy) for x, y in poly] for poly in p.polygons] if p.polygons else None)
    return q


def test_every_clipping_move_between_legal_cells_meets_a_guard():
    rng = random.Random(11)
    for name, p0 in PADS.items():
        clips = 0
        for _ in range(250):
            p = _moved(p0, rng.uniform(0, STEP), rng.uniform(0, STEP))
            guards = _guards_mm(p)
            cx, cy = round(p.global_x / STEP), round(p.global_y / STEP)
            for gx in range(cx - 10, cx + 11):
                for gy in range(cy - 10, cy + 11):
                    a = (gx * STEP, gy * STEP)
                    da = dist(p, *a)
                    if da < MARGIN or da > MARGIN + 0.15:
                        continue                    # illegal, or too far for a 0.141 mm step to reach
                    for dx, dy in DIRS + [(-x, -y) for x, y in DIRS]:
                        b = ((gx + dx) * STEP, (gy + dy) * STEP)
                        if dist(p, *b) < MARGIN:
                            continue
                        if seg_dist(p, a, b) < MARGIN - 1e-6:
                            clips += 1
                            assert any(_seg_pt(a[0], a[1], b[0], b[1], x, y) < r for x, y, r in guards), (name, a, b)
        print("  %-15s %d clipping moves, all guarded" % (name, clips))
        assert clips > 0, name


if __name__ == '__main__':
    test_nothing_inside_a_guard_is_legal()
    test_every_clipping_move_between_legal_cells_meets_a_guard()
    print("PASS")
