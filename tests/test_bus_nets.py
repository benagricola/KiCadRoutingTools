#!/usr/bin/env python3
"""--bus-nets, a stated bus (placemat fork, docs/connections.md).

  * two nets SDA and SCL, one pad pair each: detection drops a group under 3 members, so without the flag there is
    no bus group, and with `--bus-nets SDA SCL` the summary has one stated group of both;
  * `stated_bus_groups` in memory: one BusGroup, net_ids in physical order, named stated_0, a net absent from the
    call left out;
  * names are include patterns as placemat sends them: `\\!RST` names the active-low net only, `D[[]0]` names the net
    D[0] and not D0;
  * --bus-nets repeats, one group per use, and implies --bus.

    python3 tests/test_bus_nets.py
"""
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, 'py_router'))
sys.path.insert(0, HERE)

fails = []
NETS = ['SDA', 'SCL', 'D0', 'D[0]', '!RST', 'RST']


def check(name, cond, detail=''):
    print(('PASS: ' if cond else 'FAIL: ') + name + (f'  {detail}' if detail else ''))
    if not cond:
        fails.append(name)


def _board(path):
    """Each net has one pad on U<i> at x=4 and one on V<i> at x=26, rows 2 mm apart (SDA below SCL)."""
    parts = []
    for i, name in enumerate(NETS):
        y = 4.0 + 2.0 * i
        for ref, x in (('U', 4.0), ('V', 26.0)):
            parts.append(f' (footprint "t:P" (layer "F.Cu") (at {x} {y})\n'
                         f'  (property "Reference" "{ref}{i}" (at 0 -2) (layer "F.SilkS"))\n'
                         f'  (pad "1" smd rect (at 0 0) (size 0.8 0.8) (layers "F.Cu") '
                         f'(net {i + 1} "{name}"))\n )\n')
    nets = ''.join(f' (net {i + 1} "{n}")\n' for i, n in enumerate(NETS))
    txt = ('(kicad_pcb\n (version 20221018)\n (generator "test_bus_nets")\n (general (thickness 1.6))\n'
           ' (layers (0 "F.Cu" signal) (31 "B.Cu" signal) (44 "Edge.Cuts" user))\n (net 0 "")\n' + nets +
           ' (gr_rect (start 0 0) (end 30 20) (layer "Edge.Cuts") (width 0.1))\n' + ''.join(parts) + ')\n')
    with open(path, 'w', encoding='utf-8') as f:
        f.write(txt)
    doc = {"board": {"design_settings": {"rules": {"min_clearance": 0.15, "min_track_width": 0.15}}},
           "net_settings": {"classes": [{"name": "Default", "clearance": 0.15, "track_width": 0.2,
                                         "via_diameter": 0.6, "via_drill": 0.3}]}}
    with open(os.path.splitext(path)[0] + '.kicad_pro', 'w', encoding='utf-8') as f:
        json.dump(doc, f)


def _route(src, out, js, *extra):
    r = subprocess.run([sys.executable, '-X', 'utf8', os.path.join(ROOT, 'py_router', 'route.py'), src, out,
                        '--layers', 'F.Cu', 'B.Cu', '--json-out', js, *extra],
                       capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=900)
    return r.returncode, (r.stdout or '') + (r.stderr or '')


def t_summary(tmp):
    src = os.path.join(tmp, 'in.kicad_pcb')
    _board(src)
    docs = {}
    for tag, extra in (('stated', ['--nets', 'SDA', 'SCL', '--bus-nets', 'SDA', 'SCL']),
                       ('plain', ['--nets', 'SDA', 'SCL', '--bus']),
                       ('two', ['--nets', 'SDA', 'SCL', 'D0', 'D[[]0]', '--bus-nets', 'SDA', 'SCL',
                                '--bus-nets', 'D0', 'D[[]0]']),
                       ('dup', ['--nets', 'SDA', 'SCL', 'D0', '--bus-nets', 'SDA', 'SCL',
                                '--bus-nets', 'SCL', 'D0'])):
        out, js = os.path.join(tmp, tag + '.kicad_pcb'), os.path.join(tmp, tag + '.json')
        rc, log = _route(src, out, js, *extra)
        if rc != 0 or 'Traceback' in log:
            check(f'route.py ran ({tag})', False, log[-2000:])
            return
        docs[tag] = json.load(open(js, encoding='utf-8'))
    groups = docs['stated'].get('bus_groups') or []
    check('the stated pair is one bus group',
          len(groups) == 1 and groups[0]['origin'] == 'stated' and sorted(groups[0]['nets']) == ['SCL', 'SDA'],
          groups)
    check('a group record has name and demoted', groups and set(groups[0]) == {'name', 'nets', 'origin', 'demoted'},
          groups)
    check('without the stated bus detection finds none', not (docs['plain'].get('bus_groups') or []),
          docs['plain'].get('bus_groups'))
    g2 = docs['two'].get('bus_groups') or []
    check('--bus-nets repeats, one group per use',
          sorted(sorted(g['nets']) for g in g2) == [['D0', 'D[0]'], ['SCL', 'SDA']], g2)
    g3 = docs['dup'].get('bus_groups') or []
    check('a net named in two uses is in the first group only',
          [g['name'] for g in g3] == ['stated_0'] and sorted(g3[0]['nets']) == ['SCL', 'SDA'], g3)


def t_memory(tmp):
    from kicad_parser import parse_kicad_pcb
    from routing_config import GridRouteConfig
    from bus_detection import stated_bus_groups, resolve_stated_buses
    src = os.path.join(tmp, 'm.kicad_pcb')
    _board(src)
    pcb = parse_kicad_pcb(src)
    ids = {n.name: i for i, n in pcb.nets.items()}
    # order is by position: SDA (row 0) above SCL (row 1) -> ys, ties on x, so physical order is SDA, SCL
    config = GridRouteConfig()
    config.stated_buses = [[ids['SCL'], ids['SDA']]]
    groups = stated_bus_groups(pcb, config)
    check('one BusGroup from a stated list', len(groups) == 1 and groups[0].name == 'stated_0', groups)
    if groups:
        check('net_ids in physical order', groups[0].net_ids == [ids['SDA'], ids['SCL']], groups[0].net_ids)
        check('endpoints are parallel to net_ids', len(groups[0].source_positions) == 2
              and len(groups[0].target_positions) == 2)
    check('a group left with one routable net is dropped',
          stated_bus_groups(pcb, config, present={ids['SDA']}) == [])
    config.stated_buses = [[ids['SCL'], ids['SDA'], ids['D0']]]
    check('a net absent from the call is left out',
          [sorted(g.net_ids) for g in stated_bus_groups(pcb, config, present={ids['SDA'], ids['SCL']})]
          == [sorted([ids['SDA'], ids['SCL']])])
    config.stated_buses = [[ids['SCL'], ids['SDA']]]
    config.stated_buses = [[ids['SDA'], ids['SCL']], [ids['SCL'], ids['D0'], ids['D[0]']]]
    g = stated_bus_groups(pcb, config)
    check('a net named twice stays in the first group',
          [sorted(x.net_ids) for x in g] == [sorted([ids['SDA'], ids['SCL']]), sorted([ids['D0'], ids['D[0]']])]
          and [x.name for x in g] == ['stated_0', 'stated_1'], [(x.name, x.net_ids) for x in g])
    config.stated_buses = [[ids['SDA'], ids['SCL']], [ids['SCL'], ids['D0']]]
    check('a later group left with one net is dropped', [x.name for x in stated_bus_groups(pcb, config)] == ['stated_0'])
    config.stated_buses = [[ids['SCL'], ids['SDA']]]
    # names are include patterns
    r = resolve_stated_buses(pcb, [['\\!RST'], ['RST'], ['D[[]0]'], ['D0'], ['D[0]'], ['NOPE', 'SDA']])
    check('\\!RST names the active-low net only', r[0] == [ids['!RST']], r[0])
    check('RST names RST only', r[1] == [ids['RST']], r[1])
    check('D[[]0] names D[0] only', r[2] == [ids['D[0]']], r[2])
    check('D0 names D0 only', r[3] == [ids['D0']], r[3])
    check('a bare D[0] is the class pattern and names D0', r[4] == [ids['D0']], r[4])
    check('a name with no net is dropped', r[5] == [ids['SDA']], r[5])


def main():
    with tempfile.TemporaryDirectory() as tmp:
        t_memory(tmp)
        t_summary(tmp)
    print(f"\n{len(fails)} failure(s)" if fails else "\nall passed")
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
