#!/usr/bin/env python3
"""A pair report gives each member's uncoupled track length, the straight-line length still open, and the coupled
minimum (docs/fork-divergences.md, "Uncoupled length per pair member")."""
import os
import sys
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'py_router'))

from kicad_parser import Segment, Pad
from diff_pair_custody import member_uncoupled_mm, member_open_mm, build_pair_reports

P, N = 1, 2
SPACING = 0.2       # 0.1 track + 0.1 gap


def seg(x1, y1, x2, y2, net, layer='F.Cu'):
    return Segment(x1, y1, x2, y2, 0.1, layer, net)


def test_tracks_run_beside_each_other_are_coupled():
    segs = [seg(0, 0, 10, 0, P), seg(0, 0.2, 10, 0.2, N)]
    assert member_uncoupled_mm(segs, P, N, SPACING) < 1e-6


def test_a_leg_away_from_the_partner_is_uncoupled_by_its_length():
    segs = [seg(0, 0, 10, 0, P), seg(10, 0, 10, 4, P), seg(0, 0.2, 10, 0.2, N)]
    assert abs(member_uncoupled_mm(segs, P, N, SPACING) - 3.5) < 0.06


def test_a_partner_on_another_layer_does_not_couple():
    segs = [seg(0, 0, 10, 0, P), seg(0, 0.2, 10, 0.2, N, 'B.Cu')]
    assert abs(member_uncoupled_mm(segs, P, N, SPACING) - 10.0) < 1e-6


def _pad(x, y, net):
    return Pad(component_ref='J1', pad_number='1', global_x=x, global_y=y, local_x=0, local_y=0, size_x=0.3,
               size_y=0.3, shape='rect', layers=['F.Cu'], net_id=net, net_name='n%d' % net)


def test_an_open_member_is_measured_pad_to_nearest_pad():
    board = SimpleNamespace(segments=[], vias=[], zones=[], pads_by_net={P: [_pad(0, 0, P), _pad(3, 4, P)]})
    assert abs(member_open_mm(board, P) - 5.0) < 1e-6


def test_the_report_carries_the_lengths_and_the_coupled_minimum():
    pads = {P: [_pad(0, 0, P), _pad(10, 4, P)], N: [_pad(0, 0.2, N), _pad(10, 0.2, N)]}
    board = SimpleNamespace(segments=[seg(0, 0, 10, 0, P), seg(10, 0, 10, 4, P), seg(0, 0.2, 10, 0.2, N)],
                            vias=[], zones=[], pads_by_net=pads)
    cfg = SimpleNamespace(track_width=0.1, diff_pair_gap=0.1, diff_pair_centerline_setback=None)
    state = SimpleNamespace(routed_results={}, diff_pair_single_ended_nets={}, pair_diagnostics={},
                            casualty_custody={}, config=cfg, pcb_data=board)
    pair = SimpleNamespace(p_net_id=P, n_net_id=N, p_net_name='D_P', n_net_name='D_N')
    rep, = build_pair_reports(state, [('D', pair)], {'D': {'p': True, 'n': True}})
    assert abs(rep['uncoupled_mm']['p'] - 3.5) < 0.06 and rep['uncoupled_mm']['n'] < 1e-6
    assert rep['open_mm'] == {'p': 0.0, 'n': 0.0}
    assert rep['min_coupled_mm'] == 3.0


def test_the_coupled_minimum_is_the_pairs_own_by_its_net_class_geometry():
    from routing_config import GridRouteConfig
    pads = {P: [_pad(0, 0, P), _pad(10, 0, P)], N: [_pad(0, 0.2, N), _pad(10, 0.2, N)]}
    board = SimpleNamespace(segments=[], vias=[], zones=[], pads_by_net=pads)
    cfg = GridRouteConfig(track_width=0.1, diff_pair_gap=0.1)
    state = SimpleNamespace(routed_results={}, diff_pair_single_ended_nets={}, pair_diagnostics={},
                            casualty_custody={}, config=cfg, pcb_data=board, pair_diff_geom={P: (0.3, 0.3)})
    pair = SimpleNamespace(p_net_id=P, n_net_id=N, p_net_name='D_P', n_net_name='D_N')
    rep, = build_pair_reports(state, [('D', pair)], {'D': {'p': True, 'n': True}})
    from diff_pair_multipoint import diff_pair_min_coupled_length
    from dataclasses import replace
    assert rep['min_coupled_mm'] == round(diff_pair_min_coupled_length(replace(cfg, track_width=0.3,
                                                                               diff_pair_gap=0.3)), 3)
    assert rep['min_coupled_mm'] != round(diff_pair_min_coupled_length(cfg), 3)
