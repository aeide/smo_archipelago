# Free Lake/Wooded detour with a combined "both" gate (Devon, 2026-06-20)

**Goal.** Today the randomizer forces a linear order on the first main-path detour
pair: after Sand you must visit **Lake** before **Wooded** (and symmetrically
**Snow** before **Seaside** on the second pair). Devon wants the first detour
opened up: once you leave Sand for the first time, fly the Odyssey **freely
between Lake and Wooded** (in either order, like any earlier kingdom) — but
require the **minimum moon counts from BOTH Lake and Wooded** before you can move
on past the detour (toward Cloud / Lost).

This doc covers the **Lake/Wooded** pair only (the explicit request). The
Snow/Seaside pair is structurally identical — everything here applies symmetrically
if that's wanted later — but is out of scope for now.

**Status: investigated, NOT started. Estimate ~80% feasible, medium effort.**
A near-guaranteed logic-only version is low effort; the full in-game "both" gate is
the medium-effort part, and it reuses plumbing that already exists.

---

## How the order is enforced today (two tiers)

The forced order is implemented in **both** tiers and a faithful change must touch
both. Neither alone is sufficient: the apworld decides what the fill considers
reachable; the switch-mod decides what Mario can physically do in-game.

### Tier 1 — apworld logic graph (`data/regions.json` + `hooks/Rules.py`)

The region graph is a **linear chain** through the detour
([data/regions.json](../../apworld/smo_archipelago/data/regions.json)):

```
Sand   → Cap, Lake                 requires KingdomMoons(Cascade,5)
Lake   → Wooded                    requires KingdomMoons(Sand,16)
Wooded → Lost                      requires KingdomMoons(Lake,8)
Lost   → Night Metro               requires KingdomMoons(Wooded,16)
Night Metro → Cloud, Metro         requires KingdomMoons(Lost,10)
```

Two things worth flagging up front:

- **Lake-before-Wooded is encoded purely as graph edges.** `Lake` requires Sand
  moons; `Wooded` requires *Lake* moons; the next critical region (`Lost`)
  requires *Wooded* moons. That chained dependency is exactly the "linear order"
  to be broken.
- **"Cloud Kingdom" is NOT the next critical-path region in the logic graph.**
  Cloud is hung off `Night Metro` (its moons open on re-arrival — see `CloudPeace`
  in [hooks/Rules.py](../../apworld/smo_archipelago/hooks/Rules.py), gated on Night
  Metro). In the *game's* flow Cloud is the brief Bowser/RoboBrood kingdom right
  after Wooded, but in the *logic* the transition that "leaves the detour" is the
  `Lost` region's `requires`. So Devon's "gate before Cloud" maps, in logic terms,
  to the `Lost` edge.

### Devon's clarifications on Cloud entry (2026-06-20)

Two facts from Devon that pin down the in-game side (Part 3):

- **After both Lake AND Wooded are completed, the next kingdom is ALWAYS Cloud** —
  it's story-forced and deterministic, NOT a free map pick. The overworld kingdom
  *selection* can differ from the actual destination because the story interrupts
  travel (the analogous later case: you *select* Metro on the map, but Bowser swoops
  in and reroutes you Moon → Lost → Metro-night). So the "skip Lake via a free
  Sand→Wooded→Cloud pick" concern is weaker than I assumed: Cloud isn't something
  you can freely select out of order — it's the forced consequence of finishing the
  detour pair.
- **Cloud is entered via a CUTSCENE**, arriving in Cloud's **pre-peace** state at the
  Odyssey, about to fight Bowser.

**Implication for Approach B:** the chokepoint is the **cutscene-warp seam**, i.e.
`tryChangeNextStageWithDemoWorldWarp` (the `tryChangeDemoWarpHook` /
"BACKSTOP" path in [WorldMapSelectHook.cpp](../../switch-mod/src/hooks/WorldMapSelectHook.cpp)),
NOT the `calcNextLocked*` map-pick seam. That removes the "which warp path enters
Cloud?" unknown — it's the demo-warp. The gate to add: when that cutscene warp is
about to fire toward Cloud, require both Lake's and Wooded's moon thresholds met
(else hold the player in the detour). Because the destination is story-forced rather
than player-selected, this is a cleaner single chokepoint than a general map gate.

`KingdomMoons(<kingdom>, N)` ([Rules.py:160](../../apworld/smo_archipelago/hooks/Rules.py))
is the key helper: it returns a **requires-string** (an OR-chain over Multi-Moon /
Power-Moon combinations) representing "N effective moons from that specific
kingdom," and it already honors the per-seed `randomize_kingdom_gates` rolled
thresholds. Because it returns a string spliced into the `{...}` template, two
calls can be `and`-combined in one `requires` (this is the lever for "both").

### Tier 2 — switch-mod in-game gate

Three cooperating pieces:

1. **`KingdomOrderGate`**
   ([switch-mod/src/game/KingdomOrderGate.cpp](../../switch-mod/src/game/KingdomOrderGate.cpp))
   holds the forced-order rule table:
   ```cpp
   constexpr Rule kRules[] = {
       {"Wooded",  "Lake", "LakeWorldHomeStage"},   // pick Wooded → redirect to Lake until Lake visited
       {"Seaside", "Snow", "SnowWorldHomeStage"},
   };
   ```
   It releases the redirect once the prereq kingdom is **visited** (sticky bit in
   `ApState::visited_kingdoms`) or is Mario's current kingdom.

2. **`WorldMapSelectHook`**
   ([switch-mod/src/hooks/WorldMapSelectHook.cpp](../../switch-mod/src/hooks/WorldMapSelectHook.cpp))
   applies that decision at three seams: `calcNextLockedWorldIdForWorldMap` (the
   map's "next-locked frontier", 2 overloads) and `tryChangeNextStageWithDemoWorldWarp`
   (the **BACKSTOP** that rewrites the actual stage warp). Per the
   [[kingdom-order-gate-premature-destinations]] memory, destinations already show
   as *selectable* ahead of order and **the BACKSTOP substitution is the only thing
   actually enforcing the linear order** — i.e. the map frontier in this fork is
   already wide open; order is enforced post-hoc by the redirect. This is good news
   for the request (see below).

3. **`UnlockShineNumHook`**
   ([switch-mod/src/hooks/UnlockShineNumHook.cpp](../../switch-mod/src/hooks/UnlockShineNumHook.cpp))
   is the in-game moon-fuel gate: it overrides `findUnlockShineNum[ByWorldId]` to
   return the rolled `ApState::kingdom_gate[bit]` value — "how many moons the
   Odyssey needs to leave the kingdom you're in." It is inherently **single-kingdom**
   (keyed to the current/queried world), which is the core obstacle to a "needs
   both" gate.

---

## What the change requires, piece by piece

### Part 1 — apworld logic: EASY (low effort, ~95% confidence)

Rewrite the detour edges so both Lake and Wooded hang off Sand and the onward
transition requires both:

```
Sand   → Cap, Lake, Wooded          (add Wooded to connects_to)
Lake   → (no longer → Wooded)        requires KingdomMoons(Sand,16)
Wooded → Lost                        requires KingdomMoons(Sand,16)   (was Lake,8)
Lost   → Night Metro                 requires "{KingdomMoons(Lake,8)} and {KingdomMoons(Wooded,16)}"
```

- Both detour kingdoms become reachable directly from Sand for the same Sand-16
  cost (the vanilla cost to *leave* Sand).
- The post-detour edge (`Lost`) requires **both** detour thresholds — the literal
  "minimum moon counts from BOTH Lake and Wooded." `KingdomMoons` returns
  parenthesized sub-expressions, so `{KingdomMoons(Lake,8)} and {KingdomMoons(Wooded,16)}`
  composes cleanly.
- Total moons-to-progress is essentially unchanged from vanilla; the only relaxation
  is *order*, which the fill handles fine (both moon sets just land in an earlier,
  unordered sphere).

**Open check:** confirm the `{A} and {B}` string-combine evaluates correctly through
the Manual-AP `requires` parser (each `KingdomMoons` call already returns a balanced
`(... OR ...)` group, so joining with ` and ` should be valid — verify in a generate
run, not by eye). Decoupling Lake/Wooded order has no known interaction with the
per-kingdom peace gates (`LakePeace`/`WoodedPeace` are independent story-moon checks)
or multi-moon shuffle (each boss MM is location-pinned regardless of order).

### Part 2 — switch-mod free travel: LIKELY EASY (low effort, ~75% confidence)

Per the [[kingdom-order-gate-premature-destinations]] finding, the map frontier is
already open and the **only** thing forcing Lake-first is the BACKSTOP redirect.
If that holds, free Lake↔Wooded travel is achieved by **deleting the first
`kRules` entry** (`{"Wooded","Lake",...}`) in `KingdomOrderGate.cpp`. With the rule
gone, picking Wooded after Sand stops being rewritten to Lake.

Two safety nets confirm this is low-risk even if the frontier is *not* already open:

- **`unlockWorld(GameDataHolderWriter, worldIndex)` already exists and is resolved**
  (used by [OdysseyRescue.cpp](../../switch-mod/src/game/OdysseyRescue.cpp) to force-
  open Lost). If Wooded needs to be force-revealed on the map after Sand, that's a
  one-call primitive we already own — call `unlockWorld(getWorldIndexForest())`
  once Sand is left.
- The Sand→Wooded departure still costs Sand's 16 (the `UnlockShineNum` gate for
  Sand is unchanged), so opening the door doesn't trivialize anything.

**Verify in-game:** that after leaving Sand the map actually offers Wooded as a
flyable destination with the rule removed (the central assumption). If it doesn't,
fall back to the `unlockWorld` force-reveal.

### Part 3 — switch-mod "both before Cloud" gate: MEDIUM (the crux)

This is the only genuinely new in-game logic, because `UnlockShineNum` is
single-kingdom and can't natively express "need moons from two *other* kingdoms."
Two viable approaches:

**Approach A — logic-only (no in-game combined gate). Effort: ~zero beyond Part 1.**
Leave the in-game fuel gates per-kingdom (leave Lake = 8, leave Wooded = 16). The
AP fill guarantees nothing *required* is placed past the detour until both sets are
satisfiable, so the seed is always completable. The cost: a player *could*
physically go Sand→Wooded→Cloud and skip Lake in the moment (Lake stays revisitable),
so the in-game experience doesn't perfectly mirror the "both" rule even though the
logic does. For many use-cases this is acceptable and is the safe fallback.

**Approach B — true in-game combined gate. Effort: medium, ~70% confidence.**
Gate the departure that leaves the detour on **both** per-kingdom counts. The
building blocks already exist:
- **Per-kingdom collected counts** are readable — `ShineNumByWorldGetHook` already
  trampolines `getGotShineNum(world_id)`, and `ApState::ap_moons_kingdom[bit]`
  tracks AP credit per kingdom.
- **Per-kingdom thresholds** are already in `ApState::kingdom_gate[bit]` (the rolled
  values), the same source `UnlockShineNumHook` reads.
- **The chokepoint already exists**: extend `KingdomOrderGate`/`WorldMapSelectHook`
  with a rule "the transition into Cloud (and anything past the detour) is blocked
  until `count(Lake) >= gate(Lake) && count(Wooded) >= gate(Wooded)`." This is the
  same `OrderGateDecision` mechanism, just with a two-kingdom predicate instead of a
  visited-bit, applied to the Wooded→Cloud (and any Lake→onward) warp.

The wrinkles to nail down before building Approach B:
- **Cloud entry path: RESOLVED — it's the forced cutscene warp** (see Devon's
  clarifications above). Hook `tryChangeNextStageWithDemoWorldWarp` (the
  `tryChangeDemoWarpHook` / BACKSTOP seam already in
  [WorldMapSelectHook.cpp](../../switch-mod/src/hooks/WorldMapSelectHook.cpp)); when its
  target resolves to Cloud, apply the two-kingdom predicate. No disasm needed to find
  the seam.
- **Guard the warp, not just map visibility.** Because Cloud is story-forced rather
  than map-selected, the gate naturally belongs on that warp anyway — hold the
  cutscene/departure until both Lake's and Wooded's thresholds are met. (Whether a
  partial-skip is even reachable is now doubtful given the forced routing, but
  guarding the warp is the safe place regardless.)
- **Pick the count source consistently** with how the fuel gate measures (SMO's
  natural per-world shine count vs. AP credit) so the displayed/required numbers
  agree.

---

## Recommendation / first step (when pursued)

1. **Do Part 1 (logic) + Part 2 (remove the kRule) + Approach A first.** That's a
   small, safe diff that delivers free Lake/Wooded travel with a logic-correct
   "both" gate, and is independently shippable. Generate a seed and confirm the
   `{A} and {B}` requires parses and the fill is happy; play-test that Wooded is
   selectable after Sand.
2. **Then decide whether Approach B is worth it.** If the in-game skip-Lake hole
   bothers Devon, layer the two-kingdom predicate onto `KingdomOrderGate` at the
   confirmed Cloud-departure warp. Read the decomp/log which warp path enters Cloud
   before picking the hook seam (per CLAUDE.md's "read the decomp before picking a
   chokepoint" rule).

**Why ~80% overall:** the logic side is easy and well-supported; free travel is
almost certainly a one-rule deletion given the already-open frontier (with
`unlockWorld` as a proven fallback); and the only hard part (the in-game "both"
gate) reuses existing per-kingdom counts, existing rolled thresholds, and the
existing order-gate chokepoint — plus there's a guaranteed logic-only fallback that
can't fail. The points off are for the unverified map-frontier assumption and the
need to confirm Cloud's actual departure warp before wiring Approach B.

Sources consulted (all disk-truth reads this session):
[regions.json](../../apworld/smo_archipelago/data/regions.json),
[Rules.py](../../apworld/smo_archipelago/hooks/Rules.py),
[KingdomOrderGate.cpp](../../switch-mod/src/game/KingdomOrderGate.cpp)/`.hpp`,
[WorldMapSelectHook.cpp](../../switch-mod/src/hooks/WorldMapSelectHook.cpp),
[UnlockShineNumHook.cpp](../../switch-mod/src/hooks/UnlockShineNumHook.cpp),
[ShineNumByWorldGetHook.cpp](../../switch-mod/src/hooks/ShineNumByWorldGetHook.cpp),
[OdysseyRescue.cpp](../../switch-mod/src/game/OdysseyRescue.cpp)/`.hpp`,
[KingdomUnlock.hpp](../../switch-mod/src/game/KingdomUnlock.hpp); memory
[[kingdom-order-gate-premature-destinations]].
