// Warp paintings always open — Tier 1 force+log spike.
//
// SMO's warp paintings transport Mario to a small isolated area in a *different*
// kingdom (a Power Moon or two + a return painting). In vanilla a source
// painting only becomes usable once its destination kingdom is unlocked (with
// three early-view exceptions: Metro, Luncheon, Mushroom). We want every warp
// painting usable from the start.
//
// The availability decision is a NAMED, data-driven predicate:
//   GameDataHolder::checkIsOpenWorldWarpHoleInScenario(s32 worldId,
//                                                       s32 scenarioNo) const
// (GameDataHolder.h:203). It is the "is the painting to `worldId` open right now?"
// check — returns false early in vanilla. This symbol is confirmed present
// out-of-line in retail main.nso's dynsym (scripts/check_nso_symbols.py), so the
// doc's "predicate-is-inlined" risk is largely retired: installAtSym resolves and
// won't abort boot, and the function was not fully inlined away.
//
// THE ONE REMAINING UNKNOWN this spike answers in-game: does the WorldWarpHole
// actor actually CALL this out-of-line copy (so our trampoline observes the
// decision), or is the call inlined at the actor's call site (out-of-line symbol
// exists but is dead — the log would never fire at a painting)? Plus the content
// question: when we force it true at a NORMALLY-LATE painting, does the
// destination sub-stage load and present its moon in a usable state pre-unlock?
//
// SPIKE BEHAVIOR (this file): trampoline the predicate, log every distinct
// (worldId, scenarioNo, origResult) once, and return true when
// kWarpPaintingsAlwaysOpen. No AP toggle, no logic change, no visited-bit change
// — those are Tier 1 step 2 / Tier 2 once the spike confirms the seam.
// See docs/v3-feasibility/future-feasibility-warp-paintings-always-open.md.

#include "hk/hook/Trampoline.h"

#include "../ap/ApState.hpp"
#include "../util/Log.hpp"

#include <atomic>
#include <cstddef>
#include <cstdint>

namespace smoap::hooks {

namespace {

// Spike master switch. Flip to false to restore vanilla availability while
// keeping the log. Tier 1 step 2 replaces this with the
// `warp_paintings_always_open` AP toggle (read from ApState). For the spike it
// is an unconditional force so the binary gating questions are answered with the
// fewest moving parts.
constexpr bool kWarpPaintingsAlwaysOpen = true;

// --- one-time-per-(worldId,scenarioNo,origResult) log dedup ---------------------
// The predicate is polled from UI / actor code (potentially every frame while a
// painting's prompt is on screen), so log each distinct observation exactly once
// to keep the field diagnostic readable. `this` is deliberately NOT part of the
// key — the interesting axes are the destination worldId, the scenario, and what
// vanilla would have decided.
struct SeenKey { int worldId; int scenarioNo; bool origResult; };
constexpr std::size_t kSeenCap = 128;
SeenKey s_seen[kSeenCap] = {};
std::size_t s_seenLen = 0;

bool seenAddIfNew(int worldId, int scenarioNo, bool origResult) {
    for (std::size_t i = 0; i < s_seenLen; ++i) {
        if (s_seen[i].worldId == worldId &&
            s_seen[i].scenarioNo == scenarioNo &&
            s_seen[i].origResult == origResult) {
            return false;  // already logged this exact observation
        }
    }
    if (s_seenLen < kSeenCap) {
        s_seen[s_seenLen++] = SeenKey{worldId, scenarioNo, origResult};
    }
    return true;
}

// GameDataHolder::checkIsOpenWorldWarpHoleInScenario(worldId, scenarioNo) const.
// Member function → `this` (const GameDataHolder*) is the first argument.
HkTrampoline<bool, const void*, int, int> checkIsOpenWarpHoleHook =
    hk::hook::trampoline(
        [](const void* self, int worldId, int scenarioNo) -> bool {
            const bool orig = checkIsOpenWarpHoleHook.orig(self, worldId, scenarioNo);
            const bool forced = kWarpPaintingsAlwaysOpen ? true : orig;

            if (seenAddIfNew(worldId, scenarioNo, orig)) {
                SMOAP_LOG_INFO(
                    "[warp-painting] checkIsOpenWorldWarpHoleInScenario "
                    "worldId=%d scenarioNo=%d origResult=%d -> return %d%s",
                    worldId, scenarioNo, static_cast<int>(orig),
                    static_cast<int>(forced),
                    (forced != orig) ? " (FORCED OPEN)" : "");
            }
            return forced;
        });

// ===========================================================================
// The UPSTREAM appearance gate — FOUND (probe 2, 2026-07-06): isUnlockedWorld.
//
// Probe 2 disproved the "-1 destination" theory: getWorldIdForWorldWarpHole DOES
// return the real dest (idx=12 -> dest=12 = Bowser's). Immediately after, the
// actor calls isUnlockedWorld(12) -> 0, and THAT is what blanks the painting and
// stops checkIsOpen(12) from ever being asked. A working painting shows the
// mirror pattern (idx=8 -> dest=9, isUnlockedWorld(9) -> 1).
//
// So the appearance gate is isUnlockedWorld(destWorldId). We CANNOT force it true
// globally — it drives the world map, kingdom-order gate, and Odyssey travel. But
// the log shows a tight, warp-specific pairing on one thread:
//   getWorldIdForWorldWarpHole(idx) -> dest=X   immediately followed by
//   isUnlockedWorld(X)
// and the world map uses a DIFFERENT getter (getWorldIdForWorldMap). So we ARM on
// the warp-hole dest in getWorldIdForWorldWarpHole and force isUnlockedWorld true
// ONLY for that just-armed world (single-shot, consumed on match). That confines
// the force to the warp-hole enumeration path. Combined with the checkIsOpen force
// above, a normally-late painting should light up and be enterable.
//
// Heuristic caveat: the arm lingers until the next getWorldIdForWorldWarpHole call
// or a matching isUnlockedWorld consumes it, so a stray isUnlockedWorld(sameDest)
// in that tiny same-thread window could be forced once. Bounded + behind
// kWarpPaintingsAlwaysOpen; tighten with a frame/timestamp guard if it misbehaves.
// ===========================================================================

// Time-bounded ring of destinations recently returned by getWorldIdForWorldWarp
// Hole. A single-slot arm was too fragile: the actor loop calls
// getWorldIdForWorldWarpHole repeatedly and a *silent* repeat (dedup only hides
// the log, not the call) overwrote the slot before the matching isUnlockedWorld
// read it (proven 2026-07-06: idx=12->dest=12 armed, then isUnlockedWorld(12)
// saw a clobbered arm and did NOT force). The ring holds the last several dests
// each stamped with nowMs; isUnlockedWorld(w) forces only if w was returned by
// getWorldIdForWorldWarpHole within kArmWindowMs — tight enough that an unrelated
// world-map isUnlockedWorld(w) seconds later is not affected. Per-slot atomics
// keep cross-thread reads (isUnlockedWorld runs on multiple threads) untorn.
constexpr std::size_t kArmRingCap = 16;
constexpr std::int64_t kArmWindowMs = 150;
std::atomic<int> s_armDest[kArmRingCap];       // -1 = empty
std::atomic<std::int64_t> s_armMs[kArmRingCap];
std::atomic<std::size_t> s_armWrite{0};

void armWarpDest(int dest) {
    const std::size_t i =
        s_armWrite.fetch_add(1, std::memory_order_relaxed) % kArmRingCap;
    s_armMs[i].store(smoap::ap::ApState::nowMs(), std::memory_order_relaxed);
    s_armDest[i].store(dest, std::memory_order_relaxed);
}

// True if `worldId` was returned by getWorldIdForWorldWarpHole within the window.
bool warpDestArmedRecently(int worldId) {
    const std::int64_t now = smoap::ap::ApState::nowMs();
    for (std::size_t i = 0; i < kArmRingCap; ++i) {
        if (s_armDest[i].load(std::memory_order_relaxed) != worldId) continue;
        const std::int64_t ms = s_armMs[i].load(std::memory_order_relaxed);
        if (now - ms <= kArmWindowMs) return true;
    }
    return false;
}

// --- getWorldIdForWorldWarpHole dedup (by idx + returned dest) ---
struct HoleSeen { int idx; int dest; };
constexpr std::size_t kHoleSeenCap = 64;
HoleSeen s_holeSeen[kHoleSeenCap] = {};
std::size_t s_holeSeenLen = 0;
bool holeSeenAddIfNew(int idx, int dest) {
    for (std::size_t i = 0; i < s_holeSeenLen; ++i)
        if (s_holeSeen[i].idx == idx && s_holeSeen[i].dest == dest) return false;
    if (s_holeSeenLen < kHoleSeenCap) s_holeSeen[s_holeSeenLen++] = HoleSeen{idx, dest};
    return true;
}

// GameProgressData::getWorldIdForWorldWarpHole(idx) const — `this` is first arg.
// Arms s_armedWarpDest so the very next isUnlockedWorld(dest) call (the actor's
// per-hole availability check) can be forced true in the warp-hole path only.
HkTrampoline<int, const void*, int> getWorldIdForWarpHoleHook =
    hk::hook::trampoline([](const void* self, int idx) -> int {
        const int dest = getWorldIdForWarpHoleHook.orig(self, idx);
        if (kWarpPaintingsAlwaysOpen && dest >= 0) {
            armWarpDest(dest);
        }
        if (holeSeenAddIfNew(idx, dest)) {
            SMOAP_LOG_INFO(
                "[warp-painting] getWorldIdForWorldWarpHole idx=%d -> dest=%d%s",
                idx, dest, (dest < 0) ? "  (UNREVEALED / blanks painting?)" : "");
        }
        return dest;
    });

// GameDataFunction::isUnlockedWorld(GameDataHolderAccessor, worldId) — accessor
// (single pointer) in x0, worldId in x1. Very hot; deduped by (worldId, result).
struct GameDataHolderAccessor { void* mData; };
struct UnlockSeen { int worldId; bool unlocked; };
constexpr std::size_t kUnlockSeenCap = 64;
UnlockSeen s_unlockSeen[kUnlockSeenCap] = {};
std::size_t s_unlockSeenLen = 0;
bool unlockSeenAddIfNew(int worldId, bool unlocked) {
    for (std::size_t i = 0; i < s_unlockSeenLen; ++i)
        if (s_unlockSeen[i].worldId == worldId &&
            s_unlockSeen[i].unlocked == unlocked) return false;
    if (s_unlockSeenLen < kUnlockSeenCap)
        s_unlockSeen[s_unlockSeenLen++] = UnlockSeen{worldId, unlocked};
    return true;
}

HkTrampoline<bool, GameDataHolderAccessor, int> isUnlockedWorldHook =
    hk::hook::trampoline([](GameDataHolderAccessor acc, int worldId) -> bool {
        const bool r = isUnlockedWorldHook.orig(acc, worldId);

        // Warp-hole-scoped force: only when this worldId was returned by
        // getWorldIdForWorldWarpHole within kArmWindowMs (i.e. we're inside the
        // actor's per-hole availability check). The time-bounded ring tolerates
        // interleaved silent getWorldIdForWorldWarpHole calls while still keeping
        // an unrelated later isUnlockedWorld(w) (world map, etc.) unaffected.
        if (kWarpPaintingsAlwaysOpen && !r && warpDestArmedRecently(worldId)) {
            static int s_forceLogged[64] = {};
            static std::size_t s_forceLoggedLen = 0;
            bool seen = false;
            for (std::size_t i = 0; i < s_forceLoggedLen; ++i)
                if (s_forceLogged[i] == worldId) { seen = true; break; }
            if (!seen) {
                if (s_forceLoggedLen < 64) s_forceLogged[s_forceLoggedLen++] = worldId;
                SMOAP_LOG_INFO(
                    "[warp-painting] isUnlockedWorld worldId=%d -> 0 FORCED->1 "
                    "(warp-hole path)", worldId);
            }
            return true;
        }

        if (unlockSeenAddIfNew(worldId, r)) {
            SMOAP_LOG_INFO("[warp-painting] isUnlockedWorld worldId=%d -> %d",
                           worldId, static_cast<int>(r));
        }
        return r;
    });

// GameDataFunction::isAlreadyGoWorld(GameDataHolderAccessor, worldId) — probe 3.
// LOG-ONLY, arm-scoped: forcing isUnlockedWorld did not un-blank the post-game
// Cascade->Bowser's painting, so the appearance gate is deeper. If the actor
// reads isAlreadyGoWorld(dest) during the warp-hole eval this line shows it (and
// its value) — the prime suspect for what keeps the painting blank until game
// clear. NOT forced: isAlreadyGoWorld drives scenario/cutscene/kingdom state
// game-wide, so we confirm before deciding force-vs-curate.
struct AlreadyGoSeen { int worldId; bool go; };
constexpr std::size_t kAlreadyGoSeenCap = 64;
AlreadyGoSeen s_alreadyGoSeen[kAlreadyGoSeenCap] = {};
std::size_t s_alreadyGoSeenLen = 0;
bool alreadyGoSeenAddIfNew(int worldId, bool go) {
    for (std::size_t i = 0; i < s_alreadyGoSeenLen; ++i)
        if (s_alreadyGoSeen[i].worldId == worldId &&
            s_alreadyGoSeen[i].go == go) return false;
    if (s_alreadyGoSeenLen < kAlreadyGoSeenCap)
        s_alreadyGoSeen[s_alreadyGoSeenLen++] = AlreadyGoSeen{worldId, go};
    return true;
}

HkTrampoline<bool, GameDataHolderAccessor, int> isAlreadyGoWorldHook =
    hk::hook::trampoline([](GameDataHolderAccessor acc, int worldId) -> bool {
        const bool r = isAlreadyGoWorldHook.orig(acc, worldId);
        if (warpDestArmedRecently(worldId) && alreadyGoSeenAddIfNew(worldId, r)) {
            SMOAP_LOG_INFO(
                "[warp-painting] isAlreadyGoWorld worldId=%d -> %d (warp-hole "
                "path — appearance-gate suspect)", worldId, static_cast<int>(r));
        }
        return r;
    });

}  // namespace

void installWorldWarpHoleGateHook() {
    SMOAP_LOG_INFO(
        "installing WorldWarpHoleGateHook -> GameDataHolder::"
        "checkIsOpenWorldWarpHoleInScenario (spike: log + force open=%d) + probe2 "
        "loggers (getWorldIdForWorldWarpHole, isUnlockedWorld)",
        static_cast<int>(kWarpPaintingsAlwaysOpen));
    checkIsOpenWarpHoleHook.installAtSym<
        "_ZNK14GameDataHolder34checkIsOpenWorldWarpHoleInScenarioEii">();
    getWorldIdForWarpHoleHook.installAtSym<
        "_ZNK16GameProgressData26getWorldIdForWorldWarpHoleEi">();
    isUnlockedWorldHook.installAtSym<
        "_ZN16GameDataFunction15isUnlockedWorldE22GameDataHolderAccessori">();
    isAlreadyGoWorldHook.installAtSym<
        "_ZN16GameDataFunction16isAlreadyGoWorldE22GameDataHolderAccessori">();
}

}  // namespace smoap::hooks
