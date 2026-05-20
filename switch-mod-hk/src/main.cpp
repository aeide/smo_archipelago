// Spicy Meatball Overdrive — Hakkun edition entry point.
//
// Phase 3b in progress: installing trampoline hooks incrementally. Each
// installXxx call below pulls a HkTrampoline + lambda definition from a
// hooks/*.cpp into the link (gc-sections drops uninstalled trampolines, so
// an installAtSym call here is what keeps the hook live).

#include "util/Log.hpp"

namespace smoap::hooks {
void installScenarioFlagHook();
}  // namespace smoap::hooks

extern "C" void hkMain() {
    SMOAP_LOG_INFO("=== hkMain START ===");
    smoap::hooks::installScenarioFlagHook();
    SMOAP_LOG_INFO("=== hkMain END ===");
}
