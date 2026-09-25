# A Pair Exchanges Its Sides at a Layer Change: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** a pair whose P and N sit on opposite sides at its two ends routes coupled, exchanging sides where it changes layer, instead of looping or falling back to single-ended.

**Architecture:** first the upstream mechanism the diagnosis found broken: the hybrid (coupled middle, single-ended legs that each drop a via and resolve the side swap at the pads) fails on USB_MCU only because its launch search walks the straight line between the terminals. Task 1 lets it search round each terminal. Only if the case still fails does Task 2 add the staggered-via crossover to the coupled route (the spec's geometry) as one more polarity candidate.

**Tech Stack:** Python in `py_router/` (`diff_pair_routing.py`); tests are scripts.

**Spec:** `docs/pair-via-crossover-design.md` (and the diagnosis, `docs/pair-polarity-crossover-design.md`)

## Global Constraints

- Local branch `feat/fanout-fixes`; no upstream issues, PRs or pushes.
- Tunables are settings (`routing_defaults.py`).
- Measured on: the module fan-out case's USB_MCU pair; the tracked boards with pairs; the router's diff-pair tests.
- Plain ASCII.

---

### Task 1: The hybrid's launch search looks round each terminal

**Files:** Modify `py_router/diff_pair_routing.py` (`_route_direct_coupled_middle._closest_launch`), `py_router/routing_defaults.py` (`HYBRID_LAUNCH_RADIUS`); Test `tests/test_hybrid_launch_search.py`, fixture `tests/fixtures/pair_crossover/usb_north.kicad_pcb` (the module fan-out case, only USB_MCU to route)

- [ ] Failing test: route_diff on the fixture, `--nets 'USB_MCU_*'`, F.Cu + B.Cu: the pair report says `outcome: coupled`; both launch points lie within `HYBRID_LAUNCH_RADIUS` of their own terminals (today both land beside R2/R3); KiCad's DRC finds no clearance violation.
- [ ] Implement: from each terminal, the nearest cell (breadth-first over open cells on the candidate layer, within the radius) whose pair-wide swath is clear, ties broken toward the other terminal; the straight-line walk stays the first try.
- [ ] Run the router's diff-pair and hybrid tests.
- [ ] Commit.

### Task 2 (only if Task 1 leaves USB_MCU uncoupled): the staggered-via crossover

**Files:** Modify `py_router/diff_pair_routing.py` (a `force_crossover` candidate beside the pad swap and the flips; the geometry at the first layer change); Test `tests/test_pair_via_crossover.py`

- [ ] Failing test: a straight two-layer pair whose sides swap between its ends routes coupled with one crossover: two vias on one offset line at least the via-to-via distance apart, no P/N crossing on either layer, every clearance met.
- [ ] Implement the spec's geometry; the candidate joins the length comparison.
- [ ] Commit.

### Task 3: Measurement

- [ ] The module fan-out case through placemat's route step: USB_MCU coupled, nets open no more than 1.
- [ ] Tracked boards with pairs (lvds_converter_dualclk, lvds_converter_dualclk_gnd, qfn_diffpair_escape, qfn_csi_underpad_diff, watchy, tigard): pairs coupled equal or more, no new DRC violations.
- [ ] Spec status; commit.
