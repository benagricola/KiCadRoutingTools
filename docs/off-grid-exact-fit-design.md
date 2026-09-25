# Grid alignment and exact escape stubs

Date: 2026-09-25
Status: part 1 (grid alignment) implemented, on by default. Part 2 (exact
escape stubs) implemented and OFF by default (KICAD_EXACT_ESCAPE=1 turns it
on): its motivating case no longer needs it. gpio23 and gpio24 were sealed
by two over-blocking bugs, fixed on feat/fanout-fixes (every base-map pad
kept the half-cell corner buffer, c319ff35; every via blocked tracks 0.125
mm past its clearance, 78bd7dd3), and with those fixed both route on the
grid with or without stubs, clean by KiCad's DRC. On the cap sweep (36
cases, both layer setups) the build with stubs and their rip-up rule
routes exactly as the build without: 19 and 11 failed pins. The code stays
for a case that needs it.
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

## Grid alignment

Measured with placemat's `fixtures/route_spread.py`, which routes the module
case at 8 sub-grid offsets of the whole board (0.1 mm grid, F.Cu + B.Cu):

| board offset (dx, dy) mm | failed nets |
|---|---|
| (0, 0): as placed | 5 |
| dx a multiple of 0.025 (0.05, 0.025, 0.075) | 33 in each |
| dx a multiple of 0.0125 but not 0.025 (0.0125, 0.0375, 0.0625, 0.0875) | 56 in each |

The same with the east side moved out 0.5 mm: 3, 33, 56. At 0.2/0.2 and
0.4 mm pitch the only legal straight lane out of a pin is on the pin's own
centre line. As placed, the QFN's row centre lines fall on the 0.1 mm grid;
moved off it, the nearest grid lane is too close to a neighbour and whole rows
seal. So a board's routability at minimum pitch depends on where its fine-pitch
parts sit relative to the router's grid origin, which is the board origin
(`routing_config.py:801`, `GridCoord` rounds from zero).

**Part 1, the cheaper fix**: before routing, choose the sub-grid translation
(dx, dy) in [0, grid) that puts the most fine-pitch row centre lines (rows as
the fan order finds them: pitch at most 2 x (track + clearance)) on grid
lines, weighted by pin count; translate the board by it, route, and translate
the result back. One origin serves the whole board, so two fine-pitch parts
out of phase with each other cannot both be aligned; the rest of the board
is unaffected by a sub-grid translation. The exact stubs below (part 2) are
what covers a part the origin cannot align.

## The fix: exact escape stubs

When a pin's probe from its pad stops early (the existing "stuck (N < probe
limit)" signal), before the boxed-pad fallbacks, search a small family of
escape stubs in exact geometry (`py_router/exact_escape.py`):

- **Shapes**: from the pad's centre along its row's outward normal n to an
  open grid cell E; or along n for a length t, a 45 degree turn to either
  side, then along n again to E (no last leg when the turn lands on E). A
  diagonal that ends on a grid point lies on a grid diagonal, which the
  search has anyway; the leg back along n is what lets the diagonal sit on
  any line (the designer's gpio24 diagonal is 0.0127 mm off the nearest
  grid diagonal, with every clearance at the rule).
- **Solving t**: for a given E and turn, t is the only free length. Each
  foreign item's gap to the sliding diagonal is convex in t, so the t at
  which it is too close form one interval; the legal t are what the two
  straight legs allow minus the union of those intervals, solved to 1e-7 mm
  (a fit whose window is a micrometre wide is found). Of the legal t, the
  turn landing on E, else the middle of the highest window, else its ends:
  the first with no overlap at all, else the least.
- **Legality**: each stub, at the net's track width, is checked exactly
  against foreign copper on its layer at the pair's clearance: pads as their
  real copper (rect, roundrect, rotated, custom polygons), tracks as
  capsules, vias as discs; a stub exactly at the rule is legal (the 1e-6 mm
  tie tolerance the rasterisers use).
- **Which ends**: only cells outside the pocket the grid search can reach
  from the stuck side's endpoint cells (a flood fill that counts a diagonal
  step only where both cells beside it are open), within a reach of the pad
  (a setting, default 3 mm).
- **Use**: the shortest legal stubs, one per end cell (a setting, default
  16; among equals, the end nearer the other side first), have their ends
  added to the stuck side's endpoints and the route is tried again; the stub
  whose end the route starts from is committed as the net's copper (as the
  via-in-pad unblock's copper is). If no stub is legal or the route still
  fails, the existing fallbacks run as today (the rung search, the #189
  via-in-pad escape, rip-up). `KICAD_EXACT_ESCAPE=0` turns this off.

This is Python only, and it runs only for pins whose probe is stuck.

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
  clean by KiCad's DRC; a pad with no way out at all: no stub, and the
  existing fallback runs. KiCad works in whole nanometres and passes a fit
  exactly at the rule; `check_drc.py --clearance-margin 0` grades the
  nanometre residue of such a fit (it flags the designer's own layout of
  these pins at 0.000 mm), so an exact fit is judged by KiCad.
- Part 1: the module case routed at the 8 offsets above gives the same
  failed nets as at (0, 0); a synthetic board with two QFNs out of phase
  aligns the one with more pins.
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
