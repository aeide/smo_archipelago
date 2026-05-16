// Hook on PlayerHackKeeper::startHack(al::HitSensor*, al::HitSensor*, al::LiveActor*).
//
// After Orig, the hack actor is bound and `self->getCurrentHackName()`
// returns the canonical hack name (e.g. "Goomba", "Kuribo", "Frog"). We
// forward the raw name to the bridge, which resolves it against
// capture_map.json into the apworld-canonical cap name.
//
// We resolve PlayerHackKeeper::getCurrentHackName via nn::ro::LookupSymbol
// at install time (storing the fn pointer) so we never depend on the
// link-time presence of SMO's internal symbols. M7 flips this hook into
// REPLACE-mode for cap gating.

#include "lib.hpp"
#include "lib/nx/nx.h"
#include "nn/ro.h"
#include "../ap/ApFrameBridge.hpp"
#include "../ap/ApState.hpp"
#include "../game/CaptureGate.hpp"
#include "../util/Log.hpp"
#include "HookSymbols.hpp"
#include "SoftInstall.hpp"

class PlayerHackKeeper;
namespace al { class HitSensor; class LiveActor; }

namespace smoap::hooks {

namespace {

// `const char* PlayerHackKeeper::getCurrentHackName() const`
// Mangled: _ZNK16PlayerHackKeeper18getCurrentHackNameEv
constexpr const char* kGetCurrentHackNameSym =
    "_ZNK16PlayerHackKeeper18getCurrentHackNameEv";

using GetCurrentHackNameFn = const char* (*)(const PlayerHackKeeper*);
GetCurrentHackNameFn s_getCurrentHackName = nullptr;

// `void PlayerHackKeeper::forceKillHack()` — M7 deny path.
// (cancelHack was tried first; logged BLOCKED + ran clean but did not actually
//  release Mario when called from inside the startHack callback. See
//  HookSymbols.hpp comment for forceKillHack rationale.)
using ForceKillHackFn = void (*)(PlayerHackKeeper*);
ForceKillHackFn s_forceKillHack = nullptr;

// Delay between BLOCKED detection and forceKillHack invocation.
//
// Firing immediately is a no-op (the hack state machine hasn't fully entered
// — see synthetic_uncapture_this_frame comment in ApState.hpp). 1s released
// Mario cleanly for fast captures like Goomba, but broke the camera and
// despawned the actor for T-Rex (the slowest dive-in cinematic — playtest
// 2026-05-16). 4s clears every cinematic we've measured; globally tuned for
// simplicity, promote to a per-hack-name override if a single laggy capture
// pushes us further.
constexpr int kDeferredKillMs = 4000;

HOOK_DEFINE_TRAMPOLINE(CaptureStartHook) {
    static void Callback(PlayerHackKeeper* self,
                         al::HitSensor* a, al::HitSensor* b, al::LiveActor* target) {
        Orig(self, a, b, target);
        if (!s_getCurrentHackName || !self) return;
        const char* name = s_getCurrentHackName(self);
        if (!name || !*name) return;

        SMOAP_LOG_INFO("CaptureStartHook: hack_name=%s", name);
        // Report unconditionally — the AP location check fires whether or not
        // the player owns the capture item yet. First touch sends the check,
        // AP replies with the item, second touch succeeds.
        smoap::ap::reportCaptureChecked(name);

        // M7: deny captures the player hasn't unlocked via AP. The actual
        // forceKillHack call is deferred to tickPendingUncapture() running
        // from drawMain — both because firing it inline doesn't release
        // Mario (state machine isn't fully entered yet) and because a brief
        // "captured the enemy and then got yanked out" beat is funnier.
        if (smoap::game::captureBlocked(name)) {
            if (s_forceKillHack) {
                auto& st = smoap::ap::ApState::instance();
                st.pending_kill_keeper.store(self, std::memory_order_release);
                st.pending_kill_at_ms.store(
                    smoap::ap::ApState::nowMs() + kDeferredKillMs,
                    std::memory_order_release);
                SMOAP_LOG_INFO(
                    "CaptureStartHook: BLOCKED hack=%s — forceKillHack queued in %dms",
                    name, kDeferredKillMs);
            } else {
                SMOAP_LOG_ERROR(
                    "CaptureStartHook: hack=%s blocked but forceKillHack unresolved — "
                    "capture goes through ungated", name);
            }
        }
    }
};
}  // namespace

void installCaptureStartHook() {
    SMOAP_LOG_INFO("installing CaptureStartHook -> %s", smoap::sym::kPlayerHackKeeperStartHack);
    softInstallAtSymbol<CaptureStartHook>(smoap::sym::kPlayerHackKeeperStartHack);

    // Resolve getCurrentHackName once. If lookup fails we log it; the hook
    // still installs (Orig runs as normal) and we just won't report captures.
    uintptr_t addr = 0;
    const Result rc = nn::ro::LookupSymbol(&addr, kGetCurrentHackNameSym);
    if (R_FAILED(rc)) {
        SMOAP_LOG_ERROR("getCurrentHackName lookup FAILED rc=0x%x", rc);
    } else {
        s_getCurrentHackName = reinterpret_cast<GetCurrentHackNameFn>(addr);
        SMOAP_LOG_INFO("getCurrentHackName resolved @ 0x%lx", addr);
    }

    // M7: resolve forceKillHack. If this fails we fall through to a logged
    // warning on the deny path (capture goes ungated) rather than crashing.
    uintptr_t fkh_addr = 0;
    const Result rc2 = nn::ro::LookupSymbol(&fkh_addr, smoap::sym::kPlayerHackKeeperForceKillHack);
    if (R_FAILED(rc2)) {
        SMOAP_LOG_ERROR("forceKillHack lookup FAILED rc=0x%x — M7 deny path disabled", rc2);
    } else {
        s_forceKillHack = reinterpret_cast<ForceKillHackFn>(fkh_addr);
        SMOAP_LOG_INFO("forceKillHack resolved @ 0x%lx", fkh_addr);
    }
}

// Called once per frame from DrawMainHook::Callback. Fires any pending
// deferred forceKillHack that's reached its target time.
void tickPendingUncapture() {
    if (!s_forceKillHack) return;
    auto& st = smoap::ap::ApState::instance();
    void* keeper = st.pending_kill_keeper.load(std::memory_order_acquire);
    if (!keeper) return;
    if (smoap::ap::ApState::nowMs() <
            st.pending_kill_at_ms.load(std::memory_order_acquire)) {
        return;
    }
    // Clear FIRST so we don't double-fire if the kill itself takes more than
    // one frame to settle and tickPendingUncapture runs again before the
    // keeper state machine catches up.
    st.pending_kill_keeper.store(nullptr, std::memory_order_release);
    st.synthetic_uncapture_this_frame = true;
    SMOAP_LOG_INFO("M7 deferred forceKillHack firing on keeper=%p", keeper);
    s_forceKillHack(static_cast<PlayerHackKeeper*>(keeper));
    smoap::game::playSE_NG();
}

}  // namespace smoap::hooks
