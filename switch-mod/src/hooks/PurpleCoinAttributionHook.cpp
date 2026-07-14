// PurpleCoinAttributionHook — regional (purple) coins credit the SUBAREA's
// HOME kingdom, not the kingdom the player arrived from.
//
// ── The bug (playtest 2026-07-13, cap-purples-found-in-metro-subarea.txt) ────
// With P7 entrance shuffle live, a subarea can be entered from a FOREIGN
// kingdom (Cap -> TrexBikeExStage, a world-7 subarea, via a shuffled door).
// Purple coins collected there were banked to CAP, not the subarea's home
// kingdom. In-game the wrong kingdom's Crazy Cap regional-coin balance grew.
//
// ── Root cause (decomp) ──────────────────────────────────────────────────────
// The whole per-kingdom purple-coin subsystem keys on the engine's CURRENT
// world id, which for a save/scene is GameDataFile::mCurWorldId (read via
// getCurrentWorldIdNoDevelop()). A decoupled cross-world door/pipe entry does
// NOT refresh mCurWorldId — only flights / demo warps do (the P5 CrossWorldLoad
// T-A note documents the same staleness for the world-resource loader; the
// [p5-reswatch] trace in the log shows `resident=7 engineCurWorld=0`, i.e.
// Metro resources resident while the engine still thinks world 0 = Cap).
//
// Collect path (OdysseyDecomp, verified this session):
//   Item/CoinCollect.cpp  exeGot()/exeCountUp():
//       watcher->countup(this);                       // HUD popup (reads coins)
//       GameDataFunction::addCoinCollect(this, mPlacementId);   // the BANK
//   System/GameDataFunction.cpp:1088:
//       void addCoinCollect(GameDataHolderWriter w, const al::PlacementId* p) {
//           w->getGameDataFile()->addCoinCollect(p);   // <- keys by mCurWorldId
//       }
//   System/GameDataFile.cpp:241 (sibling, proves the keying pattern):
//       void useCoinCollect(s32 n) {
//           mUseCoinCollectNum[getCurrentWorldIdNoDevelop()] += n;  // current world
//       }
//   Item/CoinCollectWatcher.cpp:27 countup():
//       s32 got = GameDataFunction::getCoinCollectGotNum(actor);      // current world
//       s32 max = GameDataFunction::getCoinCollectNumMax(actor);      // current world
//       layout->appearCounter(max, got + 1, player);                 // the popup
// `GameDataFile::addCoinCollect(const al::PlacementId*)` itself is not
// decompiled, but the keying input is getCurrentWorldIdNoDevelop() == mCurWorldId
// with high confidence (every current-world coin variant uses it) — and the fix
// is robust either way: we correct the keying INPUT, not the storage.
//
// ── The fix ──────────────────────────────────────────────────────────────────
// For the duration of each purple-coin collect call, temporarily set the
// playing GameDataFile::mCurWorldId to the world of the stage the player is
// actually STANDING in (currentStageWorldId() = getCurrentStageName() ->
// WorldList::tryFindWorldIndexByStageName — the subarea-aware stage->world map
// the entrance/P5 code already uses), then restore it. Scoped + restored so NO
// other current-world-keyed system (world map, scenario/placement selection,
// moon-rock gate, the AddPayShine moon deposit) ever observes the change — this
// is NOT the globally-rewrite-mCurWorldId "T-B" approach the P5 layer rejected
// (whose return-trip restoration is unproven); the value is only different for
// the few instructions of the collect call, on the main game thread.
//
// Two seams, same correction:
//   * GameDataFunction::addCoinCollect  — THE bank (credits the home kingdom).
//   * CoinCollectWatcher::countup       — the on-collect HUD popup, which runs
//     BEFORE addCoinCollect and would otherwise show the ARRIVAL kingdom's
//     total/max (and never tick, since the coin now banks elsewhere).
// Both symbols are HITs in the retail 1.0.0 dynsym (scripts/check_nso_symbols.py,
// this session) and are called from >=2 sites, so they stay out-of-line.
//
// When the player is legitimately in the kingdom (vanilla case, or after flying
// in properly), stageWorld == mCurWorldId and the correction is a pure no-op —
// no write, no log. resolveWorldIdForStage() failing (cold caches / unknown
// stage) also degrades to vanilla behavior (bank to current world). So the fix
// is never worse than today.
//
// Scope note (read side): the Crazy Cap SHOP reads the current-world purple
// balance too. Shops are normally reached with mCurWorldId already correct (the
// home stage / a proper flight), so once collection banks to the right kingdom
// the shop shows and spends the right balance. A shop entered directly through a
// shuffled cross-world entrance would still display the arrival kingdom's
// balance mid-visit (same stale-mCurWorldId class) — out of scope for this fix;
// see the handoff for the accept-vs-address decision.

#include "hk/hook/Trampoline.h"
#include "hk/types.h"

#include "game/System/GameDataFile.h"    // GameDataFile::mCurWorldId
#include "game/System/GameDataHolder.h"  // GameDataHolder::getGameDataFile()

#include "../ap/ApState.hpp"
#include "../game/CrossWorldLoad.hpp"    // currentStageWorldId()
#include "../game/KingdomUnlock.hpp"     // kingdomShortFromWorldId (log only)
#include "../util/Log.hpp"

namespace smoap::hooks {

namespace {

// GameDataHolderWriter is a single GameDataHolder* passed by value (x0) — the
// same ABI shim AddPayShineHook uses. We don't read it; orig needs the exact
// shape.
struct GameDataHolderWriterAbi {
    void* mData;
};

// Scoped correction of the playing GameDataFile::mCurWorldId to the current
// subarea's HOME world for exactly one collect call, restored on scope exit.
// Main-thread only (actor nerve exe), so the transient value is never observed
// elsewhere.
struct ScopedStageWorldFix {
    GameDataFile* file = nullptr;
    s32 saved = 0;
    bool active = false;

    explicit ScopedStageWorldFix(const char* tag) {
        void* holder = smoap::ap::ApState::instance().game_data_holder_cache.load(
            std::memory_order_relaxed);
        if (!holder) return;
        // The authoritative playing file — the exact object the collect path's
        // writer->getGameDataFile() resolves to (holder->mPlayingFile).
        file = static_cast<GameDataHolder*>(holder)->getGameDataFile();
        if (!file) return;

        const int stageWorld = smoap::game::currentStageWorldId();
        if (stageWorld < 0) return;            // caches cold / unknown -> vanilla
        saved = file->mCurWorldId;
        if (stageWorld == saved) return;       // already correct -> vanilla no-op

        file->mCurWorldId = static_cast<s32>(stageWorld);
        active = true;

        const char* fromK = smoap::game::kingdomShortFromWorldId(saved);
        const char* toK = smoap::game::kingdomShortFromWorldId(stageWorld);
        SMOAP_LOG_INFO("[purple-coin] %s redirect mCurWorldId %d(%s) -> %d(%s)",
                       tag, saved, fromK ? fromK : "?", stageWorld,
                       toK ? toK : "?");
    }

    ~ScopedStageWorldFix() {
        if (active) file->mCurWorldId = saved;
    }

    ScopedStageWorldFix(const ScopedStageWorldFix&) = delete;
    ScopedStageWorldFix& operator=(const ScopedStageWorldFix&) = delete;
};

// GameDataFunction::addCoinCollect(GameDataHolderWriter, const al::PlacementId*)
// — the BANK. Correct the world, then let orig key the per-world "got" store.
HkTrampoline<void, GameDataHolderWriterAbi, const void*> addCoinCollectHook =
    hk::hook::trampoline(
        [](GameDataHolderWriterAbi writer, const void* placementId) -> void {
            ScopedStageWorldFix fix("bank");
            addCoinCollectHook.orig(writer, placementId);
        });

// CoinCollectWatcher::countup(const al::LiveActor*) — the on-collect HUD popup.
// Correct the world so the popup reads the HOME kingdom's got/max (runs before
// the bank; see header).
HkTrampoline<void, void*, const void*> coinCountupHook =
    hk::hook::trampoline([](void* self, const void* actor) -> void {
        ScopedStageWorldFix fix("hud");
        coinCountupHook.orig(self, actor);
    });

}  // namespace

void installPurpleCoinAttributionHook() {
    SMOAP_LOG_INFO("installing PurpleCoinAttributionHook "
                   "(regional coins credit the subarea's home kingdom)");
    addCoinCollectHook.installAtSym<
        "_ZN16GameDataFunction14addCoinCollectE20GameDataHolderWriterPKN2al11PlacementIdE">();
    coinCountupHook.installAtSym<
        "_ZN18CoinCollectWatcher7countupEPKN2al9LiveActorE">();
}

}  // namespace smoap::hooks
