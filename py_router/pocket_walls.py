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
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

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
    nets on its wall as BlockingInfo, most wall cells first."""
    target_xy: Tuple[float, float]
    flood: PocketFlood
    walls: Tuple  # BlockingInfo, ordered


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


def pocket_wall_blockers(failed_edge_blocking: Dict, obstacles, pcb_data, config,
                         net_id: int, routed_net_paths: Dict, exclude_net_ids,
                         obstacle_cache=None) -> List[Pocket]:
    """The boxed-in targets of a net's failed tap edges, smallest pocket first.

    Each failed edge's entry carries its target cells ('tgt_cells' in the
    direction dict, single_ended_routing.route_multipoint_taps). A target whose
    flood closes within config.max_probe_iterations states (the router's own
    stuck test) is boxed in; its wall cells are attributed to routed nets by
    analyze_frontier_blocking and the nets ordered by how many wall cells each
    owns."""
    from blocking_analysis import analyze_frontier_blocking
    margins = config.track_margins_for_net(net_id)
    rung = getattr(config, 'via_rung', 0)
    forbidden = [i for i, c in enumerate(config.get_layer_costs()) if c < 0]
    cap = int(config.max_probe_iterations)
    pockets = []
    done = set()
    for _key, entry in failed_edge_blocking.items():
        dirs = entry[2] if len(entry) > 2 else None
        starts = tuple(sorted(set(tuple(c) for c in (dirs or {}).get('tgt_cells') or ())))
        sources = tuple(sorted(set(tuple(c) for c in (dirs or {}).get('src_cells') or ())))
        key = (starts, sources)
        if not starts or not sources or key in done:
            continue
        done.add(key)
        flood = flood_pocket(obstacles, starts, margins, cap, rung, forbidden, sources)
        if flood is None or not flood.wall:
            continue
        walls = list(analyze_frontier_blocking(
            list(flood.wall), pcb_data, config, routed_net_paths,
            exclude_net_ids=exclude_net_ids, target_xy=entry[1],
            obstacle_cache=obstacle_cache))
        walls.sort(key=lambda b: (-b.blocked_count, -b.unique_cells, b.net_id))
        if walls:
            pockets.append(Pocket(target_xy=tuple(entry[1]), flood=flood,
                                  walls=tuple(walls)))
    pockets.sort(key=lambda p: (p.flood.cells, p.target_xy))
    return pockets
