"""Uuids for the items the router writes, the same in every run on the same board.

FORK DIVERGENCE (placemat): upstream mints uuid.uuid4() for every segment,
via, zone and drawing kicad_writer.py writes. KiCad orders and tie-breaks on
KIIDs - the order a loaded board hands out its tracks in, which of two items
a DRC marker names, overlapping zones' fill (see zone_overlap_priorities) -
so the same routed copper graded differently from run to run, and placemat's
reference set, which compares one run with another, needs the router's
output to be the same in every run. See docs/fork-divergences.md.

An item's uuid is uuid5 of the seed, the item's text and how many items of
that same text this process has stamped before. The seed is set from each
board the parser reads (`seed_from_board`): its lines with their uuids taken
out, sorted, so the input's own uuids and block order do not change it, and
a later run on a board that already holds an item of the same text stamps
it a different uuid.
"""
from __future__ import annotations

import collections
import hashlib
import re
import uuid

PLACEHOLDER = '__KRT_ITEM_UUID__'

_NAMESPACE = uuid.UUID('6f1b6a52-6d2c-5e8e-9a63-0c2a4b1f7d10')
_ID_RE = re.compile(r'\((?:uuid|tstamp)\s+"?[^\s")]*"?\)')

_seed = ''
_stamped: collections.Counter = collections.Counter()


def seed_from_board(content: str) -> None:
    """Set the seed from a board's text, its uuids and line order left out."""
    global _seed
    lines = sorted(_ID_RE.sub('', line).strip() for line in content.splitlines())
    _seed = hashlib.sha256('\n'.join(lines).encode('utf-8')).hexdigest()


def current_seed() -> str:
    return _seed


def stamp(text: str) -> str:
    """`text` with its PLACEHOLDER replaced by the item's uuid."""
    n = _stamped[text]
    _stamped[text] = n + 1
    return text.replace(PLACEHOLDER, str(uuid.uuid5(_NAMESPACE, '%s\n%d\n%s' % (_seed, n, text))))
