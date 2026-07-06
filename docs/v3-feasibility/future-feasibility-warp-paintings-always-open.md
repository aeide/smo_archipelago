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

**Status: SPIKE COMPLETE (2026-07-06, 5 in-game iterations). Gate chain fully mapped;
`isUnlockedWorld` force built + working for the normal case; the post-game Cascade→Bowser's
painting is gated by undecompiled actor-internal logic and is recommended CURATED OUT.
Net: ~70% estimate confirmed — feasible for normal paintings, actor-RE-gated for post-game
ones.** See the "Spike conclusion" box immediately below, then the iteration log.

### Spike conclusion (2026-07-06)

- **Gate chain (mapped in-game):** a warp painting resolves its destination via
  `getWorldIdForWorldWarpHole(idx)`, then queries `isUnlockedWorld(dest)`; only if that
  passes does it reach `checkIsOpenWorldWarpHoleInScenario(dest, scenario)`. All three are
  hookable named functions.
- **Built + working:** `WorldWarpHoleGateHook` force-opens `checkIsOpen` (all paintings)
  and force-returns `isUnlockedWorld(dest)=true` **scoped to the warp-hole path** via a
  150 ms arm ring keyed on `getWorldIdForWorldWarpHole` (so the world map / order gate /
  Odyssey travel are untouched — verified: world 15/Dark, never armed, stayed `0`). This
  is the right lever for **normal** warp paintings (those gated on destination-kingdom
  unlock).
- **The post-game Cascade→Bowser's painting is NOT crackable this way.** With
  `isUnlockedWorld(12)` forced true it stayed **fully blank**, and the actor made **no other
  world-12 query at all** (`checkIsOpen`/`isAlreadyGoWorld` fired only for worlds 1 & 10,
  never 12). So its blank state is decided **inside the undecompiled `WorldWarpHole` actor**
  (model/asset selection or cached placement state), below the world-state API layer — it
  would require a `main.nso` actor disassembly pass to force.
- **Save-coverage caveat:** on the test save (worlds 0–10 unlocked) the Bowser's painting
  is the *only* warp painting to a locked destination — every normal warp painting targets
  an already-unlocked kingdom and works in vanilla. So the `isUnlockedWorld` fix for the
  normal case is **built but unvalidated**; validate on an earlier save where a normal
  destination is still locked (e.g. Sand→Metro pre-Metro).
- **Recommendation:** land here. **Curate the post-game painting(s) out** of the always-open
  set (exactly the "curated subset" this doc predicted); keep the `isUnlockedWorld` force as
  the normal-case mechanism; gate the whole thing behind `warp_paintings_always_open`; do the
  Tier-2 logic edges. Only pursue the `WorldWarpHole` actor-RE pass if post-game paintings
  specifically become a priority. The spike hook (`WorldWarpHoleGateHook.cpp`) currently runs
  unconditionally with `kWarpPaintingsAlwaysOpen=true` — before shipping, gate it behind the
  option and add the post-game exclusion.

---

**Estimate
~70% feasible → higher after the dynsym check below, Medium effort.** The big
de-riskers: the warp-painting machinery is a **named, data-driven** SMO subsystem
(`WorldWarpHole`), its transition commit is **already hooked in this project**, and the
"is this painting open?" decision is a **named predicate** we can force true — far better
seams than the undecompiled-actor docs in this index. The points off are one real
content risk (do the seven non-early destinations load correctly when their kingdom was
never visited?) and the logic care-work (route-variant destinations + opening a
normally-post-game painting early).

**⚠ Spike RESULT (2026-07-06): `checkIsOpenWorldWarpHoleInScenario` is NOT the gate
for normally-late paintings — the blank state is an UPSTREAM appearance gate.**
Devon built the force+log spike and approached the Cascade→Bowser's painting; it
stayed **blank and unusable**. The `[warp-painting]` log fired (seam is live, not
inlined) but only for destinations that were *already* open (`origResult=1`): dest=10
(Luncheon) on Luncheon load and dest=1 (Cascade) on Cascade load. **The Bowser's
destination (worldId=12) was never queried at all.** The decomp explains why:

```cpp
bool GameDataHolder::checkIsOpenWorldWarpHoleInScenario(s32 worldId, s32 scenarioNo) const {
    for (i…) if (mWorldWarpHoleInfos[i].worldId == worldId && name=="Go")
                 return scenarioNo >= mWorldWarpHoleInfos[i].scenarioNo;
    return false;   // worldId = DESTINATION world
}
```

The actor must already know its **destination** to call this. Destination comes from
`calcWorldIdFromWorldWarpHoleId(holeId)` → `GameProgressData::getWorldIdForWorldWarpHole(idx)`
(the `mWorldIdForWorldWarpHole` array), which returns **-1 until the destination world
is revealed**. So a `-1` there both **blanks the painting** (no dest → no preview
image) **and** stops `checkIsOpen(12, …)` from ever being asked — exactly matching the
log. Corroboration: OdysseyRescue's `isAlreadyGoWorld` bitmap at Cascade was
`11111111111000000` — index 12 (Bowser's) = 0, not unlocked. **Consequence:** the
always-open feature needs the three-layer pattern (this project's known "lie to the
game" shape) — force the UPSTREAM appearance gate (destination mapping / unlock), not
just the `checkIsOpen` commit predicate. Forcing `checkIsOpen` alone is necessary but
insufficient. Feasibility is unchanged in spirit but the Tier-1 hook target moves
upstream into (or adjacent to) the undecompiled `WorldWarpHole` actor's data source —
closer to the doc's ~75% actor-pass floor than the one-liner. **Probe 2 RESULT (2026-07-06):
the gate is `isUnlockedWorld(destWorldId)`.** The "-1 destination" theory was WRONG —
`getWorldIdForWorldWarpHole(idx=12) -> dest=12` (the actor knows dest = Bowser's). The
next call is `isUnlockedWorld(12) -> 0`, and *that* blanks the painting and prevents
`checkIsOpen(12)` from ever running. The working mirror: `idx=8 -> dest=9` then
`isUnlockedWorld(9) -> 1`. So the appearance gate is the generic world-unlock query, not
a warp-specific predicate.

**Scoped-force fix (built 2026-07-06, awaiting test).** `isUnlockedWorld` cannot be
forced true globally (it drives the world map, kingdom-order gate, and Odyssey travel).
But the log shows a tight same-thread pairing — `getWorldIdForWorldWarpHole(idx)->dest=X`
*immediately* followed by `isUnlockedWorld(X)` — and the world map uses a *different*
getter (`getWorldIdForWorldMap`). So `WorldWarpHoleGateHook` now **arms** on the warp-hole
dest in `getWorldIdForWorldWarpHole` and forces `isUnlockedWorld` true **only** for that
just-armed world (single-shot, consumed on match), confining the force to the warp-hole
enumeration path. Combined with the existing `checkIsOpen` force, a normally-late painting
should now light up and be enterable. **Next in-game test answers the doc's dominant
content risk:** does the Bowser's destination sub-stage actually load + present its moon
when entered pre-unlock? Watch for `isUnlockedWorld worldId=12 -> 0 FORCED->1 (warp-hole
path)` to confirm the force fired.

**Iteration 2 (2026-07-06): single-slot arm was too fragile — replaced with a
time-bounded ring.** The first scoped-force attempt did NOT fire (`isUnlockedWorld(12)`
logged plainly, no `FORCED`). Cause: `getWorldIdForWorldWarpHole` is called repeatedly by
the actor loop and *silent repeats* (dedup hides only the log line, not the call)
overwrote the single-slot arm before the matching `isUnlockedWorld(12)` read it. Fix: a
16-entry ring of `(dest, nowMs)`; `isUnlockedWorld(w)` forces true only if `w` was
returned by `getWorldIdForWorldWarpHole` within `kArmWindowMs` (150 ms) — robust to the
interleaving, still time-scoped so an unrelated world-map `isUnlockedWorld(w)` seconds
later is untouched.

**Iteration 3 RESULT (2026-07-06): the force now fires correctly, but the painting is
STILL fully blank.** Log confirms `isUnlockedWorld worldId=12 -> 0 FORCED->1 (warp-hole
path)` fired, and scoping held (`isUnlockedWorld(15)` for Dark, never armed, logged plain
`-> 0`). Devon confirmed in-game: still a blank frame. So **`isUnlockedWorld` is not the
appearance gate** for this painting — the blank is decided one layer deeper. Two facts
reframe the effort: (1) **Cascade→Bowser's is the doc's worst case** — the post-game
"blank until game clear" painting, gated at game-clear level, not kingdom-unlock level;
(2) it is the **only locked warp painting on Devon's save** (bitmap `11111111111000000`:
worlds 0–10 unlocked; every *normal* warp painting targets those and already works in
vanilla). So the `isUnlockedWorld` lever we built is the plausible fix for *normal*
paintings but can't be validated on this save, and the post-game painting needs
deeper/game-clear state. **Probe 3 (built, log-only): arm-scoped logger on
`isAlreadyGoWorld(dest)`** — the prime suspect for the blank gate; NOT forced (it drives
scenario/cutscene/kingdom state game-wide, so confirm before touching). Next test: watch
for `isAlreadyGoWorld worldId=12 -> 0 (warp-hole path — appearance-gate suspect)` during
the Cascade scene load. **Likely landing:** curate the post-game paintings OUT of the
always-open set (the doc anticipated a curated subset) and keep `isUnlockedWorld` as the
normal-case lever; validate the normal case on an earlier save where a normal warp
destination is still locked.

**Spike progress (2026-07-06).** The predicate symbol
`_ZNK14GameDataHolder34checkIsOpenWorldWarpHoleInScenarioEii` was mangling-verified
(demangle round-trip: `GameDataHolder::checkIsOpenWorldWarpHoleInScenario(int, int)
const`, length prefixes 14/34 correct) **and confirmed present out-of-line in retail
`main.nso`'s dynsym** via `scripts/check_nso_symbols.py` — so it was **not fully inlined
away**, which retires most of the "predicate-is-inlined" risk and guarantees
`installAtSym` resolves (no boot abort). The Tier-1 spike is now coded:
[WorldWarpHoleGateHook.cpp](../../switch-mod/src/hooks/WorldWarpHoleGateHook.cpp)
trampolines the predicate, logs each distinct `(worldId, scenarioNo, origResult)` once,
and forces it open (`kWarpPaintingsAlwaysOpen = true`, no AP toggle / no logic change
yet). Symbol added to `SmoApSymbols.sym` + `HookSymbols.hpp`; install wired into
`main.cpp` (pool at `0x100`, ample headroom). **The one seam question the dynsym check
can't answer — does the `WorldWarpHole` actor call this out-of-line copy or an inlined
copy at its call site? — is what the in-game log answers:** build + deploy, approach a
painting, and watch for `[warp-painting] checkIsOpenWorldWarpHoleInScenario …` in the
Ryujinx/SMOClient log. If it fires, the seam is live; then enter a normally-late painting
to answer the content question (does the destination load pre-unlock).

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
