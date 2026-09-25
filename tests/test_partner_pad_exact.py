#!/usr/bin/env python3
"""A hybrid leg keeps clear of its partner's pads by the pads' exact copper
(docs/pair-via-crossover-plan.md, task 1).

The leg map left the partner pad to a capsule widened to short*sqrt(2) so
its caps reach a rect pad's corners (_pad_obstacle_segments). Along the
pad's sides that capsule bulges 0.21*short past the copper: at 0.4 mm pitch
it closes the lane the leg needs out of the pad beside the partner (the
module fan-out case's USB_MCU_P leg, boxed in at its own pad). Where the map
takes corner guards, the partner pad is stamped exact instead, as every
other pad is.

A 0.2 x 0.665 mm partner pad, 0.2/0.2: the next pad's centreline, 0.4 mm
over, sits at exactly track/2 + clearance from the partner copper.

Run: python3 -X utf8 tests/test_partner_pad_exact.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'py_router'))

from kicad_parser import Pad  # noqa: E402
from routing_config import GridRouteConfig  # noqa: E402
import obstacle_map as om  # noqa: E402
from grid_router import GridObstacleMap  # noqa: E402

_fails = []


def check(name, cond, detail=''):
    print(('PASS ' if cond else 'FAIL ') + name + ('' if cond else ': ' + detail))
    if not cond:
        _fails.append(name)


cfg = GridRouteConfig(track_width=0.2, clearance=0.2, grid_step=0.1, layers=['F.Cu', 'B.Cu'])
pad = Pad(component_ref='U1', pad_number='67', global_x=50.0, global_y=50.0,
          local_x=0.0, local_y=0.0, size_x=0.2, size_y=0.665, shape='rect',
          layers=['F.Cu'], net_id=2, net_name='D_N')
WIN = [(gx, gy, li) for li in (0, 1) for gx in range(490, 511) for gy in range(490, 511)]

m = GridObstacleMap(2)
held = om.add_pads_track_keepout(m, [pad], cfg)
lane = [gy for gy in range(494, 507) if m.is_blocked(504, gy, 0)]
check("the next pad's lane beside the partner pad is open", not lane, repr(lane))
check('the partner pad itself is blocked', m.is_blocked(500, 500, 0) and m.is_blocked(503, 500, 0))
check('the other layer is untouched', not m.is_blocked(500, 500, 1))
check("the pad's corner guards are in", m.corner_guard_count() > 0)
om.remove_pads_track_keepout(m, held)
left = [c for c in WIN if m.is_blocked(*c)]
check('removing it leaves the map as it was', not left and m.corner_guard_count() == 0,
      '%d cells, %d guards' % (len(left), m.corner_guard_count()))

sys.exit(1 if _fails else 0)
