// Hook on GameDataFile::initializeData(). Clears session dedupe state and
// requests a fresh HELLO replay from the bridge. Debounces a burst of
// initializeData calls that SMO emits for a single save-load event.

#include "hk/hook/Trampoline.h"
#include "hk/ro/RoUtil.h"
#include "hk/types.h"

#include <atomic>
#include <cstdint>

#include "../ap/ApClient.hpp"
#include "../ap/ApState.hpp"
#include "../ui/CappyMessenger.hpp"
#include "../util/Log.hpp"

class GameDataFile;

namespace smoap::hooks {

namespace {

std::atomic<std::uint64_t> g_fire_counter{0};
std::atomic<std::int64_t>  g_last_fire_ms{0};
std::atomic<std::int64_t>  g_last_side_effect_ms{0};
constexpr std::int64_t kSaveLoadDebounceMs = 500;

// BISECT phase 10: phase 9 (bare .orig) was stable -> lambda body code is
// the trigger. Restore PRE-.orig() code only; leave POST-.orig() out.
// Survives -> post-orig code is the culprit (state resets, requestRehello,
// CappyMessenger access). Crashes -> pre-orig code (atomics on file
// statics, ApState::instance() accessor, SMOAP_LOG_INFO buffer).
HkTrampoline<void, GameDataFile*> saveLoadHook =
    hk::hook::trampoline([](GameDataFile* self) -> void {
        const std::uint64_t fire_n =
            g_fire_counter.fetch_add(1, std::memory_order_relaxed) + 1;
        const std::int64_t now_ms = smoap::ap::ApState::nowMs();
        const std::int64_t prev_ms =
            g_last_fire_ms.exchange(now_ms, std::memory_order_relaxed);
        const std::int64_t delta_ms = prev_ms ? (now_ms - prev_ms) : -1;

        SMOAP_LOG_INFO("[saveload-diag] fire#%llu dt=%lldms self=%p",
                       static_cast<unsigned long long>(fire_n),
                       static_cast<long long>(delta_ms),
                       self);

        auto& st = smoap::ap::ApState::instance();
        st.save_load_passthrough.store(true, std::memory_order_release);
        saveLoadHook.orig(self);
        st.save_load_passthrough.store(false, std::memory_order_release);
    });

}  // namespace

void installSaveLoadHook() {
    SMOAP_LOG_INFO("installing SaveLoadHook -> GameDataFile::initializeData");
    saveLoadHook.installAtSym<"_ZN12GameDataFile14initializeDataEv">();
}

}  // namespace smoap::hooks
