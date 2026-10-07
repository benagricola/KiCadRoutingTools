# Fork divergences

Base: upstream `origin/main` 364b4572 (2026-10-06), branch `placemat/upstream-2026-10b`; the fork's commits on it are
`git log 364b4572..placemat/upstream-2026-10b`.

Deliberate differences between this fork and upstream. Each is marked in the code with a `FORK DIVERGENCE` comment.

## Clearance floored at the board's min_clearance

- Upstream: routes the Default class and every net class at its own clearance, and declines `min_clearance` as a
  floor (list_nets.py:91-94, :729-736). KiCad grades every clearance as max(rule, min_clearance)
  (design_rules.py:24), so a board whose class sits below `min_clearance` routes at a clearance KiCad then flags.
- Fork: `list_nets.resolve_floored_clearances` raises the base clearance (after any `--clearance-ceiling`) and every
  per-net clearance, from classes or `--net-clearances`, to the board's `min_clearance`. A board with no minimum is
  unchanged. Applied in route.py and route_diff.py mains.
- Why: placemat writes the project KiCad grades by.
- Test: tests/test_fork_floors.py (`t_floored_clearance`).

## Necks floored at the board's min_track_width

- Upstream: `_neck_pair_partner_grazes` (diff_pair_routing.py) and `prune_grazing_segments` (pcb_modification.py)
  floor a neck at the bare fab tier (`_fab_track_floor`, 0.0889 mm on 4+ layers). The single-ended terminal neck
  already uses `config.track_floor` (single_ended_routing.py:960-962).
- Fork: both floor at `config.track_floor(net_id, layer, fab)`, which includes the board's `min_track_width` only
  when board rules are loaded and the escalation policy is not `fab` (`GridRouteConfig.rule_floors`,
  routing_config.py:370-406; the fab policy is the explicit request to go below the board's minimums, so the fork
  leaves it). `prune_grazing_segments` takes a `floor_of(net_id, layer)` argument; `run_post_route_cleanup` and
  repair_planes.py pass `config.track_floor`.
- Plane scripts: route_planes.py `_finalize_plane_copper` has no config. `plane_track_floor(pcb_data)`
  (pcb_modification.py) reads the board's `min_track_width` from `pcb_data.source_path`, 0 when there is no path, no
  rule, or the policy is `fab`. It raises `_neck_plane_segments`' `min_width` (upstream: the literal 0.1 mm) to
  `max(0.1, floor)` and is passed as `floor_of` to `cleanup_plane_taps_grazing`.
- Why: a neck under `min_track_width` is a DRC error on the board KiCad grades.
- Test: tests/test_fork_floors.py (`t_pair_neck_floor`, `t_plane_neck_floor`, `t_floor_of_threaded`).

## --connections: routing given pad pairs of a net

- Upstream: routes whole nets; no flag selects pad pairs or sets a width per layer per call.
- Fork: `--connections FILE` (py_router/connections.py, hooks in route.py marked `FORK DIVERGENCE
  (docs/connections.md)`), `pin_pair_path_length(..., return_path=True)` in net_queries.py, and the private nets'
  protection in protected_nets.py `protection_map`. Described in docs/connections.md.
- Why: placemat's routing phases route chosen connections of a net at their own widths.
- Test: tests/test_connections_unit.py, tests/test_connections_route.py.
