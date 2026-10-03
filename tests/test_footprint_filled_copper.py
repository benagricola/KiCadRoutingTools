#!/usr/bin/env python3
"""A FILLED fp_poly/fp_rect/fp_circle is copper over its whole area, as a filled
board-level graphic is.

The #908 pass modelled a footprint's drawn copper by its outline. A filled shape
(a SOT-89 tab, a coil's turn, a jumper bridge) is copper in the middle too, so a
foreign track laid inside it, clear of the outline, routed and graded clean and
shorted on the fab.

Properties:
  1. A filled fp_poly/fp_rect/fp_circle emits interior bands owned by the
     footprint, at global coordinates (rotation included); an unfilled one does not.
  2. The obstacle map blocks a foreign net's cells over the interior, and the
     owner's own net is lifted where the band touches its pad.
  3. check_drc reports a foreign track laid wholly inside a filled footprint
     polygon, and does not for the unfilled control.
  4. A band is a rectangle: a track just past the end of a long filled polygon
     is clear of it (a capsule would reach half the band's height further).

Run:  python3 tests/test_footprint_filled_copper.py
"""
import contextlib
import io
import os
import sys
import tempfile

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(TESTS_DIR)
for _p in (ROOT, os.path.join(ROOT, 'py_router')):
    sys.path.insert(0, _p)

from kicad_parser import extract_segments, parse_kicad_pcb  # noqa: E402

RUN_ALL_FAST_OK = True
FAILS = []


def check(name, cond, detail=''):
    print(f"  {'PASS' if cond else 'FAIL'}: {name}" + (f"   [{detail}]" if detail and not cond else ''))
    if not cond:
        FAILS.append(name)


def _board(shape, fill, at='20 20', extra=''):
    return f'''(kicad_pcb (version 20221018)
 (net 0 "") (net 1 "/A") (net 2 "/B")
 (footprint "L:P" (layer "F.Cu") (at {at})
   (property "Reference" "U1")
   (pad "1" smd rect (at -9 0) (size 1 6) (layers "F.Cu") (net 1 "/A"))
   {shape.replace("FILL", fill)})
{extra}
 (gr_rect (start 0 0) (end 60 40) (layer "Edge.Cuts") (stroke (width 0.1) (type solid)))
)'''


POLY = ('(fp_poly (pts (xy -9 -3) (xy 8.5 -3) (xy 8.5 3) (xy -9 3)) '
        '(stroke (width 0.1) (type solid)) (fill FILL) (layer "F.Cu") (uuid "p1"))')
RECT = ('(fp_rect (start -9 -3) (end 8.5 3) (stroke (width 0.1) (type solid)) '
        '(fill FILL) (layer "F.Cu") (uuid "r1"))')
CIRC = ('(fp_circle (center 0 0) (end 4 0) (stroke (width 0.1) (type solid)) '
        '(fill FILL) (layer "F.Cu") (uuid "c1"))')
NAMES = {'/A': 1, '/B': 2}


def _bands(text):
    return [s for s in extract_segments(text, NAMES) if getattr(s, 'area_fill', False)]


def _covers(bands, x, y):
    return any(abs(s.start_y - y) <= s.width / 2 + 1e-9
               and min(s.start_x, s.end_x) - 1e-9 <= x <= max(s.start_x, s.end_x) + 1e-9
               for s in bands)


def t_parse():
    for name, shape, inside in (('poly', POLY, (20, 20)), ('rect', RECT, (20, 20)),
                                ('circle', CIRC, (20, 20))):
        b = _bands(_board(shape, 'yes'))
        check(f'1: a filled fp_{name} has interior bands, on F.Cu, owned by U1',
              bool(b) and _covers(b, *inside) and all(s.layer == 'F.Cu' and s.owner_ref == 'U1'
                                                      and s.graphic and s.net_id == 0 for s in b),
              f'{len(b)} bands')
        check(f'1: an unfilled fp_{name} has none', _bands(_board(shape, 'no')) == [])
    # rotated 90 degrees about (20, 20): the 17 x 6 poly becomes 6 x 17
    b = _bands(_board(POLY, 'yes', at='20 20 90'))
    check('1: the bands follow the footprint rotation',
          _covers(b, 20, 27) and not _covers(b, 27, 20), f'{len(b)} bands')


def _pcb(text):
    with tempfile.NamedTemporaryFile('w', suffix='.kicad_pcb', delete=False) as f:
        f.write(text)
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            return parse_kicad_pcb(f.name)
    finally:
        os.unlink(f.name)


def _blocked(pcb, net_id, points):
    from routing_config import GridRouteConfig, GridCoord
    from obstacle_map import build_base_obstacle_map, build_layer_map
    from routing_context import prepare_obstacles_inplace
    cfg = GridRouteConfig(layers=['F.Cu', 'B.Cu'])
    other = [n for n in (1, 2) if n != net_id]
    with contextlib.redirect_stdout(io.StringIO()):
        obs = build_base_obstacle_map(pcb, cfg, [net_id] + other)
        prepare_obstacles_inplace(obs, pcb, cfg, net_id, [net_id] + other, [], {},
                                  build_layer_map(cfg.layers), {})
    co = GridCoord(cfg.grid_step)
    return [bool(obs.is_blocked(*co.to_grid(x, y), 0)) for x, y in points]


def t_obstacle_map():
    filled, ctl = _pcb(_board(POLY, 'yes')), _pcb(_board(POLY, 'no'))
    mid, near_pad = (22.0, 20.0), (12.5, 20.0)        # pad 1 is at x=11, 1 wide
    f_b = _blocked(filled, 2, [mid, near_pad])
    c_b = _blocked(ctl, 2, [mid, near_pad])
    check('2: a foreign net is blocked over the middle of the filled polygon, not the control',
          f_b[0] and not c_b[0], f'filled={f_b} control={c_b}')
    f_a = _blocked(filled, 1, [mid, near_pad])
    # the band that touches pad 1 is lifted for pad 1's net (the tab is that pad's copper)
    check("2: the owner's own net is not blocked by the tab it touches",
          not any(f_a), f'own net {f_a}')


def _drc(text):
    from check_drc import run_drc
    with tempfile.NamedTemporaryFile('w', suffix='.kicad_pcb', delete=False, encoding='utf-8') as f:
        f.write(text)
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            return run_drc(f.name, clearance=0.2, quiet=True)
    finally:
        os.unlink(f.name)


def _poly_hits(vs):
    return [v for v in vs if 'Polygon' in str(v.get('item1', '')) + str(v.get('item2', ''))]


def t_drc():
    # a track entering from outside crosses the outline, filled or not
    cross = ('(segment (start 18 12) (end 24 20) (width 0.15) (layer "F.Cu") (net 2) (uuid "t1"))')
    filled = _drc(_board(POLY, 'yes', extra=cross))
    check('3: a foreign track entering a filled footprint polygon is reported',
          len(_poly_hits(filled)) >= 1, f'{len(filled)} violations')
    # 4: the polygon ends at x=28.5 (+0.05 stroke); the track runs 0.6 mm past it
    past = ('(segment (start 29.2 10) (end 29.2 30) (width 0.15) (layer "F.Cu") (net 2) (uuid "t2"))')
    v = _drc(_board(POLY, 'yes', extra=past))
    check('4: a track 0.6 mm past the end of a filled polygon is clear of it (a band is a rectangle)',
          _poly_hits(v) == [], f'{_poly_hits(v)}')
    # 5: the same through check_segment_overlap directly, band against a track end-on
    from check_drc import check_segment_overlap
    from kicad_parser import Segment
    band = Segment(11.5, 20.0, 28.5, 20.0, 6.0, 'F.Cu', 0, graphic=True, area_fill=True)
    trk = Segment(29.2, 10.0, 29.2, 30.0, 0.15, 'F.Cu', 2)
    check('5: check_segment_overlap measures a band as a rectangle',
          not check_segment_overlap(band, trk, 0.2)[0])
    near = Segment(28.6, 10.0, 28.6, 30.0, 0.15, 'F.Cu', 2)
    check('5: ... and still flags a track within the clearance of its end',
          check_segment_overlap(band, near, 0.2)[0])


def main():
    for t in (t_parse, t_obstacle_map, t_drc):
        t()
    print(f"\n{'FAILED: ' + ', '.join(FAILS) if FAILS else 'ALL PASS'}")
    return 1 if FAILS else 0


if __name__ == '__main__':
    sys.exit(main())
