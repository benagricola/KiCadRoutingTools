#!/usr/bin/env python3
"""Task 4 (docs/off-grid-exact-fit-plan.md): exact escape stubs.

The board is the MCU module's neighbourhood of pins gpio23 and gpio24 (a
0.4 mm pitch QFN row, 0.2/0.2): the supply pin between them serves an 0402
turned 45 degrees past the row, with its trace and via-in-pad; the pins
either side carry their hand-routed tracks. gpio23 and gpio24 each escape
only by an exact fit, every clearance at the rule and the turns off the
0.1 mm grid (the designer's own paths do). Coordinates are the module's.

Run: python3 -X utf8 tests/test_exact_escape.py
"""
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'py_router'))

from kicad_parser import parse_kicad_pcb, Segment  # noqa: E402
from routing_config import GridRouteConfig, GridCoord  # noqa: E402
from check_drc import check_pad_segment_overlap, check_segment_overlap, check_via_segment_overlap  # noqa: E402
from exact_escape import exact_escapes  # noqa: E402

CX, CY = 14.0, 13.6
_fails = []


def check(name, cond, detail=''):
    print(('PASS ' if cond else 'FAIL ') + name + ('' if cond else ': ' + detail))
    if not cond:
        _fails.append(name)


ROW = [(21, 'gpio21', -3.8), (22, 'gpio22', -3.4), (23, 'gpio23', -3.0), (24, 'v3v3', -2.6),
       (25, 'gpio24', -2.2), (26, 'gpio25', -1.8), (27, 'gpio26', -1.4), (28, 'gpio27', -1.0),
       (29, 'v3v3', -0.6), (30, 'OSC_XIN', -0.2), (31, 'OSC_XOUT', 0.2), (32, 'V1V1', 0.6)]
WEST = [(15, 'v3v3', 1.8), (16, 'gpio16', 2.2), (17, 'gpio17', 2.6), (18, 'gpio18', 3.0),
        (19, 'gpio19', 3.4), (20, 'gpio20', 3.8)]
PARTS = [('C9', 1, 'v3v3', -1.0106, 6.4606, 225, 0.56, 0.62), ('C9', 2, 'gnd', -1.6894, 7.1394, 225, 0.56, 0.62),
         ('C7', 1, 'v3v3', -5.97, 1.8, 180, 0.56, 0.62), ('C20', 1, 'OSC_XIN', -2.5606, 8.2106, 225, 0.56, 0.62),
         ('C8', 1, 'v3v3', -2.9212, 6.5212, 225, 0.56, 0.62), ('C8', 2, 'gnd', -3.6, 7.2, 225, 0.56, 0.62),
         ('R4', 2, 'OSC_XOUT', 0.25, 7.2, 135, 0.54, 0.64)]
TRACKS = [('V1V1', 0.6, 6.4606, 1.0106, 6.4606), ('V1V1', 0.6, 4.91, 0.6, 6.4606),
          ('v3v3', -2.6, 4.91, -2.6, 6.5212), ('v3v3', -0.6, 6.4606, -1.0106, 6.4606),
          ('v3v3', -0.6, 4.91, -0.6, 6.4606), ('v3v3', -2.6, 6.5212, -2.9212, 6.5212),
          ('v3v3', -5.97, 1.8, -4.91, 1.8), ('gpio16', -3.75, 2.2, -2.95, 1.4), ('gpio16', -4.91, 2.2, -3.75, 2.2),
          ('gpio21', -3.8, 5.406, -4.452, 6.058), ('gpio21', -3.8, 4.91, -3.8, 5.406),
          ('gpio22', -3.4, 5.5716, -4.2142, 6.3858), ('gpio22', -3.4, 4.91, -3.4, 5.5716),
          ('gpio25', -2.0, 3.8, -2.35, 3.8), ('gpio25', -1.8, 4.91, -1.8, 4.0), ('gpio25', -1.8, 4.0, -2.0, 3.8),
          ('gpio26', -1.4, 3.35, -1.75, 3.0), ('gpio26', -1.75, 3.0, -2.35, 3.0), ('gpio26', -1.4, 4.91, -1.4, 3.35),
          ('gpio27', -1.0, 4.91, -1.0, 2.95), ('gpio27', -1.75, 2.2, -2.35, 2.2), ('gpio27', -1.0, 2.95, -1.75, 2.2),
          ('OSC_XIN', -0.2, 6.6563, -0.2, 4.91), ('OSC_XIN', -1.7543, 8.2106, -0.2, 6.6563),
          ('OSC_XIN', -1.6289, 9.1423, -2.5606, 8.2106), ('OSC_XIN', -2.5606, 8.2106, -1.7543, 8.2106),
          ('OSC_XOUT', 0.2, 7.15, 0.25, 7.2), ('OSC_XOUT', 0.2, 4.91, 0.2, 7.15)]
VIAS = [('gnd', -1.6894, 7.1394), ('gnd', -3.6, 7.2), ('v3v3', -2.9212, 6.5212), ('v3v3', -1.0106, 6.4606),
        ('v3v3', -5.97, 1.8), ('gpio25', -2.35, 3.8), ('gpio26', -2.35, 3.0), ('gpio27', -2.35, 2.2)]
SINKS = [('gpio23', -7.0, 10.5), ('gpio24', -6.0, 11.5)]


def board(walls=(), routed=()):
    """The board's text; `walls`: extra foreign pads (net, x, y, w, h), chip-relative.
    Tracks and vias carry uuids, as a KiCad file's do, except those of the
    nets in `routed`: copper the router laid in this run has none."""
    names = sorted({n for _, n, _ in ROW + WEST} | {p[2] for p in PARTS} | {t[0] for t in TRACKS}
                   | {v[0] for v in VIAS} | {'wall'})
    nid = {n: i + 1 for i, n in enumerate(names)}
    out = ['(kicad_pcb\n\t(version 20241229)\n\t(generator "test")\n',
           '\t(layers\n\t\t(0 "F.Cu" signal)\n\t\t(2 "B.Cu" signal)\n\t\t(25 "Edge.Cuts" user)\n\t)\n',
           '\t(net 0 "")\n'] + ['\t(net %d "%s")\n' % (nid[n], n) for n in names]
    pads = ''.join('\t\t(pad "%d" smd rect (at %g 4.91) (size 0.2 0.665) (layers "F.Cu") (net %d "%s"))\n'
                   % (k, x, nid[n], n) for k, n, x in ROW)
    pads += ''.join('\t\t(pad "%d" smd rect (at -4.91 %g) (size 0.665 0.2) (layers "F.Cu") (net %d "%s"))\n'
                    % (k, y, nid[n], n) for k, n, y in WEST)
    out.append('\t(footprint "t:qfn" (layer "F.Cu") (at %g %g)\n\t\t(property "Reference" "U2" (at 0 0))\n%s\t)\n'
               % (CX, CY, pads))
    for ref, num, n, x, y, rot, w, h in PARTS:
        out.append('\t(footprint "t:part" (layer "F.Cu") (at %g %g %g)\n\t\t(property "Reference" "%s_%d" (at 0 0))\n'
                   '\t\t(pad "%d" smd roundrect (at 0 0 %g) (size %g %g) (layers "F.Cu") (roundrect_rratio 0.25) (net %d "%s"))\n\t)\n'
                   % (CX + x, CY + y, rot, ref, num, num, rot, w, h, nid[n], n))
    for k, (n, x, y, w, h) in enumerate(walls):
        out.append('\t(footprint "t:wall" (layer "F.Cu") (at %g %g)\n\t\t(property "Reference" "W%d" (at 0 0))\n'
                   '\t\t(pad "1" smd rect (at 0 0) (size %g %g) (layers "F.Cu") (net %d "%s"))\n\t)\n'
                   % (CX + x, CY + y, k, w, h, nid[n], n))
    for n, x, y in SINKS:
        out.append('\t(footprint "t:sink" (layer "F.Cu") (at %g %g)\n\t\t(property "Reference" "S_%s" (at 0 0))\n'
                   '\t\t(pad "1" smd rect (at 0 0) (size 0.6 0.6) (layers "F.Cu") (net %d "%s"))\n\t)\n'
                   % (CX + x, CY + y, n, nid[n], n))
    uid = lambda k, n: '' if n in routed else ' (uuid "00000000-0000-0000-0000-%012d")' % k
    for k, (n, x1, y1, x2, y2) in enumerate(TRACKS):
        out.append('\t(segment (start %g %g) (end %g %g) (width 0.2) (layer "F.Cu") (net %d)%s)\n'
                   % (round(CX + x1, 6), round(CY + y1, 6), round(CX + x2, 6), round(CY + y2, 6), nid[n], uid(k, n)))
    for k, (n, x, y) in enumerate(VIAS):
        out.append('\t(via (at %g %g) (size 0.6) (drill 0.3) (layers "F.Cu" "B.Cu") (net %d)%s)\n'
                   % (round(CX + x, 6), round(CY + y, 6), nid[n], uid(1000 + k, n)))
    out.append('\t(gr_rect (start %g %g) (end %g %g) (stroke (width 0.1) (type solid)) (fill no) (layer "Edge.Cuts"))\n'
               % (CX - 10, CY - 2, CX + 4, CY + 14))
    return ''.join(out) + ')\n'


def parse(text):
    fd, path = tempfile.mkstemp(suffix='.kicad_pcb')
    os.close(fd)
    with open(path, 'w') as fh:
        fh.write(text)
    try:
        return parse_kicad_pcb(path)
    finally:
        os.unlink(path)


def pad_of(pcb, number):
    return next(p for p in pcb.footprints['U2'].pads if p.pad_number == str(number))


def drc_clean(pcb, net_id, segs, clearance=0.2):
    """Every stub segment against every foreign pad, track and via, no margin."""
    for s in segs:
        for fp in pcb.footprints.values():
            for p in fp.pads:
                if p.net_id != net_id and check_pad_segment_overlap(p, s, clearance, ['F.Cu', 'B.Cu'], 1e-6 / clearance)[0]:
                    return 'pad %s.%s' % (p.component_ref, p.pad_number)
        for t in pcb.segments:
            if t.net_id != net_id and check_segment_overlap(s, t, clearance, 1e-6 / clearance)[0]:
                return 'track of net %d' % t.net_id
        for v in pcb.vias:
            if v.net_id != net_id and check_via_segment_overlap(v, s, clearance, 1e-6 / clearance)[0]:
                return 'via of net %d' % v.net_id
    return ''


def open_cells(pcb, config):
    """The routing map's test for a cell a stub may end on: the base map
    of the board with gpio23 and gpio24 to route."""
    from obstacle_map import build_base_obstacle_map
    ids = [nid for nid, n in pcb.nets.items() if n.name in ('gpio23', 'gpio24')]
    obs = build_base_obstacle_map(pcb, config, nets_to_route=ids)
    return lambda gx, gy, li: not obs.is_blocked(gx, gy, li)


config = GridRouteConfig(track_width=0.2, clearance=0.2, grid_step=0.1, layers=['F.Cu'])
coord = GridCoord(0.1)
pcb = parse(board())
is_open = open_cells(pcb, config)
for number, name in ((25, 'gpio24'), (23, 'gpio23')):
    pad = pad_of(pcb, number)
    start = [coord.to_grid(pad.global_x, pad.global_y) + (0,)]
    stubs = exact_escapes(pcb, pad.net_id, pad, config, coord, ['F.Cu'], is_open=is_open, start_cells=start)
    check('%s: stubs are found' % name, bool(stubs))
    bad = [drc_clean(pcb, pad.net_id, segs) for _e, segs in stubs]
    check('%s: every stub keeps its clearance, exactly' % name, stubs and not any(bad), repr([b for b in bad if b][:3]))
    ends_ok = all(abs(segs[-1].end_x - coord.to_float(e[0], e[1])[0]) < 1e-9
                  and abs(segs[-1].end_y - coord.to_float(e[0], e[1])[1]) < 1e-9 for e, segs in stubs)
    check('%s: every stub ends on its grid cell' % name, ends_ok)
    starts = all(abs(segs[0].start_x - pad.global_x) < 1e-9 and abs(segs[0].start_y - pad.global_y) < 1e-9
                 for _e, segs in stubs)
    check('%s: every stub starts at the pad centre' % name, starts)
    if stubs:
        print('   shortest: ' + ' -> '.join('(%.4f, %.4f)' % (s.start_x - CX, s.start_y - CY) for s in stubs[0][1])
              + ' -> (%.4f, %.4f)' % (stubs[0][1][-1].end_x - CX, stubs[0][1][-1].end_y - CY))

from exact_escape import walled_by_routed  # noqa: E402

pad = pad_of(pcb, 25)
start = [coord.to_grid(pad.global_x, pad.global_y) + (0,)]
check("gpio24 walled in by fixed copper only: stubs are for it",
      not walled_by_routed(pcb, pad.net_id, config, coord, ['F.Cu'], is_open, start))
routed = parse(board(routed=('v3v3',)))
pad = pad_of(routed, 25)
check("gpio24 walled in partly by copper routed this run (v3v3's trace): rip-up's, not a stub's",
      walled_by_routed(routed, pad.net_id, config, coord, ['F.Cu'], open_cells(routed, config), start))

walled = parse(board(walls=[('wall', -2.2, 5.6, 6.0, 0.6)]))
pad = pad_of(walled, 25)
check('a pad walled in on its layer has no stub',
      exact_escapes(walled, pad.net_id, pad, config, coord, ['F.Cu'], is_open=open_cells(walled, config),
                    start_cells=[coord.to_grid(pad.global_x, pad.global_y) + (0,)]) == [])


def copper_by_net(path):
    p = parse_kicad_pcb(path)
    out = {}
    for t in p.segments:
        out.setdefault(p.nets[t.net_id].name, []).append(
            tuple(round(v, 4) for v in (t.start_x, t.start_y, t.end_x, t.end_y)))
    return {k: sorted(v) for k, v in out.items()}


def kicad_copper_violations(path):
    """KiCad's own DRC: clearance, short and crossing violations (None
    without kicad-cli). KiCad works in whole nanometres, so a fit exactly at
    the rule passes it, as the designer's own layout of these pins does;
    check_drc at no margin grades the nanometre residue of such a fit."""
    import shutil
    if not shutil.which('kicad-cli'):
        return None
    out = path + '.drc.json'
    subprocess.run(['kicad-cli', 'pcb', 'drc', '--format', 'json', '-o', out, path], capture_output=True)
    j = json.load(open(out))
    return [v['type'] for v in j.get('violations', [])
            if v['type'] in ('clearance', 'shorting_items', 'tracks_crossing', 'hole_clearance')]


with tempfile.TemporaryDirectory() as tmp:
    src = os.path.join(tmp, 'b.kicad_pcb')
    with open(src, 'w') as fh:
        fh.write(board())
    runs = {}
    for knob in ('1', '0'):
        out = os.path.join(tmp, 'o%s.kicad_pcb' % knob)
        js = os.path.join(tmp, 'j%s.json' % knob)
        r = subprocess.run([sys.executable, '-X', 'utf8', os.path.join(ROOT, 'py_router', 'route.py'), src, out,
                            '--nets', 'gpio23', 'gpio24', '--layers', 'F.Cu', '--track-width', '0.2',
                            '--clearance', '0.2', '--escalation', 'off', '--json-out', js],
                           capture_output=True, text=True, cwd=ROOT, env=dict(os.environ, KICAD_EXACT_ESCAPE=knob))
        runs[knob] = (out, json.load(open(js)) if os.path.isfile(js) else {}, r.stdout)
    out, j, log = runs['1']
    check('route: both nets route', not j.get('failed_single'), repr(j.get('failed_single')))
    c = subprocess.run([sys.executable, '-X', 'utf8', os.path.join(ROOT, 'py_router', 'check_connected.py'), out,
                        '--nets', 'gpio23', 'gpio24', '--quiet'], capture_output=True, text=True, cwd=ROOT)
    check('route: gpio23 and gpio24 are connected',
          'connectivity... OK' in c.stdout and 'FAILED' not in c.stdout, c.stdout[-300:])
    v = kicad_copper_violations(out)
    check("route: KiCad's DRC finds no clearance violation", v is None or v == [], repr(v))
    before, after = copper_by_net(src), copper_by_net(out)
    changed = [n for n in before if before[n] != after.get(n)]
    check('route: every other net keeps its copper', not changed, repr(changed))
    check('with KICAD_EXACT_ESCAPE=0 no stub is used', 'Exact escape' not in runs['0'][2])

sys.exit(1 if _fails else 0)
