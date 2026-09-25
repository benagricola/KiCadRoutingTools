# A pair whose P and N swap sides between its ends

Date: 2026-09-25
Status: proposal (diagnosis first)
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
