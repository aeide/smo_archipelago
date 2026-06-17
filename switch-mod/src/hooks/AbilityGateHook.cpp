// P4 ability enforcement — judge-backed move gates.
//
// SMO decides whether a move may start by calling a PlayerJudge*::judge()
// (an IJudge override returning bool). Trampolining that judge() and forcing
// it to return false when the player hasn't received the gating AP ability
// cleanly suppresses the move with no other side effects — judge() is const
// and only reports "should this move start?", so returning false simply means
// "not now". This is the cleanest enforcement point (the M7 lesson: hook the
// decision, upstream of the visible state change).
//
// Scope so far:
//   Crouch       PlayerJudgeStartSquat::judge       <- Progressive Crouch >= 1  [TESTED]
//   Roll         PlayerJudgeStartRolling::judge     <- Progressive Crouch >= 2  [TESTED]
//   Ground Pound PlayerJudgeStartHipDrop::judge     <- Progressive Ground Pound >= 1  [TESTED]
//   Roll Boost   PlayerInput::isTriggerRollingRestartSwing <- Progressive Crouch >= 3  [TESTED]
//   Roll(GP-out) PlayerInput::isTriggerRollingCancelHipDrop <- Progressive Crouch >= 2  [confirm in-game]
//   Backflip     Option 3 / ITER 2 (below)          <- Backflip item >= 1  [TESTED]
//   Long Jump    Option 3 / ITER 2 (below)          <- Long Jump item >= 1  [TESTED]
//   Wall Slide   PlayerJudge{WallKeep,WallHitDown,WallCatch,WallCatchInputDir}::judge <- Wall Slide >= 1  [confirm in-game]
//   Climb        PlayerJudgePoleClimb::judge        <- Climb item >= 1  [TESTED]
//   Dive         PlayerInput::isTriggerHeadSliding  <- Progressive Ground Pound >= 2  [TESTED]
//   Spin Throw   PlayerInput::isThrowType{Spiral,Rolling} <- Spin Throw item >= 1  [TESTED]
//   Ledge Grab   PlayerJudgeGrabCeil::judge          <- Ledge Grab item >= 1  [judge-hook FAILED; abandoned — Wall Slide enables ledge grab]
//   Dbl/Triple   PlayerContinuousJump::countUp (wrap mCount to 0 past cap) <- Progressive Jump 1/2  [TESTED]
//   GP Jump      PlayerStateHipDrop::isEnableLandCancel <- Ground Pound Jump >= 1  [TESTED]
//   Side Flip    neuter turn-jump physics (PlayerConst::getTurnJump{Power,VelH,Gravity}) <- Side Flip item >= 1  [confirm in-game]
//   Cap Bounce   rs::sendMsgPlayerCapTouchJump (sender, skip delivery) <- Cap Bounce item >= 1  [confirm in-game]
//
// Roll Boost is the shake-while-rolling speed boost (motion-control only), so it
// is NOT a judge — it's gated at the input predicate that reports the boost
// swing. This is a DIFFERENT pattern from the judges: we suppress the input read
// rather than a move-start decision. isTriggerRolling (roll START) is untouched,
// so rolling still works at PC>=2; only the boost is withheld until PC>=3.
// Symbol verified present in main.nso (2026-06-14). If in-game shows this
// predicate isn't the boost (or also breaks normal rolling), the fallback
// candidate is isSpinInput()/the rolling-state shake read — see plan-p4-detail.md.
//
// Backflip / Long Jump have NO judge — they start from a jump-input inside the
// squat state (the squat→jump trigger lives in the undecompiled
// PlayerActorHakoniwa::exe* body; OdysseyDecomp's .cpp is a stub). Option 3
// gates them indirectly via three cooperating hooks:
//   1. PlayerStateSquat::appear (squatAppearHook) — stashes the live
//      PlayerStateSquat* in g_squatState on every squat entry (the state object
//      is a stable actor member — same pointer every time).
//   2. PlayerActorHakoniwa::exeSquat (exeSquatBeaconHook) — refreshes
//      g_squatWindow to 2 every squat frame so the jump hook can tell "in squat".
//   3. PlayerJudgePreInputJump::judge (preInputJumpHook) — suppresses the jump
//      while g_squatWindow > 0 AND the relevant ability is missing. ITER 2 calls
//      isEnableLongJump(g_squatState) to distinguish Backflip (stationary) from
//      Long Jump (moving), so each is gated independently.
//
// Side Flip is the "quick turn jump" — isEnableTurnJump() = mTrigger->isOn(QuickTurn)
// || mCounter>0, with the QuickTurn SET and the READ inlined back-to-back inside the
// undecompiled run nerve. Seven interception attempts (the reader, update(), exeRun,
// the trigger set, executePreMovementNerveChange, the preInputJump judge, and
// PlayerStateJump::appear) all failed: nothing out-of-line runs between the set and
// the read, so the turn-jump STATE can't be cleanly prevented. The getTurnJumpVelH
// probe DID confirm the move is a PlayerConst turn jump whose physics getters run
// out-of-line every frame, so we NEUTER instead of suppress — when Side Flip is
// unowned the turn-jump physics getters return normal-jump values, removing the
// height/distance advantage (the flip animation still plays — accepted trade-off,
// Devon 2026-06-17). See the turnJump*Hook block below. Cap Bounce is gated at the sender
// of the cap touch-jump (rs::sendMsgPlayerCapTouchJump — the real vault trigger),
// NOT sendMsgPlayerCapTrample (the cap-trample reaction, which logged but didn't
// stop the bounce) — see those hooks for the inlining/wrong-message write-up. Dive
// is Progressive Ground Pound level 2.
// Up/Down Throw remain deferred: they are motion-flick throws whose only
// distinguishing signal is the computed throw-DIRECTION vector (no boolean
// predicate exists in the headers — unlike Spin Throw's isThrowType* classifiers),
// so gating them needs the cap-throw-action direction computation clamped, which
// lives in the undecompiled actor body. See plan-p4-detail.md.
//
// Safety net: ApState::abilityAtLeast() returns true unconditionally when
// ApState::ability_gate_force_unlock is set (toggle in the ImGui debug
// console), so a mis-hooked judge can never permanently brick a save.

#include "hk/hook/Trampoline.h"

#include <atomic>

#include <hk/ro/RoUtil.h>

#include "game/Player/PlayerContinuousJump.h"
// Side Flip neuter: the turn-jump physics getters live on PlayerConst, which also
// provides the normal-jump getters we substitute when Side Flip is unowned.
#include "game/Player/PlayerConst.h"

#include "../ap/ApState.hpp"
#include "../util/Log.hpp"

// Opaque — we never dereference these `this` pointers; we only forward to orig
// or (in the Option 3 case) pass to a lazily-resolved function pointer.
class PlayerJudgeStartSquat;
class PlayerJudgeStartRolling;
class PlayerJudgeStartHipDrop;
class PlayerJudgeWallCatch;
class PlayerJudgeWallHitDown;
class PlayerJudgeWallKeep;
class PlayerJudgeWallCatchInputDir;
class PlayerJudgePoleClimb;
class PlayerJudgeGrabCeil;
class PlayerStateHipDrop;
class PlayerInput;
// Option 3 (squat-jump suppression) — see plan-p4-detail.md "Option 3".
class PlayerActorHakoniwa;  // squat beacon only forwards this pointer
class PlayerJudgePreInputJump;
class PlayerStateSquat;

namespace smoap::hooks {

namespace {

// AP ability item names (match data/items.json "Ability" category exactly —
// the bridge ships these strings verbatim in ability_state).
constexpr const char* kProgressiveCrouch     = "Progressive Crouch";
constexpr const char* kProgressiveGroundPound = "Progressive Ground Pound";
constexpr const char* kBackflip = "Backflip";
constexpr const char* kLongJump = "Long Jump";
constexpr const char* kWallSlide = "Wall Slide";
constexpr const char* kClimb     = "Climb";
constexpr const char* kSpinThrow = "Spin Throw";
constexpr const char* kLedgeGrab = "Ledge Grab";
constexpr const char* kProgressiveJump = "Progressive Jump";
constexpr const char* kGroundPoundJump = "Ground Pound Jump";
constexpr const char* kSideFlip = "Side Flip";
constexpr const char* kCapBounce = "Cap Bounce";

// --- Option 3: context-aware squat-jump suppression --------------------------
// Backflip and Long Jump are the only moves that start from a jump-input while
// in the squat state, and neither has a judge (decided in the undecompiled
// PlayerActorHakoniwa::exe* body). We gate the jump-input judge, but ONLY while
// the player is squatting, tracked by a small decaying window:
//   - exeSquat (runs every frame in squat, and only then) refreshes it to 2.
//   - tickAbilityGate() (called once/frame from drawMain) decays it toward 0.
//   - the PreInputJump judge treats window>0 as "in squat".
// Window=2 because the judge fires BEFORE exeSquat within a frame (pre-movement
// nerve change runs first), so frame N's judge must see frame N-1's refresh
// after one decay (2->1). All on the single game thread; relaxed atomic is fine.
// Full design + truth table + test points: plan-p4-detail.md "Option 3".
std::atomic<int> g_squatWindow{0};

// ITER 2: pointer to the live PlayerStateSquat, stashed by squatAppearHook.
// PlayerStateSquat is a stable actor member — same object every squat; the
// pointer is valid for the lifetime of the actor. Game-thread only on both
// read and write; plain pointer is safe (no atomic needed).
const void* g_squatState = nullptr;

// Logs a suppressed move at most ~once/second so a held input can't spam the
// log (judge() can read true for several consecutive frames while the button
// is down). Each move gets its own throttle counter via the template param.
template <int Slot>
void logSuppressed(const char* move) {
    static int s_n = 0;
    if ((s_n++ % 60) == 0) {
        SMOAP_LOG_INFO("AbilityGate: suppressed %s (not yet unlocked)", move);
    }
}

// Crouch — Progressive Crouch level 1.
HkTrampoline<bool, PlayerJudgeStartSquat*> squatJudgeHook =
    hk::hook::trampoline([](PlayerJudgeStartSquat* self) -> bool {
        const bool want = squatJudgeHook.orig(self);
        if (!want) return false;  // move wasn't going to start anyway
        if (smoap::ap::ApState::instance().abilityAtLeast(kProgressiveCrouch, 1))
            return true;
        logSuppressed<0>("Crouch");
        return false;
    });

// Roll (crouch-roll) — Progressive Crouch level 2.
HkTrampoline<bool, PlayerJudgeStartRolling*> rollJudgeHook =
    hk::hook::trampoline([](PlayerJudgeStartRolling* self) -> bool {
        const bool want = rollJudgeHook.orig(self);
        if (!want) return false;
        if (smoap::ap::ApState::instance().abilityAtLeast(kProgressiveCrouch, 2))
            return true;
        logSuppressed<1>("Roll");
        return false;
    });

// Ground Pound (hip drop) — Progressive Ground Pound level 1.
HkTrampoline<bool, PlayerJudgeStartHipDrop*> hipDropJudgeHook =
    hk::hook::trampoline([](PlayerJudgeStartHipDrop* self) -> bool {
        const bool want = hipDropJudgeHook.orig(self);
        if (!want) return false;
        if (smoap::ap::ApState::instance().abilityAtLeast(kProgressiveGroundPound, 1))
            return true;
        logSuppressed<2>("Ground Pound");
        return false;
    });

// Wall Slide — Wall Slide item. The wall-air state (slide + wall jump) is gated
// by the wall-judge FAMILY, not a single judge: the decomp of PlayerStateWallAir
// shows wall contact is kept via mJudgeWallKeep and re-engaged from the jump
// sub-state via the same; the air→wall ENTRY (in the undecompiled actor body)
// consults the WallHitDown / WallCatch judges. Gating PlayerJudgeWallCatch alone
// did NOT stop the slide/jump in-game (2026-06-15), so we suppress the whole
// family while Wall Slide is unowned — orig-first, so each only suppresses a real
// wall interaction. All share log slot 6 ("Wall Slide"). WallHitDownForceRun /
// WallHitDownRolling are deliberately NOT gated (they handle running/rolling
// bonks into walls, not the catch — gating them risks odd run-into-wall behavior).
HkTrampoline<bool, PlayerJudgeWallKeep*> wallKeepJudgeHook =
    hk::hook::trampoline([](PlayerJudgeWallKeep* self) -> bool {
        const bool want = wallKeepJudgeHook.orig(self);
        if (!want) return false;
        if (smoap::ap::ApState::instance().abilityAtLeast(kWallSlide, 1))
            return true;
        logSuppressed<6>("Wall Slide");
        return false;
    });
HkTrampoline<bool, PlayerJudgeWallHitDown*> wallHitDownJudgeHook =
    hk::hook::trampoline([](PlayerJudgeWallHitDown* self) -> bool {
        const bool want = wallHitDownJudgeHook.orig(self);
        if (!want) return false;
        if (smoap::ap::ApState::instance().abilityAtLeast(kWallSlide, 1))
            return true;
        logSuppressed<6>("Wall Slide");
        return false;
    });
HkTrampoline<bool, PlayerJudgeWallCatch*> wallCatchJudgeHook =
    hk::hook::trampoline([](PlayerJudgeWallCatch* self) -> bool {
        const bool want = wallCatchJudgeHook.orig(self);
        if (!want) return false;
        if (smoap::ap::ApState::instance().abilityAtLeast(kWallSlide, 1))
            return true;
        logSuppressed<6>("Wall Slide");
        return false;
    });
HkTrampoline<bool, PlayerJudgeWallCatchInputDir*> wallCatchInputDirJudgeHook =
    hk::hook::trampoline([](PlayerJudgeWallCatchInputDir* self) -> bool {
        const bool want = wallCatchInputDirJudgeHook.orig(self);
        if (!want) return false;
        if (smoap::ap::ApState::instance().abilityAtLeast(kWallSlide, 1))
            return true;
        logSuppressed<6>("Wall Slide");
        return false;
    });

// Ledge Grab — Ledge Grab item. The move is PlayerStateGrabCeil (grabbing a
// wall-top/ceiling edge — isCollisionCodeGrabCeilWall). PlayerJudgeGrabCeil::
// judge() is the entry detector: the decomp shows it returns mIsJudge, set each
// frame by rs::findGrabCeilPos{WallHit,NoWallHit} (purely "is there a grabbable
// edge in reach?"). Forcing it false suppresses ENTRY only — it has nothing to
// do with jumping OFF a grab (the earlier soft-lock fear was unfounded; the jump
// is a separate state transition). Structurally identical to PlayerJudgePoleClimb
// (Climb), which gates cleanly here, so this judge is not inlined at its call site.
//
// IMPORTANT — decoupled from Wall Slide. Ledge grab is normally reached by
// catching a wall and sliding to its top edge, so the Wall Slide family gate
// (above) also blocks the *approach* when Wall Slide is unowned (Devon, 2026-06-15:
// "ledge grab is removed, but collecting Ledge Grab doesn't restore it" — Wall
// Slide was the actual block, not a ledge-grab gate). This judge sits DOWNSTREAM
// of the wall judges: with Wall Slide owned the player can wall-slide up, and this
// gate independently decides whether the grab itself is allowed. So Ledge Grab is
// gated by its own item even when Wall Slide is present.
HkTrampoline<bool, PlayerJudgeGrabCeil*> grabCeilJudgeHook =
    hk::hook::trampoline([](PlayerJudgeGrabCeil* self) -> bool {
        const bool want = grabCeilJudgeHook.orig(self);
        if (!want) return false;
        if (smoap::ap::ApState::instance().abilityAtLeast(kLedgeGrab, 1))
            return true;
        logSuppressed<8>("Ledge Grab");
        return false;
    });

// Climb — Climb item. PlayerJudgePoleClimb::judge decides whether Mario grabs
// onto a pole/net to start climbing. Suppressing it keeps Mario off poles/nets
// until the item is owned. (If in-game shows a climb path leaks through — e.g.
// nets via a separate trigger — add PlayerJudgeStatusPoleClimb::judge, also HIT.)
HkTrampoline<bool, PlayerJudgePoleClimb*> poleClimbJudgeHook =
    hk::hook::trampoline([](PlayerJudgePoleClimb* self) -> bool {
        const bool want = poleClimbJudgeHook.orig(self);
        if (!want) return false;
        if (smoap::ap::ApState::instance().abilityAtLeast(kClimb, 1))
            return true;
        logSuppressed<7>("Climb");
        return false;
    });

// Roll Boost — Progressive Crouch level 3. NOT a judge: this is the
// motion-control "shake while rolling to boost" input predicate. Suppressing
// it withholds the boost while leaving roll START (PC>=2) intact. Mirrors the
// judge pattern (orig first; only suppress when it would have fired).
// CONFIRM IN-GAME that this is the boost and doesn't break normal rolling — if
// wrong, see plan-p4-detail.md "Motion-control abilities" for fallbacks.
HkTrampoline<bool, PlayerInput*> rollRestartSwingHook =
    hk::hook::trampoline([](PlayerInput* self) -> bool {
        const bool want = rollRestartSwingHook.orig(self);
        if (!want) return false;
        if (smoap::ap::ApState::instance().abilityAtLeast(kProgressiveCrouch, 3))
            return true;
        logSuppressed<3>("Roll Boost");
        return false;
    });

// Dive (head slide) — Progressive Ground Pound level 2. NOT a judge: the dive
// trigger lives in the undecompiled PlayerActorHakoniwa body, but the input
// predicate PlayerInput::isTriggerHeadSliding() reports "dive input pressed"
// and is the clean chokepoint (same shape as Roll Boost). Suppress it to
// withhold the dive while leaving Ground Pound (PGP>=1, its own judge) intact.
HkTrampoline<bool, PlayerInput*> headSlidingHook =
    hk::hook::trampoline([](PlayerInput* self) -> bool {
        const bool want = headSlidingHook.orig(self);
        if (!want) return false;
        if (smoap::ap::ApState::instance().abilityAtLeast(kProgressiveGroundPound, 2))
            return true;
        logSuppressed<9>("Dive");
        return false;
    });

// Spin Throw — Spin Throw item. Two earlier attempts were wrong:
//   - isTriggerSpinCap gated ALL throws (the basic Y throw is internally a "spin
//     cap" throw) → killed the neutral throw.
//   - isSpinInput (the raw spin gesture) did NOT suppress the spin throw at all.
// The correct discriminator is the throw-TYPE classifier: PlayerInput::
// isThrowTypeSpiral(const Vector2f&) returns "this throw is the circular/spiral
// spin throw". Forcing it false downgrades a spin attempt to a normal forward
// throw — the neutral throw (not spiral) is untouched. We also gate the sibling
// isThrowTypeRolling (the other non-neutral spin-family type; not the up/down
// throws, which are direction-based separate items) so any spin-gesture throw
// falls back to normal. The Vector2f& arg is ABI-identical to a pointer, so we
// take it as const void* and forward it untouched. Both share log slot 10.
HkTrampoline<bool, PlayerInput*, const void*> throwTypeSpiralHook =
    hk::hook::trampoline([](PlayerInput* self, const void* vec) -> bool {
        const bool want = throwTypeSpiralHook.orig(self, vec);
        if (!want) return false;
        if (smoap::ap::ApState::instance().abilityAtLeast(kSpinThrow, 1))
            return true;
        logSuppressed<10>("Spin Throw");
        return false;
    });
HkTrampoline<bool, PlayerInput*, const void*> throwTypeRollingHook =
    hk::hook::trampoline([](PlayerInput* self, const void* vec) -> bool {
        const bool want = throwTypeRollingHook.orig(self, vec);
        if (!want) return false;
        if (smoap::ap::ApState::instance().abilityAtLeast(kSpinThrow, 1))
            return true;
        logSuppressed<10>("Spin Throw");
        return false;
    });

// Roll-out-of-Ground-Pound — Progressive Crouch level 2 (same gate as Roll).
// After a hip drop, pressing Y / shaking rolls Mario out of it; this path does
// NOT go through PlayerJudgeStartRolling, so it leaked Roll in for free even
// without PC>=2 (Devon, 2026-06-15). PlayerInput::isTriggerRollingCancelHipDrop
// is the input predicate for that cancel; gate it on PC>=2 like the roll judge.
// Takes a bool arg (forwarded to orig untouched).
HkTrampoline<bool, PlayerInput*, bool> rollCancelHipDropHook =
    hk::hook::trampoline([](PlayerInput* self, bool a) -> bool {
        const bool want = rollCancelHipDropHook.orig(self, a);
        if (!want) return false;
        if (smoap::ap::ApState::instance().abilityAtLeast(kProgressiveCrouch, 2))
            return true;
        logSuppressed<1>("Roll");  // share the Roll throttle slot
        return false;
    });

// Progressive Jump (Double / Triple Jump) — NOT a judge. SMO tracks the jump
// combo in PlayerContinuousJump::mCount (0 = single/first jump, 1 = double,
// 2 = triple). countUp() raises mCount on each chained re-jump, and the jump
// state reads it to pick the jump height/animation. In vanilla the combo is a
// FINITE chain that loops: single->double->triple->(combo ends)->single->...
// — after the terminal jump the count returns to 0 so the next jump is a fresh
// single.
//
// We cap the combo at the owned Progressive Jump level immediately after orig
// raises mCount. The cap must WRAP to 0, not pin at the cap: pinning (the
// original bug) froze mCount just below the terminal value so the combo never
// ended, and every chained jump past the cap repeated the capped jump (level 1
// gave single-double-double-double... instead of single-double-single-double).
// Resetting to 0 when the count exceeds the cap reproduces vanilla's "terminal
// jump ends the combo, next jump restarts at single" at the lower cap:
//   owned 0   -> any chained jump resets to single (every jump is single)
//   owned >=1 -> cap = double; the would-be triple ends the combo -> next single
//   owned >=2 -> uncapped (full single/double/triple chain)
// The base single jump (mCount 0) is never touched, so jumping always works.
// abilityAtLeast honors ability_gate_force_unlock, so the >=2 check
// short-circuits to the full chain when force-unlock is on. jumpDir is a
// const sead::Vector3f& (ABI = pointer); forwarded untouched as const void*.
HkTrampoline<void, PlayerContinuousJump*, const void*> continuousJumpCountUpHook =
    hk::hook::trampoline([](PlayerContinuousJump* self, const void* jumpDir) -> void {
        continuousJumpCountUpHook.orig(self, jumpDir);
        if (!self) return;
        auto& st = smoap::ap::ApState::instance();
        if (st.abilityAtLeast(kProgressiveJump, 2)) return;  // full chain owned
        const unsigned maxCount =
            st.abilityAtLeast(kProgressiveJump, 1) ? 1u : 0u;
        if (self->mCount > maxCount) {
            self->mCount = 0;  // combo terminates -> next chained jump is a single
            logSuppressed<11>(maxCount == 0 ? "Double Jump" : "Triple Jump");
        }
    });

// Ground Pound Jump — the high jump out of a hip-drop landing. NOT a judge:
// PlayerStateHipDrop exposes dedicated isEnable* predicates, and
// isEnableLandCancel() is the one that decides whether the landing recovery may
// be canceled into a jump (the GP-jump). HeadSliding (dive, gated separately via
// isTriggerHeadSliding on Progressive Ground Pound L2) and the airborne
// roll-out-of-GP (isTriggerRollingCancelHipDrop, gated on Progressive Crouch L2)
// go through their own predicates, so forcing LandCancel false withholds ONLY
// the GP-jump and leaves a normal hip-drop landing (and dive/roll-out) intact.
// Mechanically the player must own Ground Pound first to reach this state at all
// (PlayerJudgeStartHipDrop is gated on Progressive Ground Pound L1). Orig-first;
// only suppress when it would have allowed the cancel. CONFIRM IN-GAME that this
// is the GP-jump and doesn't block dive/roll-out — if it over-blocks, fall back
// to a hip-drop-land window on PlayerJudgePreInputJump (mirror the squat-jump
// Option 3 pattern). HIT in rodata (2026-06-17).
HkTrampoline<bool, PlayerStateHipDrop*> hipDropLandCancelHook =
    hk::hook::trampoline([](PlayerStateHipDrop* self) -> bool {
        const bool want = hipDropLandCancelHook.orig(self);
        if (!want) return false;
        if (smoap::ap::ApState::instance().abilityAtLeast(kGroundPoundJump, 1))
            return true;
        logSuppressed<12>("Ground Pound Jump");
        return false;
    });

// Side Flip — Side Flip item. SMO's "turn jump": isEnableTurnJump() =
// mTrigger->isOn(QuickTurn) || mCounter>0, with both the QuickTurn SET (skid
// detection) and the READ inlined back-to-back inside the undecompiled run nerve.
// SEVEN interception attempts (the reader, update(), exeRun, the trigger set,
// executePreMovementNerveChange, the preInputJump judge, and PlayerStateJump::appear)
// all failed: nothing out-of-line runs between the set and the read, so the turn-jump
// STATE can't be cleanly prevented (and the spin animation, bound to that state's
// nerve, can't be removed without binary-patching the run nerve). See plan-p4-detail.md
// for the full investigation.
//
// What IS reachable: the turn-jump PHYSICS getters on PlayerConst (virtual → real
// out-of-line bodies, confirmed called every frame of the side-flip arc via the
// getTurnJumpVelH probe). So we NEUTER the move — when Side Flip is unowned, return
// normal-jump values so the side flip provides NO height or distance advantage (it
// behaves like a normal jump and can't reach side-flip-only spots). The flip ANIMATION
// still plays — accepted trade-off (Devon, 2026-06-17), since the clean
// state-suppression seam doesn't exist. Power → scaled to the normal MAX single-jump
// height (see kSideFlipPowerScale below — a bare getJumpPowerMax() only reaches the
// un-extended ~105 floor); VelH → 0 (no backward launch); Gravity → normal jump
// gravity. getJumpPowerMax / getJumpGravity are other PlayerConst virtuals on the same
// object (not hooked → no recursion). Only applied while Side Flip is unowned;
// abilityAtLeast honors force-unlock.
// Target the FULL normal single-jump height. A normal jump launches at
// getJumpPowerMax() but only reaches its tall ~258 height because the jump state
// EXTENDS the rise while A is held (getExtendFrame / held-low-gravity). The side
// flip is a fixed move that never runs that extend phase, so a bare ballistic
// launch at getJumpPowerMax() under getJumpGravity() peaks at only ~105 (the
// un-extended floor) — too weak (a missed input would barely clear anything).
// Peak height is v²/(2g), so to make the un-extended arc reach the held-jump
// height (258) we scale the launch impulse by sqrt(258/105) ≈ 1.567. This caps
// the side flip at the normal MAX single jump (no side-flip-only height advantage)
// while keeping it a usable jump. (If in-game shows it over/undershoots a normal
// full jump, nudge kSideFlipPowerScale.)
constexpr float kSideFlipPowerScale = 1.567f;  // sqrt(258/105)
HkTrampoline<float, PlayerConst*> turnJumpPowerHook =
    hk::hook::trampoline([](PlayerConst* self) -> float {
        if (self && !smoap::ap::ApState::instance().abilityAtLeast(kSideFlip, 1))
            return self->getJumpPowerMax() * kSideFlipPowerScale;  // ≈ normal max-hold height
        return turnJumpPowerHook.orig(self);
    });
HkTrampoline<float, PlayerConst*> turnJumpVelHHook =
    hk::hook::trampoline([](PlayerConst* self) -> float {
        if (self && !smoap::ap::ApState::instance().abilityAtLeast(kSideFlip, 1))
            return 0.0f;  // no backward launch (keeps only carried momentum)
        return turnJumpVelHHook.orig(self);
    });
HkTrampoline<float, PlayerConst*> turnJumpGravityHook =
    hk::hook::trampoline([](PlayerConst* self) -> float {
        if (self && !smoap::ap::ApState::instance().abilityAtLeast(kSideFlip, 1))
            return self->getJumpGravity();  // normal-jump arc
        return turnJumpGravityHook.orig(self);
    });

// Cap Bounce (cap vault) — Cap Bounce item. The held/thrown HackCap detects Mario
// landing on it and sends a sensor message to deliver the bounce. There are TWO
// related cap messages, and the v2 hook picked the wrong one:
//   - rs::sendMsgPlayerCapTrample — Mario TRAMPLES the cap (the cap reacts/wobbles
//     to being stepped on). Hooking this logged but did NOT stop the bounce
//     (2026-06-17): it's the cap's reaction, not Mario's vault.
//   - rs::sendMsgPlayerCapTouchJump — the actual cap-bounce / vault trigger (the
//     "touch the cap and jump off it" message). THIS is the bounce. (v3.)
// (The generic enemy-stomp bounce is rs::sendMsgRequestPlayerTrampleJump, which
// takes an f32 power — a distinct function, so gating CapTouchJump is cap-specific
// and won't break Goomba/enemy stomps.)
// We gate the SENDER: when Cap Bounce is unowned, skip delivery entirely (don't
// call orig) and report "not handled", so Mario never receives the touch-jump and
// falls past Cappy. Covers BOTH the walk-into and dive-into-Cappy variants (the cap
// sends the same message regardless of how Mario approached). Args are two
// al::HitSensor* (forwarded untouched as const void*). HIT (2026-06-17).
HkTrampoline<bool, const void*, const void*> capTouchJumpSendHook =
    hk::hook::trampoline([](const void* source, const void* target) -> bool {
        if (smoap::ap::ApState::instance().abilityAtLeast(kCapBounce, 1))
            return capTouchJumpSendHook.orig(source, target);
        logSuppressed<14>("Cap Bounce");
        return false;  // not delivered → no bounce
    });

// Squat-state entry beacon — stashes the live PlayerStateSquat* so that
// preInputJumpHook can call isEnableLongJump on it (ITER 2). The state object
// is a stable actor member and never moves, so the pointer stays valid for the
// lifetime of the actor. (PlayerStateSquat::appear fires once per squat entry,
// NOT every frame — the per-frame refresh is done by exeSquatBeaconHook below.)
HkTrampoline<void, PlayerStateSquat*> squatAppearHook =
    hk::hook::trampoline([](PlayerStateSquat* self) -> void {
        g_squatState = self;
        squatAppearHook.orig(self);
    });

// Squat beacon — refreshes the "in squat" window every squat tick. We never
// touch `self`; orig does all the work. (PlayerActorHakoniwa::exeSquat is the
// undecompiled squat tick; we only use it as a once-per-frame-in-squat signal.)
HkTrampoline<void, PlayerActorHakoniwa*> exeSquatBeaconHook =
    hk::hook::trampoline([](PlayerActorHakoniwa* self) -> void {
        g_squatWindow.store(2, std::memory_order_relaxed);
        exeSquatBeaconHook.orig(self);
    });

// Jump-input gate. PlayerJudgePreInputJump::judge() reports "should a jump start
// now?" for ALL jump contexts. We only override it while squatting (window>0),
// so standing/run/wall jumps are untouched.
//
// ITER 2: when in squat, call PlayerStateSquat::isEnableLongJump(g_squatState)
// to tell which squat-jump the player is attempting (true = Long Jump when moving,
// false = Backflip when stationary). Gate each independently against its own AP
// ability item. See plan-p4-detail.md "Option 3" truth table.
//
// isEnableLongJump is resolved lazily via hk::ro::lookupSymbol (NOT via sail's
// installAtSym) so a missing dynsym entry soft-fails instead of aborting module
// init. Fallback when the fn or state ptr is unavailable: treat as Backflip
// (stationary case) — conservative, but in practice g_squatState is always valid
// when the gate is active (see timing analysis in the 2026-06-15 session log).
HkTrampoline<bool, PlayerJudgePreInputJump*> preInputJumpHook =
    hk::hook::trampoline([](PlayerJudgePreInputJump* self) -> bool {
        const bool want = preInputJumpHook.orig(self);
        if (!want) return false;
        if (g_squatWindow.load(std::memory_order_relaxed) <= 0)
            return true;  // not in squat → normal jump, leave it alone
                          // (Side Flip is handled by neutering the turn-jump physics
                          //  getters — the preInputJump clear never fired for it.)

        // --- in squat: this jump is a Backflip or Long Jump ---
        // Lazy-resolve isEnableLongJump once. Cached as a static void* so the
        // lookup runs at most once across the whole session.
        using IsEnableLongJumpFn = bool (*)(const void*);
        static void* s_isEnableLongJumpPtr = nullptr;
        if (!s_isEnableLongJumpPtr) {
            const auto addr = hk::ro::lookupSymbol(
                "_ZNK16PlayerStateSquat16isEnableLongJumpEv");
            if (addr) {
                s_isEnableLongJumpPtr = reinterpret_cast<void*>(addr);
                SMOAP_LOG_INFO("AbilityGate: isEnableLongJump resolved @ 0x%lx",
                               static_cast<unsigned long>(addr));
            } else {
                SMOAP_LOG_WARN("AbilityGate: isEnableLongJump not in dynsym — "
                               "squat-jumps will gate as Backflip (fallback)");
            }
        }

        bool moving = false;
        if (g_squatState && s_isEnableLongJumpPtr) {
            moving = reinterpret_cast<IsEnableLongJumpFn>(
                s_isEnableLongJumpPtr)(g_squatState);
        }
        // moving=true → Long Jump (forward momentum); false → Backflip (stationary)
        const char* needed = moving ? kLongJump : kBackflip;
        if (smoap::ap::ApState::instance().abilityAtLeast(needed, 1))
            return true;  // owns the required move — allow
        if (moving) logSuppressed<4>("Long Jump");
        else        logSuppressed<5>("Backflip");
        return false;  // swallow the jump; Mario stays crouched
    });

}  // namespace

// Called once per frame from drawMain (game thread). Decays the squat window so
// it returns to 0 within ~1 frame of the player leaving the squat state.
// Also clears g_squatState on window expiry (belt-and-braces against stale
// access — the gate is already inactive at window=0, so this is defensive only).
void tickAbilityGate() {
    int w = g_squatWindow.load(std::memory_order_relaxed);
    if (w > 0) {
        --w;
        g_squatWindow.store(w, std::memory_order_relaxed);
        if (w == 0)
            g_squatState = nullptr;
    }
}

void installAbilityGateHooks() {
    SMOAP_LOG_INFO("installing AbilityGateHook (Crouch/Roll/GPound/RollBoost/RollCancelHipDrop/WallSlide-family/Climb/LedgeGrab/Dive/SpinThrow/ProgJump/GPJump/SideFlip/CapBounce + squat-jump ITER2)");
    // judge() is `bool judge() const` — mangled _ZNK<len><Class>5judgeEv.
    // Verified mangling via aarch64 Itanium ABI (no args). These symbols must
    // exist in main.nso (virtual overrides → kept in the vtable); confirm with
    // smo-extract-data + `llvm-nm --dynamic main.nso | grep 5judgeEv`.
    squatJudgeHook.installAtSym<"_ZNK21PlayerJudgeStartSquat5judgeEv">();
    rollJudgeHook.installAtSym<"_ZNK23PlayerJudgeStartRolling5judgeEv">();
    hipDropJudgeHook.installAtSym<"_ZNK23PlayerJudgeStartHipDrop5judgeEv">();
    // Wall Slide — the wall-judge FAMILY (WallCatch alone did NOT gate the slide/
    // jump; WallKeep is the confirmed wall-contact gate per the decomp). Class
    // name lengths: WallKeep=19, WallHitDown=22, WallCatch=20, WallCatchInputDir=28.
    wallKeepJudgeHook.installAtSym<"_ZNK19PlayerJudgeWallKeep5judgeEv">();
    wallHitDownJudgeHook.installAtSym<"_ZNK22PlayerJudgeWallHitDown5judgeEv">();
    wallCatchJudgeHook.installAtSym<"_ZNK20PlayerJudgeWallCatch5judgeEv">();
    wallCatchInputDirJudgeHook.installAtSym<"_ZNK28PlayerJudgeWallCatchInputDir5judgeEv">();
    // Climb — PlayerJudgePoleClimb::judge (20).
    poleClimbJudgeHook.installAtSym<"_ZNK20PlayerJudgePoleClimb5judgeEv">();
    // Ledge Grab — PlayerJudgeGrabCeil::judge (19). Decoupled from Wall Slide:
    // sits downstream of the wall judges so it gates the grab on its own item.
    grabCeilJudgeHook.installAtSym<"_ZNK19PlayerJudgeGrabCeil5judgeEv">();
    // Roll Boost (motion-control) — input predicate, not a judge.
    rollRestartSwingHook.installAtSym<"_ZNK11PlayerInput28isTriggerRollingRestartSwingEv">();
    // Roll-out-of-Ground-Pound — input predicate; gate on PC>=2 (Roll). Has a bool arg.
    rollCancelHipDropHook.installAtSym<"_ZNK11PlayerInput29isTriggerRollingCancelHipDropEb">();
    // Dive (head slide) — Progressive Ground Pound L2. Input predicate.
    headSlidingHook.installAtSym<"_ZNK11PlayerInput20isTriggerHeadSlidingEv">();
    // Spin Throw — gate the throw-TYPE classifiers (spiral + rolling), NOT
    // isTriggerSpinCap (gates the neutral throw) nor isSpinInput (didn't suppress).
    // Forcing these false downgrades a spin throw to a normal throw. Arg is a
    // const sead::Vector2f& (taken as const void*).
    throwTypeSpiralHook.installAtSym<"_ZNK11PlayerInput17isThrowTypeSpiralERKN4sead7Vector2IfEE">();
    throwTypeRollingHook.installAtSym<"_ZNK11PlayerInput18isThrowTypeRollingERKN4sead7Vector2IfEE">();
    // Progressive Jump (Double / Triple) — clamp the PlayerContinuousJump combo
    // counter; NOT a judge. "PlayerContinuousJump"=20, "countUp"=7; arg is a
    // const sead::Vector3f& (N4sead7Vector3IfEE). HIT (2026-06-17).
    continuousJumpCountUpHook.installAtSym<"_ZN20PlayerContinuousJump7countUpERKN4sead7Vector3IfEE">();
    // Ground Pound Jump — gate the hip-drop land-cancel predicate. "PlayerStateHipDrop"=18,
    // "isEnableLandCancel"=18, const. HIT (2026-06-17).
    hipDropLandCancelHook.installAtSym<"_ZNK18PlayerStateHipDrop18isEnableLandCancelEv">();
    // Side Flip (neuter) — the turn-jump decision is inlined in the undecompiled run
    // nerve (7 interception attempts failed). Instead we neuter the turn-jump PHYSICS
    // getters (PlayerConst virtuals, confirmed every-frame in-path) so the side flip
    // gives no advantage when Side Flip is unowned. "PlayerConst"=11;
    // "getTurnJumpPower"=16, "getTurnJumpVelH"=15, "getTurnJumpGravity"=18; all const.
    // All HIT (2026-06-17).
    turnJumpPowerHook.installAtSym<"_ZNK11PlayerConst16getTurnJumpPowerEv">();
    turnJumpVelHHook.installAtSym<"_ZNK11PlayerConst15getTurnJumpVelHEv">();
    turnJumpGravityHook.installAtSym<"_ZNK11PlayerConst18getTurnJumpGravityEv">();
    // Cap Bounce — gate the SENDER of the cap touch-jump (the actual vault trigger),
    // NOT sendMsgPlayerCapTrample (the cap-trample reaction, which logged but didn't
    // stop the bounce). _ZN2rs25sendMsgPlayerCapTouchJumpEPN2al9HitSensorES2_. HIT (2026-06-17).
    capTouchJumpSendHook.installAtSym<"_ZN2rs25sendMsgPlayerCapTouchJumpEPN2al9HitSensorES2_">();
    // Option 3 ITER 2: squat-jump suppression (Backflip + Long Jump).
    // squatAppearHook stashes the PlayerStateSquat* for isEnableLongJump calls
    // (ITER 2 per-move split). exeSquatBeaconHook refreshes the "in squat"
    // window. preInputJumpHook is the gate. All three symbols verified HIT in
    // main.nso (2026-06-14). isEnableLongJump is resolved lazily via
    // hk::ro::lookupSymbol (no installAtSym — soft-fail if absent).
    squatAppearHook.installAtSym<"_ZN16PlayerStateSquat6appearEv">();
    exeSquatBeaconHook.installAtSym<"_ZN19PlayerActorHakoniwa8exeSquatEv">();
    preInputJumpHook.installAtSym<"_ZNK23PlayerJudgePreInputJump5judgeEv">();
}

}  // namespace smoap::hooks
