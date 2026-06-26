// Cascade / Madame Broode multi-moon respawn (Approach C — placement scenario).
//
// === The bug ==============================================================
// If Mario leaves Cascade BEFORE fighting Madame Broode, she never reappears
// and her Multi-Moon ("Multi Moon Atop the Falls") becomes permanently
// uncollectable — seed-fatal when that moon is progression. Possible whenever
// the Cascade leave-gate is small enough to satisfy pre-Broode (a low
// randomize_kingdom_gates roll, etc.).
//
// === Mechanism (OdysseyDecomp, see docs/handoff-cascade-broode-respawn.md) =
// Madame Broode + her Multi-Moon are PLACEMENT-gated on Cascade's scenario-1
// layout. The object-placement masker reads the placement scenario via
// GameDataFile::getScenarioNoPlacement() const, which returns the backing field
// GameDataFile::mScenarioNoPlacement. After leaving early and progressing the
// global story, Cascade's computed placement scenario advances past 1, so
// neither actor is placed.
//
// === Why we WRITE the field instead of hooking the read ====================
// Two read seams were tried in-game and BOTH fired zero times on Cascade
// re-entry (2026-06-26):
//   v2: the free-fn wrapper GameDataFunction::getScenarioNoPlacement(accessor)
//   v3: the member        GameDataFile::getScenarioNoPlacement() const
// i.e. the read is fully INLINED at the placement site (no out-of-line caller
// flows through either). And the decomp confirms there's nothing left to hook:
// in OdysseyDecomp src/System/GameDataFunction.cpp both are thin wrappers
// (getScenarioNoPlacement(accessor) -> file->getScenarioNoPlacement()), while
// the GameDataFile MEMBERS themselves (getScenarioNoPlacement / calcNextScenarioNo
// / setMainScenarioNo / any writer of mScenarioNoPlacement) are UNDECOMPILED —
// no body to read, no out-of-line writer symbol to trampoline.
//
// So we go to the value itself. The decomp GameDataFile.h pins the field by
// size: the last three s32 members are
//     s32 mTotalAchievementNum;   // 0xb5c
//     s32 mScenarioNoPlacement;   // 0xb60   <-- this
//     s32 mScenarioNoOverride;    // 0xb64
// and static_assert(sizeof(GameDataFile) == 0xb68) (matches the local
// OdysseyHeaders mirror), so 0xb60/0xb64 are anchored to the end of the struct
// and reliable even though mid-struct decomp offsets are not.
//
// === Where we write it ====================================================
// At the GameDataFile::changeNextStage(info, raceType) commit — the universal
// forward-transition chokepoint we already trampoline in EntranceShuffleHook
// (which holds the GameDataFile* `self`). Post-orig, when the FINAL destination
// stage is Cascade's home stage AND the Multi-Moon is still uncollected, we set
// mScenarioNoPlacement = 1. changeNextStage runs BEFORE the new stage's
// placement, so the inlined read picks up our 1 and Broode + her Multi-Moon are
// placed again. Because we re-apply at every commit INTO Cascade (rather than
// persisting anything), it is immune to calcNextScenarioNo recomputing the value
// each transition — the same reason the Cap-peace WRITE experiment failed
// (MoonRockHook.cpp header) does not bite a per-commit re-apply.
//
// NOTE (testing): this fires on a TRANSITION into Cascade (leave a kingdom and
// come back), NOT on reloading a save that is already sitting in a broken
// Cascade — a reload loads the stage directly with no changeNextStage commit
// (confirmed: no [entrance:file] line precedes the initial arrival), so the
// actors were already placed at the bad scenario and can't be retro-placed.
// To verify: from a pre-Broode Cascade, fly to another kingdom and return.
//
// === Self-healing condition ===============================================
// Force fires ONLY when ALL of:
//   * destination stage == WaterfallWorldHomeStage      (scoped to Cascade —
//                                                         mScenarioNoPlacement is
//                                                         a single field, so we
//                                                         must NOT force it for a
//                                                         non-Cascade load)
//   * the Multi-Moon is DEFINITIVELY uncollected         (moon not yet got)
//
// Collection is read by walking GameDataFile::mShineHintList and reading
// HintInfo::isGet (smoap::game::probeShineGot, matched by (stage, obj)) — the
// SAME proven mechanism the HELLO snapshot uses. We deliberately do NOT call
// GameDataFile::isGotShine(int): that overload indexes by shine INDEX, not the
// apworld shine_uid, so feeding it the Multi-Moon's uid (218) reported
// "uncollected" forever and the forced scenario never released after the moon
// was collected (Broode lingered; scenario refused to advance to 2; 2026-06-26).
// Once Broode is beaten the Multi-Moon's HintInfo::isGet flips, the probe
// returns collected, the gate goes false, and Cascade returns to its computed
// scenario — satisfying Devon's
// "if the whole kingdom's layout reverts it's acceptable as long as it
// re-reverts back after I leave again" (greenlit 2026-06-25). Approach B
// (surgical Shine force-spawn) remains the fallback if this shows a side effect
// or if a recompute clobbers mScenarioNoPlacement between the commit and the load
// (the [broode-respawn] field-timeline logs below will reveal that).

#include "../ap/shine_lookup.hpp"
#include "../game/MoonApply.hpp"
#include "../util/Log.hpp"

#include <cstddef>
#include <cstdint>
#include <cstring>

namespace smoap::hooks {

namespace {

// When false the helper only LOGS its verdict (the mScenarioNoPlacement write is
// suppressed), for shipping a diagnostic build without touching placement. Devon
// greenlit the apply path (2026-06-25), so default true.
inline constexpr bool kCascadeRespawnApply = true;

// The placement scenario Broode + her Multi-Moon are laid out for.
inline constexpr int kBroodeScenario = 1;

// Cascade's home stage — the kingdom overworld where Madame Broode is fought and
// her Multi-Moon appears. We scope the force to commits whose FINAL destination
// is this stage (mScenarioNoPlacement is a single shared field; forcing it for a
// non-Cascade load would mis-place that kingdom).
inline constexpr const char* kCascadeHomeStage = "WaterfallWorldHomeStage";

// GameDataFile::mScenarioNoPlacement byte offset (see header block: anchored to
// the end of the 0xb68-byte struct, second-to-last s32).
inline constexpr std::size_t kOffScenarioNoPlacement = 0xb60;
// mScenarioNoOverride — logged for diagnosis only (not written); a built-in
// engine override seam next to mScenarioNoPlacement, normally -1.
inline constexpr std::size_t kOffScenarioNoOverride = 0xb64;

// The AP-display name of Cascade's Multi-Moon, used to resolve its shine_uid
// from shine_table.h at install. If this logs uid=-1 in-game, the shine_id in
// shine_table.h differs — grep shine_table.h and update this string.
inline constexpr const char* kMultiMoonDisplayName = "Multi Moon Atop the Falls";

// Multi-Moon collection is read via the proven HintInfo walk
// (smoap::game::probeShineGot), matched by (stage, obj). GameDataFile::
// isGotShine(int) is NOT used: it indexes by shine INDEX, not the apworld
// shine_uid, so feeding it 218 mis-reported "uncollected" forever — which is
// why the forced scenario never released after the moon was collected
// (2026-06-26). Resolve (stage, obj) once at install from shine_table.h.
int         s_multiMoonUid   = -1;     // logging only
const char* s_multiMoonStage = nullptr;
const char* s_multiMoonObj   = nullptr;

// Tri-state collection probe wrapper. Returns true only when the Multi-Moon is
// DEFINITIVELY uncollected (probe == 0). probe == 1 (collected) or -1 (unknown:
// game data not ready / not in hint list) → false, so the caller does NOT force
// the scenario — fail-safe direction (never force forever).
bool multiMoonDefinitelyUncollected() {
    if (s_multiMoonStage == nullptr || s_multiMoonObj == nullptr) return false;
    return smoap::game::probeShineGot(s_multiMoonStage, s_multiMoonObj) == 0;
}

std::int32_t* scenarioPlacementPtr(void* gdf) {
    return reinterpret_cast<std::int32_t*>(
        reinterpret_cast<std::uint8_t*>(gdf) + kOffScenarioNoPlacement);
}
std::int32_t scenarioOverride(const void* gdf) {
    return *reinterpret_cast<const std::int32_t*>(
        reinterpret_cast<const std::uint8_t*>(gdf) + kOffScenarioNoOverride);
}

}  // namespace

// Called from EntranceShuffleHook's changeNextStage trampoline (post-orig) with
// the GameDataFile* and the FINAL (post-remap) destination stage name. Forces
// Cascade's placement scenario back to 1 so Madame Broode + her Multi-Moon are
// placed, when the Multi-Moon is still uncollected. No-op for any non-Cascade
// destination or once the moon is collected (fail-safe direction).
void forceCascadePlacementScenario(void* gameDataFile, const char* destStageName,
                                   const char* tag) {
    if (gameDataFile == nullptr || destStageName == nullptr) return;
    if (std::strcmp(destStageName, kCascadeHomeStage) != 0) return;

    // Can't resolve the Multi-Moon's (stage, obj)? Fail SAFE: do not force.
    if (s_multiMoonStage == nullptr || s_multiMoonObj == nullptr) return;
    // probe: 1=collected, 0=uncollected, -1=unknown. Treat anything but a
    // definitive 0 as "collected" (don't force) so we never revert Cascade
    // forever after the moon is taken.
    const bool uncollected = multiMoonDefinitelyUncollected();

    std::int32_t* p = scenarioPlacementPtr(gameDataFile);
    const std::int32_t before   = *p;
    const std::int32_t override = scenarioOverride(gameDataFile);

    if (!uncollected) {
        // Broode beaten / moon collected — leave Cascade's real scenario alone.
        // Log once-ish so the "self-heal" transition is visible in the timeline.
        static int s_gotLog = 0;
        if (s_gotLog < 4) {
            ++s_gotLog;
            SMOAP_LOG_INFO("[broode-respawn] %s Cascade entry, Multi-Moon "
                           "COLLECTED — leaving placement scenario=%d (uid=%d)",
                           tag, before, s_multiMoonUid);
        }
        return;
    }

    // Uncollected: force the placement scenario to Broode's layout. Log every
    // time `before` is NOT already 1 — that directly reveals whether a recompute
    // clobbers our value between commits (repeated "N->1" = clobbered each
    // session; a single "N->1" then silence = our write held).
    static int s_log = 0;
    if (before != kBroodeScenario && s_log < 40) {
        ++s_log;
        SMOAP_LOG_INFO("[broode-respawn] %s FORCE Cascade mScenarioNoPlacement "
                       "%d -> %d (mScenarioNoOverride=%d Multi-Moon uid=%d "
                       "uncollected) apply=%d #%d",
                       tag, before, kBroodeScenario, override, s_multiMoonUid,
                       kCascadeRespawnApply ? 1 : 0, s_log);
    }
    if (kCascadeRespawnApply && before != kBroodeScenario)
        *p = kBroodeScenario;
}

// Returns kBroodeScenario when committing a transition INTO Cascade's home stage
// with the Multi-Moon still uncollected (else -1 = "don't force"). The caller
// writes this into the ChangeStageInfo's scenario field (mScenarioNo) BEFORE
// changeNextStage's orig, so the engine loads Cascade directly in Broode's
// scenario. This is the documented scenario-jump input (what moon rocks use) and
// DRIVES the load, unlike the GameDataFile mScenarioNoPlacement field write
// (forceCascadePlacementScenario) which fired but did NOT take in-game — the
// stage load recomputed the field back to 7 before placement read it (Cascade
// returned in the world-peace scenario, 2026-06-26).
int cascadeArrivalScenarioOverride(void* gameDataFile, const char* destStageName) {
    if (gameDataFile == nullptr || destStageName == nullptr) return -1;
    if (std::strcmp(destStageName, kCascadeHomeStage) != 0) return -1;
    if (!kCascadeRespawnApply) return -1;
    // Fail SAFE if we can't verify collection — never force forever. Only force
    // when the Multi-Moon is DEFINITIVELY uncollected (probe == 0).
    if (!multiMoonDefinitelyUncollected()) return -1;
    return kBroodeScenario;
}

void installCascadeBroodeRespawnHook() {
    // Resolve the Multi-Moon's row from the (gitignored, per-machine)
    // shine_table.h. We need its (stage, obj) — the canonical key the HintInfo
    // collection probe matches on. Absent on a no-romfs release build -> nullptr
    // -> the force soft-degrades (no respawn), the fail-safe direction.
    const auto* row = smoap::game::shineRowByDisplayName(kMultiMoonDisplayName);
    if (row == nullptr) {
        SMOAP_LOG_WARN("[broode-respawn] Multi-Moon %s NOT in shine_table.h "
                       "— respawn disabled until shine data is present (re-run "
                       "sync_shine_table.py) or the display string is corrected",
                       kMultiMoonDisplayName);
        return;
    }
    // string_view aliases the static constexpr kShineTable literals, which are
    // null-terminated and live for the program lifetime — safe as const char*.
    s_multiMoonStage = row->stage_name.data();
    s_multiMoonObj   = row->object_id.data();
    s_multiMoonUid   = row->shine_uid;
    SMOAP_LOG_INFO("[broode-respawn] Multi-Moon %s -> stage=%s obj=%s "
                   "(shine_uid %d, logging only)",
                   kMultiMoonDisplayName, s_multiMoonStage, s_multiMoonObj,
                   s_multiMoonUid);

    // No trampoline of our own: both getScenarioNoPlacement read seams are
    // inlined at the placement site (proven 2026-06-26), so the scenario is
    // forced from EntranceShuffleHook's existing changeNextStage commit:
    // cascadeArrivalScenarioOverride() sets ChangeStageInfo.mScenarioNo before
    // orig (the load input), and forceCascadePlacementScenario() writes the
    // mScenarioNoPlacement field post-orig as belt-and-braces. Collection is
    // read via the HintInfo walk (probeShineGot), NOT GameDataFile::isGotShine
    // (which indexes by shine INDEX, not shine_uid, and mis-reported forever).
    SMOAP_LOG_INFO("[broode-respawn] armed (force ChangeStageInfo.scenario -> %d "
                   "on commit into %s while Multi-Moon (stage=%s obj=%s) "
                   "uncollected; + belt-and-braces mScenarioNoPlacement@0x%zx; "
                   "apply=%d) — invoked from changeNextStage",
                   kBroodeScenario, kCascadeHomeStage, s_multiMoonStage,
                   s_multiMoonObj, kOffScenarioNoPlacement,
                   kCascadeRespawnApply ? 1 : 0);
}

}  // namespace smoap::hooks
