#!/usr/bin/env python3
"""Fork: a wide bus corridor rung measures its sibling room past a setback.

The planner probes the representative at rungs k, a track k sibling-rooms
wider per side. A wide track cannot leave a 0.4 mm-pitch pin row, so every
rung above 0 failed at the pins and the corridor reserved no width for the
members. A rung that fails from the terminals is now probed again between two
points a setback along the rung-0 path from its ends, and the rung-0 path
joins those points to the terminals.

The router is replaced by a stand-in that fails a wide probe from the pads and
routes one between override endpoints, so the test is about the planner.

Run:
    python3 tests/test_bus_corridor_setback.py
"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, 'py_router'))
sys.path.insert(0, os.path.join(ROOT, 'rust_router'))

NETS = ['B0', 'B1', 'B2']
PITCH = 0.5
fails = []


def check(name, cond, detail=''):
    print(('PASS: ' if cond else 'FAIL: ') + name + (f'  {detail}' if detail else ''))
    if not cond:
        fails.append(name)


def _board(path):
    """Three nets, each a pad in a 0.5 mm pitch row on U and a pad on V 10 mm below."""
    parts = []
    for i, name in enumerate(NETS):
        x = 10.0 + PITCH * i
        for ref, y in (('U', 4.0), ('V', 14.0)):
            parts.append(f' (footprint "t:P" (layer "F.Cu") (at {x} {y})\n'
                         f'  (property "Reference" "{ref}{i}" (at 0 -2) (layer "F.SilkS"))\n'
                         f'  (pad "1" smd rect (at 0 0) (size 0.25 0.6) (layers "F.Cu") '
                         f'(net {i + 1} "{name}"))\n )\n')
    nets = ''.join(f' (net {i + 1} "{n}")\n' for i, n in enumerate(NETS))
    txt = ('(kicad_pcb\n (version 20221018)\n (generator "test_bus_corridor_sibling_pads")\n'
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


def t_wide_rung_routes_past_a_setback(tmp):
    import bus_corridor
    import single_ended_routing
    from bus_detection import BusGroup
    from kicad_parser import parse_kicad_pcb
    from routing_config import GridCoord, GridRouteConfig

    pcb_path = os.path.join(tmp, 'row.kicad_pcb')
    _board(pcb_path)
    pcb = parse_kicad_pcb(pcb_path)
    ids = {n.name: nid for nid, n in pcb.nets.items() if n.name in NETS}
    config = GridRouteConfig(track_width=0.127, clearance=0.127, via_size=0.45, via_drill=0.2,
                             layers=['F.Cu', 'B.Cu'])
    group = BusGroup(name='row', net_ids=[ids[n] for n in NETS],
                     source_positions=[(10.0 + PITCH * i, 4.0) for i in range(3)],
                     target_positions=[(10.0 + PITCH * i, 14.0) for i in range(3)])
    coord = GridCoord(config.grid_step)
    gx0, gy0 = coord.to_grid(10.5, 4.0)
    straight = [(gx0, gy0 + i, 0) for i in range(100)]      # 10 mm straight down
    calls = []
    real = single_ended_routing.route_net_with_obstacles

    def stand_in(pcb_data, net_id, cfg, obstacles, **kw):
        wide = cfg.power_net_widths.get(net_id, cfg.track_width) > cfg.track_width + 1e-9
        src, tgt = kw.get('sources_override'), kw.get('targets_override')
        calls.append((wide, src, tgt))
        if wide and src is None:
            return None                   # a wide track cannot leave the pins
        path = straight if src is None else [(src[0][0], src[0][1], 0), (tgt[0][0], tgt[0][1], 0)]
        return {'new_segments': [], 'new_vias': [], 'path': path}
    single_ended_routing.route_net_with_obstacles = stand_in
    try:
        corridors, _ = bus_corridor.plan_bus_corridors(pcb, config, [group])
    finally:
        single_ended_routing.route_net_with_obstacles = real

    check('a wide rung was probed between override endpoints',
          any(w and s is not None for w, s, _ in calls), len(calls))
    over = [(s, t) for w, s, t in calls if w and s is not None]
    if over:
        s, t = over[0]
        check('the setback start is clear of the pins', s[0][1] - gy0 >= 10, s[0][:3])
        check('the setback end is clear of the pins', gy0 + 99 - t[0][1] >= 10, t[0][:3])
    path = corridors.get('row')
    check('the group has a corridor', bool(path))
    if path:
        check('the corridor still starts at the terminal', path[0][:2] == (gx0, gy0), path[0])
        check('the corridor still ends at the other terminal', path[-1][:2] == (gx0, gy0 + 99), path[-1])


def main():
    with tempfile.TemporaryDirectory() as tmp:
        t_wide_rung_routes_past_a_setback(tmp)
    print(f"\n{len(fails)} failure(s)" if fails else "\nall passed")
    return 1 if fails else 0


def test_main():
    assert main() == 0


if __name__ == '__main__':
    sys.exit(main())
