# Handoff — decoupled entrance shuffle collapses the flight moon economy (audit + fix plan)

**Status: AUDITED 2026-07-12, fix NOT yet implemented.** This doc is the complete
diagnosis plus a step-by-step plan sized for a single implementation session
(Opus/Sonnet). Read [design-decoupled-kingdom-order.md](design-decoupled-kingdom-order.md)
(D1–D9) and the docstring of `hooks/World.py::_wire_decoupled_entrances` first —
the fix must live inside those constraints, not replace them.

## Symptom

`entrance_shuffle: decoupled` seeds generate "successfully" but produce absurdly
short playthroughs (~8 spheres, victory after a handful of moons) with a huge
Unreachable Progression Items list. The same YAML with `simple` or `off`
produces normal 20+ sphere playthroughs. Devon's evidence pair (2026-07-12):
seed 86329896626912593217 (decoupled, victory at sphere 8, ~200 stranded
progression items) vs seed 66114738543517465258 (simple, victory at sphere 22,
5 stranded items). Both spoilers show Mushroom Kingdom checks in **sphere 1**
of the decoupled seed — the goal kingdom's neighborhood is logic-reachable
nearly from the start.

**The invariant that must hold after the fix:** the Odyssey still has to fly the
kingdom chain in order, so reaching Moon Kingdom (the victory region) must cost
the full cumulative moon economy — vanilla 124, or the sum-preserved rolled
total under `randomize_kingdom_gates`. Decoupled may widen WHERE you can stand
and WHICH checks open early (that's the point of the mode), but it must never
discount a single flight gate (design D1, signed off).

## Root cause — three layers that compose into the leak

1. **The Manual egress quirk** ([handoff-region-gating-egress.md](handoff-region-gating-egress.md)):
   `Rules.py::set_rules` applies a region's `requires` to its **outgoing**
   entrances. Each inter-kingdom flight edge therefore carries exactly ONE
   kingdom's gate (the source region's own `requires`, e.g. the Bowser's →
   Moon edge carries only Bowser's `{KingdomMoons(Ruined,3)}`). The cumulative
   124-moon cost is never present on any single edge — it emerges ONLY from
   `reach()` having to traverse the whole `regions.json` chain.

2. **The decoupled two-channel wiring** (`hooks/World.py::_wire_decoupled_entrances`):
   every matched port edge whose target is an overworld mouth in kingdom K
   lands in a synthetic "K Arrival" region, and a **free** "K Arrival → K"
   presence edge grants the `regions.json` kingdom region itself (so K's
   overworld locations enter logic — intended, D1/D9).

3. **The port matching is connectivity-guaranteed** (`port_matching.roll_port_matching`),
   so from the free start (Cascade/Cap) nearly every kingdom's Arrival region
   is chain-reachable at low cost (just movement/capture items on the edge
   rules — no moons at all).

Compose them: chain into Bowser's Kingdom on foot → free presence edge grants
the Bowser's *region* → Bowser's outgoing flight edge to Moon charges only its
single-hop `{KingdomMoons(Ruined,3)}` → **reach(Moon Kingdom) = 3 Ruined moons
plus some movement items.** The victory location ("Arrive in the Mushroom
Kingdom", `region: Moon Kingdom`) has only a movement-item `requires`
(Parabones/Banzai Bill/Spark pylon OR the GPJ/Cap Bounce/Wall Slide alt), so the
whole seed's goal costs ~one kingdom's worth of moons. That is exactly what the
decoupled spoiler shows: Ruined moons in spheres 1–2, the movement chain by
sphere 7, victory at sphere 8.

The design doc's D1 claim — "a chain-reached K only opens K's onward FLIGHT
edge if K's requires is also genuinely satisfied" — re-charges only the **last
hop**, not the accumulated chain. `reach()` was the accumulator, and the free
Arrival→K edge poisons `reach()`. D1's *intent* (chains never discount flight
costs) is violated by D1's own *implementation sketch*. This needs an erratum
in the design doc (step 5 below).

Two aggravating factors (context, not causes):

- **The world force-relaxes accessibility full → minimal**
  (`hooks/World.py::_relax_full_accessibility`, a known, deliberate
  limitation). Fill therefore only guarantees the goal. With the goal
  near-free, fill happily strands ~200 progression items — the giant
  Unreachable list is a *symptom* of the cheap goal, not an independent bug.
- **Physical honesty:** per D3 the Odyssey stays home on chain arrival, and
  reload evicts Mario to his last flight-unlocked kingdom. You genuinely
  cannot fly Bowser's → Moon without having flown TO Bowser's. So the current
  logic doesn't just make seeds short — it makes them **unwinnable in the real
  game** (logic promises a Bowser's→Moon flight the player can never perform).

## Why the tests missed it

`tests/test_decoupled_region_wiring.py::test_kingdom_arrival_channel_and_flight_gates_unchanged`
asserts the *letter* of D1 — flight edges' rules are untouched
(`unclobbered == 0`) — but never the *invariant*: that `can_reach_region("Moon
Kingdom")` still costs the full economy. Leaving each flight edge untouched is
precisely the bug: untouched single-hop gates + a polluted `reach()` = discount.

## The fix — AND a flight-channel predicate onto inter-kingdom flight edges

Smallest change that restores the invariant while keeping the two-channel
model, the Arrival regions, D9 Mushroom promotion, and the simple/off paths
byte-identical:

**Under decoupled only**, after the core `set_rules` clobber has run, walk the
`regions.json` kingdom DAG and `add_rule` (AND, never `set_rule`) onto every
entrance `K → J` where **both K and J are `regions.json` regions** (skip
"K Arrival" destinations; see the Pokino decision below) a predicate
`flight_reach(state, K)` meaning "the player could have FLOWN to K":

```python
# hooks/World.py — new helper, called from the decoupled branch of after_set_rules
def _apply_decoupled_flight_economy(world, multiworld, player):
    """D1 erratum fix: chain arrival (matched edge -> K Arrival -> K) must
    never discount the cumulative flight moon economy. Every inter-kingdom
    flight edge gets the source kingdom's flight-channel reachability ANDed
    on, computed over regions.json connects_to ONLY (chain edges excluded
    by construction). Pure evaluation, ~16 nodes, no memo needed."""
    region_map = ...  # the same regionMap Rules.py::set_rules iterates (Data/Game region table)
    parents: dict[str, list[str]] = {}   # J -> [P, ...] from P.connects_to
    start = ...                          # the region with "starting": true (Cascade)

    def requires_ok(state, name):
        # EXACTLY the same evaluation the set_rules clobber uses for the
        # region's requires (fullLocationOrRegionCheck / fullRegionCheck on
        # regionMap[name]) — do not reimplement the requires DSL.
        ...

    def flight_reach(state, name):
        if name == start:
            return True
        return any(flight_reach(state, p) and requires_ok(state, p)
                   for p in parents.get(name, ()))

    for K in region_map:
        for ent in multiworld.get_region(K, player).exits:
            dest = ent.connected_region.name
            if dest not in region_map or dest in FLIGHT_ECONOMY_EXEMPT:
                continue  # skips "K Arrival" edges and exempted pseudo-regions
            add_rule(ent, lambda state, k=K: flight_reach(state, k))
```

Why this is correct and sufficient:

- Under **pure flight** (no chains), `flight_reach(K)` is implied by having
  reached K through the chain anyway — the AND is redundant, so vanilla-shaped
  reachability is unchanged. Forks (Sand → Lake/Wooded; Night Metro →
  Cloud/Metro; Metro → Snow/Seaside → Very Early Luncheon → Luncheon) are
  handled by the OR-over-parents recursion, mirroring `reach()` semantics
  exactly. Empty `requires` (Cascade, Very Early Luncheon, Mushroom, Dark
  Side) evaluate free, exactly as the clobber does.
- Under **chains**, a chain-granted K region can no longer open K's onward
  flight edges: `flight_reach(K)` demands the whole gate chain up to K as item
  predicates ({KingdomMoons} counts are location-agnostic, so this equals
  "could have flown here in order"). reach(Moon) is restored to
  5+16+8+16+10+20+10+10+18+3+8 = **124** (or the rolled sum-preserved total —
  `KingdomMoons` is rolled-gate aware already).
- Moon/Dark/Darker have no Arrival regions (D6 — their overworld mouths never
  pool), so the victory region is reachable ONLY through the now-honest
  Bowser's → Moon flight edge.
- Chain widening survives: Arrival regions, the free Arrival→K presence edge,
  the D9 Mushroom promotion, interior/far-side wiring — all untouched. Only
  the flight edges got honest.

### Decisions taken (change only with Devon's sign-off)

- **`FLIGHT_ECONOMY_EXEMPT = {"Pokino"}`.** Pokino is a `regions.json`
  pseudo-region hanging off Bowser's that exists to hold the Pokio capture
  check (`{YamlDisabled(capturesanity)} or |Pokio|`). A chain visitor standing
  in Bowser's overworld with the Pokio item can physically do it — gating it
  on `flight_reach(Bowser's)` would over-restrict. Exempt it (this preserves
  the intended chain widening for that check).
- **Do NOT touch "K → K Arrival" edges** (destination not in `regions.json`,
  so the loop above skips them naturally). Chain visitors are already IN
  Arrival; the edge only matters for flight arrivals, whose clobbered rule is
  already the honest predicate. Touching it would also break the
  `start_at_cap_peace` sphere-0 Cap assumption.
- **Ordering:** call the new helper at the END of the
  `option_decoupled` branch of `after_set_rules` (after
  `_apply_entrance_shuffle_location_rules` + `_apply_subarea_scenario_gates`).
  `_apply_start_at_cap_peace_rules` and `_apply_no_logic` already run after
  that branch and use `set_rule` (replace), so they still win — that is
  correct (Cap-peace frees Cap's incoming edges, Cap has no onward
  `connects_to`, no leak; no_logic must flatten everything).
- **Do NOT attempt the systemic egress→ingress engine fix** (deferred item 2
  of handoff-region-gating-egress.md). It's orthogonal, high-risk, and this
  fix neither needs it nor blocks it.

## Step-by-step plan

1. **Implement `_apply_decoupled_flight_economy`** in
   `apworld/smo_archipelago/hooks/World.py` per the sketch above.
   - Source the region table the same way `Rules.py::set_rules` does (grep
     for the region loop ~L231 and reuse its data + check helpers — do not
     re-parse regions.json independently at rule-eval time).
   - `from worlds.generic.Rules import add_rule` (AND semantics — the
     clobbered core rule must survive as a conjunct; grep the existing
     `_apply_entrance_shuffle_door_rules` for the established add_rule
     pattern and its "add_rule NOT set_rule" warning).
   - Guard: no-op unless `_entrance_shuffle_mode(...) == option_decoupled`.
2. **Wire the call** into the `elif _es_mode == EntranceShuffle.option_decoupled:`
   branch of `after_set_rules` (hooks/World.py ~L1457), last in the branch.
   Update that branch's comment block — its current text claims the clobbered
   flight rule "is exactly what we want", which the audit disproved.
3. **Fix the guard test** `tests/test_decoupled_region_wiring.py::
   test_kingdom_arrival_channel_and_flight_gates_unchanged`: the
   `unclobbered == 0` assertion now fails by design (flight edges carry
   core-rule AND flight-predicate). Rework the collector to assert the new
   shape instead: every exit of a regions.json region whose destination is a
   non-exempt regions.json region has BOTH conjuncts.
4. **Add the invariant test** (same file, reuse its `build()` harness and the
   probe pattern from `tests/test_cascade_reachability.py`):
   - Empty state, decoupled seed: `can_reach_region("Moon Kingdom")` is
     **False**; also False after granting ALL non-moon progression (abilities
     + captures) — proves moons are the binding constraint.
   - Collection walk: Moon first becomes reachable only when every kingdom's
     gate count is satisfied (sum == 124 vanilla, or the rolled sum with
     `randomize_kingdom_gates` on — assert against `world`'s rolled gate
     table, not a hardcoded 124).
   - Sibling seed with `simple`: assertions about simple-mode wiring
     (`test_simple_mode_grows_no_decoupled_machinery`) still pass — the fix
     must be decoupled-only.
5. **Docs:** add an erratum block to
   [design-decoupled-kingdom-order.md](design-decoupled-kingdom-order.md) §D1
   (the two-channel sketch discounted flight via the Arrival→K presence edge;
   fixed by the flight-economy predicate, date + this doc's name), and a
   one-line pointer in CLAUDE.md's P7/decoupled status paragraph.
6. **Validate on Windows** (the Linux sandbox mount is unreliable — see
   CLAUDE.md dev-environment gotcha — and Generate must use the rebuilt zip):
   ```powershell
   cd E:\smo_archipelago
   python -m pytest apworld\smo_archipelago\tests\test_decoupled_region_wiring.py apworld\smo_archipelago\tests\test_entrance_shuffle_option_modes.py apworld\smo_archipelago\tests\test_cascade_reachability.py -q
   python scripts\install_apworld.py          # REQUIRED — Generate loads the zip, not the source tree
   python vendor\Archipelago\Generate.py      # with Devon's decoupled YAML in Players/
   ```
   Acceptance on the new spoiler: victory sphere depth comparable to the
   simple seed (~20+, not 8); no Mushroom/Bowser's/Moon checks in sphere 1's
   *flight-gated* sense is NOT required (chain-opened overworld checks in
   early spheres are the mode working) — the acceptance criterion is that the
   **playthrough's collected kingdom-moon counts reach the full gate total
   before victory**, and the Unreachable Progression Items list shrinks to
   simple-seed scale. Re-generate the SIMPLE and OFF yamls too and diff —
   they must be byte-identically shaped (no rule changes leak outside
   decoupled).
7. **No other tiers change.** This is apworld-generation only: no switch-mod
   rebuild, no client change, no slot_data schema change, no
   `sync_shine_table`/`sync_capture_table` runs.

## Pointers

- Wiring under audit: `apworld/smo_archipelago/hooks/World.py` —
  `_prepare_decoupled_entrance_shuffle`, `_wire_decoupled_entrances`
  (docstring documents the two-channel model), `after_set_rules` decoupled
  branch, `_relax_full_accessibility`.
- Port model: `apworld/smo_archipelago/port_graph.py`,
  `port_matching.py` (connectivity guarantee = why every kingdom is
  chain-reachable).
- Flight DAG + gates: `apworld/smo_archipelago/data/regions.json`
  (egress semantics! `requires` on K gates LEAVING K — see
  [handoff-region-gating-egress.md](handoff-region-gating-egress.md)).
- Victory location: `data/locations.json` → "Arrive in the Mushroom Kingdom"
  (`region: Moon Kingdom`, movement-item requires only).
- Design constraints: [design-decoupled-kingdom-order.md](design-decoupled-kingdom-order.md)
  — D1 (no discount), D3 (Odyssey is home / reload evicts), D6 (endgame via
  chain permanently out), D9 (Mushroom promotion stays).
- Evidence seeds: Devon's spoiler pair, 2026-07-12 (decoupled
  86329896626912593217 vs simple 66114738543517465258).
