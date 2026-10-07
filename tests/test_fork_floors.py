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


def t_plane_neck_floor():
    """_neck_plane_segments floors at min_width; _finalize_plane_copper raises it to the board's min_track_width."""
    from types import SimpleNamespace
    from route_planes import _neck_plane_segments
    pad = SimpleNamespace(global_x=2.5, global_y=1.0, size_x=1.0, size_y=1.0, shape='rect', rect_rotation=0.0,
                          layers=['F.Cu'], local_clearance=0.4)
    brd = SimpleNamespace(pads_by_net={2: [pad]}, vias=[])
    seg = lambda: {'start': (0.0, 0.0), 'end': (5.0, 0.0), 'width': 0.3, 'layer': 'F.Cu', 'net_id': 1}
    s0 = [seg()]
    _neck_plane_segments(s0, brd, 0.2, ['F.Cu'], min_width=0.1)
    s1 = [seg()]
    _neck_plane_segments(s1, brd, 0.2, ['F.Cu'], min_width=0.25)
    check('a plane neck goes to its natural width above the floor', s0[0]['width'] < 0.21, s0[0]['width'])
    check('a plane neck stops at the board track floor', abs(s1[0]['width'] - 0.25) < 1e-9, s1[0]['width'])

    import pcb_modification
    with tempfile.TemporaryDirectory() as tmp:
        pcb = os.path.join(tmp, 'b.kicad_pcb')
        open(pcb, 'w').write('(kicad_pcb (version 20241229) (generator "t"))\n')
        _project(os.path.join(tmp, 'b.kicad_pro'), 0.125, 0.15, 0.2)
        import fab_tiers
        prev = fab_tiers.get_escalation_policy()
        try:
            fab_tiers.set_escalation_policy('board')
            got = pcb_modification.plane_track_floor(SimpleNamespace(source_path=pcb))
            check('plane_track_floor reads the board min_track_width', abs(got - 0.2) < 1e-9, got)
            fab_tiers.set_escalation_policy('fab')
            check('plane_track_floor is 0 under --escalation fab', pcb_modification.plane_track_floor(
                SimpleNamespace(source_path=pcb)) == 0.0)
        finally:
            fab_tiers.set_escalation_policy(*prev)
        check('plane_track_floor is 0 with no board path', pcb_modification.plane_track_floor(
            SimpleNamespace(source_path='')) == 0.0)


def t_floor_of_threaded():
    """cleanup_plane_taps_grazing hands floor_of to prune_grazing_segments."""
    import pcb_modification as pm
    seen = {}
    real = pm.prune_grazing_segments

    def spy(*a, **kw):
        seen['floor_of'] = kw.get('floor_of')
        return 0, 0, []
    pm.prune_grazing_segments = spy
    try:
        from synth import make_pcb
        f = lambda nid, layer: 0.25
        seg = {'start': (0.0, 0.0), 'end': (5.0, 0.0), 'width': 0.3, 'layer': 'F.Cu', 'net_id': 1}
        try:
            pm.cleanup_plane_taps_grazing(make_pcb(), [seg], {1}, floor_of=f)
        except Exception as e:                       # later passes may reject the bare board; the spy ran first
            print('note: later pass raised', type(e).__name__)
    finally:
        pm.prune_grazing_segments = real
    check('floor_of reaches prune_grazing_segments', seen.get('floor_of') is f, seen)
    import inspect
    check('prune_grazing_segments takes floor_of', 'floor_of' in inspect.signature(real).parameters)


if __name__ == '__main__':
    t_floored_clearance()
    t_pair_neck_floor()
    t_plane_neck_floor()
    t_floor_of_threaded()
    if fails:
        print(f'{len(fails)} FAILURE(S): {fails}')
        sys.exit(1)
    print('all checks passed')
