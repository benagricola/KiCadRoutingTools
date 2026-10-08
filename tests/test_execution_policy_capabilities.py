"""Pure source capability inventory; never imports router CLI/native."""
import importlib.util
from pathlib import Path
import hashlib
import pytest
HERE=Path(__file__).resolve().parents[1]/'py_router'
spec=importlib.util.spec_from_file_location('controlled_capabilities',HERE/'krt_capabilities.py')
caps=importlib.util.module_from_spec(spec);spec.loader.exec_module(caps)

@pytest.fixture
def tool(tmp_path):
    (tmp_path/'py_router').mkdir()
    route=tmp_path/'py_router/route.py'
    route.write_text("KRT_EXECUTION_POLICIES={'schema':1,'legacy_only':True,'pocket':True,'policy_receipt_schema':2,'parent_scope_schema':2,'ordinary_grade_request_schema':2}\n")
    helper=route.with_name('route_execution_receipt.py');helper.write_text('controlled source marker only')
    route.with_name('route_candidates.py').write_text('controlled grade source marker only')
    return tmp_path,route,helper


def test_source_bound_literal_modes(tool):
    root,route,helper=tool
    record=caps.execution_policies(str(root))['route.py']
    assert record['route_sha256']==hashlib.sha256(route.read_bytes()).hexdigest()
    assert record['helper_sha256']==hashlib.sha256(helper.read_bytes()).hexdigest()
    assert record['route_path']==str(route.resolve())

@pytest.mark.parametrize('change',["'schema':True","'schema':2","'pocket':1","'legacy_only':False","'ordinary_grade_request_schema':True"])
def test_unknown_or_nonliteral_mode_does_not_enable_suppression(tool,change):
    root,route,helper=tool
    key=change.split(':')[0]
    source=route.read_text()
    import re
    route.write_text(re.sub(key+r':(?:1|2|True)',change,source))
    assert caps.execution_policies(str(root))=={}


def test_helper_presence_alone_never_advertises_mode(tool):
    root,route,helper=tool
    route.write_text('pass\n')
    assert caps.execution_policies(str(root))=={}
