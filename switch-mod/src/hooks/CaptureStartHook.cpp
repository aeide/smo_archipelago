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
#include <cstring>
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
//
// Considered alternative: PlayerHackKeeper::endHack (SMO's canonical
// voluntary-release path used for Y-press). Prototyped 2026-05-17; T-Rex
// CRASHED ~530ms after endHack returned cleanly when its exeHackStart state
// machine null-deref'd on the cleared keeper. forceKillHack does additional
// synchronous teardown that prevents the actor from continuing its intro
// state machine after release, so the actor can't race. Visual cost of
// forceKillHack: captured enemy despawns on release.
using ForceKillHackFn = void (*)(PlayerHackKeeper*);
ForceKillHackFn s_forceKillHack = nullptr;

// Default delay between BLOCKED detection and forceKillHack invocation.
//
// Firing immediately is a no-op (the hack state machine hasn't fully entered
// — see synthetic_uncapture_this_frame comment in ApState.hpp). 1s released
// Mario cleanly for fast captures like Goomba, but broke the camera and
// despawned the actor for T-Rex (the slowest dive-in cinematic — playtest
// 2026-05-16). 4s clears every cinematic we've measured at this default;
// per-cap overrides below for confirmed slow-intro outliers.
constexpr int kDeferredKillMs = 4000;

// Per-cap delay overrides. The default 4s causes a camera/visual issue for
// T-Rex on release (the dinosaur's intro state machine is still active when
// forceKillHack despawns it mid-frame). 6s gives T-Rex enough time for its
// intro to wrap up naturally before we kill it. Tested: see playtest log
// 2026-05-17 21-43-41 for the 4s crash data.
//
// Add new entries here as future playtests identify slow-intro bosses.
struct CapKillDelayOverride {
    const char* hack_name;
    int delay_ms;
};
constexpr CapKillDelayOverride kCapKillDelayOverrides[] = {
    {"TRex", 6000},
};

int deferredKillMsForCap(const char* hack_name) {
    if (!hack_name || !*hack_name) return kDeferredKillMs;
    const std::size_t n = std::strlen(hack_name);
    for (const auto& e : kCapKillDelayOverrides) {
        const std::size_t en = std::strlen(e.hack_name);
        if (en == n && std::memcmp(hack_name, e.hack_name, n) == 0) {
            return e.delay_ms;
        }
    }
    return kDeferredKillMs;
}

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
                // Phase 1.5a: stash the cap name we're queuing for so
                // tickPendingUncapture can verify the keeper still holds the
                // same capture at deadline (vs. SMO having released it for
                // any reason — Y-press, env death, scene change, etc.).
                std::size_t i = 0;
                for (; i < sizeof(st.pending_kill_hack_name) - 1
                        && name[i]; ++i) {
                    st.pending_kill_hack_name[i] = name[i];
                }
                st.pending_kill_hack_name[i] = '\0';
                const int delay_ms = deferredKillMsForCap(name);
                st.pending_kill_keeper.store(self, std::memory_order_release);
                st.pending_kill_at_ms.store(
                    smoap::ap::ApState::nowMs() + delay_ms,
                    std::memory_order_release);
                SMOAP_LOG_INFO(
                    "CaptureStartHook: BLOCKED hack=%s — forceKillHack queued in %dms%s",
                    name, delay_ms,
                    (delay_ms != kDeferredKillMs) ? " (per-cap override)" : "");
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
//
// Phase 1.5b adds a re-verify guard: SMO may have already released the
// capture during the wait window (player Y-press, env death, scene change,
// save load) — re-read getCurrentHackName(keeper) and skip if it no longer
// matches the cap we queued for. See pending_kill_hack_name in ApState.hpp.
void tickPendingUncapture() {
    if (!s_forceKillHack) return;
    auto& st = smoap::ap::ApState::instance();
    void* keeper = st.pending_kill_keeper.load(std::memory_order_acquire);
    if (!keeper) return;
    if (smoap::ap::ApState::nowMs() <
            st.pending_kill_at_ms.load(std::memory_order_acquire)) {
        return;
    }
    // Phase 1.5b: PRIMARY GUARD against stale-keeper kills. The keeper
    // outlives any individual capture (it's owned by the Player actor), so
    // the read is safe; only its bound-cap pointer changes per release.
    // If a different cap is now active and IS also blocked, CaptureStartHook
    // already re-queued a fresh deferred kill for it — letting this stale
    // entry fire would double-kill.
    bool name_ok = false;
    if (s_getCurrentHackName) {
        const char* cur = s_getCurrentHackName(
            static_cast<const PlayerHackKeeper*>(keeper));
        if (cur && *cur) {
            bool match = true;
            for (std::size_t i = 0; i < sizeof(st.pending_kill_hack_name); ++i) {
                const char want = st.pending_kill_hack_name[i];
                const char got = cur[i];
                if (want != got) { match = false; break; }
                if (want == '\0') break;
            }
            name_ok = match;
            if (!match) {
                SMOAP_LOG_INFO(
                    "M7 pending kill SKIPPED keeper=%p — cap changed: "
                    "queued='%s' now='%s'",
                    keeper, st.pending_kill_hack_name, cur);
            }
        } else {
            SMOAP_LOG_INFO(
                "M7 pending kill SKIPPED keeper=%p — no active cap "
                "(queued='%s'; player or env released first)",
                keeper, st.pending_kill_hack_name);
        }
    } else {
        // Without getCurrentHackName we can't verify, so fall through to
        // historical behavior (fire blind). Should never happen in practice
        // since the hook install logs the lookup result.
        name_ok = true;
        SMOAP_LOG_WARN(
            "M7 pending kill firing blind (getCurrentHackName unresolved)");
    }
    // Clear FIRST so we don't double-fire if the kill itself takes more than
    // one frame to settle and tickPendingUncapture runs again before the
    // keeper state machine catches up. Also clears the pending-name slot so
    // the next BLOCKED queue starts from a clean state.
    st.pending_kill_keeper.store(nullptr, std::memory_order_release);
    st.pending_kill_hack_name[0] = '\0';
    if (!name_ok) return;
    st.synthetic_uncapture_this_frame = true;
    SMOAP_LOG_INFO("M7 deferred forceKillHack firing on keeper=%p", keeper);
    s_forceKillHack(static_cast<PlayerHackKeeper*>(keeper));
    smoap::game::playSE_NG();
}

}  // namespace smoap::hooks
