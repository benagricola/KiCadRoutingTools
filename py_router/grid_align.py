"""Grid alignment (docs/off-grid-exact-fit-design.md, part 1).

At minimum pitch the only legal straight lane out of a pin is on the pin's
own centre line, so a fine-pitch row routes only when its centre lines fall
on grid lines. The grid's origin is the board's (GridCoord rounds from
zero), so `aligning_offset` picks the sub-grid translation of the whole
board that puts the most row pins' centre lines on the grid; the board is
routed translated and the result translated back.
"""
from __future__ import annotations

from typing import Dict, Tuple

from fan_order import find_fan_rows

_NM = 1_000_000          # nanometres per mm: residues are exact in whole nm


def aligning_offset(pcb_data, grid_step: float, max_pitch: float) -> Tuple[float, float]:
    """(dx, dy) in mm, each in [0, grid_step) and whole nanometres: the
    translation that puts the most fine-pitch row pins' centre lines on the
    grid. Per axis, each row pin votes for its centre line's residue modulo
    the grid; the most voted residue is moved to zero. Rows not along x or
    y are not counted; no rows gives (0, 0)."""
    step = round(grid_step * _NM)
    votes: Tuple[Dict[int, int], Dict[int, int]] = ({}, {})
    for row in find_fan_rows(pcb_data, max_pitch):
        ax, ay = row.axis
        if abs(abs(ax) - 1.0) < 1e-6:
            axis = 0            # a row along x: its lanes run along y, at the pads' x
        elif abs(abs(ay) - 1.0) < 1e-6:
            axis = 1
        else:
            continue
        for p in row.pads:
            c = p.global_x if axis == 0 else p.global_y
            r = round(c * _NM) % step
            votes[axis][r] = votes[axis][r] + 1 if r in votes[axis] else 1
    out = []
    for v in votes:
        if not v:
            out.append(0.0)
            continue
        r = max(sorted(v), key=lambda k: v[k])      # ties: the smallest residue
        out.append(((step - r) % step) / _NM)
    return out[0], out[1]
