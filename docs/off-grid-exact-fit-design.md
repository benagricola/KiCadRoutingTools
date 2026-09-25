# Exact escape stubs

Date: 2026-09-25
Status: proposal
Branch: fix/escape-at-min-pitch (local)

## The problem

Some pins escape only by an exact fit: a path whose clearances are all at the
rule and whose turns sit off the routing grid. The grid router cannot place
such a path, so the pin reads as boxed in, and a pin whose probe stops early
is failed without the full search (`single_ended_routing.py:1636`).

The case that shows it: the MCU module (`MCU_RP2350B/layout/layout.kicad_pcb`,
0.2/0.2 class, 0.4 mm pitch QFN), pins gpio23 (pad 23) and gpio24 (pad 25)
either side of a v3v3 supply pin (pad 24) whose 0402 cap sits tilted at 45
degrees past the row. The designer's paths for them (saved 2026-09-25):

- gpio23: straight out 0.827 mm, then 45 degrees away from the cap;
- gpio24: straight out 1.877 mm past the cap, then 45 degrees back under it.

KiCad's DRC finds no violation on them. Every clearance on both paths is
exactly 0.2 mm (to the cap's two pads, the neighbouring pads, the v3v3 serve
trace and gpio22's track), and the turns are off the 0.1 mm grid (gpio23
turns at y = +5.737 mm from the chip centre).

Routed with the corner move check in, default order, F.Cu + B.Cu, on the
module case (placement and rail copper kept, each GPIO netted to a sink):

| grid | runs routing both gpio23 and gpio24 |
|---|---|
| 0.1 mm | 0 of 6 |
| 0.05 mm | 1 of 6 |

(six near-identical inputs each: the module as placed and with its east side
moved out by 0.5-2.0 mm; the east side is 5 mm from these pins.)

On a 0.1 mm grid a 45 degree track can lie only on the lines x +/- y =
k x 0.1 mm, 0.0707 mm apart; an exact fit past a tilted pad needs one line,
and it is between two of them. A finer grid moves the problem rather than
removing it, at four times the cells.

## The fix: exact escape stubs

When a pin's probe from its pad stops early (the existing "stuck (N < probe
limit)" signal), before the boxed-pad fallbacks, search a small family of
escape stubs in exact geometry:

- **Shapes**: from the pad's centre along its row's outward normal for a
  length L1; then optionally a 45 degree turn to either side for a length L2;
  then optionally a turn back to the normal. L1 and L2 are continuous,
  sampled finely (a setting, default 0.005 mm), up to a reach (a setting,
  default 3 mm, the row's escape region).
- **Legality**: each stub, at the net's track width, is checked exactly
  against foreign copper on its layer at the pair's clearance: pads as their
  real copper (rect, roundrect, rotated, custom polygons), tracks as
  capsules, vias as discs; a stub exactly at the rule is legal (the 1e-6 mm
  tie tolerance the rasterisers use).
- **Acceptance**: the stub's end is an open grid cell from which the probe
  toward the net's target is no longer stuck. The end is snapped onto the
  grid by adjusting the last leg's length.
- **Order of candidates**: shortest total length first; a turn toward the
  net's target before one away from it; no turn before one turn before two.
- **Use**: the accepted stub is committed as the net's copper for this route
  (as fan-out stubs are) and the route continues from its end. If no stub is
  accepted, the existing fallbacks run as today (the relief via where it
  applies, the #189 via-in-pad escape, rip-up).

This is Python only: the search is small (one pin, a few hundred candidate
stubs, each an exact distance test against the copper near the pad), and it
runs only for pins whose probe is stuck.

## Alternatives considered

- **A finer global grid**: measured above, 1 of 6 at 0.05 mm; four times the
  cells for every net on the board to help a few pins.
- **A grid aligned to each footprint's pads**: puts straight lanes on pad
  centres, but a 45 degree fit past a tilted pad still needs an off-grid line.
- **Any-angle search**: covers more cases than octilinear stubs, at the cost
  of a new search in the router's core; the hand paths here are octilinear.
- **The QFN fan-out tool's stubs** (`qfn_fanout/geometry.py`): exact, but one
  fixed straight length and a 45 degree fan for every pin, which is the
  shape that fails at minimum pitch; this search varies L1 and L2 per pin.

## Verification

Outcomes on dense boards vary with small changes to the input, so the
measures here are spreads: each case routed at 8 sub-grid offsets of the
whole board (placemat `fixtures/route_spread.py`), reported as failed nets
per run (min, median, max) and failures per net.

- Unit: a pad whose only way out is an exact-fit octilinear path (built as
  text, the designer's gpio24 geometry): the stub is found and the route is
  DRC clean with `check_drc.py --clearance-margin 0`; a pad with no way out
  at all: no stub, and the existing fallback runs.
- The module case: gpio23 and gpio24 fail in 0 of 8 runs (today 8 of 8 is
  expected at 0.1 mm; to be measured first), no other net's failure rate
  up by more than 1 in 8, DRC clean.
- The bare 80-pin QFN: 80/80 unchanged; the cap sweep: failed pins no more
  than before.
- The tracked-board A/B against the build it lands on: no new DRC
  violations, connectivity equal or better, time within 20%.

## Not in scope

The relief via for pins whose outward lane is truly closed (a cap on the
pin's axis): docs/relief-via-escape-design.md. Exact fits in the middle of a
route rather than at its escape.
