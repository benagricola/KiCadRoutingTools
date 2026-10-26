#!/usr/bin/env python3
"""Fork: the copper between two nearby pads of a net becomes a straight link.

A route humped between two pads in line (a soft cost had steered it), with a
third pad's branch hanging off the hump. The hump is replaced by a direct
link, the branch is redrawn from its pad, and old stubs go -- unless the link
is blocked, or it would cut a foreign pour into more pieces than the hump did.

    python3 tests/test_straighten_pad_links.py
"""
import math
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, 'py_router'))
sys.path.insert(0, os.path.join(REPO, 'py_tools'))

from kicad_parser import Pad, Net, PCBData, BoardInfo, Segment, Zone
from pcb_modification import straighten_pad_links
from routing_config import GridRouteConfig

fails = []
W = 0.2


def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (f"  {detail}" if detail else ""))
    if not cond:
        fails.append(name)


def _pad(ref, x, y, net_id, net_name, sx=0.5, sy=0.5):
    return Pad(component_ref=ref, pad_number='1', global_x=x, global_y=y,
               local_x=0.0, local_y=0.0, size_x=sx, size_y=sy, shape='rect',
               layers=['F.Cu'], net_id=net_id, net_name=net_name, drill=0, pad_type='smd')


def _board(blocker=None, pour=None):
    """Pads A (10, 10) and B (12, 10) joined over a hump up to y = 9.5; pad
    C (12, 8.6) hangs off the hump at (11.5, 9.5). With `blocker`, a foreign
    pad sits there; with `pour`, a foreign GND pour has that outline."""
    pts = [(10.0, 10.0), (10.5, 9.5), (11.5, 9.5), (12.0, 10.0)]
    segs = [Segment(start_x=a[0], start_y=a[1], end_x=b[0], end_y=b[1], width=W,
                    layer='F.Cu', net_id=1) for a, b in zip(pts, pts[1:])]
    segs.append(Segment(start_x=11.5, start_y=9.5, end_x=12.0, end_y=9.0, width=W,
                        layer='F.Cu', net_id=1))
    segs.append(Segment(start_x=12.0, start_y=9.0, end_x=12.0, end_y=8.6, width=W,
                        layer='F.Cu', net_id=1))
    pads = {1: [_pad('A', 10.0, 10.0, 1, '/VIN'), _pad('B', 12.0, 10.0, 1, '/VIN'),
                _pad('C', 12.0, 8.6, 1, '/VIN')]}
    if blocker:
        pads[2] = [_pad('X', blocker[0], blocker[1], 2, '/OTHER', 0.3, 0.3)]
    zones = []
    if pour:
        zones.append(Zone(3, 'GND', 'F.Cu', pour, clearance=0.2, min_thickness=0.1))
    pcb = PCBData(footprints={}, nets={1: Net(1, '/VIN'), 2: Net(2, '/OTHER'), 3: Net(3, 'GND')},
                  segments=segs, vias=[],
                  board_info=BoardInfo(layers={}, copper_layers=['F.Cu', 'B.Cu'],
                                       board_bounds=(0.0, 0.0, 200.0, 200.0)),
                  pads_by_net=pads, zones=zones)
    cfg = GridRouteConfig(track_width=W, clearance=0.15, via_size=0.6, via_drill=0.3,
                          layers=['F.Cu', 'B.Cu'])
    return pcb, cfg


def _segs(pcb):
    return sorted((round(s.start_x, 3), round(s.start_y, 3), round(s.end_x, 3), round(s.end_y, 3))
                  for s in pcb.segments if s.net_id == 1)


def test_hump_becomes_a_straight_link():
    pcb, cfg = _board()
    n, _strip, _added = straighten_pad_links([], pcb, None, cfg)
    check("one link straightened", n >= 1, n)
    got = _segs(pcb)
    check("A and B are joined by a straight line",
          any({(s[0], s[1]), (s[2], s[3])} == {(10.0, 10.0), (12.0, 10.0)} for s in got), got)
    check("C is joined straight down to B",
          any({(s[0], s[1]), (s[2], s[3])} == {(12.0, 8.6), (12.0, 10.0)} for s in got), got)
    check("no copper is left on the hump", not any(s[1] == 9.5 or s[3] == 9.5 for s in got), got)


def test_blocked_link_is_left_alone():
    pcb, cfg = _board(blocker=(11.0, 10.0))
    before = _segs(pcb)
    straighten_pad_links([], pcb, None, cfg)
    check("a link through foreign copper is not laid",
          not any({(s[0], s[1]), (s[2], s[3])} == {(10.0, 10.0), (12.0, 10.0)} for s in _segs(pcb)),
          _segs(pcb))
    check("the hump stays", any(s[1] == 9.5 for s in _segs(pcb)), before)


def test_link_that_splits_a_pour_is_refused():
    """A GND pour spans y 9.3..10.6 between the pads. The hump at y = 9.5
    only trims its top; a straight link at y = 10 cuts it in two."""
    pcb, cfg = _board(pour=[(10.6, 9.3), (11.4, 9.3), (11.4, 10.6), (10.6, 10.6)])
    straighten_pad_links([], pcb, None, cfg)
    check("the link that would split the pour is not laid",
          not any({(s[0], s[1]), (s[2], s[3])} == {(10.0, 10.0), (12.0, 10.0)} for s in _segs(pcb)),
          _segs(pcb))


def main():
    test_hump_becomes_a_straight_link()
    test_blocked_link_is_left_alone()
    test_link_that_splits_a_pour_is_refused()
    print(f"\n{len(fails)} failure(s)" if fails else "\nall passed")
    return 1 if fails else 0


def test_main():
    assert main() == 0


if __name__ == '__main__':
    sys.exit(main())
