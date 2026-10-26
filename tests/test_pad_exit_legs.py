#!/usr/bin/env python3
"""Fork: a track leaves an elongated pad along the pad's long axis.

A route ended on its pad's centre but could turn there, so on a long thin pad
the track crossed the pad at an angle. The track from the centre now runs
along the long axis until its copper is clear of the pad end, then rejoins the
route turning no more than 45 degrees at each bend, with the fewest bends.

    python3 tests/test_pad_exit_legs.py
"""
import math
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, 'py_router'))
sys.path.insert(0, os.path.join(REPO, 'py_tools'))

from kicad_parser import Pad, Net, PCBData, BoardInfo, Segment, Footprint
from pcb_modification import pad_exit_legs
from routing_config import GridRouteConfig

fails = []
W = 0.127


def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (f"  {detail}" if detail else ""))
    if not cond:
        fails.append(name)


def _pad(ref, x, y, net_id, net_name, sx, sy):
    return Pad(component_ref=ref, pad_number='1', global_x=x, global_y=y,
               local_x=0.0, local_y=0.0, size_x=sx, size_y=sy, shape='rect',
               layers=['F.Cu'], net_id=net_id, net_name=net_name, drill=0, pad_type='smd')


def _board(sx=0.3, sy=1.25, foreign=None):
    """A pad at (10, 10); its route turns 45 degrees at the centre, runs to
    (10.5, 10.5) and down to a pad at (10.5, 14)."""
    segs = [Segment(start_x=10.0, start_y=10.0, end_x=10.5, end_y=10.5, width=W,
                    layer='F.Cu', net_id=1),
            Segment(start_x=10.5, start_y=10.5, end_x=10.5, end_y=14.0, width=W,
                    layer='F.Cu', net_id=1)]
    pads = {1: [_pad('U1', 10.0, 10.0, 1, '/SIG', sx, sy),
                _pad('U2', 10.5, 14.0, 1, '/SIG', 0.5, 0.5)]}
    if foreign:
        pads[2] = [_pad('C9', foreign[0], foreign[1], 2, '/OTHER', 0.3, 0.3)]
    pcb = PCBData(footprints={}, nets={1: Net(1, '/SIG'), 2: Net(2, '/OTHER')},
                  segments=segs, vias=[],
                  board_info=BoardInfo(layers={}, copper_layers=['F.Cu', 'B.Cu'],
                                       board_bounds=(0.0, 0.0, 200.0, 200.0)),
                  pads_by_net=pads)
    cfg = GridRouteConfig(track_width=W, clearance=0.127, via_size=0.45, via_drill=0.2,
                          layers=['F.Cu', 'B.Cu'])
    return pcb, cfg


def _polyline(pcb):
    """The net's copper walked from (10, 10)."""
    segs = [s for s in pcb.segments if s.net_id == 1]
    pts = [(10.0, 10.0)]
    while segs:
        cur = pts[-1]
        nxt = None
        for s in segs:
            if math.hypot(s.start_x - cur[0], s.start_y - cur[1]) < 1e-6:
                nxt = (s, (s.end_x, s.end_y))
            elif math.hypot(s.end_x - cur[0], s.end_y - cur[1]) < 1e-6:
                nxt = (s, (s.start_x, s.start_y))
            if nxt:
                break
        if not nxt:
            break
        segs.remove(nxt[0])
        pts.append(nxt[1])
    return pts, segs


def test_track_leaves_along_the_long_axis():
    pcb, cfg = _board()
    n, _strip, _added = pad_exit_legs([], pcb, None, cfg)
    check("one pad changed", n == 1, n)
    pts, rest = _polyline(pcb)
    check("the copper is one walk from pad to pad", not rest and pts[-1] == (10.5, 14.0), pts)
    first = math.hypot(pts[1][0] - pts[0][0], pts[1][1] - pts[0][1])
    check("the first leg runs down the pad's long axis",
          abs(pts[1][0] - 10.0) < 1e-9 and pts[1][1] > 10.0, pts[1])
    check("it ends clear of the pad", first >= 1.25 / 2 + W / 2 - 1e-6, round(first, 4))
    turns = []
    for a, b, c in zip(pts, pts[1:], pts[2:]):
        u = (b[0] - a[0], b[1] - a[1])
        v = (c[0] - b[0], c[1] - b[1])
        cosang = (u[0] * v[0] + u[1] * v[1]) / (math.hypot(*u) * math.hypot(*v))
        turns.append(math.degrees(math.acos(max(-1.0, min(1.0, cosang)))))
    check("no bend turns more than 45 degrees", all(t <= 45.0 + 0.1 for t in turns),
          [round(t, 1) for t in turns])
    check("the track takes one 45-degree turn, not a jog",
          sum(1 for t in turns if t > 0.1) == 1, [round(t, 1) for t in turns])


def test_square_pad_is_left_alone():
    pcb, cfg = _board(sx=0.5, sy=0.5)
    n, _strip, _added = pad_exit_legs([], pcb, None, cfg)
    check("a square pad keeps its route", n == 0, n)


def test_blocked_exit_is_left_alone():
    pcb, cfg = _board(foreign=(10.0, 11.05))
    n, _strip, _added = pad_exit_legs([], pcb, None, cfg)
    check("an exit leg into foreign copper is not laid", n == 0, n)
    check("the route is unchanged", len(pcb.segments) == 2)


def test_two_pad_part_is_entered_through_its_outer_end():
    """A resistor along x at (12, 10)-(12.6, 10); its pad 1 track arrives from
    the left 0.1 mm off the resistor's axis and steps into the pad at 45
    degrees. It should step earlier and enter pad 1 along the axis, from the
    left (the end away from pad 2)."""
    r1 = _pad('R1', 12.0, 10.0, 1, '/SIG', 0.46, 0.4)
    r2 = _pad('R1', 12.6, 10.0, 2, '/OTHER', 0.46, 0.4)
    r1.pad_number, r2.pad_number = '1', '2'
    src = _pad('U9', 6.0, 10.1, 1, '/SIG', 0.5, 0.5)
    segs = [Segment(start_x=6.0, start_y=10.1, end_x=11.9, end_y=10.1, width=W,
                    layer='F.Cu', net_id=1),
            Segment(start_x=11.9, start_y=10.1, end_x=12.0, end_y=10.0, width=W,
                    layer='F.Cu', net_id=1)]
    fp = Footprint(reference='R1', footprint_name='t:R', x=12.3, y=10.0, rotation=0.0,
                   layer='F.Cu', pads=[r1, r2])
    pcb = PCBData(footprints={'R1': fp}, nets={1: Net(1, '/SIG'), 2: Net(2, '/OTHER')},
                  segments=segs, vias=[],
                  board_info=BoardInfo(layers={}, copper_layers=['F.Cu', 'B.Cu'],
                                       board_bounds=(0.0, 0.0, 200.0, 200.0)),
                  pads_by_net={1: [src, r1], 2: [r2]})
    cfg = GridRouteConfig(track_width=W, clearance=0.127, via_size=0.45, via_drill=0.2,
                          layers=['F.Cu', 'B.Cu'])
    n, _strip, _added = pad_exit_legs([], pcb, None, cfg)
    check("the resistor pad changed", n == 1, n)
    into = [s for s in pcb.segments if s.net_id == 1 and
            (abs(s.end_x - 12.0) < 1e-6 and abs(s.end_y - 10.0) < 1e-6
             or abs(s.start_x - 12.0) < 1e-6 and abs(s.start_y - 10.0) < 1e-6)]
    check("one segment reaches the pad centre", len(into) == 1, len(into))
    if into:
        s = into[0]
        far = (s.start_x, s.start_y) if abs(s.end_x - 12.0) < 1e-6 else (s.end_x, s.end_y)
        check("it comes in along the resistor's axis from the outer end",
              abs(far[1] - 10.0) < 1e-9 and far[0] <= 12.0 - (0.23 + W / 2) + 1e-6, far)


def main():
    test_track_leaves_along_the_long_axis()
    test_square_pad_is_left_alone()
    test_blocked_exit_is_left_alone()
    test_two_pad_part_is_entered_through_its_outer_end()
    print(f"\n{len(fails)} failure(s)" if fails else "\nall passed")
    return 1 if fails else 0


def test_main():
    assert main() == 0


if __name__ == '__main__':
    sys.exit(main())
