// Hook on GameDataFunction::getGotShineNum(GameDataHolderAccessor, s32 worldId).
//
// Called by SMO for per-kingdom moon counts (kingdom menu, shine list, possibly
// some progression gates). We trampoline through orig() and DELIBERATELY DROP
// orig — only the AP-credit count for the matching kingdom is returned. See
// ShineNumGetHook.cpp for the design rationale (AP-only counting).
//
// Important M6 unknown: SMO's worldId space vs our kingdomBitFor() index.
// kKingdoms[] in KingdomUnlock.cpp is ordered "Cap, Cascade, Sand, Wooded,
// Lake, Cloud, Lost, Metro, Snow, Seaside, Luncheon, Ruined, Bowser, Moon,
// Mushroom, Dark Side, Darker Side". OdysseyDecomp suggests SMO's internal
// worldId follows the same play order. If playtest reveals a mismatch, the
// mapping table below is the surgical fix point.
//
// Second M6 unknown: this hook never fired during the first phase-A playtest.
// SMO's natural per-kingdom counter (Cascade "5/19" type stats) appears to
// read shine flags directly rather than going through getGotShineNum. If
// further playtest confirms the hook stays silent, the per-kingdom counter
// substitution simply does nothing — kingdom progression then has to be
// gated via phase B's `unlockWorld` path instead.

#include "lib.hpp"
#include "../ap/ApState.hpp"
#include "../game/KingdomUnlock.hpp"
#include "../util/Log.hpp"
#include "HookSymbols.hpp"
#include "SoftInstall.hpp"

struct GameDataHolderAccessor {
    void* mData;
};

namespace smoap::hooks {

namespace {

// Map SMO's internal worldId to our kKingdoms bit index. M6 phase A assumes
// identity; phase A playtest logs the mapping so we catch divergence.
inline int smoWorldIdToOurBit(int world_id) {
    if (world_id < 0 || world_id >= 17) return -1;
    return world_id;
}

HOOK_DEFINE_TRAMPOLINE(ShineNumByWorldGetHook) {
    static int Callback(GameDataHolderAccessor accessor, int world_id) {
        const int orig = Orig(accessor, world_id);  // diagnostic + side effects
        const int bit = smoWorldIdToOurBit(world_id);
        int credit = 0;
        auto& s = smoap::ap::ApState::instance();
        if (bit >= 0 && bit < 17) {
            credit = s.ap_moons_kingdom[bit].load(std::memory_order_relaxed);
        }

        // Throttle: first 6 calls (we expect ~17 distinct world_ids being
        // queried at menu open, want at least a few) plus any change on
        // either side (so we catch local moon collects via orig AND AP
        // credit applications via credit).
        static int s_call_count = 0;
        static int s_last_returned[17] = {};
        static int s_last_orig[17] = {};
        static bool s_inited = false;
        if (!s_inited) {
            for (int i = 0; i < 17; ++i) { s_last_returned[i] = -1; s_last_orig[i] = -1; }
            s_inited = true;
        }
        const bool first_calls = (s_call_count < 6);
        const bool valid_bit = (bit >= 0 && bit < 17);
        const bool ret_changed = valid_bit && (credit != s_last_returned[bit]);
        const bool orig_changed = valid_bit && (orig != s_last_orig[bit]);
        if (first_calls || ret_changed || orig_changed) {
            const char* kname = (bit >= 0 && bit < 17)
                ? smoap::game::kingdomForBit(static_cast<std::uint8_t>(bit))
                : "<oob>";
            SMOAP_LOG_INFO("[m6-hook] getGotShineNum: worldId=%d (our "
                           "bit=%d, name=%s) smo_natural=%d credit=%d "
                           "returned (call#%d%s%s)",
                           world_id, bit, kname, orig, credit,
                           s_call_count + 1,
                           ret_changed && !first_calls ? " ap-changed" : "",
                           orig_changed && !first_calls ? " natural-changed" : "");
        }
        ++s_call_count;
        if (valid_bit) { s_last_returned[bit] = credit; s_last_orig[bit] = orig; }
        return credit;
    }
};

}  // namespace

void installShineNumByWorldGetHook() {
    SMOAP_LOG_INFO("installing ShineNumByWorldGetHook -> %s",
                   smoap::sym::kGameDataFunctionGetGotShineNum);
    softInstallAtSymbol<ShineNumByWorldGetHook>(
        smoap::sym::kGameDataFunctionGetGotShineNum);
}

}  // namespace smoap::hooks
