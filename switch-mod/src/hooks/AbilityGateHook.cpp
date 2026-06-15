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
//   Roll Boost   PlayerInput::isTriggerRollingRestartSwing <- Progressive Crouch >= 3  [NEW — confirm in-game]
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
// (below) gates them indirectly: trampoline the jump-input judge
// (PlayerJudgePreInputJump) but only suppress while a squat beacon (exeSquat)
// says we're squatting — so standing jumps are untouched. Side Flip is a
// separate jump-state branch, still deferred. Dive is Progressive Ground Pound
// level 2. Up/Down Throw are motion-direction throws (getSwingThrowDir) — later.
//
// Safety net: ApState::abilityAtLeast() returns true unconditionally when
// ApState::ability_gate_force_unlock is set (toggle in the ImGui debug
// console), so a mis-hooked judge can never permanently brick a save.

#include "hk/hook/Trampoline.h"

#include <atomic>

#include "../ap/ApState.hpp"
#include "../util/Log.hpp"

// Opaque — we never dereference the judge `this`; we only forward it to orig.
class PlayerJudgeStartSquat;
class PlayerJudgeStartRolling;
class PlayerJudgeStartHipDrop;
class PlayerInput;
// Option 3 (squat-jump suppression) — see plan-p4-detail.md "Option 3".
class PlayerActorHakoniwa;
class PlayerJudgePreInputJump;

namespace smoap::hooks {

namespace {

// AP ability item names (match data/items.json "Ability" category exactly —
// the bridge ships these strings verbatim in ability_state).
constexpr const char* kProgressiveCrouch     = "Progressive Crouch";
constexpr const char* kProgressiveGroundPound = "Progressive Ground Pound";
constexpr const char* kBackflip = "Backflip";
constexpr const char* kLongJump = "Long Jump";

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
// so standing/run/wall jumps are untouched. ITER 1: suppress the squat-jump only
// when the player owns NEITHER Backflip NOR Long Jump (the dominant early-game
// case). Owning either currently unlocks both crouch-jumps — refined in ITER 2
// via isEnableLongJump. See plan-p4-detail.md "Option 3".
HkTrampoline<bool, PlayerJudgePreInputJump*> preInputJumpHook =
    hk::hook::trampoline([](PlayerJudgePreInputJump* self) -> bool {
        const bool want = preInputJumpHook.orig(self);
        if (!want) return false;
        if (g_squatWindow.load(std::memory_order_relaxed) <= 0)
            return true;  // not in squat → a normal jump, leave it alone
        auto& ap = smoap::ap::ApState::instance();
        if (ap.abilityAtLeast(kBackflip, 1) || ap.abilityAtLeast(kLongJump, 1))
            return true;  // owns at least one squat-jump move (ITER 1: unlocks both)
        logSuppressed<4>("squat-jump (Backflip/Long Jump)");
        return false;     // owns neither → swallow the jump; Mario stays crouched
    });

}  // namespace

// Called once per frame from drawMain (game thread). Decays the squat window so
// it returns to 0 within ~1 frame of the player leaving the squat state.
void tickAbilityGate() {
    int w = g_squatWindow.load(std::memory_order_relaxed);
    if (w > 0)
        g_squatWindow.store(w - 1, std::memory_order_relaxed);
}

void installAbilityGateHooks() {
    SMOAP_LOG_INFO("installing AbilityGateHook (Crouch/Roll/GroundPound/RollBoost + squat-jump)");
    // judge() is `bool judge() const` — mangled _ZNK<len><Class>5judgeEv.
    // Verified mangling via aarch64 Itanium ABI (no args). These symbols must
    // exist in main.nso (virtual overrides → kept in the vtable); confirm with
    // smo-extract-data + `llvm-nm --dynamic main.nso | grep 5judgeEv`.
    squatJudgeHook.installAtSym<"_ZNK21PlayerJudgeStartSquat5judgeEv">();
    rollJudgeHook.installAtSym<"_ZNK23PlayerJudgeStartRolling5judgeEv">();
    hipDropJudgeHook.installAtSym<"_ZNK23PlayerJudgeStartHipDrop5judgeEv">();
    // Roll Boost (motion-control) — input predicate, not a judge.
    rollRestartSwingHook.installAtSym<"_ZNK11PlayerInput28isTriggerRollingRestartSwingEv">();
    // Option 3: squat-jump suppression (Backflip + Long Jump). The beacon marks
    // "in squat"; the PreInputJump judge is the gate. Both symbols verified HIT
    // in main.nso (2026-06-14). See plan-p4-detail.md "Option 3".
    exeSquatBeaconHook.installAtSym<"_ZN19PlayerActorHakoniwa8exeSquatEv">();
    preInputJumpHook.installAtSym<"_ZNK23PlayerJudgePreInputJump5judgeEv">();
}

}  // namespace smoap::hooks
