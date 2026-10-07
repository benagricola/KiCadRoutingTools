#!/usr/bin/env python3
"""--connections end to end (placemat fork, docs/connections.md).

A net PWR on pads A (U1.1), B (U2.1), C (U3.1) and a sibling pad of A (U1.2), on F.Cu and B.Cu, with a wall of
another net's pads across F.Cu so A-B must drop to B.Cu. route.py with --connections A-B at {F.Cu: 0.5, B.Cu: 0.3}:
  * the task is routed and joined, new copper sits at the asked width on each layer, and C and the sibling get none;
  * the private net's name reaches neither the output board nor its project;
  * a second run on the routed board reports joined_before, through the nothing-to-route early return;
  * a board whose A-B is already joined by a 0.2 mm track reports joined_narrow with that track as its path, counts
    it joined and lays no new copper (the D3 fallback);
  * --connections refuses --nets alongside;
  * batch_route in process with final_reconcile=False writes the key.

    python3 tests/test_connections_route.py
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

from run_utils import evidence  # noqa: E402

fails = []
A, B, C, SIB = (4.0, 10.0), (26.0, 10.0), (8.0, 4.0), (4.0, 12.0)
WIDTHS = {"F.Cu": 0.5, "B.Cu": 0.3}


def check(name, cond, detail=''):
    print(('PASS: ' if cond else 'FAIL: ') + name + (f'  {detail}' if detail else ''))
    if not cond:
        fails.append(name)


def _fp(ref, x, y, net, name, pads=(('1', 0, 0),)):
    body = ''.join(f'  (pad "{n}" smd rect (at {dx} {dy}) (size 1 1) (layers "F.Cu") (net {net} "{name}"))\n'
                   for n, dx, dy in pads)
    return (f' (footprint "t:P" (layer "F.Cu") (at {x} {y})\n'
            f'  (property "Reference" "{ref}" (at 0 -2) (layer "F.SilkS"))\n{body} )\n')


def _board(path, wall=True, stub=False):
    parts = [_fp('U1', A[0], A[1], 1, 'PWR', (('1', 0, 0), ('2', 0, SIB[1] - A[1]))),
             _fp('U2', B[0], B[1], 1, 'PWR'), _fp('U3', C[0], C[1], 1, 'PWR')]
    if wall:
        pads, y, i = [], 0.6, 0
        while y < 19.5:
            i += 1
            pads.append((str(i), 0, round(y - 10.0, 3)))
            y += 0.9
        parts.append(_fp('J1', 15, 10, 2, 'SIG', pads).replace('(size 1 1)', '(size 0.8 0.8)'))
    if stub:
        parts.append(f' (segment (start {A[0]} {A[1]}) (end {B[0]} {B[1]}) (width 0.2) (layer "F.Cu") (net 1) '
                     f'(uuid "stub"))\n')
    txt = ('(kicad_pcb\n (version 20221018)\n (generator "test_connections")\n (general (thickness 1.6))\n'
           ' (layers (0 "F.Cu" signal) (31 "B.Cu" signal) (44 "Edge.Cuts" user))\n'
           ' (net 0 "")\n (net 1 "PWR")\n (net 2 "SIG")\n'
           ' (gr_rect (start 0 0) (end 30 20) (layer "Edge.Cuts") (width 0.1))\n'
           + ''.join(parts) + ')\n')
    with open(path, 'w', encoding='utf-8') as f:
        f.write(txt)
    doc = {"board": {"design_settings": {"rules": {"min_clearance": 0.15, "min_track_width": 0.15}}},
           "net_settings": {"classes": [{"name": "Default", "clearance": 0.15, "track_width": 0.2,
                                         "via_diameter": 0.6, "via_drill": 0.3}]}}
    with open(os.path.splitext(path)[0] + '.kicad_pro', 'w', encoding='utf-8') as f:
        json.dump(doc, f)


def _tasks(path):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump([{"net": "PWR", "from": {"ref": "U1", "pad": "1"}, "to": {"ref": "U2", "pad": "1"},
                    "widths": WIDTHS}], f)


def _route(src, out, conn, js, *extra):
    r = subprocess.run([sys.executable, '-X', 'utf8', os.path.join(ROOT, 'py_router', 'route.py'), src, out,
                        '--connections', conn, '--layers', 'F.Cu', 'B.Cu', '--json-out', js, *extra],
                       capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=900)
    return r.returncode, (r.stdout or '') + (r.stderr or '')


def _key(s):
    return (s.layer, round(s.start_x, 3), round(s.start_y, 3), round(s.end_x, 3), round(s.end_y, 3), round(s.width, 4))


def _new(src, out):
    from kicad_parser import parse_kicad_pcb
    before = {_key(s) for s in parse_kicad_pcb(src).segments}
    return [s for s in parse_kicad_pcb(out).segments if _key(s) not in before]


def _touches(s, at, half=0.5 + 0.05):
    return any(abs(x - at[0]) <= half and abs(y - at[1]) <= half for x, y in ((s.start_x, s.start_y),
                                                                                (s.end_x, s.end_y)))


def t_routed_then_joined(tmp):
    src, out, conn, js = (os.path.join(tmp, n) for n in ('in.kicad_pcb', 'out.kicad_pcb', 'c.json', 's.json'))
    _board(src)
    _tasks(conn)
    rc, log = _route(src, out, conn, js)
    if rc != 0 or 'Traceback' in log:
        check('route.py ran', False, log[-2000:])
        return
    evidence(out, 'routed board')
    doc = json.load(open(js, encoding='utf-8'))
    rec = (doc.get('connections') or [None])[0]
    check('the summary carries one record per task', len(doc.get('connections') or []) == 1, sorted(doc))
    if rec is None:
        return
    new = _new(src, out)
    check('the task is routed and joined', rec['status'] == 'routed' and rec['joined'], rec)
    check('the record has its length', isinstance(rec['length_mm'], float) and rec['length_mm'] > 20.0, rec)
    check('the record ends are structured', rec['from'] == {"ref": "U1", "pad": "1"} and rec['reason'] is None, rec)
    check('the wall forces copper onto B.Cu', any(s.layer == 'B.Cu' for s in new), [_key(s) for s in new])
    check('new copper on F.Cu is at its asked width',
          all(abs(s.width - 0.5) < 1e-3 for s in new if s.layer == 'F.Cu'), [_key(s) for s in new])
    check('new copper on B.Cu is at its asked width',
          all(abs(s.width - 0.3) < 1e-3 for s in new if s.layer == 'B.Cu'), [_key(s) for s in new])
    check('min_width_mm is the asked width per layer',
          rec['min_width_mm'].get('F.Cu', 0) >= 0.5 - 1e-3 and rec['min_width_mm'].get('B.Cu', 0) >= 0.3 - 1e-3, rec)
    check('C gets no new copper', not any(_touches(s, C) for s in new))
    check('the sibling pad of A gets no new copper (D4)', not any(_touches(s, SIB) for s in new))
    out_pro = os.path.splitext(out)[0] + '.kicad_pro'
    pro_txt = open(out_pro, encoding='utf-8').read() if os.path.isfile(out_pro) else ''
    check('the private net name is in neither output file',
          '__connections_private' not in open(out, encoding='utf-8').read()
          and '__connections_private' not in pro_txt)

    out2, js2 = os.path.join(tmp, 'out2.kicad_pcb'), os.path.join(tmp, 's2.json')
    rc, log = _route(out, out2, conn, js2)
    if rc != 0 or 'Traceback' in log:
        check('route.py ran a second time', False, log[-2000:])
        return
    doc2 = json.load(open(js2, encoding='utf-8'))
    rec2 = (doc2.get('connections') or [{}])[0]
    check('a second run reports joined_before', rec2.get('status') == 'joined_before' and rec2.get('joined'), doc2)
    check('a second run lays no copper', not _new(out, out2))


def t_joined_narrow(tmp):
    src, out, conn, js = (os.path.join(tmp, n) for n in ('n_in.kicad_pcb', 'n_out.kicad_pcb', 'n.json', 'ns.json'))
    _board(src, wall=False, stub=True)
    _tasks(conn)
    rc, log = _route(src, out, conn, js)
    if rc != 0 or 'Traceback' in log:
        check('route.py ran on the stub board', False, log[-2000:])
        return
    rec = (json.load(open(js, encoding='utf-8')).get('connections') or [{}])[0]
    check('joined by a narrower track is joined_narrow and counted joined',
          rec.get('status') == 'joined_narrow' and rec.get('joined') is True, rec)
    check('its narrowest width is the stub width', rec.get('min_width_mm') == {"F.Cu": 0.2}, rec)
    check('its path is the stub',
          rec.get('path') == [{"layer": "F.Cu", "start": [A[0], A[1]], "end": [B[0], B[1]], "width": 0.2}], rec)
    check('no new copper is laid (D3 fallback)', not _new(src, out), [_key(s) for s in _new(src, out)])


def t_refuses_nets(tmp):
    src, conn = os.path.join(tmp, 'r_in.kicad_pcb'), os.path.join(tmp, 'r.json')
    _board(src)
    _tasks(conn)
    rc, log = _route(src, os.path.join(tmp, 'r_out.kicad_pcb'), conn, os.path.join(tmp, 'r.s.json'), '--nets', 'PWR')
    check('--connections with --nets is refused', rc == 2 and '--connections' in log, (rc, log[-400:]))


def t_refused_lays_nothing(tmp):
    """A net whose every task is refused, or which is not on the board, is left alone and still reported."""
    src = os.path.join(tmp, 'f_in.kicad_pcb')
    _board(src, wall=False)
    cases = [('width_under_board_minimum', "PWR", ("U1", "1"), ("U2", "1"), {"F.Cu": 0.05, "B.Cu": 0.05}),
             ('unknown_pad', "PWR", ("U1", "9"), ("U2", "1"), WIDTHS),
             ('pad_not_on_net', "PWR", ("U1", "1"), ("J9", "1"), WIDTHS),
             ('layer_width_missing', "PWR", ("U1", "1"), ("U2", "1"), {"F.Cu": 0.5}),
             ('pad_not_on_net', "NOPE", ("U1", "1"), ("U2", "1"), WIDTHS)]
    with open(src, encoding='utf-8') as f:
        txt = f.read()
    with open(src, 'w', encoding='utf-8') as f:     # J9.1 on another net, for pad_not_on_net
        f.write(txt.rstrip().rstrip(')') + _fp('J9', 20, 16, 2, 'SIG') + ')\n')
    for i, (reason, net, a, b, widths) in enumerate(cases):
        conn, out, js = (os.path.join(tmp, f'f{i}.{e}') for e in ('json', 'kicad_pcb', 's.json'))
        with open(conn, 'w', encoding='utf-8') as f:
            json.dump([{"net": net, "from": {"ref": a[0], "pad": a[1]}, "to": {"ref": b[0], "pad": b[1]},
                        "widths": widths}], f)
        rc, log = _route(src, out, conn, js)
        recs = json.load(open(js, encoding='utf-8')).get('connections') if os.path.isfile(js) else None
        check(f'{reason} on {net}: rc 0 and one refused record',
              rc == 0 and recs and recs[0]['status'] == 'refused' and recs[0]['reason'] == reason,
              (rc, recs, log[-600:] if rc else ''))
        check(f'{reason} on {net}: no new copper', os.path.isfile(out) and not _new(src, out))


def t_in_process(tmp):
    from route import batch_route
    src, out, js = (os.path.join(tmp, n) for n in ('p_in.kicad_pcb', 'p_out.kicad_pcb', 'p.json'))
    _board(src, wall=False)
    raw = [{"net": "PWR", "from": {"ref": "U1", "pad": "1"}, "to": {"ref": "U2", "pad": "1"}, "widths": WIDTHS}]
    batch_route(src, out, ['PWR'], layers=['F.Cu', 'B.Cu'], clearance=0.15, track_width=0.2,
                final_reconcile=False, connections=raw, json_out=js)
    doc = json.load(open(js, encoding='utf-8')) if os.path.isfile(js) else {}
    recs = doc.get('connections') or []
    check('in process with final_reconcile=False the key is written',
          len(recs) == 1 and recs[0]['status'] == 'routed', recs)


if __name__ == '__main__':
    with tempfile.TemporaryDirectory() as tmp:
        t_routed_then_joined(tmp)
        t_joined_narrow(tmp)
        t_refuses_nets(tmp)
        t_refused_lays_nothing(tmp)
        t_in_process(tmp)
    if fails:
        print(f'{len(fails)} FAILURE(S): {fails}')
        sys.exit(1)
    print('all checks passed')
