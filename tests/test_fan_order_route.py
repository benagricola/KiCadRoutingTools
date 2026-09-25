#!/usr/bin/env python3
"""Task 2 (docs/row-fan-order-plan.md): fan order wired into route.py.

A bare QFN-shaped chip (20 pads per side, four sides, 0.4 mm pitch, class
0.2/0.2, each pin netted to its own sink spread wider than the pins and
6 mm out -- docs/row-fan-order-design.md's own bare-QFN measurement)
routed on F.Cu with escalation off: with the fan order (default) every net
connects and check_drc --clearance-margin 0 is clean; with --no-fan-order
(same board, same call) at least one pin fails -- the case that shows the
order matters, not just that routing works.

The plan named a TWO-face row for this fixture. Measured: a clean two-face
case (no adjacent-face corners) routed 40/40 with plain MPS order on this
router build -- the failure the design doc measures is a corner effect (a
lane from one face cutting across a not-yet-routed pin near the adjacent
face), so a row in isolation does not reproduce it. Four faces, the same
shape the design doc's own escape lab measured against, does: 12/80 failed
with --no-fan-order, 0/80 with the fan order, on this exact board.

Calls route.batch_route in-process (as tests/test_734_reconcile_scope.py
does), so this is not a CLI/subprocess test.

Run: python3 -X utf8 tests/test_fan_order_route.py
"""
import contextlib
import io
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'py_router'))

fails = []


def check(name, cond):
    print(("  ok  " if cond else " FAIL ") + name)
    if not cond:
        fails.append(name)


PITCH = 0.4
N = 20                  # pads per side, so EDGE_HALF below clears the corners
OUT_PITCH = 1.0
OUT = 6.0
TRACK = 0.2
CLEARANCE = 0.2
EDGE_HALF = (N - 1) * PITCH / 2.0 + 0.5   # chip half-size: past the row's own
                                          # length so adjacent-side pads (and
                                          # their sinks) never overlap


def _pin(num, x, y, sx, sy, net_id, net_name):
    return ('\t\t(pad "%s" smd rect (at %.4f %.4f) (size %s %s) '
            '(layers "F.Cu") (net %d "%s"))\n'
            % (num, x, y, sx, sy, net_id, net_name))


def _sink(ref, x, y, net_id, net_name):
    return ('\t(footprint "test:sink" (layer "F.Cu") (at %.4f %.4f)\n'
            '\t\t(property "Reference" "%s" (at 0 0))\n'
            '\t\t(pad "1" smd rect (at 0 0) (size 0.6 0.6) (layers "F.Cu") '
            '(net %d "%s"))\n\t)\n' % (x, y, ref, net_id, net_name))


def _board_text():
    """U1: a bare QFN-shaped chip, N pads per side at 0.4mm pitch. Each pin's
    own sink sits OUT mm further out, spread at OUT_PITCH (wider than the pin
    pitch) so the pins must fan outward to reach them -- the shape
    docs/row-fan-order-design.md measures the bare QFN case against."""
    center = (N - 1) * PITCH / 2.0
    out_center = (N - 1) * OUT_PITCH / 2.0
    pins, sinks, nets = [], [], []
    net_id = 1
    sides = [('L', -EDGE_HALF, -EDGE_HALF - OUT, 'vert'),
            ('R', EDGE_HALF, EDGE_HALF + OUT, 'vert'),
            ('T', -EDGE_HALF, -EDGE_HALF - OUT, 'horiz'),
            ('B', EDGE_HALF, EDGE_HALF + OUT, 'horiz')]
    for side, edge, out_edge, kind in sides:
        for i in range(N):
            name = 'N%s%d' % (side, i + 1)
            u = i * PITCH - center
            ou = i * OUT_PITCH - out_center
            if kind == 'vert':
                # long_x (0.5 x 0.2): a horizontal lead, pads stacked
                # vertically -- a left/right-edge row.
                pins.append(_pin('%s%d' % (side, i + 1), edge, u, '0.5', '0.2',
                                 net_id, name))
                sinks.append(_sink('S%s%d' % (side, i + 1), out_edge, ou,
                                   net_id, name))
            else:
                # long_y (0.2 x 0.5): a vertical lead -- a top/bottom-edge row.
                pins.append(_pin('%s%d' % (side, i + 1), u, edge, '0.2', '0.5',
                                 net_id, name))
                sinks.append(_sink('S%s%d' % (side, i + 1), ou, out_edge,
                                   net_id, name))
            nets.append((net_id, name))
            net_id += 1
    u1 = ('\t(footprint "test:qfn" (layer "F.Cu") (at 0 0)\n'
         '\t\t(property "Reference" "U1" (at 0 0))\n'
         + ''.join(pins) + '\t)\n')
    board_half = EDGE_HALF + OUT + 5.0    # 5mm margin past the outermost sink
    head = ['(kicad_pcb\n\t(version 20241229)\n\t(generator "test")\n',
           '\t(net 0 "")\n']
    for nid, name in nets:
        head.append('\t(net %d "%s")\n' % (nid, name))
    head.append('\t(gr_rect (start -%.1f -%.1f) (end %.1f %.1f) '
               '(layer "Edge.Cuts") (uuid "edge"))\n'
               % (board_half, board_half, board_half, board_half))
    return ''.join(head) + u1 + ''.join(sinks) + ')\n', [n for _i, n in nets]


def _unconnected_nets(pcb):
    from check_connected import check_net_connectivity
    bad = []
    for nid, pads in pcb.pads_by_net.items():
        if nid == 0:
            continue
        segs = [s for s in pcb.segments if s.net_id == nid]
        vias = [v for v in pcb.vias if v.net_id == nid]
        res = check_net_connectivity(nid, segs, vias, pads,
                                     zones=pcb.zones, pcb_data=pcb)
        if not res['connected']:
            bad.append(nid)
    return bad


def _route(src, dst, net_names, fan_order):
    import route
    import fab_tiers
    from kicad_parser import parse_kicad_pcb
    fab_tiers.set_default_fab_tier('auto')
    fab_tiers.set_escalation_policy('off')
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        route.batch_route(src, dst, net_names, layers=['F.Cu'],
                          track_width=TRACK, clearance=CLEARANCE,
                          grid_step=0.1, ordering_strategy='mps',
                          fan_order=fan_order)
    return parse_kicad_pcb(dst), buf.getvalue()


def test_fan_order_routes_the_row_default_orders_do_not():
    text, net_names = _board_text()
    with tempfile.TemporaryDirectory() as td:
        src = os.path.join(td, 'in.kicad_pcb')
        with open(src, 'w', encoding='utf-8') as f:
            f.write(text)

        dst_on = os.path.join(td, 'on.kicad_pcb')
        pcb_on, out_on = _route(src, dst_on, net_names, fan_order=True)
        bad_on = _unconnected_nets(pcb_on)
        check("fan order (default): every net connects (%d/%d failed)"
             % (len(bad_on), len(net_names)), len(bad_on) == 0)
        check("fan order: named the rows found and nets re-sequenced",
             'Row fan order:' in out_on and '4 row(s)' in out_on
             and ('%d net(s)' % len(net_names)) in out_on)

        import run_utils
        # check_drc.py exits 1 iff any unaccepted violation -- accept=True
        # asserts exit 0 (and that the process did not just die), so this IS
        # "clean at --clearance-margin 0", not a proxy for it.
        run_utils.check(
            [sys.executable, run_utils.tool('check_drc.py'), dst_on,
             '--clearance-margin', '0'], accept=True)
        check("fan order: check_drc --clearance-margin 0 clean", True)

        dst_off = os.path.join(td, 'off.kicad_pcb')
        pcb_off, _out_off = _route(src, dst_off, net_names, fan_order=False)
        bad_off = _unconnected_nets(pcb_off)
        check("--no-fan-order: at least one pin fails on the identical "
             "board (%d/%d failed) -- the case shows the order matters"
             % (len(bad_off), len(net_names)), len(bad_off) >= 1)


def main():
    test_fan_order_routes_the_row_default_orders_do_not()
    if fails:
        print("\n%d FAILURE(S)" % len(fails))
        return 1
    print("\nALL PASS")
    return 0


if __name__ == '__main__':
    sys.exit(main())
