# Grid Alignment and Exact Escape Stubs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** a fine-pitch part routes the same wherever it sits relative to the grid, and a pin whose only way out is an exact fit gets it.

**Architecture:** Part 1 wraps `route.py`'s CLI run: the input board's text is translated by a sub-grid offset that aligns its finest pin rows with the grid, routed, and the output translated back. Part 2 adds an exact octilinear stub search to the boxed-pin path in `single_ended_routing.py`, ahead of the existing fallbacks. Both Python only.

**Tech Stack:** Python in `py_router/`; placemat's `fixtures/route_spread.py` for spreads.

**Spec:** `docs/off-grid-exact-fit-design.md`

## Global Constraints

- Branch off `feat/row-fan-order` (reuses its `find_fan_rows`); local only, nothing pushed.
- Coordinates move by whole nanometres, so the translation back is exact.
- `--no-align-grid` restores today's behaviour; the GUI path (live pcbnew board) is left as it is.
- Tests are scripts; plain ASCII.

---

### Task 1: The aligning offset

**Files:** Create `py_router/grid_align.py`; Test `tests/test_grid_align.py`

**Interfaces:** Produces `aligning_offset(pcb_data, grid_step, max_pitch) -> (dx, dy)` in mm, each in [0, grid_step), rounded to 1 nm.

- [x] Failing tests: a QFN whose west/east rows' pad centre lines sit at y = k*0.4 + 0.05 gets dy = 0.05 and dx aligning its north/south rows; an aligned part gets (0, 0); two parts out of phase: the offset aligns the one with more row pins; no fine-pitch rows: (0, 0).
- [x] Implement: for each row from `find_fan_rows`, the residue of its pins' across-row coordinate modulo the grid (the lane line); pick per axis the residue class carrying the most pins; the offset moves that residue to 0.
- [x] Commit.

### Task 2: Translating a board's text

**Files:** Create `py_router/board_translate.py`; Test `tests/test_board_translate.py`

**Interfaces:** Produces `translate_board_text(text, dx, dy) -> str`.

- [x] Failing tests on tracked boards (`kicad_files/*.kicad_pcb`): translating by (dx, dy) then (-dx, -dy) parses to the same geometry as the original (every pad, segment, via, zone outline, edge shape equal to 1 nm); translating by (dx, dy) moves every parsed pad centre and track end by exactly (dx, dy); coordinates inside footprints (pad `at`, fp_* shapes) are untouched.
- [x] Implement: shift the coordinates of the board's top-level items only (footprint `at`; segment/arc `start`/`mid`/`end`; via `at`; zone `polygon` and `filled_polygon` `pts`; `gr_*` `start`/`end`/`mid`/`center`/`pts`; text and dimension points), numbers written back in KiCad's own style (up to 6 decimals, trailing zeros dropped).
- [x] Commit.

### Task 3: Aligned routing in route.py

**Files:** Modify `py_router/route.py` (CLI entry, around `batch_route`), argument parser (`--align-grid` default on, `--no-align-grid`), JSON summary (`grid_alignment: {dx, dy, rows}`); Test `tests/test_grid_align_route.py`

- [ ] Failing test: the lab's bare QFN (built as text) moved by (0.05, 0.05) routes 80/80 on F.Cu at 0.2/0.2 with `--escalation off` and alignment on, the output's copper lands on the original board's coordinates, DRC clean at no margin; with `--no-align-grid` it fails pins.
- [ ] Implement: when the offset is not (0, 0), write the translated input (and siblings) to a temp dir, route it to a temp output, translate the output back to the requested path, and carry the router's written project over.
- [ ] Commit.

### Task 4: Exact escape stubs

**Files:** Create `py_router/exact_escape.py`; Modify `py_router/single_ended_routing.py` (the boxed-probe path before the #189 fallback); Test `tests/test_exact_escape.py`

**Interfaces:** Produces `find_exact_escape(pcb_data, net_id, pad, config, coord) -> list[Segment] | None`.

- [ ] Failing tests on a board written as text with the module's gpio24 geometry (pad row at 0.4 mm, a tilted 0402 on the neighbouring supply pin with its serve trace and via-in-pad, gpio22's track): the stub is found, it is DRC clean at no margin, and a route from its end reaches a sink; a pad walled in on its layer: None.
- [ ] Implement the search as the spec: straight L1 along the row normal, optional 45 degree turn either side (L2), optional turn back; L1, L2 in 0.005 mm steps to 3 mm; exact distance tests against foreign pads (real copper), tracks and vias at the pair clearance with the 1e-6 mm tie; the end snapped to the grid by the last leg; shortest first, a turn toward the target first. Commit the stub as the net's copper and route from its end; otherwise fall through to the existing fallbacks.
- [ ] Commit.

### Task 5: Measurement

- [ ] Module case (placemat scratch `fan/module`), `route_spread --perturb offset`, 8 runs: failed nets equal in every run to the aligned run (Part 1).
- [ ] Module case, `route_spread` (order), 8 runs: gpio23 and gpio24 in 0 of 8 (Part 2); no other net's failures up by more than 1 of 8.
- [ ] Bare QFN 80/80; cap sweep failed pins no more than the fan-order build's.
- [ ] Tracked-board A/B against the fan-order build: no new DRC violations, connectivity equal or better, time within 20%.
- [ ] Router tests touching routing, terminals, fallbacks and the CLI, both builds.
- [ ] Spec status, README note for the flag; commit.
