#!/usr/bin/env python3
"""The phase-3 tap rip ladder rips the copper that walls a boxed-in pad first
(placemat fork, docs/fork-divergences.md "Rip ladder: pocket walls first").

Two failed tap edges of one net:
- pad P (5, 5) is walled in on both layers by a small square of net W's track;
- pad Q (20, 5) is walled in by a larger square of net Z's track.

Z's wall is longer, so the frontier ranking ('count') puts Z first (it did
before the pocket step). The pocket step floods each failed edge's target on
the router's grid: P's flood closes, walled only by W, and Q's passes the
router's probe budget, so the ladder rips W first.

The frontier cells are the router's own backward probe from each pad, as the
tap router records them. rip_up_net is replaced by a recorder so the test
reads which net the ladder asks to rip, in order.

    python3 tests/test_rip_pocket_walls_first.py
"""
import os
import sys
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'py_router'))
sys.path.insert(0, os.path.join(ROOT, 'tests'))
sys.path.insert(0, os.path.join(ROOT, 'rust_router'))

from synth import make_pad, make_seg, make_net, make_pcb  # noqa: E402
from routing_config import GridRouteConfig  # noqa: E402
from blocking_analysis import compute_net_obstacle_cells, _unpack_xy  # noqa: E402
from grid_router import GridObstacleMap, GridRouter  # noqa: E402
import phase3_routing  # noqa: E402

OURS, W, Z = 1, 2, 3
LAYERS = ['F.Cu', 'B.Cu']


def _square(cx, cy, half, net_id):
    pts = [(cx - half, cy - half), (cx + half, cy - half),
           (cx + half, cy + half), (cx - half, cy + half)]
    segs = []
    for layer in LAYERS:
        for i in range(4):
            (x1, y1), (x2, y2) = pts[i], pts[(i + 1) % 4]
            segs.append(make_seg(x1, y1, x2, y2, layer=layer, net_id=net_id,
                                 width=0.2))
    return segs


def _board():
    pads = {OURS: [make_pad(OURS, 5.0, 5.0, ref='U1', num='1'),
                   make_pad(OURS, 20.0, 5.0, ref='U2', num='1'),
                   make_pad(OURS, 12.0, 15.0, ref='U3', num='1')]}
    nets = {OURS: make_net(OURS, 'OURS'), W: make_net(W, 'W'),
            Z: make_net(Z, 'Z')}
    segs = _square(5.0, 5.0, 1.0, W) + _square(20.0, 5.0, 3.0, Z)
    return make_pcb(nets=nets, pads_by_net=pads, segments=segs)


def _config():
    return GridRouteConfig(layers=list(LAYERS), track_width=0.2,
                           clearance=0.15, grid_step=0.1)


def _map(pcb, cfg):
    obstacles = GridObstacleMap(len(LAYERS))
    for nid in (W, Z):
        tk, vk = compute_net_obstacle_cells(pcb, nid, None, cfg)
        keys = np.concatenate([tk, vk])
        gx, gy = _unpack_xy(keys)
        cells = np.stack([gx, gy, keys & 0xFF], axis=1).astype(np.int32)
        obstacles.add_blocked_cells_batch(cells)
    return obstacles


def _cell(x, y, layer=0):
    return (int(round(x / 0.1)), int(round(y / 0.1)), layer)


def _backward_frontier(obstacles, target, source):
    router = GridRouter(via_cost=500, h_weight=1.0, turn_cost=10)
    obstacles.clear_source_target_cells()
    for c in (target, source):
        obstacles.add_source_target_cell(*c)
    path, _it, blocked = router.route_with_frontier(
        obstacles, [target], [source], 5000)
    obstacles.clear_source_target_cells()
    assert path is None, "the pad must be walled in"
    return [tuple(c) for c in blocked]


def test_flood_finds_the_closed_pocket_and_its_wall():
    from pocket_walls import flood_pocket
    pcb, cfg = _board(), _config()
    obstacles = _map(pcb, cfg)
    p = flood_pocket(obstacles, [_cell(5.0, 5.0)], [0.0, 0.0], 5000)
    assert p is not None, "P is walled in on both layers"
    assert 0 < p.cells < 5000
    gx = [c[0] for c in p.wall]
    assert min(gx) >= 38 and max(gx) <= 62, (min(gx), max(gx))
    # The open pad is not boxed in: the flood passes the cap.
    assert flood_pocket(obstacles, [_cell(12.0, 15.0)], [0.0, 0.0], 5000) is None


def test_flood_preserves_terminal_exemptions_and_does_not_mutate_map():
    from pocket_walls import flood_pocket
    obstacles = GridObstacleMap(1)
    for x in range(-2, 3):
        for y in range(-2, 3):
            if abs(x) == 2 or abs(y) == 2:
                obstacles.add_blocked_cell(x, y, 0)
    assert flood_pocket(obstacles, [(0, 0, 0)], 0, 100) is not None
    obstacles.add_source_target_cell(2, 0, 0)
    assert flood_pocket(obstacles, [(0, 0, 0)], 0, 100) is None
    assert obstacles.is_terminal_cell(2, 0, 0)
    assert not obstacles.is_terminal_cell(0, 0, 0)


def test_closed_region_with_a_search_source_is_not_a_trapped_target():
    from pocket_walls import flood_pocket
    obstacles = _map(_board(), _config())
    target = _cell(5.0, 5.0)
    assert flood_pocket(obstacles, [target], 0, 5000,
                        sources=[_cell(5.5, 5.0)]) is None
    assert flood_pocket(obstacles, [target], 0, 5000,
                        sources=[_cell(12.0, 15.0)]) is not None


def _ladder_rips(pockets=None):
    pcb, cfg = _board(), _config()
    obstacles = _map(pcb, cfg)
    src = _cell(12.0, 15.0)
    tp, tq = _cell(5.0, 5.0), _cell(20.0, 5.0)
    bwd_p = _backward_frontier(obstacles, tp, src)
    bwd_q = _backward_frontier(obstacles, tq, src)
    # Z's edge first, as a run that met Q first would record it.
    failed = {
        (0, 2): (bwd_q, (20.0, 5.0), {'fwd': [], 'bwd': bwd_q, 'extra': [],
                                     'tgt_cells': [tq], 'src_cells': [src]}),
        (0, 1): (bwd_p, (5.0, 5.0), {'fwd': [], 'bwd': bwd_p, 'extra': [],
                                    'tgt_cells': [tp], 'src_cells': [src]}),
    }
    ripped = []

    def _record(net_id, *a, **kw):
        ripped.append(net_id)
        return None, None, None

    state = SimpleNamespace(frontier_blocking={}, working_obstacles=None,
                            net_obstacles_cache=None,
                            ripped_route_layer_costs={},
                            ripped_route_via_positions={})
    completed = {'tap_edges_failed': 2, 'new_segments': [], 'new_vias': [],
                 'mst_edges': [(2, 0, 1.0), (2, 1, 1.0)]}
    with patch.object(phase3_routing, "rip_up_net", _record), \
            patch.object(phase3_routing, "LEG_RIP_ENABLED", False), \
            _pockets_patch(pockets):
        out = phase3_routing.try_phase3_ripup(
            OURS, completed, failed, [], [], pcb, cfg, state,
            [W, Z], [], [], {W: [], Z: []}, {W: {}, Z: {}}, {}, [], {},
            {'F.Cu': 0, 'B.Cu': 1}, None, None, [],
            obstacle_cache={}, tap_obstacles=obstacles)
    assert out is None
    return ripped


def _pockets_patch(pockets):
    import contextlib
    import pocket_walls
    if pockets is None:
        return contextlib.nullcontext()
    return patch.object(pocket_walls, "pocket_wall_blockers",
                        lambda *a, **kw: pockets)


def _blocker(net_id, cells):
    from blocking_analysis import BlockingInfo
    return BlockingInfo(net_id=net_id, net_name={W: 'W', Z: 'Z'}[net_id],
                        blocked_count=cells, track_cells=cells, via_cells=0,
                        unique_cells=cells, near_target_cells=0,
                        near_source_cells=0, details='')


def test_pocket_walls_keep_the_ladders_ranking():
    """One pocket walled by W (more wall cells) and Z. The ladder's ranking
    puts Z first (Q's larger frontier), so Z is ripped first: a pocket's walls
    are ordered by the ranking, not by wall cells."""
    from pocket_walls import Pocket, PocketFlood
    pocket = Pocket(target_xy=(5.0, 5.0), flood=PocketFlood(10, ((50, 50, 0),)),
                    walls=(_blocker(W, 50), _blocker(Z, 10)))
    assert _ladder_rips([pocket]) == [Z]


def test_ladder_rips_the_small_pockets_wall_first():
    assert _ladder_rips() == [W]


def main():
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith('test_') and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except Exception as e:
                fails += 1
                print(f"FAIL {name}: {e}")
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
