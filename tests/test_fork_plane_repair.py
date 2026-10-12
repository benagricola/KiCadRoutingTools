"""Fork divergence (docs/fork-divergences.md, "Plane repair for a caller that tracks"): the plane repair keeps a tap
via's hole off foreign copper at the board's copper-to-hole floor, can leave a footprint's own copper blocking every
net, takes per-net clearances by name, taps only the pads it is given, and can leave what is still split to its
caller.

    python3 tests/test_fork_plane_repair.py
"""
import json
import os
import pathlib
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, 'py_router'))

from kicad_parser import BoardInfo, Footprint, Net, Pad, PCBData, Segment  # noqa: E402
from routing_config import GridCoord, GridRouteConfig  # noqa: E402


def _pad(ref, number, net, x, y=0.0):
    return Pad(pad_number=number, net_id=net, net_name='N%d' % net, global_x=x, global_y=y, local_x=x, local_y=y,
               size_x=1.0, size_y=1.0, shape='rect', layers=['F.Cu'], drill=0, pad_type='smd', component_ref=ref)


def _board(segments=(), pads=()):
    info = BoardInfo(layers={0: 'F.Cu', 2: 'B.Cu', 4: 'In1.Cu'}, copper_layers=['F.Cu', 'In1.Cu', 'B.Cu'],
                     board_bounds=(-2.0, -2.0, 2.0, 2.0))
    by_net = {}
    for p in pads:
        by_net.setdefault(p.net_id, []).append(p)
    return PCBData(board_info=info, nets={1: Net(1, 'GND'), 2: Net(2, 'SIG')}, footprints={}, vias=[],
                   segments=list(segments), pads_by_net=by_net)


def test_via_reach_takes_the_hole_floor_when_it_is_the_wider():
    from plane_obstacle_builder import via_reach
    cfg = GridRouteConfig(via_size=0.6, via_drill=0.4, clearance=0.15)
    assert abs(via_reach(cfg, 0.15, 0.254) - 0.454) < 1e-9          # 0.2 + 0.254 beats 0.3 + 0.15
    assert abs(via_reach(cfg, 0.15, 0.0) - 0.45) < 1e-9


def test_a_tap_via_keeps_its_hole_off_a_track_on_another_layer_at_the_hole_floor():
    """watchy: a 0.6/0.4 via at 0.15 mm clearance stood 0.25 mm hole-to-track from an In1.Cu track; the board asks
    0.254. With the hole floor the via map blocks that spot."""
    from plane_obstacle_builder import build_via_obstacle_map
    track = Segment(start_x=-0.5, start_y=0.0, end_x=0.5, end_y=0.0, width=0.2, layer='In1.Cu', net_id=2)
    pcb = _board(segments=[track])
    coord = GridCoord(0.002)
    # a via centre 0.552 mm off the track's centreline: its ring 0.152 mm off the track (clear of 0.15), its hole
    # 0.252 mm off (under 0.254)
    gx, gy = coord.to_grid(0.0, 0.552)
    loose = GridRouteConfig(via_size=0.6, via_drill=0.4, clearance=0.15, grid_step=0.002, board_edge_clearance=0.0,
                            layers=['F.Cu', 'In1.Cu', 'B.Cu'])
    assert not build_via_obstacle_map(pcb, loose, exclude_net_id=1, verbose=False).is_via_blocked(gx, gy)
    held = GridRouteConfig(via_size=0.6, via_drill=0.4, clearance=0.15, grid_step=0.002, board_edge_clearance=0.0,
                           layers=['F.Cu', 'In1.Cu', 'B.Cu'], hole_clearance=0.254)
    assert build_via_obstacle_map(pcb, held, exclude_net_id=1, verbose=False).is_via_blocked(gx, gy)


def test_without_the_own_pad_lift_a_footprints_copper_lifts_for_no_net():
    import check_drc
    pad1 = _pad('U1', '1', 1, 0.0)
    art = Segment(start_x=0.5, start_y=0.0, end_x=3.0, end_y=0.0, width=0.3, layer='F.Cu', net_id=0, graphic=True,
                  owner_ref='U1')
    fp = Footprint(reference='U1', footprint_name='L:P', x=0.0, y=0.0, rotation=0.0, layer='F.Cu', pads=[pad1])
    pcb = _board(segments=[art], pads=[pad1])
    pcb.footprints = {'U1': fp}
    assert check_drc.graphic_own_pad_nets(pcb).get(id(art)) == frozenset({1})
    check_drc.OWN_PAD_LIFT = False
    try:
        assert check_drc.graphic_own_pad_nets(pcb) == {}
    finally:
        check_drc.OWN_PAD_LIFT = True


def test_named_pads_are_found_by_reference_and_by_footprint_uuid():
    from repair_planes import named_pads
    a, b, c = _pad('C1', '1', 1, 0.0), _pad('TP4', '1', 1, 2.0), _pad('TP4~2', '1', 1, 4.0)
    pcb = _board(pads=[a, b, c])
    pcb.footprints = {'TP4': Footprint(reference='TP4', footprint_name='L:P', x=2, y=0, rotation=0, layer='F.Cu',
                                       pads=[b]),
                      'TP4~2': Footprint(reference='TP4', footprint_name='L:P', x=4, y=0, rotation=0, layer='F.Cu',
                                         pads=[c])}
    pcb.footprints['TP4'].uuid, pcb.footprints['TP4~2'].uuid = 'u-first', 'u-second'
    assert named_pads(pcb, [{'ref': 'C1', 'pad': '1'}]) == {id(a)}
    assert named_pads(pcb, [{'ref': 'TP4', 'pad': '1', 'fp': 'u-second'}]) == {id(c)}
    assert named_pads(pcb, [{'ref': 'C9', 'pad': '1'}]) == set()


def test_named_clearances_are_floored_at_the_boards_minimum():
    from repair_planes import named_clearances
    with tempfile.TemporaryDirectory() as d:
        _named_clearances(pathlib.Path(d), named_clearances)


def _named_clearances(tmp_path, named_clearances):
    pcb_file = tmp_path / 'b.kicad_pcb'
    pcb_file.write_text('(kicad_pcb (version 20241229))\n')
    (tmp_path / 'b.kicad_pro').write_text(json.dumps({'board': {'design_settings': {'rules': {'min_clearance': 0.2}}},
                                                      'net_settings': {'classes': []}}))
    pcb = _board()
    got = named_clearances(pcb, {'GND': 0.3, 'SIG': 0.1, 'NONE': 0.5}, str(pcb_file), 0.15)
    assert got == {1: 0.3, 2: 0.2}


def test_the_new_flags_are_parsed_and_listed():
    py = sys.executable
    out = subprocess.run([py, os.path.join(ROOT, 'krt_capabilities.py')], capture_output=True, text=True, cwd=ROOT,
                         timeout=120, check=True).stdout
    flags = json.loads(out)['flags']
    assert {'--net-clearances', '--pads', '--no-join-gate', '--no-own-pad-lift'} <= set(flags['repair_planes.py'])
    assert '--no-own-pad-lift' in flags['route.py']



def test_via_hole_raise_is_exactly_nothing_when_the_floor_is_not_above_the_clearance():
    """Raise-only: a board declaring no hole floor keeps every via keep-out to the bit."""
    cfg = GridRouteConfig(via_size=0.6, via_drill=0.4, clearance=0.15)
    assert cfg.via_hole_raise(0.15) == 0.0 and cfg.via_hole_raise(0.15, 0.15) == 0.0
    cfg.via_hole_floor = 0.254
    assert abs(cfg.via_hole_raise(0.15) - 0.004) < 1e-12        # 0.2 + 0.254 - 0.3 - 0.15
    assert cfg.via_hole_raise(0.3) == 0.0


def _route_map(floor):
    from obstacle_map import build_base_obstacle_map
    track = Segment(start_x=-0.5, start_y=0.0, end_x=0.5, end_y=0.0, width=0.2, layer='In1.Cu', net_id=2)
    pcb = _board(segments=[track])
    cfg = GridRouteConfig(via_size=0.6, via_drill=0.4, clearance=0.15, grid_step=0.002, board_edge_clearance=0.0,
                          layers=['F.Cu', 'In1.Cu', 'B.Cu'])
    cfg.via_hole_floor = floor
    return build_base_obstacle_map(pcb, cfg, [1])


def test_a_routed_via_keeps_its_hole_off_a_foreign_track_at_the_boards_hole_clearance():
    """watchy: route.py placed a 0.6/0.4 via 0.250 mm hole-to-track from a BTN3 In1.Cu track where the board asks
    0.254. With the board's floor, the router's via keep-out holds the hole at it."""
    coord = GridCoord(0.002)
    gx, gy = coord.to_grid(0.0, 0.552)          # ring 0.152 off the track, hole 0.252
    assert not _route_map(0.0).is_via_blocked(gx, gy)
    assert _route_map(0.254).is_via_blocked(gx, gy)


def test_a_board_declaring_no_hole_floor_gets_the_same_route_map():
    coord = GridCoord(0.002)
    a, b = _route_map(0.0), _route_map(0.1)     # a floor at or under the clearance raises nothing
    for y in range(240, 320):
        assert a.is_via_blocked(0, y) == b.is_via_blocked(0, y)

if __name__ == '__main__':
    failed = []
    for name, fn in sorted((n, f) for n, f in globals().items() if n.startswith('test_') and callable(f)):
        try:
            fn()
            print('PASS: ' + name)
        except Exception as e:      # a failed assertion or an error, reported per test
            failed.append(name)
            print('FAIL: %s  %s: %s' % (name, type(e).__name__, e))
    sys.exit(1 if failed else 0)
