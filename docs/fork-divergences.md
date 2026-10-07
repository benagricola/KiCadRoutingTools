# Fork divergences

## Rip ladder: pocket walls first

- Upstream: phase3_routing.py `try_phase3_ripup` ranks failed tap frontiers,
  then tries progressively larger sets of rippable nets. A larger failed
  frontier can outrank the copper enclosing a small endpoint pocket.
- Fork: pocket_walls.py floods each failed tap target on the obstacle map
  used by that search. A closed region within `max_probe_iterations` supplies
  its boundary nets before the existing ladder ranking, smallest region
  first and then most boundary cells owned. The ladder's rip limits,
  protection checks and acceptance rules remain unchanged.
- Flood semantics: track margins, corner guards, terminal exemptions, via
  rungs and forbidden destination layers follow rust_router/src/router.rs
  GridSearch's neighbour loop. Direction and path-local via restrictions
  are omitted, making reachability conservative: those omissions can miss
  a pocket but cannot create one. The map is cloned and never mutated.
- Why: bounded rip attempts should open a trapped endpoint before spending
  their budget on unrelated copper.
- Test: tests/test_rip_pocket_walls_first.py.
