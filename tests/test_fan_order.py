#!/usr/bin/env python3
"""Task 1 (docs/row-fan-order-plan.md): the fan sequence.

`fan_order.find_fan_rows` locates fine-pitch pin rows; `fan_order.fan_order`
re-sequences a net order (route.py's `(name, id)` pairs) so each row's nets
fan outside-in, as a person fans a row of pins out
(docs/row-fan-order-design.md). Every board here is written as text and
parsed with the real parser -- no router involved.

Ported from the accepted prototype (scratchpad fan/fan_order.py, its default
"block" mode with the chip-to-chip carve-out always on).

Run: python3 -X utf8 tests/test_fan_order.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'py_router'))

import tempfile  # noqa: E402

from kicad_parser import parse_kicad_pcb  # noqa: E402
import fan_order as FO  # noqa: E402

MAX_PITCH = 0.8  # 2 x (track 0.2 + clearance 0.2), the plan's own example

_fails = []


def check(cond, msg):
    if not cond:
        _fails.append(msg)


def _pad(num, x, y, sx, sy, net_id, net_name):
    return ('\t\t(pad "%s" smd rect (at %s %s) (size %s %s) '
            '(layers "F.Cu") (net %d "%s"))\n'
            % (num, x, y, sx, sy, net_id, net_name))


def _footprint(ref, x, y, pads_text, rot=None):
    at = '%s %s' % (x, y) if rot is None else '%s %s %s' % (x, y, rot)
    return ('\t(footprint "test:fp" (layer "F.Cu") (at %s)\n'
            '\t\t(property "Reference" "%s" (at 0 0))\n'
            % (at, ref) + pads_text + '\t)\n')


def _sink(ref, x, y, net_id, net_name):
    """A single-pad footprint: the far end of one net, off the row."""
    return _footprint(ref, x, y,
                      '\t\t(pad "1" smd rect (at 0 0) (size 0.6 0.6) '
                      '(layers "F.Cu") (net %d "%s"))\n' % (net_id, net_name))


def _board(footprints, nets):
    head = ['(kicad_pcb\n\t(version 20241229)\n\t(generator "test")\n']
    head.append('\t(net 0 "")\n')
    for nid, name in nets:
        head.append('\t(net %d "%s")\n' % (nid, name))
    head.append('\t(gr_rect (start -50 -50) (end 50 50) (layer "Edge.Cuts") '
               '(uuid "edge"))\n')
    return ''.join(head) + ''.join(footprints) + ')\n'


def _write(text):
    fd, path = tempfile.mkstemp(suffix='.kicad_pcb')
    os.close(fd)
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write(text)
    return path


def _parse(text):
    path = _write(text)
    try:
        return parse_kicad_pcb(path)
    finally:
        os.unlink(path)


# ---------------------------------------------------------------------------
# (a) A 9-pad row: left group from the left end inward, then the right group
# from the right end inward, then the ahead group; the row's nets occupy the
# base order's slot of its first net; non-row nets keep their positions.
# ---------------------------------------------------------------------------

def t_a_nine_pad_row_fan_sequence():
    # Row: 9 pads at x = 0, 0.4, .. 3.2, y = 0 (tall pads: a horizontal row).
    pin_pads = ''
    nets = []
    for i in range(9):
        nid = 100 + i + 1
        name = 'P%d' % (i + 1)
        nets.append((nid, name))
        pin_pads += _pad(str(i + 1), '%.1f' % (i * 0.4), '0', '0.2', '0.6',
                         nid, name)
    footprints = [_footprint('U1', '0', '0', pin_pads)]

    # Far pads (sinks), one per row net:
    #   right group: P1, P2, P3 (x=0, 0.4, 0.8) -> target far to the right
    #   ahead group: P4, P5, P6 (x=1.2, 1.6, 2.0) -> target straight out (+y)
    #   left group:  P7, P8, P9 (x=2.4, 2.8, 3.2) -> target far to the left
    sinks = []
    sinks.append(_sink('SR1', '20', '0', 101, 'P1'))
    sinks.append(_sink('SR2', '20', '1', 102, 'P2'))
    sinks.append(_sink('SR3', '20', '2', 103, 'P3'))
    sinks.append(_sink('SA4', '1.2', '10', 104, 'P4'))
    sinks.append(_sink('SA5', '1.6', '10', 105, 'P5'))
    sinks.append(_sink('SA6', '2.0', '10', 106, 'P6'))
    sinks.append(_sink('SL7', '-20', '0', 107, 'P7'))
    sinks.append(_sink('SL8', '-20', '1', 108, 'P8'))
    sinks.append(_sink('SL9', '-20', '2', 109, 'P9'))
    footprints += sinks

    other_a = (900, 'OTHER_A')
    other_b = (901, 'OTHER_B')
    nets = [other_a] + nets + [other_b]
    footprints.append(_sink('OA1', '-40', '-40', *other_a))
    footprints.append(_sink('OA2', '-40', '-41', *other_a))
    footprints.append(_sink('OB1', '40', '-40', *other_b))
    footprints.append(_sink('OB2', '40', '-41', *other_b))

    pcb = _parse(_board(footprints, nets))

    base = [('OTHER_A', 900)] + [('P%d' % i, 100 + i) for i in range(1, 10)] \
        + [('OTHER_B', 901)]
    out = FO.fan_order(pcb, base, MAX_PITCH)
    names = [n for n, _ in out]

    check(names[0] == 'OTHER_A',
          'a non-row net changed position: %r' % names)
    check(names[-1] == 'OTHER_B',
          'a non-row net changed position: %r' % names)
    expect_row = ['P7', 'P8', 'P9', 'P3', 'P2', 'P1', 'P4', 'P5', 'P6']
    check(names[1:10] == expect_row,
          'fan sequence wrong: expected %r, got %r' % (expect_row, names[1:10]))


# ---------------------------------------------------------------------------
# (b) A net between two rows' footprints (chip to chip) keeps its base
# position.
# ---------------------------------------------------------------------------

def _row_footprint(ref, x0, nets, y=0.0):
    """A footprint with one row of len(nets) pads along x, pitch 0.4."""
    pads = ''
    for i, (nid, name) in enumerate(nets):
        pads += _pad(str(i + 1), '%.1f' % (x0 + i * 0.4), '%.1f' % y,
                    '0.2', '0.6', nid, name)
    return _footprint(ref, '0', '0', pads)


def t_b_chip_to_chip_keeps_base_position():
    # U1: row of 3 (A, B, X). U2: row of 3 (C, D, X) -- X is chip-to-chip.
    net_a, net_b, net_x, net_c, net_d = \
        (11, 'A'), (12, 'B'), (13, 'X'), (14, 'C'), (15, 'D')
    u1 = _row_footprint('U1', 0.0, [net_a, net_b, net_x], y=0.0)
    u2 = _row_footprint('U2', 0.0, [net_c, net_d, net_x], y=20.0)
    # X's far pads are on U1 and U2 themselves (chip-to-chip: no external
    # sink needed -- its pads ARE the two chips).
    footprints = [u1, u2]
    nets = [net_a, net_b, net_x, net_c, net_d]
    pcb = _parse(_board(footprints, nets))

    base = [('X', 13), ('A', 11), ('B', 12), ('C', 14), ('D', 15)]
    out = FO.fan_order(pcb, base, MAX_PITCH)
    check(out[0] == ('X', 13),
          'chip-to-chip net moved from its base-order slot: %r' % (out,))


# ---------------------------------------------------------------------------
# (c) A row at 1.27 mm pitch (above 2 x 0.4) is left alone.
# ---------------------------------------------------------------------------

def t_c_coarse_row_left_alone():
    nets = [(21, 'C1'), (22, 'C2'), (23, 'C3')]
    pads = ''
    for i, (nid, name) in enumerate(nets):
        pads += _pad(str(i + 1), '%.2f' % (i * 1.27), '0', '0.5', '0.9',
                    nid, name)
    footprints = [_footprint('U1', '0', '0', pads),
                 _sink('S1', '20', '0', *nets[0]),
                 _sink('S2', '20', '1', *nets[1]),
                 _sink('S3', '20', '2', *nets[2])]
    pcb = _parse(_board(footprints, nets))

    rows = FO.find_fan_rows(pcb, MAX_PITCH)
    check(not any(r.ref == 'U1' for r in rows),
          'a 1.27 mm pitch row (> 2x0.4) was still found: %r' % rows)

    base = [('C1', 21), ('C2', 22), ('C3', 23)]
    out = FO.fan_order(pcb, base, MAX_PITCH)
    check(out == base,
          'a coarse row changed the net order: %r' % (out,))


# ---------------------------------------------------------------------------
# (d) A net on two rows is sequenced by the finer row.
# ---------------------------------------------------------------------------

def t_d_net_on_two_rows_uses_finer_row():
    # U1 carries two rows: a fine one (pitch 0.3, y=0) and a coarser one
    # (pitch 0.6, y=10), sharing net SHARED between one pad on each.
    fine_a, fine_shared = (31, 'FA'), (32, 'SHARED')
    coarse_b, coarse_c = (33, 'CB'), (34, 'CC')
    fine_pads = (_pad('1', '0.0', '0', '0.15', '0.5', *fine_a)
                + _pad('2', '0.3', '0', '0.15', '0.5', *fine_shared)
                + _pad('3', '0.6', '0', '0.15', '0.5', 35, 'FX'))
    coarse_pads = (_pad('4', '0.0', '10', '0.3', '0.5', *coarse_b)
                  + _pad('5', '0.6', '10', '0.3', '0.5', *fine_shared)
                  + _pad('6', '1.2', '10', '0.3', '0.5', *coarse_c))
    u1 = _footprint('U1', '0', '0', fine_pads + coarse_pads)
    nets = [fine_a, fine_shared, (35, 'FX'), coarse_b, coarse_c]
    footprints = [u1,
                 _sink('SFA', '-20', '0', *fine_a),
                 _sink('SFX', '20', '0', 35, 'FX'),
                 _sink('SCB', '-20', '10', *coarse_b),
                 _sink('SCC', '20', '10', *coarse_c)]
    pcb = _parse(_board(footprints, nets))

    rows = FO.find_fan_rows(pcb, MAX_PITCH)
    fine_rows = [r for r in rows if r.pitch < 0.5]
    coarse_rows = [r for r in rows if r.pitch >= 0.5]
    check(len(fine_rows) == 1 and len(coarse_rows) == 1,
          'expected one fine and one coarse row on U1: %r' % rows)

    base = [('CB', 33), ('SHARED', 32), ('CC', 34),
           ('FA', 31), ('FX', 35)]
    out = FO.fan_order(pcb, base, MAX_PITCH)
    names = [n for n, _ in out]
    # A row's nets occupy ONE contiguous block. SHARED must land in the
    # FINE row's block (with FA/FX), not the coarse row's (with CB/CC).
    fine_idxs = sorted(names.index(n) for n in ('FA', 'FX', 'SHARED'))
    check(fine_idxs == list(range(fine_idxs[0], fine_idxs[0] + 3)),
          'SHARED was not grouped into the finer row block with FA/FX '
          '(sequenced by the coarser row instead): %r' % names)


# ---------------------------------------------------------------------------
# (e) Pads of a 2-pad part never form a row.
# ---------------------------------------------------------------------------

def t_e_two_pad_part_never_a_row():
    nets = [(41, 'R1A'), (42, 'R1B')]
    pads = (_pad('1', '0.0', '0', '0.2', '0.6', *nets[0])
           + _pad('2', '0.4', '0', '0.2', '0.6', *nets[1]))
    footprints = [_footprint('R1', '0', '0', pads),
                 _sink('S1', '20', '0', *nets[0]),
                 _sink('S2', '20', '1', *nets[1])]
    pcb = _parse(_board(footprints, nets))

    rows = FO.find_fan_rows(pcb, MAX_PITCH)
    check(not any(r.ref == 'R1' for r in rows),
          'a 2-pad part formed a row: %r' % rows)


def t_f_net_with_more_than_two_pads_keeps_its_place():
    # A 5-pad row; P1 is a rail (its row pad plus two far pads), first in the
    # base order. It keeps its place, and the row's block goes to the slot of
    # the first two-pad net (P3), not to the rail's.
    pin_pads = ''
    nets = []
    for i in range(5):
        nid = 200 + i + 1
        nets.append((nid, 'P%d' % (i + 1)))
        pin_pads += _pad(str(i + 1), '%.1f' % (i * 0.4), '0', '0.2', '0.6', nid, 'P%d' % (i + 1))
    fps = [_footprint('U1', '0', '0', pin_pads)]
    fps.append(_sink('R1', '-30', '30', 201, 'P1'))
    fps.append(_sink('R2', '30', '30', 201, 'P1'))
    for i in range(2, 6):
        fps.append(_sink('S%d' % i, '20', str(i), 200 + i, 'P%d' % i))
    other = (900, 'OTHER')
    fps.append(_sink('OA', '-40', '-40', *other))
    fps.append(_sink('OB', '-40', '-41', *other))
    pcb = _parse(_board(fps, nets + [other]))
    base = [('P1', 201), ('OTHER', 900), ('P3', 203), ('P2', 202), ('P4', 204), ('P5', 205)]
    names = [n for n, _ in FO.fan_order(pcb, base, MAX_PITCH)]
    check(names[:2] == ['P1', 'OTHER'],
          'the rail or the net after it moved: %r' % names)
    check(sorted(names[2:]) == ['P2', 'P3', 'P4', 'P5'],
          'the row block is not at the first two-pad net: %r' % names)


def main():
    tests = sorted(n for n in globals() if n.startswith('t_'))
    for name in tests:
        globals()[name]()
    for f in _fails:
        print('FAIL: %s' % f)
    print('test_fan_order: %s (%d tests, %d checks failed)'
         % ('FAIL' if _fails else 'PASS', len(tests), len(_fails)))
    return 1 if _fails else 0


if __name__ == '__main__':
    sys.exit(main())
