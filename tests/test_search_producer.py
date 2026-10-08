"""Controlled actual prepared-map producer and shared failure-epoch seam."""
import ast
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
HERE = ROOT / "py_router"
sys.path.insert(0, str(HERE))


@pytest.fixture
def evidence(monkeypatch):
    import failure_evidence as module
    monkeypatch.setitem(sys.modules,'failure_evidence',module)
    def record(state, net_id, event, details=None):
        state.net_history.setdefault(net_id,[]).append({'event':event,'details':details})
    monkeypatch.setitem(sys.modules,'routing_state',SimpleNamespace(record_net_event=record))
    return module


def actual_prepared_producer(evidence, search, prepare, restore):
    source=ast.parse((HERE/'single_ended_loop.py').read_text())
    node=next(n for n in source.body if isinstance(n,ast.FunctionDef) and n.name=='_route_on_prepared_map')
    namespace={'route_net_with_obstacles':search,'prepare_obstacles_inplace':prepare,
               'restore_obstacles_inplace':restore}
    exec(compile(ast.Module(body=[node],type_ignores=[]),str(HERE/'single_ended_loop.py'),'exec'),namespace)
    return namespace[node.name]


def state():
    return SimpleNamespace(net_history={},working_obstacles={},all_unrouted_net_ids={7},
                           net_obstacles_cache={},ripped_route_layer_costs={},ripped_route_via_positions={})


def test_actual_prepared_map_captures_before_restoration_and_preserves_result(evidence,monkeypatch):
    owner=state();calls=[];cfg=SimpleNamespace(failure_evidence=True,track_width=.5)
    result={'failed':True,'blocked_cells_forward':[1,2],'iterations_forward':12}
    def prepare(*args):calls.append('prepare');owner.working_obstacles['prepared']=True;return None,[]
    def search(*args):calls.append('search');return result
    def facts(actual,board,config,net,nets):
        calls.append('capture');assert owner.working_obstacles['prepared'];assert actual is result
        assert config is cfg and nets=={7};return {'forward':{'iterations':12,'frontier_cells':2},'backward':{},'static':[]}
    monkeypatch.setattr(evidence,'search_facts',facts)
    def restore(*args):calls.append('restore');owner.working_obstacles.clear()
    producer=actual_prepared_producer(evidence,search,prepare,restore)
    assert producer(object(),7,cfg,owner,set(),None,None) is result
    assert calls==['prepare','search','capture','restore']
    assert result['blocked_cells_forward']==[1,2]
    assert evidence.evidence_of(owner,7)['search']['forward']['frontier_cells']==2


def test_actual_prepared_evidence_off_does_no_fact_work_or_events(evidence,monkeypatch):
    owner=state();result={'failed':True,'blocked_cells_forward':[1]}
    monkeypatch.setattr(evidence,'search_facts',lambda *a:pytest.fail('evidence disabled'))
    producer=actual_prepared_producer(evidence,lambda *a:result,lambda *a:(None,[]),lambda *a:None)
    assert producer(object(),7,SimpleNamespace(failure_evidence=False),owner,set(),None,None) is result
    assert owner.net_history=={} and result['blocked_cells_forward']==[1]


def test_latest_attempt_config_and_frontier_replace_initial_epoch(evidence,monkeypatch):
    owner=state();observed=[]
    def facts(result,board,config,net,nets):
        observed.append(config.track_width)
        return {'forward':{'iterations':result['iterations_forward'],'frontier_cells':len(result['blocked_cells_forward'])},'backward':{},'static':[]}
    monkeypatch.setattr(evidence,'search_facts',facts)
    observe=evidence.search_observer(owner,{7})
    initial={'failed':True,'iterations_forward':10,'blocked_cells_forward':[1,2]}
    retry={'failed':True,'iterations_forward':20,'blocked_cells_forward':[3]}
    observe(initial,None,SimpleNamespace(failure_evidence=True,track_width=.5),7)
    observe(retry,None,SimpleNamespace(failure_evidence=True,track_width=.3),7)
    assert observed==[.5,.3]
    assert evidence.evidence_of(owner,7)['search']['forward']=={'iterations':20,'frontier_cells':1}
    assert initial['blocked_cells_forward']==[1,2] and retry['blocked_cells_forward']==[3]


@pytest.mark.parametrize(('outcome','rejected'),[(None,False),({'new_segments':[]},False),({'new_segments':[]},True)])
def test_unavailable_found_partial_and_rejected_outcomes_clear_old_failure(evidence,monkeypatch,outcome,rejected):
    owner=state();cfg=SimpleNamespace(failure_evidence=True)
    monkeypatch.setattr(evidence,'search_facts',lambda *a:{'forward':{},'backward':{},'static':[]})
    observe=evidence.search_observer(owner,{7})
    observe({'failed':True},None,cfg,7)
    observe(outcome,None,cfg,7,rejected=rejected)
    assert evidence.evidence_of(owner,7)==evidence.EMPTY
    assert all(event['event']!='terminal_escalation_succeeded' for event in owner.net_history[7])


def test_oracle_reparsed_ids_bind_original_semantic_history(evidence,monkeypatch):
    owner=state();owner.pcb_data=SimpleNamespace(nets={7:SimpleNamespace(name='GND'),8:SimpleNamespace(name='VCC')})
    current=SimpleNamespace(nets={103:SimpleNamespace(name='GND'),107:SimpleNamespace(name='VCC')})
    cfg=SimpleNamespace(failure_evidence=True);observed=[]
    def facts(result,board,config,net,nets):
        observed.append((board,net,nets));return {'forward':{},'backward':{},'static':[]}
    monkeypatch.setattr(evidence,'search_facts',facts)
    evidence.oracle_search_observer(owner,{7,8})({'failed':True},current,cfg,107)
    assert observed==[(current,107,{103,107})]
    assert owner.net_history[8][-1]['event']=='search_failed'
    assert 107 not in owner.net_history


@pytest.mark.parametrize('defect',['missing_original_id','duplicate_original_name','duplicate_current_name'])
def test_oracle_incomplete_selected_domain_clears_affected_evidence(evidence,monkeypatch,defect):
    owner=state();owner.pcb_data=SimpleNamespace(nets={7:SimpleNamespace(name='GND'),8:SimpleNamespace(name='VCC')})
    current=SimpleNamespace(nets={103:SimpleNamespace(name='GND'),107:SimpleNamespace(name='VCC')})
    selected={7,8}
    if defect=='missing_original_id':selected.add(999)
    elif defect=='duplicate_original_name':owner.pcb_data.nets[9]=SimpleNamespace(name='VCC')
    else:current.nets[109]=SimpleNamespace(name='VCC')
    for net in (7,8):owner.net_history[net]=[{'event':'search_failed','details':{'forward':{},'backward':{},'static':[]}}]
    monkeypatch.setattr(evidence,'search_facts',lambda *a:pytest.fail('ambiguous domain attributed'))
    evidence.oracle_search_observer(owner,selected)({'failed':True},current,SimpleNamespace(failure_evidence=True),103)
    for net in (7,8):
        assert evidence.evidence_of(owner,net)==evidence.EMPTY
        assert owner.net_history[net][-1]['details']['outcome']=='oracle_name_domain_unproved'
    assert 999 not in owner.net_history


def actual_group_producer(monkeypatch, search, components, add, remove):
    """Execute the actual rung body; replace geometry/native operation boundaries."""
    noop = lambda *a, **k: None
    monkeypatch.setitem(sys.modules, 'obstacle_map', SimpleNamespace(
        build_base_obstacle_map=noop, add_same_net_via_clearance=noop,
        add_same_net_pad_drill_via_clearance=noop))
    monkeypatch.setitem(sys.modules, 'pcb_modification', SimpleNamespace(
        add_route_to_pcb_data=add, remove_route_from_pcb_data=remove))
    monkeypatch.setitem(sys.modules, 'routing_context', SimpleNamespace(_add_free_via_positions=noop))
    monkeypatch.setitem(sys.modules, 'single_ended_routing', SimpleNamespace(route_net_with_obstacles=search))
    monkeypatch.setitem(sys.modules, 'connectivity', SimpleNamespace(
        get_net_endpoints_anchor_split=lambda *a, **k: (None, None, None)))
    tree = ast.parse((HERE / 'net_rescue.py').read_text())
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                and n.name == '_attempt_net_at_geometry')
    namespace = {'_pristine_rescue_map': lambda *a: {}, 'stamp_keep_away': noop,
                 '_net_component_info': components, '_main_component': lambda pads: 0,
                 '_closest_pair': lambda a, b: (1, *a[0], *b[0]),
                 'defaults': SimpleNamespace(RESCUE_MAX_EDGES_PER_NET=2)}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(HERE / 'net_rescue.py'), 'exec'), namespace)
    return namespace[node.name]


@pytest.mark.parametrize('accepted', [True, False])
def test_actual_group_partial_search_clears_stale_failure_before_commit_or_undo(evidence, monkeypatch, accepted):
    owner = state()
    cfg = SimpleNamespace(failure_evidence=True, debug_lines=False)
    observe = evidence.search_observer(owner, {7})
    monkeypatch.setattr(evidence, 'search_facts', lambda *a: {
        'forward': {'iterations': 3, 'frontier_cells': 1}, 'backward': {}, 'static': []})
    observe({'failed': True}, object(), cfg, 7)
    result = {'failed': False, 'segments': [], 'vias': []}
    calls = []
    states = iter([3, 2 if accepted else 3, 3])
    def components(*args):
        num = next(states)
        points = {i: [(float(i), 0.0)] for i in range(num)}
        return num, points, {i: [] for i in range(num)}
    def changed(*args, **kwargs):
        calls.append('commit')
        assert owner.net_history[7][-1]['event'] == 'search_found'
    def undone(*args):
        calls.append('undo')
        assert owner.net_history[7][-1]['event'] == 'search_outcome_unknown'
    producer = actual_group_producer(monkeypatch, lambda *a, **k: result,
                                    components, changed, undone)
    # One real edge is enough to witness a successful partial search with the
    # whole net still open, or a found route rejected by authoritative grouping.
    producer.__globals__['defaults'].RESCUE_MAX_EDGES_PER_NET = 1
    edges, joined = producer(object(), 7, cfg, {}, search_observer=observe)
    assert joined is False
    assert edges == ([result] if accepted else [])
    assert calls == (['commit'] if accepted else ['commit', 'undo'])
    assert evidence.evidence_of(owner, 7)['search'] is None


def test_actual_outer_rung_partial_edges_invalidate_epoch_before_reverse_undo(evidence, monkeypatch):
    """Actual terminal-rung rollback block; native/rung setup is controlled."""
    owner = state()
    cfg = SimpleNamespace(failure_evidence=True)
    observe = evidence.search_observer(owner, {7})
    observe({'failed': False}, object(), cfg, 7)
    edges = [{'ordinal': 1}, {'ordinal': 2}]
    undone = []
    tree = ast.parse((HERE / 'net_rescue.py').read_text())
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                    and n.name == 'terminal_geometry_escalation')
    # Execute the exact consecutive rejection guard and reverse-undo loop.
    containers = [n.body for n in ast.walk(function) if isinstance(n, ast.For)]
    blocks = []
    for body in containers:
        for i, node in enumerate(body[:-1]):
            if (isinstance(node, ast.If) and ast.unparse(node.test)
                    == 'edges and observe_search is not None'):
                blocks.append(body[i:i + 2])
    assert len(blocks) == 1
    def undo(board, edge):
        assert owner.net_history[7][-1]['event'] == 'search_outcome_unknown'
        undone.append(edge['ordinal'])
    namespace = dict(edges=edges, observe_search=observe, pcb_data=object(),
                     cfg=cfg, net_id=7, remove_route_from_pcb_data=undo)
    exec(compile(ast.Module(body=blocks[0], type_ignores=[]),
                 str(HERE / 'net_rescue.py'), 'exec'), namespace)
    assert undone == [2, 1]
    assert evidence.evidence_of(owner, 7)['search'] is None


def test_actual_retry_dispatch_captures_retry_config_before_frontier_consumption(evidence, monkeypatch):
    """Execute actual retry dispatch/observer and failed-result pop statements."""
    tree = ast.parse((HERE / 'single_ended_loop.py').read_text())
    dispatch = next(n for n in ast.walk(tree) if isinstance(n, ast.If)
                    and ast.unparse(n.test) == '_olinks_r')
    observer = next(n for n in ast.walk(tree) if isinstance(n, ast.If)
                    and ast.unparse(n.test) == "getattr(retry_cfg, 'failure_evidence', False)")
    pops = [n for n in ast.walk(tree) if isinstance(n, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id in
                    ('retry_fwd_cells', 'retry_bwd_cells') for t in n.targets)
            and isinstance(n.value, ast.Call) and isinstance(n.value.func, ast.Attribute)
            and n.value.func.attr == 'pop']
    assert len(pops) == 2
    owner = state()
    cfg = SimpleNamespace(failure_evidence=True, track_width=.41)
    result = {'failed': True, 'blocked_cells_forward': [11, 12],
              'blocked_cells_backward': [13]}
    captures = []
    def facts(raw, board, actual_cfg, net, selected):
        assert raw is result and actual_cfg is cfg
        captures.append((list(raw['blocked_cells_forward']), list(raw['blocked_cells_backward'])))
        return {'forward': {'iterations': 9, 'frontier_cells': 2},
                'backward': {'iterations': 3, 'frontier_cells': 1}, 'static': []}
    monkeypatch.setattr(evidence, 'search_facts', facts)
    namespace = dict(_olinks_r=None, retry_multipoint_pads=None, pcb_data=object(),
                     net_id=7, retry_cfg=cfg, retry_obstacles={},
                     retry_attraction_path=None, retry_reverse_direction=False,
                     state=owner, remaining_net_ids={7},
                     route_net_with_obstacles=lambda *a, **k: result)
    exec(compile(ast.Module(body=[dispatch, observer, *pops], type_ignores=[]),
                 str(HERE / 'single_ended_loop.py'), 'exec'), namespace)
    assert captures == [([11, 12], [13])]
    assert namespace['retry_fwd_cells'] == [11, 12]
    assert namespace['retry_bwd_cells'] == [13]
    assert 'blocked_cells_forward' not in result and 'blocked_cells_backward' not in result
    assert evidence.evidence_of(owner, 7)['search']['forward']['iterations'] == 9


def test_actual_attempt_geometry_survives_direction_attachment_json_and_reconcile(evidence, monkeypatch):
    owner = state()
    cfg = SimpleNamespace(failure_evidence=True, layers=['F.Cu', 'B.Cu'],
                          grid_step=.08, via_size=.65, via_drill=.31,
                          get_net_track_width=lambda net, layer: .418 if layer == 'F.Cu' else .5)
    monkeypatch.setattr(evidence, 'search_facts', lambda *a: {
        'forward': {'iterations': 9, 'frontier_cells': 1, 'at': None},
        'backward': {'iterations': 4, 'frontier_cells': 1, 'at': None}, 'static': []})
    evidence.search_observer(owner, {7})({'failed': True}, object(), cfg, 7)
    record = evidence.evidence_of(owner, 7)
    expected = {'grid_step_mm': .08, 'track_widths_mm': {'F.Cu': .418, 'B.Cu': .5},
                'layers': ['F.Cu', 'B.Cu'], 'via_size_mm': .65, 'via_drill_mm': .31}
    assert record['attempt'] == expected
    root = HERE
    attach_node = next(n for n in ast.parse((root / 'connections.py').read_text()).body
                       if isinstance(n, ast.FunctionDef) and n.name == 'attach_evidence')
    namespace = {'List': list, 'Task': object, 'Optional': __import__('typing').Optional,
                 '_end_at': lambda *a: None}
    exec(compile(ast.Module(body=[attach_node], type_ignores=[]), str(root / 'connections.py'), 'exec'), namespace)
    task = SimpleNamespace(status='failed', net='N')
    namespace['attach_evidence']([task], {'N': record})
    import json
    wire = json.loads(json.dumps(task.evidence))
    assert wire['attempt'] == expected and 'end' not in wire['attempt']
    carry = next(n for n in ast.parse((root / 'route_summary.py').read_text()).body
                 if isinstance(n, ast.FunctionDef) and n.name == '_carry_net_evidence')
    namespace = {'Dict': __import__('typing').Dict, 'List': __import__('typing').List}
    exec(compile(ast.Module(body=[carry], type_ignores=[]), str(root / 'route_summary.py'), 'exec'), namespace)
    merged = {}
    namespace['_carry_net_evidence'](merged, [{'net_evidence': {'N': wire}}], {'N'})
    assert merged['net_evidence']['N']['attempt'] == expected


@pytest.mark.parametrize('value', [None, True, 0, -1, float('nan'), float('inf'), '0.4'])
def test_unavailable_attempt_dimensions_are_not_inferred(evidence, value):
    cfg = SimpleNamespace(layers=['F.Cu'], grid_step=value, via_size=value,
                          via_drill=value, get_net_track_width=lambda *a: value)
    record = evidence.attempt_geometry(cfg, 7)
    assert record['grid_step_mm'] is None
    assert record['via_size_mm'] is None and record['via_drill_mm'] is None
    assert record['track_widths_mm'] == {'F.Cu': None}


@pytest.mark.parametrize('layers', [None, [], ['F.Cu', 'F.Cu'], ['Edge.Cuts'], ['Custom.Cu'], ['In31.Cu']])
def test_unsupported_attempt_layer_domain_stays_unknown(evidence, layers):
    cfg = SimpleNamespace(layers=layers, get_net_track_width=lambda *a: pytest.fail('unsupported layer lookup'))
    assert evidence.attempt_geometry(cfg, 7)['layers'] is None
    assert evidence.attempt_geometry(cfg, 7)['track_widths_mm'] is None


def test_actual_grid_config_clone_records_effective_layer_and_net_widths(evidence, monkeypatch):
    from dataclasses import replace
    monkeypatch.syspath_prepend(str(HERE))
    from routing_config import GridRouteConfig
    asked = GridRouteConfig(failure_evidence=True, track_width=.5, grid_step=.1, via_size=1.6,
                            via_drill=.6, layers=['F.Cu', 'B.Cu'])
    assert evidence.attempt_geometry(asked, 7)['track_widths_mm'] == {'F.Cu': .5, 'B.Cu': .5}
    layered = replace(asked, layer_widths={'F.Cu': .6, 'B.Cu': .7})
    assert evidence.attempt_geometry(layered, 7)['track_widths_mm'] == {'F.Cu': .6, 'B.Cu': .7}
    retry = replace(layered, track_width=.418, grid_step=.08, via_size=.65,
                    via_drill=.31, net_track_widths={7: .42},
                    net_layer_widths={7: {'F.Cu': .33}})
    owner = state()
    monkeypatch.setattr(evidence, 'search_facts', lambda *a: {
        'forward': {'iterations': 1, 'frontier_cells': 1, 'at': None},
        'backward': {'iterations': 2, 'frontier_cells': 1, 'at': None}, 'static': []})
    evidence.search_observer(owner, {7})({'failed': True}, object(), retry, 7)
    attempt = evidence.evidence_of(owner, 7)['attempt']
    assert attempt == {'grid_step_mm': .08, 'track_widths_mm': {'F.Cu': .33, 'B.Cu': .42},
                       'layers': ['F.Cu', 'B.Cu'], 'via_size_mm': .65, 'via_drill_mm': .31}
    assert asked.track_width == .5 and asked.via_size == 1.6
