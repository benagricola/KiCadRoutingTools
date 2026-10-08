"""Failure evidence: what the router knew when a net failed, as plain data (placemat fork, docs/connections.md).

Facts only: the net's last failed search (iterations and frontier size per direction), the copper its frontier met
and the verdicts KRT's own diagnostics recorded (routing_diagnostics.py). `diagnosis` names a verdict only when
exactly one was recorded; otherwise it is "unknown". Nothing here infers a cause the router did not record."""
from __future__ import annotations

import copy
import math
import re

VERDICTS = ('boxed_in_static', 'sealed_by_snpc', 'fanout_dropped')
EMPTY = {"scope": "net", "search": None, "blocked_by": [], "verdicts": [], "narrow": [], "diagnosis": "unknown"}
_BLOCKER = ("found_by", "kind", "net", "ref", "pad", "layer", "at", "cells", "seen_from", "near_source_cells",
            "near_target_cells")


def _last(history, event):
    got = None
    for ev in history or ():
        if ev.get('event') == event:
            got = ev.get('details') or got
    return got


# Net events that mean a route of the net was found after a failed search (routing_state.record_net_event callers);
# a search that one of these follows no longer describes the net's failure.
# search_found is edge-local: it clears evidence, not whole-net connectivity.
_SUCCESS = ('initial_route', 'reroute_succeeded', 'rescue_succeeded', 'terminal_escalation_succeeded', 'search_found')


def _failure_epoch(history):
    """Events after the latest successful route or new failed search.

    A new search invalidates older diagnoses and blocker attribution even
    when the net did not route successfully between those attempts.
    """
    start = 0
    for i, ev in enumerate(history or ()):
        if ev.get('event') in _SUCCESS:
            start = i + 1
        elif ev.get('event') in ('search_failed', 'search_outcome_unknown'):
            start = i
    return (history or [])[start:]


def _blocker(**kw) -> dict:
    return {k: kw.get(k) for k in _BLOCKER}


def search_facts(result, pcb_data, config, net_id, nets_to_route) -> dict:
    """A failed search's recorded iterations and frontier attribution.

    Starts stay unknown unless explicitly supplied by the search result.
    Net endpoints are not necessarily the searched endpoints.
    """
    from blocking_analysis import static_blocker_records
    out, static = {}, []
    for d in ("forward", "backward"):
        cells = list(result.get('blocked_cells_' + d) or [])
        iterations = result.get("iterations_" + d)
        out[d] = {"iterations": int(iterations) if iterations is not None else None,
                  "frontier_cells": len(cells) if "blocked_cells_" + d in result else None,
                  "at": result.get("search_start_" + d)}
        recs = static_blocker_records(cells, pcb_data, config, set(nets_to_route), net_id=net_id)
        static += [dict(r, seen_from=d) for r in recs]
    out["static"] = static
    return out


def _positive_dimension(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        return float(value) if math.isfinite(value) and value > 0 else None
    except OverflowError:
        return None


def attempt_geometry(config, net_id):
    """Actual attempt configuration only; absent or unsupported facts stay unknown."""
    layers = getattr(config, 'layers', None)
    if not (isinstance(layers, (list, tuple)) and layers
            and all(isinstance(layer, str) and re.fullmatch(
                r'(?:F|B|In(?:[1-9]|[12][0-9]|30))\.Cu', layer) for layer in layers)
            and len(set(layers)) == len(layers)):
        layers = None
    widths = None
    getter = getattr(config, 'get_net_track_width', None)
    if layers is not None and callable(getter):
        widths = {}
        for layer in layers:
            try:
                widths[layer] = _positive_dimension(getter(net_id, layer))
            except (AttributeError, KeyError, TypeError, ValueError, OverflowError):
                widths[layer] = None
    return {'grid_step_mm': _positive_dimension(getattr(config, 'grid_step', None)),
            'track_widths_mm': widths,
            'layers': list(layers) if layers is not None else None,
            'via_size_mm': _positive_dimension(getattr(config, 'via_size', None)),
            'via_drill_mm': _positive_dimension(getattr(config, 'via_drill', None))}


def _capture_search_outcome(state, record_id, result, pcb_data, config,
                            source_id, nets_to_route, *, rejected=False):
    if not getattr(config, 'failure_evidence', False):
        return
    from routing_state import record_net_event
    if rejected or result is None:
        record_net_event(state, record_id, 'search_outcome_unknown',
                         {'outcome': 'route_rejected' if rejected else 'unavailable'})
    elif result.get('failed'):
        facts = search_facts(result, pcb_data, config, source_id, set(nets_to_route))
        facts['attempt'] = attempt_geometry(config, source_id)
        record_net_event(state, record_id, 'search_failed', facts)
    else:
        # Edge-local success clears stale facts without claiming net closure.
        record_net_event(state, record_id, 'search_found')


def search_observer(state, nets_to_route):
    """Capture actual attempts before frontier consumption or terrain restore."""
    def observe(result, pcb_data, config, net_id, *, rejected=False):
        _capture_search_outcome(state, net_id, result, pcb_data, config,
                                net_id, nets_to_route, rejected=rejected)
    return observe


def oracle_search_observer(state, nets_to_route):
    """Bind a reparsed oracle's IDs by the original state's semantic names.

    Failure attribution uses the actual parsed board and its IDs, while the
    resulting event belongs to the original state. An ambiguous name domain
    clears prior evidence to unknown; it never guesses an electrical net.
    """
    original = {}
    for net_id, net in state.pcb_data.nets.items():
        original.setdefault(net.name, []).append(net_id)
    requested_ids = set(nets_to_route)
    available_ids = requested_ids & set(state.pcb_data.nets)
    selected = {state.pcb_data.nets[net_id].name for net_id in available_ids}
    original_domain_proved = (available_ids == requested_ids
                              and all(len(original[name]) == 1 for name in selected))

    def observe(result, pcb_data, config, net_id, *, rejected=False):
        if not getattr(config, 'failure_evidence', False):
            return
        from routing_state import record_net_event
        current = {}
        for source_id, net in pcb_data.nets.items():
            current.setdefault(net.name, []).append(source_id)
        name = pcb_data.nets[net_id].name if net_id in pcb_data.nets else None
        matches = original.get(name, [])
        if (not original_domain_proved or len(matches) != 1
                or any(len(current.get(n, [])) != 1 for n in selected)):
            affected = selected | ({name} if name in original else set())
            for n in affected:
                for record_id in original.get(n, []):
                    record_net_event(state, record_id, 'search_outcome_unknown',
                                     {'outcome': 'oracle_name_domain_unproved'})
            return
        source_ids = {current[n][0] for n in selected}
        _capture_search_outcome(state, matches[0], result, pcb_data, config,
                                net_id, source_ids, rejected=rejected)
    return observe


def evidence_of(state, net_id: int) -> dict:
    """A failed net's evidence: its last failed search, the copper met (routed this run, static, from an earlier
    run, in that order) and KRT's verdicts; failure_evidence.EMPTY's shape."""
    history = _failure_epoch(state.net_history.get(net_id) or [])
    search = _last(history, 'search_failed')
    blocked = []
    for b in (_last(history, 'frontier_blocking') or {}).get('blocked_by') or ():
        blocked.append(_blocker(found_by="frontier", kind="routed_copper", net=b['net'], cells=b.get('blocked_count'),
                                near_source_cells=b.get('near_source_cells'),
                                near_target_cells=b.get('near_target_cells')))
    for r in (search or {}).get('static') or ():
        blocked.append(_blocker(found_by="static", **r))
    for name in (_last(history, 'preexisting_blockers') or {}).get('blockers') or ():
        blocked.append(_blocker(found_by="preexisting", kind="copper", net=name))
    verdicts = [dict(_last(history, v), verdict=v) for v in VERDICTS if _last(history, v)]
    out = copy.deepcopy(EMPTY)
    out.update(search={d: search[d] for d in ("forward", "backward")} if search else None, blocked_by=blocked,
               verdicts=verdicts, diagnosis=verdicts[0]["verdict"] if len(verdicts) == 1 else "unknown")
    if search and 'attempt' in search:
        out['attempt'] = copy.deepcopy(search['attempt'])
    return out
