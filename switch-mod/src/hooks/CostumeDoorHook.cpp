// Costume doors always unlocked (while entrance shuffle is on).
//
// Each kingdom's costume / fitting-room door is locked in vanilla until Mario
// wears the matching outfit. Under this project's entrance/shop shuffle the
// gating outfit can become awkward or circular to obtain, and the destination
// mapped BEHIND a shuffled costume door is then stranded. So when entrance
// shuffle is active we force every costume door open.
//
// === Mechanism (confirmed from main.nso symbol dump, 2026-06-24) ==============
//   * There are TWO distinct door classes (an earlier note WRONGLY claimed the
//     unit name "DoorWarpStageChange" had no class symbol and that all 8 doors
//     were `DoorWarp` — the main.nso dump disproves this):
//       - `DoorWarpStageChange` — the 7 LOADING-ZONE fitting-room doors (Sand,
//         Wooded, Seaside, Snow, Luncheon, Bowser's, Mushroom). Its own full
//         method set exists: `_ZN19DoorWarpStageChange18initAfterPlacementEv`,
//         `4init`, `7exeLock`, `6unlock`, plus a `createActorFunction` template
//         instantiation, so it is a real instantiated actor.
//       - `DoorWarp` — the Lake `LakeWorldTownZone` SAME-STAGE door.
//     BOTH multiply-inherit `al::LiveActor` (primary base @0) and
//     `al::IUseStageSwitch` — confirmed by `_ZTC8DoorWarp24_N2al15IUseStageSwitchE`
//     AND `_ZTC19DoorWarpStageChange24_N2al15IUseStageSwitchE`: the IUseStageSwitch
//     subobject sits at byte offset 24 in BOTH (LiveActor's 4th interface base:
//     IUseNerve, IUseEffectKeeper, IUseAudioKeeper, then IUseStageSwitch — 3 x
//     8-byte vtable-ptr bases = offset 24). So we hook BOTH classes'
//     initAfterPlacement into one queue; the offset + switch link are identical.
//     (Hooking only `DoorWarp::initAfterPlacement` logged NOTHING in Sand — its
//     fitting-room door is a `DoorWarpStageChange`, the other class.)
//   * The padlock is a separate runtime-spawned `DoorWarpLock` actor whose `Push`
//     sensor (Type=MapObj, Radius=100) is the "invisible barrier". Both the door
//     and the lock gate on an `OpenKeySwitch` -> StageSwitch link. An all-stages
//     romfs scan found "OpenKeySwitch" in EXACTLY the 8 costume doors and nowhere
//     else, so matching on that link NAME is both sufficient and complete.
//
// === Hooking history (and the REAL root cause of the "hangs", 2026-06-24) ======
//   ROUND 1 (force `al::isOnStageSwitch` true) — INERT: doors don't poll it.
//   ROUND 2 (hook `al::listenStageSwitchOn`/`listenStageSwitchOnOff`) and
//   ROUND 3a (hook `DoorWarp::exeLock`) both HUNG the boot. These were long
//   blamed on "trampolining a tiny shim overruns the prologue steal into the
//   adjacent function" — that theory is WRONG. `hk::hook::TrampolineHook` steals
//   exactly ONE instruction and relocates it; it never overruns into the next
//   function (read sys/hakkun/src/hk/hook/Trampoline.cpp). The actual cause was
//   TRAMPOLINE POOL EXHAUSTION: the build sat at exactly TRAMPOLINE_POOL_SIZE
//   (0x40 = 64) installed HkTrampolines, so adding a SECOND door trampoline
//   (initAfterPlacement + exeLock, or the two-class initAfterPlacement pair) made
//   the 65th — `sTrampolinePool.allocate()` returned nullptr and the resulting
//   HK_ABORT_UNLESS hung inside hk::diag's IPC logger under Ryujinx instead of
//   printing "TrampolinePool full". Symptom: an unexplained boot hang right after
//   GameSystem::init with the door hook never even firing. Fixed by bumping
//   TRAMPOLINE_POOL_SIZE to 0x80 in config/config.cmake. With headroom, hooking
//   BOTH door classes' initAfterPlacement is fine (and ROUND 2's listen* approach
//   would likely have worked too — but this split design is cleaner, so keep it).
//
// ROUND 3b (this file) — hook each door class's `initAfterPlacement` (a real,
//   sizable per-spawn method). It may run BEFORE the door's StageSwitch link is
//   resolvable, and we must NOT call the al switch helpers from a fragile context.
//   So we split the work:
//     1. `initAfterPlacement` (the trampoline) merely RECORDS the door pointer
//        into a small pending registry — no al calls here.
//     2. `tickCostumeDoors()` runs from the ALREADY-SAFE `drawMain` frame pump
//        (same place as tickArrivalPoll / tickWorldTravelPeach). Once entrance
//        shuffle is active it calls `al::tryOnStageSwitch(door,"OpenKeySwitch")`
//        on each pending door and drops it from the list. Turning the switch on
//        is the one master lever: the door unlocks through its own machinery and
//        the shared switch despawns the DoorWarpLock + Push barrier too. Calling
//        the al helpers is fine — it was only HOOKING `listen*` that hung — and
//        the frame pump gives the switch link the frames it needs to be valid.
//        Scoped by `al::isValidStageSwitch(door,"OpenKeySwitch")` so only the 8
//        costume doors are touched.
//
// Gating: ApState::entrance_shuffle_active — costume doors unlock only when
// entrance shuffle is enabled for the seed; vanilla locked behavior when off.
// Switch-mod only, no wire/apworld change.
//
// Diagnosis lines: "[costume-door] seam initAfterPlacement fired (door=…,
// shuffle=…)" proves the class assumption + records the door; "[costume-door]
// force-on OpenKeySwitch (door=…, valid=…, ok=…)" proves the per-frame switch
// toggle. If valid=0 the door doesn't carry the link (wrong class / not a costume
// door). If ok=1 but the door still won't warp, additionally call the resolved
// `DoorWarp::unlock()` (symbol `_ZN8DoorWarp6unlockEv`) on the door.

#include "hk/hook/Trampoline.h"
#include "hk/ro/RoUtil.h"

#include "../ap/ApState.hpp"
#include "../util/Log.hpp"

#include <cstddef>

namespace smoap::hooks {

namespace {

constexpr const char* kOpenKeySwitchLink = "OpenKeySwitch";

// IUseStageSwitch subobject offset within an al::LiveActor (see header comment:
// confirmed by _ZTC8DoorWarp24_… and the LiveActor base order). DoorWarp* aliases
// its LiveActor base at offset 0, so the IUseStageSwitch* the al switch helpers
// expect is (char*)door + 24.
constexpr std::ptrdiff_t kUseStageSwitchOffset = 24;

void* doorToUseStageSwitch(void* door) {
    if (!door) return nullptr;
    return reinterpret_cast<char*>(door) + kUseStageSwitchOffset;
}

// al switch helpers, resolved lazily via hk::ro::lookupSymbol (raw literals, NOT
// sail installAtSym) so a missing dynsym entry soft-fails instead of aborting init.
// We only CALL these from the frame pump — hooking them is what hung the load.
using IsValidStageSwitchFn = bool (*)(const void* /*user*/, const char* /*link*/);
using TryOnStageSwitchFn = bool (*)(void* /*user*/, const char* /*link*/);

IsValidStageSwitchFn resolveIsValid() {
    static IsValidStageSwitchFn fn = nullptr;
    static bool tried = false;
    if (!tried) {
        tried = true;
        const auto addr = hk::ro::lookupSymbol(
            "_ZN2al18isValidStageSwitchEPKNS_15IUseStageSwitchEPKc");
        if (addr) {
            fn = reinterpret_cast<IsValidStageSwitchFn>(addr);
            SMOAP_LOG_INFO("[costume-door] isValidStageSwitch resolved @ 0x%lx",
                           static_cast<unsigned long>(addr));
        } else {
            SMOAP_LOG_WARN("[costume-door] isValidStageSwitch not in dynsym");
        }
    }
    return fn;
}

TryOnStageSwitchFn resolveTryOn() {
    static TryOnStageSwitchFn fn = nullptr;
    static bool tried = false;
    if (!tried) {
        tried = true;
        const auto addr = hk::ro::lookupSymbol(
            "_ZN2al16tryOnStageSwitchEPNS_15IUseStageSwitchEPKc");
        if (addr) {
            fn = reinterpret_cast<TryOnStageSwitchFn>(addr);
            SMOAP_LOG_INFO("[costume-door] tryOnStageSwitch resolved @ 0x%lx",
                           static_cast<unsigned long>(addr));
        } else {
            SMOAP_LOG_WARN("[costume-door] tryOnStageSwitch not in dynsym — "
                           "cannot force costume doors open");
        }
    }
    return fn;
}

// --- pending door registry ------------------------------------------------------
// initAfterPlacement (game thread) appends; tickCostumeDoors (frame thread, also
// the game thread) drains. SMO actor methods and drawMain run on the same game
// thread, so no synchronization is needed. A door pointer lives here only for the
// frame(s) between its init and the next tick — by which point it is fully alive,
// so there is no dangling-pointer window in practice (and we never store a door we
// don't promptly process). Cap is generous: only ~1-2 costume doors exist per
// loaded stage, but other DoorWarps (non-costume) also land here and are filtered
// out by isValidStageSwitch when ticked.
constexpr std::size_t kPendingCap = 64;
void* s_pending[kPendingCap] = {};
std::size_t s_pendingLen = 0;

bool pendingContains(void* door) {
    for (std::size_t i = 0; i < s_pendingLen; ++i)
        if (s_pending[i] == door) return true;
    return false;
}
void pendingAdd(void* door) {
    if (pendingContains(door)) return;
    if (s_pendingLen < kPendingCap) s_pending[s_pendingLen++] = door;
}
void pendingRemoveAt(std::size_t i) {
    // unordered remove: swap with last
    s_pending[i] = s_pending[s_pendingLen - 1];
    --s_pendingLen;
}

// --- one-time-per-door seam log -------------------------------------------------
// Low-volume field diagnostic (<=8 costume doors per stage, deduped by pointer):
// records that a door of class `cls` spawned and the entrance_shuffle_active state
// at spawn. Pairs with the "force-on OpenKeySwitch" line from the frame pump.
constexpr std::size_t kSeamCap = 48;
const void* s_seam[kSeamCap] = {};
std::size_t s_seamLen = 0;
void seamLogOnce(const char* cls, const void* door) {
    for (std::size_t i = 0; i < s_seamLen; ++i)
        if (s_seam[i] == door) return;
    if (s_seamLen < kSeamCap) s_seam[s_seamLen++] = door;
    SMOAP_LOG_INFO("[costume-door] seam %s::initAfterPlacement fired (door=%p, "
                   "shuffle=%d)",
                   cls, door,
                   static_cast<int>(smoap::ap::ApState::instance()
                                        .entrance_shuffle_active.load(
                                            std::memory_order_relaxed)));
}

// initAfterPlacement() for the two door classes — `this` is the actor (==
// LiveActor* @0). A real per-spawn method, SAFE to trampoline (the game boots
// clean with it). We do the minimum here: log once + queue the door for the frame
// pump to process. No al switch calls in this context. BOTH classes feed the same
// queue (same +24 IUseStageSwitch offset, same OpenKeySwitch link).
HkTrampoline<void, void*> doorWarpStageChangeInitHook =
    hk::hook::trampoline([](void* self) -> void {
        doorWarpStageChangeInitHook.orig(self);
        if (!self) return;
        seamLogOnce("DoorWarpStageChange", self);
        pendingAdd(self);
    });

HkTrampoline<void, void*> doorWarpInitAfterPlacementHook =
    hk::hook::trampoline([](void* self) -> void {
        doorWarpInitAfterPlacementHook.orig(self);
        if (!self) return;
        seamLogOnce("DoorWarp", self);
        pendingAdd(self);
    });

}  // namespace

// Frame-pump driver (called from drawMain — a proven-safe context). Once entrance
// shuffle is active, force the OpenKeySwitch on for every pending costume door,
// then drop it from the queue. No-op (and doesn't consume the queue) until shuffle
// is active, so a door queued before the entrance map applied still gets handled.
void tickCostumeDoors() {
    if (s_pendingLen == 0) return;
    if (!smoap::ap::ApState::instance()
             .entrance_shuffle_active.load(std::memory_order_relaxed))
        return;  // shuffle not active yet — leave queued, retry next frame

    const auto tryOn = resolveTryOn();
    if (!tryOn) {
        // Can't force anything — drop the queue so we don't spin forever.
        s_pendingLen = 0;
        return;
    }
    const auto isValid = resolveIsValid();

    // Walk the queue; process + remove each door exactly once.
    for (std::size_t i = 0; i < s_pendingLen;) {
        void* door = s_pending[i];
        void* sw = doorToUseStageSwitch(door);
        const bool valid = isValid ? isValid(sw, kOpenKeySwitchLink) : true;
        if (valid) {
            const bool ok = tryOn(sw, kOpenKeySwitchLink);
            SMOAP_LOG_INFO("[costume-door] force-on OpenKeySwitch (door=%p, "
                           "valid=1, ok=%d)",
                           door, static_cast<int>(ok));
        }
        // Whether it was a costume door (valid) or not (filtered), we're done with
        // it — remove from the queue. A non-costume DoorWarp simply gets skipped.
        pendingRemoveAt(i);
        // pendingRemoveAt swapped the last element into slot i, so don't ++i.
    }
}

void installCostumeDoorHook() {
    SMOAP_LOG_INFO("installing CostumeDoorHook -> DoorWarpStageChange + DoorWarp "
                   "::initAfterPlacement (queue) + drawMain tickCostumeDoors "
                   "(force OpenKeySwitch open while entrance shuffle active)");
    doorWarpStageChangeInitHook
        .installAtSym<"_ZN19DoorWarpStageChange18initAfterPlacementEv">();
    doorWarpInitAfterPlacementHook
        .installAtSym<"_ZN8DoorWarp18initAfterPlacementEv">();
}

}  // namespace smoap::hooks
