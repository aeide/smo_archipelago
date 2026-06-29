// Cap Kingdom "return" scenario FLOOR.
//
// === What this does =======================================================
// Ensures Cap Kingdom (CapWorldHomeStage) always loads in AT LEAST its "return"
// / post-peace layout — scenario 2 — on every forward transition into it, while
// NEVER pulling it below a higher (moon-rock) scenario. Cap's peace / re-arrival
// moons (the ~17 `{CapPeace()}`-gated checks in data/scenario_gates.json: the Cup
// moons, Peach-in-the-Cap, Hint Art, Timer Challenges, the fog-cleared overworld
// moons, etc.) only physically exist from the return layout onward; in the
// prologue / first-visit layout the kingdom is fogged and walled and those moons
// aren't placed. So a player who can reach Cap from sphere 0 (the
// start_at_cap_peace direction — docs/handoff-cap-peace-sphere-0.md) needs the
// return layout to collect them.
//
// === Why a FLOOR, not a fixed force (the moon-rock interaction) ============
// Cap ALSO has a Moon Rock — 14 of its 31 moons spawn only after the rock is
// broken, which the engine implements as a scenario JUMP to Cap's MOON-ROCK
// scenario (a layout ABOVE the return state; see MoonRockHook.cpp). If we forced
// a fixed scenario 2 unconditionally we would:
//   (a) clobber the rock-open scenario jump (the commit carries the moon-rock
//       scenario; overwriting it with 2 cancels the open), and
//   (b) revert Cap to the return layout on every later arrival, hiding the 14
//       rock moons again.
// So we only force the scenario UP to the return floor when the incoming /
// stored scenario is BELOW it. Anything at or above 2 — the return state itself,
// the moon-rock scenario, the rock-open jump — is left untouched, so the moon
// rock stays gated and its moons spawn and persist normally.
//
// === Mechanism — same lever as the Cascade/Broode force ====================
// We do NOT trampoline anything here. The override is applied from
// EntranceShuffleHook's GameDataFile::changeNextStage commit (the one chokepoint
// that runs BEFORE the upcoming stage's object placement and hands us both the
// GameDataFile* and the ChangeStageInfo). capArrivalScenarioOverride() returns 2
// only when the effective incoming scenario is below the return floor, and the
// caller writes it into ChangeStageInfo.mScenarioNo (@0x1CC) before orig — the
// documented scenario-jump load input (what moon rocks use), which DRIVES the
// load rather than being recomputed away.
//
// The "effective incoming scenario" is the ChangeStageInfo's mScenarioNo when it
// is an explicit value (>= 0), else (the common -1 = "compute from quest state")
// Cap's stored GameDataFile::getScenarioNo(world) — the SAME signal MoonRockHook
// uses to detect "moon-rock scenario active". This catches the post-break normal
// arrival case (info scenario -1, but stored == moon-rock scenario > 2 → leave).
//
// === How it composes with MoonRockHook =====================================
// Independent and complementary. The placement-scenario force here controls which
// LAYOUT loads; MoonRockHook's rock-openable gate keys off the story-complete
// flag (isClearWorldMainScenario), which is set by the actual peace state on the
// save, not by our placement write. So on the Cap-peace save the rock is
// openable, breaking it jumps to the moon-rock scenario (we don't clobber it,
// 14 moons spawn), and the floor keeps Cap at the return layout the rest of the
// time (17 peace moons, 14 rock moons gated until the rock is broken).
//
// === Caveat (transitions only, not reload) =================================
// Like the Cascade force, this fires on a TRANSITION into Cap (warp / Odyssey
// arrival / moon-rock scenario jump), NOT on reloading a save already sitting in
// Cap — a reload loads the stage directly with no changeNextStage commit. The
// start_at_cap_peace save is authored at the peace state, so its initial load is
// correct; every subsequent return into Cap is pinned by this floor.

#include "hk/ro/RoUtil.h"
#include "hk/types.h"

#include "HookSymbols.hpp"
#include "../util/Log.hpp"

#include <cstring>
#include <type_traits>

namespace smoap::hooks {

namespace {

// When false the override is suppressed (returns -1 always) so a diagnostic
// build can ship without touching Cap placement. Default true — Devon greenlit
// the always-return behavior.
inline constexpr bool kCapReturnApply = true;

// Cap's "return" / post-peace placement scenario (fog cleared, peace moons
// present) — the FLOOR we never let Cap load below. Devon-specified. Cap's
// moon-rock scenario is ABOVE this; we never force down to it, so the rock and
// its 14 moons stay gated. One-line change if a different return layout is wanted.
inline constexpr int kCapReturnScenario = 2;

// Cap Kingdom's home stage — the overworld we scope the force to. mScenarioNo on
// the ChangeStageInfo is per-transition, so this is safe to set only when the
// destination IS Cap; every other destination returns -1 (don't force).
inline constexpr const char* kCapHomeStage = "CapWorldHomeStage";

// SMO world id 0 = Cap (kKingdoms[0], identity-mapped — matches MoonRockHook's
// kCapWorldId).
inline constexpr int kCapWorldId = 0;

// GameDataFile::getScenarioNo(int worldId) const — Cap's STORED scenario, used to
// resolve a -1 ("compute") incoming ChangeStageInfo scenario. The SAME function
// MoonRockHook uses to detect the moon-rock scenario being active, so the
// broken-rock state reads consistently between the two hooks.
using GetScenarioNoFn = int (*)(const void* gdf, int world_id);
GetScenarioNoFn s_getScenarioNo = nullptr;

}  // namespace

// Called from EntranceShuffleHook's changeNextStage trampoline (pre-orig) with
// the GameDataFile* (`self`), the incoming ChangeStageInfo.mScenarioNo, and the
// FINAL (post-remap) destination stage name. Returns kCapReturnScenario ONLY when
// committing into Cap's home stage AND the effective incoming scenario is below
// the return floor; else -1 ("don't force"). Never lowers a higher (moon-rock)
// scenario, so the Moon Rock and its 14 moons stay gated and spawn/persist
// normally.
int capArrivalScenarioOverride(const void* gameDataFile, int incomingScenario,
                               const char* destStageName) {
    if (destStageName == nullptr) return -1;
    if (!kCapReturnApply) return -1;
    if (std::strcmp(destStageName, kCapHomeStage) != 0) return -1;

    // Effective scenario the load would otherwise use: the explicit info value if
    // present (>= 0), else Cap's stored scenario (info -1 = "compute from quest
    // state"). If we can't read the stored value, fall back to the info value so
    // an explicit moon-rock-jump scenario is still protected.
    int effective = incomingScenario;
    if (effective < 0 && s_getScenarioNo != nullptr && gameDataFile != nullptr)
        effective = s_getScenarioNo(gameDataFile, kCapWorldId);

    // At or above the return floor (return state, OR the moon-rock scenario / its
    // open-jump) — leave it alone so the rock and its moons aren't clobbered.
    if (effective >= kCapReturnScenario) return -1;

    // Below the floor (prologue / fog layout) — pin to the return state.
    return kCapReturnScenario;
}

void installCapReturnScenarioHook() {
    // Resolve Cap's stored-scenario reader (soft-degrade on miss, like
    // MoonRockHook). Without it the floor still protects an EXPLICIT moon-rock
    // jump (info carries the scenario), but a post-break normal arrival (info -1)
    // could be forced back to 2 — so log loudly if it's missing.
    const ptr addr = hk::ro::lookupSymbol(smoap::sym::kGameDataFileGetScenarioNo);
    if (addr == 0) {
        s_getScenarioNo = nullptr;
        SMOAP_LOG_WARN("[cap-return] getScenarioNo lookup FAILED — floor degrades "
                       "to info-only (post-moon-rock normal arrivals may revert to "
                       "the return layout)");
    } else {
        s_getScenarioNo = reinterpret_cast<GetScenarioNoFn>(addr);
    }

    // No trampoline of our own: the floor is applied from EntranceShuffleHook's
    // existing changeNextStage commit (capArrivalScenarioOverride() sets
    // ChangeStageInfo.mScenarioNo before orig — the scenario-jump load input).
    SMOAP_LOG_INFO("[cap-return] armed (force ChangeStageInfo.scenario UP to %d on "
                   "commits into %s whose effective scenario is below it; "
                   "moon-rock scenario left untouched; apply=%d getScenarioNo=%d)",
                   kCapReturnScenario, kCapHomeStage, kCapReturnApply ? 1 : 0,
                   s_getScenarioNo != nullptr ? 1 : 0);
}

}  // namespace smoap::hooks
