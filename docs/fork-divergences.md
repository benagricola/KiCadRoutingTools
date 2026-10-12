# Fork divergences

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
