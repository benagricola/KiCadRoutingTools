# Row fan order: a pin row is routed outside-in, as a person fans it out

Date: 2026-09-25
Status: proposal (revised twice: fan order replaces escape lanes; chip-to-chip nets keep their place)
Branch: fix/escape-at-min-pitch (local), after the corner move check

## The problem

The router takes nets one at a time, each on its cheapest path given what
is already placed. Around a fine-pitch pin row the default order (MPS, then
length) routes pins in no particular order along the row: a middle pin's
lane turns early and runs diagonally in front of pins not yet routed, or an
early net drops a via beside the row, and later pins are sealed in pockets.
Rip-up moves the damage from pin to pin, and the final reconciliation may
not rip committed nets.

Measured on a bare 80-pin QFN (0.4 mm pitch, 0.2 mm pads), each pin netted
to its own sink 6 mm out with the sinks spread to 1 mm, class 0.2/0.2, with
the corner move check in (placemat escape lab, 2026-09-25):

| run | F.Cu only | F.Cu + B.Cu |
|---|---|---|
| default order | 78/80 | 77/80, 42 vias |
| `--via-cost 300` | - | 77/80, 42 vias |
| `--ordering inside_out` (acts only with BGA zones: none here) | - | 78/80 |
| pre-laid straight stubs, 0.5 / 1.0 / 2.0 mm | 79 / 79 / 74 | 79 / 80 / 80 (with `--no-stub-layer-swap`) |
| **each face outside-in, `--ordering original`** | **80/80, 0 vias** | **80/80, 0 vias** |

All DRC clean at 0.2 with no margin. With the order right, the chip fans
out on F.Cu alone: each face's pins either side of its middle peel outward
in turn, every lane beside the one routed before it. Stubs only moved the
pocket further out (the fan still went in the wrong order beyond them).

## The fix: row fan order

An ordering pass after the net order is chosen (MPS or any other), for the
nets that leave a fine-pitch row:

- **Rows**: pads of one footprint in a line with a common orientation, at
  least three, pitch at most `2 x (track + clearance)` of the nets
  concerned (where one lane per pitch is all there is; wider rows leave room
  and keep the order they had). The row's outward normal and axis as
  `qfn_fanout` finds them (footprint-local edge classification).
- **Fan direction**: for a pin, where its net's other end lies along the
  row's axis relative to the pin: to one side, the other, or ahead (within
  one pitch).
- **Order within a row**: the pins fanning toward one end, from that end
  inward; the pins fanning toward the other end, from that end inward; the
  pins going straight ahead last. That is the sequence in which each lane
  can lie beside the previous one: the outermost turns first.
- **Across rows and the rest of the board**: row nets keep the positions
  the base order gave the row as a whole (the first of its nets in the base
  order); within that block they are re-sequenced as above.
- **Chip to chip**: a net with pads on two footprints that each have a
  fine-pitch row keeps its place in the base order. MPS already sequences
  such nets by where both ends sit; re-sequencing them by one end lost a
  QSPI line on the MCU module (below).
- **Switch**: `--fan-order` on by default, `--no-fan-order` for the old
  behaviour. It changes order only, never geometry or rules.

## With parts round the chip

Measured 2026-09-25 with a prototype of this order passed to the router as
`--ordering original --nets ...` (F.Cu + B.Cu, `--escalation off`), failed
pins in total:

| case | default order | fan order |
|---|---|---|
| bare QFN, F.Cu only | 2 | 0 |
| bare QFN, F.Cu + B.Cu | 3 | 0 |
| one 0402 on a mid-row supply pin, 36 placements (3 turns x 4 slides along the row x 3 gaps), F.Cu only | 204 (1 of 36 all routed) | 24 (23 of 36) |
| the same, F.Cu + B.Cu | 74 (7 of 36) | 13 (26 of 36) |
| the MCU module (its caps, crystal, flash and LDO placed; rail copper kept; each GPIO to a sink), F.Cu + B.Cu | 4 | 6 (7 without the chip-to-chip rule) |
| the same, F.Cu only | 19 | 21 |

With the fan order, the sweep's failures sit within a few pins of the
served pin, where the cap takes the room; with the default order they are
spread over all four faces. On the module both orders lose the pins beside
cap-served supply pins (gpio23/24/40/47, RUN, USB_MCU_P), which the hand
layout escapes partly by relief vias under the package; that is a separate
mechanism (docs/relief-via-escape-design.md), and the module is re-measured
with it. A variant that keeps every net in its base-order slot and only
sorts within a row's fan groups did worse on the sweep (66 and 24) and was
dropped.

## Findings, not in this change

- The stub layer swap moved all 80 pre-laid stubs to B.Cu and every net
  then failed; with `--no-stub-layer-swap` the same board routed. A swap
  that leaves more nets unroutable than before it should not be kept.
- `--via-cost 300` left the via count at 42: to be checked whether the
  option reaches the search.
- `--ordering inside_out` needs BGA exclusion zones to do anything, and the
  run log says it is in use anyway.
- Escape lanes (reserving each pin's straight exit for its own net until it
  is routed), the first proposal here, are set aside: the measured cause was
  the order, and lanes did not fix it. They come back only if the cases with
  parts round the chip need them.

## Verification

- The escape case: the bare QFN at 0.2/0.2, 0.15/0.15 and 0.1/0.1, both
  layer setups, default command line: 80/80 each, DRC clean with no margin,
  no more vias than the order-alone runs above.
- Unit: the fan sequence of a row for targets on either side, ahead, and a
  mix; a net on two rows; rows too coarse to reorder keep their order.
- The A/B on the tracked boards against the corner-move-check build: no new
  DRC violations, connectivity equal or better, failed nets equal or fewer
  in total, time within 20%.
- The router's tests that touch ordering, fan-out, escalation and terminals.
