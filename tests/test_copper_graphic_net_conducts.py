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
  3b. A filled polygon with slanted edges is one piece. Its interior bands
     meet at exact tangency, which the graph does not credit, so the bands
     alone are as many pieces as there are bands; the stroke ties them.
  4. split_nets keeps a via joined to a task end only through a graphic on
     the net, and keeps every graphic of the net on the net, also one that
     touches nothing; a via the graphic does not reach still moves.
  5. The router does not route to a graphic: a multipoint net's terminals are
     its pads and track ends, not a graphic's stroke or band ends, and pads a
     graphic joins share a terminal group.
  6. A task's width through a graphic: a line, an arc or an unfilled outline
     at its stroke as drawn, so a thin stroke join reads joined_narrow; a
     filled shape (its bands and outline) carries no width, like a pour.

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


def _pieces(segs, which):
    """How many components of the graph over `segs` the segments in `which` fall into."""
    r = check_net_connectivity(1, segs, [], [], [], return_graph=True)
    parent = {}

    def find(a):
        parent.setdefault(a, a)
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a
    for a, b in r['graph'].get('edges', ()):
        parent[find(a)] = find(b)
    ids = {id(s) for s in which}
    return len({find(2 * i) for i, s in enumerate(segs) if id(s) in ids})


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
    # The board's polygon: slanted edges, 0.1 mm scanline bands and one merged 0.7 mm band.
    pts = ((2.04, 1.776), (1.831, 0.0), (1.299, 0.0), (0.4, 1.776), (0.4, 2.526), (2.04, 2.526))
    poly = extract_segments('(gr_poly (pts ' + ' '.join('(xy %g %g)' % p for p in pts) + ') (stroke (width 0.2) '
                            '(type solid)) (fill yes) (layer "F.Cu") (net "PWR") (uuid "g4"))', NAME_TO_ID)
    bands = [s for s in poly if s.area_fill]
    check('3b: the bands alone are separate pieces (they meet at exact tangency)',
          len(bands) > 2 and _pieces(bands, bands) == len(bands), (len(bands), _pieces(bands, bands)))
    check('3c: with the stroke the polygon is one piece', _pieces(poly, bands) == 1, _pieces(poly, bands))


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
    twins = list(getattr(pcb, 'connections_art_twins', None) or ())
    island_ids = {s.uuid for s in island}
    check('4e: a graphic joined to no end has an obstacle twin on the private net, one per segment',
          len(twins) == len(island) and all(s.net_id == pid and s.uuid in island_ids for s in twins)
          and all(s in pcb.segments for s in twins), (len(twins), len(island)))
    from connections import _Unsplit
    with _Unsplit(pcb):
        inside = [s for s in pcb.segments if getattr(s, 'graphic', False)]
    check('4f: the twins are not on the board the call ships', len(inside) == len(segs)
          and all(s in pcb.segments for s in twins), (len(inside), len(segs)))


def _three_pads():
    """PWR: U1.1 at (0,0) and U2.1 at (5,0) under one slanted filled polygon, J1.1 at (20,0) on its own."""
    pads = {1: [make_pad(1, 0, 0, ref='U1', num='1', net_name='PWR', size_x=1.0, size_y=1.0),
                make_pad(1, 5, 0, ref='U2', num='1', net_name='PWR', size_x=1.0, size_y=1.0),
                make_pad(1, 20, 0, ref='J1', num='1', net_name='PWR')]}
    segs = extract_segments('(gr_poly (pts (xy -1 -1) (xy 7 -1) (xy -1 4)) (stroke (width 0.2) (type solid)) '
                            '(fill yes) (layer "F.Cu") (net "PWR") (uuid "g5"))', NAME_TO_ID)
    return make_pcb(nets={1: Net(1, 'PWR')}, pads_by_net=pads, segments=segs)


def t_terminals():
    from connectivity import get_multipoint_net_pads, get_copper_connected_terminal_groups
    from routing_config import GridRouteConfig
    pcb = _three_pads()
    pcb.segments.append(make_seg(5, 0, 8, 0, width=0.3, net_id=1))     # a track stub off U2.1
    info = get_multipoint_net_pads(pcb, 1, GridRouteConfig(layers=['F.Cu', 'B.Cu']))
    refs = sorted(getattr(r[5], 'component_ref', '?') for r in info or ())
    where = sorted((round(r[3], 3), round(r[4], 3)) for r in info or ())
    check('5a: the terminals are pads and the track\'s free end, none on the polygon',
          set(where) <= {(0, 0), (5, 0), (8, 0), (20, 0)} and (20, 0) in where and (0, 0) in where, where)
    groups = get_copper_connected_terminal_groups(pcb, 1, info)
    at = {(round(r[3], 3), round(r[4], 3)): groups[i] for i, r in enumerate(info)}
    near = {g for xy, g in at.items() if xy != (20, 0)}
    check('5b: the pads the polygon joins share a group, the far pad does not',
          len(near) == 1 and at[(20, 0)] not in near, at)
    from connectivity import get_net_mst_segments, get_net_routing_endpoints
    bare = _three_pads()
    bare.segments = [s for s in pcb.segments if not getattr(s, 'graphic', False)]
    check('5c: MPS ordering\'s endpoints and MST read no graphic',
          get_net_routing_endpoints(pcb, 1) == get_net_routing_endpoints(bare, 1)
          and get_net_mst_segments(pcb, 1) == get_net_mst_segments(bare, 1),
          (get_net_routing_endpoints(pcb, 1), get_net_routing_endpoints(bare, 1)))


def t_width():
    from connections import resolve, judge_joined
    pcb = _three_pads()
    pcb.segments.append(make_seg(7, -1, 20, 0, width=0.3, net_id=1))     # from the polygon's corner to J1
    tasks = resolve([{"net": "PWR", "from": {"ref": "U1", "pad": "1"}, "to": {"ref": "J1", "pad": "1"},
                      "widths": {"F.Cu": 0.25, "B.Cu": 0.25}}], pcb, ['F.Cu', 'B.Cu'], min_track=0.1)
    judge_joined(pcb, tasks)
    t = tasks[0]
    check('6: joined through the polygon and a track, the width is the track\'s',
          t.joined and t.length_mm is not None and t.min_width_mm == {'F.Cu': 0.3} and t.status == 'joined_before',
          (t.status, t.length_mm, t.min_width_mm))


def t_width_cases():
    """U1.1 at (0,0) and J1.1 at (10,0) joined only by one graphic of PWR; the task asks 1.0 mm."""
    from connections import resolve, judge_joined
    cases = (
        ('6a: a 0.1 mm line reads joined_narrow at 0.1', '(gr_line (start 0 0) (end 10 0) (stroke (width 0.1) '
         '(type solid)) (layer "F.Cu") (net "PWR") (uuid "w1"))', 'joined_narrow', {'F.Cu': 0.1}),
        ('6b: a filled polygon 0.2 mm tall carries no width', '(gr_poly (pts (xy 0 -0.1) (xy 10 -0.1) (xy 10 0.1) '
         '(xy 0 0.1)) (stroke (width 0.2) (type solid)) (fill yes) (layer "F.Cu") (net "PWR") (uuid "w2"))',
         'joined_before', {}),
        ('6c: a 1.5 mm line reads joined_before at 1.5', '(gr_line (start 0 0) (end 10 0) (stroke (width 1.5) '
         '(type solid)) (layer "F.Cu") (net "PWR") (uuid "w3"))', 'joined_before', {'F.Cu': 1.5}),
    )
    for name, text, status, widths in cases:
        pads = {1: [make_pad(1, 0, 0, ref='U1', num='1', net_name='PWR'),
                    make_pad(1, 10, 0, ref='J1', num='1', net_name='PWR')]}
        pcb = make_pcb(nets={1: Net(1, 'PWR')}, pads_by_net=pads, segments=extract_segments(text, NAME_TO_ID))
        tasks = resolve([{"net": "PWR", "from": {"ref": "U1", "pad": "1"}, "to": {"ref": "J1", "pad": "1"},
                          "widths": {"F.Cu": 1.0, "B.Cu": 1.0}}], pcb, ['F.Cu', 'B.Cu'], min_track=0.1)
        judge_joined(pcb, tasks)
        got = {k: round(v, 4) for k, v in tasks[0].min_width_mm.items()}
        check(name, tasks[0].joined and tasks[0].status == status and got == widths, (tasks[0].status, got))


def t_route_leaves_off_task_art_alone():
    """--connections J1.1-J2.1 on VB. Between them a pad of VB (U2.1, not a task end) under filled VB polygons on
    both layers. The route goes round the polygons: J1 and J2 end up joined, U2.1 not joined to them."""
    import json
    import subprocess
    import tempfile
    from test_connections_evidence import _board, _tht
    from kicad_parser import parse_kicad_pcb
    from connections import _Components
    polys = ''.join('(gr_poly (pts (xy 12.5 3.5) (xy 17.5 3.5) (xy 17.5 8.5) (xy 12.5 8.5)) (stroke (width 0.2) '
                    '(type solid)) (fill yes) (layer "%s") (net 1) (uuid "a%s"))\n' % (l, l[0]) for l in ('F.Cu', 'B.Cu'))
    with tempfile.TemporaryDirectory() as tmp:
        src, out, conn, js = (os.path.join(tmp, 'art' + s) for s in ('_in.kicad_pcb', '_out.kicad_pcb', '_c.json',
                                                                       '_s.json'))
        _board(src, [_tht('U2', 15, 6, [('1', 0, 0, 1, 'VB')]), polys])
        with open(conn, 'w', encoding='utf-8') as f:
            json.dump([{"net": "VB", "from": {"ref": "J1", "pad": "1"}, "to": {"ref": "J2", "pad": "1"},
                        "widths": {"F.Cu": 1.0, "B.Cu": 1.0}}], f)
        r = subprocess.run([sys.executable, '-X', 'utf8', os.path.join(ROOT, 'py_router', 'route.py'), src, out,
                            '--connections', conn, '--layers', 'F.Cu', 'B.Cu', '--no-power-tap-neckdown',
                            '--json-out', js], capture_output=True, text=True, encoding='utf-8', errors='replace',
                           timeout=900, env=dict(os.environ, KICAD_NET_RESCUE='0'))
        if r.returncode != 0 or not os.path.isfile(js) or not os.path.isfile(out):
            check('7: route.py ran', False, ((r.stdout or '') + (r.stderr or ''))[-1500:])
            return
        rec = json.load(open(js, encoding='utf-8'))['connections'][0]
        pcb = parse_kicad_pcb(out)
        comps = _Components(pcb, 1)
        pad = {p.component_ref: p for p in pcb.pads_by_net[1]}
        root = {ref: comps.root.get(id(p)) for ref, p in pad.items()}
        check('7a: the task is routed', rec['status'] == 'routed', rec['status'])
        check('7b: the route did not join the task to U2.1 through the polygons',
              root['J1'] == root['J2'] and root['U2'] != root['J1'], root)


def t_graze_bridge():
    """A via whose barrel grazes pad U1.1 (#470 graze class). Bare, close_soft_joints bridges them; when a filled
    polygon of the net already covers both, it does not."""
    from pcb_modification import close_soft_joints
    from routing_config import GridRouteConfig
    poly = ('(gr_poly (pts (xy -0.3 -0.3) (xy 1.2 -0.3) (xy 1.2 0.3) (xy -0.3 0.3)) (stroke (width 0.1) '
            '(type solid)) (fill yes) (layer "F.Cu") (net "PWR") (uuid "z"))')
    got = {}
    for name, segs in (('bare', []), ('poly', extract_segments(poly, NAME_TO_ID))):
        pcb = make_pcb(nets={1: Net(1, 'PWR')}, segments=segs,
                       pads_by_net={1: [make_pad(1, 0, 0, ref='U1', num='1', net_name='PWR', size_x=1.0,
                                                 size_y=0.6)]},
                       vias=[make_via(0.9, 0, net_id=1, size=0.45, drill=0.2)])
        got[name] = close_soft_joints([], pcb, {1}, GridRouteConfig(track_width=0.2, clearance=0.1,
                                                                   layers=['F.Cu', 'B.Cu']))
    check('8: the graze is bridged bare and not where a polygon of the net joins via and pad',
          got == {'bare': 1, 'poly': 0}, got)


if __name__ == '__main__':
    t_conducts()
    t_joins()
    t_split()
    t_terminals()
    t_width()
    t_width_cases()
    t_route_leaves_off_task_art_alone()
    t_graze_bridge()
    if fails:
        print(f'{len(fails)} FAILURE(S): {fails}')
        sys.exit(1)
    print('all checks passed')
