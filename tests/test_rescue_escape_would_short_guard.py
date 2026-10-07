#!/usr/bin/env python3
"""Rescue escapes are checked against real copper before they are kept.

At rescue time the board is already ROUTED, and the tap/fanout planners' own
conflict models cover balls, teeth and passives - not this run's tracks, and
not a filled copper graphic. An unguarded rung ships a short.

That is not hypothetical: the dogbone rung had no guard, and on a 56 mm board
it landed a via in the middle of a net-tagged 5V pour. The A* router had
already refused the same net for 313721 iterations in both directions BECAUSE
the pour blocks it; then the rescue put copper there anyway, and ordinary
routing to the new via dragged two more tracks in after it.

Properties:
  1. _via_site_clear rejects a via sitting inside foreign copper, including the
     area bands that model a filled graphic's interior.
  2. _leg_clear rejects a leg crossing the same copper.
  3. Both accept the same geometry when the copper belongs to the via's own net.
  4. Every rescue rung that extends pcb_data copper calls the guard first.

Run:  python3 tests/test_rescue_escape_would_short_guard.py
"""

import os
import re
import sys
from types import SimpleNamespace

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_TESTS_DIR)
for _p in (_ROOT, os.path.join(_ROOT, 'py_router')):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from net_rescue import _leg_clear, _via_site_clear
from protected_nets import graphic_net_names, protection_map
from kicad_parser import Segment
from routing_config import GridRouteConfig

FAILURES = []


def check(cond, label):
    print(f"  {'PASS' if cond else 'FAIL'}  {label}")
    if not cond:
        FAILURES.append(label)


CONFIG = GridRouteConfig(clearance=0.2, track_width=0.2, via_size=0.6,
                         via_drill=0.3, layers=['F.Cu', 'B.Cu'], grid_step=0.05)
CONFIG.hole_to_hole_clearance = 0.2


def _board(net_id):
    """One horizontal band of foreign copper, as the parser models a pour."""
    band = Segment(start_x=31.6, start_y=14.85, end_x=38.8, end_y=14.85,
                   width=1.0, layer='B.Cu', net_id=net_id,
                   graphic=True, area_fill=True)
    return SimpleNamespace(segments=[band], vias=[], footprints={},
                           pads_by_net={}, zones=[])


def test_via_in_foreign_pour_is_refused():
    pcb = _board(net_id=5)                       # the pour is net 5
    check(not _via_site_clear(pcb, 33.1, 14.9, CONFIG, net_id=21),
          "1: a via inside a foreign pour is refused")
    check(_via_site_clear(pcb, 33.1, 20.0, CONFIG, net_id=21),
          "1b: a via well clear of it is allowed")


def test_leg_through_foreign_pour_is_refused():
    pcb = _board(net_id=5)
    check(not _leg_clear(pcb, [(32.0, 14.9), (34.0, 14.9)], 'B.Cu', 0.2,
                         CONFIG.clearance, net_id=21),
          "2: a leg crossing a foreign pour is refused")
    check(_leg_clear(pcb, [(32.0, 20.0), (34.0, 20.0)], 'B.Cu', 0.2,
                     CONFIG.clearance, net_id=21),
          "2b: a leg well clear of it is allowed")


def test_own_net_copper_is_exempt():
    pcb = _board(net_id=21)                      # the pour is the escape's net
    check(_via_site_clear(pcb, 33.1, 14.9, CONFIG, net_id=21),
          "3: a via landing on its OWN net's pour is allowed")
    check(_leg_clear(pcb, [(32.0, 14.9), (34.0, 14.9)], 'B.Cu', 0.2,
                     CONFIG.clearance, net_id=21),
          "3b: and so is a leg along it")


def _jumper_board():
    """A solder jumper's two custom pads as the parser reads them (from a
    real board): pad 1 (net 1) is a chevron whose tip points into pad 2's
    notch. Its size_x is 2.0, centred on the anchor, so a box model puts
    copper 0.39 mm right of the chevron's real edge away from the tip."""
    pad1 = SimpleNamespace(
        component_ref='JP1', pad_number='1', net_id=1, shape='custom',
        global_x=147.357, global_y=97.79, size_x=2.0, size_y=1.5,
        rect_rotation=0.0, roundrect_rratio=0.0, drill=0.0,
        pad_type='smd', layers=['B.Cu', 'B.Mask'], local_clearance=0.0,
        hole_x=None, hole_y=None,
        polygons=[[(148.357, 97.79), (147.857, 97.04), (146.857, 97.04),
                   (146.857, 98.54), (147.857, 98.54)],
                  [(147.207, 97.64), (147.507, 97.64), (147.507, 97.94),
                   (147.207, 97.94)]])
    pad2 = SimpleNamespace(**{**vars(pad1), 'pad_number': '2', 'net_id': 13,
                              'global_x': 148.807, 'size_x': 1.3,
                              'polygons': []})
    fp = SimpleNamespace(reference='JP1', pads=[pad1, pad2])
    return SimpleNamespace(segments=[], vias=[], footprints={'JP1': fp},
                           pads_by_net={}, zones=[])


def test_dogbone_via_judged_by_real_pad_copper():
    """The dogbone guard judges a foreign pad by its copper, not its box.

    Measured on a reference board: the dogbone via of JP1.2 at (149.3, 97.2),
    1.6 mm, sits 1.112 mm from the centre of JP1.1's chevron, past the 1.05 mm
    the 0.25 mm clearance asks. Upstream places it and the route is DRC-clean.
    _via_site_clear's box model (|dx| - size_x/2) read 0.943 mm and declined
    it, and the net stayed open."""
    cfg = GridRouteConfig(clearance=0.25, track_width=0.5, via_size=1.6,
                          via_drill=0.6, layers=['F.Cu', 'B.Cu'],
                          grid_step=0.1)
    cfg.hole_to_hole_clearance = 0.25
    pcb = _jumper_board()
    check(not _via_site_clear(pcb, 149.3, 97.2, cfg, net_id=13),
          "7: upstream's box model still refuses the site (unchanged)")
    check(_via_site_clear(pcb, 149.3, 97.2, cfg, net_id=13, exact_pads=True),
          "7b: with exact pads the site clears the chevron")
    check(not _via_site_clear(pcb, 149.1, 97.79, cfg, net_id=13,
                              exact_pads=True),
          "7c: with exact pads a via facing the chevron's tip is refused")


def test_dogbone_rung_uses_exact_pads():
    """The fork's dogbone guard asks for exact pads; upstream's #666 escape
    keeps its own call as it is."""
    src = open(os.path.join(_ROOT, 'py_router', 'net_rescue.py')).read()
    i = src.index('dogbone declined')
    window = src[max(0, i - 2500):i]
    check(re.search(r'_via_site_clear\([^)]*exact_pads=True', window)
          is not None,
          "8: the dogbone rung calls _via_site_clear with exact_pads=True")


def test_every_rescue_rung_guards_its_copper():
    """Source invariant: the bug was one rung that appended without asking."""
    src = open(os.path.join(_ROOT, 'py_router', 'net_rescue.py')).read()
    lines = src.split('\n')
    appends = [i for i, l in enumerate(lines)
               if re.search(r'pcb_data\.(segments|vias)\.extend\(', l)]
    check(bool(appends), "4a: the rescue does append copper somewhere")
    unguarded = []
    for i in appends:
        window = '\n'.join(lines[max(0, i - 40):i])
        if '_via_site_clear' not in window and '_leg_clear' not in window:
            unguarded.append(i + 1)
    check(not unguarded,
          "4: every rescue rung checks the escape before keeping it "
          "(unguarded at line(s) %s)" % (unguarded or 'none'))


def test_a_net_made_of_art_is_not_rippable():
    """The rip ladder frees a corridor by removing the blocker's copper. It
    cannot remove art - the writer splices the original file text - so ripping
    such a net leaves the corridor full and the victim routes into it."""
    pcb = _board(net_id=5)
    pcb.nets = {5: SimpleNamespace(name='5V')}
    check('5V' in graphic_net_names(pcb),
          "5: a net whose copper is art is named as such")
    check(protection_map(pcb, None).get('5V') == 'graphic',
          "5b: and the protection map refuses it to the rip ladder")


def test_a_net_of_ordinary_copper_stays_rippable():
    pcb = _board(net_id=5)
    pcb.segments[0].graphic = False
    pcb.segments[0].area_fill = False
    pcb.nets = {5: SimpleNamespace(name='5V')}
    check(not graphic_net_names(pcb),
          "6: ordinary copper leaves its net rippable")


if __name__ == '__main__':
    for fn in (test_via_in_foreign_pour_is_refused,
               test_leg_through_foreign_pour_is_refused,
               test_own_net_copper_is_exempt,
               test_dogbone_via_judged_by_real_pad_copper,
               test_dogbone_rung_uses_exact_pads,
               test_every_rescue_rung_guards_its_copper,
               test_a_net_made_of_art_is_not_rippable,
               test_a_net_of_ordinary_copper_stays_rippable):
        print(fn.__name__)
        fn()
    print()
    if FAILURES:
        print("FAILED: %d" % len(FAILURES))
        for f in FAILURES:
            print("  -", f)
        sys.exit(1)
    print("all checks passed")
