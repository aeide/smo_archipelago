# P7 — Entrance shuffle: pre-design spike

Opus pre-design investigation for P7 (the entrance-shuffle headline feature). Read
[plan-v2-vision.md](plan-v2-vision.md) §P7 first; this doc is the spike output it calls for
("Pre-design Opus spike — investigate first"). Status: **investigation only — no code written.**
Authored 2026-06-18.

---

## 1. Data validation (entrance_exclusions.json ↔ subareas.json)

Devon authored [data/entrance_exclusions.json](../apworld/smo_archipelago/data/entrance_exclusions.json)
(now strict JSON; the authoring notes moved to `entrance_exclusions.md`). Cross-checked against
`data/subareas.json` (131 subareas):

- **Exclusion entries:** 19 listed, 18 unique. `Inside New Donk City Tower` appears twice (once
  under `Night Metro`, once under `Metro Kingdom`) — harmless, dedupes to one subarea name.
- **16 match a subareas.json key; 3 don't:** `Inside Top-Hat Tower` (Cap), `New Donk City Hall
  Auditorium` (Metro), `A Traditional Festival!` (Metro). These are correctly empty `{}` — they
  aren't in subareas.json at all (no AP locations), so excluding them is a defensive no-op. Fine
  to keep.
- **Shuffle pool = 85 subareas** = 100 subareas-with-≥1-AP-location − 15 excluded-that-have-locations.
  (subareas.json: 100 have AP locations, 31 have none.)

### 1a. `csv_names` vs `location_names`, and "location-less" subareas (VERIFIED)
- `csv_names` = every moon physically in the subarea, named as in the source requirements
  spreadsheet (subarea-prefixed).
- `location_names` = the subset that are **AP checks in THIS apworld** (kingdom-prefixed
  naming). The apworld's location pool is the curated upstream set (545 names incl. events), not
  every SMO moon.
- A **location-less subarea** (`location_names: []`, 31 of them) = a real SMO subarea whose moons
  simply aren't in the curated AP pool — e.g. `Precision Rolling` (Cap), `Mysterious Clouds`
  (Cascade), `Gusty Bridges`, `Colossal Ruins`, `Invisible Road`, `Herding Sheep`.
  **Verified not a bug:** 0 of the 31 empties' csv moons match any real AP location by suffix, so
  the empties are genuinely non-AP-check subareas, not a name-matching failure.

Pool-scope decision: **(B) shuffle ALL physical doors — Devon, 2026-06-18.** The 31 empties are
the **moon-pipe / post-peace** subareas; their moons must first be added as AP locations (see §6),
so this pulls a data phase IN FRONT of P7. After §6 the pool grows from 85 toward ~115.

### 1b-bis. Conflated subareas — subareas.json MERGES same-named rooms across kingdoms
The importer split most repeated subareas by kingdom suffix (`Crazy Cap Store (Lake)`, `(Metro)`,
…). But **two entries still merge multiple physical instances** because their moons live under
different kingdom prefixes inside one CSV block:
- **`Costume Room`** → moons in Sand + Wooded + Seaside ⇒ **3 physical costume rooms** merged.
- **`Sphynx Treasure Vault`** → moons in Sand + Seaside ⇒ **2 physical vaults** merged.

For entrance shuffle each **physical door instance must be its own node**, so these two entries
must be split per-kingdom before P7 logic (fix in `import_moon_requirements.py` / source xlsx, not
by hand-patching the regenerated json). All other pool subareas are already 1 instance = 1 entry.
(`Picture Match (Goomba)` Lake→Cloud and `Picture Match (Mario)` Mushroom are distinct single
instances — both shuffle, no split needed.)

### 1b. Cross-kingdom subareas in the pool (3) — door-kingdom ≠ moon-kingdom
| Subarea | Door is in | Holds moons of | Note |
|---|---|---|---|
| Costume Room | Sand | Sand + Wooded + Seaside | mixed |
| Sphynx Treasure Vault | Sand | Sand + Seaside | mixed |
| Picture Match (Goomba) | Lake | Cloud | single foreign |

For reachability the **door's kingdom gates the subarea** (matches the P6 carry-over note). A P5
recolor keyed on *physical* kingdom would disagree with this grouping — already flagged in P5.

### 1c. Data bug to fix upstream (not blocking P7)
`subareas.json` mis-tags two subareas' `kingdom` field: **`Shiveria Town`** and **`Class A
Race`** are labelled `Seaside Kingdom` but their moons are `Snow:` — they're Snow Kingdom
content. Both are *excluded* from the shuffle, so the pool is unaffected, but the bug is in
`scripts/import_moon_requirements.py`'s kingdom inference (the json is regenerated, so don't
hand-patch the json — fix the importer or the xlsx). If reachability ever keys a door's gating
kingdom off this field, these would gate on the wrong kingdom. (`Picture Match (Goomba)` =
Lake-door/Cloud-moon is **not** a bug — genuine cross-kingdom.)

---

## 2. Hook architecture — the chokepoint is found and viable

### 2a. Chokepoint
Subarea entry/exit funnels through **`GameDataFunction::tryChangeNextStage(GameDataHolderWriter,
const ChangeStageInfo*)`** (OdysseyDecomp `src/System/GameDataFunction.h`). This is distinct
from the two kingdom-map-warp variants we already hook
(`tryChangeNextStageWithDemoWorldWarp` / `…WithWorldWarpHole`, both `(…, const char*)`) — those
handle the overworld→overworld Odyssey flight; the `ChangeStageInfo*` form is the
door/pipe/painting path. MoonRockHook's header already documents the rock-open reload using this
same call, confirming it's the generic transition path.

### 2b. `ChangeStageInfo` carries everything we need (one hook does entry AND exit)
OdysseyDecomp `src/MapObj/ChangeStageInfo.h`, global namespace, 0x278 bytes:
```
sead::FixedSafeString<0x80> mChangeStageId    // entrance / spawn placement id
sead::FixedSafeString<0x80> mChangeStageName  // destination stage name
sead::FixedSafeString<0x80> mPlacementString
bool                         mIsReturn         // <-- entry vs exit, at the SAME hook
s32                          mScenarioNo
SubScenarioType              mSubScenarioType
sead::FixedSafeString<0x80> mWipeType
s32                          mHintPriority
```
`mIsReturn` is the key find: one trampoline distinguishes **entry** (`!mIsReturn` — remap dest)
from **exit** (`mIsReturn` — override return to the recorded origin door). Remap must copy the
whole *target subarea's* ChangeStageInfo shape (stage **+** entrance **+** scenario **+**
placement), not just the stage name, so cross-kingdom/scenario destinations load consistently
(see §3a).

### 2c. Symbol — needs discovery (not yet in our DB)
Our DB has only the two WorldWarp variants. Candidate mangling for the door chokepoint:
```
_ZN16GameDataFunction18tryChangeNextStageE20GameDataHolderWriterPK15ChangeStageInfo
```
(`20GameDataHolderWriter` by-value matches the existing two syms; `PK15ChangeStageInfo` =
`const ChangeStageInfo*`.) **Verify via the smo-symbol-discovery skill** (sail .sym +
fakesymbols.so / llvm-nm) before relying on it.

### 2d. FIRST build step is a read-only logger, not the remap
Per the "a HIT symbol ≠ the decision flows through it / read the decomp before a chokepoint"
invariant: the definitive coverage test is to install `tryChangeNextStage` as a **pure logging
trampoline** (dump `mChangeStageName`, `mChangeStageId`, `mIsReturn`, `mScenarioNo` and the
current stage), then walk through every subarea-entry door **type** in-game — pipe, door,
painting/picture-match, treasure-vault, hat-door, race-lobby — and confirm each appears. Only
after the log proves coverage do we add remap logic. (Visual door actors like `DoorCity` do
*not* trigger the change themselves — they react to a stage-switch — so the trigger is a
separate collision object; logging at the chokepoint sidesteps having to enumerate every trigger
actor in the decomp.) This is one cheap build to de-risk the whole feature.

---

## 3. Risk investigations (the four §P7 spike items)

### 3a. Cross-kingdom subarea loads (scenario / time-of-day) — MANAGEABLE
The 3 cross-kingdom subareas (§1b) plus Metro's day/night split (the exclusions separate `Night
Metro`) mean a destination can carry a specific scenario/time-of-day. Because `ChangeStageInfo`
already encodes `mScenarioNo`/`mSubScenarioType`/stage, **remapping by copying the target's full
ChangeStageInfo** loads the target in its own correct state — we are not synthesizing state, just
substituting one game-authored transition tuple for another. The residual risk is a remapped
door whose *origin* scenario differs from what the target subarea's interior assumes; mitigate by
keying the bijection on the door's kingdom/region reachability (already the plan) and by
excluding the obviously scenario-bound rooms (Devon's list already excludes the story interiors).

### 3b. Multi-moon / story subareas — COVERED BY EXCLUSIONS
The story interiors and boss arenas that would strand scenario progression are already in the
exclusion list (Inverted Pyramid, Underground Caverns + Wedding Room in Moon, Peach's Castle,
Deepest Underground, etc.). Multi-Moon locations aren't in the 435 ability-mapped universe
anyway. No additional action beyond honoring the exclusions.

### 3c. Checkpoint / save-load — THE realintegration cost
Entering a subarea updates the game's "current stage / return entrance" in save data, so
save+quit inside a subarea resumes there and a vanilla exit would route to the subarea's
*original* parent door — not the door the shuffle sent Mario through. So the **recorded origin
(the door entered) must persist across save-load**, surfaced via `SaveLoadHook`. This is the
single most fiddly part of P7 and should be designed before the remap (mirror how
KingdomOrderGate's `visited` mask is deliberately *not* repopulated by save load).

### 3d. Talkatoo% / moon-rock interactions — ONE GUARD REQUIRED
- **Moon-rock reload uses the same `tryChangeNextStage(ChangeStageInfo*)` chokepoint.** Our
  entrance hook MUST NOT remap it. Distinguish: a moon-rock reload is a **same-stage scenario
  jump** (`mChangeStageName == getCurrentStageName()` with a scenario change), whereas a subarea
  door changes to a *different* stage. Guard the remap on "destination stage ≠ current stage AND
  (stage,entrance) ∈ shuffle table." MoonRockHook stays untouched.
- **Talkatoo%** gates *moon collection* (MoonGetHook), orthogonal to stage change — no hook
  conflict. The only coupling is logical: if a named/required moon lives in a shuffled subarea,
  its reachability now flows through the assigned door. That's handled by the apworld
  reachability sweep, not the Switch.

---

## 4. Recommended build order (when P7 starts)

1. **apworld reachability + fill** (Sonnet-able): build the door→subarea bijection over the 85
   pool (or all-doors per §1a), gate each subarea on `door-kingdom reachable AND subarea interior
   requirements` (reuse the P6 `SUBAREA_GATES` data + the kingdom-gates reachability guard).
   Resolve the P6 carry-over: attach **entrance** requirements to the door, **interior**
   requirements to the moon (see plan §P7-carryover items 1–2 — Narrow Valley is the test case).
2. **wire msg** `entrance_map` (additive, fixed-size table — respect committed buffer patterns)
   slot_data → `ApState`.
3. **switch-mod, phase 1 (read-only):** verify the chokepoint symbol (smo-symbol-discovery),
   install `tryChangeNextStage` as a pure logger, in-game door-type coverage walk (§2d).
4. **switch-mod, phase 2 (remap):** entry remap (copy target ChangeStageInfo) + record origin;
   exit override to origin; moon-rock same-stage guard (§3d); SaveLoadHook origin persistence
   (§3c).

## 6. PREREQUISITE data phase — add the moon-pipe moons (P6.5, before P7) ✅ COMPLETE (2026-06-18)

Devon (2026-06-18): the 31 location-less subareas are gated behind **moon pipes that open after
the kingdom's moon rock is opened (= world peace)**. The Switch side already does the gating
(`MoonRockHook` opens rocks post-kingdom-peace), but these moons were **never added as AP
locations** (CLAUDE.md: "Moon-rock moons are NOT yet AP locations (phase 2)"). For pool-scope (B)
to be meaningful, that phase must happen first:

- **~60 new AP locations** across 30 subareas (2 each, except `Crazy Cap Store (Moon)` and
  `Moon Kingdom Treasure Vault` at 1 — and those two are shop/vault moons, NOT moon-pipe content,
  handle separately or leave as the existing shop pattern). Add to `data/locations.json`.
- **Names:** source from the upstream manual-AP lineage / Devon's `SMO Requirements.xlsx`
  `csv_names` (safe to commit), converted to kingdom-prefix form (`"<Kingdom>: <suffix>"`, suffix
  = text after the first `": "` — watch the double-prefixed rows like `Colossal Ruins: Colossal
  Ruins: Dash! Jump!`). Must match shine_map at build so `sync_shine_table.py` resolves them —
  verify each row's `// Count:` grows. **Never bulk-source from the romfs dump.**
- **Interior requirements:** run them through the P6 pipeline (`import_moon_requirements.py` →
  `compile_moon_logic.py`) so each gets its real ability/capture `requires`.
- **Entrance peace-gate (NEW logic requirement):** each moon-pipe subarea's entrance requires
  **kingdom world peace**. Rules.py already has the stub functions `SandPeace` / `LakePeace` /
  `WoodedPeace` / `MetroPeace` / `SnowPeace` / `LuncheonPeace` / `BowserPeace` … (all currently
  `return True`). These are the designed extension point — fill them in and AND them onto the
  moon-pipe subarea entrance terms.
- **"<Kingdom>Peace" model = `canReachLocation(<the kingdom's world-peace moon>)`** (Devon,
  2026-06-18 — CORRECTED; supersedes the earlier "has(Multi-Moon item)" model, which was flawed,
  see below). i.e. `MetroPeace = canReachLocation("Metro: A Traditional Festival!")`. Mirrors the
  Switch rock-open gate (`MoonRockHook` = kingdom main-story scenario complete): in-game the rock
  opens when the player **collects the specific story-completing moon**, regardless of what AP
  item that moon now holds. The canonical world-peace moon per kingdom (Devon's verified list,
  all confirmed present in locations.json):

  | Kingdom | `<Kingdom>Peace` = canReachLocation(...) |
  |---|---|
  | Cascade | `Cascade: Multi Moon Atop the Falls` |
  | Sand | `Sand: The Hole in the Desert` |
  | Lake | `Lake: Broodals Over the Lake` |
  | Wooded | `Wooded: Defend the Secret Flower Field!` |
  | Metro | `Metro: A Traditional Festival!` |
  | Snow | `Snow: The Bound Bowl Grand Prix` |
  | Seaside | `Seaside: The Glass Is Half Full!` |
  | Luncheon | `Luncheon: Cookatiel Showdown!` |
  | Ruined | `Ruined: Battle with the Lord of Lightning!` |
  | Bowser's | `Bowser's: Showdown at Bowser's Castle` |

  All 10 peace functions are implemented in `Rules.py` — Cascade, Sand, Lake, Wooded, Metro,
  Snow, Seaside, Luncheon, Ruined, Bowser's. Acyclic: every world-peace moon is an overworld
  story moon gated only on abilities + kingdom reachability (no `canReachLocation`, no
  moon-pipe dependency), so gating moon-pipe entrances on them introduces no cycle.

- **Why `has(Multi-Moon item)` was WRONG (the flaw Devon caught, 2026-06-18):**
  `multi_moon_shuffle` is **default on** and relocates each `<Kingdom> Kingdom Multi-Moon` item
  *away from* its world-peace location. So possessing the item no longer corresponds to having
  cleared the story moon. **Metro is the concrete break:** the Metro MM item rides on
  `New Donk City's Pest Problem` (night metro), but world peace fires from `A Traditional
  Festival!` (day metro). A player could hold the relocated Metro MM item without ever doing the
  festival ⇒ logic believes the rock is open while in-game it is not ⇒ moon-pipe moons logically
  "reachable" but physically locked = a broken/BK seed. (And of the 10 world-peace moons, 9 are
  themselves `multi_moon: true` — i.e. the exact locations whose item the shuffle moves; Metro's
  festival holds no item and is the `victory` goal location.) `canReachLocation(<world-peace
  moon>)` sidesteps this entirely: it tracks *can the player clear that moon*, which is what opens
  the rock, in both shuffle-on and shuffle-off modes.
- **COUPLED FIX — the festival location must SURVIVE as a real check under non-festival goals**
  (Devon, 2026-06-18). Today `__init__.py:184-185` *deletes* every non-selected `victory: true`
  location from its region (`unused_goal.parent_region.locations.remove(...)`). Under the default
  `mushroom_kingdom` goal that **removes `Metro: A Traditional Festival!` entirely** — so it is
  (a) not an AP check even though it's a real, collectable in-game Multi-Moon, and (b) absent for
  `canReachLocation`, which would make `MetroPeace` reference a non-existent location and error.
  Devon: "A Traditional Festival! should absolutely hold an item if it isn't the chosen goal."
  So the fix (do this with the P6.5 peace work — it's the MetroPeace prerequisite):
  - **Keep, don't delete,** a non-selected victory location that is a *real moon* (the festival).
    Distinguish from the synthetic goal-only location `Arrive in the Mushroom Kingdom`, which has
    no real moon behind it and is fine to remove when it's not the active goal. (Decide the
    discriminator: an explicit data flag is cleaner than name-matching.)
  - **Give the surviving festival the currently-dropped Metro Multi-Moon.** Today
    `before_create_items_filler` (World.py:344-348) unconditionally pops one `Metro Kingdom
    Multi-Moon` because "the festival can't hold an item." Make that drop **conditional on
    `goal == festival`**; under the default goal keep both Metro MMs and let one land on the
    festival.
  - **Matching count:** under the default goal the festival becomes a 14th `multi_moon` location
    ⇒ 14 MM items ↔ 14 locations (still exactly solvable). Under the festival goal it stays the
    victory location (13 ↔ 13, one Metro MM dropped — current behavior). The `multi_moon`
    inclusion is therefore **goal-conditional**, not a static tag, so it can't be expressed by
    flipping the json tag alone — handle it in `_apply_multi_moon_rules` / the matching setup.
  - **Tests to update (they currently encode the OPPOSITE):**
    `tests/test_multi_moon_shuffle.py::test_festival_victory_location_is_not_tagged` and the
    "drop one Metro MM" assertion both assume the festival never holds an item. They must become
    goal-aware. ⚠️ Blast radius = fill balance — implement + run the suite on Windows, don't
    hand-wave.
- **Optimization note (only if sweep cost bites):** `canReachLocation` runs a nested
  reachability sub-sweep per call; ~30 moon-pipe entrances × every fill sweep. If that proves
  slow, the idiomatic AP alternative is an **event item** (`<Kingdom> World Peace`) placed-locked
  at the world-peace location, gating on `has(event)`. canReachLocation is lower-friction and
  already supported, so start there.

- **4 bossless kingdoms — RESOLVED by Devon's "peace on leave" rule (2026-06-18):** Cap / Cloud /
  Lost / Moon "become world peace once you LEAVE them; returning makes the rock hittable."
  - **Cap, Cloud, Lost** have no AP items required to leave, and any return visit implies you
    already left ⇒ **no extra peace term needed — gate their moon-pipe subareas on plain kingdom
    reachability** (same kingdom-gate as the rest of that kingdom's moons). (Verify Cloud's
    `2D Cube` moons are real post-leave content and not first-visit-only before adding them.)
  - **Moon**: leaving Moon = **beating the game**. Gate on the game-clear proxy (closest item:
    `Bowser's Kingdom Multi-Moon`, the last pre-ending MM). ⚠️ **Current iteration:** the goal is
    the Mushroom festival, and beating the game ENDS the AP — so Moon's post-peace moon-pipe
    moons are effectively at/after the goal. **Future-goal note:** if goals beyond the festival
    are ever added, revisit Moon's "leave = win" coupling so these moons stay collectable.
- This phase is Sonnet-able (apworld/data/Python) EXCEPT the peace-model decision, which is
  Devon's. Also fixes the §1b-bis conflated-subarea split while editing the same data.

## 7. Decisions & open questions
- **Bijection = ONE GLOBAL POOL** (Devon, 2026-06-18) — any door → any subarea, all kingdoms
  mixed. Drives deepest logic.
- **Conflated subareas split per-instance** (Devon, 2026-06-18) — all costume rooms and all
  sphynx vaults shuffle individually; Picture Match Goomba + Mario both shuffle. ⇒ split
  `Costume Room` (×3) and `Sphynx Treasure Vault` (×2) in the importer before P7 logic (§1b-bis).
- **Pool scope = ALL physical doors (B)** (Devon, 2026-06-18) — requires the §6 moon-pipe data
  phase (P6.5) first.
- **Peace model FINALIZED — CORRECTED** (Devon, 2026-06-18): the 10 story kingdoms →
  `canReachLocation(<that kingdom's world-peace moon>)` (table in §6), **NOT** `has(MM item)` —
  `multi_moon_shuffle` relocates the MM item off its world-peace location, so possession no longer
  tracks story completion (Metro is the concrete break). Cap/Cloud/Lost → kingdom-reachable only
  (peace-on-leave is automatic); Moon → game-clear proxy (`Bowser's Kingdom Multi-Moon`), with a
  future-goal caveat. (§6)
- **COUPLED to the peace model:** `Metro: A Traditional Festival!` must survive as a real
  Multi-Moon check (holding the currently-dropped Metro MM) whenever it isn't the chosen goal —
  today `__init__.py:184-185` deletes it under the default goal, which both loses a check and
  breaks the `MetroPeace` anchor. Goal-conditional `multi_moon` inclusion + drop; existing
  `test_multi_moon_shuffle.py` tests must become goal-aware. (§6)
- **`CascadePeace` / `RuinedPeace`** — implemented in Rules.py (P6.5 complete). ✅
- **Cloud `2D Cube` moons** — 2 Cloud Moon Rock locations included and gated on plain kingdom
  reachability (no extra peace term, per Cap/Cloud/Lost rule). Verify first-visit-only status
  in-game if any logic issues surface.
