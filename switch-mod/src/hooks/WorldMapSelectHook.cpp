// M7 Path A — fork-cinematic kingdom-order gate.
//
// See production switch-mod's WorldMapSelectHook.cpp for the full design
// narrative. This port keeps logic identical and swaps HOOK_DEFINE_TRAMPOLINE
// → HkTrampoline + installAtSym.

#include "hk/hook/Trampoline.h"
#include "hk/ro/RoUtil.h"
#include "hk/types.h"

#include <cstdint>
#include <cstdio>
#include <cstring>

#include "../ap/ApState.hpp"
#include "../game/KingdomOrderGate.hpp"
#include "../game/KingdomUnlock.hpp"
#include "../game/OdysseyRescue.hpp"
#include "../ui/CappyMessenger.hpp"
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
struct GameDataHolderAccessor { void* mData; };

constexpr bool kGateEnabled = true;

// Resolve the kingdom Mario is CURRENTLY standing in (the departing kingdom
// at a flight commit) — same plumbing as UnlockShineNumHook's
// resolveCurrentKingdomBit. 0xff when the holder/symbol isn't ready.
using GetCurrentWorldIdNoDevelopFn = int (*)(GameDataHolderAccessor);
std::uint8_t resolveDepartingKingdomBit(int* out_world_id) {
    if (out_world_id) *out_world_id = -1;
    auto& s = smoap::ap::ApState::instance();
    void* holder = s.game_data_holder_cache.load(std::memory_order_relaxed);
    if (!holder || !s.get_current_world_id_fn) return 0xff;
    auto fn = reinterpret_cast<GetCurrentWorldIdNoDevelopFn>(
        s.get_current_world_id_fn);
    const int world_id = fn(GameDataHolderAccessor{holder});
    if (out_world_id) *out_world_id = world_id;
    return smoap::game::kingdomBitForWorldId(world_id);
}

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
        // P5 §1.5-B1: EntranceShuffleHook re-routes remapped cross-world
        // OVERWORLD commits through this wrapper (the proven native world-swap
        // path — flights into Metro are consistently clean). That synthetic
        // call must not be re-gated: the order-gate BACKSTOP and the
        // chain-return bounce below would redirect the very chain arrival
        // that raised them. One-shot flag, set right before the call.
        const bool synthetic_chain_warp =
            smoap::ap::ApState::instance().chain_demo_warp_pending.exchange(
                false, std::memory_order_relaxed);
        if (synthetic_chain_warp) {
            SMOAP_LOG_INFO("[wmap.tryChange.Demo] synthetic chain warp to '%s' "
                           "(backstop + bounce skipped)",
                           stage ? stage : "(null)");
        }
        const char* final_stage = stage;
        const char* kingdom = stage ? smoap::game::kingdomShortFromHomeStage(stage)
                                     : nullptr;
        if (kGateEnabled && kingdom && !synthetic_chain_warp) {
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

        // P4/P5 decoupled — chain-return VISITED-ONLY bounce (Devon rulings
        // 2026-07-07/08). From a chain-reached kingdom, flights may go to
        // already-visited kingdoms ONLY — substitute any un-visited pick with
        // the chain ORIGIN (falling back to Cap, always reachable) —
        // substitution is the proven primitive at this seam (same mechanism as
        // the order-gate BACKSTOP above; the decomp shows
        // tryChangeNextStageWithDemoWorldWarp commits unconditionally, so a
        // refusal-by-return-false has no vanilla path).
        //
        // P5 finding-13 fix: the condition is the DEPARTING kingdom being
        // chain-reached (session bit OR the save-derived chain-only marker,
        // alreadyGo && !unlocked — persists across save/load and across gate
        // PAYMENT), no longer the chain_allowance_bit — which payment clears
        // by design, and which let the post-payment story `firstNext` flight
        // commit to an out-of-logic kingdom unbounced. Paying never
        // legitimizes story-forward travel (Devon ruling); the kingdom stops
        // bouncing only when it is later reached legitimately (story unlock
        // clears the save-derived marker... and the session bit dies with the
        // session).
        //
        // "Visited" = the session bit (flight commits + chain arrivals) OR the
        // save's isAlreadyGoWorld (official visits predating this session;
        // chain arrivals force it too, so post-normalization both agree).
        if (kGateEnabled && final_stage && !synthetic_chain_warp) {
            auto& st = smoap::ap::ApState::instance();
            int depart_world = -1;
            const std::uint8_t depart_bit =
                resolveDepartingKingdomBit(&depart_world);
            // Combined chain-only marker (2026-07-09 fix): a legitimately
            // UNLOCKED departing kingdom never bounces, whatever the session
            // chain bit says — see OdysseyRescue::isKingdomChainReachedOnly.
            const bool depart_chain_only =
                depart_bit < 17 &&
                smoap::game::isKingdomChainReachedOnly(depart_bit, depart_world);
            // Devon 2026-07-15: "if I have enough moons for that kingdom I can
            // leave it and progress the story, no matter what scenario." Once the
            // departing kingdom's rolled leave-gate is MET (enough lifetime
            // effective moons collected), forward flights are no longer bounced —
            // the moon leave-gate becomes the sole gate on progression. This
            // reverses P5 finding-13 ("paying never legitimizes story-forward
            // travel") on purpose: the visited-only bounce now applies ONLY while
            // the leave-gate is still unmet (so an under-fueled chain arrival is
            // still funneled back to visited kingdoms to go collect / receive
            // more, rather than stranded forward out of logic).
            const bool leave_gate_met = smoap::game::leaveGateSatisfied(depart_bit);
            const char* tgt_kingdom =
                smoap::game::kingdomShortFromHomeStage(final_stage);
            if (depart_chain_only && !leave_gate_met && tgt_kingdom) {
                const std::uint8_t tgt_bit = smoap::game::kingdomBitFor(tgt_kingdom);
                const int tgt_world = smoap::game::worldIdFromKingdomShort(tgt_kingdom);
                const bool allowed =
                    tgt_bit == depart_bit ||  // flying "to" the kingdom we're in
                    (tgt_bit < 17 && st.isKingdomBitVisited(tgt_bit)) ||
                    smoap::game::isWorldAlreadyGo(tgt_world);
                if (!allowed) {
                    const std::uint8_t origin_bit =
                        st.chain_origin_bit[depart_bit].load(std::memory_order_relaxed);
                    const char* origin_kingdom =
                        origin_bit < 17 ? smoap::game::kingdomForBit(origin_bit)
                                        : nullptr;
                    const char* bounce_stage = origin_kingdom
                        ? smoap::game::homeStageForKingdomShort(origin_kingdom)
                        : nullptr;
                    if (!bounce_stage) {
                        // Session origin unknown (e.g. after save/quit/reload —
                        // chain_origin_bit is session-only): Cap is always safe.
                        origin_kingdom = "Cap";
                        bounce_stage   = "CapWorldHomeStage";
                    }
                    SMOAP_LOG_WARN("[chain-return] BOUNCE un-visited pick "
                                   "stage='%s' (%s) -> '%s' (%s) [depart "
                                   "bit=%u origin bit=%u]",
                                   final_stage, tgt_kingdom, bounce_stage,
                                   origin_kingdom, depart_bit, origin_bit);
                    char bubble[64];
                    std::snprintf(bubble, sizeof(bubble),
                                  "Can't chart a course there yet! Back to %s!",
                                  origin_kingdom);
                    smoap::ui::CappyMessenger::instance().enqueueSystem(bubble);
                    final_stage = bounce_stage;
                }
            } else if (depart_chain_only && leave_gate_met && tgt_kingdom) {
                // Bounce lifted by the leave-gate: enough moons collected in the
                // departing (chain-reached) kingdom, so forward progression is
                // allowed (Devon 2026-07-15). Rate-limited on change.
                static std::uint8_t s_last_depart = 0xff;
                if (s_last_depart != depart_bit) {
                    s_last_depart = depart_bit;
                    SMOAP_LOG_INFO("[chain-return] leave-gate MET for %s(bit=%u) "
                                   "-> allow forward flight to '%s' (no bounce)",
                                   smoap::game::kingdomForBit(depart_bit),
                                   depart_bit, final_stage);
                }
            }
        }

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
