"""Exact escape stubs (docs/off-grid-exact-fit-design.md, part 2).

Some pins escape only by an exact fit: a path whose clearances are all at the
rule and whose turns sit off the routing grid, which the grid search cannot
place. For a pin whose probe is stuck, `exact_escapes` searches octilinear
stubs from the pad's centre in exact geometry, each ending on an open grid
cell E:

- straight along the pin row's outward normal n, to E;
- along n for a length t, a 45 degree turn to either side, then along n
  again to E (the last leg of length 0 when the turn ends on E).

A diagonal that ends on a grid point lies on a grid diagonal, which the grid
search has anyway; the leg back along n is what lets the diagonal sit on any
line. For a given E and turn, t is the only free length. Each foreign item's
gap to the stub is a convex function of t (the diagonal slides along n), so
the lengths at which an item is too close form one interval; the legal t
are what the straight legs allow minus the union of those intervals, found
by ternary search and bisection to 1e-7 mm. An exact fit whose window is a
micrometre wide is found.

A stub is legal when, at the net's track width, it keeps the pairwise
clearance to every foreign pad (its real copper), track and via on its
layer, exactly at the rule allowed (the 1e-6 mm tie the rasterisers use).
The legal stubs are returned shortest first, one per end cell; the caller
offers their ends to the search as extra endpoints and keeps the stub whose
end the route used.
"""
from __future__ import annotations

import math
from typing import List, Optional, Tuple

import routing_defaults as defaults
from check_drc import (_expand_cu, check_pad_segment_overlap, check_segment_overlap,
                       check_via_segment_overlap)
from kicad_parser import Segment

_TIE = 1e-6           # mm: a stub exactly at the rule is legal
_EPS = 1e-7           # mm: the resolution lengths are solved to
_BIG = 10.0           # mm: added to a clearance so the checks report any gap


def _row_normal(pcb_data, pad, max_pitch: float) -> Optional[Tuple[float, float]]:
    """The outward normal of the fine-pitch row `pad` is on, or None. The
    rows are found once per board and pitch."""
    cache = getattr(pcb_data, '_exact_escape_rows', None)
    if cache is None or cache[0] != max_pitch:
        from fan_order import find_fan_rows
        normals = {}
        for row in find_fan_rows(pcb_data, max_pitch):
            for p in row.pads:
                normals[(row.ref, p.pad_number, round(p.global_x, 6), round(p.global_y, 6))] = row.normal
        cache = (max_pitch, normals)
        pcb_data._exact_escape_rows = cache
    return cache[1].get((pad.component_ref, pad.pad_number,
                         round(pad.global_x, 6), round(pad.global_y, 6)))


class _Copper:
    """The foreign copper on one layer near a pad, each item with its
    clearance and the box outside which it cannot touch a track."""

    def __init__(self, pcb_data, net_id, layer, routing_layers, config, cx, cy, radius):
        own = config.obstacle_clearance(net_id)
        self.items = []         # (kind, item, clearance, x0, y0, x1, y1)
        for fp in pcb_data.footprints.values():
            for p in fp.pads:
                if (p.net_id == net_id and net_id) or layer not in _expand_cu(p.layers, routing_layers):
                    continue
                if abs(p.global_x - cx) > radius or abs(p.global_y - cy) > radius:
                    continue
                c = max(own, config.obstacle_clearance(p.net_id),
                        getattr(p, 'local_clearance', 0.0) or 0.0)
                r = math.hypot(p.size_x, p.size_y) / 2
                for poly in getattr(p, 'polygons', None) or ():
                    for qx, qy in poly:
                        r = max(r, math.hypot(qx - p.global_x, qy - p.global_y))
                self._add('pad', p, c, p.global_x - r, p.global_y - r, p.global_x + r, p.global_y + r)
        for t in pcb_data.segments:
            if t.net_id == net_id or t.layer != layer:
                continue
            h = t.width / 2
            x0, x1 = min(t.start_x, t.end_x) - h, max(t.start_x, t.end_x) + h
            y0, y1 = min(t.start_y, t.end_y) - h, max(t.start_y, t.end_y) + h
            if x0 > cx + radius or x1 < cx - radius or y0 > cy + radius or y1 < cy - radius:
                continue
            self._add('seg', t, max(own, config.obstacle_clearance(t.net_id)), x0, y0, x1, y1)
        for v in pcb_data.vias:
            if v.net_id == net_id or abs(v.x - cx) > radius or abs(v.y - cy) > radius:
                continue
            h = v.size / 2
            self._add('via', v, max(own, config.obstacle_clearance(v.net_id)),
                      v.x - h, v.y - h, v.x + h, v.y + h)
        self.routing_layers = routing_layers

    def _add(self, kind, item, c, x0, y0, x1, y1):
        self.items.append((kind, item, c, x0 - c, y0 - c, x1 + c, y1 + c))

    def near(self, x0, y0, x1, y1):
        """The items whose boxes meet the box (x0, y0)-(x1, y1)."""
        return [e for e in self.items if not (x1 < e[3] or x0 > e[5] or y1 < e[4] or y0 > e[6])]

    def overlap(self, entry, seg: Segment) -> float:
        """How far `seg` comes inside the entry's clearance (mm; negative is
        the gap to spare)."""
        kind, it, c = entry[0], entry[1], entry[2]
        big = c + _BIG
        if kind == 'pad':
            r = check_pad_segment_overlap(it, seg, big, self.routing_layers, 1e-12)
        elif kind == 'seg':
            r = check_segment_overlap(seg, it, big, 1e-12)
        else:
            r = check_via_segment_overlap(it, seg, big, 1e-12)
        return (r[1] - _BIG) if r[0] else -_BIG

    def worst(self, seg: Segment) -> float:
        """The most `seg` comes inside any item's clearance (mm; negative is
        the least gap to spare)."""
        h = seg.width / 2
        es = self.near(min(seg.start_x, seg.end_x) - h, min(seg.start_y, seg.end_y) - h,
                       max(seg.start_x, seg.end_x) + h, max(seg.start_y, seg.end_y) + h)
        return max((self.overlap(e, seg) for e in es), default=-_BIG)

    def legal(self, seg: Segment) -> bool:
        """Whether `seg` keeps its clearance to every item, exactly at the rule
        allowed."""
        h = seg.width / 2
        for e in self.near(min(seg.start_x, seg.end_x) - h, min(seg.start_y, seg.end_y) - h,
                           max(seg.start_x, seg.end_x) + h, max(seg.start_y, seg.end_y) + h):
            kind, it, c = e[0], e[1], e[2]
            if kind == 'pad':
                bad = check_pad_segment_overlap(it, seg, c, self.routing_layers, _TIE / c)[0]
            elif kind == 'seg':
                bad = check_segment_overlap(seg, it, c, _TIE / c)[0]
            else:
                bad = check_via_segment_overlap(it, seg, c, _TIE / c)[0]
            if bad:
                return False
        return True


def _turn(n, sign):
    """`n` turned by 45 degrees; sign +1 or -1 picks the side."""
    c = math.sqrt(0.5)
    return (c * (n[0] - sign * n[1]), c * (sign * n[0] + n[1]))


def _longest(legal_at, top: float) -> float:
    """The longest length in [0, top] at which a leg growing from a fixed
    end is legal (legality only shrinks as it grows); -1 when not even a
    point is."""
    if not legal_at(1e-6):
        return -1.0
    if legal_at(top):
        return top
    lo, hi = 0.0, top
    while hi - lo > _EPS:
        mid = (lo + hi) / 2
        if legal_at(mid):
            lo = mid
        else:
            hi = mid
    return lo


def _violated(f, lo: float, hi: float):
    """The interval of t in [lo, hi] where the concave `f` (an overlap) is
    above the tie, or None."""
    a, b = lo, hi
    while b - a > _EPS:             # ternary search for the peak
        m1, m2 = a + (b - a) / 3, b - (b - a) / 3
        if f(m1) < f(m2):
            a = m1
        else:
            b = m2
    peak = (a + b) / 2
    if f(peak) <= _TIE:
        return None

    def edge(inside, outside):
        if f(outside) > _TIE:
            return outside
        while abs(outside - inside) > _EPS:
            mid = (inside + outside) / 2
            if f(mid) > _TIE:
                inside = mid
            else:
                outside = mid
        return outside

    return (edge(peak, lo), edge(peak, hi))


def _pocket(start_cells, is_open, box):
    """The cells the grid search can reach from `start_cells` within `box`
    (gx0, gy0, gx1, gy1), per layer: open cells joined orthogonally, or
    diagonally where both cells beside the step are open too (so it counts
    no more than the search reaches)."""
    gx0, gy0, gx1, gy1 = box
    seen = set(start_cells)
    todo = list(start_cells)
    while todo:
        x, y, li = todo.pop()
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)):
            c = (x + dx, y + dy, li)
            if c in seen or not (gx0 <= c[0] <= gx1 and gy0 <= c[1] <= gy1):
                continue
            if not is_open(*c):
                continue
            if dx and dy and not (is_open(x + dx, y, li) and is_open(x, y + dy, li)):
                continue
            seen.add(c)
            todo.append(c)
    return seen


def walled_by_routed(pcb_data, net_id: int, config, coord, layer_names, is_open, start_cells,
                     reach: float = None) -> bool:
    """Whether any blocked cell walling in the pocket reachable from
    `start_cells` is blocked by copper this run routed: a foreign track or
    via with no uuid (a board file's copper carries one; the router's new
    copper has none until it is written). Such a wall can be ripped up and
    rerouted, which leaves the pin its ordinary lane; an exact stub squeezed
    past it takes that lane's room from the pins after it (measured on the
    cap sweep: P20 squeezed past P9's new track, three later pins failed).
    Exact stubs are for pins walled in by copper that stays."""
    from geometry_utils import point_to_segment_distance
    reach = defaults.EXACT_ESCAPE_REACH if reach is None else reach
    g = config.grid_step
    cells = [tuple(c[:3]) for c in start_cells]
    if not cells:
        return False
    xs = [c[0] for c in cells]
    ys = [c[1] for c in cells]
    r = int(math.ceil(reach / g)) + 1
    box = (min(xs) - r, min(ys) - r, max(xs) + r, max(ys) + r)
    pocket = _pocket(cells, is_open, box)
    wall = set()
    for x, y, li in pocket:
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                c = (x + dx, y + dy, li)
                if c not in pocket and not is_open(*c):
                    wall.add(c)
    if not wall:
        return False
    own = config.obstacle_clearance(net_id)
    segs = [s for s in pcb_data.segments if not s.uuid and s.net_id != net_id]
    vias = [v for v in pcb_data.vias if not v.uuid and v.net_id != net_id]
    for gx, gy, li in wall:
        x, y = coord.to_float(gx, gy)
        layer = layer_names[li]
        w = config.get_net_track_width(net_id, layer)
        for s in segs:
            if s.layer != layer:
                continue
            c = max(own, config.obstacle_clearance(s.net_id))
            if point_to_segment_distance(x, y, s.start_x, s.start_y, s.end_x, s.end_y) < s.width / 2 + w / 2 + c + 1e-6:
                return True
        for v in vias:
            c = max(own, config.obstacle_clearance(v.net_id))
            if math.hypot(x - v.x, y - v.y) < v.size / 2 + w / 2 + c + 1e-6:
                return True
    return False


def exact_escapes(pcb_data, net_id: int, pad, config, coord,
                  layer_names: List[str], is_open=None, start_cells=(),
                  toward=None, reach: float = None, limit: int = None
                  ) -> List[Tuple[Tuple[int, int, int], List[Segment]]]:
    """Legal escape stubs from `pad`: [((gx, gy, layer index), segments)],
    shortest first (among equals, the end nearer `toward`, an (x, y)), at
    most `limit`, one per end cell. `is_open(gx, gy, layer index)` says
    whether a grid cell may end a stub (the obstacle map's test; None: every
    cell). A stub is only offered where the grid search could not go: its
    end outside the pocket reachable from `start_cells` (the stuck side's
    endpoint cells). Empty when the pad is not on a fine-pitch row or no
    stub fits."""
    reach = defaults.EXACT_ESCAPE_REACH if reach is None else reach
    limit = defaults.EXACT_ESCAPE_ENDS if limit is None else limit
    max_pitch = defaults.FAN_ORDER_MAX_PITCH_FACTOR * (config.track_width + config.clearance)
    n = _row_normal(pcb_data, pad, max_pitch)
    if n is None:
        return []
    px, py = pad.global_x, pad.global_y
    g = config.grid_step
    pad_layers = set(_expand_cu(pad.layers, layer_names))
    box = (int(math.floor((px - reach) / g)) - 1, int(math.floor((py - reach) / g)) - 1,
           int(math.ceil((px + reach) / g)) + 1, int(math.ceil((py + reach) / g)) + 1)
    pocket = _pocket(start_cells, is_open, box) if (is_open is not None and start_cells) else set()
    found = []
    for li, layer in enumerate(layer_names):
        if layer not in pad_layers:
            continue
        w = config.get_net_track_width(net_id, layer)
        copper = _Copper(pcb_data, net_id, layer, layer_names, config, px, py, reach + 2.0)

        def seg(ax, ay, bx, by):
            return Segment(start_x=ax, start_y=ay, end_x=bx, end_y=by, width=w,
                           layer=layer, net_id=net_id)

        l1_max = _longest(lambda t: copper.legal(seg(px, py, px + n[0] * t, py + n[1] * t)), reach)
        if l1_max < 0:
            continue

        cands = []      # (length, distance to `toward`, gx, gy, spec)
        gx0, gx1 = int(math.floor((px - reach) / g)), int(math.ceil((px + reach) / g))
        gy0, gy1 = int(math.floor((py - reach) / g)), int(math.ceil((py + reach) / g))
        for gx in range(gx0, gx1 + 1):
            for gy in range(gy0, gy1 + 1):
                ex, ey = coord.to_float(gx, gy)
                dx, dy = ex - px, ey - py
                if dx * dx + dy * dy > reach * reach or dx * n[0] + dy * n[1] <= 0:
                    continue
                if (is_open is not None and not is_open(gx, gy, li)) or (gx, gy, li) in pocket:
                    continue
                rank = math.hypot(toward[0] - ex, toward[1] - ey) if toward is not None else 0.0
                if abs(dx * n[1] - dy * n[0]) < 1e-9:
                    cands.append((dx * n[0] + dy * n[1], rank, gx, gy, None))
                    continue
                for sign in (1, -1):
                    d = _turn(n, sign)
                    det = n[0] * d[1] - n[1] * d[0]
                    a = (dx * d[1] - dy * d[0]) / det       # along the normal, both legs
                    b = (n[0] * dy - n[1] * dx) / det       # along the turn
                    if a < -1e-9 or b <= 1e-9:
                        continue
                    cands.append((a + b, rank, gx, gy, (max(a, 0.0), b, d)))
        cands.sort(key=lambda c: (round(c[0], 6), c[1]))

        seen = set()
        mine = []
        for length, _rank, gx, gy, spec in cands:
            if len(mine) >= limit:
                break
            if (gx, gy) in seen:
                continue
            ex, ey = coord.to_float(gx, gy)
            if spec is None:
                legs = [(px, py, ex, ey)] if length <= l1_max else None
            else:
                legs = _turned(copper, seg, px, py, ex, ey, n, *spec, l1_max)
            if legs is not None:
                seen.add((gx, gy))
                mine.append((length, (gx, gy, li), [seg(*q) for q in legs]))
        found += mine
    found.sort(key=lambda f: f[0])
    return [(end, segs) for _l, end, segs in found[:limit]]


def _turned(copper, seg, px, py, ex, ey, n, a, b, d, l1_max):
    """The legs of a legal stub along n for t, along d for b, then along n
    to (ex, ey), with t the largest legal length (no last leg when t = a).
    None when no t is legal."""
    # the last leg grows back from E as t shrinks
    l3_max = _longest(lambda s: copper.legal(seg(ex - n[0] * s, ey - n[1] * s, ex, ey)), a)
    if l3_max < 0:
        return None
    lo, hi = max(0.0, a - l3_max), min(a, l1_max)
    if lo > hi:
        return None

    def diag(t):
        cx, cy = px + n[0] * t, py + n[1] * t
        return seg(cx, cy, cx + d[0] * b, cy + d[1] * b)

    s_lo, s_hi = diag(lo), diag(hi)
    h = s_lo.width / 2
    xs = (s_lo.start_x, s_lo.end_x, s_hi.start_x, s_hi.end_x)
    ys = (s_lo.start_y, s_lo.end_y, s_hi.start_y, s_hi.end_y)
    bad = []
    for e in copper.near(min(xs) - h, min(ys) - h, max(xs) + h, max(ys) + h):
        iv = _violated(lambda t, e=e: copper.overlap(e, diag(t)), lo, hi)
        if iv is not None:
            bad.append(iv)
    bad.sort()
    # the legal windows: [lo, hi] minus the union of the violated intervals
    windows, at = [], lo
    for v0, v1 in bad:
        if v0 > at:
            windows.append((at, v0))
        at = max(at, v1)
    if at <= hi:
        windows.append((at, hi))
    # in the highest window: the turn landing on E if it can, else the
    # window's middle, else its ends; the first with no overlap at all, else
    # the legal one with the least (a fit exactly at the rule)
    for w0, w1 in reversed(windows):
        best = None
        for t in ((a,) if w1 >= a - 1e-12 else ()) + ((w0 + w1) / 2, w1, w0):
            cx1, cy1 = px + n[0] * t, py + n[1] * t
            cx2, cy2 = cx1 + d[0] * b, cy1 + d[1] * b
            legs = ([(px, py, cx1, cy1)] if t > 1e-9 else []) + [(cx1, cy1, cx2, cy2)]
            if a - t > 1e-9:
                legs.append((cx2, cy2, ex, ey))
            if not all(copper.legal(seg(*q)) for q in legs):
                continue
            worst = max(copper.worst(seg(*q)) for q in legs)
            if worst <= 0:
                return legs
            if best is None or worst < best[0]:
                best = (worst, legs)
        if best is not None:
            return best[1]
    return None
