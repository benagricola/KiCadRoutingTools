# Relief-via escape

Date: 2026-09-25
Status: proposal, to be re-scoped (see the correction below)
Branch: fix/escape-at-min-pitch (local), after the corner move check

## Correction (2026-09-25)

The premise below is wrong for two of the four pins. gpio23 and gpio24 sit
beside a supply pin whose cap is tilted 45 degrees, not on the pin's axis,
and both escape outward on F.Cu: the board's designer drew them (the module's
layout.kicad_pcb, saved 2026-09-25), and KiCad's DRC finds no violation. Every
clearance on those paths is exactly 0.2 mm and the turns sit off the 0.1 mm
grid (gpio23 turns at y = +5.737 mm from the chip centre), so the router
misses them from grid quantization, not for want of a via: at a 0.05 mm grid
it routed both in one of six runs, at 0.1 mm in none. That is the subject of
docs/off-grid-exact-fit-design.md. LAYOUT-INTENT point 6 holds for caps on a
pin's axis (the west face, the east face's flanking pairs), and the relief via
stays the proposal for those pins; this document is to be re-scoped to them
and re-measured with route spreads (the module's failing set changes between
near-identical inputs, so single routes do not decide it).

## The problem

A pin on a fine-pitch QFN/BGA row sits 0.4 mm from its neighbours. When the
neighbour is a bypass cap's supply pin, the cap's own pad sits point-blank on
the pin's axis just past the row, and the two pins either side of it have no
way out: a lane needs `pad_half_height + clearance` off the cap axis to clear
it, which for a 0402 cap pad (0.31 mm half-height) is 0.61 mm -- more than the
0.4 mm pitch gives at any track width. The hand-routed reference for this
board says as much directly: "the +/-0.4 mm neighbours of a cap pin are
impossible at any track width" (`MCU_RP2350B/LAYOUT-INTENT.md`, the escape and
decoupling architecture, point 6). Its fix for the pins this hits on the west
and east faces is a **relief via**: dive inward, under the package, to a via
in the ring between the exposed pad (EP) and the pad row, and continue on the
other copper layer.

### Measured

The module case (`MCU_RP2350B/layout/layout.kicad_pcb`'s placement and rail
copper -- v3v3/gnd/V1V1 cap-serve traces and via-in-pad drops -- with every
other track and via stripped, each chip pin netted to a sink outside the
module) reproduces the failure with the current router (corner guards in,
default net order, `--escalation off`, 0.2/0.2 class, `F.Cu`+`B.Cu`):

```
.venv/bin/python -X utf8 py_router/route.py IN.kicad_pcb OUT.kicad_pcb \
  --nets <63 nets, the chip's GPIOs and buses minus the unconnected VREG_LX pin> \
  --layers F.Cu B.Cu --escalation off --json-out r.json
```

4 of 67 single-ended nets fail: `gpio23`, `gpio24`, `gpio40_adc0`,
`gpio47_adc7` (reproduced in this investigation; on `F.Cu` only, 19 fail).
Each is the immediate, one-pin-pitch neighbour of a `v3v3` pad (an IOVDD or
ADC_AVDD pin, i.e. a cap axis):

| net | pad, chip-relative (mm) | neighbour `v3v3` pad (mm) |
|---|---|---|
| gpio23 | (-3.0, 4.91) | (-2.6, 4.91) |
| gpio24 | (-2.2, 4.91) | (-2.6, 4.91) |
| gpio40_adc0 | (4.91, 0.6) | (4.91, 0.2) |
| gpio47_adc7 | (4.91, -3.0) | (4.91, -3.4) |

This is exactly the LAYOUT-INTENT.md point-6 geometry, on the south and east
faces (the hand board only offers relief vias on the west/east faces; the
south pair uses a different, placement-level trick -- see Alternatives).

Each net's log entry reads the same way:

```
backward stuck (49 < 5000), forward=5000
  backward cell (472, 740, layer=0): ok, 6/8 neighbors blocked
    Blocking obstacles: gpio25(1 track, 1 pad), v3v3(1 track, 1 pad)
No route found after 5049 iterations (both directions)
```

`5000` is `GridRouteConfig.max_probe_iterations` (`routing_config.py:104`):
a bidirectional probe runs before any full search, and when one side dies far
below that cap the router calls it boxed in by static geometry and skips the
full search rather than paying for it (`single_ended_routing.py:1634-1658`;
the same short-circuit is documented in `docs/rip-up-reroute.md`'s "Early
probe detection"). `static_boxin_hint` names the signature explicitly:
"typical for fine-pitch (0.4-0.65 mm) packages at coarse grid/clearance
settings" (`routing_diagnostics.py:788-791`). 49-54 iterations at a 0.1 mm
grid reaches well under 1 mm from the pad -- nowhere near the ~2.56 mm a
relief via needs -- so even an unbounded primary search would have to grind
through a dead end at the row before it could discover the inward option; the
router's own probe correctly reports that the immediate neighbourhood is a
wall.

Rip-up cannot fix it either. The named blockers are mostly `v3v3` itself --
pre-existing rail copper, unrippable by default -- plus neighbour GPIO tracks
that, per LAYOUT-INTENT's own rule, are not the real obstacle: clearing them
still leaves a 0.4 mm lane against the 0.61 mm a cap pad needs. Ripping
anything nameable here cannot open a path.

### The existing boxed-pad fallback

Issue #189 gives a boxed SMD pad a last-resort rescue: drop a fab-legal via
in or near the pad and retry (`single_ended_routing.py:2883-2967`,
implementation in `_place_shrunk_via_in_pad_impl` at 2595-2792). When no
via fits inside the pad it escalates to an **off-pad escape stub**: search
`KICAD_ESCAPE_STUB_RADIUS` mm (default 1.0, `env_knobs.py:133`) around the pad
for a legal through-via site and route a trace from pad to via
(`plane_pad_tap.py:1296-1411`, `tap_pad_with_escalation`). That search is
capped at `FINE_TAP_SEARCH_RADIUS = 3.0` mm regardless of the caller's radius
(`routing_defaults.py:289`) -- comfortably past the ~2.56 mm to the ring, so
the radius should not be the obstacle.

Measured directly: re-running the module case with
`KICAD_ESCAPE_STUB_RADIUS=3.0` (so the fallback's own search window is at its
ceiling either way) leaves the same 4 nets failing, with the identical
"Boxed in ... after 5005 iteration(s)" signature at both the default 1.0 mm
and the 3.0 mm radius. With `KICAD_UNBLOCK_DEBUG=1`, the run's blame
attribution (`find_via_position_blocker`, consulted when no via site is found
at all) names the same single blocker, `v3v3`, at both radii. Widening the
knob does not find the option -- this is a discovery gap in the fallback, not
a budget one. The fallback is built for a different job: `find_via_position`
(`route_planes.py:91-338`) is a **direction-agnostic nearest-legal-site
search**, seeded from ground/power-plane pad tapping, with no notion of "the
ring between the EP and the row" as a place worth looking; and it plugs into
the same generic search whether the pad's neighbour is a via-blocked trace two
cells away or a package's EP 2.5 mm inward.

### The inward via, placed by hand

For each of the four nets, adding one via at the ring position that mirrors
the hand layout's own scheme (`gpio40_adc0`'s matches the reference exactly,
at chip-relative (2.35, 0.6); the other three use the same construction --
keep the pin's own row coordinate, move to x/y = +-2.35 on the inward side)
plus a single straight 0.2 mm `F.Cu` stub from the pad, is clean under
`check_drc.py --clearance-margin 0` (`--baseline` against the case's own
pre-existing via-in-paste notes) -- individually and all four together -- and
with that copper pre-placed the router completes the rest of each net (via to
sink, on `B.Cu`) on every net tried, both alone and with all four present at
once:

| net | pad (mm) | relief via (mm) | offset |
|---|---|---|---|
| gpio23 | (-3.0, 4.91) | (-3.0, 2.35) | 2.56 mm inward |
| gpio24 | (-2.2, 4.91) | (-2.2, 2.35) | 2.56 mm inward |
| gpio40_adc0 | (4.91, 0.6) | (2.35, 0.6) | 2.56 mm inward |
| gpio47_adc7 | (4.91, -3.0) | (2.35, -3.0) | 2.56 mm inward |

(chip-relative; the offset is the same 2.56 mm on every face because the EP
is square and every row sits at the same 4.91 mm.) This nails the finding:
the escape is geometrically available and sufficient. What is missing is a
search that knows to look there.

## The mechanism

**What is offered.** When the boxed-pad fallback (#189) runs for a
single-ended net's endpoint pad, and that pad belongs to a footprint with a
qualifying large centre pad (an EP, sized well past the escaping pin's own
pad and past its pitch -- generic geometry, not a named footprint or part),
try one directed via candidate first: straight in from the pad, on the
inward side of the centre pad's edge, at the pin's own row coordinate. Offer
it before the existing radius-based, direction-agnostic search, so the one
promising site is tried before the search burns its budget scanning
everywhere else.

**When.** Only on the existing boxed-in-static signature the router already
detects (a probe direction exhausted under `max_probe_iterations`, no full
search attempted) -- the same trigger #189 already uses. A net that routes
normally never reaches this code path, so the mechanism is inert everywhere
it currently is.

**Where the via may go.** Between the centre pad's outer edge and the row's
own inner edge (the ring), at a site that is DRC-legal at the class the net
is routing at -- exactly what `find_via_position`'s existing legality check
(via-to-copper clearance) and `route_via_to_pad`'s existing routability check
(a real trace from the via to the pad) already verify (`route_planes.py:346-422`,
553-599). No new legality machinery is needed; the directed candidate is
just a better first guess about where to look.

**Capacity.** Not a separate rule. A relief via is ordinary committed copper
and blocks a later via placement the normal way, so two pins whose directed
candidates land within a via diameter of each other naturally contend for
the same site through the obstacle map's own clearance check, and the second
one falls back to the existing radius search. The hand reference's own
count -- vias 0.8 mm apart on the ring (double the 0.4 mm pin pitch, the
minimum that clears via-to-via spacing at this class) and a documented dead
row where "no x between two 0.4-pitch pads clears a 0.6 mm via"
(LAYOUT-INTENT.md point 3) -- is what this emergent behaviour reproduces,
not a lattice the router has to know about.

**Corner guards.** The pad-to-via stub is routed by `route_via_to_pad`
calling `router.route_with_frontier` (`route_planes.py:648`) -- the same
Rust A* core every other track goes through, where `move_clips_corner` is
checked on every move (`docs/corner-move-check-design.md`, "Rust"). No
special-casing is needed: a diagonal stub near a pad corner is refused the
same way any other clipping move is.

**Rip-up.** The directed candidate should be tried before the rip-up ladder
spends a pass on this failure, not after: the evidence above says the named
blockers are usually unrippable rail copper, and where they are rippable
in-run copper, ripping them does not open a corridor that is impossible at
any width. Once placed, a relief via is an ordinary piece of the net's
copper -- rippable by name like any other track if that net is later
reconsidered, never auto-preferred as a rip target.

**Python-only vs Rust.** Python-only. Everything the mechanism needs --
via legality queries, the corner-guarded A*, source/target cell overrides --
is already exposed to Python and already used by `find_via_position` /
`route_via_to_pad` / `_place_shrunk_via_in_pad_impl`. `find_via_position`
already accepts a `position_preference` predicate for exactly this kind of
soft, never-excluding steer (used today to prefer zone-fill-confirmed sites,
`route_planes.py:104-139`, `plane_pad_tap.py:1216-1238`), but
`tap_pad_with_escalation` (`plane_pad_tap.py:1296-1411`) does not yet thread
one through from its caller. The implementation is: give
`tap_pad_with_escalation` an optional `position_preference` passthrough to
`try_tap_pad`'s `find_via_position` call, and have
`_place_shrunk_via_in_pad_impl` (`single_ended_routing.py:2595-2792`) build
one -- when the pad's footprint has a qualifying centre pad, prefer the
straight-in ring cell -- and pass it down. A board with no such footprint,
or no legal site there, degrades to today's search exactly as the existing
zone/ghost preferences do.

## Alternatives considered

- **Widen `KICAD_ESCAPE_STUB_RADIUS`.** Tested directly (see Measured
  above): raising it to match the fallback's own 3.0 mm ceiling does not
  find the option. The search is direction-agnostic, not budget-starved, so
  a bigger radius searches a bigger haystack without a better idea of where
  the needle is.
- **Grant `--rip-existing-nets` on the named blockers.** Rejected on the
  evidence above: the decisive blocker is protected rail copper, and even a
  hypothetical rip of the rippable neighbours does not reopen a lane that is
  impossible at any track width. Rip-up is the wrong lever for this failure
  class, not merely an expensive one.
- **A global finer grid / tighter clearance** (`static_boxin_hint`'s own
  standing advice). Works for some fine-pitch dead ends, but not this one:
  the blocking geometry is a fixed 0.4 mm pitch against a 0.61 mm requirement,
  which no grid or clearance short of relaxing the class actually clears: the
  0402 cap pad's real copper does not move. A finer grid only makes the
  probe more precise about the same wall.
- **Match the hand layout's south-face fix (shift a neighbouring part to
  open a gap).** This is what LAYOUT-INTENT.md does for `gpio23`/`gpio24`
  instead of a relief via (a 0.3 mm south slide of the crystal block). It is
  a placement-level decision specific to what else is near that pin on that
  board, not a general router mechanism, and it is out of scope here: this
  proposal is router-side only. (It is also not required -- this
  investigation's relief vias route both south pins cleanly without moving
  anything.)

## Verification

- **The module case, 0 failures.** With the mechanism implemented, the same
  reproduction command above should leave `gpio23`, `gpio24`, `gpio40_adc0`,
  `gpio47_adc7` all routed, `check_drc.py --clearance-margin 0` clean at the
  routed 0.2/0.2 class. This investigation's hand-placed proof (the table
  above) is the existence proof the geometry supports that outcome; closing
  the loop through the router's own search is the implementation's job.
  Net-order sensitivity elsewhere on the board (a marginal net such as
  `gpio33`, which already fails its main pass and is rescued in the
  untouched baseline, landing differently once new copper is present nearby)
  is the row-fan-order work's territory, not a regression this proposal
  should be judged against.
- **No regression on the bare 80-pin QFN.** The escape lab's bare-QFN case
  (same footprint, no caps/rails, each pin to its own external sink) routes
  80/80 with 0 vias today (`--ordering original`, 0.2/0.2, `F.Cu`+`B.Cu`,
  `--escalation off`). No pin there is ever boxed-in-static, so the new
  fallback path is never reached; re-run the same case after the change and
  confirm 80/80 holds with the same 0 vias.
- **Unit.** The directed-candidate builder: given a pad and its footprint,
  returns the correct ring cell for each of the four faces, and returns
  nothing for a footprint with no qualifying centre pad or for a pad that
  is not boxed-in-static.
- **A/B on the tracked boards** (`kicad_files`), same terms as the corner
  move check: `check_drc` at the routed clearance with no margin,
  `check_connected`, closure. Expected: no new clearance violations, no
  regressions, closure equal or better on any board with a qualifying
  footprint.

## Not in scope

- Rust changes -- none needed (see Python-only vs Rust above).
- Footprints with no large centre pad to dive toward (two-row connectors,
  discrete parts): the trigger simply never fires for them.
- A second via back to the near layer when the far layer cannot reach the
  sink either (chained relief): the first cut is a single dive, matching
  every case measured here.
- Differential pairs and multipoint nets: single-ended only for this change.
- The row-fan-order net-ordering work, revised in parallel
  (`docs/row-fan-order-design.md`): this proposal does not touch net
  ordering, and the marginal-net wobble noted under Verification is that
  work's territory.
- The south-face placement fix the hand layout uses instead of a relief via
  (see Alternatives): out of scope, router-side only.
