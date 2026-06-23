// Costume doors always unlocked (while entrance shuffle is on).
//
// Each kingdom's costume / fitting-room door is locked in vanilla until Mario
// wears the matching outfit and an NPC drops the chained padlock. Under this
// project's entrance/shop shuffle the gating outfit can become awkward or
// circular to obtain, and the destination mapped BEHIND a shuffled costume door
// is then stranded by that outfit. So when entrance shuffle is active we force
// every costume door open.
//
// Mechanism (confirmed from romfs + the decompiled sibling DoorCity, 2026-06-23):
//   * The padlock is a runtime-spawned DoorWarpLock actor (no BYML placement).
//     Its archive carries a Push sensor (Type=MapObj, Radius=100) and no .kcl —
//     that Push sensor IS the "invisible barrier" you feel at a locked door.
//   * Every costume door gates its OPEN transition on an "OpenKeySwitch" ->
//     StageSwitch link. Per the al-library door pattern (DoorCity), a switch-
//     gated door initializes into / transitions to its Open state and calls
//     al::invalidateCollisionParts when open — i.e. the switch governs the
//     whole open (lock removal AND the warp), not just the visual padlock.
//   * An all-stages romfs string scan found "OpenKeySwitch" in EXACTLY the 8
//     costume doors and nowhere else: 7 DoorWarpStageChange fitting rooms (Sand,
//     Wooded, Seaside, Snow, Luncheon, Bowser's, Mushroom) + the Lake DoorWarp
//     same-stage door (-> the "I Feel Underdressed" moon area). So matching on
//     the link NAME alone is both sufficient and complete — nothing else opens.
//
// Hook: trampoline al::isOnStageSwitch(user, linkName) and return true for
// linkName=="OpenKeySwitch" while entrance shuffle is active. The vanilla door
// then initializes straight into Open on stage load. One hook covers all 8.
//
// Gating: ApState::entrance_shuffle_active (set when a non-empty entrance_map is
// applied, cleared otherwise) — costume doors unlock only when entrance shuffle
// is enabled for the seed; vanilla locked behavior when it's off. Switch-mod
// only, no wire/apworld change.
//
// Residual risk (logged, not fatal): if the door is PURELY event-driven and
// never queries isOnStageSwitch (even at listen-registration), the force is
// inert. The [costume-door] log line firing at a door proves the seam; its
// ABSENCE is the tell to pivot to listenStageSwitchOnStart / the door actor.

#include "hk/hook/Trampoline.h"

#include "../ap/ApState.hpp"
#include "../util/Log.hpp"

#include <cstring>

namespace smoap::hooks {

namespace {

constexpr const char* kOpenKeySwitchLink = "OpenKeySwitch";

// Small dedupe of recently force-opened door pointers so a door that polls
// isOnStageSwitch every frame logs once rather than spamming the 200-line ring.
// Pointers are stable per stage load; on a stage reload the slot is naturally
// overwritten as new doors cycle through. Frame-thread only (the al query runs
// on the game thread), so no synchronization needed.
constexpr std::size_t kLoggedCap = 16;
const void* s_logged[kLoggedCap] = {};
std::size_t s_loggedHead = 0;

bool alreadyLogged(const void* user) {
    for (std::size_t i = 0; i < kLoggedCap; ++i)
        if (s_logged[i] == user) return true;
    s_logged[s_loggedHead] = user;
    s_loggedHead = (s_loggedHead + 1) % kLoggedCap;
    return false;
}

// al::isOnStageSwitch(const al::IUseStageSwitch* user, const char* linkName).
// user is opaque here (only used as a log/dedupe key), so a void* suffices.
HkTrampoline<bool, const void*, const char*> isOnStageSwitchHook =
    hk::hook::trampoline([](const void* user, const char* linkName) -> bool {
        const bool orig = isOnStageSwitchHook.orig(user, linkName);
        if (linkName && std::strcmp(linkName, kOpenKeySwitchLink) == 0) {
            const bool active = smoap::ap::ApState::instance()
                .entrance_shuffle_active.load(std::memory_order_relaxed);
            if (active && !orig) {
                if (!alreadyLogged(user))
                    SMOAP_LOG_INFO("[costume-door] force-open OpenKeySwitch "
                                   "(door=%p, was locked)", user);
                return true;
            }
        }
        return orig;
    });

}  // namespace

void installCostumeDoorHook() {
    SMOAP_LOG_INFO("installing CostumeDoorHook -> al::isOnStageSwitch "
                   "(force OpenKeySwitch open while entrance shuffle active)");
    // Raw symbol literal (the installAtSym convention used by every other hook;
    // the matching entry lives in syms/game/SmoApSymbols.sym).
    isOnStageSwitchHook.installAtSym<
        "_ZN2al15isOnStageSwitchEPKNS_15IUseStageSwitchEPKc">();
}

}  // namespace smoap::hooks
