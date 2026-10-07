# Fork divergences

## Rip ladder: pocket walls first

- Upstream: phase3_routing.py `try_phase3_ripup` ranks failed tap frontiers,
  then tries progressively larger sets of rippable nets. A larger failed
  frontier can outrank the copper enclosing a small endpoint pocket.
- Fork: pocket_walls.py floods each failed tap target on the obstacle map
  used by that search. A closed region within `max_probe_iterations` supplies
  its boundary nets before the existing ladder ranking only when no actual
  search source is reachable within it. Both endpoint sets use their search
  terminal exemptions; missing recorded sources declines pocket priority.
  Regions are ordered smallest first and then most boundary cells owned. The ladder's rip limits,
  protection checks and acceptance rules remain unchanged.
- Flood semantics: track margins, corner guards, terminal exemptions, via
  rungs and forbidden destination layers follow rust_router/src/router.rs
  GridSearch's neighbour loop. Direction and path-local via restrictions
  are omitted, making reachability conservative: those omissions can miss
  a pocket but cannot create one. The map is cloned and never mutated.
- Why: bounded rip attempts should open a trapped endpoint before spending
  their budget on unrelated copper.
- Test: tests/test_rip_pocket_walls_first.py.

The boundary attribution is advisory and incomplete: a corner-clipping refusal
records its destination cell rather than every neighbouring guard cell, and
blocked via rungs are not attributed to copper owners. Either can miss wall
nets. Open or unattributed regions use the existing frontier-ranked ladder.

## Isolated pocket repair candidate

Pocket priority is disabled for direct `batch_route` calls. The full CLI first
runs the legacy router from an isolated copy of the input board and its project
and rule sidecars. A reported complete legacy result is preserved exactly;
this shortcut is a routing scope report, not a manufacturing certificate.
Only an incomplete measured result permits one pocket-prioritized proposal
from the same original input, with identical routing flags and a frozen task file.
Both grades use the same requested net set plus the union of both summaries'
owned nets; the sorted scope and task identity are recorded with a SHA-256.
CLI option handling follows argparse, including unambiguous abbreviations and
attached short-option values. File-valued clearance overrides are frozen along
with connection tasks; their digests are recorded. Only the parent records the
original redo invocation; children never record ephemeral trial paths.

Both runs and independent final-file grading share a wall-clock deadline:
`KRT_ROUTE_BUDGET_S` defaults to 3600 seconds, and a caller's earlier absolute
UTC deadline in `KRT_ROUTE_DEADLINE_UTC` takes precedence. Timeout of a proposal
or grader retains the first result. There are at most two complete routing
runs; each retains the existing per-search and rip caps. The internal child
switches are `KRT_INTERNAL_ROUTE_CANDIDATE` and `KRT_INTERNAL_POCKET_WALLS`.

Adoption requires known final-file connectivity in the actual selected net or
pad-task scope, no physical DRC violations, and no requested-size violations.
This first policy requires zero physical violations, including inherited ones;
existing unrelated manufacturing faults may withhold an otherwise helpful
proposal. Required netclass, explicit track and power widths are separate from
fabrication floors. Task endpoint joins and track path widths are remeasured.
A narrower path might be a permitted neck, and a poured join has no track-path
width proof: either makes width compliance unknown and withholds adoption.
Impedance obligations likewise withhold adoption until independently proved.
Only changed outside-scope nets whose connectivity worsens are charged.

A legal, width-proven proposal must reduce open obligations; equal incomplete
closure retains legacy. Complete ties compare vias, copper length, then
segments, with exact ties retaining legacy. The selected board, project/rule
sidecars and summary are staged together, board last, with rollback on a
publication failure. The selected summary retains its own failures and
attribution; `route_candidates` adds budget, grades and selection provenance.
`ROUTE_CANDIDATES` carries the same decision on stdout.

Quick routing (`KRT_ROUTE_QUICK`), preview, skip-routing and schematic-mutating
calls retain the legacy path and report fallback unavailable. The quick wrapper
can continue rewriting its existing top-level `batch_route` anchors unchanged.
Tests: test_route_candidates.py and test_rip_pocket_walls_first.py.
