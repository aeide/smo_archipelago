// Cascade / Madame Broode multi-moon respawn (Approach C — "lie at the query").
//
// === The bug ==============================================================
// If Mario leaves Cascade BEFORE fighting Madame Broode, she never reappears
// and her Multi-Moon ("Multi Moon Atop the Falls") becomes permanently
// uncollectable — seed-fatal when that moon is progression. Possible whenever
// the Cascade leave-gate is small enough to satisfy pre-Broode (a low
// randomize_kingdom_gates roll, etc.).
//
// === Mechanism (OdysseyDecomp, see docs/handoff-cascade-broode-respawn.md) =
// Madame Broode + her Multi-Moon are PLACEMENT-gated on Cascade's scenario-1
// layout. The object-placement masker reads the placement scenario via
// GameDataFunction::getScenarioNoPlacement(accessor) (the out-of-line free fn
// wrapping GameDataFile::getScenarioNoPlacement(), the inlined mScenarioNoPlacement
// getter). After leaving early and progressing the global story, Cascade's
// computed placement scenario advances past 1, so neither actor is placed.
//
// The placement/main scenario is RECOMPUTED from quest state on every stage
// transition (calcNextScenarioNo), so you cannot durably WRITE it back to 1 —
// the Cap-peace experiment proved that losing fight (MoonRockHook.cpp header).
// So we intercept the READ instead (the M7 "lie to the game at the query"
// pattern, cf. UnlockShineNumHook): override getScenarioNoPlacement to return 1
// while in Cascade with the Multi-Moon still uncollected. Because it drives the
// value the placement system reads EACH load rather than persisting anything, it
// is immune to calcNextScenarioNo overwriting.
//
// === Self-healing condition ===============================================
// Override fires ONLY when ALL of:
//   * getCurrentStageName() == "WaterfallWorldHomeStage"  (Cascade home)
//   * orig placement scenario > 1                         (kingdom advanced
//                                                           past the Broode
//                                                           scenario — protects
//                                                           the legit first
//                                                           visit / intro)
//   * GameDataFile::isGotShine(multiMoonUid) == false     (moon not yet got)
// Once Broode is beaten the Multi-Moon shine flag flips, the condition goes
// false, and Cascade returns to its computed scenario — satisfying Devon's
// "if the whole kingdom's layout reverts it's acceptable as long as it
// re-reverts back after I leave again."
//
// Devon greenlit the whole-kingdom revert (2026-06-25). Approach B (surgical
// Shine force-spawn) is the fallback if C shows an unforeseen side effect.
//
// === Chokepoint confidence / first-test diagnosis =========================
// getScenarioNoPlacement is provably an out-of-line free function in the decomp
// and is purpose-named for placement, but whether the masker calls IT vs. the
// inlined member was not resolvable from the decomp remotely. So this hook LOGS
// every decision (first N): if Cascade-load produces zero "[broode-respawn]"
// hit lines, the masker inlines the member and we pivot (hook the member's
// caller, or Approach B) — caught in ONE in-game cycle rather than as a silent
// no-op. kCascadeRespawnApply gates the actual return-value override so the hook
// can be shipped log-only if the override ever misbehaves.

#include "hk/hook/Trampoline.h"
#include "hk/ro/RoUtil.h"
#include "hk/types.h"

#include "../ap/shine_lookup.hpp"
#include "../util/Log.hpp"
#include "HookSymbols.hpp"

#include <cstddef>
#include <cstdint>
#include <cstring>

namespace smoap::hooks {

namespace {

// When false the hook only LOGS its verdict (return-value override disabled),
// for shipping a diagnostic build without touching placement. Devon greenlit
// the apply path (2026-06-25), so default true.
inline constexpr bool kCascadeRespawnApply = true;

// Cascade home stage — where Madame Broode is fought (atop the falls).
inline constexpr const char* kCascadeHomeStage = "WaterfallWorldHomeStage";

// The placement scenario Broode + her Multi-Moon are laid out for. We only
// override when the kingdom's computed scenario has advanced PAST this (so the
// legit first-visit / intro flow, scenario 0/1, is never disturbed).
inline constexpr int kBroodeScenario = 1;

// Cascade's SMO world id (KingdomUnlock kKingdoms[] index 1). Used only for the
// diagnostic getScenarioNo(world) read.
inline constexpr int kCascadeWorldId = 1;

// The AP-display name of Cascade's Multi-Moon, used to resolve its shine_uid
// from shine_table.h at install. If this logs uid=-1 in-game, the shine_id in
// shine_table.h differs — grep shine_table.h and update this string.
inline constexpr const char* kMultiMoonDisplayName = "Multi Moon Atop the Falls";

// GameDataHolder + 0x20 -> GameDataFile* (same mirror as MoonRockHook /
// ShineAppearanceHook).
inline constexpr std::size_t kGameDataHolder_mGameDataFileOffset = 0x20;

// Single pointer-sized struct passed in x0 — matches CaptureStartHook /
// OdysseyRescue for the same GameDataFunction free-function calls.
struct GameDataHolderAccessor {
    void* mData;
};

using GetCurrentStageNameFn = const char* (*)(GameDataHolderAccessor);
using IsGotShineFn          = bool (*)(const void* gdf, int uid);
using GetScenarioNoFn       = int (*)(const void* gdf, int world);

GetCurrentStageNameFn s_getCurrentStageName = nullptr;
IsGotShineFn          s_isGotShine          = nullptr;
GetScenarioNoFn       s_getScenarioNo       = nullptr;  // diagnostic only
int                   s_multiMoonUid        = -1;

inline void* gameDataFileFromAccessor(GameDataHolderAccessor acc) {
    if (acc.mData == nullptr) return nullptr;
    return *reinterpret_cast<void* const*>(
        reinterpret_cast<const std::uint8_t*>(acc.mData)
            + kGameDataHolder_mGameDataFileOffset);
}

HkTrampoline<int, GameDataHolderAccessor> scenarioPlacementHook =
    hk::hook::trampoline([](GameDataHolderAccessor acc) -> int {
        const int orig = scenarioPlacementHook.orig(acc);

        const char* stage =
            s_getCurrentStageName ? s_getCurrentStageName(acc) : nullptr;
        const bool inCascade =
            stage != nullptr && std::strcmp(stage, kCascadeHomeStage) == 0;

        static int s_diagCascade = 0;
        static int s_diagOther = 0;

        // === DIAGNOSTIC ===================================================
        // The 2026-06-26 in-game test showed zero override lines on Cascade
        // re-entry, but the old hook only logged inside the override branch —
        // so "no log" couldn't distinguish (A) this free fn is never called on
        // the placement path from (B) it's called but isGotShine returned true.
        // Two SEPARATE caps so early-boot calls can't starve the Cascade ones:
        //   * always log calls made WHILE IN CASCADE (cap 16) — the case we care
        //     about; if this stays silent on Cascade load, the masker doesn't go
        //     through this free fn (case A → pivot).
        //   * log the first few non-Cascade calls (cap 6) just to confirm the fn
        //     is invoked at all.
        const bool doLog = inCascade ? (s_diagCascade < 16)
                                     : (s_diagOther < 6);
        if (doLog) {
            if (inCascade) ++s_diagCascade; else ++s_diagOther;
            void* gdf = gameDataFileFromAccessor(acc);
            int got = -1;
            if (inCascade && s_isGotShine && s_multiMoonUid >= 0 && gdf)
                got = s_isGotShine(gdf, s_multiMoonUid) ? 1 : 0;
            int storedScen = -1;
            if (s_getScenarioNo && gdf)
                storedScen = s_getScenarioNo(gdf, kCascadeWorldId);
            SMOAP_LOG_INFO("[broode-respawn] getScenarioNoPlacement "
                           "stage=%s orig=%d cascade=%d storedScen(Cascade)=%d "
                           "gotMulti=%d uid=%d",
                           stage ? stage : "(null)", orig,
                           inCascade ? 1 : 0, storedScen, got, s_multiMoonUid);
        }

        // === OVERRIDE =====================================================
        if (!inCascade) return orig;

        // Still on / before the Broode scenario: boss is naturally placed
        // (or this is the arrival/intro). Don't touch.
        if (orig <= kBroodeScenario) return orig;

        // Can't verify collection (no shine data / wrong name)? Fail SAFE: do
        // not override, or we'd revert Cascade forever even after the moon is
        // collected.
        if (s_isGotShine == nullptr || s_multiMoonUid < 0) return orig;

        void* gdf = gameDataFileFromAccessor(acc);
        if (gdf == nullptr) return orig;

        const bool got = s_isGotShine(gdf, s_multiMoonUid);
        if (got) return orig;  // Broode beaten / moon collected — real scenario.

        // Left Cascade pre-Broode and progressed: revert to scenario 1 so she
        // and her Multi-Moon are placed again.
        static int s_logged = 0;
        if (s_logged < 8) {
            ++s_logged;
            SMOAP_LOG_INFO("[broode-respawn] OVERRIDE Cascade placement scenario "
                           "%d -> %d (Multi-Moon uid=%d uncollected) apply=%d #%d",
                           orig, kBroodeScenario, s_multiMoonUid,
                           kCascadeRespawnApply ? 1 : 0, s_logged);
        }
        return kCascadeRespawnApply ? kBroodeScenario : orig;
    });

}  // namespace

void installCascadeBroodeRespawnHook() {
    // Resolve the Multi-Moon shine_uid from the (gitignored, per-machine)
    // shine_table.h. Absent on a no-romfs release build -> -1 -> hook
    // soft-degrades (no respawn), which is the fail-safe direction.
    s_multiMoonUid = smoap::game::shineUidByDisplayName(kMultiMoonDisplayName);
    if (s_multiMoonUid < 0) {
        SMOAP_LOG_WARN("[broode-respawn] Multi-Moon %s NOT in shine_table.h "
                       "(uid=-1) — respawn disabled until shine data is present "
                       "(re-run sync_shine_table.py) or the display string is "
                       "corrected", kMultiMoonDisplayName);
    } else {
        SMOAP_LOG_INFO("[broode-respawn] Multi-Moon %s -> shine_uid %d",
                       kMultiMoonDisplayName, s_multiMoonUid);
    }

    // getCurrentStageName + isGotShine — soft-degrade on miss (never abort).
    const ptr stageAddr =
        hk::ro::lookupSymbol(smoap::sym::kGameDataFunctionGetCurrentStageName);
    s_getCurrentStageName =
        reinterpret_cast<GetCurrentStageNameFn>(stageAddr);
    if (stageAddr == 0) {
        SMOAP_LOG_ERROR("[broode-respawn] getCurrentStageName lookup FAILED — "
                        "hook NOT installed (cannot scope to Cascade)");
        return;
    }

    const ptr gotAddr =
        hk::ro::lookupSymbol(smoap::sym::kGameDataFileIsGotShineByUid);
    s_isGotShine = reinterpret_cast<IsGotShineFn>(gotAddr);
    if (gotAddr == 0) {
        SMOAP_LOG_ERROR("[broode-respawn] isGotShine lookup FAILED — hook NOT "
                        "installed (cannot verify Multi-Moon collection)");
        return;
    }

    // getScenarioNo(world) — diagnostic only (logs Cascade's stored scenario
    // alongside the placement scenario). Soft-degrade; not required for the gate.
    s_getScenarioNo = reinterpret_cast<GetScenarioNoFn>(
        hk::ro::lookupSymbol(smoap::sym::kGameDataFileGetScenarioNo));

    // Trampoline getScenarioNoPlacement via runtime lookup + installAtPtr (NOT
    // installAtSym — a miss must soft-degrade, not HK_ABORT the module). Same
    // contract as MoonRockHook's isEnableOpenMoonRock.
    const ptr placementAddr =
        hk::ro::lookupSymbol(smoap::sym::kGameDataFunctionGetScenarioNoPlacement);
    if (placementAddr == 0) {
        SMOAP_LOG_ERROR("[broode-respawn] getScenarioNoPlacement lookup FAILED — "
                        "hook NOT installed; Cascade Broode respawn disabled");
        return;
    }
    SMOAP_LOG_INFO("installing CascadeBroodeRespawnHook -> "
                   "GameDataFunction::getScenarioNoPlacement @ %p (apply=%d)",
                   reinterpret_cast<void*>(placementAddr),
                   kCascadeRespawnApply ? 1 : 0);
    scenarioPlacementHook.installAtPtr(placementAddr);
}

}  // namespace smoap::hooks
