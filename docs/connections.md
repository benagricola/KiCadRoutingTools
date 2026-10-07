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
 "min_width_mm": {"F.Cu": 0.5, "B.Cu": 0.3}, "path": null}
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

The early return taken when there is nothing to route writes the same key.

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
  dropped.
- A stated group skips detection and the geometric filter (bus_detection.py `stated_bus_groups`). Its members are
  ordered by position and it is named `stated_<n>`, `n` being the index of its use of the flag. A group with fewer
  than two routable nets in the call is dropped. The nets of a stated group are left out of detection.
- Corridor planning and demotion (bus_corridor.py `plan_bus_corridors`) apply to stated groups as to detected ones.

`--json-out` gains `bus_groups` on any `--bus` run, in route order:

```json
[{"name": "stated_0", "nets": ["SDA", "SCL"], "origin": "stated", "demoted": false}]
```

`origin` is `stated` or `detected`; `demoted` is true for a group that lost bus treatment because its corridor needed
too many layer changes. `nets` is in the group's physical order.
