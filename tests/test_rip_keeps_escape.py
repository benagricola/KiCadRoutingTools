#!/usr/bin/env python3
"""A net ripped as a blocker keeps its escape out of a fine-pitch row
(docs/rip-keeps-escape-design.md): leg_rip.keep_row_escape narrows the rip
set to everything but the net's copper within the escape depth of the row
pad's outer edge, splitting the segment that crosses it, unless the stuck
search's blocked cells lie on that escape.

Run: python3 -X utf8 tests/test_rip_keeps_escape.py
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'py_router'))

from kicad_parser import parse_kicad_pcb  # noqa: E402
from routing_config import GridRouteConfig  # noqa: E402
import leg_rip  # noqa: E402

_fails = []


def check(name, cond, detail=''):
    print(('PASS ' if cond else 'FAIL ') + name + ('' if cond else ': ' + detail))
    if not cond:
        _fails.append(name)


def board(route_middle=True):
    pads = ''.join('\t\t(pad "%d" smd rect (at %g 0) (size 0.2 0.665) (layers "F.Cu") (net %d "N%d"))\n'
                   % (k, (k - 3) * 0.4, k, k) for k in range(1, 6))
    segs = ''
    if route_middle:
        segs = ('\t(segment (start 50 50) (end 50 53) (width 0.2) (layer "F.Cu") (net 3))\n'
                '\t(segment (start 50 53) (end 55 53) (width 0.2) (layer "F.Cu") (net 3))\n')
    text = ('(kicad_pcb\n\t(version 20241229)\n\t(generator "test")\n'
            '\t(layers\n\t\t(0 "F.Cu" signal)\n\t\t(2 "B.Cu" signal)\n\t\t(25 "Edge.Cuts" user)\n\t)\n'
            '\t(net 0 "")\n' + ''.join('\t(net %d "N%d")\n' % (k, k) for k in range(1, 6)) +
            '\t(footprint "t:row" (layer "F.Cu") (at 50 50)\n\t\t(property "Reference" "U1" (at 0 0))\n'
            + pads + '\t)\n'
            '\t(footprint "t:s" (layer "F.Cu") (at 55 53)\n\t\t(property "Reference" "S3" (at 0 0))\n'
            '\t\t(pad "1" smd rect (at 0 0) (size 0.6 0.6) (layers "F.Cu") (net 3 "N3"))\n\t)\n'
            + segs + ')\n')
    fd, path = tempfile.mkstemp(suffix='.kicad_pcb')
    os.close(fd)
    with open(path, 'w') as fh:
        fh.write(text)
    try:
        return parse_kicad_pcb(path)
    finally:
        os.unlink(path)


cfg = GridRouteConfig(track_width=0.2, clearance=0.2, grid_step=0.1, layers=['F.Cu', 'B.Cu'])


def setup():
    pcb = board()
    nid = [k for k, n in pcb.nets.items() if n.name == 'N3'][0]
    segs = [s for s in pcb.segments if s.net_id == nid]
    results = {nid: {'new_segments': list(segs), 'new_vias': []}}
    return pcb, nid, segs, results


# (a) blocked far from the pad: the escape is kept, the straight run split at
# 0.8 mm past the pad's outer edge (50.3325 + 0.8 = 51.1325)
pcb, nid, segs, results = setup()
out = leg_rip.keep_row_escape(pcb, nid, [(530, 530, 0)], cfg, None, results)
now = [s for s in pcb.segments if s.net_id == nid]
kept = [s for s in now if s not in (out or [])]
check('the escape is kept: one segment from the pad to 0.8 mm past its edge',
      len(kept) == 1 and abs(kept[0].start_y - 50) < 1e-9 and abs(max(kept[0].start_y, kept[0].end_y) - 51.1325) < 1e-6,
      repr([(s.start_x, s.start_y, s.end_x, s.end_y) for s in kept]))
check('the rest is ripped: the split outer piece and the run across',
      out is not None and len(out) == 2 and all(s in pcb.segments for s in out), repr(out))
check("the net's result lists the split pieces", set(map(id, results[nid]['new_segments'])) == set(map(id, now)))

# (b) blocked on the escape itself: the rip set is left as it was
pcb, nid, segs, results = setup()
out = leg_rip.keep_row_escape(pcb, nid, [(500, 506, 0)], cfg, None, results)
check('blocked cells on the escape: the rip set is unchanged', out is None, repr(out))
check('and nothing is split', len([s for s in pcb.segments if s.net_id == nid]) == 2)

# (c) a net with no pad on a fine-pitch row
pcb, nid, segs, results = setup()
sink_only = [k for k, n in pcb.nets.items() if n.name == 'N1'][0]
check('a net off any fine-pitch row: unchanged',
      leg_rip.keep_row_escape(pcb, sink_only, [(530, 530, 0)], cfg, None, results) is None)

# (d) the switch
os.environ['KICAD_RIP_KEEP_ESCAPE'] = '0'
import env_knobs  # noqa: E402
env_knobs.refresh()
pcb, nid, segs, results = setup()
check('KICAD_RIP_KEEP_ESCAPE=0: unchanged', leg_rip.keep_row_escape(pcb, nid, [(530, 530, 0)], cfg, None, results) is None)

sys.exit(1 if _fails else 0)
