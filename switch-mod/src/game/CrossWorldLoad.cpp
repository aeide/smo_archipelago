// See CrossWorldLoad.hpp for design context.

#include "CrossWorldLoad.hpp"

#include <atomic>
#include <cstdint>
#include <cstring>

#include <hk/hook/Trampoline.h>
#include <hk/ro/RoUtil.h>
#include <hk/svc/api.h>
#include <hk/types.h>

// OdysseyHeaders — real layouts, static_assert-guarded (GameDataHolder 0x268,
// HakoniwaSequence 0x418). We only use inline getters / public fields off
// them; every out-of-line call below goes through hk::ro::lookupSymbol.
#include "game/Sequence/HakoniwaSequence.h"
#include "game/System/GameDataHolder.h"

#include "../ap/ApState.hpp"
#include "../hooks/HookSymbols.hpp"
#include "../util/Log.hpp"
#include "OdysseyRescue.hpp"  // tickChainKingdomListing (scene-init assert)

namespace smoap::game {

namespace {

// ── Resolved out-of-line game functions (soft; see HookSymbols.hpp) ─────────
using TryFindWorldIndexByStageNameFn = s32  (*)(const WorldList*, const char*);
using RequestLoadWorldHomeStageFn    = bool (*)(WorldResourceLoader*, s32, s32);
using IsEndLoadWorldResourceFn       = bool (*)(const WorldResourceLoader*);
using GetLoadWorldIdFn               = s32  (*)(const WorldResourceLoader*);
using GetScenarioNoByWorldIdFn       = s32  (*)(const void* /*GameDataFile*/, s32);
using GetCurrentWorldIdFn            = int  (*)(GameDataHolderAccessor);
using GetNextStageNameFn             = const char* (*)(GameDataHolderAccessor);
using TryDestroyWorldResourceFn      = void (*)(WorldResourceLoader*);

TryFindWorldIndexByStageNameFn s_tryFindWorldIndexByStageName = nullptr;
RequestLoadWorldHomeStageFn    s_requestLoadWorldHomeStage    = nullptr;
IsEndLoadWorldResourceFn       s_isEndLoadWorldResource       = nullptr;
GetLoadWorldIdFn               s_getLoadWorldId               = nullptr;
GetScenarioNoByWorldIdFn       s_getScenarioNoByWorldId       = nullptr;
GetNextStageNameFn             s_getNextStageName             = nullptr;
GetNextStageNameFn             s_getCurrentStageName          = nullptr;  // T-A
TryDestroyWorldResourceFn      s_tryDestroyWorldResource      = nullptr;  // §11

// HakoniwaSequence* — cached by drawMainHook every frame (and refreshed by
// the two trampolines below, which receive it as `this`). Frame-thread only;
// atomic for hygiene, same as the ApState pointer caches.
std::atomic<const void*> s_sequence{nullptr};

// One-shot pending pre-load. world id < 0 = nothing armed. The stage name is
// log-only (written before the world store on the same thread).
std::atomic<int> s_pending_world{-1};
char             s_pending_stage[64] = {0};

template <typename Fn>
bool resolveOne(Fn& slot, const char* mangled, const char* tag) {
    const ptr addr = hk::ro::lookupSymbol(mangled);
    if (addr == 0) {
        SMOAP_LOG_WARN("[p5-prearm] %s lookup FAILED", tag);
        slot = nullptr;
        return false;
    }
    slot = reinterpret_cast<Fn>(addr);
    SMOAP_LOG_INFO("[p5-prearm] %s @ 0x%lx", tag,
                   static_cast<unsigned long>(addr));
    return true;
}

WorldResourceLoader* resolveLoader() {
    const auto* seq = static_cast<const HakoniwaSequence*>(
        s_sequence.load(std::memory_order_relaxed));
    if (!seq) return nullptr;
    return seq->mResourceLoader;
}

// ── P5 §11: boot dual-heap teardown (2026-07-12 Sand crash) ─────────────────
//
// A session that BOOTS into the Cap prologue creates the twin resident set —
// requestLoadWorldHomeStageResource(0, 1) takes its special branch and builds
// mCapWorldHeap + mWaterfallWorldHeap so the whole prologue (Cap AND Cascade)
// runs without world loads (decomp WorldResourceLoader.cpp, read 2026-07-12).
// While mWaterfallWorldHeap exists the HomeStage request variant HARD-REFUSES
// on its first line — and the only vanilla teardown is the FIRST FLIGHT's
// world-change seam calling tryDestroyWorldResource() before its request. The
// chain topology never crosses that seam (door hops, the prologue crash
// cutscene, and the Odyssey->Cap divert are all changeNextStage commits), so
// on a start_at_cap_peace fresh-save session the dual-heap lived forever:
// Devon's Cascade -> City shop -> Sand walk had the pre-arm AND the per-tick
// backstop refused for 4.5 s, Sand's scene began init with the boot pair
// still resident, the engine's PLAIN request (no waterfall guard) then
// started the world load mid-scene-init, and the SZS decompressor aborted in
// ExpHeap::tryAlloc (sand-crash.txt).
//
// Fix: when a HomeStage request refuses at our seams and the eliminable
// guards don't explain it — no load in flight, a DIFFERENT world resident —
// the cause is the boot dual-heap (or the never-absent WorldList byml).
// Replicate the vanilla flight seam: tryDestroyWorldResource(), re-request.
// Safe here because both call sites run in the load phase with the old scene
// dead — exactly where vanilla does it.
//
// EXEMPTION — HEALTHY dual-heap ONLY (2026-07-13, cap-crash.txt): the dual-
// heap build calls requestLoadWorldResourceCommon(0), so its canonical
// mLoadWorldId is 0 (Cap). While it is intact, BOTH boot-pair worlds
// (Cap=0, Cascade=1) are served from mCapWorldHeap/mWaterfallWorldHeap, so a
// HomeStage request for either refuses on the `if (mWaterfallWorldHeap)
// return false` guard yet needs NO load — tearing it down would only force a
// pointless reload (this is the validated Cascade->Cap divert, which runs
// with resident==0). But the chain topology never hits the vanilla first-
// flight teardown, so the dual-heap gets ORPHANED, and once the engine's
// plain requestLoadWorldResource moves mLoadWorldId OFF Cap (resident != 0)
// while the waterfall heap is still set, the dual-heap is STALE: the boot-
// pair dest is no longer reliably resident, the HomeStage guard refuses
// forever, and the engine's next plain request loads the dest onto the stale
// heaps -> ExpHeap abort (cap-crash.txt: Cascade->Cap divert, dest=Cap(0),
// resident=1). So exempt ONLY resident==0 with a boot-pair dest; every other
// refusal (foreign world, OR stale boot pair with resident != 0) must tear
// down. `resident != world` already covers the redundant resident==0 &&
// dest==Cap(0) case, so the exemption's live effect is exactly "keep the
// healthy dual-heap serving Cascade" (resident==0, dest==Cascade(1)).
inline constexpr int kBootPairMaxWorldId = 1;  // Cap=0, Waterfall/Cascade=1
inline constexpr int kDualHeapResidentId = 0;  // dual-heap canonical mLoadWorldId (Cap)

bool requestWorldLoad(WorldResourceLoader* loader, int world, int scenario,
                      const char* tag) {
    bool ok = s_requestLoadWorldHomeStage(loader, world, scenario);
    if (!ok && s_tryDestroyWorldResource && s_isEndLoadWorldResource &&
        s_isEndLoadWorldResource(loader)) {
        const int resident = s_getLoadWorldId ? s_getLoadWorldId(loader) : -100;
        const bool healthyDualHeap =
            resident == kDualHeapResidentId && world <= kBootPairMaxWorldId;
        if (resident != world && !healthyDualHeap) {
            s_tryDestroyWorldResource(loader);
            ok = s_requestLoadWorldHomeStage(loader, world, scenario);
            SMOAP_LOG_INFO("[p5-prearm] %s boot dual-heap TEARDOWN "
                           "(resident_was=%d) -> re-request world=%d "
                           "scenario=%d -> %s",
                           tag, resident, world, scenario,
                           ok ? "LOAD STARTED" : "STILL REFUSED");
        }
    }
    return ok;
}

// Fire the armed pre-load, if any. `trigger` names the seam for the log.
void firePendingPreload(const char* trigger) {
    const int world = s_pending_world.exchange(-1, std::memory_order_relaxed);
    if (world < 0) return;

    WorldResourceLoader* loader = resolveLoader();
    if (!loader || !s_requestLoadWorldHomeStage) {
        SMOAP_LOG_WARN("[p5-prearm] fire@%s world=%d dest='%s' ABORTED "
                       "(loader=%p requestFn=%p) — plain load proceeds unarmed",
                       trigger, world, s_pending_stage,
                       static_cast<void*>(loader),
                       reinterpret_cast<void*>(s_requestLoadWorldHomeStage));
        return;
    }

    const int resident = s_getLoadWorldId ? s_getLoadWorldId(loader) : -100;

    // Per-world live scenario for the request's scenario argument. A wrong
    // value only costs scenario-variant resources (they fall back to
    // per-stage loads) — never the world resident set itself.
    int scenario = 1;
    if (s_getScenarioNoByWorldId) {
        void* file = smoap::ap::ApState::instance().game_data_file_cache.load(
            std::memory_order_relaxed);
        if (file) {
            const int sc = s_getScenarioNoByWorldId(file, world);
            if (sc >= 1) scenario = sc;
        }
    }

    // Self-guarding (decomp WorldResourceLoader.cpp, read verbatim
    // 2026-07-09): boot dual-heap alive / previous load unfinished / same
    // world already resident / WorldList byml missing all return false
    // without touching anything. On true it destroys the old resident set
    // (safe here: the old scene is already dead at both trigger seams) and
    // starts the async reload on the loader's own thread. The §11 wrapper
    // clears the boot dual-heap refusal (vanilla first-flight teardown).
    const bool ok = requestWorldLoad(loader, world, scenario, trigger);
    SMOAP_LOG_INFO("[p5-prearm] fire@%s world=%d scenario=%d dest='%s' "
                   "resident_was=%d -> %s",
                   trigger, world, scenario, s_pending_stage, resident,
                   ok ? "LOAD STARTED" : "refused (guard)");
}

// ── Fire triggers ────────────────────────────────────────────────────────────
//
// destroySceneHeap post-orig is the primary seam: the scene (and its heaps)
// are gone, the destination stage load hasn't started. exeLoadStage is the
// belt-and-braces fallback in case a transition path skips destroySceneHeap
// (pre-orig on its first tick per pending; the one-shot exchange makes the
// two triggers race-free). Both installAtPtr (soft) — a lookup miss only
// disables the trigger, logged at install.

HkTrampoline<void, HakoniwaSequence*, bool> destroySceneHeapHook =
    hk::hook::trampoline([](HakoniwaSequence* self, bool destroyResource) -> void {
        destroySceneHeapHook.orig(self, destroyResource);
        s_sequence.store(self, std::memory_order_relaxed);
        firePendingPreload("destroySceneHeap");
    });

// UNIVERSAL backstop (pre-orig, every load tick): if the pending stage's
// world differs from the loader's resident world, request the swap — no
// arming bookkeeping, so it also covers paths the commit-side arm can't see
// (returnPrevStage pops back to the entry-origin world after a pre-arm
// swapped residency, divert/detour rewrites, anything future). The request
// self-guards: same world resident / load already running / boot dual-heap
// all refuse without side effects, so calling every tick is free once the
// first tick started the load.
void universalCrossWorldCheck() {
    if (!s_getNextStageName || !s_requestLoadWorldHomeStage) return;
    void* holder = smoap::ap::ApState::instance().game_data_holder_cache.load(
        std::memory_order_relaxed);
    if (!holder) return;
    WorldResourceLoader* loader = resolveLoader();
    if (!loader || !s_getLoadWorldId) return;

    const char* next = s_getNextStageName(
        GameDataHolderAccessor{static_cast<GameDataHolder*>(holder)});
    const int next_world = resolveWorldIdForStage(next);
    if (next_world < 0) return;
    const int resident = s_getLoadWorldId(loader);
    if (next_world == resident) return;

    int scenario = 1;
    if (s_getScenarioNoByWorldId) {
        void* file = smoap::ap::ApState::instance().game_data_file_cache.load(
            std::memory_order_relaxed);
        if (file) {
            const int sc = s_getScenarioNoByWorldId(file, next_world);
            if (sc >= 1) scenario = sc;
        }
    }
    const bool ok = requestWorldLoad(loader, next_world, scenario, "backstop");
    // Rate-limit: this runs per load tick — only log transitions. A refusal
    // right after a successful start is the loader's own in-progress guard,
    // not a failure.
    static int s_last_world = -100;
    static bool s_last_ok = false;
    if (next_world != s_last_world || ok != s_last_ok) {
        s_last_world = next_world;
        s_last_ok = ok;
        SMOAP_LOG_INFO("[p5-prearm] backstop@exeLoadStage next='%s' world=%d "
                       "scenario=%d resident_was=%d -> %s",
                       next ? next : "(null)", next_world, scenario, resident,
                       ok ? "LOAD STARTED" : "refused (guard)");
    }
}

// P5 §6.1: a world-resource load running concurrently with the stage load
// races nn::g3d ResFile setup on the scene InitializeThread (both walked
// foreign-interior entries crashed). Block HERE, inside the exe body, until
// the loader is done — transparent to the nerve step counter (no ticks are
// skipped, first-step init still runs when orig finally executes). The
// loader's AsyncFunctorThread + the SZS decompressor threads do not need
// the main thread to progress. Timeout fails open to orig (the old crash
// risk, logged loudly).
constexpr int kHoldTimeoutMs = 30000;
void holdForWorldLoad() {
    if (!s_isEndLoadWorldResource) return;
    WorldResourceLoader* loader = resolveLoader();
    if (!loader || s_isEndLoadWorldResource(loader)) return;
    const int world = s_getLoadWorldId ? s_getLoadWorldId(loader) : -1;
    int waited_ms = 0;
    while (!s_isEndLoadWorldResource(loader) && waited_ms < kHoldTimeoutMs) {
        hk::svc::SleepThread(10'000'000LL);  // 10 ms
        waited_ms += 10;
    }
    const bool done = s_isEndLoadWorldResource(loader);
    if (done)
        SMOAP_LOG_INFO("[p5-hold] exeLoadStage held %d ms for world %d -> done",
                       waited_ms, world);
    else
        SMOAP_LOG_WARN("[p5-hold] exeLoadStage held %d ms for world %d -> "
                       "TIMEOUT (fail-open, crash risk)", waited_ms, world);
}

HkTrampoline<void, HakoniwaSequence*> exeLoadStageHook =
    hk::hook::trampoline([](HakoniwaSequence* self) -> void {
        s_sequence.store(self, std::memory_order_relaxed);
        firePendingPreload("exeLoadStage");
        universalCrossWorldCheck();
        // Chain-ship existence (2026-07-11): isExistHome is DERIVED —
        // isGameClear || (isActivateHome && isUnlockedCurrentWorld) — and the
        // Odyssey actor placement reads it during scene init inside orig's
        // ticks. Re-assert the chain-kingdom unlock force pre-orig on EVERY
        // load tick so a B1/chain arrival into a locked kingdom (alreadyGo
        // set at commit, unlocked never) has mIsUnlockWorld[dest]=true when
        // placement runs — the 1 Hz drawMain pump alone can lose that race.
        tickChainKingdomListing();
        // start_at_cap_peace bootstrap (2026-07-12): the ship-acquire
        // (activateHome + upHomeLevel + launchHome) normally fires only at the
        // changeNextStage commits into Cap/Cascade — a DIRECT load (save
        // sitting in Cascade, save/quit/reload) skips that seam entirely, so
        // the scene inits with the ship buried + deactivated, the boarding
        // door dead, and the Odyssey->Cap divert unreachable. Re-assert the
        // acquired save-state pre-orig on every load tick so placement reads
        // it (same reasoning as the listing re-assert above). True no-op once
        // the Odyssey is legitimately owned; gated on the seed's option.
        if (smoap::ap::ApState::instance().cap_peace_start.load(
                std::memory_order_relaxed))
            forceAcquireOdyssey("cap-peace-load");
        // Metro "day city" placement force (exit-into-festival fix). The
        // changeNextStage commit stashed the target scenario in ApState when
        // metroDayArrivalScenarioOverride fired (a non-flight arrival into
        // CityWorldHomeStage). The ChangeStageInfo write it made moves only the
        // scenario-LOGIC number; the visible layout is placement-gated on
        // GameDataFile::mScenarioNoPlacement (@0xb60), which the load recomputes
        // from GLOBAL story progress (-> festival scenario 7 on an advanced
        // save). We write that field HERE, pre-orig — the recompute has already
        // run by this seam (a post-orig field write at the commit "did NOT
        // take"; this is the same seam the chain-unlock + cap-peace re-asserts
        // use so placement reads them). One-shot: consume + clear the pending
        // target so it can't linger. mScenarioNoPlacement is a SINGLE shared
        // field, so we DROP the force (without writing) if the stage now loading
        // resolves to a kingdom OTHER than Metro — the flag is only ever set for
        // a Metro commit, but this guards a diverted/intervening load from being
        // mis-placed.
        {
            auto& st = smoap::ap::ApState::instance();
            const int pending =
                st.metro_day_placement_scenario.load(std::memory_order_relaxed);
            if (pending >= 0) {
                // Recomputed each call (NOT a static): resolveWorldIdForStage
                // returns -1 until the holder is primed, and a static would
                // latch that -1 forever.
                const int kMetroWorld =
                    resolveWorldIdForStage("CityWorldHomeStage");
                int stageWorld = -1;
                if (s_getCurrentStageName) {
                    void* holder = st.game_data_holder_cache.load(
                        std::memory_order_relaxed);
                    if (holder) {
                        const char* cur = s_getCurrentStageName(
                            GameDataHolderAccessor{
                                static_cast<GameDataHolder*>(holder)});
                        stageWorld = resolveWorldIdForStage(cur);
                    }
                }
                const bool wrongKingdom =
                    stageWorld >= 0 && kMetroWorld >= 0 &&
                    stageWorld != kMetroWorld;
                void* gdf =
                    st.game_data_file_cache.load(std::memory_order_relaxed);
                if (wrongKingdom) {
                    st.metro_day_placement_scenario.store(
                        -1, std::memory_order_relaxed);
                    SMOAP_LOG_INFO("[metro-day] exeLoadStage SKIP placement "
                                   "force (stageWorld=%d != Metro %d) — pending "
                                   "dropped", stageWorld, kMetroWorld);
                } else if (gdf) {
                    constexpr std::size_t kOffScenarioNoPlacement = 0xb60;
                    auto* p = reinterpret_cast<std::int32_t*>(
                        reinterpret_cast<std::uint8_t*>(gdf)
                        + kOffScenarioNoPlacement);
                    const std::int32_t before = *p;
                    if (before != pending) *p = pending;
                    SMOAP_LOG_INFO("[metro-day] exeLoadStage force Metro "
                                   "mScenarioNoPlacement %d -> %d "
                                   "(stageWorld=%d)", before, pending,
                                   stageWorld);
                    st.metro_day_placement_scenario.store(
                        -1, std::memory_order_relaxed);
                }
                // gdf null (cache not yet primed): leave pending for the next
                // load tick; it self-corrects (applied on a Metro load, dropped
                // on a confirmed non-Metro one).
            }
        }
        holdForWorldLoad();
        exeLoadStageHook.orig(self);
    });

// ── P5 §7 probe (2026-07-10 walk): the residency-CLOBBER ledger ─────────────
//
// The §6.6 walk left three facts only one theory fits: (a) B1 read the
// ORIGIN world as resident right after a pre-arm had loaded a foreign world
// (wooded-early-flight: resident 0 with Metro loaded); (b) B1 AND the
// backstop were silent on two cross-world overworld exits (PT-SS-return,
// cap-store) — both read getLoadWorldId, so silence means residency had
// reverted to the origin; (c) Swinging Along the High-Rises aborted ~7 s
// AFTER a completed hold, in ExpHeap, while STREAMING — §1.2's per-stage
// fallback, i.e. the Metro set was gone again post-load. Theory: the engine
// re-requests the world set for its OWN stale current world (never updated —
// calcNextWorldId can't see subarea targets, §1.3) sometime around scene
// init, destroying the pre-armed set. Small deltas (SwingSteel, shops)
// survive the fallback; the city-streaming PoleGrabCeil dies.
//
// This trampoline logs EVERY requestLoadWorldHomeStageResource call — ours
// (they arrive through the same patched entry) and the suspected engine
// clobber — with the pre-call resident id. One walk of the Swinging door
// decides the fix seam: an engine request for the ORIGIN world after our
// "LOAD STARTED" line is the clobber, timestamped.
HkTrampoline<bool, WorldResourceLoader*, s32, s32> requestLoadWorldHook =
    hk::hook::trampoline(
        [](WorldResourceLoader* loader, s32 world, s32 scenario) -> bool {
            const int prev = s_getLoadWorldId ? s_getLoadWorldId(loader) : -100;
            const bool ok = requestLoadWorldHook.orig(loader, world, scenario);
            static int s_log = 0;
            if (s_log < 300) {
                ++s_log;
                SMOAP_LOG_INFO("[p5-worldreq] request world=%d scenario=%d "
                               "(resident_was=%d) -> %s #%d",
                               world, scenario, prev,
                               ok ? "LOAD STARTED" : "refused/no-op", s_log);
            }
            return ok;
        });

// §8 re-triage (2026-07-11): the 07-10 Swinging walk's ledger showed NO
// engine request between our pre-arm completing and the ExpHeap abort — so
// if residency died it went through a writer the HomeStage-request ledger
// can't see. Two exist (decomp WorldResourceLoader.cpp/.h):
//   - tryDestroyWorldResource(): frees the resident heap, mLoadWorldId=-1.
//     Standalone engine call = the silent clobber, now timestamped.
//   - requestLoadWorldResource(s32): the SECOND load entry (plain variant,
//     no internal destroy) — also sets the resident world.
// Both get ledger lines under the same [p5-worldreq] tag. If NEITHER fires
// before the next Swinging crash, residency was intact and the abort is a
// per-stage-fallback / heap-sizing problem keyed on the engine's stale
// current-world bookkeeping, not a destroyed resident set.
HkTrampoline<void, WorldResourceLoader*> destroyWorldResourceHook =
    hk::hook::trampoline([](WorldResourceLoader* loader) -> void {
        const int prev = s_getLoadWorldId ? s_getLoadWorldId(loader) : -100;
        destroyWorldResourceHook.orig(loader);
        // prev<0 = no resident heap existed — the call was a no-op
        // (tryDestroyWorldResource only acts when mWorldResourceHeap is
        // live); skip those to keep the ledger signal-only.
        if (prev >= 0) {
            static int s_log = 0;
            if (s_log < 300) {
                ++s_log;
                SMOAP_LOG_INFO("[p5-worldreq] DESTROY resident_was=%d -> -1 #%d",
                               prev, s_log);
            }
        }
    });

// P5 §9.2 T-A — the residency-CLOBBER FIX (was the §8 plain-request probe).
//
// The engine issues this plain requestLoadWorldResource(currentWorld) at every
// scene entry against its OWN current-world bookkeeping (GameDataFile::
// mCurWorldId). A door commit into a foreign-world subarea never updates that
// field — only flights/demo warps do (decomp-confirmed: mCurWorldId's writer
// lives in the undecompiled GameDataFile::startStage and the [p5-reswatch]
// trace shows engineCurWorld stuck at the ORIGIN world across a door hop). So
// after a B2 pre-arm has loaded the destination world, this stale refresh
// re-points the loader back at the ORIGIN world and destroys the pre-armed set
// (the Swinging Along the High-Rises ExpHeap abort, §9.2).
//
// In vanilla the plain entry is ALWAYS a same-world refresh (arg == mCurWorldId
// == resident == the world of the stage we are in). The decoupled remap is the
// only thing that makes them diverge, so `world != resident` here is by
// construction the stale-bookkeeping artifact. Redirect it to the resident
// world IFF the stage we are actually standing in is already fully resident
// (`resolveWorldIdForStage(getCurrentStageName()) == resident`). That predicate
// is true ONLY in the clobber case: during a legitimate cross-world load the
// destination is not yet resident, so resident != stage_world and this cannot
// hijack a real world swap. The redirect keeps the plain request's scenario-
// resource refresh — for the CORRECT (resident) world instead of the stale one.
// T-B (write mCurWorldId at commit) was ruled out: the field's writer is
// invisible in the decomp, so the return-trip restoration T-B relies on is
// unproven; T-A is provably correct in both directions (§10).
HkTrampoline<bool, WorldResourceLoader*, s32> requestLoadWorldPlainHook =
    hk::hook::trampoline([](WorldResourceLoader* loader, s32 world) -> bool {
        const int resident = s_getLoadWorldId ? s_getLoadWorldId(loader) : -100;

        int  eff_world  = world;
        int  stage_world = -1;
        bool redirected = false;
        if (world != resident && resident >= 0 && s_getCurrentStageName) {
            void* holder =
                smoap::ap::ApState::instance().game_data_holder_cache.load(
                    std::memory_order_relaxed);
            if (holder) {
                const char* cur = s_getCurrentStageName(
                    GameDataHolderAccessor{static_cast<GameDataHolder*>(holder)});
                stage_world = resolveWorldIdForStage(cur);
                if (stage_world == resident) {
                    eff_world  = resident;
                    redirected = true;
                }
            }
        }

        const bool ok = requestLoadWorldPlainHook.orig(loader, eff_world);
        static int s_log = 0;
        if (s_log < 300) {
            ++s_log;
            if (redirected)
                SMOAP_LOG_INFO("[p5-worldreq] request(plain) REDIRECTED "
                               "stale=%d -> %d (resident_was=%d, stage_world=%d) "
                               "-> %s #%d",
                               world, eff_world, resident, stage_world,
                               ok ? "LOAD STARTED" : "refused/no-op", s_log);
            else
                SMOAP_LOG_INFO("[p5-worldreq] request(plain) world=%d "
                               "(resident_was=%d) -> %s #%d",
                               world, resident,
                               ok ? "LOAD STARTED" : "refused/no-op", s_log);
        }
        return ok;
    });

}  // namespace

void installCrossWorldLoadHooks() {
    resolveOne(s_tryFindWorldIndexByStageName,
               smoap::sym::kWorldListTryFindWorldIndexByStageName,
               "WorldList::tryFindWorldIndexByStageName");
    resolveOne(s_requestLoadWorldHomeStage,
               smoap::sym::kWorldResourceLoaderRequestLoadWorldHomeStageResource,
               "WorldResourceLoader::requestLoadWorldHomeStageResource");
    resolveOne(s_isEndLoadWorldResource,
               smoap::sym::kWorldResourceLoaderIsEndLoadWorldResource,
               "WorldResourceLoader::isEndLoadWorldResource");
    resolveOne(s_getLoadWorldId,
               smoap::sym::kWorldResourceLoaderGetLoadWorldId,
               "WorldResourceLoader::getLoadWorldId");
    resolveOne(s_getScenarioNoByWorldId,
               smoap::sym::kGameDataFileGetScenarioNoByWorldId,
               "GameDataFile::getScenarioNo(worldId)");
    resolveOne(s_getNextStageName,
               smoap::sym::kGameDataFunctionGetNextStageName,
               "GameDataFunction::getNextStageName");
    resolveOne(s_getCurrentStageName,
               smoap::sym::kGameDataFunctionGetCurrentStageName,
               "GameDataFunction::getCurrentStageName");  // T-A redirect
    // §11 teardown — same entry the destroy probe patches, so our own calls
    // land in the [p5-worldreq] DESTROY ledger too (wanted).
    resolveOne(s_tryDestroyWorldResource,
               smoap::sym::kWorldResourceLoaderTryDestroyWorldResource,
               "WorldResourceLoader::tryDestroyWorldResource");

    // §7 probe: patch the request entry so every caller (ours included —
    // s_requestLoadWorldHomeStage points at the same, now-patched, entry and
    // recurses harmlessly through orig) lands in the ledger above.
    const ptr reqAddr = hk::ro::lookupSymbol(
        smoap::sym::kWorldResourceLoaderRequestLoadWorldHomeStageResource);
    if (reqAddr) {
        requestLoadWorldHook.installAtPtr(reqAddr);
        SMOAP_LOG_INFO("[p5-worldreq] request probe @ 0x%lx",
                       static_cast<unsigned long>(reqAddr));
    } else {
        SMOAP_LOG_WARN("[p5-worldreq] request probe lookup FAILED (ledger off)");
    }

    // §8 probes — soft installs; a miss only silences that ledger line.
    const ptr destroyResAddr = hk::ro::lookupSymbol(
        smoap::sym::kWorldResourceLoaderTryDestroyWorldResource);
    if (destroyResAddr) {
        destroyWorldResourceHook.installAtPtr(destroyResAddr);
        SMOAP_LOG_INFO("[p5-worldreq] destroy probe @ 0x%lx",
                       static_cast<unsigned long>(destroyResAddr));
    } else {
        SMOAP_LOG_WARN("[p5-worldreq] destroy probe lookup FAILED");
    }
    const ptr plainReqAddr = hk::ro::lookupSymbol(
        smoap::sym::kWorldResourceLoaderRequestLoadWorldResource);
    if (plainReqAddr) {
        requestLoadWorldPlainHook.installAtPtr(plainReqAddr);
        SMOAP_LOG_INFO("[p5-worldreq] plain-request probe @ 0x%lx",
                       static_cast<unsigned long>(plainReqAddr));
    } else {
        SMOAP_LOG_WARN("[p5-worldreq] plain-request probe lookup FAILED");
    }

    const ptr destroyAddr =
        hk::ro::lookupSymbol(smoap::sym::kHakoniwaSequenceDestroySceneHeap);
    if (destroyAddr) {
        destroySceneHeapHook.installAtPtr(destroyAddr);
        SMOAP_LOG_INFO("[p5-prearm] destroySceneHeap trigger @ 0x%lx",
                       static_cast<unsigned long>(destroyAddr));
    } else {
        SMOAP_LOG_WARN("[p5-prearm] destroySceneHeap lookup FAILED "
                       "(exeLoadStage remains the only trigger)");
    }

    const ptr loadStageAddr =
        hk::ro::lookupSymbol(smoap::sym::kHakoniwaSequenceExeLoadStage);
    if (loadStageAddr) {
        exeLoadStageHook.installAtPtr(loadStageAddr);
        SMOAP_LOG_INFO("[p5-prearm] exeLoadStage trigger @ 0x%lx",
                       static_cast<unsigned long>(loadStageAddr));
    } else {
        SMOAP_LOG_WARN("[p5-prearm] exeLoadStage lookup FAILED "
                       "(destroySceneHeap remains the only trigger)");
    }
}

void cacheHakoniwaSequence(const void* sequence) {
    if (sequence) s_sequence.store(sequence, std::memory_order_relaxed);
}

int resolveWorldIdForStage(const char* stage) {
    if (!stage || !stage[0] || !s_tryFindWorldIndexByStageName) return -1;
    void* holder = smoap::ap::ApState::instance().game_data_holder_cache.load(
        std::memory_order_relaxed);
    if (!holder) return -1;
    const WorldList* list =
        static_cast<const GameDataHolder*>(holder)->getWorldList();
    if (!list) return -1;
    return s_tryFindWorldIndexByStageName(list, stage);
}

int currentStageWorldId() {
    if (!s_getCurrentStageName) return -1;
    void* holder = smoap::ap::ApState::instance().game_data_holder_cache.load(
        std::memory_order_relaxed);
    if (!holder) return -1;
    const char* cur = s_getCurrentStageName(
        GameDataHolderAccessor{static_cast<GameDataHolder*>(holder)});
    return resolveWorldIdForStage(cur);
}

int residentWorldId() {
    if (WorldResourceLoader* loader = resolveLoader()) {
        if (s_getLoadWorldId) {
            const int id = s_getLoadWorldId(loader);
            if (id >= 0) return id;
        }
    }
    // Loader unreachable (early boot): the engine's current world id is a
    // correct fallback — residency only diverges from it after OUR pre-arms,
    // by which point the loader is cached.
    auto& st = smoap::ap::ApState::instance();
    void* holder = st.game_data_holder_cache.load(std::memory_order_relaxed);
    if (holder && st.get_current_world_id_fn) {
        auto fn = reinterpret_cast<GetCurrentWorldIdFn>(st.get_current_world_id_fn);
        return fn(GameDataHolderAccessor{static_cast<GameDataHolder*>(holder)});
    }
    return -1;
}

void tickResidencyWatch() {
    // §8 companion to the [p5-worldreq] ledger: a 1 Hz (resident world,
    // engine current world) trace. The pair diverging is EXPECTED after a
    // pre-arm (that's the whole B2 point); what the Swinging walk needs is
    // whether resident FLIPS (destroy/reload) between arrival and the abort,
    // and what the engine thought its current world was the whole time.
    WorldResourceLoader* loader = resolveLoader();
    if (!loader || !s_getLoadWorldId) return;
    const int resident = s_getLoadWorldId(loader);

    int cur = -101;
    auto& st = smoap::ap::ApState::instance();
    void* holder = st.game_data_holder_cache.load(std::memory_order_relaxed);
    if (holder && st.get_current_world_id_fn) {
        auto fn = reinterpret_cast<GetCurrentWorldIdFn>(st.get_current_world_id_fn);
        cur = fn(GameDataHolderAccessor{static_cast<GameDataHolder*>(holder)});
    }

    static int s_last_resident = -102;
    static int s_last_cur      = -102;
    if (resident == s_last_resident && cur == s_last_cur) return;
    s_last_resident = resident;
    s_last_cur      = cur;
    static int s_log = 0;
    if (s_log < 200) {
        ++s_log;
        SMOAP_LOG_INFO("[p5-reswatch] resident=%d engineCurWorld=%d #%d",
                       resident, cur, s_log);
    }
}

int scenarioNoForWorld(int world_id) {
    if (world_id < 0 || !s_getScenarioNoByWorldId) return -1;
    void* file = smoap::ap::ApState::instance().game_data_file_cache.load(
        std::memory_order_relaxed);
    if (!file) return -1;
    return s_getScenarioNoByWorldId(file, world_id);
}

void armCrossWorldPreload(int dest_world_id, const char* dest_stage) {
    if (dest_world_id < 0) return;
    std::strncpy(s_pending_stage, dest_stage ? dest_stage : "?",
                 sizeof(s_pending_stage) - 1);
    s_pending_stage[sizeof(s_pending_stage) - 1] = '\0';
    s_pending_world.store(dest_world_id, std::memory_order_relaxed);
    SMOAP_LOG_INFO("[p5-prearm] ARMED world=%d dest='%s' (resident=%d) — fires "
                   "at the next destroySceneHeap/exeLoadStage",
                   dest_world_id, s_pending_stage, residentWorldId());
}

}  // namespace smoap::game
