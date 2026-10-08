from pathlib import Path
from types import SimpleNamespace
import hashlib
import sys
import pytest

KRT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(KRT_ROOT/'py_router'))
from seed_site_policy import captured_original, conventional_site_filter, SitePolicyRefusal
from kicad_parser import Pad
from paste_apertures import PasteAperture


def board(pads=(), apertures=()):
    return SimpleNamespace(board_info=SimpleNamespace(copper_layers=['F.Cu','In1.Cu','B.Cu']), footprints={'U':SimpleNamespace(pads=list(pads))},
                           paste_apertures=list(apertures))


def pad(layer='F.Cu', shape='rect', rotation=0):
    p = Pad('U','1',0,0,0,0,1,1,shape,[layer],7,'FOREIGN')
    p.rect_rotation = rotation
    return p


def test_foreign_net_barrel_and_boundary_are_not_authorized():
    allowed = conventional_site_filter(board([pad()]), .6, ['F.Cu','B.Cu'])
    assert not allowed(0,0)
    assert not allowed(.8,0)
    assert allowed(.801,0)


def test_layer_participation_is_exact():
    allowed = conventional_site_filter(board([pad('B.Cu')]), .6, ['F.Cu','In1.Cu'])
    assert allowed(0,0)
    assert not conventional_site_filter(board([pad('B.Cu')]), .6, ['F.Cu','B.Cu'])(0,0)


def test_unassigned_paste_is_not_dropped():
    ap = PasteAperture('', 'F.Paste','graphic',net_id=0,circle=(0,0,.5))
    allowed = conventional_site_filter(board(apertures=[ap]), .6, ['F.Cu','B.Cu'])
    assert not allowed(0,0)
    assert not allowed(.8,0)
    assert allowed(.801,0)


def test_unsupported_pad_or_approximate_paste_refuses():
    with pytest.raises(SitePolicyRefusal):
        conventional_site_filter(board([pad(shape='custom')]),.6,['F.Cu'])
    ap=PasteAperture('', 'F.Paste','graphic',approximations=('unsupported',))
    with pytest.raises(SitePolicyRefusal):
        conventional_site_filter(board(apertures=[ap]),.6,['F.Cu'])


def test_original_source_bytes_and_custody_are_bound(tmp_path):
    path=tmp_path/'original.kicad_pcb'
    path.write_text('(kicad_pcb (setup (capping no) (filling no)))')
    record={'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
            'custody_sha256':'a'*64}
    result=captured_original(record)
    assert result['source']==record
    assert result['setup']['capping']=='no' and result['setup']['filling']=='no'
    assert result['authorization']=='unproved'
    path.write_text('(kicad_pcb (setup (capping yes) (filling yes)))')
    with pytest.raises(SitePolicyRefusal,match='changed'):
        captured_original(record)

@pytest.mark.parametrize('clearance', [-1.0, 0.0, .25])
@pytest.mark.parametrize('mutate_original', [False, True])
def test_actual_seed_callee_receives_exact_policy_and_conventional_filter(tmp_path, clearance, mutate_original):
    import importlib.util
    import copy
    from unittest.mock import patch
    from routing_config import GridRouteConfig
    from plane_pad_tap import TapResult
    def load(name, path):
        spec=importlib.util.spec_from_file_location(name,path)
        module=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    old=load('old_seed_fixture',KRT_ROOT/'tests/test_final_escape.py')
    import final_escape as escape
    _,_,proof,identity,failure=old.fixture(tmp_path)
    original=tmp_path/'original.kicad_pcb'
    original.write_text('(kicad_pcb (setup (capping no) (filling no)))')
    proof['original_fabrication']={'path':str(original),'sha256':hashlib.sha256(original.read_bytes()).hexdigest(),'custody_sha256':'b'*64}
    identity['proof_sha256']=escape.record_digest(proof)
    failure['proof_sha256']=identity['proof_sha256']
    p=Pad('J1','1',0,0,0,0,1,1,'rect',['F.Cu'],1,'SIGNAL')
    pcb=board([p]);pcb.nets={1:SimpleNamespace(name='SIGNAL')}
    pcb.pads_by_net={1:[p]};pcb.segments=[];pcb.vias=[]
    config=GridRouteConfig(track_width=.5,clearance=.25,via_size=.6,via_drill=.3,
                          same_net_pad_clearance=clearance)
    failure['epoch']['rule_context']=escape.nominal_rule_context(config,1)
    def graph(pcb,nid,graph_out):
        graph_out.update(graph=copy.deepcopy(failure['graph']),net_pads=copy.deepcopy(failure['net_pads']))
        return 2,{},{}
    def tap(*args, **kwargs):
        assert kwargs['same_net_pad_clearance']==clearance
        assert not kwargs['seed_site_filter'](0,0)
        assert kwargs['seed_site_filter'](2,0)
        if mutate_original:
            original.write_text('(kicad_pcb (setup (capping yes) (filling yes)))')
        return TapResult(success=True,via={'x':1,'y':0,'size':.6,'drill':.3,'layers':['F.Cu','B.Cu']})
    with patch.object(escape.time,'time',return_value=150), patch('net_rescue._net_component_info',side_effect=graph), patch('plane_pad_tap.try_tap_pad',side_effect=tap) as actual_tap, patch('net_rescue._via_site_clear',return_value=True), patch('pcb_modification.bump_copper_epoch'):
        if mutate_original:
            with pytest.raises(SitePolicyRefusal, match='original_fabrication_source_changed'):
                escape.seed_nominal(pcb,config,proof,identity,[failure,failure])
            assert actual_tap.call_count == 1
            return
        result=escape.seed_nominal(pcb,config,proof,identity,[failure,failure])
    assert actual_tap.call_count==1
    assert result['attempts'][0]['accepted_seed']
    assert result['attempts'][0]['original_fabrication']['source']==proof['original_fabrication']

@pytest.mark.parametrize('layers', [['Bad.Cu'],['B.Cu','F.Cu'],['F.Cu','F.Cu'],[]])
def test_invalid_layer_span_refuses(layers):
    with pytest.raises(SitePolicyRefusal):
        conventional_site_filter(board([pad()]),.6,layers)

@pytest.mark.parametrize('ratio', [float('nan'), -.1, .6, True])
def test_invalid_roundrect_refuses(ratio):
    p=pad(shape='roundrect');p.roundrect_rratio=ratio
    with pytest.raises(SitePolicyRefusal):
        conventional_site_filter(board([p]),.6,['F.Cu'])

@pytest.mark.parametrize('ring', [[(0,0),(1,1),(0,1),(1,0)],[(0,0),(0,0),(0,0)],[(0,0,1),(1,0),(0,1)]])
def test_invalid_paste_polygon_refuses(ring):
    ap=PasteAperture('', 'F.Paste','graphic',rings=[ring])
    with pytest.raises(SitePolicyRefusal):
        conventional_site_filter(board(apertures=[ap]),.6,['F.Cu'])


def test_actual_finder_skips_pad_and_uses_bounded_offpad_site():
    from route_planes import find_via_position
    from routing_config import GridCoord
    p=pad()
    coord=GridCoord(.1)
    obstacles=SimpleNamespace(is_via_blocked=lambda x,y: False)
    allowed=conventional_site_filter(board([p]),.6,['F.Cu','B.Cu'])
    found=find_via_position(p,obstacles,coord,1.5,position_filter=allowed)
    assert found is not None and allowed(*found)
    assert abs(found[0]) <= 1.5 and abs(found[1]) <= 1.5
    assert find_via_position(p,obstacles,coord,1.5,position_filter=lambda x,y:False) is None

@pytest.mark.parametrize('seed_filter, expected, zone', [(lambda x,y:x>.8,False,False),(None,True,False),(None,True,True),(lambda x,y:x>.8,False,True)])
def test_actual_tap_postclamp_filter_is_seed_only(seed_filter, expected, zone):
    from unittest.mock import patch
    from routing_config import GridRouteConfig
    import plane_pad_tap as tap
    p=pad();pcb=board([p]);pcb.zones=[];pcb.vias=[];pcb.segments=[]
    if zone:
        pcb.zones=[SimpleNamespace(net_id=7,polygon=[(-.2,-.2),(1.2,-.2),(1.2,.2),(-.2,.2)])]
    if zone and seed_filter is None:
        pcb.zones[0].polygon=[(.9,-.2),(1.2,-.2),(1.2,.2),(.9,.2)]
    config=GridRouteConfig(via_size=.6,via_drill=.3)
    def finder(*args,**kwargs):
        predicate=kwargs['position_filter']
        if seed_filter is not None:
            assert not predicate(0,0) and predicate(1,0)
            if zone:
                assert not predicate(2,0)  # seed allows, zone refuses
        elif zone:
            assert predicate(1,0) and not predicate(2,0)
        else:
            assert predicate is None
        return (1,0)
    with patch.object(tap,'make_local_window',return_value=pcb), patch.object(tap,'build_via_obstacle_map',return_value=object()), patch('route_planes.find_via_position',side_effect=finder), patch.object(tap,'clamp_tap_via_to_edge',return_value=((0,0),True)):
        result=tap.try_tap_pad(p,'F.Cu',7,pcb,config,0,.6,.3,disable_reuse=True,seed_site_filter=seed_filter)
    assert result.success is expected

@pytest.mark.parametrize('field, value', [('path','other.kicad_pcb'),('sha256','c'*64),('custody_sha256','d'*64)])
def test_actual_context_binding_refuses_original_record_substitution(tmp_path, field, value):
    import final_escape as actual
    import importlib.util
    import json
    spec=importlib.util.spec_from_file_location('capture_fixture',KRT_ROOT/'tests/test_final_escape.py')
    fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)
    source,_,proof,identity,_=fixture.fixture(tmp_path)
    proof['original_fabrication']={'path':str(source),'sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'custody_sha256':'b'*64}
    identity['proof_sha256']=actual.record_digest(proof)
    context={'proof':proof,'identity':identity,'candidate':'escape','evidence_file':str(tmp_path/'evidence.json'),'failures':[]}
    path=tmp_path/'context.json';path.write_text(json.dumps(context))
    assert actual.load_child_context(path,source,['SIGNAL'],['F.Cu','B.Cu'])['proof']['original_fabrication']==proof['original_fabrication']
    context['proof']['original_fabrication'][field]=value
    path.write_text(json.dumps(context))
    with pytest.raises(actual.ProofRefusal,match='child_context_binding'):
        actual.load_child_context(path,source,['SIGNAL'],['F.Cu','B.Cu'])
