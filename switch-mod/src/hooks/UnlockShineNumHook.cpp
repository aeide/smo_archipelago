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
#include "hk/ro/RoUtil.h"
#include "hk/types.h"

#include "../ap/ApState.hpp"
#include "../game/KingdomUnlock.hpp"
#include "../util/Log.hpp"
#include "HookSymbols.hpp"

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

// SMO's two world-map detour pairs are FREE DETOURS (see
// docs/v3-feasibility/future-feasibility-lake-wooded-free-detour.md): after the
// bifurcation the player may fly the siblings in either order, and the Odyssey
// must be launchable at 0 moons so the onward flight opens the instant Mario
// arrives — rather than after collecting that kingdom's leave-fuel.
//   - Post-Sand:  Lake <-> Wooded  (exit into Cloud)
//   - Post-Metro: Snow <-> Seaside (exit into Luncheon)
//
// The takeoff gate is getPayShineNum(cur) >= findUnlockShineNum(cur), reading
// the CURRENT-WORLD findUnlockShineNum out-of-line — so forcing that to 0 for
// these four kingdoms opens the crossing (proven in-game, iterations 2-4).
// Trade-off accepted by Devon: the in-kingdom takeoff gauge reads the same
// current-world value, so it shows 0/"full"; the world-map GLOBE per-kingdom
// label reads the by-world variant (left at the rolled value) and still shows
// the true threshold. The "finish the detour before the exit" enforcement lives
// solely in the combined exit gate (evaluateDetourExitGate, gated on BOTH
// siblings' moons). NOTE: a discarded experiment tried to keep the gauge at the
// real count by leaving findUnlockShineNum alone and forcing
// isUnlockedNextWorld true instead — that function is NOT the predicate
// consulted at the takeoff seam (it never fired), so it's not used here.
bool isFreeDetourBit(std::uint8_t bit) {
    static const std::uint8_t s_lake    = smoap::game::kingdomBitFor("Lake");
    static const std::uint8_t s_wooded  = smoap::game::kingdomBitFor("Wooded");
    static const std::uint8_t s_snow    = smoap::game::kingdomBitFor("Snow");
    static const std::uint8_t s_seaside = smoap::game::kingdomBitFor("Seaside");
    return bit < 17 && (bit == s_lake || bit == s_wooded ||
                        bit == s_snow || bit == s_seaside);
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
        // Free-detour kingdoms: force the CURRENT-WORLD leave-threshold to 0 so
        // the Odyssey takes off at 0 moons and the sibling crossing opens the
        // instant Mario arrives. This is the PROVEN lever (iterations 2-4,
        // confirmed in-game): the takeoff gate is getPayShineNum(cur) >=
        // findUnlockShineNum(cur), reading THIS function out-of-line, so 0
        // satisfies it. The isUnlockedNextWorld force-true experiment did NOT
        // open the takeoff — that function is not the gate consulted at the
        // takeoff seam (no [free-detour] line EVER fired in the 2026-06-25 log),
        // so the real fix lives here, not there.
        //
        // Trade-off (accepted as cosmetic in iteration 4): the IN-KINGDOM takeoff
        // gauge reads this same current-world value, so it shows 0/"full". The
        // world-map GLOBE per-kingdom label reads the by-world variant below and
        // still shows the true rolled threshold (e.g. Snow 10 / Seaside 10).
        if (isFreeDetourBit(bit)) {
            logSubstitution("findUnlockShineNum[free-detour]", bit, orig, 0);
            return 0;
        }
        // NOTE: Cascade is NOT special-cased here anymore. The "beat Broode to
        // leave" escape used to zero Cascade's current-world gate (and the member
        // worker + isUnlockedNextWorld) once Broode's Multi-Moon was collected, but
        // that made the in-kingdom takeoff gauge read 0/"full" and hid the
        // moons-to-unlock counter. The Cascade escape now lives entirely in
        // EntranceShuffleHook::processCascadeOdysseyDivert (walking into the Odyssey
        // door warps straight to Cap, never reaching the globe/gate), so Cascade can
        // keep its true rolled gate here and display correctly. See
        // [[cap-return-and-cascade-arrival-demo]].
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
        // NOTE: do NOT free-detour-zero the by-world variant. Decomp:
        // selectability is GameDataFile::isUnlockedWorld(world_id) (does not read
        // this), and the launch check (isUnlockedNextWorld) uses only the
        // current-world findUnlockShineNum. This variant feeds the world-map's
        // per-kingdom required-count DISPLAY, so leaving it at the rolled value
        // shows the real Lake/Wooded thresholds (e.g. 7/18) while the crossing
        // stays free via the current-world zero above.
        const int rolled = rolledGateForBit(bit);
        if (rolled < 0) return orig;
        logSubstitution("findUnlockShineNumByWorldId", bit, orig, rolled);
        return rolled;
    });

// NOTE: the Cascade "force the takeoff gate open" hooks (isUnlockedNextWorld +
// the shared member worker GameDataHolder::findUnlockShineNum) were REMOVED
// 2026-06-29. They were the round 1-3 attempts to let the player fly out of
// Cascade post-Broode without paying the rolled gate; the working escape is now
// the door divert in EntranceShuffleHook::processCascadeOdysseyDivert (walking
// into the Odyssey warps straight to Cap, never reaching the globe/gate). Forcing
// the gate to 0 also made the in-kingdom takeoff gauge read 0/"full" and hid the
// moon counter — removing them restores correct UI. See
// [[cap-return-and-cascade-arrival-demo]].

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
