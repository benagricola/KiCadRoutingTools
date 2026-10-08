#!/usr/bin/env python3
"""Final-call proof and actual nominal failure eligibility; no physical routing."""
import argparse
import copy
import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'py_router'))
import final_escape as escape


def parser():
    p = argparse.ArgumentParser()
    p.add_argument('input_file')
    p.add_argument('output_file', nargs='?')
    p.add_argument('net_patterns', nargs='*')
    p.add_argument('--nets', '-n', nargs='+')
    p.add_argument('--layers', nargs='+')
    p.add_argument('--output')
    p.add_argument('--json-out')
    p.add_argument('--overwrite', '-O', action='store_true')
    p.add_argument('--final-call-proof')
    p.add_argument('--candidate-artifacts')
    p.add_argument('--track-width', type=float)
    return p


def fixture(root):
    from routing_config import GridRouteConfig
    board = root/'input.kicad_pcb'
    board.write_text('same immutable geometry')
    board.with_suffix('.kicad_pro').write_text('same original rules')
    argv = [str(board), str(root/'out.kicad_pcb'), '--nets', 'SIGNAL', '--layers', 'F.Cu', 'B.Cu']
    proof = {'schema': 1, 'input_files': escape.input_identity(board),
        'call': {'id': 'last-call', 'kind': 'single', 'routing_flags': escape.routing_vector(argv, parser()),
                 'nets': ['SIGNAL'], 'tasks_sha256': None, 'bus_groups': [], 'layers': ['F.Cu', 'B.Cu'],
                 'pair_owned_nets': [], 'obligations': [{'net': 'SIGNAL', 'from': {'ref': 'J1', 'pad': '1'},
                 'to': {'ref': 'U1', 'pad': '2'}, 'widths': {'F.Cu': .5, 'B.Cu': .5}}]},
        'nominal_policy': {'receipt_sha256': 'a'*64, 'sources_sha256': escape.source_fingerprint(),
                           'by_net': {'SIGNAL': {'F.Cu': .5, 'B.Cu': .5}}},
        'copper_work': [{'id': 'earlier', 'kind': 'pairs'}, {'id': 'last-call', 'kind': 'single'}],
        'deferred_work': [], 'finalization': list(escape.FINALIZATION),
        'standing_authority': {'schema': 1, 'available': True, 'contract_sha256': 'b'*64,
                              'settings_sha256': 'c'*64, 'check_context_sha256': 'd'*64,
                              'adapter_sha256': 'e'*64}, 'deadline_utc': 200}
    identity = escape.validate_proof(proof, board=board, argv=argv, parser=parser(),
                                    scope=['SIGNAL'], kind='single', layers=['F.Cu','B.Cu'], now=100)
    failure = {'proof_sha256': identity['proof_sha256'], 'call_id': identity['call_id'],
               'input_files': proof['input_files'], 'policy_sha256': identity['policy_sha256'],
               'endpoint': {'net': 'SIGNAL', 'ref': 'J1', 'pad': '1', 'physical_index': 0},
               'peer': {'ref': 'U1', 'pad': '2', 'physical_index': 1},
               'nominal_result': {'success': False, 'via_blocked': True}, 'nominal_only': True,
               'epoch': {'sequence':0,'candidate':'legacy','nominal_widths':{'F.Cu':.5,'B.Cu':.5},
                         'clearance_policy':{'by_net':{},'routing_floor':.25}},
               'observed_utc':150,'router_sources_sha256':proof['nominal_policy']['sources_sha256'],
               'nominal_geometry': {'track_width':.5,'clearance':.25,'via_size':.6,'via_drill':.3,'layers':['F.Cu','B.Cu'],'pad_layer':'F.Cu'},
               'graph': {'edges': [[0,1],[2,3]], 'pad_index_repr': {'0':0,'1':2}, 'num_points':4, 'zone_blob_fallback':False},
               'net_pads': [{'component_ref': 'J1', 'pad_number': '1', 'net_name':'SIGNAL'}, {'component_ref': 'U1', 'pad_number': '2', 'net_name':'SIGNAL'}]}
    failure['epoch']['rule_context'] = escape.nominal_rule_context(
        GridRouteConfig(track_width=.5,clearance=.25,via_size=.6,via_drill=.3),1)
    return board, argv, proof, identity, failure


def refused(fn, reason):
    try:
        fn()
    except escape.ProofRefusal as error:
        assert error.reason == reason, (error.reason, reason)
    else:
        raise AssertionError('unproved escape accepted')


def test_transport_vector_uses_parser_positions_preserves_net_spelling():
    p=parser()
    argv=['same', 'same', '--nets', 'same', '--track-width=.5', '--output=same', '--json-out','owned', '--final-call-proof','proof','--candidate-artifacts=dest']
    assert escape.routing_vector(argv,p)==['--nets','same','--track-width=.5']
    assert escape.routing_vector(['input','--nets','A','--output','out','--overwrite'],p)==['--nets','A']
    assert escape.routing_vector(['input','out','--','input'],p)==['--','input']
    assert escape.routing_vector(['input','out','-n','A','-O'],p)==['-n','A']


def test_final_call_proof_identity_scope_finalization_and_authority():
    with tempfile.TemporaryDirectory() as tmp:
        board,argv,proof,identity,failure=fixture(Path(tmp))
        assert identity['call_id']=='last-call'
        for field,value,reason in [('deferred_work',[{'id':'later','kind':'connections'}],'deferred_work'),
            ('copper_work',proof['copper_work']+[{'id':'later','kind':'single'}],'not_final_copper_call'),
            ('copper_work',[{'id':'','kind':'pairs'},proof['copper_work'][-1]],'copper_work'),
            ('copper_work',[{'id':'earlier','kind':'unknown'},proof['copper_work'][-1]],'copper_work'),
            ('finalization',['original_rules_drc'],'unsupported_finalization'),
            ('deadline_utc',99,'proof_deadline')]:
            changed=copy.deepcopy(proof);changed[field]=value
            refused(lambda:escape.validate_proof(changed,board=board,argv=argv,parser=parser(),scope=['SIGNAL'],kind='single',layers=['F.Cu','B.Cu'],now=100),reason)
        changed=copy.deepcopy(proof);changed['standing_authority']['available']=False
        refused(lambda:escape.validate_proof(changed,board=board,argv=argv,parser=parser(),scope=['SIGNAL'],kind='single',layers=['F.Cu','B.Cu'],now=100),'standing_unavailable')
        board.with_suffix('.kicad_dru').write_text('new custom constraint')
        refused(lambda:escape.validate_proof(proof,board=board,argv=argv,parser=parser(),scope=['SIGNAL'],kind='single',layers=['F.Cu','B.Cu'],now=100),'input_identity')


def test_bound_nominal_failure_requires_selected_disconnected_physical_peer():
    with tempfile.TemporaryDirectory() as tmp:
        _,_,proof,identity,failure=fixture(Path(tmp))
        assert escape.validate_failure(failure,proof,identity) is failure
        changes=[('proof_sha256','f'*64,'stale_failure'),('nominal_only',False,'nominal_policy_unproved'),
                 ('nominal_result',{'success':False,'via_blocked':False},'nominal_failure_unobserved'),
                 ('graph',{'edges':[[0,1],[1,2],[2,3]],'pad_index_repr':{'0':0,'1':2},'num_points':4,'zone_blob_fallback':False},'already_connected_terminal'),
                 ('graph',None,'graph_unavailable')]
        for field,value,reason in changes:
            changed=copy.deepcopy(failure);changed[field]=value
            refused(lambda:escape.validate_failure(changed,proof,identity),reason)
        changed=copy.deepcopy(failure);changed['peer']['ref']='UNRELATED'
        refused(lambda:escape.validate_failure(changed,proof,identity),'required_peer_scope')
        changed=copy.deepcopy(failure);changed['net_pads'].append(changed['net_pads'][0])
        refused(lambda:escape.validate_failure(changed,proof,identity),'repeated_pad_shape_escape_unproved')
        changed=copy.deepcopy(failure);changed['endpoint']['physical_index']=1
        refused(lambda:escape.validate_failure(changed,proof,identity),'graph_pad_identity')


def test_nominal_receipt_requires_actual_router_values_and_source_identity():
    with tempfile.TemporaryDirectory() as tmp:
        _,_,proof,_,_=fixture(Path(tmp));policy=proof['nominal_policy']
        escape.validate_nominal(policy,{'SIGNAL':{'F.Cu':.5,'B.Cu':.5}})
        refused(lambda:escape.validate_nominal(policy,{'SIGNAL':{'F.Cu':.2,'B.Cu':.2}}),'nominal_values')
        changed=copy.deepcopy(policy);changed['sources_sha256']='a'*64
        refused(lambda:escape.validate_nominal(changed,policy['by_net']),'nominal_source_identity')

def test_failure_recorder_freezes_graph_policy_and_actual_nominal_result():
    from types import SimpleNamespace
    from unittest.mock import patch
    import plane_pad_tap as tap
    with tempfile.TemporaryDirectory() as tmp:
        _,_,proof,identity,failure=fixture(Path(tmp))
        recorder=escape.FailureRecorder(proof,identity)
        from routing_config import GridRouteConfig
        config=GridRouteConfig(track_width=.5,clearance=.25,via_size=.6,via_drill=.3)
        original={'graph':copy.deepcopy(failure['graph']),'net_pads':copy.deepcopy(failure['net_pads'])}
        config.net_clearances = {}
        config.net_clearance_floor = .25
        epoch=recorder.epoch('SIGNAL',original,config,1)
        pad=SimpleNamespace(component_ref='J1',pad_number='1')
        observe=recorder.observer(epoch,pad,config,'F.Cu')
        result=tap.TapResult(success=False,via_blocked=True)
        with patch.object(escape.time,'time',return_value=150):observe(result)
        original['graph']['edges'].append([1,2]);result.via_blocked=False;config.track_width=.1
        proof['call']['obligations'].clear();epoch['graph']['edges'].append([1,2])
        assert len(recorder.eligible())==1
        receipt=recorder.receipt();receipt['nominal_taps'][0]['graph']['edges'].append([1,2])
        assert len(recorder.eligible())==1
        narrow=SimpleNamespace(track_width=.1)
        assert recorder.observer(epoch,pad,narrow,'F.Cu') is None


def test_optional_graph_sink_retains_actual_graph_without_rechecking():
    from types import SimpleNamespace
    from unittest.mock import patch
    import net_rescue
    import check_connected
    from kicad_parser import Pad
    pads=[Pad('J1','1',0,0,0,0,1,1,'rect',['F.Cu'],1,'SIGNAL'),
          Pad('U1','2',5,0,0,0,1,1,'rect',['F.Cu'],1,'SIGNAL')]
    pcb=SimpleNamespace(segments=[],vias=[],zones=[],pads_by_net={1:pads})
    graph={'edges':[[0,1],[2,3]],'pad_index_repr':{0:0,1:2},'num_points':4,'zone_blob_fallback':False}
    with patch.object(check_connected,'check_net_connectivity',return_value={'graph':graph}) as checker:
        legacy=net_rescue._net_component_info(pcb,1)
        sink={}
        observed=net_rescue._net_component_info(pcb,1,graph_out=sink)
        assert observed==legacy and len(observed)==3
        assert checker.call_count==2  # Once per real invocation, no extra probe.
        assert sink['net_pads'][0]['component_ref']=='J1'
        sink['graph']['edges'].append([1,2])
        assert graph['edges']==[[0,1],[2,3]]


def test_nominal_observer_reports_initial_result_and_cannot_change_success():
    from types import SimpleNamespace
    from unittest.mock import patch
    import plane_pad_tap as tap
    from kicad_parser import Pad
    from routing_config import GridRouteConfig
    pad = Pad('J1','1',0,0,0,0,3,3,'rect',['F.Cu'],1,'SIGNAL')
    pcb = SimpleNamespace(board_info=SimpleNamespace(copper_layers=['F.Cu','B.Cu']))
    config = GridRouteConfig(track_width=.5,clearance=.25,via_size=.6,via_drill=.3)
    success = tap.TapResult(success=True)
    def broken(result):
        raise ValueError('evidence storage failed')
    with patch.object(tap,'try_tap_pad',return_value=success) as attempt:
        result=tap.tap_pad_with_escalation(pad,'F.Cu',1,pcb,config,1.5,.6,.3,nominal_observer=broken)
        assert result is success and result.success
        assert pcb._final_escape_evidence_refusal=='ValueError'
        assert attempt.call_count==1
    observed=[]
    failed=tap.TapResult(success=False,via_blocked=True)
    with patch.object(tap,'try_tap_pad',return_value=failed), patch.object(tap,'pad_is_fine_pitch',return_value=False):
        result=tap.tap_pad_with_escalation(pad,'F.Cu',1,pcb,config,1.5,.6,.3,nominal_observer=observed.append)
        assert result is failed and observed==[failed]
    observed=[]
    with patch.object(tap,'try_tap_pad') as attempt, patch.object(tap,'pad_is_fine_pitch',return_value=False):
        tap.tap_pad_with_escalation(pad,'F.Cu',1,pcb,config,1.5,.6,.3,try_default=False,nominal_observer=observed.append)
        assert not attempt.called and observed==[]


def test_nominal_seed_retains_via_only_copper_and_does_not_call_ladder():
    from types import SimpleNamespace
    from unittest.mock import patch
    from kicad_parser import Pad
    from routing_config import GridRouteConfig
    from plane_pad_tap import TapResult
    with tempfile.TemporaryDirectory() as directory:
        _, _, proof, identity, failure = fixture(Path(directory))
        pad = Pad('J1','1',0,0,0,0,1,1,'rect',['F.Cu'],1,'SIGNAL')
        pcb = SimpleNamespace(nets={1:SimpleNamespace(name='SIGNAL')},
                              pads_by_net={1:[pad]}, segments=[], vias=[])
        config = GridRouteConfig(track_width=.5, clearance=.25, via_size=.6, via_drill=.3)
        result = TapResult(success=True, via={'x':0,'y':0,'size':.6,'drill':.3,
                                             'layers':['F.Cu','B.Cu']})
        def actual_graph(pcb, net_id, graph_out):
            graph_out.update(graph=copy.deepcopy(failure['graph']),
                             net_pads=copy.deepcopy(failure['net_pads']))
            return 2, {}, {}
        with patch.object(escape.time,'time',return_value=150), \
             patch('plane_pad_tap.try_tap_pad',return_value=result) as tap, \
             patch('plane_pad_tap.tap_pad_with_escalation') as ladder, \
             patch('net_rescue._net_component_info',side_effect=actual_graph), \
             patch('net_rescue._via_site_clear',return_value=True), \
             patch('pcb_modification.bump_copper_epoch') as bump:
            seed = escape.seed_nominal(pcb,config,proof,identity,[failure,failure])
        assert tap.call_count == 1 and not ladder.called
        assert len(seed['vias']) == 1 and seed['segments'] == []
        assert seed['vias'][0] is pcb.vias[0] and bump.call_count == 1
        assert seed['attempts'][0]['accepted_seed']
        assert config.track_width == .5
        config.net_clearances = {1:.75, 2:1.0}
        failure['epoch']['clearance_policy'] = {
            'by_net':{'1':.75, '2':1.0}, 'routing_floor':.75}
        failure['epoch']['rule_context'] = escape.nominal_rule_context(config,1)
        with patch.object(escape.time,'time',return_value=150), \
             patch('net_rescue._net_component_info',side_effect=actual_graph), \
             patch('plane_pad_tap.try_tap_pad',return_value=result) as tap, \
             patch('net_rescue._via_site_clear',return_value=True) as exact_guard, \
             patch('pcb_modification.bump_copper_epoch'):
            escape.seed_nominal(pcb,config,proof,identity,[failure])
        nominal_config = tap.call_args.args[4]
        assert nominal_config.clearance == .25
        assert nominal_config.net_clearance_floor == .75
        assert nominal_config.pair_clearance(1,2,kind='stack') == 1.0
        assert exact_guard.call_args.args[3] is nominal_config
        assert config.net_clearance_floor is None  # Legacy config unchanged.
        config.track_clearances = {1:.9,2:1.1}
        config.layer_clearances = {'F.Cu':.8}
        config.hole_to_hole_clearance = .35
        config.board_edge_clearance = .6
        failure['epoch']['rule_context'] = escape.nominal_rule_context(config,1)
        with patch.object(escape.time,'time',return_value=150), \
             patch('net_rescue._net_component_info',side_effect=actual_graph), \
             patch('plane_pad_tap.try_tap_pad',return_value=result) as tap, \
             patch('net_rescue._via_site_clear',return_value=True), \
             patch('pcb_modification.bump_copper_epoch'):
            escape.seed_nominal(pcb,config,proof,identity,[failure])
        nominal_config = tap.call_args.args[4]
        assert nominal_config.pair_clearance(1,2,'F.Cu',kind='track') == 1.1
        assert nominal_config.hole_to_hole_clearance == .35
        assert nominal_config.board_edge_clearance == .6
        config.track_clearances[2] = 1.2
        with patch.object(escape.time,'time',return_value=150), \
             patch('net_rescue._net_component_info',side_effect=actual_graph), \
             patch('plane_pad_tap.try_tap_pad') as tap:
            refused(lambda: escape.seed_nominal(pcb,config,proof,identity,[failure]),
                    'seed_nominal_rule_context_changed')
        assert not tap.called
        config.net_clearances[1] = .8
        with patch.object(escape.time,'time',return_value=150), \
             patch('net_rescue._net_component_info',side_effect=actual_graph), \
             patch('plane_pad_tap.try_tap_pad') as tap:
            refused(lambda: escape.seed_nominal(pcb,config,proof,identity,[failure]),
                    'seed_nominal_clearance_map_changed')
        assert not tap.called
        failure['graph']['edges'].append([1,2])
        with patch.object(escape.time,'time',return_value=150), \
             patch('net_rescue._net_component_info',side_effect=actual_graph), \
             patch('plane_pad_tap.try_tap_pad') as tap:
            # Keep the historical disconnected evidence; fresh graph now
            # joins the required peer and must suppress another nominal tap.
            historical = copy.deepcopy(failure)
            historical['graph']['edges'].pop()
            refused_seed = escape.seed_nominal(pcb,config,proof,identity,[historical])
        assert not tap.called and not refused_seed['vias']
        assert refused_seed['attempts'][0]['refusal'].startswith('fresh_input_')


def test_candidate_bundle_matches_copper_summary_and_refuses_reuse():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        board, _, proof, identity, _ = fixture(root)
        candidates = [{'name':'legacy', 'board':board,
                       'summary':{'open':1}, 'rc':0}]
        destination = root / 'artifacts'
        receipt = escape.persist_artifacts(destination,proof,identity,candidates,
                                           {'escape_refused':'no_nominal_failure'})
        manifest = json.loads((destination / 'receipt.json').read_text())
        assert manifest['incumbent'] == 'legacy'
        assert manifest['adoption'] == 'withheld_pending_finalized_full_standing'
        assert receipt['receipt_sha256'] == escape.digest(destination / 'receipt.json')
        for name, expected in manifest['candidates'][0]['files'].items():
            assert escape.digest(destination / 'legacy' / name) == expected
        assert (destination / 'legacy' / 'board.kicad_pcb').read_bytes() == board.read_bytes()
        refused(lambda: escape.persist_artifacts(destination,proof,identity,candidates,{}),
                'candidate_artifacts_exist')
        invalid = [dict(candidates[0], name='pocket')]
        refused(lambda: escape.persist_artifacts(root / 'bad',proof,identity,invalid,{}),
                'candidate_slot_inventory')
        assert not (root / 'bad').exists()


def _controller_case(failure_mode=None):
    import os
    import time
    from types import SimpleNamespace
    from unittest.mock import patch
    import route_candidates
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        board, argv, proof, _, failure = fixture(root)
        proof['deadline_utc'] = time.time() + 100
        identity = escape.validate_proof(proof, board=board, argv=argv, parser=parser(),
            scope=['SIGNAL'], kind='single', layers=['F.Cu','B.Cu'])
        failure.update(identity)
        proof_file = root / 'proof.json'
        proof_file.write_text(json.dumps(proof))
        args = SimpleNamespace(input_file=str(board), output_file=str(root/'out.kicad_pcb'),
            json_out=str(root/'result.json'), preview=False, skip_routing=False,
            schematic_dir=None, connections=None, final_call_proof=str(proof_file),
            candidate_artifacts=str(root/'artifacts'), layers=['F.Cu','B.Cu'],
            track_width=.5, clearance=.25, via_size=.6, via_drill=.3)
        calls = []
        def run(command, log, env, deadline):
            if '--grade' in command:
                Path(command[-1]).write_text(json.dumps({'known':True,'drc':0,
                    'undersized':0,'widths_unknown':False,'open':1,'quality':[1,10,10]}))
                return 0
            context_file = env.get('KRT_INTERNAL_FINAL_CALL_CONTEXT')
            context = json.loads(Path(context_file).read_text()) if context_file else None
            name = context['candidate'] if context else (
                'pocket' if env['KRT_INTERNAL_POCKET_WALLS']=='1' else 'legacy')
            calls.append(name)
            if not failure_mode:
                assert env['KRT_INTERNAL_POCKET_WALLS'] == '0'
            if failure_mode != 'context_write':
                assert deadline <= time.monotonic() + 100
            output = Path(command[command.index('--output')+1])
            output.write_text(name)
            log.write_text(name)
            summary = {'regrade':{}, 'failed_single':['SIGNAL'] if name!='escape' else []}
            Path(command[command.index('--json-out')+1]).write_text(json.dumps(summary))
            if context:
                escape.write_record(context['evidence_file'], {'nominal_taps':[failure]})
                if failure_mode == 'stale_no_completion':
                    recorder = escape.FailureRecorder(proof,identity,
                        evidence_file=context['evidence_file'])
                    recorder.records.append(failure)
                    recorder.flush()
                    with patch.object(escape,'write_record',side_effect=OSError('later disk failure')), \
                         patch.object(escape,'print',side_effect=BrokenPipeError('log failed'),create=True):
                        recorder.flush()
                        recorder.finish()
                    assert recorder.disabled and not recorder.eligible()
                    stale = json.loads(Path(context['evidence_file']).read_text())
                    assert not stale['disabled'] and stale['nominal_taps']
                if failure_mode != 'stale_no_completion':
                    with log.open('a') as stream:
                        stream.write('\nFINAL_CALL_EVIDENCE_COMPLETE: ' + json.dumps({
                            'schema':1,'proof_sha256':identity['proof_sha256'],
                            'call_id':identity['call_id'],
                            'evidence_sha256':escape.digest(context['evidence_file'])}))
                if failure_mode == 'stale_evidence':
                    # Prior eligible JSON survived a subsequent failed update.
                    with log.open('a') as stream:
                        stream.write('\nFINAL_CALL_EVIDENCE_REFUSED: ' + json.dumps(identity))
            return 0
        original_write = escape.write_record
        def write(path, record):
            if failure_mode == 'context_write' and Path(path).name == 'context.json':
                raise OSError('optional context storage failed')
            return original_write(path,record)
        with patch.dict(os.environ,{},clear=True), patch.object(route_candidates,'run_child',side_effect=run), \
             patch.object(escape,'write_record',side_effect=write):
            assert route_candidates.maybe_run_candidates(args,argv,'route.py',parser(),['SIGNAL']) == 0
        assert calls == ['legacy','pocket' if failure_mode else 'escape']
        assert Path(args.output_file).read_text() == 'legacy'
        if not failure_mode:
            bundle = json.loads((root/'artifacts'/'receipt.json').read_text())
            assert [c['name'] for c in bundle['candidates']] == calls
            assert (root/'artifacts'/'escape'/'board.kicad_pcb').read_text() == 'escape'
        else:
            assert not (root/'artifacts'/'escape').exists()
        assert json.loads(Path(args.json_out).read_text())['route_candidates']['selected'] == 'legacy'


def test_escape_uses_second_slot_but_never_locally_replaces_incumbent():
    _controller_case()


def test_optional_context_write_and_stale_evidence_failure_keep_normal_policy():
    _controller_case('context_write')
    _controller_case('stale_evidence')
    _controller_case('stale_no_completion')


def test_optional_child_context_load_failure_only_discards_escape():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        board, _, proof, identity, _ = fixture(root)
        bad = root/'context.json'
        bad.write_text('{malformed')
        assert escape.optional_child_context(bad,board,['SIGNAL'],['F.Cu','B.Cu'],
            candidate='legacy',identity=identity) is None
        try:
            escape.optional_child_context(bad,board,['SIGNAL'],['F.Cu','B.Cu'],
                candidate='escape',identity=identity)
        except ValueError:
            pass
        else:
            raise AssertionError('malformed escape context was allowed')
        context = {'proof':proof,'identity':identity,'candidate':'legacy'}
        bad.write_text(json.dumps(context))
        assert escape.optional_child_context(bad,board,['SIGNAL'],['F.Cu','B.Cu'],
            candidate='legacy',identity=identity) == context
        different_call = dict(identity,call_id='different-call')
        assert escape.optional_child_context(bad,board,['SIGNAL'],['F.Cu','B.Cu'],
            candidate='legacy',identity=different_call) is None


def test_connection_task_identity_and_conflicting_terminal_policies():
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / 'tasks.json'
        task = {'net': 'SIGNAL', 'from': {'ref': 'J1', 'pad': '1'},
                'to': {'ref': 'U1', 'pad': '2'}, 'widths': {'F.Cu': .5}}
        obligation = dict(task, task_sha256=escape.record_digest(escape.task_identity(task)))
        path.write_text(json.dumps([task]))
        escape.validate_task_scope(path, [obligation])
        wrong = dict(obligation, task_sha256='0' * 64)
        refused(lambda: escape.validate_task_scope(path, [wrong]), 'connection_task_identity')
        sibling = copy.deepcopy(task)
        sibling['to'] = {'ref': 'U2', 'pad': '3'}
        sibling['widths']['F.Cu'] = .3
        path.write_text(json.dumps([task, sibling]))
        refused(lambda: escape.validate_task_scope(path, [obligation]),
                'connection_terminal_policy_conflict')
        sibling['from'] = {'ref': 'J2', 'pad': '1'}
        path.write_text(json.dumps([task, sibling]))
        refused(lambda: escape.validate_task_scope(path, [obligation]),
                'connection_net_policy_conflict')
        sibling['widths']['F.Cu'] = .5
        path.write_text(json.dumps([task, sibling]))
        escape.validate_task_scope(path, [obligation])


def test_legacy_policy_and_evidence_errors_preserve_model_and_disable_eligibility():
    from types import SimpleNamespace
    from unittest.mock import patch
    from routing_config import GridRouteConfig
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        _, _, proof, identity, _ = fixture(root)
        pcb = SimpleNamespace(nets={1:SimpleNamespace(name='SIGNAL')}, segments=[], vias=[])
        cfg = GridRouteConfig(track_width=.2)
        context = {'proof':proof, 'identity':identity, 'candidate':'legacy',
                   'evidence_file':str(root/'evidence.json')}
        recorder, seed = escape.prepare_runtime(pcb,cfg,context)
        assert recorder is None and seed is None
        assert not pcb.segments and not pcb.vias and cfg.track_width == .2
        assert json.loads((root/'evidence.json').read_text())['disabled']
        cfg.track_width = .5
        with patch.object(escape,'write_record',side_effect=OSError('receipt failure')):
            recorder, seed = escape.prepare_runtime(pcb,cfg,context)
        assert seed is None and recorder.disabled and not recorder.eligible()
        assert not pcb.segments and not pcb.vias and cfg.track_width == .5


def test_rescue_epoch_and_observer_errors_preserve_legacy_tap_and_failure_result():
    from types import SimpleNamespace
    from unittest.mock import patch
    import net_rescue
    from plane_pad_tap import TapResult
    from routing_config import GridRouteConfig
    from synth import make_net, make_pad, make_pcb
    class BrokenRecorder:
        def __init__(self, stage):
            self.stage, self.disabled = stage, False
        def epoch(self, *args):
            if self.stage == 'epoch':
                raise ValueError('epoch storage')
            return {}
        def observer(self, *args):
            raise ValueError('observer serialization')
        def invalidate(self, error):
            self.disabled = True
    def run(recorder):
        pads=[make_pad(1,0,0,ref='J1',num='1',net_name='SIGNAL'),
              make_pad(1,5,0,ref='U1',num='2',net_name='SIGNAL')]
        pcb=make_pcb(nets={1:make_net(1,'SIGNAL')},pads_by_net={1:pads})
        state=SimpleNamespace(pcb_data=pcb,config=GridRouteConfig(track_width=.5),
                              routed_results={})
        with patch.object(net_rescue.env_knobs,'NET_RESCUE',True), \
             patch.object(net_rescue.env_knobs,'BARE_PAD_ESCAPE',True), \
             patch('plane_pad_tap.tap_pad_with_escalation',return_value=TapResult(False)) as tap, \
             patch.object(net_rescue,'_attempt_edge',return_value=(None,None)), \
             patch.object(net_rescue,'record_net_event'), \
             patch.object(net_rescue.time,'time',return_value=150):
            summary=net_rescue.rescue_failed_nets(state,[('SIGNAL',1)],nominal_recorder=recorder)
        return summary,tap.call_count,list(pcb.segments),list(pcb.vias)
    legacy=run(None)
    assert legacy[1] == 2
    for stage in ('epoch','observer'):
        recorder=BrokenRecorder(stage)
        assert run(recorder) == legacy
        assert recorder.disabled
    # Exercise the actual recorder's invalidation sink through the same
    # incumbent rescue path, with an already-broken optional log transport.
    with tempfile.TemporaryDirectory() as directory:
        _, _, proof, identity, _ = fixture(Path(directory))
        recorder = escape.FailureRecorder(proof,identity)
        with patch.object(recorder,'epoch',side_effect=ValueError('epoch')), \
             patch.object(escape,'print',side_effect=BrokenPipeError('optional log'),create=True):
            assert run(recorder) == legacy
        assert recorder.disabled and not recorder.eligible()


if __name__ == '__main__':
    tests = [fn for name, fn in sorted(globals().items()) if name.startswith('test_')]
    for test in tests:
        test()
        print('PASS', test.__name__)
    print(len(tests), 'passed')
