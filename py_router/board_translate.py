"""Translating a board's text by (dx, dy) mm, for grid alignment
(docs/off-grid-exact-fit-design.md, part 1): the input is routed translated
by a sub-grid offset and the output translated back.

Moved: every top-level item's coordinates -- a footprint by its own `at`
(its pads, shapes and texts are local to it) and the zones a footprint owns
(stored in board coordinates, kicad_parser._iter_zone_blocks); tracks, arcs,
vias, zones and graphics at every coordinate they carry. The board's header
(setup, layers, nets) is left alone. Coordinates are moved in whole
nanometres, KiCad's own unit, so translating back restores them exactly.
"""
from __future__ import annotations

import re
from decimal import Decimal

_NM = 1_000_000
# lists whose first two numbers are a point
_POINT_KEYS = {'at', 'start', 'end', 'mid', 'center', 'xy'}
# top-level items whose points are all in board coordinates
_ITEMS = {'segment', 'arc', 'via', 'zone', 'gr_line', 'gr_rect', 'gr_circle',
          'gr_arc', 'gr_poly', 'gr_curve', 'gr_bbox', 'gr_text', 'gr_text_box',
          'dimension', 'image', 'target', 'table', 'barcode', 'point',
          'generated'}
_TOKENS = re.compile(r'"(?:[^"\\]|\\.)*"|[()]')
_HEAD = re.compile(r'[^\s()"]+')
_TWO_NUMBERS = re.compile(r'(\s+)(-?[0-9.]+(?:[eE][-+]?[0-9]+)?)(\s+)(-?[0-9.]+(?:[eE][-+]?[0-9]+)?)(?=[\s)])')


def _nm(s: str) -> int:
    return int((Decimal(s) * _NM).to_integral_value())


def _mm(nm: int, like: str) -> str:
    """In the style of `like`, the number it replaces: six decimals if it has
    six ending in a zero (written by a tool that pads), otherwise KiCad's
    own (up to six decimals, trailing zeros dropped)."""
    sign = '-' if nm < 0 else ''
    whole, frac = divmod(abs(nm), _NM)
    digits = like.partition('.')[2]
    if len(digits) == 6 and digits.endswith('0'):
        return sign + str(whole) + '.%06d' % frac
    return sign + str(whole) + (('.' + ('%06d' % frac).rstrip('0')) if frac else '')


def translate_board_text(text: str, dx: float, dy: float) -> str:
    """`text` (a .kicad_pcb) with its top-level items moved by (dx, dy) mm."""
    ddx, ddy = round(dx * _NM), round(dy * _NM)
    if not ddx and not ddy:
        return text
    out = []
    last = 0
    stack = []                  # list heads, outermost first
    for m in _TOKENS.finditer(text):
        tok = m.group()
        if tok == ')':
            if stack:
                stack.pop()
            continue
        if tok != '(':
            continue            # a quoted string
        h = _HEAD.match(text, m.end())
        head = h.group() if h else ''
        stack.append(head)
        if head not in _POINT_KEYS or len(stack) < 3:
            continue
        item = stack[1]
        if item == 'footprint':
            if not ((len(stack) == 3 and head == 'at') or stack[2] == 'zone'):
                continue
        elif item not in _ITEMS:
            continue
        n = _TWO_NUMBERS.match(text, h.end())
        if not n:
            continue
        out.append(text[last:n.start(2)])
        out.append(_mm(_nm(n.group(2)) + ddx, n.group(2)))
        out.append(n.group(3))
        out.append(_mm(_nm(n.group(4)) + ddy, n.group(4)))
        last = n.end(4)
    out.append(text[last:])
    return ''.join(out)
