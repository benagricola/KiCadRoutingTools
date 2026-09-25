#!/usr/bin/env python3
"""A via's track keep-out is exact (docs/corner-move-check-design.md, the
via twin of the pad corner guards).

A 0.6 mm via, 0.2 mm track, 0.2 mm clearance: a track centre must stay 0.6 mm
from the via's centre. The keep-out used to be the ceiling of that in cells
(0.6000000000000001 / 0.1 -> 7) plus a quarter cell, so it blocked cells up to
0.725 mm out; on the MCU module a router via 0.721 mm from a pin's only lane
sealed the pin. Now the cells are blocked exactly (within 0.6 mm, a cell
exactly at 0.6 open) and the via is a guard circle, so a move between two open
cells that passes within 0.6 mm is refused, and no move that keeps 0.6 mm is.
Both the base map and the per-net cache.

Run: python3 -X utf8 tests/test_via_keepout_exact.py
"""
import math
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'py_router'))

from kicad_parser import parse_kicad_pcb  # noqa: E402
from routing_config import GridRouteConfig  # noqa: E402
import obstacle_map as om  # noqa: E402
import obstacle_cache as oc  # noqa: E402
from grid_router import GridObstacleMap  # noqa: E402

_fails = []


def check(name, cond, detail=''):
    print(('PASS ' if cond else 'FAIL ') + name + ('' if cond else ': ' + detail))
    if not cond:
        _fails.append(name)


VX, VY, R = 20.0, 20.0, 0.6
text = ('(kicad_pcb\n\t(version 20241229)\n\t(generator "test")\n'
        '\t(layers\n\t\t(0 "F.Cu" signal)\n\t\t(2 "B.Cu" signal)\n\t\t(25 "Edge.Cuts" user)\n\t)\n'
        '\t(net 0 "")\n\t(net 1 "VX")\n\t(net 2 "N")\n'
        '\t(footprint "t:p" (layer "F.Cu") (at 30 30)\n\t\t(property "Reference" "J1" (at 0 0))\n'
        '\t\t(pad "1" smd rect (at 0 0) (size 0.6 0.6) (layers "F.Cu") (net 2 "N"))\n\t)\n'
        '\t(via (at %g %g) (size 0.6) (drill 0.3) (layers "F.Cu" "B.Cu") (net 1))\n'
        '\t(gr_rect (start 0 0) (end 40 40) (stroke (width 0.1) (type solid)) (fill no) (layer "Edge.Cuts"))\n)\n'
        % (VX, VY))
fd, path = tempfile.mkstemp(suffix='.kicad_pcb')
os.close(fd)
with open(path, 'w') as fh:
    fh.write(text)
pcb = parse_kicad_pcb(path)
os.unlink(path)
cfg = GridRouteConfig(track_width=0.2, clearance=0.2, grid_step=0.1, layers=['F.Cu', 'B.Cu'])
n_id = [k for k, n in pcb.nets.items() if n.name == 'N'][0]
v_id = [k for k, n in pcb.nets.items() if n.name == 'VX'][0]


def seg_dist(ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    t = max(0.0, min(1.0, ((VX - ax) * dx + (VY - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(ax + t * dx - VX, ay + t * dy - VY)


def audit(name, obs):
    g0, g1 = 190, 211
    wrong_cells = []
    for gx in range(g0, g1):
        for gy in range(g0, g1):
            d = math.hypot(gx * 0.1 - VX, gy * 0.1 - VY)
            if obs.is_blocked(gx, gy, 0) != (d < R - 1e-6):
                wrong_cells.append((gx, gy, round(d, 4)))
    check('%s: cells within %.1f mm blocked, the rest open' % (name, R), not wrong_cells, repr(wrong_cells[:6]))
    check('%s: a cell 0.721 mm away is open' % name, not obs.is_blocked(206, 204, 0))
    wrong_moves = []
    for gx in range(g0, g1):
        for gy in range(g0, g1):
            for dx, dy in ((1, 0), (0, 1), (1, 1), (1, -1)):
                a, b = (gx, gy), (gx + dx, gy + dy)
                if obs.is_blocked(*a, 0) or obs.is_blocked(*b, 0):
                    continue
                near = seg_dist(a[0] * 0.1, a[1] * 0.1, b[0] * 0.1, b[1] * 0.1) < R - 1e-6
                if obs.move_clips_corner(a[0], a[1], b[0], b[1], 0, 0.0) != near:
                    wrong_moves.append((a, b))
    check('%s: the move check refuses exactly the moves that pass within %.1f mm' % (name, R),
          not wrong_moves, repr(wrong_moves[:6]))


# the base map: the via's net is not being routed
audit('base map', om.build_base_obstacle_map(pcb, cfg, nets_to_route=[n_id], static_base=True))
# the per-net cache: the via's net is routed, its copper comes from its cache
m = GridObstacleMap(2)
oc.add_net_obstacles_from_cache(m, oc.precompute_net_obstacles(pcb, v_id, cfg))
audit('per-net cache', m)

sys.exit(1 if _fails else 0)
