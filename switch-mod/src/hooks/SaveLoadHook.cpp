// Hook on GameDataFile::initializeData().
//
// M3: empty trampoline. M4 wires this to drop our session dedupe set and
// request a checked_replay from the bridge (which fires automatically on
// our next HELLO).

#include <atomic>
#include <cstdint>

#include "lib.hpp"
#include "lib/util/modules.hpp"
#include "nn/os.h"
#include "nn/os/os_tick.hpp"
#include "nn/time/time_timespan.hpp"
#include "../ap/ApClient.hpp"
#include "../ap/ApProtocol.hpp"  // kCheckFieldCap
#include "../ap/ApState.hpp"
#include "../ap/shine_table.h"
#include "../game/KingdomUnlock.hpp"
#include "../ui/CappyMessenger.hpp"
#include "../util/Log.hpp"
#include "HookSymbols.hpp"
#include "SoftInstall.hpp"

#include <cstring>

class GameDataFile;

namespace smoap::hooks {

namespace {

// Diagnostic counters for the "initializeData fires N times in 200 ms"
// mystery (Goomba-spam investigation, 2026-05-18). Frame thread only —
// no atomic ordering needed beyond avoiding tear on the u64.
std::atomic<std::uint64_t> g_fire_counter{0};
std::atomic<std::int64_t> g_last_fire_ms{0};
// Debounce gate. SMO calls initializeData on ~5 distinct GameDataFile
// objects, each 2-3 times, within ~200 ms for a single user save-load
// action (confirmed by `self` pointer diversity in [saveload-diag] logs).
// Without a debounce, every fire triggers a connection cycle + full item
// replay — and the rapid dict rebuild/teardown races the replay drain,
// letting the first 1-2 capture bubbles leak before the capture-already-
// in-dict gate catches subsequent replays. Side effects run on the first
// fire of a burst; subsequent fires within kSaveLoadDebounceMs still run
// Orig (the game needs it) but skip reset + requestRehello.
std::atomic<std::int64_t> g_last_side_effect_ms{0};
constexpr std::int64_t kSaveLoadDebounceMs = 500;

std::int64_t monotonic_ms() {
    const auto ts = nn::os::ConvertToTimeSpan(nn::os::GetSystemTick());
    return static_cast<std::int64_t>(ts.GetMilliSeconds());
}

// Talkatoo% Phase 2 — pre-mark non-AP moons so the world only contains
// AP-pool locations. SKELETON, not wired yet — runs the apworld×shine_map
// intersection (kShineTable) against the per-kingdom AP pool and counts
// how many moons WOULD be pre-marked. The actual setGotShine() call is
// TODO: GameDataFile::setGotShine takes `const ShineInfo*`, not a
// uid — we'd need to either (a) discover a setGotShineByUid overload (run
// scripts/check_nso_symbols.py against an "_ZN12GameDataFile11setGotShineEi"
// candidate) or (b) construct a ShineInfo on the stack from the
// HintInfo at mShineHintList[i] and pass it. Both are next-session work.
//
// Logging-only today means: enabling Talkatoo% on the user side doesn't
// hide non-AP moons yet. The world still contains every moon. Phase 3's
// speech-hook gives the AP feel; Phase 2's pre-marking is the polish.
void premarkNonApMoonsIfTalkatooMode() {
    auto& st = smoap::ap::ApState::instance();
    if (!st.talkatoo_mode.load(std::memory_order_acquire)) return;

    // Snapshot every kingdom's AP-pool once so we can do membership checks
    // by linear search. Stack-allocated to keep allocators out — fixed
    // upper bound from the wire-cap constants in ApProtocol.hpp.
    using Pool = smoap::ap::ApState::TalkatooKingdomPool;
    constexpr std::size_t kK = smoap::ap::ApState::kTalkatooKingdomCount;
    static char pool[kK][Pool::kMaxMoons][smoap::ap::kCheckFieldCap];
    static std::size_t pool_count[kK];
    for (std::size_t b = 0; b < kK; ++b) {
        pool_count[b] = st.snapshotTalkatooKingdom(
            static_cast<int>(b), pool[b], Pool::kMaxMoons);
    }

    // Walk the static shine_table built from apworld locations × shine_map.
    // For each moon NOT in its kingdom's pool, count it (real setGotShine
    // call is TODO — see file header comment).
    std::size_t would_premark = 0;
    std::size_t hits = 0;
    for (const auto& row : smoap::game::kShineTable) {
        // AP-form kingdom → bit. Translation is identity for everything
        // except "Bowser's" → bit 12 (see KingdomUnlock.cpp).
        const std::uint8_t bit = smoap::game::kingdomBitFor(row.kingdom.data());
        if (bit >= kK) continue;  // unknown kingdom — leave it alone
        bool in_pool = false;
        for (std::size_t i = 0; i < pool_count[bit]; ++i) {
            if (std::strcmp(pool[bit][i], row.shine_id.data()) == 0) {
                in_pool = true; break;
            }
        }
        if (in_pool) {
            ++hits;
        } else {
            ++would_premark;
            // TODO: actually mark `row.shine_uid` collected once we have
            // a write-side primitive. Candidates (need symbol discovery):
            //   - GameDataFile::setGotShineByUid(int)        — unverified
            //   - GameDataFile::setGotShine(const ShineInfo*) with a
            //       hand-constructed ShineInfo borrowed from the
            //       matching mShineHintList entry
            //   - Direct memory write into the GameDataFile shine flags
            //       table (offset unknown).
        }
    }
    SMOAP_LOG_INFO("[talkatoo-premark] pool-hit=%zu would-premark=%zu (NOT WIRED — see file header)",
                   hits, would_premark);
}

HOOK_DEFINE_TRAMPOLINE(SaveLoadHook) {
    // Capture both return addresses BEFORE any other work so the compiler
    // can't reshuffle them. ret0 is the trampoline's bl-Callback site
    // (will land in our subsdk9 region — useful as a sanity check). ret1
    // tries to walk one frame up; on aarch64 with -fno-omit-frame-pointer
    // this lands at the trampoline's caller, which is SMO's caller of
    // initializeData. May return null if the trampoline doesn't establish
    // a proper frame — we log "ret1=NULL" rather than crashing.
    static void Callback(GameDataFile* self) {
        const auto ret0 = reinterpret_cast<std::uintptr_t>(__builtin_return_address(0));
        const auto ret1 = reinterpret_cast<std::uintptr_t>(__builtin_return_address(1));
        const std::uintptr_t main_base = exl::util::modules::GetTargetStart();
        // Compute offsets relative to main.nso base for stable IDs across
        // boots (ASLR shifts the absolute address). A return addr that
        // falls OUTSIDE main.nso's range (the subsdk9 trampoline does)
        // shows up as a "huge" offset — we report it as raw delta with a
        // marker so it's still useful.
        auto fmt_off = [main_base](std::uintptr_t ra) -> std::int64_t {
            return ra ? static_cast<std::int64_t>(ra - main_base) : 0;
        };

        const std::uint64_t fire_n = g_fire_counter.fetch_add(1, std::memory_order_relaxed) + 1;
        const std::int64_t now_ms = monotonic_ms();
        const std::int64_t prev_ms = g_last_fire_ms.exchange(now_ms, std::memory_order_relaxed);
        const std::int64_t delta_ms = prev_ms ? (now_ms - prev_ms) : -1;

        SMOAP_LOG_INFO("[saveload-diag] fire#%llu dt=%lldms self=%p "
                       "ret0_off=0x%llx ret1_off=0x%llx (main_base=0x%llx)",
                       static_cast<unsigned long long>(fire_n),
                       static_cast<long long>(delta_ms),
                       self,
                       static_cast<long long>(fmt_off(ret0)),
                       static_cast<long long>(fmt_off(ret1)),
                       static_cast<unsigned long long>(main_base));

        auto& st = smoap::ap::ApState::instance();
        // Let AddHackDictionaryHook pass every addHackDictionary call
        // through during the rehydration pass. Otherwise our capture-gate
        // filter would block save-restored entries for any cap whose
        // AP-grant bit isn't currently set in captures_unlocked. Must run
        // around EVERY Orig call (even debounced ones) because the game
        // re-populates the dictionary on every initializeData regardless
        // of our side-effect gating.
        st.save_load_passthrough.store(true, std::memory_order_release);
        Orig(self);
        st.save_load_passthrough.store(false, std::memory_order_release);

        // Debounce the reactive side effects. The first fire of a burst
        // does the full reset + rehello; subsequent fires within
        // kSaveLoadDebounceMs only run Orig above and return early.
        const std::int64_t prev_side_effect = g_last_side_effect_ms.load(std::memory_order_relaxed);
        if (prev_side_effect != 0 && (now_ms - prev_side_effect) < kSaveLoadDebounceMs) {
            SMOAP_LOG_INFO("[saveload-diag] fire#%llu debounced "
                           "(last side-effect %lldms ago, window=%lldms)",
                           static_cast<unsigned long long>(fire_n),
                           static_cast<long long>(now_ms - prev_side_effect),
                           static_cast<long long>(kSaveLoadDebounceMs));
            return;
        }
        g_last_side_effect_ms.store(now_ms, std::memory_order_relaxed);

        SMOAP_LOG_INFO("SaveLoadHook: clearing session state + requesting re-HELLO");
        // Reset frame-thread-only dedupe state. These are touched only from
        // the frame thread so no lock is needed.
        st.locations_checked.reset();
        st.captures_unlocked.reset();
        st.goal_sent = false;
        st.death_pending_send.store(false, std::memory_order_release);
        // Clear the "Cappy has dispatched" latch so the post-HELLO snapshot
        // gate re-arms. The deferSaveLoadStatusBubble() call below enqueues a
        // fresh status bubble whose successful dispatch will re-flip the
        // latch — at which point we know scene + director are alive and the
        // shine bitmap is safe to enumerate. Without this clear, a save load
        // from inside live gameplay would let sendSnapshot fire immediately
        // (latch still true from a prior dispatch), racing the new save's
        // deserialization.
        smoap::ui::CappyMessenger::instance().clearDispatchLatch();
        // Drain any pending capture-grant retries left over from before this
        // save load. After captures_unlocked is wiped above, AddHackDictionary
        // Hook would block any flushPendingCaptureGrants retry whose bit
        // hasn't been re-set yet — the dict write gets silently swallowed
        // while the deferred Cappy bubble still fires, recreating the
        // original "Cappy bubble without compendium entry" symptom in a small
        // race window between this reset and the bridge re-HELLO replay. The
        // bridge re-HELLO is the canonical re-population path; let it do its
        // job cleanly. Both producer (applyOnFrame) and consumer
        // (flushPendingCaptureGrants) of this queue run on the frame thread,
        // same as this hook, so draining via popDiscard is race-free.
        std::size_t drained = 0;
        while (st.pending_capture_grant.peekRef() != nullptr) {
            st.pending_capture_grant.popDiscard();
            ++drained;
        }
        if (drained > 0) {
            SMOAP_LOG_INFO("SaveLoadHook: dropped %zu pending capture grant(s) "
                           "(bridge re-HELLO will re-send them)",
                           drained);
        }
        // Latch save_was_loaded so the upcoming re-HELLO's sendSnapshot
        // enumerates against actually-loaded GameDataHolder state instead of
        // whatever the title screen had cached for save-preview rendering.
        // Release ordering pairs with the worker thread's acquire load in
        // threadMain before sendSnapshot. Once set, stays set for the rest
        // of the process — a subsequent New Game / Load Save still triggers
        // re-HELLO via the requestRehello call below.
        st.save_was_loaded.store(true, std::memory_order_release);
        // Tell the socket worker to close-and-reopen so the bridge's HELLO
        // replay re-syncs both sides. The actual socket close happens on the
        // worker thread; we just set the atomic here.
        smoap::ap::ApClient::instance().requestRehello();

        // Talkatoo% pre-mark pass. No-op when mode is off; today even when
        // mode is on this just logs the count of moons that would be pre-
        // marked — see the function header for the missing write primitive.
        premarkNonApMoonsIfTalkatooMode();

        // Arm a "current connection status" Cappy bubble on every save load
        // (covers both New Game and Continue). On New Game the messenger holds
        // it until the Cap Kingdom intro releases the CapMessage director
        // (kSceneSettleFrames + retry budget), so it surfaces right when Cappy
        // first becomes able to talk to Mario — answering the "did my AP
        // connection survive?" question the player otherwise has to guess at.
        // On Continue the bubble fires within seconds of the load completing.
        //
        // Deferred (not synchronous): we just requested a re-HELLO above, and
        // SMOClient typically takes ~1s after our HELLO to finish dialing AP.
        // Reading ApState::conn here would announce "Not connected" for the
        // common "AP is about to be ready" case — and the matching natural
        // ap_state(ready) bubble would be suppressed by the rehello window we
        // just armed, leaving the player with the wrong status until next save
        // load. Instead, deferSaveLoadStatusBubble() arms a worker-thread
        // deadline that fires the right text the moment ap_state=ready arrives
        // (fast path), or falls back to "Not connected" once the wait expires.
        smoap::ap::ApClient::instance().deferSaveLoadStatusBubble();
    }
};
}  // namespace

void installSaveLoadHook() {
    SMOAP_LOG_INFO("installing SaveLoadHook -> %s", smoap::sym::kGameDataFileInitializeData);
    softInstallAtSymbol<SaveLoadHook>(smoap::sym::kGameDataFileInitializeData);
}

}  // namespace smoap::hooks
