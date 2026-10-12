#!/usr/bin/env python3
"""Diff-pair GND return vias (_create_gnd_vias) keep clearance from the pair's
own just-routed copper and from foreign copper.

The pose router picks a return via's side (ahead of or behind the signal vias)
on the obstacle map, which does not hold the pair's own tracks. When the pair
bends back within reach of the via, the via landed on the pair's track and
KiCad reported shorting_items GND/P and GND/N. Fork divergence: see
docs/fork-divergences.md, "Diff-pair GND return vias".

    python3 tests/test_gnd_return_via_pair_copper.py
"""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, 'py_router'))
sys.path.insert(0, os.path.join(_ROOT, 'py_tools'))

from kicad_parser import Segment, Via, Net, PCBData, BoardInfo
from routing_config import GridRouteConfig, GridCoord
import obstacle_map  # noqa: F401  # puts rust_router on sys.path
from diff_pair_routing import _create_gnd_vias
from check_drc import check_via_segment_overlap

P, N, GND, FOREIGN = 1, 2, 3, 4


def _cfg():
    return GridRouteConfig(grid_step=0.05, via_size=0.6, via_drill=0.3,
                           clearance=0.15, hole_to_hole_clearance=0.25,
                           track_width=0.2, layers=['F.Cu', 'B.Cu'])


def _pcb(segments=(), vias=()):
    return PCBData(board_info=BoardInfo(layers={}, copper_layers=['F.Cu', 'B.Cu'],
                                        board_bounds=(-10.0, -10.0, 10.0, 10.0)),
                   nets={P: Net(net_id=P, name='D_P', pads=[]),
                         N: Net(net_id=N, name='D_N', pads=[]),
                         GND: Net(net_id=GND, name='GND', pads=[]),
                         FOREIGN: Net(net_id=FOREIGN, name='SIG', pads=[])},
                   footprints={}, vias=list(vias), segments=list(segments),
                   pads_by_net={})


def _path(coord):
    # Centerline heading +x on F.Cu, a layer change at the origin, then +x on B.Cu.
    pts = [(-3.0, 0.0, 0), (0.0, 0.0, 0), (0.0, 0.0, 1), (3.0, 0.0, 1)]
    return [(coord.to_grid(x, y)[0], coord.to_grid(x, y)[1], layer) for x, y, layer in pts]


def _sites(cfg, coord, spacing):
    """Upstream placement with no gate: [p_ahead, n_ahead] and [p_behind, n_behind]."""
    ahead = _create_gnd_vias(_path(coord), coord, cfg, cfg.layers, spacing, GND, [1])
    behind = _create_gnd_vias(_path(coord), coord, cfg, cfg.layers, spacing, GND, [-1])
    return ahead, behind


def _shorts(vias, segments, cfg):
    return [(v, s) for v in vias for s in segments
            if s.net_id != v.net_id and check_via_segment_overlap(v, s, cfg.clearance)[0]]


def _exact_clear(v, segments, vias, cfg):
    """Full clearance, no tolerance: copper to every track and via, drill to
    every drill."""
    from geometry_utils import point_to_segment_distance
    import math
    for s in segments:
        d = point_to_segment_distance(v.x, v.y, s.start_x, s.start_y, s.end_x, s.end_y)
        if d < v.size / 2 + s.width / 2 + cfg.clearance - 1e-9:
            return False
    for o in vias:
        d = math.hypot(v.x - o.x, v.y - o.y)
        if d < v.size / 2 + o.size / 2 + cfg.clearance - 1e-9:
            return False
        if d < v.drill / 2 + o.drill / 2 + cfg.hole_to_hole_clearance - 1e-9:
            return False
    return True


def _seg(x1, y1, x2, y2, net, layer='F.Cu', w=0.2):
    return Segment(start_x=x1, start_y=y1, end_x=x2, end_y=y2, width=w, layer=layer, net_id=net)


def test_return_via_moves_off_the_pairs_own_track():
    """The pair's N track bends back across the ahead site: that side's via
    goes behind, clear of the track, instead of shorting it."""
    cfg, spacing = _cfg(), 0.25
    coord = GridCoord(cfg.grid_step)
    ahead, behind = _sites(cfg, coord, spacing)
    n_site = ahead[1]
    # A short N track on F.Cu through the ahead N site, out of reach of the
    # behind site.
    own_n = _seg(n_site.x - 0.3, n_site.y, n_site.x + 0.3, n_site.y, N)
    assert _shorts(ahead, [own_n], cfg), "test setup: the ahead site must short the track"

    vias = _create_gnd_vias(_path(coord), coord, cfg, cfg.layers, spacing, GND, [1],
                            pair_segments=[own_n], pair_vias=[], pcb_data=_pcb())
    assert len(vias) == 2, vias
    assert not _shorts(vias, [own_n], cfg), vias
    # Both vias move behind together (upstream places them as a pair).
    for v, b in zip(vias, behind):
        assert abs(v.x - b.x) < 1e-9 and abs(v.y - b.y) < 1e-9, (v, b)


def test_return_via_dropped_when_nothing_clear_within_the_bound():
    """Foreign copper covers every N-side site out to one via diameter: the
    N-side via is not placed; the P-side via keeps the router's site."""
    cfg, spacing = _cfg(), 0.25
    coord = GridCoord(cfg.grid_step)
    ahead, _ = _sites(cfg, coord, spacing)
    # A 3 mm wide foreign track whose edge sits at y = -0.5: every N-side
    # candidate (y <= -0.2) is within clearance, every P-side one is clear.
    foreign = _seg(-3.0, -2.0, 3.0, -2.0, FOREIGN, layer='B.Cu', w=3.0)

    vias = _create_gnd_vias(_path(coord), coord, cfg, cfg.layers, spacing, GND, [1],
                            pair_segments=[], pair_vias=[],
                            pcb_data=_pcb(segments=[foreign]))
    assert len(vias) == 1, vias
    assert abs(vias[0].x - ahead[0].x) < 1e-9 and abs(vias[0].y - ahead[0].y) < 1e-9, vias


def test_blocked_at_both_sites_placed_one_step_away():
    """The pair's own copper 0.01 mm inside clearance of both N-side sites:
    the N-side via lands one grid step from one of them, at full clearance."""
    import math
    cfg, spacing = _cfg(), 0.25
    coord = GridCoord(cfg.grid_step)
    ahead, behind = _sites(cfg, coord, spacing)
    d = cfg.via_size + cfg.clearance - 0.01
    own_vias = [Via(x=s.x, y=s.y - d, size=cfg.via_size, drill=cfg.via_drill,
                    layers=['F.Cu', 'B.Cu'], net_id=N) for s in (ahead[1], behind[1])]
    vias = _create_gnd_vias(_path(coord), coord, cfg, cfg.layers, spacing, GND, [1],
                            pair_segments=[], pair_vias=own_vias, pcb_data=_pcb())
    assert len(vias) == 2, vias
    p_via, n_via = vias
    assert abs(p_via.x - ahead[0].x) < 1e-9 and abs(p_via.y - ahead[0].y) < 1e-9, p_via
    step = min(math.hypot(n_via.x - s.x, n_via.y - s.y) for s in (ahead[1], behind[1]))
    assert abs(step - cfg.grid_step) < 1e-9, (n_via, step)
    assert _exact_clear(n_via, [], own_vias + [p_via], cfg), n_via


def test_return_vias_keep_the_upstream_site_when_clear():
    """Nothing in reach: the vias land where upstream puts them."""
    cfg, spacing = _cfg(), 0.25
    coord = GridCoord(cfg.grid_step)
    ahead, _ = _sites(cfg, coord, spacing)
    # The pair's own straight tracks either side of the via, at +-spacing.
    own = [_seg(-3.0, spacing, 0.0, spacing, P), _seg(-3.0, -spacing, 0.0, -spacing, N),
           _seg(0.0, spacing, 3.0, spacing, P, 'B.Cu'), _seg(0.0, -spacing, 3.0, -spacing, N, 'B.Cu')]
    pair_vias = [Via(x=0.0, y=spacing, size=cfg.via_size, drill=cfg.via_drill,
                     layers=['F.Cu', 'B.Cu'], net_id=P),
                 Via(x=0.0, y=-spacing, size=cfg.via_size, drill=cfg.via_drill,
                     layers=['F.Cu', 'B.Cu'], net_id=N)]
    vias = _create_gnd_vias(_path(coord), coord, cfg, cfg.layers, spacing, GND, [1],
                            pair_segments=own, pair_vias=pair_vias, pcb_data=_pcb())
    assert len(vias) == 2, vias
    for v, a in zip(vias, ahead):
        assert abs(v.x - a.x) < 1e-9 and abs(v.y - a.y) < 1e-9, (v, a)


def test_own_copper_just_inside_clearance_moves_the_via():
    """A pair track 0.01 mm inside the via's clearance, or a pair via 0.01 mm
    inside via-to-via clearance, counts as a conflict: the via moves to the
    other side, or off both sites when that side is taken too."""
    cfg, spacing = _cfg(), 0.25
    coord = GridCoord(cfg.grid_step)
    ahead, behind = _sites(cfg, coord, spacing)
    n = ahead[1]
    gap = cfg.via_size / 2 + 0.1 + cfg.clearance - 0.01
    own = _seg(n.x - 0.3, n.y - gap, n.x + 0.3, n.y - gap, N)
    vias = _create_gnd_vias(_path(coord), coord, cfg, cfg.layers, spacing, GND, [1],
                            pair_segments=[own], pair_vias=[], pcb_data=_pcb())
    assert len(vias) == 2, vias
    for v, b in zip(vias, behind):
        assert abs(v.x - b.x) < 1e-9 and abs(v.y - b.y) < 1e-9, (v, b)

    # A pair via just inside via-to-via clearance of the ahead N site, and the
    # pair's track over the behind N site: the N-side via moves off both, to a
    # site at full clearance.
    d = cfg.via_size + cfg.clearance - 0.01
    own_via = Via(x=n.x, y=n.y - d, size=cfg.via_size, drill=cfg.via_drill,
                  layers=['F.Cu', 'B.Cu'], net_id=N)
    b = behind[1]
    own_behind = _seg(b.x - 0.3, b.y, b.x + 0.3, b.y, N)
    vias = _create_gnd_vias(_path(coord), coord, cfg, cfg.layers, spacing, GND, [1],
                            pair_segments=[own_behind], pair_vias=[own_via], pcb_data=_pcb())
    assert len(vias) == 2, vias
    assert abs(vias[0].x - ahead[0].x) < 1e-9 and abs(vias[0].y - ahead[0].y) < 1e-9, vias
    assert not any(abs(vias[1].x - s.x) < 1e-9 and abs(vias[1].y - s.y) < 1e-9
                   for s in (n, b)), vias
    assert _exact_clear(vias[1], [own_behind], [own_via, vias[0]], cfg), vias


def test_no_board_is_upstreams_placement():
    """With pcb_data None nothing is checked: the vias land on the router's
    side even over the pair's own copper (upstream's behaviour)."""
    cfg, spacing = _cfg(), 0.25
    coord = GridCoord(cfg.grid_step)
    ahead, _ = _sites(cfg, coord, spacing)
    vias = _create_gnd_vias(_path(coord), coord, cfg, cfg.layers, spacing, GND, [1],
                            pair_segments=[_seg(ahead[1].x - 0.3, ahead[1].y,
                                                ahead[1].x + 0.3, ahead[1].y, N)])
    assert [(v.x, v.y) for v in vias] == [(a.x, a.y) for a in ahead], vias


def run():
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith('test_') and callable(fn):
            try:
                fn()
                print(f"  PASS: {name}")
            except Exception as e:  # noqa: BLE001
                fails += 1
                print(f"  FAIL: {name}: {type(e).__name__}: {e}")
    print(f"\n{fails} failed" if fails else "\nall passed")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(run())
