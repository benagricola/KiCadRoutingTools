"""Bus corridor planning (#296 R9 / #424): plan ONE centerline per bus group.

The neighbor-attraction bus router has a structural flaw: the guide (middle)
member routes FIRST with no guidance, so the group's corridor is whatever the
guide's solo shortest path happened to be -- chosen with no knowledge that
N-1 siblings must fit beside it. When that corridor threads a one-track gap,
the siblings' attraction loses to real obstacle costs and the group scatters
(measured corpus-wide in #296: 2.57 vs 1.24 vias/member vs the human).

This module plans the corridor BEFORE any member routes, with capacity chosen
SOFTLY (no hard rejection): the group's representative net is probe-routed at
a ladder of inflated clearances -- extra clearance k*(track+clearance) is
"room for k sibling tracks on each side" -- and the winner minimizes

    score = probe_length_mm + (k_max - k) * room_mm * ROOM_WEIGHT

i.e. a corridor with room for the whole bus wins unless it costs too much
length. The winning probe's path (grid coords + layers) is then fed as the
attraction path to EVERY member, including the guide, so the whole group
packs into a corridor that was chosen with group knowledge. Probes commit
nothing; members still route individually with full rip-up, so everything
stays soft -- a member that genuinely cannot follow the corridor routes
around it exactly as before.

The inflation mechanism is the existing wide-power-net machinery: the probe
temporarily gives the representative a track width of track + 2k*(track+
clearance), so the router itself keeps k sibling-rooms of margin per side on
the SHARED obstacle map (track_margin) -- no per-rung map builds. The power
neck-down ladder is disabled for probes (power_tap_neckdown=False) so a wide
probe either routes at its full margin or fails the rung honestly. One probe
map is still built, excluding ALL bus members' stubs (the siblings will pack
into the corridor; their present stubs must not veto it).
"""

from dataclasses import replace

import env_knobs
from typing import Dict, List, Optional, Tuple

from bus_detection import BusGroup, get_bus_routing_order
from obstacle_map import add_net_pads_as_obstacles, build_base_obstacle_map

# A missing sibling-room costs this many mm of detour before the planner
# prefers the narrower corridor: k rungs below k_max is penalized like
# ROOM_WEIGHT * k * (track + clearance) millimetres of extra length.
ROOM_WEIGHT = 40.0
# Rung cap: k_max = min(ceil((N-1)/2), MAX_RUNG) sibling-rooms per side.
MAX_RUNG = 3
# Probe via-cost multiplier (#296 R9 phase C): the human routes a bus as a
# river on ONE layer; a centerline probed at normal via cost hops layers
# freely and then guides every member incoherently. Pricing vias up in the
# PROBE ONLY makes the planned corridor layer-coherent; members still pay
# normal via costs. Override with KICAD_BUS_CORRIDOR_VIA_MULT (1 = off).
CORRIDOR_VIA_COST_MULT = 4.0
# Fork: setbacks (mm) tried for a wide rung that cannot leave the terminals.
# A rung's sibling room is measured only past the setback: the corridor runs
# at the rung-0 path from each terminal to the setback point, and the wide
# probe routes between the two setback points. A 0.4 mm-pitch pin row has no
# room for a wide track at the pins, so without it only rung 0 ever routes.
CORRIDOR_SETBACKS_MM = (1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0, 8.0)


def _sample_dense(path: List[Tuple[int, int, int]], step: int = 1
                  ) -> List[Tuple[int, int, int]]:
    """Densify a simplified (gx, gy, layer) waypoint path so the Rust
    attraction lookup sees a point every `step` grid cells (same contract as
    single_ended_loop's neighbor-path sampling)."""
    if len(path) < 2:
        return list(path)
    out: List[Tuple[int, int, int]] = []
    for (x1, y1, l1), (x2, y2, l2) in zip(path, path[1:]):
        dx, dy = x2 - x1, y2 - y1
        n = max(abs(dx), abs(dy))
        if n == 0:
            out.append((x1, y1, l1))
            continue
        for i in range(0, n, step):
            t = i / n
            out.append((int(round(x1 + dx * t)), int(round(y1 + dy * t)), l1))
    out.append(path[-1])
    return out


def _cell_at_setback(dense, setback_cells):
    """Index of the first cell of `dense` at least `setback_cells` grid cells
    (path length) from its start, or None when the path is shorter. Cells of a
    layer change are skipped so the setback point is a plain track cell."""
    import math
    cum = 0.0
    for i in range(1, len(dense)):
        cum += math.hypot(dense[i][0] - dense[i - 1][0],
                          dense[i][1] - dense[i - 1][1])
        if cum >= setback_cells and dense[i][2] == dense[i - 1][2] and (
                i + 1 >= len(dense) or dense[i + 1][2] == dense[i][2]):
            return i
    return None


def _setback_probe(pcb_data, rep, cfg_k, group_map, base_path, setback_mm,
                   grid_step):
    """Fork: route the wide probe between two points `setback_mm` along the
    rung-0 path from its ends, and stitch the rung-0 path back on at both
    ends. Returns (result, dense_path, extra_length_mm) or None."""
    import math
    from single_ended_routing import route_net_with_obstacles
    from routing_config import GridCoord
    dense = _sample_dense(base_path, step=1)
    cells = setback_mm / grid_step
    i = _cell_at_setback(dense, cells)
    j_rev = _cell_at_setback(list(reversed(dense)), cells)
    if i is None or j_rev is None:
        return None
    j = len(dense) - 1 - j_rev
    if i >= j:
        return None
    coord = GridCoord(grid_step)

    def row(c):
        x, y = coord.to_float(c[0], c[1])
        return (c[0], c[1], c[2], x, y)
    probe_map = group_map.clone_fresh()
    result = route_net_with_obstacles(
        pcb_data, rep, cfg_k, probe_map,
        sources_override=[row(dense[i])], targets_override=[row(dense[j])])
    if not result or result.get('failed') or not result.get('path'):
        return None
    head, tail = dense[:i], dense[j + 1:]
    extra = sum(math.hypot(a[0] - b[0], a[1] - b[1])
                for seq in (dense[:i + 1], dense[j:])
                for a, b in zip(seq, seq[1:])) * grid_step
    return result, head + _sample_dense(result['path'], step=1) + tail, extra


def plan_bus_corridors(pcb_data, config, bus_groups: List[BusGroup],
                       verbose: bool = False
                       ) -> Tuple[Dict[str, List[Tuple[int, int, int]]], List[str]]:
    """Plan a corridor centerline per bus group. Returns (corridors,
    demoted_group_names): corridors is {group.name: dense (gx, gy, layer)
    path}; demoted lists groups whose centerline needs more than the
    allowed layer changes even at the laminar probe price -- the caller
    must strip their bus treatment (members route as plain nets). Groups
    whose every probe rung fails are in neither (callers fall back to
    neighbor attraction)."""
    # Deferred import: single_ended_routing must not import this module.
    from single_ended_routing import route_net_with_obstacles
    from net_queries import calculate_route_length

    corridors: Dict[str, List[Tuple[int, int, int]]] = {}
    demoted: List[str] = []
    if not bus_groups:
        return corridors, demoted

    all_member_ids = [nid for g in bus_groups for nid in g.net_ids]
    room_mm = config.track_width + config.clearance
    probe_map = build_base_obstacle_map(
        pcb_data, config, all_member_ids,
        net_clearances=config.net_clearances)

    print(f"\n=== Bus corridor planning: {len(bus_groups)} group(s), "
          f"room unit {room_mm:.3f}mm ===")
    for g in bus_groups:
        rep = get_bus_routing_order(g)[0]
        rep_name = pcb_data.nets[rep].name if rep in pcb_data.nets else str(rep)
        k_max = min(MAX_RUNG, max(1, (len(g.net_ids)) // 2))
        # The probe map leaves every member out so that their stubs do not
        # veto the corridor, but their PADS stay where they are: a probe that
        # runs its terminal across a sibling's pin is refused by the terminal
        # graze gate (which measures against all foreign copper), so every rung
        # fails at a fine-pitch row a plain member route leaves cleanly.
        group_map = probe_map.clone_fresh()
        for _sib in all_member_ids:
            if _sib != rep:
                add_net_pads_as_obstacles(group_map, pcb_data, _sib, config)
        best = None      # (score, k, length, result, dense_path)
        probes = {}      # rung -> (result, length) of a full-length probe

        def _cfg(k):
            # Probe via the wide-power mechanism: a track k sibling-rooms
            # wider per side keeps that much margin from every obstacle on
            # the shared map. Neck-down is disabled so the rung fails
            # honestly instead of silently degrading to rung 0.
            # LAMINAR probe: the corridor centerline is the reference every
            # member is attracted to -- if the probe itself wanders layers,
            # "same-layer attraction" chases a different layer every span
            # and no river can form (observed: SDC0's corridor spanned all
            # four layers at the old 4x). The probe pays a much stiffer
            # layer-change price than member routing, so the skeleton stays
            # on one layer unless a change is genuinely unavoidable.
            via_mult = env_knobs.BUS_CORRIDOR_PROBE_VIA_MULT
            return replace(
                config, power_tap_neckdown=False,
                via_cost=int(round(config.via_cost * via_mult)),
                power_net_widths={**config.power_net_widths,
                                  rep: config.track_width + 2 * k * room_mm})

        def _plain(k):
            if k in probes:
                return probes[k]
            result = route_net_with_obstacles(
                pcb_data, rep, _cfg(k), group_map,
                reverse_direction=(g.clique_endpoint == "target"))
            if not result or result.get('failed') or not result.get('path'):
                probes[k] = None
            else:
                probes[k] = (result, calculate_route_length(
                    result['new_segments'], result.get('new_vias', []),
                    pcb_data))
            return probes[k]

        for k in range(k_max, -1, -1):
            found = _plain(k)
            dense = None
            if found is None and k > 0:
                # Fork: the wide rung cannot leave the terminals (a fine-pitch
                # row). Measure its room only past a setback from them.
                base = _plain(0)
                for sb in (CORRIDOR_SETBACKS_MM if base else ()):
                    sp = _setback_probe(pcb_data, rep, _cfg(k), group_map,
                                        base[0]['path'], sb, config.grid_step)
                    if sp is None:
                        continue
                    result, sdense, extra = sp
                    slen = calculate_route_length(
                        result['new_segments'], result.get('new_vias', []),
                        pcb_data) + extra
                    if verbose:
                        print(f"  {g.name}: rung {k} past a {sb:.1f}mm "
                              f"setback: {slen:.1f}mm")
                    # The shortest setback that routes wins; a longer
                    # setback only replaces it by being shorter.
                    if found is None or slen < found[1]:
                        found, dense = (result, slen), sdense
            if found is None:
                if verbose:
                    print(f"  {g.name}: rung {k} (+{k * room_mm:.2f}mm "
                          f"clearance) no route")
                continue
            result, length = found
            score = length + (k_max - k) * room_mm * ROOM_WEIGHT
            if verbose:
                print(f"  {g.name}: rung {k} routes, length {length:.1f}mm, "
                      f"score {score:.1f}")
            if best is None or score < best[0]:
                best = (score, k, length, result, dense)
        if best is None:
            print(f"  {g.name}: no corridor at any rung -- falling back to "
                  f"neighbor attraction")
            continue
        _score, k, length, result, _dense = best
        # Demotion rule: a bus whose CENTERLINE still needs more than
        # KICAD_BUS_MAX_CORRIDOR_LAYER_CHANGES (default 1) layer changes at
        # the stiff probe price has no laminar lane to offer -- routing it
        # "as a bus" would just attract members to a wandering skeleton.
        # Such a group is DEMOTED: no corridor, and the caller strips its
        # bus treatment entirely (members route as plain nets).
        # Count MID-PATH layer changes only: a transition within ~3mm of
        # either endpoint is the river's on-ramp (the dogbone dive from a
        # surface stub into the lane and back out -- the human's exact PCM
        # topology), not wander. Only changes in the middle demote. The
        # path is simplified waypoints, so measure geometric distance.
        import math as _math
        _path = _dense if _dense is not None else result['path']
        _cum = [0.0]
        for i in range(1, len(_path)):
            _cum.append(_cum[-1] + _math.hypot(
                _path[i][0] - _path[i - 1][0], _path[i][1] - _path[i - 1][1]))
        _total = _cum[-1] or 1.0
        _ramp = 3.0 / config.grid_step
        _changes = sum(
            1 for i in range(1, len(_path))
            if _path[i][2] != _path[i - 1][2]
            and _ramp < _cum[i] < _total - _ramp)
        _max_changes = env_knobs.BUS_MAX_CORRIDOR_LAYER_CHANGES
        if _changes > _max_changes:
            demoted.append(g.name)
            print(f"  {g.name}: corridor needs {_changes} layer change(s) "
                  f"(> {_max_changes}) even at the laminar probe price -- "
                  f"DEMOTED, members route as plain nets")
            continue
        corridors[g.name] = (_dense if _dense is not None
                             else _sample_dense(result['path'], step=1))
        lay = sorted({p[2] for p in result['path']})
        print(f"  {g.name}: corridor via {rep_name} at rung {k} "
              f"(room for {k} sibling(s)/side), {length:.1f}mm, "
              f"{_changes} layer change(s), layers {lay}, "
              f"{len(corridors[g.name])} pts")
    return corridors, demoted
