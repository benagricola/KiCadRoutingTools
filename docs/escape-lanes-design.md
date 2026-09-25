# Escape lanes: a pin row escapes before other nets cross it

Date: 2026-09-25
Status: proposal
Branch: fix/escape-at-min-pitch (local), after the corner move check

## The problem

The router takes nets one at a time, each on its cheapest path given what
is already placed. Around a fine-pitch pin row that is greedy in a way that
loses pins: an early net's route turns straight across a neighbouring pin's
face, or drops a via just past the row, and the neighbour is sealed in.
Rip-up moves the damage from pin to pin ("P75: ripped by P76, P77, P26,
P74"), and the final reconciliation pass may not rip committed nets.

Measured on a bare 80-pin QFN (0.4 mm pitch, 0.2 mm pads), each pin netted
to its own sink 6 mm out, class 0.2/0.2, with the corner move check in
(placemat escape lab, 2026-09-25):

| run | F.Cu only | F.Cu + B.Cu |
|---|---|---|
| as routed | 78/80 | 77/80 (42 vias, 21 within 2 mm of the rows) |
| `--via-cost 300` | - | 77/80, 42 vias |
| `--ordering inside_out` | - | 78/80, 22 vias |
| each pin pre-escaped: a straight own-layer stub 0.5 mm out | 79/80 | 79/80 |
| stub 1.0 mm out | 79/80 | **80/80** |
| stub 2.0 mm out | 74/80 | **80/80** |

(The two-layer stub runs need `--no-stub-layer-swap`; see the finding
below.) Every run DRC clean at 0.2 with no margin. So the failures are not
capacity: the row escapes when every pin first leaves straight on its own
layer, and neither the via cost nor the ordering gets there.

More layers doing worse than one is the same effect: with B.Cu available,
early nets drop vias beside the row (a 0.6 mm via and its clearance claim
about 1 mm, 2.5 pitches), which F.Cu-only routing cannot do.

## The fix: escape lanes

Before routing, each pin of a fine-pitch row whose net is being routed gets
an **escape lane**: its straight exit along the row's outward normal, from
the pad's edge out to the lane depth, on the pad's layer. To every OTHER
net the lane is blocked exactly as a track of the pin's net along it would
be (tracks and vias, at the pair's clearance). The pin's own net may use it
or not. When the pin's net is routed, the lane goes: the net's obstacles
are recomputed from its real copper.

This is the stub experiment without committing copper: other nets cannot
cross in front of a pin that has not escaped, so each pin keeps its straight
way out, and a pin whose route leaves another way (a via in pad, a turn at
the pad) is not forced along a stub it does not use.

- **Rows**: pads of one footprint in a line with a common orientation, at
  least three, their pitch at most `2 x (track + clearance)` of the pin's
  net (closer pins are where other nets' copper can seal a pin; wider rows
  have room). The lane's direction is the row's outward normal, as
  `qfn_fanout` finds it (footprint-local edge classification).
- **Depth**: `--escape-lane-depth` in mm, default 1.0 (the measured best
  on both layer setups); 0 turns lanes off.
- **Which nets**: signal nets being routed; not plane or excluded nets, and
  not a pad already carrying copper of its net (it has escaped).
- **Where**: the lane is added to the pin's net's obstacle cache
  (`precompute_net_obstacles`) as a capsule of the pin's net, so it is added,
  removed while that net routes, and recomputed after it routes, with no new
  lifecycle.

## A finding, not in this change

With pre-laid stubs on two layers, the stub layer swap moved all 80 stubs to
B.Cu and every net then failed (80/80 open); with `--no-stub-layer-swap`
the same board routed 80/80. A swap that leaves more nets unroutable than
before it should not be kept. Filed as a follow-up.

## Verification

- The escape case: the bare QFN at 0.2/0.2, 0.15/0.15 and 0.1/0.1, both
  layer setups: 80/80 on two layers at every class, at least 79/80 on F.Cu,
  DRC clean with no margin; the lanes off gives today's numbers.
- A unit test: a seven-pin row with an obstacle net whose cheapest route
  crosses in front of the middle pin: with lanes it goes round, and the
  middle pin escapes.
- The A/B on the tracked boards against the corner-move-check build: no new
  DRC violations, connectivity equal or better, failed nets equal or fewer
  in total, and time within 20%.
- The router's tests that touch obstacle maps, fan-out, escalation and
  terminals.
