#!/usr/bin/env python3
"""Failure evidence (placemat fork, docs/connections.md): the router's facts about a failed net, as plain data, and a
diagnosis only when KRT recorded exactly one verdict."""
import os
import sys
from types import SimpleNamespace as N

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, 'py_router'))
sys.path.insert(0, HERE)

from synth import make_pad, make_pcb  # noqa: E402
from kicad_parser import Net  # noqa: E402

fails = []


def check(name, cond, detail=''):
    print(('PASS: ' if cond else 'FAIL: ') + name + (f'  {detail}' if detail else ''))
    if not cond:
        fails.append(name)


def state(history=None, frontier=None):
    return N(net_history=history or {}, frontier_blocking=frontier or {})


BOXED = {"verdict": "boxed_in_static", "iterations": 12,
         "geometry": {"grid_step": 0.1, "clearance": 0.2, "track_width": 0.2, "via_diameter": 0.6}}
SEALED = {"verdict": "sealed_by_snpc", "pad": "U1.1", "aperture": [], "same_net_pad_clearance": 0.3,
          "required_surround_mm": 0.9}


def t_nothing_recorded_is_unknown():
    from failure_evidence import EMPTY, evidence_of
    e = evidence_of(state(), 1)
    check('a net with nothing recorded has no search, no blockers and an unknown diagnosis', e == EMPTY, e)
    check('the unknown record is the documented shape', EMPTY == {"scope": "net", "search": None, "blocked_by": [],
                                                                  "verdicts": [], "narrow": [], "diagnosis": "unknown"})


def t_one_verdict_is_the_diagnosis():
    from failure_evidence import evidence_of
    e = evidence_of(state({1: [{"event": "boxed_in_static", "details": BOXED}]}), 1)
    check('one verdict is the diagnosis', e["diagnosis"] == "boxed_in_static", e)
    check('the verdict keeps KRT fields', e["verdicts"] == [BOXED], e["verdicts"])


def t_two_verdicts_are_unknown():
    from failure_evidence import evidence_of
    e = evidence_of(state({1: [{"event": "boxed_in_static", "details": BOXED},
                               {"event": "sealed_by_snpc", "details": SEALED}]}), 1)
    check('two verdicts leave the diagnosis unknown', e["diagnosis"] == "unknown", e)
    check('both verdicts are listed', [v["verdict"] for v in e["verdicts"]] == ["boxed_in_static", "sealed_by_snpc"])


def t_blockers_keep_where_they_were_found():
    from failure_evidence import evidence_of
    static = {"kind": "pad", "net": "N3", "ref": "U1", "pad": "3", "layer": None, "at": [15.0, 6.0], "cells": 4,
              "seen_from": "forward"}
    search = {"forward": {"iterations": 900, "frontier_cells": 40},
              "backward": {"iterations": 950, "frontier_cells": 38}, "static": [static]}
    frontier = {1: {"stage": "single_ended", "blocked_by": [
        {"net": "SIG", "blocked_count": 30, "unique_cells": 30, "track_cells": 30, "via_cells": 0,
         "near_target_cells": 5, "near_source_cells": 0}]}}
    history = {1: [{"event": "search_failed", "details": search},
                   {"event": "frontier_blocking", "details": frontier[1]},
                   {"event": "preexisting_blockers", "details": {"hint": "text", "blockers": ["GND"]}}]}
    e = evidence_of(state(history, frontier), 1)
    check('blockers in found order', [b["found_by"] for b in e["blocked_by"]] == ["frontier", "static", "preexisting"],
          e["blocked_by"])
    check('a static pad is named by ref and pad', e["blocked_by"][1]["ref"] == "U1" and e["blocked_by"][1]["pad"] == "3")
    check('routed copper keeps its near-end counts', e["blocked_by"][0]["near_target_cells"] == 5
          and e["blocked_by"][0]["kind"] == "routed_copper")
    check('preexisting copper is named by net only', e["blocked_by"][2] == {
        "found_by": "preexisting", "kind": "copper", "net": "GND", "ref": None, "pad": None, "layer": None,
        "at": None, "cells": None, "seen_from": None, "near_source_cells": None, "near_target_cells": None})
    check('the search keeps both directions, without its static list',
          e["search"] == {"forward": search["forward"], "backward": search["backward"]}, e["search"])
    check('no verdict: unknown', e["diagnosis"] == "unknown")


def t_a_search_a_later_route_superseded_is_dropped():
    from failure_evidence import evidence_of
    search = {"forward": {"iterations": 9, "frontier_cells": 4},
              "backward": {"iterations": 7, "frontier_cells": 3}, "static": []}
    e = evidence_of(state({1: [{"event": "search_failed", "details": search},
                               {"event": "initial_route", "details": {}}]}), 1)
    check('a search the net later routed past is not its failure', e["search"] is None, e["search"])
    e = evidence_of(state({1: [{"event": "initial_route", "details": {}},
                               {"event": "search_failed", "details": search}]}), 1)
    check('a search after the last route is kept', e["search"] is not None, e["search"])


def t_old_failure_facts_do_not_survive_success_or_a_new_search():
    from failure_evidence import evidence_of
    search = {'forward': {'iterations': 5, 'frontier_cells': 1},
              'backward': {'iterations': 6, 'frontier_cells': 1}, 'static': []}
    frontier = {'blocked_by': [{'net': 'OLD', 'blocked_count': 9}]}
    old = [{'event': 'search_failed', 'details': search},
           {'event': 'boxed_in_static', 'details': BOXED},
           {'event': 'preexisting_blockers', 'details': {'blockers': ['OLD']}},
           {'event': 'frontier_blocking', 'details': frontier}]
    for boundary in ([{'event': 'rescue_succeeded', 'details': {}}], []):
        history = old + boundary + [{'event': 'search_failed', 'details': search}]
        ev = evidence_of(state({1: history}, {1: frontier}), 1)
        check('new failure clears old verdict and blockers',
              ev['diagnosis'] == 'unknown' and ev['verdicts'] == [] and ev['blocked_by'] == [], ev)


def t_a_rescue_that_leaves_the_net_split_keeps_the_failure():
    from failure_evidence import evidence_of
    search = {'forward': {'iterations': 98, 'frontier_cells': 12},
              'backward': {'iterations': 5000, 'frontier_cells': 300}, 'static': []}
    frontier = {'blocked_by': [{'net': 'WALL', 'blocked_count': 9}]}
    before = [{'event': 'search_failed', 'details': search},
              {'event': 'frontier_blocking', 'details': frontier},
              {'event': 'boxed_in_static', 'details': BOXED}]
    partial = {'fully_connected': False, 'edges_routed': 1, 'components_before': 3, 'components_after': 2}
    ev = evidence_of(state({1: before + [{'event': 'rescue_succeeded', 'details': partial}]}), 1)
    check('a rescue that leaves the net in pieces keeps the search', ev['search'] is not None, ev)
    check('...its blockers', [b['net'] for b in ev['blocked_by']] == ['WALL'], ev['blocked_by'])
    check('...and its verdict', ev['diagnosis'] == 'boxed_in_static', ev)
    full = dict(partial, fully_connected=True, components_after=1)
    ev = evidence_of(state({1: before + [{'event': 'rescue_succeeded', 'details': full}]}), 1)
    check('a rescue that joins the net ends the failure', ev['search'] is None and ev['verdicts'] == [], ev)


def t_tap_edge_search_is_recorded():
    """phase3_routing records each failed tap edge's search from its failed_edge_blocking entry, and the verdict
    when the search fits static_boxin_hint."""
    from phase3_routing import _record_tap_boxin, _record_tap_searches
    from failure_evidence import evidence_of
    from routing_config import GridRouteConfig
    pcb = make_pcb(nets={1: Net(1, 'VB')})
    entry = ([(1, 1, 0), (2, 1, 0), (3, 1, 0)], (0.1, 0.1),
             {'fwd': [(1, 1, 0)], 'bwd': [(2, 1, 0), (3, 1, 0)], 'extra': [(9, 9, 0)],
              'iterations': {'forward': 98, 'backward': 5000}, 'tgt_cells': [], 'src_cells': []})
    cfg = GridRouteConfig(layers=['F.Cu', 'B.Cu'])
    st = N(net_history={}, frontier_blocking={}, route_index=0)
    _record_tap_searches(st, pcb, cfg, 1, {(0, 1): entry}, [])
    check('no search is recorded when the call keeps no evidence', st.net_history.get(1) is None, st.net_history)
    cfg.failure_evidence = True
    _record_tap_searches(st, pcb, cfg, 1, {(0, 1): entry}, [])
    _record_tap_boxin(st, pcb, cfg, 1, {(0, 1): entry})
    ev = evidence_of(st, 1)
    check('the tap edge search is the net\'s, per direction',
          ev['search'] == {'forward': {'iterations': 98, 'frontier_cells': 1},
                           'backward': {'iterations': 5000, 'frontier_cells': 2}}, ev['search'])
    check('the verdict is recorded', ev['diagnosis'] == 'boxed_in_static'
          and ev['verdicts'][0]['iterations'] == 5098, ev['verdicts'])
    many = dict(entry[2], iterations={'forward': 20000, 'backward': 5000})
    st2 = N(net_history={}, frontier_blocking={}, route_index=0)
    _record_tap_boxin(st2, pcb, cfg, 1, {(0, 1): (entry[0], entry[1], many)})
    check('a search past the bound gets no verdict', st2.net_history.get(1) is None, st2.net_history)


def t_unrecorded_search_start_is_unknown():
    from failure_evidence import search_facts
    from routing_config import GridRouteConfig
    pcb = make_pcb(nets={1: Net(1, 'SIG')})
    cfg = GridRouteConfig(layers=['F.Cu', 'B.Cu'])
    facts = search_facts({'iterations_forward': 1, 'iterations_backward': 2}, pcb, cfg, 1, {1})
    check('a search records no start', set(facts['forward']) == {'iterations', 'frontier_cells'}, facts)
    missing = search_facts({}, pcb, cfg, 1, {1})
    check('unrecorded counts stay unknown',
          missing['forward']['iterations'] is None and missing['forward']['frontier_cells'] is None, missing)
    check('recorded iterations remain exact', facts['forward']['iterations'] == 1, facts)


def t_static_records_name_the_pads():
    from blocking_analysis import static_blocker_records
    from routing_config import GridRouteConfig
    pads = {2: [make_pad(2, 15.0, 6.0, ref='U1', num='3', net_name='N3', size_x=1.7, size_y=1.7,
                         layers=('F.Cu', 'B.Cu'), drill=1.0, pad_type='thru_hole')]}
    pcb = make_pcb(nets={1: Net(1, 'VB'), 2: Net(2, 'N3')}, pads_by_net=pads)
    cfg = GridRouteConfig(layers=["F.Cu", "B.Cu"], grid_step=0.1, clearance=0.2, track_width=0.2)
    cells = [(140, 60, 0), (141, 60, 0), (160, 60, 1)]              # the pad's left and right edges, both layers
    recs = static_blocker_records(cells, pcb, cfg, nets_to_route={1})
    check('the pad is one record', len(recs) == 1, recs)
    r = recs[0]
    check('named by ref, pad and net', (r["kind"], r["ref"], r["pad"], r["net"]) == ("pad", "U1", "3", "N3"), r)
    check('with its position and cells', r["at"] == [15.0, 6.0] and r["cells"] == 3, r)


def t_joined_narrow_names_its_narrow_segments():
    from connections import Task, attach_evidence
    from synth import make_seg
    t = Task(index=0, net="VB", start={"ref": "J1", "pad": "1"}, end={"ref": "J2", "pad": "1"},
             widths={"F.Cu": 1.0, "B.Cu": 1.0})
    t.status, t.path = 'joined_narrow', [make_seg(3, 6, 15, 6, width=0.2), make_seg(15, 6, 27, 6, width=1.0)]
    f = Task(index=1, net="VB", start={"ref": "J1", "pad": "1"}, end={"ref": "J3", "pad": "1"}, widths={"F.Cu": 1.0})
    f.status = 'failed'
    r = Task(index=2, net="VB", start={"ref": "J1", "pad": "1"}, end={"ref": "J4", "pad": "1"}, widths={"F.Cu": 1.0})
    r.status = 'routed'
    attach_evidence([t, f, r], {"VB": {"scope": "net", "search": None, "blocked_by": [], "verdicts": [BOXED],
                                       "narrow": [], "diagnosis": "boxed_in_static"}})
    check('joined_narrow: task scope, narrow_copper', t.evidence["scope"] == "task"
          and t.evidence["diagnosis"] == "narrow_copper", t.evidence)
    check('only the segment under its width is narrow', t.evidence["narrow"] == [
        {"layer": "F.Cu", "start": [3, 6], "end": [15, 6], "width": 0.2, "need": 1.0}], t.evidence["narrow"])
    check('a failed task carries its net evidence', f.evidence["diagnosis"] == "boxed_in_static")
    check('a routed task has none', r.evidence is None and r.record()["evidence"] is None)
    check('every record says what was asked', r.record()["widths"] == {"F.Cu": 1.0})


def t_static_tracks_per_net_and_layer():
    from blocking_analysis import analyze_static_blockers, static_blocker_records
    from routing_config import GridRouteConfig
    from synth import make_seg
    segs = [make_seg(15, 0, 15, 6, layer='F.Cu', net_id=2, width=0.5), make_seg(15, 6, 15, 12, layer='F.Cu', net_id=2,
                                                                              width=0.5),
            make_seg(15, 0, 15, 12, layer='B.Cu', net_id=2, width=0.5)]
    pcb = make_pcb(nets={1: Net(1, 'VB'), 2: Net(2, 'GND')}, segments=segs)
    cfg = GridRouteConfig(layers=["F.Cu", "B.Cu"], grid_step=0.1, clearance=0.2, track_width=0.2)
    cells = [(150, 30, 0), (150, 90, 0), (150, 60, 1), (100, 60, 0)]
    recs = sorted(static_blocker_records(cells, pcb, cfg, nets_to_route={1}), key=lambda r: r["layer"])
    check('one track record per layer', [(r["kind"], r["net"], r["layer"], r["cells"]) for r in recs]
          == [("track", "GND", "B.Cu", 1), ("track", "GND", "F.Cu", 2)], recs)
    check('at the first hit segment', recs[1]["at"] == [15.0, 3.0], recs[1])
    check('the printed form is unchanged', analyze_static_blockers(cells, pcb, cfg, {1})["tracks"] == ["GND"])


def t_static_evidence_rejects_diagonal_bbox_and_preserves_legacy_pad_layers():
    from blocking_analysis import analyze_static_blockers, static_blocker_records
    from routing_config import GridRouteConfig
    from synth import make_seg
    pad = make_pad(2, 5, 5, ref='U1', num='1', layers=['*.Cu'])
    pcb = make_pcb(nets={1: Net(1, 'SIG'), 2: Net(2, 'OTHER')},
                   pads_by_net={2: [pad]},
                   segments=[make_seg(0, 0, 10, 10, net_id=2)])
    cfg = GridRouteConfig(layers=['F.Cu', 'B.Cu'], grid_step=0.1,
                          clearance=0.2, track_width=0.2)
    cells = [(50, 50, 0), (10, 90, 0)]
    recs = static_blocker_records(cells, pcb, cfg, {1}, net_id=1)
    check('evidence includes through-hole pad', any(r['kind'] == 'pad' for r in recs), recs)
    tracks = [r for r in recs if r['kind'] == 'track']
    check('diagonal empty bbox corner is not copper', len(tracks) == 1 and tracks[0]['cells'] == 1, recs)
    check('legacy print keeps unexpanded pad layers',
          analyze_static_blockers(cells, pcb, cfg, {1})['pads'] == [])


def t_private_nets_are_named_by_their_net():
    from connections import Task, attach_evidence
    pad = make_pad(1, 3.0, 6.0, ref='J1', num='1', net_name='VB', size_x=1.7, size_y=1.7)
    f = Task(index=0, net="VB", start={"ref": "J1", "pad": "1"}, end={"ref": "J2", "pad": "1"}, widths={"F.Cu": 1.0})
    f.status, f.start_pads = 'failed', [pad]
    ev = {"scope": "net", "search": {"forward": {"iterations": 5, "frontier_cells": 2},
                                     "backward": {"iterations": 4, "frontier_cells": 2}},
          "blocked_by": [{"found_by": "static", "kind": "pad", "net": "__connections_private_1", "ref": "J3",
                          "pad": "1", "layer": None, "at": [9, 6], "cells": 2, "seen_from": "forward",
                          "near_source_cells": None, "near_target_cells": None}],
          "verdicts": [], "narrow": [], "diagnosis": "unknown"}
    attach_evidence([f], {"VB": ev}, names={"__connections_private_1": "VB"})
    check('copper of a private obstacle net is named by its net', f.evidence["blocked_by"][0]["net"] == "VB",
          f.evidence["blocked_by"])
    check('the search is carried as recorded', f.evidence["search"] == ev["search"], f.evidence["search"])
    check('the run\'s record is left as it was', ev["blocked_by"][0]["net"] == "__connections_private_1")


def t_merged_summaries_keep_newest_evidence_of_failing_nets():
    from route_summary import merge_summaries
    a = {"failed_single": ["A", "B"], "net_evidence": {"A": {"diagnosis": "unknown"}, "B": {"diagnosis": "x"}}}
    b = {"failed_single": ["A"], "net_evidence": {"A": {"diagnosis": "boxed_in_static"}}}
    m = merge_summaries([a, b])
    check('the newest record of each net still failing', m.get("net_evidence") == {"A": {"diagnosis":
                                                                                           "boxed_in_static"}}, m)
    c = {"failed_single": ["A", "B"]}
    m = merge_summaries([a, c])
    check('a pass without the key keeps the earlier records', m.get("net_evidence") == a["net_evidence"], m)
    m = merge_summaries([a, {"failed_single": []}])
    check('none failing: no key', "net_evidence" not in m, m)


if __name__ == '__main__':
    t_nothing_recorded_is_unknown()
    t_one_verdict_is_the_diagnosis()
    t_two_verdicts_are_unknown()
    t_blockers_keep_where_they_were_found()
    t_a_search_a_later_route_superseded_is_dropped()
    t_old_failure_facts_do_not_survive_success_or_a_new_search()
    t_a_rescue_that_leaves_the_net_split_keeps_the_failure()
    t_tap_edge_search_is_recorded()
    t_unrecorded_search_start_is_unknown()
    t_static_records_name_the_pads()
    t_static_tracks_per_net_and_layer()
    t_static_evidence_rejects_diagonal_bbox_and_preserves_legacy_pad_layers()
    t_private_nets_are_named_by_their_net()
    t_merged_summaries_keep_newest_evidence_of_failing_nets()
    t_joined_narrow_names_its_narrow_segments()
    if fails:
        print(f'{len(fails)} FAILURE(S): {fails}')
        sys.exit(1)
    print('all checks passed')
