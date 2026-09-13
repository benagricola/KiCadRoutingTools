#!/usr/bin/env python3
"""A filled copper graphic's interior bands block a RECTANGLE, not a capsule.

The interior of a filled gr_poly is modelled as run-length merged scanline
bands, each a Segment whose `width` is the band's height. The obstacle map
stamped every segment as a capsule expanded by half its width in every
direction, so a 12 x 200 mm pour became a band with 100 mm round caps and
blanketed a board 40 mm away from it: every net on that board read "boxed
in by static obstacles" and each failed at 0.5 s per iteration.

Properties:
  1. A cell inside the pour is blocked.
  2. A cell beside the pour, further away than the clearance, is free -
     however tall the pour is.
  3. A cell just past the pour's top or bottom edge, beyond the clearance,
     is free: the band's ends are square, not round.
  4. The same holds for via blocking.
  5. The terminal-graze distance to a band is a rectangle distance: a point
     beside a tall band is as far from it as it is from its edge, and a
     point inside it is inside by the nearest edge.
  6. The blame map (which net boxed a failed search in) stamps the same
     rectangle, so a band never gets blamed for cells it does not block.

Run:  python3 tests/test_filled_graphic_band_no_caps.py
"""
import os
import sys

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(TESTS_DIR)
sys.path.insert(0, ROOT_DIR)
sys.path.insert(0, os.path.join(ROOT_DIR, 'py_router'))
sys.path.insert(0, os.path.join(ROOT_DIR, 'py_tools'))

from kicad_parser import PCBData, Segment, Net, BoardInfo
from routing_config import GridRouteConfig
from obstacle_map import build_base_obstacle_map
from single_ended_routing import _foreign_edge_dist
from blocking_analysis import compute_net_obstacle_cells, _unpack_xy
import numpy as np

FAILS = []


def check(name, cond):
    print(f"  {'PASS' if cond else 'FAIL'}: {name}")
    if not cond:
        FAILS.append(name)


def main():
    cfg = GridRouteConfig()
    cfg.layers = ['F.Cu', 'B.Cu']
    cfg.grid_step = 0.1
    cfg.track_width = 0.2
    cfg.clearance = 0.2
    cfg.via_size = 0.6
    bi = BoardInfo(layers={0: 'F.Cu', 31: 'B.Cu'}, copper_layers=cfg.layers,
                   board_bounds=(0.0, 0.0, 60.0, 260.0))
    # one band: a 12 mm wide, 200 mm tall pour on net 2, centred on x=30
    band = Segment(start_x=24.0, start_y=110.0, end_x=36.0, end_y=110.0, width=200.0,
                   layer='F.Cu', net_id=2, graphic=True, area_fill=True)
    pcb = PCBData(board_info=bi, nets={1: Net(1, 'SIG'), 2: Net(2, 'POUR')}, footprints={},
                  vias=[], segments=[band], pads_by_net={})
    obs = build_base_obstacle_map(pcb, cfg, [1])

    def blocked(x_mm, y_mm):
        return obs.is_blocked(int(round(x_mm / cfg.grid_step)), int(round(y_mm / cfg.grid_step)), 0)

    def via_blocked(x_mm, y_mm):
        return obs.is_via_blocked(int(round(x_mm / cfg.grid_step)), int(round(y_mm / cfg.grid_step)))

    print("filled band as a rectangle")
    check("1: inside the pour is blocked", blocked(30.0, 110.0))
    check("2a: 5 mm beside the pour is free", not blocked(19.0, 110.0))
    check("2b: 20 mm beside the pour is free (was the capped region)", not blocked(10.0, 110.0))
    check("2c: 20 mm beside the pour, at its top, is free", not blocked(10.0, 12.0))
    check("3a: 1 mm above the pour's top edge is free", not blocked(30.0, 9.0))
    check("3b: 1 mm below the pour's bottom edge is free", not blocked(30.0, 211.0))
    check("3c: just inside the top edge is blocked", blocked(30.0, 10.5))
    check("4a: a via 20 mm beside the pour is free", not via_blocked(10.0, 110.0))
    check("4b: a via inside the pour is blocked", via_blocked(30.0, 110.0))

    print("edge distance to a band")
    ax, ay, bx, by = np.array([24.0]), np.array([110.0]), np.array([36.0]), np.array([110.0])
    hw, fill = np.array([100.0]), np.array([True])
    d, _, _ = _foreign_edge_dist(np.array([10.0]), np.array([110.0]), ax, ay, bx, by, hw, fill)
    check("5a: 14 mm beside the band reads 14 mm (a capsule read -86)", abs(d[0, 0] - 14.0) < 1e-9)
    d, _, _ = _foreign_edge_dist(np.array([30.0]), np.array([5.0]), ax, ay, bx, by, hw, fill)
    check("5b: 5 mm above the band's top edge reads 5 mm", abs(d[0, 0] - 5.0) < 1e-9)
    d, _, _ = _foreign_edge_dist(np.array([25.0]), np.array([110.0]), ax, ay, bx, by, hw, fill)
    check("5c: 1 mm inside the band's left edge reads -1 mm", abs(d[0, 0] + 1.0) < 1e-9)
    d, _, _ = _foreign_edge_dist(np.array([10.0]), np.array([110.0]), ax, ay, bx, by, hw, np.array([False]))
    check("5d: the same geometry as a capsule still reads as a capsule", abs(d[0, 0] + 86.0) < 1e-9)
    print("blame map stamps a band as a rectangle")
    keys, _ = compute_net_obstacle_cells(pcb, 2, None, cfg)
    gx, gy = _unpack_xy(keys)
    blamed = set(zip(gx.tolist(), gy.tolist()))

    def blamed_at(x_mm, y_mm):
        return (int(round(x_mm / cfg.grid_step)), int(round(y_mm / cfg.grid_step))) in blamed
    check("6a: inside the pour is blamed", blamed_at(30.0, 110.0))
    check("6b: 20 mm beside the pour is not blamed", not blamed_at(10.0, 110.0))
    check("6c: 1 mm above the pour's top edge is not blamed", not blamed_at(30.0, 9.0))
    if FAILS:
        print("\nFAILED: %d" % len(FAILS))
        sys.exit(1)
    print("\nALL PASS")


if __name__ == '__main__':
    main()
