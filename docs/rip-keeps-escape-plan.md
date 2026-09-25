# A Ripped Net Keeps Its Escape: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** a net ripped as a blocker keeps its escape out of a fine-pitch row, so its neighbours cannot take its only lane while it waits to be rerouted.

**Architecture:** `leg_rip.keep_row_escape` narrows the rip set that `select_blocking_branch` (#510) chose, removing the escape from it; the existing partial rip (`rip_up_net(only_segments=...)`) does the rest (removal, cache recompute, requeue, restore). The three blocker-rip call sites that already call `select_blocking_branch` call it after.

**Tech Stack:** Python in `py_router/`; tests are scripts; placemat's escape-lab cap sweep (scratch `fan/sweep2.py`) and the A/B loop for measurement.

**Spec:** `docs/rip-keeps-escape-design.md`

## Global Constraints

- Local branch `feat/fanout-fixes` only; nothing pushed, no upstream issues or PRs.
- Tunables are settings: `RIP_KEEP_ESCAPE_DEPTH_FACTOR` (2.0, times track + clearance) in `routing_defaults.py`; `KICAD_RIP_KEEP_ESCAPE` (on by default) in `env_knobs.py`.
- Plain ASCII.

---

### Task 1: The escape and the narrowed rip set

**Files:** Modify `py_router/leg_rip.py`, `py_router/routing_defaults.py`, `py_router/env_knobs.py`; Test `tests/test_rip_keeps_escape.py`

**Interfaces:** Produces `keep_row_escape(pcb_data, net_id, blocked_cells, config, only, routed_results) -> Optional[List[Segment]]`: the segments to rip (a list of objects in `pcb_data.segments`), or `only` unchanged when nothing is kept. May split one segment per escape in `pcb_data.segments` and in the net's result lists.

- [ ] Failing tests on a board written as text: five 0.2 x 0.665 mm pads at 0.4 mm pitch, 0.2/0.2, the middle pad's net routed straight out 3 mm then across. (a) With blocked cells far from the pad: the set returned is every segment but the first 0.8 mm past the pad's outer edge; the straight segment is split there, both pieces in `pcb_data.segments`, the inner one kept. (b) With blocked cells on that escape: `only` comes back unchanged. (c) A net with no pad on a fine-pitch row: unchanged. (d) `KICAD_RIP_KEEP_ESCAPE=0`: unchanged.
- [ ] Implement: rows via `fan_order.find_fan_rows`; the escape walked from the segment with an end in the pad's copper, following same-layer segments, stopping at a via or a branch; depth measured along the row's outward normal from the pad's outer edge; the escape's keep-out tested against the blocked cells as the obstacle stamp would (track/2 + clearance + track/2 from the segment).
- [ ] Commit.

### Task 2: At the blocker rips

**Files:** Modify `py_router/single_ended_loop.py`, `py_router/reroute_loop.py` (both sites), `py_router/phase3_routing.py` (both sites); Test `tests/test_rip_keeps_escape_route.py`

- [ ] Failing test: the cap-sweep case `cap-0402-diagonal-s0.4-g0.5`, F.Cu + B.Cu (the lab board written as text), routes 80/80 with the knob on; with `KICAD_RIP_KEEP_ESCAPE=0` it fails P17 (today's outcome), so the case shows the change.
- [ ] Implement: after each `select_blocking_branch` call, `_only = keep_row_escape(pcb_data, blocker.net_id, cells, config, _only, routed_results)`; where the net is a diff pair, leave it.
- [ ] Run the router's rip, restore, custody, multipoint, balance and fan-order tests.
- [ ] Commit.

### Task 3: Measurement

- [ ] Cap sweep (36 cases, both setups): failed pins at most half of 19 (F.Cu) and 11 (two layers); no case worse.
- [ ] Bare QFN 0.2/0.2: 80/80, both setups (`tests/test_fan_order_route.py`).
- [ ] Module fan-out case through placemat's route step: nets open no more than 1.
- [ ] The A/B loop's next pass on the commit: no new DRC violations, connectivity equal or better.
- [ ] Spec status; commit.
