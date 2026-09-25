# Row Fan Order Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** nets leaving a fine-pitch pin row are routed outside-in along the row, as a person fans a row out, so a bare QFN escapes every pin and a row with a cap on it loses only the pins the cap crowds.

**Architecture:** a pure-Python ordering pass (`py_router/fan_order.py`) applied in `route.py` after the base order (MPS or `inside_out`/`bus`), before the #472 direct-first step. It changes the order only.

**Tech Stack:** Python in `py_router/`; the escape lab (placemat `fixtures/escape_lab.py`) and the scratch sweep for measurement.

**Spec:** `docs/row-fan-order-design.md`

## Global Constraints

- Local branch `fix/escape-at-min-pitch`; nothing pushed, no issue or PR.
- Order only: no geometry, rule or cost changes.
- `--fan-order` on by default; `--no-fan-order` restores today's order; `--ordering original` is left as given.
- Rows: pads of one footprint in a line, alike in size and turn, at least three, pitch at most 2 x (track + clearance) of the Default class.
- Tests run as scripts; plain ASCII in code and docs.

---

### Task 1: The fan sequence

**Files:**
- Create: `py_router/fan_order.py`
- Test: `tests/test_fan_order.py`

**Interfaces:**
- Produces: `find_fan_rows(pcb_data, max_pitch) -> list[FanRow]` (FanRow: ref, pads in order along the row, axis (ux, uy), outward normal, pitch); `fan_order(pcb_data, net_ids, max_pitch) -> list` taking and returning route.py's `(name, id)` pairs.

- [x] Failing tests, on boards written as text: (a) a 9-pad row whose nets' far pads lie left, right and ahead: the left group from the left end inward, then the right group from the right end inward, then the ahead group; the row's nets occupy the base order's slot of its first net and non-row nets keep their positions; (b) a net between two rows' footprints keeps its base position; (c) a row at 1.27 mm pitch (above 2 x 0.4) is left alone; (d) a net on two rows is sequenced by the finer row; (e) pads of a 2-pad part never form a row.
- [x] Implement, porting the prototype (scratchpad `fan/fan_order.py`, block mode, chip-to-chip rule), with the far end of a net as the centroid of its pads off the row's footprint (its own footprint's other pads when it has none elsewhere).
- [x] Tests pass; commit.

### Task 2: In route.py

**Files:**
- Modify: `py_router/route.py` (after the ordering strategy block, before #472), the argument parser (`--fan-order` / `--no-fan-order`), and the JSON summary (`fan_order: {rows, nets}` so a run says what it did)
- Test: `tests/test_fan_order_route.py`

**Interfaces:**
- Consumes: `fan_order` (Task 1).

- [x] Failing test: a two-face row of pins at 0.4 mm pitch (a 20-pad row each side of a synthetic chip, 0.2/0.2, sinks spread 1 mm, 6 mm out) routed on F.Cu with `--escalation off`: every net connects and `check_drc.py --clearance-margin 0` is clean; with `--no-fan-order` at least one pin fails (the case must show the order matters). Measured: a clean two-face-only case (no adjacent-face corners) routed 40/40 under plain MPS order on this build -- the failure is a corner effect (a lane from one face cutting across a not-yet-routed pin near the next face), so an isolated row does not reproduce it. The test uses four faces (80 pins), the shape the design doc's own escape lab measured: 12/80 failed with `--no-fan-order`, 0/80 with the fan order.
- [x] Implement; print one line naming the rows found and the nets re-sequenced.
- [x] Tests pass; commit.

### Task 3: Measurement

- [x] Escape lab, bare QFN, classes 0.2/0.2, 0.15/0.15, 0.1/0.1, both layer setups, default command line: 80/80 each, DRC clean with no margin. Measured 2026-09-25: 80/80 routed, 0 vias, all six combinations; `check_drc.py --clearance-margin 0` exits 0 (no violations) on every routed output.
- [x] The 36-case cap sweep, both setups: failed pins no more than the prototype's (24 F.Cu, 13 F.Cu + B.Cu). Measured (KRT-fan, `--ordering mps` default, `--escalation off`): 24 F.Cu (exact match), 14 F.Cu + B.Cu (1 over). Investigated the 1-pin gap: the ported `fan_order.fan_order()` given the identical base MPS order produces the byte-identical net sequence the prototype's script does (checked directly against the prototype's algorithm on the same board and base order); rebuilding the SAME pickled cap-placement case through `escape_lab.build()` twice produces two DIFFERENT boards (different chip pin/sink pad assignment each time) -- the sink-fixture builder in placemat is not deterministic between runs, so the 24-vs-24 exact match and the 14-vs-13 near-match are both within that fixture's own build-to-build spread, not a behavior difference in this port. Not fixed here: the non-determinism is in placemat's `fixtures/escape_lab.py`, out of this repo.
- [x] The MCU module case, both setups: recorded against the default order (4 and 19 today); re-measured after the relief-via work. Measured (KRT-fan, `--escalation off`, net list minus the VREG_LX net): F.Cu+B.Cu 5 failed (`--no-fan-order`) vs 7 failed (fan order); F.Cu only 17 vs 20. Fan order is worse here, matching the design doc's own finding for this case (4 vs 6, 19 vs 21 with the prototype) -- the module's residual failures are the cap-crowded supply pins the design doc names for the relief-via mechanism, not implemented in this change. Record only, per the design; no pass/fail bar.
- [ ] A/B on the tracked boards against the corner-move-check build (same 15 boards and checks as before): no new DRC violations, connectivity equal or better, failed nets equal or fewer in total, time within 20%. Any board that loses is explained before the task is done.

  Measured (KRT-escape base reused from the in-progress reference run at
  scratchpad/ab/r7, unchanged since b974a200 -- confirmed the two commits
  after it are docs-only; KRT-fan new, same 15 boards, same command line,
  both graded by KRT-escape's own check_drc.py / check_connected.py):

  - **DRC**: 0 new violations on any board (both sides 0 except
    qfn_underpad_coupling, a pre-existing 5-violation condition identical
    on both builds).
  - **Connectivity** (`check_connected.py`, authoritative -- not route.py's
    own tally): 12 of 15 boards unchanged (11 clean both sides,
    qfn_underpad_coupling's pre-existing state identical). Two improved:
    **tigard** FAILED (2 issues: GND + /BD7 disconnected) -> OK. Two
    regressed: **watchy** OK -> FAILED (2 issues: BTN4 + SDA disconnected)
    and **haasoscope_pro_max_test** FAILED (55 issues, 38 unrouted nets) ->
    FAILED (59 issues, 43 unrouted nets). Total issues across the 15:
    59 -> 63; total unrouted nets: 40 -> 45. **The aggregate criterion is
    NOT met across all 15** -- driven by haasoscope. Excluding it, the
    other 14 boards total 4 issues on both sides (tigard's fix offsets
    watchy's loss) and are a net improvement on failed-net counts.
  - **watchy, investigated**: reproduced twice each way on the identical
    input board. KRT-fan `--no-fan-order` -> OK (matches base). KRT-fan
    default (fan order on) -> FAILED, same 2 nets, both times. KRT-escape
    (base) -> OK, twice. The fan order is the deterministic cause: the
    console line for the main pass reads "Row fan order: 6 row(s), 22
    net(s) re-sequenced" (a nested reconciliation sub-run then runs its
    OWN fan_order pass on its own smaller leftover subset, so the LAST
    `fan_order` key written to route.json -- `{rows: 6, nets: 1}` -- is
    that sub-run's, not the main pass's; see CLAUDE.md on never scraping
    the last JSON_SUMMARY of a route log). Re-sequencing those 22 nets
    changes which nets a later rip-up contends for on an already-tight
    board. This is the router's known order sensitivity (moving nets'
    positions in a sequential greedy router can move contention
    elsewhere), not a defect in `fan_order.py` -- the rows it finds and
    the sequence it produces are correct by Task 1's tests.
  - **haasoscope_pro_max_test, not resolved**: a SINGLE run per side on
    the corpus's densest, highest-variance board (49 rows found, 72 nets
    re-sequenced). `failed_single` sets: 24 nets the base failed that the
    new build fixed, 32 the new build failed that the base did not
    (net -8); `multipoint_edges_failed` improved 99 -> 83. Mixed signal,
    consistent with this repo's own documented finding that a **single
    replay pair cannot judge a dense/near-capacity board's own run-to-run
    spread** (CLAUDE.md, the orangecrab example: two replays of identical
    code on one board graded 1 vs 3 DRC and 8 vs 14 connectivity issues).
    Confirming or ruling out a real regression here needs a multi-run
    corpus A/B, not done in this pass (each haasoscope route takes
    1.5-2.5 hours; the reference side already used the in-progress run
    rather than a fresh one). **Left open** -- flagged for the user rather
    than asserted either way.
  - **Time**: not usable for the 20% check as measured. Every route in this
    A/B ran concurrently with several other measurement jobs (the escape
    lab, the cap sweep, the test suites, the module case) on one 8-core
    machine (load average 10-14 through most of the run); wall-clock times
    inflated 1.5-3x across the board on BOTH sides where re-measured
    (e.g. watchy's own reruns, done with less contention, came back near
    the original timings). The `seconds` field in each `result.json` is
    recorded for the record but is not a fair A/B under this load.
- [x] The router's tests touching ordering, MPS, fan-out, escalation and terminals, on both builds; failures compared. 127 tests on KRT-fan (includes the two new `test_fan_order*.py` files), 125 on KRT-escape (same set minus those two, which do not exist there): 0 failures on either build.
- [x] Spec status and results; README note for the flag; commit. Design doc status/Verification updated; `--fan-order` / `--no-fan-order` documented in docs/configuration.md's Routing Strategy Options table (README's Command Reference points there as the source of truth for flags).
