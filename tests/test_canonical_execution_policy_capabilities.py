"""Configured capability CLI, pure source provenance and import-origin controls."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import pytest
ROOT=Path(__file__).resolve().parents[1]
POLICY="KRT_EXECUTION_POLICIES={'schema':1,'legacy_only':True,'pocket':True,'policy_receipt_schema':2,'parent_scope_schema':2,'ordinary_grade_request_schema':2}\n"

def clone(tmp_path,split=True):
    root=tmp_path/'clone';root.mkdir();tools=root/'py_router' if split else root;tools.mkdir(exist_ok=True)
    shutil.copyfile(ROOT/'krt_capabilities.py',root/'krt_capabilities.py')
    shutil.copyfile(ROOT/'py_router/execution_policy_capabilities.py',tools/'execution_policy_capabilities.py')
    (root/'VERSION').write_text('controlled-version\n');(tools/'route.py').write_text(POLICY)
    for name in ('route_execution_receipt.py','route_candidates.py'):(tools/name).write_text('# controlled source-only fixture\n')
    return root,tools

def cli(root,env=None):
    return subprocess.run([sys.executable,str(root/'krt_capabilities.py')],cwd=root,env=env,capture_output=True,text=True,timeout=10)

@pytest.mark.parametrize('split',[False,True])
def test_canonical_cli_root_version_hashes_and_publisher(tmp_path,split):
    root,tools=clone(tmp_path,split);result=cli(root);assert result.returncode==0,result.stderr;caps=json.loads(result.stdout)
    assert caps['root']==str(root) and caps['version']=='controlled-version'
    publisher=tools/'execution_policy_capabilities.py'
    assert caps['execution_policy_publisher']=={'path':str(publisher.resolve()),'sha256':hashlib.sha256(publisher.read_bytes()).hexdigest()}
    policy=caps['execution_policies']['route.py']
    for name,key in [('route.py','route'),('route_execution_receipt.py','helper'),('route_candidates.py','grade')]:
        p=tools/name;assert policy[key+'_path']==str(p.resolve()) and policy[key+'_sha256']==hashlib.sha256(p.read_bytes()).hexdigest()

@pytest.mark.parametrize('change',["'legacy_only':False","'pocket':1","'schema':True"])
def test_malformed_literal_mode_withholds(tmp_path,change):
    import re
    root,tools=clone(tmp_path);key=change.split(':')[0];(tools/'route.py').write_text(re.sub(key+r':(?:1|2|True)',change,POLICY))
    result=cli(root);assert result.returncode==0;assert json.loads(result.stdout)['execution_policies']=={}

@pytest.mark.parametrize('missing',['route.py','route_execution_receipt.py','route_candidates.py'])
def test_missing_policy_source_withholds(tmp_path,missing):
    root,tools=clone(tmp_path);(tools/missing).unlink();result=cli(root);assert result.returncode==0
    assert json.loads(result.stdout)['execution_policies']=={}

@pytest.mark.parametrize('regular',[False,True])
def test_competing_pythonpath_namespace_cannot_shadow_publisher(tmp_path,regular):
    root,tools=clone(tmp_path);competing=tmp_path/'installed';package=competing/'py_router';package.mkdir(parents=True)
    if regular:(package/'__init__.py').write_text('raise RuntimeError("wrong installed package")\n')
    (package/'execution_policy_capabilities.py').write_text('raise RuntimeError("wrong installed publisher")\n')
    result=cli(root,dict(os.environ,PYTHONPATH=str(competing)));assert result.returncode==0,result.stderr
    assert json.loads(result.stdout)['execution_policy_publisher']['path']==str((tools/'execution_policy_capabilities.py').resolve())

def test_wrong_publisher_origin_refuses(tmp_path):
    root,tools=clone(tmp_path);p=tools/'execution_policy_capabilities.py';p.write_text(p.read_text()+"\n__file__='/wrong/publisher.py'\n")
    result=cli(root);assert result.returncode!=0 and 'publisher origin changed' in result.stderr

def test_nested_missing_dependency_propagates(tmp_path):
    root,tools=clone(tmp_path);(tools/'execution_policy_capabilities.py').write_text('import nonexistent_nested_publisher_dependency\n')
    result=cli(root);assert result.returncode!=0 and 'nonexistent_nested_publisher_dependency' in result.stderr
