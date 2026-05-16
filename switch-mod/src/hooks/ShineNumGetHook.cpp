// Hook on GameDataFunction::getCurrentShineNum(GameDataHolderAccessor).
//
// SMO calls this to render the global moon counter (HUD top-left "x/N").
// We trampoline through orig() but DELIBERATELY DROP orig and return only
// our AP-credit total. Per the user's M6 design call: locally-collected
// moons should not give kingdom-counter credit; only AP-issued items
// should. Returning credit-only keeps `setGotShine`'s natural flag flip
// (so the shine list still shows the collected moon) but suppresses the
// counter bump that the flag would otherwise drive.
//
// orig is still logged so we can diagnose mismatches between SMO's natural
// counter and the AP credit total. The visual UX of "natural counter shows
// 0 after a local pickup" is intentional for M6; a dedicated AP HUD
// overlay lands in M8.

#include "lib.hpp"  // HOOK_DEFINE_TRAMPOLINE
#include "../ap/ApState.hpp"
#include "../util/Log.hpp"
#include "HookSymbols.hpp"
#include "SoftInstall.hpp"

// Minimal layout mirror — avoids pulling in lunakit-vendor's full
// GameDataHolderAccessor.h. Itanium ABI passes a single-pointer trivially-
// copyable class in x0, so this is calling-convention-compatible.
struct GameDataHolderAccessor {
    void* mData;
};

namespace smoap::hooks {

namespace {

int sumAllKingdomCredits() {
    int total = 0;
    auto& s = smoap::ap::ApState::instance();
    for (auto& a : s.ap_moons_kingdom) {
        total += a.load(std::memory_order_relaxed);
    }
    return total;
}

HOOK_DEFINE_TRAMPOLINE(ShineNumGetHook) {
    static int Callback(GameDataHolderAccessor accessor) {
        const int orig = Orig(accessor);  // called for diagnostics + side effects
        const int ap_total = sumAllKingdomCredits();

        // Throttle: log first few calls (proves the hook is firing at all)
        // and any time the returned value OR the orig-vs-ap delta changes
        // (catches local moon collections and AP credits). Per-frame HUD
        // calls otherwise stay silent.
        static int s_call_count = 0;
        static int s_last_returned = -1;
        static int s_last_orig = -1;
        const bool first_calls = (s_call_count < 3);
        const bool ret_changed = (ap_total != s_last_returned);
        const bool orig_changed = (orig != s_last_orig);
        if (first_calls || ret_changed || orig_changed) {
            SMOAP_LOG_INFO("[m6-hook] getCurrentShineNum: smo_natural=%d "
                           "ap=%d returned (call#%d%s%s)",
                           orig, ap_total,
                           s_call_count + 1,
                           ret_changed && !first_calls ? " ap-changed" : "",
                           orig_changed && !first_calls ? " natural-changed" : "");
        }
        ++s_call_count;
        s_last_returned = ap_total;
        s_last_orig = orig;
        return ap_total;
    }
};

}  // namespace

void installShineNumGetHook() {
    SMOAP_LOG_INFO("installing ShineNumGetHook -> %s",
                   smoap::sym::kGameDataFunctionGetCurrentShineNum);
    softInstallAtSymbol<ShineNumGetHook>(
        smoap::sym::kGameDataFunctionGetCurrentShineNum);
}

}  // namespace smoap::hooks
