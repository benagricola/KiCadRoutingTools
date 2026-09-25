"""Grid alignment (docs/off-grid-exact-fit-design.md, part 1).

At minimum pitch the only legal straight lane out of a pin is on the pin's
own centre line, so a fine-pitch row routes only when its centre lines fall
on grid lines. The grid's origin is the board's (GridCoord rounds from
zero), so `aligning_offset` picks the sub-grid translation of the whole
board that puts the most row pins' centre lines on the grid; the board is
routed translated and the result translated back.
"""
from __future__ import annotations

from typing import Dict, Tuple

from fan_order import find_fan_rows

_UM = 1_000              # micrometres per mm: residues are voted in whole um, so
                         # pads a few nm apart (12.349999 beside 12.35) vote together


def aligning_offset(pcb_data, grid_step: float, max_pitch: float) -> Tuple[float, float]:
    """(dx, dy) in mm, each in [0, grid_step) and whole micrometres: the
    translation that puts the most fine-pitch row pins' centre lines on the
    grid. Per axis, each row pin votes for its centre line's residue modulo
    the grid; the most voted residue is moved to zero. Rows not along x or
    y are not counted; no rows gives (0, 0)."""
    step = round(grid_step * _UM)
    votes: Tuple[Dict[int, int], Dict[int, int]] = ({}, {})
    for row in find_fan_rows(pcb_data, max_pitch):
        ax, ay = row.axis
        if abs(abs(ax) - 1.0) < 1e-6:
            axis = 0            # a row along x: its lanes run along y, at the pads' x
        elif abs(abs(ay) - 1.0) < 1e-6:
            axis = 1
        else:
            continue
        for p in row.pads:
            c = p.global_x if axis == 0 else p.global_y
            r = round(c * _UM) % step
            votes[axis][r] = votes[axis][r] + 1 if r in votes[axis] else 1
    out = []
    for v in votes:
        if not v:
            out.append(0.0)
            continue
        r = max(sorted(v), key=lambda k: v[k])      # ties: the smallest residue
        out.append(((step - r) % step) / _UM)
    return out[0], out[1]


def child_argv(argv, input_file: str, output_file: str, tmp_in: str, tmp_out: str):
    """route.py's own arguments (`argv`, without the program) for the run on
    the translated copy: the board paths replaced by the copy's, the output
    options dropped, alignment off."""
    rest = list(argv)
    for tok in (input_file, output_file):
        if tok in rest:
            rest.remove(tok)
    out = []
    skip = False
    for tok in rest:
        if skip:
            skip = False
            continue
        if tok == '--output':
            skip = True
            continue
        if tok.startswith('--output=') or tok == '--overwrite':
            continue
        out.append(tok)
    return [tmp_in, tmp_out] + out + ['--no-align-grid']


def route_aligned(script: str, argv, input_file: str, output_file: str,
                  dx: float, dy: float, rows: int, json_out=None) -> int:
    """Route the board translated by (dx, dy): its text and the files beside
    it with the same stem are copied to a temporary directory, `script` is
    run on the copy with `child_argv`, and every file the run wrote beside
    its output is carried to `output_file`'s stem, boards translated back.
    Returns the run's exit code."""
    import glob
    import json
    import os
    import shutil
    import subprocess
    import sys
    import tempfile
    from board_translate import translate_board_text

    stem_in = os.path.splitext(input_file)[0]
    stem_out = os.path.splitext(output_file)[0]
    with tempfile.TemporaryDirectory(prefix='align-') as tmp:
        tmp_in = os.path.join(tmp, 'in.kicad_pcb')
        for f in glob.glob(glob.escape(stem_in) + '.*'):
            dst = os.path.join(tmp, 'in' + f[len(stem_in):])
            if f == input_file or os.path.abspath(f) == os.path.abspath(input_file):
                with open(f, encoding='utf-8') as fh:
                    text = fh.read()
                with open(tmp_in, 'w', encoding='utf-8') as fh:
                    fh.write(translate_board_text(text, dx, dy))
            elif os.path.isfile(f):
                shutil.copy2(f, dst)
        tmp_out = os.path.join(tmp, 'out.kicad_pcb')
        rc = subprocess.run([sys.executable, '-X', 'utf8', script]
                            + child_argv(argv, input_file, output_file, tmp_in, tmp_out)).returncode
        for name in sorted(os.listdir(tmp)):
            if not name.startswith('out.'):
                continue
            src = os.path.join(tmp, name)
            dst = stem_out + name[len('out'):]
            if name.endswith('.kicad_pcb'):
                with open(src, encoding='utf-8') as fh:
                    text = fh.read()
                with open(dst, 'w', encoding='utf-8') as fh:
                    fh.write(translate_board_text(text, -dx, -dy))
            elif os.path.isfile(src):
                shutil.copy2(src, dst)
    if json_out and os.path.isfile(json_out):
        with open(json_out, encoding='utf-8') as fh:
            summary = json.load(fh)
        summary['grid_alignment'] = {'dx': dx, 'dy': dy, 'rows': rows}
        with open(json_out, 'w', encoding='utf-8') as fh:
            json.dump(summary, fh, indent=2)
    return rc
