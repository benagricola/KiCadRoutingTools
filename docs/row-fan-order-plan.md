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

- [ ] Failing test: a two-face row of pins at 0.4 mm pitch (a 20-pad row each side of a synthetic chip, 0.2/0.2, sinks spread 1 mm, 6 mm out) routed on F.Cu with `--escalation off`: every net connects and `check_drc.py --clearance-margin 0` is clean; with `--no-fan-order` at least one pin fails (the case must show the order matters).
- [ ] Implement; print one line naming the rows found and the nets re-sequenced.
- [ ] Tests pass; commit.

### Task 3: Measurement

- [ ] Escape lab, bare QFN, classes 0.2/0.2, 0.15/0.15, 0.1/0.1, both layer setups, default command line: 80/80 each, DRC clean with no margin.
- [ ] The 36-case cap sweep, both setups: failed pins no more than the prototype's (24 F.Cu, 13 F.Cu + B.Cu).
- [ ] The MCU module case, both setups: recorded against the default order (4 and 19 today); re-measured after the relief-via work.
- [ ] A/B on the tracked boards against the corner-move-check build (same 15 boards and checks as before): no new DRC violations, connectivity equal or better, failed nets equal or fewer in total, time within 20%. Any board that loses is explained before the task is done.
- [ ] The router's tests touching ordering, MPS, fan-out, escalation and terminals, on both builds; failures compared.
- [ ] Spec status and results; README note for the flag; commit.
