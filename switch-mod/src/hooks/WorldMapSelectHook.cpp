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
#include "../game/OdysseyRescue.hpp"
#include "../util/Log.hpp"
#include "HookSymbols.hpp"

namespace smoap::hooks {

// Defined in CascadeBroodeRespawnHook.cpp — true once Cascade's Madame Broode
// Multi-Moon is collected (Broode beaten). Used to scope the Cascade first-visit
// world-warp-demo suppression below to PRE-Broode only: post-Broode this is a
// normal revisit and clearing mIsPlayDemoWorldWarp desynced the arrival load
// (crash on long-haul flights into Cascade, 2026-07-05). See the suppression site.
bool cascadeMultiMoonCollected();

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

        const bool cascadeBound = final_stage &&
            std::strcmp(final_stage, kCascadeHomeStage) == 0;

        // DIAGNOSTIC (2026-07-05): dump the world-warp-demo flag set + the
        // isAlreadyGoWorld bitmap for a Cascade-bound flight BEFORE orig sets
        // mIsPlayDemoWorldWarp, so a WORKING (from Cap) vs CRASHING (from a
        // long-haul kingdom) fly-in can be compared row-for-row. Read-only.
        if (cascadeBound)
            smoap::game::logWorldWarpDemoDiagNow("demoWarp-pre->Cascade");

        const bool r = tryChangeDemoWarpHook.orig(writer, final_stage);

        // Cascade first-visit cutscene suppression — SCOPED TO PRE-BROODE.
        //
        // The suppression exists ONLY to stop the first-visit warp cutscene from
        // GROUNDING the Odyssey (a pre-Broode tutorial state) and stranding a
        // free-travel player who flew in from Cap. But
        // tryChangeNextStageWithDemoWorldWarp is the STANDARD world-map flight
        // commit (it fires on every globe flight, not just first visits — see
        // HookSymbols.hpp:759), so clearing mIsPlayDemoWorldWarp unconditionally
        // also cleared it on POST-Broode revisits. Devon, 2026-07-05: "I crash
        // every time I revisit Cascade UNLESS I visit from Cap." Adjacent
        // Cap->Cascade doesn't set the demo state, so clearing it there was a
        // harmless no-op; a long-haul fly-in (Sand->Cascade, etc.) DOES set it,
        // and clearing it mid-flight desynced the arrival load -> crash during
        // load. Once Broode's Multi-Moon is collected there is no grounding
        // tutorial left to suppress, so leave the vanilla revisit path untouched.
        if (cascadeBound) {
            const bool firstVisit = !cascadeMultiMoonCollected();
            if (s_noPlayDemoWorldWarp && firstVisit) {
                s_noPlayDemoWorldWarp(writer);
                static int s_log = 0;
                if (s_log < 20) {
                    ++s_log;
                    SMOAP_LOG_INFO("[cascade-arrival] noPlayDemoWorldWarp -> "
                                   "suppress first-visit cutscene, land Odyssey "
                                   "parked + boardable (dest=%s, PRE-Broode) #%d",
                                   final_stage, s_log);
                }
            } else {
                static int s_log2 = 0;
                if (s_log2 < 20) {
                    ++s_log2;
                    SMOAP_LOG_INFO("[cascade-arrival] KEEP vanilla demo-warp "
                                   "(dest=%s broodeCollected=%d suppressorReady=%d) "
                                   "— post-Broode revisit path, do NOT clear "
                                   "mIsPlayDemoWorldWarp #%d",
                                   final_stage,
                                   cascadeMultiMoonCollected() ? 1 : 0,
                                   s_noPlayDemoWorldWarp ? 1 : 0, s_log2);
                }
            }
            smoap::game::logWorldWarpDemoDiagNow("demoWarp-post->Cascade");
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
