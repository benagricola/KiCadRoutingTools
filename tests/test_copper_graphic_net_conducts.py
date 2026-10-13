#!/usr/bin/env python3
"""A copper graphic with a net is copper of that net (fork divergence).

KiCad 10 counts a PCB_SHAPE with a net as a connected item: pads and vias
joined only by a net-tagged line, an unfilled polygon's stroke or a filled
polygon read connected. Upstream's connectivity credits no join through a
graphic (#513 item 6), and a --connections call then moved copper joined to a
task's end only through a graphic onto the private obstacle net.

Properties:
  1. conducts(): a track conducts; a graphic with a net conducts, stroke and
     fill band alike; a graphic with no net does not.
  2. check_net_connectivity joins a pad and a via through a net-tagged line,
     an unfilled polygon's stroke and a filled polygon.
  3. It does not join them through an unfilled rectangle whose stroke misses
     both (KiCad does not either: the interior of an unfilled shape is not
     copper).
  3b. A filled polygon with a slanted edge joins a pad and a via at opposite
     ends of it. Its interior bands meet at exact tangency, which the graph
     does not credit; the stroke ties them.
  4. split_nets keeps a via joined to a task end only through a graphic on
     the net, and keeps every graphic of the net on the net, also one that
     touches nothing; a via the graphic does not reach still moves.

Run:  python3 tests/test_copper_graphic_net_conducts.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, 'py_router'))
sys.path.insert(0, HERE)

from synth import make_pad, make_pcb, make_seg, make_via  # noqa: E402
from kicad_parser import Net, extract_segments  # noqa: E402
from check_connected import check_net_connectivity, conducts  # noqa: E402

NAME_TO_ID = {'PWR': 1}
fails = []


def check(name, cond, detail=''):
    print(('PASS: ' if cond else 'FAIL: ') + name + (f'  {detail}' if detail else ''))
    if not cond:
        fails.append(name)


def _graphic(kind, fill='yes', net='PWR', layer='F.Cu'):
    """One graphic's segments through the parser. Pad at (0,0), via at (5,0)."""
    net_tok = f'(net "{net}")' if net else ''
    if kind == 'line':
        text = (f'(gr_line (start 0 0) (end 5 0) (stroke (width 0.2) (type solid)) '
                f'(layer "{layer}") {net_tok} (uuid "g1"))')
    elif kind == 'poly':      # its stroke runs through the pad and the via
        text = (f'(gr_poly (pts (xy -1 0) (xy 6 0) (xy 6 0.6) (xy -1 0.6)) '
                f'(stroke (width 0.2) (type solid)) (fill {fill}) (layer "{layer}") {net_tok} (uuid "g2"))')
    elif kind == 'wide_poly':  # both inside it, its stroke far from either
        text = (f'(gr_poly (pts (xy -2 -2) (xy 7 -2) (xy 7 2) (xy -2 2)) '
                f'(stroke (width 0.2) (type solid)) (fill {fill}) (layer "{layer}") {net_tok} (uuid "g3"))')
    else:
        raise ValueError(kind)
    return extract_segments(text, NAME_TO_ID)


def _joined(segs):
    pads = [make_pad(1, 0, 0, ref='U1', num='1', net_name='PWR', size_x=1.0, size_y=1.0)]
    vias = [make_via(5, 0, net_id=1)]
    r = check_net_connectivity(1, [s for s in segs if s.net_id == 1], vias, pads, [],
                               return_graph=True)
    g = r.get('graph') or {}
    parent = {}

    def find(a):
        parent.setdefault(a, a)
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a
    for a, b in g.get('edges', ()):
        parent[find(a)] = find(b)
    return find(g['pad_index_repr'][0]) == find(g['via_index_repr'][0])


def t_conducts():
    check('1a: a track conducts', conducts(make_seg(0, 0, 1, 0, net_id=1)))
    line = _graphic('line')
    check('1b: a net-tagged line conducts', bool(line) and all(conducts(s) for s in line), line)
    stroke = _graphic('poly', fill='no')
    check('1c: an unfilled polygon\'s stroke conducts', bool(stroke) and all(conducts(s) for s in stroke))
    filled = [s for s in _graphic('wide_poly') if getattr(s, 'area_fill', False)]
    check('1d: a filled polygon\'s interior band conducts', bool(filled) and all(conducts(s) for s in filled))
    bare = _graphic('line', net=None)
    check('1e: a graphic with no net does not conduct',
          bool(bare) and bare[0].net_id == 0 and not any(conducts(s) for s in bare), bare)


def t_joins():
    check('2a: pad and via join through a net-tagged line', _joined(_graphic('line')))
    check('2b: pad and via join through an unfilled polygon\'s stroke', _joined(_graphic('poly', fill='no')))
    check('2c: pad and via join through a filled polygon', _joined(_graphic('wide_poly', fill='yes')))
    check('3: no join through an unfilled rectangle whose stroke misses both',
          not _joined(_graphic('wide_poly', fill='no')))
    tri = extract_segments('(gr_poly (pts (xy -1 -1) (xy 7 -1) (xy -1 4)) (stroke (width 0.2) (type solid)) '
                           '(fill yes) (layer "F.Cu") (net "PWR") (uuid "g4"))', NAME_TO_ID)
    pads = [make_pad(1, 0, 2.5, ref='U1', num='1', net_name='PWR', size_x=1.0, size_y=1.0)]
    r = check_net_connectivity(1, tri, [make_via(5, -0.5, net_id=1)], pads, [])
    check('3b: a slanted filled polygon joins a pad and a via at its two ends',
          r.get('connected') is True and sum(1 for s in tri if s.area_fill) > 1, r.get('connected'))


def t_split():
    """A --connections task J1.1 -> U1.1. Via V1 at (5,0) is joined to U1.1 only by a filled polygon; via V2 at
    (5,6) touches nothing of the net; a second polygon of the net at (20,20) touches nothing."""
    from connections import resolve, judge_joined, choose_groups, split_nets
    pads = {1: [make_pad(1, -10, 0, ref='J1', num='1', net_name='PWR'),
                make_pad(1, 0, 0, ref='U1', num='1', net_name='PWR', size_x=1.0, size_y=1.0)]}
    island = extract_segments('(gr_poly (pts (xy 20 20) (xy 22 20) (xy 22 22) (xy 20 22)) '
                              '(stroke (width 0.2) (type solid)) (fill yes) (layer "F.Cu") (net "PWR") '
                              '(uuid "g9"))', NAME_TO_ID)
    segs = _graphic('wide_poly', fill='yes') + island
    v1, v2 = make_via(5, 0, net_id=1), make_via(5, 6, net_id=1)
    pcb = make_pcb(nets={1: Net(1, 'PWR')}, pads_by_net=pads, vias=[v1, v2], segments=segs)
    tasks = resolve([{"net": "PWR", "from": {"ref": "J1", "pad": "1"}, "to": {"ref": "U1", "pad": "1"},
                      "widths": {"F.Cu": 0.5, "B.Cu": 0.5}}], pcb, ['F.Cu', 'B.Cu'], min_track=0.1)
    judge_joined(pcb, tasks)
    check('4a: the task is open', tasks[0].status is None, tasks[0])
    private = split_nets(pcb, choose_groups(tasks))
    pid = private[1]
    check('4b: a via joined to the end only through a graphic stays on the net', v1.net_id == 1, v1.net_id)
    check('4c: every graphic of the net stays on the net', all(s.net_id == 1 for s in segs),
          sorted({s.net_id for s in segs}))
    check('4d: a via the graphic does not reach moves to the private net', v2.net_id == pid, v2.net_id)


if __name__ == '__main__':
    t_conducts()
    t_joins()
    t_split()
    if fails:
        print(f'{len(fails)} FAILURE(S): {fails}')
        sys.exit(1)
    print('all checks passed')
