# P5 — cross-world load crashes + chain-return hardening (design)

> **STATUS 2026-07-12 — read §12 first.** All P5 code is shipped and the
> crash class is closed in-game (§10.3 walk clean; §11.1 verified). §§1–10
> are historical design/triage — skip unless debugging a regression. The
> only open items are the §12.2 verification signals, which ride the next
> full seed-gen playtest (steps in §12.1).

Written 2026-07-08 after Devon's cold-repro walk confirmed finding 10 and
surfaced the Swinging Along the High-Rises crash. Decomp reads done per the
CLAUDE.md rule BEFORE any seam was picked; citations inline. Companion to
[plan-decoupled-entrances.md](plan-decoupled-entrances.md) (P4 findings 10–13)
and Devon's 2026-07-08 rulings:

- Paying a chain-reached kingdom's rolled gate NEVER legitimizes
  story-forward travel from it.
- Finding 12: stop calling `unlockWorld`; find a listing-only seam.
- Globe should list only visited kingdoms (hide the rest).

## 1. The crash class — what the decomp actually says

### 1.1 Observed crashes (all: FileLoadThread, `ParallelSZSDecompressor::
tryDecompFromDevice` → heap `tryAlloc` abort during `ResourceMgr::tryLoad` /
`al::ArchiveEntry::load`)

| Log | Origin → final target | Heap that aborted | When |
|---|---|---|---|
| 2026-07-07 + PBP-cold-crash.txt (COLD, fresh boot) | `PushBlockExStage` exit → `CityWorldHomeStage` (`donsuke`) | `sead::FrameHeap` | ~4 s after commit, mid-load |
| metro-swinging-crash.txt (deterministic, every entry) | `CapWorldHomeStage` pipe → `PoleGrabCeilExStage` (`tenjo`, = "Swinging Along the High-Rises", Metro subarea) | `sead::ExpHeap` | ~10 s AFTER arrival, while streaming |
| Control (same session as cold crash) | `SandWorldHomeStage` shop door → `CityWorldHomeStage` (`bikereturn`) | — clean | — |
| Control | every Odyssey flight into Metro | — clean | — |

Finding 10 is therefore **cold-reproducible → P5 is in scope** (Devon's
condition), and the class is **wider than overworld targets**: a foreign-world
INTERIOR target crashes too (ExpHeap variant). Scenario is NOT the variable
(the cold repro carried `scenario=-1` end to end).

### 1.2 World resources are per-world, swapped only on a detected world change

`src/Sequence/WorldResourceLoader.cpp` (OdysseyDecomp, read 2026-07-08):

- Each world's shared assets load async into a dedicated
  **WorldResourceHeap**; `requestLoadWorldHomeStageResource(loadWorldId,
  scenario)` early-returns when `mLoadWorldId == loadWorldId` (cached
  per-world), destroys the old heap, and reloads from the
  `SystemData/WorldList` → `WorldResource` byml lists.
- The loader is owned by `HakoniwaSequence` (`mResourceLoader`), which has the
  dedicated sequence states `exeLoadWorldResource` /
  `exeLoadWorldResourceWithBoot` — the flight loading screen (the percent bar
  is literally `calcLoadPercent()`).

So a stage load is only safe when the destination world's resident set is (or
is being) loaded. Assets missing from the resident set fall back to per-stage
loads into the scene-scope heaps — fine for a small delta, fatal for a Metro
delta.

### 1.3 The next-world decision cannot see subarea targets — decomp-confirmed

`GameDataFunction::calcNextWorldId(accessor)` =
`worldList->tryFindWorldIndexByMainStageName(getNextStageName())`
(GameDataFunction.cpp:1686). `ByMainStageName` matches **HomeStage names
only** — for a subarea target it returns **-1**. In vanilla that's a safe
invariant ("a subarea always belongs to the current world"); the decoupled
remap breaks exactly this invariant. This is the confirmed mechanism for the
Swinging crash: `PoleGrabCeilExStage` from Cap resolves no world → no
world-resource swap → City-sized assets stream into scene heaps → ExpHeap
abort. Deterministic, matches "crashes every time I enter it."

(`WorldList::tryFindWorldIndexByStageName` — the NON-main variant that DOES
resolve subareas via each world's `stageNames` list — exists one line below in
the same class. The engine deliberately uses the cheap main-stage variant at
this seam.)

### 1.4 The commit paths differ in WHEN the load starts

`GameDataHolder` decomp (GameDataHolder.cpp:599-629):

- `changeNextStage(info, raceType)` → `mIsStageChanging = true` — the sequence
  picks the pending stage up on the next update and goes STRAIGHT to the
  stage load.
- `changeNextStageWithDemoWorldWarp(stageName)` → sets the demo-warp state and
  leaves `mIsStageChanging = false` — the actual load is deferred into
  `HakoniwaStateDemoWorldWarp` (the flight cinematic), i.e. the engine gets a
  full demo's worth of wall-clock plus the dedicated `exeLoadWorldResource`
  await before the destination scene initializes.

That is why flights into Metro are consistently clean and door-shaped
cross-world commits are the crash surface. The overworld-HomeStage subcase
(PBP → City crash vs Sand → City clean) is not fully explained by the decomp
(HakoniwaSequence::update is undecompiled); the FrameHeap variant suggests the
world-resource swap DID start but raced the stage load. §1.6 instrumentation
resolves this empirically.

### 1.5 Fix options, ranked

**B1 — route remapped commits whose FINAL target is a foreign-world
overworld HomeStage through `tryChangeNextStageWithDemoWorldWarp`**
(Devon's directive; covers the finding-10 / FrameHeap class).

- Seam: inside `fileChangeNextStageHook`, when `processEntranceRemap` applied
  a row AND `kingdomShortFromHomeStage(final)` != current kingdom's stage:
  skip `orig`, call the already-bound
  `kGameDataFunctionTryChangeNextStageWithDemoWorldWarp` with the final stage
  name (holder from `game_data_holder_cache`).
- The wrapper guards `mIsStageChanging` (still false pre-orig) — no double
  commit. Substitution INSIDE that wrapper is already proven (order-gate
  BACKSTOP + chain bounce); *initiating* it from a door context is the new
  part → needs one in-game probe.
- Costs (accepted in the P5 framing): entrance id is lost — the player lands
  at the Odyssey, not the paired mouth (chain-arrival bookkeeping +
  normalization still run; they key on the final stage, not the id). The
  first-visit warp demo may play (isForwardWorldWarpDemo) — the Cascade
  pre-Broode suppressor stays scoped as-is.
- Risks to probe in-game: demo-warp from inside a subarea (camera/actor
  context), demo-warp while airborne/capture, and Lost/Ruined exempt kingdoms
  (keep them on the plain commit — their story-managed arrivals are the
  reason they're exempt from normalization).

**B2 — foreign-world INTERIOR targets (the Swinging class): make the
world-swap fire.** B1 cannot cover these (the demo warp is an
Odyssey/overworld arrival). Two candidate levers, in order:

1. **Write the next-world id where the engine reads it.** `GameDataFile`
   stores `mNextWorldId` (decomp GameDataFile.h:585/839, getter
   `getNextWorldId`). If the sequence's world-swap decision consumes the
   STORED id (set at commit from the ByMainStageName resolution), a single
   post-orig field write in `fileChangeNextStageHook` — world id of the
   remap row's destination kingdom, which the apworld already knows per row —
   fixes both crash classes natively, loading screen included. Needs the
   OdysseyHeaders offset for `mNextWorldId` + a logging spike to confirm the
   sequence reads the stored value (trampoline `GameDataFunction::
   getNextWorldId` + `calcNextWorldId`, log at every transition: does the
   engine call either around a door commit, and with what value?).
2. If the sequence recomputes via an INLINED ByMainStageName walk (spike shows
   no out-of-line read): fall back to **pre-arming the loader** — call
   `WorldResourceLoader::requestLoadWorldHomeStageResource(destWorld,
   scenario)` at commit (symbol + owner pointer needed — more invasive, and
   the stage load still races the async world load; only worth pursuing if
   lever 1 is dead).
3. Interim mitigation while B2 is unproven (data-only, apworld): none worth
   shipping — constraining the matching to same-world interiors guts the
   feature. Devon can simply avoid the known-crashing doors; S&Q recovers.

**Wire/slot_data note for B1+B2:** the remap rows should carry the
destination's world id (the apworld knows each mouth's kingdom from
`entrance_stages.json`). Extending the `entrance_map` slot_data/wire rows is
an ADDITIVE field — plan it into the next reseed so the switch mod doesn't
need its own stage→world table for subareas (it only has HomeStage↔kingdom).
Until then B2 lever 1 can resolve the world id via
`kingdomShortFromHomeStage` for overworld targets only.

### 1.6 Instrumentation to ship with the next build (read-only)

- Trampoline loggers (installAtPtr, soft-degrade): `GameDataFunction::
  calcNextWorldId`, `GameDataFunction::getNextWorldId` — one line per call
  with return value while a commit is pending. Tells us which read the
  sequence consumes and what it resolves for door vs flight vs subarea
  targets.
- Log line in `fileChangeNextStageHook`: final target + its resolved kingdom
  + current world id — classifies every commit as same-world / cross-world
  for correlation with the above.

## 2. Findings 11–13 — the chain-return hardening (designed this session,
implemented in switch-mod, Devon builds)

The decomp read of `GameProgressData` (GameProgressData.cpp, full read
2026-07-08) reshaped all three fixes:

- The save stores ONLY the monotonic `mUnlockWorldNum` counter (+ 2 branch
  enums). `mIsUnlockWorld[]` and the per-view orderings (`mWorldIdForWorldMap`
  / `WorldWarpHole` / `ShineList`) are DERIVED by `updateList()`. There is no
  per-world unlock bit to set — `unlockWorld(late)` necessarily unlocks
  everything earlier (finding 12), and `unlockNextWorld` also RAISES
  `mHomeLevel` (the overshoot leveled the ship too). Nothing listing-only
  exists on the save side.
- `mIsFirstTimeWorld[]` (= `isAlreadyGoWorld`) IS per-world and saved. Chain
  arrivals already force it (`setAlreadyGoWorld`) — that's why A5 (S&Q inside
  a chain kingdom) came back perfect.

### 2.1 The key derivation (fixes 13's persistence with zero wire surface)

Once `unlockWorld` is no longer called (12), a kingdom is chain-reached-only
**iff `isAlreadyGoWorld(w) && !isUnlockWorld(w)`** — both save-backed, so the
marker survives save/quit/reload by construction, is independent of gate
payment (payment touches neither), and self-clears if the kingdom is later
reached legitimately (story unlock covers it). No new wire message, no client
persistence.

Caveat: on the CURRENT polluted save (unlockWorld overshoot already written)
chain kingdoms read as unlocked → the derivation degrades to the session bits.
Fresh save on the next re-seed (already required by the no-O↔O topology
change) restores full semantics. Not worth save surgery.

### 2.2 Finding 12 — remove `forceUnlockWorld` from `processChainArrival`

Normalization becomes setAlreadyGoWorld + forceAcquireOdyssey only. With the
honest counter, the vanilla globe automatically satisfies Devon's "hide the
rest" ruling on fresh saves: vanilla-unlocked = visited ∪ the legitimate
story-next destination, nothing else. (Strict visited-only would hide the
story-next kingdom and brick vanilla progression — the ruling is implemented
as "hide everything the MOD would have over-unlocked", which is exactly what
removing the call achieves.)

### 2.3 Finding 12b — listing chain kingdoms as return destinations
(the "listing-only seam")

Chain kingdoms are now alreadyGo-but-not-unlocked → the vanilla globe won't
list them, but the ruling wants visited kingdoms flyable. Seam chosen per the
CLAUDE.md inlining guidance (attack DATA inputs, not tiny getters):
`GameProgressData::mIsUnlockWorld[w]` is a plain heap bool array (ptr @ +0x20,
OdysseyHeaders == decomp layout), rebuilt only by `updateList()` and NEVER
saved (`write()` serializes the counter, not the array). So: a per-frame,
throttled force from the drawMain pump — `mIsUnlockWorld[w] |=
chainReachedOnly(w)` — is clobber-proof (re-asserted after any updateList),
RAM-only, and needs no symbol that might be inlined. Same pattern as the
costume-door OpenKeySwitch force.

Reaching the array: `GameDataFile* → mGameProgressData @ +0x6a8` (established
read). The pump gets the GameDataFile* from a new `ApState::
game_data_file_cache`, refreshed by every `changeNextStage` / `returnPrevStage`
commit AND by SaveLoadHook (`GameDataFile::initializeData`) so a save reload
can't leave it dangling.

Verification walk: chain into a kingdom, leave, open the globe elsewhere —
is the chain kingdom listed/selectable? If the map turns out to be driven by
the derived `mWorldIdForWorldMap` slots instead of the per-world bool, the
force won't list it (harmless) and the fallback is the messier
`mWorldIdForWorldMap`/count surgery — next session, with the walk log.

### 2.4 Finding 13 — persistent visited-only bounce

`WorldMapSelectHook`'s bounce no longer keys on `chain_allowance_bit`
(cleared by payment — the leak). New condition, evaluated per flight commit:
bounce any pick that is neither visited (session bit) nor alreadyGo
(save) whenever the DEPARTING kingdom is chain-reached-only (session bit OR
the §2.1 save-derived marker). Payment does not clear it (ruling), so the
post-payment story `firstNext` flight to Moon bounces to the chain origin.
Origin memory stays session-only (`chain_origin_bit`); after S&Q it falls
back to Cap — acceptable, documented.

### 2.5 Finding 11 — the story-launch predicate

The launch state machine lives on `ShineTowerRocket` (exeNoStart* /
receiveEvent nerves) — NOT decompiled, so the predicate's exact read can't be
read from source. Known from the 2026-06-29 Cascade rounds: the free
`findUnlockShineNum` + `isUnlockedNextWorld` are inlined at the takeoff seam
(isUnlockedNextWorld absent from dynsym), and the shared out-of-line worker
`GameDataHolder::findUnlockShineNum(bool*, s32)` FIRED but did not open the
IN-CABIN globe gate. The story launch ("chase Bowser") is a DIFFERENT site —
it may well consult the member (or the by-world free fn, which we substitute
with the honest rolled value on purpose).

Plan: hook the member worker (soft installAtPtr, symbols already in
HookSymbols.hpp) — under an active chain-return allowance for the CURRENT
world, return 0; always log fires with worldId so Devon's next refusal walk
shows definitively which read the story launch makes. If the member fires at
refusal time and the zero opens the launch: done — the resulting `firstNext`
commit is caught by §2.4's bounce (story-forward never allowed). If it does
NOT fire: next candidate is `rs::checkGetEnoughShineInCurrentWorld` /
a raw shine-count compare — logged for the session after.

Free-fn hook interplay (safe): our two free-fn hooks call orig → the member
trampoline fires nested → under allowance orig returns 0 → the by-world hook
still substitutes the rolled value (globe labels stay honest), the
current-world hook returns 0 under the same allowance anyway.

## 3. Session deliverables tied to this doc

Implemented in switch-mod THIS session (unbuilt — Devon's build+walk loop):
§2.2 (unlockWorld removal), §2.3 (file cache + listing force), §2.4
(persistent bounce), §2.5 (member-worker hook + logging), §1.6's commit-side
classification log line. §1.5 B1/B2 are NOT implemented — this doc is the
design gate; B2's lever-1 spike (calcNextWorldId/getNextWorldId loggers) ships
with §1.6 so the next walk decides the lever.

Walk matrix for the next build:
1. Swinging Along the High-Rises entry — read the §1.6 log lines (crash is
   expected to persist; we want the calc/getNextWorldId values).
2. PBP cold repro — same, FrameHeap variant.
3. Chain into an unvisited kingdom → pay the gate → story launch: does the
   member hook fire at refusal? Does the launch open? Is the firstNext flight
   bounced?
4. Chain, leave, open globe elsewhere: is the chain kingdom listed
   (§2.3 verification)? Are formerly-over-unlocked kingdoms absent (fresh
   save only)?
5. S&Q inside a chain kingdom (A5 repeat) on a FRESH save: takeoff allowance
   still open post-reload (save-derived marker), bounce still active.

## 4. 2026-07-08 late-session status — first walk VOID (stale binary)

Devon's first pass over the §3 matrix ran a subsdk9 built at 9:45 AM,
before ANY of this doc's §1.6/§2 implementation reached disk (12:40 PM) —
no `[chain-launch]` / `[p5-nextworld]` install lines in the logs, and the
finding-12 `unlockWorld` call still fired. So: no next-world spike data
(B1/B2 lever decision still open), finding-11 seam still undecided, and
W3–W5 "failures" were old-code behavior. W1 DID reconfirm the Swinging
ExpHeap crash on the new seed. Full triage + the client reconnect-race
bug this surfaced (fresh boot parked "inactive" → no post-HELLO replay →
ability gates enforce an empty table AND the entrance remap silently
reverts to vanilla; fixed in `client/switch_server.py`, regression test
shipped): plan-decoupled-entrances.md, "session 2026-07-08 (fourth)".
Mod rebuilt + redeployed same session; matrix unchanged, needs a fresh
save (the stale build's unlockWorld overshot the walk save again).

## 5. 2026-07-09 — spike data in, LEVER DECIDED, B1 + B2 IMPLEMENTED (built,
unwalked)

**R0 verified first** (per the stale-binary lesson): deployed subsdk9
2026-07-09 9:40 AM postdated every findings-11–13 source edit (07-08
12:39–12:45), all walk logs postdated the deploy, every log carries the
unconditional `[chain-launch]`/`[p5-nextworld]` install lines, no
`chain-arrival unlockWorld(...)` calls, no `unknown message t=kick` (the
client reconnect fix HELD in-game). This walk's results are real.

### 5.1 The §1.6 spike verdict — lever 1 is DEAD

Across the whole walk (seed regenerated 07-09 9:41, spoiler
`AP_16310405358685788791`): `calcNextWorldId -> 1 (cur='CapWorldHomeStage')`
fired at the one Odyssey-flight commit and `getNextWorldId -> 1
(cur='DemoChangeWorldStage')` during its demo — and **neither fired around
ANY door commit** (several observed, incl. two cross-world interior entries
and two cross-world overworld exits; the spikes log on value change, and a
door target's world id differs, so silence = genuinely not called). The
plain changeNextStage path never consults a next-world read out-of-line:
writing `mNextWorldId` (B2 lever 1) has no reader there. **Lever 1 dead;
lever 2 (drive the world-resource swap ourselves) is the fix, with B1
demo-warp routing for non-exempt overworld targets per Devon's directive.**

### 5.2 What shipped (all switch-mod; built 07-09 10:38, Ryujinx copy is
Devon's)

- **B1 — `routeRemappedCrossWorld` (EntranceShuffleHook.cpp):** a REMAPPED
  commit whose final target is a non-exempt overworld HomeStage in a world
  ≠ the RESIDENT world skips orig and calls the already-proven
  `tryChangeNextStageWithDemoWorldWarp` (native swap path). A one-shot
  `ApState::chain_demo_warp_pending` handshake makes WorldMapSelectHook
  skip the order-gate BACKSTOP + chain bounce for that synthetic call
  (`[wmap.tryChange.Demo] synthetic chain warp` log). Chain-arrival
  bookkeeping/normalization run BEFORE the warp, so the arrival lands
  parked (setAlreadyGoWorld pre-warp), and the demo's own internal :file
  commit re-enters the hook un-remapped (cascade/cap overrides run there
  normally). Accepted costs (per §1.5): marker id lost (land at the
  Odyssey), flight cinematic on a door hop — this includes the RETRACE out
  of a foreign interior, which now flies home. If the UX cost reads too
  high on the walk, the fallback is routing overworld targets through B2
  too (one-line change in routeRemappedCrossWorld).
- **B2 — `game/CrossWorldLoad.{hpp,cpp}` (NEW):** every other cross-world
  remapped commit (foreign INTERIOR targets + the Lost/Ruined exempt
  overworlds) stays a plain commit and ARMS a one-shot pre-load; it fires
  at `HakoniwaSequence::destroySceneHeap` post-orig (old scene dead — the
  request's internal tryDestroyWorldResource can't free memory a live
  scene references) with `exeLoadStage` first-tick as fallback, calling
  `WorldResourceLoader::requestLoadWorldHomeStageResource(destWorld,
  scenario)` (loader off `HakoniwaSequence::mResourceLoader`, sequence ptr
  cached by drawMain; scenario from `GameDataFile::getScenarioNo(worldId)`,
  fallback 1). The request is self-guarding (decomp read verbatim: boot
  dual-heap / load-in-progress / same-world all refuse side-effect-free).
  **Plus a UNIVERSAL backstop**: every exeLoadStage tick compares
  `getNextStageName`'s world against the loader's resident world and
  requests on mismatch — covers paths the commit-side arm can't see
  (returnPrevStage pops back to the entry-origin world after a pre-arm
  swapped residency, divert/detour rewrites). Residual accepted risk: the
  stage load races the async world load; partial mitigation may or may not
  be enough — that's what the walk decides. Log tag: `[p5-prearm]`.
- **World ids for subarea stages** come from
  `WorldList::tryFindWorldIndexByStageName` (the NON-main variant, §1.3)
  off the cached GameDataHolder's `getWorldList()` — **no wire/slot_data
  change, no reseed**. All 8 new symbols verified HIT in retail dynsym via
  `scripts/check_nso_symbols.py` (which reads `.romfs-cache/main.nso`
  directly — the tool of choice for future symbol checks).
- **Chain-only marker fix (walk finding):** the session
  `chain_reached_kingdoms` bit is set by ANY remapped overworld commit —
  including into a kingdom the player already LEGITIMATELY unlocked. First
  live case: a chain door back into flight-visited Cascade zeroed its
  takeoff gate (`[chain-launch] ... orig=5 -> 0 (allowance ZERO)`) and
  would have armed the visited-only bounce on departure. Fixed both sides:
  `OdysseyRescue::isKingdomChainReachedOnly(bit, world_id)` =
  `(session bit || alreadyGo) && !isWorldUnlockedRaw` (unlock-read-
  unavailable degrades to the session bit; the save arm keeps its
  fail-closed shape) now backs BOTH the takeoff allowance and the flight
  bounce, and `processChainArrival` no longer sets the session bit for a
  legitimately-unlocked destination (log gained `unlocked=` field).

### 5.3 W2–W5 triage (fresh-binary walk, all explained)

- **W2/W3 "no Odyssey, stranded" in Ruined and Lost = the DESIGNED
  normalization exemption**, not a fix regression (`exempt=1` in both
  chain-arrival logs; forceAcquireOdyssey correctly skipped). S&Q recovered
  both (respawn via the save's own kingdom — W5 confirming that is the
  designed A5 behavior). **Open design decision for Devon**: chains into
  Lost/Ruined strand by design — options are (a) accept + document S&Q,
  (b) lift the exemption with story-state guards (Lost's crash-repair
  sweep + Ruined's pinned Multi-Moon are the reasons it exists), or
  (c) drop Lost/Ruined door mouths from the pool (apworld, needs reseed).
- **W3/W4 signals (gate pay → story launch, globe listing) are still
  UNTESTED** — this seed's walked chains all landed in exempt kingdoms.
  Walkable non-exempt route on THIS seed: **Cap "Precision Rolling" door →
  8-Bit Chasm Lifts (Cascade interior) → its 'Lift2DExit' exit → Sand
  "Crazy Cap Store" door mouth** = chain arrival into Sand (non-detour,
  non-exempt, vanilla gate 16). Post-B1 that exit is a demo warp into
  Sand; allowance/launch/bounce all exercisable there. Finding-11's seam
  question (does the story launch consult the member findUnlockShineNum?)
  remains open pending that walk.
- **The Cap→Cascade flight that "should have bounced" didn't — correct
  behavior**: this is the cap-peace bootstrap save, where Cascade is
  `isAlreadyGoWorld=1` from the prologue story-drop, so the pick was
  legitimately allowed. No bounce bug.
- No fresh save needed for the next walk: this walk ran finding-12 code
  (no unlockWorld overshoot), and the chain-bit poisoning was session-only.

### 5.4 Next-walk matrix (supersedes §3; check `[p5-prearm]`/`[p5-b1]`
install lines FIRST, R0-style)

Boot lines to confirm: 6× `[p5-prearm] <symbol> @ 0x...`, `[p5-prearm]
destroySceneHeap trigger @`, `[p5-prearm] exeLoadStage trigger @`,
`[p5-b1] tryChangeNextStageWithDemoWorldWarp @`.

1. **Foreign-interior entry** (e.g. Cap "Precision Rolling" door → 8-Bit
   Chasm Lifts): expect `[p5-prearm] ARMED world=...` at the commit,
   `fire@destroySceneHeap ... LOAD STARTED`, clean load. Then the
   deterministic crasher: **Swinging Along the High-Rises** (this seed:
   Wooded "Crowded Elevator" door) — the class verdict.
2. **Foreign-overworld exit** (8-Bit Chasm Lifts 'Lift2DExit' → Sand):
   expect `[p5-b1] ... -> demo warp` + `synthetic chain warp` + flight
   cinematic + parked Odyssey at Sand + `[chain-arrival] ... unlocked=0`.
3. **W3 signal in Sand**: globe opens at 0 (allowance), un-visited pick
   bounces, visited pick flies; AP-grant + deposit 16 Sand moons → story
   launch: does `[chain-launch]` fire at the refusal (finding 11)?
4. **Retrace / :return coverage**: walk back out of a pre-armed foreign
   interior through its OTHER (vanilla-kept, if any) exit — expect
   `[p5-prearm] backstop@exeLoadStage ... LOAD STARTED` on the pop.
5. **Legit-kingdom regression**: chain door back into a flight-visited
   kingdom — expect NO `allowance ZERO` (honest `orig=N -> N`), no bounce
   departing it, `[chain-arrival] ... unlocked=1`.
6. **PBP-cold class** (cross-world overworld, the FrameHeap variant): any
   interior exit → non-exempt foreign door mouth, fresh boot — should now
   be a B1 demo warp (crash surface removed by construction).

## 6. 2026-07-09 (sixth session) — §5.4 walk triage: B2 concurrent load is
## UNSAFE (new crash class), hold seam decided; Lost sweep = the counter
## overshoot; Cap floor + capturesanity leaks root-caused

**R0:** deployed subsdk9 07-09 10:57:30 == staged build, postdates every
source (newest 10:37). The three NEW logs (`boot.txt`,
`swinging-crash.txt`, `crash-entering-8bit-chasm.txt`) carry the full
item-0 install-line set — real. **But `chain-to-lost-then-luncheon.txt`
(Devon's notes 3/4) and `subarea-exit-to-sand-crash.txt` have ZERO
`[p5-prearm]`/`[p5-b1]` lines — they ran the PREVIOUS (9:40) binary**
(no B1/B2, no chain-bit-poisoning fix). Notes 3/4 are still valid triage
input (the code they exercised is unchanged by B1/B2) but are old-binary
evidence.

### 6.1 Items 1+2 — FAIL, and the failure reshapes B2

Both foreign-interior entries crashed:

- Cap "Precision Rolling" door → `Lift2DExStage` (8-Bit Chasm, world 1):
  `ARMED world=1 (resident=0)` → `fire@exeLoadStage ... LOAD STARTED` →
  crash. `nn::g3d::ResFile::ResCast` → invalid access, on
  `al::InitializeThread`.
- Wooded "Crowded Elevator" door → `PoleGrabCeilExStage` (Swinging, world
  7): `ARMED world=7 (resident=3)` → `fire@exeLoadStage ... LOAD STARTED`
  → crash. `agl::g3d::ResFile::Setup` → null-deref
  (`getResTextureFile` on 0x0), on `al::InitializeThread`.

Two hard facts:

1. **The destroySceneHeap primary trigger NEVER fired** — door-shaped
   transitions do not call `HakoniwaSequence::destroySceneHeap` (the
   engine only destroys the scene heap when IT detects a world change,
   which is exactly what the remap breaks). The exeLoadStage first-tick
   fallback is the ONLY live trigger on the B2 paths, so the world load
   starts simultaneously with the stage load — zero head start.
2. **Concurrency itself is the killer, not just timing.** The crashes are
   no longer heap-exhaustion aborts (§1.1); they are resource-setup races:
   the scene's async `InitializeThread` does per-stage loads of the same
   archives the `WorldResourceLoader` thread is concurrently loading into
   the world heap, and one side gets a partially-set-up
   `nn::g3d::ResFile`. Firing the pre-arm concurrently with the stage load
   made the crash EARLIER (mid-load) than no pre-arm at all
   (post-arrival streaming). Serialization is mandatory.

**Fix decided (T1 in the execution handoff): HOLD `exeLoadStage` until
the world load completes.** Decomp check done: `HakoniwaSequence::
exeLoadStage`/`destroySceneHeap` are NOT decompiled (HakoniwaSequence.cpp
upstream contains only `drawMain`), so any seam relying on its internal
step logic is out. The chosen seam avoids that entirely: inside our
existing `exeLoadStageHook`, pre-orig, after `firePendingPreload`/
`universalCrossWorldCheck` — if `!isEndLoadWorldResource(loader)`, poll
`hk::svc::SleepThread(10ms)` until done or a 30 s timeout, THEN call
orig. Blocking inside the exe body is transparent to the nerve step
counter (no ticks are skipped, first-step init still runs); the loader's
`AsyncFunctorThread` + the SZS decompressor/FileLoadThread run on their
own threads and don't need the main thread to progress. Timeout
fails open to orig (the old crash risk, logged loudly). Frozen frame for
the load duration = vanilla's `exeLoadWorldResource` wait without the
percent bar — accepted v1 cost. This also serializes the universal
backstop's :return-pop reload by construction. (Rejected alternatives:
skipping orig per-tick — desynchronizes `al::isFirstStep` init; firing at
commit time — destroys the origin world's resident set under a LIVE
scene.)

Items 2/6's B1 half (`[p5-b1]` demo warp on overworld exits) was **never
reached** — the interiors crash before their exits can be walked. B1
remains implemented-but-unwalked; Devon has ruled its UX acceptable, so
no fallback routing is needed if it works.

### 6.2 Notes 3/4 — the "prefix unlock through Lost" root cause is the
### LOST SOFTLOCK SWEEP, and the §2.3 listing force is confirmed dead

Old-binary log (`chain-to-lost-then-luncheon.txt`), but the code is
unchanged in the new build, so the bugs are live:

- `[chain-arrival] dest=ClashWorldHomeStage ... exempt=1` → then
  `OdysseyRescue: Lost crashHome → repair + unlock`. The Lost sweep
  ([OdysseyRescue.cpp:561-575](../switch-mod/src/game/OdysseyRescue.cpp))
  calls `unlockWorld(getWorldIndexClash())` — and per the GameProgressData
  decomp (§2), `unlockWorld` is the monotonic-counter loop: unlocking Lost
  NECESSARILY unlocks Sand/Lake/Wooded/Cloud first and PERSISTS
  (`mUnlockWorldNum` is saved). That is exactly Devon's globe: Cap…Lost
  listed ("new" icons), Snow/Seaside/Luncheon absent. The sweep's own
  comment claims unlocking the current world "doesn't perturb" — the
  finding-12 lesson says otherwise; the sweep is the last surviving
  `unlockWorld` caller. **Fix (T2): gate the sweep's unlock on the
  kingdom NOT being chain-reached-only** (repair stays unconditional;
  chain departures are handled by allowance+bounce, legit story arrivals
  have Lost unlocked already so the unlock is a no-op there).
- **Luncheon absent from the globe despite
  `[chain-listing] force mIsUnlockWorld[10]=true`** = the §2.3 fallback
  case confirmed: `updateList()` derives `mWorldIdForWorldMap` + the map
  count from the COUNTER, not the bool array, so the RAM bool force can
  never list a chain kingdom. The messier surgery would be the map-array/
  count fields — but there is no stored map count (`GameProgressData.h`:
  only `mUnlockWorldNum`), and the actual list consumer
  (`StageSceneStateWorldMap`, `mWorldNum` @ 0x104) is NOT decompiled.
  **Ruling (this session): accept the interim** — with T2 killing the
  overshoot, chain kingdoms are simply not flyable-back from the globe;
  departure works (allowance + bounce to a visited kingdom), returning =
  re-walk the chain or S&Q. The bool force stays (harmless, may feed pick
  validation). Making chain kingdoms LISTED is a future disasm/research
  task (StageSceneStateWorldMap seam), NOT in the execution handoff.
  Devon can veto the interim.
- The good news in the same log: the member `[chain-launch]` hook fired
  with correct allowance zeroing for Lost AND Luncheon, the Metro pick
  from Lost bounced to Cascade (§2.4 works), and Luncheon (non-exempt)
  got the full normalization — ship present, exactly the designed
  behavior ("some odyssey chain logic is working" = yes, all of it, for
  non-exempt kingdoms).
- **Devon's save is now polluted** (counter ≈ 7 persisted by the old
  binary's sweep). The next walk needs a FRESH SAVE for clean globe/
  listing signals.

### 6.3 Item 3 / finding 11 — still open, now unblocked by T1

"Globe at 0" was the allowance working at the in-cabin globe. A clean
STORY-launch refusal was never reached (Lost self-unlocked via 6.2). The
Sand route (§5.3) is blocked by the item-1 crash until T1 ships. Verdict
case unchanged: pay the gate in chain-reached Sand, attempt the story
launch, watch `[chain-launch]`.

### 6.4 Devon rulings recorded this session

- **B1 UX: acceptable** (flight cinematic + Odyssey landing on door hops).
- **Lost/Ruined: lift the exemption with story guards** (option b).
  Design decided here (T3): **Lost lifts fully** — normalization
  (setAlreadyGoWorld + forceAcquireOdyssey) runs, B1 covers its overworld
  mouths; the story guard is T2 (sweep repairs but never unlocks).
  **Ruined lifts conditionally** — normalize/B1 ONLY when the dragon is
  already beaten (`GameDataFile::getScenarioNo(Ruined) >= 2`, the
  quest-recomputed post-boss scenario); pre-dragon arrivals stay
  story-managed (plain commit + B2 pre-arm, no normalization) so the
  Lord-of-Lightning fight arms and its vanilla completion repairs the
  ship — the in-game escape, and the pinned progression Multi-Moon stays
  earnable. Post-dragon chain arrivals were the true hard-strand case
  (no ship, no dragon, S&Q only) and now get a parked ship.

### 6.5 Notes 1+2 — root causes (apworld/hook tier)

- **Note 1 (start_at_cap_peace=false but Cap advanced to peace):**
  `CapReturnScenarioHook` is an UNCONDITIONAL floor — any commit into
  `CapWorldHomeStage` below scenario 2 is forced up (plus
  forceAcquireOdyssey + forceUnlockCascadeDestination on the same
  branch). On a vanilla start, exiting the Cap tower during the prologue
  is exactly such a commit → prologue skipped. **Fix (T5): gate the floor
  on `isWorldAlreadyGo(Cascade)`** — save-backed, true on the cap-peace
  bootstrap save (prologue story-drop sets it) and true on any vanilla
  save after the prologue flight, false DURING a vanilla prologue. No
  wire/slot_data change. Degraded read (alreadyGo unavailable) keeps the
  floor (protects cap-peace runs) and warns.
  **2026-07-12 addendum:** T5's guard also killed the *fresh-save*
  Cap-peace bootstrap (option ON, no authored save: tower-exit was the
  intended peace trigger). Restored option-aware via a new
  `cap_peace_start` wire msg (slot_data `start_at_cap_peace` — already
  auto-shipped by fill_slot_data — → SMOContext → SwitchServer stash/push
  on Connected + HELLO replay → ApState::cap_peace_start, boot-default
  false). When set, CapReturnScenarioHook bypasses the T5 guard (tower
  exit floors Cap to peace + parks Odyssey + unlocks Cascade) and
  processCascadeOdysseyDivert fires even pre-Broode (leave-gate would
  otherwise strand a 0-check player in Cascade). Option-off/vanilla
  behavior is byte-identical (flag false ⇒ same code path as T5).
- **Note 2 (capturesanity off but Jizo in the pool):** abilitysanity OFF
  has the drop+precollect pair (`World.py:910-950`); capturesanity OFF
  only drops LOCATIONS (`before_is_location_enabled`) — the capture
  ITEMS still ride the pool. **Fix (T4): mirror the ability pattern for
  the Capture category** (drop from pool + precollect, skipping names
  already precollected by `_precollect_starting_captures`). No client
  change: precollected items ride the normal received-items path (the 3
  fixed starters prove it), so the Switch capture gate opens naturally.
  Requires install_apworld + RESEED.

### 6.6 Next-walk matrix (post-T1..T5 build, CURRENT seed until T4's
### reseed, FRESH SAVE)

Boot lines: the §5.4 set PLUS at least one `[p5-hold]` line per
cross-world interior entry.

1. **Item 1 retest:** Cap "Precision Rolling" door → 8-Bit Chasm Lifts.
   Expect ARMED → fire@exeLoadStage → `[p5-hold] ... waited N ms -> done`
   → clean load, no ResFile crash.
2. **Item 5:** inside 8-Bit Chasm, exit back through the 'Lift2D' mouth →
   B1 demo warp to Cap (visited+unlocked): `[chain-arrival] ...
   unlocked=1`, no `allowance ZERO` for Cap. (Alt: Sand "Freezing
   Waterway"(EX_2DHosui_Exit) door → Spinning-Platforms Treasure Vault →
   'bonus2' mouth → Cascade.)
3. **Item 4 (backstop/:return):** Cap "Frog Pond" door → Crazy Cap Store
   (Lake) [pre-arm swaps residency to Lake] → walk back out the shop
   door → expect `[p5-prearm] backstop@exeLoadStage ... LOAD STARTED`
   (+ hold) on the pop back to Cap, clean arrival.
4. **Item 2 + 6:** fresh boot → Cap → 8-Bit Chasm → 'Lift2DExit' mouth →
   Sand: `[p5-b1] ... -> demo warp`, `synthetic chain warp`, flight
   cinematic, parked Odyssey, `[chain-arrival] ... unlocked=0` (this is
   also the PBP-cold-class-as-B1 verdict).
5. **Item 3 / finding 11:** in chain-reached Sand — globe allowance 0,
   AP-grant + deposit the rolled gate shown in the Odyssey, story launch:
   does `[chain-launch]` fire at the refusal, and does its 0 open the
   launch (then the firstNext flight must bounce)?
6. **Swinging class verdict:** Sand "Bullet Bill Maze"(doukutu1) door →
   Ice Cave (same-world, no pre-arm) → 'arijigoku2' mouth → Shards Under
   Siege (Metro interior, cross-world I→I pre-arm + hold) → 'taxi' mouth
   → Wooded overworld (B1) → Wooded "Crowded Elevator"(EX_Tankuro) door →
   **Swinging Along the High-Rises** (the deterministic crasher; clean =
   the P5 crash class is CLOSED for interiors).
7. **T3 verdict:** chain into Lost (e.g. Wooded "Breakdown
   Road"(KillerRoad) door → Stretch and Traverse the Jungle → 'imomu_01'
   mouth → ... any Lost mouth): expect normalization to run (`exempt` no
   longer short-circuits), ship PRESENT, `Lost crashHome → repair
   (unlock SKIPPED, chain-reached-only)` log, globe NOT prefix-unlocked.
8. **T5 verdict:** fresh vanilla save (option false), play the prologue,
   exit the Cap tower: scenario NOT forced (no `[cap-return]
   changeNextStage floor` line), prologue intact.

### 6.7 IMPLEMENTED (execution session, per docs/handoff-prompt-p5-execution.md)

- **T1**: `holdForWorldLoad()` added in `switch-mod/src/game/CrossWorldLoad.cpp`,
  called pre-orig in `exeLoadStageHook` after `firePendingPreload`/
  `universalCrossWorldCheck`, before `orig` — polls `hk::svc::SleepThread(10ms)`
  until `isEndLoadWorldResource()` or a 30s timeout, logs `[p5-hold]`.
- **T2**: `switch-mod/src/game/OdysseyRescue.cpp`'s Lost sweep branch now
  guards `unlockWorld(wr, clashWorld)` on
  `!isKingdomChainReachedOnly(kingdomBitFor("Lost"), clashWorld)` — `repairHome`
  stays unconditional; logs `unlock SKIPPED, chain-reached-only` when guarded.
- **T3**: `isChainExemptOverworld` replaced with `chainArrivalStoryManaged`
  in `switch-mod/src/hooks/EntranceShuffleHook.cpp` (Lost lifts fully; Ruined
  stays story-managed only while `scenarioNoForWorld(Ruined) < 2`); new
  `scenarioNoForWorld(int)` added to `switch-mod/src/game/CrossWorldLoad.{hpp,cpp}`;
  `processChainArrival`'s `exempt` var and `[chain-arrival]` log field renamed
  `storyManaged`; `routeRemappedCrossWorld`'s B1 condition updated to match.
- **T4**: `_drop_capture_items_if_disabled` / `_precollect_capture_items_if_disabled`
  added to `apworld/smo_archipelago/hooks/World.py` (mirrors the abilitysanity
  pair; precollect subtracts already-precollected starter copies via
  `multiworld.precollected_items[player]`), wired into `before_create_items_filler`.
  New tests: `tests/test_capturesanity_precollect.py` (source-parse, 8 tests) +
  `tests/test_capturesanity_precollect_reachability.py` (SMOAP_LIVE_AP-gated,
  asserts zero pool Capture items + every Capture name precollected at its
  full items.json count with starters counted once). Both green;
  `install_apworld.py` re-run.
- **T5**: `capArrivalScenarioOverride()` in
  `switch-mod/src/hooks/CapReturnScenarioHook.cpp` now early-returns -1 unless
  `isWorldAlreadyGo(worldIdFromKingdomShort("Cascade"))` — the floor no longer
  fires during a vanilla Cap prologue.
- Full suite: 1021 passed / 99 skipped (baseline 1013/98 + this session's 8
  new source-parse tests + 1 new SMOAP_LIVE_AP-gated test); the two
  SMOAP_LIVE_AP reachability tests (capturesanity + abilitysanity mirrors)
  both pass against the reinstalled zip.
- **Build/walk/reseed/fresh-save: Devon's**, per §6.6 (T4 changed the item
  pool — reseed required; Devon's current save also carries the T2-era
  unlock-counter overshoot — fresh save required regardless).

## 7. 2026-07-10 (seventh session) — §6.6 walk triage: hold VALIDATED 6/8,
## Swinging residual re-classified as a residency CLOBBER (theory, probe
## shipped), test-7 strand fixed ([odyssey-strand-rescue])

Walk ran on the reseeded `AP_57213197975398613665` (fresh save, T1–T5
build; door names re-derived from the new spoiler — routes below are THIS
seed's).

### 7.1 Results

| §6.6 item | Route walked | Verdict |
|---|---|---|
| 1 (hold, foreign interior) | Cap "Poison Tides" → Swinging Scaffolding (Metro) | **PASS** — ARMED 7 → fire → `[p5-hold] 3340 ms -> done` → clean |
| 2 (retrace) | SS 'gragra' → Cap | **PASS** — clean, `unlocked=1`, no `allowance ZERO`. NOTE: NO `[p5-b1]` fired (see 7.2) |
| 3 (backstop/:return) | Sand shop `bar2` → Lake shop → walk out | **PASS** — entry ARMED 4 + hold 1670 ms; return clean. NOTE: NO backstop line (see 7.2) |
| 4 (B1 chain into overworld) | SS 'gragrareturn' → Wooded | **PASS** — `[p5-b1] (world 3, resident 0) -> demo warp`, synthetic chain warp, parked ship. Wooded read `alreadyGo=1 unlocked=1` (vanilla Sand fork legit-unlocks Lake+Wooded — NOT a chain-reached-only arrival) |
| 5 (allowance/launch) | in Wooded | **PASS as walked** but finding 11 still unexercised — Wooded was legit-unlocked, so no `[chain-launch]` zero was ever in play; globe visited-only = the honest counter listing (finding 12 working) |
| 6 (Swinging verdict) | Wooded "Flower Road" (EX_RailCollision) → PoleGrabCeilExStage | **FAIL** — ARMED 7 → fire → `[p5-hold] 2990 ms -> done` → clean arrival → **ExpHeap abort ~7 s later on FileLoadThread while streaming** (the §1.1 signature, POST-hold) |
| 7 (T3 Lost) | — | **BLOCKED** — item-6 crash stranded the save (see 7.3) |
| 8 (T5 prologue) | fresh vanilla save | **PASS** — no `[cap-return]` floor, prologue intact |

### 7.2 The unifying finding — residency is being CLOBBERED back to the
### engine's stale current world (theory; probe shipped, one walk decides)

Three independent log facts, one explanation:

1. **wooded-early-flight**: B1 printed `resident 0` (the origin, Cap) even
   though that boot's Poison Tides entry had pre-arm-loaded Metro (7).
2. **PT-SS-return + cap-store return**: cross-world overworld exits fired
   NEITHER `[p5-b1]` NOR the backstop. Both decisions read
   `getLoadWorldId`; joint silence is only possible if resident had
   reverted to the ORIGIN world (0 and 2 respectively — which each equalled
   the dest, so both gates skipped).
3. **swinging-along-crash**: the hold COMPLETED (Metro fully loaded), yet
   the stage aborted ~7 s post-arrival in ExpHeap while streaming — §1.2's
   per-stage fallback, i.e. the Metro resident set was gone AGAIN.

Theory: shortly after a pre-armed foreign load, the engine re-requests the
world set for its OWN notion of current world — which never updated,
because `calcNextWorldId` can't see subarea targets (§1.3) — destroying
the pre-armed set. In vanilla that re-request is always a same-world no-op
(the early-return), so it's invisible; our pre-arm makes
`mLoadWorldId != engine-current` and turns it destructive. Small-delta
stages (SwingSteel, the shops) survive on per-stage fallback — the
city-streaming PoleGrabCeil dies. Corollary: **the clean cinematic-free
overworld returns in items 2/3 were the clobber COINCIDENTALLY restoring
the dest's residency, not the backstop working** — do not generalize them.

Shipped this session: `[p5-worldreq]` — a trampoline ledger on
`requestLoadWorldHomeStageResource` (CrossWorldLoad.cpp) logging every
call (world, scenario, pre-call resident, result). Our own calls route
through the same patched entry, so the ledger is complete. An engine
request for the ORIGIN world after our `LOAD STARTED` line = the clobber,
timestamped relative to hold/arrival.

Fix decision tree (next session, with the ledger):
- Clobber confirmed, one-shot around scene init → preferred fix is making
  the ENGINE's world bookkeeping correct at the commit (a field write on
  the GameDataFile/Holder current/next-world state — note the §5.1 "lever
  1 dead" verdict only ruled out out-of-line READERS of getNextWorldId at
  the swap decision; the ensure-request may consume the stored field via
  inlined reads). Fallback: a one-shot post-clobber corrector (re-request
  our world at first drawMain after scene init) — riskier, §6.1's
  concurrency lesson applies to a LIVE scene.
- No engine request in the ledger → theory wrong, re-triage.
- Until fixed: avoid the Swinging door; a crash no longer strands (7.3).

### 7.3 Test-7 strand — root-caused + FIXED ([odyssey-strand-rescue])

After the item-6 crash, reload put Mario in Wooded with
`exist=0 activate=1 launch=1 level=1` — ship owned but not placed (the B1
demo warp's landing placement didn't survive the crash), and S&Q reloads
the same kingdom: hard strand. `forceAcquireOdyssey` cannot repair this
state (its `a0 && l0 && lv0>=1` guard no-ops). New OdysseyRescue sweep
branch: standing in an overworld HomeStage with
`activate=1 && exist=0 && crash=0` (crash=1 stays the Lost/Ruined repair
path; Ruined pre-dragon excluded per T3, fail-closed on a cold scenario
read) → re-run `activateHome` (sets isExistHome / places the ship in the
CURRENT world — A5-proven persistence) + launch/level top-ups. Log
`[odyssey-strand-rescue]`; one line then silence = took (the actor may
need ONE S&Q to spawn — placement is scene-init-time); repeated lines =
activateHome doesn't re-place → escalate. This is also the first slice of
the v3 "Odyssey always available" backstop the logOdysseyHomeStateDiag
spike was built to decide.

### 7.4 Devon Q&A recorded

- **"Ditch the B1 cinematic?"** — Deferred, likely yes LATER: once the
  clobber fix makes plain commits genuinely safe under pre-arm+hold,
  overworld targets can route through B2 (land at the paired mouth,
  marker preserved, no flight). Not now: this walk's cinematic-free
  successes were the clobber coincidence (7.2), not evidence.
- Both fixes are **switch-mod-only** — NO reseed, NO apworld change, and
  the current save should be KEPT (the stranded Wooded save is the
  strand-rescue's test case).

### 7.5 Next-walk matrix (post-§7 build; same seed, same save)

Boot lines: §6.6 set PLUS `[p5-worldreq] request probe @ 0x...`.

1. **Unstrand (test-7 retest)**: boot the stranded Wooded save → expect
   ONE `[odyssey-strand-rescue] Wooded ...` line; if no ship visible,
   S&Q once → ship parked, flight to a visited kingdom works.
2. **Clobber ledger**: re-enter Swinging Along the High-Rises (Wooded
   "Flower Road", EX_RailCollision). Crash expected and now recoverable.
   Deliverable = the full `[p5-worldreq]` sequence around the entry
   (ours at fire, then who requests what, when).
3. **Ledger control**: one clean foreign-interior round trip (Cap
   "Poison Tides" ↔ Swinging Scaffolding) — does the engine's clobber
   request appear there too (surviving on small delta), or only on
   crashing stages?
4. **T3 Lost + finding 11** (carried, now unblocked): chain into a
   genuinely-locked kingdom. This seed: Cascade "Gusty Bridges"
   (WindBlowExStart) → Simmering in the Kitchen (Luncheon interior) →
   its 'CostumeOut' mouth → Luncheon overworld = B1 chain arrival,
   `unlocked=0` expected → allowance zero, story-launch refusal,
   `[chain-launch]` verdict. (Lake/Wooded can never exercise this —
   the vanilla Sand fork legit-unlocks both.)

## 8. 2026-07-11 (eighth session) — §7.5 walk triage: strand ROOT-CAUSED
## (isExistHome is DERIVED — fix shipped, unbuilt), clobber-as-request
## theory REFUTED by the ledger (new probes shipped)

Walk log: `7.5.2-swinging-along-crash.txt` — ONE boot covering §7.5 items
1 + 2 (Devon: item 3 unreachable while stranded, item 4 untested; Devon
also flagged he has NOT paid the Sand fork, so Lake/Wooded are genuinely
LOCKED on this save — load-bearing below). R0 fine: full install-line set
incl. `[p5-worldreq] request probe`.

### 8.1 Item 1 FAIL root-caused — `isExistHome` is a DERIVED predicate,
### and the strand-rescue could never have worked

Decomp (GameDataFunction.cpp, read 2026-07-11):

```cpp
isExistHome = isGameClear || (isActivateHome && isUnlockedCurrentWorld)
```

There is NO stored per-world "ship exists here" flag. A chain-reached-only
kingdom is BY DESIGN not unlocked (finding 12's honest counter), so in it
`exist` derives false, the Odyssey actor never places at scene init, and
`activateHome` (activate already 1) is a guaranteed no-op. The log proves
it: the rescue called activateHome every sweep tick from 00:00:24.9, diag
`exist` stayed pinned 0 for ~53 s, then flipped to 1 in the SAME tick that
`[chain-listing] force mIsUnlockWorld[3]=true #1` first ran (00:01:18.0) —
the unlock-array force, not the rescue, is what controls `exist`.

Second bug stacked on top: **the chain-listing force was dead until the
first door commit.** At boot `GameDataFile::initializeData` fires across
ALL FIVE save-slot instances (the `[saveload-diag] self=` addresses);
SaveLoadHook's cache store is last-write-wins, so `game_data_file_cache`
pointed at the last-initialized EMPTY slot (whose GameProgressData arrays
aren't even allocated — `tickChainKingdomListing` bailed silently on the
null array). Only the 00:01:17 commit (EntranceShuffleHook re-cache)
brought the force alive.

Corollaries: (a) §7.1 item 4's "parked ship in Wooded" pass was the
`unlocked=1` coincidence, NOT B1 working for locked kingdoms — on the
CURRENT save (Sand fork unpaid) Wooded is locked and the B1 promise
fails; (b) §7.5 item 4 (Luncheon chain arrival) is HARD-BLOCKED until
this fix builds — `unlocked=0` ⇒ no ship ⇒ the story-launch/finding-11
test can't run.

**Fixes shipped this session (switch-mod only, unbuilt):**

- `OdysseyRescue::liveGameDataFile()` — GameProgressData now reached via
  the holder's `getGameDataFile()` (inline OdysseyHeaders getter for
  `mPlayingFile`, always the LIVE file), falling back to the old cache.
  The chain-listing force now works from the first pump tick after boot.
- `exeLoadStageHook` (CrossWorldLoad) calls `tickChainKingdomListing()`
  pre-orig on EVERY load tick — the unlock array is true when scene-init
  placement reads `isExistHome`, on every load path (boot, S&Q, plain
  commit, B1 warp), not just when the 1 Hz pump wins the race.
- The strand-rescue branch is now a log-only WATCHDOG
  (`[odyssey-strand-watch]`, WARN, ~30 s throttle, logs
  alreadyGo/chainOnlySave): it firing at all means the force is not
  covering the current kingdom — escalate.

### 8.2 Item 2 — the ledger came back CLEAN: clobber-as-request REFUTED

The crash reproduced exactly (§1.1 signature: ExpHeap abort on
FileLoadThread in `ParallelSZSDecompressor::tryDecompFromDevice`, ~8.5 s
after arrival). But the full `[p5-worldreq]` sequence was: boot load
world=3 (#1), two same-world refused re-requests (#2/#3, benign engine
behavior around Wooded sub-transitions), our pre-arm `world=7 → LOAD
STARTED` (#4), post-hold self-refusal (#5, ours) — **and NOTHING between
hold-done and the abort.** No engine request for the origin world = the
§7.2 theory as stated (clobber via `requestLoadWorldHomeStageResource`)
is dead.

Two suspects remain, and the old ledger could see neither:

1. **A silent destroy**: `tryDestroyWorldResource()` frees the resident
   heap and sets `mLoadWorldId=-1` (decomp) without any request; a
   standalone engine call would not appear in the request ledger.
   `requestLoadWorldResource(s32)` (the plain second load entry, no
   internal destroy) is equally invisible.
2. **Residency intact, abort anyway**: the Metro set stays loaded but the
   stage still per-stage-loads city assets (lookup keyed on the engine's
   stale current-world bookkeeping, or scene-heap sizing) until the scene
   ExpHeap exhausts.

**Probes shipped (both symbols verified HIT in retail dynsym):**
`[p5-worldreq] DESTROY resident_was=N` (trampoline on
tryDestroyWorldResource; no-op destroys skipped) and `[p5-worldreq]
request(plain) world=N` ledger lines, plus `[p5-reswatch] resident=X
engineCurWorld=Y` — a 1 Hz on-change trace from the drawMain pump. One
Swinging re-entry decides: DESTROY/plain line before the abort = suspect
1 (fix = suppress/react to the destroy); resident pinned at 7 through the
abort = suspect 2 (fix moves to the engine's current-world bookkeeping —
a field write at commit, or accept + size mitigation).

### 8.3 Next-walk matrix (post-§8 build; same seed, SAME stranded save —
### it is the perfect fixture)

Boot lines: §7.5 set PLUS `[p5-worldreq] destroy probe @`, `[p5-worldreq]
plain-request probe @`.

1. **Unstrand, take 2**: boot the stranded Wooded save. Expect
   `[chain-listing] force mIsUnlockWorld[3]=true` within ~1 s of first
   frame, NO `[odyssey-strand-watch]` lines, and the Odyssey PARKED at
   scene init — no S&Q needed. Flight out to a visited kingdom works
   (bounce governs the pick).
2. **Swinging probe walk**: re-enter Swinging Along the High-Rises
   (Wooded "Flower Road", EX_RailCollision). Crash allowed (recovery =
   item 1 now working). Deliverable = the `[p5-reswatch]` trace plus any
   DESTROY / request(plain) lines between `[p5-hold] ... -> done` and the
   abort.
3. **Ledger control** (§7.5 item 3 carried): Cap "Poison Tides" ↔
   Swinging Scaffolding round trip — do DESTROY/plain lines appear on a
   SURVIVING foreign interior too?
4. **T3 Lost + finding 11** (§7.5 item 4 carried, now truly unblocked):
   Cascade "Gusty Bridges" → Simmering in the Kitchen → 'CostumeOut' →
   Luncheon. Expect `unlocked=0` chain arrival WITH a parked ship (the
   §8.1 fix), allowance zero at the globe, story-launch refusal →
   `[chain-launch]` verdict.

## 9. 2026-07-11 (ninth session) — §8.3 walk: 3/4 PASS, CLOBBER CONFIRMED
## (mechanism = engine's plain `requestLoadWorldResource(stale current
## world)` at scene entry), NEW bug: the listing force poisons the
## chain-only derivation

Walk logs: `swinging-crash.txt` (items 1+2), `reroute.txt` (items 3+4).
Both carry the full §8.3 boot-line set (destroy + plain-request probes
installed). Same seed `AP_57213197975398613665`, same save.

### 9.1 Results

| §8.3 item | Verdict |
|---|---|
| 1 (unstrand) | **PASS** — `[chain-listing] force mIsUnlockWorld[3]` within ~1 s of boot, `exist=1`, NO strand-watch lines, ship parked + boardable, no S&Q needed. §8.1 fix validated in-game. |
| 2 (Swinging probes) | Crash reproduced, **probes decisive — see 9.2** |
| 3 (Poison Tides ↔ SwingSteel round trip) | **PASS** — pre-arm + hold + retrace clean, arrived back in Wooded in the scenario he left it at |
| 4 (Luncheon chain arrival) | **PASS as walked** — `[chain-arrival] ... alreadyGo=0 unlocked=0`, B1 demo warp, chain-listing forced `mIsUnlockWorld[10]`, ship PRESENT in locked Luncheon (diag `exist=1`). BUT the allowance did NOT zero — see 9.3; finding 11's launch-refusal verdict still open. |

### 9.2 The clobber, caught in the act — suspect 1 (plain variant) confirmed

The engine calls the PLAIN `requestLoadWorldResource(currentWorld)` at
(apparently) every scene entry — visible throughout both logs as benign
same-world `request(plain) world=N (resident_was=N)` lines right after
each `stage_in_out` entry. In vanilla that is always a same-world
refresh. Under a B2 pre-arm the engine's current world is STALE (§1.3:
calcNextWorldId can't see subarea targets, and the door path never
updates it — reswatch shows `resident=7 engineCurWorld=3` post-hold), so
at the foreign-interior scene entry the plain request re-points the
loader at the ORIGIN world:

```
[p5-hold] exeLoadStage held 4240 ms for world 7 -> done
[p5-reswatch] resident=7 engineCurWorld=3
[p5-worldreq] request(plain) world=3 (resident_was=7) -> LOAD STARTED   ← CLOBBER
[p5-reswatch] resident=3 engineCurWorld=3
... ~8 s of city streaming on per-stage fallback ...
sead::ExpHeap::tryAlloc abort (FileLoadThread, ParallelSZSDecompressor)
```

`reroute.txt` shows the SAME clobber on the surviving stages
(`world=0 (resident_was=7)` at SwingSteel, `world=1 (resident_was=10)`
at LavaWorldCostume) — small per-stage deltas survive it, PoleGrabCeil's
city delta dies. §7.2's small-delta theory was right; only the writer
was the invisible plain entry, not the HomeStage request. Also note:
the B1 demo-warp path DOES update the engine world
(`engineCurWorld` 1→10 after the Luncheon warp) — only plain door
commits leave it stale.

**Fix options (next session; DECOMP READ FIRST per CLAUDE.md):**

- **B (root, preferred if the field is clean): write the engine's
  current-world bookkeeping at the remapped commit.** Read the decomp
  for what `GameDataFunction::getCurrentWorldId` returns (which field on
  GameDataFile/Holder, who writes it, who else consumes it). In vanilla
  a subarea visit keeps current world = its owning world, so setting it
  to the remap dest's world id at commit is vanilla-consistent and makes
  the plain request load the RIGHT world natively — fixes this crash
  class at the source (and un-stales every other current-world
  consumer). Risk: unknown consumers (regional coins, map, checkpoint
  lists) — the decomp read decides.
- **A (targeted fallback): redirect the stale plain request.** In
  `requestLoadWorldPlainHook`, when the requested world != resident AND
  `resolveWorldIdForStage(getCurrentStageName())` == resident (i.e. the
  loaded set matches the stage we are actually in, the request is the
  stale-bookkeeping artifact), call orig with the RESIDENT world instead
  (or skip). One-liner, no new symbols, but leaves the engine's world id
  stale for every other consumer.

### 9.3 NEW bug — the §8.1 listing force poisons the chain-only derivation

At the Luncheon chain arrival the takeoff allowance did NOT zero:
`[chain-launch] member findUnlockShineNum worldId=10 (Luncheon) orig=18
-> 18` (expected `-> 0 (allowance ZERO)`). Cause: the §2.1 marker reads
`isWorldUnlockedRaw` → `GameProgressData::isUnlockWorld` → **the very
array tickChainKingdomListing forces true** (that force is what makes
the ship exist, §8.1). So the moment the force runs, the kingdom reads
"legitimately unlocked" and `isKingdomChainReachedOnly` returns false —
neutering the allowance zeroing, the visited-only bounce, AND the T2
Lost-sweep guard for every chain-reached kingdom. The exist-fix and the
chain-only marker are currently mutually exclusive.

**Fix shape:** track which worlds WE forced (ApState bitmask, set in
`tickChainKingdomListing`), and subtract them in the honest unlock read
(`isWorldUnlockedRaw(w) && !forced(w)` — or equivalently read the
save-backed `mUnlockWorldNum` counter instead of the RAM array). Clear a
world's forced bit when the engine legitimately unlocks it — trampoline
`GameDataFunction::unlockWorld` (symbol already resolved, out-of-line)
or re-derive from the counter. Finding 11's verdict (does the zeroed
gate open the story launch?) needs this fix built first.

### 9.4 Handoff

Next-session tasks, walk matrix, and all constraints:
[handoff-prompt-p5-clobber-fix.md](handoff-prompt-p5-clobber-fix.md).

## 10. 2026-07-11 (tenth session) — clobber fix + T-C SHIPPED (built + deployed,
## awaiting the verification walk)

Executes the handoff. Both bugs are code-complete, the switch-mod BUILT clean
(zero `error:`, `[100/100]` linked, `.nso`+`main.npdm` generated) and deployed
into Ryujinx (`%APPDATA%\Ryujinx\mods\...\exefs`, `BRIDGE_HOST=192.168.4.100`
verified full-dotted in CMakeCache). Switch-mod-only — NO reseed, KEEP the save
(`AP_57213197975398613665`). The verification walk (§9.4 handoff §"Verification
walk") is Devon's.

### 10.1 Bug 1 — shipped T-A, NOT T-B. The decomp read made the call.

**Decomp read (CLAUDE.md rule; the payoff):** `getCurrentWorldId()` returns
`GameDataFile::mCurrentWorldId` — a plain stored `s32` (OdysseyHeaders
`mCurWorldId` @ `0x9f0`; the decomp's adjacent `_9f8` field pins the offset,
`mCurrentWorldIdForWrite` @ `0x9f4`). BUT **no writer exists anywhere in the
decompiled source** (`GameDataFile.cpp`, `GameDataFunction.cpp`,
`GameDataHolder.cpp` all grepped): the write lives inside the undecompiled
`GameDataFile::startStage` (called from `GameDataHolder::startStage`, which then
reads `getCurrentWorldId()` — decomp GameDataHolder.cpp:684). Consumers of the
field: regional coins (`mUseCoinCollectNum[getCurrentWorldIdNoDevelop()]`),
Sphinx quiz, moon-rock talk (`isEnableOpenMoonRock`/`calcMoonRockTalkMessageIndex`),
map name (`tryGetWorldNameCurrent`), checkpoint list, costume/cap type name, and
the plain `requestLoadWorldResource(currentWorld)` scene-entry refresh (the
clobber).

T-B's decision criterion was "plain stored s32 **with a clear writer**." The
field is plain but the writer is invisible, and the `[p5-reswatch]` trace proves
door commits never touch it (engineCurWorld stuck at the ORIGIN across a door
hop). So T-B's return-trip correctness — that returning to the origin overworld
restores `mCurWorldId` and undoes an interior write — is **unproven** (the clean
retraces only prove the current no-write behavior is clean). Writing DEST at the
interior commit would strand `mCurWorldId=DEST` into the return and load the
wrong world on the way out. **Ruled T-B out; shipped T-A.**

**T-A** (`requestLoadWorldPlainHook`, CrossWorldLoad.cpp): pre-orig, if
`world != resident && resolveWorldIdForStage(getCurrentStageName()) == resident`,
call `orig(loader, resident)` instead and log `request(plain) REDIRECTED
stale=N -> M`. Correctness argument (both directions provable): in vanilla the
plain entry is ALWAYS a same-world refresh (`arg == mCurWorldId == resident ==
stage's world`); the remap is the only thing that diverges them, so
`world != resident` here is by construction the stale artifact. The guard
`stage_world == resident` is true ONLY when we are standing in a stage whose
world is already fully resident — precisely the clobber. During a legitimate
cross-world load the destination is not yet resident (`resident != stage_world`),
so T-A cannot hijack a real swap; and the return to the origin overworld either
sees `arg == resident` (no-op) or, if `arg` is stale, correctly redirects to the
resident origin. New symbol: none — `getCurrentStageName` was already in
HookSymbols; added `s_getCurrentStageName` resolve in CrossWorldLoad.

### 10.2 Bug 2 — T-C shipped (forced-bits mask + honest read + unlockWorld clear)

- ApState `chain_unlock_forced_bits` (atomic u32, world-indexed) +
  `markKingdomUnlockForced` / `isKingdomUnlockForced` /
  `clearAllKingdomUnlockForced` (mirrors the `visited_kingdoms` pattern).
- `tickChainKingdomListing` sets bit `w` whenever it force-lists a world
  (unconditional/idempotent — set even when `unlock_arr[w]` was already true, so
  the bit persists across the `continue`).
- New `isWorldUnlockedHonest(w)` = `isWorldUnlockedRaw(w) && !forced(w)`.
  `isKingdomChainReachedOnlySave`, `isKingdomChainReachedOnly`, AND the
  EntranceShuffleHook chain-arrival marking site (was the last poisoned reader)
  now route through it. `isWorldUnlockedRaw` kept as the literal RAM read.
- `GameDataFunction::unlockWorld` trampoline (`unlockWorldClearHook`, patched at
  the already-resolved symbol) clears ALL forced bits post-orig; the next tick
  re-forces any world still chain-only (honest read stays false there) and does
  NOT re-force a world that just became legitimately unlocked (raw array rebuilt
  true + forced bit clear). Self-healing, no story-order table. Our own
  `g_fns.unlockWorld` calls (Lost sweep / Cascade destination) also land here and
  recurse harmlessly through orig.
- Regression guard #4 holds by construction: forced bits are only ever set for
  chain-reached-only worlds, so a kingdom we never forced reads its raw value —
  a legit unlock can never be flipped to chain-only.

The exist-fix (RAM `mIsUnlockWorld` force, which drives the engine's own
`isExistHome` derivation) and the chain-only marker (honest read subtracting our
forces) are now decoupled — no longer mutually exclusive.

### 10.3 Verification walk (Devon; same seed, same save)

Per the handoff §"Verification walk": (1) Swinging verdict — expect
`request(plain) REDIRECTED stale=3 -> 7`, reswatch stays `resident=7`, no ExpHeap
abort = **P5 crash class CLOSED**; (2) Cap↔Swinging survivor regression stays
clean; (3) finding 11 — Luncheon chain arrival now expects `[chain-launch] ...
orig=20 -> 0 (allowance ZERO)` (the T-C fix), then the story-launch-refusal
verdict. Log lines to grep: `[p5-worldreq] request(plain) REDIRECTED`,
`[chain-listing] unlockWorld(...) -> cleared`, `[chain-launch] ... -> 0`.

## 11. 2026-07-12 — §10.3 walk PASSED (Devon: no crashes, all as expected);
## B1 flight-cinematic RETIRED + coin-grant bugs fixed (apworld + switch-mod,
## unbuilt/unwalked)

Devon's §10.3 walk over `AP_57213197975398613665` came back clean — no
crashes, everything worked. The clobber fix (T-A) is validated in-game. Two
follow-up issues from that walk, both fixed this session:

### 11.1 Odyssey flight cinematic on cross-world door hops — RETIRED (B1 off)

Devon: the Odyssey flight cutscene must play ONLY when picking a kingdom on
the in-cabin world-map — NEVER on a door / subarea exit. The 23:15 walk log
confirmed the mechanism: a cross-world exit whose remapped dest is an
**overworld** HomeStage (`ForestWorldHomeStage`, Wooded ×2) fired B1's
`tryChangeNextStageWithDemoWorldWarp` → flight; one whose dest is an
**interior** (`LavaWorldCostumeStage` → exit remapped to
`LavaWorldHomeStage`/`GabuzouClockEx`, Luncheon) took the plain-commit +
pre-arm path → no flight, landed at the paired mouth, Odyssey parked. The
interior case is the desired behavior.

Fix: `kB1DemoWarpCrossWorld = false` ([EntranceShuffleHook.cpp], new flag) gates
the B1 demo-warp block in `routeRemappedCrossWorld` — cross-world **overworld**
hops now take the SAME plain-commit + pre-arm + hold path as interiors (land at
the paired mouth, marker id preserved, Odyssey parked by `processChainArrival`'s
`forceAcquireOdyssey`, no flight). This is the §5.2 / §7.4 "ditch the B1
cinematic" change, unblocked by T-A. `WorldMapSelectHook`'s own kingdom-select
flight is untouched (that's the ONLY flight now). Switch-mod-only, NO reseed,
KEEP the seed/save. Walk check: any cross-world door whose exit lands on an
`...HomeStage` — expect NO `[p5-b1]` line, lands at the mouth, no cinematic.

### 11.2 Coin-grant bugs — sanity-OFF flood + every-boot re-application

Two independent bugs (Devon: coins maxed out, esp. with abilitysanity/
capturesanity OFF; "should only be awarded once, on initial collection"):

- **A (apworld, needs RESEED):** sanity-OFF precollected each ability/capture
  at its FULL items.json count — including the pool-only "clone" copies — and
  `compute_total_coin_grant` counted `(count-1)` as coins, over-counting even
  legit progressive chain levels (Progressive Crouch ×3 minted 200). Fixes:
  new `abilities.unlock_count(name)` (chain length for progressives, 1 else);
  `_precollect_{ability,capture}_items_if_disabled` precollect only
  `min(count, unlock_count)` (no clones → no dup coins, still satisfies every
  `requires` — max demanded level == chain length, verified);
  `compute_total_coin_grant` counts `max(0, count - unlock_count)`.
- **B (client + switch-mod, no reseed for this half):** the Switch's
  `coins_applied` high-water mark is in-memory and resets to 0 every game boot
  while SMO PERSISTS coins → the full `total` re-applied each boot. Fix:
  client `coin_state.py` persists the confirmed-applied total per (seed, slot)
  in `%APPDATA%/SMOArchipelago/coins_applied.json`; `CoinGrant` gained a
  `baseline` field; `applyCoinGrant` seeds `coins_applied = max(coins_applied,
  baseline)`. Baseline advanced only when the Switch is confirmed on a save
  file (PaySnapshot received) — and `apply_pay_snapshot_from_switch` re-pushes
  coin_grant so a PaySnapshot arriving after the HELLO replay still persists it.
  Log: `[p1-coins] seeding coins_applied N -> M from save baseline`.

Suite: 1035 passed / 99 skipped (baseline 1027 + coin baseline/persistence
tests). Zip rebuilt. **Build + walk + reseed: Devon's** — the apworld coin
half (A) needs a reseed; §11.1 + coin half B are switch-mod build only.
Fresh reseed also starts `coin_state` clean (baseline 0), so coins accumulate
correctly from the start.

## 12. 2026-07-12 — CURRENT STATUS: code-complete, ready for a full
## seed-gen playtest (§11 walk verdicts recorded)

Devon's verdicts on the §11 build (previously undocumented):

- **§11.1 (B1 flight-cinematic retired): TESTED, VERIFIED working as
  intended** — cross-world door hops land at the paired mouth, no cinematic.
  This also means the deployed subsdk9 postdates the 07-12 edits (11.1 and
  the 11.2-B binary half are the same build).
- **§11.2 (coin-grant fixes): UNTESTED** — minor per Devon; verified as part
  of the playtest below, does not gate readiness.

Everything in this plan is shipped: crash class closed (T-A clobber redirect,
§10.3 walk clean), chain-return hardening live (findings 11–13, T1–T5, T-C),
B1 retired. **No open code work.** Deferred, explicitly out of scope:
chain kingdoms listed on the globe (§6.2 interim accepted — future
StageSceneStateWorldMap disasm task) and removal of the dead B1 code path
behind `kB1DemoWarpCrossWorld=false` (optional cleanup).

### 12.1 Steps to the full seed-gen test

1. Confirm the installed `meatballs.apworld` postdates the 2026-07-12 coin
   edits (§11.2-A + the coin_state client half live in the zip); if stale,
   `python scripts/install_apworld.py` on Windows.
2. No table sync, no switch-mod rebuild needed (no items/locations.json
   change; binary confirmed current via the 11.1 verdict).
3. `python vendor/Archipelago/Generate.py` — **reseed required** (§11.2-A
   changed sanity-OFF precollect/pool behavior). Fresh save. The new seed
   auto-resets the client coin baseline.
4. R0 first, per the §4 lesson: confirm the full install-line set in the
   boot log before trusting any signal.

### 12.2 What the playtest must verify (the only open signals)

1. **§11.2 coins**: with abilitysanity/capturesanity OFF, no coin flood at
   start; reboot mid-session → no re-grant (expect `[p1-coins] seeding
   coins_applied N -> M from save baseline`).
2. **Finding 11, explicit log**: chain into a genuinely locked kingdom, pay
   the gate, attempt the story launch — archive the `[chain-launch] ... ->
   0 (allowance ZERO)` + refusal/bounce lines. (§10.3 reported passed, but
   the log was never archived here.)
3. **T2/T3 Lost/Ruined** (shipped §6.7, never walked): chain into Lost —
   normalization runs, ship present, `Lost crashHome → repair (unlock
   SKIPPED, chain-reached-only)`, globe NOT prefix-unlocked. Ruined pre-/
   post-dragon behavior if the seed's routes allow.
4. **B1-retired regression**: zero `[p5-b1]` lines anywhere; every
   cross-world hop shows ARMED → `[p5-hold]` → (when the stale plain
   request fires) `REDIRECTED` → clean arrival.

## 13. 2026-07-12 (later same day) — NEW crash instance: BOOT DUAL-HEAP
## refusal (fresh-save prologue session), teardown fix SHIPPED (built,
## walk pending)

**The walk (sand-crash.txt):** Cascade → Crazy Cap shop (City interior) →
exit remapped to Sand (`shop_coin → SandWorldHomeStage/bar1`). Pre-arm ARMED
(resident=1), then at exeLoadStage: `fire@exeLoadStage world=2 …
resident_was=1 -> refused (guard)`, backstop also refused, and the per-tick
`[p5-worldreq] request world=2 scenario=1 (resident_was=1) -> refused/no-op`
repeated ~50× over 4.5 s. **No `[p5-hold]` line** — so `isEndLoadWorldResource`
was TRUE the whole time; the refusal was NOT an in-flight load. Sand's scene
began actor placement (costume-door seams, 00:19:15.8) with Cascade still
resident; at 00:19:16.1 the engine's PLAIN `request(plain) world=2 → LOAD
STARTED` ran the world load mid-scene-init and `sead::ExpHeap::tryAlloc`
aborted inside `ParallelSZSDecompressor` on FileLoadThread.

**Root cause (decomp `Sequence/WorldResourceLoader.cpp`, read verbatim
2026-07-12):** `requestLoadWorldHomeStageResource`'s FIRST guard is
`if (mWaterfallWorldHeap) return false;`. That heap exists only in the **boot
dual-heap** state: a session that boots into the Cap prologue calls
`requestLoadWorldHomeStageResource(0, 1)`, whose special branch
(`loadWorldId==0 && scenario==1`) builds `mCapWorldHeap` (0x1F400000,
forward) + `mWaterfallWorldHeap` (reverse) inside one world-resource heap so
the whole prologue (Cap AND Cascade) runs with zero world loads. The ONLY
vanilla teardown is `tryDestroyWorldResource()` — called by the first
FLIGHT's world-change seam before its own HomeStage request. The plain
variant `requestLoadWorldResource` has NO waterfall guard (only
`!isEndLoadWorldResource`), which is why the engine's stale-bookkeeping plain
request could still start the (fatally late) load.

**Why 8 prior walk sessions never saw it:** heap state is per-SESSION, and
every prior walk booted a mid-game save (boot request = single-world branch,
no dual-heap). A `start_at_cap_peace` seed is played from the fresh-save
prologue in ONE session, and the chain topology replaces every flight with a
`changeNextStage` commit (prologue crash cutscene, Odyssey→Cap divert, chain
doors) — the vanilla first-flight teardown seam never runs, so the dual-heap
lives for the entire session and every HomeStage request refuses forever.

**Fix (CrossWorldLoad.cpp, §11-tagged in code):** both request sites
(`firePendingPreload`, `universalCrossWorldCheck` backstop) now route through
`requestWorldLoad()`: on refusal, if the eliminable guards don't explain it
(`isEndLoadWorldResource()` true AND resident != dest — leaving only the
waterfall heap or the never-absent WorldList byml), call
`tryDestroyWorldResource()` (resolved from the same symbol the §8 DESTROY
probe patches, so our call lands in the ledger) and re-request. This is
byte-for-byte what the vanilla flight seam does, at seams where the old scene
is equally dead. **Boot-pair exemption:** destinations Cap(0)/Cascade(1) skip
the teardown (`kBootPairMaxWorldId`) — the dual-heap serves exactly those two
worlds, a refused request for them needs no load, and the validated
Cascade→Cap divert runs on this state.

**Expected log on the retest:** at the first cross-world hop out of the boot
pair (e.g. Cascade → City shop): `[p5-worldreq] DESTROY resident_was=1 -> -1`
followed by `[p5-prearm] exeLoadStage boot dual-heap TEARDOWN
(resident_was=1) -> re-request world=N scenario=S -> LOAD STARTED`, then the
normal `[p5-hold]` → clean arrival. Subsequent hops are ordinary single-heap
pre-arms (no further TEARDOWN lines). Built + SD-staged 2026-07-12
(BRIDGE_HOST placeholder — Devon rebuilds with his LAN IP); walk pending.
