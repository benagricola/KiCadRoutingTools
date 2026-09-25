#!/usr/bin/env python3
"""KICAD_ORDER_JITTER: a seeded perturbation of the net order, for measuring
how much a board's outcome depends on it. Seed 0 leaves the order alone; any
other seed swaps a tenth of the nets (at least one pair) with a neighbour,
the same swaps every time for the same seed.

Run: python3 -X utf8 tests/test_order_jitter.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'py_router'))

from order_jitter import jittered  # noqa: E402

_fails = []


def check(name, cond):
    print(('PASS ' if cond else 'FAIL ') + name)
    if not cond:
        _fails.append(name)


order = [('n%d' % i, i) for i in range(40)]

check('seed 0 leaves the order unchanged', jittered(order, 0) == order)
a = jittered(order, 3)
check('a seed changes the order', a != order)
check('the same seed gives the same order', jittered(order, 3) == a)
check('the nets are the same nets', sorted(a) == sorted(order))
check('different seeds give different orders', jittered(order, 4) != a)
moved = [abs(a.index(x) - i) for i, x in enumerate(order)]
check('nets move only a little', max(moved) <= 4)
check('the input is not modified', order == [('n%d' % i, i) for i in range(40)])
check('a one-net order is left alone', jittered(order[:1], 7) == order[:1])

sys.exit(1 if _fails else 0)
