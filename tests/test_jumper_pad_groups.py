"""Pads a part joins inside its package (KiCad 10 internal connections).

`(jumper_pad_groups ("1" "6") ("3" "4"))` names pad groups the part connects
internally -- a flow-through ESD array's in and out pins carry one net and
meet at one node inside the package. `(duplicate_pad_numbers_are_jumpers yes)`
does the same for pads sharing a number. KiCad's connectivity treats such a
group as one item: no ratsnest between its pads, no unconnected item. The
router must agree, or it reports the net open and lays a bridge between the
pads outside the package. Covers:

  1. the text parser reads both forms onto the footprint and each pad
  2. check_net_connectivity joins a group's pads, and only with the groups
  3. a net whose only pads are one group needs no copper
  4. the pcbnew path reads the same groups as the text path
"""
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'py_router'))

#: U1 is a flow-through ESD array: D+ enters on 1 and leaves on 6, D- on 3
#: and 4. J1 feeds 1 and 3; U2 is fed from 6 and 4. No copper joins 1-6 or
#: 3-4. U3's two pads numbered "1" are joined by duplicate numbers.
BOARD = """(kicad_pcb (version 20241229) (generator "pcbnew")
  (general (thickness 1.6))
  (layers
    (0 "F.Cu" signal)
    (2 "B.Cu" signal)
    (25 "Edge.Cuts" user)
  )
  (net 0 "")
  (net 1 "DP")
  (net 2 "DN")
  (net 3 "SHIELD")
  (footprint "test:esd" (layer "F.Cu")
    (at 10 10)
    (property "Reference" "U1" (at 0 -2 0) (layer "F.SilkS") (effects (font (size 1 1) (thickness 0.15))))
    (duplicate_pad_numbers_are_jumpers no)
    {groups}
    (pad "1" smd rect (at -0.5 -0.7) (size 0.3 0.5) (layers "F.Cu") (net 1 "DP"))
    (pad "3" smd rect (at 0.5 -0.7) (size 0.3 0.5) (layers "F.Cu") (net 2 "DN"))
    (pad "4" smd rect (at 0.5 0.7) (size 0.3 0.5) (layers "F.Cu") (net 2 "DN"))
    (pad "6" smd rect (at -0.5 0.7) (size 0.3 0.5) (layers "F.Cu") (net 1 "DP"))
  )
  (footprint "test:conn" (layer "F.Cu")
    (at 9.5 5)
    (property "Reference" "J1" (at 0 -2 0) (layer "F.SilkS") (effects (font (size 1 1) (thickness 0.15))))
    (pad "1" smd rect (at 0 0) (size 0.5 0.5) (layers "F.Cu") (net 1 "DP"))
    (pad "2" smd rect (at 1 0) (size 0.5 0.5) (layers "F.Cu") (net 2 "DN"))
  )
  (footprint "test:mcu" (layer "F.Cu")
    (at 9.5 15)
    (property "Reference" "U2" (at 0 -2 0) (layer "F.SilkS") (effects (font (size 1 1) (thickness 0.15))))
    (pad "1" smd rect (at 0 0) (size 0.5 0.5) (layers "F.Cu") (net 1 "DP"))
    (pad "2" smd rect (at 1 0) (size 0.5 0.5) (layers "F.Cu") (net 2 "DN"))
  )
  (footprint "test:shell" (layer "F.Cu")
    (at 20 10)
    (property "Reference" "U3" (at 0 -2 0) (layer "F.SilkS") (effects (font (size 1 1) (thickness 0.15))))
    {duplicates}
    (pad "1" smd rect (at -2 0) (size 0.5 0.5) (layers "F.Cu") (net 3 "SHIELD"))
    (pad "1" smd rect (at 2 0) (size 0.5 0.5) (layers "F.Cu") (net 3 "SHIELD"))
  )
  (segment (start 9.5 5) (end 9.5 9.3) (width 0.2) (layer "F.Cu") (net 1))
  (segment (start 10.5 5) (end 10.5 9.3) (width 0.2) (layer "F.Cu") (net 2))
  (segment (start 9.5 10.7) (end 9.5 15) (width 0.2) (layer "F.Cu") (net 1))
  (segment (start 10.5 10.7) (end 10.5 15) (width 0.2) (layer "F.Cu") (net 2))
  (gr_rect (start 0 0) (end 30 20) (layer "Edge.Cuts") (stroke (width 0.1) (type solid)))
)
"""

GROUPED = BOARD.format(groups='(jumper_pad_groups ("1" "6") ("3" "4"))',
                       duplicates='(duplicate_pad_numbers_are_jumpers yes)')
PLAIN = BOARD.format(groups='', duplicates='')


def _write(text):
    f = tempfile.NamedTemporaryFile('w', suffix='.kicad_pcb', delete=False)
    f.write(text)
    f.close()
    return f.name


def _parse(text):
    from kicad_parser import parse_kicad_pcb
    path = _write(text)
    try:
        return parse_kicad_pcb(path)
    finally:
        os.unlink(path)


def _net(pcb, name):
    return next(i for i, n in pcb.nets.items() if n.name == name)


def _connected(pcb, name):
    from check_connected import check_net_connectivity
    nid = _net(pcb, name)
    return check_net_connectivity(
        nid, [s for s in pcb.segments if s.net_id == nid],
        [v for v in pcb.vias if v.net_id == nid], pcb.pads_by_net[nid],
        [z for z in pcb.zones if z.net_id == nid], pcb_data=pcb)


def test_parser_reads_groups_onto_footprint_and_pads():
    pcb = _parse(GROUPED)
    esd = pcb.footprints['U1']
    assert esd.jumper_groups == [['1', '6'], ['3', '4']]
    assert not esd.duplicate_pad_numbers_are_jumpers
    keys = {p.pad_number: p.jumper_group for p in esd.pads}
    assert keys['1'] == keys['6'] and keys['3'] == keys['4']
    assert keys['1'] is not None and keys['3'] is not None and keys['1'] != keys['3']
    shell = pcb.footprints['U3']
    assert shell.duplicate_pad_numbers_are_jumpers
    assert len({p.jumper_group for p in shell.pads}) == 1
    assert shell.pads[0].jumper_group is not None
    for p in pcb.footprints['J1'].pads:
        assert p.jumper_group is None


def test_flow_through_net_is_connected_only_with_groups():
    grouped, plain = _parse(GROUPED), _parse(PLAIN)
    for name in ('DP', 'DN'):
        assert _connected(grouped, name)['connected'], name
        r = _connected(plain, name)
        assert not r['connected'] and r['num_components'] == 2, name


def test_group_only_net_needs_no_copper():
    from check_connected import _net_pads_connected_by_overlap
    grouped, plain = _parse(GROUPED), _parse(PLAIN)
    layers = ['F.Cu', 'B.Cu']
    assert _net_pads_connected_by_overlap(grouped.pads_by_net[_net(grouped, 'SHIELD')], layers)
    assert not _net_pads_connected_by_overlap(plain.pads_by_net[_net(plain, 'SHIELD')], layers)
    assert _connected(grouped, 'SHIELD')['connected']
    assert not _connected(plain, 'SHIELD')['connected']


def test_pcbnew_path_matches_text_path():
    pcbnew = pytest.importorskip('pcbnew')
    from kicad_parser import build_pcb_data_from_board
    path = _write(GROUPED)
    board = pcbnew.LoadBoard(path)
    os.unlink(path)     # the groups come from the live board, not the file
    live = build_pcb_data_from_board(board)
    text = _parse(GROUPED)
    for ref in ('U1', 'U3'):
        assert live.footprints[ref].jumper_groups == text.footprints[ref].jumper_groups
        assert (live.footprints[ref].duplicate_pad_numbers_are_jumpers
                == text.footprints[ref].duplicate_pad_numbers_are_jumpers)
        def keys(fp):
            return sorted((p.pad_number, p.global_x, p.jumper_group) for p in fp.pads)
        assert keys(live.footprints[ref]) == keys(text.footprints[ref])
    assert _connected(live, 'DP')['connected']


def test_pair_chain_passes_through_joined_terminals():
    from diff_pair_multipoint import terminals_joined, candidate_terminal_chains
    pcb = _parse(GROUPED)
    pad = {(p.component_ref, p.pad_number): p for p in pcb.pads_by_net[_net(pcb, 'DP')]
           + pcb.pads_by_net[_net(pcb, 'DN')]}
    conn = (pad['J1', '1'], pad['J1', '2'])
    esd_in = (pad['U1', '1'], pad['U1', '3'])
    esd_out = (pad['U1', '6'], pad['U1', '4'])
    mcu = (pad['U2', '1'], pad['U2', '2'])
    assert terminals_joined(esd_in, esd_out) and terminals_joined(esd_out, esd_in)
    assert not terminals_joined(conn, esd_in)
    plain = _parse(PLAIN)
    ppad = {(p.component_ref, p.pad_number): p for nid in (_net(plain, 'DP'), _net(plain, 'DN'))
            for p in plain.pads_by_net[nid]}
    assert not terminals_joined((ppad['U1', '1'], ppad['U1', '3']), (ppad['U1', '6'], ppad['U1', '4']))
    best = candidate_terminal_chains([mcu, esd_out, conn, esd_in])[0]
    names = [t[0].component_ref + t[0].pad_number for t in best]
    assert names in (['J11', 'U11', 'U16', 'U21'], ['U21', 'U16', 'U11', 'J11']), names
