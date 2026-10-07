#!/usr/bin/env python3
"""Bounded whole-run candidate isolation, selection and legacy preservation."""
import json
import argparse
import os
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'py_router'))
import route_candidates as candidates


def parser_for_tests():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output')
    parser.add_argument('--json-out')
    parser.add_argument('--overwrite', action='store_true')
    parser.add_argument('--connections')
    parser.add_argument('--bus-nets', nargs='+')
    parser.add_argument('--capture')
    parser.add_argument('--net-clearances')
    parser.add_argument('--track-width', type=float)
    parser.add_argument('--via-size', type=float)
    parser.add_argument('--via-drill', type=float)
    parser.add_argument('--nets', '-n', nargs='+')
    return parser


def args_for(root):
    inp, out = root / 'input.kicad_pcb', root / 'out.kicad_pcb'
    inp.write_text('original')
    inp.with_suffix('.kicad_pro').write_text('original rules')
    return SimpleNamespace(input_file=str(inp), output_file=str(out), output=None,
        preview=False, skip_routing=False, schematic_dir=None,
        json_out=str(root / 'result.json'), track_width=0.2, connections=None, via_size=0.6, via_drill=0.3, clearance=0.25)


def grade(opened, vias=10, **overrides):
    return dict(known=True, drc=0, undersized=0, widths_unknown=False,
                open=opened, quality=[vias, 100, 20], **overrides)


def test_selection_requires_proof_and_preserves_incomplete_ties():
    assert candidates.prefer_pocket(grade(2), grade(1))
    assert not candidates.prefer_pocket(grade(1), grade(1, 1))
    for field in ('drc', 'undersized', 'widths_unknown'):
        bad = grade(0)
        bad[field] = 1
        assert not candidates.prefer_pocket(grade(1), bad)
    assert not candidates.prefer_pocket(None, grade(0))
    assert not candidates.prefer_pocket(grade(1), {'known': False})


def test_deadline_uses_lower_caller_budget():
    end, budget = candidates.deadline_from_env({'KRT_ROUTE_BUDGET_S': '100',
        'KRT_ROUTE_DEADLINE_UTC': str(time.time() + 2)})
    assert 0 < budget <= 2
    assert time.monotonic() < end <= time.monotonic() + 2
    for bad in ('nan', 'inf', '0', '-1'):
        try:
            candidates.deadline_from_env({'KRT_ROUTE_BUDGET_S': bad})
        except ValueError:
            pass
        else:
            raise AssertionError(bad)


def test_argv_preserves_scope_options_and_overwrite_isolation():
    args = SimpleNamespace(input_file='in.pcb', output_file='in.pcb')
    argv = ['in.pcb', '--overwrite', '--connections', 'tasks.json', '--bus-nets',
            'A,B', '--json-out=old.json', '--capture', 'capture.json']
    out = candidates.child_argv(argv, args, 'copy.pcb', 'trial.pcb', 'trial.json', parser_for_tests())
    assert out == ['copy.pcb', '--overwrite', '--connections', 'tasks.json',
        '--bus-nets', 'A,B', '--capture', 'capture.json', '--output',
        'trial.pcb', '--json-out', 'trial.json']
    out = candidates.child_argv(['in.pcb', 'in.pcb'], args, 'copy.pcb', 'trial.pcb', 's.json', parser_for_tests())
    assert out[:2] == ['copy.pcb', 'trial.pcb']


def fake_run(closure, calls, scores=None, timeout_pocket=False):
    def run(command, log, env, deadline):
        calls.append((command, dict(env)))
        log.write_text('selected log ' + env['KRT_INTERNAL_POCKET_WALLS'] + '\n')
        if '--grade' in command:
            name = Path(command[-1]).parent.name
            Path(command[-1]).write_text(json.dumps(scores[name]))
            return 0
        name = 'pocket' if env['KRT_INTERNAL_POCKET_WALLS'] == '1' else 'legacy'
        if timeout_pocket and name == 'pocket':
            raise TimeoutError('shared candidate deadline expired')
        original = Path(command[2])
        assert original.read_text() == 'original'
        assert original.with_suffix('.kicad_pro').read_text() == 'original rules'
        out = Path(command[command.index('--output') + 1])
        out.write_text(name)
        out.with_suffix('.kicad_pro').write_text(name + ' rules')
        summary = {'regrade': {'graded_nets': 1}, 'failed_single': ['N'] if closure[name] else [],
                   'open_single': [], 'multipoint_pads_total': 0,
                   'multipoint_pads_connected': 0, 'net_evidence': {'N': name}}
        Path(command[command.index('--json-out') + 1]).write_text(json.dumps(summary))
        return 0
    return run


def test_complete_legacy_never_runs_pocket_and_preserves_summary():
    with tempfile.TemporaryDirectory() as tmp:
        args, calls = args_for(Path(tmp)), []
        with patch.dict(os.environ, {}, clear=True), patch.object(candidates, 'run_child', fake_run({'legacy': 0}, calls)):
            assert candidates.maybe_run_candidates(args, [args.input_file, '--nets', 'N'], 'route.py', parser_for_tests(), ['N']) == 0
        assert len(calls) == 1
        assert Path(args.output_file).read_text() == 'legacy'
        assert Path(args.input_file).read_text() == 'original'
        assert json.loads(Path(args.json_out).read_text())['net_evidence'] == {'N': 'legacy'}


def test_isolated_proposal_publishes_matching_artifacts_and_preserves_input():
    with tempfile.TemporaryDirectory() as tmp:
        args, calls = args_for(Path(tmp)), []
        scores = {'legacy': grade(2), 'pocket': grade(0)}
        with patch.dict(os.environ, {}, clear=True), patch.object(candidates, 'run_child', fake_run({'legacy': 1, 'pocket': 0}, calls, scores)):
            assert candidates.maybe_run_candidates(args, [args.input_file, '--nets', 'N'], 'route.py', parser_for_tests(), ['N']) == 0
        assert len(calls) == 4
        assert Path(args.output_file).read_text() == 'pocket'
        assert Path(args.output_file).with_suffix('.kicad_pro').read_text() == 'pocket rules'
        assert Path(args.input_file).read_text() == 'original'
        result = json.loads(Path(args.json_out).read_text())
        assert result['net_evidence'] == {'N': 'pocket'}
        assert result['route_candidates']['attempts'] == 2


def test_timeout_retains_complete_first_artifacts():
    with tempfile.TemporaryDirectory() as tmp:
        args, calls = args_for(Path(tmp)), []
        with patch.dict(os.environ, {}, clear=True), patch.object(candidates, 'run_child', fake_run({'legacy': 1}, calls, timeout_pocket=True)):
            assert candidates.maybe_run_candidates(args, [args.input_file], 'route.py', parser_for_tests(), ['N']) == 0
        assert Path(args.output_file).read_text() == 'legacy'
        assert json.loads(Path(args.json_out).read_text())['route_candidates']['stopped']


def test_quick_preview_skip_schematic_are_legacy():
    with tempfile.TemporaryDirectory() as tmp:
        for field in ('preview', 'skip_routing', 'schematic_dir'):
            args = args_for(Path(tmp))
            setattr(args, field, True)
            with patch.dict(os.environ, {}, clear=True), patch.object(candidates, 'run_child', side_effect=AssertionError('child')):
                assert candidates.maybe_run_candidates(args, [args.input_file], 'route.py', parser_for_tests(), ['N']) is None
        args = args_for(Path(tmp))
        with patch.dict(os.environ, {'KRT_ROUTE_QUICK': '1'}, clear=True):
            assert candidates.maybe_run_candidates(args, [args.input_file], 'route.py', parser_for_tests(), ['N']) is None


def test_output_aliases_are_rewritten_by_position():
    args = SimpleNamespace(input_file='input.pcb', output_file='input.pcb')
    for argv in (['input.pcb', '--output', 'input.pcb'],
                 ['input.pcb', '--output=input.pcb'],
                 ['input.pcb', 'input.pcb'], ['input.pcb', '--overwrite'],
                 ['--capture', 'input.pcb', 'input.pcb']):
        result = candidates.child_argv(argv, args, '/copy/input.pcb',
                                      '/trial/output.pcb', '/trial/s.json', parser_for_tests())
        assert result.count('/copy/input.pcb') == 1
        assert result[result.index('--output') + 1] == '/trial/output.pcb'
    result = candidates.child_argv(['/abs/input.pcb'], args, '/copy/input.pcb',
                                  '/trial/output.pcb', '/trial/s.json', parser_for_tests())
    assert result[0] == '/copy/input.pcb'


def test_publication_failure_restores_entire_previous_artifact_set():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        source, output = root / 'new.pcb', root / 'old.pcb'
        source.write_text('new board')
        source.with_suffix('.kicad_pro').write_text('new rules')
        output.write_text('old board')
        output.with_suffix('.kicad_pro').write_text('old rules')
        result = root / 'result.json'
        result.write_text('old summary')
        log = root / 'run.log'
        log.write_text('new log')
        original_replace = os.replace
        def fail_board(src, dst):
            if Path(dst) == output and Path(src).name == 'new':
                raise OSError('injected board commit failure')
            return original_replace(src, dst)
        with patch.object(candidates.os, 'replace', fail_board):
            try:
                candidates.publish({'board': source, 'summary': {'selected': 'new'}, 'log': log}, output, result, {})
            except OSError:
                pass
            else:
                raise AssertionError('failure not injected')
        assert output.read_text() == 'old board'
        assert output.with_suffix('.kicad_pro').read_text() == 'old rules'
        assert result.read_text() == 'old summary'


def test_frozen_scope_charges_a_candidate_that_omits_an_owned_failure():
    inputs = [{'summary': {'failed_single': ['omitted']}},
              {'summary': {'routed_single': ['requested']}}]
    scope, identity = candidates.freeze_scope(['requested'], inputs)
    assert scope == ['omitted', 'requested']
    assert identity['requested_nets'] == ['requested']
    assert identity['sha256'] == candidates.freeze_scope(['requested'], list(reversed(inputs)))[1]['sha256']


def test_short_attached_net_values_are_preserved():
    parser = parser_for_tests()
    args = SimpleNamespace(input_file='in.pcb', output_file='out.pcb')
    result = candidates.child_argv(['in.pcb', 'out.pcb', '-nNET', 'NEXT'], args,
                                   '/copy/in.pcb', '/trial/out.pcb', 's.json', parser)
    assert result[:4] == ['/copy/in.pcb', '/trial/out.pcb', '-nNET', 'NEXT']
    result = candidates.child_argv(['in.pcb', '--out=out.pcb'], args,
                                   '/copy/in.pcb', '/trial/out.pcb', 's.json', parser)
    assert result == ['/copy/in.pcb', '--output', '/trial/out.pcb', '--json-out', 's.json']
    assert candidates.explicit_fields(['--track-w=0.5', '--via-s=0.6'], parser) == {'track_width', 'via_size'}


def test_constraint_files_are_frozen_and_child_redo_manifest_is_disabled():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        args, calls = args_for(root), []
        constraints = root / 'clearances.json'
        constraints.write_text('{"N":0.2}')
        args.net_clearances = str(constraints)
        original_fake = fake_run({'legacy': 0}, calls)
        def run(command, log, env, deadline):
            assert 'REDO_MANIFEST' not in env
            frozen = Path(command[command.index('--net-clearances') + 1])
            assert frozen != constraints and frozen.read_text() == constraints.read_text()
            return original_fake(command, log, env, deadline)
        with patch.dict(os.environ, {'REDO_MANIFEST': 'original-record'}, clear=True), patch.object(candidates, 'run_child', run):
            candidates.maybe_run_candidates(args, [args.input_file, '--net-clearances', str(constraints)], 'route.py', parser_for_tests(), ['N'])
            assert os.environ['REDO_MANIFEST'] == 'original-record'


def test_expired_caller_deadline_never_starts_a_child_or_overwrites_output():
    with tempfile.TemporaryDirectory() as tmp:
        args = args_for(Path(tmp))
        Path(args.output_file).write_text('previous board')
        with patch.dict(os.environ, {'KRT_ROUTE_DEADLINE_UTC': str(time.time() - 1)}, clear=True):
            assert candidates.maybe_run_candidates(args, [args.input_file], 'route.py', parser_for_tests(), ['N']) == 124
        assert Path(args.output_file).read_text() == 'previous board'


def test_failed_pocket_process_is_never_adopted():
    with tempfile.TemporaryDirectory() as tmp:
        args, calls = args_for(Path(tmp)), []
        original_fake = fake_run({'legacy': 1, 'pocket': 0}, calls)
        def run(command, log, env, deadline):
            original_fake(command, log, env, deadline)
            return 3 if env['KRT_INTERNAL_POCKET_WALLS'] == '1' else 0
        with patch.dict(os.environ, {}, clear=True), patch.object(candidates, 'run_child', run):
            assert candidates.maybe_run_candidates(args, [args.input_file], 'route.py', parser_for_tests(), ['N']) == 0
        assert Path(args.output_file).read_text() == 'legacy'
        assert len(calls) == 2


def test_grade_preserves_original_rule_floors_without_promoting_nominal_width():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'py_tools'))
    import board_score
    import kicad_parser
    import improvement_gate
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        original, output = root / 'input.kicad_pcb', root / 'output.kicad_pcb'
        original.write_text('original board')
        output.write_text('final copper')
        original.with_suffix('.kicad_pro').write_text(json.dumps({
            'net_settings': {'classes': [{'name': 'Default', 'track_width': 0.4}]},
            'board': {'design_settings': {'rules': {'min_track_width': 0.1}}}}))
        output.with_suffix('.kicad_pro').write_text(json.dumps({
            'board': {'design_settings': {'rules': {'min_track_width': 0.01}}}}))
        segment = SimpleNamespace(net_id=1, layer='F.Cu', width=0.2,
            start_x=0, start_y=0, end_x=1, end_y=0, graphic=False)
        board = SimpleNamespace(nets={1: SimpleNamespace(name='N')}, segments=[segment],
            vias=[], footprints={}, board_info=SimpleNamespace(copper_layers=['F.Cu', 'B.Cu']))
        def check(root, final_file, **kwargs):
            assert Path(final_file).read_text() == 'final copper'
            project = json.loads(Path(final_file).with_suffix('.kicad_pro').read_text())
            assert project['board']['design_settings']['rules']['min_track_width'] == 0.1
            assert project['net_settings']['classes'][0]['track_width'] == 0.4
            return {'ran': True, 'count': 0}, {'ran': True, 'count': 0}, {}
        request = {'board': str(output), 'input': str(original), 'explicit_width': None,
                   'summary': {'routed_single': ['N']}, 'scope': ['N'], 'connections': None,
                   'manufacturing_defaults': {'clearance': 0.1}}
        with patch.object(kicad_parser, 'parse_kicad_pcb', return_value=board), \
             patch.object(improvement_gate, 'grade_nets', return_value={1: {'broken': False, 'failed_pads': []}}), \
             patch.object(board_score, 'score_drc', check), \
             patch.object(board_score, 'quality', return_value={'vias': 0, 'copper_mm': 1, 'segments': 1}):
            result = candidates.grade_request(request)
            assert result['known'] and not result['widths_unknown'], result
            request['manufacturing_defaults']['size_floors'] = {'track_width': 0.15}
            assert 'original_size_floor_below_factory_track_width' in candidates.grade_request(request)['unproved']
            request['manufacturing_defaults'].pop('size_floors')
            request['explicit_width'] = 0.3
            assert candidates.grade_request(request)['widths_unknown']
            request['clearance_unproved'] = True
            assert not candidates.grade_request(request)['known']
            request['clearance_unproved'] = False
            original.with_suffix('.kicad_dru').write_text('(version 1)')
            assert 'custom_clearance_rules_unproved' in candidates.grade_request(request)['unproved']
            original.with_suffix('.kicad_dru').unlink()
            board.footprints = {'U1': SimpleNamespace(pads=[SimpleNamespace(local_clearance=0.1)])}
            assert 'local_clearance_overrides_unproved' in candidates.grade_request(request)['unproved']


def test_no_project_grading_uses_frozen_default_not_candidate_writeback():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'py_tools'))
    import board_score
    import kicad_parser
    import improvement_gate
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        original, output = root / 'input.kicad_pcb', root / 'output.kicad_pcb'
        original.write_text('original board without project')
        output.write_text('final copper')
        output.with_suffix('.kicad_pro').write_text(json.dumps({'board': {
            'design_settings': {'rules': {'min_clearance': 0.01}}}}))
        board = SimpleNamespace(nets={1: SimpleNamespace(name='N')}, segments=[],
            vias=[], footprints={}, board_info=SimpleNamespace(copper_layers=['F.Cu', 'B.Cu']))
        def check(root, final_file, **kwargs):
            assert kwargs['clearance'] == expected[0]
            assert kwargs['sizes'] == {}
            assert not Path(final_file).with_suffix('.kicad_pro').exists()
            return {'ran': True, 'count': 0}, {'ran': True, 'count': 0}, {}
        expected = [0.15]
        request = {'board': str(output), 'input': str(original), 'explicit_width': None,
                   'summary': {'routed_single': ['N']}, 'scope': ['N'], 'connections': None,
                   'manufacturing_defaults': {'clearance': 0.15}}
        with patch.object(kicad_parser, 'parse_kicad_pcb', return_value=board), \
             patch.object(improvement_gate, 'grade_nets', return_value={1: {'broken': False, 'failed_pads': []}}), \
             patch.object(board_score, 'score_drc', check), \
             patch.object(board_score, 'quality', return_value={'vias': 0, 'copper_mm': 0, 'segments': 0}):
            assert candidates.grade_request(request)['known']
            original.write_text('(kicad_pcb\n(net_class \"Default\" \"\"\n(clearance 0.35)\n(trace_width 0.4)\n)\n)')
            expected[0] = 0.35
            assert candidates.grade_request(request)['known']
            request['manufacturing_defaults']['tier'] = 'standard'
            assert not candidates.grade_request(request)['known']


if __name__ == '__main__':
    failures = 0
    for name, fn in sorted(list(globals().items())):
        if name.startswith('test_'):
            try:
                fn()
                print('PASS ' + name)
            except Exception as error:
                failures += 1
                print('FAIL ' + name + ': ' + str(error))
    sys.exit(bool(failures))
