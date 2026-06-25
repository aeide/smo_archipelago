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

**Status (2026-06-24): Part 1 (logic) + Part 2 (free-travel kRule removal) WRITTEN
in source, UNCOMMITTED, NOT YET BUILT/DEPLOYED/PLAY-TESTED. Approach A is the
implicit gate model so far; Approach B (true in-game "both" gate) NOT started.**
Original estimate ~80% feasible, medium effort. A near-guaranteed logic-only version
is low effort; the full in-game "both" gate is the medium-effort part, and it reuses
plumbing that already exists. See the **Implementation log** and **Handoff** sections
at the bottom for exactly what's done and what's next.

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

### Devon's clarification on the Metro-select → Cloud cutscene (2026-06-24)

**Load-bearing in-game behavior that MUST be preserved (Approach B / any switch-mod
gate near Cloud).** Devon: once both Lake and Wooded are complete and the player can
progress to Cloud, on the overworld map screen **the player is ACTUALLY selecting Metro
Kingdom** — *not* Cloud. A story cutscene then plays: Bowser interrupts the trip and the
player is rerouted into **Cloud** (pre-peace, Bowser fight). This is the same
"select-a-later-kingdom, story-reroutes-you" pattern as the later Moon→Lost→Metro-night
interrupt.

Implications:
- The map pick that leads to Cloud reads as **Metro**, so any in-game gate must NOT key
  on "player selected Cloud" — it must key on the **forced cutscene warp**
  (`tryChangeNextStageWithDemoWorldWarp` / `tryChangeDemoWarpHook` BACKSTOP), whose
  resolved target is the Cloud stage, OR on the Metro selection while both detour gates
  are unmet. Confirm the warp target resolves to Cloud at that seam before wiring.
- **Do not break the Metro-selection→Bowser-cutscene→Cloud flow** when adding the
  Approach B "both before Cloud" gate. The gate should *hold* the player in the detour
  until both thresholds are met, then let the existing Metro-select cutscene fire
  normally — not replace or reroute that cutscene.

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

---

## Implementation log — work done so far (2026-06-24)

All changes are **in the working tree, UNCOMMITTED**, and held out of the
2026-06-24 Jaxi/logic commit (`efdcebf`) at Devon's request ("nothing from the
new lake/wooded work just yet"). A `_lakewood_backups/` dir holds pre-edit copies.

### Done — Part 1 (apworld logic): `data/regions.json`

Rewrote the detour edges exactly as the Part-1 plan specifies. Current state on disk:

```
Sand   → Cap, Lake, Wooded     requires {KingdomMoons(Cascade,5)}   (added Wooded)
Lake   → (nothing)             requires {KingdomMoons(Sand,16)}      (connects_to [])
Wooded → Lost                  requires {KingdomMoons(Sand,16)}      (was Lake,8)
Lost   → Night Metro           requires {KingdomMoons(Lake,8)} and {KingdomMoons(Wooded,16)}
```

Both detour kingdoms now hang off Sand for the same Sand-16 cost; the onward `Lost`
edge requires **both** detour thresholds. This is the Approach-A logic model: the
fill guarantees nothing required lands past the detour until both moon sets are
satisfiable, so every seed stays completable regardless of in-game visit order.

- **NOT yet verified in a generate run.** The `{KingdomMoons(Lake,8)} and
  {KingdomMoons(Wooded,16)}` string-combine on the `Lost` edge is the one thing to
  confirm parses (each call returns a balanced `(... OR ...)` group, so joining with
  ` and ` *should* be valid — but verify, don't eyeball). See the Part-1 "Open check".
- ⚠ This change interacts with the **residual full+entrance_shuffle "No more spots"
  fill tightness** still open from the Jaxi session: adding the Wooded-off-Sand edge
  *widened* the early sphere and made that failure more frequent in testing. Keep the
  two issues mentally separate — the tightness predates this feature (reproduces at
  04aa685) — but expect this feature to stress it.

### Done — Part 2 (switch-mod free travel): `KingdomOrderGate.cpp`

Removed the `{"Wooded","Lake","LakeWorldHomeStage"}` entry from `kRules`, leaving
only `{"Seaside","Snow","SnowWorldHomeStage"}` (the second detour pair stays ordered).
Added a header comment documenting that Lake/Wooded is intentionally a free detour and
pointing back to this doc. With the rule gone, picking Wooded after Sand is no longer
rewritten to Lake.

- **NOT yet built or deployed.** A `KingdomOrderGate.cpp` edit changes nothing in-game
  until the subsdk9 binary is rebuilt and copied into Ryujinx's exefs (see CLAUDE.md
  "Switch-mod build & deploy"). This is the first task of the next session.
- This relies on the [[kingdom-order-gate-premature-destinations]] finding that the
  map frontier is **already open** and the BACKSTOP redirect was the only thing forcing
  order. If that assumption is wrong in-game (Wooded doesn't appear flyable after Sand),
  the proven fallback is the `unlockWorld(getWorldIndexForest())` force-reveal — see
  Part 2's safety nets.

### Done — Part 2 build + deploy + Part 1 generate verify (2026-06-24, later session)
- **Switch-mod built + deployed.** `build_switchmod.py "-DBRIDGE_HOST=192.168.4.100"`
  linked clean (97/97), BRIDGE_HOST baked as the full dotted IP (verified in CMakeCache),
  `subsdk9` + `main.npdm` copied into `%APPDATA%\Ryujinx\mods\contents\0100000000010000\exefs\`.
  Tables re-synced first (51 captures, 775 shine rows).
- **Generate verified Part 1 parses.** Rebuilt the zip (`install_apworld.py`) and ran
  `Generate.py` — succeeded ("Done. Enjoy."), so `{KingdomMoons(Lake,8)} and
  {KingdomMoons(Wooded,16)}` on the `Lost` edge parses and the fill is happy. This seed
  ran with entrance_shuffle on (119 subareas) with no "No more spots" — but that
  tightness is intermittent, so it's not a guarantee it's gone.

### NOT done
- **In-game verification** that after Sand BOTH Lake and Wooded are flyable in either
  order (Wooded no longer redirected to Lake) — Devon's manual play-test. If Wooded
  isn't offered, fall back to `unlockWorld(getWorldIndexForest())`.
- **Approach B** (true in-game "both before leaving the detour" gate) — not started.
  Approach A (logic-only) is the current model and is independently shippable.

---

## Handoff — next session (switch-mod: free Lake/Wooded travel after Sand)

**Devon's goal for next session (verbatim):** "start working on the switch mod to
make sure you can visit lake or wooded at any time after completing Sand, rather than
having to choose one to complete before moving on to the next."

That goal = Part 2 (free travel) verified in-game, then optionally Approach B (the
in-game "both" gate so you also can't *leave* the detour with only one done). Part 1
logic is already written and supports both.

### Step 0 — reground (do this first)
- Re-read this doc's **Tier 2** section and the [[kingdom-order-gate-premature-destinations]]
  memory — the whole plan hinges on "the map frontier is already open; the BACKSTOP
  redirect is what enforced order." Confirm that's still true in the current
  `WorldMapSelectHook.cpp` before relying on the one-rule-deletion being sufficient.
- The source edits (regions.json, KingdomOrderGate.cpp) are **already made and
  uncommitted**. Don't redo them — verify them against the Implementation log above,
  then build.

### Step 1 — build + deploy the switch-mod, verify free travel
1. Build + deploy per the CLAUDE.md "Switch-mod build & deploy" canonical PowerShell
   loop (sync tables → find LAN IP → `build_switchmod.py "-DBRIDGE_HOST=$LAN_IP"` →
   copy `subsdk9` + `main.npdm` into `%APPDATA%\Ryujinx\mods\contents\0100000000010000\exefs\`).
   Remember: **quote the `-DBRIDGE_HOST` arg** (PS 5.1 splits an unquoted dotted IP).
2. In-game: reach Sand, complete it (Sand-16 / story), and confirm the map now offers
   **both Lake and Wooded** as flyable destinations in **either** order — picking Wooded
   first is no longer redirected to Lake.
3. **If Wooded does NOT appear flyable after Sand:** the frontier assumption was wrong.
   Fall back to force-revealing it — call `unlockWorld(getWorldIndexForest())` (the
   primitive already used in [OdysseyRescue.cpp](../../switch-mod/src/game/OdysseyRescue.cpp))
   once Sand is left/peaced. Decide the trigger seam (Sand peace flag, or leaving Sand).

### Step 2 — generate + sanity-check Part 1 logic
- Rebuild the apworld zip (`install_apworld.py`) and run `Generate.py` to confirm the
  `Lost` edge's `{KingdomMoons(Lake,8)} and {KingdomMoons(Wooded,16)}` parses and the
  fill is happy. **Expect occasional "No more spots" failures under full+entrance_shuffle**
  — that's the *pre-existing* tightness, not this feature; run a few seeds and/or test
  with `entrance_shuffle:false` to isolate. If this feature makes it fail *every* time,
  that's a new signal worth chasing.

### Step 3 (optional) — Approach B: the true in-game "both" gate
Only if Devon wants the in-game experience to also block *leaving* the detour with one
kingdom unfinished (Approach A's logic already guarantees completability without it).
- **Confirmed chokepoint:** the forced cutscene warp into Cloud —
  `tryChangeNextStageWithDemoWorldWarp` (the `tryChangeDemoWarpHook`/BACKSTOP seam in
  [WorldMapSelectHook.cpp](../../switch-mod/src/hooks/WorldMapSelectHook.cpp)). Cloud is
  story-forced, entered via cutscene in its pre-peace state — NOT a free map pick (Devon
  confirmed 2026-06-20). So gate the warp, not map visibility.
- **Predicate:** `count(Lake) >= gate(Lake) && count(Wooded) >= gate(Wooded)`, using
  the per-kingdom counts (`ShineNumByWorldGetHook` / `ApState::ap_moons_kingdom[bit]`)
  and rolled thresholds (`ApState::kingdom_gate[bit]`) that already exist. Pick the
  count source consistently with how `UnlockShineNumHook` measures so displayed numbers
  agree.
- **Per CLAUDE.md:** read the decomp / log the actual warp target resolution before
  finalizing the hook — confirm the demo-warp target resolves to Cloud at that seam.

---

## Approach B — implementation log (2026-06-24, current session)

**Decisions taken this session (Devon):**
1. **Logic gate stays on Lost** (no `regions.json` change). Confirmed game-faithful:
   **Cloud has ONLY re-arrival moons** — like Cap, the first (Bowser-fight) arrival has
   *zero* AP checks, and **leaving Cloud activates its world peace** (Devon, 2026-06-24).
   All 11 Cloud AP locations are `{CloudPeace()}`-gated (re-arrival, `KingdomMoons(Lost,10)`).
   So the first kingdom with collectable moons after the detour is **Lost** (35 locs), and
   the current edit already gates all of Lost + everything onward on
   `{KingdomMoons(Lake,8)} and {KingdomMoons(Wooded,16)}`. Restructuring Cloud into the
   chain would gate its *re-arrival* moons (legitimately later) → less faithful. KEEP.
2. **Build Approach B now** — the true in-game "both before Cloud" gate.

**Research confirmed this session (all disk-truth / decomp reads):**
- **Chokepoint = `tryChangeNextStageWithDemoWorldWarp(writer, stage_name)`**, already hooked
  as `tryChangeDemoWarpHook` in [WorldMapSelectHook.cpp](../../switch-mod/src/hooks/WorldMapSelectHook.cpp).
  OdysseyDecomp: it's a thin wrapper — `writer->changeNextStageWithDemoWorldWarp(stage_name)`
  — so **substituting `stage_name` redirects the destination** (the exact mechanism the M7
  Path A Wooded→Lake BACKSTOP already uses + validated). Fork-cinematic warps route through
  this fn (M7 Path A proved it). In-game flow Devon confirmed: complete both → **select Metro**
  on the map → Bowser cutscene → **Cloud** (pre-peace). Gate the warp, not map visibility.
- **Kingdom table** ([KingdomUnlock.cpp](../../switch-mod/src/game/KingdomUnlock.cpp)):
  Lake=bit 4 (`LakeWorldHomeStage`), Wooded=bit 3 (`ForestWorldHomeStage`),
  Cloud=bit 5 (`CloudWorldHomeStage`). `kingdomShortFromHomeStage` maps stage→short name.
- **Count source = `ApState::ap_moons_kingdom[bit]`** (per-kingdom). It's the bridge-derived
  **outstanding** balance (`lifetime_received − PayShineNum`) in **effective-moon units**
  (Multi-Moon=3, Power-Moon=1 — [client/state.py:145](../../apworld/smo_archipelago/client/state.py),
  set from the `outstanding` wire msg in [ApClient.cpp:1002](../../switch-mod/src/ap/ApClient.cpp)).
  Chosen because it's the **same value the existing leave-gates use** (`getGotShineNum`
  override → `sumAllKingdomCredits` → `UnlockShineNumHook`), so displayed/required numbers
  agree. ⚠ **Known consideration:** outstanding is a *spendable* balance, so in theory it can
  drop below the threshold after the player deposits moons. The existing M7 Path A Snow gate
  accepts the same model and works (the warp fires at the leave moment, when outstanding is at
  its peak). If in-game testing shows the Cloud gate blocks spuriously because outstanding
  dropped, the fallback is to ship a per-kingdom **lifetime** count to the Switch (new wire
  field from `state.moons_received_by_kingdom`) and gate on that instead.
- **Threshold source = `ApState::kingdom_gate[bit]`** (rolled; `-1` ⇒ vanilla). Vanilla
  fallbacks: Lake=8, Wooded=16. `KingdomMoons` honors the same rolls, so logic + in-game agree.

**Design (the gate):**
- New `smoap::game::evaluateDetourCloudGate()` in
  [KingdomOrderGate.cpp](../../switch-mod/src/game/KingdomOrderGate.cpp)/`.hpp` returns
  `{blocked, redirect_stage, have/need diagnostics}`. `blocked = !(have(Lake)>=need(Lake) &&
  have(Wooded)>=need(Wooded))`. When blocked it redirects to the **unmet** kingdom's HomeStage
  (Lake first if both unmet) to hold the player in the detour. Fails OPEN on mis-config.
- In `tryChangeDemoWarpHook`: after the existing order-gate block, if the resolved destination
  kingdom is **Cloud**, apply `evaluateDetourCloudGate()` and substitute `final_stage` when
  blocked. Always logs the demo-warp stage + decision (discrete event, not per-frame) so
  Devon's test reveals the actual Cloud-entry stage string + the gate state.

**Implementation status (this session):**
- [x] `KingdomOrderGate.hpp` — added `DetourCloudGateDecision` + `evaluateDetourCloudGate()` decl
- [x] `KingdomOrderGate.cpp` — implemented the predicate (ap_moons_kingdom vs kingdom_gate,
      vanilla fallbacks 8/16, fails open, redirects to unmet kingdom HomeStage)
- [x] `WorldMapSelectHook.cpp` — wired the Cloud gate into `tryChangeDemoWarpHook` (re-resolves
      dest from final_stage post-order-gate) + per-warp `[wmap.tryChange.Demo]` logging (+`<cstring>`)
- [x] Build + deploy switch-mod (2026-06-24, 97/97 link clean, subsdk9 525138→525466 bytes,
      copied to `%APPDATA%\Ryujinx\mods\...\exefs\`, BRIDGE_HOST=192.168.4.100 baked)
- [ ] **In-game (Devon) — NOT yet tested:** complete both Lake+Wooded → confirm Cloud cutscene
      fires & passes (look for `DETOUR-GATE pass to Cloud`); try reaching Cloud with only one
      done → confirm held in detour (`DETOUR-GATE holding out of Cloud ... -> 'LakeWorldHomeStage'`).
      **Capture the `[wmap.tryChange.Demo] warp stage=...` lines** — they reveal the REAL
      Cloud-entry stage string. If the Cloud entry does NOT log through this seam at all, the
      cutscene warp uses a different chokepoint and we re-target (next candidate: hook the
      lower-level `GameDataHolderWriter::changeNextStageWithDemoWorldWarp` directly).

**Resumption note:** if a session ends mid-way, the checkboxes above are the state of truth.
The logic edits (regions.json, KingdomOrderGate kRule removal) are DONE + built + deployed +
generate-verified from the earlier session; Approach B is purely additive switch-mod code.

---

## Playtest log analysis + free-crossing build (2026-06-25, current session)

Devon ran Sand → Lake → Wooded → Cloud (collecting each kingdom's leave-moons via the
cheat console) and attached the Ryujinx log. Two findings:

### Finding 1 — Approach B's Cloud gate NEVER FIRED (wrong seam, proven by the log)

The Wooded→Cloud transition logged:
```
[wmap.tryChange.Demo] warp stage='CityWorldHomeStage' (kingdom=Metro)
[entrance:file]       stage='CloudWorldHomeStage' id='' isReturn=0 scenario=-1 cur='ForestWorldHomeStage'
[pump] arrival status kingdom=Cloud stage=CloudWorldHomeStage
```
At the `tryChangeDemoWarpHook` seam the warp target is **Metro (`CityWorldHomeStage`)**, NOT
Cloud — exactly the "select Metro → Bowser cutscene → Cloud" reroute. So the `dest=="Cloud"`
branch in [WorldMapSelectHook.cpp](../../switch-mod/src/hooks/WorldMapSelectHook.cpp) never runs;
there is **not a single `DETOUR-GATE` line in the entire log**. The real Cloud destination only
appears one seam later, at **`GameDataFile::changeNextStage`** (the `[entrance:file]` logger in
[EntranceShuffleHook.cpp](../../switch-mod/src/hooks/EntranceShuffleHook.cpp)). That is the
contingency the doc anticipated ("if Cloud does NOT log through this seam … re-target the
lower-level commit"). **Approach B must move to the `:file`/`changeNextStage` seam.** The
"can't choose Cloud after only Lake / goes to Cloud after both" behavior Devon observed was NOT
Approach B — it was the natural fuel gate + story flow (the run completed both kingdoms, so the
gate was never exercised).

### Finding 2 — "free bridge on arrival" was blocked by the moon-FUEL gate, not order

Decomp (`GameDataFunction.cpp`): `isUnlockedNextWorld = is_game_clear || getPayShineNum >=
findUnlockShineNum(...)` (the **current-world** variant). The connecting cutscene is the
demo-world-warp, available only once that launch check passes. Log confirmed live fuel gates
(`findUnlockShineNumByWorldId: Lake rolled=13, Wooded rolled=14`). Devon chose **truly free
crossing**: arrive Lake/Wooded → board at 0 moons → cutscene fires → fly to sibling.

### Done this session — free crossing (BUILT + DEPLOYED, awaiting Devon's in-game test)
- [UnlockShineNumHook.cpp](../../switch-mod/src/hooks/UnlockShineNumHook.cpp): new
  `isFreeDetourBit(bit)` (Lake or Wooded). **Both** `findUnlockShineNum` and
  `findUnlockShineNumByWorldId` now return **0** for those two kingdoms → Odyssey launchable
  at 0 moons → connecting cutscene opens on arrival. Logs as `findUnlockShineNum[free-detour]`.
  The rolled `kingdom_gate[]` thresholds (read by `evaluateDetourCloudGate`) are untouched.
- Built 97/97 clean, `subsdk9` 525981 bytes, deployed to `%APPDATA%\Ryujinx\…\exefs\`,
  BRIDGE_HOST=192.168.4.100.
- ⚠ **Knowing trade-off:** zeroing the fuel removes the gate that *incidentally* enforced
  "finish the detour before Cloud." The combined Cloud gate (Finding 1) is still mis-wired, so
  this build does NOT block premature progression. That is intentional for this iteration — the
  test below tells us whether premature Cloud is even reachable and, if so, the exact seam.

### Devon's test for the next iteration
1. **Free crossing:** arrive Lake (or Wooded) at the Sand fork, collect 0 moons, board the
   Odyssey → confirm the connecting cutscene fires and you can fly to the sibling. Expect
   `findUnlockShineNum[free-detour]: kingdom=Lake(bit=4) … -> rolled=0`.
2. **Cloud regression watch (capture logs):** from a detour kingdom with only one (or neither)
   kingdom's moons, try to progress past the detour (board → the normal Metro-select flow).
   Capture ALL `[wmap.tryChange.Demo] warp stage=…` and `[entrance:file] stage=…` lines. We
   need: (a) is premature Cloud reachable now that fuel is free? (b) the exact stage string +
   seam where Cloud commits → this is where Approach B's combined gate gets re-wired next.

### Iteration 2 result + Cloud-gate fix (2026-06-25, same session)

Devon's test of the free-crossing build:
1. **Free crossing WORKS** — collected 0/7 Lake, boarded → connecting cutscene played → crossed to
   Wooded freely. Log: `findUnlockShineNumByWorldId[free-detour]: kingdom=Lake(bit=4) vanilla=8 ->
   rolled=0` then `kingdom=Wooded(bit=3) vanilla=16 -> rolled=0`. ✅ exactly as intended.
2. **Premature exit reachable (expected regression)** — from Wooded at 0/18, the "Metro" (→Cloud)
   cutscene played and let him leave the detour. ❌ needs the combined gate.

**Decision: gate at the demo-warp seam keyed on METRO, not the `:file` seam.** Reasoning: the
detour-exit demo-warp target reads as `Metro`/`CityWorldHomeStage` (the Bowser swap to Cloud is
downstream at `:file`). Redirecting the demo-warp arg is the *proven* M7 Path A mechanism
(Seaside→Snow), and substituting the target to a detour HomeStage before the Metro selection
commits should stop the Bowser→Cloud reroute from arming at all — cleaner than a mid-cutscene
`:file` rewrite. The `:file` re-wire stays the fallback if this doesn't hold.

**Done (BUILT + DEPLOYED, subsdk9 526287, awaiting Devon test):** rewired the Approach B gate in
[WorldMapSelectHook.cpp](../../switch-mod/src/hooks/WorldMapSelectHook.cpp) `tryChangeDemoWarpHook`:
- Now fires when `dest ∈ {Metro, Cloud}` (was Cloud-only) AND the warp ORIGINATES from a detour
  kingdom (`currentKingdomBit()` ∈ {Lake, Wooded}) — new `currentKingdomBit()`/`isDetourKingdomBit()`
  helpers. The cur-in-detour guard keeps legitimate post-detour Metro trips from being blocked
  (and is the backstop for the known `ap_moons_kingdom` outstanding-can-drop concern).
- Blocked → substitute `final_stage` to the unmet kingdom HomeStage (`evaluateDetourCloudGate`,
  Lake first if both unmet). Logs `[wmap.tryChange.Demo] DETOUR-GATE holding/pass (dest=...)`.

**Devon test next:**
1. Re-confirm free crossing still works (Lake↔Wooded at 0 moons).
2. From Wooded at <both thresholds, board → select Metro → expect to be **held in the detour**
   (flown back to Lake), log `DETOUR-GATE holding in detour (dest=Metro) ... -> 'LakeWorldHomeStage'`.
3. Collect both kingdoms' thresholds → board → select Metro → expect **pass to Cloud**, log
   `DETOUR-GATE pass (dest=Metro)`, Bowser cutscene → Cloud as normal.
4. If step 2 still leaks to Cloud (the Bowser reroute arms independently of the demo-warp arg),
   fall back to the `:file`/`changeNextStage` seam: gate in `fileChangeNextStageHook` after
   `processEntranceRemap`, rewriting `mChangeStageName`/`mChangeStageId` to the unmet HomeStage
   (Cloud's `:file` info had an EMPTY entrance id → empty-id HomeStage redirect is the candidate).

### Iteration 3 — gate moved to `:file` seam + display restored (2026-06-25, same session)

Iteration 2 test: **free crossing still works**; **demo-warp Metro gate did NOT hold** (still
reached Cloud at 0/0). Confirms the Bowser→Cloud reroute regenerates the target downstream of the
demo-warp arg. Devon also asked: keep the **real required counts on the Odyssey map** (7 Lake / 18
Wooded) while crossing stays free.

Two fixes (BUILT + DEPLOYED, subsdk9 526262, awaiting test):
- **Gate moved to the `:file` commit.** Removed the demo-warp Approach B block (+ helpers) from
  [WorldMapSelectHook.cpp](../../switch-mod/src/hooks/WorldMapSelectHook.cpp). New
  `processDetourCloudGate()` in [EntranceShuffleHook.cpp](../../switch-mod/src/hooks/EntranceShuffleHook.cpp),
  called in `fileChangeNextStageHook` after `processEntranceRemap`: when dest kingdom resolves to
  **Cloud** AND cur kingdom is Lake/Wooded AND `evaluateDetourCloudGate()` is blocked, rewrite
  `mChangeStageName` to the unmet HomeStage + empty `mChangeStageId` (same bounded in-place mutation
  entrance-shuffle uses). Logs `[entrance:detour-gate] HOLDING/pass`.
- **Display restored.** Reverted the by-world free-detour zeroing in
  [UnlockShineNumHook.cpp](../../switch-mod/src/hooks/UnlockShineNumHook.cpp) — `findUnlockShineNumByWorldId`
  returns the rolled value again (map shows 7/18). Decomp-confirmed safe: selectability is
  `GameDataFile::isUnlockedWorld(world_id)` (doesn't read it) and the launch check uses only the
  **current-world** `findUnlockShineNum`, which stays forced to 0 → crossing still free.

**Devon test:** (1) free crossing still OK + map now shows 7/18; (2) from Wooded <both, board →
select Metro → held back to Lake, log `[entrance:detour-gate] HOLDING out of Cloud (cur=Wooded)`;
(3) both met → Metro → `[entrance:detour-gate] pass to Cloud` → Bowser/Cloud as normal. Watch for
any visual glitch from the mid-cutscene `:file` redirect (cutscene may fly toward Metro then land
at Lake) — if jarring, re-add the demo-warp Metro redirect purely for the fly animation while
`:file` stays the authoritative load gate.

### Iteration 4 — `:file` gate WORKS; fixed gate counting deposited moons as 0 (2026-06-25)

Iteration 3 test: free crossing OK; the `:file` redirect held cleanly (Devon: "looked clean,
arrived back in Lake"); held correctly with one/zero kingdoms done. **But the gate blocked even
with BOTH thresholds met** — it read `ap_moons_kingdom` (OUTSTANDING = lifetime − deposited), and
the player had **deposited** 7 Lake + 18 Wooded into the Odyssey (required to progress), dropping
outstanding to 0. Log: `HOLDING out of Cloud (cur=Wooded): Lake 0/7 Wooded 0/18` right after
`addPayShine count=18`. Exactly the documented "outstanding can drop after deposits" fallback case.

**Fix (BUILT + DEPLOYED, subsdk9 526106):** `collectedEffectiveMoons()` in
[KingdomOrderGate.cpp](../../switch-mod/src/game/KingdomOrderGate.cpp) now returns
**lifetime = outstanding + deposited**. New `depositedEffectiveMoons(bit)` reads the by-world
`getPayShineNum` already resolved into `ApState::get_pay_shine_num_fn` (the M6 PaySnapshot path) —
reads the save, so it survives reloads and isn't depleted by paying the Odyssey. The bridge defines
`outstanding = lifetime − PayShineNum`, so the sum reconstructs lifetime-received, matching
`KingdomMoons()` (counts received, not deposited). A just-deposited frame may transiently over-count
(harmless for a `>=` gate, never falsely blocks). Side effect: a player who has *received* both
thresholds passes even before depositing — consistent with the apworld logic (received, not deposited).

**Devon test:** collect both thresholds → board → select Metro → should now `DETOUR-GATE pass` →
Bowser → Cloud.

**Still open (lowest priority, cosmetic):** the in-kingdom Odyssey takeoff prompt shows "0 / full on
moons" because the **current-world** `findUnlockShineNum` is forced to 0 for the free launch — the
takeoff *check* and *display* read the same function, so it can't show 7/18 there while staying free
to launch. The per-kingdom **globe** display does show the real 7/18, and the tracker is correct.
Accepted as-is.

### Commit guidance
This work is being kept on its own and out of the logic commits. When ready, commit the
free-detour feature as its own change set: `regions.json` + `KingdomOrderGate.{cpp,hpp}` +
`EntranceShuffleHook.cpp` + `UnlockShineNumHook.cpp` + `WorldMapSelectHook.cpp` +
the `Rules.py` docstring touch-up. No Nintendo IP is involved in these files.
`_lakewood_backups/` is a scratch dir — delete it (don't commit) once the feature is settled.

---

## Mirror to the 2nd fork — Snow/Seaside → Luncheon (2026-06-25)

Lake/Wooded → Cloud was **confirmed in-game** (Devon: collected both thresholds → boarded →
reached Cloud). Devon then asked to mirror the whole mechanic to SMO's other world-map fork:
after Metro the Odyssey can go to **Snow** or **Seaside** (both 10 moons in vanilla), and after
completing **both** it reaches **Luncheon**. **Key difference:** Luncheon is reached *directly* —
there is **no Bowser intercept** rerouting the destination, so the exit stage resolves to
`LavaWorldHomeStage` at the `:file` `changeNextStage` seam (not Metro like the Cloud case).

### What changed (generalized, not copy-pasted)

The implementation was refactored to a **table-driven** form so both pairs share one code path:

- **`KingdomOrderGate.{hpp,cpp}`** — `DetourCloudGateDecision` / `evaluateDetourCloudGate()`
  became generic `DetourExitGateDecision` / `evaluateDetourExitGate(const char* exit_short)`,
  driven by `kDetourPairs[]`:
  - `{"Cloud",    Lake/LakeWorldHomeStage/8,    Wooded/ForestWorldHomeStage/16}`
  - `{"Luncheon", Snow/SnowWorldHomeStage/10,   Seaside/SeaWorldHomeStage/10}`

  Returns `exit_kingdom == nullptr` (fail-open) when `exit_short` isn't a known exit — that
  doubles as the "is this a detour exit?" test. The redirect picks sibling `a` first when both
  are unmet. Lifetime-moon counting (`outstanding + deposited`, the iteration-4 fix) is unchanged
  and shared. The old `kVanillaLake/WoodedGate` constants are gone (folded into the table).

  The strict-order `kRules` table lost its last entry (`{"Seaside","Snow",...}`) — Snow/Seaside
  is now free either-order, just like Lake/Wooded. `kRules` keeps one inert `{nullptr,...}`
  sentinel (the loop skips it) to avoid a zero-size-array and to leave the seam for any future
  strict-order fork.

- **`EntranceShuffleHook.cpp`** — `processDetourCloudGate` → `processDetourExitGate`: reads the
  `:file` commit's dest kingdom, calls `evaluateDetourExitGate(dest)`, and gates only when the
  *current* stage is one of that pair's two siblings. Works unchanged for both Cloud (Bowser
  reroute resolves to Cloud here) and Luncheon (direct). Logs now use `%s` for the exit + siblings.

- **`UnlockShineNumHook.cpp`** — `isFreeDetourBit` extended to **Snow + Seaside** so all four
  detour kingdoms launch the Odyssey at 0 moons (free crossing). The **by-world** display variant
  is still left at the rolled value, so the globe shows the real Snow/Seaside thresholds.

- **`regions.json` (logic, Part-1 mirror)** — `Metro` now connects to **both** Snow and Seaside;
  `Snow` is a dead-end branch (like Lake, `connects_to: []`); `Seaside.requires` is `Metro,20`
  (was `Snow,10` — it's now entered directly from Metro, like Wooded off Sand); and the combined
  exit gate sits on `Luncheon.requires = {KingdomMoons(Snow,10)} and {KingdomMoons(Seaside,10)}`
  (was `Seaside,10`). The "Very Early Luncheon" intermediate region is untouched. The
  `KingdomMoons` docstring in `Rules.py` was updated (the chain is no longer purely linear).
  Peace predicates (`SeasidePeace`/`LuncheonPeace`, which are `canReachLocation` calls) follow the
  region graph automatically — no edits needed.

### Verification
- **Build:** `[97/97] Linking` clean; `subsdk9` 526396 bytes, `BRIDGE_HOST=192.168.4.100` baked;
  deployed to `%APPDATA%\Ryujinx\mods\contents\0100000000010000\exefs\`.
- **Generate:** `Done. Enjoy.` (exit 0) with **entrance_shuffle ON** and a tight rolled-gate seed
  (Snow=10, Seaside=7, Luncheon=22) — the free-detour edges + combined Luncheon gate parsed and
  filled without `FillError`.

### Devon in-game test (Snow/Seaside)
1. Complete Metro, arrive at Snow (or Seaside) — board the Odyssey at **0 moons**; the onward
   flight to the sibling should be available (free crossing). Repeat the other direction.
2. With only **one** sibling's threshold met, board → select Luncheon → expect
   `[entrance:detour-gate] HOLDING out of Luncheon ... -> '<unmet sibling> HomeStage'` (redirected
   back into the detour).
3. With **both** Snow-10 and Seaside-10 collected, board → select Luncheon → expect
   `[entrance:detour-gate] pass to Luncheon` → arrive in Luncheon.

Same accepted cosmetic caveat as Lake/Wooded: the in-kingdom takeoff prompt reads "0 / full on
moons" for the free-launch kingdoms; the globe shows the real counts.

**CONFIRMED IN-GAME (Devon, 2026-06-25, after iteration 5 below):** Snow→Seaside at 0 moons
works; Seaside→Luncheon at 0 moons is held back to Snow (combined gate holds with one sibling
unfinished); and with full Snow+Seaside moons, boarding at Snow → Luncheon passes **without
redepositing at Seaside** — i.e. the iteration-4 lifetime counting (`outstanding + deposited`,
counts received not deposited) is correct. **The Snow/Seaside fork is DONE.** Both detour pairs
(Lake/Wooded → Cloud and Snow/Seaside → Luncheon) are now confirmed end-to-end.

### Iteration 5 — `isUnlockedNextWorld` display-split REVERTED; free crossing restored (2026-06-25)

**Symptom (Devon, Snow/Seaside test from a Cloud save):** at Snow with 0 moons the Odyssey
said "needs 10 more" and Seaside was unreachable — i.e. **free crossing was BROKEN.**

**Root cause — a regression introduced by a display-split experiment that does not work.**
Between iteration 4 and this test, `UnlockShineNumHook.cpp` was changed to *stop* zeroing the
current-world `findUnlockShineNum` (to make the in-kingdom takeoff gauge show the real rolled
count) and instead force `GameDataFunction::isUnlockedNextWorld` **true** for the four
free-detour bits, on the theory that `isUnlockedNextWorld` is the takeoff gate. The 2026-06-25
log disproves that theory: **not a single `[free-detour] isUnlockedNextWorld FORCED true` line
ever fired**, even though the hook installed (`00:00:12.170`). `isUnlockedNextWorld` is **not**
the predicate consulted at the in-kingdom Odyssey takeoff seam (classic inlined/wrong-seam
trap — and it directly contradicts iteration 4's Devon-confirmed finding that *"the takeoff
check and display read the same function,"* i.e. current-world `findUnlockShineNum`). So
reverting the zeroing simply re-armed the leave-gate at the rolled threshold with nothing to
open it. Same code path → **Lake/Wooded crossing was broken too** by this change.

**The hard constraint (why the display-split can't work at this layer).** The in-kingdom
takeoff "needs N more" number **is** the gate: it is `required − collected`, the exact deficit
the gate tests (`getPayShineNum(cur) >= findUnlockShineNum(cur)`). Any lever that opens the
gate (lower `findUnlockShineNum` or raise `getPayShineNum`) mathematically zeroes that number;
moreover, once the gate is open SMO does not show "needs N more" at all — that message only
renders while *blocked*. So you cannot show "10" on the in-kingdom takeoff prompt while leaving
at 0. The real per-kingdom "10" that survives a free crossing is the **world-map globe label**
(the by-world `findUnlockShineNumByWorldId` variant), which already shows the true rolled value.

**Fix (in source, awaiting build+deploy):** restored the iteration-4 lever in
[UnlockShineNumHook.cpp](../../switch-mod/src/hooks/UnlockShineNumHook.cpp) — `unlockShineNumHook`
(current-world) returns **0** for free-detour bits again (`findUnlockShineNum[free-detour]` log),
so takeoff is free at 0 moons. The by-world variant stays at the rolled value (globe shows real
10/10). The dead `isUnlockedNextWorldHook` experiment (hook + `installIsUnlockedNextWorldHook`
in main.cpp + the symbol in `SmoApSymbols.sym`) was **removed during pre-commit cleanup** — the
proven lever is the current-world zero, and forcing `isUnlockedNextWorld` true risked side
effects on its other (unknown) consumers for no benefit. Devon's call: **globe label is enough**
— the in-kingdom takeoff gauge reading 0/"full" is the accepted cosmetic, same as before.

### Follow-up (deferred, low priority) — force the in-kingdom takeoff text to show the real count

If the 0/"full" in-kingdom takeoff gauge ever bothers anyone, the only way to show the real
rolled threshold there *while keeping the crossing free* is to **decouple the displayed text
from the gate** — i.e. hook the takeoff "needs N more" / required-count **message string** (the
same technique as `ShopItemMessageHook` / `CappyMessenger`'s text-lookup trampolines) and inject
the rolled value as display-only, while the gate stays forced open via the current-world zero.
Effort: needs symbol discovery for that specific UI message path (not yet located), and the UX
is mildly contradictory ("needs 10 more" on a prompt that then lets you leave). Not worth it for
the cosmetic; recorded here so a future session doesn't re-derive the `isUnlockedNextWorld`
dead end. The globe already shows the true counts, which is the load-bearing display.
