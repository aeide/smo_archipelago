# P4 — Ability enforcement (gating Mario's moveset on AP ability items)

**Living document** — canonical plan + tracker for P4 (the last v2-vision phase).
P4 is the *enforcement* layer on top of P3-3b ability *tracking*: the bridge ships
`ability_state` (a full-overwrite per-ability count snapshot), the Switch stores it in
`ApState::ability_table` under a seqlock, and P4 reads that from the frame thread and
suppresses moves the player hasn't received. Read `CLAUDE.md` invariants first.

**Status: P4 feature-complete — every ability gate is implemented.** All moves are
TESTED-PASS or code-complete; the two final items (Side Flip neuter tuning, Up/Down
Throw) are code-complete and awaiting in-game confirmation (see "Remaining work"). Item
pool, classification, wire protocol, tracking bitfield, Cappy unlock bubble, and
duplicate→coins are all P3 and done.

---

## Architecture — the two enforcement patterns (load-bearing, reusable)

**Pattern A — judge() trampoline (the clean one).** SMO decides whether a move may
start by calling a `PlayerJudge*`'s `IJudge::judge() const` (returns "should this move
start NOW?"). Trampoline the concrete `judge()` and return false when the gating AP
ability isn't owned → the move cleanly never starts. `judge()` is `const` and
side-effect-free (`update()` mutates state, not `judge()`), so forcing false is pure
suppression with no teardown to race. This is the preferred point (M7 lesson: hook the
decision, upstream of the visible change). Mangling: `bool Class::judge() const` →
`_ZNK<len><Class>5judgeEv`.

**Pattern B — input-predicate / message-sender suppression (for no-judge moves).**
Motion moves (Roll Boost, Dive, Spin Throw) and message-driven moves (Cap Bounce) have
no judge. Gate the out-of-line input predicate (`PlayerInput::isTrigger*`/`isThrowType*`)
or the `rs::sendMsg*` sender instead: call `orig` first, suppress only when it would have
fired. Same orig-first/suppress shape as the judges.

**Verification is mandatory** before hooking any symbol — a trampoline target missing
from `main.nso`'s dynsym aborts the whole module at sail `loadSymbols` (NOT a soft-fail):

```
python scripts/check_nso_symbols.py .romfs-cache/main <mangled> [<mangled> ...]
```

(`.romfs-cache/main` is produced by the romfs extraction. Needs only `pip install lz4`,
NOT llvm-nm.) A HIT symbol still isn't a guarantee the decision *flows through* it —
trivial predicates are often inlined at the hot call site while the linker keeps an
out-of-line copy (hook installs, does nothing). When the target is inlined, attack its
out-of-line *inputs*, and prefer functions called from many sites (those stay
out-of-line). **Read the decomp before picking a chokepoint** — see the Side Flip saga.

### Frame-thread reader
`ApState::abilityAtLeast(name, level)` — lock-free seqlock read over `ability_table`,
returns `count >= level`, and returns true unconditionally when
`ability_gate_force_unlock` is set. Counts are monotonic, so a torn/stale read can only
briefly *under*-report — never grant a move the player doesn't own.

### Progressive-chain semantics
| Item | count→move |
|---|---|
| `Progressive Jump` (pool ×2) | 1 = Double Jump, 2 = Triple Jump |
| `Progressive Crouch` (pool ×3) | 1 = Crouch, 2 = Roll, 3 = Roll Boost |
| `Progressive Ground Pound` (pool ×3 = 2 chain + 1 clone) | 1 = Ground Pound, 2 = Dive; 3rd copy is a clone→100 coins |

### Crouch-conditioned jumps (mechanical free-gating)
Backflip and Long Jump start *from the squat state*, so the Crouch gate
(`PlayerJudgeStartSquat`) already blocks both for free while Crouch is locked — their
own gates only matter once the player has Crouch but not the jump. **P6 logic must still
AND Backflip/Long Jump on `Progressive Crouch:1`, and Ground Pound Jump on
`Progressive Ground Pound:1`**, so the randomizer never expects them before the
prerequisite is reachable.

### Safety net (recovery from a misfired gate)
`ability_gate_force_unlock` (ApState atomic, default false, honored by `abilityAtLeast`)
makes every gate fail-open. It is NOT yet wired to a command — the current recovery
hatch is `/send <slot> <ability>` (per-ability, works because `ability_state` is a
full-overwrite snapshot). **Deferred work:** wire a client→Switch `/abilities
unlock|gate` command mirroring `coin_grant` (protocol dataclass → switch_server push →
context.py command → ApProtocol parse → ApClient dispatch → set the atomic) so one
console command disables every gate at once. Low priority — no gated move is required to
leave a kingdom, so brick risk is low.

---

## Ability → enforcement mapping (final)

All hooks live in `hooks/AbilityGateHook.cpp`; symbols in `syms/game/SmoApSymbols.sym`.
✅ = TESTED-PASS in-game · 🟢 = code-complete, confirm in-game · 🟡 = in active testing ·
❓ = not started.

| Ability item | Move | Hook point | Gate | Status |
|---|---|---|---|---|
| Progressive Crouch L1 | Crouch | `PlayerJudgeStartSquat::judge` | ≥1 | ✅ |
| Progressive Crouch L2 | Roll | `PlayerJudgeStartRolling::judge` + `PlayerInput::isTriggerRollingCancelHipDrop` (roll-out-of-GP) | ≥2 | ✅ judge / 🟢 GP-out |
| Progressive Crouch L3 | Roll Boost | `PlayerInput::isTriggerRollingRestartSwing` (motion shake-while-rolling) | ≥3 | ✅ |
| Progressive Ground Pound L1 | Ground Pound | `PlayerJudgeStartHipDrop::judge` (normal hip drop) **+** `PlayerInput::isTriggerHipDrop` (input trigger — also covers the spin-jump down-attack, a separate undecompiled `exeJump` path using `getSpinJumpDownFall*` physics that bypasses the judge) | ≥1 | ✅ judge / 🟢 input-trigger |
| Progressive Ground Pound L2 | Dive | `PlayerInput::isTriggerHeadSliding` | ≥2 | ✅ |
| Wall Slide | Wall catch/slide | `PlayerJudge{WallKeep,WallHitDown,WallCatch,WallCatchInputDir}::judge` family | ≥1 | 🟢 |
| Ledge Grab | Ledge grab | none — `PlayerJudgeGrabCeil::judge` hook FAILED/abandoned; **Wall Slide is the real gate** (ledge grab is reached via wall-slide, so the Wall Slide family blocks it). The grabCeil hook remains as a downstream no-op. | ≥1 (via Wall Slide) | ✅ (via Wall Slide) |
| Climb | Pole/net climb | `PlayerJudgePoleClimb::judge` | ≥1 | ✅ |
| Progressive Jump L1/L2 | Double / Triple Jump | `PlayerContinuousJump::countUp` — wrap `mCount` to 0 past the owned cap | 1/2 | ✅ |
| Backflip | Backflip | **Option 3** squat-jump suppression (`PlayerJudgePreInputJump::judge` while the `exeSquat` window is open; `isEnableLongJump` splits BF/LJ) | ≥1 | ✅ |
| Long Jump | Long jump | **Option 3**, same hook as Backflip (moving branch) | ≥1 | ✅ |
| Side Flip | Side flip | **NEUTER** the turn-jump physics getters (`PlayerConst::getTurnJump{Power,VelH,Gravity}`) — the STATE can't be suppressed (inlined, no seam), so we strip the height/distance advantage; flip animation still plays | ≥1 | 🟡 in-test |
| Ground Pound Jump | GP-jump | `PlayerStateHipDrop::isEnableLandCancel` | ≥1 | ✅ |
| Cap Bounce | Bounce on thrown cap | gate the SENDER `rs::sendMsgPlayerCapTouchJump` (skip delivery when unowned) | ≥1 | ✅ |
| Spin Throw | Spin cap throw | `PlayerInput::isThrowTypeSpiral` (horizontal flick → downgrade to normal throw) | ≥1 | ✅ |
| Up Throw | Cap throw up | `PlayerInput::isThrowTypeRolling` with `v.y >= 0` (vertical flick, split by sign) | ≥1 | 🟢 |
| Down Throw | Cap throw down | `PlayerInput::isThrowTypeRolling` with `v.y < 0` | ≥1 | 🟢 |
| Spin | High spin jump | `PlayerJudgeStartGroundSpin::judge` (decomp: `isSpinInput() && isOnGround`) — suppress ground-spin entry → no spin jump; spin animation also drops. **GP-out-of-spin is gated via the `isTriggerHipDrop` input hook in the Ground Pound row** (in-game proved it does NOT route through `PlayerJudgeStartHipDrop` — separate undecompiled path). Fallback if a post-spin boost window leaks: neuter `PlayerConst::getSpinJump{Power,Gravity,MoveSpeedMax}` like Side Flip (symbols UNVERIFIED). New item (from the spin-ability-gate feasibility doc); also joins the 496 vault tier in `compile_moon_logic.py`. | ≥1 | ✅ spin-jump gated in-game; 🟢 GP-out awaiting confirm |
| Wall Slide / Prog. GP clones | — | duplicate→100 coins via the P1 coin path; no gate | n/a | ✅ (P3) |

---

## Remaining work

### 1. Side Flip neuter — finish in-game tuning (active)
Resolved as a physics NEUTER (the turn-jump STATE is inlined into the undecompiled run
nerve with no out-of-line interception seam — see the Side Flip saga below). When Side
Flip is unowned, the three `PlayerConst::getTurnJump*` virtuals return normal-jump
values: VelH→0 (no backward launch), Gravity→`getJumpGravity()`, Power→
`getJumpPowerMax() * kSideFlipPowerScale`. A bare `getJumpPowerMax()` only reaches the
*un-extended* ballistic floor (~105) because the side flip never runs the held-A extend
phase that gives a normal jump its tall ~258; since peak height ∝ v²/(2g),
`kSideFlipPowerScale = √(258/105) ≈ 1.567` scales the impulse to the normal MAX
single-jump height. **The flip animation still plays** (bound to the uncatchable nerve)
— accepted trade-off (Devon, 2026-06-17). No suppression log fires (it's a physics
override) — verify by feel/height.
- **Open test (2026-06-17):** `kSideFlipPowerScale` temporarily set to `0.0f` to probe
  whether a zero-impulse turn jump effectively *removes* the side flip (no rise → spin
  in place / immediate fall). Revert to `1.567f` after the test. Watch for an odd
  hang/lock if the airborne turn-jump nerve persists at zero velocity.

### 2. Up Throw / Down Throw — code-complete, confirm in-game
Resolved cleanly via the SAME `isThrowType*` family as Spin Throw (the
`getCapThrowDir`/`calcCapThrowInput` names from the earlier plan don't exist in
OdysseyHeaders — they were aspirational). The OdysseyDecomp source of
`PlayerInput::isThrowTypeRolling(const Vector2f& v)` returns true exactly when the throw
GESTURE is **vertical-dominant** (`|v.y| >= |v.x|` and `v.y != 0`) — i.e. the up/down
flick — and the gesture vector is the function ARGUMENT, so `throwTypeRollingHook` reads
`v.y`'s sign to split up vs down and gates each on its own item. Forcing the classifier
false downgrades the vertical flick to a normal forward throw (same neuter shape proven
for Spin Throw / Spiral). **No new symbols, no undecompiled actor access.**
- **Fixed a latent bug:** Spin Throw previously gated BOTH `isThrowTypeSpiral` AND
  `isThrowTypeRolling` ("belt and braces"), which silently blocked the up/down throws too
  (and tied them to Spin Throw ownership). Spin Throw now gates only Spiral; Rolling is
  the dedicated Up/Down gate.
- **Sign convention unverified:** `kUpThrowIsPositiveY` (default true) maps `v.y >= 0` to
  up. The hook logs the suppressed direction; if owning Up Throw restores the DOWN throw,
  flip that one constant. **Devon test:** with neither owned, an up-flick and a down-flick
  cap throw both become normal forward throws (watch `AbilityGate: suppressed Up/Down
  Throw`, slots 15/16); `/send <slot> Up Throw` restores only the up-flick; confirm the
  neutral forward throw and the spin throw are unaffected.

---

## Option 3 — context-aware squat-jump suppression (DONE, kept for reference)

Backflip and Long Jump have no judge (the squat→jump trigger is in the undecompiled
`PlayerActorHakoniwa` body — its `.cpp` is a 40-byte stub on OdysseyDecomp). Gated
without RE-ing the trigger, using only verified symbols:
- `PlayerActorHakoniwa::exeSquat` (runs every frame in squat, and only then) → beacon
  sets `g_squatWindow = 2` each squat tick; `tickAbilityGate()` in drawMain decays it.
- `PlayerJudgePreInputJump::judge` (the jump-input predicate) → suppress while
  `g_squatWindow > 0` (in squat) AND the relevant ability is missing.
- `PlayerStateSquat::appear` → stashes `g_squatState`; `PlayerStateSquat::isEnableLongJump`
  (lazy `hk::ro::lookupSymbol`) splits stationary(Backflip)/moving(Long Jump).

Window = 2 because the judge fires BEFORE exeSquat within a frame (so frame N sees frame
N-1's refresh after one decay). Single game thread; relaxed atomic is fine. Truth table:
own neither → both suppressed; own BF → stationary only; own LJ → moving only; own both →
both. **TESTED-PASS in-game** (both ITER 1 both-unowned and ITER 2 per-move split).

---

## The Side Flip saga (8 iterations → NEUTER) — lesson archive

Kept as a cautionary tale (it cost ~6 build cycles of guessing). `isEnableTurnJump() =
mTrigger->isOn(QuickTurn) || mCounter>0`, with the QuickTurn SET (skid detection) and the
READ inlined back-to-back inside the undecompiled run nerve. Eight attempts to suppress
the STATE all failed:
1. `isEnableTurnJump` getter — inlined.
2. `PlayerCounterQuickTurnJump::update` (arms mCounter) — inlined; also mCounter is only
   the grace window, the *trigger* is the primary path (decomp read caught this).
3. `exeRun` mCounter clamp — update() isn't called from exeRun.
4. `PlayerTrigger::set(EActionTrigger)` (the trigger setter) — also inlined at the skid site.
5. `executePreMovementNerveChange` per-frame clear — runs BEFORE the run nerve's set+read.
6. `PlayerJudgePreInputJump::judge` non-squat clear — same, doesn't straddle the set/read.
7. `PlayerStateJump::appear` clear — never fired (not the entry).
8. Instrumented build (`[sf-appear]`/`[sf-velH]` probes) → **case 3 confirmed:**
   `getTurnJumpVelH` fires every frame (it IS a PlayerConst turn jump), but no out-of-line
   point sits between the inlined set and read. Same wall as Ledge Grab.

**Conclusion:** no clean state-suppression seam exists. The only in-path, out-of-line
lever is the turn-jump PHYSICS (the `getTurnJump*` virtuals) → NEUTER instead of suppress.
General lesson reinforced: **read the decomp first**; a HIT symbol ≠ the decision flows
through it; for inlined predicates attack out-of-line *inputs* called from many sites.

---

## Session log (condensed)

- **2026-06-14c–h:** P4 kickoff; judge-gate spike (Crouch/Roll/Ground Pound) TESTED-PASS;
  frame-thread reader + `ability_gate_force_unlock` added. Roll Boost gate
  (`isTriggerRollingRestartSwing`, PC≥3). Backflip/Long Jump via Option 3 squat-jump
  suppression — ITER 1 (both-unowned) then ITER 2 (per-move split) both TESTED-PASS.
- **2026-06-17:** Cap Bounce TESTED-PASS (`sendMsgPlayerCapTouchJump` sender — earlier
  `sendMsgPlayerCapTrample` was the wrong message). Wave of code-complete gates added:
  Dive (`isTriggerHeadSliding`), Spin Throw (`isThrowType{Spiral,Rolling}`), roll-out-of-GP
  (`isTriggerRollingCancelHipDrop`), Progressive Jump (`countUp` wrap), Ground Pound Jump
  (`isEnableLandCancel`), Wall Slide family, Climb (`PoleClimb::judge`). Ledge Grab judge
  hook abandoned (Wall Slide is the real gate).
- **2026-06-17 (Side Flip):** 8 iterations (see saga above) → resolved as physics NEUTER.
  Then height-tuned: bare `getJumpPowerMax()` was too weak (~105 floor); scaled by
  `√(258/105) ≈ 1.567` to the normal max single-jump height. Devon liked `0.0f`
  (zero-impulse turn jump ≈ removes the move; only the voice line still plays — the voice
  is fired from the same uncatchable inlined nerve / opaque `PlayerSeCtrl`, so not a
  cheap suppress). Scale left at the tested value per Devon.
- **2026-06-17 (Up/Down Throw — final P4 abilities, code-complete):** read the
  OdysseyDecomp `isThrowType{Spiral,Rolling}` bodies — Spiral = horizontal-dominant
  gesture, Rolling = vertical-dominant (the up/down flick), and the gesture Vector2f is
  the argument. So `throwTypeRollingHook` now reads `v.y`'s sign to gate Up Throw
  (`v.y >= 0`) / Down Throw (`v.y < 0`) independently; Spin Throw narrowed to Spiral-only
  (it had been over-gating Rolling, silently blocking up/down). No new symbols / no
  undecompiled actor. Sign convention (`kUpThrowIsPositiveY`) unverified — logs + one
  constant to flip. Needs Devon build+test.
