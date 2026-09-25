# A Pair Exchanges Its Sides at a Layer Change: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** a pair whose P and N sit on opposite sides at its two ends routes coupled, exchanging sides where it changes layer, instead of looping or falling back to single-ended.

**Status:** done (Task 1 2c1b0fac, 32d03387; Task 2 not needed).

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

- [x] Failing test: route_diff on the fixture, `--nets 'USB_MCU_*'`, F.Cu + B.Cu: the pair report says `outcome: coupled`; both launch points lie within `HYBRID_LAUNCH_RADIUS` of their own terminals (today both land beside R2/R3); KiCad's DRC finds no clearance violation.
- [x] Implement: from each terminal, the nearest cell (breadth-first over open cells on the candidate layer, within the radius) whose pair-wide swath is clear, ties broken toward the other terminal; the straight-line walk stays the first try.
- [x] Run the router's diff-pair and hybrid tests.
- [x] Commit.
- [x] Found on the way: the launch search alone left the legs unable to attach. The leg map stamped the partner's pads as capsules widened to short*sqrt(2) (`_pad_obstacle_segments`), which close the lane out of the pad beside a 0.4 mm pitch partner pad; the leg map now stamps them exact with corner guards (`obstacle_map.add_pads_track_keepout`, test `tests/test_partner_pad_exact.py`), the capsule kept as the fallback for a map without guards.
- Result: USB_MCU coupled, DRC clean, launches 2.0 mm and 2.3 mm from their terminals. The resistor-end N leg loops about 5 mm round the resistors on F.Cu rather than dropping under the P pad.

### Task 2 (only if Task 1 leaves USB_MCU uncoupled): the staggered-via crossover

**Files:** Modify `py_router/diff_pair_routing.py` (a `force_crossover` candidate beside the pad swap and the flips; the geometry at the first layer change); Test `tests/test_pair_via_crossover.py`

- [ ] Failing test: a straight two-layer pair whose sides swap between its ends routes coupled with one crossover: two vias on one offset line at least the via-to-via distance apart, no P/N crossing on either layer, every clearance met.
- [ ] Implement the spec's geometry; the candidate joins the length comparison.
- [ ] Commit.

### Task 3: Measurement

- [x] The module fan-out case through placemat's route step (32d03387): USB_MCU coupled (single-ended before), KiCad DRC clean. One run left 2 nets open (gpio18, gpio38) against 1 before; gpio38 fails at its own pin on the far face, boxed by neighbours from an earlier round. A jitter spread (8 runs each, the same router, only the pair copper differing) puts it in the noise: disconnected nets per run median 5.0 (4-8) with the coupled pair against 5.5 (4-10) before, three of them the excluded plane nets in every run; gpio38 fails in 2 of 8 against 1 of 8.
- [x] Tracked boards with pairs, route_diff on the board's copper layers, before (e5d08f7a) and after (2c1b0fac): pair outcomes and new DRC counts identical on all six. Their own pipeline tests (fanout then route_diff: watchy, tigard, qfn_csi_underpad_diff) pass.
- [x] Task 2 is not needed (USB_MCU routes coupled). What remains: the resistor-end N leg loops about 5 mm round the resistors on F.Cu rather than dropping under the P pad, which the leg's via cost (75, two vias against 5 mm) prefers. The placement fix is the pair-crossing weight (placemat 0.36: swap the two series resistors).
