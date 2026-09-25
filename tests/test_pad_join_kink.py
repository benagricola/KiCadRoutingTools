#!/usr/bin/env python3
"""A route ends on a grid cell inside its pad, and route conversion used to
join that cell to the pad's centre with a short segment, whatever the angle:
on the MCU module case 25 of the router's 27 turns of 90 degrees or more were
such joins, 0.01-0.1 mm long, some doubling back (170-180 degrees). A track
end inside the pad's copper already connects (KiCad counts any end inside the
pad), so a join that would turn 90 degrees or more is left out. A join that
continues the track, or turns less, is kept; so is one from a cell outside
the pad, or to a point that is not a pad's centre (a stub's end).

Run: python3 -X utf8 tests/test_pad_join_kink.py
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'py_router'))

from kicad_parser import parse_kicad_pcb  # noqa: E402
from single_ended_routing import _pad_join_is_kink  # noqa: E402

_fails = []


def check(name, cond, detail=''):
    print(('PASS ' if cond else 'FAIL ') + name + ('' if cond else ': ' + detail))
    if not cond:
        _fails.append(name)


text = ('(kicad_pcb\n\t(version 20241229)\n\t(generator "test")\n'
        '\t(layers\n\t\t(0 "F.Cu" signal)\n\t\t(2 "B.Cu" signal)\n\t\t(25 "Edge.Cuts" user)\n\t)\n'
        '\t(net 0 "")\n\t(net 1 "N")\n'
        '\t(footprint "t:p" (layer "F.Cu") (at 10.05 10)\n\t\t(property "Reference" "J1" (at 0 0))\n'
        '\t\t(pad "1" smd rect (at 0 0) (size 0.6 0.6) (layers "F.Cu") (net 1 "N"))\n\t)\n'
        '\t(footprint "t:p" (layer "F.Cu") (at 20.05 10)\n\t\t(property "Reference" "J2" (at 0 0))\n'
        '\t\t(pad "1" smd rect (at 0 0) (size 0.06 0.06) (layers "F.Cu") (net 1 "N"))\n\t)\n)\n')
fd, path = tempfile.mkstemp(suffix='.kicad_pcb')
os.close(fd)
with open(path, 'w') as fh:
    fh.write(text)
pcb = parse_kicad_pcb(path)
os.unlink(path)
nid = [k for k, n in pcb.nets.items() if n.name == 'N'][0]
centre = (10.05, 10.0, 'F.Cu')

check('a track arriving from above, ending inside the pad: the sideways join is a kink',
      _pad_join_is_kink(pcb, nid, centre, (10.0, 10.0), (10.0, 9.0), 'F.Cu'))
check('a track arriving from the left: the join continues it, kept',
      not _pad_join_is_kink(pcb, nid, centre, (10.0, 10.0), (9.0, 10.0), 'F.Cu'))
check('a join that doubles back is a kink',
      _pad_join_is_kink(pcb, nid, centre, (10.0, 10.0), (11.0, 10.0), 'F.Cu'))
check('an end outside the pad keeps its join',
      not _pad_join_is_kink(pcb, nid, (20.05, 10.0, 'F.Cu'), (20.0, 10.0), (20.0, 9.0), 'F.Cu'))
check('a point that is no pad centre (a stub end) keeps its join',
      not _pad_join_is_kink(pcb, nid, (10.02, 10.0, 'F.Cu'), (10.0, 10.0), (10.0, 9.0), 'F.Cu'))
check('another layer keeps its join',
      not _pad_join_is_kink(pcb, nid, (10.05, 10.0, 'B.Cu'), (10.0, 10.0), (10.0, 9.0), 'B.Cu'))

sys.exit(1 if _fails else 0)
