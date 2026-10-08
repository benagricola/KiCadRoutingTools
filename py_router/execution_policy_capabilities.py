"""Pure source-advertised execution modes, never routing/adoption proof."""
import ast
import os

def execution_policies(root, tool_path):
    """Source-advertised internal requests, never routing/adoption proof."""
    import hashlib
    route = tool_path(root, 'route.py')
    helper = os.path.join(os.path.dirname(route), 'route_execution_receipt.py')
    grade = os.path.join(os.path.dirname(route), 'route_candidates.py')
    try:
        raw = open(route, 'rb').read()
        helper_raw = open(helper, 'rb').read()
        grade_raw = open(grade, 'rb').read()
        tree = ast.parse(raw, filename=route)
        records = [ast.literal_eval(node.value) for node in tree.body
                   if isinstance(node, ast.Assign) and any(
                       isinstance(target, ast.Name) and target.id == 'KRT_EXECUTION_POLICIES'
                       for target in node.targets)]
    except (OSError, SyntaxError, ValueError, TypeError):
        return {}
    expected = {'schema', 'legacy_only', 'pocket', 'policy_receipt_schema', 'parent_scope_schema', 'ordinary_grade_request_schema'}
    if len(records) != 1 or not isinstance(records[0], dict) or set(records[0]) != expected:
        return {}
    record = records[0]
    if (any(type(record[key]) is not int or record[key] != expected_value
            for key, expected_value in {'schema':1,'policy_receipt_schema':2,
                'parent_scope_schema':2,'ordinary_grade_request_schema':2}.items())
            or record['legacy_only'] is not True or record['pocket'] is not True):
        return {}
    return {'route.py': dict(record, route_path=os.path.realpath(route),
                            helper_path=os.path.realpath(helper),
                            route_sha256=hashlib.sha256(raw).hexdigest(),
                            helper_sha256=hashlib.sha256(helper_raw).hexdigest(),
                            grade_path=os.path.realpath(grade),
                            grade_sha256=hashlib.sha256(grade_raw).hexdigest())}

