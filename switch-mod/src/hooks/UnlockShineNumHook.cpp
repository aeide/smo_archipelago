// Hooks on GameDataFunction::findUnlockShineNum +
// GameDataFunction::findUnlockShineNumByWorldId.
//
// These are the game's "how many moons does the Odyssey need to leave this
// kingdom" reads (header: OdysseyHeaders game/System/GameDataFunction.h;
// both wrap GameDataHolder::findUnlockShineNum(bool* isCountTotal, s32)).
// The world-map UI's required-count display and the Odyssey launch check
// route through them, so overriding the return here is the single lie that
// keeps the in-game gate consistent with the rolled AP logic.
//
// randomize_kingdom_gates: the bridge ships rolled thresholds in a
// kingdom_gates message (full-overwrite -> ApState::kingdom_gate[bit],
// -1 = vanilla). Both trampolines call Orig first (preserves the
// isGameClear/isCountTotal out-param), then substitute the rolled value
// when one is present for the resolved kingdom. Bridge offline or slot
// still -1 -> vanilla value passes through untouched.

#include "hk/hook/Trampoline.h"
#include "hk/types.h"

#include "../ap/ApState.hpp"
#include "../game/KingdomUnlock.hpp"
#include "../util/Log.hpp"

#include <cstdint>

struct GameDataHolderAccessor {
    void* mData;
};

namespace smoap::hooks {

namespace {

using GetCurrentWorldIdNoDevelopFn = int (*)(GameDataHolderAccessor);

// Same plumbing as ShineNumGetHook/AddPayShineHook: resolve the kingdom
// Mario is currently in via the cached GameDataHolder.
std::uint8_t resolveCurrentKingdomBit() {
    auto& s = smoap::ap::ApState::instance();
    void* holder = s.game_data_holder_cache.load(std::memory_order_relaxed);
    if (!holder || !s.get_current_world_id_fn) return 0xff;
    auto fn = reinterpret_cast<GetCurrentWorldIdNoDevelopFn>(s.get_current_world_id_fn);
    GameDataHolderAccessor acc{holder};
    return smoap::game::kingdomBitForWorldId(fn(acc));
}

int rolledGateForBit(std::uint8_t bit) {
    if (bit >= 17) return -1;
    return smoap::ap::ApState::instance().kingdom_gate[bit].load(
        std::memory_order_relaxed);
}

void logSubstitution(const char* which, std::uint8_t bit, int orig, int rolled) {
    // Rate-limit: only log on change — these reads fire per-frame while the
    // world map / launch UI is open.
    static std::uint8_t s_last_bit = 0xff;
    static int s_last_rolled = -2;
    if (bit != s_last_bit || rolled != s_last_rolled) {
        SMOAP_LOG_INFO("[kingdom-gates] %s: kingdom=%s(bit=%u) vanilla=%d -> rolled=%d",
                       which,
                       bit < 17 ? smoap::game::kingdomForBit(bit) : "<unknown>",
                       bit, orig, rolled);
        s_last_bit = bit;
        s_last_rolled = rolled;
    }
}

HkTrampoline<int, bool*, GameDataHolderAccessor> unlockShineNumHook =
    hk::hook::trampoline([](bool* is_game_clear,
                            GameDataHolderAccessor accessor) -> int {
        const int orig = unlockShineNumHook.orig(is_game_clear, accessor);
        const std::uint8_t bit = resolveCurrentKingdomBit();
        const int rolled = rolledGateForBit(bit);
        if (rolled < 0) return orig;
        logSubstitution("findUnlockShineNum", bit, orig, rolled);
        return rolled;
    });

HkTrampoline<int, bool*, GameDataHolderAccessor, int> unlockShineNumByWorldIdHook =
    hk::hook::trampoline([](bool* is_game_clear,
                            GameDataHolderAccessor accessor,
                            int world_id) -> int {
        const int orig = unlockShineNumByWorldIdHook.orig(
            is_game_clear, accessor, world_id);
        const std::uint8_t bit = smoap::game::kingdomBitForWorldId(world_id);
        const int rolled = rolledGateForBit(bit);
        if (rolled < 0) return orig;
        logSubstitution("findUnlockShineNumByWorldId", bit, orig, rolled);
        return rolled;
    });

}  // namespace

void installUnlockShineNumHook() {
    SMOAP_LOG_INFO("installing UnlockShineNumHook -> "
                   "GameDataFunction::findUnlockShineNum");
    unlockShineNumHook.installAtSym<
        "_ZN16GameDataFunction18findUnlockShineNumEPb22GameDataHolderAccessor">();
}

void installUnlockShineNumByWorldIdHook() {
    SMOAP_LOG_INFO("installing UnlockShineNumByWorldIdHook -> "
                   "GameDataFunction::findUnlockShineNumByWorldId");
    unlockShineNumByWorldIdHook.installAtSym<
        "_ZN16GameDataFunction27findUnlockShineNumByWorldIdEPb22GameDataHolderAccessori">();
}

}  // namespace smoap::hooks
