# A ripped net keeps its escape out of a fine-pitch row

Date: 2026-09-25
Status: tried and not adopted (see "Result")
Branch: feat/fanout-fixes (local)

## The problem

On the cap sweep (the escape lab's 80-pin QFN, one 0402 on a mid-row supply
pin, 36 placements, F.Cu and F.Cu + B.Cu), feat/fanout-fixes leaves 31 pins
failed (19 on F.Cu, 11 on two layers, one case counted in both with
different pins). Rerunning every failing case with its log, 29 of the 31
follow one pattern:

1. the pin routes early (the fan order routes rows outside-in);
2. a later net is stuck and the blame names the pin's track, so the pin is
   ripped up to make room;
3. while it waits to be rerouted, its two row neighbours route (or reroute)
   through the lane it had in front of its pad;
4. its reroute is stuck at its own pad after a handful of steps, walled in
   by exactly those two neighbours ("backward stuck (7 < 5000) ...
   Blocking obstacles: P16(2 track, 1 pad), P18(1 track, 1 pad)").

At minimum pitch a pin has one lane out, its own centre line (the corner
move check work). A rip hands that lane to whoever routes next, and the
neighbours are the ones next to it.

## What upstream already has

- #468 rip-restore: a rip victim that ends the run unrouted gets its
  escape stub back (rip_restore._stub_subset: the saved copper's short
  segments from a pad centre, and their vias), "so the pad keeps its landing
  site". It runs at terminal failure, after the lane is gone, and it drops
  a stub piece that now collides (it did here: "dropped 2 colliding
  piece(s)").
- #510 partial rip: rip_up_net(only_segments=...) removes just the named
  segments; the net keeps the rest and is requeued, and the router
  reconnects from the copper that remains (a pre-existing stub is a route
  source, as a fanout stub is).

## The change

When a net is ripped as a blocker and one of its pads is on a fine-pitch
row (fan_order.find_fan_rows, pitch at most FAN_ORDER_MAX_PITCH_FACTOR x
(track + clearance)), rip it partially: keep its escape from that pad, and
rip the rest.

- **The escape**: the net's copper from the row pad's centre along its
  route until the route is a set distance out from the row, measured along
  the row's outward normal from the pad's outer edge: a setting,
  RIP_KEEP_ESCAPE_DEPTH, default 2 x (track + clearance) (0.8 mm at
  0.2/0.2, two pitches), the zone where only the pin's own lane exists. A
  segment crossing that depth is split there, and the escape ends at the
  split point.
- **Kept only when it is not the blockage**: if any of the stuck search's
  frontier cells blamed on this net lie in the escape's own keep-out, the
  ripper needs that lane itself, and the net is ripped whole, as now.
- **Rerouting**: the kept escape is ordinary copper of an unrouted net, so
  it is stamped for the other nets (the lane stays the pin's) and the
  reroute starts from its free end (#510's requeue).
- **Terminal failure**: #468 applies unchanged to whatever remains.
- **Switch**: KICAD_RIP_KEEP_ESCAPE, on by default; 0 restores whole rips.

## Verification

- Unit: a row of 0.4 mm pitch pins at 0.2/0.2, one routed straight out; a
  rip of it keeps exactly its first 0.8 mm past the pad edge (a split
  segment) and removes the rest; a rip whose blamed cells lie on that escape
  removes everything.
- The cap sweep: failed pins at most half of today's (19 on F.Cu, 11 on two
  layers), no case worse.
- The bare QFN at 0.2/0.2: 80/80 on both layer setups.
- The module fan-out case through placemat's route step: nets left open no
  more than today's one.
- The tracked-board A/B loop: no new DRC violations, connectivity equal or
  better on each board.
- The router's rip-up, restore, custody and multipoint tests.

## Result (2026-09-25)

Implemented as planned (plan task 1, 2a15a3ac; wired at the five blocker-rip
sites) and measured on the cap sweep against the same build without it:

| | F.Cu | F.Cu + B.Cu |
|---|---|---|
| without | 19 failed pins | 11 |
| with | 31 | 18 |

18 of the 72 case/setup runs got worse. The kept escapes also stand in the
way of the nets that caused the rip, which need to turn near the row, and a
victim rerouting from the end of its escape has less freedom than one
starting at its pad; the rip set chosen by the blame changes too (the case
the plan named, cap-0402-diagonal-s0.4-g0.5, still lost one pin, P15 in
place of P17). A first version that kept the whole rip whenever a blocked
cell touched the escape never kept one: at minimum pitch a neighbour's lane
borders the escape, so such a cell is always among the blocked ones.
Reverted (08ff696f). The failure pattern in "The problem" stands and needs
another approach.

A second approach, measured the same way and also not adopted: routing a
rip victim straight after the net that ripped it (inserted into the main
loop's work list, instead of waiting for the reroute phase while its
neighbours take its lane; an uncommitted experiment behind
KICAD_RIP_REROUTE_NOW). Cap sweep: 20 failed pins on F.Cu and 9 on two
layers, against 19 and 11; 7 case/setup runs worse, 8 better -- no clear
effect either way.

## Not in scope

Reserving lanes for pins that have never been routed (the "escape lanes"
proposal set aside with the fan order): the rip is where the measured
failures come from.
