#!/usr/bin/env python3
"""A pair's GND return vias keep clear of the pair's own tracks.

The router picks the side of a layer change the two GND vias go (ahead or
behind) against the obstacle map, which does not hold the pair's own copper.
A pair that turns back on itself just before its layer change (the USB pair
on a six-layer core board, at the MCU) had a GND via dropped onto its own N
track, 0.294 mm into it. A layer change whose GND vias would break the
clearance to the pair's tracks now gets none.

Run: python3 -X utf8 tests/test_gnd_via_own_copper.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'py_router'))

from kicad_parser import Segment  # noqa: E402
from routing_config import GridRouteConfig, GridCoord  # noqa: E402
from diff_pair_routing import _create_gnd_vias  # noqa: E402

_fails = []


def check(name, cond, detail=''):
    print(('PASS ' if cond else 'FAIL ') + name + ('' if cond else ': ' + detail))
    if not cond:
        _fails.append(name)


LAYERS = ['F.Cu', 'In1.Cu', 'B.Cu']
cfg = GridRouteConfig(track_width=0.15, clearance=0.15, via_size=0.45, via_drill=0.2,
                      grid_step=0.1, layers=LAYERS)
coord = GridCoord(cfg.grid_step)
path = [(0, 0, 0), (20, 0, 0), (20, 0, 1), (40, 0, 1)]     # east on F.Cu, a layer change at x=2
spacing = 0.15

free = _create_gnd_vias(path, coord, cfg, LAYERS, spacing, 9, [-1])
check('two GND vias behind the layer change', len(free) == 2 and all(v.x < 2.0 for v in free),
      repr([(v.x, v.y) for v in free]))

g = free[0]
through = Segment(start_x=g.x - 0.3, start_y=g.y, end_x=g.x + 0.3, end_y=g.y, width=0.15,
                  layer='F.Cu', net_id=2)
got = _create_gnd_vias(path, coord, cfg, LAYERS, spacing, 9, [-1], own_segments=[through])
check("a GND via on the pair's own track: that layer change gets none", got == [],
      repr([(v.x, v.y) for v in got]))

far = Segment(start_x=g.x - 0.3, start_y=g.y + 2.0, end_x=g.x + 0.3, end_y=g.y + 2.0, width=0.15,
              layer='F.Cu', net_id=2)
got = _create_gnd_vias(path, coord, cfg, LAYERS, spacing, 9, [-1], own_segments=[far])
check('a pair track clear of them keeps both', len(got) == 2)

sys.exit(1 if _fails else 0)
