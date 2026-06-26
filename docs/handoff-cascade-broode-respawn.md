# Handoff — Cascade / Madame Broode multi-moon respawn

**Status: IN PROGRESS (investigation).** Running doc per Devon's request — likely to span
multiple sessions / usage windows. Keep this updated every session.

## The bug (Devon, 2026-06-25)

If Mario advances OUT of Cascade Kingdom **before** fighting Madame Broode, she is never
available to fight again, and her **Multi Moon ("Multi Moon Atop the Falls")** disappears
forever — the AP check becomes permanently uncollectable, which can brick a seed if that
moon is progression / needed for the goal.

**When it can happen:** only when the Odyssey leave-gate for Cascade requires **≤2 moons**
AND both of those moons are reachable *pre-Broode*. Then the player can satisfy the gate and
fly out without ever triggering the boss. Rare (needs `randomize_kingdom_gates` to roll
Cascade very low, or a naturally tiny gate) but possible.

Root mechanism (hypothesis, to confirm against decomp): Madame Broode + her Multi-Moon are
placed actors gated on Cascade **scenario 1** (the kingdom's main-story scenario). SMO's
`getScenarioNo(world)` is *recomputed from global quest state at every load* (documented in
`MoonRockHook.cpp` header). Once the player progresses the global story, Cascade's computed
scenario advances past 1, so the boss placement condition never matches again → no boss, no
moon.

## Desired fix (Devon's words)

> "spawn madame broode's triple moon in her normal location if it hasn't been collected yet
> once returning to cascade kingdom"

So: on (re)entering Cascade, if the Multi-Moon is **uncollected**, make it obtainable again
in its normal spot. Re-fighting Broode is acceptable (that's the vanilla way to get it).

## Key facts established

- AP location name: **`Cascade: Multi Moon Atop the Falls`**
  (moon_requirements key `Cascade Kingdom: Multi Moon Atop the Falls`).
- Cascade home stage internal name: `WaterfallWorldHomeStage` (Cascade = "WaterfallWorld").
- This is a **multi_moon** (boss) location — part of the `multi_moon_shuffle` set.
- It is almost certainly **progression** (gated-kingdom / story moon) — losing it is seed-fatal.

## Existing switch-mod machinery we can reuse

- **`MoonRockHook.cpp`** — the model for scenario-aware, per-kingdom, peace-gated hooks.
  Has `resolveGameCtx()` (GameDataHolder → GameDataFile + world_id), and resolved fn ptrs:
  `getScenarioNo`, `getMainScenarioNo`, `isClearWorldMainScenario`, `getMoonRockScenarioNo`,
  plus `setMainScenarioNo` via `kGameDataFileSetMainScenarioNo`. ⚠ Its header documents that
  forcing a scenario MID-story is destructive (skips bosses/quests) — but here we *want* the
  boss scenario, so that caveat may not apply. CONFIRM.
- **Shine collected check:** need to read whether the Multi-Moon's shine flag is set. Options:
  (a) `ApState::locations_checked` (session hash set — NOT persistent across reload), or
  (b) the game's own shine table via `GameDataFunction::isGotShine` / shine_uid from
  `shine_table.h` (persistent, authoritative). (b) is the right source.
- **`ShineAppearanceHook.cpp` line 461-467** has a load-bearing note: re-entering Cascade
  after the first multi-moon spawns the multi-moon shine as a **stub (no model keeper)** via
  `AppearSwitchTimer` — i.e. the moon actor IS placed on revisit but in already-collected
  form. This suggests the moon's placement may persist; the question is the *boss* gating.

## Open questions (investigate next)

1. **Decomp read REQUIRED** (per CLAUDE.md invariant — don't guess a hook chokepoint):
   - What exactly gates Madame Broode's spawn? (Cascade boss actor name in OdysseyDecomp.)
   - What scenario number is the Broode fight / the Multi-Moon placement?
   - How does `getScenarioNo(Cascade)` actually compute after leaving early? Does it really
     advance past the boss scenario, or is the boss gone for a different reason?
2. Will `setMainScenarioNo(Cascade, 1)` STICK, or get recomputed away on the next load (the
   MoonRockHook header warns Cap's scenario was recomputed back every load)?
3. If scenario-rollback is too destructive / non-sticky, the alternative is to **force-spawn
   just the Shine actor** at Broode's location — heavier (actor placement) but surgical.

## Candidate approaches (ranked, pre-decomp)

- **A. Scenario rollback on Cascade entry (preferred if it sticks):** hook stage-enter for
  `WaterfallWorldHomeStage`; if Multi-Moon shine flag unset AND `getScenarioNo(Cascade)` >
  Broode scenario, `setMainScenarioNo(Cascade, broodeScenario)` (or the quest-state lever that
  actually drives placement) so the next stage init re-places Broode + moon. Reuses all
  vanilla boss/moon logic.
- **B. Direct shine force-spawn:** place a Shine actor at Broode's coords when entering
  Cascade with the moon uncollected. No re-fight. More code, no scenario side effects.

## Decomp findings — session 2026-06-25

Read OdysseyDecomp `src/System/{BossSaveData,GameDataFile}.{h,cpp}` (+ headers in-repo) before
picking a chokepoint. What's now locked down vs. still open:

### Confirmed mechanism

1. **Boss spawn is gated on the CURRENT world's PLACEMENT scenario, not on a boss flag.**
   `GameDataFile` exposes `getScenarioNoPlacement()` (the value the object-placement system
   masks every actor against) distinct from the stored per-world `getScenarioNo(world_id)`
   (plain `mScenarioNo[world_id]` array read) and `getMainScenarioNo(world_id)`. Madame Broode +
   her Multi-Moon are placement-gated on Cascade's scenario-1 layout; if the placement scenario
   isn't 1 when you load Cascade, neither actor is placed.

2. **The placement/main scenario is RECOMPUTED from quest state on stage transitions — you
   cannot durably WRITE it.** `GameDataFile::calcNextScenarioNo()` is the computer;
   `setMainScenarioNo(s32)` (note: **no world_id arg — it sets the *current* world**, symbol
   `_ZN12GameDataFile17setMainScenarioNoEi`, already in `SmoApSymbols.sym`) is overwritten on the
   next transition. This is the **exact** failure the Cap-peace experiment hit
   (`MoonRockHook.cpp` header: "capScen pinned at 1 across reloads while capMain held 4; the game
   re-writes main=1 on transitions" — only a *write-interception upgrade* held, and even that
   needed quest cooperation). ⇒ **Approach A (force Cascade scenario back to 1) is the same
   losing fight** — it won't stick, and to make `calcNextScenarioNo` itself return 1 you'd have to
   manipulate the quest *inputs* (destructive: rewinds Cascade's whole story state).

3. **Boss-defeat IS tracked, cleanly and per-world.** `BossSaveData::isAlreadyDeadGK(world, lv)`
   / `onAlreadyDeadGK(world, lv)` over `mIsAlreadyDeadGK{Lv1,Lv2,Lv3}[world]`. World→index via
   `sGKWorldIndexTable = {0,1,2}` ⇒ **Cap=0, Cascade=1, Sand=2** (matches `KingdomUnlock.cpp`
   `kKingdoms[]`: Cascade is index **1**). The Broode fight is **lv 1**. So
   `isAlreadyDeadGK(1, 1) == false` is a reliable "Broode never beaten" signal, persistent across
   save/quit (it's in the BYML save). Symbols for `isAlreadyDeadGK` are **not** yet in our DB —
   resolve via `hk::ro::lookupSymbol` like MoonRockHook does for the World-Travel-Peach accessors
   (soft-degrade on miss; never `installAtSym`).

4. **The Multi-Moon appears via an AppearSwitch tied to the boss event, not free placement.**
   `ShineAppearanceHook.cpp:460-468` already documents the revisit-after-collection case: the
   multi-moon shine re-spawns as a **stub (no model keeper) via `AppearSwitchTimer`**. So the moon
   is wired to the boss-defeat switch; no boss event ⇒ switch never fires ⇒ no collectable moon.

### The key insight this unlocks (supersedes the pre-decomp A/B ranking)

Don't fight the recompute by **writing** scenario state. Intercept the **READ** the placement
system uses — the M7 "lie to the game at the query" pattern (cf. `UnlockShineNumHook`, the
kingdom-order gate). Override the placement-scenario getter to return **1** *only when* all of:
`getCurrentStageName()=="WaterfallWorldHomeStage"` **AND** `isAlreadyDeadGK(1,1)==false` **AND**
the `Cascade: Multi Moon Atop the Falls` shine flag is unset. Because it drives the value the
placement system reads *each load* rather than persisting anything, it is immune to
`calcNextScenarioNo` overwriting — exactly the property the Cap-peace write-approach lacked.

**RESOLVED by Devon (2026-06-25): whole-kingdom revert is ACCEPTABLE — Approach C is greenlit.**
Devon's exact words: "if the whole kingdom's layout reverts it's acceptable as long as it
re-reverts back after i leave again." ⇒ The placement-scenario read-override is fine to revert
Cascade to its scenario-1 layout on entry **provided the override is conditional** (stage==
`WaterfallWorldHomeStage` AND `isAlreadyDeadGK(1,1)`==false AND multi-moon shine unset) so that
once Broode is beaten the condition goes false and the kingdom returns to its computed scenario.
The "re-reverts after leaving again" requirement is automatically satisfied because the override
reads quest/boss state live each load and stops firing the moment Broode is dead. **No in-game
disambiguating experiment needed before implementing C** — proceed with Approach C in a new
`CascadeBroodeRespawnHook.cpp`. (Approach B — surgical Shine force-spawn — remains the fallback
only if C produces some unforeseen non-layout side effect in testing.)

### Disambiguating experiment for Devon (authoritative in-game source)

On a save that left Cascade pre-Broode (or force one), re-enter Cascade and log, from the frame
pump / a stage-enter hook:
- `getCurrentStageName`, `getScenarioNo(1)`, `getMainScenarioNo(1)`, `getScenarioNoPlacement()`,
  `isAlreadyDeadGK(1,1)`, and whether the Broode actor / multi-moon shine is present.
This tells us (a) what Cascade's placement scenario actually computes to on early-return (confirms
or kills the "advanced past 1" hypothesis), and (b) whether the moon spawns as active / stub /
absent — which decides C vs B.

### Symbols still to add/resolve

`getScenarioNoPlacement` (or whichever getter the placement masker calls), `calcNextScenarioNo`,
and `BossSaveData::isAlreadyDeadGK` — resolve via `hk::ro::lookupSymbol` (soft-degrade), mirroring
MoonRockHook. `setMainScenarioNo` is already present but is the wrong lever per finding #2.

## Implemented — session 2026-06-26 (Approach C, code-complete, AWAITING BUILD + IN-GAME TEST)

`switch-mod/src/hooks/CascadeBroodeRespawnHook.cpp` written + wired into `main.cpp`
(`installCascadeBroodeRespawnHook()`, after CostumeDoorHook). CMake globs `src/*.cpp`, so no
build-file edit needed. Committed on `cascade-fixes`.

**What it does.** Trampolines `GameDataFunction::getScenarioNoPlacement(GameDataHolderAccessor)`
— the out-of-line free fn the placement masker reads (wraps the inlined member
`GameDataFile::getScenarioNoPlacement()`). Returns **1** (`kBroodeScenario`) only when ALL of:
- `getCurrentStageName() == "WaterfallWorldHomeStage"`,
- `orig placement scenario > 1` (protects the legit first-visit/intro — scenario 0/1),
- `GameDataFile::isGotShine(multiMoonUid) == false`.
Else passes `orig` through. Self-healing: once the Multi-Moon shine flips, the gate goes false and
Cascade returns to its computed scenario.

**Signal choice — isGotShine, NOT isAlreadyDeadGK.** Matches Devon's wording ("if it hasn't been
collected yet"), reuses the already-verified `_ZNK12GameDataFile10isGotShineEi`, and needs no
`BossSaveData*` offset (OdysseyHeaders has no `BossSaveData.h`; `mBossSaveData` has no accessor →
hand-computed offset would be fragile). The Multi-Moon `shine_uid` is resolved at install via
`shineUidByDisplayName("Multi Moon Atop the Falls")`. uid<0 → hook soft-degrades (fail-safe).

**All three symbols resolved via `hk::ro::lookupSymbol` (soft-degrade, never `installAtSym`)** so a
miss disables the hook instead of aborting the module: `getScenarioNoPlacement` (new HookSymbols
constant `kGameDataFunctionGetScenarioNoPlacement`, mangled
`_ZN16GameDataFunction22getScenarioNoPlacementE22GameDataHolderAccessor`, **not** added to
SmoApSymbols.sym), `getCurrentStageName`, `isGotShine`. `kCascadeRespawnApply` (default true) gates
the actual return override so it can ship log-only.

### ⚠ Two things the FIRST in-game test must confirm (both logged)

1. **Does the chokepoint fire?** The free-fn-vs-inlined-member caller question was NOT resolvable
   from the decomp remotely (404s on `GameDataFile.h/.cpp`, no `gh`/code-search in the sandbox). If
   loading Cascade after leaving pre-Broode produces **zero `[broode-respawn]` lines**, the masker
   inlines the member → pivot: hook the member's caller, or fall back to Approach B (Shine
   force-spawn). The per-call logging turns this into a one-cycle diagnosis, not a silent no-op.
2. **Did the Multi-Moon string resolve?** Install logs `Multi-Moon ... -> shine_uid N`. If it logs
   `uid=-1`, the `shine_id` in `shine_table.h` differs from `"Multi Moon Atop the Falls"` — grep
   `shine_table.h` for the real string and update `kMultiMoonDisplayName`.

### Build + test loop (Devon)

`sync_shine_table.py` (so `shine_table.h` has the Multi-Moon row) → `build_switchmod.py` → copy
`subsdk9`/`main.npdm` into Ryujinx → force/load a save that left Cascade pre-Broode, re-enter
Cascade, watch the guest log for `[broode-respawn]` and confirm Broode + her Multi-Moon re-appear;
then beat her and confirm Cascade reverts to its computed layout on next entry.
