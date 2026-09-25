#!/usr/bin/env python3
"""Task 3 (docs/off-grid-exact-fit-plan.md): aligned routing in route.py.

An 80-pin QFN at 0.4 mm pitch, every pin netted to its own sink pad well
outside it, 0.2 mm track and clearance, F.Cu only: routed where its pin rows'
centre lines fall on the 0.1 mm grid, every pin escapes. The same board
moved by (0.05, 0.05) mm routes the same with alignment on; the output's
copper lands on the board's own coordinates and is DRC clean at no margin.
With --no-align-grid it fails pins.

Run: python3 -X utf8 tests/test_grid_align_route.py
"""
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'py_router'))

from kicad_parser import parse_kicad_pcb  # noqa: E402

PY = sys.executable
_fails = []


def check(name, cond, detail=''):
    print(('PASS ' if cond else 'FAIL ') + name + ('' if cond else ': ' + detail))
    if not cond:
        _fails.append(name)


def qfn_board(cx, cy):
    """The chip at (cx, cy): 20 rect pads a side at 0.4 mm pitch, 0.665 x 0.2,
    their centres 4.91 mm out; a 3.4 mm centre pad; a sink per pin 6 mm past
    the row, at 2.5 times the pin pitch."""
    pads, sinks, nets = [], [], []
    n = 0
    for side in range(4):
        for k in range(20):
            n += 1
            t = -3.8 + 0.4 * k
            if side == 0:
                px, py, sx, sy, qx, qy = -4.91, t, 0.665, 0.2, -11.2425, 2.5 * t
            elif side == 1:
                px, py, sx, sy, qx, qy = t, 4.91, 0.2, 0.665, 2.5 * t, 11.2425
            elif side == 2:
                px, py, sx, sy, qx, qy = 4.91, -t, 0.665, 0.2, 11.2425, -2.5 * t
            else:
                px, py, sx, sy, qx, qy = -t, -4.91, 0.2, 0.665, -2.5 * t, -11.2425
            nets.append('P%d' % n)
            pads.append('\t\t(pad "%d" smd rect (at %g %g) (size %g %g) (layers "F.Cu") (net %d "P%d"))\n'
                        % (n, px, py, sx, sy, n, n))
            sinks.append('\t(footprint "t:sink" (layer "F.Cu") (at %g %g)\n'
                         '\t\t(property "Reference" "S%d" (at 0 0))\n'
                         '\t\t(pad "1" smd rect (at 0 0) (size 0.6 0.6) (layers "F.Cu") (net %d "P%d"))\n\t)\n'
                         % (round(cx + qx, 6), round(cy + qy, 6), n, n, n))
    pads.append('\t\t(pad "81" smd rect (at 0 0) (size 3.4 3.4) (layers "F.Cu"))\n')
    e = 17.0
    text = ['(kicad_pcb\n\t(version 20241229)\n\t(generator "test")\n',
            '\t(layers\n\t\t(0 "F.Cu" signal)\n\t\t(2 "B.Cu" signal)\n\t\t(25 "Edge.Cuts" user)\n\t)\n',
            '\t(net 0 "")\n'] + ['\t(net %d "%s")\n' % (i + 1, nm) for i, nm in enumerate(nets)]
    text.append('\t(footprint "t:qfn" (layer "F.Cu") (at %g %g)\n\t\t(property "Reference" "U1" (at 0 0))\n'
                % (cx, cy) + ''.join(pads) + '\t)\n')
    text += sinks
    text.append('\t(gr_rect (start %g %g) (end %g %g) (stroke (width 0.1) (type solid)) (fill no) (layer "Edge.Cuts"))\n'
                % (cx - e, cy - e, cx + e, cy + e))
    return ''.join(text) + ')\n'


def route(board_text, tmp, name, extra):
    src = os.path.join(tmp, name + '.kicad_pcb')
    with open(src, 'w') as fh:
        fh.write(board_text)
    out = os.path.join(tmp, name + '_out.kicad_pcb')
    js = os.path.join(tmp, name + '.json')
    r = subprocess.run([PY, '-X', 'utf8', os.path.join(ROOT, 'py_router', 'route.py'), src, out,
                        '--layers', 'F.Cu', '--track-width', '0.2', '--clearance', '0.2',
                        '--escalation', 'off', '--json-out', js] + extra,
                       capture_output=True, text=True, cwd=ROOT)
    with open(os.path.join(tmp, name + '.log'), 'w') as fh:
        fh.write(r.stdout + r.stderr)
    j = json.load(open(js)) if os.path.isfile(js) else {}
    return src, out, j, r


def pads(path):
    pcb = parse_kicad_pcb(path)
    return {(ref, p.pad_number): (round(p.global_x, 6), round(p.global_y, 6))
            for ref, fp in pcb.footprints.items() for p in fp.pads}


def failed(j):
    return len(j.get('failed_single') or []) + len(j.get('failed_multipoint') or [])


with tempfile.TemporaryDirectory() as tmp:
    moved = qfn_board(50.05, 50.05)
    src, out, j, r = route(moved, tmp, 'aligned', [])
    check('the run reports the alignment', j.get('grid_alignment', {}).get('dx') == 0.05
          and j.get('grid_alignment', {}).get('dy') == 0.05, repr(j.get('grid_alignment')))
    check('aligned: every pin routes', r.returncode == 0 and j and failed(j) == 0,
          'rc %s failed %s' % (r.returncode, j and failed(j)))
    check("the output's pads are the board's own", pads(out) == pads(src))
    c = subprocess.run([PY, '-X', 'utf8', os.path.join(ROOT, 'py_router', 'check_connected.py'), out, '--quiet'],
                       capture_output=True, text=True, cwd=ROOT)
    check('the output is connected on the original coordinates', '\nOK\n' in c.stdout, c.stdout[-400:])
    d = subprocess.run([PY, '-X', 'utf8', os.path.join(ROOT, 'py_router', 'check_drc.py'), out,
                        '--clearance-margin', '0'], capture_output=True, text=True, cwd=ROOT)
    check('the output is DRC clean at no margin', d.returncode == 0, d.stdout[-400:])

    _, _, j2, r2 = route(moved, tmp, 'unaligned', ['--no-align-grid'])
    check('--no-align-grid: pins fail', j2 and failed(j2) > 0, 'failed %s' % (j2 and failed(j2)))
    check('--no-align-grid: no alignment reported', 'grid_alignment' not in j2)

sys.exit(1 if _fails else 0)
