# Handoff prompts — 2026-07-13 playtest issues

Devon's 8 playtest observations collapse into 5 fix sessions (two observations are control
data / downstream symptoms). Ryujinx logs for all issues are committed-ready at
`docs/testing-logs/2026-07-13/`. Each prompt below is self-contained — paste it into a
fresh session as-is.

Suggested order: **Session 5 → Session 2** (the cascade-unloaded log shows Cascade being
requested at `scenario=4`, so the Session 5 scenario-state bug may be feeding Session 2's
cascade case). Sessions 1, 3, 4 are independent and can run anytime/in parallel.

---

## Session 1 — Crazy Cap shop label shows wrong kingdom's item

**Model: Sonnet 5** (contained client-side Python investigation; escalate to Opus 4.8 only
if the root cause turns out to live in the switch-mod BL-patch keying).

```
Read CLAUDE.md fully first (especially the stale-shell-mount warning — use the Read/Grep
tools for all file contents, never shell cat/grep).

BUG (playtest 2026-07-13): I purchased a Power Moon in a Crazy Cap shop. The shop slot
label said it was a Lost Kingdom Power Moon, but the check that actually got
sent/received was a Cap Kingdom Power Moon. The label and the actual location contents
disagreed.

Architecture of the shop-label channel (read these in order):
- switch-mod/src/hooks/ShopItemMessageHook.cpp — BL-patches two getSystemMessageString
  call sites in ShopLayoutInfo::updateItemPartsData; substitutes our UTF-16 label when
  the (fileName, key) pair matches a pushed entry, falls through otherwise.
- apworld/smo_archipelago/client/shop_labels.py — SHOP_LOCATION_TO_FILEKEY: the
  hard-coded {kingdom shop location → (fileName, key)} dict, populated empirically from
  discovery logs.
- apworld/smo_archipelago/client/context.py — _derive_and_push_shop_labels (~line 1303)
  and compose_shop_label_for_location (~line 1643): composes the label from Channel-A
  LocationScouts results and pushes to the Switch.
- apworld/smo_archipelago/client/switch_server.py — set_shop_labels/push_shop_labels
  (~line 416): resolves "<Kingdom>: Shopping in X" location names.

Investigate which side was wrong:
1. Was the LABEL wrong (scout/location-ID mixup: label composed for a different shop
   location than the slot actually holds)? Off-by-one or wrong-kingdom keying in
   SHOP_LOCATION_TO_FILEKEY is the prime suspect — audit every entry for collisions or
   swapped (fileName, key) pairs, especially Lost vs Cap.
2. Or was the CHECK wrong (the purchase reported the wrong AP location)? The purchased
   shine goes through MoonGetHook by (stage, obj) — cross-check the shine_table row for
   the shop stage's moon.
3. Consider entrance-shuffle interaction: shop interiors are shuffled entrance
   destinations (see docs/testing-logs/2026-07-13/lake-loaded.txt lines ~75-79, where
   entering 'LakeWorldShop' remaps to ForestWorldWaterExStage). If labels are keyed by
   the kingdom the player is standing in, but the shop UI's (fileName, key) belongs to
   the shop stage's home kingdom, a shuffled shop shows another kingdom's labels.
   Determine which key the two patched BL sites actually receive for a shuffled shop.

Also check: are there kingdoms with TWO shop location checks (regular + outfit slot)
where the label channel maps only one?

Deliverable: root cause + fix + a unit test in apworld/smo_archipelago/tests/ that
pins label↔location agreement for every SHOP_LOCATION_TO_FILEKEY entry. If the fix is
client/apworld-only, remind me to re-run `python scripts/install_apworld.py` on Windows.
Do NOT rebuild or run anything in the Linux shell against edited files. Ask me which
kingdom's shop I was standing in and for the seed's spoiler log if you need
ground truth for the scouted item.
```

---

## Session 2 — Unloaded kingdom arrivals via entrance shuffle (fell forever)

**Model: Fable 5** (hardest issue — engine world-resource internals, requires decomp
reading and careful hypothesis discipline). Opus 4.8 is the fallback if Fable is
unavailable.

```
Read CLAUDE.md fully first (stale-shell-mount warning; "READ THE DECOMP BEFORE PICKING A
HOOK CHOKEPOINT" invariant; switch-mod build loop). This is a switch-mod-side
investigation of the P5/P7 entrance-shuffle + cross-world-load machinery.

BUG (playtest 2026-07-13, two occurrences of the same signature):

Occurrence A — docs/testing-logs/2026-07-13/lake-unloaded.txt:
Entered a shuffled entrance from CapAppearExStage; remap-APPLIED sent me to
dest='LakeWorldTownZone' id='CapTrampolineB'. I arrived in Lake but the kingdom was
almost entirely unloaded. Key line (end of log):
  [p5-reswatch] resident=4 engineCurWorld=2 #16   ← MISMATCH (Lake resources resident,
                                                     engine still thinks world 2)

Control — docs/testing-logs/2026-07-13/lake-loaded.txt:
Later I re-reached Lake via dest='LakeWorldHomeStage' (EX_Water_Exit remap) and it
loaded fully. Key line:
  [p5-reswatch] resident=4 engineCurWorld=4 #18   ← match, world loaded fine.
NOTE this control log ALSO shows me collecting moons inside LakeWorldTownZone fine at
00:30 — so the TownZone stage itself can render when reached the right way.

Occurrence B — docs/testing-logs/2026-07-13/cascade-unloaded-after-leaving-taxi.txt:
Left the taxi Sherm room (ShootingCityExStage) through its entrance-side door
('taxireturn' remap → WaterfallWorldHomeStage id='WindBlowExStart'); arrived in an
unloaded Cascade and fell forever. Note in this log:
  - the Cascade load was requested at scenario=4 (request world=1 scenario=4) — possibly
    fed by a separate Cascade scenario-state bug being fixed in another session (Cascade
    was wrongly in peace with Madame Broode absent); coordinate if that fix lands first.
  - the later 'taxi' exit remap → SeaWorldWallCaveWestZone ends with
    [p5-reswatch] resident=8 engineCurWorld=1 #10 — the same resident≠engineCurWorld
    mismatch as occurrence A.

Working hypotheses to test (in rough priority order):
1. The resident≠engineCurWorld mismatch is causal: whatever consumes engineCurWorld
   (scenario/placement selection, zone streaming, world-list state) is reading a stale
   world while the p5 world-resource loader has already swapped resources. Find where
   engineCurWorld is updated in the vanilla flow (read the OdysseyDecomp sources for the
   world-list / GameDataHolder / StageResourceKeeper paths — raw URLs under
   https://raw.githubusercontent.com/MonsterDruide1/OdysseyDecomp/master/src/) and why
   the plain request(plain) REDIRECT path (see '[p5-worldreq] request(plain) REDIRECTED
   stale=2 -> 1' lines) updates resources but not the engine's current-world.
2. Zone stages as shuffle destinations: both bad arrivals landed in ZONE stages
   (LakeWorldTownZone, SeaWorldWallCaveWestZone) — zones are embedded in their parent
   home stage in vanilla. Determine whether zone-stage destinations need the parent home
   stage's world scenario/placement to be requested instead, or whether they're fine
   when engineCurWorld matches (the control log suggests the zone CAN work).
3. Scenario mismatch (occurrence B's scenario=4) independently producing empty placement.

Relevant code: switch-mod/src/game/CrossWorldLoad.{cpp,hpp} (p5-worldreq / p5-prearm /
p5-hold / p5-reswatch), switch-mod/src/hooks/EntranceShuffleHook.cpp,
switch-mod/src/game/OdysseyRescue.cpp. Prior art: docs/p7-entrance-shuffle-spike.md,
docs/devon-p7-entrance-testing-results.md.

Constraints: read the decomp BEFORE adding/moving any hook; every wrong guess costs me a
full build+deploy+in-game cycle. Propose the minimal fix, explain the causal chain
end-to-end from the log lines, and give me the exact build/deploy commands (CLAUDE.md
"Switch-mod build & deploy" section) plus a concrete in-game repro checklist for me to
validate (fly Cap→enter CapAppearExStage's shuffled exit→confirm Lake TownZone loads;
taxi-room entrance-side exit→confirm Cascade loads).
```

---

## Session 3 — Remove the vestigial "Ledge Grab" ability item (folded into Wall Slide)

**Model: Sonnet 5** (mechanical multi-file cleanup with clear grep trail and existing
tests; no switch-mod rebuild expected).

```
Read CLAUDE.md fully first (stale-shell-mount warning — use Read/Grep tools, never shell
cat/grep; regen loop: source edits do nothing until scripts/install_apworld.py is re-run
on Windows).

BUG (playtest 2026-07-13): I received "Ledge Grab" as an ability item. Ledge Grab was
removed as a distinct ability long ago — it's gated via Wall Slide on the switch-mod
side (see CLAUDE.md P4: "Ledge Grab [via Wall Slide]"). The item should not exist in the
pool at all.

Known current state (verified today):
- apworld/smo_archipelago/data/items.json line ~680 still defines a "Ledge Grab" item.
- hooks/World.py ~1190: comment says 'Ledge Grab — no longer a real ability (folded into
  Wall Slide); pending' and DEMOTE_ALL = {"Spin Throw", "Ledge Grab"} demotes it — but
  demotion clearly isn't removal; a seed placed it (tests/seeds/out/ spoiler shows
  'Ruined: Roulette Tower: Climbed: Ledge Grab').
- tests/test_ability_wire.py ~109 asserts moves_owned("Ledge Grab", ...) behavior.
- Also grep hits in client/coin_state.py, hooks/Options.py, tests/test_moon_requirements.py.

Task:
1. Confirm the intended design in docs/plan-p4-detail.md (canonical P4 ability→hook
   mapping) and docs/plan-p3-detail.md: Ledge Grab is not a pool item; the ledge-grab
   MOVE is granted by Wall Slide ownership.
2. Remove the "Ledge Grab" item from data/items.json and every pool/count surface
   (hooks/World.py DEMOTE_ALL, any Ability-category counts, duplicate→coin folding in
   client/coin_state.py, ability_state snapshot composition). Removing an item shifts
   pool size — check filler/junk balancing in hooks/World.py and any ItemValue math.
3. Sweep LOGIC for the ability: data/moon_requirements.json ability vocabulary, any
   compiled `requires` strings in data/locations.json/regions.json, and
   scripts/compile_moon_logic.py + scripts/import_moon_requirements.py vocabulary
   normalization — every LedgeGrab/Ledge Grab requirement must become Wall Slide. If
   compile_moon_logic.py would need re-running, STOP and tell me instead (it must only
   run on the machine with shine_map.json/world_scenarios.json — see CLAUDE.md).
4. Confirm the switch-mod side needs NO change: AbilityGateHook should already gate
   ledge-grab off Wall Slide and should never reference a "Ledge Grab" ability name in
   the ability_state wire snapshot. If it DOES, report it — don't rebuild the mod.
5. Update tests (test_ability_wire.py, test_moon_requirements.py, others that reference
   it) and add a guard test that fails if an item named "Ledge Grab" ever reappears in
   items.json or the generated pool.

Do not run pytest/Generate in the Linux shell against edited files — hand me the
verification steps to run on Windows (pytest, install_apworld.py, Generate.py). Note:
this changes the item pool, so old seeds/YAMLs remain internally consistent but new
seeds are required; no wire-format change expected.
```

---

## Session 4 — Ruined Kingdom arrival with no Odyssey (stranded)

**Model: Opus 4.8** (the shipped diagnostic already names the gap; the risk is in not
breaking story-managed kingdom handling — needs care, not maximal horsepower).

```
Read CLAUDE.md fully first (stale-shell-mount warning; switch-mod build loop; "READ THE
DECOMP BEFORE PICKING A HOOK CHOKEPOINT").

BUG (playtest 2026-07-13): First arrival in Ruined Kingdom via a shuffled entrance
(CityWorldHomeStage 'gunsyu' remap → BossRaidWorldHomeStage) — the Odyssey is absent.
Log: docs/testing-logs/2026-07-13/ruined-no-odyssey.txt. The shipped strand-watch
diagnostic fires and names the cause:

  [chain-arrival] dest=BossRaidWorldHomeStage kingdom=Ruined bit=11 origin_bit=0
      worldId=11 alreadyGo=0 unlocked=0 storyManaged=1
  OdysseyRescue/diag: stage=BossRaidWorldHomeStage kingdom=Ruined exist=0 activate=1
      launch=1 crash=0 level=1
  [odyssey-strand-watch] Ruined: ship owned but isExistHome=0 (derived: kingdom locked
      here) worldId=11 alreadyGo=0 chainOnlySave=0 ??? chain-listing force not covering
      this kingdom #1  (repeats, #31 by log end)

Contrast with the healthy non-story-managed path (docs/testing-logs/2026-07-13/
lake-loaded.txt, chain arrival into Lake): [chain-arrival] runs setAlreadyGoWorld
("parked flight arrival"), [chain-listing] forces mIsUnlockWorld[4]=true, and
OdysseyRescue/diag shows exist=1. For Ruined, storyManaged=1 routes arrival through the
first-visit-warp path instead ([first-visit-warp] ARMED world=11 ... 30000ms backstop)
and neither setAlreadyGoWorld nor the chain-listing unlock force covers it, so the game
derives "kingdom locked here" → no Odyssey home → player stranded with no way to leave.

Task: extend the chain-arrival / chain-listing coverage (switch-mod/src/game/
OdysseyRescue.cpp, CrossWorldLoad.*, KingdomUnlock.* — the strand-watch and chain-listing
code lives there; also hooks/HookSymbols.hpp if a new symbol is needed) so story-managed
kingdoms (Ruined at minimum — audit which others are storyManaged: likely Moon/Dark/
Darker) get a spawnable Odyssey on chain arrival, WITHOUT breaking:
  - their story scenario progression (Ruined's dragon fight is scenario-managed),
  - the first-visit warp demo handling that was deliberately armed here,
  - the M7 kingdom-order gate semantics.
Read the decomp for whatever function derives isExistHome before choosing where to
intervene. Check whether the existing 30000ms first-visit backstop is also implicated
(alreadyGo never being consumed?).

Deliverable: minimal patch + causal explanation + build/deploy commands (CLAUDE.md
switch-mod section) + an in-game repro checklist (chain-fly/shuffled-door into Ruined
first-visit; confirm Odyssey present, story intact, and that leaving works). Switch-mod
only — no apworld rebuild needed.
```

---

## Session 5 — Cascade wrongly in peace on first flight arrival (no Madame Broode) + crash on "Our First Power Moon"

**Model: Fable 5** (scenario-state semantics across save/quest recomputation, several
interacting prior fixes, and a crash whose root cause is the same state bug). Opus 4.8
fallback.

```
Read CLAUDE.md fully first (stale-shell-mount warning; the MoonRockHook peace-gating
lesson: scenario numbers are RECOMPUTED from quest state at every load, and forcing
scenario state mid-story without the peace gate skips kingdom bosses; the P2 note that
"Broode's Chain Chomp" was precollected specifically as a Cascade scenario-gating fix).

BUG (playtest 2026-07-13, two symptoms, one root cause):

Symptom 1: I flew to Cascade Kingdom for the FIRST time from Cap Kingdom. Cascade
loaded already in "peace" — no Madame Broode, story skipped. Required behavior: when
arriving by flight from Cap and Broode's Multi Moon ("Multi Moon Atop the Falls") has
NOT been collected, the Broode story scenario must be active — she stays IFF her
multi-moon is uncollected.

Symptom 2 (downstream crash): in that wrong peace state I collected "Our First Power
Moon" (obj214 — the M5.7 ground-truth anchor). Log:
docs/testing-logs/2026-07-13/cascade-crash.txt —
  MoonGetHook: reporting stage=WaterfallWorldHomeStage id=obj214
  complete_main_scenario_event world_id=1 main_scenario_no=1 / ScenarioFlagHook: scenario_no=1
  ...18s later, null-deref crash:
  PC => StageTalkDemoNpcCap::tryStartDemo(), LR => StageTalkDemoNpcCap::startDemoFromScene()
  called from StageScene::exeDemoShineMainGet — Invalid memory access at 0x0.
In vanilla scenario 1, collecting that story moon plays a main-get demo where Cappy's
NPC talks; in the wrongly-loaded peace placement that demo NPC doesn't exist → null
deref. Fixing the scenario state should make this unreachable, but evaluate whether a
cheap defensive null-guard at the tryStartDemo call site is ALSO warranted (read the
decomp for StageScene::exeDemoShineMainGet / StageTalkDemoNpcCap first — CLAUDE.md
invariant — and remember any such guard must not mask real story regressions).

Corroborating data: docs/testing-logs/2026-07-13/cascade-unloaded-after-leaving-taxi.txt
shows a later arrival requesting Cascade at scenario=4 ([p5-worldreq] request world=1
scenario=4) — consistent with the save's Cascade quest state reading as story-complete.

Investigate WHERE Cascade's quest state got marked complete for a first visit:
1. The chain-arrival flight path: lake-loaded.txt shows chain arrivals call
   setAlreadyGoWorld ("parked flight arrival, not buried first-visit demo") — does any
   part of that (or KingdomOrderGate / first-visit-warp suppression) also advance or
   mask Cascade's main scenario progress?
2. multi_moon_shuffle: the 14 story-boss Multi Moons ride the pool (PM-first demotion
   variant). Does receiving/holding a "Cascade Multi Moon" AP ITEM — or the m6
   OutstandingMsg kingdom-balance replay — write anything the scenario recomputation
   reads as "Broode beaten"? (M6 phase D invariant: Moon items are skipped in replay
   precisely because OutstandingMsg is authoritative — check the scenario side has the
   same discipline.)
3. The Broode's Chain Chomp precollect + peace-gated MoonRockHook interplay: is the
   peace gate deriving "peace" from a signal that a fresh, never-visited Cascade save
   already satisfies (e.g. moon COUNT rather than scenario/quest flags, with AP-granted
   moons inflating it)?
4. ScenarioFlagHook and the scenario chosen by p5-prearm at first arrival (the crash log
   shows scenario_no=1 being COMPLETED by the moon get — so the game thought scenario 1
   was active for quest purposes while the LOADED placement was peace; that divergence
   is the core of the bug).

Relevant code: switch-mod/src/hooks/{ScenarioFlagHook,MoonRockHook,WorldMapSelectHook}
.cpp, switch-mod/src/game/{KingdomOrderGate,KingdomUnlock,CrossWorldLoad,OdysseyRescue},
apworld hooks/World.py (multi-moon + precollect), client context.py
(_process_received_items / OutstandingMsg). Prior art: docs/milestones.md M6 phase D +
M7 Path A, docs/handoff-refight-multi-moons.md, MoonRockHook.cpp header (cap-peace
experiment postmortem).

Constraint reminders: NEVER force scenario state while a moon-rock scenario is active;
the goal-detection wiring (CreditsStartHook) must not be touched; propose the minimal
fix and identify which tier it lives in (switch-mod vs apworld/client — they have
independent rebuild loops, see CLAUDE.md). Deliverable: causal chain from logs, patch,
build/verification commands for Windows, and an in-game repro checklist (fresh seed,
fly Cap→Cascade first, confirm Broode present + story moons collectable + no crash on
"Our First Power Moon"; then beat Broode and confirm peace/moon-rock behavior intact).
```

---

## Model summary

| Session | Issue | Model | Why |
|---|---|---|---|
| 1 | Shop label wrong kingdom | **Sonnet 5** | Contained client-side mapping audit with a clear code trail |
| 2 | Unloaded arrivals / fell forever | **Fable 5** | Engine world-residency internals, decomp reading, costliest wrong guesses |
| 3 | Ledge Grab item removal | **Sonnet 5** | Mechanical cleanup, existing tests, no switch-mod rebuild |
| 4 | Ruined no Odyssey | **Opus 4.8** | Diagnostic already pinpoints the gap; care > horsepower |
| 5 | Cascade peace/Broode + obj214 crash | **Fable 5** | Cross-tier scenario-state semantics touching several load-bearing invariants |
