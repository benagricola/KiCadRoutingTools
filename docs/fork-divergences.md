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
  An end is `{ref, pad}` and, when two footprints share a reference, also `fp`, the footprint's KiCad uuid: it then
  matches only that footprint's pads, an `fp` naming no footprint is refused `unknown_fp`, one whose footprint has another reference `fp_ref_mismatch`, and records echo `fp`.
- Why: placemat's routing phases route chosen connections of a net at their own widths.
- Test: tests/test_connections_unit.py, tests/test_connections_route.py.

## Failure evidence as data

- Upstream: the facts about a failed net are printed and partly serialised in the summary's `blockers`, `boxed_in`,
  `fanout_dropped` and `sealed_by_snpc`; the static copper a failed search met is printed as strings only
  (`analyze_static_blockers`), and the failed search's iterations and frontier are not kept.
- Fork: a failed search is recorded as a `search_failed` net event when the call writes a summary
  (`GridRouteConfig.failure_evidence`, single_ended_loop.py); `static_blocker_records` (blocking_analysis.py) returns
  the static copper as records and `analyze_static_blockers` prints from them (its strings unchanged; the track loop
  keeps one record per net and layer). Evidence checks distance to the actual segment,
  avoiding attribution to the empty corners of a diagonal track's bounding box, and uses pairwise obstacle clearance. For the evidence (`net_id` given) a cell is tested at the failed net's own
  track width plus a cell's slack, and a `*.Cu` pad counts on every layer; upstream's tests, kept for the print,
  use a track bounding box grown by its own half-width only and compare pad layers by name, so they name neither a wide net's
  blocking tracks nor any through-hole pad; `failure_evidence.evidence_of` builds one record per failed net, written as
  the summary's `net_evidence` (route.py, merged in route_summary.py) and as each failed or `joined_narrow`
  connections record's `evidence`. Each marked `FORK DIVERGENCE`. Described in docs/connections.md, "Failure
  evidence".
- Tap edges: a failed multipoint tap edge keeps its per-direction iterations in its `failed_edge_blocking` entry
  (single_ended_routing.py `route_multipoint_taps`; upstream discards them), and phase3_routing.py records each failed
  edge's search as `search_failed` before the rip ladder (`_record_tap_searches`) and, when the net's tap edges are
  still failed after it, KRT's `boxed_in_static` verdict for the first failed edge whose search fits
  `static_boxin_hint` (`_record_tap_boxin`), as the single-ended path does. Upstream records neither for a tap edge.
- A per-net rescue that leaves the net in pieces (`rescue_succeeded` with `fully_connected: false`) does not end the
  failure: `failure_evidence._failure_epoch` keeps the search, blockers and verdicts recorded before it.
- Why: placemat's run loop reads why a connection failed as data, to choose what to move.
- Test: tests/test_failure_evidence.py, tests/test_connections_evidence.py.

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

## Plane repair for a caller that tracks

- Upstream: repair_planes.py taps every plane-net pad its own geometric test finds unjoined, then routes whatever is
  still split as a multipoint net (the guaranteed-join gate). It takes the net-class clearances only, with no
  per-net map on its command line. Its via map keeps a tap via's copper ring off foreign copper at the copper
  clearance, and nothing holds the via's hole at the board's copper-to-hole floor. A footprint's own copper (an
  antenna, a tab) stops blocking the nets of the pads it touches (`check_drc.graphic_own_pad_nets`), so a route
  may cross it to reach such a pad.
- Fork:
  - `plane_obstacle_builder.via_reach`: in the via map, foreign tracks and pads are kept off a new via by the
    larger of its ring at the clearance and its hole at the board's hole clearance (`resolve_hole_clearance`).
    This applies to every caller of `build_via_obstacle_map`, the in-run plane finalize included. The via-to-via
    disc stays at upstream's ring plus clearance, as in "Via hole floor" below.
  - `repair_planes.py --net-clearances JSON` takes a {net name: mm} map as route.py does, floored at the board's
    `min_clearance` (`named_clearances`).
  - `--pads JSON` lists the pads pad repair may tap, as `{ref, pad[, fp]}` connection ends (`named_pads`).
  - `--no-join-gate` leaves what is still split after the taps and region joins to the caller.
  - `--no-own-pad-lift` on repair_planes.py and route.py sets `check_drc.OWN_PAD_LIFT` False. A footprint's own
    copper then blocks every net, in the generators and the checker.
- Why: placemat joins a pour net's pads by via drops, then routes the groups still apart itself, one connection task
  each, so it needs to:
  - name the pads to tap;
  - keep the repair from tracking the whole net;
  - give the repair the capture's stated clearances.

  On watchy, a tap via's hole stood 0.25 mm from a track where the board asks 0.254 mm. A GND track also crossed
  AE1's netless antenna copper to reach AE1's GND pad, a short KiCad reports.
- Test: tests/test_fork_plane_repair.py.

## Via hole floor

- Upstream: the router's via keep-out (obstacle_map.py and obstacle_cache.py, for tracks and pads, base map and
  per-net caches alike) holds a new via's copper ring at the clearance from foreign copper. The board's
  copper-to-hole floor (`resolve_hole_clearance`) is applied only to NPTH walls (#1038, #505). Where that floor
  exceeds the clearance plus the via's annular ring, a routed via's hole lands inside it. On watchy, a 0.6/0.4 via
  at clearance 0.15 left 0.250 mm hole-to-track where the board asks 0.254 mm. Measured: the ring sat exactly at
  0.15, so the rule is missing; the grid did not cause it.
- Fork: `GridRouteConfig.via_hole_floor` is the board's floor, set in route.py, route_diff.py and repair_planes.py
  from `resolve_hole_clearance`. Every via keep-out against a foreign track or pad adds
  `GridRouteConfig.via_hole_raise(clearance)`, so the hole's edge is max(clearance, floor) from the copper's edge.
  This applies in the base map, the per-net caches and their removal twins, the plane via map, and its sync twin.
  The raise is exactly 0.0 when the floor is not above the clearance, so a board declaring nothing is unchanged to
  the bit. Via-to-via keep-outs are not changed, in either map: vias keep ring plus clearance and the hole-to-hole
  clearance between them, as upstream.
- Why: placemat judges each phase on KiCad's DRC, and KiCad grades hole_clearance.
- Test: tests/test_fork_plane_repair.py (`test_a_routed_via_keeps_its_hole_off_a_foreign_track...`,
  `test_via_hole_raise_is_exactly_nothing...`, `test_a_board_declaring_no_hole_floor_gets_the_same_route_map`);
  tests/test_plane_via_map_sync.py's hole floor runs, where the floor is above clearance plus ring and the plane via
  map's incremental removal must still equal a fresh rebuild.

## --connections "apart"

- Upstream: no --connections at all (see "--connections" above). Within the fork, a task whose ends the router's own
  connectivity model already finds joined was always answered `joined_before` (or `joined_narrow`) and not routed.
- Fork: a task may carry `"apart": true`. `judge_joined` still measures it (its ends' copper components group
  tasks that share copper) but leaves it open, `choose_groups` routes it, and
  `finish` answers it `routed` (the call routed and the ends end up joined) or `failed`, never `joined_before`.
  `read_file` refuses a non-boolean `apart` (`bad_task`). `connections.TASK_FIELDS` lists the fields, and
  krt_capabilities.py publishes them as `task_fields`.
- Why: placemat judges a pour's pads by KiCad's connectivity, with the zones refilled. The router's fill model can
  count a pour island as joining pads that KiCad leaves apart (a starved thermal, a cut fill), and then it skipped
  the very task placemat sent it for those pads.
- No pour credit for an apart group: when a group holds an apart task, `split_nets` builds its components from copper
  alone and moves the net's zones to the private net for the call. A foreign zone is no routing obstacle to KRT, so
  this removes the zones' credit without walling the route in. The router then sees the ends apart and must join
  them with copper; a pour's fill no longer counts as reaching the far end. A group with no apart task is split
  exactly as before.
- Routed only by copper: `finish` answers an apart task `routed` only when copper alone joins its ends. Otherwise it
  answers `failed`. When the router's model joined the ends through the pour, the task's `pour_only` is set and its
  evidence carries `scope: task` and `diagnosis: joined_by_pour_only`.
- After an improvement-gate revert: the records are written before the gate runs. When the gate ships the input board
  instead, the apart tasks answered `routed` are measured again on that shipped board and the summary is rewritten.
  Such a task becomes `failed`, with `diagnosis: reverted_by_improvement_gate`.
- Test: tests/test_connections_unit.py (`t_apart`, `t_apart_drops_pour_credit`, `t_apart_routed_only_by_copper`,
  `t_apart_published`).

## Diff-pair GND return vias

- Upstream: the pose router picks each return via's side, ahead of or behind the signal vias, by `is_via_blocked`
  on the diff-pair obstacle map (rust_router/src/pose_router.rs `gnd_via_sites`, `compute_gnd_via_directions`).
  That map holds foreign copper only, not the pair's own tracks. The pair must run straight for the via's along
  offset plus 2 grid cells after a layer change (`straight_after_via`), but the via's clearance disc reaches about
  0.6 mm further, and a pair that bends back within that reach is not checked. `_create_gnd_vias`
  (py_router/diff_pair_routing.py) then places the vias where the router said, unchecked. On esp-rust-board the
  USB pair turned back over both return vias of one layer change, and KiCad reported shorting_items GND/USB_D+ and
  GND/USB_D-. The same code is in upstream's origin/main 364b4572.
- Fork: `_create_gnd_vias` takes the pair's just-built segments and vias and the board. Each site must pass
  `net_rescue._via_site_clear`, the via-landing check upstream's other callers use: tracks and vias at each net
  pair's class clearance, pads by their copper, every drill at hole-to-hole. It does not check zones or the board
  edge. The pair's own tracks and vias are checked at full clearance, the same as any other net's. The
  router's side is tried first and then the other one, both vias together as upstream places them. Failing that,
  each via searches near its own two sites with add_gnd_vias.py's ring search (nearest ring first, 24 angles 15
  degrees apart): rings one grid step apart out to one via diameter, around the router's site and then the other
  side's. The candidates are not snapped to the grid as add_gnd_vias does, because this check is exact rather than
  per grid cell. The first clear candidate wins; a via with none is not placed (logged as "GND return via ... not
  placed"). Both callers pass the board: route_diff_pair_with_obstacles, and the meander rebuild in
  length_matching.apply_meanders_to_diff_pair. The meander rebuild leaves out the pair's pre-meander copper it
  replaces, matched by object or by net and coordinates; copper copied and then moved by a cleanup pass would stay
  in the view and could move or drop a return via. No test reaches the meander branch.
- Why: placemat judges each phase on KiCad's DRC. A return via that shorts the pair costs the pair, where a missing
  return via costs nothing KiCad grades.
- Test: tests/test_gnd_return_via_pair_copper.py.

## Copper graphics with a net conduct

- Upstream: a net-tagged copper graphic (`gr_line`, `gr_arc`, `gr_rect`, `gr_circle`, `gr_poly` and footprint shapes
  on a copper layer) parses as `Segment(graphic=True)`: an obstacle and DRC copper, never a join.
  `check_net_connectivity` keeps every graphic out of the join graph (#513 item 6, check_connected.py), on the premise
  that KiCad's connectivity never counts a graphic. `--connections` did not exist upstream; in the fork its
  `split_nets` moved copper that only a graphic joined to a task's end, and the graphic itself, onto the private
  obstacle net.
- Fork: `check_connected.conducts` counts a graphic that carries a net as copper of that net: its stroke segments
  and, for a filled shape, its interior bands (`area_fill`). A graphic with no net stays an obstacle only.
  `connections.split_nets` leaves every graphic on its net. The router still does not route to a graphic:
  `connectivity.terminal_segments` leaves graphics out of a net's terminals, free ends and stub length (upstream's
  `get_net_endpoints` and `get_multipoint_net_pads` take a free end of every band and stroke as a terminal, 60 of
  them on the board below), and the pads and tracks a graphic joins are grouped by the graph, which counts it. A
  `--connections` task's `min_width_mm` leaves out the graphics on its path, whose `width` is a stroke or a band's
  height.
- Why: KiCad 10 counts a PCB_SHAPE with a net as a connected item. Measured with pcbnew 10.0.6: a pad and a via
  joined only by a net-tagged line, an unfilled polygon's stroke or a filled polygon read connected
  (`GetConnectedItems`, `GetUnconnectedCount`); an unfilled rectangle whose stroke misses both does not. On a real
  board a cell joined five vias of its via field to a MOSFET's source pads with two filled B.Cu polygons on the net.
  A `--connections` call moved two of those vias and both polygons, stroke and interior, to the private net, which
  walled the task's end in. The interior bands alone did not hold a polygon together: neighbouring bands meet at
  exact tangency, which the graph does not credit, so one polygon read as several pieces. The conducting stroke
  meets every band at both ends and joins them.
- Replayed on that board (the four VBIKE tasks at 2.4651 mm on F.Cu and B.Cu): all four routed, 2.4651 mm on F.Cu.
- Test: tests/test_copper_graphic_net_conducts.py, tests/test_filled_copper_graphic_area.py (`7b`),
  tests/test_check_weird.py (art soft joint).
