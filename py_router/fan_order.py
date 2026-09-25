"""Row fan order (docs/row-fan-order-design.md): nets leaving a fine-pitch
pin row are routed outside-in along the row, the way a person fans a row of
pins out -- the outermost turn first, so each lane can lie beside the one
routed before it.

`find_fan_rows` locates the rows; `fan_order` re-sequences a base net order
(route.py's `(name, id)` pairs) so each row's nets occupy the base order's
slot of their first net, resequenced within it: the pins fanning toward one
end of the row, from that end inward; the pins fanning toward the other end,
from that end inward; the pins going straight ahead last.

Ported from the accepted prototype (scratchpad fan/fan_order.py): its default
"block" mode, with the chip-to-chip carve-out always on. The prototype's
"slots" and "others_first" modes measured worse on the cap sweep and were
dropped (see the design doc's Findings).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Tuple

from kicad_parser import Pad, PCBData


@dataclass
class FanRow:
    """One fine-pitch pin row: pads of one footprint, in a line, alike in
    size and turn, three or more, at most `max_pitch` apart."""
    ref: str
    pads: List[Pad]                # in order along the row's axis
    axis: Tuple[float, float]      # unit vector along the row, global
    normal: Tuple[float, float]    # unit vector pointing outward, global
    pitch: float                   # mm, the row's own (minimum) pad spacing


def _rotate(vx: float, vy: float, rotation_deg: float) -> Tuple[float, float]:
    """A LOCAL direction vector, turned into GLOBAL board coordinates by the
    same convention kicad_parser.local_to_global uses for positions."""
    rad = math.radians(-rotation_deg)
    c, s = math.cos(rad), math.sin(rad)
    return (vx * c - vy * s, vx * s + vy * c)


def find_fan_rows(pcb_data: PCBData, max_pitch: float) -> List[FanRow]:
    """Every fine-pitch row on the board.

    Works in the footprint's LOCAL frame (rotation-safe, the same footprint-
    local edge classification qfn_fanout.layout uses): a pad long across its
    own axis (size_x >= size_y) sits on a row running along local y, grouped
    by the pads sharing its local x; a pad long the other way sits on a row
    along local x, grouped by shared local y. One footprint can carry more
    than one row (e.g. a QFN's top and bottom edges).
    """
    rows: List[FanRow] = []
    for ref, fp in pcb_data.footprints.items():
        pads = fp.pads
        if len(pads) < 3:
            continue
        groups: Dict[Tuple[str, float], List[Pad]] = {}
        for p in pads:
            if p.size_x >= p.size_y:
                key = ('y', round(p.local_x, 4))
            else:
                key = ('x', round(p.local_y, 4))
            groups.setdefault(key, []).append(p)
        center_x = sum(p.local_x for p in pads) / len(pads)
        center_y = sum(p.local_y for p in pads) / len(pads)
        for (kind, coord), group in groups.items():
            if len(group) < 3:
                continue
            if kind == 'y':
                group.sort(key=lambda p: p.local_y)
                gaps = [b.local_y - a.local_y for a, b in zip(group, group[1:])]
                l_axis = (0.0, 1.0)
                l_normal = (1.0 if coord >= center_x else -1.0, 0.0)
            else:
                group.sort(key=lambda p: p.local_x)
                gaps = [b.local_x - a.local_x for a, b in zip(group, group[1:])]
                l_axis = (1.0, 0.0)
                l_normal = (0.0, 1.0 if coord >= center_y else -1.0)
            if not gaps:
                continue
            pitch = min(gaps)
            if pitch <= 1e-9 or pitch > max_pitch + 1e-9:
                continue
            axis = _rotate(l_axis[0], l_axis[1], fp.rotation)
            normal = _rotate(l_normal[0], l_normal[1], fp.rotation)
            rows.append(FanRow(ref=ref, pads=list(group), axis=axis,
                               normal=normal, pitch=pitch))
    return rows


def fan_order(pcb_data: PCBData, net_ids: List[Tuple[str, int]],
              max_pitch: float) -> List[Tuple[str, int]]:
    """`net_ids` ((name, id) pairs, route.py's base order) with each fine-
    pitch row's nets re-sequenced in place. Non-row nets keep their base
    position; a row's nets occupy the base order's slot of their first net.
    """
    rows = find_fan_rows(pcb_data, max_pitch)
    if not rows:
        return list(net_ids)

    base_id_set = {nid for _name, nid in net_ids}
    name_of = {nid: name for name, nid in net_ids}
    chip_refs = {row.ref for row in rows}

    # A net touching more than one row is sequenced by the FINER row (the
    # one with less room, whose order matters more).
    row_of_net: Dict[int, int] = {}
    for ri, row in enumerate(rows):
        for p in row.pads:
            prev = row_of_net.get(p.net_id)
            if prev is None or rows[prev].pitch > row.pitch:
                row_of_net[p.net_id] = ri

    seqs: Dict[int, List[int]] = {}
    for ri, row in enumerate(rows):
        toward_neg: List[Tuple[float, int]] = []
        toward_pos: List[Tuple[float, int]] = []
        ahead: List[Tuple[float, int]] = []
        for p in row.pads:
            if row_of_net.get(p.net_id) != ri or p.net_id not in base_id_set:
                continue
            other_pads = pcb_data.pads_by_net.get(p.net_id, [])
            # A net with more than two pads (a rail, a bus tap) has no one
            # other end to fan toward: it keeps its base-order place, and
            # does not pull the row's block to its own slot.
            if len(other_pads) > 2:
                continue
            # Chip to chip: a net with a pad on ANOTHER chip's row keeps its
            # base-order place -- MPS already sequences it by where both
            # ends sit (docs/row-fan-order-design.md).
            if any(q.component_ref in chip_refs and q.component_ref != row.ref
                   for q in other_pads):
                continue
            targets = [q for q in other_pads
                      if q is not p and q.component_ref != row.ref]
            if not targets:
                targets = [q for q in other_pads if q is not p]
            if not targets:
                continue
            tx = sum(q.global_x for q in targets) / len(targets)
            ty = sum(q.global_y for q in targets) / len(targets)
            a_pin = p.global_x * row.axis[0] + p.global_y * row.axis[1]
            a_tgt = tx * row.axis[0] + ty * row.axis[1]
            if a_tgt < a_pin - row.pitch:
                toward_neg.append((a_pin, p.net_id))
            elif a_tgt > a_pin + row.pitch:
                toward_pos.append((-a_pin, p.net_id))
            else:
                ahead.append((a_pin, p.net_id))
        seqs[ri] = ([nid for _, nid in sorted(toward_neg)]
                    + [nid for _, nid in sorted(toward_pos)]
                    + [nid for _, nid in sorted(ahead)])

    out: List[Tuple[str, int]] = []
    placed_rows = set()
    for name, nid in net_ids:
        ri = row_of_net.get(nid)
        if ri is not None and nid in seqs.get(ri, ()):
            if ri in placed_rows:
                continue
            placed_rows.add(ri)
            out += [(name_of[n], n) for n in seqs[ri]]
        else:
            out.append((name, nid))
    return out
