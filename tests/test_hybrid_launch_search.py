#!/usr/bin/env python3
"""Plan task 1 (docs/pair-via-crossover-plan.md): the hybrid's launch search
looks round each terminal.

The MCU module's USB pair (chip pins 66/67 on the north face, series
resistors east of the chip) has P and N on opposite sides at its two ends,
and a pad swap is not allowed for USB. The hybrid (coupled middle, legs that
resolve the swap at the pads) is the mechanism for it, but its launch
search walked the straight line between the terminals, found the first
pair-wide clear swath beside the resistors from both ends, and its middle
looped on itself (docs/img/pair-polarity/hybrid-middle.png). Searching
round each terminal, the pair routes coupled.

Run: python3 -X utf8 tests/test_hybrid_launch_search.py
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIX = os.path.join(ROOT, 'tests', 'fixtures', 'pair_crossover', 'usb_north')
_fails = []


def check(name, cond, detail=''):
    print(('PASS ' if cond else 'FAIL ') + name + ('' if cond else ': ' + detail))
    if not cond:
        _fails.append(name)


with tempfile.TemporaryDirectory() as tmp:
    for ext in ('.kicad_pcb', '.kicad_pro'):
        shutil.copy(FIX + ext, os.path.join(tmp, 'in' + ext))
    out = os.path.join(tmp, 'out.kicad_pcb')
    r = subprocess.run([sys.executable, '-X', 'utf8', os.path.join(ROOT, 'py_router', 'route_diff.py'),
                        os.path.join(tmp, 'in.kicad_pcb'), out, '--nets', 'USB_MCU_*',
                        '--layers', 'F.Cu', 'B.Cu', '--diff-pair-gap', '0.45', '--escalation', 'off'],
                       capture_output=True, text=True, cwd=ROOT)
    m = [json.loads(x) for x in re.findall(r'JSON_SUMMARY: (\{.*\})', r.stdout) if '"routed_diff_pairs"' in x]
    rep = (m[-1].get('pair_reports') or [{}])[0] if m else {}
    check('the USB pair routes coupled', rep.get('outcome') == 'coupled', repr(rep))
    if shutil.which('kicad-cli') and os.path.isfile(out):
        dj = os.path.join(tmp, 'drc.json')
        subprocess.run(['kicad-cli', 'pcb', 'drc', '--format', 'json', '-o', dj, out], capture_output=True)
        v = [x['type'] for x in json.load(open(dj)).get('violations', [])
             if x['type'] in ('clearance', 'shorting_items', 'tracks_crossing')]
        check("KiCad's DRC finds no clearance violation", not v, repr(v))

sys.exit(1 if _fails else 0)
