// Cloud Kingdom first-arrival Bowser encounter (vanilla-arrival force).
//
// === The bug (2026-07-14) ==================================================
// Flying to Cloud Kingdom for the FIRST time (post Lake/Wooded fork) loaded the
// kingdom in its world-peace layout instead of scenario 1's Bowser encounter.
// The quest state was still pre-fight — the Odyssey globe demanded the Bowser
// fight before offering onward story progress AND grounded the ship — but with
// the peace layout placed there is no encounter trigger to satisfy it: a hard
// softlock. Same failure class as the Cascade first-flight peace bug
// (CascadeBroodeRespawnHook): the engine recomputes a kingdom's arrival
// scenario from global progress signals our forces have advanced, and vanilla
// never map-selects Cloud pre-fight, so a direct pre-fight fly-in has no
// correct recompute answer (the engine handed Cloud scenario 4).
//
// === The fix ===============================================================
// While the Bowser encounter has not happened yet, force EVERY commit into
// Cloud's home stage to scenario 1 so the encounter is placed and plays on
// arrival — the vanilla first visit. Afterwards the force releases and
// arrivals load the engine's computed (peace) scenario: fight once, peaceful
// ever after, exactly vanilla.
//
// "Has not happened yet" = GameProgressData::mHomeStatus < HomeStatus::
// FoundKoopa — read as !isFindKoopa && !isCrashHome && !isRepairHome (the
// three exported reads are ==FoundKoopa(3), ==CrashedHome(4), >CrashedHome;
// see HookSymbols.hpp). This is the SAME monotonic gate vanilla's own
// interception scheduler uses, which is what makes it robust:
//   * It can never disagree with the globe's story lock: the interception can
//     only arm while status < FoundKoopa, so whenever the lock demands the
//     fight we force it, and once status passes FoundKoopa the lock can never
//     re-arm (monotonic) so releasing is always safe.
//   * The vanilla fight itself advances it (the knockdown calls crashHome →
//     CrashedHome; the Lost repair — vanilla or OdysseyRescue's gated force —
//     advances to RepairedHome), so completion releases the force without any
//     bookkeeping of ours.
//   * Chain arrivals / shuffled-door visits (Lost included) never touch
//     HomeStatus, unlike alreadyGo bits — the trap the previous predicate had.
//   * Our own forces can't poison it: forceAcquireOdyssey's activateHome/
//     launchHome cap at LaunchedHome(2); every live repairHome call in
//     OdysseyRescue is gated on isCrashHome (only true post-knockdown); the
//     one ungated repairHome (kCascadeFreeTravelRescue) is a dead false stub.
//   * A Ruined-first shuffled seed jumps status to BossAttackedHome(6) via the
//     dragon before Cloud: the force then never fires — correct, because with
//     status past FoundKoopa the interception (and its globe lock) can never
//     arm, so peace-Cloud is consistent and the fight beat is simply skipped.
//
// === Predicate provenance (three in-game walks, 2026-07-14) ================
//   walk #1 — isClearWorldMainScenario(Cloud) read TRUE on the pre-fight
//     softlocked save (force never fired): poisoned by the same global
//     recompute. Demoted to a diagnostic.
//   walk #2 — getMainScenarioNo(Cloud) <= 1 fired correctly and the fight
//     un-softlocked the save, but it stays 1 AFTER the fight too (Cloud has no
//     quest-tracked advancement), so the fight re-triggered on every arrival.
//   walk #3 — the re-triggered fight is actively dangerous, not just
//     annoying: with HomeStatus already >= CrashedHome the knockdown chain has
//     nothing to advance and REFUSES to play, stranding Mario in a dead
//     post-fight state (no save, no warp, objects missing); and an Odyssey
//     takeoff attempted from the forced scenario-1 layout CRASHES (takeoff
//     demo vs a placement vanilla can never take off from — the Cascade
//     obj214 demo-vs-placement crash class). Hence the release must be
//     save-backed and once-only: HomeStatus.
//   (alreadyGo(Lost) was briefly the release between walks #2 and #3 — never
//   shipped: chain-visiting Lost pre-fight would poison it. getMainScenarioNo
//   stays in the diag line only.)
//
// Scope: EVERY commit into Cloud's home stage while the encounter is pending —
// external origins (kingdom-select flights, chain arrivals / shuffled doors,
// the Odyssey cabin) AND Cloud-internal ones (subarea pop-outs). "Cloud's home
// stage" matches BOTH the literal 'CloudWorldHomeStage' AND the
// 'CurrentWorldHome' ALIAS the Odyssey-cabin exit door commits with (walk #1
// log) when the engine's current world is Cloud — so the in-place rescue on a
// softlocked save is boarding the Odyssey and stepping back out. No
// internal-origin exemption is needed: a moon-rock reload can only follow
// story completion, and the predicate has released by then.
//
// === Mechanism — same two levers as the Cascade/Broode force ===============
// No trampoline of our own. EntranceShuffleHook's GameDataFile::changeNextStage
// commit calls:
//   - cloudArrivalScenarioOverride() pre-orig → written into
//     ChangeStageInfo.mScenarioNo (@0x1CC), the scenario-jump load input that
//     DRIVES the load (proven on Cascade and again on walk #2 here).
//   - forceCloudPlacementScenario() post-orig → belt-and-braces write of
//     GameDataFile::mScenarioNoPlacement (@0xb60), the field the object-
//     placement masker reads (offset provenance: CascadeBroodeRespawnHook).
//
// Fail direction: any degraded read (symbol unresolved, holder missing) forces
// NOTHING — the arrival loads whatever the engine computed, never a stuck
// forced state. Every Cloud-home commit logs a bounded ground-truth line with
// all candidate signals so a wrong assumption shows up in the next walk
// instead of a silent no-op (the walk-#1 lesson).

#include "hk/ro/RoUtil.h"
#include "hk/types.h"

#include "../ap/ApState.hpp"           // holder cache (accessor reads)
#include "../game/CrossWorldLoad.hpp"  // resolveWorldIdForStage
#include "../util/Log.hpp"
#include "HookSymbols.hpp"

#include <atomic>
#include <cstddef>
#include <cstdint>
#include <cstring>

namespace smoap::hooks {

namespace {

// When false both entry points return "don't force" so a diagnostic build can
// ship without touching Cloud placement.
inline constexpr bool kCloudEncounterApply = true;

// Cloud's Bowser-encounter scenario — the layout the vanilla first visit loads
// (analogous to Broode's Cascade scenario 1).
inline constexpr int kCloudEncounterScenario = 1;

// Cloud Kingdom's overworld — the only destination this force is scoped to.
inline constexpr const char* kCloudHomeStage = "CloudWorldHomeStage";

// The "reload my current world's home stage" alias the Odyssey-cabin exit door
// commits with. Only counts as a Cloud commit when the engine's current world
// IS Cloud.
inline constexpr const char* kCurrentWorldHomeAlias = "CurrentWorldHome";

// GameDataFile::mScenarioNoPlacement (see CascadeBroodeRespawnHook: pinned by
// the decomp's end-of-struct static_assert, 0xb68 total).
inline constexpr std::size_t kOffScenarioNoPlacement = 0xb60;

struct GameDataHolderAccessorMirror { void* mData; };

// The three HomeStatus reads whose OR is "status >= FoundKoopa" (see
// HookSymbols.hpp). All three must resolve or the force stays disabled.
using HomeStatusReadFn = bool (*)(GameDataHolderAccessorMirror);
HomeStatusReadFn s_isFindKoopa  = nullptr;
HomeStatusReadFn s_isCrashHome  = nullptr;
HomeStatusReadFn s_isRepairHome = nullptr;

// Diagnostic-only reads (logged, never gate anything): the walk-#1 poisoned
// clear flag and the walk-#2 quest-stage number.
using IsClearWorldMainScenarioFn = bool (*)(const void* gdf, int world_id);
using GetMainScenarioNoFn        = int  (*)(const void* gdf, int world_id);
IsClearWorldMainScenarioFn s_isClearWorldMainScenario = nullptr;
GetMainScenarioNoFn        s_getMainScenarioNo        = nullptr;

// Engine current-world read (same plumbing KingdomOrderGate/MoonRockHook use).
// -1 when the holder or symbol isn't ready.
int engineCurrentWorldId() {
    using GetCurrentWorldIdFn = int (*)(GameDataHolderAccessorMirror);
    auto& s = smoap::ap::ApState::instance();
    void* holder = s.game_data_holder_cache.load(std::memory_order_relaxed);
    if (!holder || !s.get_current_world_id_fn) return -1;
    auto fn = reinterpret_cast<GetCurrentWorldIdFn>(s.get_current_world_id_fn);
    return fn(GameDataHolderAccessorMirror{holder});
}

// True when this commit's destination is Cloud's overworld: the literal home
// stage, or the CurrentWorldHome alias while the current world is Cloud.
bool isCloudHomeCommit(const char* destStageName) {
    if (destStageName == nullptr) return false;
    if (std::strcmp(destStageName, kCloudHomeStage) == 0) return true;
    if (std::strcmp(destStageName, kCurrentWorldHomeAlias) == 0) {
        const int cloudWorld =
            smoap::game::resolveWorldIdForStage(kCloudHomeStage);
        return cloudWorld >= 0 && engineCurrentWorldId() == cloudWorld;
    }
    return false;
}

// True only when the encounter is DEFINITIVELY not yet done: all three
// HomeStatus reads are available and all read false (status < FoundKoopa).
// Unreadable state → false, so the caller does not force.
bool encounterDefinitelyNotDone() {
    if (!s_isFindKoopa || !s_isCrashHome || !s_isRepairHome) return false;
    void* holder = smoap::ap::ApState::instance().game_data_holder_cache.load(
        std::memory_order_relaxed);
    if (!holder) return false;
    GameDataHolderAccessorMirror acc{holder};
    return !s_isFindKoopa(acc) && !s_isCrashHome(acc) && !s_isRepairHome(acc);
}

// Ground-truth line on every Cloud-home commit (bounded): whatever the
// predicate decides, all candidate signals are in the log so a wrong
// assumption shows up in the next walk instead of a silent no-op.
void logCloudCommitDiag(const void* gdf, const char* dest, const char* cur,
                        bool forcing) {
    static std::atomic<int> s_log{0};
    if (s_log.fetch_add(1, std::memory_order_relaxed) >= 24) return;
    int findK = -99, crash = -99, repaired = -99;
    void* holder = smoap::ap::ApState::instance().game_data_holder_cache.load(
        std::memory_order_relaxed);
    if (holder) {
        GameDataHolderAccessorMirror acc{holder};
        if (s_isFindKoopa)  findK    = s_isFindKoopa(acc) ? 1 : 0;
        if (s_isCrashHome)  crash    = s_isCrashHome(acc) ? 1 : 0;
        if (s_isRepairHome) repaired = s_isRepairHome(acc) ? 1 : 0;
    }
    const int cloudWorld = smoap::game::resolveWorldIdForStage(kCloudHomeStage);
    const int mainSc = (gdf && s_getMainScenarioNo && cloudWorld >= 0)
        ? s_getMainScenarioNo(gdf, cloudWorld) : -99;
    const int clear = (gdf && s_isClearWorldMainScenario && cloudWorld >= 0)
        ? (s_isClearWorldMainScenario(gdf, cloudWorld) ? 1 : 0) : -99;
    SMOAP_LOG_INFO("[cloud-encounter] commit dest='%s' cur='%s' "
                   "findKoopa=%d crashHome=%d repairHome=%d "
                   "(mainScenario=%d clearFlag=%d) -> %s",
                   dest ? dest : "(null)", cur ? cur : "(null)",
                   findK, crash, repaired, mainSc, clear,
                   forcing ? "FORCE scenario 1" : "leave (vanilla)");
}

}  // namespace

// Called from EntranceShuffleHook's changeNextStage trampoline (pre-orig) with
// the GameDataFile* and the FINAL (post-remap) destination stage name. Returns
// kCloudEncounterScenario when committing ANY arrival into Cloud's home stage
// (any origin — see the scope note above) with the Bowser encounter not yet
// done, else -1 ("don't force"). The caller writes it into
// ChangeStageInfo.mScenarioNo before orig. gameDataFile/curStageName feed the
// diagnostic line only — the gate reads HomeStatus via the holder cache.
int cloudArrivalScenarioOverride(const void* gameDataFile,
                                 const char* destStageName,
                                 const char* curStageName) {
    if (!kCloudEncounterApply) return -1;
    if (!isCloudHomeCommit(destStageName)) return -1;
    const bool force = encounterDefinitelyNotDone();
    logCloudCommitDiag(gameDataFile, destStageName, curStageName, force);
    return force ? kCloudEncounterScenario : -1;
}

// Post-orig belt-and-braces (same pairing as forceCascadePlacementScenario):
// re-assert the placement field so the object-placement masker sees the
// encounter layout even if a recompute between the commit and the load moved
// it. Same predicate as the pre-orig force.
void forceCloudPlacementScenario(void* gameDataFile, const char* destStageName,
                                 const char* curStageName, const char* tag) {
    (void)curStageName;
    if (!kCloudEncounterApply) return;
    if (gameDataFile == nullptr) return;
    if (!isCloudHomeCommit(destStageName)) return;
    if (!encounterDefinitelyNotDone()) return;

    auto* p = reinterpret_cast<std::int32_t*>(
        reinterpret_cast<std::uint8_t*>(gameDataFile) + kOffScenarioNoPlacement);
    const std::int32_t before = *p;
    if (before != kCloudEncounterScenario) *p = kCloudEncounterScenario;
    static int s_log = 0;
    if (s_log < 20) {
        ++s_log;
        SMOAP_LOG_INFO("[cloud-encounter] %s Cloud mScenarioNoPlacement %d -> %d "
                       "(encounter pending) #%d",
                       tag, before, kCloudEncounterScenario, s_log);
    }
}

void installCloudArrivalScenarioHook() {
    struct Read { const char* sym; HomeStatusReadFn* slot; const char* tag; };
    const Read reads[] = {
        {smoap::sym::kGameDataFunctionIsFindKoopa,  &s_isFindKoopa,  "isFindKoopa"},
        {smoap::sym::kGameDataFunctionIsCrashHome,  &s_isCrashHome,  "isCrashHome"},
        {smoap::sym::kGameDataFunctionIsRepairHome, &s_isRepairHome, "isRepairHome"},
    };
    bool ok = true;
    for (const auto& r : reads) {
        const ptr addr = hk::ro::lookupSymbol(r.sym);
        if (addr == 0) {
            *r.slot = nullptr;
            ok = false;
            SMOAP_LOG_WARN("[cloud-encounter] %s lookup FAILED", r.tag);
        } else {
            *r.slot = reinterpret_cast<HomeStatusReadFn>(addr);
        }
    }
    if (!ok) {
        SMOAP_LOG_WARN("[cloud-encounter] HomeStatus reads incomplete — Cloud "
                       "first-arrival force disabled (arrivals load the "
                       "engine's computed scenario)");
        return;
    }

    // Diagnostic-only companions; a miss just blanks that log field.
    const ptr mainAddr =
        hk::ro::lookupSymbol(smoap::sym::kGameDataFileGetMainScenarioNo);
    s_getMainScenarioNo = mainAddr
        ? reinterpret_cast<GetMainScenarioNoFn>(mainAddr) : nullptr;
    const ptr clearAddr =
        hk::ro::lookupSymbol(smoap::sym::kGameDataFileIsClearWorldMainScenario);
    s_isClearWorldMainScenario = clearAddr
        ? reinterpret_cast<IsClearWorldMainScenarioFn>(clearAddr) : nullptr;

    SMOAP_LOG_INFO("[cloud-encounter] armed (force ChangeStageInfo.scenario -> %d "
                   "+ mScenarioNoPlacement@0x%zx on ANY commit into %s or its "
                   "CurrentWorldHome alias while HomeStatus < FoundKoopa; "
                   "apply=%d) — invoked from changeNextStage",
                   kCloudEncounterScenario, kOffScenarioNoPlacement,
                   kCloudHomeStage, kCloudEncounterApply ? 1 : 0);
}

}  // namespace smoap::hooks
