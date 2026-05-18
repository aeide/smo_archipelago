// Hook on GameDataFile::initializeData().
//
// M3: empty trampoline. M4 wires this to drop our session dedupe set and
// request a checked_replay from the bridge (which fires automatically on
// our next HELLO).

#include "lib.hpp"
#include "../ap/ApClient.hpp"
#include "../ap/ApState.hpp"
#include "../util/Log.hpp"
#include "HookSymbols.hpp"
#include "SoftInstall.hpp"

class GameDataFile;

namespace smoap::hooks {

namespace {
HOOK_DEFINE_TRAMPOLINE(SaveLoadHook) {
    static void Callback(GameDataFile* self) {
        auto& st = smoap::ap::ApState::instance();
        // Let AddHackDictionaryHook pass every addHackDictionary call
        // through during the rehydration pass. Otherwise the just-cleared
        // captures_unlocked bitset would block every entry as
        // initializeData re-populates the dictionary from save data.
        st.save_load_passthrough.store(true, std::memory_order_release);
        Orig(self);
        st.save_load_passthrough.store(false, std::memory_order_release);
        SMOAP_LOG_INFO("SaveLoadHook: clearing session state + requesting re-HELLO");
        // Reset frame-thread-only dedupe state. These are touched only from
        // the frame thread so no lock is needed.
        st.locations_checked.reset();
        st.captures_unlocked.reset();
        st.received_kingdom_mask = 0;
        st.goal_sent = false;
        st.death_pending_send.store(false, std::memory_order_release);
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
    }
};
}  // namespace

void installSaveLoadHook() {
    SMOAP_LOG_INFO("installing SaveLoadHook -> %s", smoap::sym::kGameDataFileInitializeData);
    softInstallAtSymbol<SaveLoadHook>(smoap::sym::kGameDataFileInitializeData);
}

}  // namespace smoap::hooks
