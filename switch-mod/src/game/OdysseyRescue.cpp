// See OdysseyRescue.hpp for design context.

#include "OdysseyRescue.hpp"

#include <cstring>

#include <hk/ro/RoUtil.h>

#include "../ap/ApState.hpp"
#include "../hooks/HookSymbols.hpp"
#include "../util/Log.hpp"
#include "KingdomUnlock.hpp"

namespace smoap::game {

namespace {

// Match the GameDataHolderAccessor/Writer layout used by other hooks in this
// codebase (see ShineNumGetHook.cpp, AddHackDictionaryHook.cpp). Both are a
// single void* wrapper; the Itanium ABI passes them by value as a single
// pointer-sized argument in x0 on aarch64.
struct GameDataHolderAccessor { void* mData; };
struct GameDataHolderWriter   { void* mData; };

using IsCrashHomeFn               = bool        (*)(GameDataHolderAccessor);
using RepairHomeFn                = void        (*)(GameDataHolderWriter);
using UnlockWorldFn               = void        (*)(GameDataHolderWriter, int);
using GetWorldIndexFn             = int         (*)();
using GetCurrentStageNameFn       = const char* (*)(GameDataHolderAccessor);
using HomeFlagFn                  = bool        (*)(GameDataHolderAccessor);
using GetHomeLevelFn              = int         (*)(GameDataHolderAccessor);
using HomeWriteFn                 = void        (*)(GameDataHolderWriter);

struct ResolvedFns {
    IsCrashHomeFn               isCrashHome               = nullptr;
    RepairHomeFn                repairHome                = nullptr;
    UnlockWorldFn               unlockWorld               = nullptr;
    GetWorldIndexFn             getWorldIndexClash        = nullptr;
    GetCurrentStageNameFn       getCurrentStageName       = nullptr;
    // Diagnostic getters (logger-only spike) — read-only, never mutate save.
    HomeFlagFn                  isExistHome               = nullptr;
    HomeFlagFn                  isActivateHome            = nullptr;
    HomeFlagFn                  isLaunchHome              = nullptr;
    GetHomeLevelFn              getHomeLevel              = nullptr;
    // Force-acquire mutators (forceAcquireOdyssey) — WRITE save state.
    HomeWriteFn                 activateHome              = nullptr;
    HomeWriteFn                 upHomeLevel               = nullptr;
    HomeWriteFn                 launchHome                = nullptr;
};

ResolvedFns g_fns;
bool        g_ready = false;        // repair path (the 5 Lost-softlock fns)
bool        g_diag_ready = false;   // diagnostic getters (4 *Home flag reads)
bool        g_acquire_ready = false;  // force-acquire mutators (3 *Home writes)

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

    // Diagnostic getters resolve independently — a missing one disables only
    // the logging spike, never the Lost repair path (and vice versa).
    bool diag = true;
    diag &= resolveOne(g_fns.isExistHome,
        smoap::sym::kGameDataFunctionIsExistHome, "isExistHome");
    diag &= resolveOne(g_fns.isActivateHome,
        smoap::sym::kGameDataFunctionIsActivateHome, "isActivateHome");
    diag &= resolveOne(g_fns.isLaunchHome,
        smoap::sym::kGameDataFunctionIsLaunchHome, "isLaunchHome");
    diag &= resolveOne(g_fns.getHomeLevel,
        smoap::sym::kGameDataFunctionGetHomeLevel, "getHomeLevel");
    // getCurrentStageName is shared with the repair path; the diag pass also
    // needs it, so fold its readiness in.
    g_diag_ready = diag && (g_fns.getCurrentStageName != nullptr);
    SMOAP_LOG_INFO("OdysseyRescue: diagnostic getters %s",
                   g_diag_ready ? "COMPLETE" : "PARTIAL (home-state log disabled)");

    // Force-acquire mutators (forceAcquireOdyssey). Independent readiness — a
    // missing one disables only the acquire path, never the repair/diag paths.
    bool acq = true;
    acq &= resolveOne(g_fns.activateHome,
        smoap::sym::kGameDataFunctionActivateHome, "activateHome");
    acq &= resolveOne(g_fns.upHomeLevel,
        smoap::sym::kGameDataFunctionUpHomeLevel, "upHomeLevel");
    acq &= resolveOne(g_fns.launchHome,
        smoap::sym::kGameDataFunctionLaunchHome, "launchHome");
    g_acquire_ready = acq;
    SMOAP_LOG_INFO("OdysseyRescue: force-acquire mutators %s",
                   g_acquire_ready ? "COMPLETE" : "PARTIAL (acquire disabled)");
}

void forceAcquireOdyssey(const char* tag) {
    if (!g_acquire_ready) return;
    void* gdh = smoap::ap::ApState::instance().game_data_holder_cache.load(
        std::memory_order_relaxed);
    if (!gdh) return;
    GameDataHolderAccessor acc{gdh};
    GameDataHolderWriter   wr {gdh};

    // Read the before-state (best-effort; diag getters share readiness with the
    // log path but are resolved independently of g_acquire_ready).
    const bool e0  = g_fns.isExistHome    ? g_fns.isExistHome(acc)    : false;
    const bool a0  = g_fns.isActivateHome ? g_fns.isActivateHome(acc) : false;
    const bool l0  = g_fns.isLaunchHome   ? g_fns.isLaunchHome(acc)   : false;
    const int  lv0 = g_fns.getHomeLevel   ? g_fns.getHomeLevel(acc)   : 0;

    // Already fully acquired (post-Broode / a normal revisit) → nothing to do.
    // This keeps the write a true no-op once the Odyssey is legitimately owned.
    if (a0 && l0 && lv0 >= 1) return;

    // Write the same save-state the Broode-completion path sets:
    //   activateHome -> isExistHome + isActivateHome
    //   upHomeLevel  -> level 0 -> 1 (only bump from 0 so we never over-level
    //                   the player's paid Odyssey upgrades)
    //   launchHome   -> isLaunchHome (flightworthy / boardable)
    if (!a0)       g_fns.activateHome(wr);
    if (lv0 < 1)   g_fns.upHomeLevel(wr);
    if (!l0)       g_fns.launchHome(wr);

    static int s_log = 0;
    if (s_log < 20) {
        ++s_log;
        SMOAP_LOG_INFO("[odyssey-acquire] %s force: before exist=%d activate=%d "
                       "launch=%d level=%d -> activate+level+launch #%d",
                       tag ? tag : "?", e0, a0, l0, lv0, s_log);
    }
}

namespace {

// Logger-only spike for the "Odyssey always available in any visited overworld"
// feature (docs/v3-feasibility/future-feasibility-odyssey-always-available.md).
//
// Characterizes the home-ship save-state in whatever overworld Mario is
// currently standing in. NO mutation — this only READS flags, so it can never
// corrupt a save. We log the (exist/activate/launch/crash/level) tuple only
// when it changes for the current stage (plus an occasional heartbeat), so a
// session produces a clean transition trace rather than 1 line/sec of spam.
//
// What the trace decides (per the feasibility doc's "dominant unknown"):
//   - which flag(s) are FALSE in a stranded overworld vs. a normal one →
//     which mutator(s) (activateHome / launchHome / repairHome) the force-fix
//     tier must call; and
//   - whether a not-yet-spawned Odyssey ever flips exist=1 on its own (it
//     won't here — that question needs the force tier) — but the baseline
//     trace tells us the normal-arrival flag progression to target.
void logOdysseyHomeStateDiag(GameDataHolderAccessor acc) {
    if (!g_diag_ready) return;

    const char* stage = g_fns.getCurrentStageName(acc);
    if (!stage) return;

    // Only overworld home stages are interesting — kingdomShortFromHomeStage
    // returns nullptr for subareas / boss / cutscene stages.
    const char* kingdom = kingdomShortFromHomeStage(stage);
    if (!kingdom) return;

    const bool exist    = g_fns.isExistHome(acc);
    const bool activate = g_fns.isActivateHome(acc);
    const bool launch   = g_fns.isLaunchHome(acc);
    const bool crash    = g_fns.isCrashHome ? g_fns.isCrashHome(acc) : false;
    const int  level    = g_fns.getHomeLevel(acc);

    // Pack into a small signature to dedupe. Stage pointer identity isn't
    // stable across loads, so key on the kingdom short name + flag bits.
    const unsigned bits = (exist ? 1u : 0u) | (activate ? 2u : 0u) |
                          (launch ? 4u : 0u) | (crash ? 8u : 0u) |
                          (static_cast<unsigned>(level & 0xf) << 4);

    static const char* s_last_kingdom = nullptr;
    static unsigned     s_last_bits    = 0xffffffffu;
    static int          s_heartbeat    = 0;

    const bool changed = (kingdom != s_last_kingdom) || (bits != s_last_bits);
    const bool heartbeat = (++s_heartbeat % 1800) == 0;  // ~30 min @ 1 call/s
    if (!changed && !heartbeat) return;
    s_last_kingdom = kingdom;
    s_last_bits    = bits;

    SMOAP_LOG_INFO(
        "OdysseyRescue/diag: stage=%s kingdom=%s exist=%d activate=%d "
        "launch=%d crash=%d level=%d%s",
        stage, kingdom, exist, activate, launch, crash, level,
        heartbeat ? " (heartbeat)" : "");
}

}  // namespace

void runOdysseySoftlockSweep() {
    if (!g_ready) return;
    void* gdh = smoap::ap::ApState::instance().game_data_holder_cache.load(
        std::memory_order_relaxed);
    if (!gdh) return;
    GameDataHolderAccessor acc{gdh};
    GameDataHolderWriter   wr {gdh};

    // Logger-only spike: characterize the home-ship save-state in the current
    // overworld (read-only; see logOdysseyHomeStateDiag). Runs on the same
    // ~1s throttle as the repair sweep below.
    logOdysseyHomeStateDiag(acc);

    // Log throttle — the branch below is a no-op on virtually every call once
    // the player leaves Lost; only state transitions are worth logging.
    // Logging every 600 calls (≈10s at the caller's ~1 call/s throttle × 60
    // frames) gives a heartbeat without spam.
    static int s_lost_log = 0;

    // --- Lost Kingdom ---
    // Wrecked Odyssey state in Lost: force repair + unlock so a player who
    // rushed in with an unswept upstream can backtrack to Wooded and collect
    // the moons that gate this kingdom. unlockWorld(getWorldIndexClash())
    // unlocks the world Mario is already in (Lost), so it doesn't perturb the
    // post-kingdom autopilot the way pre-unlocking the *next* world would.
    //
    // Ruined Kingdom is deliberately NOT handled here. Ruined grounds the
    // Odyssey via the Lord of Lightning's boss-attack state, which vanilla
    // clears the moment the player beats the dragon and collects the Ruined
    // Multi-Moon. We keep that Multi-Moon pinned to its vanilla location (the
    // dragon) in AP fill — see apworld locations.json "place_item" on
    // "Ruined: Battle with the Lord of Lightning!" — so beating the dragon
    // always repairs the Odyssey and lets the player leave. No sweep needed,
    // and crucially no risk of the counter-overshoot bug that the old Ruined
    // backtrack path triggered (post-boss autopilot skipping Bowser → Moon).
    if (g_fns.isCrashHome(acc)) {
        const char* stage = g_fns.getCurrentStageName(acc);
        if (stage && std::strcmp(stage, "ClashWorldHomeStage") == 0) {
            if ((s_lost_log++ % 600) == 0) {
                SMOAP_LOG_INFO(
                    "OdysseyRescue: Lost crashHome → repair + unlock");
            }
            g_fns.repairHome(wr);
            g_fns.unlockWorld(wr, g_fns.getWorldIndexClash());
        } else {
            // Crashed home outside Lost: a stray mid-cinematic crash — repair
            // so the player isn't stranded.
            g_fns.repairHome(wr);
        }
    }
}

}  // namespace smoap::game
