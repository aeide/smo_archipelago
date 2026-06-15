# P4 — Ability enforcement (gating Mario's moveset on AP ability items)

**Living document.** This is the canonical plan + progress tracker for the entire P4
phase. Update the Status table and the session log at the end of every P4 session.
Started 2026-06-14 (after the capturesanity gate + Spark-Pylon fixes landed and the
capture gate was confirmed working in-game).

Read `CLAUDE.md` invariants first. P4 builds on P3-3b (ability *tracking*): the bridge
already ships `ability_state` (a full-overwrite per-ability count snapshot) and the
Switch stores it in `ApState::ability_table` under a seqlock. P4 is the *enforcement*
layer: read that table from the frame thread and suppress moves the player hasn't
received.

---

## Goal

Each "Dark Side moon" AP item is bound to one ability (or one step of a progressive
chain). Until the player receives the item, the corresponding move is disabled in
game. The starting kit is intentionally tiny (single jump + neutral cap throw, plus
Frog / Chain Chomp / 1 random capture), so most of Mario's moveset begins locked and
opens up as ability items arrive.

P4 is enforcement only. The item pool, classification, wire protocol, tracking
bitfield, Cappy unlock bubble, and duplicate→coins are all P3 and already done.

---

## Architecture — the judge() trampoline pattern (load-bearing)

SMO decides whether a move may start by calling a `PlayerJudge*`'s
`IJudge::judge() const`:

```cpp
class IJudge {
    virtual void reset() = 0;
    virtual void update() = 0;     // does the state work
    virtual bool judge() const = 0; // returns "should this move start NOW?"
};
```

`PlayerActorHakoniwa`'s nerve/exe functions call each judge's `judge()` to gate
transitions. **Trampoline the concrete `judge()` and return false when the gating AP
ability isn't owned** → the move cleanly never starts. `judge()` is `const` and
side-effect-free (`update()` mutates state, not `judge()`), so forcing false is a pure
suppression with no teardown to race — this is the cleanest enforcement point and
follows the M7 lesson (hook the decision, upstream of the visible change).

Mangling: `bool Class::judge() const` → `_ZNK<len><Class>5judgeEv` (no args). Some
judges multiply-inherit (`al::HioNode` + `IJudge`); that does NOT change the `judge()`
symbol name, and trampolining the symbol gets the real function body with the
full-object `this`, which we only forward to `orig` — so it's fine.

**Verification is mandatory** (smo-symbol-discovery rule): a trampoline target that
isn't in `main.nso`'s dynsym aborts the whole module at sail `loadSymbols` (NOT a
soft-fail). The project's verifier is `scripts/check_nso_symbols.py` (LZ4-decompresses
the NSO and string-searches dynstr — needs only `pip install lz4`, NOT llvm-nm):

```
python scripts/check_nso_symbols.py .romfs-cache/main <mangled> [<mangled> ...]
```

`.romfs-cache/main` is the SMO executable NSO produced by the romfs extraction
(`scripts/extract_shine_map.py` — the same run that makes shine_map/capture_map; the
`main` file is already in `.romfs-cache/` after that). Virtual overrides are normally
kept (vtable needs the body), so judges are good candidates, but verify each.

**Spike symbols VERIFIED present in SMO 1.0.0 main.nso (2026-06-14):** all three judge
symbols HIT (`PlayerJudgeStartSquat`/`StartRolling`/`StartHipDrop` `judge()`), alongside
known-good controls (addCoin, addHackDictionary). No loadSymbols-abort risk for the spike.

**Non-judge moves** (cap throws, jump combo, backflip/side-flip, long jump) have no
`judge()` — they're input-routing or jump-state branches. They need different hook
points (see the mapping table) and are the harder, later subset.

### Frame-thread reader (done)
`ApState::abilityCount(name)` — lock-free seqlock read over `ability_table` (the
seqlock was added in P3-3b for exactly this). `abilityAtLeast(name, level)` =
`count >= level`, and returns true unconditionally when `ability_gate_force_unlock`
is set. Counts are monotonic (the bridge only raises them), so a torn/stale read can
only briefly *under*-report — it can never grant a move the player doesn't own.

### Progressive-chain semantics
The bridge ships the cumulative received count per ability; gates compare against a
level:

| Item | count→move |
|---|---|
| `Progressive Jump` (pool ×2) | 1 = Double Jump, 2 = Triple Jump |
| `Progressive Crouch` (pool ×3) | 1 = Crouch, 2 = Roll, 3 = Roll Boost |
| `Progressive Ground Pound` (pool ×3 = 2 chain + 1 clone) | 1 = Ground Pound, 2 = Dive; the 3rd copy is a clone→100 coins, NOT a move |

### Logic prerequisites (P6 concern, noted here)
Backflip and Long Jump also require Crouch (`Progressive Crouch:1`); Ground Pound Jump
requires Ground Pound (`Progressive Ground Pound:1`). In-game these are **mechanically**
gated for free (you can't backflip or long jump without first entering the squat state,
which the Crouch judge already gates — see "Crouch-conditioned jumps" below), but P6
logic must still AND them explicitly so the randomizer never expects a backflip/long-jump
check before Crouch is reachable.

---

## Ability → enforcement mapping (the master checklist)

20 ability items (11 unique + 3 progressive chains spanning 8 steps + 2 clones). Status:
✅ done+code-complete, 🔵 candidate hook identified, ❓ hook unknown / needs discovery.

| Ability item | In-game move | Hook point | Gate | Status |
|---|---|---|---|---|
| Progressive Crouch (L1) | Crouch | `PlayerJudgeStartSquat::judge` | `Progressive Crouch≥1` | ✅ TESTED-PASS |
| Progressive Crouch (L2) | Roll | `PlayerJudgeStartRolling::judge` | `Progressive Crouch≥2` | ✅ TESTED-PASS |
| Progressive Crouch (L3) | Roll Boost | `PlayerInput::isTriggerRollingRestartSwing` (motion shake-while-rolling boost predicate; verified in main.nso). Hooked, gated ≥3. NOT a judge — suppresses the input read; roll START untouched. | `Progressive Crouch≥3` | 🔵 HOOKED — confirm in-game |
| Progressive Ground Pound (L1) | Ground Pound | `PlayerJudgeStartHipDrop::judge` | `Progressive Ground Pound≥1` | ✅ TESTED-PASS |
| Progressive Ground Pound (L2) | Dive | TBD (air dive after GP; not `PlayerJudgeDiveInWater` — that's water). Likely a cap-throw-dive trigger in PlayerActorHakoniwa | `Progressive Ground Pound≥2` | ❓ |
| Wall Slide | Wall catch/slide | `PlayerJudgeWallCatch::judge` (multi-inherit HioNode+IJudge) | owned≥1 | 🔵 |
| Ledge Grab | Ledge grab | TBD — candidate `PlayerJudgeGrabCeil` is ceiling, not ledge; investigate grab judges | owned≥1 | ❓ |
| Climb | Pole/net climb | TBD — climb start judge / nerve; investigate | owned≥1 | ❓ |
| Progressive Jump (L1/L2) | Double / Triple Jump | NOT a judge — jump combo counter (`PlayerContinuousJump`); gate by clamping the chain index, likely in `exeJump`/jump-state | 1=Double, 2=Triple | ❓ hard |
| Backflip | Backflip | Gated via **Option 3** (squat-jump suppression): jump-from-squat is suppressed at `PlayerJudgePreInputJump::judge` while the `exeSquat` in-squat window is open. ITER 1 (both-unowned) **TESTED-PASS**. ITER 2 will split stationary(backflip)/moving(longjump) via `isEnableLongJump`. | owned≥1 (mechanically needs Crouch) | ✅ ITER 1 TESTED (both-unowned); 🟡 ITER 2 for per-move split |
| Side Flip | Side flip | NOT a judge — jump-state branch (quick-turn + jump) | owned≥1 | ❓ hard |
| Long Jump | Long jump | Gated via **Option 3** (squat-jump suppression), same hook as Backflip. ITER 1 (both-unowned) **TESTED-PASS** — moving crouch-jump suppressed. ITER 2 splits it from Backflip via `isEnableLongJump` (`_ZNK16PlayerStateSquat16isEnableLongJumpEv`, HIT; true iff forward momentum). **Naturally blocked while Crouch is locked.** | owned≥1 (mechanically needs Crouch) | ✅ ITER 1 TESTED (both-unowned); 🟡 ITER 2 for per-move split |
| Ground Pound Jump | GP-jump | NOT a judge — jump out of ground-pound; composite trigger | owned≥1 (needs GP) | ❓ |
| Cap Bounce | Bounce on thrown cap | NOT a judge — cap-actor bounce interaction | owned≥1 | ❓ |
| Up Throw | Cap throw up | **motion-control only** (flick up). Cap-throw input routing (`PlayerCapActionHistory` / HackCap throw dispatch) + the motion/shake detector. See "Motion-control abilities". | owned≥1 | ❓ |
| Down Throw | Cap throw down | **motion-control only** (flick down). Same as Up Throw. | owned≥1 | ❓ |
| Spin Throw | Spin cap throw | cap-throw routing (spin variant). NOTE: the button "spin throw" (shake) vs `PlayerJudgeStartGroundSpin` (ground spin move) — confirm which the AP item means. | owned≥1 | ❓ |
| Wall Slide (clone) | — | duplicate→100 coins via existing coin path; no gate | n/a | ✅ (P3) |
| Progressive Ground Pound (clone, 3rd copy) | — | duplicate→100 coins; eases Dive find | n/a | ✅ (P3) |

Notes:
- "TBD" hooks need OdysseyDecomp cross-reference and/or an in-game probe. Mark each
  with the chosen symbol + verification result as it's resolved.
- The judge list available in OdysseyHeaders (for reference when resolving TBDs):
  `PlayerJudgeStartSquat/Rolling/HipDrop/GroundSpin/Rise/Run/WaterSurfaceRun`,
  `PlayerJudgeAirForceCount`, `PlayerJudgeWallCatch`, `PlayerJudgeGrabCeil`,
  `PlayerJudgeDirectRolling/ForceRolling`, `PlayerJudgeDiveInWater`,
  `PlayerJudgeEnableStandUp`, `PlayerJudgeLongFall`, `PlayerJudgePreInputJump`,
  `PlayerJudgeSlopeSlide/ForceSlopeSlide`, `HackerJudge`.

---

## Motion-control abilities (NEW — Devon, 2026-06-14, handoff-critical)

Three abilities are **motion-control only** (no button equivalent) and so are NOT
triggered through the normal judge/button-input path:

- **Roll Boost** — shake the controller *while rolling* to speed-boost. (Currently
  leaks in at Progressive Crouch L2; wants its own gate at L3.)
- **Up Throw** — flick the controller up to throw the cap upward.
- **Down Throw** — flick down.

Implication for hooking: these are detected via SMO's shake/motion detector, not a
`PlayerJudge*::judge()` or a button-press branch. We don't yet know the exact code
path. Candidates to investigate next session (need OdysseyDecomp / in-game probe):
- A shake/振り input predicate on `PlayerInput` (e.g. an `isMotion…` / `isShake…` /
  `isTwist…` getter) read inside the rolling state (Roll Boost) and the cap-throw
  dispatch (Up/Down Throw).
- `rs::` input helpers in `PlayerActorHakoniwa::exe*` (the throw/roll nerves).
- A common gyro/accel gate — if one predicate backs all three, a single hook gates
  all the motion moves at once (but each still maps to a DIFFERENT AP item/level, so
  the hook must branch on which motion gesture, not just "any motion").

Open question for Devon: do you want motion-throw (Up/Down) gated independently of the
button cap-throw? In vanilla, up/down throw are ONLY motion — there's no button form —
so gating the motion detector for "throw up"/"throw down" is the whole ability. Spin
Throw similarly has a motion form (shake) and is the homing throw; confirm whether the
"Spin Throw" AP item refers to that.

**Roll Boost is the immediate next task** (Devon wants it behind Progressive Crouch L3).
Since it's motion-gated, the hook point differs from the Crouch/Roll judges — find the
shake-read in the rolling state and gate it on `abilityAtLeast("Progressive Crouch", 3)`.
(IMPLEMENTED this session — `isTriggerRollingRestartSwing`; see Status + session log.)

---

## Crouch-conditioned jumps — Backflip & Long Jump (Devon, 2026-06-14)

Devon clarified the exact mechanic, which resolves an earlier inconsistency about how
these "hard, no-judge" moves get gated:

- **Backflip** = crouch (squat), then jump **while stationary**.
- **Long Jump** = crouch (squat), then jump **with forward momentum**.

Both are entered *from the squat state* and are distinguished only by horizontal speed at
the moment of the jump-from-squat. Two consequences:

1. **Natural gating is already in place.** We gate `PlayerJudgeStartSquat::judge` behind
   `Progressive Crouch≥1`. A player without Crouch literally cannot enter the squat state,
   so they can do **neither** backflip nor long jump — both are blocked for free with zero
   extra hooks. This is why these moves don't need their own gate to stay locked *while
   Crouch is locked*, and is the simplification the earlier plan missed.

2. **Independent gating** (the only remaining work) is needed for the narrow case where the
   player HAS Crouch but NOT Backflip and/or NOT Long Jump. That's a single decision point:
   the jump-from-squat transition, branched on momentum.
   - **Long Jump** has its own state (`PlayerStateLongJump`) and exe (`exeLongJump` —
     `PlayerActorHakoniwa::exeLongJump`, present in OdysseyHeaders). Gate the *transition
     into* that state (don't trampoline `exeLongJump` itself — by then the state is entered;
     suppressing it mid-flight would freeze Mario rather than cleanly fall back to a normal
     jump). Need the symbol that selects the long-jump state from squat+momentum — resolve
     via OdysseyDecomp, then verify in dynsym before hooking.
   - **Backflip** has no dedicated state class — it's a branch inside the normal jump state.
     Same trigger point (jump-from-squat), the stationary branch. Harder to isolate; do it
     after Long Jump since they share the entry.

**DESIGN DECISION (Devon, 2026-06-14e): SUPPRESS the jump.** When the player has Crouch but
not Backflip and presses jump from a stationary squat, the input is **swallowed — nothing
happens** (no backflip, and no fall-back standing jump). Same for Long Jump (crouch+jump with
momentum): if Long Jump isn't owned, the input is swallowed. The player stays in/returns to
the squat state. Rationale: vanilla has no "small hop from squat" (crouch+jump is *always*
backflip or long jump), and suppression matches the clean judge-trampoline pattern already
used for Crouch/Roll/Ground Pound (force the start decision false → the move simply never
begins, no redirect, no teardown to race). This means the hook does NOT need to synthesize a
normal jump — it just returns "don't start this transition," and Mario remains crouched until
the player releases and jumps normally from standing.

Implementation consequence: gate at the **transition-start decision**, not mid-state. For
Long Jump, suppress the squat→`PlayerStateLongJump` transition selector (returning the
"long jump should start" predicate as false leaves Mario in squat). For Backflip, suppress
the squat→backflip jump branch the same way. Neither path redirects to a standing jump.

---

## Option 3 — context-aware squat-jump suppression (IN PROGRESS, 2026-06-14g)

Chosen by Devon after the decomp-caller path proved dead (PlayerActorHakoniwa.cpp is a
40-byte stub on OdysseyDecomp master — confirmed via GitHub API `size:40`, not a read bug;
the squat→jump trigger is undecompiled). This achieves the SUPPRESS design ("nothing
happens, Mario stays crouched") for BOTH Backflip and Long Jump using only symbols VERIFIED
present in main.nso, no reverse-engineering of the trigger required.

### Mechanism
Backflip and Long Jump are the only two moves that start from a jump-input while in the
squat state. So: gate the jump-input decision, but ONLY while the player is in squat.

Verified symbols used (all HIT in `.romfs-cache/main`):
- `_ZN19PlayerActorHakoniwa8exeSquatEv` — `PlayerActorHakoniwa::exeSquat()`, the squat tick.
  Runs every frame the player is squatting, and ONLY then. Used as the "am I in squat?" beacon.
- `_ZNK23PlayerJudgePreInputJump5judgeEv` — `PlayerJudgePreInputJump::judge() const`, the
  jump-input predicate the player consults to decide "should a jump start now?". This is the
  gate. (CORE ASSUMPTION: the squat→jump transition consults THIS judge. If in-game testing
  shows crouch-jump still fires when gated, the squat-jump uses a different trigger and we
  pivot — see Risks.)
- `_ZNK16PlayerStateSquat16isEnableLongJumpEv` — the LJ-vs-backflip discriminator
  (`front·velocity > 0`). Used in ITER 2 only, to tell which move a given squat-jump would be.
- `_ZN16PlayerStateSquat6appearEv` — squat-state entry; ITER 2 uses it to stash the live
  `PlayerStateSquat*` so `isEnableLongJump` can be called without the actor layout.

### "In squat" tracking (race-free, single game thread)
`exeSquat`, the player judges, and `drawMain` all run on the one game/render thread, in this
per-frame order: pre-movement nerve change (PreInputJump::judge fires) → current-nerve exe
(exeSquat) → drawMain. So:
- `exeSquat` hook sets `g_squatWindow = 2` every squat tick.
- `drawMain` (main.cpp per-frame) calls `tickAbilityGate()` which decrements `g_squatWindow`
  toward 0.
- The judge hook treats `g_squatWindow > 0` as "in (or just in) squat".

Window = 2 (not 1) because the judge fires BEFORE exeSquat within a frame, so on frame N the
judge must see the value set by frame N-1's exeSquat (which drawMain has decremented once:
2→1). Steady state oscillates 2→1 while squatting; decays to 0 within ~1 frame of leaving
squat. A standing jump (not in squat) sees window 0 → untouched. Plain `int`/relaxed atomic
is safe (single thread). 1-frame leaks possible at squat-entry/exit boundaries — acceptable.

### Gate logic
```
PreInputJump::judge hook:
    want = orig(self)
    if (!want) return false              // no jump anyway
    if (g_squatWindow <= 0) return want  // not in squat → normal jump, untouched
    // --- we are mid-squat; this jump would be a backflip or long jump ---
    ITER 1: if (!owns Backflip && !owns Long Jump) return false;  else return want;
    ITER 2: bool moving = isEnableLongJump(g_squatState);
            bool needed = moving ? owns(Long Jump) : owns(Backflip);
            return needed ? want : false;
```
- ITER 1 (this commit): suppress the squat-jump only when the player owns NEITHER move (the
  dominant early-game state). Owning either move currently unlocks both crouch-jumps — a known
  imprecision, refined in ITER 2. This isolates and validates the CORE assumption (does
  gating PreInputJump-while-in-squat actually stop the move?) with minimal moving parts.
- ITER 2 (after ITER 1 tests green): add the `isEnableLongJump` branch for per-move precision
  (own LJ not BF → long jump only when moving, backflip suppressed; own BF not LJ → backflip
  only; etc.). Stash `g_squatState` in a `PlayerStateSquat::appear` hook; resolve
  `isEnableLongJump` via `hk::ro::lookupSymbol` into `bool(*)(const void*)` (lazy, like addCoin).

### Truth table (final, ITER 2)
| Owns BF | Owns LJ | stationary crouch-jump | moving crouch-jump |
|---|---|---|---|
| no | no | suppressed (nothing) | suppressed (nothing) |
| yes | no | backflip | backflip (isEnableLongJump moot — BF branch) |
| no | yes | suppressed | long jump |
| yes | yes | backflip | long jump |

### Recovery / safety
`ability_gate_force_unlock` (ApState atomic) already makes `abilityAtLeast` return true
unconditionally, so a misfire can't brick. `/send <slot> Backflip` / `/send <slot> Long Jump`
also unlock per-move. Low brick risk (neither move is required to leave a kingdom).

### Risks / test points (Devon, in-game)
1. **CORE:** with neither move owned, does crouch+jump now do NOTHING (Mario stays crouched),
   both stationary and moving? If it still backflips/long-jumps, PreInputJump::judge is NOT the
   squat-jump trigger → pivot to gating `exeSquat` directly (neutralize jump input around orig)
   or RE the trigger. Watch log: `AbilityGate: suppressed squat-jump`.
2. **No collateral:** standing jumps, wall jumps, run jumps, dive, etc. must be UNAFFECTED
   (the g_squatWindow guard should ensure this). Verify normal jumping feels identical.
3. `/send Backflip` and `/send Long Jump` re-enable crouch-jumps (ITER 1: either unlocks both).
4. Edge: jumping on the exact frame you stand up — tolerable 1-frame quirk.

### Status
**ITER 1 TESTED-PASS in-game 2026-06-14h** (uncommitted). With neither move owned, crouch+jump
does NOTHING — log shows `AbilityGate: suppressed squat-jump (Backflip/Long Jump)` for both the
stationary (backflip) and moving (long jump) cases. **The CORE assumption is CONFIRMED:
`PlayerJudgePreInputJump::judge` IS the squat-jump trigger, and the in-squat window correctly
scopes the suppression.** No pivot needed.

Still unverified (low-risk, confirm opportunistically next session): (a) `/send Backflip` /
`/send Long Jump` re-enabling crouch-jumps — the unlock path reuses the proven
`abilityAtLeast` mechanism from the spike, so high confidence; (b) normal standing/run/wall
jumps unaffected — the window guard should ensure this, and no breakage was reported.

**Next: ITER 2** (per-move precision) — see "ITER 2 plan" below. ITER 1's known imprecision is
that owning EITHER Backflip or Long Jump unlocks BOTH crouch-jumps; since they're separate AP
items, ITER 2 must split them so Backflip grants only the stationary jump and Long Jump only
the moving one.

### ITER 2 plan (next session — the accuracy refinement)
Add per-move precision using the verified discriminator. Concretely:
1. **Stash the live squat state.** Add a beacon trampoline on `PlayerStateSquat::appear`
   (`_ZN16PlayerStateSquat6appearEv`, verified HIT) → `g_squatState = self` (a
   `const void*`). The state object is an actor member (constructed once, reused), so the
   pointer stays valid; clear it to nullptr in `tickAbilityGate()` when the window hits 0.
2. **Resolve `isEnableLongJump` lazily.** `hk::ro::lookupSymbol` on
   `_ZNK16PlayerStateSquat16isEnableLongJumpEv` (verified HIT) into
   `bool(*)(const void*)`, cached on first use (mirror the `addCoin` lazy-lookup pattern in
   ApState). Returns true iff in Brake nerve + not-2D + forward momentum.
3. **Branch the gate** (replace ITER 1's both-check):
   ```
   if (g_squatWindow <= 0) return want;            // not in squat
   bool moving = (g_squatState && isEnableLongJumpFn) ? isEnableLongJumpFn(g_squatState)
                                                      : false;  // fallback = treat as backflip
   const char* needed = moving ? kLongJump : kBackflip;
   return ApState::instance().abilityAtLeast(needed, 1) ? want : false;
   ```
4. Add `_ZN16PlayerStateSquat6appearEv` to `SmoApSymbols.sym` (isEnableLongJump goes via
   lookupSymbol, no .sym entry needed — but adding it is also fine).
5. **Test matrix** (truth table above): own BF-not-LJ → stationary crouch-jump backflips,
   moving crouch-jump does nothing; own LJ-not-BF → moving long-jumps, stationary does nothing;
   own both → both work; own neither → both suppressed (the ITER 1 case, already green).
6. Risk: `isEnableLongJump` reads velocity at the moment PreInputJump fires (pre-movement
   pass) — velocity is last frame's, which reflects "moving" correctly. If the moving/stationary
   split feels off at the threshold, that's the place to look (the `front·velocity > 0` test).

## Rollout strategy

1. **Spike (DONE, pending test):** the 3 cleanest single-inheritance judges
   (Crouch/Roll/Ground Pound) to prove the whole chain end-to-end. ← we are here.
2. **Judge-backed wave:** add Wall Slide (`WallCatch`), then resolve the TBD judges
   (Roll Boost, Ledge Grab, Climb) one per commit, each verified in dynsym + tested.
3. **Cap throws:** find the cap-throw input dispatch; gate Up/Down/Spin Throw.
4. **Jump-state moves (hardest, last):** Long Jump (`exeLongJump`), then Backflip /
   Side Flip (`PlayerStateJump` branches), Double/Triple Jump (combo-index clamp),
   Ground Pound Jump, Cap Bounce.
5. **Dive** (`Progressive Ground Pound:2`) once the dive trigger is located.

One ability (or chain step) per commit. Each commit: resolve symbol → verify in
dynsym → hook → build → Ryujinx test → log result in the Status table.

### Safety net
- **Current (spike):** no interactive force-unlock wired. Recovery hatch =
  `/send <slot> <ability>` from the AP server console, which unlocks any blocked move
  immediately (ability_state is a full-overwrite snapshot). The spike's 3 moves carry
  low brick risk (none strictly required to leave a kingdom).
- **`ability_gate_force_unlock`** atomic exists on ApState (default false; honored by
  `abilityAtLeast`). **Wire it to a `/`-command before the jump-state wave** (higher
  brick risk): new client→Switch msg mirroring `coin_grant`
  (protocol.py dataclass → switch_server push → `/abilities unlock|gate` command in
  context.py → ApProtocol parse → ApClient dispatch → set the atomic). Then a single
  console command flips every gate off if a hook misfires.

---

## Risks / known unknowns

- **Judge may not be the only chokepoint.** Same caveat as `PlayerHackKeeper::startHack`
  in CLAUDE.md — a move might have multiple entry paths; the in-game test reveals
  misses. If a single `judge()` doesn't fully block, find the additional path rather
  than forcing deeper.
- **`PlayerJudgeStartRolling` identity** — assumed to be the crouch-roll. If the test
  shows it gates the wrong move, remap (candidates: `DirectRolling`, `ForceRolling`).
- **Inlined judges** — if a `judge()` isn't in dynsym (inlined in 1.0.0), hook the
  caller (`PlayerActorHakoniwa::exe*`) or delta-poll instead.
- **Double/triple jump is counter-based**, not a boolean judge — gating means clamping
  the combo index, a different shape than the judge trampolines.
- **Brick risk grows with the jump-state wave** — wire the force-unlock command first.

---

## Status

**Spike TESTED IN-GAME + PASSED 2026-06-14.** Crouch (PC≥1), Roll (PC≥2), Ground Pound
(PGP≥1) all gate correctly and unlock via `/send`; Cappy bubble fires on receipt.
One defect: **Roll Boost leaks in at Progressive Crouch L2** — it should be a separate
L3 unlock. Roll Boost is motion-control only (shake while rolling), so it's not the
`PlayerJudgeStartRolling` judge — needs a separate hook on the shake-read in the rolling
state (see "Motion-control abilities"). This is the NEXT task. Up Throw / Down Throw are
also motion-control only (flick) — same investigation feeds them.

**Roll Boost gate IMPLEMENTED this session (uncommitted; needs build+test).** Hook on
`PlayerInput::isTriggerRollingRestartSwing` gated on Progressive Crouch ≥3 — see the
session log below for the investigation + fallback. Symbol verified in main.nso.

Spike code (still uncommitted — Devon to commit when ready):
- `ap/ApState.hpp` / `ap/ApState.cpp`: `abilityCount`, `abilityAtLeast`,
  `ability_gate_force_unlock` (default false).
- `hooks/AbilityGateHook.cpp` (new): Crouch/Roll/Ground-Pound `judge()` trampolines
  PLUS the Roll Boost `isTriggerRollingRestartSwing` trampoline (PC≥3).
- `syms/game/SmoApSymbols.sym`: `_ZNK21PlayerJudgeStartSquat5judgeEv`,
  `_ZNK23PlayerJudgeStartRolling5judgeEv`, `_ZNK23PlayerJudgeStartHipDrop5judgeEv`,
  `_ZNK11PlayerInput28isTriggerRollingRestartSwingEv`.
- `main.cpp`: `installAbilityGateHooks()` wired in (after CaptureStartHook).

**Symbols already verified present (2026-06-14)** via
`python scripts/check_nso_symbols.py .romfs-cache/main _ZNK21PlayerJudgeStartSquat5judgeEv _ZNK23PlayerJudgeStartRolling5judgeEv _ZNK23PlayerJudgeStartHipDrop5judgeEv`
→ all three HIT. So no loadSymbols-abort risk.

**Awaiting:** Devon (1) rebuild + redeploy; (2) test:
on a save without the abilities, Crouch/Roll/Ground-Pound are suppressed (watch
`AbilityGate: suppressed …`), then `/send <slot> Progressive Crouch` (×1 crouch,
×2 roll) and `/send <slot> Progressive Ground Pound` (ground pound) re-enable them;
confirm a Cappy bubble pops on receipt.

---

## Next session — handoff outline (start here)

Ordered, concrete steps for the next P4 session. Read `CLAUDE.md` invariants + the
"Crouch-conditioned jumps" and "Motion-control abilities" sections above first.

**Step 0 — Roll Boost verification (carried over; do this first).**
Roll Boost code is complete + uncommitted from session 14d. It has NOT been built or
tested in-game yet. Devon to:
1. Rebuild + redeploy the switch-mod (the canonical PowerShell loop in `CLAUDE.md` →
   "Switch-mod build & deploy"). `isTriggerRollingRestartSwing` is already in
   `SmoApSymbols.sym` and verified in `main.nso`, so the build won't loadSymbols-abort.
2. In-game test: at `Progressive Crouch=2`, rolling works but shaking gives NO boost; at
   `=3`, the boost returns. Watch the log for `AbilityGate: suppressed Roll Boost`.
   **Confirm normal rolling is NOT broken.**
3. If `isTriggerRollingRestartSwing` turns out not to be the boost (or breaks rolling),
   swap to the fallback `isSpinInput()` or the rolling-state shake read — see
   "Motion-control abilities". Update the Status table row + session log with the result.
4. Once confirmed, this + the spike are ready to commit (Devon owns the commit decision).

**Step 1 — Long Jump gate (next new enforcement; design locked = SUPPRESS).**
This is the chosen next target (Backflip shares the entry but is harder — do it after).
1. **Resolve the hook symbol.** We need the squat→long-jump *transition selector*, NOT
   `exeLongJump` (by then the state is entered — suppressing it mid-flight would freeze
   Mario, not cleanly keep him crouched). Cross-reference OdysseyDecomp for where
   `PlayerStateLongJump` is started from the squat/jump path (look near
   `PlayerActorHakoniwa::exeJump`/`exeSwim`-style nerves and `tryChangeLongJump`-type
   helpers, or a `PlayerJudge*` if one exists for it — check the judge list). Candidate
   names to grep in OdysseyDecomp: `LongJump`, `tryChange...LongJump`, `PlayerStateLongJump`
   ctor/`appear`/`isEnableLongJump`.
2. **Verify the chosen mangled symbol in dynsym BEFORE hooking:**
   `python scripts/check_nso_symbols.py .romfs-cache/main <mangled>` → must HIT (a missing
   trampoline target aborts the whole module at sail loadSymbols).
3. **Implement** in `hooks/AbilityGateHook.cpp` following the exact judge/predicate pattern:
   call `orig` first; if it wants to start AND `abilityAtLeast("Long Jump", 1)` is false,
   return the suppressing value (false / no-op) so Mario stays in squat. Add a
   `logSuppressed<4>("Long Jump")` throttle line. Add the symbol to `SmoApSymbols.sym`.
4. **Note the gate is independent of Crouch by construction:** Crouch lock already blocks
   long jump (can't squat); this hook only matters once the player has Crouch. No extra
   AND needed in the hook (logic-side AND is the P6 concern).
5. Build → in-game test (have Crouch, NOT Long Jump → crouch+jump-with-momentum does
   nothing; `/send <slot> Long Jump` → it works). Update Status table + session log.

**Step 2 — Backflip gate.** Same jump-from-squat entry, the *stationary* branch (no
dedicated state class). Harder to isolate the exact branch; tackle after Long Jump proves
the squat-jump interception point. Design = SUPPRESS (input swallowed, Mario stays crouched).

**Step 3 (parallel option) — Wall Slide.** If a clean known-judge win is wanted instead of
the jump-state hunt, `PlayerJudgeWallCatch::judge` is a real judge already in OdysseyHeaders
(`_ZNK19PlayerJudgeWallCatch5judgeEv` — verify the length prefix `19`). Pure spike-pattern,
low risk. Good "bank a win" filler between the harder jump-state gates.

**Before the jump-state wave grows: wire the force-unlock command.** `ability_gate_force_unlock`
exists on `ApState` (honored by `abilityAtLeast`) but nothing flips it yet. As brick risk
rises with jump-state gates, add a client→Switch path mirroring `coin_grant`
(protocol dataclass → `switch_server` push → `/abilities unlock|gate` command in
`context.py` → `ApProtocol` parse → `ApClient` dispatch → set the atomic) so one console
command disables every gate if a hook misfires. Currently the only recovery hatch is
`/send <slot> <ability>` (works, but per-ability).

## Session log

### 2026-06-14c — P4 kickoff + judge-gate spike
- Confirmed the capture gate works in-game; began P4.
- Decisions: spike-first; spike target pivoted jumps → judge-backed moves after
  finding backflip/side-flip have no judge class.
- Implemented the spike (Crouch/Roll/Ground Pound) + the frame-thread reader +
  force-unlock atomic + symbols + install wiring. Code complete; build/test pending.
- Wrote this plan doc.
- **Verified all 3 judge symbols HIT in `.romfs-cache/main`** (SMO 1.0.0) via
  `scripts/check_nso_symbols.py` — no sail loadSymbols-abort risk. Corrected the
  earlier llvm-nm reference (project uses check_nso_symbols.py; llvm-nm isn't on PATH).

### 2026-06-14d — spike TESTED, passed; Roll Boost + motion-control findings
- Devon built + deployed + tested in-game. Crouch/Roll/Ground Pound gate and unlock
  exactly as intended (`/send Progressive Crouch` ×1→crouch, ×2→roll;
  `/send Progressive Ground Pound`→ground pound; Cappy bubbles confirm tracking).
- **Defect found:** the 2nd Progressive Crouch (Roll) ALSO enabled Roll Boost. Roll
  Boost should be its own L3 unlock. Root cause: Roll Boost is a separate, motion-only
  move (shake while rolling) that we never gated, so it rides in for free as soon as
  rolling is allowed.
- **Devon flagged** Roll Boost, Up Throw, Down Throw are all motion-control only.
  Added the "Motion-control abilities" section above. Next session: locate the
  shake/motion input read (rolling state + cap-throw dispatch) and gate Roll Boost on
  Progressive Crouch ≥3, then Up/Down Throw on their items.
- Investigation into the Roll Boost hook point (this session, after the handoff doc):
  - Read `PlayerInput.h` — it exposes the full motion-input API. Verified the
    candidates against `.romfs-cache/main` (all HIT). Enumerated all 116
    `PlayerInput::` dynsym getters; the motion/swing/throw-relevant ones:
    `isTriggerRollingRestartSwing`, `isSpinInput`, `isSpinClockwise`/`CounterClockwise`,
    `getCapThrowDir`, `getSwingThrowDir`, `calcCapThrowInput`,
    `isThrowTypeSpiral`/`isThrowTypeRolling`/`isThrowTypeLeftRight`,
    `isTriggerSwingActionMario`/`Cap`, `isTriggerCapSingleHandThrow`/`DoubleHandThrow`,
    `isTriggerSwingDoubleHand*` (reverse/inside/outside dir variants).
  - **Roll Boost → `PlayerInput::isTriggerRollingRestartSwing()`** is the lead: "swing"
    is Nintendo's term for the motion shake, and "RollingRestartSwing" = the swing that
    refreshes/boosts an active roll. Distinct from `isTriggerRolling(bool)` (roll START,
    already gated by the StartRolling judge), so suppressing it should withhold ONLY the
    boost. Fallback if wrong: `isSpinInput()` (generic shake) or the rolling-state read.
  - **IMPLEMENTED** the Roll Boost gate: new `rollRestartSwingHook` trampoline in
    `hooks/AbilityGateHook.cpp` on `_ZNK11PlayerInput28isTriggerRollingRestartSwingEv`,
    gated on `Progressive Crouch >= 3`; symbol added to `SmoApSymbols.sym` (verified
    HIT). Same orig-first/suppress pattern as the judges. **Needs Devon build+test:**
    at PC=2, roll works but shaking gives no boost; at PC=3, boost returns. Watch
    `AbilityGate: suppressed Roll Boost`. CONFIRM it doesn't break normal rolling.
  - **Up/Down Throw (deferred, now scoped):** these are motion-DIRECTION throws — the
    throw direction is computed via `getSwingThrowDir`/`getCapThrowDir`/`calcCapThrowInput`
    + `isThrowType{Spiral,Rolling,LeftRight}`, not a single boolean. Gating "throw up"
    vs "throw down" means intercepting the direction computation and clamping out the
    up/down component, which is materially harder than a boolean predicate. Left for a
    dedicated pass; the API surface above is the starting point. Open Q for Devon stands
    (is there even a button form to fall back to? In vanilla up/down throw are motion-only).

### 2026-06-14f — Long Jump / Backflip symbol discovery (Step 1/2 start)
- Confirmed via OdysseyHeaders: NO `PlayerJudgeStartLongJump`/backflip judge exists — both
  moves are decided inside the squat state, not a judge. So the judge-trampoline pattern
  does not apply; this is the harder jump-state subset.
- Pulled `PlayerStateSquat.cpp` from OdysseyDecomp. Key finding:
  **`PlayerStateSquat::isEnableLongJump() const`** is the long-jump discriminator — returns
  true iff (in the `Brake` nerve) AND (not 2D) AND (`calcFrontDir · velocity > 0`), i.e.
  crouch + forward momentum. This matches Devon's mechanic exactly (crouch+jump+momentum =
  long jump; crouch+jump+stationary = backflip).
- **Symbol VERIFIED HIT** in `.romfs-cache/main` rodata:
  `python scripts/check_nso_symbols.py .romfs-cache/main _ZNK16PlayerStateSquat16isEnableLongJumpEv`
  (controls `_ZNK21PlayerJudgeStartSquat5judgeEv`, `_ZN16PlayerStateSquat6appearEv` also HIT,
  so the verifier is good this session). Not inlined → hookable.
- **BLOCKER for clean suppress:** hooking `isEnableLongJump → false` denies long jump but the
  caller's else-branch is a **backflip** (crouch+jump always yields backflip-or-longjump), so
  isEnableLongJump-only = "long-jump becomes backflip", NOT Devon's chosen SUPPRESS ("nothing
  happens"). And it does nothing to gate Backflip itself. True suppression + Backflip gating
  both require the **squat→jump trigger inside `PlayerActorHakoniwa::exeSquat`** (the caller
  that reads jump input during squat and sets the LongJump/Jump nerve). That function lives in
  `PlayerActorHakoniwa.cpp`, which the web-fetch tool truncates at line 1 (file too large; all
  3 mirrors — raw.githubusercontent, jsdelivr, statically — return only the first `#include`).
  Could not read the caller this session.
- **Decision pending from Devon** (see chat): (a) ship the verified `isEnableLongJump` gate
  now as an interim — denies long jump, but a moving crouch-jump becomes a backflip until
  Backflip is also gated; recoverable via `/send`; or (b) provide `PlayerActorHakoniwa::exeSquat`
  (Devon has the repo / can open the file locally) so the squat→jump trigger can be hooked for
  true suppression of BOTH moves at once, matching the SUPPRESS decision. (b) is the
  design-faithful path; (a) is a quick partial.
- Next regardless: once the caller is in hand, the truth table is — lacks both → suppress the
  squat→jump trigger (nothing); has LJ not BF → allow + isEnableLongJump passthrough (long jump
  when moving, suppress the stationary backflip); has BF not LJ → allow + force isEnableLongJump
  false (backflip only); has both → passthrough.

### 2026-06-14f (cont.) — the caller ISN'T in public decomp; binary-symbol surface mapped
- **Key discovery:** `src/Player/PlayerActorHakoniwa.cpp` on OdysseyDecomp `master` is a
  **40-byte stub** — literally just `#include "Player/PlayerActorHakoniwa.h"`. Confirmed via
  the Chrome extension (`document.documentElement.innerText` = 40 chars; not a fetch-tool
  truncation — the file really is that). So `exeSquat` and the `isEnableLongJump` caller are
  **NOT decompiled publicly**. The "get the caller from decomp" path is therefore closed;
  reading PlayerStateSquat.cpp got us the discriminator but the squat→jump *trigger* lives in
  the undecompiled `PlayerActorHakoniwa::exe*` body. True clean suppression now requires
  binary RE (IDA/Ghidra on main.nso), not a source read.
- **Binary symbols verified in main.nso (for a future RE/hook pass):**
  - HIT `_ZN19PlayerActorHakoniwa8exeSquatEv` — the squat tick (contains the jump trigger).
    Hookable, but it's the whole squat exe; gating just the jump-transition inside needs RE.
  - HIT `_ZN19PlayerStateLongJump6appearEv` — long-jump state ENTRY. Hookable; could redirect
    out on entry when LJ unowned, but that's post-commit (≈1-frame blip, not "nothing").
  - HIT `_ZNK23PlayerJudgePreInputJump5judgeEv` — the jump-input predicate, but it fires for
    ALL jumps (standing too); gating it needs an "am I in squat?" context read, else it breaks
    normal jumping.
  - HIT `_ZNK16PlayerStateSquat16isEnableLongJumpEv` — the LJ-vs-backflip discriminator (from
    earlier).
  - MISS `_ZN19PlayerStateLongJump4killEv`, `_ZN16PlayerStateSquat6updateEv` (inlined/base —
    not standalone targets).
- **Net:** no single verified symbol gives clean SUPPRESS of both moves without either (a) RE
  of `exeSquat`'s internals, or (b) a context-aware judge hook (`PreInputJump::judge` gated on
  "currently in PlayerStateSquat", which needs a state read). Re-surfaced to Devon — the
  honest options are the interim `isEnableLongJump` gate, a `PlayerStateLongJump::appear`
  redirect, or a dedicated IDA pass to gate the squat→jump trigger properly.

### 2026-06-14g — Option 3 ITER 1 implemented (squat-jump suppression)
- Devon chose option (b), the context-aware gate (option 3). Verified the stub finding is
  real via GitHub API (`size:40`), not a read bug — moved on.
- Read main.cpp: `drawMain` is the once-per-frame game-thread tick (drives applyCoinGrant
  etc.); player judges/exes run earlier on the same thread same frame → race-free window.
- Implemented ITER 1 (uncommitted) — full design in the "Option 3" section above:
  - `hooks/AbilityGateHook.cpp`: `g_squatWindow` atomic; `exeSquatBeaconHook`
    (`PlayerActorHakoniwa::exeSquat` → refresh window to 2); `preInputJumpHook`
    (`PlayerJudgePreInputJump::judge` → suppress while window>0 AND owns neither Backflip nor
    Long Jump); `tickAbilityGate()` (decay, called from drawMain).
  - `syms/game/SmoApSymbols.sym`: added `_ZN19PlayerActorHakoniwa8exeSquatEv` +
    `_ZNK23PlayerJudgePreInputJump5judgeEv` (both VERIFIED HIT this session).
  - `main.cpp`: declared + called `smoap::hooks::tickAbilityGate()` in the drawMain per-frame
    block (after tickPendingUncapture).
  - Item names confirmed against items.json: `Backflip`, `Long Jump` (exact).
- **Awaiting Devon build+test** against the risk points in the Option 3 section: (1) CORE —
  with neither owned, crouch+jump does NOTHING (watch `AbilityGate: suppressed squat-jump`);
  (2) normal/standing/run/wall jumps UNAFFECTED; (3) `/send Backflip` or `/send Long Jump`
  re-enables crouch-jumps (ITER 1: either unlocks both). If (1) fails, PreInputJump isn't the
  squat-jump trigger → pivot (gate exeSquat directly, or RE). If green → ITER 2 (per-move
  precision via isEnableLongJump + a PlayerStateSquat::appear beacon to stash the state ptr).

### 2026-06-14h — Option 3 ITER 1 TESTED-PASS in-game
- Devon built + deployed + tested. With neither Backflip nor Long Jump owned, crouch+jump does
  NOTHING — log: `AbilityGate: suppressed squat-jump (Backflip/Long Jump)` for BOTH the
  stationary (backflip) and moving (long jump) cases. **CORE ASSUMPTION CONFIRMED:**
  `PlayerJudgePreInputJump::judge` is the squat-jump trigger and the `exeSquat`-beacon window
  correctly scopes suppression to the squat state. No pivot needed; the mechanism works.
- Marked Status + mapping-table rows accordingly. **Next session = ITER 2** (per-move precision:
  split Backflip/Long Jump via `isEnableLongJump` + `PlayerStateSquat::appear` state-ptr beacon)
  — full step list in the "ITER 2 plan" subsection under "Option 3". ITER 1 is committable once
  Devon's happy (still uncommitted, bundled with the untested Roll Boost gate in the same build).
- Opportunistic follow-ups (low-risk, not blocking): confirm `/send Backflip|Long Jump` unlock,
  and that standing/run/wall jumps are unaffected (none reported broken).

### 2026-06-14e — doc reconciliation + crouch-jump insight
- Picked up mid-stream: confirmed last session's Roll Boost work fully landed on disk —
  `hooks/AbilityGateHook.cpp` (the `rollRestartSwingHook` trampoline, PC≥3),
  `SmoApSymbols.sym` (`_ZNK11PlayerInput28isTriggerRollingRestartSwingEv`), `main.cpp`
  wiring, and `ApState` reader are all present and mutually consistent → no
  loadSymbols-abort risk. Code is complete and uncommitted; still needs Devon build+test.
- **Finished the CLAUDE.md update that ran out of session limit last time:** the P4 line
  now reflects the spike TESTED-PASS + the Roll Boost gate + the crouch-jump insight.
- **Devon's backflip/long-jump mechanic** (crouch+jump-stationary=backflip,
  crouch+jump-momentum=long jump) folded in: new "Crouch-conditioned jumps" section + table
  rows + prerequisite note. Key takeaway recorded — Crouch gating already blocks both for
  free; independent gating only matters when the player has Crouch but not Backflip/LongJump,
  and is a single jump-from-squat decision branched on momentum.
- **Next implementable target:** Long Jump (`PlayerStateLongJump`/`exeLongJump` exist in
  OdysseyHeaders) — need the state-transition selector symbol (NOT `exeLongJump` itself),
  resolve via OdysseyDecomp + verify in dynsym. Wall Slide (`PlayerJudgeWallCatch::judge`)
  is the easiest fully-known-judge next gate if we want another clean spike-pattern win
  first.
- **DESIGN DECISION (Devon):** when a player has Crouch but not Backflip/Long Jump, the
  crouch-jump input is **SUPPRESSED — swallowed, nothing happens** (no move, no fall-back
  standing jump; Mario stays crouched). Recorded in the "Crouch-conditioned jumps" section.
- Roll Boost in-game test deferred to next session (Devon out of time). Wrote a full
  ordered "Next session — handoff outline" above the session log: Step 0 Roll Boost
  build+test, Step 1 Long Jump gate (suppress; resolve+verify the transition-selector
  symbol, NOT `exeLongJump`), Step 2 Backflip, Step 3 optional Wall Slide, plus the
  force-unlock-command reminder before the jump-state wave grows.
