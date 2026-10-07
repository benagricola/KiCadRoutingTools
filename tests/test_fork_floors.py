#!/usr/bin/env python3
"""Fork divergence (docs/fork-divergences.md): the board's own minimums floor what the router routes at.

  * the base clearance and every per-net clearance are at least the board's min_clearance, which KiCad grades by
    (design_rules.py:24 states KiCad's rule; upstream declines it, list_nets.py:91-94);
  * a pair partner neck and a pruned graze neck no lower than the net's track floor, as the single-ended terminal
    neck does (single_ended_routing.py:960-962).

    python3 tests/test_fork_floors.py
"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, 'py_router'))
sys.path.insert(0, HERE)

fails = []


def check(name, cond, detail=''):
    print(('PASS: ' if cond else 'FAIL: ') + name + (f'  {detail}' if detail else ''))
    if not cond:
        fails.append(name)


def _project(path, default_clearance, min_clearance, min_track):
    doc = {"board": {"design_settings": {"rules": {"min_clearance": min_clearance, "min_track_width": min_track}}},
           "net_settings": {"classes": [{"name": "Default", "clearance": default_clearance, "track_width": 0.2,
                                         "via_diameter": 0.6, "via_drill": 0.3}]}}
    with open(path, 'w') as f:
        json.dump(doc, f)


def t_floored_clearance():
    from route import resolve_floored_clearances
    with tempfile.TemporaryDirectory() as tmp:
        pcb = os.path.join(tmp, 'b.kicad_pcb')
        open(pcb, 'w').write('(kicad_pcb (version 20241229) (generator "t"))\n')
        _project(os.path.join(tmp, 'b.kicad_pro'), 0.125, 0.15, 0.125)
        base, by_id = resolve_floored_clearances(pcb, 0.125, {1: 0.125, 2: 0.2})
        check('base clearance floored at min_clearance', abs(base - 0.15) < 1e-9, base)
        check('a class under the minimum is raised to it', abs(by_id[1] - 0.15) < 1e-9, by_id)
        check('a class over the minimum keeps its own', abs(by_id[2] - 0.2) < 1e-9, by_id)
        _project(os.path.join(tmp, 'b.kicad_pro'), 0.125, 0.0, 0.125)
        base, _ = resolve_floored_clearances(pcb, 0.125, {})
        check('a board with no minimum is left at its class', abs(base - 0.125) < 1e-9, base)


def t_pair_neck_floor():
    from synth import make_seg
    from diff_pair_routing import _neck_pair_partner_grazes

    class Cfg:
        net_clearances = {}
        clearance = 0.2
        def track_floor(self, net_id, layer, fab_value):
            return max(fab_value, 0.25)
        def obstacle_clearance(self, net_id):
            return 0.2

    class Info:
        copper_layers = ['F.Cu', 'B.Cu']

    class Pcb:
        board_info = Info()
    p = [make_seg(0, 0, 10, 0, width=0.4, net_id=1)]
    n = [make_seg(0, 0.45, 10, 0.45, width=0.4, net_id=2)]
    _neck_pair_partner_grazes(p, n, Cfg(), Pcb())
    check('a pair neck stays at or above the board track floor',
          min(s.width for s in p + n) >= 0.25 - 1e-9, [s.width for s in p + n])


if __name__ == '__main__':
    t_floored_clearance()
    t_pair_neck_floor()
    if fails:
        print(f'{len(fails)} FAILURE(S): {fails}')
        sys.exit(1)
    print('all checks passed')
