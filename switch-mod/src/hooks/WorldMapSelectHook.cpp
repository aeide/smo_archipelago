// M7 Path A — fork-cinematic kingdom-order gate.
//
// See production switch-mod's WorldMapSelectHook.cpp for the full design
// narrative. This port keeps logic identical and swaps HOOK_DEFINE_TRAMPOLINE
// → HkTrampoline + installAtSym.

#include "hk/hook/Trampoline.h"
#include "hk/ro/RoUtil.h"
#include "hk/types.h"

#include <cstdint>
#include <cstring>

#include "../ap/ApState.hpp"
#include "../game/KingdomOrderGate.hpp"
#include "../game/KingdomUnlock.hpp"
#include "../util/Log.hpp"
#include "HookSymbols.hpp"

namespace smoap::hooks {

namespace {

struct GameDataHolderWriter { void* mData; };

constexpr bool kGateEnabled = true;

// First-visit forward-warp cutscene suppression (2026-06-29). Cap is forced into
// its return layout (CapReturnScenarioHook) so a free-travel player can fly out
// of Cap from sphere 0. But flying the Odyssey to a NEVER-VISITED kingdom is a
// "forward world warp" (isForwardWorldWarpDemo true), so the engine plays the
// first-visit warp cutscene. For Cascade that cutscene ALSO grounds the Odyssey
// (the vanilla "needs the first Multi-Moon to fly again" tutorial state), which
// strands the player: they can't fly back to Cap until they collect enough
// Cascade moons — a potential unwinnable seed if a required Cap moon is gated
// behind Cascade content.
//
// Fix: GameDataFunction::noPlayDemoWorldWarp(writer) clears the stored
// mIsPlayDemoWorldWarp flag. changeNextStageWithDemoWorldWarp SETS that flag
// inside tryChangeNextStageWithDemoWorldWarp (proven by the log timeline: the
// flag flips to 1 AFTER our GameDataFile::changeNextStage commit returns — i.e.
// the wrapper sets it around the commit), and the arrival reads it to decide
// whether to play the cutscene. So we clear it POST-orig here, in the wrapper
// that sets it, before the destination stage init reads it → plain parked flight
// landing, Odyssey boardable, player can leave. Resolved soft-degrade; a miss
// just leaves the cutscene in place (no crash).
//
// Scoped to Cascade (the only forward kingdom whose first-visit demo grounds the
// ship). Other kingdoms' intro cutscenes are harmless and left intact.
using NoPlayDemoWorldWarpFn = void (*)(GameDataHolderWriter);
NoPlayDemoWorldWarpFn s_noPlayDemoWorldWarp = nullptr;

inline constexpr const char* kCascadeHomeStage = "WaterfallWorldHomeStage";

int substituteSlotWorldId(const char* origin, int index, int orig_world_id) {
    if (!kGateEnabled) return orig_world_id;
    const char* kingdom = smoap::game::kingdomShortFromWorldId(orig_world_id);
    if (!kingdom) return orig_world_id;
    auto decision = smoap::game::evaluateOrderGateForKingdom(kingdom);
    if (!decision.blocked) return orig_world_id;
    const int prereq_id = smoap::game::worldIdFromKingdomShort(
        decision.required_kingdom_short);
    if (prereq_id < 0) {
        SMOAP_LOG_WARN("[wmap.%s] gate misconfigured: prereq='%s' not in "
                       "kKingdoms; passing original worldId=%d through",
                       origin,
                       decision.required_kingdom_short ?
                           decision.required_kingdom_short : "(null)",
                       orig_world_id);
        return orig_world_id;
    }
    static const char* s_last_origin   = nullptr;
    static int         s_last_index    = -1;
    static int         s_last_orig_id  = -1;
    const bool changed =
        s_last_origin  != origin  ||
        s_last_index   != index   ||
        s_last_orig_id != orig_world_id;
    if (changed) {
        SMOAP_LOG_INFO("[wmap.%s] SUB slot=%d origId=%d (%s) -> prereqId=%d (%s)",
                       origin, index, orig_world_id, kingdom,
                       prereq_id, decision.required_kingdom_short);
        s_last_origin = origin;
        s_last_index = index;
        s_last_orig_id = orig_world_id;
    }
    return prereq_id;
}

void markVisitedFromStage(const char* origin, const char* stage) {
    if (!stage) return;
    const char* kingdom = smoap::game::kingdomShortFromHomeStage(stage);
    if (!kingdom) return;
    const std::uint8_t bit = smoap::game::kingdomBitFor(kingdom);
    if (bit >= 17) return;
    auto& st = smoap::ap::ApState::instance();
    const bool was_visited = st.isKingdomBitVisited(static_cast<int>(bit));
    if (!was_visited) {
        SMOAP_LOG_INFO("[wmap.%s] visited[%s] = true (stage='%s')",
                       origin, kingdom, stage);
    }
    st.markKingdomBitVisited(static_cast<int>(bit));
}

HkTrampoline<int, const void*, int> calcNextLockedLayoutHook =
    hk::hook::trampoline([](const void* p, int index) -> int {
        return substituteSlotWorldId("menu.NextLocked.Layout", index,
                                     calcNextLockedLayoutHook.orig(p, index));
    });

HkTrampoline<int, const void*, int> calcNextLockedSceneHook =
    hk::hook::trampoline([](const void* p, int index) -> int {
        return substituteSlotWorldId("menu.NextLocked.Scene", index,
                                     calcNextLockedSceneHook.orig(p, index));
    });

HkTrampoline<bool, GameDataHolderWriter, const char*> tryChangeDemoWarpHook =
    hk::hook::trampoline([](GameDataHolderWriter writer, const char* stage) -> bool {
        const char* final_stage = stage;
        const char* kingdom = stage ? smoap::game::kingdomShortFromHomeStage(stage)
                                     : nullptr;
        if (kGateEnabled && kingdom) {
            const auto decision = smoap::game::evaluateOrderGateForKingdom(kingdom);
            if (decision.blocked && decision.required_stage) {
                SMOAP_LOG_WARN("[wmap.tryChange.Demo] BACKSTOP substituting "
                               "stage='%s' -> '%s'",
                               stage, decision.required_stage);
                final_stage = decision.required_stage;
            }
        }
        // Approach B (the free-detour "both before leaving" gate) is NOT here.
        // The detour-exit warp reads as Metro at this seam, and redirecting the
        // demo-warp target did NOT stop the downstream Bowser->Cloud reroute
        // (playtest 2026-06-25, iteration 2 leaked to Cloud). The gate now lives
        // at the universal GameDataFile::changeNextStage commit, where Cloud
        // provably resolves — see processDetourExitGate in EntranceShuffleHook.cpp.
        markVisitedFromStage("tryChange.Demo", final_stage);
        const bool r = tryChangeDemoWarpHook.orig(writer, final_stage);
        // Suppress the first-visit cutscene for Cascade so its Odyssey isn't
        // grounded (see header). orig has now set mIsPlayDemoWorldWarp; clear it
        // before the arrival reads it. No-op for every other destination.
        if (s_noPlayDemoWorldWarp && final_stage &&
            std::strcmp(final_stage, kCascadeHomeStage) == 0) {
            s_noPlayDemoWorldWarp(writer);
            static int s_log = 0;
            if (s_log < 20) {
                ++s_log;
                SMOAP_LOG_INFO("[cascade-arrival] noPlayDemoWorldWarp -> suppress "
                               "first-visit cutscene, land Odyssey parked + "
                               "boardable (dest=%s) #%d",
                               final_stage, s_log);
            }
        }
        return r;
    });

HkTrampoline<bool, GameDataHolderWriter, const char*> tryChangeWarpHoleHook =
    hk::hook::trampoline([](GameDataHolderWriter writer, const char* stage) -> bool {
        markVisitedFromStage("tryChange.Hole", stage);
        return tryChangeWarpHoleHook.orig(writer, stage);
    });

}  // namespace

void installWorldMapSelectHook() {
    SMOAP_LOG_INFO("installing M7 Path A Layer 1 (calcNextLocked, 2 overloads)");
    calcNextLockedLayoutHook.installAtSym<
        "_ZN16GameDataFunction32calcNextLockedWorldIdForWorldMapEPKN2al11LayoutActorEi">();
    calcNextLockedSceneHook.installAtSym<
        "_ZN16GameDataFunction32calcNextLockedWorldIdForWorldMapEPKN2al5SceneEi">();

    SMOAP_LOG_INFO("installing M7 Path A Layer 2 (DemoWorldWarp backstop + visited)");
    tryChangeDemoWarpHook.installAtSym<
        "_ZN16GameDataFunction35tryChangeNextStageWithDemoWorldWarpE20GameDataHolderWriterPKc">();

    SMOAP_LOG_INFO("installing M7 Path A WorldWarpHole (visited-only, no gate)");
    tryChangeWarpHoleHook.installAtSym<
        "_ZN16GameDataFunction35tryChangeNextStageWithWorldWarpHoleE20GameDataHolderWriterPKc">();

    // Cascade first-visit cutscene suppressor (see header). Soft-degrade: a miss
    // leaves the cutscene in place rather than aborting the module.
    const ptr addr = hk::ro::lookupSymbol(
        smoap::sym::kGameDataFunctionNoPlayDemoWorldWarp);
    if (addr == 0) {
        s_noPlayDemoWorldWarp = nullptr;
        SMOAP_LOG_WARN("[cascade-arrival] noPlayDemoWorldWarp lookup FAILED — "
                       "Cascade first-visit cutscene NOT suppressed (Odyssey may "
                       "still ground on first arrival)");
    } else {
        s_noPlayDemoWorldWarp = reinterpret_cast<NoPlayDemoWorldWarpFn>(addr);
        SMOAP_LOG_INFO("[cascade-arrival] noPlayDemoWorldWarp @ 0x%lx — first-visit "
                       "cutscene suppression armed", static_cast<unsigned long>(addr));
    }
}

}  // namespace smoap::hooks
