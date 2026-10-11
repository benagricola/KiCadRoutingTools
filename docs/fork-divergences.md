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
- The boundary attribution calls blocking_analysis.py
  `analyze_frontier_blocking` with `record_history=False` (a fork keyword,
  default True). With it False the call charges nothing to the #590 history
  field: neither the contest (`record_contested`) nor the failed-frontier
  charge (`record_blocked_frontier`), and the frontier duplicate guard
  (`last_frontier`) is left as it was.
- Flood semantics: track margins, corner guards, terminal exemptions, via
  rungs and forbidden destination layers follow rust_router/src/router.rs
  GridSearch's neighbour loop. Direction and path-local via restrictions
  are omitted, making reachability conservative: those omissions can miss
  a pocket but cannot create one. The flood runs on a clone of the map with
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
