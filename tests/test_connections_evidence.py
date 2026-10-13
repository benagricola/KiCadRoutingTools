#!/usr/bin/env python3
"""--connections failure evidence end to end (placemat fork, docs/connections.md): boards built to fail one way each.

Run with KICAD_NET_RESCUE=0 (env_knobs.py): the per-net fine-parameter rescue spends more than ten minutes on each of
these sealed boards and records no search of its own, so it adds time and no evidence.

    python3 tests/test_connections_evidence.py
"""
import json
import math
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, 'py_router'))
sys.path.insert(0, HERE)

from run_utils import evidence  # noqa: E402
from failure_evidence import VERDICTS, _BLOCKER  # noqa: E402

fails = []
WIDTHS = {"F.Cu": 1.0, "B.Cu": 1.0}


def check(name, cond, detail=''):
    print(('PASS: ' if cond else 'FAIL: ') + name + (f'  {detail}' if detail else ''))
    if not cond:
        fails.append(name)


def _tht(ref, x, y, pads, size=1.7):
    """A through-hole footprint: pads [(number, dx, dy, net id, net name)] on *.Cu."""
    body = ''.join(f'  (pad "{n}" thru_hole circle (at {dx} {dy}) (size {size} {size}) (drill 1.0) '
                   f'(layers "*.Cu") (net {nid} "{name}"))\n' for n, dx, dy, nid, name in pads)
    return (f' (footprint "t:T" (layer "F.Cu") (at {x} {y})\n'
            f'  (property "Reference" "{ref}" (at 0 -2) (layer "F.SilkS"))\n{body} )\n')


def _seg(x1, y1, x2, y2, width, layer, net):
    return (f' (segment (start {x1} {y1}) (end {x2} {y2}) (width {width}) (layer "{layer}") (net {net}) '
            f'(uuid "s{x1}{y1}{layer}"))\n')


def _board(path, extra=(), nets=('VB',)):
    """J1.1 and J2.1 on VB; `extra` footprint or segment texts; `nets` every net name, VB first (ids from 1)."""
    parts = [_tht('J1', 3, 6, [('1', 0, 0, 1, 'VB')]), _tht('J2', 27, 6, [('1', 0, 0, 1, 'VB')])] + list(extra)
    txt = ('(kicad_pcb\n (version 20221018)\n (generator "test_evidence")\n (general (thickness 1.6))\n'
           ' (layers (0 "F.Cu" signal) (31 "B.Cu" signal) (44 "Edge.Cuts" user))\n (net 0 "")\n'
           + ''.join(f' (net {i} "{n}")\n' for i, n in enumerate(nets, 1))
           + ' (gr_rect (start 0 0) (end 30 12) (layer "Edge.Cuts") (width 0.1))\n' + ''.join(parts) + ')\n')
    with open(path, 'w', encoding='utf-8') as f:
        f.write(txt)
    doc = {"board": {"design_settings": {"rules": {"min_clearance": 0.2, "min_track_width": 0.2}}},
           "net_settings": {"classes": [{"name": "Default", "clearance": 0.2, "track_width": 0.2,
                                         "via_diameter": 0.6, "via_drill": 0.3}]}}
    with open(os.path.splitext(path)[0] + '.kicad_pro', 'w', encoding='utf-8') as f:
        json.dump(doc, f)


def _run(tmp, name, extra=(), nets=('VB',), ends=(('J1', 'J2'),)):
    """Route J1.1-J2.1 (or each pair of `ends`) on a board of `extra`; (the first record, the summary, the log) or
    (None, None, None) after a failed check."""
    src, out, conn, js = (os.path.join(tmp, name + s) for s in ('_in.kicad_pcb', '_out.kicad_pcb', '_c.json', '_s.json'))
    _board(src, extra, nets)
    with open(conn, 'w', encoding='utf-8') as f:
        json.dump([{"net": "VB", "from": {"ref": a, "pad": "1"}, "to": {"ref": b, "pad": "1"},
                    "widths": WIDTHS} for a, b in ends], f)
    evidence(conn, 'connections file')
    r = subprocess.run([sys.executable, '-X', 'utf8', os.path.join(ROOT, 'py_router', 'route.py'), src, out,
                        '--connections', conn, '--layers', 'F.Cu', 'B.Cu', '--no-power-tap-neckdown', '--json-out', js],
                       capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=900,
                       env=dict(os.environ, KICAD_NET_RESCUE='0'))
    log = (r.stdout or '') + (r.stderr or '')
    if r.returncode != 0 or 'Traceback' in log or not os.path.isfile(js):
        check(name + ': route.py ran', False, log[-2000:])
        return None, None, None
    doc = json.load(open(js, encoding='utf-8'))
    return (doc.get('connections') or [None])[0], doc, r.stdout or ''


WALL = [(str(i + 1), 0, round(-5.08 + 2.54 * i, 2), i + 2, 'N%d' % (i + 1)) for i in range(5)]
RING = [(str(i + 1), round(1.9 * math.cos(i * math.pi / 4), 3), round(1.9 * math.sin(i * math.pi / 4), 3), 2, 'N1')
        for i in range(8)]


def t_a_part_on_neither_end_is_named(tmp):
    """U1's five 2.4 mm pads at 2.54 mm pitch wall the board off with 0.14 mm gaps. (1.7 mm pads leave 0.84 mm gaps,
    which KRT's terminal geometry escalation passes at 0.418 mm: the task then reads routed, min_width_mm 0.418.)"""
    rec, _, _ = _run(tmp, 'wall', [_tht('U1', 15, 6, WALL, size=2.4)], ('VB', 'N1', 'N2', 'N3', 'N4', 'N5'))
    if rec is None:
        return
    ev = rec.get('evidence') or {}
    print('  wall diagnosis: %s' % ev.get('diagnosis'))
    check('the task failed', rec['status'] == 'failed' and not rec['joined'], rec)
    check('the record says what was asked', rec['widths'] == WIDTHS and rec['layers'] == ['F.Cu', 'B.Cu'], rec)
    check('net scope', ev.get('scope') == 'net', ev)
    check('U1 is named by its pads', any(b['found_by'] == 'static' and b['kind'] == 'pad' and b['ref'] == 'U1'
                                         for b in ev.get('blocked_by') or ()), ev.get('blocked_by'))
    check('every blocker has the documented keys', all(set(b) == set(_BLOCKER) for b in ev.get('blocked_by') or ()))
    check('the diagnosis is a documented value', ev.get('diagnosis') in ('unknown',) + VERDICTS, ev.get('diagnosis'))


def t_an_end_boxed_in_by_pads_says_so(tmp):
    """J1.1 inside a closed ring of eight pads of N1 (U2)."""
    rec, _, _ = _run(tmp, 'ring', [_tht('U2', 3, 6, RING)], ('VB', 'N1'))
    if rec is None:
        return
    ev = rec.get('evidence') or {}
    check('KRT says boxed in', ev.get('diagnosis') == 'boxed_in_static', ev)
    check('within its iteration bound', all(v.get('iterations', 0) < 20000 for v in ev.get('verdicts') or ()),
          ev.get('verdicts'))
    directions = list((ev.get('search') or {}).values())
    check('a search records iterations and frontier only',
          len(directions) == 2 and all(set(d) == {'iterations', 'frontier_cells'} for d in directions),
          ev.get('search'))
    check('the ring is named by its pads', {b['pad'] for b in ev.get('blocked_by') or ()
                                            if b['found_by'] == 'static' and b['ref'] == 'U2'}
          == {str(i + 1) for i in range(8)}, ev.get('blocked_by'))


def t_a_boxed_in_tap_edge_says_so(tmp):
    """J1.1-J4.1 and J4.1-J3.1, one multipoint group. J3.1 sits 3.5 mm from J4.1 inside a closed ring of eight pads of
    N1 (U2), so the main edge J1-J4 routes and the tap edge J4-J3 fails. The final reconciliation then retries the
    net single-ended and records its own search, so the tap edge's record is read from the first pass's summary
    (`scope: run`)."""
    ring = [(str(i + 1), round(1.6 * math.cos(i * math.pi / 4), 3), round(1.6 * math.sin(i * math.pi / 4), 3), 2,
             'N1') for i in range(8)]
    extra = [_tht('J4', 20, 6, [('1', 0, 0, 1, 'VB')]), _tht('J3', 20, 9.5, [('1', 0, 0, 1, 'VB')], size=1.0),
             _tht('U2', 20, 9.5, ring, size=1.2)]
    rec, _, out = _run(tmp, 'tap', extra, ('VB', 'N1'), ends=(('J1', 'J4'), ('J4', 'J3')))
    if rec is None:
        return
    first = [json.loads(line[len('JSON_SUMMARY: '):]) for line in out.splitlines()
             if line.startswith('JSON_SUMMARY: ')]
    first = [d for d in first if d.get('scope') == 'run']
    failed_tap = first and any(f.get('net_name') == 'VB' for f in first[0].get('failed_multipoint') or ())
    if not failed_tap:
        check('the first pass failed VB in a tap edge', False, first[:1])
        return
    ev = (first[0].get('net_evidence') or {}).get('VB') or {}
    directions = list((ev.get('search') or {}).values())
    check('the tap edge records its search', len(directions) == 2 and all(
        set(d) == {'iterations', 'frontier_cells'} and d['iterations'] is not None for d in directions),
        ev.get('search'))
    check('KRT says the tap edge is boxed in', ev.get('diagnosis') == 'boxed_in_static', ev)
    check('the ring is named by its pads', {b['pad'] for b in ev.get('blocked_by') or ()
                                            if b['found_by'] == 'static' and b['ref'] == 'U2'}
          == {str(i + 1) for i in range(8)}, ev.get('blocked_by'))


def t_earlier_copper_is_named_by_net(tmp):
    """A GND track across the board on each layer."""
    walls = [_seg(15, 0.2, 15, 11.8, 0.5, layer, 2) for layer in ('F.Cu', 'B.Cu')]
    rec, _, _ = _run(tmp, 'tracks', walls, ('VB', 'GND'))
    if rec is None:
        return
    ev = rec.get('evidence') or {}
    check('GND copper is named', any(b['net'] == 'GND' and b['found_by'] in ('static', 'preexisting')
                                     and b['kind'] in ('track', 'copper') for b in ev.get('blocked_by') or ()),
          ev.get('blocked_by'))


def t_joined_narrow_carries_its_narrow_segments(tmp):
    rec, _, _ = _run(tmp, 'narrow', [_seg(3, 6, 27, 6, 0.2, 'F.Cu', 1)])
    if rec is None:
        return
    ev = rec.get('evidence') or {}
    check('joined_narrow', rec['status'] == 'joined_narrow', rec)
    check('narrow_copper, task scope', ev.get('diagnosis') == 'narrow_copper' and ev.get('scope') == 'task', ev)
    check('its narrow segment', [(n['width'], n['need']) for n in ev.get('narrow') or ()] == [(0.2, 1.0)], ev)


def t_a_routed_task_has_no_evidence(tmp):
    rec, doc, _ = _run(tmp, 'clear')
    if rec is None:
        return
    check('routed', rec['status'] == 'routed', rec)
    check('no evidence', rec['evidence'] is None, rec)
    check('no net evidence for VB', 'VB' not in (doc.get('net_evidence') or {}), doc.get('net_evidence'))


if __name__ == '__main__':
    with tempfile.TemporaryDirectory() as tmp:
        t_a_part_on_neither_end_is_named(tmp)
        t_an_end_boxed_in_by_pads_says_so(tmp)
        t_a_boxed_in_tap_edge_says_so(tmp)
        t_earlier_copper_is_named_by_net(tmp)
        t_joined_narrow_carries_its_narrow_segments(tmp)
        t_a_routed_task_has_no_evidence(tmp)
    if fails:
        print(f'{len(fails)} FAILURE(S): {fails}')
        sys.exit(1)
    print('all checks passed')
