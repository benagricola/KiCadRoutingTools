#!/usr/bin/env python3
"""Fork: the smoother chamfers a right-angle corner its shortcuts leave.

A shortcut joins existing vertices, so an L whose whole-leg diagonal grazes a
foreign pad kept its 90-degree corner. The corner is now cut by the largest
45-degree chamfer that clears, and a cut that would take away the copper a
same-net via touches gives way to a smaller one.

    python3 tests/test_smooth_chamfer.py
"""
import math
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, 'py_router'))
sys.path.insert(0, os.path.join(REPO, 'py_tools'))

from kicad_parser import Pad, Net, PCBData, BoardInfo, Segment, Via
from pcb_modification import smooth_octolinear_chains

fails = []


def check(name, cond, detail=""):
    print(("  PASS " if cond else "  FAIL ") + name + (f"  {detail}" if detail else ""))
    if not cond:
        fails.append(name)


def _pad(ref, x, y, net_id, net_name, sx=0.5, sy=0.5):
    return Pad(component_ref=ref, pad_number='1', global_x=x, global_y=y,
               local_x=0.0, local_y=0.0, size_x=sx, size_y=sy, shape='rect',
               layers=['F.Cu'], net_id=net_id, net_name=net_name, drill=0)


def _ell(vias=None):
    """An L from U1 (10, 10) east to (14, 10), then south to U2 (14, 14), with a
    foreign pad on the whole-leg diagonal."""
    segs = [Segment(start_x=10.0, start_y=10.0, end_x=14.0, end_y=10.0, width=0.15,
                    layer='F.Cu', net_id=1),
            Segment(start_x=14.0, start_y=10.0, end_x=14.0, end_y=14.0, width=0.15,
                    layer='F.Cu', net_id=1)]
    pads = {1: [_pad('U1', 10.0, 10.0, 1, '/SIG'), _pad('U2', 14.0, 14.0, 1, '/SIG')],
            2: [_pad('C9', 12.0, 12.0, 2, '/OTHER', sx=0.3, sy=0.3)]}
    return PCBData(footprints={}, nets={1: Net(1, '/SIG'), 2: Net(2, '/OTHER')},
                   segments=segs, vias=vias or [],
                   board_info=BoardInfo(layers={}, copper_layers=['F.Cu', 'B.Cu'],
                                        board_bounds=(0.0, 0.0, 200.0, 200.0)),
                   pads_by_net=pads)


def _diagonals(pcb):
    return [s for s in pcb.segments
            if abs(abs(s.end_x - s.start_x) - abs(s.end_y - s.start_y)) < 1e-6
            and abs(s.end_x - s.start_x) > 1e-6]


def _corner_gone(pcb):
    return not any(abs(s.start_x - 14.0) < 1e-6 and abs(s.start_y - 10.0) < 1e-6
                   or abs(s.end_x - 14.0) < 1e-6 and abs(s.end_y - 10.0) < 1e-6
                   for s in pcb.segments)


def _clear(pcb):
    from single_ended_routing import _seg_foreign_pad_dist
    return all(_seg_foreign_pad_dist(pcb, 1, s.start_x, s.start_y, s.end_x, s.end_y,
                                     'F.Cu', base_clearance=0.1) >= 0.1 + s.width / 2 - 1e-4
               for s in pcb.segments)


def test_right_angle_is_chamfered():
    pcb = _ell()
    _n, nets, _strip, _added, st = smooth_octolinear_chains([], pcb, clearance=0.1)
    d = _diagonals(pcb)
    check("one 45-degree chamfer", len(d) == 1, [(s.start_x, s.start_y, s.end_x, s.end_y) for s in d])
    if d:
        L = math.hypot(d[0].end_x - d[0].start_x, d[0].end_y - d[0].start_y)
        check("the chamfer is the largest that clears (3 mm legs)",
              abs(L - 3.0 * math.sqrt(2)) < 1e-6, round(L, 4))
    check("the corner vertex is gone", _corner_gone(pcb))
    check("the copper clears the foreign pad", _clear(pcb))
    check("the counter records it", st.get('chamfers') == 1, st.get('chamfers'))


def test_via_on_the_cut_gives_way_to_a_smaller_chamfer():
    via = Via(x=14.0, y=12.0, size=0.6, drill=0.3, layers=['F.Cu', 'B.Cu'], net_id=1)
    pcb = _ell([via])
    smooth_octolinear_chains([], pcb, clearance=0.1)
    d = _diagonals(pcb)
    check("one chamfer", len(d) == 1)
    if d:
        L = math.hypot(d[0].end_x - d[0].start_x, d[0].end_y - d[0].start_y)
        check("the chamfer stops short of the via (1.4 mm legs)",
              abs(L - 1.4 * math.sqrt(2)) < 1e-6, round(L, 4))
    touching = [s for s in pcb.segments
                if min(math.hypot(s.start_x - 14.0, s.start_y - 12.0),
                       math.hypot(s.end_x - 14.0, s.end_y - 12.0)) < 1e-6
                or (abs(s.start_x - 14.0) < 1e-6 and abs(s.end_x - 14.0) < 1e-6
                    and min(s.start_y, s.end_y) < 12.0 < max(s.start_y, s.end_y))]
    check("the via keeps its copper", bool(touching))


def main():
    test_right_angle_is_chamfered()
    test_via_on_the_cut_gives_way_to_a_smaller_chamfer()
    print(f"\n{len(fails)} failure(s)" if fails else "\nall passed")
    return 1 if fails else 0


def test_main():
    assert main() == 0


if __name__ == '__main__':
    sys.exit(main())
