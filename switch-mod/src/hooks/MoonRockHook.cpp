// Moon Rocks active after WORLD PEACE (per kingdom) + the Cap-peace-from-
// start experiment.
//
// === Why the gate is "kingdom story complete", not "always" ================
// Vanilla rock-open flow (OdysseyDecomp MapObj/MoonRock.cpp): hitting the
// rock plays the open demo, then `tryChangeNextStage(mChangeStageInfo)`
// RELOADS THE STAGE INTO THE KINGDOM'S MOON-ROCK SCENARIO. On the reloaded
// stage the rock re-inits, sees isEnableOpenMoonRock false + scenario ==
// its placement ScenarioNo, and takes the wreckage branch that commits
// `openMoonRock()` (hints + map demo) and leaves the rock broken.
//
// Mid-story that scenario jump is destructive: it skips the kingdom's
// remaining bosses/quests (observed: Sand's inverted pyramid skyborne, no
// Hariet fight — story Multi-Moon checks stranded). Post-peace the jump is
// safe: everything still collectable in the kingdom survives into the
// moon-rock scenario (it's the vanilla post-game state).
//
// Hook logic on GameDataFunction::isEnableOpenMoonRock(actor):
//   1. orig true (real post-game)            -> true (vanilla)
//   2. kingdom main story NOT complete       -> false (vanilla dormant rock)
//   3. moon-rock scenario already active     -> false — CRITICAL: the
//      reloaded rock must take the vanilla wreckage/commit branch; forcing
//      true here re-arms the rock forever and openMoonRock never commits
//      (the bug in the first version of this hook).
//   4. otherwise                             -> true (rock openable early)
//
// === Cap peace from start (EXPERIMENT — kCapPeaceFromStart) ================
// Cap's prologue is its main story, so under the gate above Cap's rock is
// openable on first revisit. Devon wants more: Cap already AT peace during
// the prologue so its checks are collectable before Cascade. We force
// Cap's main scenario to its moon-rock scenario (peace state + the rock
// self-opens via the wreckage branch on load) from two directions:
//   a. ScenarioFlagHook upgrade: when the game writes a smaller main-
//      scenario for Cap, substitute the moon-rock scenario (wins ordering
//      races at new-save init) — see maybeUpgradeCapScenario().
//   b. A throttled frame tick (mirrors OdysseyRescue's sweep) for saves
//      where the game never re-writes Cap's scenario.
// KNOWN RISK (accepted): the prologue is scripted in Cap scenario 1.
// Forcing peace may break the intro on a fresh save (no Cappy meet, no
// path to Cascade). If it does, flip kCapPeaceFromStart to false and
// rebuild — everything else in this file stays valid.

#include "hk/hook/Trampoline.h"
#include "hk/ro/RoUtil.h"
#include "hk/types.h"

#include "../ap/ApState.hpp"
#include "../util/Log.hpp"
#include "HookSymbols.hpp"

#include <cstdint>
#include <type_traits>

// Real layout header: needed ONLY for the inline GameDataHolder::
// getWorldList() (the accessor compiles to a plain field read at the
// layout-correct offset; the method is not exported so a symbol lookup
// can't provide it).
#include "System/GameDataHolder.h"

namespace al {
class LiveActor;
}

namespace smoap::hooks {

namespace {

// Cap-peace-from-start experiment: OFF (2026-06-11 verdict). Forcing Cap's
// stored main scenario is recomputed away from quest state at every stage
// load (observed: capScen pinned at 1 across reloads while capMain held 4;
// the game re-writes main=1 on transitions and only the write-upgrade kept
// it at 4). Reaching "fresh save starts at Cap peace with the Odyssey"
// needs new-save state surgery (initializeData post-hook: mIsPlayDemoOpening,
// meetCap, setActivateHome, unlockWorld, quest state) — scoped as a possible
// future milestone, not this flag. The code below is kept as a documented
// stub; everything is compiled out / early-returned while this is false.
inline constexpr bool kCapPeaceFromStart = false;
// SMO world id 0 = Cap (kKingdoms[0], identity-mapped in kWorldIdToBit).
inline constexpr int kCapWorldId = 0;

struct GameDataHolderAccessorMirror {
    void* mData;
};

// Same mirror as ShineAppearanceHook: GameDataHolder + 0x20 -> GameDataFile*.
inline constexpr std::size_t kGameDataHolder_mGameDataFileOffset = 0x20;

using GetCurrentWorldIdNoDevelopFn = int (*)(GameDataHolderAccessorMirror);
using IsClearWorldMainScenarioFn   = bool (*)(const void* gdf, int world_id);
using GetScenarioNoFn              = int (*)(const void* gdf, int world_id);
using GetMainScenarioNoFn          = int (*)(const void* gdf, int world_id);
using GetMoonRockScenarioNoFn      = int (*)(const void* world_list, int world_id);

IsClearWorldMainScenarioFn s_isClearWorldMainScenario = nullptr;
GetScenarioNoFn            s_getScenarioNo            = nullptr;
GetMainScenarioNoFn        s_getMainScenarioNo        = nullptr;
GetMoonRockScenarioNoFn    s_getMoonRockScenarioNo    = nullptr;

struct GameCtx {
    GameDataHolder* holder = nullptr;
    void* gdf = nullptr;
    const WorldList* world_list = nullptr;
    int world_id = -1;
};

bool resolveGameCtx(GameCtx& out) {
    auto& s = smoap::ap::ApState::instance();
    void* holder = s.game_data_holder_cache.load(std::memory_order_relaxed);
    if (!holder || !s.get_current_world_id_fn) return false;
    out.holder = static_cast<GameDataHolder*>(holder);
    out.gdf = *reinterpret_cast<void* const*>(
        reinterpret_cast<const std::uint8_t*>(holder)
            + kGameDataHolder_mGameDataFileOffset);
    if (!out.gdf) return false;
    out.world_list = out.holder->getWorldList();
    auto fn = reinterpret_cast<GetCurrentWorldIdNoDevelopFn>(
        s.get_current_world_id_fn);
    out.world_id = fn(GameDataHolderAccessorMirror{holder});
    return out.world_id >= 0;
}

int moonRockScenarioFor(const GameCtx& ctx, int world_id) {
    if (!ctx.world_list || s_getMoonRockScenarioNo == nullptr) return -1;
    return s_getMoonRockScenarioNo(ctx.world_list, world_id);
}

HkTrampoline<bool, const al::LiveActor*> moonRockEnableHook =
    hk::hook::trampoline([](const al::LiveActor* actor) -> bool {
        const bool orig = moonRockEnableHook.orig(actor);
        if (orig) return true;  // real post-game: fully vanilla

        GameCtx ctx;
        if (!resolveGameCtx(ctx) || s_isClearWorldMainScenario == nullptr) {
            // Missing plumbing: fail closed to vanilla (dormant rock) rather
            // than risk the scenario jump in an unknown state.
            return false;
        }

        // Gate 1: kingdom story must be complete (world peace).
        if (!s_isClearWorldMainScenario(ctx.gdf, ctx.world_id)) return false;

        // Gate 2: never force while the moon-rock scenario is active — the
        // reloaded rock must run the vanilla wreckage/openMoonRock branch.
        const int mr_scenario = moonRockScenarioFor(ctx, ctx.world_id);
        if (mr_scenario > 0 && s_getScenarioNo != nullptr &&
            s_getScenarioNo(ctx.gdf, ctx.world_id) == mr_scenario) {
            return false;
        }

        static int s_logged = 0;
        if (s_logged < 8) {
            SMOAP_LOG_INFO("[moon-rock] enable forced (world=%d peace done, "
                           "scenario=%d mr=%d) #%d",
                           ctx.world_id,
                           s_getScenarioNo ? s_getScenarioNo(ctx.gdf, ctx.world_id) : -1,
                           mr_scenario, s_logged + 1);
            ++s_logged;
        }
        return true;
    });

}  // namespace

// Called by ScenarioFlagHook BEFORE forwarding to orig: when the game writes
// a main-scenario value for Cap that's below Cap's moon-rock scenario,
// substitute the moon-rock scenario so Cap loads at peace with its rock
// pre-broken. Returns the (possibly upgraded) scenario_no.
int maybeUpgradeCapScenario(int scenario_no) {
    if constexpr (!kCapPeaceFromStart) return scenario_no;

    GameCtx ctx;
    if (!resolveGameCtx(ctx)) return scenario_no;
    if (ctx.world_id != kCapWorldId) return scenario_no;

    const int mr = moonRockScenarioFor(ctx, kCapWorldId);
    if (mr <= 0 || scenario_no >= mr) return scenario_no;

    SMOAP_LOG_INFO("[cap-peace] setMainScenarioNo(Cap): %d -> %d (upgrade)",
                   scenario_no, mr);
    return mr;
}

// Throttled frame sweep (called from the drawMain pump alongside the
// OdysseyRescue sweep): covers saves where the game never re-writes Cap's
// main scenario after load. Applies on the NEXT Cap stage load.
void tickCapPeaceExperiment() {
    if constexpr (!kCapPeaceFromStart) return;

    static int s_tick = 0;
    if (++s_tick < 60) return;  // ~1s @ 60fps
    s_tick = 0;

    GameCtx ctx;
    if (!resolveGameCtx(ctx)) return;

    // Diagnostic heartbeat (~every 5s, first 24 lines): all the values the
    // experiment depends on, logged regardless of whether we act — so a
    // silent no-op is distinguishable from a dead code path. Visible in
    // Ryujinx's guest log (kernel debug sink) even if bridge log shipping
    // is filtered.
    {
        static int s_beat = 0;
        static int s_diagLogged = 0;
        if (++s_beat >= 5 && s_diagLogged < 24) {
            s_beat = 0;
            ++s_diagLogged;
            const int cap_mr = moonRockScenarioFor(ctx, kCapWorldId);
            SMOAP_LOG_INFO("[cap-peace] diag#%d world=%d capMain=%d capScen=%d "
                           "capMr=%d capClear=%d curClear=%d fns(main=%d scen=%d mr=%d)",
                           s_diagLogged, ctx.world_id,
                           s_getMainScenarioNo ? s_getMainScenarioNo(ctx.gdf, kCapWorldId) : -99,
                           s_getScenarioNo ? s_getScenarioNo(ctx.gdf, kCapWorldId) : -99,
                           cap_mr,
                           // The peace gate's actual verdict, for Cap and for
                           // the current kingdom: distinguishes "gate ignores
                           // our forced main scenario" from nerve/init-order
                           // explanations when the rock stays inert.
                           s_isClearWorldMainScenario
                               ? s_isClearWorldMainScenario(ctx.gdf, kCapWorldId) : -99,
                           s_isClearWorldMainScenario
                               ? s_isClearWorldMainScenario(ctx.gdf, ctx.world_id) : -99,
                           s_getMainScenarioNo != nullptr,
                           s_getScenarioNo != nullptr,
                           s_getMoonRockScenarioNo != nullptr);
        }
    }

    if (ctx.world_id != kCapWorldId) return;

    const int mr = moonRockScenarioFor(ctx, kCapWorldId);
    if (mr <= 0 || s_getMainScenarioNo == nullptr) return;
    if (s_getMainScenarioNo(ctx.gdf, kCapWorldId) >= mr) return;

    // Route through the game's own setter (already trampolined by
    // ScenarioFlagHook, which reports the change to the bridge — desired).
    const ptr addr = hk::ro::lookupSymbol(smoap::sym::kGameDataFileSetMainScenarioNo);
    if (addr == 0) return;
    auto setMainScenarioNo = reinterpret_cast<void (*)(void*, int)>(addr);
    SMOAP_LOG_INFO("[cap-peace] sweep: forcing Cap main scenario -> %d", mr);
    setMainScenarioNo(ctx.gdf, mr);
}

void installMoonRockHook() {
    auto resolve = [](const char* mangled, auto& out, const char* label) {
        const ptr addr = hk::ro::lookupSymbol(mangled);
        if (addr == 0) {
            SMOAP_LOG_ERROR("[moon-rock] %s lookup FAILED — hook degrades to "
                            "vanilla behavior", label);
            out = nullptr;
            return;
        }
        out = reinterpret_cast<std::remove_reference_t<decltype(out)>>(addr);
    };
    resolve(smoap::sym::kGameDataFileIsClearWorldMainScenario,
            s_isClearWorldMainScenario, "isClearWorldMainScenario");
    resolve(smoap::sym::kGameDataFileGetScenarioNo,
            s_getScenarioNo, "getScenarioNo");
    resolve(smoap::sym::kGameDataFileGetMainScenarioNo,
            s_getMainScenarioNo, "getMainScenarioNo");
    resolve(smoap::sym::kWorldListGetMoonRockScenarioNo,
            s_getMoonRockScenarioNo, "getMoonRockScenarioNo");

    SMOAP_LOG_INFO("installing MoonRockHook -> "
                   "GameDataFunction::isEnableOpenMoonRock (peace-gated)");
    moonRockEnableHook.installAtSym<
        "_ZN16GameDataFunction20isEnableOpenMoonRockEPKN2al9LiveActorE">();
}

}  // namespace smoap::hooks
