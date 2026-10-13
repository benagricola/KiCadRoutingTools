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
    assert json.loads(out)['flag_forms']['repair_planes.py']['--max-track-width'] == ['number', 'per_layer']
    assert json.loads(out)['pad_fields']['repair_planes.py'] == ['ref', 'pad', 'fp', 'width']



def test_max_track_width_takes_a_number_or_a_width_per_layer():
    import argparse
    from repair_planes import parse_layer_widths
    assert parse_layer_widths('2') == 2.0
    assert parse_layer_widths('F.Cu=1.37,In1.Cu=3.56') == {'F.Cu': 1.37, 'In1.Cu': 3.56}
    for bad in ('F.Cu=', 'F.Cu=x', '=1.0', 'F.Cu=-1', 'wide'):
        try:
            parse_layer_widths(bad)
        except argparse.ArgumentTypeError:
            continue
        raise AssertionError(bad)


def test_each_layer_of_the_repairs_copper_is_laid_at_its_own_width():
    from kicad_parser import Segment
    from repair_planes import _cap_layer_widths
    caps = {'F.Cu': 1.37, 'In1.Cu': 3.56}
    new = [{'layer': 'F.Cu', 'width': 3.56, 'net_id': 1}, {'layer': 'In1.Cu', 'width': 3.56, 'net_id': 1},
           {'layer': 'F.Cu', 'width': 0.5, 'net_id': 1}, {'layer': 'B.Cu', 'width': 3.56, 'net_id': 1},
           {'layer': 'F.Cu', 'width': 3.56, 'net_id': 2}]
    old = Segment(start_x=0, start_y=0, end_x=1, end_y=0, width=3.56, layer='F.Cu', net_id=1)
    added = Segment(start_x=0, start_y=1, end_x=1, end_y=1, width=3.56, layer='F.Cu', net_id=1)
    _cap_layer_widths(new, [old, added], caps, {1}, {id(old)})
    assert [d['width'] for d in new] == [1.37, 3.56, 0.5, 3.56, 3.56]
    assert old.width == 3.56 and added.width == 1.37


def _plane_board(path):
    """GND poured on B.Cu over a 30 x 20 mm board; F.Cu SMD pads of GND, none joined to it: C1.2 (a decoupling pad),
    J1.1 and R1.2."""
    def fp(ref, x, y, gnd_pad, gnd_dx):
        other = '2' if gnd_pad == '1' else '1'
        return ('(footprint "t:P" (layer "F.Cu") (uuid "u-%s") (at %s %s)\n'
                ' (property "Reference" "%s" (at 0 0) (layer "F.SilkS"))\n'
                ' (pad "%s" smd rect (at %s 0) (size 0.5 0.5) (layers "F.Cu") (net 2 "SIG"))\n'
                ' (pad "%s" smd rect (at %s 0) (size 0.25 0.25) (layers "F.Cu") (net 1 "GND")))\n'
                % (ref, x, y, ref, other, -gnd_dx, gnd_pad, gnd_dx))
    text = ('(kicad_pcb (version 20241229) (generator "test")\n (general (thickness 1.6))\n'
            ' (layers (0 "F.Cu" signal) (2 "B.Cu" signal) (25 "Edge.Cuts" user))\n'
            ' (net 0 "") (net 1 "GND") (net 2 "SIG")\n'
            ' (gr_rect (start 0 0) (end 30 20) (stroke (width 0.1) (type solid)) (fill no) (layer "Edge.Cuts"))\n'
            + fp('C1', 8, 10, '2', 0.5) + fp('J1', 22, 10, '1', -0.5) + fp('R1', 15, 15, '2', 0.5)
            + ' (zone (net 1) (net_name "GND") (layer "B.Cu") (uuid "z") (hatch edge 0.5)'
            ' (connect_pads (clearance 0.5)) (min_thickness 0.2) (fill yes (thermal_gap 0.5)'
            ' (thermal_bridge_width 0.5))\n  (polygon (pts (xy 1 1) (xy 29 1) (xy 29 19) (xy 1 19)))\n'
            '  (filled_polygon (layer "B.Cu") (pts (xy 1 1) (xy 29 1) (xy 29 19) (xy 1 19))))\n)\n')
    pathlib.Path(path).write_text(text)


def _tap_widths(pads):
    """{(ref, pad): the track width each tap of pad repair was asked for}, repairing _plane_board's GND with
    --track-width 0.8 and the given --pads ends."""
    import repair_planes as rp
    seen = {}
    real = rp.tap_pad_with_escalation

    def spy(pad, layer, net_id, pcb_data, cfg, *a, **k):
        seen.setdefault((pad.component_ref, pad.pad_number), set()).add(round(cfg.track_width, 4))
        return real(pad, layer, net_id, pcb_data, cfg, *a, **k)
    rp.tap_pad_with_escalation = spy
    try:
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, 'plane.kicad_pcb')
            _plane_board(src)
            rp.repair_planes(src, os.path.join(tmp, 'out.kicad_pcb'), ['GND'], ['B.Cu'], track_width=0.8,
                             min_track_width=0.8, max_track_width=0.8, via_size=0.6, via_drill=0.3,
                             routing_layers=['F.Cu', 'B.Cu'], pads=pads, dry_run=True)
    finally:
        rp.tap_pad_with_escalation = real
    return seen


def test_a_pad_given_a_width_is_tapped_at_it_beside_pads_at_the_nets_width():
    """A decoupling pad (C1.2, width 0.25) and carrier pads (J1.1, R1.2, no width) in one call. Pad repair skips a
    pad it already finds on the plane, so at least one carrier pad is tapped."""
    seen = _tap_widths([{"ref": "C1", "pad": "2", "width": 0.25}, {"ref": "J1", "pad": "1"},
                        {"ref": "R1", "pad": "2"}])
    assert seen.get(('C1', '2')) == {0.25}, seen
    carriers = {k: v for k, v in seen.items() if k != ('C1', '2')}
    assert carriers and all(v == {0.8} for v in carriers.values()), seen


def test_ends_without_a_width_are_tapped_as_before():
    seen = _tap_widths([{"ref": "C1", "pad": "2"}, {"ref": "J1", "pad": "1"}, {"ref": "R1", "pad": "2"}])
    assert seen and all(v == {0.8} for v in seen.values()), seen


def test_a_bad_pads_end_is_refused_with_its_index_and_field():
    from repair_planes import PadsError, read_pads
    cases = [([{"ref": "C1", "pad": "2", "width": 0}], 'width'), ([{"ref": "C1", "pad": "2", "width": -1}], 'width'),
             ([{"ref": "C1", "pad": "2", "width": "0.2"}], 'width'),
             ([{"ref": "C1", "pad": "2", "width": True}], 'width'),
             ([{"ref": "C1", "pad": "2"}, {"pad": "1"}], 'ref'), ([{"ref": "C1", "pad": None}], 'pad'),
             ([{"ref": "C1", "pad": "2", "fp": 3}], 'fp')]
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, 'pads.json')
        for doc, fld in cases:
            pathlib.Path(path).write_text(json.dumps(doc))
            try:
                read_pads(path)
            except PadsError as e:
                assert e.code == 'bad_pad' and e.facts['field'] == fld \
                    and e.facts['index'] == len(doc) - 1, (doc, e.code, e.facts)
                continue
            raise AssertionError(doc)
        pathlib.Path(path).write_text(json.dumps({"ref": "C1"}))
        try:
            read_pads(path)
        except PadsError as e:
            assert e.code == 'not_a_list'
        else:
            raise AssertionError('not a list')
        good = [{"ref": "C1", "pad": "2", "width": 0.25}, {"ref": "J1", "pad": 1, "fp": "u"}]
        pathlib.Path(path).write_text(json.dumps(good))
        assert read_pads(path) == good
        pathlib.Path(path).write_text(json.dumps([{"ref": "C1", "pad": "2", "width": 0}]))
        out = subprocess.run([sys.executable, os.path.join(ROOT, 'py_router', 'repair_planes.py'), 'x.kicad_pcb',
                              'y.kicad_pcb', '--nets', 'GND', '--pads', path], capture_output=True, text=True,
                             cwd=tmp, timeout=120)
        assert out.returncode == 2 and 'bad_pad' in out.stderr and '"field": "width"' in out.stderr, out.stderr[-500:]


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
