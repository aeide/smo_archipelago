// See OdysseyRescue.hpp for design context.

#include "OdysseyRescue.hpp"

#include <cstring>

#include <hk/ro/RoUtil.h>

#include "../ap/ApState.hpp"
#include "../hooks/HookSymbols.hpp"
#include "../util/Log.hpp"

namespace smoap::game {

namespace {

// Match the GameDataHolderAccessor/Writer layout used by other hooks in this
// codebase (see ShineNumGetHook.cpp, AddHackDictionaryHook.cpp). Both are a
// single void* wrapper; the Itanium ABI passes them by value as a single
// pointer-sized argument in x0 on aarch64.
struct GameDataHolderAccessor { void* mData; };
struct GameDataHolderWriter   { void* mData; };

using IsCrashHomeFn         = bool        (*)(GameDataHolderAccessor);
using RepairHomeFn          = void        (*)(GameDataHolderWriter);
using UnlockWorldFn         = void        (*)(GameDataHolderWriter, int);
using GetWorldIndexFn       = int         (*)();
using GetCurrentStageNameFn = const char* (*)(GameDataHolderAccessor);

struct ResolvedFns {
    IsCrashHomeFn         isCrashHome         = nullptr;
    RepairHomeFn          repairHome          = nullptr;
    UnlockWorldFn         unlockWorld         = nullptr;
    GetWorldIndexFn       getWorldIndexClash  = nullptr;
    GetCurrentStageNameFn getCurrentStageName = nullptr;
};

ResolvedFns g_fns;
bool        g_ready = false;

template <typename Fn>
bool resolveOne(Fn& slot, const char* mangled, const char* tag) {
    const ptr addr = hk::ro::lookupSymbol(mangled);
    if (addr == 0) {
        SMOAP_LOG_ERROR("OdysseyRescue: %s lookup FAILED", tag);
        slot = nullptr;
        return false;
    }
    slot = reinterpret_cast<Fn>(addr);
    SMOAP_LOG_INFO("OdysseyRescue: %s @ 0x%lx", tag,
                   static_cast<unsigned long>(addr));
    return true;
}

}  // namespace

void installOdysseyRescueSymbols() {
    bool ok = true;
    ok &= resolveOne(g_fns.isCrashHome,
        smoap::sym::kGameDataFunctionIsCrashHome, "isCrashHome");
    ok &= resolveOne(g_fns.repairHome,
        smoap::sym::kGameDataFunctionRepairHome, "repairHome");
    ok &= resolveOne(g_fns.unlockWorld,
        smoap::sym::kGameDataFunctionUnlockWorld, "unlockWorld");
    ok &= resolveOne(g_fns.getWorldIndexClash,
        smoap::sym::kGameDataFunctionGetWorldIndexClash, "getWorldIndexClash");
    ok &= resolveOne(g_fns.getCurrentStageName,
        smoap::sym::kGameDataFunctionGetCurrentStageName,
        "getCurrentStageName");
    g_ready = ok;
    SMOAP_LOG_INFO("OdysseyRescue: symbol resolution %s",
                   ok ? "COMPLETE" : "PARTIAL (sweep disabled)");
}

void runOdysseySoftlockSweep() {
    if (!g_ready) return;
    void* gdh = smoap::ap::ApState::instance().game_data_holder_cache.load(
        std::memory_order_relaxed);
    if (!gdh) return;
    GameDataHolderAccessor acc{gdh};
    GameDataHolderWriter   wr {gdh};

    // Heartbeat log throttle — Lost transitions are rare; log once every
    // 600 sweep calls (~10s when caller throttles to 1 sweep/s).
    static int s_lost_log = 0;

    // Wrecked Odyssey state in Lost Kingdom — detect and force-repair so
    // the player can backtrack to Wooded. No defensive else branch:
    // vanilla SMO does not crash the home outside ClashWorldHomeStage, so
    // a crashHome predicate outside Lost would be a vanilla bug we don't
    // currently model. The original defensive branch from when we also
    // patched Ruined has been removed along with the Ruined patching.
    if (g_fns.isCrashHome(acc)) {
        const char* stage = g_fns.getCurrentStageName(acc);
        if (stage && std::strcmp(stage, "ClashWorldHomeStage") == 0) {
            if ((s_lost_log++ % 600) == 0) {
                SMOAP_LOG_INFO(
                    "OdysseyRescue: Lost crashHome -> repair + unlock");
            }
            g_fns.repairHome(wr);
            g_fns.unlockWorld(wr, g_fns.getWorldIndexClash());
        }
    }
}

}  // namespace smoap::game
