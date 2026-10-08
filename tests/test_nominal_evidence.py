"""Pinned existing failure validator: synthetic geometry, no native board or route."""
import copy,hashlib,importlib.util,json,sys,time
from pathlib import Path
import pytest
KRT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(KRT/'py_router'))
import final_escape as escape
import route_candidates as worker
import test_final_escape as existing

@pytest.fixture
def packet(tmp_path):
    board,argv,proof,identity,failure=existing.fixture(tmp_path)
    deadline=time.time()+60;proof['deadline_utc']=deadline
    identity=escape.validate_proof(proof,board=board,argv=argv,parser=existing.parser(),scope=['SIGNAL'],kind='single',layers=['F.Cu','B.Cu'])
    failure.update(proof_sha256=identity['proof_sha256'],policy_sha256=identity['policy_sha256'],observed_utc=time.time())
    context=tmp_path/'context.json';evidence=tmp_path/'evidence.json';log=tmp_path/'router.log';summary=tmp_path/'summary.json'
    context.write_text(json.dumps(dict(proof=proof,identity=identity,candidate='legacy',evidence_file=str(evidence))))
    summary.write_text(json.dumps({'execution_policy':{'schema':2,'policy':'nested-board-candidates-disabled','board_proposals':1,'deadline_utc':deadline,'nets':['SIGNAL'],'layers':['F.Cu','B.Cu']}}))
    request={'schema':1,'deadline_utc':deadline,'board':str(board),'context':str(context),'evidence':str(evidence),'log':str(log),'summary':str(summary),'files':{}}
    def save(record=failure):
        evidence.write_text(json.dumps({'schema':1,'disabled':False,'nominal_taps':[record]}))
        marker=dict(schema=1,proof_sha256=identity['proof_sha256'],call_id=identity['call_id'],evidence_sha256=escape.digest(evidence))
        log.write_text('FINAL_CALL_EVIDENCE_COMPLETE: '+json.dumps(marker)+'\n')
        paths=[board,board.with_suffix('.kicad_pro'),board.with_suffix('.kicad_dru'),context,evidence,log,summary]
        request['files']={str(path.resolve()):escape.digest(path) if path.is_file() else None for path in paths}
    save()
    return request,failure,save

def test_nominal_failed_tap_with_separate_peer_is_eligible(packet):
    request,failure,save=packet
    result=worker.nominal_evidence_request(request)
    assert result['failures']==[failure] and result['comparison_authority'] is False

@pytest.mark.parametrize('mode',['connected','escalated','successful','stale'])
def test_unproved_nominal_failures_are_not_candidates(packet,mode):
    request,failure,save=packet
    if mode=='connected':failure['graph']['edges'].append([1,2])
    elif mode=='escalated':failure['nominal_only']=False
    elif mode=='successful':failure['nominal_result']['success']=True
    else:failure['proof_sha256']='0'*64
    save(failure)
    assert worker.nominal_evidence_request(request)['failures']==[]

@pytest.mark.parametrize('marker',['aborted','cancelled','timed_out','deferred_nets'])
def test_completed_metadata_does_not_hide_interrupted_or_deferred_summary(packet,marker):
    request,failure,save=packet;path=Path(request['summary']);value=json.loads(path.read_text());value[marker]=True;path.write_text(json.dumps(value));save()
    with pytest.raises(ValueError):worker.nominal_evidence_request(request)

def test_changed_log_cannot_reuse_positive_marker(packet):
    request,_,_=packet;Path(request['log']).write_text('replacement without completion')
    with pytest.raises(ValueError,match='artifact changed'):worker.nominal_evidence_request(request)

def test_actual_owned_evidence_worker_returns_fresh_bound_reply(packet,tmp_path):
    import os
    request,_,_=packet;source=KRT/'py_router/route_candidates.py'
    given=tmp_path/'request.json';reply=tmp_path/'reply.json';given.write_text(json.dumps(request))
    before=escape.digest(source)
    log=tmp_path/'worker.log'
    remaining=request['deadline_utc']-time.time()
    assert remaining>0
    code=worker.run_child([sys.executable,str(source),'--nominal-evidence',str(given),str(reply)],
        log,dict(os.environ,PYTHONPATH=str(KRT/'py_router'),KRT_ROUTE_DEADLINE_UTC=str(request['deadline_utc'])),
        time.monotonic()+remaining)
    assert code==0,log.read_text()
    value=json.loads(reply.read_bytes());assert len(value['failures'])==1
    assert value['files']==request['files'] and escape.digest(source)==before


def test_owned_internal_escape_transport_bypasses_public_candidates(packet,monkeypatch,tmp_path):
    request,_,_=packet
    monkeypatch.setenv('KRT_INTERNAL_ROUTE_CANDIDATE','1')
    assert worker.maybe_run_candidates(None,[],str(KRT/'py_router/route.py'),existing.parser(),['SIGNAL'],['F.Cu','B.Cu']) is None
    context=json.loads(Path(request['context']).read_bytes())
    context['candidate']='escape';context['evidence_file']=str(tmp_path/'fresh-seed.json')
    seed=tmp_path/'seed-context.json';seed.write_text(json.dumps(context))
    argv=[request['board'],str(tmp_path/'seed-board.kicad_pcb'),*context['proof']['call']['routing_flags']]
    actual=escape.validated_child_context(seed,request['board'],['SIGNAL'],['F.Cu','B.Cu'],
        argv=argv,parser=existing.parser(),tasks=None,candidate='escape',identity=context['identity'])
    assert actual['candidate']=='escape' and actual['evidence_file']!=request['evidence']


@pytest.mark.parametrize('field',['summary','context','evidence','log'])
def test_transient_read_substitution_refuses_exact_decoded_bytes(packet,monkeypatch,field):
    request,_,_=packet;target=Path(request[field]);read=Path.read_bytes
    def substituted(path):
        raw=read(path)
        # digest() uses read_bytes too: allow the first hash inspection, then
        # substitute only the later decode read without changing disk bytes.
        if path==target:
            substituted.calls+=1
            if substituted.calls==2:return raw+b' '
        return raw
    substituted.calls=0
    monkeypatch.setattr(Path,'read_bytes',substituted)
    with pytest.raises(ValueError,match='decoded bytes changed'):
        worker.nominal_evidence_request(request)
