# Grid Alignment and Exact Escape Stubs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Status:** done; merged into feat/fanout-fixes (alignment on by default).

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

- [x] Failing test: the lab's bare QFN (built as text) moved by (0.05, 0.05) routes 80/80 on F.Cu at 0.2/0.2 with `--escalation off` and alignment on, the output's copper lands on the original board's coordinates, DRC clean at no margin; with `--no-align-grid` it fails pins.
- [x] Implement: when the offset is not (0, 0), write the translated input (and siblings) to a temp dir, route it to a temp output, translate the output back to the requested path, and carry the router's written project over.
- [x] Commit.

### Task 4: Exact escape stubs

**Files:** Create `py_router/exact_escape.py`; Modify `py_router/single_ended_routing.py` (`_route_with_via_unblock`, ahead of the rung search and the #189 fallback), `routing_defaults.py` (`EXACT_ESCAPE_REACH`, `EXACT_ESCAPE_ENDS`), `env_knobs.py` (`KICAD_EXACT_ESCAPE`); Test `tests/test_exact_escape.py`

**Interfaces:** Produces `exact_escapes(pcb_data, net_id, pad, config, coord, layer_names, is_open=None, start_cells=(), toward=None, reach=None, limit=None) -> list[((gx, gy, layer), list[Segment])]` (changed from the single-stub `find_exact_escape` first planned: the retry is offered several ends at once).

- [x] Failing tests on a board written as text with the module's gpio23/gpio24 geometry (pad row at 0.4 mm, the tilted 0402 on the supply pin between them with its serve trace and via-in-pad, the neighbouring pins' hand tracks): stubs are found, exactly clear, ending on their grid cells; routed, both nets connect, KiCad's DRC finds no clearance violation and every other net keeps its copper; a pad walled in on its layer: none.
- [x] Implement the search as the spec (the first leg's length solved exactly rather than sampled); offer the ends to one retry; commit the stub the route used.
- [x] Commit.

### Task 5: Measurement

Measured 2026-09-25 on feat/grid-align at 7e5c2a1d (feat/fanout-fixes merged in, so the two builds differ by the alignment alone).

- [x] Module case (placemat scratch `fo/case3`), `route_spread --perturb offset`, 8 runs: 2 failed nets in every run (V1V1, gpio18), the aligned run's. Without alignment: median 46.5 (2 to 56).
- [x] Module case, order spread, 8 runs: 2 failed in every run (V1V1, gpio18); gpio23 and gpio24 in 0 of 8. The fan-order build: 7 in every run, gpio24 in 8 of 8. Jitter spread: median 2.5 against 8.5. Not met in full: gpio18 fails in 8 of 8 order runs against 0 of 8 on the fan build, and gpio9 in 4 of 8 jitter runs against 1. gpio18 fails at its sink (29 of 32 frontier cells at the target, boxed by gpio14 and gpio27), the case's ring of sinks, not at its escape.
- [x] Bare QFN, escape lab: 80/80 at 0.2/0.2, 0.15/0.15 and 0.1/0.1, one and two layers, no vias (the fan-order build the same). Cap sweep: 19 and 11 failed pins, as the dev build (fan-order build 21 and 16).
- [ ] Tracked-board A/B against dev (14 boards, haasoscope left out for time): no new DRC violations; rp2350 5 failed nets against 8, esp_prog 0 against 1, time within 20% (tigard +14%; the small boards gain about 1 s for the alignment step). Not met: tigard leaves /BD4 and GND disconnected in 8 of 8 jitter runs with alignment, 0 of 8 without. U3.43's first route fails in both builds (walled by the +3V3 track along the row); dev reconnects it in the rescue pass at a 0.025 mm grid and 0.0889 mm track, while in the aligned run a /BD2 track also runs there and the rescue finds no room. The same walled-pin class as the sweep's remaining failures.
- [x] Router tests touching routing, terminals, fallbacks, escapes, alignment and the CLI: 174 of 174 pass on the aligned build.
- [x] README note for the flag. Decided 2026-09-25: alignment on by default, merged into feat/fanout-fixes; the tigard pin joins the walled-pin failures.
