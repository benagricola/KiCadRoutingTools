"""A seeded perturbation of the net order (KICAD_ORDER_JITTER), for measuring
how much a board's outcome depends on the order its nets route in: on a
dense board a small change to the input changes which nets fail, so a
single run cannot judge a router change. Seed 0 is no change."""
import random


def jittered(net_ids, seed):
    """`net_ids` with a tenth of its entries (at least one pair) swapped with
    a neighbour, the swaps chosen by `seed`; seed 0 returns it unchanged."""
    out = list(net_ids)
    if not seed or len(out) < 2:
        return out
    rng = random.Random(seed)
    for _ in range(max(1, len(out) // 10)):
        i = rng.randrange(len(out) - 1)
        out[i], out[i + 1] = out[i + 1], out[i]
    return out
