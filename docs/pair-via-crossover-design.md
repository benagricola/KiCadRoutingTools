# A pair exchanges its sides at a layer change

Date: 2026-09-25
Status: proposal, for review
Branch: feat/fanout-fixes (local)
Follows: docs/pair-polarity-crossover-design.md (the diagnosis)

## The problem

A pair whose P and N sit on opposite sides at its two ends (USB_MCU on the
MCU module: P left of N at the chip's pins 66/67, right of it at R2/R3) can
only be coupled today by a loop (the flip; drawn in
img/pair-polarity/flip-route.png) or not at all (the hybrid collapses when
its terminals are congested). A pad swap is not allowed for USB (#279).

The designer exchanges the sides at a layer change: the pair drops into the
annulus under the package, and its two vias are staggered along the pair,
N's 0.9 mm past P's (MCU_RP2350B_layout.py, USB_N_VIA_DY), so each track
crosses the other's side on the layer the other has left.

## The change

A third polarity resolution in route_diff, tried after the pad swap (when
allowed) and before the flip: a **via crossover**.

- **Where**: at a layer change of the coupled route. When the route has
  none, the pose search is asked for one (the pair's two layers, a via cost
  as today); a route with a layer change is required for this resolution.
- **Geometry**, going along the route toward the change, P on the left and
  N on the right, from layer A to layer B:
  1. the first track's via (the one on the side the route turns away from,
     so the crossing tracks run with the turn) sits on its own offset line
     at the change;
  2. on layer B that track crosses the centreline to the other side, under
     the second track, which is still on layer A;
  3. the second track continues on layer A past the first via, by the
     stagger, crosses to the vacated side, and drops through its own via;
  4. from there both continue on layer B, sides exchanged, at the pair's
     spacing.
  The stagger is the least that keeps via-to-via, via-to-track and
  track-to-track clearance for the pair's width and gap (a setting's floor:
  PAIR_CROSSOVER_MIN_STAGGER, default the via-to-via centre distance), and
  the crossing segments are 45 degrees.
- **Legality**: the crossover's tracks and vias are checked against foreign
  copper with the same check the pair's connectors use
  (`_connector_grazes_foreign_copper`) and against each other (no P/N
  crossing on one layer, `_pn_tracks_cross_full`); an illegal crossover
  falls through to the flip.
- **Report**: `pair_reports` gains `"polarity": "via-crossover"`.
- **Switch**: `--pair-crossover` / `--no-pair-crossover`, on by default.

## Verification

- Unit: a straight pair on two layers with its sides swapped between the
  ends: routes coupled with one crossover, both vias legal, no P/N crossing
  on either layer, the stagger at least the floor.
- The MCU module fan-out case: USB_MCU coupled, KiCad's DRC clean, no loop
  (its length within 1.5x the straight line between its ends).
- Tracked boards with pairs (lvds_converter_dualclk*, qfn_diffpair_escape,
  qfn_csi_underpad_diff, watchy, tigard): pairs coupled equal or more, no new
  DRC violations, no pair longer than before by more than 10%.
- The router's diff-pair tests.

## Not in scope

Where on the route the crossover goes when there is a choice of layer
changes (the first is taken); length matching of the crossover's extra
length (the intra-pair match pass, when asked for, runs after as today).
