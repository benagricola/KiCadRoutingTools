#!/usr/bin/env python3
"""The base map built for a run (static_base=True, the #422 static bitmap
path route.py uses) carries the same pad corner guards and the same blocked
cells as the dynamic build (docs/corner-move-check-design.md).

Five 0.665 x 0.2 mm pads at 0.4 mm pitch, 0.2/0.2, the middle pad's net
routed: its lane out passes the neighbouring pads' corners at exactly the
clearance. The neighbours are not routed, so their pads are in the base map.
Without guards there, the base map fell back to the half-cell corner buffer
and blocked the lane's cells beside the pad corners.

Run: python3 -X utf8 tests/test_static_base_guards.py
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'py_router'))

from kicad_parser import parse_kicad_pcb  # noqa: E402
from routing_config import GridRouteConfig  # noqa: E402
import obstacle_map as om  # noqa: E402

_fails = []


def check(name, cond, detail=''):
    print(('PASS ' if cond else 'FAIL ') + name + ('' if cond else ': ' + detail))
    if not cond:
        _fails.append(name)


pads = ''.join('\t\t(pad "%d" smd rect (at %g 0) (size 0.2 0.665) (layers "F.Cu") (net %d "N%d"))\n'
               % (k, (k - 3) * 0.4, k, k) for k in range(1, 6))
text = ('(kicad_pcb\n\t(version 20241229)\n\t(generator "test")\n'
        '\t(layers\n\t\t(0 "F.Cu" signal)\n\t\t(2 "B.Cu" signal)\n\t\t(25 "Edge.Cuts" user)\n\t)\n'
        '\t(net 0 "")\n' + ''.join('\t(net %d "N%d")\n' % (k, k) for k in range(1, 6)) +
        '\t(footprint "t:row" (layer "F.Cu") (at 50 50)\n\t\t(property "Reference" "U1" (at 0 0))\n'
        + pads + '\t)\n'
        '\t(gr_rect (start 40 40) (end 60 60) (stroke (width 0.1) (type solid)) (fill no) (layer "Edge.Cuts"))\n)\n')
fd, path = tempfile.mkstemp(suffix='.kicad_pcb')
os.close(fd)
with open(path, 'w') as fh:
    fh.write(text)
pcb = parse_kicad_pcb(path)
os.unlink(path)

cfg = GridRouteConfig(track_width=0.2, clearance=0.2, grid_step=0.1, layers=['F.Cu', 'B.Cu'])
nid = [k for k, n in pcb.nets.items() if n.name == 'N3'][0]
dyn = om.build_base_obstacle_map(pcb, cfg, nets_to_route=[nid], static_base=False)
sta = om.build_base_obstacle_map(pcb, cfg, nets_to_route=[nid], static_base=True)
check('the static base carries the pads\' corner guards',
      sta.corner_guard_count() == dyn.corner_guard_count() > 0,
      'static %d, dynamic %d' % (sta.corner_guard_count(), dyn.corner_guard_count()))
diff = [(gx, gy, li) for li in (0, 1) for gx in range(480, 521) for gy in range(480, 521)
        if sta.is_blocked(gx, gy, li) != dyn.is_blocked(gx, gy, li)]
check('the static base blocks the same cells as the dynamic one', not diff, repr(diff[:6]))
lane = [gy for gy in range(504, 515) if sta.is_blocked(500, gy, 0)]
check("the routed pad's lane out is open in the static base", not lane, repr(lane))
clone = sta.clone_fresh()
check('a working clone keeps the guards', clone.corner_guard_count() == sta.corner_guard_count())

sys.exit(1 if _fails else 0)
