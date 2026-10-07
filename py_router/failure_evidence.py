"""Failure evidence: what the router knew when a net failed, as plain data (placemat fork, docs/connections.md).

Facts only: the net's last failed search (iterations and frontier size per direction), the copper its frontier met
and the verdicts KRT's own diagnostics recorded (routing_diagnostics.py). `diagnosis` names a verdict only when
exactly one was recorded; otherwise it is "unknown". Nothing here infers a cause the router did not record."""
from __future__ import annotations

import copy

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
_SUCCESS = ('initial_route', 'reroute_succeeded', 'rescue_succeeded', 'terminal_escalation_succeeded')


def _last_search(history):
    got = None
    for ev in history or ():
        if ev.get('event') == 'search_failed':
            got = ev.get('details') or got
        elif ev.get('event') in _SUCCESS:
            got = None
    return got


def _blocker(**kw) -> dict:
    return {k: kw.get(k) for k in _BLOCKER}


def search_facts(result, pcb_data, config, net_id, nets_to_route) -> dict:
    """A failed search's facts: per direction its iterations, how many frontier cells it found blocked and the point
    it started from, and the static copper those cells fall on, tested at the net's own track width."""
    from blocking_analysis import static_blocker_records
    from connectivity import get_net_endpoints
    sources, targets, _ = get_net_endpoints(pcb_data, net_id, config)
    start = {"forward": [sources[0][3], sources[0][4]] if sources else None,
             "backward": [targets[0][3], targets[0][4]] if targets else None}
    out, static = {}, []
    for d in ("forward", "backward"):
        cells = list(result.get('blocked_cells_' + d) or [])
        out[d] = {"iterations": int(result.get('iterations_' + d, 0)), "frontier_cells": len(cells), "at": start[d]}
        recs = static_blocker_records(cells, pcb_data, config, set(nets_to_route), net_id=net_id)
        static += [dict(r, seen_from=d) for r in recs]
    out["static"] = static
    return out


def evidence_of(state, net_id: int) -> dict:
    """A failed net's evidence: its last failed search, the copper met (routed this run, static, from an earlier
    run, in that order) and KRT's verdicts; failure_evidence.EMPTY's shape."""
    history = state.net_history.get(net_id) or []
    search = _last_search(history)
    blocked = []
    for b in (state.frontier_blocking.get(net_id) or {}).get('blocked_by') or ():
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
    return out
