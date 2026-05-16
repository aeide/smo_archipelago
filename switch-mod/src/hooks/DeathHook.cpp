// Hook on PlayerHitPointData::kill().
//
// Mario's HP transitions to 0 here regardless of cause (fall, drown, poison,
// damage, abyss). Three responsibilities:
//   1. Outbound: emit a debounced death event for the bridge (which forwards
//      as a Bounce when DeathLink is enabled bridge-side).
//   2. Inbound apply support: cache `self` into ApState::player_hp_cache so
//      maybeApplyInboundKill can re-invoke kill() later via DeathHook::Orig
//      (skipping our Callback, breaking the loop).
//   3. Loopback guard: synthetic kills set ApState::synthetic_death_this_frame
//      before calling Orig, so we skip the outbound report and don't bounce
//      our own induced deaths back into AP.

#include "lib.hpp"
#include "../ap/ApFrameBridge.hpp"
#include "../ap/ApState.hpp"
#include "../util/Log.hpp"
#include "DeathHook.hpp"
#include "HookSymbols.hpp"
#include "SoftInstall.hpp"

class PlayerHitPointData;

namespace smoap::hooks {

namespace {
HOOK_DEFINE_TRAMPOLINE(DeathHook) {
    static void Callback(PlayerHitPointData* self) {
        auto& st = smoap::ap::ApState::instance();
        // Cache for the inbound apply path. Updated every fire so we always
        // hold a live pointer (PlayerHitPointData is rebuilt per stage).
        st.player_hp_cache.store(self, std::memory_order_relaxed);
        Orig(self);
        // Stamp AFTER Orig so the timestamp reflects "Mario is now dead".
        // Updated for organic AND synthetic deaths — the debounce window in
        // maybeApplyInboundKill keys off this.
        st.last_observed_death_ms.store(smoap::ap::ApState::nowMs(),
                                        std::memory_order_relaxed);
        // If we induced this death ourselves, don't echo it back out as a
        // fresh DeathLink. Bridge-side dedupe (own-slot bounce filter) is the
        // belt; this is the suspenders. Note: DeathHook::Orig invoked from
        // synthKillMario bypasses this Callback anyway — the guard exists for
        // hypothetical future hooks downstream of kill() on the same path.
        if (st.synthetic_death_this_frame) return;
        smoap::ap::reportDeath();  // debounced inside reportDeath
    }
};
}  // namespace

void installDeathHook() {
    SMOAP_LOG_INFO("installing DeathHook -> %s", smoap::sym::kPlayerHitPointDataKill);
    softInstallAtSymbol<DeathHook>(smoap::sym::kPlayerHitPointDataKill);
}

void synthKillMario(PlayerHitPointData* hp) {
    // Direct call to the trampoline's stored original. Bypasses our Callback,
    // so the only thing the game sees is a normal PlayerHitPointData::kill
    // invocation. Caller is responsible for setting synthetic_death_this_frame
    // (already done by maybeApplyInboundKill) and for non-null hp.
    DeathHook::Orig(hp);
}

}  // namespace smoap::hooks
