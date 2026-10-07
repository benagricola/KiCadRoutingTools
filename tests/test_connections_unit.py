#!/usr/bin/env python3
"""--connections: load, refusals, the width-aware joined judgement, grouping, and the net split (placemat fork)."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, 'py_router'))
sys.path.insert(0, HERE)

from synth import make_pad, make_pcb, make_seg  # noqa: E402
from kicad_parser import Net  # noqa: E402

fails = []


def check(name, cond, detail=''):
    print(('PASS: ' if cond else 'FAIL: ') + name + (f'  {detail}' if detail else ''))
    if not cond:
        fails.append(name)


def board():
    """Net 1 "PWR": J1.1 at (0,0), U1.1 at (10,0), U1.2 at (10,1) (a sibling pad), C1.1 at (5,8). Net 2 "SIG": R1.1."""
    pads = {1: [make_pad(1, 0, 0, ref='J1', num='1', net_name='PWR'),
                make_pad(1, 10, 0, ref='U1', num='1', net_name='PWR'),
                make_pad(1, 10, 1, ref='U1', num='2', net_name='PWR'),
                make_pad(1, 5, 8, ref='C1', num='1', net_name='PWR')],
            2: [make_pad(2, 20, 0, ref='R1', num='1', net_name='SIG')]}
    return make_pcb(nets={1: Net(1, 'PWR'), 2: Net(2, 'SIG')}, pads_by_net=pads)


def task(frm, to, widths=None, net='PWR'):
    return {"net": net, "from": {"ref": frm[0], "pad": frm[1]}, "to": {"ref": to[0], "pad": to[1]},
            "widths": widths or {"F.Cu": 0.5, "B.Cu": 0.5}}


def t_refusals():
    from connections import resolve
    pcb = board()
    layers = ['F.Cu', 'B.Cu']
    got = resolve([task(('J9', '1'), ('U1', '1')), task(('J1', '7'), ('U1', '1')), task(('R1', '1'), ('U1', '1')),
                   task(('J1', '1'), ('U1', '1'), {"F.Cu": 0.5, "In1.Cu": 0.5}),
                   task(('J1', '1'), ('U1', '1'), {"F.Cu": 0.05, "B.Cu": 0.05})], pcb, layers, min_track=0.1)
    check('an unknown ref is refused', got[0].reason == 'unknown_ref', got[0])
    check('an unknown pad is refused', got[1].reason == 'unknown_pad', got[1])
    check('a pad on another net is refused', got[2].reason == 'pad_not_on_net', got[2])
    check('a width layer the call does not route is refused', got[3].reason == 'layer_not_routed', got[3])
    check('a width under the board minimum is refused', got[4].reason == 'width_under_board_minimum', got[4])
    miss = resolve([task(('J1', '1'), ('U1', '1'), {"F.Cu": 0.5})], pcb, layers, min_track=0.1)
    check('a routed layer without a width is refused', miss[0].reason == 'layer_width_missing', miss[0])


def t_joined():
    from connections import resolve, judge_joined
    pcb = board()
    pcb.segments.append(make_seg(0, 0, 10, 0, width=0.2, net_id=1))     # J1.1-U1.1 joined at 0.2 on F.Cu
    tasks = resolve([task(('J1', '1'), ('U1', '1')), task(('J1', '1'), ('U1', '1'), {"F.Cu": 0.2, "B.Cu": 0.2}),
                     task(('J1', '1'), ('C1', '1'))], pcb, ['F.Cu', 'B.Cu'], min_track=0.1)
    judge_joined(pcb, tasks)
    check('joined by narrower copper is joined_narrow', tasks[0].status == 'joined_narrow', tasks[0])
    check('joined at its width is joined_before', tasks[1].status == 'joined_before', tasks[1])
    check('an open task stays open', tasks[2].status is None, tasks[2])


def t_grouping():
    from connections import resolve, judge_joined, choose_groups
    pcb = board()
    tasks = resolve([task(('J1', '1'), ('U1', '1')), task(('C1', '1'), ('U1', '2')),
                     task(('U1', '1'), ('C1', '1'), {"F.Cu": 0.3, "B.Cu": 0.3})], pcb, ['F.Cu', 'B.Cu'], min_track=0.1)
    judge_joined(pcb, tasks)
    routed = choose_groups(tasks)
    check('the first group in file order is routed', tasks[0] in routed[1], routed)
    check('a second, disjoint group of the net is deferred', tasks[1].status == 'deferred', tasks[1])
    check('a task with another width map on the net is deferred', tasks[2].status == 'deferred', tasks[2])


def t_split():
    from connections import resolve, judge_joined, choose_groups, split_nets
    pcb = board()
    pcb.segments.append(make_seg(5, 8, 5, 5, width=0.2, net_id=1))       # a stub on C1.1, not a task end
    tasks = resolve([task(('J1', '1'), ('U1', '1'))], pcb, ['F.Cu', 'B.Cu'], min_track=0.1)
    judge_joined(pcb, tasks)
    private = split_nets(pcb, choose_groups(tasks))
    pid = private[1]
    on_net = {(p.component_ref, p.pad_number) for p in pcb.pads_by_net[1]}
    moved = {(p.component_ref, p.pad_number) for p in pcb.pads_by_net[pid]}
    check('the task ends stay on the net', on_net == {('J1', '1'), ('U1', '1')}, on_net)
    check('the sibling pad and the other pad move to the private net (D4)', moved == {('U1', '2'), ('C1', '1')}, moved)
    check('copper joined to no end moves with them', all(s.net_id == pid for s in pcb.segments), pcb.segments)
    check('the private net is not named like a board net', pcb.nets[pid].name.startswith('__connections_private'),
          pcb.nets[pid].name)


def t_narrow_record():
    """D3 fallback: a joined_narrow task is reported with its joining path and is not routed."""
    from connections import resolve, judge_joined, choose_groups, split_nets
    pcb = board()
    pcb.segments.append(make_seg(0, 0, 10, 0, width=0.2, net_id=1))
    tasks = resolve([task(('J1', '1'), ('U1', '1')), task(('J1', '1'), ('U1', '1'), {"F.Cu": 0.2, "B.Cu": 0.2})],
                    pcb, ['F.Cu', 'B.Cu'], min_track=0.1)
    judge_joined(pcb, tasks)
    rec, rec2 = tasks[0].record(), tasks[1].record()
    check('a joined_narrow record counts as joined', rec['status'] == 'joined_narrow' and rec['joined'] is True, rec)
    check('a joined_narrow record names its narrowest width per layer', rec['min_width_mm'] == {'F.Cu': 0.2}, rec)
    check('a joined_narrow record carries the joining path',
          rec['path'] == [{"layer": "F.Cu", "start": [0, 0], "end": [10, 0], "width": 0.2}], rec['path'])
    check('any other record has a null path', rec2['path'] is None, rec2)
    chosen = choose_groups(tasks)
    check('a joined_narrow task is not routed', chosen == {}, chosen)
    private = split_nets(pcb, chosen, also={1})
    check('a net with nothing to route moves whole to its private net',
          not pcb.pads_by_net[1] and all(s.net_id == private[1] for s in pcb.segments), pcb.pads_by_net[1])


def t_read_file():
    import json
    import tempfile
    from connections import read_file, ConnectionsError
    with tempfile.TemporaryDirectory() as d:
        good, bad = os.path.join(d, 'good.json'), os.path.join(d, 'bad.json')
        with open(good, 'w') as f:
            json.dump([task(('J1', '1'), ('U1', '1'))], f)
        with open(bad, 'w') as f:
            json.dump([{"net": "PWR", "from": "J1.1", "to": {"ref": "U1", "pad": "1"}, "widths": {"F.Cu": 0.5}}], f)
        check('a well-formed file loads', read_file(good)[0]['net'] == 'PWR')
        try:
            read_file(bad)
            got = None
        except ConnectionsError as e:
            got = (e.code, e.facts)
        check('a string end is refused with its task index', got == ('bad_task', {'index': 0}), got)


if __name__ == '__main__':
    t_refusals()
    t_joined()
    t_grouping()
    t_split()
    t_narrow_record()
    t_read_file()
    if fails:
        print(f'{len(fails)} FAILURE(S): {fails}')
        sys.exit(1)
    print('all checks passed')
