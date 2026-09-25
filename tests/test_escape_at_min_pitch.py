"""A pad row at its own class's minimum pitch escapes (docs/corner-move-check-design.md).

Seven 0.665 x 0.2 mm pads at 0.4 mm pitch, each on its own net and netted to
a sink 6 mm out, the sinks 1 mm apart; the Default class 0.2/0.2, so each
pin's straight lane out is exactly the clearance from its neighbours. The
half-cell corner buffer used to block the lanes' first cells past the row,
and only the end pins, with room beside them, could leave. With the pads'
cells exact and the corner move check in the search, every pin routes on
F.Cu, and KiCad's own clearance (no margin) finds no violation.
"""
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

N = 7
PITCH, SINK_PITCH, SINK_OUT = 0.4, 1.0, 6.0


def _board():
    nets = "".join('  (net %d "N%d")\n' % (k, k) for k in range(1, N + 1))
    row = "".join('    (pad "%d" smd rect (at 0 %.3f) (size 0.665 0.2) (layers "F.Cu" "F.Mask") (net %d "N%d"))\n'
                  % (k, (k - 1 - N // 2) * PITCH, k, k) for k in range(1, N + 1))
    sinks = "".join('  (footprint "test:SINK" (at %.4f %.3f) (layer "F.Cu")\n'
                    '    (property "Reference" "TP%d" (at 0 0) (layer "F.SilkS"))\n'
                    '    (pad "1" smd rect (at 0 0) (size 0.6 0.6) (layers "F.Cu" "F.Mask") (net %d "N%d"))\n  )\n'
                    % (100 - 0.3325 - SINK_OUT, 100 + (k - 1 - N // 2) * SINK_PITCH, k, k, k) for k in range(1, N + 1))
    return ('(kicad_pcb (version 20240108) (generator test)\n'
            '  (general (thickness 1.6))\n'
            '  (layers (0 "F.Cu" signal) (31 "B.Cu" signal) (37 "F.SilkS" user) (39 "F.Mask" user) (44 "Edge.Cuts" user))\n'
            '  (net 0 "")\n' + nets +
            '  (gr_rect (start 85 88) (end 106 112) (layer "Edge.Cuts") (width 0.1))\n'
            '  (footprint "test:ROW" (at 100 100) (layer "F.Cu")\n'
            '    (property "Reference" "U1" (at 0 0) (layer "F.SilkS"))\n' + row + '  )\n' + sinks + ')\n')


def _project():
    cls = {"name": "Default", "clearance": 0.2, "track_width": 0.2, "via_diameter": 0.6, "via_drill": 0.3,
           "microvia_diameter": 0.3, "microvia_drill": 0.1, "diff_pair_width": 0.2, "diff_pair_gap": 0.2,
           "diff_pair_via_gap": 0.2, "priority": 2147483647, "bus_width": 12, "wire_width": 6, "line_style": 0}
    rules = {"min_clearance": 0.0, "min_track_width": 0.2, "min_via_diameter": 0.5, "min_through_hole_diameter": 0.3,
             "min_via_annular_width": 0.1, "min_copper_edge_clearance": 0.3, "min_hole_clearance": 0.2,
             "min_hole_to_hole": 0.2}
    return {"board": {"design_settings": {"rules": rules, "defaults": {}, "meta": {"version": 2}}},
            "net_settings": {"classes": [cls], "meta": {"version": 5}, "net_colors": None,
                             "netclass_assignments": None, "netclass_patterns": []},
            "meta": {"filename": "in.kicad_pro", "version": 3}}


def test_every_pin_of_a_minimum_pitch_row_escapes():
    with tempfile.TemporaryDirectory() as td:
        pcb, out, js = (os.path.join(td, f) for f in ("in.kicad_pcb", "out.kicad_pcb", "out.json"))
        open(pcb, "w").write(_board())
        json.dump(_project(), open(os.path.join(td, "in.kicad_pro"), "w"))
        r = subprocess.run([sys.executable, '-X', 'utf8', os.path.join(ROOT, 'py_router', 'route.py'), pcb, out,
                            '--nets', '*', '--layers', 'F.Cu', '--escalation', 'off', '--json-out', js],
                           capture_output=True, text=True, encoding='utf-8', errors='replace', cwd=ROOT)
        assert os.path.exists(js), r.stdout[-3000:]
        data = json.load(open(js, encoding='utf-8'))
        assert data.get('failed', 1) == 0 and not data.get('open_single'), (data.get('failed_single'), data.get('open_single'))
        d = subprocess.run([sys.executable, '-X', 'utf8', os.path.join(ROOT, 'py_router', 'check_drc.py'), out,
                            '--clearance', '0.2', '--clearance-margin', '0'],
                           capture_output=True, text=True, encoding='utf-8', errors='replace', cwd=ROOT)
        assert 'NO DRC VIOLATIONS FOUND' in d.stdout, d.stdout[-2000:]


if __name__ == '__main__':
    test_every_pin_of_a_minimum_pitch_row_escapes()
    print("PASS")
