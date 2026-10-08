"""FORK DIVERGENCE: proof-bound final-call escape proposals.

The executor owns full-board finalization and Standing adoption. This module
cannot promote a locally attractive route to a complete-board certificate.
No proof means the existing legacy/pocket routing policy remains unchanged.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import time

SCHEMA = 1
FINALIZATION = ('remove_guards', 'refill_zones', 'remove_dangling_router_copper',
                'original_rules_drc', 'phase_recheck', 'critical_checks')
TRANSPORT_FIELDS = frozenset(('output', 'json_out', 'overwrite',
                             'final_call_proof', 'candidate_artifacts'))


def nominal_rule_context(config, net_id):
    """Exact installed rule channels consumed by nominal tap and guards."""
    import copy
    return copy.deepcopy({
        'layer_clearances': dict(config.layer_clearances or {}),
        'track_clearances': {str(nid): value for nid, value in (config.track_clearances or {}).items()},
        'hole_to_hole_clearance': config.hole_to_hole_clearance,
        'board_edge_clearance': config.board_edge_clearance,
        'same_net_pad_clearance': config.same_net_pad_clearance,
        'grid_step': config.grid_step,
        'board_copper_layers': list(config.board_copper_layers or config.layers),
        'board_min': dict(getattr(config.rules, 'board_min', {}) or {}),
        'per_layer_rule_floors': {layer: config.rule_floors(net_id, layer)
                                  for layer in config.layers},
    })


class ProofRefusal(ValueError):
    """An unsupported/unproved proposal leaves the incumbent policy intact."""

    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def record_digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    allow_nan=False).encode()).hexdigest()


def input_identity(board):
    board = Path(board)
    return {suffix: digest(board.with_suffix(suffix)) if board.with_suffix(suffix).is_file()
            else None for suffix in ('.kicad_pcb', '.kicad_pro', '.kicad_dru')}


def routing_vector(argv, parser):
    """Remove transport by argparse positions; preserve routing tokens verbatim.

    Exact issued vectors are compared. Equivalent aliases do not silently earn
    equivalence; the same real parser identifies option arity and transport.
    Nets whose spelling equals a file path are never removed by value matching.
    """
    out = []
    position = 0
    i = 0
    while i < len(argv):
        token = argv[i]
        if token == '--':
            rest = argv[i + 1:]
            retained = rest[max(0, 2 - position):]
            if retained:
                out.extend(['--'] + retained)
            return out
        parsed = parser._parse_optional(token)
        if parsed is None:
            if position >= 2:
                out.append(token)
            position += 1
            i += 1
            continue
        action, flag, explicit = parsed[0], parsed[1], parsed[-1]
        if action is None:
            raise ProofRefusal('unknown_routing_argument')
        count = 0
        if explicit is None:
            if action.nargs in ('*', '+'):
                j = i + 1
                while j < len(argv) and parser._parse_optional(argv[j]) is None:
                    j += 1
                count = j - i - 1
            elif action.nargs == '?':
                count = int(i + 1 < len(argv) and parser._parse_optional(argv[i + 1]) is None)
            elif action.nargs is None:
                count = 1
            elif isinstance(action.nargs, int):
                count = action.nargs
            else:
                raise ProofRefusal('unsupported_argument_arity')
        elif action.nargs in ('*', '+'):
            j = i + 1
            while j < len(argv) and parser._parse_optional(argv[j]) is None:
                j += 1
            count = j - i - 1
        if action.dest not in TRANSPORT_FIELDS:
            out.extend(argv[i:i + count + 1])
        i += count + 1
    return out


def _hash(value):
    return isinstance(value, str) and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


def validate_proof(proof, *, board, argv, parser, scope, kind, layers,
                   tasks=None, bus_groups=(), pair_owned_nets=(), now=None):
    """Validate the final-call descriptor against actual router facts.

    This validates a trusted executor's bound declaration, not an arbitrary
    claim that a phase happens to be last. Full-board adoption remains external.
    """
    def require(condition, reason):
        if not condition:
            raise ProofRefusal(reason)
    require(isinstance(proof, dict) and type(proof.get('schema')) is int and proof['schema'] == SCHEMA, 'proof_schema')
    require(proof.get('input_files') == input_identity(board), 'input_identity')
    call = proof.get('call')
    require(isinstance(call, dict), 'call_schema')
    require(isinstance(call.get('id'), str) and bool(call['id']), 'call_id')
    require(kind in ('single', 'connections', 'bus') and call.get('kind') == kind, 'call_kind')
    require(call.get('routing_flags') == routing_vector(argv, parser), 'routing_flags')
    named = call.get('nets')
    require(isinstance(named, list) and bool(named) and all(isinstance(n, str) and n for n in named) and
            len(set(named)) == len(named) and set(named) == set(scope), 'selected_scope')
    require(call.get('layers') == list(layers), 'selected_layers')
    require(call.get('tasks_sha256') == (digest(tasks) if tasks else None), 'task_scope')
    require(call.get('bus_groups') == list(bus_groups), 'bus_group_scope')
    require(call.get('pair_owned_nets') == sorted(set(pair_owned_nets)), 'pair_scope')
    obligations = call.get('obligations')
    require(isinstance(obligations, list) and bool(obligations), 'obligation_scope')
    for obligation in obligations:
        require(isinstance(obligation, dict) and obligation.get('net') in call['nets'], 'obligation_net')
        for side in ('from', 'to'):
            terminal = obligation.get(side)
            require(isinstance(terminal, dict) and isinstance(terminal.get('ref'), str) and bool(terminal['ref']) and
                    isinstance(terminal.get('pad'), str) and bool(terminal['pad']), 'obligation_terminal')
        widths = obligation.get('widths')
        require(isinstance(widths, dict) and set(widths) == set(layers) and all(layer in layers and isinstance(width, (int, float)) and
                not isinstance(width, bool) and math.isfinite(width) and width > 0 for layer, width in widths.items()), 'obligation_widths')
    require(not (set(pair_owned_nets) & set(scope)), 'single_escape_pair_owned')
    # Bus endpoint/group custody is not supplied by route.py's net-name list.
    # Do not infer it from coincidental names or independently route a bundle.
    require(kind != 'bus' or bool(bus_groups), 'bus_endpoint_scope_unproved')
    if kind == 'connections':
        require(bool(tasks), 'connection_task_scope')
        validate_task_scope(tasks, obligations)
        # Ordinary per-net nominal receipts omit explicit connection task
        # declarations. A coincidental matching class width is not authority.
        # Until a bound task-resolver receipt is supplied, keep normal routing.
        raise ProofRefusal('connection_task_nominal_receipt_unavailable')
    work = proof.get('copper_work')
    require(isinstance(work, list) and bool(work) and all(isinstance(x, dict) and
            isinstance(x.get('id'), str) and bool(x['id']) and
            x.get('kind') in ('single', 'connections', 'bus', 'pairs', 'pour', 'tuning')
            for x in work), 'copper_work')
    require(len({x['id'] for x in work}) == len(work), 'duplicate_work_id')
    require(work[-1] == {'id': call['id'], 'kind': kind}, 'not_final_copper_call')
    require(proof.get('deferred_work') == [], 'deferred_work')
    require(proof.get('finalization') == list(FINALIZATION), 'unsupported_finalization')
    authority = proof.get('standing_authority')
    require(isinstance(authority, dict) and type(authority.get('schema')) is int and authority['schema'] == SCHEMA and
            authority.get('available') is True, 'standing_unavailable')
    require(all(_hash(authority.get(k)) for k in ('contract_sha256', 'settings_sha256',
            'check_context_sha256', 'adapter_sha256')), 'standing_identity')
    policy = proof.get('nominal_policy')
    require(isinstance(policy, dict) and _hash(policy.get('receipt_sha256')) and
            _hash(policy.get('sources_sha256')) and isinstance(policy.get('by_net'), dict), 'nominal_policy')
    require(set(policy['by_net']) == set(scope), 'nominal_policy_scope')
    require(all(isinstance(widths, dict) and set(widths) == set(layers) and
                all(isinstance(w, (int, float)) and not isinstance(w, bool) and
                    math.isfinite(w) and w > 0 for w in widths.values())
                for widths in policy['by_net'].values()), 'nominal_policy_values')
    for obligation in obligations:
        require(policy['by_net'].get(obligation['net']) == obligation['widths'],
                'obligation_nominal_policy_conflict')
    deadline = proof.get('deadline_utc')
    require(not isinstance(deadline, bool) and isinstance(deadline, (int, float)) and
            math.isfinite(deadline) and deadline > (time.time() if now is None else now), 'proof_deadline')
    return {'proof_sha256': record_digest(proof), 'call_id': call['id'],
            'deadline_utc': deadline, 'policy_sha256': record_digest(policy)}


def validate_failure(record, proof, identity):
    """Eligibility is an observed nominal failure of the selected physical join."""
    if not isinstance(record, dict):
        raise ProofRefusal('failure_schema')
    expected = {'proof_sha256': identity['proof_sha256'], 'call_id': identity['call_id'],
                'input_files': proof['input_files'], 'policy_sha256': identity['policy_sha256']}
    if any(record.get(k) != v for k, v in expected.items()):
        raise ProofRefusal('stale_failure')
    epoch = record.get('epoch')
    if not isinstance(epoch, dict) or epoch.get('candidate') != 'legacy' or type(epoch.get('sequence')) is not int or epoch['sequence'] < 0:
        raise ProofRefusal('failure_epoch')
    clearance_policy = epoch.get('clearance_policy')
    if (not isinstance(clearance_policy, dict) or
            not isinstance(clearance_policy.get('by_net'), dict) or
            any(not isinstance(key, str) or isinstance(value, bool) or
                not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0
                for key, value in clearance_policy['by_net'].items()) or
            isinstance(clearance_policy.get('routing_floor'), bool) or
            not isinstance(clearance_policy.get('routing_floor'), (int, float)) or
            not math.isfinite(clearance_policy['routing_floor']) or clearance_policy['routing_floor'] < 0):
        raise ProofRefusal('nominal_clearance_policy_unproved')
    if not isinstance(epoch.get('rule_context'), dict):
        raise ProofRefusal('nominal_rule_context_unproved')
    observed = record.get('observed_utc')
    if isinstance(observed, bool) or not isinstance(observed, (int, float)) or not math.isfinite(observed) or observed <= 0 or observed > proof['deadline_utc']:
        raise ProofRefusal('failure_epoch')
    if record.get('router_sources_sha256') != proof['nominal_policy']['sources_sha256']:
        raise ProofRefusal('nominal_source_identity')
    endpoint, peer = record.get('endpoint'), record.get('peer')
    if not all(isinstance(x, dict) and isinstance(x.get('ref'), str) and
               isinstance(x.get('pad'), str) and isinstance(x.get('physical_index'), int)
               and not isinstance(x['physical_index'], bool) and x['physical_index'] >= 0
               for x in (endpoint, peer)):
        raise ProofRefusal('physical_endpoint')
    net = endpoint.get('net')
    if net not in proof['call']['nets'] or net in proof['call']['pair_owned_nets']:
        raise ProofRefusal('endpoint_scope')
    selected = None
    for obligation in proof['call']['obligations']:
        if obligation['net'] != net:
            continue
        for first, second in (('from', 'to'), ('to', 'from')):
            source, target = obligation[first], obligation[second]
            if (endpoint['ref'], endpoint['pad'], peer['ref'], peer['pad']) == (source['ref'], source['pad'], target['ref'], target['pad']):
                selected = (source, target)
    if selected is None:
        raise ProofRefusal('required_peer_scope')
    geometry = record.get('nominal_geometry')
    if not isinstance(geometry, dict) or geometry.get('pad_layer') not in proof['call']['layers'] or geometry.get('layers') != proof['call']['layers']:
        raise ProofRefusal('nominal_policy_unproved')
    widths = proof['nominal_policy']['by_net'].get(net, {})
    if geometry.get('track_width') != widths.get(geometry['pad_layer']) or epoch.get('nominal_widths') != widths:
        raise ProofRefusal('nominal_values')
    for name in ('track_width', 'via_size', 'via_drill', 'clearance'):
        value = geometry.get(name)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0 or (name != 'clearance' and value == 0):
            raise ProofRefusal('nominal_policy_unproved')
    result = record.get('nominal_result')
    if not isinstance(result, dict) or result.get('success') is not False or result.get('via_blocked') is not True:
        raise ProofRefusal('nominal_failure_unobserved')
    if record.get('nominal_only') is not True:
        raise ProofRefusal('nominal_policy_unproved')
    graph = record.get('graph')
    if not isinstance(graph, dict) or not isinstance(graph.get('edges'), list) or not isinstance(graph.get('pad_index_repr'), dict):
        raise ProofRefusal('graph_unavailable')
    points = graph.get('num_points')
    if isinstance(points, bool) or not isinstance(points, int) or points < 0 or graph.get('zone_blob_fallback') is not False:
        raise ProofRefusal('graph_unavailable')
    a, b = endpoint['physical_index'], peer['physical_index']
    pad_repr = graph['pad_index_repr']
    # Unrepresented pads need distinct isolated components, not a shared None.
    pads = record.get('net_pads')
    if not isinstance(pads, list) or max(a, b) >= len(pads):
        raise ProofRefusal('graph_pad_inventory')
    for terminal in (endpoint, peer):
        matching = [i for i, item in enumerate(pads) if isinstance(item, dict) and
                    (item.get('component_ref'), item.get('pad_number')) == (terminal['ref'], terminal['pad'])]
        if len(matching) != 1:
            raise ProofRefusal('repeated_pad_shape_escape_unproved')
        if matching[0] != terminal['physical_index']:
            raise ProofRefusal('graph_pad_identity')
        pad = pads[terminal['physical_index']]
        if not isinstance(pad, dict) or pad.get('net_name') != net or (pad.get('component_ref'), pad.get('pad_number')) != (terminal['ref'], terminal['pad']):
            raise ProofRefusal('graph_pad_identity')
    if a == b:
        raise ProofRefusal('already_connected_terminal')
    try:
        reps = {int(k): v for k, v in pad_repr.items()}
    except (TypeError, ValueError):
        raise ProofRefusal('graph_unavailable') from None
    if any(i < 0 or i >= len(pads) or isinstance(v, bool) or not isinstance(v, int) or v < 0 or v >= points for i, v in reps.items()):
        raise ProofRefusal('graph_unavailable')
    parent = {}
    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            x = parent[x]
        return x
    try:
        for edge in graph['edges']:
            if not isinstance(edge, (list, tuple)) or len(edge) != 2:
                raise ValueError
            x, y = edge
            if any(isinstance(v, bool) or not isinstance(v, int) or v < 0 or v >= points for v in (x, y)):
                raise ValueError
            parent[find(x)] = find(y)
        connected = a in reps and b in reps and find(reps[a]) == find(reps[b])
    except (TypeError, ValueError):
        raise ProofRefusal('graph_unavailable') from None
    if connected:
        raise ProofRefusal('already_connected_terminal')
    return record


def source_fingerprint():
    """Same source inventory as the router-authoritative nominal receipt."""
    router = Path(__file__).resolve().parents[1]
    files = set(router.glob('*.py')) | set(Path(__file__).parent.rglob('*.py'))
    return record_digest({str(p.relative_to(router)): digest(p) for p in sorted(files)})


def validate_nominal(policy, actual_widths):
    """Proof declarations must match live nominal resolution, not stale numbers."""
    if policy.get('sources_sha256') != source_fingerprint():
        raise ProofRefusal('nominal_source_identity')
    if policy.get('by_net') != actual_widths:
        raise ProofRefusal('nominal_values')
    if not isinstance(actual_widths, dict) or not actual_widths:
        raise ProofRefusal('nominal_unknown')
    for widths in actual_widths.values():
        if not isinstance(widths, dict) or not widths or any(isinstance(w, bool) or
                not isinstance(w, (int, float)) or not math.isfinite(w) or w <= 0
                for w in widths.values()):
            raise ProofRefusal('nominal_unknown')


class FailureRecorder:
    """Immutable per-rescue epochs tied to the final call's selected joins.

    Only the callback from the actual initial nominal tap can create a failure
    record. The graph was captured by the same rescue invocation, not inferred
    from a later board or recomputed while recording.
    """
    def __init__(self, proof, identity, candidate='legacy', evidence_file=None):
        import copy
        self.proof = copy.deepcopy(proof)
        self.identity = dict(identity)
        self.candidate = candidate
        self.records = []
        self.epochs = []
        self.refusals = []
        self.evidence_file = evidence_file
        self.disabled = False
        self.flush()

    def invalidate(self, error):
        self.disabled = True
        self.records.clear()
        self.refusals.append('evidence_' + type(error).__name__)
        # A structured owned-child receipt in the already-open log survives a
        # disk/permission failure that prevents replacing the evidence file.
        try:
            print('FINAL_CALL_EVIDENCE_REFUSED: ' + json.dumps({
                'proof_sha256': self.identity['proof_sha256'],
                'call_id': self.identity['call_id'], 'reason': self.refusals[-1]}),
                flush=True)
        except Exception:
            pass  # Optional evidence must not interrupt incumbent routing.
        if self.evidence_file is not None:
            try:
                write_record(self.evidence_file, self.receipt())
            except (OSError, TypeError, ValueError):
                pass

    def flush(self):
        if self.evidence_file is not None:
            try:
                write_record(self.evidence_file, self.receipt())
            except (OSError, TypeError, ValueError) as error:
                # Evidence storage is optional. Do not abort or alter the
                # incumbent's actual routing because a proposal receipt failed.
                self.invalidate(error)
                self.evidence_file = None

    def finish(self):
        """Positive custody receipt, only after the final successful write."""
        if self.disabled or self.evidence_file is None:
            return
        try:
            write_record(self.evidence_file, self.receipt())
            print('FINAL_CALL_EVIDENCE_COMPLETE: ' + json.dumps({
                'schema': SCHEMA, 'proof_sha256': self.identity['proof_sha256'],
                'call_id': self.identity['call_id'],
                'evidence_sha256': digest(self.evidence_file)}), flush=True)
        except Exception as error:
            self.invalidate(error)

    def epoch(self, net_name, graph_out, config, net_id):
        import copy
        snapshot = copy.deepcopy(graph_out)
        scope = self.proof['call']
        widths = {layer: config.get_net_track_width(net_id, layer) for layer in scope['layers']}
        expected = self.proof['nominal_policy']['by_net'].get(net_name)
        epoch = {'sequence': len(self.epochs), 'net': net_name,
                 'candidate': self.candidate, 'pid': os.getpid(),
                 'graph': snapshot.get('graph'), 'net_pads': snapshot.get('net_pads'),
                 'nominal_widths': widths, 'policy_widths_match': widths == expected}
        epoch['clearance_policy'] = {
            'by_net': {str(nid): value for nid, value in (config.net_clearances or {}).items()},
            'routing_floor': (config.net_clearance_floor if config.net_clearance_floor is not None
                              else config.clearance)}
        epoch['rule_context'] = nominal_rule_context(config, net_id)
        self.epochs.append(copy.deepcopy(epoch))
        self.flush()
        return epoch

    def observer(self, epoch, pad, config, pad_layer):
        import copy
        from dataclasses import asdict
        if self.disabled:
            return None
        if not epoch['policy_widths_match'] or pad_layer not in epoch['nominal_widths']:
            self.refusals.append('nominal_values')
            return None
        if config.track_width != epoch['nominal_widths'][pad_layer]:
            self.refusals.append('nominal_tap_width_unproved')
            return None
        pads = epoch['net_pads'] or []
        index = [i for i, p in enumerate(pads) if p.get('component_ref') == pad.component_ref
                 and p.get('pad_number') == pad.pad_number]
        if len(index) != 1:
            self.refusals.append('repeated_pad_shape_escape_unproved')
            return None
        endpoint = {'net': epoch['net'], 'ref': pad.component_ref, 'pad': pad.pad_number,
                    'physical_index': index[0]}
        pairs = []
        for obligation in self.proof['call']['obligations']:
            if obligation['net'] != epoch['net']:
                continue
            for a, b in (('from', 'to'), ('to', 'from')):
                if obligation[a] == {'ref': pad.component_ref, 'pad': pad.pad_number}:
                    peer = obligation[b]
                    indices = [i for i, p in enumerate(pads) if
                               (p.get('component_ref'), p.get('pad_number')) == (peer['ref'], peer['pad'])]
                    if len(indices) == 1:
                        pairs.append(dict(peer, physical_index=indices[0]))
        if not pairs:
            self.refusals.append('required_peer_scope')
            return None
        # Freeze configuration and epoch here. Later ladder rungs and subsequent
        # copper additions must not rewrite the meaning of the nominal failure.
        frozen = copy.deepcopy(epoch)
        geometry = {'track_width': config.track_width, 'clearance': config.clearance,
                    'via_size': config.via_size, 'via_drill': config.via_drill,
                    'layers': list(config.layers), 'pad_layer': pad_layer}
        def observe(result):
            outcome = asdict(result)
            for peer in pairs:
                record = dict(self.identity, input_files=self.proof['input_files'],
                              policy_sha256=self.identity['policy_sha256'],
                              router_sources_sha256=self.proof['nominal_policy']['sources_sha256'],
                              epoch=copy.deepcopy(frozen), endpoint=dict(endpoint), peer=dict(peer),
                              graph=copy.deepcopy(frozen['graph']), net_pads=copy.deepcopy(frozen['net_pads']),
                              nominal_result=copy.deepcopy(outcome), nominal_only=True,
                              nominal_geometry=dict(geometry), observed_utc=time.time())
                self.records.append(record)
            self.flush()
        return observe

    def eligible(self):
        if self.disabled:
            return []
        accepted = []
        for record in self.records:
            try:
                validate_failure(record, self.proof, self.identity)
            except ProofRefusal as error:
                self.refusals.append(error.reason)
            else:
                accepted.append(record)
        import copy
        return copy.deepcopy(accepted)

    def receipt(self):
        import copy
        return copy.deepcopy({'schema': SCHEMA, 'epochs': self.epochs,
                              'nominal_taps': self.records, 'refusals': self.refusals,
                              'disabled': self.disabled})


def task_identity(task):
    """Canonical actual parsed declaration, retaining terminal direction."""
    return {'net': task['net'], 'from': dict(task['from']), 'to': dict(task['to']),
            'widths': {layer: float(width) for layer, width in task['widths'].items()}}


def write_record(path, record):
    """Atomic owned evidence update; a terminated child leaves a complete JSON."""
    import tempfile
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(record, stream, sort_keys=True, allow_nan=False)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def load_child_context(path, board, scope, layers):
    context = json.loads(Path(path).read_text(encoding='utf-8'))
    proof, identity = context['proof'], context['identity']
    if (identity['proof_sha256'] != record_digest(proof) or
            proof['input_files'] != input_identity(board) or
            set(proof['call']['nets']) != set(scope) or
            proof['call']['layers'] != list(layers) or
            proof['nominal_policy']['sources_sha256'] != source_fingerprint() or
            context['candidate'] not in ('legacy', 'escape') or
            identity['policy_sha256'] != record_digest(proof['nominal_policy']) or
            identity['call_id'] != proof['call']['id']):
        raise ProofRefusal('child_context_binding')
    return context


def optional_child_context(path, board, scope, layers, *, candidate, identity):
    try:
        context = load_child_context(path, board, scope, layers)
        if (context['candidate'] != candidate or
                any(context['identity'].get(key) != identity.get(key)
                    for key in ('proof_sha256', 'call_id'))):
            raise ProofRefusal('child_context_invocation')
        return context
    except Exception as error:
        if candidate == 'escape':
            raise
        try:
            print('FINAL_CALL_EVIDENCE_REFUSED: ' + json.dumps(dict(identity,
                reason='child_context_' + type(error).__name__)), flush=True)
        except Exception:
            pass
        return None


def validated_child_context(path, board, scope, layers, *, argv, parser, tasks,
                            candidate, identity):
    """Actual single-call parser validation; transport cannot authorize adoption."""
    try:
        if tasks is not None:
            raise ProofRefusal('connection_recorder_unsupported')
        try:
            raw_context = Path(path).read_bytes()
            context_sha256 = hashlib.sha256(raw_context).hexdigest()
            context = json.loads(raw_context.decode('utf-8'))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as error:
            raise ProofRefusal('child_context_unavailable') from error
        if (not isinstance(context, dict) or not isinstance(context.get('identity'), dict)
                or context.get('candidate') != candidate):
            raise ProofRefusal('child_context_schema')
        actual = validate_proof(context.get('proof'), board=board, argv=argv,
            parser=parser, scope=scope, kind='single', layers=layers,
            tasks=None, bus_groups=(), pair_owned_nets=())
        if (any(context['identity'].get(key) != value for key, value in actual.items())
                or any(actual.get(key) != value for key, value in identity.items())):
            raise ProofRefusal('actual_child_invocation_identity')
        try:
            loaded = load_child_context(path, board, scope, layers)
        except (OSError, json.JSONDecodeError, UnicodeDecodeError, KeyError, TypeError) as error:
            raise ProofRefusal('child_context_changed_or_malformed') from error
        try:
            final_context_sha256 = digest(path)
        except OSError as error:
            raise ProofRefusal('child_context_unavailable_after_load') from error
        if final_context_sha256 != context_sha256 or record_digest(loaded) != record_digest(context):
            raise ProofRefusal('child_context_changed')
    except ProofRefusal as error:
        if candidate != 'legacy':
            raise
        print('FINAL_CALL_EVIDENCE_REFUSED: ' + json.dumps(dict(identity,
              reason=error.reason)), flush=True)
        return None
    return loaded


def prepare_runtime(pcb_data, config, context, cancel_check=None):
    """Optional legacy telemetry cannot change the incumbent routing result."""
    from routing_common import resolve_net_ids
    try:
        proof, identity = context['proof'], context['identity']
        actual = {name: {layer: config.get_net_track_width(nid, layer)
                         for layer in proof['call']['layers']}
                  for name, nid in resolve_net_ids(pcb_data, proof['call']['nets'])}
        validate_nominal(proof['nominal_policy'], actual)
        if context['candidate'] == 'legacy':
            recorder = FailureRecorder(proof, identity, evidence_file=context['evidence_file'])
            context.setdefault('recorders', []).append(recorder)
            return recorder, None
        if context['candidate'] != 'escape':
            raise ProofRefusal('unknown_final_call_candidate')
        seed = seed_nominal(pcb_data, config, proof, identity, context['failures'],
                            cancel_check=cancel_check)
        write_record(context['evidence_file'], {'schema': SCHEMA,
                                              'seed_attempts': seed['attempts']})
        return None, seed
    except Exception as error:
        if context['candidate'] != 'legacy':
            raise
        receipt = {'schema': SCHEMA, 'disabled': True,
                   'proof_sha256': context['identity']['proof_sha256'],
                   'call_id': context['identity']['call_id'],
                   'reason': getattr(error, 'reason', type(error).__name__)}
        try:
            print('FINAL_CALL_EVIDENCE_REFUSED: ' + json.dumps(receipt), flush=True)
            write_record(context['evidence_file'], receipt)
        except (OSError, TypeError, ValueError):
            pass
        return None, None


def finish_context(context):
    recorders = context.get('recorders', [])
    if len(recorders) == 1:
        recorders[0].finish()
    elif recorders:
        for recorder in recorders:
            recorder.invalidate(ProofRefusal('recording_owner_ambiguous'))


def validate_task_scope(path, obligations):
    import connections
    try:
        declared = [task_identity(t) for t in connections.read_file(path)]
    except (OSError, ValueError, TypeError) as error:
        raise ProofRefusal('connection_task_scope') from error
    by_terminal, by_net = {}, {}
    for task in declared:
        width_key = record_digest(task['widths'])
        net_conflict = task['net'] in by_net and by_net[task['net']] != width_key
        for side in ('from', 'to'):
            terminal = task[side]
            key = (task['net'], terminal['ref'], terminal['pad'])
            if key in by_terminal and by_terminal[key] != width_key:
                raise ProofRefusal('connection_terminal_policy_conflict')
            by_terminal[key] = width_key
        if net_conflict:
            raise ProofRefusal('connection_net_policy_conflict')
        by_net[task['net']] = width_key
    for obligation in obligations:
        canonical = task_identity(obligation)
        if canonical not in declared or obligation.get('task_sha256') != record_digest(canonical):
            raise ProofRefusal('connection_task_identity')


def seed_nominal(pcb_data, config, proof, identity, failures, *,
                 cancel_check=None):
    """One nominal tap per proved endpoint, returning explicit writer channels.

    This changes only the isolated proposal's mutable model. A seed is neither
    a joined obligation nor a width certificate. The caller must retain the
    returned objects in the existing swap writer channels, including via-only
    taps, and independently finalize and judge the emitted whole board.
    """
    import copy
    from dataclasses import asdict
    from kicad_parser import Segment, Via
    from plane_pad_tap import try_tap_pad
    from net_rescue import (_leg_clear, _via_site_clear, _drills_too_close,
                            _net_component_info)
    from pcb_modification import bump_copper_epoch

    from seed_site_policy import captured_original, conventional_site_filter
    fabrication = captured_original(proof.get('original_fabrication'))
    site_filter = conventional_site_filter(pcb_data, config.via_size, config.layers)
    segments, vias, attempts = [], [], []
    seen, successes = set(), {}
    for failure in failures:
        if time.time() >= proof['deadline_utc'] or (cancel_check and cancel_check()):
            break
        validate_failure(failure, proof, identity)
        endpoint = failure['endpoint']
        key = (endpoint['net'], endpoint['ref'], endpoint['pad'])
        if key in seen or successes.get(endpoint['net'], 0) >= 4:
            continue
        seen.add(key)
        net_ids = [nid for nid, net in pcb_data.nets.items()
                   if net.name == endpoint['net']]
        if len(net_ids) != 1:
            raise ProofRefusal('seed_net_identity')
        net_id = net_ids[0]
        pads = [pad for pad in pcb_data.pads_by_net.get(net_id, [])
                if (pad.component_ref, pad.pad_number) == key[1:]]
        if len(pads) != 1:
            raise ProofRefusal('seed_physical_terminal')
        # Failure evidence describes a historical rescue epoch. Recheck the
        # declared join on this proposal's current model, including earlier
        # seeds, rather than treating that historical graph as current truth.
        fresh_graph = {}
        _net_component_info(pcb_data, net_id, graph_out=fresh_graph)
        current = copy.deepcopy(failure)
        current.update(fresh_graph)
        for side in ('endpoint', 'peer'):
            terminal = current[side]
            indices = [i for i, p in enumerate(current['net_pads']) if
                       (p['component_ref'], p['pad_number']) ==
                       (terminal['ref'], terminal['pad'])]
            if len(indices) != 1:
                raise ProofRefusal('seed_physical_terminal')
            terminal['physical_index'] = indices[0]
        try:
            validate_failure(current, proof, identity)
        except ProofRefusal as error:
            attempts.append({'endpoint': dict(endpoint), 'accepted_seed': False,
                             'refusal': 'fresh_input_' + error.reason})
            continue
        pad = pads[0]
        if pad.drill and pad.drill > 0:
            raise ProofRefusal('seed_barrel_terminal')
        layer = failure['nominal_geometry']['pad_layer']
        expected = proof['nominal_policy']['by_net'][endpoint['net']]
        actual = {name: config.get_net_track_width(net_id, name)
                  for name in proof['call']['layers']}
        if actual != expected:
            raise ProofRefusal('seed_nominal_values')
        tap_config = copy.copy(config)
        tap_config.track_width = expected[layer]
        captured_clearance = failure['epoch']['clearance_policy']
        live_map = {str(nid): value for nid, value in (config.net_clearances or {}).items()}
        if live_map != captured_clearance['by_net']:
            raise ProofRefusal('seed_nominal_clearance_map_changed')
        if captured_clearance['routing_floor'] < max(config.clearance,
                live_map.get(str(net_id), config.clearance)):
            raise ProofRefusal('seed_nominal_clearance_floor')
        # Legacy installs the routing-side floor before building its maps,
        # after this seed point. Reuse the actual captured nominal floor and
        # active class map on the proposal-only clone, without changing legacy.
        tap_config.net_clearances = dict(config.net_clearances or {})
        tap_config.net_clearance_floor = captured_clearance['routing_floor']
        if nominal_rule_context(tap_config, net_id) != failure['epoch']['rule_context']:
            raise ProofRefusal('seed_nominal_rule_context_changed')
        live_geometry = {'track_width': tap_config.track_width,
                         'clearance': tap_config.clearance,
                         'via_size': tap_config.via_size,
                         'via_drill': tap_config.via_drill,
                         'layers': list(tap_config.layers), 'pad_layer': layer}
        if live_geometry != failure['nominal_geometry']:
            raise ProofRefusal('seed_nominal_geometry_changed')
        result = try_tap_pad(pad, layer, net_id, pcb_data, tap_config,
                             max_search_radius=1.5,
                             via_size=config.via_size, via_drill=config.via_drill,
                             same_net_pad_clearance=config.same_net_pad_clearance,
                             seed_site_filter=site_filter)
        receipt = {'endpoint': dict(endpoint), 'result': copy.deepcopy(asdict(result)),
                   'accepted_seed': False,
                   'fresh_graph_sha256': record_digest(fresh_graph),
                   'original_fabrication': fabrication,
                   'same_net_pad_clearance': config.same_net_pad_clearance}
        attempts.append(receipt)
        if not result.success:
            continue
        new_segments = [Segment(s['start'][0], s['start'][1],
                                s['end'][0], s['end'][1], s['width'],
                                s['layer'], net_id) for s in result.segments]
        v = result.via
        new_vias = ([Via(v['x'], v['y'], v['size'], v['drill'],
                         v.get('layers', ['F.Cu', 'B.Cu']), net_id)] if v else [])
        if any(not site_filter(v.x, v.y) for v in new_vias):
            receipt['refusal'] = 'seed_fabrication_site_unproved'
            continue
        # Same exact copper guards as the existing rescue; the tap's window
        # alone does not certify foreign copper or drills on the whole board.
        if (any(not _leg_clear(pcb_data,
                              [(s.start_x, s.start_y), (s.end_x, s.end_y)],
                              s.layer, s.width, config.clearance, net_id,
                              config=tap_config) for s in new_segments) or
                any(not _via_site_clear(pcb_data, v.x, v.y, tap_config,
                                        net_id, exact_pads=True) for v in new_vias) or
                _drills_too_close(new_vias, config.hole_to_hole_clearance)):
            receipt['refusal'] = 'seed_foreign_copper_or_drill'
            continue
        if not new_segments and not new_vias:
            receipt['refusal'] = 'seed_no_new_copper'
            continue
        pcb_data.segments.extend(new_segments)
        pcb_data.vias.extend(new_vias)
        bump_copper_epoch(pcb_data)
        segments.extend(new_segments)
        vias.extend(new_vias)
        successes[endpoint['net']] = successes.get(endpoint['net'], 0) + 1
        receipt['accepted_seed'] = True
    if captured_original(proof['original_fabrication']) != fabrication:
        raise ProofRefusal('seed_original_fabrication_changed')
    return {'segments': segments, 'vias': vias, 'attempts': attempts}


def persist_artifacts(destination, proof, identity, candidates, evidence):
    """Publish a new, hash-bound bundle for external whole-board judgment.

    Refuse a preexisting destination rather than reusing a receipt from a
    previous invocation. No candidate in this bundle is locally adopted.
    """
    import shutil
    import tempfile
    destination = Path(destination)
    if os.path.lexists(destination):
        raise ProofRefusal('candidate_artifacts_exist')
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='.final-call-', dir=destination.parent))
    try:
        manifest = {'schema': SCHEMA, 'proof_sha256': identity['proof_sha256'],
                    'call_id': identity['call_id'], 'incumbent': 'legacy',
                    'adoption': 'withheld_pending_finalized_full_standing',
                    'evidence': evidence, 'candidates': []}
        if (not candidates or candidates[0]['name'] != 'legacy' or len(candidates) > 2 or
                (len(candidates) == 2 and candidates[1]['name'] != 'escape')):
            raise ProofRefusal('candidate_slot_inventory')
        for candidate in candidates:
            name = candidate['name']
            if name not in ('legacy', 'escape'):
                raise ProofRefusal('candidate_slot_kind')
            folder = staging / name
            folder.mkdir()
            hashes = {}
            board = Path(candidate['board'])
            for suffix in ('.kicad_pcb', '.kicad_pro', '.kicad_dru'):
                source = board.with_suffix(suffix)
                if source.is_file():
                    target = folder / ('board' + suffix)
                    shutil.copyfile(source, target)
                    hashes[target.name] = digest(target)
            if 'board.kicad_pcb' not in hashes:
                raise ProofRefusal('candidate_board_missing')
            summary = folder / 'summary.json'
            summary.write_text(json.dumps(candidate['summary'], sort_keys=True,
                                          allow_nan=False), encoding='utf-8')
            hashes[summary.name] = digest(summary)
            log = candidate.get('log')
            if log is not None and Path(log).is_file():
                shutil.copyfile(log, folder / 'route.log')
                hashes['route.log'] = digest(folder / 'route.log')
            manifest['candidates'].append({'name': name, 'returncode': candidate['rc'],
                                           'files': hashes})
        (staging / 'proof.json').write_text(json.dumps(proof, sort_keys=True,
                                                     allow_nan=False), encoding='utf-8')
        manifest['proof_file_sha256'] = digest(staging / 'proof.json')
        (staging / 'receipt.json').write_text(json.dumps(manifest, sort_keys=True,
                                                       allow_nan=False), encoding='utf-8')
        for file in staging.rglob('*'):
            if file.is_file():
                file.chmod(0o444)
        staging.rename(destination)
        return {'path': str(destination), 'receipt_sha256': digest(destination / 'receipt.json'),
                'proof_sha256': identity['proof_sha256']}
    finally:
        if staging.exists():
            shutil.rmtree(staging)
