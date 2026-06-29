// P7 entrance shuffle — Step 3.5: DEEPENED LOGGER (no behavior change yet).
//
// Step 3's pure logger on GameDataFunction::tryChangeNextStage(GameDataHolderWriter,
// const ChangeStageInfo*) proved that function is NOT the universal chokepoint:
// the 2026-06-18 in-game walk showed shop / house / slots ENTRY fire it, but
// Push-Block-Peril ENTRY, Dinosaur Nest, and Top-Hat Tower fire NO entrance line
// (only the EXIT pipe OUT of PushBlockExStage fired it). Those entries reach the
// next-stage commit through a direct actor call that bypasses the GameDataFunction
// free function. Per OdysseyDecomp the convergence point one level down is
// GameDataFile::changeNextStage(const ChangeStageInfo*, s32) — analogous to
// GameDataFile::setGotShine being the 5-way moon chokepoint.
//
// So this revision installs THREE loggers, each with a distinct prefix so the
// next walk can classify every transition by which path(s) it takes:
//   [entrance:try]    GameDataFunction::tryChangeNextStage  (the GameDataFunction path)
//   [entrance:file]   GameDataFile::changeNextStage         (the universal forward commit)
//   [entrance:return] GameDataFile::returnPrevStage         (the separate exit/return path)
// A transition that logs BOTH :try and :file took the GameDataFunction path; one
// that logs ONLY :file took a direct-actor path (the case Step 3 missed). A door
// exit that logs :return uses the return stack (likely correct for free in Step 4
// since we only rewrite the forward target); one that instead logs :file with
// stage==home took a forward "exit pipe" and WILL need exit handling.
//
// Spurious-call note: the walk logged empty `stage='' id=''` :try lines ~1s after
// each moon collect (the get-shine demo). The Step 4 remap MUST skip empty stages.
//
// Field layout is read by raw offset rather than including the OdysseyHeaders
// + sead string headers (matches the local-mirror idiom the other hooks use).
// Offsets per OdysseyHeaders game/Sequence/ChangeStageInfo.h (sizeof 0x278):
//   mChangeStageId   @ 0x000  (sead::FixedSafeString<0x80>, cstr ptr @ +0x08)
//   mChangeStageName @ 0x098  (cstr ptr @ 0x098 + 0x08 = 0x0A0)
//   mIsReturn        @ 0x1C8  (bool)
//   mScenarioNo      @ 0x1CC  (s32)
// (each FixedSafeString<0x80> is 0x98 bytes; the live string pointer is
//  mStringTop at +0x08, after the SafeStringBase vtable pointer.)
//
// See HookSymbols.hpp:kGameDataFunctionTryChangeNextStage / kGameDataFileChangeNextStage
// / kGameDataFileReturnPrevStage for symbol provenance.

#include "hk/hook/Trampoline.h"
#include "hk/ro/RoUtil.h"
#include "hk/types.h"

#include "../ap/ApFrameBridge.hpp"
#include "../ap/ApState.hpp"
#include "../game/KingdomOrderGate.hpp"
#include "../game/KingdomUnlock.hpp"
#include "../game/OdysseyRescue.hpp"
#include "../util/Log.hpp"
#include "HookSymbols.hpp"

#include <cstdint>
#include <cstring>

namespace smoap::hooks {

// Defined in CascadeBroodeRespawnHook.cpp. On a forward commit INTO Cascade's
// home stage with Madame Broode's Multi-Moon still uncollected, forces
// GameDataFile::mScenarioNoPlacement back to 1 so she + her Multi-Moon are
// placed by the upcoming stage load. No-op for any other destination. We route
// it through this hook because changeNextStage is the one chokepoint that both
// (a) runs before the next stage's placement and (b) hands us the GameDataFile*;
// both getScenarioNoPlacement read seams are inlined (see that file's header).
void forceCascadePlacementScenario(void* gameDataFile, const char* destStageName,
                                   const char* tag);

// Defined in CascadeBroodeRespawnHook.cpp. Returns the scenario to force the
// upcoming Cascade arrival to (so Madame Broode is placed) when committing into
// Cascade's home stage with her Multi-Moon uncollected, else -1. We write it into
// the ChangeStageInfo scenario field BEFORE orig — the engine's scenario-jump
// load input, which actually drives the load (the GameDataFile field write did not).
int cascadeArrivalScenarioOverride(void* gameDataFile, const char* destStageName);

// Defined in CascadeBroodeRespawnHook.cpp — true once Cascade's Madame Broode
// Multi-Moon is collected (Broode beaten). Pure save-state read; used by the
// Cascade Odyssey "board -> Cap" door divert below.
bool cascadeMultiMoonCollected();

// Defined in CapReturnScenarioHook.cpp. Returns Cap's "return" placement scenario
// (2) to FLOOR the upcoming Cap arrival to its post-peace layout when committing
// into Cap's home stage AND the effective incoming scenario is below it, else -1.
// Never lowers a higher (moon-rock) scenario, so Cap's Moon Rock and its 14 moons
// stay gated and spawn/persist normally. Same lever as the Cascade force: written
// into the ChangeStageInfo scenario field BEFORE orig (the scenario-jump load
// input). Takes the GameDataFile* (to read Cap's stored scenario for a -1 info
// value) and the incoming ChangeStageInfo.mScenarioNo.
int capArrivalScenarioOverride(const void* gameDataFile, int incomingScenario,
                               const char* destStageName);

namespace {

struct GameDataHolderWriter { void* mData; };
struct GameDataHolderAccessor { void* mData; };

// Opaque — fields read via the byte offsets documented above.
class ChangeStageInfo;
class GameDataFile;

constexpr std::size_t kOffChangeStageIdCstr   = 0x08;
constexpr std::size_t kOffChangeStageNameCstr = 0xA0;
constexpr std::size_t kOffIsReturn            = 0x1C8;
constexpr std::size_t kOffScenarioNo          = 0x1CC;

// ── First-arrival Odyssey pose: hijack the story drop into the flight arrival ─
// Devon's approach (2026-06-27). The story-drop into Cascade carries entrance
// id='start'; that arrival init places the Odyssey BURIED (resets home level to
// 0) and spawns Mario at the intro point. The Odyssey FLIGHT arrival instead
// carries an EMPTY entrance id and places the ship PARKED at its return landing
// pad. So on the pre-Broode commit into Cascade we rewrite a 'start' entrance id
// to the flight (empty) shape — the same "HomeStage default-spawn" id the detour
// gate writes — so the ship arrives parked at its return location instead of in
// the rocks, and Mario steps off it. Paired with forceAcquireOdyssey (which sets
// launch/level so the ship is flightworthy for the landing). If the empty-id
// assumption proves wrong in-game, flip kCascadeFlightArrivalId to the named
// landing id (read it off an [entrance:file] line from a legitimate fly-in).
inline constexpr const char* kCascadeStoryArrivalId  = "start";
inline constexpr const char* kCascadeFlightArrivalId = "";  // empty = home default spawn

// Stage names for the Cascade Odyssey "board -> Cap" door divert (see
// processCascadeOdysseyDivert). HomeShipInsideStage is the Odyssey cabin interior
// reached by walking into the ship in ANY kingdom — boarding is a plain door
// transition (proven on :file), not the in-cabin ShineTowerRocket world-map nerve.
inline constexpr const char* kCascadeHomeStage   = "WaterfallWorldHomeStage";
inline constexpr const char* kOdysseyInsideStage = "HomeShipInsideStage";
inline constexpr const char* kCapHomeStage       = "CapWorldHomeStage";

using GetCurrentStageNameFn = const char* (*)(GameDataHolderAccessor);
GetCurrentStageNameFn s_getCurrentStageName = nullptr;

const char* readCstrAt(const ChangeStageInfo* info, std::size_t off) {
    const auto* base = reinterpret_cast<const std::uint8_t*>(info);
    const char* p = *reinterpret_cast<const char* const*>(base + off);
    return p ? p : "(null)";
}

const char* currentStageName() {
    if (!s_getCurrentStageName) return "(unresolved)";
    void* gdh = smoap::ap::ApState::instance().game_data_holder_cache.load(
        std::memory_order_relaxed);
    if (!gdh) return "(no-holder)";
    const char* s = s_getCurrentStageName(GameDataHolderAccessor{gdh});
    return s ? s : "(null)";
}

// Shared logging body for the two ChangeStageInfo* hooks (:try and :file).
void logChangeStageInfo(const char* tag, const ChangeStageInfo* info) {
    if (!info) {
        SMOAP_LOG_INFO("[entrance:%s] info=null", tag);
        return;
    }
    const char* stage    = readCstrAt(info, kOffChangeStageNameCstr);
    const char* entrance = readCstrAt(info, kOffChangeStageIdCstr);
    const bool isReturn =
        *reinterpret_cast<const bool*>(
            reinterpret_cast<const std::uint8_t*>(info) + kOffIsReturn);
    const int scenario =
        *reinterpret_cast<const std::int32_t*>(
            reinterpret_cast<const std::uint8_t*>(info) + kOffScenarioNo);
    SMOAP_LOG_INFO(
        "[entrance:%s] stage='%s' id='%s' isReturn=%d scenario=%d cur='%s'",
        tag, stage, entrance, isReturn ? 1 : 0, scenario, currentStageName());
}

// ── Step 4 forward-remap seam (COMPILE-TIME GATED, default OFF) ──────────────
//
// kEntranceRemapApply == false (the shipped default): processEntranceRemap is a
// pure PREVIEW — it looks up the inbound dest stage and LOGS what the rewrite
// would do, mutating nothing. A build+deploy in this state changes NO in-game
// behavior; it only emits [entrance:remap-preview] so a walk can confirm the
// bridge-shipped table matches the doors that actually fire :file.
//
// Flip kEntranceRemapApply to true (and rebuild) to enable the actual rewrite:
// the "lie to the game" swap of mChangeStageName + mChangeStageId in the
// ChangeStageInfo buffer. This is BOTH-directions ready (Step 4 exit rows
// landed 2026-06-19): processEntranceRemap passes both keys to
// lookupEntranceRemap, which prefers an entry row matching `dest` else an exit
// row matching `cur`, and the same mutation body rewrites whichever hit. Coupled
// return-to-origin is handled two ways: exits that fire :file (changeNextStage
// with a ChangeStageInfo hardcoded to the vanilla parent overworld) get the
// exit-by-cur rewrite here; exits that fire :return (returnPrevStage, no info)
// pop back to wherever Mario came FROM, which under a rewritten forward entry is
// already the correct origin. Validated read-only via [entrance:remap-preview]
// across doors/pipes/multi-exit subareas/moon pipes (2026-06-19); the dest==cur
// guard skips moon-rock same-stage reloads.
static constexpr bool kEntranceRemapApply = true;

// FixedSafeString<0x80> inline buffer capacity (incl. terminator). mStringTop
// (cstr ptr @ +0x08) points into this object-owned buffer, so a bounded,
// null-terminated overwrite is a safe in-place edit; sead stores capacity in
// mBufferSize and computes length on demand, so there is no length field to fix.
constexpr std::size_t kFixedStringCap = 0x80;

char* mutableCstrAt(ChangeStageInfo* info, std::size_t off) {
    auto* base = reinterpret_cast<std::uint8_t*>(info);
    return *reinterpret_cast<char* const*>(base + off);
}

void processEntranceRemap(const ChangeStageInfo* info) {
    if (!info) return;
    const char* dest = readCstrAt(info, kOffChangeStageNameCstr);
    if (!dest || dest[0] == '\0' || std::strcmp(dest, "(null)") == 0) return;
    // getCurrentStageName — the EXIT key. We're leaving `cur`; an exit row keyed
    // on it rewrites the forward "exit pipe" dest to the origin door's overworld.
    const char* cur = currentStageName();
    // Moon-rock reload (and any self-transition) fires :file with dest == cur:
    // a scenario-jump reload of the SAME stage, never a door/exit. Skip it so we
    // don't remap a reload. (cur may be a sentinel like "(unresolved)" when
    // getCurrentStageName didn't resolve — that never equals a real dest, so the
    // guard is inert and we fall back to an entry-only lookup below.)
    if (cur && std::strcmp(dest, cur) == 0) return;

    char to_stage[smoap::ap::kCheckFieldCap];
    char to_id[smoap::ap::kCheckFieldCap];
    if (!smoap::ap::ApState::instance().lookupEntranceRemap(dest, cur, to_stage, to_id))
        return;

    if constexpr (!kEntranceRemapApply) {
        SMOAP_LOG_INFO("[entrance:remap-preview] dest='%s' cur='%s' -> stage='%s' "
                       "id='%s' (NOT YET APPLIED — kEntranceRemapApply is false)",
                       dest, cur, to_stage, to_id);
        return;
    }

    auto* mut          = const_cast<ChangeStageInfo*>(info);
    char* dst_stage    = mutableCstrAt(mut, kOffChangeStageNameCstr);
    char* dst_id       = mutableCstrAt(mut, kOffChangeStageIdCstr);
    const std::size_t stage_len = std::strlen(to_stage);
    const std::size_t id_len    = std::strlen(to_id);
    // Verify BOTH fit before writing EITHER — never leave a torn rewrite (right
    // stage / stale entrance id). to_stage/to_id come from kCheckFieldCap(64)
    // buffers, so this always passes in practice; the guard is belt-and-braces.
    if (!dst_stage || !dst_id ||
        stage_len + 1 > kFixedStringCap || id_len + 1 > kFixedStringCap) {
        SMOAP_LOG_WARN("[entrance:remap-FAILED] dest='%s' cur='%s' -> stage='%s' "
                       "id='%s' (buffer guard tripped) — left vanilla",
                       dest, cur, to_stage, to_id);
        return;
    }
    char old_id[smoap::ap::kCheckFieldCap];
    std::strncpy(old_id, readCstrAt(info, kOffChangeStageIdCstr),
                 smoap::ap::kCheckFieldCap - 1);
    old_id[smoap::ap::kCheckFieldCap - 1] = '\0';
    std::memcpy(dst_stage, to_stage, stage_len + 1);
    std::memcpy(dst_id, to_id, id_len + 1);
    SMOAP_LOG_INFO("[entrance:remap-APPLIED] dest='%s'/'%s' cur='%s' -> stage='%s' id='%s'",
                   dest, old_id, cur, to_stage, to_id);
}

// ── Free-detour: "both siblings before the exit" gate ───────────────────────
//
// Both detours are free to cross (sibling fuel forced to 0, see
// UnlockShineNumHook), so the ONLY thing holding the player in a detour until
// both leave-thresholds are met must live here. Two pairs (see kDetourPairs in
// KingdomOrderGate.cpp):
//   - Lake/Wooded -> Cloud: story-forced (select Metro on the map -> Bowser
//     cutscene -> Cloud pre-peace). The demo-warp seam reads as Metro and
//     redirecting it did NOT stop the reroute (iteration 2 leaked to Cloud).
//   - Snow/Seaside -> Luncheon: a normal onward flight — no Bowser intercept,
//     so the destination resolves to Luncheon directly.
// In BOTH cases this `:file`/changeNextStage commit is where the destination
// provably resolves to the exit kingdom's HomeStage (Cloud playtest 2026-06-25),
// so it's the authoritative chokepoint. When the gate is unmet we rewrite the
// commit target in place (same bounded mutation processEntranceRemap uses) to
// the unmet sibling's HomeStage with an empty entrance id (the normal HomeStage
// default-spawn arrival shape — the exit's :file id was empty too).
//
// Scoped to commits ORIGINATING from this pair's siblings so a legitimate
// post-detour entry is never touched, and as a backstop for the known
// "outstanding can drop after deposits" concern.
void processDetourExitGate(const ChangeStageInfo* info) {
    if (!info) return;
    const char* dest = readCstrAt(info, kOffChangeStageNameCstr);
    const char* dest_kingdom = dest ? smoap::game::kingdomShortFromHomeStage(dest)
                                    : nullptr;
    if (!dest_kingdom) return;

    // exit_kingdom is non-null only when dest is a known detour exit
    // (Cloud / Luncheon); otherwise this is a no-op (fail open).
    const auto cg = smoap::game::evaluateDetourExitGate(dest_kingdom);
    if (!cg.exit_kingdom) return;

    // Only gate commits ORIGINATING from this pair's siblings, so a legitimate
    // post-detour entry is never touched and the "outstanding can drop after
    // deposits" concern is backstopped.
    const char* cur_kingdom =
        smoap::game::kingdomShortFromHomeStage(currentStageName());
    if (!cur_kingdom || (std::strcmp(cur_kingdom, cg.a_short) != 0 &&
                         std::strcmp(cur_kingdom, cg.b_short) != 0))
        return;

    if (!cg.blocked || !cg.redirect_stage) {
        SMOAP_LOG_INFO("[entrance:detour-gate] pass to %s (cur=%s): "
                       "%s %d/%d %s %d/%d", cg.exit_kingdom, cur_kingdom,
                       cg.a_short, cg.a_have, cg.a_need,
                       cg.b_short, cg.b_have, cg.b_need);
        return;
    }

    auto* mut       = const_cast<ChangeStageInfo*>(info);
    char* dst_stage = mutableCstrAt(mut, kOffChangeStageNameCstr);
    char* dst_id    = mutableCstrAt(mut, kOffChangeStageIdCstr);
    const std::size_t stage_len = std::strlen(cg.redirect_stage);
    if (!dst_stage || !dst_id || stage_len + 1 > kFixedStringCap) {
        SMOAP_LOG_WARN("[entrance:detour-gate] redirect buffer guard tripped "
                       "(-> '%s') — left vanilla", cg.redirect_stage);
        return;
    }
    std::memcpy(dst_stage, cg.redirect_stage, stage_len + 1);
    dst_id[0] = '\0';
    SMOAP_LOG_WARN("[entrance:detour-gate] HOLDING out of %s (cur=%s): "
                   "%s %d/%d %s %d/%d -> '%s'", cg.exit_kingdom, cur_kingdom,
                   cg.a_short, cg.a_have, cg.a_need,
                   cg.b_short, cg.b_have, cg.b_need, cg.redirect_stage);
}

// ── Cascade Odyssey "board -> Cap" door divert (Devon's no-flight-map escape) ──
//
// The free-travel softlock: the player flies the Odyssey Cap->Cascade pre-equipped
// to grab one ability/capture, beats Broode (always possible — her Chain Chomp is a
// fixed starter), collects her Multi-Moon... then can't afford the rolled
// kingdom-gate moons to fly back out. Three attempts to OPEN the takeoff gate all
// hit the inlining wall (findUnlockShineNum free-fn caught only globe labels;
// isUnlockedNextWorld absent from dynsym; the member worker fired but did NOT open
// the in-cabin gate). See [[cap-return-and-cascade-arrival-demo]].
//
// Devon's idea instead — and the seam the log finally revealed: BOARDING the Odyssey
// is a plain door transition into the cabin interior (HomeShipInsideStage), which
// fires :file right here with cur=='WaterfallWorldHomeStage'. (The earlier
// OdysseyBoardDivertHook hooked ShineTowerRocket::exeGoToWorldMap* — the in-cabin
// globe nerves — one layer too deep, so it never fired.) So we treat boarding like
// a subarea door and rewrite ITS dest to Cap, exactly as processDetourExitGate
// rewrites a held detour: when leaving Cascade's home stage post-Broode, walking
// into the Odyssey loads Cap directly — no flight map. From Cap (always peace'd,
// Odyssey present) the player flies onward normally.
//
// Empty entrance id = the HomeStage default-spawn shape (same as the detour gate).
// The existing CapReturnScenarioHook floors Cap to scenario 2 + force-acquires the
// Odyssey on the resulting commit into CapWorldHomeStage, so Cap arrives peace'd
// with a boardable ship. Scope (Devon's choice): Cascade post-Broode ONLY — every
// other kingdom keeps the vanilla cabin + flight map. Trade-off (accepted):
// post-Broode, Cascade's Odyssey is a one-way Cap shuttle (pick another dest from
// Cap, not Cascade). Runs after processEntranceRemap/processDetourExitGate so it
// reads the final (post-remap) dest, and BEFORE the reportArrival block so the
// tracker sees Cap, not the ship interior.
void processCascadeOdysseyDivert(const ChangeStageInfo* info) {
    if (!info) return;
    const char* dest = readCstrAt(info, kOffChangeStageNameCstr);
    if (!dest || std::strcmp(dest, kOdysseyInsideStage) != 0) return;
    const char* cur = currentStageName();
    if (!cur || std::strcmp(cur, kCascadeHomeStage) != 0) return;
    if (!cascadeMultiMoonCollected()) return;

    auto* mut       = const_cast<ChangeStageInfo*>(info);
    char* dst_stage = mutableCstrAt(mut, kOffChangeStageNameCstr);
    char* dst_id    = mutableCstrAt(mut, kOffChangeStageIdCstr);
    const std::size_t stage_len = std::strlen(kCapHomeStage);
    if (!dst_stage || !dst_id || stage_len + 1 > kFixedStringCap) {
        SMOAP_LOG_WARN("[odyssey->cap] redirect buffer guard tripped — left vanilla "
                       "(Cascade boarding enters the cabin instead)");
        return;
    }
    std::memcpy(dst_stage, kCapHomeStage, stage_len + 1);
    dst_id[0] = '\0';
    SMOAP_LOG_INFO("[odyssey->cap] Cascade post-Broode boarding diverted to Cap "
                   "(no flight map): %s -> %s (cur=%s)",
                   kOdysseyInsideStage, kCapHomeStage, cur);
}

// [entrance:try] — GameDataFunction::tryChangeNextStage(writer, info). Free
// function, writer passed by value. The GameDataFunction-path forward transitions.
HkTrampoline<bool, GameDataHolderWriter, const ChangeStageInfo*>
    tryChangeNextStageHook = hk::hook::trampoline(
        [](GameDataHolderWriter writer, const ChangeStageInfo* info) -> bool {
            logChangeStageInfo("try", info);
            return tryChangeNextStageHook.orig(writer, info);
        });

// [entrance:file] — GameDataFile::changeNextStage(info, raceType). Member
// function (implicit GameDataFile* this). The UNIVERSAL forward commit: catches
// both the GameDataFunction path and the direct-actor paths Step 3 missed.
HkTrampoline<void, GameDataFile*, const ChangeStageInfo*, std::int32_t>
    fileChangeNextStageHook = hk::hook::trampoline(
        [](GameDataFile* self, const ChangeStageInfo* info,
           std::int32_t raceType) -> void {
            logChangeStageInfo("file", info);
            processEntranceRemap(info);
            processDetourExitGate(info);
            processCascadeOdysseyDivert(info);
            // Overworld-arrival signal for the PC tracker. processEntranceRemap
            // has already rewritten mChangeStageName in place when shuffled, so
            // the dest read here is the FINAL stage Mario is committing to. If
            // it's a kingdom HomeStage, tell the bridge which kingdom — it
            // reveals that kingdom's rolled exit gate (randomize_kingdom_gates).
            if (info) {
                const char* dest = readCstrAt(info, kOffChangeStageNameCstr);
                const char* kingdom = smoap::game::kingdomShortFromHomeStage(dest);
                if (kingdom) smoap::ap::reportArrival(dest, kingdom);
                // Cascade/Broode respawn (PRIMARY): force the arrival scenario in
                // the ChangeStageInfo BEFORE orig consumes it, so the engine loads
                // Cascade directly in Broode's scenario (the scenario-jump input
                // moon rocks use). The post-orig GameDataFile field write below
                // fired but did NOT take (the load recomputes it), so this drives
                // the load instead. dest is the FINAL (post-remap) target.
                const int sc = cascadeArrivalScenarioOverride(self, dest);
                if (sc >= 0) {
                    auto* mut = const_cast<ChangeStageInfo*>(info);
                    auto* scp = reinterpret_cast<std::int32_t*>(
                        reinterpret_cast<std::uint8_t*>(mut) + kOffScenarioNo);
                    const std::int32_t before = *scp;
                    *scp = sc;
                    SMOAP_LOG_INFO("[broode-respawn] changeNextStage force Cascade "
                                   "arrival ChangeStageInfo.scenario %d -> %d (dest=%s)",
                                   before, sc, dest);

                    // Logger spike (2026-06-27): capture the pending-warp
                    // first-visit flags NOW, before any of our writes. At this
                    // commit cur is still Cap, so isFirstTimeNextWorld /
                    // isForwardWorldWarpDemo / isPlayDemoWorldWarp describe the
                    // upcoming Cascade warp — the suspected lever for the buried
                    // arrival pose (entrance id / scenario / Home flags / level
                    // were all ruled out 2026-06-27).
                    smoap::game::logWorldWarpDemoDiagNow("commit->Cascade");

                    // First-arrival Odyssey fix: sc>=0 means we're committing
                    // into Cascade pre-Broode (the scenario-1 force above keeps
                    // Broode present). Force-acquire the Odyssey here, BEFORE the
                    // stage loads, so Cascade inits with the parked + boardable
                    // ship instead of the buried wreck. Measured: every
                    // Odyssey-flight arrival lands parked (exist/act/launch=1);
                    // the story-drop arrives buried with the flags at 0.
                    smoap::game::forceAcquireOdyssey("changeNextStage->Cascade");

                    // First-arrival parked-pose FIX (2026-06-27): mark Cascade
                    // already-visited so the engine runs the normal PARKED
                    // flight landing, not the buried first-visit demo. The
                    // warpdemo spike proved isAlreadyGoWorld(Cascade) is the
                    // buried-vs-parked discriminator (0 buried first arrival vs
                    // 1 parked return flight, same forced scenario 1 + entrance
                    // id). self is the GameDataFile* (mGameProgressData @+0x6a8).
                    smoap::game::forceCascadeAlreadyVisited(
                        self, "changeNextStage->Cascade");

                    // H2 (Devon's entrance-id approach, 2026-06-27): the flags
                    // alone (H1) de-rocked the ship but did NOT move it — the
                    // buried POSE is baked at the ship actor's init off the
                    // story-drop entrance. So also REROUTE the arrival: rewrite a
                    // 'start' entrance id to the flight (empty) id so the engine
                    // runs the Odyssey landing arrival and places the ship parked
                    // at its return pad. Only the story drop is hijacked — a real
                    // pre-Broode fly-in already carries the empty id (no-op).
                    char* idbuf = mutableCstrAt(mut, kOffChangeStageIdCstr);
                    const char* cur_id = readCstrAt(info, kOffChangeStageIdCstr);
                    if (idbuf && cur_id &&
                        std::strcmp(cur_id, kCascadeStoryArrivalId) == 0) {
                        const std::size_t fid_len =
                            std::strlen(kCascadeFlightArrivalId);
                        if (fid_len + 1 <= kFixedStringCap) {
                            std::memcpy(idbuf, kCascadeFlightArrivalId,
                                        fid_len + 1);
                            SMOAP_LOG_INFO(
                                "[odyssey-arrival] Cascade story-drop id='%s' -> "
                                "flight id='%s' (land parked at return pad, "
                                "dest=%s)",
                                kCascadeStoryArrivalId, kCascadeFlightArrivalId,
                                dest);
                        }
                    }
                }

                // Cap "return" scenario floor: ensure every commit into Cap's
                // home stage loads AT LEAST its post-peace layout (scenario 2) so
                // the {CapPeace()}-gated moons are placed, WITHOUT lowering a
                // higher moon-rock scenario (Cap's Moon Rock + its 14 moons stay
                // gated). Same lever as the Cascade force above — write the
                // ChangeStageInfo scenario BEFORE orig consumes it. dest is the
                // FINAL (post-remap) target; pass the current info scenario so the
                // override can tell a fog/prologue load from a moon-rock load.
                {
                    auto* scp = reinterpret_cast<std::int32_t*>(
                        reinterpret_cast<std::uint8_t*>(const_cast<ChangeStageInfo*>(info))
                        + kOffScenarioNo);
                    const std::int32_t before = *scp;
                    const int capSc = capArrivalScenarioOverride(self, before, dest);
                    if (capSc >= 0) {
                        if (before != capSc) {
                            *scp = capSc;
                            SMOAP_LOG_INFO("[cap-return] changeNextStage floor Cap "
                                           "arrival ChangeStageInfo.scenario %d -> "
                                           "%d (dest=%s)",
                                           before, capSc, dest);
                        }
                        // The prologue layout we're overriding has no Odyssey, so
                        // the player can't leave Cap. Force the ship present +
                        // boardable BEFORE the stage loads (no-op once owned), and
                        // unlock Cascade so the world map offers it as a
                        // destination (the prologue's scripted unlockWorld is
                        // skipped). Mirrors the Cascade first-arrival fix above.
                        smoap::game::forceAcquireOdyssey("changeNextStage->Cap");
                        smoap::game::forceUnlockCascadeDestination(
                            "changeNextStage->Cap");
                    }
                }
            }
            fileChangeNextStageHook.orig(self, info, raceType);
            // Belt-and-braces: also re-assert the GameDataFile placement field
            // post-orig. It did NOT take alone (kept so the logs show both paths;
            // if the ChangeStageInfo write above succeeds this is redundant).
            if (info)
                forceCascadePlacementScenario(
                    self, readCstrAt(info, kOffChangeStageNameCstr),
                    "changeNextStage");
        });

// [entrance:return] — GameDataFile::returnPrevStage(). Member function, no args.
// The separate exit path (no ChangeStageInfo).
HkTrampoline<void, GameDataFile*> returnPrevStageHook =
    hk::hook::trampoline([](GameDataFile* self) -> void {
        SMOAP_LOG_INFO("[entrance:return] returnPrevStage cur='%s'",
                       currentStageName());
        returnPrevStageHook.orig(self);
    });

}  // namespace

// Per-frame overworld-arrival poll (driven by drawMain). The changeNextStage
// commit emit alone is not enough for two cases: (1) the opening/first arrival
// into a kingdom can predate the PC client connecting, and (2) the frame-thread
// dedup `last_arrival_kingdom` survives a client disconnect while the client
// RESETS its reached_kingdoms set on every (re)connect — so a reconnect while
// standing in a kingdom would never re-reveal it. Polling the current stage each
// frame and routing through reportArrival (which self-dedups) closes both:
// reportArrival only enqueues on an actual kingdom change, and the resync flag
// (set by the socket worker on hello_ack) clears the dedup once per connect so
// the current kingdom re-emits without needing a stage change. Throttled — an
// arrival is a once-per-area event, frame precision is unnecessary.
void tickArrivalPoll() {
    auto& st = smoap::ap::ApState::instance();
    if (st.arrival_resync.exchange(false, std::memory_order_relaxed)) {
        // Fresh client connection: forget the last emitted kingdom so the poll
        // below re-emits whatever overworld Mario is currently standing in.
        st.last_arrival_kingdom[0] = '\0';
    }
    static int s_tick = 0;
    if (++s_tick < 30) return;  // ~0.5s @ 60fps
    s_tick = 0;
    const char* stage = currentStageName();
    const char* kingdom = smoap::game::kingdomShortFromHomeStage(stage);
    if (kingdom) smoap::ap::reportArrival(stage, kingdom);
}

void installEntranceShuffleHook() {
    const ptr addr =
        hk::ro::lookupSymbol(smoap::sym::kGameDataFunctionGetCurrentStageName);
    if (addr == 0) {
        SMOAP_LOG_WARN("[entrance] getCurrentStageName lookup FAILED — current "
                       "stage will log as (unresolved)");
        s_getCurrentStageName = nullptr;
    } else {
        s_getCurrentStageName = reinterpret_cast<GetCurrentStageNameFn>(addr);
    }

    SMOAP_LOG_INFO("installing EntranceShuffleHook (LOGGER x3 + forward-remap "
                   "seam, apply=%d) -> tryChangeNextStage + "
                   "GameDataFile::changeNextStage + returnPrevStage",
                   kEntranceRemapApply ? 1 : 0);
    tryChangeNextStageHook.installAtSym<
        "_ZN16GameDataFunction18tryChangeNextStageE20GameDataHolderWriterPK15ChangeStageInfo">();
    fileChangeNextStageHook.installAtSym<
        "_ZN12GameDataFile15changeNextStageEPK15ChangeStageInfoi">();
    returnPrevStageHook.installAtSym<
        "_ZN12GameDataFile15returnPrevStageEv">();
}

}  // namespace smoap::hooks
