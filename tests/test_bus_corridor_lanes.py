#!/usr/bin/env python3
"""Fork: bus members are attracted to their own lane of the corridor.

Every member used to be attracted to the one planned centerline. The member
routed first took it and crossed the launch of each pad between it and the
guide, and on a 0.4 mm-pitch row the member left behind was walled in. A
member is now attracted to the corridor shifted sideways by where its pad sits
across the guide's pad, so the members keep their sides as a river does.

Run:
    python3 tests/test_bus_corridor_lanes.py
"""
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, 'py_router'))
sys.path.insert(0, os.path.join(ROOT, 'rust_router'))

STEP = 0.1
fails = []


def check(name, cond, detail=''):
    print(('PASS: ' if cond else 'FAIL: ') + name + (f'  {detail}' if detail else ''))
    if not cond:
        fails.append(name)


def _corridor():
    """From (0, 0) east for 20 mm, then north (-y) for 20 mm; grid cells."""
    east = [(i, 0, 0) for i in range(200)]
    north = [(200, -i, 0) for i in range(201)]
    return east + north


def main():
    import bus_corridor
    from bus_detection import BusGroup, bus_attraction_context

    # Pads in a column 0.4 mm apart (a row seen from the east): guide 'B' in
    # the middle, 'A' 0.4 mm to the north (-y), 'C' 0.4 mm to the south.
    group = BusGroup(name='g', net_ids=[1, 2, 3],
                     source_positions=[(0.0, -0.4), (0.0, 0.0), (0.0, 0.4)],
                     target_positions=[(19.6, -20.0), (20.0, -20.0), (20.4, -20.0)])
    corridor = _corridor()
    lanes = bus_corridor.lane_paths(group, 2, corridor, STEP)

    check('the guide has no lane of its own', 2 not in lanes)
    check('the other members have one', set(lanes) == {1, 3}, sorted(lanes))
    if set(lanes) != {1, 3}:
        return 1

    def at(path, i):
        return path[i][0] * STEP, path[i][1] * STEP

    # Launch: on the east leg the lane of A is 0.4 mm north of the corridor.
    ax, ay = at(lanes[1], 20)
    cx, cy = at(lanes[3], 20)
    check('A launches 0.4 mm north of the guide', abs(ay + 0.4) < 0.06, (ax, ay))
    check('C launches 0.4 mm south of the guide', abs(cy - 0.4) < 0.06, (cx, cy))
    # After the turn north, the same members stay on their sides: A (north of
    # the guide while heading east) is west of it while heading north.
    ax, ay = at(lanes[1], 300)
    cx, cy = at(lanes[3], 300)
    check('A stays on the west side after the turn', abs(ax - 19.6) < 0.06, (ax, ay))
    check('C stays on the east side after the turn', abs(cx - 20.4) < 0.06, (cx, cy))
    # No lane crosses another: along the path the cross-corridor order holds.
    cross = 0
    for j in range(len(corridor)):
        a, c = lanes[1][j], lanes[3][j]
        if j < 150:
            cross += a[1] >= c[1]
        elif j > 250:
            cross += a[0] >= c[0]
    check('the lanes never swap sides along the straight legs', cross == 0, cross)

    # The attraction path a member gets: its lane, the guide's is the corridor.
    corridors = {'g': corridor, ('g', 1): lanes[1], ('g', 3): lanes[3]}
    b2g = {n: group for n in group.net_ids}
    check('A is attracted to its lane',
          bus_attraction_context(1, b2g, corridors)[0] == lanes[1])
    check('the guide is attracted to the corridor',
          bus_attraction_context(2, b2g, corridors)[0] == corridor)
    check('a corridor without lanes still attracts a member to the corridor',
          bus_attraction_context(1, b2g, {'g': corridor})[0] == corridor)

    print(f"\n{len(fails)} failure(s)" if fails else "\nall passed")
    return 1 if fails else 0


def test_main():
    assert main() == 0


if __name__ == '__main__':
    sys.exit(main())
