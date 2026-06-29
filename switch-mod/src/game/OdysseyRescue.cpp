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
// First-visit / world-warp-demo getters (logger spike, 2026-06-27).
using GetCurrentWorldIdFn         = int         (*)(GameDataHolderAccessor);
using IsAlreadyGoWorldFn          = bool        (*)(GameDataHolderAccessor, int);
// First-arrival parked-pose fix: GameProgressData::setAlreadyGoWorld(s32) is a
// MEMBER (implicit this = GameProgressData*); the Itanium ABI passes this in x0.
using SetAlreadyGoWorldFn         = void        (*)(void* /*GameProgressData*/, int);

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
    // First-visit / world-warp-demo getters (logger spike) — read-only.
    GetCurrentWorldIdFn         getCurrentWorldId         = nullptr;
    IsAlreadyGoWorldFn          isAlreadyGoWorld          = nullptr;
    HomeFlagFn                  isFirstTimeNextWorld      = nullptr;
    HomeFlagFn                  isForwardWorldWarpDemo    = nullptr;
    HomeFlagFn                  isPlayDemoWorldWarp       = nullptr;
    HomeFlagFn                  isEnterStageFirst         = nullptr;
    // First-arrival parked-pose fix (forceCascadeAlreadyVisited) — WRITE.
    SetAlreadyGoWorldFn         setAlreadyGoWorld         = nullptr;
    GetWorldIndexFn             getWorldIndexWaterfall    = nullptr;
};

// Cascade free-travel rescue (2026-06-29): DISABLED after in-game test. The
// repairHome+launch sweep was a NO-OP — the log showed the ship already
// exist=activate=launch=1, crash=0, level=1 on Cascade arrival, unchanged before
// vs after, yet still unboardable pre-Broode. So the burial is the SCENARIO-1
// actor placement, not any home-ship flag (repairHome had nothing to repair).
// The real blocker to leaving Cascade was never the ship — it was the AP
// leave-gate (findUnlockShineNum -> rolled 6); that's now handled in
// UnlockShineNumHook (drop the gate to 0 once Broode's Multi-Moon is collected).
// Kept as a documented stub (false) rather than deleted, in case the
// scenario-placed-pose question is revisited.
inline constexpr bool kCascadeFreeTravelRescue = false;

ResolvedFns g_fns;
bool        g_ready = false;        // repair path (the 5 Lost-softlock fns)
bool        g_diag_ready = false;   // diagnostic getters (4 *Home flag reads)
bool        g_acquire_ready = false;  // force-acquire mutators (3 *Home writes)
bool        g_warpdemo_ready = false; // first-visit / world-warp-demo getters

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

    // First-visit / world-warp-demo getters (logger spike, 2026-06-27).
    // Independent readiness — these only feed logWorldWarpDemoDiag and never
    // mutate. A wrong mangling shows as "lookup FAILED" here; fix that one and
    // rebuild. getCurrentStageName is shared with the diag path above.
    // Per-function (tolerant): some of these demo getters may be inlined / not
    // exported in main.nso's dynsym. We don't &&-fold readiness — each resolves
    // independently and the diag prints -1 for any that didn't, so one miss never
    // disables the whole trace. The spike runs as long as the two essentials
    // (getCurrentStageName + getCurrentWorldId) are present.
    resolveOne(g_fns.getCurrentWorldId,
        smoap::sym::kGameDataFunctionGetCurrentWorldId, "getCurrentWorldId");
    resolveOne(g_fns.isAlreadyGoWorld,
        smoap::sym::kGameDataFunctionIsAlreadyGoWorld, "isAlreadyGoWorld");
    resolveOne(g_fns.isFirstTimeNextWorld,
        smoap::sym::kGameDataFunctionIsFirstTimeNextWorld, "isFirstTimeNextWorld");
    resolveOne(g_fns.isForwardWorldWarpDemo,
        smoap::sym::kGameDataFunctionIsForwardWorldWarpDemo, "isForwardWorldWarpDemo");
    resolveOne(g_fns.isPlayDemoWorldWarp,
        smoap::sym::kGameDataFunctionIsPlayDemoWorldWarp, "isPlayDemoWorldWarp");
    resolveOne(g_fns.isEnterStageFirst,
        smoap::sym::kGameDataFunctionIsEnterStageFirst, "isEnterStageFirst");
    g_warpdemo_ready = (g_fns.getCurrentStageName != nullptr) &&
                       (g_fns.getCurrentWorldId != nullptr);
    SMOAP_LOG_INFO("OdysseyRescue: world-warp-demo getters %s",
                   g_warpdemo_ready ? "READY (per-flag; -1 = unresolved)"
                                    : "DISABLED (no stage/world getter)");

    // First-arrival parked-pose fix (forceCascadeAlreadyVisited). Independent
    // readiness; a missing one self-disables only this fix.
    resolveOne(g_fns.setAlreadyGoWorld,
        smoap::sym::kGameProgressDataSetAlreadyGoWorld, "setAlreadyGoWorld");
    resolveOne(g_fns.getWorldIndexWaterfall,
        smoap::sym::kGameDataFunctionGetWorldIndexWaterfall, "getWorldIndexWaterfall");
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

// First-visit / world-warp-demo logger spike (2026-06-27). READ-ONLY — decides
// what gates the BURIED Cascade arrival pose. The 2026-06-27 trace ruled out
// entrance id / ChangeStageInfo scenario / Home activate-launch flags / level
// (all forced, ship stayed buried). Devon's datapoint: a RETURN flight to
// Cascade forced to scenario 1 lands PARKED with Broode present, while the FIRST
// arrival at scenario 1 buries it — so the lever is a first-visit/demo flag.
// This logs that flag set for the current overworld so we can read it on the
// buried first arrival and (ideally) compare to a parked revisit.
//
// What to look for: on the BURIED first Cascade arrival vs. a PARKED revisit,
// which of {alreadyGo, firstNext, fwdWarpDemo, playWarpDemo, enterFirst} differs.
// The one that flips between buried and parked is the lever to set/suppress
// (e.g. mark isAlreadyGoWorld true / noPlayDemoWorldWarp before the commit).
void logWorldWarpDemoDiag(GameDataHolderAccessor acc) {
    if (!g_warpdemo_ready) return;

    const char* stage = g_fns.getCurrentStageName(acc);
    if (!stage) return;
    const char* kingdom = kingdomShortFromHomeStage(stage);
    if (!kingdom) return;  // overworld home stages only

    const int worldId    = g_fns.getCurrentWorldId(acc);
    // -1 = the getter didn't resolve (inlined / not exported); 0/1 otherwise.
    const int alreadyGo   = g_fns.isAlreadyGoWorld ? g_fns.isAlreadyGoWorld(acc, worldId) : -1;
    const int firstNext   = g_fns.isFirstTimeNextWorld ? g_fns.isFirstTimeNextWorld(acc) : -1;
    const int fwdWarpDemo = g_fns.isForwardWorldWarpDemo ? g_fns.isForwardWorldWarpDemo(acc) : -1;
    const int playWarpDemo= g_fns.isPlayDemoWorldWarp ? g_fns.isPlayDemoWorldWarp(acc) : -1;
    const int enterFirst  = g_fns.isEnterStageFirst ? g_fns.isEnterStageFirst(acc) : -1;

    const unsigned bits =
        (static_cast<unsigned>(alreadyGo & 3) << 0) |
        (static_cast<unsigned>(firstNext & 3) << 2) |
        (static_cast<unsigned>(fwdWarpDemo & 3) << 4) |
        (static_cast<unsigned>(playWarpDemo & 3) << 6) |
        (static_cast<unsigned>(enterFirst & 3) << 8) |
        (static_cast<unsigned>(worldId & 0xff) << 10);

    static const char* s_last_kingdom = nullptr;
    static unsigned     s_last_bits    = 0xffffffffu;
    static int          s_heartbeat    = 0;
    const bool changed = (kingdom != s_last_kingdom) || (bits != s_last_bits);
    const bool heartbeat = (++s_heartbeat % 1800) == 0;
    if (!changed && !heartbeat) return;
    s_last_kingdom = kingdom;
    s_last_bits    = bits;

    SMOAP_LOG_INFO(
        "OdysseyRescue/warpdemo: stage=%s kingdom=%s worldId=%d alreadyGo=%d "
        "firstNext=%d fwdWarpDemo=%d playWarpDemo=%d enterFirst=%d%s",
        stage, kingdom, worldId, alreadyGo, firstNext, fwdWarpDemo,
        playWarpDemo, enterFirst, heartbeat ? " (heartbeat)" : "");
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
    // First-visit / world-warp-demo spike (read-only; see logWorldWarpDemoDiag).
    logWorldWarpDemoDiag(acc);

    // --- Cascade first-arrival: lift the Odyssey out of the rocks ---
    // On the story-drop into Cascade (entrance id='start') the arrival init
    // resets the home LEVEL to 0 AFTER forceAcquireOdyssey's pre-load write, so
    // the ship is PLACED in its buried/level-0 pose even though activate/launch
    // stuck (measured 2026-06-27: post-arrival exist/activate/launch=1, level=0).
    // The parked-vs-buried pose tracks getHomeLevel — proven by the flight
    // arrival into Cascade, which is the SAME state (scenario 1, Broode present)
    // but lands parked precisely because its level survives at 1. So re-assert
    // level 1 here, AFTER the arrival init has run, to lift the ship into the
    // parked pose while leaving the scenario-1 Broode force untouched.
    //
    // getHomeLevel is a plain stored field (OdysseyDecomp GameProgressData), so
    // upHomeLevel(0->1) is a bounded one-step bump; the level==0 guard makes it
    // a true no-op once it has taken (and post-first-moon / post-Broode, where
    // level is already >=1). isActivateHome gates it to a Cascade where the
    // Odyssey is ours (our force ran, or normal play) so we never poke a kingdom
    // mid-cinematic before the ship belongs to the player.
    //
    // Needs the diag getters (isActivateHome/getHomeLevel) + the acquire mutator
    // (upHomeLevel); both resolve independently of the Lost repair path.
    if (g_diag_ready && g_acquire_ready) {
        const char* stage = g_fns.getCurrentStageName(acc);
        if (stage && std::strcmp(stage, "WaterfallWorldHomeStage") == 0 &&
            g_fns.isActivateHome(acc) && g_fns.getHomeLevel(acc) == 0) {
            g_fns.upHomeLevel(wr);
            static int s_free_log = 0;
            if (s_free_log < 20) {
                ++s_free_log;
                // A SINGLE line then silence = the arrival init clobbered level
                // once and our re-assert held. REPEATED lines = the level is
                // re-clamped every frame (the ship would flicker) — escalate to
                // a self-reload instead of a per-frame top-up.
                SMOAP_LOG_INFO("[odyssey-freeship] Cascade home level 0 -> 1 "
                               "(re-assert post-arrival; lift ship from rocks) #%d",
                               s_free_log);
            }
        }
    }

    // --- Cascade free-travel rescue (Lost-style, 2026-06-29) ---
    // Devon's request: make Cascade's Odyssey boardable the same way the Lost
    // sweep below repairs Lost, so a free-travel player who flew in from Cap can
    // fly back out WITHOUT first beating Broode / clearing the kingdom. Unlike
    // Lost (isCrashHome=true → repairHome clears it), Cascade reads crash=0: its
    // ship is placed buried by the SCENARIO-1 layout, not by the crash flag. So
    // repairHome may be a no-op here — this is a TEST. The before/after home-state
    // log tells us definitively: if (exist,activate,launch,crash,level) is
    // unchanged AND the ship stays in the rocks, the burial is pure scenario
    // placement and the real fix is to arrive in a peace scenario (which removes
    // Broode — a trade-off to settle with Devon). repairHome is called UNGATED by
    // isCrashHome (the one change vs. the Lost branch). We also force
    // activate/launch/level so the save-state is fully flightworthy.
    if (kCascadeFreeTravelRescue && g_ready && g_diag_ready && g_acquire_ready) {
        const char* stage = g_fns.getCurrentStageName(acc);
        if (stage && std::strcmp(stage, "WaterfallWorldHomeStage") == 0) {
            const bool e0 = g_fns.isExistHome(acc);
            const bool a0 = g_fns.isActivateHome(acc);
            const bool l0 = g_fns.isLaunchHome(acc);
            const bool c0 = g_fns.isCrashHome(acc);
            const int  v0 = g_fns.getHomeLevel(acc);

            // Lost-style repair (ungated by crash) + full flightworthy state.
            g_fns.repairHome(wr);
            if (!a0) g_fns.activateHome(wr);
            if (!l0) g_fns.launchHome(wr);
            if (v0 < 1) g_fns.upHomeLevel(wr);

            const bool e1 = g_fns.isExistHome(acc);
            const bool a1 = g_fns.isActivateHome(acc);
            const bool l1 = g_fns.isLaunchHome(acc);
            const bool c1 = g_fns.isCrashHome(acc);
            const int  v1 = g_fns.getHomeLevel(acc);

            static int s_resc_log = 0;
            if (s_resc_log < 30) {
                ++s_resc_log;
                SMOAP_LOG_INFO("[cascade-rescue] repairHome+launch: before "
                               "exist=%d act=%d launch=%d crash=%d lvl=%d -> after "
                               "exist=%d act=%d launch=%d crash=%d lvl=%d #%d",
                               e0, a0, l0, c0, v0, e1, a1, l1, c1, v1, s_resc_log);
            }
        }
    }

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

void logWorldWarpDemoDiagNow(const char* tag) {
    if (!g_warpdemo_ready) return;
    void* gdh = smoap::ap::ApState::instance().game_data_holder_cache.load(
        std::memory_order_relaxed);
    if (!gdh) return;
    GameDataHolderAccessor acc{gdh};

    const char* stage   = g_fns.getCurrentStageName(acc);
    const int   worldId = g_fns.getCurrentWorldId(acc);
    // -1 = the getter didn't resolve (inlined / not exported); 0/1 otherwise.
    SMOAP_LOG_INFO(
        "OdysseyRescue/warpdemo-now[%s]: cur=%s worldId=%d alreadyGo=%d "
        "firstNext=%d fwdWarpDemo=%d playWarpDemo=%d enterFirst=%d",
        tag ? tag : "?", stage ? stage : "(null)", worldId,
        g_fns.isAlreadyGoWorld ? g_fns.isAlreadyGoWorld(acc, worldId) : -1,
        g_fns.isFirstTimeNextWorld ? g_fns.isFirstTimeNextWorld(acc) : -1,
        g_fns.isForwardWorldWarpDemo ? g_fns.isForwardWorldWarpDemo(acc) : -1,
        g_fns.isPlayDemoWorldWarp ? g_fns.isPlayDemoWorldWarp(acc) : -1,
        g_fns.isEnterStageFirst ? g_fns.isEnterStageFirst(acc) : -1);

    // isAlreadyGoWorld bitmap across ALL worlds (index = worldId; Cap=0,
    // Cascade=1, Sand=2, ...). At the Cap->Cascade commit getCurrentWorldId is
    // still Cap, so the single read above is Cap's flag — useless for Cascade.
    // THIS is the decisive read: Cascade's bit (index 1) BEFORE the first
    // arrival vs. before a return flight. If it reads 0 on first arrival and 1
    // on a return flight, "already gone to Cascade" is the buried-vs-parked
    // lever and we try setting it before the commit. If it's identical, the
    // pose is driven by the prologue demo-warp PATH, not this flag (→ pursue the
    // Cap-peace / depart-via-world-map route).
    if (g_fns.isAlreadyGoWorld) {
        char bits[24];
        int n = 0;
        for (int w = 0; w <= 16 && n < static_cast<int>(sizeof(bits)) - 1; ++w)
            bits[n++] = g_fns.isAlreadyGoWorld(acc, w) ? '1' : '0';
        bits[n] = '\0';
        SMOAP_LOG_INFO(
            "OdysseyRescue/warpdemo-now[%s]: alreadyGoWorld[0..16]=%s "
            "(idx1=Cascade)", tag ? tag : "?", bits);
    }
}

void forceUnlockCascadeDestination(const char* tag) {
    if (!g_fns.unlockWorld || !g_fns.getWorldIndexWaterfall) return;
    void* gdh = smoap::ap::ApState::instance().game_data_holder_cache.load(
        std::memory_order_relaxed);
    if (!gdh) return;
    GameDataHolderWriter wr{gdh};
    const int widx = g_fns.getWorldIndexWaterfall();  // Cascade's world index.
    g_fns.unlockWorld(wr, widx);
    static int s_log = 0;
    if (s_log < 20) {
        ++s_log;
        SMOAP_LOG_INFO("[cap-return] %s unlockWorld(Cascade widx=%d) -> Odyssey "
                       "world map offers Cascade as a flight destination #%d",
                       tag ? tag : "?", widx, s_log);
    }
}

void forceCascadeAlreadyVisited(void* gameDataFile, const char* tag) {
    if (!gameDataFile || !g_fns.setAlreadyGoWorld || !g_fns.getWorldIndexWaterfall)
        return;
    // GameDataFile::mGameProgressData @ 0x6a8 (OdysseyHeaders GameDataFile.h).
    void* progress = *reinterpret_cast<void**>(
        reinterpret_cast<std::uint8_t*>(gameDataFile) + 0x6a8);
    if (!progress) return;
    const int widx = g_fns.getWorldIndexWaterfall();  // Cascade's world index.
    // setAlreadyGoWorld just inserts into the visited set (idempotent — the
    // return-flight path has it set already and re-arrives fine), so calling it
    // unconditionally before the first-arrival commit makes the engine run the
    // normal PARKED flight landing instead of the buried first-visit demo.
    g_fns.setAlreadyGoWorld(progress, widx);
    static int s_log = 0;
    if (s_log < 20) {
        ++s_log;
        SMOAP_LOG_INFO("[odyssey-arrival] %s setAlreadyGoWorld(Cascade widx=%d) "
                       "-> run parked flight arrival, not buried demo #%d",
                       tag ? tag : "?", widx, s_log);
    }
}

}  // namespace smoap::game
