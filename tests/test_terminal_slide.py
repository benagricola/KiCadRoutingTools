#!/usr/bin/env python3
"""Fork: a route's first run slides onto its off-grid pad's centre.

A grid route ends on the cell nearest an off-grid pad and a short stub joins
that cell to the pad centre, so the track ran beside the centre with a jog at
the pad. The first straight run now moves sideways onto the line through the
pad centre, its far bend slides along the next segment's line, and both keep
their directions. A slide that would come too close to foreign copper is not
taken.

Run:
    python3 tests/test_terminal_slide.py
"""
import json
import math
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, 'py_router'))
sys.path.insert(0, os.path.join(ROOT, 'rust_router'))

fails = []


def check(name, cond, detail=''):
    print(('PASS: ' if cond else 'FAIL: ') + name + (f'  {detail}' if detail else ''))
    if not cond:
        fails.append(name)


def _board(path, pads):
    """pads: [(ref, x, y, net_name)] -- 0.25 x 0.6 mm SMD pads on F.Cu."""
    names = sorted({p[3] for p in pads})
    num = {n: i + 1 for i, n in enumerate(names)}
    parts = []
    for ref, x, y, net in pads:
        parts.append(f' (footprint "t:P" (layer "F.Cu") (at {x} {y})\n'
                     f'  (property "Reference" "{ref}" (at 0 -2) (layer "F.SilkS"))\n'
                     f'  (pad "1" smd rect (at 0 0) (size 0.25 0.6) (layers "F.Cu") '
                     f'(net {num[net]} "{net}"))\n )\n')
    nets = ''.join(f' (net {num[n]} "{n}")\n' for n in names)
    txt = ('(kicad_pcb\n (version 20221018)\n (generator "test_terminal_slide")\n'
           ' (general (thickness 1.6))\n'
           ' (layers (0 "F.Cu" signal) (31 "B.Cu" signal) (44 "Edge.Cuts" user))\n (net 0 "")\n' + nets +
           ' (gr_rect (start 0 0) (end 22 18) (layer "Edge.Cuts") (width 0.1))\n' + ''.join(parts) + ')\n')
    with open(path, 'w', encoding='utf-8') as f:
        f.write(txt)
    doc = {"board": {"design_settings": {"rules": {"min_clearance": 0.127, "min_track_width": 0.127}}},
           "net_settings": {"classes": [{"name": "Default", "clearance": 0.127, "track_width": 0.127,
                                         "via_diameter": 0.45, "via_drill": 0.2}]}}
    with open(os.path.splitext(path)[0] + '.kicad_pro', 'w', encoding='utf-8') as f:
        json.dump(doc, f)


def _setup(tmp, pads):
    from kicad_parser import parse_kicad_pcb
    from routing_config import GridRouteConfig
    p = os.path.join(tmp, 'b.kicad_pcb')
    _board(p, pads)
    pcb = parse_kicad_pcb(p)
    config = GridRouteConfig(track_width=0.127, clearance=0.127, via_size=0.45, via_drill=0.2,
                             layers=['F.Cu', 'B.Cu'])
    ids = {n.name: nid for nid, n in pcb.nets.items()}
    return pcb, config, ids


def _bearing(a, b):
    return math.degrees(math.atan2(b[1] - a[1], b[0] - a[0])) % 360


def t_run_slides_onto_the_pad_centre(tmp):
    from single_ended_routing import _slide_terminal_onto_exact
    pcb, config, ids = _setup(tmp, [('U1', 10.05, 4.0, 'A'), ('V1', 14.0, 10.0, 'A')])
    # Grid path: down from the cell beside the pad, then a 45-degree run.
    path = [(100, 40, 0), (100, 60, 0), (130, 90, 0)]
    pts = [(10.0, 4.0), (10.0, 6.0), (13.0, 9.0)]
    before = (_bearing(pts[0], pts[1]), _bearing(pts[1], pts[2]))
    ok = _slide_terminal_onto_exact(path, 0, 1, 2, (10.05, 4.0, 'F.Cu'), pts, pcb,
                                    ids['A'], config, ['F.Cu', 'B.Cu'])
    check('the run slides', ok)
    check('the run starts at the pad centre', pts[0] == (10.05, 4.0), pts[0])
    after = (_bearing(pts[0], pts[1]), _bearing(pts[1], pts[2]))
    check('the run keeps its direction', abs(after[0] - before[0]) < 1e-6, (before, after))
    check('the next segment keeps its direction', abs(after[1] - before[1]) < 1e-6, (before, after))
    check('the bend moved along the next segment', abs(pts[1][0] - 10.05) < 1e-9
          and abs(pts[1][1] - 6.05) < 1e-9, pts[1])
    check('the far end is unchanged', pts[2] == (13.0, 9.0), pts[2])


def t_slide_into_foreign_copper_is_refused(tmp):
    from single_ended_routing import _slide_terminal_onto_exact
    # A foreign pad beside the run: the grid run clears it by 0.14 mm, the
    # slid run would clear it by 0.09 mm, under the 0.127 mm clearance.
    pcb, config, ids = _setup(tmp, [('U1', 10.05, 4.0, 'A'), ('V1', 14.0, 10.0, 'A'),
                                    ('W1', 10.33, 5.0, 'B')])
    path = [(100, 40, 0), (100, 60, 0), (130, 90, 0)]
    pts = [(10.0, 4.0), (10.0, 6.0), (13.0, 9.0)]
    ok = _slide_terminal_onto_exact(path, 0, 1, 2, (10.05, 4.0, 'F.Cu'), pts, pcb,
                                    ids['A'], config, ['F.Cu', 'B.Cu'])
    check('the slide is refused', not ok)
    check('the points are unchanged', pts == [(10.0, 4.0), (10.0, 6.0), (13.0, 9.0)], pts)


def t_routed_net_leaves_its_pad_on_the_centre(tmp):
    from obstacle_map import build_base_obstacle_map
    from single_ended_routing import route_net_with_obstacles
    pcb, config, ids = _setup(tmp, [('U1', 10.05, 4.0, 'A'), ('V1', 14.05, 12.0, 'A')])
    obstacles = build_base_obstacle_map(pcb, config, [ids['A']])
    result = route_net_with_obstacles(pcb, ids['A'], config, obstacles)
    check('the net routes', bool(result) and not result.get('failed'))
    if not result or result.get('failed'):
        return
    for cx, cy in ((10.05, 4.0), (14.05, 12.0)):
        at = [s for s in result['new_segments']
              if (abs(s.start_x - cx) < 1e-6 and abs(s.start_y - cy) < 1e-6)
              or (abs(s.end_x - cx) < 1e-6 and abs(s.end_y - cy) < 1e-6)]
        check(f'one segment ends on the pad centre ({cx}, {cy})', len(at) == 1, len(at))
        for s in at:
            b = _bearing((s.start_x, s.start_y), (s.end_x, s.end_y)) % 45
            L = math.hypot(s.end_x - s.start_x, s.end_y - s.start_y)
            check(f'it is octolinear and longer than a grid cell ({cx}, {cy})',
                  min(b, 45 - b) < 1e-6 and L > config.grid_step, (round(b, 3), round(L, 3)))


def main():
    with tempfile.TemporaryDirectory() as tmp:
        t_run_slides_onto_the_pad_centre(tmp)
        t_slide_into_foreign_copper_is_refused(tmp)
        t_routed_net_leaves_its_pad_on_the_centre(tmp)
    print(f"\n{len(fails)} failure(s)" if fails else "\nall passed")
    return 1 if fails else 0


def test_main():
    assert main() == 0


if __name__ == '__main__':
    sys.exit(main())
