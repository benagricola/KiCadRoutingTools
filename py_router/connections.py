"""--connections: route only given pad pairs of a net, at a width per layer (placemat fork, docs/connections.md).

FORK DIVERGENCE (docs/fork-divergences.md): upstream has no per-connection routing.

KRT closes whole nets (connectivity.py find_connected_groups); every pass works per net id. For a call with
--connections each named net is restricted to the pads of its tasks and the copper joined to them: the net's other pads
and copper move, for this call only, to a private net that is an obstacle (D4: a same-net sibling pad of an end's
footprint is one too). The writer copies the input text and appends only new copper by name (output_writer.py:26,
:387-452), so the private ids never reach the file.

A task whose ends are already joined by copper narrower than asked is `joined_narrow` and is NOT routed (the D3
fallback): KRT has no single place that makes own-net copper passable, see docs/connections.md. Its record carries the
joining path so the caller can judge and report it.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional

STATUSES = ('routed', 'failed', 'joined_before', 'joined_narrow', 'deferred', 'refused')
REASONS = ('unknown_ref', 'unknown_pad', 'pad_not_on_net', 'layer_not_routed', 'layer_width_missing',
           'width_under_board_minimum')
PRIVATE_PREFIX = '__connections_private_'
_UNDER = 1e-3            # KRT's own width tolerance (routing_common.py power_width_report)


class ConnectionsError(ValueError):
    """A connections file that cannot be read at all: `code` and `facts`."""

    def __init__(self, code: str, **facts):
        self.code, self.facts = code, facts
        super().__init__(f'--connections: {code} {json.dumps(facts, sort_keys=True)}')


@dataclass
class Task:
    index: int
    net: str
    start: dict          # {"ref", "pad"}
    end: dict
    widths: Dict[str, float]
    net_id: Optional[int] = None
    start_pads: list = field(default_factory=list)
    end_pads: list = field(default_factory=list)
    status: Optional[str] = None
    reason: Optional[str] = None
    joined: bool = False
    length_mm: Optional[float] = None
    min_width_mm: Dict[str, float] = field(default_factory=dict)
    path: Optional[list] = None          # the joining path's segments, kept for joined_narrow only
    start_roots: set = field(default_factory=set)
    end_roots: set = field(default_factory=set)

    def record(self) -> dict:
        path = None
        if self.status == 'joined_narrow' and self.path is not None:
            path = [{"layer": s.layer, "start": [s.start_x, s.start_y], "end": [s.end_x, s.end_y], "width": s.width}
                    for s in self.path]
        return {"net": self.net, "from": dict(self.start), "to": dict(self.end), "status": self.status,
                "reason": self.reason, "joined": self.joined, "length_mm": self.length_mm,
                "min_width_mm": dict(self.min_width_mm), "path": path}


def read_file(path) -> list:
    """The parsed connections file: a JSON list of {net, from: {ref, pad}, to: {ref, pad}, widths: {layer: mm}}."""
    with open(path, encoding='utf-8') as f:
        doc = json.load(f)
    if not isinstance(doc, list):
        raise ConnectionsError('not_a_list', path=str(path))
    for i, t in enumerate(doc):
        ok = (isinstance(t, dict) and isinstance(t.get('net'), str) and isinstance(t.get('widths'), dict)
              and bool(t['widths'])
              and all(isinstance(k, str) and isinstance(v, (int, float)) and not isinstance(v, bool)
                      for k, v in t['widths'].items())
              and all(isinstance(t.get(k), dict) and isinstance(t[k].get('ref'), str)
                      and isinstance(t[k].get('pad'), str) for k in ('from', 'to')))
        if not ok:
            raise ConnectionsError('bad_task', index=i)
    return doc


def resolve(raw: list, pcb_data, routing_layers, min_track: float) -> List[Task]:
    """Each task with its net id and the pads of each end (every pad of that footprint with that number on the net:
    a number may repeat, kicad_parser.py:219-240), or refused with a reason."""
    by_name = {n.name: nid for nid, n in pcb_data.nets.items()}
    all_pads = [p for ps in pcb_data.pads_by_net.values() for p in ps]
    refs = {p.component_ref for p in all_pads} | set(getattr(pcb_data, 'footprints', None) or {})
    out = []
    for i, t in enumerate(raw):
        task = Task(i, t['net'], {"ref": t['from']['ref'], "pad": t['from']['pad']},
                    {"ref": t['to']['ref'], "pad": t['to']['pad']},
                    {k: float(v) for k, v in t['widths'].items()})
        out.append(task)
        nid = by_name.get(task.net)
        task.net_id = nid
        for end, into in ((task.start, task.start_pads), (task.end, task.end_pads)):
            if end['ref'] not in refs:
                task.status, task.reason = 'refused', 'unknown_ref'
                break
            numbered = [p for p in all_pads if p.component_ref == end['ref'] and p.pad_number == end['pad']]
            if not numbered:
                task.status, task.reason = 'refused', 'unknown_pad'
                break
            on_net = [p for p in numbered if nid is not None and p.net_id == nid]
            if not on_net:
                task.status, task.reason = 'refused', 'pad_not_on_net'
                break
            into.extend(on_net)
        if task.status:
            continue
        if any(layer not in routing_layers for layer in task.widths):
            task.status, task.reason = 'refused', 'layer_not_routed'
        elif any(layer not in task.widths for layer in routing_layers):
            task.status, task.reason = 'refused', 'layer_width_missing'
        elif any(w < (min_track or 0.0) - _UNDER for w in task.widths.values()):
            task.status, task.reason = 'refused', 'width_under_board_minimum'
    return out


class _Components:
    """One net's copper components from check_net_connectivity's graph (check_connected.py:1590-1601): the graph
    records every union as an edge, so a fresh union-find over the edges gives one root space for pads (by
    pad_index_repr), segments (point ids 2i and 2i+1), vias (via_index_repr) and zones (zone_index_repr)."""

    def __init__(self, pcb_data, net_id):
        from check_connected import check_net_connectivity
        self.segs = [s for s in pcb_data.segments if s.net_id == net_id]
        self.vias = [v for v in pcb_data.vias if v.net_id == net_id]
        self.zones = [z for z in pcb_data.zones if z.net_id == net_id]
        self.pads = list(pcb_data.pads_by_net.get(net_id, []))
        res = check_net_connectivity(net_id, self.segs, self.vias, self.pads, self.zones,
                                     tolerance=0.02, return_graph=True, pcb_data=pcb_data)
        g = res.get('graph') or {}
        parent: Dict[int, int] = {}

        def find(a):
            parent.setdefault(a, a)
            while parent[a] != a:
                parent[a] = parent[parent[a]]
                a = parent[a]
            return a

        for a, b in g.get('edges', ()):
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[ra] = rb
        self.root = {}
        for i, pid in (g.get('pad_index_repr') or {}).items():
            self.root[id(self.pads[i])] = find(pid)
        for i in range(len(self.segs)):
            self.root[id(self.segs[i])] = find(2 * i)
        for i, pid in (g.get('via_index_repr') or {}).items():
            self.root[id(self.vias[i])] = find(pid)
        for i, pid in (g.get('zone_index_repr') or {}).items():
            self.root[id(self.zones[i])] = find(pid)

    def roots(self, items: Iterable) -> set:
        return {self.root[id(x)] for x in items if id(x) in self.root}


def measure(pcb_data, task: Task, comps: Optional[_Components] = None) -> bool:
    """Set the task's `joined`, `length_mm`, `min_width_mm` and `path` from `pcb_data`'s copper; returns `joined`.
    The length and widths are those of the shortest track path between the two ends (net_queries
    pin_pair_path_length); a join only through a pour has no track path and reports a null length."""
    from net_queries import pin_pair_path_length
    if comps is None:
        comps = _Components(pcb_data, task.net_id)
    task.start_roots, task.end_roots = comps.roots(task.start_pads), comps.roots(task.end_pads)
    task.joined = bool(task.start_roots & task.end_roots)
    task.length_mm, task.min_width_mm, task.path = None, {}, None
    if not task.joined:
        return False
    best = None
    for pa in task.start_pads:
        for pb in task.end_pads:
            length, path = pin_pair_path_length(pcb_data, task.net_id, pa, pb, return_path=True)
            if length is not None and (best is None or length < best[0]):
                best = (length, path)
    if best is not None:
        narrow: Dict[str, float] = {}
        for s in best[1]:
            narrow[s.layer] = min(narrow.get(s.layer, s.width), s.width)
        task.length_mm, task.min_width_mm, task.path = round(best[0], 4), narrow, list(best[1])
    return True


def judge_joined(pcb_data, tasks: List[Task]) -> None:
    """A task whose two ends share a copper component before the call is `joined_before` when the joining path is at
    least its width on every layer, else `joined_narrow` (D3 fallback: reported with the path, not routed)."""
    comps: Dict[int, _Components] = {}
    for t in tasks:
        if t.status:
            continue
        if t.net_id not in comps:
            comps[t.net_id] = _Components(pcb_data, t.net_id)
        if not measure(pcb_data, t, comps[t.net_id]):
            continue
        under = any(w < t.widths.get(layer, 0.0) - _UNDER for layer, w in t.min_width_mm.items())
        t.status = 'joined_narrow' if under else 'joined_before'


def choose_groups(tasks: List[Task]) -> Dict[int, List[Task]]:
    """Per net, the first group in file order of open tasks joined through shared ends (the same pad, or pads one
    copper component already joins) whose tasks share one widths map; every other open task of that net is
    `deferred`. KRT holds one width map and one connected terminal set per net per call (routing_config.py:602-640)."""
    chosen: Dict[int, List[Task]] = {}
    open_tasks = [t for t in tasks if t.status is None]
    for nid in dict.fromkeys(t.net_id for t in open_tasks):
        mine = [t for t in open_tasks if t.net_id == nid]
        first = mine[0]
        group, ends = [first], _end_keys(first)
        grew = True
        while grew:
            grew = False
            for t in mine:
                if t in group or t.widths != first.widths:
                    continue
                if _end_keys(t) & ends:
                    group.append(t)
                    ends |= _end_keys(t)
                    grew = True
        for t in mine:
            if t not in group:
                t.status = 'deferred'
        chosen[nid] = group
    return chosen


def _end_keys(t: Task) -> set:
    return ({('pad', t.start['ref'], t.start['pad']), ('pad', t.end['ref'], t.end['pad'])}
            | {('copper', r) for r in t.start_roots | t.end_roots})


def split_nets(pcb_data, chosen: Dict[int, List[Task]], also: Iterable[int] = ()) -> Dict[int, int]:
    """Move, for each chosen net, every pad and copper item outside the components of its tasks' ends into a private
    obstacle net; a net in `also` (named by the file, nothing to route) moves whole, so the call leaves it alone.
    Returns {net id: private id}. The caller gives the private net its net's class clearance and protects it."""
    from kicad_parser import Net
    private: Dict[int, int] = {}
    next_id = max(list(pcb_data.nets) + list(pcb_data.pads_by_net) + [0]) + 1
    names = getattr(pcb_data, 'net_id_to_name', None)
    for nid in list(dict.fromkeys(list(chosen) + [n for n in also if n is not None])):
        group = chosen.get(nid) or []
        comps = _Components(pcb_data, nid)
        keep = comps.roots(p for t in group for p in t.start_pads + t.end_pads)
        ends = {id(p) for t in group for p in t.start_pads + t.end_pads}
        pid = next_id
        next_id += 1
        pname = '%s%d' % (PRIVATE_PREFIX, nid)
        pnet = Net(pid, pname)
        pcb_data.nets[pid] = pnet
        if isinstance(names, dict):
            names[pid] = pname
        stay, moved = [], []
        for p in pcb_data.pads_by_net.get(nid, []):
            (stay if id(p) in ends or comps.root.get(id(p)) in keep else moved).append(p)
        for p in moved:
            p.net_id, p.net_name = pid, pname
        moved_ids = {id(p) for p in moved}
        if nid in pcb_data.nets:
            pcb_data.nets[nid].pads = [p for p in pcb_data.nets[nid].pads if id(p) not in moved_ids]
        pnet.pads = list(moved)
        pcb_data.pads_by_net[nid], pcb_data.pads_by_net[pid] = stay, moved
        for item in list(comps.segs) + list(comps.vias) + list(comps.zones):
            if comps.root.get(id(item)) not in keep:
                item.net_id = pid
        private[nid] = pid
    pcb_data.connections_private = {**(getattr(pcb_data, 'connections_private', None) or {}), **private}
    pcb_data.connections_private_names = set(getattr(pcb_data, 'connections_private_names', None) or ()) | {
        pcb_data.nets[p].name for p in private.values()}
    return private


class _Unsplit:
    """While open, the private nets' pads and copper are back on their nets, so a board split by split_nets measures
    as the board the call ships."""

    def __init__(self, pcb_data):
        self.pcb = pcb_data
        self.moved = []
        self.pads_by_net = None

    def __enter__(self):
        back = {pid: nid for nid, pid in (getattr(self.pcb, 'connections_private', None) or {}).items()}
        if not back:
            return self
        self.pads_by_net = dict(self.pcb.pads_by_net)
        for pid, nid in back.items():
            self.pcb.pads_by_net[nid] = list(self.pcb.pads_by_net.get(nid, [])) + list(
                self.pcb.pads_by_net.get(pid, []))
        for item in ([p for pid in back for p in self.pcb.pads_by_net.get(pid, [])]
                     + list(self.pcb.segments) + list(self.pcb.vias) + list(self.pcb.zones)):
            if item.net_id in back:
                self.moved.append((item, item.net_id))
                item.net_id = back[item.net_id]
        return self

    def __exit__(self, *exc):
        for item, pid in self.moved:
            item.net_id = pid
        if self.pads_by_net is not None:
            self.pcb.pads_by_net.clear()
            self.pcb.pads_by_net.update(self.pads_by_net)
        return False


def finish(pcb_after, tasks: List[Task], chosen: Dict[int, List[Task]], routed: bool) -> None:
    """Measure every resolved task on the board the call ships and set the chosen tasks' status: `routed` or
    `failed` after a routing call, `joined_before` or `failed` when the call returned before routing. A board split
    by split_nets is measured with its private nets folded back."""
    with _Unsplit(pcb_after):
        _finish(pcb_after, tasks, chosen, routed)


def _finish(pcb_after, tasks, chosen, routed):
    by_name = {n.name: nid for nid, n in pcb_after.nets.items()}
    pads = {}
    for ps in pcb_after.pads_by_net.values():
        for p in ps:
            pads.setdefault((p.component_ref, p.pad_number), []).append(p)
    comps: Dict[int, _Components] = {}
    in_group = {id(t) for g in chosen.values() for t in g}
    for t in tasks:
        if t.status == 'refused':
            continue
        nid = by_name.get(t.net)
        t.net_id = nid
        t.start_pads = [p for p in pads.get((t.start['ref'], t.start['pad']), []) if p.net_id == nid]
        t.end_pads = [p for p in pads.get((t.end['ref'], t.end['pad']), []) if p.net_id == nid]
        if nid is None or not t.start_pads or not t.end_pads:
            t.joined = False
        else:
            if nid not in comps:
                comps[nid] = _Components(pcb_after, nid)
            measure(pcb_after, t, comps[nid])
        if t.status != 'joined_narrow':
            t.path = None
        if id(t) in in_group and t.status is None:
            t.status = ('routed' if routed else 'joined_before') if t.joined else 'failed'


def records(tasks: List[Task]) -> list:
    return [t.record() for t in tasks]
