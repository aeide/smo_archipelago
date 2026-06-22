# Handoff — region-gating egress off-by-one + scenario-predicate audit

Deferred work spun out of the **2026-06-21 Cascade leave-deadlock (round 2)** fix. Read
[scenario-logic-revisit-june-20.md §11](scenario-logic-revisit-june-20.md) first — it is the
full diagnosis. This file is the task list + rationale for the items that were *not* shipped
with the round-2 fix.

## Background: what shipped 2026-06-21 (so you don't redo it)

`CascadeDeparture()` and `CapPeace()` in `apworld/smo_archipelago/hooks/Rules.py` were defined
as `canReachRegion("Sand Kingdom")`, which evaluates **True from sphere 0** and made the
Cascade after-leaving moons a no-op gate → unwinnable starting kingdom. Both were repointed to
`KingdomMoons(<kingdom>, N)` (rolled-gate aware). Guard test:
`apworld/smo_archipelago/tests/test_cascade_reachability.py` (SMOAP_LIVE_AP). Fully verified
(empirical probe + report seed re-gen + 5-seed `accessibility: full` sweep). **Do not reopen
the Cascade gate — it is correct.**

## The root cause both items below share

The Manual-derived generation engine (`apworld/smo_archipelago/Rules.py::set_rules`, region
loop ~L231-238) applies a region's `requires` to that region's **OUTGOING** entrances. So a
region's gate controls **leaving** it, not **entering** it ("egress semantics"). The data was
authored as if `requires` gated **ingress** (e.g. Sand's `{KingdomMoons(Cascade,N)}` reads as
"need N Cascade moons to *reach* Sand"). The mismatch means:

- **Region reachability is off by one kingdom.** `can_reach_region(K)` becomes true one
  kingdom *earlier* than the player could actually be in K. Verified at empty state:
  `can_reach_region("Sand Kingdom") = True` (Sand sits right after the free starting Cascade
  region), while `Cap/Lake/Wooded = False`.
- It is **masked** for kingdom progression because each *location* is independently gated by
  (a) its own region's `requires` string ANDed on at the location level (`set_rules` L249-259)
  and (b) AP's parent-region reachability. So Sand/Lake/etc. *locations* are still correctly
  gated. Only **region-level** `canReachRegion` reads leak the off-by-one.
- That is why the only victims are predicates that call `canReachRegion(<kingdom>)`, and why
  only the **starting** kingdom (Cascade — empty region `requires`, so no location-level gate
  masks it) was catastrophic.

---

## Deferred item 1 — audit `CloudPeace` / `LostPeace` / `MoonPeace` (LOW risk, DO THIS FIRST) — ✅ DONE 2026-06-22

**Outcome:** audited with a solo-multiworld collection walk; the off-by-one reproduced exactly.
`canReachRegion("Night Metro")` opens at the **Wooded** leave-gate (zero Lost moons) — one
kingdom early; `canReachRegion("Mushroom Kingdom")` at the **Bowser's** leave-gate — one kingdom
early; Cloud's *region* is correctly gated at Lost(10) by its parent edge. **Fix:** `LostPeace` +
`CloudPeace` → `KingdomMoons("Lost",10)`; `MoonPeace` left on `canReachRegion` (no faithful
pre-win threshold — Moon→Mushroom is the win edge). Guard test
`tests/test_rearrival_reachability.py` added; full record in
[scenario-logic-revisit-june-20.md §12](scenario-logic-revisit-june-20.md). Item 2 (the systemic
engine fix) remains deferred. *(Original task notes preserved below for context.)*

These three re-arrival predicates still use `canReachRegion`:

| Predicate | Current def | Empty-state value (1 probe) |
|---|---|---|
| `CloudPeace` | `canReachRegion("Night Metro")` | False |
| `LostPeace`  | `canReachRegion("Night Metro")` | False |
| `MoonPeace`  | `canReachRegion("Mushroom Kingdom")` | False |

They are **not no-ops** (their target regions are genuinely gated, unlike free Sand), so they
do not have the acute Cascade bug. **But** because region reachability is off by one kingdom,
they may gate at the *wrong threshold* (one kingdom too early). Tasks:

1. With the `setup_multiworld` probe pattern (see the inline `_PROBE` in
   `tests/test_cascade_reachability.py`), check at empty state AND across a collection walk:
   does `canReachRegion("Night Metro")` open exactly when the player can first be in Night
   Metro in-game, or one kingdom early? Same for `Mushroom Kingdom`.
2. If they open too early, repoint each to the faithful moon-count gate, the same way
   `CascadeDeparture` was fixed:
   - "Has left Lost" / "post-Night-Metro" → `KingdomMoons("Lost", N)` (Lost IS in
     `KINGDOM_MOON_GATES`, N=10) — confirm Lost's gate is the right threshold for the Cloud
     re-arrival route, since Cloud is reached *after* Lost in the travel graph.
   - `MoonPeace` is documented as a deliberate no-op today (Moon→Mushroom is the win edge);
     leave it unless a post-festival goal is ever added (see CLAUDE.md "Deferred work").
3. Extend `test_cascade_reachability.py` (or a sibling) with the same empty/boundary/open
   assertions for whichever predicates you touch. **Rule going forward: never express "player
   has left kingdom K" as `canReachRegion(<kingdom>)` — use `KingdomMoons(K, …)`.**

Risk: low. These are leaf predicates on post-game moon layers; a too-early gate over-permits
(benign-ish) rather than deadlocks, and the fix is a one-line repoint per predicate. No
generation re-tune needed. Sweep a handful of `accessibility: full` seeds after.

---

## Deferred item 2 — the systemic egress→ingress engine fix (HIGH risk, needs a sweep budget)

The *correct* fix for the off-by-one is to make `set_rules` gate region **ingress**: apply a
region's `requires` to its **incoming** entrances (rule on entrance `X→Y` = Y's requires),
matching how the data was authored. Sketch (region loop in `Rules.py::set_rules`):

```python
for region in regionMap.keys():
    if region == "Menu":
        continue
    for ent in multiworld.get_region(region, player).exits:
        dest = ent.connected_region.name            # gate INGRESS: use the destination
        if dest in regionMap:
            def rule(state, rdata=regionMap[dest]):  # was regionMap[region] (source = egress)
                return fullLocationOrRegionCheck(state, rdata)
            set_rule(multiworld.get_entrance(ent.name, player), rule)
```

This removes the off-by-one **globally** and makes `canReachRegion(K)` mean "the player can
actually be in K" — after which `CascadeDeparture`/`CapPeace` could revert to the natural
`canReachRegion` form and item 1's predicates become trivially correct.

**Why it is deferred (do NOT attempt casually):**

- It shifts **every** kingdom gate by one edge. `regions.json` requires, the
  `KINGDOM_MOON_GATES` table, `_demote_surplus_kingdom_moons`, and the per-kingdom
  moon-count option floors were all authored/tuned under egress semantics. Flipping to ingress
  makes gates bite **earlier/stricter**, which raises fill pressure and risks `FillError`
  across kingdoms — a clean run today is **not** evidence it survives the flip.
- Interacts with load-bearing systems that were validated under egress: `randomize_kingdom_gates`
  (the rolled table), the entrance shuffle's `make_door_access_rule` / D3 subarea gate
  re-application, and `kingdom_order_gate`. Each needs re-checking under ingress.
- The location-level region check (`set_rules` L249-259) ANDs the region `requires` onto each
  location *in addition to* the entrance rule. Under ingress this becomes partly redundant with
  the new entrance gate; confirm it doesn't double-gate or contradict (it shouldn't — AND of a
  predicate with itself — but verify, especially where entrance shuffle replaces location
  rules).

**Required validation before shipping the engine fix:**

1. Full `accessibility: full` Generate sweep, entrance-shuffle ON and OFF, randomize-gates ON
   and OFF, multi_moon_shuffle ON/OFF, festival + mushroom goals — a real matrix, not 1 seed.
   Watch for `FillError`, not just "Done."
2. Re-derive whether `KINGDOM_MOON_GATES` / the demotion thresholds still leave each gate
   satisfiable from the pre-gate location pool under the now-stricter ordering.
3. Revert `CascadeDeparture`/`CapPeace` to `canReachRegion` ONLY if the engine fix lands, and
   re-run `test_cascade_reachability.py` to prove the gate still holds.
4. In-game smoke test on the report seed class (Cascade gate at its high end, 9-10).

**Recommendation:** keep the targeted `KingdomMoons` predicate fixes (already shipped + tested)
as the production path. Treat the engine fix as a separate, budgeted refactor only if the
off-by-one causes a *second* concrete failure that the predicate-level approach can't cover.
Until then, the `KingdomMoons`-based predicates are correct and self-contained.

## Pointers

- Diagnosis + correction: [scenario-logic-revisit-june-20.md §11](scenario-logic-revisit-june-20.md)
- Original (round-1) Cascade diagnosis: same doc §1-§10
- D1/D2/D3 scenario rewrite: [handoff-scenario-logic-rewrite.md](handoff-scenario-logic-rewrite.md)
- Guard test + reusable probe pattern: `apworld/smo_archipelago/tests/test_cascade_reachability.py`
- "Not a Manual world" clarification: CLAUDE.md (top)
