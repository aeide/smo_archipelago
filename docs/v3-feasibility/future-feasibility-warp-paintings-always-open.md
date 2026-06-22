# Warp paintings always available (not randomized) + in logic (Devon, 2026-06-22)

**Goal.** SMO's **warp paintings** are paintings that transport Mario to a small
isolated area in a **different kingdom**, where a Power Moon (or two) waits, with a
return painting back. There are ~10 of them. In vanilla, **a source painting only
becomes usable once its destination kingdom is unlocked** (with three early-view
exceptions — the Metro, Luncheon and Mushroom paintings can be entered before their
kingdom is normally reached). Devon wants:

1. The warp paintings' **destinations left vanilla — NOT randomized** (this is *not* a
   request to fold them into the entrance shuffle).
2. Every warp painting **always usable from the start**, regardless of whether the
   destination kingdom has been reached.
3. That always-available access **reflected in the AP logic**, so the fill knows a
   warp-painting destination moon is reachable as soon as you can reach the painting's
   **source** kingdom.

**Status: investigated, NOT started. Estimate ~70% feasible, Medium effort.** The big
de-riskers: the warp-painting machinery is a **named, data-driven** SMO subsystem
(`WorldWarpHole`), its transition commit is **already hooked in this project**, and the
"is this painting open?" decision is a **named predicate** we can force true — far better
seams than the undecompiled-actor docs in this index. The points off are one real
content risk (do the seven non-early destinations load correctly when their kingdom was
never visited?) and the logic care-work (route-variant destinations + opening a
normally-post-game painting early).

---

## How warp paintings work today (header- + decomp-confirmed this session)

Warp paintings are a **first-class, data-driven** SMO subsystem — not ad-hoc per-actor
logic — which is exactly what makes this tractable:

- **The actor** is `WorldWarpHole` (`HakoniwaStateDemoWorldWarp` is its warp cutscene
  state). The class is declared in our headers; its body is **not** in OdysseyDecomp,
  but — crucially — we likely don't need the actor body, because the decision and the
  transition both live in the **decompiled-header `GameDataHolder` API** it calls.
- **The source↔destination mapping is a data table**, not hardcoded per painting
  ([GameDataHolder.h:55-62,194-203,272-274](../../switch-mod/lib/OdysseyHeaders/game/System/GameDataHolder.h#L55)):
  - `struct WorldWarpHoleInfo { stageName; worldId; scenarioNo; name; }` in
    `mWorldWarpHoleInfos[]` — the full painting list, each entry naming the destination
    **stage**, the destination **worldId**, and the **scenarioNo** it's valid in.
  - `calcWorldWarpHoleDestId(srcId)` / `tryCalcWorldWarpHoleSrcId(destId)` resolve the
    pairing, and it's **scenario-aware** — which is how the same painting changes target
    by progress (the Lake-first vs. Wooded-first variance the wikis describe).
  - `calcWorldWarpHoleLabelAndStageName(...)` / `findWorldWarpHoleInfo(...)` expose the
    label + stage. So the **exact fixed vanilla painting graph is enumerable** — perfect
    for building logic edges without guessing (and without randomizing anything).
- **The availability gate is a named predicate:**
  `GameDataHolder::checkIsOpenWorldWarpHoleInScenario(s32 worldId, s32 scenarioNo)`
  ([GameDataHolder.h:203](../../switch-mod/lib/OdysseyHeaders/game/System/GameDataHolder.h#L203)).
  This is almost certainly the "is the painting to `worldId` open right now?" check the
  actor consults — the thing that returns false early in vanilla. The supporting unlock
  queries (`isUnlockedWorld`, `isAlreadyGoWorld`, `isPlayDemoWorldWarpHole`) live right
  beside it in `GameDataFunction`.
- **The transition commit is ALREADY hooked here.**
  [WorldMapSelectHook.cpp:105-126](../../switch-mod/src/hooks/WorldMapSelectHook.cpp#L105)
  trampolines `GameDataFunction::tryChangeNextStageWithWorldWarpHole(writer, stageName)`
  today (currently "visited-only, no gate" — it just marks the destination kingdom
  visited and passes through). That confirms the funnel exists, is reachable, and hooks
  cleanly. **But note:** by the time that commit fires the game has *already decided* the
  painting is enterable — so it is **not** where the always-open change belongs (same
  upstream/downstream split as the costume-door doc: the decision sits above the
  already-hooked transition).

---

## What the change requires

### Tier 1 — switch-mod: force the painting open (the always-available half)

Force the availability predicate true. Trampoline
`GameDataHolder::checkIsOpenWorldWarpHoleInScenario` and return `true` for every
warp-painting worldId (optionally behind a `warp_paintings_always_open` toggle) — the
exact "force a game decision true" pattern already used by `CaptureGate`,
`AbilityGateHook`, `KingdomOrderGate`, and proposed for the costume doors. One hook
covers all paintings because they all route through this one data-driven check.

Illustrative symbol (verify via the `smo-symbol-discovery` pipeline — const member of
`GameDataHolder`, args `(s32,s32)`):
`_ZNK14GameDataHolder34checkIsOpenWorldWarpHoleInScenarioEii`.

Two confirm-before-build items (per CLAUDE.md's "read the decomp before picking a
chokepoint" rule):
1. **Confirm this predicate is the gate the actor actually reads** (a logger-only
   trampoline at a closed painting), and that it isn't *inlined* into the `WorldWarpHole`
   body — if it is, fall back to forcing the actor's own appear/enable method (then a
   `main.nso` pass on `WorldWarpHole` is needed, the costume-door situation). The strong
   prior that it's out-of-line: it's a non-trivial `GameDataHolder` method (touches the
   scenario-keyed info array) called from actor code, exactly the "generic, called from
   many sites" shape that stays out-of-line.
2. **The visited-marking side effect.** `tryChangeWarpHoleHook` already marks the
   destination kingdom *visited* on warp
   ([WorldMapSelectHook.cpp:105](../../switch-mod/src/hooks/WorldMapSelectHook.cpp#L105)).
   With paintings always open, warping to (say) Bowser's via the Cascade painting early
   would mark Bowser's visited and could perturb the kingdom-order gate
   ([[kingdom-order-gate-premature-destinations]]). Decide whether painting-warps should
   set the visited bit at all, or be exempted.

### Tier 2 — apworld logic: re-gate the destination moons on the SOURCE kingdom

Today the region graph is a simple per-kingdom chain
([regions.json](../../apworld/smo_archipelago/data/regions.json): each kingdom
`connects_to` the next) and warp paintings are **not modeled as edges at all** — the
moons in a painting's destination area are just normal moons of the destination kingdom,
implicitly reachable when that kingdom is reached. The warp-painting destinations are
**isolated platforms reachable only via the painting**, so once the painting is always
open, the correct gate for those moons becomes **"source kingdom reached"**, which can be
*earlier* than the destination kingdom. The edit:

- For each `WorldWarpHoleInfo` (enumerated straight from the data table above — fixed,
  vanilla, **not** shuffled), add a logic edge so the destination-area moon(s) are
  reachable from the **source** kingdom: either a `connects_to` edge `source → dest` in
  regions.json, or — cleaner if the painting moons can be isolated as their own
  micro-region — give those specific moons a `requires` of `{KingdomMoons(Source, 0)}` /
  a "source kingdom reached" term rather than the destination's.
- This only ever **loosens** reachability (it adds an access path), so it cannot strand
  an existing moon. It does make warp access a real, fill-relevant routing tool.
- Needs a **regenerate/re-seed** (region-graph change), unlike a pure switch-mod toggle.
  Use `KingdomMoons` (returns composable requires-strings, honors rolled gate values) and
  **avoid `canReachRegion`** for the gate term — the Manual-derived `set_rules` gates a
  region's *egress*, so `canReachRegion` reads true one kingdom early
  ([[region-gating-egress-off-by-one]]).

The two care items:
- **Route-variant destinations.** Because `calcWorldWarpHoleDestId` is scenario-keyed, a
  few paintings (Wooded/Lake/Metro) point at *different* kingdoms depending on Lake-first
  vs. Wooded-first. Logic must either take the **union** of possible destinations
  (conservative: a moon is reachable if reachable via any of its scenario-valid sources)
  or pin the deterministic mapping. The union is safe (still only loosens).
- **The Cascade→Bowser's painting is normally post-game** (blank until you beat the
  game). Opening it from the start gives very early access to a Bowser's-area moon. That's
  fine for *reachability* (loosening), but confirm it doesn't collide with the goal
  coupling or order gate (e.g. don't let it count toward "visited Bowser's" in a way that
  short-circuits story progression — see Tier 1 item 2).

### Tier 3 — entrance-shuffle interaction: explicitly EXCLUDE paintings (per the ask)

Devon wants painting destinations left vanilla. Good news: they already are — the
entrance extractor only captures six door unit types
([extract_entrance_stages.py:53-60](../../scripts/extract_entrance_stages.py#L53)) and
the `WorldWarpHole` actor is **not** among them, so warp paintings are **not** in the
shuffle pool and won't be touched. This tier is a **non-action** — just a note to keep
`WorldWarpHole` out of any future any-to-any pool (the
[decoupled-entrance-randomizer doc](future-feasibility-decoupled-entrance-randomizer.md)
should treat these as fixed) so this feature and that one don't fight.

---

## Risks / why ~70%

- **Destination stage load when the kingdom was never visited (the dominant unknown).**
  Vanilla proves *some* destinations load pre-unlock — the Metro/Luncheon/Mushroom
  early-view paintings do exactly this. But that only proves three; the other seven were
  never meant to be entered before their kingdom, and there's a real chance a destination
  sub-stage's scenario/init is malformed (or the moon's spawn condition unmet) when its
  kingdom hasn't been reached. **Mitigation/likely outcome:** this may force a per-painting
  whitelist of "safe to force early" (the always-open set might be a curated subset rather
  than all ten) — which is acceptable and still delivers the feature for most paintings.
  A logger+force spike on one normally-late painting answers this binary question.
- **Predicate-is-inlined risk.** If `checkIsOpenWorldWarpHoleInScenario` is inlined into
  the `WorldWarpHole` body, Tier 1 needs the undecompiled-actor `main.nso` pass instead
  (drops it toward the costume-door 75% floor). Strong prior it's out-of-line (non-trivial
  holder method), but unverified.
- **Logic route-variance + early-access interactions.** Scenario-keyed destinations and
  the post-game Cascade→Bowser's painting need the careful re-gating above; mishandled,
  they're a logic-vs-reality gap rather than a crash. Manageable, but real work.
- **Visited-bit side effect** on the existing warp-hole hook perturbing the order gate
  (Tier 1 item 2).
- **Goal coupling** — opening late paintings early must not let a player trip the
  game-clear/Moon "leave = win" coupling out of sequence (cross-ref the deferred-work note
  in CLAUDE.md). Low likelihood (painting areas are isolated moon platforms), but worth a
  confirm.

---

## Recommendation / first step (when pursued)

1. **One-build force+log spike, no logic change:** trampoline
   `checkIsOpenWorldWarpHoleInScenario` to log its `(worldId, scenarioNo)` args + return
   value at every painting, then force it `true`, and **in-game enter a normally-late
   painting** (e.g. a destination whose kingdom you haven't reached). That single test
   answers the two gating unknowns at once: (a) is this the real predicate the actor
   reads (not inlined), and (b) does the destination stage load + present its moon in a
   usable state pre-unlock. The result decides whether always-open is all-ten or a curated
   subset, and whether Tier 1 stays a one-liner or needs the actor pass.
2. If clean: dump `mWorldWarpHoleInfos` to enumerate the fixed source→dest(+scenario)
   table, add the Tier 2 source-kingdom logic edges (union over scenario variants),
   gate Tier 1 behind a `warp_paintings_always_open` toggle, resolve the visited-bit
   question, rebuild + regenerate. Verify: each painting usable from the start; each
   destination moon shows reachable from its source kingdom in the spoiler/sweep; nothing
   stranded; order gate + goal unaffected.

**Why ~70%:** the seams are unusually good for this project — a **named** availability
predicate to force (not an undecompiled actor compare), a **data-driven** painting table
to enumerate the fixed graph (so "not randomized" is trivial and logic edges are exact),
and the transition funnel **already hooked**. The feature is also *provably possible* —
three paintings already behave exactly this way in vanilla. The points off are the
genuine content risk that the seven non-early destinations may not initialize cleanly
pre-unlock (possibly narrowing always-open to a curated subset), the unverified
inlining of the predicate, and the logic care-work around scenario-variant destinations,
the post-game Cascade painting, and the visited-bit side effect.

---

Sources consulted (disk-truth reads + decomp + web this session):
[GameDataHolder.h](../../switch-mod/lib/OdysseyHeaders/game/System/GameDataHolder.h)
(`WorldWarpHoleInfo` table, `checkIsOpenWorldWarpHoleInScenario`,
`calcWorldWarpHoleDestId`/`tryCalcWorldWarpHoleSrcId`/`findWorldWarpHoleInfo`,
`mWorldWarpHoleInfos`),
[GameDataFunction.h](../../switch-mod/lib/OdysseyHeaders/game/System/GameDataFunction.h)
(`tryChangeNextStageWithWorldWarpHole`, `isUnlockedWorld`, `isAlreadyGoWorld`,
`isPlayDemoWorldWarpHole`),
[GameProgressData.h](../../switch-mod/lib/OdysseyHeaders/game/System/GameProgressData.h)
(`getWorldIdForWorldWarpHole`),
[WorldMapSelectHook.cpp](../../switch-mod/src/hooks/WorldMapSelectHook.cpp) (the warp-hole
transition is already trampolined, "visited-only, no gate"; the upstream/downstream split),
[regions.json](../../apworld/smo_archipelago/data/regions.json) (per-kingdom chain; no
painting edges today),
[moon_requirements.json](../../apworld/smo_archipelago/data/moon_requirements.json)
(`other_required` carries movement abilities only — no warp/painting access term today),
[extract_entrance_stages.py](../../scripts/extract_entrance_stages.py) (`DOOR_UNITS` —
`WorldWarpHole` is not a shuffle unit, so paintings are already excluded from entrance
shuffle); OdysseyDecomp tree (no `WorldWarpHole`/`Warp`/`Painting` .cpp — actor body
undecompiled, but the `GameDataHolder` API it calls is in our headers); SMO community wiki
(unlock conditions: source painting opens once destination kingdom is unlocked, with
Metro/Luncheon/Mushroom early-view exceptions; ~10 paintings; route-variant destinations).
Cross-refs: [[region-gating-egress-off-by-one]], [[kingdom-order-gate-premature-destinations]],
[future-feasibility-costume-doors-always-open.md](future-feasibility-costume-doors-always-open.md)
(upstream-of-the-hooked-transition pattern),
[future-feasibility-lake-wooded-free-detour.md](future-feasibility-lake-wooded-free-detour.md)
(`KingdomMoons` gate composition).
