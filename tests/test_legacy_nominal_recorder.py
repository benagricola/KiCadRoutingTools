"""Literal current route-parser controls; no board read or routing invocation."""
import argparse
import ast
from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import sys
import time

import pytest

KRT=Path(__file__).resolve().parents[1]
sys.path.insert(0, str(KRT/'py_router'))
import final_escape as escape
import routing_defaults as defaults

spec = importlib.util.spec_from_file_location('existing_final_escape_tests', KRT/'tests/test_final_escape.py')
existing = importlib.util.module_from_spec(spec)
spec.loader.exec_module(existing)
source=KRT/'py_router/final_escape.py'
function = next(n for n in ast.parse(source.read_text()).body
                if isinstance(n, ast.FunctionDef) and n.name == 'validated_child_context')
namespace = dict(escape.__dict__)
exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), 'exec'), namespace)
validate = namespace['validated_child_context']


def actual_parser(monkeypatch):
    """Execute exact parser-construction statements from the configured route."""
    source = KRT/'py_router/route.py'
    tree = ast.parse(source.read_text())
    main = next(n for n in tree.body if isinstance(n, ast.If) and '__name__' in ast.unparse(n.test))
    nodes, active = [], False
    for node in main.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'parser' for t in node.targets):
            active = True
        if active:
            if any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == 'parse_args'
                   for n in ast.walk(node)):
                break
            nodes.append(node)
    assert nodes
    monkeypatch.setattr(sys, 'argv', [str(source)])
    namespace = dict(argparse=argparse, defaults=defaults, sys=sys, os=os,
                     json=json, __file__=str(source))
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), 'exec'), namespace)
    return namespace['parser']


@pytest.fixture
def context(tmp_path, monkeypatch):
    board, argv, proof, _, _ = existing.fixture(tmp_path)
    parser = actual_parser(monkeypatch)
    args = parser.parse_args(argv)
    proof['deadline_utc'] = time.time()+600
    proof['call']['routing_flags'] = escape.routing_vector(argv, parser)
    identity = escape.validate_proof(proof, board=board, argv=argv, parser=parser,
                                    scope=args.nets, kind='single', layers=args.layers)
    path = tmp_path/'context.json'
    record = dict(proof=proof, identity=identity, candidate='legacy', evidence_file=str(tmp_path/'evidence.json'))
    path.write_text(json.dumps(record))
    options = dict(argv=argv, parser=parser, tasks=None, candidate='legacy',
                   identity={k: identity[k] for k in ('proof_sha256', 'call_id')})
    return path, board, args, options


def call(context):
    path, board, args, options = context
    return validate(path, board, args.nets, args.layers, **options)


def test_actual_parser_bound_legacy_context_is_retained(context):
    assert call(context)['candidate'] == 'legacy'


@pytest.mark.parametrize('argument', ['--track-width=.2', '--track-w', '--power-nets-widths'])
def test_changed_real_width_or_owned_argument_withholds_telemetry(context, argument):
    # Existing parser actions interpret aliases/nargs; no guessed flag parser.
    context[3]['argv'] = list(context[3]['argv']) + [argument] + ([] if '=' in argument else ['.2'])
    assert call(context) is None


def test_known_proof_refusal_preserves_incumbent_but_unexpected_defect_propagates(context, monkeypatch):
    monkeypatch.setitem(validate.__globals__, 'validate_proof', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('defect')))
    with pytest.raises(RuntimeError, match='defect'):
        call(context)


def test_cancellation_propagates(context, monkeypatch):
    monkeypatch.setitem(validate.__globals__, 'validate_proof', lambda *a, **k: (_ for _ in ()).throw(KeyboardInterrupt()))
    with pytest.raises(KeyboardInterrupt):
        call(context)


def test_ambiguous_argument_is_rejected_by_actual_parser_before_recording(context):
    with pytest.raises(SystemExit) as error:
        context[3]['parser'].parse_args(list(context[3]['argv']) + ['--lay', 'F.Cu'])
    assert error.value.code == 2


def test_actual_loader_unexpected_error_is_not_swallowed(context, monkeypatch):
    monkeypatch.setitem(validate.__globals__, 'load_child_context', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('loader defect')))
    with pytest.raises(RuntimeError, match='loader defect'):
        call(context)


def test_declared_pair_scope_cannot_prove_itself(context):
    path, board, args, options = context
    record = json.loads(path.read_text())
    record['proof']['call']['pair_owned_nets'] = ['unrelated_prior_pair']
    record['identity']['proof_sha256'] = escape.record_digest(record['proof'])
    options['identity']['proof_sha256'] = record['identity']['proof_sha256']
    path.write_text(json.dumps(record))
    assert call(context) is None


def test_connection_execution_is_explicitly_unsupported(context):
    context[3]['tasks'] = 'actual-connections-file.json'
    assert call(context) is None


@pytest.mark.parametrize('contents', ['{broken json', '[]', '{"proof": false}'])
def test_malformed_transport_withholds_only_optional_telemetry(context, contents):
    context[0].write_text(contents)
    assert call(context) is None


def test_actual_loader_cancellation_propagates(context, monkeypatch):
    monkeypatch.setitem(validate.__globals__, 'load_child_context', lambda *a, **k: (_ for _ in ()).throw(KeyboardInterrupt()))
    with pytest.raises(KeyboardInterrupt):
        call(context)


def test_semantically_equal_transport_rewrite_is_stale(context, monkeypatch):
    original = validate.__globals__['load_child_context']
    def rewrite(path, *args):
        loaded = original(path, *args)
        path.write_text(json.dumps(loaded, indent=2))
        return loaded
    monkeypatch.setitem(validate.__globals__, 'load_child_context', rewrite)
    assert call(context) is None


def test_deleted_transport_after_loader_withholds_optional_evidence(context, monkeypatch):
    original = validate.__globals__['load_child_context']
    def remove(path, *args):
        loaded = original(path, *args)
        path.unlink()
        return loaded
    monkeypatch.setitem(validate.__globals__, 'load_child_context', remove)
    assert call(context) is None
