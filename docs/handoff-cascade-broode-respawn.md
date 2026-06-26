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

### First in-game test — 2026-06-26 (Devon): moon did NOT respawn

Devon left Cascade pre-Broode (collected 6 random Cascade moons via `!getitem` to satisfy the
rolled leave-gate of 6), went to Sand, returned to Cascade. Broode's Multi-Moon was absent.

From the Ryujinx log:
- **Check 2 PASSED:** `[broode-respawn] Multi-Moon Multi Moon Atop the Falls -> shine_uid 218` and
  `installing ... getScenarioNoPlacement @ 0x8a2c284 (apply=1)`. String + install fine.
- **Check 1 INCONCLUSIVE (the bug):** ZERO `[broode-respawn]` runtime lines on Cascade re-entry.
  The moon-rock hook DID fire there — `[moon-rock] enable forced (world=1 peace done, scenario=7
  mr=4)` — so Cascade's stored `getScenarioNo(1)=7` and `isClearWorldMainScenario(Cascade)=true`
  (advanced way past Broode's scenario 1: exactly the bug). But the v1 hook only logged inside the
  override branch, so "no line" can't distinguish:
  - **(A)** `GameDataFunction::getScenarioNoPlacement` (free fn) is NOT on the placement path — the
    object masker reads the inlined `GameDataFile::getScenarioNoPlacement()` member or a different
    scenario source → our trampoline never fires for placement. **Strongly favored** (Devon didn't
    beat Broode, so `isGotShine(218)` should be false → an override WOULD have logged if the fn
    were called; the silence implies it isn't called in Cascade).
  - **(B)** it IS called but `isGotShine(218)` returned true (would require uid 218 ≠ Broode's moon;
    unlikely given the exact name match).

**v2 (this commit): diagnostic upgrade.** The hook now logs EVERY `getScenarioNoPlacement` call
(separate caps: 16 in-Cascade, 6 elsewhere — so early-boot calls can't starve the Cascade ones),
printing stage, `orig`, `cascade`, stored `getScenarioNo(Cascade)`, and `gotMulti` (isGotShine).
Override path unchanged (still apply=1). Next test resolves A vs B:
- **In-Cascade `[broode-respawn] getScenarioNoPlacement` lines appear with `gotMulti=0`** but no
  `OVERRIDE` line → impossible (override would fire); if they appear WITH `OVERRIDE` and the moon
  still doesn't spawn → the placement masker uses a *different* scenario than this getter returns.
- **No in-Cascade lines at all (only non-Cascade)** → case (A) confirmed: pivot to hooking the
  actual masker / the `mScenarioNoPlacement` setter (need the decomp body of
  `GameDataFile::changeNextStage` / `startStage` — couldn't retrieve it remotely; ask Devon to
  paste `src/System/GameDataFile.cpp`'s scenario-write lines, or fall back to Approach B
  force-spawn).

### Second in-game test — 2026-06-26 (Devon): CASE A CONFIRMED

v2 diagnostic build, reloaded the same save into `WaterfallWorldHomeStage`. Log showed install OK
(uid 218, hook @ `0x8a2c284`), moon-rock fired (`world=1 peace done scenario=7`) — bug condition
present — but **not a single `[broode-respawn]` runtime line**, including the v2 *unconditional*
per-call diagnostics. Since v2 logs on every call regardless of branch, zero lines ⇒ the trampoline
never fired ⇒ **case (A): the free-fn wrapper `GameDataFunction::getScenarioNoPlacement(accessor)`
is not on the placement path.**

### v3 fix (this session): hook the MEMBER

WebFetch of `OdysseyDecomp/src/System/GameDataFile.h` confirmed the layout:
`s32 getScenarioNoPlacement() const;` (member, no args) plus fields `s32 mScenarioNoPlacement = -1;`
and a previously-unknown `s32 mScenarioNoOverride = -1;`. Placement holds the `GameDataFile` and
calls the **member** directly; the `GameDataFunction` free function is just an out-of-line wrapper
nothing on the hot path uses.

So `CascadeBroodeRespawnHook` now trampolines the member
`_ZNK12GameDataFile22getScenarioNoPlacementEv` (HookSymbols `kGameDataFileGetScenarioNoPlacement`),
via `lookupSymbol` + `installAtPtr` (soft-degrade). `this` (x0) is the `GameDataFile*`, which gives
**both** the Cascade scope check (`gdf->mCurWorldId == 1`, field exposed by the local
`switch-mod/lib/OdysseyHeaders/game/System/GameDataFile.h`) **and** the `isGotShine(gdf, 218)`
receiver — so the accessor + `getCurrentStageName` machinery is gone. Override unchanged in spirit:
`world==Cascade && orig>1 && !isGotShine(218)` → return `1`. Compiles clean (98/98 link, 0 errors),
deployed to `%APPDATA%\Ryujinx\mods\...\exefs\` (subsdk9 + main.npdm, 2026-06-26 10:04).

**Next-test log read:**
- In-Cascade `[broode-respawn] getScenarioNoPlacement(member) world=1 orig=N ...` diag lines appear,
  and an `OVERRIDE` line with the moon re-spawning → **fixed**.
- Diag lines appear WITH `OVERRIDE` but the moon still doesn't spawn → placement uses a *different*
  scenario value than this member returns (revisit which getter the masker reads).
- STILL zero `[broode-respawn]` lines → the member is inlined at the placement site too (or the
  `_ZNK..Ev` symbol didn't resolve — check the install log for the `(member) lookup FAILED` line).
  Pivot to the scenario **WRITE** path: force `mScenarioNoPlacement` / `mScenarioNoOverride` at the
  stage-init compute (`calcNextScenarioNo` / `changeNextStage`). That needs the decomp body of those
  writers — couldn't fetch the large `GameDataFile.cpp` via WebFetch (summarizer truncates it);
  **paste the `mScenarioNoPlacement` / `mScenarioNoOverride` assignment lines from your local
  OdysseyDecomp `src/System/GameDataFile.cpp`** and I'll target the writer directly. Or Approach B
  (Shine force-spawn).

### Build + test loop (Devon)

`sync_shine_table.py` (so `shine_table.h` has the Multi-Moon row) → `build_switchmod.py` → copy
`subsdk9`/`main.npdm` into Ryujinx → force/load a save that left Cascade pre-Broode, re-enter
Cascade, watch the guest log for `[broode-respawn]` and confirm Broode + her Multi-Moon re-appear;
then beat her and confirm Cascade reverts to its computed layout on next entry.

(For the v3 test the build is already done + deployed — just reload your existing pre-Broode save
into Cascade and grab the log.)

### v3 result + v4 fix (this session): WRITE the field, don't hook the read

**v3 member hook ALSO fired zero times.** The `Ryujinx_..._10-26-01` log shows the member installed
(`installing CascadeBroodeRespawnHook -> GameDataFile::getScenarioNoPlacement(member) @ 0x8a28cac`,
uid 218 resolved) and `[moon-rock] enable forced (world=1 ... scenario=7 ...)` confirming the bug is
live in that save — yet ZERO `[broode-respawn]` lines across multiple Cascade entries. So the read is
**fully inlined at the placement site** (both the free-fn wrapper *and* the member are dead seams).

**Decomp confirms there is nothing left to hook.** Pulled the OdysseyDecomp `src/System` files
locally (PowerShell `Invoke-WebRequest` → Read tool, because WebFetch's summarizer truncates the big
`.cpp`): in `GameDataFunction.cpp` both `getScenarioNoPlacement(accessor)` and
`calcNextScenarioNo(accessor)` are one-line wrappers calling the GameDataFile member; the GameDataFile
**members** (`getScenarioNoPlacement()`, `calcNextScenarioNo()`, `setMainScenarioNo()`, and any writer
of `mScenarioNoPlacement`/`mScenarioNoOverride`) are **undecompiled** — they aren't in the 250-line
`GameDataFile.cpp` nor any other `GameData*.cpp`. No body to read, no out-of-line writer symbol. So
fetching more decomp won't help — that line of attack is exhausted.

**v4 = write the backing field.** `GameDataFile.h` pins it by size: the last three `s32` are
`mTotalAchievementNum`(0xb5c) / `mScenarioNoPlacement`(**0xb60**) / `mScenarioNoOverride`(0xb64), and
`static_assert(sizeof(GameDataFile)==0xb68)` (matches the local OdysseyHeaders mirror), so 0xb60 is
anchored to the struct end and reliable. `CascadeBroodeRespawnHook` no longer trampolines anything; it
exposes `forceCascadePlacementScenario(gdf, destStage, tag)`, and **EntranceShuffleHook's existing
`fileChangeNextStageHook` (`GameDataFile::changeNextStage`, which already hands us `self`) calls it
post-orig**. When the final (post-remap) destination is `WaterfallWorldHomeStage` and
`isGotShine(218)==false`, it writes `*(s32*)(gdf+0xb60)=1`. `changeNextStage` runs before the next
stage's placement, so the inlined read picks up our `1` → Broode + her Multi-Moon are placed.
Re-applied on every commit into Cascade, so `calcNextScenarioNo` recompute can't durably defeat it.
Built clean (98/98) + deployed (subsdk9 + main.npdm, 2026-06-26 10:46).

**⚠ Test via ROUND-TRIP, not reload.** A save reload loads the stage **directly** with no
`changeNextStage` commit (the `10-26-01` log shows no `[entrance:file]` before the initial Cascade
arrival), so the actors were already placed at the bad scenario and can't be retro-placed — the hook
can't fire on that path. **To test: from the pre-Broode Cascade, fly to another kingdom (e.g. Sand)
and come back.** On the return you should see a `[broode-respawn] changeNextStage FORCE Cascade
mScenarioNoPlacement N -> 1 ...` line, then Broode + her Multi-Moon on arrival.

**Log read (v4):**
- `FORCE ... N -> 1` on the Cascade return + Broode/moon present → **fixed**.
- The `FORCE ... N -> 1` line is emitted ONLY when the field wasn't already 1, so: a single line then
  silence on subsequent commits = our write held through the load. **Repeated** `N -> 1` lines every
  time you re-enter Cascade, but no Broode = a recompute clobbers `mScenarioNoPlacement` *between*
  `changeNextStage` and the placement read → move the write later (a StageScene-init seam) or go to
  Approach B (Shine force-spawn). `mScenarioNoOverride` is logged (not written) for the same diagnosis.
- No `[broode-respawn]` line at all on a Cascade return → the destination didn't read as
  `WaterfallWorldHomeStage` (check the `[entrance:file] stage='...'` line) or `isGotShine` lookup
  failed (check the install-time `armed`/`isGotShine lookup FAILED` line).

### v4 result + intent change + v5 fix (this session, cont.)

**v4 fired but didn't take.** The `10-49-29` round-trip (Sand→Cascade) logged
`[broode-respawn] changeNextStage FORCE Cascade mScenarioNoPlacement 7 -> 1` exactly once (offset
0xb60 verified: `before=7` matched moon-rock's `scenario=7`) — but Cascade **still loaded in the
world-peace scenario**: Broode did NOT respawn, and `[moon-rock] ... scenario=7` kept logging after
the return. So the stage load **recomputes `mScenarioNoPlacement` back to 7** between our
`changeNextStage` write and the placement read. Writing the GameDataFile field at `changeNextStage`
is too early. (Aside: `mScenarioNoOverride`@0xb64 read `256`, not `-1` — unexplained, unused here.)

**Intent clarified (Devon).** The *ideal* is a **standalone Multi-Moon collectible at Broode's
spot, no boss** — but per `ShineAppearanceHook.cpp:460-468` that moon has **no dormant actor to
reveal**; it's created on demand by an `AppearSwitchTimer` + `createLinksActorFromFactory` linked-Shine
that the **boss-defeat event** triggers. So "standalone moon" means force-triggering that AppearSwitch
or hand-spawning a `Shine` (real work + crash risk). Devon **accepted the Broode-respawn fallback**
("forcing cascade back to a scenario madame broode exists in is also fine") — provided it actually
loads scenario 1.

**v5 = force the ChangeStageInfo scenario field (built+deployed 11:03).** The `ChangeStageInfo` carries
`mScenarioNo` @ 0x1CC (the `[entrance:file] ... scenario=-1` value; -1 = "compute from quest state"
→7). That is the engine's **scenario-jump load input** — exactly what moon rocks use to load a
completed kingdom in a past scenario. `cascadeArrivalScenarioOverride` returns 1 when
dest==`WaterfallWorldHomeStage` and the Multi-Moon is uncollected, and `EntranceShuffleHook` writes it
into the info **before** `changeNextStage`'s orig, so the engine loads Cascade in scenario 1 directly
rather than recomputing. The v4 GameDataFile field write is kept post-orig as belt-and-braces.

**Test (v5):** round-trip into Cascade. Expect
`[broode-respawn] changeNextStage force Cascade arrival ChangeStageInfo.scenario -1 -> 1`, then Broode
present + fightable; beating her drops the collectable Multi-Moon (which reports the AP check). The gate
self-heals once `isGotShine(218)` flips. If Cascade **still** loads as scenario 7, the info scenario is
overridden downstream too → next options are hooking the scenario **recompute** (the `calcNextScenarioNo`
path) or going back to the standalone-moon **AppearSwitch trigger / Shine spawn**.

### v5 result + v6 fix (this session): the scenario force WORKS — the COLLECTION GATE was broken

**v5 took: Broode respawns and the Multi-Moon is collectable.** The v5 `ChangeStageInfo.mScenarioNo`
override drives the load correctly — on a round-trip into Cascade the kingdom loads in scenario 1, Broode
is present + fightable, and her Multi-Moon is obtainable. The scenario-jump-input approach (what moon
rocks use) is the right lever; the GameDataFile field write (v4) was just too early in the pipeline.

**But the force never RELEASED after collection.** The log around `00:04:14` showed the game trying to
advance Cascade to scenario 2 (post-Broode) immediately after the Multi-Moon was collected — and our hook
forcing it **back to 1**, because the collection gate still read "uncollected." So Broode lingered and the
scenario refused to advance.

**Root cause: `GameDataFile::isGotShine(int)` was fed the wrong id.** The gate called
`isGotShine(gdf, 218)` where `218` is the apworld **`shine_uid`** (the romfs `ShineInfo::UniqueId`, from
`shine_table.h`). But that `isGotShine` overload indexes by **shine INDEX**, not the unique id — so 218
never matched the Multi-Moon's collected flag and the probe returned "uncollected" forever. The actual
working "is this moon collected?" mechanism in the codebase is the **HintInfo walk** — `MoonApply.cpp`'s
`enumerateOwnedShines` reads each `GameDataFile::mShineHintList` entry's `HintInfo::isGet` flag (that walk
correctly reported the owned shine at HELLO). `isGotShine` is used **nowhere** in the working snapshot path.

**v6 = read collection via the HintInfo walk, matched by (stage, obj).** New
`smoap::game::probeShineGot(stage, obj)` (in `MoonApply.cpp`, factored onto the same
`shineHintListBase()` helper `enumerateOwnedShines` now shares) returns tri-state **1=collected /
0=uncollected / -1=unknown**, matched on `(stage_name, object_id)` — the canonical key both `shine_table.h`
and the bridge already use, sidestepping the `shine_uid`-vs-index ambiguity entirely. The hook resolves the
Multi-Moon's `(stage, obj)` = (`WaterfallWorldHomeStage`, `obj21`) at install via new
`shineRowByDisplayName()` in `shine_lookup.hpp`. Both gate sites (`forceCascadePlacementScenario` post-orig
field write **and** `cascadeArrivalScenarioOverride` pre-orig ChangeStageInfo write) now force **only** when
`probeShineGot == 0` (definitively uncollected); `1`/`-1` → don't force (fail-safe, never force forever).
The `isGotShine` symbol lookup is gone (no `BossSaveData` / no symbol dependency). `GameDataFile::isGotShine`
indexing-by-index is the load-bearing lesson — recorded in memory [[broode-respawn-scenario-recompute]].

**Test (v6):** with the same pre-Broode Cascade save, round-trip in → Broode respawns (v5, unchanged) →
beat her → collect the Multi-Moon. Expect: on the NEXT entry into Cascade, **no** `FORCE ... -> 1` line
(the gate now reads collected), Broode gone, Cascade back to its computed scenario (7). If the force still
fires after collection, check that `HintInfo::isGet` for `(WaterfallWorldHomeStage, obj21)` actually flipped
(add a one-shot `probeShineGot` log) — but the snapshot path proves the walk is sound. Build: unbuilt this
session — `build_switchmod.py` + deploy, then test.
