"""Failure evidence: what the router knew when a net failed, as plain data (placemat fork, docs/connections.md).

FORK DIVERGENCE (docs/fork-divergences.md, "Failure evidence as data"): upstream keeps no such record.

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


def _succeeded(ev) -> bool:
    """A success event that ends the failure. A rescue that left the net in pieces (`rescue_succeeded` with
    `fully_connected` false, net_rescue.py) joined some pads and not others, so the failure it follows still stands."""
    if ev.get('event') not in _SUCCESS:
        return False
    return not (ev.get('event') == 'rescue_succeeded' and (ev.get('details') or {}).get('fully_connected') is False)


def _failure_epoch(history):
    """Events after the latest successful route or new failed search.

    A new search invalidates older diagnoses and blocker attribution even
    when the net did not route successfully between those attempts.
    """
    start = 0
    for i, ev in enumerate(history or ()):
        if _succeeded(ev):
            start = i + 1
        elif ev.get('event') == 'search_failed':
            start = i
    return (history or [])[start:]


def _blocker(**kw) -> dict:
    return {k: kw.get(k) for k in _BLOCKER}


def search_facts(result, pcb_data, config, net_id, nets_to_route) -> dict:
    """A failed search's recorded iterations and frontier attribution.

    The search is multi-source and multi-target and reports no start, so the
    record carries none.
    """
    from blocking_analysis import static_blocker_records
    out, static = {}, []
    for d in ("forward", "backward"):
        cells = list(result.get('blocked_cells_' + d) or [])
        iterations = result.get("iterations_" + d)
        out[d] = {"iterations": int(iterations) if iterations is not None else None,
                  "frontier_cells": len(cells) if "blocked_cells_" + d in result else None}
        recs = static_blocker_records(cells, pcb_data, config, set(nets_to_route), net_id=net_id)
        static += [dict(r, seen_from=d) for r in recs]
    out["static"] = static
    return out


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
    return out
