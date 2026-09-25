"""A terminal that sits exactly at the clearance is legal, not a graze.

A 0.4 mm pitch pad row with 0.2 mm pads leaves 0.2 mm between pads. A 0.2 mm
track leaving a pad straight out along its centreline is then exactly 0.2 mm
(the Default class clearance) from both neighbours: legal copper, as KiCad's
DRC grades it. `_neck_terminal_grazes` judged it against the clearance less
1e-4 mm, so it read as a graze; under `--escalation off` a graze that only a
narrower track could clear is refused, and the route failed. Every pin of
such a row failed this way, the whole row unroutable at its own class.

The refusal also reported the wrong distance: the one to foreign tracks and
vias (1e9 mm with none), under the words "OVERLAP a foreign track/via".
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'py_router'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'py_tools'))

from kicad_parser import Segment, parse_kicad_pcb  # noqa: E402
from routing_config import GridRouteConfig  # noqa: E402
import fab_tiers  # noqa: E402
from single_ended_routing import _neck_terminal_grazes  # noqa: E402

# Three pads of a west-facing row, 0.665 x 0.2 mm, 0.4 mm apart, at x = 100.
BOARD = """(kicad_pcb (version 20240108) (generator test)
  (layers
    (0 "F.Cu" signal)
    (31 "B.Cu" signal)
    (44 "Edge.Cuts" user)
  )
  (net 0 "")
  (net 1 "A")
  (net 2 "B")
  (net 3 "C")
  (gr_line (start 90 90) (end 110 90) (layer "Edge.Cuts") (width 0.1))
  (gr_line (start 110 90) (end 110 110) (layer "Edge.Cuts") (width 0.1))
  (gr_line (start 110 110) (end 90 110) (layer "Edge.Cuts") (width 0.1))
  (gr_line (start 90 110) (end 90 90) (layer "Edge.Cuts") (width 0.1))
  (footprint "test:ROW" (at 100 100) (layer "F.Cu")
    (pad "1" smd rect (at 0 -0.4) (size 0.665 0.2) (layers "F.Cu") (net 1 "A"))
    (pad "2" smd rect (at 0 0) (size 0.665 0.2) (layers "F.Cu") (net 2 "B"))
    (pad "3" smd rect (at 0 0.4) (size 0.665 0.2) (layers "F.Cu") (net 3 "C"))
  )
)
"""


def _parse(text):
    with tempfile.NamedTemporaryFile(suffix='.kicad_pcb', mode='w', delete=False) as f:
        f.write(text)
        path = f.name
    try:
        return parse_kicad_pcb(path)
    finally:
        os.unlink(path)


def _terminal(x_end):
    """Pad 2's terminal: from its centre straight out west, 0.2 mm wide."""
    return Segment(start_x=100.0, start_y=100.0, end_x=x_end, end_y=100.0, width=0.2, layer='F.Cu', net_id=2)


def _neck(segment):
    pcb = _parse(BOARD)
    config = GridRouteConfig(track_width=0.2, clearance=0.2, grid_step=0.1)
    prev = fab_tiers.get_escalation_policy()
    fab_tiers.set_escalation_policy('off')
    try:
        return _neck_terminal_grazes([segment], [(100.0, 100.0)], pcb, 2, config)
    finally:
        fab_tiers.set_escalation_policy(*prev)


def test_a_terminal_exactly_at_the_clearance_is_not_refused():
    necked, hard = _neck(_terminal(98.0))
    assert (necked, hard) == (0, [])


def test_a_terminal_closer_than_the_clearance_is_still_refused():
    seg = _terminal(98.0)
    seg.width = 0.25                    # 0.175 mm from each neighbour: a graze only a neck could clear
    necked, hard = _neck(seg)
    assert necked == 0 and len(hard) == 1


if __name__ == '__main__':
    test_a_terminal_exactly_at_the_clearance_is_not_refused()
    test_a_terminal_closer_than_the_clearance_is_still_refused()
    print("PASS")
