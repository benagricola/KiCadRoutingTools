#!/usr/bin/env python3
"""Fork: the bus corridor probe keeps the bus siblings' pads as obstacles.

The probe map is built with every bus member left out, so that the members'
present stubs do not veto the corridor. That also took their PADS off the map:
on a fine-pitch row the representative's probe ran its terminal across a
sibling's pin, the terminal graze gate (which measures against all foreign
copper) refused it, and every rung failed although a plain member route left
the row cleanly. The probe now routes on a copy with the siblings' pads back.

Run:
    python3 tests/test_bus_corridor_sibling_pads.py
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


def t_probe_map_keeps_sibling_pads(tmp):
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
    seen = []
    real = single_ended_routing.route_net_with_obstacles

    def record(pcb_data, net_id, cfg, obstacles, **kw):
        seen.append((net_id, obstacles))
        return None                                   # every rung "fails": only the maps are of interest
    single_ended_routing.route_net_with_obstacles = record
    try:
        bus_corridor.plan_bus_corridors(pcb, config, [group])
    finally:
        single_ended_routing.route_net_with_obstacles = real

    check('the planner probed the group', bool(seen), len(seen))
    if not seen:
        return
    rep, obstacles = seen[0]
    coord = GridCoord(config.grid_step)
    for i, name in enumerate(NETS):
        if ids[name] == rep:
            continue
        gx, gy = coord.to_grid(10.0 + PITCH * i, 4.0)
        check(f'sibling {name} pad blocks the probe of the representative',
              obstacles.is_blocked(gx, gy, 0), (gx, gy))
    rx, ry = coord.to_grid(10.0 + PITCH * NETS.index(pcb.nets[rep].name), 4.0)
    check('the representative still reaches its own pad', not obstacles.is_blocked(rx, ry, 0), (rx, ry))


def main():
    with tempfile.TemporaryDirectory() as tmp:
        t_probe_map_keeps_sibling_pads(tmp)
    print(f"\n{len(fails)} failure(s)" if fails else "\nall passed")
    return 1 if fails else 0


def test_main():
    assert main() == 0


if __name__ == '__main__':
    sys.exit(main())
