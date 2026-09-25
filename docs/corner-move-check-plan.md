# Corner Move Check Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** a pad's keep-out cells are exact, and the grid router refuses a move whose segment clips a foreign pad's corner, so a straight escape lane at exactly the class clearance is open.

**Architecture:** Python stamps pad cells with no corner buffer and emits corner guards (circles in grid units, per layer); the Rust `GridObstacleMap` stores them refcounted and bucketed by cell, and the A* expansion in `router.rs` and `pose_router.rs` refuses a move that passes inside one.

**Tech Stack:** Rust (pyo3, numpy) in `rust_router/`, Python in `py_router/`, KiCad 10 for DRC.

**Spec:** `docs/corner-move-check-design.md`

## Global Constraints

- Local branch `fix/escape-at-min-pitch` only: nothing pushed, no issue or PR.
- Crate 0.22.0 -> 0.23.0; `/VERSION` and `metadata.json` aligned; README version history; built with `python3 build_router.py --from-source`.
- A Rust module without `add_corner_guards_batch` keeps today's behaviour (the half-cell buffer).
- Tie rule: a move exactly at the margin is legal (`GRID_TIE_EPS` = 1e-6 mm, as the capsule rasteriser).
- Tests run as scripts (`.venv/bin/python tests/<file>.py`), as the suite does.

---

### Task 1: Guards in the obstacle map (Rust)

**Files:**
- Modify: `rust_router/src/obstacle_map.rs`, `rust_router/Cargo.toml`, `/VERSION`, `metadata.json`, `rust_router/README.md`
- Test: `tests/test_corner_guards_map.py`

**Interfaces:**
- Produces: `GridObstacleMap.add_corner_guards_batch(rows: ndarray[N,4] f64)` and `remove_corner_guards_batch(rows)`, rows `(gx, gy, r, layer)` in grid units; `move_clips_corner(gx1, gy1, gx2, gy2, layer, extra) -> bool`; `corner_guard_count() -> int`; `clone`/`clone_fresh` carry guards; `__version__ == "0.23.0"`.

- [ ] Failing test: build a `GridObstacleMap(2)`, add random guards, and for random one-step moves (8 directions) compare `move_clips_corner` with a brute-force Python segment-to-circle distance (`< r + extra - tie`); add-then-remove leaves `corner_guard_count() == 0`; a guard added twice needs two removes; `clone_fresh()` answers the same.
- [ ] Implement: `corner_guards: Vec<FxHashMap<u64, Vec<(f64, f64, f64, u32)>>>` (per layer, cell -> guards with refcount), a `guard_bitmap: BlockedBitmap` set while a cell's list is non-empty; a guard is filed in every cell whose unit square its disc meets; `move_clips_corner` reads the two end cells' lists (bitmap first).
- [ ] Version bump, build from source, run the test.
- [ ] Commit.

### Task 2: The move check in the searches (Rust)

**Files:**
- Modify: `rust_router/src/router.rs` (8-direction expansion, after `segment_blocked`), `rust_router/src/pose_router.rs` (both expansion sites)
- Test: covered end to end in Task 4.

**Interfaces:**
- Consumes: `move_clips_corner` (Task 1), `self.opts.track_margin.at(layer)` as `extra`.

- [ ] Implement: `if obstacles.move_clips_corner(current.gx, current.gy, ngx, ngy, layer, margin) { sink.on_blocked(ngx, ngy, layer); continue; }` at each site (the pose router passes 0.0: it has no track margin).
- [ ] Build; the suite's quick routing tests still pass (no guards added yet, so no behaviour change).
- [ ] Commit.

### Task 3: Guards for a pad (Python)

**Files:**
- Modify: `py_router/routing_utils.py` (new `pad_corner_guards`)
- Test: `tests/test_pad_corner_guards.py`

**Interfaces:**
- Produces: `pad_corner_guards(pad, grid_step, margin) -> ndarray[N,3] f64` (gx, gy, r in grid units): four corner-arc centres (deduplicated) with radius `margin + corner_radius` for rect/roundrect/circle/oval (corner radius as `_add_pad_obstacle` computes it), rotated by `pad.rect_rotation`; for a custom-polygon pad (`pad.polygons`), every vertex with radius `margin`.

- [ ] Failing tests, for rect, roundrect, circle, oval, rotated rect and a custom polygon: (a) no over-block - every sample point inside a guard is within `margin` of the pad's exact copper; (b) no miss - for random one-step moves between two cells whose centres are at least `margin` from the pad, the move's segment is nearer than `margin - tie` to the pad exactly when it is inside some guard.
- [ ] Implement; tests pass.
- [ ] Commit.

### Task 4: Pads stamped exact, with guards

**Files:**
- Modify: `py_router/obstacle_map.py` (`_add_pad_obstacle`), `py_router/obstacle_cache.py` (`_collect_pad_obstacles`, `NetObstacleData`, `precompute_net_obstacles`, `add_net_obstacles_from_cache`, `remove_net_obstacles_from_cache`)
- Test: `tests/test_escape_at_min_pitch.py`

**Interfaces:**
- Consumes: Tasks 1-3.
- Produces: `NetObstacleData.corner_guards` (ndarray[N,4] or None).

- [ ] Failing test: a board written as text - a row of seven 0.665 x 0.2 mm pads at 0.4 mm pitch, each on its own net, each netted to a sink pad 6 mm out and spread to 1 mm pitch, class 0.2/0.2 in a sibling `.kicad_pro` - routed with `route.py --escalation off --layers F.Cu`; every net connects (`check_connected`) and `check_drc` at 0.2 with no margin reports no clearance violation. Today the middle pins fail.
- [ ] Implement: where the map supports guards (`hasattr(obstacles, 'add_corner_guards_batch')`, and for the cache a module-level probe) and `extra_clearance == 0`, stamp pad cells with `corner_buffer=0` and emit `pad_corner_guards` per layer group (radius from that group's margin); the base map adds them at once, the cache carries them and adds/removes them in the same order as the cells.
- [ ] Tests pass; commit.

### Task 5: Cell tests outside the A*

**Files:** `py_router` callers of `is_blocked` / `segment_blocked` (single_ended_routing 16, diff_pair_routing 10, route_planes 4, obstacle_cache 2, obstacle_map 2, add_gnd_vias, diff_pair_multipoint, layer_swap_fallback, plane_region_connector).

- [ ] For each call: record whether it tests a point (a via site, a tap cell: meaning unchanged) or accepts a straight segment between cells (needs `move_clips_corner` too). Fix each of the second kind, with a test where one exists to extend.
- [ ] Commit with the audit table in the message.

### Task 6: Verification and the escape case

- [ ] Baseline: a second worktree at `origin/main` built at 0.22.0.
- [ ] A/B on the tracked boards the suite routes quickly (`kicad_files/*.kicad_pcb` with a routing test), same commands both builds: `check_drc` at the routed clearance with `--clearance-margin 0`, `check_connected`, closure. Accept: no new clearance violations; closure equal or better; differences explained.
- [ ] The escape case: placemat's escape lab, bare 80-pin QFN at 0.2/0.2, both layer setups; accept at least 70/80 each with a clean DRC.
- [ ] The router suite's routing tests locally (the ones touching obstacle maps, fanout, escalation, terminal necking).
- [ ] Docs: the design's status; README version history; commit.
