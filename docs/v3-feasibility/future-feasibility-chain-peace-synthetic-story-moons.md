# Future feasibility — forced world peace on chain arrival + synthetic story-moon collection ("peace pedestals")

**Status: IDEA-GATHERING ONLY (2026-07-09). Not scheduled. Devon review pending.**
Origin: design conversation 2026-07-09, on top of the decoupled entrance
randomizer (P4 state, see [../plan-decoupled-entrances.md](../plan-decoupled-entrances.md)).
Decomp reads for the two crux mechanism questions were done this session and are
recorded below — the feasibility calls in this doc are decomp-grounded, not guesses.

**Sequencing:** gated behind **P5 (cross-world stage loads)** — both features ride
the same remapped-commit path that currently crashes for subarea-origin /
interior-target loads, and P5's world-resource fix is likely a prerequisite for
ANY forced-scenario load being safe. Nothing here should be built before the P5
walk data is in.

---

## 1. Problem statement

Under the decoupled randomizer, chain arrivals load a kingdom's TRUE story
scenario (the P4 scenario-neutralization fix). Real costs observed in walks:

- **P4 finding 4:** a matched target mouth that is scenario-gated (e.g. Gusty
  Bridges pre-`{CascadeDeparture()}`) doesn't exist in the true scenario — the
  engine falls back to the kingdom default spawn, and the **retrace guarantee
  fails** while the arrival door doesn't exist.
- A chain-reached kingdom in early scenario exposes only a fraction of its
  content (doors, NPCs, moons).

Devon's proposal: any arrival OTHER than legitimate Odyssey flight puts the
kingdom in **world peace mode** for that visit (max doors + moons available);
legitimate arrivals load the true scenario so the story plays through normally.
The follow-on worry — "locking peace in before a boss strands her Multi-Moon
forever" — motivated the second idea: synthetic story-moon actors in the peace
scenario ("collect as if you'd beaten her").

## 2. Design principle #0 — NEVER PERSIST

Everything in this doc is a **per-load illusion**. The forcing writes a scenario
number into the stage-change commit; it never touches quest state, got-shine
flags, or any save field. Consequences, all load-bearing:

- **No story moon can ever be stranded.** The save never advances; fly to the
  kingdom legitimately at any time and the boss is still there. The stranding
  fear only materializes in a persist-peace variant, which this doc explicitly
  rejects (same family as the concluded-OFF cap-peace-from-start experiment and
  the MoonRockHook mid-story-forcing warnings).
- **"Revert on first legitimate arrival" costs zero code.** Scenario is
  recomputed from quest state on every non-forced load (confirmed mechanism, §4),
  so a legitimate arrival with scenario `-1` lands at the true scenario
  automatically.
- S&Q inside a forced-peace visit reloads via the save path (not a commit we
  rewrite) and comes back in the TRUE scenario. Acceptable: the parked-Odyssey
  chain-return flight (shipped) is the escape hatch. Peace is per-arrival, not
  per-session.

## 3. Mechanism A — forced peace scenario on chain arrivals

### 3.1 The lever (proven)

The explicit scenario field on the remapped ChangeStageInfo commit — the exact
field the stale-`scenario=1` bug abused downward and the P4 neutralization now
sets to `-1`. Forcing is a one-line change of WHAT we write at the existing
seam (`EntranceShuffleHook` scenario rewrite / `processChainArrival`).
Decomp support: `GameDataFile` has a dedicated `mScenarioNoOverride` member
(header, `src/System/GameDataFile.h`) — an explicit-scenario override is a
vanilla-supported engine channel, not a hack.

### 3.2 Per-kingdom peace scenario number — comes free from WorldList

No hardcoded table needed. `WorldListEntry` (decomp `src/System/WorldList.h`)
carries three per-world scenario fields with runtime accessors the mod can call
through `GameDataHolder::getWorldList()`:

| Field | Accessor | Likely meaning |
|---|---|---|
| `clearMainScenario` | `isEqualClearMainScenarioNo(worldId, no)` | scenario after story clear = "world peace" |
| `moonRockScenario` | `getMoonRockScenarioNo(worldId)` | scenario when the moon rock layer applies |
| `endingScenario` | `getAfterEndingScenarioNo(worldId)` | post-game layer |

Which one is "the peace placement Devon means" needs one log spike (dump all
three per kingdom on boot) + one walk confirmation. All three are functional
numbers — committable.

### 3.3 Scope of the forcing

Force on **every commit whose destination kingdom qualifies**, not just remapped
rows. Otherwise a shop round-trip inside the forced-peace kingdom recomputes the
true scenario on `returnPrevStage` and the door you arrived through vanishes
mid-visit. The hook already sees both commit classes (P7 work).

### 3.4 Qualifying rule — Devon decision needed

- **(a) Chain-only marker:** force while `isKingdomChainReachedOnlySave`
  (finding-13 machinery, already shipped). Matches the proposal's literal
  phrasing — peace "reverts" after first legitimate flight and never returns.
  **Logic hole:** access via the chain channel is order-dependent (dies when the
  player flies there), which AP's monotone logic can't express — a moon can be
  in logic during a window the player can permanently close, and under
  capturesanity/abilitysanity, re-earning it via story completion is not free.
- **(b) Always-force (recommended):** every chain arrival forces peace, forever;
  every legitimate arrival loads true scenario. Chain-channel access is
  permanent ⇒ honestly creditable in logic. The kingdom's story arc is
  untouched on its own timeline. Cost: chaining into a mid-story kingdom shows
  it transiently peaceful (story actors absent that load) — coherent
  "you're seeing the future" flavor, and physically harmless since nothing
  persists.

### 3.5 Exemptions

Lost/Ruined stay exempt (story-managed states, same list as the chain-arrival
ship normalization). Expand one confirmed case at a time, per the
ZONE_STAGE_ALIAS protocol. Moon/Dark/Darker are already out of the pool (D5).

### 3.6 What forced peace does NOT do — the moon-rock caveat

Decomp-grounded: moon-rock content is **save-flag-gated, not scenario-gated**.

- `MoonRockData` (decomp `src/System/MoonRockData.h`) holds only demo-shown
  flags; the open state rides `GameDataFile::isOpenMoonRock(world_id)` — a
  persisted save state, untouched by a forced scenario number.
- `GameDataFile::HintInfo::isEnableUnlock` shows moon-rock shines bypass the
  per-scenario window check (`is_moon_rock || progressBitFlag ...`) — their
  availability is the rock event, not the scenario layer.
- MoonRockHook's peace gate reads REAL quest state, so during a forced-peace
  visit to a story-incomplete kingdom the rock is not openable — which is
  correct (an open-rock save write during an illusion visit would be exactly
  the mixed-persistence hazard §2 exists to prevent).

**Open probe:** whether the project's "moon pipes" (the shuffled moon-pipe
mouths) are placed by the peace *scenario layer* (forced peace spawns them) or
gated on the *rock-open flag* (it doesn't). If rock-gated, Devon's "arrival
pipes guaranteed to exist" motivation is only partially served, and the fix is
pool-side: exclude rock-gated mouths as chain rewrite TARGETS rather than
forcing any save flag.

### 3.7 Risks

- **Mixed-placement memory class.** "Forced scenario disagreeing with quest
  state" is the exact mechanism of the 07-07 FrameHeap crash (stale scenario-1 ×
  moon-rock actor set), pointed the other direction. Forced-peace × virgin quest
  flags needs an in-game soak probe, and P5's heap/world-resource findings come
  first.
- Kingdom-specific placement assumptions in the peace layer (parked ship,
  post-boss geometry) interacting with virgin save flags — walk items, expect
  cosmetic oddities before crashes.

## 4. Decomp findings — the scenario/quest coupling (crux of Mechanism B)

Read 2026-07-09 from OdysseyDecomp (`src/System/GameDataFile.{h,cpp}`,
`src/System/GameDataFunction.cpp`, `src/Scene/QuestInfoHolder.cpp`,
`src/System/WorldList.h`, `src/System/MoonRockData.h`):

1. **Scenario numbers are stored per world** — `mScenarioNo[20]` /
   `mMainScenarioNo[20]` in `GameDataFile` — and recomputed at stage change
   (`calcNextScenarioNo`, body undecompiled) from main-quest progress.
2. **The quest system derives main-quest progress from got-shine flags at
   placement time.** `rs::createAndRegisterQuestInfoToHolderFromLinkedObj`
   (QuestInfoHolder.cpp): a registered quest whose linked shine satisfies
   `GameDataFunction::isGotShine(stage, objId)` is immediately invalidated.
3. **Quest invalidation advances the main scenario.**
   `QuestInfoHolder::invalidateQuest`: when the active quest list empties,
   `GameDataFunction::setMainScenarioNo(questNo + 1)`.

**Conclusion — NOT separable at the flag level: synthetically calling
`setGotShine` on a story shine advances the kingdom's real story at its next
load.** "Grant the flag without advancing the quest" does not exist as a data
distinction; the flag IS the quest input. Any pedestal design that writes
`mGotShine` is a real story fast-forward (plus finding-4-style scenario jumps
and every missable-window question) — **rejected**.

Bonus ground truth for the logic layer: `HintInfo::progressBitFlag` is the
engine's per-shine scenario-availability window
(`isEnableNameUnlockByScenario`: empty flag = all scenarios, else
`isOnBit(scenario_no - 1)`) — the authoritative model behind
`moon_requirements.json`'s scenario gates when auditing which moons "pop in and
out" under forced peace.

## 5. Mechanism B — synthetic story-moon collection ("peace pedestals")

Given §4, the design inverts: **the pedestal never touches the save.** A story
MM under multi_moon_shuffle is just an AP *location*; checking it does not
require the game to believe the shine is got.

### Tier 1 — trigger volume, no actor (recommended first build)

- Frame-pump position check, active only during forced-peace chain visits:
  player within radius of a per-kingdom boss-arena coordinate → report the
  matching AP location check over the wire (client accepts a synthetic
  location-check message; same reporting path shape as MoonGetHook's, without
  `setGotShine`) + Cappy bubble ("Madame Broode's Multi-Moon — checked!").
- Save untouched: no scenario advance, no missables, Broode intact, story
  replayable. When the player later beats her for real, `setGotShine` fires
  vanilla and the AP location dedupes to a no-op.
- Costs: no visible moon actor; the natural HUD moon counter doesn't bump
  (consistent with the existing AP-credit asymmetry — the deferred AP-credit
  overlay item). Coordinate table is functional data, committable.

### Tier 2 — runtime-spawned Shine actor (visual upgrade, optional)

- Community-precedented pattern (SMOO puppets): capture an `al::ActorInitInfo`
  during scene init, then `new Shine(...)` +
  `al::initCreateActorNoPlacementInfo(actor, initInfo)` (confirmed present in
  OdysseyHeaders, `al/Library/LiveActor/ActorInitUtil.h`; full `Shine` class
  layout in `game/Item/Shine.h`, `sizeof 0x380`, with `appearStatic()` /
  `appearWait(trans)` entry points).
- Collection MUST be intercepted at the `MoonGetHook` chokepoint to SUPPRESS
  the save write for the synthetic shine's identity and report the AP check
  instead — otherwise §4's fast-forward returns through the back door.
- Risks: heap discipline (stationed-heap pre-orig invariant; adjacent to the
  P5 allocation crash class), Shine model resource availability in the loaded
  stage (usually resident in overworlds), demo/camera wiring on collect.
  Gate on a dedicated spike before committing; the Shine actor body is NOT in
  OdysseyDecomp, so the spike includes a symbol-dump read of its init path.

### Rejected variants

- `setGotShine`-based grant (fast-forward, §4).
- Persistent world peace (stranding + mixed save state — the fear that
  motivated this doc, §2).

## 6. Logic layer (phased)

- **L0 — no logic credit.** Forced peace is physical QoL only: retrace fixed,
  extra content collectable out-of-logic. Zero Rules changes. Shippable alone.
- **L1 — chain-channel credit.** Peace-window moons + pedestal locations become
  reachable via the chain channel. Requires the §3.4(b) always-force variant
  (monotonicity), and rules of the shape
  `(chain edge into K reachable) OR (flight-reach K AND scenario fragment)` —
  composed onto the existing K-Arrival two-channel wiring from P3d. Scenario
  windows come from the `compile_moon_logic` data (engine ground truth:
  `progressBitFlag`, §4). This is a design-doc-gated phase of its own
  (3a-style, Devon sign-off) — the window audit is the bulk of the work.

## 7. Probes / walk items (all post-P5)

1. Log spike: dump `clearMainScenario` / `moonRockScenario` / `endingScenario`
   per kingdom; pick the peace source (§3.2).
2. Forced-peace load of a never-visited kingdom: clean load (memory class)?
   All scenario-gated doors present? Moon pipes present or absent (§3.6)?
3. Forced-peace load of a mid-story kingdom (§3.4(b) variant): clean? story
   actors absent as expected? nothing persisted after S&Q?
4. Subarea round-trip inside a forced-peace visit (§3.3 all-commits scope).
5. Boss-arena coordinate capture for the tier-1 pedestal table.
6. Tier-2 spike (only if tier 1 lands and the visual is wanted).

## 8. Interactions

- **Decoupled matching topology:** independent of the no-O↔O constraint, but
  complementary — the interior↔interior chains that do roll stop degrading to
  default-spawn landings when the destination kingdom is forced peaceful.
- **Chain-return flight / finding 13:** unchanged; the save-derived chain-only
  marker is reused by §3.4(a) if that variant is chosen.
- **Kingdom gates / allowance:** forcing a scenario does not touch deposit or
  gate machinery; the takeoff allowance logic is orthogonal.

## 9. IP note

Everything this doc needs is functional: scenario numbers, WorldList field
names, stage/obj identifiers, coordinates. No Nintendo strings anywhere.

## 10. Rating

**Mechanism A (forced peace): ~85%, Low–Medium effort** — proven lever, runtime
peace-table for free, main risk is the mixed-placement memory class (P5-adjacent).
**Mechanism B tier 1 (trigger pedestal): ~90%, Low effort** — no new engine
capability at all. **Tier 2 (spawned Shine): ~55%, Medium–High** — new
capability, undecompiled actor body, heap risk. **L1 logic credit: Medium–High
effort**, gated on its own design doc.
