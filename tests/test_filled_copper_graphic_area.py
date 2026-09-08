#!/usr/bin/env python3
"""A FILLED copper graphic is copper over its whole area, not just its edge.

The parser modelled a filled gr_poly/gr_rect/gr_circle by its outline alone, so
its interior read as free board. KiCad does not agree: it fills the shape, joins
pads through it, and reports a clearance/short violation against it. The gap
showed up as a router laying a foreign net straight across a pour and the board's
own DRC then failing.

Properties:
  1. A filled shape puts copper in the MIDDLE, not only on the rim.
  2. An unfilled shape does not - its stroke is all there is.
  3. The interior segments carry the shape's net and layer, and are graphic
     (immutable input art: never ripped, pruned or written back).
  4. Scanline bands abut, so the union has no unmodelled stripe through it.
  5. gr_rect and gr_circle behave the same as gr_poly.

Run:  python3 tests/test_filled_copper_graphic_area.py
"""

import os
import sys

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_TESTS_DIR)
for _p in (_ROOT, os.path.join(_ROOT, 'py_router')):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from kicad_parser import extract_segments, filled_area_spans, Segment, Pad
from check_connected import check_net_connectivity, conducts
import routing_defaults as defaults

NAME_TO_ID = {'GNDS': 7, 'SIG': 3}
FAILURES = []
QUIET_FAILURES = []


def check_quiet(cond):
    if not cond:
        QUIET_FAILURES.append(cond)


def check(cond, label):
    print(f"  {'PASS' if cond else 'FAIL'}  {label}")
    if not cond:
        FAILURES.append(label)


def _poly(fill):
    return f'''
    (gr_poly (pts (xy 10 10) (xy 20 10) (xy 20 20) (xy 10 20))
        (stroke (width 0.2) (type solid)) (fill {fill})
        (layer "F.Cu") (net "GNDS") (uuid "aa"))
'''


def _covers(segs, x, y):
    """Is (x, y) inside the band of some horizontal segment?"""
    for s in segs:
        if abs(s.start_y - y) <= s.width / 2 + 1e-9 and abs(s.end_y - s.start_y) < 1e-9:
            if min(s.start_x, s.end_x) - 1e-9 <= x <= max(s.start_x, s.end_x) + 1e-9:
                return True
    return False


def test_filled_covers_its_middle():
    segs = [s for s in extract_segments(_poly('yes'), NAME_TO_ID)
            if getattr(s, 'graphic', False)]
    check(_covers(segs, 15.0, 15.0), "1: a filled 10x10 poly has copper at its centre")
    check(all(s.net_id == 7 for s in segs), "3a: every segment carries the shape's net")
    check(all(s.layer == 'F.Cu' for s in segs), "3b: every segment is on the shape's layer")
    check(all(getattr(s, 'graphic', False) for s in segs), "3c: all tagged graphic")


def test_unfilled_does_not():
    segs = [s for s in extract_segments(_poly('no'), NAME_TO_ID)
            if getattr(s, 'graphic', False)]
    check(not _covers(segs, 15.0, 15.0), "2: an unfilled poly leaves its middle empty")
    check(len(segs) == 4, "2b: an unfilled quad is its four edges and nothing else")


def test_bands_merge_and_cover():
    """A rectangle is ONE band however tall it is: without the run-length merge
    a pour costs a segment per 0.1 mm and the obstacle map stalls."""
    bands = filled_area_spans([(0, 0), (10, 0), (10, 10), (0, 10)], defaults.GRID_STEP)
    check(len(bands) == 1, "4: a rectangle merges to a single band (got %d)" % len(bands))
    x0, x1, yc, h = bands[0]
    check(abs(x0) < 1e-9 and abs(x1 - 10) < 1e-9, "4b: the band spans the full width")
    check(abs(yc - 5.0) < 1e-9 and abs(h - 10.0) < 1e-9,
          "4c: and the full height, centred")


def test_merging_never_over_blocks():
    """Merging rounds a band OUTWARD to the widest span in its run, so the
    tolerance is also the bound on how far the model may over-block. A slope
    steeper than the tolerance simply does not merge."""
    tol = defaults.GRID_STEP / 10.0
    pts = [(0, 0), (20, 0), (0, 20)]          # a 45-degree edge, the worst case
    for x0, x1, yc, h in filled_area_spans(pts, defaults.GRID_STEP):
        # the triangle's hypotenuse runs x = 20 - y; the widest legal span
        # anywhere in this band is at its lowest y
        widest = 20.0 - (yc - h / 2.0)
        check_quiet(x1 <= widest + tol + 1e-9)
    check(not QUIET_FAILURES, "4d: no band reaches past the shape by more than the tolerance")


def test_concave_polygon_is_not_bridged():
    """An L: the notch is outside the shape and must stay unmodelled."""
    pts = [(0, 0), (10, 0), (10, 4), (4, 4), (4, 10), (0, 10)]
    bands = filled_area_spans(pts, 0.5)
    inside = any(abs(yc - 2.0) <= h / 2 and x0 <= 8.0 <= x1 for x0, x1, yc, h in bands)
    notch = any(abs(yc - 8.0) <= h / 2 and x0 <= 8.0 <= x1 for x0, x1, yc, h in bands)
    check(inside, "5a: a point inside the L's foot is covered")
    check(not notch, "5b: the L's notch is not covered")


def test_rect_and_circle():
    rect = '''
    (gr_rect (start 0 0) (end 10 10) (stroke (width 0.1) (type solid))
        (fill yes) (layer "B.Cu") (net "SIG") (uuid "bb"))
'''
    circ = '''
    (gr_circle (center 0 0) (end 5 0) (stroke (width 0.1) (type solid))
        (fill yes) (layer "B.Cu") (net "SIG") (uuid "cc"))
'''
    rs = [s for s in extract_segments(rect, NAME_TO_ID) if getattr(s, 'graphic', False)]
    cs = [s for s in extract_segments(circ, NAME_TO_ID) if getattr(s, 'graphic', False)]
    check(_covers(rs, 5.0, 5.0), "6a: a filled gr_rect covers its middle")
    check(_covers(cs, 0.0, 0.0), "6b: a filled gr_circle covers its middle")
    check(not _covers(cs, 4.9, 4.9), "6c: and not the corner outside the disc")


def test_filled_area_conducts_unfilled_does_not():
    """KiCad joins pads through a filled net-tagged polygon, so this model has
    to as well - and must still refuse to join through unfilled art, whose
    shape it does not have."""
    fill = [s for s in extract_segments(_poly('yes'), NAME_TO_ID)
            if getattr(s, 'area_fill', False)]
    stroke = [s for s in extract_segments(_poly('no'), NAME_TO_ID)
              if getattr(s, 'graphic', False)]
    check(bool(fill) and all(conducts(s) for s in fill),
          "7: a filled shape's interior bands conduct")
    check(bool(stroke) and not any(conducts(s) for s in stroke),
          "7b: unfilled art still does not conduct")


def test_pads_join_through_a_filled_pour():
    """Two pads inside one filled polygon and nothing else: one cluster."""
    segs = [s for s in extract_segments(_poly('yes'), NAME_TO_ID)
            if getattr(s, 'graphic', False)]
    def _pad(ref, x):
        return Pad(component_ref=ref, pad_number='1', global_x=x, global_y=15.0,
                   local_x=0.0, local_y=0.0, size_x=1.0, size_y=1.0,
                   shape='rect', layers=['F.Cu'], net_id=7, net_name='GNDS')
    pads = [_pad('R1', 12.0), _pad('R2', 18.0)]
    r = check_net_connectivity(7, segs, [], pads)
    check(r.get('connected') is True,
          "8: two pads inside one filled pour read as connected (got %r)"
          % (r.get('connected'),))


if __name__ == '__main__':
    for fn in (test_filled_covers_its_middle, test_unfilled_does_not,
               test_bands_merge_and_cover, test_merging_never_over_blocks,
               test_concave_polygon_is_not_bridged, test_rect_and_circle,
               test_filled_area_conducts_unfilled_does_not,
               test_pads_join_through_a_filled_pour):
        print(fn.__name__)
        fn()
    print()
    if FAILURES:
        print("FAILED: %d" % len(FAILURES))
        for f in FAILURES:
            print("  -", f)
        sys.exit(1)
    print("all checks passed")
