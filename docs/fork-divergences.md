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
  Regions are ordered smallest first and then most boundary cells owned. The ladder's rip limits,
  protection checks and acceptance rules remain unchanged.
- Flood semantics: track margins, corner guards, terminal exemptions, via
  rungs and forbidden destination layers follow rust_router/src/router.rs
  GridSearch's neighbour loop. Direction and path-local via restrictions
  are omitted, making reachability conservative: those omissions can miss
  a pocket but cannot create one. The map is cloned and never mutated.
- Why: bounded rip attempts should open a trapped endpoint before spending
  their budget on unrelated copper.
- Test: tests/test_rip_pocket_walls_first.py.

The boundary attribution is advisory and incomplete: a corner-clipping refusal
records its destination cell rather than every neighbouring guard cell, and
blocked via rungs are not attributed to copper owners. Either can miss wall
nets. Open or unattributed regions use the existing frontier-ranked ladder.

## Isolated pocket repair candidate

Pocket priority is disabled for direct `batch_route` calls. The full CLI first
runs the legacy router from an isolated copy of the input board and its project
and rule sidecars. A reported complete legacy result is preserved exactly;
this shortcut is a routing scope report, not a manufacturing certificate.
Only an incomplete measured result permits one pocket-prioritized proposal
from the same original input, with identical routing flags and a frozen task file.
Both grades use the same requested net set plus the union of both summaries'
owned nets; the sorted scope and task identity are recorded with a SHA-256.
CLI option handling follows argparse, including unambiguous abbreviations and
attached short-option values. File-valued clearance overrides are frozen along
with connection tasks; their digests are recorded. Only the parent records the
original redo invocation; children never record ephemeral trial paths.

Both runs and independent final-file grading share a wall-clock deadline:
`KRT_ROUTE_BUDGET_S` defaults to 3600 seconds, and a caller's earlier absolute
UTC deadline in `KRT_ROUTE_DEADLINE_UTC` takes precedence. Timeout of a proposal
or grader retains the first result. There are at most two complete routing
runs; each retains the existing per-search and rip caps. The internal child
switches are `KRT_INTERNAL_ROUTE_CANDIDATE` and `KRT_INTERNAL_POCKET_WALLS`.
TERM, INT and supervisor exceptions kill and reap the current owned child
process group before propagation; temporary signal handlers are restored.
An interrupted supervisor does not publish a candidate. Callers must allow
TERM cleanup before resorting to an uncatchable KILL.

Adoption requires known final-file connectivity in the actual selected net or
pad-task scope, no physical DRC violations, and no requested-size violations.
This first policy requires zero physical violations, including inherited ones;
existing unrelated manufacturing faults may withhold an otherwise helpful
proposal. Nominal netclass track widths are draw preferences, not minimum requirements.
Explicit track, power and task widths are enforced separately. Final copper is
checked against frozen original project and rule files so output floor writeback
cannot weaken hard input minima. Missing project clearance uses a manufacturing
envelope frozen from the original invocation's `fab_floor_min` (tier and
overrides), never the candidate's project. The `off` escalation policy freezes
the original resolved clearance instead. This avoids the checker inventing
its unrelated 0.2 mm no-project default. Default source and values are recorded
in `manufacturing_defaults` before either candidate starts. The effective global
clearance is the maximum of that envelope and the original declared floor;
stricter original per-net classes still apply. Nondefault factory tiers or
overrides, explicit via-size requests, custom rule files and local pad
clearance overrides currently withhold adoption because their combined
manufacturing proof is incomplete. Original declared track, via, drill or
annular minima below the frozen factory envelope also withhold adoption; the
checker otherwise lets such declarations replace its size fallback. Explicit clearance overrides/maps/ceilings,
unsupported rules, and length/time obligations currently withhold adoption
until their independent constraint proof is implemented. Task endpoint joins and track path widths are remeasured.
A narrower path might be a permitted neck, and a poured join has no track-path
width proof: either makes width compliance unknown and withholds adoption.
Impedance obligations likewise withhold adoption until independently proved.
Only changed outside-scope nets whose connectivity worsens are charged.

A legal, width-proven proposal must reduce open obligations; equal incomplete
closure retains legacy. Complete ties compare vias, copper length, then
segments, with exact ties retaining legacy. The selected board, project/rule
sidecars and summary are staged together, board last, with rollback on a
publication failure. The selected summary retains its own failures and
attribution; `route_candidates` adds budget, grades and selection provenance.
`ROUTE_CANDIDATES` carries the same decision on stdout.

Quick routing (`KRT_ROUTE_QUICK`), preview, skip-routing and schematic-mutating
calls retain the legacy path and report fallback unavailable. The quick wrapper
can continue rewriting its existing top-level `batch_route` anchors unchanged.
Tests: test_route_candidates.py and test_rip_pocket_walls_first.py.
