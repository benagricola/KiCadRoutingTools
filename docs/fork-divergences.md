# Fork divergences

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
- Fork: both floor at `config.track_floor(net_id, layer, fab)`, which includes the board's `min_track_width`.
  `prune_grazing_segments` takes a `floor_of(net_id, layer)` argument; `run_post_route_cleanup` passes it. The plane
  cleanup caller (pcb_modification.py, `cleanup_plane_taps_grazing`) has no config in scope and keeps the fab floor.
- Why: a neck under `min_track_width` is a DRC error on the board KiCad grades.
- Test: tests/test_fork_floors.py (`t_pair_neck_floor`).
