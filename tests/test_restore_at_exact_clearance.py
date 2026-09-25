"""A ripped net's saved copper exactly at the clearance restores (#134 check).

_saved_route_colliders refuses a restore when the saved copper would sit
nearer other-net copper than the clearance. It compared squared distances
with a strict `<` and no tie tolerance, so copper exactly at the rule --
legal, and common once pads are stamped exact (the corner move check) --
could read as a short from float rounding alone: measured on glasgow_revC's
IO_Buffer_B subset, a via 0.3000 mm (centre) from a track, at a 0.3000 mm
limit, was refused and the net was left with a pad unconnected. The check
now carries the same 1e-6 mm tie tolerance as the grid rasterisers.
"""
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'py_router'))

from kicad_parser import Segment, Via  # noqa: E402
from rip_up_reroute import _saved_route_colliders  # noqa: E402

CLEARANCE = 0.1


def _case(via_y):
    """A saved via (0.3 mm) of net 1 at (113.6, via_y), and net 2's 0.1 mm
    track along y = 106.9: the limit is 0.15 + 0.05 + 0.1 = 0.3 mm."""
    via = Via(x=113.6, y=via_y, size=0.3, drill=0.2, layers=['F.Cu', 'B.Cu'], net_id=1)
    track = Segment(start_x=114.5, start_y=106.9, end_x=112.9, end_y=106.9, width=0.1, layer='F.Cu', net_id=2)
    pcb = SimpleNamespace(segments=[track], vias=[])
    return _saved_route_colliders({'new_segments': [], 'new_vias': [via]}, pcb, [1], CLEARANCE)


def test_copper_exactly_at_the_clearance_is_not_a_short():
    assert _case(106.6) == []
    assert _case(106.9 - 0.3 + 1e-9) == []      # within float noise of the rule


def test_copper_inside_the_clearance_still_is():
    assert len(_case(106.9 - 0.3 + 1e-3)) == 1


if __name__ == '__main__':
    test_copper_exactly_at_the_clearance_is_not_a_short()
    test_copper_inside_the_clearance_still_is()
    print("PASS")
