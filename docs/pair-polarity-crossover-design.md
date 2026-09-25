# A pair whose P and N swap sides between its ends

Date: 2026-09-25
Status: diagnosed; fixed by docs/pair-via-crossover-plan.md (Task 1)
Branch: feat/fanout-fixes (local)

## The problem

On the MCU module, USB_MCU_P/USB_MCU_N run from the chip's USB pins (66, 67;
north face, 0.4 mm pitch) to the series resistors R2/R3 east of the chip. P
is on one side of N at the chip and on the other at the resistors, so a
coupled pair has to swap sides somewhere. The designer does it by taking the
pair inward into the annulus between the pad row and the exposed pad,
changing layer there, and running east on B.Cu; the staggered vias bring P
and N out on the other layer with their sides exchanged.

route_diff.py does not couple this pair. Its log (the module fan-out case
through placemat 0.35.0, gap 0.45 mm):

- At the chip end the outward escape is blocked at every setback, so the
  pair launches inward (rotated 180 degrees): the designer's direction.
- The polarity mismatch is found. Pad swap is off for this pair, as upstream
  intends for USB (#279), so it tries the two geometric resolutions:
  - source connectors out the opposite side: a route is found, but "P/N
    tracks cross in final geometry";
  - target connectors out the opposite side: a route is found, but a
    connector grazes the chip's pin 68 (v3v3) by 0.047 mm (#165).
- The hybrid fallback (coupled middle, single-ended legs that resolve the
  swap at the pads, docs/differential-pairs.md "Hybrid Escape"): F.Cu
  rejected ("no clear diff-pair-wide launch swath at a terminal"), B.Cu
  rejected ("coupled middle P/N tracks cross").
- The pair is then routed single-ended, P to P and N to N.

The gap does not change this: at 0.2 and 0.3 mm the outcome is the same.
The rejected candidates are convoluted (the flip route loops round its own
vias, F.Cu to B.Cu and back, several times), so the rejections are correct;
the question is why no clean candidate is generated.

## What upstream already has

The hybrid is the mechanism meant for exactly this: "the pair must swap
sides between the two ends ... That is where polarity is resolved: at the
pads, by independent A*, with no coupled crossing." No new mechanism is
proposed; the work is to find why the hybrid's candidates fail here and fix
that.

Upstream #266 (open) is the neighbouring gap: the hybrid cannot do a pad
polarity swap, so a side-flipping pair "wraps around" (one track detours
round the other); prior art PR #644 built part of it and was closed unmerged.
A pad swap is denied for USB by policy (#279), so for this pair the
wrap-around is the resolution upstream intends, and here even that is
rejected ("coupled middle P/N tracks cross"). If the diagnosis finds the
wrap-around cannot be clean at this geometry, the designer's layer-change
crossover (staggered vias exchanging the sides) is the alternative to
propose, as a separate change.

## Plan of the diagnosis

1. Reproduce on a minimal case: the chip's north face (pins 60-72 with
   their caps and serve copper), R2/R3 where the designer put them, the
   pair and nothing else routed. Record each hybrid layer combination's
   launch points, coupled middle and legs as an SVG saved as PNG.
2. For "no clear diff-pair-wide launch swath" on F.Cu: measure the free
   width beside pins 66/67 at the setbacks tried, against the pair's width
   (2 x width + gap), and find what closes it (a cap, a serve trace, the
   corner buffer or via over-block class of bug fixed elsewhere).
3. For "coupled middle P/N tracks cross" on B.Cu: find which middle
   segments cross. P and N offset from one centreline cannot cross each
   other, so the crossing is with the middle's via processing
   (_process_via_positions) or a leg; identify which.
4. Fix what is found, with a test on the minimal case, and write it up.

## Findings (2026-09-25)

Every rejected candidate was dumped where `_pn_tracks_cross_full` rejected
it and drawn to scale over the pads (P red, N blue, F.Cu solid, B.Cu
dashed, P/N crossings circled):

- **The flip (standard route)**, `img/pair-polarity/flip-route.png`: the
  pair launches inward from pins 66/67 as the designer does, but stays on
  F.Cu, runs south through the annulus between the exposed pad and the east
  pad row, comes back north-east, and resolves polarity by a loop beside
  R2/R3 that still crosses once. The coupled route has no way to exchange
  sides except by a loop.
- **The hybrid**, `img/pair-polarity/hybrid-middle.png`: its launch search
  (`_closest_launch`) walks the straight line from each terminal toward the
  other until a pair-wide swath is clear. From the chip's USB pins that line
  runs through the north-east decoupling caps almost all the way, so both
  launch points land beside R2/R3; the coupled middle between two nearly
  coincident points loops on itself and crosses twice. The hybrid is built
  for a terminal with room near it (docs/differential-pairs.md, "Scope"),
  which neither end of this pair has on the straight line.

Neither mechanism can exchange P and N at a layer change, which is how the
designer resolves it (staggered vias in the annulus, the pair continuing on
B.Cu with its sides swapped). Upstream has no such mechanism; #266 (open)
adds a pad swap to the hybrid, which USB may not use (#279).

## Next: a layer-change crossover (to be proposed)

A polarity resolution that, where the coupled route changes layer, places
P's and N's vias so that the offset tracks continue on the new layer with
their sides exchanged, within the pair's own width, instead of a loop. It
is a change to the coupled route's via handling (`_process_via_positions`
and the polarity stage), so it gets its own spec and plan.

## Verification

- The minimal case: USB_MCU routes coupled (the report's pair outcome
  "coupled", escape "hybrid" or not), clean by KiCad's DRC.
- The module fan-out case: USB_MCU coupled; nets left open no more than
  before (1 of 67).
- Tracked boards with pairs (lvds_converter_dualclk*, qfn_diffpair_escape,
  qfn_csi_underpad_diff, watchy, tigard): pairs coupled equal or more, no new
  DRC violations; the router's diff-pair tests.

## Not in scope

The electrically-short floor (a pair under ~6.5 mm at this gap routes
single-ended on purpose, diff_pair_min_coupled_length); whether short pairs
should couple anyway is a separate decision.
