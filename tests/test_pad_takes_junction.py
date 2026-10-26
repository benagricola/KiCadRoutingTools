#!/usr/bin/env python3
"""Fork: a pad, not the track beside it, takes the junction to a nearby via.

A route ran past its pad to a via and reached the pad by a short branch off
the track. The via's branch is now replaced by copper from the pad's centre
to the via, so the track ends in the pad and the via hangs off the pad.

    python3 tests/test_pad_takes_junction.py
"""
import math
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, 'py_router'))
sys.path.insert(0, os.path.join(REPO, 'py_tools'))

from kicad_parser import Pad, Net, PCBData, BoardInfo, Segment, Via
from pcb_modification import pad_takes_junction
from routing_config import GridRouteConfig

fails = []
W = 0.2


def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (f"  {detail}" if detail else ""))
    if not cond:
        fails.append(name)


def _pad(ref, x, y, net_id, net_name, sx, sy):
    return Pad(component_ref=ref, pad_number='1', global_x=x, global_y=y,
               local_x=0.0, local_y=0.0, size_x=sx, size_y=sy, shape='rect',
               layers=['F.Cu'], net_id=net_id, net_name=net_name, drill=0, pad_type='smd')


def _board(blocker=None):
    """A track along y = 9.5 from a pad at (6, 9.5) to a via at (11, 9.5); a
    pad at (10, 10) hangs off it by a branch from (10, 9.5). With `blocker`,
    a foreign pad sits at that point."""
    pts = [(6.0, 9.5), (10.0, 9.5), (11.0, 9.5)]
    segs = [Segment(start_x=a[0], start_y=a[1], end_x=b[0], end_y=b[1], width=W,
                    layer='F.Cu', net_id=1) for a, b in zip(pts, pts[1:])]
    segs.append(Segment(start_x=10.0, start_y=9.5, end_x=10.0, end_y=10.0, width=W,
                        layer='F.Cu', net_id=1))
    via = Via(x=11.0, y=9.5, size=0.6, drill=0.3, layers=['F.Cu', 'B.Cu'], net_id=1)
    pads = {1: [_pad('U1', 6.0, 9.5, 1, '/VIN', 0.5, 0.5),
                _pad('D1', 10.0, 10.0, 1, '/VIN', 0.8, 0.6)]}
    if blocker:
        pads[2] = [_pad('C9', blocker[0], blocker[1], 2, '/OTHER', 0.5, 0.5)]
    pcb = PCBData(footprints={}, nets={1: Net(1, '/VIN'), 2: Net(2, '/OTHER')},
                  segments=segs, vias=[via],
                  board_info=BoardInfo(layers={}, copper_layers=['F.Cu', 'B.Cu'],
                                       board_bounds=(0.0, 0.0, 200.0, 200.0)),
                  pads_by_net=pads)
    cfg = GridRouteConfig(track_width=W, clearance=0.15, via_size=0.6, via_drill=0.3,
                          layers=['F.Cu', 'B.Cu'])
    return pcb, cfg


def _touches(s, p):
    return (math.hypot(s.start_x - p[0], s.start_y - p[1]) < 1e-6
            or math.hypot(s.end_x - p[0], s.end_y - p[1]) < 1e-6)


def test_via_hangs_off_the_pad():
    pcb, cfg = _board()
    n, _strip, _added = pad_takes_junction([], pcb, None, cfg)
    check("one junction moved", n == 1, n)
    segs = [s for s in pcb.segments if s.net_id == 1]
    check("the track no longer runs on past the pad to the via",
          not any(_touches(s, (10.0, 9.5)) and s.start_y == 9.5 and s.end_y == 9.5
                  and max(s.start_x, s.end_x) > 10.0 + 1e-6 for s in segs),
[(s.start_x, s.start_y, s.end_x, s.end_y) for s in segs])
    check("copper leaves the pad's centre for the via",
          sum(1 for s in segs if _touches(s, (10.0, 10.0))) == 2)
    check("the via is still joined", any(_touches(s, (11.0, 9.5)) for s in segs))


def test_blocked_link_is_left_alone():
    pcb, cfg = _board(blocker=(10.6, 9.85))
    before = sorted((s.start_x, s.start_y, s.end_x, s.end_y) for s in pcb.segments)
    n, _strip, _added = pad_takes_junction([], pcb, None, cfg)
    check("no link through foreign copper is laid", n == 0, n)
    after = sorted((s.start_x, s.start_y, s.end_x, s.end_y) for s in pcb.segments)
    check("the route is unchanged", before == after, after)


def main():
    test_via_hangs_off_the_pad()
    test_blocked_link_is_left_alone()
    print(f"\n{len(fails)} failure(s)" if fails else "\nall passed")
    return 1 if fails else 0


def test_main():
    assert main() == 0


if __name__ == '__main__':
    sys.exit(main())
