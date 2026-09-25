#!/usr/bin/env python3
"""Task 2 (docs/off-grid-exact-fit-plan.md): translating a board's text.

`board_translate.translate_board_text(text, dx, dy)` moves every top-level
item of a board by (dx, dy) mm: footprints by their position (their pads and
shapes are local), footprint-owned zones (stored in board coordinates),
tracks, vias, zones and graphics. Checked on tracked boards with the real
parser.

Run: python3 -X utf8 tests/test_board_translate.py
"""
import os
import re
import sys
import tempfile
from decimal import Decimal

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'py_router'))

from kicad_parser import parse_kicad_pcb  # noqa: E402
from board_translate import translate_board_text  # noqa: E402

BOARDS = ['rp2350_fpga_eensy_prePlane', 'splitflap_driver', 'esp_prog',
          'lvds_converter_dualclk_gnd', 'qfn_underpad_coupling']
DX, DY = 0.0375, 0.0667
TOL = 2e-6
_fails = []


def check(name, cond, detail=''):
    print(('PASS ' if cond else 'FAIL ') + name + ('' if cond else ': ' + detail))
    if not cond:
        _fails.append(name)


def parse(text):
    fd, path = tempfile.mkstemp(suffix='.kicad_pcb')
    os.close(fd)
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write(text)
    try:
        return parse_kicad_pcb(path)
    finally:
        os.unlink(path)


def points(pcb, dx=0.0, dy=0.0):
    """Every parsed board-coordinate point, keyed, with (dx, dy) subtracted."""
    out = {}
    for ref, fp in pcb.footprints.items():
        for i, p in enumerate(fp.pads):
            out[('pad', ref, p.pad_number, i)] = (p.global_x - dx, p.global_y - dy)
    for i, s in enumerate(pcb.segments):
        out[('seg', i, 0)] = (s.start_x - dx, s.start_y - dy)
        out[('seg', i, 1)] = (s.end_x - dx, s.end_y - dy)
    for i, v in enumerate(pcb.vias):
        out[('via', i)] = (v.x - dx, v.y - dy)
    for i, z in enumerate(pcb.zones):
        for k, (x, y) in enumerate(z.polygon):
            out[('zone', i, k)] = (x - dx, y - dy)
    for k, (x, y) in enumerate(pcb.board_info.board_outline):
        out[('edge', k)] = (x - dx, y - dy)
    return out


def local(pcb):
    return {(ref, p.pad_number, i): (p.local_x, p.local_y)
            for ref, fp in pcb.footprints.items() for i, p in enumerate(fp.pads)}


def as_values(text):
    """`text` with every number read as its value."""
    return re.sub(r'(?<=[\s(])-?[0-9]+\.[0-9]+(?=[\s)])', lambda m: str(Decimal(m.group()).normalize()), text)


def same(a, b):
    if a.keys() != b.keys():
        return 'keys differ: %r' % sorted(set(a) ^ set(b))[:5]
    bad = [k for k in a if abs(a[k][0] - b[k][0]) > TOL or abs(a[k][1] - b[k][1]) > TOL]
    return 'moved wrongly: %r' % [(k, a[k], b[k]) for k in bad[:3]] if bad else ''


for name in BOARDS:
    text = open(os.path.join(ROOT, 'kicad_files', name + '.kicad_pcb'), encoding='utf-8').read()
    orig = parse(text)
    moved_text = translate_board_text(text, DX, DY)
    moved = parse(moved_text)
    back_text = translate_board_text(moved_text, -DX, -DY)
    n = len(points(orig))
    check('%s: every point moves by exactly (dx, dy) (%d points)' % (name, n),
          not same(points(orig), points(moved, DX, DY)), same(points(orig), points(moved, DX, DY)))
    check('%s: coordinates inside footprints are untouched' % name,
          local(orig) == local(moved))
    check('%s: translating back gives the original text, numbers read as values' % name,
          as_values(back_text) == as_values(text))

check('no offset leaves the text unchanged', translate_board_text(text, 0, 0) == text)
sys.exit(1 if _fails else 0)
