# Future feasibility — master index

This is the top-level index of "could we add X?" feasibility assessments for the
SMO Archipelago project. Each idea gets a **full detailed write-up in its own
`future-feasibility-<slug>.md`** doc; this file holds the one-paragraph summary
and a feasibility rating so a future session can triage at a glance without
re-reading every detail doc.

These are **reconnaissance, not committed plans**. A high rating means "looks
achievable with the effort noted," not "scheduled."

## Rating legend

- **Feasibility %** — rough odds the feature can be built as described without
  hitting a wall that kills it. Not a confidence interval; a gut estimate from
  the recon.
- **Effort** — relative build cost once started (low / medium / high).

## Summary table

| Idea | Detail doc | Feasibility | Effort |
|---|---|---|---|
| Strip Cappy's inter-kingdom flight commentary | [future-feasibility-strip-cappy-commentary.md](future-feasibility-strip-cappy-commentary.md) | **70%** | Medium |
| Moon recolor (by granted kingdom + AP class) + purple-coin model swap | [future-feasibility-moon-colors-and-coin-models.md](future-feasibility-moon-colors-and-coin-models.md) | recolor **95%** / coin models **~55%** | Small / High |
| Randomize all background music | [future-feasibility-bgm-randomizer.md](future-feasibility-bgm-randomizer.md) | **70%** | Medium |
| Warp paintings always available (not randomized) + in logic | [future-feasibility-warp-paintings-always-open.md](future-feasibility-warp-paintings-always-open.md) | **70%** | Medium |
| Show AP check name (+ owning player) in story-moon REVEAL cutscene | [future-feasibility-story-moon-check-name.md](future-feasibility-story-moon-check-name.md) | **65%** | Medium |
| Shopsanity (golden / purple / full) | [future-feasibility-shopsanity.md](future-feasibility-shopsanity.md) | **75%** | High |
| Odyssey always present + boardable in any visited overworld | [future-feasibility-odyssey-always-available.md](future-feasibility-odyssey-always-available.md) | **85%** | Low–Med |
| Relocate a save to Cap Kingdom in its peace state (Odyssey landed) | [future-feasibility-save-relocate-to-peace-kingdom.md](future-feasibility-save-relocate-to-peace-kingdom.md) | ✅ **COMPLETE** (2026-06-28) | — |
| Decoupled / chained entrance randomizer (full any-to-any) | [future-feasibility-decoupled-entrance-randomizer.md](future-feasibility-decoupled-entrance-randomizer.md) | **65%** | Very High |

---

## Strip Cappy's inter-kingdom flight commentary

**70% · Medium effort.** Suppress the forced Cappy "discussion" sections during
Odyssey flights between kingdoms (the commentary you have to spam to skip);
skippable cutscenes stay. The target is **`exeDemoWorldComment()`**, an isolated
nerve state in `StageSceneStateWorldMap`, separate from the world-open/unlock/
select states — which is what makes it look suppressible without breaking the
arrival or world-reveal. It's spam-skippable in-game, so the clean approach is to
hook the state and invoke the game's own existing skip/finish path on entry
(follows our "trigger the existing exit, don't invent a nerve transition" rule).
The catch: **`StageSceneStateWorldMap.cpp` is NOT in OdysseyDecomp** (only the
header), so the gate and exit path must be read from a Ghidra/objdump pass on
`main.nso` rather than a quick decomp read — that's the bulk of the effort and the
reason it's not a slam-dunk. The post-game auto-disable hints a gate exists but
may route through entirely different code (free vs. story flight), so don't bank
on copying it. Full write-up:
[future-feasibility-strip-cappy-commentary.md](future-feasibility-strip-cappy-commentary.md).

---

## Free Lake/Wooded detour with a combined "both" gate

**80% · Medium effort.** Open up the first main-path detour so that after leaving
Sand you can fly the Odyssey **freely between Lake and Wooded** (either order, like
any earlier kingdom) instead of being forced Lake-first, while requiring the
**minimum moon counts from BOTH** before moving on past the detour (toward Cloud /
Lost). The forced order lives in two tiers and both need touching. The **apworld
logic** side is easy: rewrite the detour edges in `regions.json` so both kingdoms
hang off Sand and the onward edge requires `{KingdomMoons(Lake,8)} and
{KingdomMoons(Wooded,16)}` — `KingdomMoons` already returns composable
requires-strings and honors rolled gate values. The **switch-mod** side has two
parts: (1) free travel is likely a **one-rule deletion** in `KingdomOrderGate`'s
`kRules` (the [[kingdom-order-gate-premature-destinations]] memory shows the map
frontier is already wide open and only the BACKSTOP redirect forces Lake-first),
with the already-resolved `unlockWorld()` primitive as a proven fallback; and (2)
the in-game "both before Cloud" gate, the only genuinely new logic — `UnlockShineNum`
is single-kingdom so it can't natively express "need two other kingdoms," but a
guaranteed **logic-only fallback** works, and a true in-game gate reuses existing
per-kingdom counts (`ShineNumByWorldGetHook`/`ap_moons_kingdom`), existing rolled
thresholds (`kingdom_gate[]`), and the existing `KingdomOrderGate` chokepoint. The
points off are an unverified map-frontier assumption and needing to confirm which
warp path actually enters Cloud (cutscene vs. map pick) before wiring the full gate.
Both pairs (Lake/Wooded → Cloud and Snow/Seaside → Luncheon) are now built and in-game; the
free crossing is delivered by zeroing the **current-world** `findUnlockShineNum` for the four
detour kingdoms (the proven lever — an `isUnlockedNextWorld` force-true experiment was a dead
end, see iteration 5). **Known cosmetic + deferred follow-up:** the in-kingdom takeoff gauge
reads "0 / full" for free-launch kingdoms because that gauge and the leave-gate are the same
`findUnlockShineNum` read (the "needs N more" number *is* the gate's deficit). The world-map
globe label still shows the true rolled count. Showing the real count on the in-kingdom takeoff
prompt too would require a dedicated message-string hook (à la `ShopItemMessageHook`) to
decouple display from gate — low priority, written up in the detail doc's iteration-5 follow-up.
Full write-up:
[future-feasibility-lake-wooded-free-detour.md](future-feasibility-lake-wooded-free-detour.md).

---

## Moon recolor (by granted kingdom + AP classification) (COMPLETE) + purple-coin model swap

**Recolor ~95% (small) · Coin-model swap ~55% (high).** The updated form of the
original plan's **P5**, with two very different halves. **Recolor** tints each AP-check
moon by meaning: SMO moon items get the **granted moon's kingdom** color (color by the
moon it's *for*, not where it sits), and foreign-game items get green/yellow/grey/red
for progression/useful/junk/trap. This half is nearly done already — the whole
per-check tint pipeline ships (`ShineAppearanceHook.cpp` trampolines `Shine::init` and
tints by a per-location palette index from `ShineScoutsMsg`; the client already
classifies items and knows each item's kingdom via `maps.py`). It only needs the
palette tables extended (16 kingdom colors + yellow/grey added; useful→yellow,
junk→grey remapped) and the client emitting the kingdom index for own moons — exactly
the scoped P5. Keying on the *item's* kingdom even sidesteps the cross-kingdom-subarea
caveat the plan flagged. **Coin-model swap** (replace the moon model with a moon-sized,
recolored per-kingdom purple-coin model) is a different, deferred class of problem:
it's a 3D model/actor swap, the **Shine actor is undecompiled** (no `Shine.cpp` in
OdysseyDecomp — needs a `main.nso` disasm of `init`/`tryChangeCoin`/`exeCoin`), the
per-kingdom regional-coin model archives must be found via an **IP-sensitive romfs
hunt** on Devon's machine (incl. the unused Ruined model), and it carries real
unknowns (cutscene surface, archive memory/availability outside home kingdom). It has
real seams though — `Shine.h` exposes `hideAllModel()`/`getCurrentModel()` and SMO
already renders collected shines as coins internally (`exeCoin`), giving a couple of
candidate routes. Recommend shipping the recolor as P5 and treating the coin models as
a separate later spike, gated on two scope questions (true per-kingdom coin *shapes* vs.
a recolored generic coin; in-world-only vs. also the get-cutscene). Full write-up:
[future-feasibility-moon-colors-and-coin-models.md](future-feasibility-moon-colors-and-coin-models.md).

---

## Randomize all background music

**70% · Medium effort.** Shuffle every BGM track (kingdom/sub-area/boss themes) so a
different one plays in each spot; SE and voice untouched. The **hook is minor** — BGM
is cleanly **string-keyed** (`al::startBgm(user, "StmRsBgm…", …)` is the single funnel,
confirmed in the decomp), so randomizing is a one-function "lie to the game" rewrite of
the name argument, byte-for-byte the entrance-shuffle pattern. What makes it Medium is
the supporting work, not the seam: you must **enumerate the valid BGM name set** (it
lives in the sound archive's `SoundItem` tables → a romfs extraction, IP-sensitive and
therefore gitignored, but a *known model here* — generate a seeded `bgm_table.h` exactly
like `shine_table.h`/`capture_table.h`). Three real gotchas hold it below 90%: (1)
**music-synced moons** — the New Donk festival "Jump Up, Super Star!", jump-rope,
beach volleyball, band sections etc. are timed to their track, so a blind shuffle
desyncs them; needs a curated blocklist (Devon-supplied, like the scenario-advancer
audit); (2) **interactive layering** — SMO fades per-situation layers (`startBgmSituation`)
into the *active* track, so a swapped track loses the original's dynamic layers (graceful
no-op, but less rich); (3) **stream residency + the demo path** — confirm a foreign
track isn't silent in another area and that cutscene-locked `DemoSyncedBgmCtrl` music
(which likely bypasses `al::startBgm`, probably desirably) is handled. No logic
involvement and no item re-seed — it can be a switch-mod-only feature on a `randomize_music`
toggle + seed. First step: a one-build hook+log spike that swaps two overworld tracks,
confirms it plays/doesn't crash/isn't silent, and harvests the name list. Full write-up:
[future-feasibility-bgm-randomizer.md](future-feasibility-bgm-randomizer.md).

---

## Costume doors always unlocked (no outfit required) - COMPLETE

**75% · Medium effort.** Make the seven fitting-room "costume doors" (the locked
doors to each kingdom's `*WorldCostumeStage`, which vanilla only opens while Mario
wears the required regional hat + outfit) **always open**. Motivated by the entrance/
shop shuffle: the demanded outfit is normally bought at that kingdom's Crazy Cap, so
once shops are shuffled it can become circular to obtain — and sharply, **under
entrance shuffle the destination mapped *behind* a costume door inherits the outfit
gate**, so a hard-to-get outfit can strand a shuffled destination, not just the
fitting-room moon. Key finding: this is **switch-mod-only, no re-seed** — the apworld
logic tier needs *zero* change because the costume-room moons already carry **no
outfit requirement** in `moon_requirements.json` (pure movement/capture), so the fill
already assumes them reachable without the outfit; always-open doors just makes the
game match what the logic already believes. The work is one in-game gate: the doors
are `DoorWarpStageChange` actors that compare the worn cap+cloth
(`getCurrentCostumeTypeName`/`getCurrentCapTypeName`) before firing the
`changeNextStage` our shuffle already hooks — i.e. the condition sits strictly
*upstream* of the existing chokepoint, so it must be cracked at the door itself. The
recommended path is one trampoline forcing the door's warp-condition true (same
"force-suppress a decision" pattern as `CaptureGate`/`AbilityGateHook`/
`KingdomOrderGate`); because all seven doors share one generic, data-driven actor
class, a **single hook fixes them all**. The points off: `DoorWarpStageChange` is
**not in OdysseyDecomp** (only the switch-gated `DoorCity`/`DoorSnow` are), so a
`main.nso` sail/disasm pass is needed to locate the condition method, with a residual
chance it's inlined — mitigated by a byte-patch fallback and by the actor being
generic/reused (which favors out-of-line, hookable code). Start with a logger-only
spike to confirm the seam before building. Full write-up:
[future-feasibility-costume-doors-always-open.md](future-feasibility-costume-doors-always-open.md).

---

## Warp paintings always available (not randomized) + in logic

**70% · Medium effort.** SMO's ~10 **warp paintings** transport Mario to an isolated
moon-platform in a *different* kingdom; vanilla only opens a painting once its
destination kingdom is unlocked (Metro/Luncheon/Mushroom are early-view exceptions).
Devon wants them **left vanilla (NOT shuffled)** but **always usable from the start**,
with that access **reflected in logic**. The recon is unusually favorable: warp paintings
are a **named, data-driven** SMO subsystem (`WorldWarpHole`), and the seams are far better
than the other "undecompiled actor" docs here. The availability gate is a **named
predicate** — `GameDataHolder::checkIsOpenWorldWarpHoleInScenario(worldId, scenarioNo)` —
so "always open" is the well-trodden *force-a-decision-true* trampoline (one hook covers
all paintings); the transition commit `tryChangeNextStageWithWorldWarpHole` is **already
hooked in this project** ([WorldMapSelectHook.cpp](../../switch-mod/src/hooks/WorldMapSelectHook.cpp),
"visited-only, no gate"), confirming the funnel; and the **fixed source↔destination
mapping is an enumerable data table** (`WorldWarpHoleInfo[]` +
`calcWorldWarpHoleDestId`/`tryCalcWorldWarpHoleSrcId` in
[GameDataHolder.h](../../switch-mod/lib/OdysseyHeaders/game/System/GameDataHolder.h)), so
the logic edges can be built exactly without randomizing anything. The logic side
re-gates each painting's destination-area moon on its **source** kingdom (regions.json /
`KingdomMoons` requires, **not** `canReachRegion` per [[region-gating-egress-off-by-one]]) —
a regenerate, but it only ever *loosens* reachability. Paintings are already **excluded
from entrance shuffle** (the extractor's `DOOR_UNITS` doesn't include `WorldWarpHole`), so
"not randomized" is free. It's *provably possible* — three paintings already behave this
way in vanilla. Points off (→70%): the dominant unknown is whether the **seven non-early
destinations load cleanly when their kingdom was never visited** (may narrow always-open
to a curated subset); plus an unverified inlining risk on the predicate, and logic
care-work for the **scenario-variant destinations** (Lake-first vs. Wooded-first), the
normally-post-game Cascade→Bowser's painting opening early, and the existing warp hook's
**visited-bit side effect** perturbing the kingdom-order gate
([[kingdom-order-gate-premature-destinations]]). First step: a one-build force+log spike
on a normally-late painting answers the two gating unknowns at once. Full write-up:
[future-feasibility-warp-paintings-always-open.md](future-feasibility-warp-paintings-always-open.md).

---

## Show AP check name (+ owning player) in story-moon REVEAL cutscene

**65% · Medium effort.** Story moons play a *reveal* cutscene (the camera pan showing
where the newly-spawned moon is, with a name banner — e.g. "Atop the Highest Tower
(Sand)"). Devon wants the **AP check identity** added to that banner: the item the
check holds, plus the owning player when it routes to another world (same line, or a
smaller second line under the underline). **Important: this is the REVEAL moment, not
COLLECTION** — and that's the whole difficulty. The *at-collection* banner is **already
AP-aware** (the shipped Channel-A [MoonLabelHook.cpp](../../switch-mod/src/hooks/MoonLabelHook.cpp)
substitutes the `TxtScenario` pane via `al::setPaneStringFormat`, with the bridge
composing "Got X!" / "Sent X to Y" incl. the recipient in
[display.py](../../apworld/smo_archipelago/client/display.py)). So **every rendering
primitive is proven** — pane substitution, label composition with the owning player,
font sanitization. What the reveal path does *not* inherit is (1) the **trigger** — the
reveal is a separate, **un-decompiled** scene state with no hook yet, needing a
`main.nso` symbol/decomp pass to find (the get states are clean `exeDemo*` siblings, a
good prior); and (2) **pre-collection text delivery** — the existing `MoonLabel` text is
produced by the *collection* Check/`seq` round-trip and doesn't exist until you grab the
moon, so the reveal must be fed from the **scout cache**, which today ships **color only**
(`ShineScoutsMsg` = `{shine_uid, palette}`). That means extending the scout push with a
per-uid label string + a Switch-side by-uid store (exact structural precedent: the
recolor path in [ShineAppearanceHook.cpp](../../switch-mod/src/hooks/ShineAppearanceHook.cpp)
already resolves `Shine → unique_id → per-uid fact`). Augment-not-replace (keep the
vanilla name, add the AP caption on a second pane) + the 30-byte budget round out the
work. Switch-mod + client + wire-struct change → apworld rebuild, no re-seed (cosmetic).
First step: a logger-only spike to find/confirm the reveal scene state and dump its
layout for a sub-pane. Full write-up:
[future-feasibility-story-moon-check-name.md](future-feasibility-story-moon-check-name.md).

---

## Shopsanity (golden / purple / full)

**75% · High effort.** A `shopsanity` YAML option turning Crazy Cap shop slots into AP
checks: **golden** shuffles the gold-coin shop's outfits (skipping the Life-Up Heart +
already-shuffled Power Moon) as filler, **purple** shuffles each kingdom's regional
purple-coin outfits/stickers/trophies as filler (except 11 hat+outfit pairs that gate
specific moons — those stay as **useful** items with a logic rule on their moon), and
**full** does both; optional cost randomization. The decisive finding: the Switch-side
purchase detection — usually the make-or-break for shopsanity — is a **solved shape**
in SMO's *decompiled* [ClothUtil.h](../../switch-mod/lib/OdysseyHeaders/game/Util/ClothUtil.h):
`buyItem(ItemInfo*)`/`buyItemInShopItemList` are clean purchase chokepoints,
`isBuyItem`/`isHaveCloth` + the four catalogs (`getClothList`/`getCapList`/`getGiftList`/
`getStickerList`) give snapshot/replay, and `buyCloth` grants outfits on AP receipt;
`ShopLayoutInfo`'s `ItemType { Cloth, Cap, Gift, Sticker, UseItem, Moon }` tags slots.
The apworld already models the shop Power Moon as a location, so "shop slot = check" is
a known shape. What makes it high-effort is **breadth, not depth**: it spans a new
option + locations + items + logic, a new `CheckMsg` shop kind, a new gitignored
`shop_table.h` + extractor (the shine_table/capture_table analogue), a snapshot/replay
extension, and a grant path. Main risks: accurately enumerating shop slots and their
**progressive unlock timing** (the golden shop's catalog opens as you reach kingdoms —
`getWorldNumForNewReleaseShop` keys this; Devon will supply lists), the in-game gating
of the 11 outfit-moons so the useful-item gate isn't bypassed by simply buying the slot,
and the usual verify-`buyItem`-isn't-inlined. Recommend doing **purple first** (bounded,
self-contained, exercises the whole new tier), then golden (adds the unlock-timing
logic), with a `ClothUtil::buyItem` hook + `shop_table` extractor spike up front to
de-risk the identity mapping. Full write-up:
[future-feasibility-shopsanity.md](future-feasibility-shopsanity.md).

---

## Odyssey always present + boardable in any visited overworld

**85% · Low–Medium effort.** No matter which overworld kingdom Mario is in — as long
as it's one he's already **visited/unlocked** — the **Odyssey must be parked and
boardable** so he can always open the world map and fly back. First a **safety net**
(Devon hit a seed where he landed in **Bowser's Kingdom overworld extremely early with
no Odyssey present** — collecting a moon would have stranded the save; only a hard reset
escaped), and second a **prerequisite for full entrance randomization**, where a shuffled
door/pipe can drop you into an overworld at a scenario state the vanilla arrival flow
never produces. The recon is unusually favorable because this is a **near-direct
generalization of the already-shipped, in-game-validated `OdysseyRescue` module**
([OdysseyRescue.cpp](../../switch-mod/src/game/OdysseyRescue.cpp)), which today force-repairs
the Odyssey in *one* kingdom (Lost) from a throttled per-frame `drawMain` sweep
([main.cpp:230-239](../../switch-mod/src/main.cpp#L230)) by calling SMO's own named state-machine
functions. The Odyssey ("Home") is a **fully-exposed named state machine** —
`isExistHome`/`isActivateHome`/`isLaunchHome`/`isCrashHome` + `activateHome`/`launchHome`/
`repairHome` ([GameDataFunction.h:454-466](../../switch-mod/lib/OdysseyHeaders/game/System/GameDataFunction.h#L454)) —
and both supporting signals the generalization needs already ship: a **sticky visited
bitset** (`ApState::visited_kingdoms`, the M7 order-gate's signal) and an **overworld-stage
classifier** (`kingdomShortFromHomeStage`). So the work is **switch-mod-only** (no apworld /
logic / re-seed / wire change): widen the sweep to "force the Odyssey boardable in any
visited overworld," add ~4 trivial same-shape symbols, and — the careful part — **gate it**
so it never stomps the legitimate grounded states (Cap/Cascade pre-acquisition guarded by
`getHomeLevel>0`, Lost via the existing repair branch, Ruined via the dragon's pinned
Multi-Moon). The points off (→85%) are the one real in-game unknown: whether setting the
save-state flags makes a not-yet-spawned Odyssey appear **this frame** vs. only on the next
stage load (middle case still fixes the strand via a cheap self-reload like `MoonRockHook`'s;
worst case needs a `main.nso` read of the home-ship actor's appear condition), plus
confirming `activateHome`-vs-`launchHome` is what gates boardability and that no forced flag
perturbs the kingdom-order/peace accounting. First step: a logger-only spike that dumps the
`*Home` flags in the stranded Bowser overworld vs. a normal one — that single trace decides
the fix shape. This is also the **landing-safety backstop** the full any-to-any entrance
randomizer (below) lists as a top risk. Full write-up:
[future-feasibility-odyssey-always-available.md](future-feasibility-odyssey-always-available.md).

---

## Relocate a save to Cap Kingdom in its peace state (Odyssey landed) — ✅ COMPLETE (2026-06-28)

**DONE — via a third path, not the Approach B this recon recommended.** The
deliverable exists: a real save loading into **post-peace Cap with the Odyssey landed
and 0 moons collected**. It was reached **by ordinary play behind temporary mod
levers**, not by editing the save (A) or runtime `initializeData` surgery (B): a
single-flag bootstrap (free Cascade takeoff at 0 moons + forcing Cascade's pre-Broode
placement scenario to **7/world-peace** so the buried Odyssey loaded parked + globe-
usable, Multi-Moon untouched) let Devon glitch OOB to the buried Cascade Odyssey, fly
Cascade → … → Cap, and **save in Cap**. Because the save is the product of a genuine
flight, the per-load scenario recompute, peace accounting, and AP deposit state are all
self-consistent for free — the exact consistency hazard that downgraded the editing
approach never arises, and the Cascade "post-peace ⇒ landed Odyssey" corollary was
confirmed in-game. All bootstrap scaffolding has been **reverted** (Cascade's pre-Broode
force is back to scenario 1 = Broode present + Multi-Moon collectable). **This produced
one save artifact, not a startable feature** — the natural follow-up is a YAML option to
make Cap-peace a sphere-0 start for any player (handoff:
[handoff-cap-peace-sphere-0.md](../handoff-cap-peace-sphere-0.md)). Full write-up
(method + revert):
[future-feasibility-save-relocate-to-peace-kingdom.md](future-feasibility-save-relocate-to-peace-kingdom.md).

---

## Relocate a save to Cap Kingdom in its peace state (Odyssey landed) — original recon (HISTORICAL)

**70% · High effort (Cascade-landing corollary ~80%).** Take a minimally-progressed
real save (Cap prologue + opening miniboss done, flown to Cascade, **zero moons**) and
transform it so Mario loads **standing back in Cap Kingdom with its story-complete/peace
state set and the Odyssey parked alongside**. The real prize is the corollary: with the
Odyssey in a post-peace (launched) state, **flying onward to Cascade finds it already at
its landing pad** rather than grounded in the rocks (the pre-departure pose), which
dissolves a genuine softlock — you can reach Cap from Cascade, but a grounded Cascade
Odyssey strands you there. The investigation collides with a constraint the project
**already proved**: in the `kCapPeaceFromStart` experiment
([MoonRockHook.cpp:68-76](../../switch-mod/src/hooks/MoonRockHook.cpp#L68)) a kingdom's
scenario number — and thus its peace state and the Odyssey's grounded-vs-landed pose — is
a **derived value, recomputed from quest state at every stage load**. *But the Moon → Cap
correction (Devon, 2026-06-22) turns that wall into a tailwind for the destination:* on a
save where Cap's prologue is **genuinely complete**, Cap's quest source-of-truth already
reads done, so the recompute lands Cap at its ≈peace revisit value **on its own** — and
there's no scripted intro left to break (the exact failure that killed the *fresh-save*
experiment). Cap is the lowest-coupling kingdom — no game-clear / AP-win entanglement
(which is what would have made *Moon* the worst case). The half that still costs: the
Odyssey isn't in Cap during the prologue (you first board it in Cascade), so "Odyssey
alongside in Cap" requires **forcing the Odyssey launched** — i.e. forcing Cascade's
departure/peace, the *same* lever the corollary needs and the fiddly recompute-bound part.
The recommended path is **not** offline `.bin` editing (Approach A: version-locked, no
committed format map, bypasses the AP deposit/outstanding accounting) but a **runtime
"state surgery on load" hook** (Approach B) — exactly the "new-save state surgery via
`initializeData` post-hook" the MoonRockHook header already scoped. That chokepoint is
**already hooked** ([SaveLoadHook.cpp](../../switch-mod/src/hooks/SaveLoadHook.cpp)), and the
writers (`setMainScenarioNo`/`unlockWorld`/`activateHome`/`launchHome`/`meetCap`/
`findKoopa`/`startWorldTravelingPeach`) are all named SMO functions the project already
calls — set the source-of-truth bits and the recompute *agrees* (the proven "write the
bit, don't hook the reader" pattern). The **Cascade corollary is the higher-confidence
sub-result (~80%)**: post-peace = landed-Odyssey is documented behavior. Points off
(→70%): forcing Cascade launch quest-consistently is the recompute-bound part where the
original experiment died; AP-consistency constrains the whole thing; and a couple of
small Cap-revisit unknowns (spawn/checkpoint, the Cap Spark-Pylon exemption on revisit).
**Recommendation: prove it on Cap directly** (it's the target *and* lowest-risk), then
force the Odyssey launched and verify the landed-pad pose in Cap and a subsequent Cascade
flight — and do *not* hand-edit `File1.bin` (Devon keeps `.bk` backups so experiments are
reversible, but Approach B is the real answer). Full write-up:
[future-feasibility-save-relocate-to-peace-kingdom.md](future-feasibility-save-relocate-to-peace-kingdom.md).

---

## Decoupled / chained entrance randomizer (full any-to-any)

**65% · Very High effort.** Evolve the shipped P7 coupled door→interior bijection into
a **full port randomizer**: a subarea's exit need not return to its origin overworld
(so leaving B can drop you into C, forming **chains**), traversal is **path-symmetric**
(A→B→C ⟹ C→B→A), and overworlds join the pool as endpoints (enter Poison Tides, wind up
in Luncheon). This is exactly the "full any-to-any" rework the existing P7 design and the
`entrance-from-parent-fix-deferred` memory both flagged as deferred. The right model is an
**undirected port matching (involution)** — and crucially, chaining + symmetry fall out of
it *for free*, and it's a cleaner model than today's directed bijection. The big
encouragement: the costly, already-validated Switch machinery **survives** — the
ChangeStageInfo "lie to the game" rewrite, the moon-rock guard, the chunked full-overwrite
wire table, and (because each exit port still maps to one destination) the **precomputed
return that sidesteps save/load origin tracking** all carry over; chaining adds rows, not
new mechanism. What must be rebuilt is heavy though: enumerate every port incl. overworld
door-mouths (re-run the extractor, split the conflated Costume Room / Sphynx Vault nodes), a
**connectivity-guaranteed matching** so a random involution doesn't strand regions, a
**general-graph reachability** model with asymmetric per-direction edge rules (forward = door
gate; reverse = reach-the-exit interior reqs), and a **compound exit key** on the Switch
(the already-scoped `from_parent` fix). Two real risks hold it at 65%: the **in-game unknown**
of landing in an overworld via a door/pipe rather than the Odyssey flight (strongly mitigated
by routing overworld arrivals through *existing* door-mouth exits — a known-good transition —
rather than a synthetic arrival), and the **kingdom-order collision** (Devon's "reduce the
early bottleneck" goal deliberately breaks the flight-order progression the order gate, peace
gates, and moon-pipe gating all assume). Recommend a one-build spike first — hand-author a
single exit→foreign-door-mouth row and confirm in-game that Mario lands in another kingdom's
overworld in a usable state; that binary result gates the whole feature. Full write-up:
[future-feasibility-decoupled-entrance-randomizer.md](future-feasibility-decoupled-entrance-randomizer.md).
