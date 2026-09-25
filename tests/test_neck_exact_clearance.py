#!/usr/bin/env python3
"""A pair's P track exactly at the clearance from its N track is legal and
keeps its width (_neck_pair_partner_grazes).

The neck took 0.2 um off each side of any partner gap within 0.2 um of the
clearance, so two legs leaving 0.4 mm pitch pins at 0.2 mm width (a gap of
exactly 0.2 mm) were written at 0.1996 mm, under a 0.2 mm board minimum
(the module fan-out case's USB_MCU legs). The obstacle map places copper at
exactly the clearance by design (pads and vias stamped at margin minus
GRID_TIE_EPS), so the neck now triggers on a deficit beyond that tolerance,
as its own hard check does; the 0.2 um cushion stays on the width it necks
to.

Run: python3 -X utf8 tests/test_neck_exact_clearance.py
"""
import os
import sys
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'py_router'))

from kicad_parser import Segment  # noqa: E402
from routing_config import GridRouteConfig  # noqa: E402
from diff_pair_routing import _neck_pair_partner_grazes  # noqa: E402

_fails = []


def check(name, cond, detail=''):
    print(('PASS ' if cond else 'FAIL ') + name + ('' if cond else ': ' + detail))
    if not cond:
        _fails.append(name)


cfg = GridRouteConfig(track_width=0.2, clearance=0.2, grid_step=0.1, layers=['F.Cu', 'B.Cu'])
pcb = SimpleNamespace(board_info=SimpleNamespace(copper_layers=['F.Cu', 'B.Cu']))


def seg(x, net):
    return Segment(start_x=x, start_y=8.7, end_x=x, end_y=9.2, width=0.2, layer='F.Cu', net_id=net)


p, n = seg(15.4, 1), seg(15.8, 2)
necked, hard = _neck_pair_partner_grazes([p], [n], cfg, pcb)
check('a gap of exactly the clearance keeps both widths',
      necked == 0 and p.width == 0.2 and n.width == 0.2, '%d necked, P %.4f N %.4f' % (necked, p.width, n.width))
check('and is not refused', not hard, repr(hard))

p, n = seg(15.4, 1), seg(15.799, 2)
necked, hard = _neck_pair_partner_grazes([p], [n], cfg, pcb)
check('a gap 1 um under the clearance is necked, with the cushion',
      necked == 1 and abs(p.width - 0.1976) < 1e-9, '%d necked, P %.4f' % (necked, p.width))

sys.exit(1 if _fails else 0)
