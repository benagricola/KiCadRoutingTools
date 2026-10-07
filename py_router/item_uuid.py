"""Uuids for the items the router writes, the same in every run on the same board.

FORK DIVERGENCE (placemat): upstream mints uuid.uuid4() for every segment,
via, zone and drawing kicad_writer.py writes. KiCad orders and tie-breaks on
KIIDs - the order a loaded board hands out its tracks in, which of two items
a DRC marker names, overlapping zones' fill (see zone_overlap_priorities) -
so the same routed copper graded differently from run to run, and placemat's
reference set, which compares one run with another, needs the router's
output to be the same in every run. The entry for this divergence is in
docs/fork-divergences.md on the branch placemat/connections (the base
branch has no divergence list).

An item's uuid is uuid5 of the seed, the item's text and how many items of
that same text this process has stamped before. The seed is set from each
board the parser reads (`seed_from_board`): its lines with every uuid-shaped
token taken out (item uuids, a group's member list, legacy 8-hex tstamps),
sorted, so the input's own ids and block order do not change it, and a
later run on a board that already holds an item of the same text stamps it
a different uuid. add_tracks_to_pcb and add_tracks_and_vias_to_pcb seed from
the board they write into. A board read through pcbnew
(build_pcb_data_from_board) seeds from its tracks, vias and footprints
instead (`seed_from_items`).
`stamp` before any board is read raises: a seed shared by
every board would give two boards' new items the same uuids.
"""
from __future__ import annotations

import collections
import hashlib
import re
import uuid

PLACEHOLDER = '__KRT_ITEM_UUID__'

_NAMESPACE = uuid.UUID('6f1b6a52-6d2c-5e8e-9a63-0c2a4b1f7d10')
_ID_RE = re.compile(r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}'
                    r'|\(tstamp\s+"?[0-9a-fA-F]{8}"?\)')

_seed = None
_stamped: collections.Counter = collections.Counter()


def seed_from_board(content: str) -> None:
    """Set the seed from a board's text, its uuids and line order left out."""
    global _seed
    lines = sorted(_ID_RE.sub('', line).strip() for line in content.splitlines())
    _seed = hashlib.sha256('\n'.join(lines).encode('utf-8')).hexdigest()


def seed_from_items(lines) -> None:
    """Set the seed from a board read through pcbnew, which has no file text:
    `lines` describe its copper and parts without their ids."""
    global _seed
    _seed = hashlib.sha256('\n'.join(sorted(lines)).encode('utf-8')).hexdigest()


def current_seed() -> str | None:
    return _seed


def stamp(text: str) -> str:
    """`text` with its PLACEHOLDER replaced by the item's uuid."""
    if _seed is None:
        raise RuntimeError('item_uuid.stamp before seed_from_board: parse the board first')
    n = _stamped[text]
    _stamped[text] = n + 1
    return text.replace(PLACEHOLDER, str(uuid.uuid5(_NAMESPACE, '%s\n%d\n%s' % (_seed, n, text))))
