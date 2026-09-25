#!/usr/bin/env python3
"""Task 1 (docs/off-grid-exact-fit-plan.md): the aligning offset.

`grid_align.aligning_offset` picks the sub-grid translation of the whole
board that puts the most fine-pitch pin rows' lane lines (the pads' centre
lines across the row) on the routing grid. Boards here are written as text
and parsed with the real parser.

Run: python3 -X utf8 tests/test_grid_align.py
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'py_router'))

from kicad_parser import parse_kicad_pcb  # noqa: E402
from grid_align import aligning_offset  # noqa: E402

GRID = 0.1
MAX_PITCH = 0.8
_fails = []


def check(name, cond, detail=''):
    print(('PASS ' if cond else 'FAIL ') + name + ('' if cond else ': ' + detail))
    if not cond:
        _fails.append(name)


def qfn(ref, x, y, per_side, net0, rot=None):
    """A QFN at (x, y): `per_side` pads a side at 0.4 mm pitch, centred."""
    pads, n = [], net0
    half = (per_side - 1) * 0.2
    for k in range(per_side):
        t = -half + k * 0.4
        for (px, py, sx, sy) in ((-3, t, 0.8, 0.2), (3, t, 0.8, 0.2),
                                 (t, -3, 0.2, 0.8), (t, 3, 0.2, 0.8)):
            pads.append('\t\t(pad "%d" smd rect (at %.4f %.4f) (size %s %s) '
                        '(layers "F.Cu") (net %d "N%d"))\n' % (n, px, py, sx, sy, n, n))
            n += 1
    at = '%s %s' % (x, y) if rot is None else '%s %s %s' % (x, y, rot)
    return ('\t(footprint "t:qfn" (layer "F.Cu") (at %s)\n'
            '\t\t(property "Reference" "%s" (at 0 0))\n' % (at, ref)
            + ''.join(pads) + '\t)\n'), n


def board(*parts):
    text, nets, n = [], [], 1
    for p in parts:
        body, n2 = qfn(*p, net0=n) if len(p) == 4 else qfn(p[0], p[1], p[2], p[3], n, p[4])
        text.append(body)
        nets += list(range(n, n2))
        n = n2
    head = '(kicad_pcb\n\t(version 20241229)\n\t(generator "test")\n\t(net 0 "")\n'
    head += ''.join('\t(net %d "N%d")\n' % (i, i) for i in nets)
    head += '\t(gr_rect (start -50 -50) (end 50 50) (layer "Edge.Cuts"))\n'
    fd, path = tempfile.mkstemp(suffix='.kicad_pcb')
    os.close(fd)
    with open(path, 'w') as fh:
        fh.write(head + ''.join(text) + ')\n')
    try:
        return parse_kicad_pcb(path)
    finally:
        os.unlink(path)


def near(a, b):
    return abs(a[0] - b[0]) < 1e-9 and abs(a[1] - b[1]) < 1e-9


off = aligning_offset(board(('U1', 10.03, 10.05, 8)), GRID, MAX_PITCH)
check('an off-grid part is moved onto the grid', near(off, (0.07, 0.05)), repr(off))

off = aligning_offset(board(('U1', 10, 20, 8)), GRID, MAX_PITCH)
check('an aligned part gives no offset', near(off, (0, 0)), repr(off))

off = aligning_offset(board(('U1', 0, 0.05, 8), ('U2', 20.03, 20.02, 4)), GRID, MAX_PITCH)
check('two parts out of phase: the one with more row pins is aligned', near(off, (0, 0.05)), repr(off))

off = aligning_offset(board(('U1', 10.02, 10.07, 8, 90)), GRID, MAX_PITCH)
check('a turned part is aligned by its global lane lines', near(off, (0.08, 0.03)), repr(off))

off = aligning_offset(board(('U1', 10.02, 10.07, 8, 45)), GRID, MAX_PITCH)
check('rows at 45 degrees are not counted', near(off, (0, 0)), repr(off))

off = aligning_offset(board(('U1', 10.03, 10.05, 8)), GRID, 0.3)
check('no fine-pitch rows gives no offset', near(off, (0, 0)), repr(off))

off = aligning_offset(board(('U1', -10.03, -10.05, 8)), GRID, MAX_PITCH)
check('negative coordinates', near(off, (0.03, 0.05)), repr(off))

sys.exit(1 if _fails else 0)
