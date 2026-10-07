#!/usr/bin/env python3
"""The uuids of the items the router writes are the same in every run on the
same board (FORK DIVERGENCE, see docs/fork-divergences.md).

Upstream minted a fresh uuid4 for every segment, via, zone and drawing it
wrote. KiCad orders and tie-breaks on KIIDs (the order a loaded board hands its
tracks out in, which item a DRC marker names, zone fill ties), so the same
routed copper graded differently from run to run: placemat's via merge on
watchy kept or merged a +3V3 via pair depending only on the router's uuids
(clean closure 61.2% or 84.3% on identical copper).

Cases:
  * two processes, at PYTHONHASHSEED 1 and 2, that parse the same board and
    write the same items mint the same uuids;
  * within one process, two items of the same text get different uuids;
  * the seed ignores the board's own uuids and block order, and changes with
    its content;
  * a board with no placeholders left: every writer stamps its uuid.

    python3 tests/test_item_uuid_determinism.py
"""
import os
import re
import subprocess
import sys
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'py_router'))

RUN_ALL_FAST_OK = True   # two short interpreter starts, no board routing

BOARD = os.path.join(ROOT, 'kicad_files', 'cap_chain.kicad_pcb')

_CHILD = r'''
import sys
sys.path.insert(0, sys.argv[1])
from kicad_parser import parse_kicad_pcb
import kicad_writer as w
parse_kicad_pcb(sys.argv[2])
items = [
    w.generate_segment_sexpr((1, 2), (3, 4), 0.2, "F.Cu", 1),
    w.generate_segment_sexpr((1, 2), (3, 4), 0.2, "F.Cu", 1),
    w.generate_via_sexpr(5, 6, 0.6, 0.3, ["F.Cu", "B.Cu"], 1),
    w.generate_gr_line_sexpr((0, 0), (1, 1), 0.1, "User.7"),
    w.generate_gr_text_sexpr("x", 1, 1, "User.7"),
    w.generate_zone_sexpr(1, "GND", "B.Cu", [(0, 0), (1, 0), (1, 1)]),
    w.generate_keepout_zone_sexpr(["F.Cu"], [(0, 0), (1, 0), (1, 1)], "k"),
]
import re
for t in items:
    m = re.findall(r'\(uuid "([^"]+)"\)', t)
    assert len(m) == 1, t
    print(m[0])
'''

failures = []


def check(cond, msg):
    print(('  PASS: ' if cond else '  FAIL: ') + msg)
    if not cond:
        failures.append(msg)


def child(seed, board=BOARD):
    env = dict(os.environ, PYTHONHASHSEED=seed)
    out = subprocess.run([sys.executable, '-c', _CHILD, os.path.join(ROOT, 'py_router'), board],
                         capture_output=True, text=True, env=env, timeout=120)
    if out.returncode:
        print(out.stderr[-2000:])
    return out.returncode, out.stdout.split()


def main():
    rc1, a = child('1')
    rc2, b = child('2')
    check(rc1 == 0 and rc2 == 0, 'both processes ran')
    check(len(a) == 7 and a == b, 'two processes mint the same uuids for the same items on the same board')
    check(all(str(uuid.UUID(u)) == u for u in a), 'every uuid is a well-formed UUID')
    check(len(set(a)) == len(a), 'two items of the same text get different uuids')

    import item_uuid
    with open(BOARD, encoding='utf-8') as f:
        content = f.read()
    item_uuid.seed_from_board(content)
    s0 = item_uuid.current_seed()
    # The board's own uuids replaced, and two top-level blocks swapped: the same seed.
    reuuided = re.sub(r'\(uuid "[^"]+"\)', lambda m: '(uuid "%s")' % uuid.uuid4(), content)
    item_uuid.seed_from_board(reuuided)
    check(item_uuid.current_seed() == s0, "the seed ignores the board's own uuids")
    blocks = content.split('\n\t(footprint')
    if len(blocks) > 3:
        swapped = '\n\t(footprint'.join([blocks[0], blocks[2], blocks[1]] + blocks[3:])
        item_uuid.seed_from_board(swapped)
        check(item_uuid.current_seed() == s0, "the seed ignores the order of the board's blocks")
    item_uuid.seed_from_board(content.replace('(width ', '(width 0', 1))
    check(item_uuid.current_seed() != s0, "the seed changes with the board's content")

    print()
    if failures:
        print('FAILED: %d' % len(failures))
        return 1
    print('ALL PASSED')
    return 0


if __name__ == '__main__':
    sys.exit(main())
