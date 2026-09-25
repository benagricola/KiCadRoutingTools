# Corner move check: legal cells stay open, clipping moves are refused

Date: 2026-09-25
Status: proposal
Branch: fix/escape-at-min-pitch (local)

## The problem

A track's centreline must stay `track/2 + clearance` (the margin, 0.3 mm at
0.2/0.2) from foreign copper. The grid router blocks the CELLS whose centres
are nearer than that, and moves between open cells. Two cells can be legal
while the move between them is not: near a pad's corner the keep-out is a
circular arc, and a step between two points outside a circle can dip inside
it. For a 0.1 mm grid the dip is at most `m - sqrt(m^2 - L^2/4)`: 0.0085 mm for
a diagonal step (L = 0.141) and 0.0042 mm for an axis step (L = 0.1) at m =
0.3.

To keep those moves out, `pad_blocked_cells_array` widens a pad's keep-out
near its corners by a corner buffer of half a grid step (0.05 mm, six times
the worst dip), and for a rectangular pad starts the "corner" region half a
cell early, on the pad's straight sides. The buffer blocks legal cells:

- A 0.4 mm pitch pad row at its own 0.2/0.2 class leaves each pin a lane
  exactly 0.3 mm from both neighbours. The lane's first cells past the row
  (0.300, 0.3055 and 0.339 mm from the neighbours' copper) are all legal and
  all blocked, so no pin in the middle of the row can leave it.
- Measured on a bare 80-pin QFN, every pin netted to a sink outside it:
  8/80 route at 0.2/0.2; with the buffer off, 77/80, with no clearance
  violations (placemat escape lab, 2026-09-25).

A smaller buffer does not help: the smallest that rules out every dip
(`sqrt(m^2 + L^2/4) - m`, 0.0082 mm) still blocks the cells at 0.300 and 0.3055
mm. The legality belongs to the move, not the cell: a straight step along
the lane is legal, a diagonal step past the corner may not be.

Tracks already have no corner buffer (`_capsule_mask` is exact, boundary
cells open), so a diagonal move past a track's end can dip up to the same
0.0085 mm today; this is likely the "~8 um grid-quantization" class
`check_drc --clearance-margin` filters.

## The fix

Keep each pad's cells exact (no corner buffer), and give the Rust router the
geometry it needs to refuse a clipping move: **corner guards**.

A guard is a circle (centre, radius) in grid units, on one layer. A move is
refused when its segment passes nearer a guard's centre than its radius (less
the tie epsilon, so a move exactly at the rule stays legal, as a cell does).
For every shape the guards are placed so that:

- **no over-blocking**: every point within a guard's radius of its centre is
  within the margin of the pad's copper, so a refused move really is
  illegal;
- **no missed clip**: with both move endpoints on legal cells, the nearest
  approach of the move to the pad is at a pad vertex or on a corner arc,
  which a guard covers. (The distance between two segments is least at an
  endpoint of one of them: at the move's ends, which are legal, or at a pad
  edge's ends, which carry guards.)

Guards per pad shape, for margin m:

| shape | guards |
|---|---|
| rect | each corner, radius m |
| roundrect | each corner arc's centre, radius m + corner radius |
| circle | the centre, radius m + radius |
| oval | each end's centre, radius m + half the short side |
| rotated rect / roundrect | the same, rotated |
| custom polygon | each vertex, radius m |

A concave polygon vertex gets a guard too; every point within m of it is
within m of the pad, so it cannot over-block.

## Rust

`obstacle_map.rs`:

- `GridObstacleMap.corner_guards`: per layer, a map from cell to the guards
  whose disc meets that cell's square (the unit square round its centre),
  refcounted per guard like `blocked_cells` (the same guard added twice is
  removed twice). Every point of a one-step move, axis or diagonal, lies in
  the square of one of its two end cells, so those two cells hold every
  guard the move can meet.
- `add_corner_guards_batch(rows)` / `remove_corner_guards_batch(rows)`,
  rows `(gx, gy, r, layer)` as f64, the exact mirror of each other.
- a per-layer bitmap "some guard reaches this cell", written at refcount
  transitions as `blocked_bitmap` is, so a move far from any guard costs one
  bit test.
- `move_clips_corner(gx1, gy1, gx2, gy2, layer, extra) -> bool`: the guards
  held at the two end cells; true when the segment passes nearer a centre
  than `r + extra - tie`. `extra` is the move's track margin in grid units
  (`opts.track_margin`), so a wide track is guarded at its own width as
  `segment_blocked` does.
- `clone_fresh`, `clone` and the other copies carry the guards.
- Source/target cells do not exempt a guard: guards come only from foreign
  copper (a net's own pads are removed with its cache before it routes).

`router.rs`: in the 8-direction expansion, after `segment_blocked`, refuse
the move when `move_clips_corner` says so, reporting it to the sink as a
blocked cell (so the blocking analysis still names the pad).
`pose_router.rs`: the same check at its two expansion sites.

Crate 0.22.0 -> 0.23.0, with `/VERSION` and `metadata.json` aligned and the
README's version history; built from source with `build_router.py
--from-source`. No binaries are published from this branch.

## Python

- `pad_blocked_cells_array` gains a caller-chosen `corner_buffer` of 0 for
  track keep-outs where the map carries guards. The two callers that stamp
  pads for tracks, `_add_pad_obstacle` (base map) and
  `_collect_pad_obstacles` (the per-net cache), pass 0 and emit the pad's
  guards alongside its cells: the base map adds them directly; the cache
  keeps them on `NetObstacleData.corner_guards`, added and removed in
  `add_net_obstacles_from_cache` / `remove_net_obstacles_from_cache` in the
  same order as the cells.
- A Rust module without `add_corner_guards_batch` (an older binary) keeps the
  old buffer: guards are only a replacement where they exist.
- Unchanged: diff-pair keep-outs (`extra_clearance > 0`, buffer 0.75 of a
  cell for the sub-grid P/N offsets), via keep-outs (a via sits at a cell
  centre; no move), and track capsules (no buffer today; guarding their ends
  is the follow-up below).
- Copper laid by testing cells outside the A* expansion must not skip the
  guards. The known paths: terminal connectors (checked exactly by
  `_neck_terminal_grazes`), the octolinear smoother (checks exact geometry).
  The remaining `is_blocked` / `segment_blocked` callers in `py_router`
  (single_ended_routing 16, diff_pair_routing 10, route_planes 4, and five
  more files) are audited in the plan: each either tests a point (unchanged
  meaning) or lays a segment and gets the guard check.

## Verification

- Unit (Rust): `move_clips_corner` against a brute-force segment-to-pad
  distance on random pads, moves and margins: refused exactly when the true
  distance is under the margin, for moves between legal cells.
- Unit (Python): the guards of each pad shape over-block nothing and miss
  nothing, against the exact pad distance, on a dense sample.
- Regression: the router's own suite (`tests/run_all.py`), and an A/B on the
  tracked boards (`kicad_files`) routed before and after: `check_drc` at the
  routed clearance with no margin, `check_connected`, closure. Expected: no
  new clearance violations, the sub-10 um grazes gone, closure equal or
  better.
- The escape case: the bare 80-pin QFN at 0.2/0.2, both layer setups, from
  8/80 to about 77/80 with a clean DRC.

## Follow-ups, not in this change

- Guards at track ends and vias, which would remove the existing sub-10 um
  dips past track ends and let `--clearance-margin` go.
- The three pins still open at 0.2/0.2 with the buffer off, and the net
  ordering that makes fan-outs block each other (the lab's next finding).
