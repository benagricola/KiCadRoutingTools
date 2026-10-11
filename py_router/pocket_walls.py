"""Pocket walls: the copper that bounds a boxed-in tap target (placemat fork).

FORK DIVERGENCE (docs/fork-divergences.md, "Rip ladder: pocket walls first"):
upstream's phase-3 tap rip ladder (phase3_routing.try_phase3_ripup) ranks
blockers by their share of the failed searches' frontiers, merged over every
failed edge. When one target is walled into a small pocket and another edge
failed in a larger region, the larger region's walls outrank the small
pocket's, and the ladder can spend its rips without touching the copper round
the boxed-in pad (splitflap_driver, U7 pin 10 of +3V3). This module floods each
failed edge's target on the router's own obstacle map, at the net's track
margins, and names the nets whose copper bounds the region when the flood
closes; the ladder tries those nets first.

The flood follows the router's move tests (rust_router/src/router.rs, the
GridSearch neighbour loop): an 8-way step is open unless `segment_blocked` at
the layer's track margin or `move_clips_corner` (steps onto or off a terminal
cell exempt), and a layer change is open where `is_via_blocked_rung` is false
or the cell is a free via, onto a layer whose cell passes `segment_blocked`.
It leaves out the search's direction rules after a via, so its region is never
smaller than what the search could reach.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

Cell = Tuple[int, int, int]

DIRECTIONS = ((1, 0), (-1, 0), (0, 1), (0, -1),
              (1, 1), (1, -1), (-1, 1), (-1, -1))


@dataclass(frozen=True)
class PocketFlood:
    """A closed region reachable from a target: `cells` grid states (gx, gy,
    layer) in it, and `wall` the blocked cells round it (each blocked cell
    within a refused step's track margin, sorted). Corner-clipping steps
    record the destination as an attribution hint; via vetoes add no wall
    cells, so the set is not a complete list of obstacle owners."""
    cells: int
    wall: Tuple[Cell, ...]


@dataclass(frozen=True)
class Pocket:
    """One failed edge's boxed-in target: where it is, its flood, and the
    nets on its wall as BlockingInfo, most wall cells first. `opens` is
    whether the flood leaves the pocket once the walls' tracks and vias
    are off the map (their pads stay, as a rip leaves them); only a pocket
    that opens has its walls promoted by the rip ladder."""
    target_xy: Tuple[float, float]
    flood: PocketFlood
    walls: Tuple  # BlockingInfo, ordered
    opens: bool = True


def _margin_at(track_margin, layer: int) -> float:
    if isinstance(track_margin, (int, float)):
        return float(track_margin)
    return float(track_margin[layer]) if layer < len(track_margin) else 0.0


def _blocking_cells(obstacles, gx1, gy1, gx2, gy2, layer, r) -> List[Cell]:
    """The blocked cells that make segment_blocked(gx1, gy1, gx2, gy2, layer, r)
    true: within Euclidean distance r of the segment (r <= 0: the end cell)."""
    if r <= 0.0:
        return [(gx2, gy2, layer)] if obstacles.is_blocked(gx2, gy2, layer) else []
    rc = int(math.ceil(r))
    dx, dy = gx2 - gx1, gy2 - gy1
    len2 = dx * dx + dy * dy
    out = []
    for cx in range(min(gx1, gx2) - rc, max(gx1, gx2) + rc + 1):
        for cy in range(min(gy1, gy2) - rc, max(gy1, gy2) + rc + 1):
            if not obstacles.is_blocked(cx, cy, layer):
                continue
            if len2 == 0:
                ex, ey = cx - gx1, cy - gy1
            else:
                t = ((cx - gx1) * dx + (cy - gy1) * dy) / len2
                t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
                ex, ey = cx - (gx1 + t * dx), cy - (gy1 + t * dy)
            if ex * ex + ey * ey <= r * r:
                out.append((cx, cy, layer))
    return out


def flood_pocket(obstacles, starts: Sequence[Cell], track_margin, max_cells: int,
                 via_rung: int = 0,
                 forbidden_layers: Iterable[int] = (),
                 sources: Sequence[Cell] = ()) -> Optional[PocketFlood]:
    """Flood from `starts` (the target's cells) on `obstacles`. Returns the
    region and its wall when it closes within `max_cells` states, else None
    (the target is not boxed in). A region that reaches any recorded search
    source is also rejected. Both endpoint sets retain their search terminal
    exemptions. Works on a clone, so the caller's map keeps
    its source/target cells."""
    if not starts:
        return None
    m = obstacles.clone()
    source_cells = set(tuple(c) for c in sources)
    for gx, gy, layer in (*starts, *sources):
        m.add_source_target_cell(gx, gy, layer)
    num_layers = m.num_layers
    forbidden = set(forbidden_layers)
    seen = set()
    queue = []
    for c in starts:
        c = (int(c[0]), int(c[1]), int(c[2]))
        if c not in seen and c[2] < num_layers:
            seen.add(c)
            queue.append(c)
    wall = set()
    i = 0
    while i < len(queue):
        if len(seen) > max_cells:
            return None
        gx, gy, layer = queue[i]
        i += 1
        if (gx, gy, layer) in source_cells:
            return None  # A reachable search source means the target is not trapped.
        r = _margin_at(track_margin, layer)
        if layer not in forbidden:
            for dx, dy in DIRECTIONS:
                nx, ny = gx + dx, gy + dy
                n = (nx, ny, layer)
                if n in seen:
                    continue
                if m.segment_blocked(gx, gy, nx, ny, layer, r):
                    wall.update(_blocking_cells(m, gx, gy, nx, ny, layer, r))
                    continue
                if (not m.is_terminal_cell(gx, gy, layer)
                        and not m.is_terminal_cell(nx, ny, layer)
                        and m.move_clips_corner(gx, gy, nx, ny, layer, r)):
                    wall.add(n)
                    continue
                seen.add(n)
                queue.append(n)
        if m.is_via_blocked_rung(gx, gy, via_rung) and not m.is_free_via(gx, gy):
            continue
        for other in range(num_layers):
            if other == layer or other in forbidden:
                continue
            n = (gx, gy, other)
            if n in seen:
                continue
            ro = _margin_at(track_margin, other)
            if m.segment_blocked(gx, gy, gx, gy, other, ro):
                wall.update(_blocking_cells(m, gx, gy, gx, gy, other, ro))
                continue
            seen.add(n)
            queue.append(n)
    return PocketFlood(cells=len(seen), wall=tuple(sorted(wall)))


def _rows_minus(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """The rows of integer array `a` that are not rows of `b`."""
    if len(a) == 0 or len(b) == 0:
        return a
    a = np.ascontiguousarray(a)
    b = np.ascontiguousarray(b, dtype=a.dtype)
    view = np.dtype((np.void, a.dtype.itemsize * a.shape[1]))
    return a[~np.isin(a.view(view).ravel(), b.view(view).ravel())]


def _copper_only_cells(pcb_data, net_id: int, config) -> Dict:
    """What taking a net's tracks and vias off the map would unstamp, as
    arrays for the map's remove batches. The net's obstacle-cache entry
    stamps its pads and its copper as one deduplicated set; a cell its pads
    also stamp stays blocked after a rip, so those cells are left out."""
    from obstacle_cache import precompute_net_obstacles
    full = precompute_net_obstacles(pcb_data, net_id, config)
    pads = precompute_net_obstacles(pcb_data, net_id, config, pads_only=True)
    rungs = {}
    for r, cells in (getattr(full, 'blocked_vias_rungs', None) or {}).items():
        rungs[r] = _rows_minus(cells, (getattr(pads, 'blocked_vias_rungs', None)
                                       or {}).get(r, np.empty((0, 2), np.int32)))
    return {
        'cells': _rows_minus(full.blocked_cells, pads.blocked_cells),
        'vias': _rows_minus(full.blocked_vias, pads.blocked_vias),
        # Spans are segment keep-outs only (pads stamp cells), refcounted
        # apart from the cells, so all of them come off.
        'cell_spans': full.blocked_cell_spans,
        'via_spans': full.blocked_via_spans,
        'vias_small': (None if 1 in rungs else _rows_minus(
            full.blocked_vias_small, pads.blocked_vias_small)),
        'rungs': rungs,
    }


def _remove_copper(m, cells: Dict) -> None:
    """Unstamp `_copper_only_cells` from map `m` (a clone)."""
    if len(cells['cells']):
        m.remove_blocked_cells_batch(np.ascontiguousarray(cells['cells'], dtype=np.int32))
    if len(cells['vias']):
        m.remove_blocked_vias_batch(np.ascontiguousarray(cells['vias'], dtype=np.int32))
    if len(cells['cell_spans']):
        m.remove_blocked_cell_spans_batch(cells['cell_spans'])
    if len(cells['via_spans']):
        m.remove_blocked_via_spans_batch(cells['via_spans'])
    small = cells['vias_small']
    if small is not None and len(small):
        m.remove_blocked_vias_small_batch(np.ascontiguousarray(small, dtype=np.int32))
    for r, c in sorted(cells['rungs'].items()):
        if len(c):
            m.remove_blocked_vias_rung_batch(r, np.ascontiguousarray(c, dtype=np.int32))


def pocket_wall_blockers(failed_edge_blocking: Dict, obstacles, pcb_data, config,
                         net_id: int, routed_net_paths: Dict, exclude_net_ids,
                         obstacle_cache=None,
                         rip_ids: Optional[Callable] = None) -> List[Pocket]:
    """The boxed-in targets of a net's failed tap edges, smallest pocket first.

    Each failed edge's entry carries its target cells ('tgt_cells' in the
    direction dict, single_ended_routing.route_multipoint_taps). A target whose
    flood closes within config.max_probe_iterations states (the router's own
    stuck test) is boxed in; its wall cells are attributed to routed nets by
    analyze_frontier_blocking and the nets ordered by how many wall cells each
    owns (the rip ladder reorders them by its own ranking). The flood runs on
    a clone of `obstacles` with the net's #908 own-pad lift applied, as the
    tap searches had it; `obstacles` must not hold that lift already (a clone
    of a lifted map would be lifted twice).

    `rip_ids(walls)` gives the net ids whose tracks and vias ripping the
    walls would take off the map (the rippable walls, each with its diff
    pair partner); by default every wall net. A pocket whose flood still
    closes with that copper off has `opens` False."""
    from blocking_analysis import analyze_frontier_blocking
    # Edges that can name a pocket: a recorded target and source. Gathered
    # first so a ladder entry with none of them costs no map clone.
    edges = []
    done = set()
    for _key, entry in failed_edge_blocking.items():
        dirs = entry[2] if len(entry) > 2 else None
        starts = tuple(sorted(set(tuple(c) for c in (dirs or {}).get('tgt_cells') or ())))
        sources = tuple(sorted(set(tuple(c) for c in (dirs or {}).get('src_cells') or ())))
        key = (starts, sources)
        if not starts or not sources or key in done:
            continue
        done.add(key)
        edges.append((starts, sources, tuple(entry[1])))
    if not edges:
        return []
    margins = config.track_margins_for_net(net_id)
    rung = getattr(config, 'via_rung', 0)
    forbidden = [i for i, c in enumerate(config.get_layer_costs()) if c < 0]
    cap = int(config.max_probe_iterations)
    pockets = []
    copper = {}  # net id -> _copper_only_cells, shared by this call's pockets
    # The taps searched with the #908 own-pad lift applied
    # (single_ended_routing.route_multipoint_taps), and it is released before
    # the rip ladder runs; without it a pad sealed only by its own
    # footprint's copper floods as a 1-cell pocket with no rippable wall. The
    # callers pass the tap map after that release, so the clone is lifted
    # here. Released below so the (map id, net) registry does not keep the
    # clone.
    from routing_context import ensure_own_pad_lift, release_own_pad_lift
    lifted = None
    _lift = None
    try:
        lifted = obstacles.clone()
        _lift = ensure_own_pad_lift(lifted, pcb_data, net_id)
        for starts, sources, target_xy in edges:
            flood = flood_pocket(lifted, starts, margins, cap, rung, forbidden, sources)
            if flood is None or not flood.wall:
                continue
            walls = list(analyze_frontier_blocking(
                list(flood.wall), pcb_data, config, routed_net_paths,
                exclude_net_ids=exclude_net_ids, target_xy=target_xy,
                obstacle_cache=obstacle_cache,
                # The wall is not a failed search's frontier: charging it to the
                # #590 history field would change later routes' costs whenever a
                # pocket is found, even when the rip order is unchanged.
                record_history=False))
            walls.sort(key=lambda b: (-b.blocked_count, -b.unique_cells, b.net_id))
            if not walls:
                continue
            ids = (set(rip_ids(walls)) if rip_ids is not None
                   else {b.net_id for b in walls})
            opens = False
            if ids:
                trial = lifted.clone()
                for nid in sorted(ids):
                    if nid not in copper:
                        copper[nid] = _copper_only_cells(pcb_data, nid, config)
                    _remove_copper(trial, copper[nid])
                opens = flood_pocket(trial, starts, margins, cap, rung,
                                     forbidden, sources) is None
            pockets.append(Pocket(target_xy=target_xy, flood=flood,
                                  walls=tuple(walls), opens=opens))
    finally:
        if lifted is not None:
            release_own_pad_lift(lifted, net_id, _lift)
    pockets.sort(key=lambda p: (p.flood.cells, p.target_xy))
    return pockets
