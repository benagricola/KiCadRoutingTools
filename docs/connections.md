# --connections: routing given pad pairs of a net

A fork feature for placemat (docs/fork-divergences.md). `route.py IN OUT --connections FILE [--json-out SUMMARY]`
routes only the named pad pairs of a net, each at its own width per layer, and leaves the net's other pads alone.

## File

A JSON list of tasks:

```json
[{"net": "PWR",
  "from": {"ref": "J1", "pad": "1"},
  "to": {"ref": "U3", "pad": "4"},
  "widths": {"F.Cu": 0.5, "B.Cu": 0.3}}]
```

- An end is every pad of that footprint with that number on the net (a number may repeat in a footprint).
- `widths` names every layer the call routes on (`--layers`) and no other; a task that misses one or adds one is
  refused.
- A file that is not a list, or a task with a missing or wrongly typed field, is refused before the board is read
  (exit 2, naming the task index).
- `--connections` sets the call's nets to the task nets. It refuses `--nets`, positional net patterns, `--component`,
  `--group`, `--undo`, `--power-nets` and `--power-nets-widths` alongside (exit 2). A task on a net absent from the
  board is refused `pad_not_on_net`; a call whose nets are all absent still exits 0 and writes its records.

## What a call does

1. Each task is resolved and judged on the input board.
2. Per net, the first group of open tasks in file order whose ends are joined through shared pads or copper and
   which share one widths map is routed. Every other open task of that net is `deferred`: KRT holds one width map and
   one connected terminal set per net per call (routing_config.py `get_net_track_width`).
3. For this call only, each named net is cut down to the pads of the routed group's ends and the copper already
   joined to them. Its other pads and copper move to a private net (`__connections_private_<id>`) that is an
   obstacle at the net's class clearance and is never ripped (protected_nets.py `protection_map`, as locked copper).
   Same-net pads of an end's footprint that are not ends are obstacles too (D4). A named net with nothing to route
   moves whole, so the call does not touch it; that includes a net whose every task is refused. The writer copies the input text and appends only new copper, so the
   private net never reaches the output board or project.
4. The routed net's copper is laid at the group's widths, per layer (`config.net_layer_widths`). Neck-down rules
   still apply (`--no-power-tap-neckdown` turns them off), so a routed task can ship narrower than asked; its record
   says so in `min_width_mm`.
5. Reconcile sub-runs re-enter with the same file. One that re-reads the written board repeats steps 1-3 on it; one
   handed this run's board in memory (the GUI front) keeps its split and the widths recorded on it.
6. Known gap: the plane-finalize oracle's forced links (off by default) are chosen per whole net in a reconcile
   sub-run, so with the oracle on, a call could lay copper on a net whose only open task reads `deferred`.

## Records

`--json-out` gains `connections`, one record per task in file order:

```json
{"net": "PWR", "from": {"ref": "J1", "pad": "1"}, "to": {"ref": "U3", "pad": "4"},
 "status": "routed", "reason": null, "joined": true, "length_mm": 22.0,
 "min_width_mm": {"F.Cu": 0.5, "B.Cu": 0.3}, "path": null,
 "widths": {"F.Cu": 0.5, "B.Cu": 0.3}, "layers": ["F.Cu", "B.Cu"], "evidence": null}
```

`joined`, `length_mm` and `min_width_mm` are measured on the board the call wrote: the shortest track path between
the two ends (net_queries.py `pin_pair_path_length`) and its narrowest width per layer. A join only through a pour
has no track path: `joined` is true, `length_mm` null and `min_width_mm` empty.

| status | meaning |
|---|---|
| `routed` | in the routed group, joined after the call |
| `failed` | in the routed group, not joined after the call |
| `joined_before` | joined before the call by copper at least its width on every layer; not routed |
| `joined_narrow` | joined before the call by copper narrower than `widths` on some layer; not routed (below) |
| `deferred` | another group of the same net was routed in this call; route it again in another call |
| `refused` | not routed; `reason` says why |

`reason` is null except for `refused`: `unknown_ref`, `unknown_pad`, `pad_not_on_net` (also a net absent from the
board), `layer_not_routed` (a `widths` layer the call does not route), `layer_width_missing` (a layer the call routes
that `widths` leaves out), `width_under_board_minimum` (a width under the board's `min_track_width`).

`path` is null except for `joined_narrow`, where it is the joining path's segments:
`[{"layer": "F.Cu", "start": [x, y], "end": [x, y], "width": mm}, ...]`, in the board's mm.

`widths` is the task's widths as asked and `layers` the layers the call routed, on every record. `evidence` is null
except for `failed` and `joined_narrow` (below, "Failure evidence").

The early return taken when there is nothing to route writes the same key; a task left `failed` there has the
unknown evidence record (no search, no blockers).

## Failure evidence

A `failed` or `joined_narrow` record's `evidence` holds what the router recorded when it failed, as data
(py_router/failure_evidence.py). It reports facts KRT has at hand; it does not name a cause KRT did not record.

```
{"scope": "net" | "task",
 "search": {"forward":  {"iterations": int | null, "frontier_cells": int | null},
            "backward": {...}} | null,
 "blocked_by": [{"found_by": "frontier" | "static" | "preexisting",
                 "kind": "routed_copper" | "pad" | "track" | "copper",
                 "net": str, "ref": str | null, "pad": str | null, "layer": str | null, "at": [x, y] | null,
                 "cells": int | null, "seen_from": "forward" | "backward" | null,
                 "near_source_cells": int | null, "near_target_cells": int | null}],
 "verdicts": [{"verdict": "boxed_in_static" | "sealed_by_snpc" | "fanout_dropped", ...KRT's own fields}],
 "narrow": [{"layer", "start": [x, y], "end": [x, y], "width", "need"}],
 "diagnosis": "narrow_copper" | "boxed_in_static" | "sealed_by_snpc" | "fanout_dropped" | "unknown"}
```

- `scope`: `"net"` for a failed task. KRT routes one group per net per call, so the evidence is the net's routed
  group's and every failed task of that group carries the same record. `"task"` for `joined_narrow`.
- `search`: the net's last recorded failed A* search (single_ended_loop.py,
  event `search_failed`), per direction: its iterations and blocked frontier
  cell count (`iterations_forward/backward`, `blocked_cells_forward/backward`).
  It has no start point: each direction searches from a set of source
  cells to a set of target cells and reports no single start.
  Search, verdict and blocker events are limited to the current recorded
  failure epoch: after the latest successful route and from the latest
  recorded failed search. Null when no failed search is on record.
- `blocked_by`, in this order:
  - `frontier`, `routed_copper`: copper this run routed that the frontier met, per net, with its cell count and the
    cells near the source and the target (`analyze_frontier_blocking`, blocking_analysis.py:266; recorded last-wins
    as a `frontier_blocking` history event. The legacy `state.frontier_blocking`
    cache remains last-non-empty for its existing summary consumers; evidence
    does not use that cache because it may describe an earlier failure;
  - `static`: the static copper the failed search's frontier cells fall on, per direction (`seen_from`): a pad of
    another net by part `ref`, `pad` number and centre, or a net's earlier tracks per `layer`, `at` the first hit
    segment's midpoint, `cells` the frontier cells it accounts for (`static_blocker_records`, blocking_analysis.py,
    which `analyze_static_blockers` now prints from). A cell counts against copper grown by the failed net's own
    track half-width on that layer plus the pairwise obstacle clearance, and one diagonal grid step and one cell more: a frontier cell
    is the neighbour the search was refused (rust_router/src/router.rs `route_with_frontier`), and the obstacle
    stamps round outward to whole cells. A through-hole pad counts on every layer (`expand_pad_layers`). A frontier
    cell refused by the board edge or a keep-out has no direct copper attribution. These grown-copper
    intersections identify candidate blockers; they do not prove which obstacle caused a refused step;
  - `preexisting`, `copper`: copper from an earlier run named by net only (`preexisting_blocker_hint`,
    routing_diagnostics.py:416; event `preexisting_blockers`).

  Copper of the task's own net outside its ends sits on the call's private net (step 3); a task's record names it
  by the net (the summary's `net_evidence` keeps the private name).
- `verdicts`: KRT's own verdicts recorded for the net, each with its fields as KRT records them: `boxed_in_static`
  (the search exhausted under 20000 iterations with nothing rippable, routing_diagnostics.py:784-880),
  `sealed_by_snpc` (`--same-net-pad-clearance` closed the last via site, :627-780), `fanout_dropped` (a pad the
  fanout never escaped, :562-625).
- `narrow`: for `joined_narrow`, the joining path's segments under their layer's asked width, with that width as
  `need`; otherwise empty.
- `diagnosis`: `narrow_copper` for `joined_narrow`; the verdict's name when exactly one verdict was recorded; else
  `unknown`. `unknown` is a valid answer: when a search fails KRT cannot tell an end it could not leave from a
  corridor it could not cross or a via it could not place.

The search on record is at the asked widths. KRT's terminal geometry escalation (net_rescue.py
`terminal_geometry_escalation`) and per-net rescue (`rescue_failed_nets`) retry a failed net narrower. When one
routes it, the task reads `routed` and its `min_width_mm` is under its `widths` (a 1.0 mm task through 0.84 mm gaps
was routed at 0.418 mm). When none does, their tries are not in the evidence; the summary's `terminal_escalations`
names their outcome per net.

The failed search is recorded only when the call writes a summary (`--json-out`; `GridRouteConfig.failure_evidence`,
set for the call and its reconcile sub-runs), since finding the static copper costs time on every failed search.

A multipoint net (a group whose ends span more than two pads) fails in one of two places. Its main edge
(single_ended_routing.py `route_multipoint_main`) fails through the same branch as a two-pad net, so its `search` is
recorded, with `at: null` because actual search starts are not recorded. A tap edge
(`route_multipoint_taps`) discards its per-direction iteration counts (single_ended_routing.py:5026-5031) and records
no search: such a failure has `search: null`, with whatever `frontier_blocking` (the phase 3 rip-up's,
phase3_routing.py:944) and the verdict events hold.

The summary gains `net_evidence`, `{net name: evidence}` for every net still failed at the end of the run (the same
population as `blockers`), in whole-net calls too, with `scope: "net"`. Merged across reconcile
passes, each net's newest record is kept while the net is still failing.

## Joined by narrower copper (D3)

A task whose ends already share copper narrower than asked is reported `joined_narrow`, with `joined` true, its
narrowest width per layer and the joining `path`. It is not routed. placemat counts it joined and its phase width
judgement raises the narrow path.

Routing it would need the narrow copper to be passable for its own net without being one of the net's terminals. KRT
has no single place that decides which copper is the net's own:

- the base obstacle map leaves out the copper of every net being routed (obstacle_map.py:266, :402, :437);
- each route lifts its own net's cached obstacles from the working map (routing_context.py:419-421, :518-520), and
  the caches are built per net id (obstacle_cache.py:756, :803);
- post-route checks treat copper of any other net id as foreign (pcb_modification.py:1181-1189 `_connector_clear`).

Moving the narrow copper to a second private net would make new copper on top of it read as a short at each of these
places; keeping it on the net makes the ends read as already joined (routing_common.py `filter_already_routed`).

## Whole-net keys

The existing summary keys still describe whole nets. The final re-grade reads the written board, where the net's other
pads are untouched by design, so a connections call reports its net under `failed_multipoint` or `open_single` even
when every task routed. A reader of a connections call takes `connections`.

# --bus-nets: a stated bus

`route.py ... --bus-nets NET [NET ...]` routes the named nets as one bus group, as given. The flag repeats, one
group per use, and implies `--bus`.

- Each name is an include pattern read the way `--nets` reads it (net_queries.py `expand_net_patterns`): `\!NAME` is
  the active-low net `!NAME`, `[[]` is a literal `[`, `*` and `?` are wildcards. A name that matches no net is
  dropped; a bare `!NAME` that is not a net is an exclusion, as in `--nets` (placemat sends `\!NAME`).
- A stated group skips detection and the geometric filter (bus_detection.py `stated_bus_groups`). Its members are
  ordered by position and it is named `stated_<n>`, `n` being the index of its use of the flag. A group with fewer
  than two routable nets in the call is dropped. A net named by several groups belongs to the first that names it. The nets of a stated group are left out of detection.
- Corridor planning and demotion (bus_corridor.py `plan_bus_corridors`) apply to stated groups as to detected ones.

`--json-out` gains `bus_groups` on any `--bus` run, in route order. A run that exits early (nothing to route, all
connected) writes no `bus_groups`; absent means no groups.

```json
[{"name": "stated_0", "nets": ["SDA", "SCL"], "origin": "stated", "demoted": false}]
```

`origin` is `stated` or `detected`; `demoted` is true for a group that lost bus treatment because its corridor needed
too many layer changes. `nets` is in the group's physical order.
