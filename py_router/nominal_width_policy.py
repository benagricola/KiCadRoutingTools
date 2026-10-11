"""Router-authoritative nominal widths, shared with read-only consumers.

FORK DIVERGENCE (docs/fork-divergences.md, "Nominal width policy"): the class
resolver is extracted unchanged from route.py initialization so placemat can
ask for the widths a call would draw. This module imports no routing CLI or
mutable router engine state.
"""
from __future__ import annotations

import os


def class_width_inputs(pcb_data, input_file, layers, *, track_width_from_class,
                       impedance=None, via_from_class=False, via_size=0.0, via_drill=0.0):
    """Return the same class/rule/fabrication inputs consumed by batch_route."""
    _per_layer, _per_net_via = {}, {}
    unknown = []
    net_track_widths = {}
    netclass_width_floors = {}
    if input_file and os.path.isfile(input_file):
        try:
            from list_nets import net_track_width_map_by_id, fab_floors
            from fab_tiers import fab_floors as _tier_floors, \
                warn_fab_escalation as _wfe435
            _ncl = len(getattr(pcb_data.board_info, 'copper_layers', None)
                       or []) or 4
            _twfloor = fab_floors(_ncl).get('track_width', 0.0)
            # Clamp at the ADVANCED-tier floor, not the standard one
            # (2026-08-06): a netclass width is DESIGNER INTENT and may
            # legitimately sit between the two tiers (ecp5 /PF37- at
            # 0.0762 vs standard 0.0889 -- the GUI honored it and routed;
            # the old standard-floor clamp silently widened it CLI-side, a
            # cross-front divergence AND the reason no in-run ladder could
            # reach the width that closes the net). Escalation floor rule:
            # min(nominal, fab_track, netclass width), never below the
            # advanced tier; dipping below standard prints the same fab
            # warning the via rungs use.
            # The DEEPEST rung of the ACTIVE tier: advanced under --fab-tier
            # auto, the tier's own floor when it is hard (#857).
            from fab_tiers import fab_floor_min as _tier_min
            _adv_tw = _tier_min(_ncl).get('track_width', _twfloor)
            net_track_widths = {}
            # #530: the per-net DRAW width is the resolver's `opt` -- the
            # aggregate net class's track_width, overridden by any .kicad_dru
            # (constraint track_width (opt ...)) that matches the net, clamped
            # into the rule's min/max -- exactly what KiCad's own router draws
            # under "use netclass values". Nets whose width equals the Default
            # class's carry no entry (they route at config.track_width, as
            # before); a rule with layer-scoped opts fills net_layer_widths.
            _per_net, _per_layer, _per_net_via = {}, {}, {}
            try:
                from design_rules import DesignRules as _DR
                _dr = _DR.from_project(
                    pcb_data, input_file,
                    fab_floor=fab_floors(_ncl),
                    copper_layers=list(getattr(pcb_data.board_info, 'copper_layers', None)
                                       or (layers or [])))
                unknown += [{'code': 'rule_unsupported', 'rule': r.name, 'detail': r.unsupported}
                            for r in _dr.rules if r.unsupported and 'track_width' in r.constraints]
                unknown += [{'code': 'rules_unread', 'detail': str(n)} for n in _dr.notes
                            if 'could not' in str(n) or 'parse' in str(n)]
                _dflt_w = _dr.classes.get('Default', {}).get('track_width')
                _cu = [l for l in (getattr(pcb_data.board_info, 'copper_layers', None)
                                   or (layers or [])) if str(l).endswith('.Cu')]
                for nid in pcb_data.nets:
                    if nid == 0:
                        continue
                    w_all = _dr.draw_size('track_width', nid)
                    by_layer = {l: _dr.draw_size('track_width', nid, l) for l in _cu}
                    by_layer = {l: w for l, w in by_layer.items() if w is not None}
                    if by_layer and len(set(by_layer.values())) > 1:
                        _per_layer[nid] = by_layer
                    if w_all is not None and (_dflt_w is None or abs(w_all - _dflt_w) > 1e-9
                                              or nid in _per_layer):
                        _per_net[nid] = w_all
                    # #530 decision 4: the net's own VIA draw size (class
                    # via_diameter/via_drill, a rule's via_diameter/hole_size
                    # opt, clamped into the rule's min/max), only when the
                    # operator gave no --via-size/--via-drill.
                    if via_from_class:
                        _vd = _dr.draw_size('via_diameter', nid, default=None)
                        _vh = _dr.draw_size('hole_size', nid, default=None)
                        if _vd and _vh and _vh < _vd and (
                                abs(_vd - via_size) > 1e-9 or abs(_vh - via_drill) > 1e-9):
                            _per_net_via[nid] = (round(_vd, 4), round(_vh, 4))
            except Exception as _dre:                          # noqa: BLE001
                unknown.append({'code': 'design_rules_unavailable', 'error': type(_dre).__name__,
                                'detail': str(_dre)})
                print(f"Warning: design-rule widths unavailable ({_dre}); "
                      f"falling back to the net-class map.")
                _per_net = dict(net_track_width_map_by_id(
                    input_file, {nid: n.name for nid, n in pcb_data.nets.items()}))
            for nid, w in _per_net.items():
                w2 = max(w, _adv_tw)
                if w2 < _twfloor - 1e-9:
                    _wfe435(f"netclass width net_{nid}")
                netclass_width_floors[nid] = w2
            # Nominal per-net widths only when no explicit --track-width
            # (the operator's flag wins for ROUTING); the floors above are
            # for the escalation ladders regardless. --impedance derives
            # width per layer, so netclass widths must not override it
            # (#610: this guard lives HERE now, so track_width_from_class
            # itself purely means "--track-width omitted" and can drive the
            # impedance width floor below).
            if track_width_from_class and impedance is None:
                net_track_widths = dict(netclass_width_floors)
            if net_track_widths:
                print(f"Auto-read netclass track widths for {len(net_track_widths)} "
                      f"non-Default net(s) (#435 single-ended companion).")
        except Exception as _e:
            unknown.append({'code': 'class_widths_unavailable', 'error': type(_e).__name__,
                            'detail': str(_e)})
            print(f"Warning: could not auto-read netclass track widths ({_e}).")
            net_track_widths = {}

    return {"net_track_widths": net_track_widths,
            "netclass_width_floors": netclass_width_floors,
            "net_layer_widths": _per_layer,
            "net_via_sizes": _per_net_via, "unknown": unknown}


def pair_class_width(classes, rules, p_net_name, base, from_class, floor):
    """The differential engine's nominal per-pair width before impedance."""
    from list_nets import resolve_net_class
    cls = classes.get(resolve_net_class(p_net_name, rules), {}) if classes else {}
    width = cls.get('diff_pair_width') if from_class else None
    return max(width if width is not None else base, floor)


class WidthPolicyRefusal(ValueError):
    """The width policy cannot answer for these arguments: `code` and `fields` say why."""

    def __init__(self, code, **fields):
        super().__init__(code, fields)
        self.code = code
        self.fields = fields


class _ParserCaptured(Exception):
    def __init__(self, parser):
        super().__init__()
        self.parser = parser


_PARSERS = {}


def router_parser(module):
    """The argparse parser `py_router/<module>` builds in its `__main__`.

    route.py and route_diff.py build their parser inline under `__main__`
    (upstream has no build_parser()), so the script is run up to its
    parse_args() call, which is intercepted before it parses anything. What
    runs before that point is imports, the CMD banner (suppressed here with
    KRT_NO_BANNER) and parser construction.
    """
    if module not in _PARSERS:
        import argparse
        import contextlib
        import io
        import runpy
        import sys
        from pathlib import Path
        script = str(Path(__file__).resolve().parent / module)
        real = argparse.ArgumentParser.parse_args

        def capture(self, *args, **kwargs):
            raise _ParserCaptured(self)

        saved_argv, saved_banner = sys.argv, os.environ.get('KRT_NO_BANNER')
        sys.argv = [script]
        os.environ['KRT_NO_BANNER'] = '1'
        argparse.ArgumentParser.parse_args = capture
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                runpy.run_path(script, run_name='__main__')
        except _ParserCaptured as got:
            _PARSERS[module] = got.parser
        finally:
            argparse.ArgumentParser.parse_args = real
            sys.argv = saved_argv
            if saved_banner is None:
                os.environ.pop('KRT_NO_BANNER', None)
            else:
                os.environ['KRT_NO_BANNER'] = saved_banner
        if module not in _PARSERS:
            raise WidthPolicyRefusal('router_parser_unavailable', module=module)
    return _PARSERS[module]


#: The options the width policy reads, by argparse dest.
_WANTED = {'track_width': '--track-width', 'diff_pair_gap': '--diff-pair-gap', 'impedance': '--impedance',
           'fab_tier': '--fab-tier', 'fab_overrides': '--fab-overrides'}
#: Options whose widths the policy needs as structured request fields, not as arguments.
_STRUCTURED = {'power_nets': '--power-nets', 'power_nets_widths': '--power-nets-widths',
               'connections': '--connections'}


def options(args, module):
    """The width options `args` give, parsed by the router script's own parser.

    Returns {flag: parsed value} for the options given; an option left out is
    absent. `args` are option arguments of one call; the board is supplied
    here as the script's positional input file.
    """
    import argparse
    import contextlib
    import io
    parser = router_parser(module)
    unset = object()
    namespace = argparse.Namespace(**{dest: unset for dest in list(_WANTED) + list(_STRUCTURED)})
    errors = io.StringIO()
    try:
        with contextlib.redirect_stderr(errors), contextlib.redirect_stdout(io.StringIO()):
            parsed = parser.parse_args(['board.kicad_pcb'] + list(args), namespace=namespace)
    except SystemExit as stop:
        raise WidthPolicyRefusal('router_arguments_rejected', module=module, args=list(args),
                                 exit_code=stop.code, error=errors.getvalue().strip()) from None
    for dest, flag in _STRUCTURED.items():
        if getattr(parsed, dest) is not unset:
            raise WidthPolicyRefusal('structured_request_field_required', option=flag)
    return {flag: getattr(parsed, dest) for dest, flag in _WANTED.items()
            if getattr(parsed, dest) is not unset}


def nominal_policy(board, requests):
    """Read-only versioned per-call width policy, using the routing resolvers.

    Impedance-derived geometry is explicitly unknown; connection task widths
    and named power widths retain their actual engine precedence.
    """
    import argparse
    import hashlib
    import json
    import math
    from pathlib import Path
    from kicad_parser import parse_kicad_pcb
    from list_nets import board_default_netclass_param, read_design_rules, fab_floors
    from fab_tiers import (add_fab_tier_args, fab_tier_from_args, set_default_fab_tier,
                           set_policy_from_args, enforce_fab_floors)
    from routing_config import GridRouteConfig
    import routing_defaults as defaults
    from protected_nets import read_impedance_for_pcb_data

    def digest(path):
        return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None

    path = Path(board).resolve()
    pcb = parse_kicad_pcb(str(path))
    names = {net.name: nid for nid, net in pcb.nets.items()}
    layers_all = list(pcb.board_info.copper_layers or [])
    ncl = len(layers_all) or 4
    stored = read_impedance_for_pcb_data(pcb, str(path)) if pcb.board_info.stackup else {}
    out = []
    external = {}
    for request in requests:
        kind = request['kind']
        args = request['args']
        rest_override = ('--track-width' in options(request.get('rest_phase_args', []), 'route.py')
                         if 'rest_phase_args' in request else False)
        if rest_override:
            kind, args = 'nets', request['rest_single_args']
        module = 'route_diff.py' if kind == 'pairs' else 'route.py'
        parsed = options(args, module)
        fab_parser = argparse.ArgumentParser(add_help=False)
        add_fab_tier_args(fab_parser)
        fab_args = []
        for flag in ('--fab-tier', '--fab-overrides'):
            if flag in parsed:
                fab_args += [flag, str(parsed[flag])]
        fab_args += ['--escalation', 'off']
        fab = fab_parser.parse_args(fab_args)
        if fab.fab_overrides:
            override = Path(fab.fab_overrides).resolve()
            external[str(override)] = digest(override)
        set_default_fab_tier(*fab_tier_from_args(fab))
        set_policy_from_args(fab, str(path))
        explicit = '--track-width' in parsed
        key = 'diff_pair_width' if kind == 'pairs' else 'track_width'
        fallback = defaults.DIFF_PAIR_WIDTH if kind == 'pairs' else defaults.TRACK_WIDTH
        base = float(parsed['--track-width']) if explicit else board_default_netclass_param(str(path), key)
        if base is None:
            base = fallback
        if not math.isfinite(base) or base <= 0:
            raise ValueError('track width must be positive and finite')
        base = enforce_fab_floors(ncl, track_width=base).get('track_width', base)
        layers = list(request['layers'])
        resolved = class_width_inputs(pcb, str(path), layers, track_width_from_class=not explicit)
        config = GridRouteConfig(track_width=base)
        config.net_track_widths = resolved['net_track_widths']
        config.net_layer_widths = resolved['net_layer_widths'] if not explicit else {}
        config.power_net_widths = {names[name]: width for name, width in request.get('power', {}).items()}
        task_widths = {names[name]: widths for name, widths in request.get('tasks', {}).items()}
        config.net_layer_widths.update(task_widths)
        for nid in task_widths:
            config.power_net_widths.pop(nid, None)
        rules = read_design_rules(str(path)) if kind == 'pairs' else {}
        classes = rules.get('classes') or {}
        paired = {name: pair[0] for pair in request.get('pairs', []) for name in pair}
        floor = fab_floors(ncl).get('track_width', 0.0)
        by_net = {}
        for name in request['nets']:
            nid = names[name]
            reason = None
            dominant = nid in task_widths or nid in config.power_net_widths
            if not dominant and ('--impedance' in parsed or name in stored):
                reason = {'code': 'impedance_width'}
            elif not dominant and not explicit and resolved['unknown']:
                reason = {'code': 'design_rules_unknown', 'rules': resolved['unknown']}
            widths = {layer: config.get_net_track_width(nid, layer) for layer in layers}
            if kind == 'pairs':
                width = pair_class_width(classes, rules, paired[name], base, not explicit, floor)
                # The engine rounds per-pair geometry to four decimals.
                # With both geometry flags explicit the global branch can
                # remain unrounded; refuse to guess which branch will win.
                if explicit and '--diff-pair-gap' in parsed and round(width, 4) != width:
                    reason = {'code': 'pair_geometry_rounding', 'width': width}
                widths = {layer: round(width, 4) for layer in layers}
            by_net[name] = {'status': 'unknown' if reason else 'known',
                            'widths': None if reason else widths, 'reason': reason}
        out.append({'name': request['name'], 'kind': request['kind'], 'base_width': base,
                    'owner': request['name'] if rest_override else request.get('owner', request['name']),
                    'effective_kind': kind, 'options': parsed, 'by_net': by_net})
    return {'schema': 1, 'board': str(path),
            'inputs': {str(p): digest(p) for p in (path, path.with_suffix('.kicad_pro'), path.with_suffix('.kicad_dru'))},
            'config_sha256': hashlib.sha256(json.dumps(requests, sort_keys=True).encode()).hexdigest(),
            'external_inputs': external,
            'policies': out}


if __name__ == '__main__':
    import json
    import sys
    data = json.load(sys.stdin)
    print('PLACEMAT_WIDTH_POLICY ' + json.dumps(nominal_policy(data['board'], data['requests']), sort_keys=True))
