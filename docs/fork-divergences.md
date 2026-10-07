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

## --bus-nets: a stated bus

- Upstream: `--bus` detects bus groups from clustered endpoints, drops groups the geometric filter does not accept
  (bus_detection.py `filter_bus_groups_geometric`), and reports none in the summary.
- Fork: `--bus-nets NET [NET ...]` (repeatable, implies `--bus`; route.py, `GridRouteConfig.stated_buses`,
  bus_detection.py `stated_bus_groups` / `resolve_stated_buses`, single_ended_loop.py, each marked `FORK DIVERGENCE
  (docs/connections.md)`). A stated group skips detection and the geometric filter; corridor planning and demotion
  stay. The summary gains `bus_groups`. Described in docs/connections.md.
- Why: placemat states every bus and interface it routes, so a group is never decided by detection (a two-net bus is
  dropped by it).
- Test: tests/test_bus_nets.py.

## Item uuids the same in every run

- Upstream: kicad_writer.py mints `uuid.uuid4()` for every segment, via, zone, keepout, graphic line and text it
  writes (check_drc.py's debug lines too). KiCad orders and tie-breaks on KIIDs: the order a loaded board hands out
  its tracks, which item a DRC marker names, overlapping zones' fill (upstream's own note at
  kicad_writer.py `zone_overlap_priorities`). So the same routed copper graded differently between runs. Seen on
  watchy (test (a), class widths): identical router copper, but placemat's close-via merge walks the vias in the
  order pcbnew hands them out, kept or merged a +3V3 via pair by that order, and clean closure read 61.2% or 84.3%.
- Fork: py_router/item_uuid.py. A writer emits `item_uuid.PLACEHOLDER` and passes its text to `item_uuid.stamp`,
  which puts in uuid5 of a seed, the item's text and how many items of that text the process has stamped before.
  `parse_kicad_pcb` seeds it from each board it reads: the board's lines with every uuid-shaped token (item uuids, a
  group's member list, legacy 8-hex tstamps) taken out, sorted, so the input's own ids and block order do not move
  it, and a later run on a board that already holds an item of the same text stamps a different uuid.
  `add_tracks_to_pcb` and `add_tracks_and_vias_to_pcb` seed from the board they write into, and
  `build_pcb_data_from_board` from the live board's tracks, vias and footprints. `stamp` before any seed raises.
  Five upstream tests that write items with no board (test_489_via_tenting, test_748_via_dialect_protection,
  test_net_name_escaping, test_soft_joint, test_zone_priority_determinism) seed one themselves. Upstream's docstrings at `zone_overlap_priorities` and `generate_zone_sexpr`
  still say "we mint a fresh uuid4"; left as upstream wrote them.
- Why: placemat's reference set compares one run with another; the router's output must be the same in every run.
- Test: tests/test_item_uuid_determinism.py.

## Dogbone guard measures foreign pads by their copper

- Upstream: the rescue's dogbone rung (net_rescue.py `rescue_failed_nets`, "bare-ball escape ... dogbone") keeps its
  via and segments with no check. `_via_site_clear`, used by upstream's #666 fanout-rescue escape, models a foreign
  pad by its size_x/size_y box centred on the anchor.
- Fork: the fork commit "immutable copper art is not rippable, and not escapable-through" guards the dogbone rung
  with `_leg_clear` / `_via_site_clear`. `_via_site_clear` takes `exact_pads` (default off, upstream callers
  unchanged); the dogbone guard passes it, and pads are then measured with `check_drc.point_to_pad_distance`
  (custom polygons, rounded shapes, rotation).
- Why: a custom pad's box can be much wider than its copper. On pic_programmer the box declined a DRC-legal dogbone
  beside JP1's chevron (0.943 mm by box, 1.112 mm by copper, 1.05 mm required). The gap route left without it is
  refused by upstream's terminal graze check (#1136 pair clearance), so /pic_sockets/VCC_PIC stayed open.
- Test: tests/test_rescue_escape_would_short_guard.py (`test_dogbone_via_judged_by_real_pad_copper`,
  `test_dogbone_rung_uses_exact_pads`).

## Rip ladder: pocket walls first

- Upstream: phase3_routing.py `try_phase3_ripup` ranks failed tap frontiers,
  then tries progressively larger sets of rippable nets. A larger failed
  frontier can outrank the copper enclosing a small endpoint pocket.
- Fork: pocket_walls.py floods each failed tap target on the obstacle map
  used by that search. A closed region within `max_probe_iterations` supplies
  its boundary nets before the existing ladder ranking only when no actual
  search source is reachable within it. Both endpoint sets use their search
  terminal exemptions; missing recorded sources declines pocket priority.
  Regions are ordered smallest first. Within a region its boundary nets keep
  the order the ladder's own ranking gave them (after the mincut step); nets
  the ranking did not name follow, most boundary cells first. The ladder's rip
  limits, protection checks and acceptance rules remain unchanged.
- A region's boundary nets are promoted only if the region opens without them:
  the flood is run again on a clone made as ripping its rippable boundary nets
  (diff pair partners included) would leave the map. For each such net the
  entry the map holds (state.net_obstacles_cache) is unstamped and the entry a
  rip recomputes is stamped: the board without the segments and vias of the
  net's routed result, so its pads, stubs and input copper stay, as
  rip_up_net leaves them (pocket_walls.py `_rip_trial`, phase3_routing.py
  `_rip_plan`, and the fork keyword `skip_object_ids` of obstacle_cache.py
  `precompute_net_obstacles`). A region that still closes keeps the ladder's
  own ranking. Measured on watchy (placemat reference board): EN's pad was
  sealed by +3V3's copper and its pads, the boundary named only BTN3, and
  ripping BTN3 first spent the rung that ripping +3V3 would have used to join
  the pad.
- Once a region is open, its boundary nets are not ripped further. After a
  failed retry each promoted region is flooded again from its recorded target
  and source cells, on the map the ladder rebuilt after its latest rip, with
  the own-pad lift and the same margins (pocket_walls.py
  `pocket_still_closed`; one lifted clone of that map serves every re-flood
  after a retry, promoted regions first). A region that no longer closes is
  open: its boundary nets not yet ripped are taken off the ladder, and the
  re-analysis does not bring them back (phase3_routing.py
  `_drop_opened_pocket_walls`), unless a net still blocks: it bounds any
  region (promoted or not) that still floods closed, or the per-edge
  attribution of a failed edge of the retry (the tighter probe side, as the
  ladder's first ranking attributes it) names it. Openness is judged by the
  flood, not by the retry's edges: the ladder judges a retry by its
  failed-edge count, which can stay put when a joined pad brings a new failed
  edge with it, and an edge may not be tried at all (its MST source did not
  join) or fail with an empty frontier and record no entry. Measured on
  watchy: ripping /32K_P joined +3V3's U4 pad 20, the joined pad's next edge
  failed, and the ladder ripped ACC_INT_1, the pocket's second wall; with the
  BGA's other escape net ripped too, the victims could not re-route and the
  tap was abandoned (open pairs 6 -> 9 at human widths). Judging "joined" by
  the retry's unconnected pads instead read a pad whose edge was never tried
  as still trapped and cost one pair at class widths.
- The boundary attribution calls blocking_analysis.py
  `analyze_frontier_blocking` with `record_history=False` (a fork keyword,
  default True). With it False the call charges nothing to the #590 history
  field: neither the contest (`record_contested`) nor the failed-frontier
  charge (`record_blocked_frontier`), and the frontier duplicate guard
  (`last_frontier`) is left as it was.
- Flood semantics: track margins, corner guards, terminal exemptions, via
  rungs and forbidden destination layers follow rust_router/src/router.rs
  GridSearch's neighbour loop. The margins are the narrowest the tap search
  may neck down to (pocket_walls.py `search_margins`, mirroring the gate in
  single_ended_routing.py `_route_main_connection`): a power-wide net floods
  at its layer width, an impedance-width net at the nominal width when
  KICAD_IMPEDANCE_NECKDOWN allows, otherwise the net's own width.
  Direction and path-local via restrictions are omitted, making
  reachability conservative: those omissions can miss a pocket but cannot
  create one. The flood runs on a clone of the map with
  the net's #908 own-pad lift applied, as the tap searches had it
  (single_ended_routing.py `route_multipoint_taps` releases the lift before
  the ladder runs); the caller's map is not mutated. A ladder entry whose
  failed edges recorded no target and source cells clones nothing. Pocket
  walls are ranked by canonical net id, so a wall naming one half of a diff
  pair sorts where the ranking put the pair.
- Why: bounded rip attempts should open a trapped endpoint before spending
  their budget on unrelated copper. Ordering a pocket's nets by boundary cells
  alone ripped a long net that only bounds a large pocket ahead of the
  ranking's first pick, which often opens the pad by itself (esp_prog in
  tests/test_703_predictor_regen.py, perturb-scatter-d1: 28 -> 32 vias).
- Test: tests/test_rip_pocket_walls_first.py.

The boundary attribution is advisory and incomplete: a corner-clipping refusal
records its destination cell rather than every neighbouring guard cell, and
blocked via rungs are not attributed to copper owners. Either can miss wall
nets. Open or unattributed regions use the existing frontier-ranked ladder.

## Nominal width policy

- Upstream: route.py `batch_route` resolves per-net and per-layer draw widths (net class, `.kicad_dru` opt, fab
  floor) inline, and route_diff.py resolves a pair's class width inline.
- Fork: both blocks are moved unchanged into py_router/nominal_width_policy.py (`class_width_inputs`,
  `pair_class_width`); route.py and route_diff.py call them (marked `FORK DIVERGENCE`). `nominal_policy` and the
  module's `__main__` (JSON on stdin, a `PLACEMAT_WIDTH_POLICY` line on stdout) answer which widths a call with given
  arguments would draw, without routing. An upstream change to either block must be carried into this module.
  The call's arguments are parsed by route.py's or route_diff.py's own argparse parser, taken by running the
  script's `__main__` up to its `parse_args()` (upstream builds the parser inline, with no function to call). A
  width the policy cannot answer has `status: unknown` and a `reason` record (`code` plus fields); a refused call
  raises `WidthPolicyRefusal` with a `code` and fields.
- Why: placemat asks KRT for the effective widths of the nets it routes rather than re-deriving KRT's precedence.
- Test: tests/test_nominal_width_policy.py.
