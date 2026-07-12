// CrossWorldLoad — P5 cross-world stage-load fix (docs/plan-p5-cross-world-loads.md §1.5).
//
// The decoupled entrance remap breaks the vanilla invariant "a subarea always
// belongs to the current world": GameDataFunction::calcNextWorldId resolves
// the commit target by MAIN stage name only, so a remapped foreign-world
// target gets no world-resource swap and the destination world's assets
// stream into scene heaps sized for the origin — the FileLoadThread
// FrameHeap/ExpHeap aborts (PBP→Metro cold, Swinging Along the High-Rises).
//
// The 2026-07-09 walk settled the §1.5 lever question empirically: the
// [p5-nextworld] spikes fired ONLY on the Odyssey-flight path (calc at the
// commit, get during DemoChangeWorldStage) and stayed SILENT across every
// door commit — the plain changeNextStage path never consults a next-world
// read out-of-line, so writing GameDataFile::mNextWorldId (lever 1) has no
// reader and is dead. This module is lever 2: drive the world-resource swap
// ourselves.
//
// Two halves (dispatch lives in EntranceShuffleHook):
//   B1  — remapped cross-world commits whose FINAL target is a non-exempt
//         overworld HomeStage re-route through
//         tryChangeNextStageWithDemoWorldWarp (the proven native swap path;
//         flights into Metro are consistently clean). Implemented in
//         EntranceShuffleHook; this module only supplies the world resolution.
//   B2  — every other cross-world commit (foreign INTERIOR targets, plus the
//         Lost/Ruined exempt overworlds that must keep their plain
//         story-managed arrival) stays a plain commit and ARMS a pre-load
//         here: at the next HakoniwaSequence::destroySceneHeap (post-orig —
//         the old scene is dead, so the request's internal
//         tryDestroyWorldResource can't free memory a live scene still
//         references; exeLoadStage first-tick is the fallback trigger) we
//         call WorldResourceLoader::requestLoadWorldHomeStageResource for the
//         destination world. The stage load then races the async world load —
//         the known, accepted residual risk; the walk decides if the partial
//         mitigation is enough.
//
// World ids for arbitrary (subarea) stages come from WorldList::
// tryFindWorldIndexByStageName — the NON-main variant that resolves via each
// world's stageNames list — so no wire-format/slot_data change is needed.
// All symbols verified in the retail 1.0.0 dynsym 2026-07-09
// (scripts/check_nso_symbols.py); everything soft-degrades on a miss.

#pragma once

namespace smoap::game {

// Resolve symbols + install the destroySceneHeap/exeLoadStage fire triggers.
// Call from hkMain alongside installOdysseyRescueSymbols.
void installCrossWorldLoadHooks();

// Cache the HakoniwaSequence* (drawMainHook calls this every frame; the
// WorldResourceLoader lives at mResourceLoader on it).
void cacheHakoniwaSequence(const void* sequence);

// World id for ANY stage name (HomeStage, zone, or subarea) via
// WorldList::tryFindWorldIndexByStageName off the cached GameDataHolder.
// -1 when unresolvable (symbol missed / caches cold / unknown stage).
int resolveWorldIdForStage(const char* stage);

// The world whose resident set is CURRENTLY loaded
// (WorldResourceLoader::getLoadWorldId), falling back to the engine's
// current world id when the loader isn't reachable. -1 when unknown.
// NOTE: after a B2 pre-arm this deliberately tracks the loader, not
// GameDataFile's world bookkeeping — residency is what the crash class
// depends on.
int residentWorldId();

// Arm the one-shot B2 pre-load for dest_world_id (fires at the next
// destroySceneHeap/exeLoadStage, whichever comes first). dest_stage is for
// the log line only.
void armCrossWorldPreload(int dest_world_id, const char* dest_stage);

// Live per-world scenario via GameDataFile::getScenarioNo(worldId)
// (symbol already resolved as s_getScenarioNoByWorldId). -1 when the
// symbol or the game_data_file_cache is unavailable. Used by the T3
// Ruined pre/post-dragon story-managed check (P5 doc §6.4).
int scenarioNoForWorld(int world_id);

// §8 Swinging re-triage: 1 Hz (resident world, engine current world) trace,
// logged on change as [p5-reswatch]. Called from the drawMain pump next to
// runOdysseySoftlockSweep. Together with the [p5-worldreq] DESTROY /
// request(plain) ledger lines this decides whether the post-hold ExpHeap
// abort loses the resident set (silent destroy) or keeps it (per-stage
// fallback / heap sizing keyed on stale current-world bookkeeping).
void tickResidencyWatch();

}  // namespace smoap::game
